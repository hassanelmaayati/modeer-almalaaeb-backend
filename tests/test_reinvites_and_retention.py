"""Reopening declined/left invitations, and expiring old notifications."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest

from models.base import utc_now
from models.membership import MembershipModel
from models.notification import NotificationModel
from services import notifications
from services.notifications import purge_old_notifications, retention_loop
from tests.lib import api


def rows(db, **filters):
    with db() as session:
        return session.query(MembershipModel).filter_by(**filters).all()


def request_friend(client, user, other, expected=201):
    return api(client, 'POST', '/friends', user=user, body={'other_user_id': other['id']}, expected=expected)


def respond(client, user, other, status):
    return api(client, 'PATCH', f"/friends/{other['id']}", user=user, body={'status': status})


@pytest.mark.parametrize('ending', ['declined', 'unfriended'])
@pytest.mark.parametrize('same_side', [True, False])
def test_a_declined_or_ended_friendship_can_start_again(client, factory, db, ending, same_side):
    first, second = factory.user(), factory.user()
    row = request_friend(client, first, second)
    if ending == 'declined':
        respond(client, second, first, 'declined')
    else:
        respond(client, second, first, 'accepted')
        respond(client, first, second, 'left')
    requester, target = (first, second) if same_side else (second, first)
    again = request_friend(client, requester, target)
    assert again['id'] == row['id'] and (again['status'], again['requested'], again['accepted']) == ('pending', True, False)
    assert again['user_id'] == requester['id'] and again['other_user_id'] == target['id']
    assert len(rows(db, other_user_id=target['id'])) + len(rows(db, other_user_id=requester['id'])) == 1
    # The new target answers and the pair can chat again
    assert respond(client, target, requester, 'accepted')['status'] == 'accepted'
    api(client, 'POST', '/messages', user=first, body={'recipient_id': second['id'], 'body': 'Hello again', 'client_request_id': str(uuid4())}, expected=201)
    with db() as session:
        assert session.query(NotificationModel).filter_by(user_id=target['id'], kind='friend.request').count() >= 1


def test_open_friendships_and_blocks_are_not_reopened(client, factory, db):
    first, second = factory.user(), factory.user()
    request_friend(client, first, second)
    request_friend(client, first, second, expected=409)      # pending
    request_friend(client, second, first, expected=409)
    respond(client, second, first, 'accepted')
    request_friend(client, first, second, expected=409)      # accepted
    respond(client, first, second, 'left')
    for flags in ({'user_blocked_other': 'true'}, {'other_blocked_user': 'yes'}):
        with db() as session:
            row = session.query(MembershipModel).filter_by(user_id=first['id']).one()
            row.user_blocked_other = row.other_blocked_user = None
            for key, value in flags.items():
                setattr(row, key, value)
            session.commit()
        for requester, target in ((first, second), (second, first)):
            assert request_friend(client, requester, target, expected=409)['detail'] == 'Friendship already exists'


def test_flipping_the_pair_keeps_each_sides_block_flag_with_that_side(client, factory, db):
    first, second = factory.user(), factory.user()
    request_friend(client, first, second)
    respond(client, second, first, 'declined')
    with db() as session:
        row = session.query(MembershipModel).filter_by(user_id=first['id']).one()
        row.user_blocked_other, row.other_blocked_user = 'false', 'no'   # not blocking, but distinguishable
        session.commit()
    request_friend(client, second, first)
    with db() as session:
        row = session.query(MembershipModel).filter_by(user_id=second['id']).one()
        assert (row.other_user_id, row.user_blocked_other, row.other_blocked_user) == (first['id'], 'no', 'false')


def test_simultaneous_re_requests_from_both_sides_reopen_once(client, factory, db):
    first, second = factory.user(), factory.user()
    request_friend(client, first, second)
    respond(client, second, first, 'declined')
    barrier = Barrier(2)
    def send(pair):
        barrier.wait(timeout=5)
        return client.post('/api/v1/friends', headers=pair[0]['headers'], json={'other_user_id': pair[1]['id']}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(send, [(first, second), (second, first)]))
    assert sorted(statuses) == [201, 409]
    with db() as session:
        assert session.query(MembershipModel).filter(MembershipModel.other_user_id.is_not(None)).count() == 1


@pytest.mark.parametrize('ending', ['declined', 'left', 'removed'])
def test_a_group_can_invite_someone_who_declined_left_or_was_removed(client, factory, db, ending):
    owner, player = factory.user(), factory.user()
    group = factory.group(owner)
    invite = lambda expected=201: api(client, 'POST', f"/groups/{group['id']}/members", user=owner, body={'user_id': player['id']}, expected=expected)
    first = invite()
    invite(409)
    patch = lambda user, status: api(client, 'PATCH', f"/groups/{group['id']}/members/{player['id']}", user=user, body={'status': status})
    if ending == 'declined':
        patch(player, 'declined')
    elif ending == 'left':
        patch(player, 'accepted'); patch(player, 'left')
    else:
        patch(player, 'accepted'); patch(owner, 'removed')
    again = invite()
    assert again['id'] == first['id'] and (again['status'], again['requested'], again['accepted']) == ('pending', False, False)
    invite(409)
    patch(player, 'accepted')
    invite(409)
    assert api(client, 'GET', f"/groups/{group['id']}").get('member_count') == 2
    api(client, 'POST', f"/groups/{group['id']}/members", user=owner, body={'user_id': owner['id']}, expected=409)
    assert len(rows(db, group_id=group['id'], user_id=player['id'])) == 1


def roster_setup(factory):
    organizer, captain, player = factory.user(), factory.user(), factory.user()
    sport = factory.sport('Football')
    group = factory.group(captain, sport)
    factory.member(player, group=group)
    from tests.lib import future
    cup = factory.cup(organizer, sport, status='registration', registration_closes_at=future().replace(tzinfo=None),
        entries=[{'group_id': group['id'], 'group_name': group['name'], 'owner_user_id': captain['id'],
                  'status': 'accepted', 'entered_at': future().isoformat()}])
    return cup, group, captain, player


@pytest.mark.parametrize('ending', ['declined', 'left', 'removed'])
def test_a_cup_roster_can_invite_again_after_decline_leave_or_removal(client, factory, db, ending):
    cup, group, captain, player = roster_setup(factory)
    body = {'user_id': player['id'], 'group_id': group['id']}
    path = f"/cups/{cup['id']}/roster"
    first = api(client, 'POST', path, user=captain, body=body, expected=201)
    api(client, 'POST', path, user=captain, body=body, expected=409)
    if ending == 'removed':
        api(client, 'PATCH', f"{path}/{player['id']}", user=captain, body={'status': 'removed'})
    elif ending == 'declined':
        api(client, 'PATCH', f"{path}/{player['id']}", user=player, body={'status': 'declined'})
    else:
        api(client, 'PATCH', f"{path}/{player['id']}", user=player, body={'status': 'accepted'})
        api(client, 'PATCH', f"{path}/{player['id']}", user=player, body={'status': 'left'})
    again = api(client, 'POST', path, user=captain, body=body, expected=201)
    assert again['id'] == first['id'] and (again['status'], again['accepted']) == ('pending', False)
    api(client, 'POST', path, user=captain, body=body, expected=409)
    assert len(rows(db, cup_id=cup['id'], user_id=player['id'])) == 1


def test_room_memberships_stay_terminal(client, factory):
    host, player = factory.user(), factory.user()
    room = factory.room(host)
    factory.member(player, room=room, status='left', accepted=False)
    api(client, 'POST', f"/rooms/{room['id']}/members", user=player, body={}, expected=409)
    api(client, 'POST', f"/rooms/{room['id']}/members", user=host, body={'user_id': player['id']}, expected=409)


def make_notice(db, user, days, read, kind='message.room'):
    with db() as session:
        row = NotificationModel(user_id=user['id'], kind=kind, target={'type': 'room', 'id': 1}, text=f'{days} days',
                                created_at=utc_now() - timedelta(days=days), read_at=utc_now() if read else None)
        session.add(row)
        session.commit()
        return row.id


def surviving(db):
    with db() as session:
        return {row.text for row in session.query(NotificationModel)}


def test_old_notifications_expire_read_after_30_days_and_everything_after_90(factory, db):
    user = factory.user()
    cases = [(31, True), (29, True), (31, False), (89, False), (91, False), (91, True), (200, True)]
    for days, read in cases:
        make_notice(db, user, days, read)
    with db() as session:
        assert purge_old_notifications(session) == 4
    assert surviving(db) == {'29 days', '31 days', '89 days'}
    with db() as session:
        assert purge_old_notifications(session) == 0
    assert len(surviving(db)) == 3
    # The surviving 31-day notice is the unread one
    with db() as session:
        assert session.query(NotificationModel).filter_by(text='31 days').one().read_at is None


def test_purging_works_in_small_batches(factory, db):
    user = factory.user()
    for _ in range(7):
        make_notice(db, user, 100, False)
    make_notice(db, user, 1, False)
    with db() as session:
        assert purge_old_notifications(session, batch=3) == 7
    assert surviving(db) == {'1 days'}


def test_chat_messages_still_create_notifications(client, factory, db):
    host, member = factory.user(), factory.user()
    room = factory.room(host)
    factory.member(member, room=room)
    api(client, 'POST', '/messages', user=host, body={'room_id': room['id'], 'body': 'hello', 'client_request_id': str(uuid4())}, expected=201)
    with db() as session:
        notice = session.query(NotificationModel).filter_by(user_id=member['id'], kind='message.room').one()
        assert notice.read_at is None


def test_the_retention_loop_purges_and_stops_cleanly(factory, db):
    user = factory.user()
    make_notice(db, user, 120, False)
    keep = make_notice(db, user, 1, False)
    async def run():
        task = asyncio.create_task(retention_loop(interval=0.05, first_delay=0, session_factory=db))
        await asyncio.sleep(0.4)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    asyncio.run(run())
    with db() as session:
        assert [row.id for row in session.query(NotificationModel)] == [keep]
