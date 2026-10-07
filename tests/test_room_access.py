"""Hidden rooms, group-only rooms, open admission and slot validation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest

from models.membership import MembershipModel
from models.notification import NotificationModel
from tests.lib import api, future


def status_and_detail(client, method, path, user=None, body=None):
    response = client.request(method, '/api/v1' + path, headers=user['headers'] if user else {}, json=body)
    detail = response.json().get('detail') if response.headers.get('content-type', '').startswith('application/json') else None
    return response.status_code, detail


def hidden_routes(room_id, other_id):
    chat = {'room_id': room_id, 'body': 'hi', 'client_request_id': str(uuid4())}
    return [
        ('GET', f'/rooms/{room_id}', None), ('GET', f'/rooms/{room_id}/members', None),
        ('POST', f'/rooms/{room_id}/members', {}), ('DELETE', f'/rooms/{room_id}/members/me', None),
        ('PATCH', f'/rooms/{room_id}/members/{other_id}', {'status': 'accepted'}),
        ('PUT', f'/rooms/{room_id}', {'revision': 0, 'title': 'Hijack'}),
        ('POST', f'/rooms/{room_id}/cancel', {'reason': 'Hijack'}),
        ('GET', f'/messages?room_id={room_id}', None), ('POST', '/messages', chat),
        ('POST', f'/rooms/{room_id}/ratings', {'user_id': other_id, 'stars': 3}),
        ('GET', f'/rooms/{room_id}/ratings/mine', None),
    ]


@pytest.mark.parametrize('kind', ['private', 'group'])
@pytest.mark.parametrize('state', ['open', 'cancelled'])
def test_hidden_rooms_answer_exactly_like_missing_rooms(client, factory, kind, state):
    host, outsider = factory.user(), factory.user()
    group = factory.group(host)
    room = factory.room(host, visibility=kind, status=state, group_id=group['id'] if kind == 'group' else None)
    missing = hidden_routes(999999, host['id'])
    hidden = hidden_routes(room['id'], host['id'])
    for (method, path, body), (m_method, m_path, m_body) in zip(hidden, missing):
        for viewer in (outsider, None):
            if viewer is None and method in ('DELETE', 'PATCH', 'PUT', 'POST'):
                continue
            expected = status_and_detail(client, m_method, m_path, viewer, m_body)
            assert expected == (404, 'Room not found') or expected[0] == 401
            assert status_and_detail(client, method, path, viewer, body) == expected, (method, path)


def test_public_rooms_still_answer_403_to_outsiders_who_can_see_them(client, factory):
    host, outsider = factory.user(), factory.user()
    room = factory.room(host)
    assert status_and_detail(client, 'PUT', f"/rooms/{room['id']}", outsider, {'revision': 0, 'title': 'Hijack'})[0] == 403
    assert status_and_detail(client, 'POST', f"/rooms/{room['id']}/cancel", outsider, {'reason': 'x'})[0] == 403
    assert status_and_detail(client, 'GET', f"/messages?room_id={room['id']}", outsider)[0] == 403
    assert status_and_detail(client, 'DELETE', f"/rooms/{room['id']}/members/me", outsider) == (404, 'Room member not found')


def test_invited_users_can_see_a_private_room_but_not_its_chat(client, factory):
    host, guest = factory.user(), factory.user()
    room = factory.room(host, visibility='private')
    api(client, 'POST', f"/rooms/{room['id']}/members", user=host, body={'user_id': guest['id']}, expected=201)
    assert 'venue_notes' not in api(client, 'GET', f"/rooms/{room['id']}", user=guest)
    assert status_and_detail(client, 'GET', f"/messages?room_id={room['id']}", guest)[0] == 403


def test_a_stale_token_is_a_guest_on_public_rooms_and_nothing_on_hidden_ones(client, factory):
    host = factory.user()
    public, private = factory.room(host), factory.room(host, visibility='private')
    stale = {'Authorization': 'Bearer not-a-real-token'}
    assert client.get(f"/api/v1/rooms/{public['id']}", headers=stale).status_code == 200
    assert client.get(f"/api/v1/rooms/{private['id']}", headers=stale).status_code == 404
    assert client.get('/api/v1/rooms', headers=stale).status_code == 200


def group_setup(factory):
    owner, member, invited, ex_member, outsider = [factory.user() for _ in range(5)]
    group = factory.group(owner)
    factory.member(member, group=group)
    factory.member(invited, group=group, status='pending')
    factory.member(ex_member, group=group, status='left')
    room = factory.room(owner, visibility='group', group_id=group['id'], venue_notes='Secret court')
    return owner, member, invited, ex_member, outsider, group, room


def test_group_members_can_see_list_and_join_group_only_rooms(client, factory):
    owner, member, invited, ex_member, outsider, group, room = group_setup(factory)
    for user in (owner, member):
        shown = api(client, 'GET', f"/rooms/{room['id']}", user=user)
        assert shown['id'] == room['id']
    # Group members get the public view; the venue stays for admitted players
    assert 'venue_notes' not in api(client, 'GET', f"/rooms/{room['id']}", user=member)
    assert 'venue_notes' in api(client, 'GET', f"/rooms/{room['id']}", user=owner)
    listed = lambda user, query='': [item['id'] for item in api(client, 'GET', '/rooms' + query, user=user)]
    assert room['id'] in listed(member) and room['id'] in listed(owner)
    assert room['id'] in listed(member, f"?group_id={group['id']}")
    for user in (invited, ex_member, outsider, None):
        assert room['id'] not in listed(user) and room['id'] not in listed(user, f"?group_id={group['id']}")
        assert status_and_detail(client, 'GET', f"/rooms/{room['id']}", user) == (404, 'Room not found')
        assert status_and_detail(client, 'POST', f"/rooms/{room['id']}/members", user, {})[0] in (404, 401)
    joined = api(client, 'POST', f"/rooms/{room['id']}/members", user=member, body={}, expected=201)
    assert joined['status'] == 'pending' and joined['requested'] is True


def test_group_filter_shows_non_members_only_the_groups_public_rooms(client, factory):
    owner, member, invited, ex_member, outsider, group, room = group_setup(factory)
    public = factory.room(owner, group_id=group['id'])
    ids = [item['id'] for item in api(client, 'GET', f"/rooms?group_id={group['id']}", user=outsider)]
    assert ids == [public['id']]
    assert room['id'] in [item['id'] for item in api(client, 'GET', f"/rooms?group_id={group['id']}", user=member)]


def test_open_rooms_accept_a_players_own_request_at_once(client, factory, db):
    host, player, invitee = factory.user(), factory.user(), factory.user()
    room = factory.room(host, admission_policy='open', capacity=3)
    row = api(client, 'POST', f"/rooms/{room['id']}/members", user=player, body={}, expected=201)
    assert (row['status'], row['accepted'], row['requested']) == ('accepted', True, True)
    shown = api(client, 'GET', f"/rooms/{room['id']}", user=host)
    assert shown['slots_left'] == 1 and shown['revision'] == 1
    assert 'venue_notes' in api(client, 'GET', f"/rooms/{room['id']}", user=player)
    with db() as session:
        assert session.query(NotificationModel).filter_by(user_id=host['id'], kind='room.membership').count() == 1
    # Invitations still wait for the invitee, even in an open room
    invited = api(client, 'POST', f"/rooms/{room['id']}/members", user=host, body={'user_id': invitee['id']}, expected=201)
    assert invited['status'] == 'pending' and invited['requested'] is False


def test_approval_rooms_still_hold_requests_for_the_host(client, factory):
    host, player = factory.user(), factory.user()
    room = factory.room(host)
    assert api(client, 'POST', f"/rooms/{room['id']}/members", user=player, body={}, expected=201)['status'] == 'pending'


def test_open_rooms_still_respect_capacity_and_the_cutoff(client, factory):
    host, first, second, third = [factory.user() for _ in range(4)]
    full = factory.room(host, admission_policy='open', capacity=2)
    api(client, 'POST', f"/rooms/{full['id']}/members", user=first, body={}, expected=201)
    assert status_and_detail(client, 'POST', f"/rooms/{full['id']}/members", second, {}) == (409, 'The room is full')
    soon = factory.room(host, admission_policy='open', starts_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                        ends_at=datetime.now(timezone.utc) + timedelta(hours=1))
    assert status_and_detail(client, 'POST', f"/rooms/{soon['id']}/members", third, {}) == (409, 'Admission is closed')


def test_group_only_open_rooms_accept_group_members_at_once(client, factory):
    owner, member, invited, ex_member, outsider, group, _ = group_setup(factory)
    room = factory.room(owner, visibility='group', group_id=group['id'], admission_policy='open')
    assert api(client, 'POST', f"/rooms/{room['id']}/members", user=member, body={}, expected=201)['status'] == 'accepted'
    assert status_and_detail(client, 'POST', f"/rooms/{room['id']}/members", outsider, {})[0] == 404


def test_two_players_racing_for_the_last_open_place_get_one_seat(client, factory, db):
    host, first, second = [factory.user() for _ in range(3)]
    room = factory.room(host, admission_policy='open', capacity=2)
    barrier = Barrier(2)
    def join(user):
        barrier.wait(timeout=5)
        return client.post(f"/api/v1/rooms/{room['id']}/members", headers=user['headers'], json={}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(join, [first, second]))
    assert sorted(statuses) == [201, 409]
    with db() as session:
        assert session.query(MembershipModel).filter_by(room_id=room['id'], status='accepted').count() == 1


def claim(client, room, member, position, expected=200):
    return api(client, 'PATCH', f"/rooms/{room['id']}/members/{member['id']}", user=member, body={'position': position}, expected=expected)


def accepted_room(factory, players=2, **changes):
    host = factory.user()
    room = factory.room(host, **changes)
    members = [factory.user() for _ in range(players)]
    for member in members:
        factory.member(member, room=room)
    return room, host, members


def test_claimed_positions_must_exist_and_be_free(client, factory):
    room, host, (first, second) = accepted_room(factory, slot_layout={'slots': ['GK', 'D1']})
    assert claim(client, room, first, 'GK')['position'] == 'GK'
    assert claim(client, room, first, ' D1 ')['position'] == 'D1'
    claim(client, room, second, 'banana', expected=422)
    claim(client, room, second, '1', expected=422)
    claim(client, room, second, '', expected=422)
    claim(client, room, second, 'D1', expected=409)
    assert claim(client, room, first, None)['position'] is None
    assert claim(client, room, second, 'D1')['position'] == 'D1'


def test_rooms_without_a_layout_offer_numbered_places(client, factory):
    room, host, (first, second) = accepted_room(factory, capacity=3)
    assert claim(client, room, first, '3')['position'] == '3'
    claim(client, room, second, '4', expected=422)
    claim(client, room, second, '0', expected=422)
    claim(client, room, second, '3', expected=409)


def test_team_layouts_offer_every_team_slot(client, factory):
    layout = {'teams': [{'name': 'A', 'slots': ['A1']}, {'name': 'B', 'slots': ['B1']}]}
    room, host, (first, second) = accepted_room(factory, slot_layout=layout)
    assert claim(client, room, first, 'B1')['position'] == 'B1'
    claim(client, room, second, 'C1', expected=422)


def test_editing_the_layout_releases_places_that_no_longer_exist(client, factory):
    room, host, (first, second) = accepted_room(factory, slot_layout={'slots': ['GK', 'D1', 'D2']}, capacity=6)
    claim(client, room, first, 'GK'); claim(client, room, second, 'D2')
    revision = api(client, 'GET', f"/rooms/{room['id']}")['revision']
    edited = api(client, 'PUT', f"/rooms/{room['id']}", user=host, body={'revision': revision, 'slot_layout': {'slots': ['GK', 'D1']}})
    rows = {row['user_id']: row['position'] for row in api(client, 'GET', f"/rooms/{room['id']}/members", user=host)}
    assert rows == {first['id']: 'GK', second['id']: None} and edited['revision'] == revision + 1
