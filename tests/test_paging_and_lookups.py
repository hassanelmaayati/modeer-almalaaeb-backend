"""Paging with X-Total-Count, group member counts, batch user lookup and query counts."""
import pytest
from sqlalchemy import event, text

from services.room_rules import count_slots_left, slots_left_map
from tests.lib import api, future


def get(client, path, user=None, **kwargs):
    return client.get('/api/v1' + path, headers=user['headers'] if user else {}, **kwargs)


def ids(response):
    return [item['id'] for item in response.json()]


def test_room_discovery_pages_in_start_order_with_a_total(client, factory):
    host = factory.user()
    rooms = [factory.room(host, starts_at=future(30 + number), ends_at=future(31 + number)) for number in range(5)]
    everything = get(client, '/rooms')
    assert ids(everything) == [room['id'] for room in rooms] and everything.headers['X-Total-Count'] == '5'
    second_page = get(client, '/rooms', params={'limit': 2, 'offset': 2})
    assert ids(second_page) == [room['id'] for room in rooms[2:4]] and second_page.headers['X-Total-Count'] == '5'
    assert get(client, '/rooms', params={'offset': 5}).json() == []
    for query in ({'limit': 0}, {'limit': 101}, {'offset': -1}, {'offset': 1_000_001}):
        assert get(client, '/rooms', params=query).status_code == 422


def test_the_total_header_is_readable_from_the_browser(client):
    response = client.get('/api/v1/rooms', headers={'Origin': 'http://localhost:5174'})
    assert response.headers['access-control-expose-headers'] == 'X-Total-Count'


def test_lists_report_totals(client, factory):
    user = factory.user()
    for _ in range(3):
        factory.group(user)
        factory.cup(user, status='registration')
    assert get(client, '/groups').headers['X-Total-Count'] == '3'
    assert get(client, '/cups').headers['X-Total-Count'] == '3'
    assert get(client, '/users').headers['X-Total-Count'] == '1'
    assert ids(get(client, '/groups', params={'limit': 2, 'offset': 1})) == [2, 3]


def test_groups_count_their_owner_and_accepted_members(client, factory):
    owner, member, pending, left = [factory.user() for _ in range(4)]
    group = factory.group(owner)
    other = factory.group(member)
    factory.member(member, group=group)
    factory.member(pending, group=group, status='pending')
    factory.member(left, group=group, status='left')
    cup = factory.cup(owner)
    factory.member(pending, group=group, cup=cup)  # cup roster rows are not group members
    counts = {item['id']: item['member_count'] for item in get(client, '/groups').json()}
    assert counts == {group['id']: 2, other['id']: 1}
    assert get(client, f"/groups/{group['id']}").json()['member_count'] == 2
    updated = api(client, 'PUT', f"/groups/{group['id']}", user=owner, body={'name': 'Renamed'})
    assert updated['member_count'] == 2
    created = api(client, 'POST', '/groups', user=owner, body={'name': 'Fresh', 'sports_id': group['sports_id']}, expected=201)
    assert created['member_count'] == 1


def test_my_groups_lists_owned_and_joined_groups_with_roles(client, factory):
    me, friend, stranger = factory.user(), factory.user(), factory.user()
    owned = factory.group(me)
    joined = factory.group(friend)
    invited = factory.group(friend)
    unrelated = factory.group(stranger)
    factory.member(me, group=joined)
    factory.member(me, group=invited, status='pending')
    mine = api(client, 'GET', '/groups/mine', user=me)
    assert {item['id']: (item['role'], item['member_count']) for item in mine} == {owned['id']: ('owner', 1), joined['id']: ('member', 2)}
    assert unrelated['id'] not in {item['id'] for item in mine}
    assert get(client, '/groups/mine', me).headers['X-Total-Count'] == '2'
    api(client, 'GET', '/groups/mine', expected=401)


def test_users_can_be_looked_up_in_a_batch_with_public_fields_only(client, factory):
    users = [factory.user() for _ in range(4)]
    wanted = [users[2]['id'], users[0]['id'], 999999, users[2]['id']]
    response = get(client, '/users', params={'ids': ','.join(map(str, wanted))})
    assert ids(response) == sorted({users[0]['id'], users[2]['id']}) and response.headers['X-Total-Count'] == '2'
    assert {'email', 'password', 'google_subject', 'token_version'}.isdisjoint(response.json()[0])
    # Paging is ignored for a batch lookup
    assert len(get(client, '/users', params={'ids': ','.join(str(u['id']) for u in users), 'limit': 1}).json()) == 4


@pytest.mark.parametrize('value', ['abc', '', '1,,2', '0', '-1', '1,x', ','.join(str(n) for n in range(1, 102)), str(10 ** 12)])
def test_invalid_user_id_lists_are_rejected(client, value):
    assert get(client, '/users', params={'ids': value}).status_code == 422


@pytest.fixture
def sql_counter(db):
    engine = db.kw['bind']
    counter = {'n': 0}
    def count(*args, **kwargs):
        counter['n'] += 1
    event.listen(engine, 'before_cursor_execute', count)
    yield counter
    event.remove(engine, 'before_cursor_execute', count)


def fill(factory, rooms):
    host, player = factory.user(), factory.user()
    for number in range(rooms):
        room = factory.room(host, starts_at=future(30 + number), ends_at=future(31 + number))
        factory.member(player, room=room)
        factory.message(host, room=room)
    return host, player


def statements(client, sql_counter, path, user):
    get(client, path, user)  # the first request on a fresh engine also runs the driver's setup queries
    sql_counter['n'] = 0
    assert get(client, path, user).status_code == 200
    return sql_counter['n']


@pytest.mark.parametrize('path,role,limit', [('/rooms', None, 3), ('/rooms/mine?limit=50', 'host', 5),
                                             ('/rooms/joined?limit=50', 'player', 6), ('/messages/conversations', 'player', 8)])
def test_list_queries_do_not_grow_with_the_number_of_rows(client, factory, sql_counter, path, role, limit):
    def run():
        return statements(client, sql_counter, path, None if role is None else dict(zip(('host', 'player'), people))[role])
    people = fill(factory, 3)
    few = run()
    people = fill(factory, 12)
    many = run()
    assert many == few and many <= limit, (path, few, many)


def test_the_one_query_slot_count_matches_the_single_room_rule(factory, db):
    host, first, second = factory.user(), factory.user(), factory.user()
    full = factory.room(host, capacity=2)
    factory.member(first, room=full)
    roomy = factory.room(host, capacity=5)
    factory.member(first, room=roomy); factory.member(second, room=roomy)
    factory.member(host, room=roomy)  # a host with a membership row still counts once
    pending = factory.room(host, capacity=3)
    factory.member(first, room=pending, status='pending')
    empty = factory.room(host, capacity=1)
    from models.room import RoomModel
    with db() as session:
        rooms = session.query(RoomModel).order_by(RoomModel.id).all()
        expected = {room.id: count_slots_left(session, room) for room in rooms}
        assert slots_left_map(session, rooms) == expected == {full['id']: 0, roomy['id']: 2, pending['id']: 2, empty['id']: 0}
        assert slots_left_map(session, []) == {}


def test_new_lookup_indexes_exist(db):
    with db() as session:
        found = {row[0] for row in session.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))}
    assert {'ix_memberships_room_id_status', 'ix_memberships_group_id_status', 'ix_memberships_cup_id_status',
            'ix_memberships_other_user_id', 'ix_cups_status_created_at', 'ix_cups_organizer_user_id', 'ix_rooms_group_id'} <= found
