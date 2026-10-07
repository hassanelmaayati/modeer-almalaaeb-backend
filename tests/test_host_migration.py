"""Manual host transfer and automatic promotion of a long-absent host."""
import asyncio
from contextlib import suppress
from datetime import timedelta
from types import SimpleNamespace

import pytest

from models.base import utc_now
from models.membership import MembershipModel
from models.message import MessageModel
from models.notification import NotificationModel
from models.room import RoomModel
from services import host_presence, realtime
from services.host_presence import HOST_AWAY_GRACE, sweep
from tests.lib import api

LATE = HOST_AWAY_GRACE + timedelta(seconds=1)


def started_room(factory, admitted=('first', 'second'), **changes):
    host = factory.user()
    room = factory.room(host, status='started', **changes)
    base = utc_now() - timedelta(hours=1)
    players = {}
    for index, name in enumerate(admitted):
        players[name] = factory.user()
        factory.member(players[name], room=room, accepted_at=base + timedelta(minutes=index))
    return room, host, players


def run_sweep(db, online, now, *, boot_over=True, is_online=None):
    online = set(online)
    with db() as session:
        return sweep(session, online, is_online or (lambda user_id: user_id in online), now=now, boot_grace_over=boot_over)


def state(db, room):
    with db() as session:
        row = session.get(RoomModel, room['id'])
        return row.host_id, row.host_generation, row.revision, row.host_away_since


def test_away_clock_starts_after_the_boot_grace_and_clears_when_the_host_returns(factory, db):
    room, host, players = started_room(factory)
    now = utc_now()
    run_sweep(db, {players['first']['id']}, now, boot_over=False)
    assert state(db, room)[3] is None
    run_sweep(db, {players['first']['id']}, now)
    assert state(db, room)[3] == now
    run_sweep(db, {host['id']}, now + timedelta(hours=1))
    assert state(db, room)[3] is None


def test_a_long_absent_host_is_replaced_by_the_longest_admitted_connected_player(factory, db):
    room, host, players = started_room(factory)
    first, second = players['first'], players['second']
    with db() as session:
        before = session.get(RoomModel, room['id']).revision
    now = utc_now()
    run_sweep(db, {first['id'], second['id']}, now)
    assert run_sweep(db, {first['id'], second['id']}, now + HOST_AWAY_GRACE - timedelta(seconds=1)) == []
    events = run_sweep(db, {first['id'], second['id']}, now + LATE)
    host_id, generation, revision, away = state(db, room)
    assert (host_id, generation, revision, away) == (first['id'], 1, before + 1, None)
    changed = next(event for event in events if event['payload']['type'] == 'room.host_changed')
    assert changed['payload'] == {'type': 'room.host_changed', 'room_id': room['id'], 'host_id': first['id'], 'host_generation': 1}
    assert set(changed['user_ids']) == {host['id'], first['id'], second['id']}
    with db() as session:
        old = session.query(MembershipModel).filter_by(room_id=room['id'], user_id=host['id']).one()
        assert (old.status, old.accepted) == ('accepted', True) and old.accepted_at is not None
        notified = {row.user_id for row in session.query(NotificationModel).filter_by(kind='room.host_changed')}
        assert notified == {host['id'], first['id'], second['id']}
        notice = session.query(MessageModel).filter_by(room_id=room['id'], type='system').one()
        assert first['user_name'] in notice.body and 'was away' in notice.body


def test_the_next_player_is_chosen_when_the_first_is_offline_a_no_show_or_unknown(factory, db):
    room, host, players = started_room(factory, admitted=('first', 'absent', 'second'))
    with db() as session:
        session.query(MembershipModel).filter_by(user_id=players['absent']['id']).one().attendance = 'no_show'
        session.commit()
    now = utc_now()
    online = {players['absent']['id'], players['second']['id']}
    run_sweep(db, online, now)
    run_sweep(db, online, now + LATE)
    assert state(db, room)[0] == players['second']['id']


def test_nobody_is_promoted_while_no_eligible_player_is_online(factory, db):
    room, host, players = started_room(factory)
    now = utc_now()
    run_sweep(db, set(), now)
    assert run_sweep(db, set(), now + LATE) == []
    assert state(db, room)[0] == host['id'] and state(db, room)[3] == now
    run_sweep(db, {players['second']['id']}, now + LATE + timedelta(seconds=30))
    assert state(db, room)[0] == players['second']['id']


def test_admission_time_decides_not_row_order_and_unknown_times_come_last(factory, db):
    host = factory.user()
    room = factory.room(host, status='started')
    unknown, late, early = factory.user(), factory.user(), factory.user()
    factory.member(unknown, room=room)
    factory.member(late, room=room, accepted_at=utc_now() - timedelta(minutes=5))
    factory.member(early, room=room, accepted_at=utc_now() - timedelta(minutes=50))
    now = utc_now()
    everyone = {unknown['id'], late['id'], early['id']}
    run_sweep(db, everyone, now)
    run_sweep(db, everyone, now + LATE)
    assert state(db, room)[0] == early['id']


def test_pending_and_departed_players_are_never_promoted(factory, db):
    host = factory.user()
    room = factory.room(host, status='started')
    pending, left = factory.user(), factory.user()
    factory.member(pending, room=room, status='pending')
    factory.member(left, room=room, status='left')
    now = utc_now()
    run_sweep(db, {pending['id'], left['id']}, now)
    run_sweep(db, {pending['id'], left['id']}, now + LATE)
    assert state(db, room)[0] == host['id']


def test_a_host_who_reconnects_just_before_the_promotion_keeps_the_room(factory, db):
    room, host, players = started_room(factory)
    now = utc_now()
    run_sweep(db, {players['first']['id']}, now)
    # The snapshot said offline, but the host is back by the time the room is locked
    run_sweep(db, {players['first']['id']}, now + LATE, is_online=lambda user_id: True)
    host_id, generation, _, away = state(db, room)
    assert (host_id, generation, away) == (host['id'], 0, None)


def test_a_restart_does_not_reset_a_long_wait(factory, db):
    room, host, players = started_room(factory)
    now = utc_now()
    run_sweep(db, {players['first']['id']}, now)
    # After a restart nobody is connected yet: the saved clock stays, and nothing moves during the boot grace
    assert run_sweep(db, set(), now + LATE, boot_over=False) == []
    assert state(db, room)[0] == host['id'] and state(db, room)[3] == now
    run_sweep(db, {players['first']['id']}, now + LATE + timedelta(seconds=90))
    assert state(db, room)[0] == players['first']['id']


@pytest.mark.parametrize('status', ['open', 'completed', 'cancelled'])
def test_only_started_rooms_are_watched(factory, db, status):
    host = factory.user()
    room = factory.room(host, status=status)
    player = factory.user()
    factory.member(player, room=room)
    now = utc_now()
    run_sweep(db, {player['id']}, now)
    run_sweep(db, {player['id']}, now + LATE)
    assert state(db, room)[0] == host['id'] and state(db, room)[3] is None


def test_hub_reports_who_is_connected():
    hub = realtime.RealtimeHub()
    hub.connections = {object(): SimpleNamespace(user_id=1), object(): SimpleNamespace(user_id=1), object(): SimpleNamespace(user_id=2)}
    assert hub.online_user_ids() == {1, 2}


def test_the_background_loop_promotes_and_stops_cleanly(factory, db, configured_app, monkeypatch):
    room, host, players = started_room(factory, admitted=('first',))
    hub = realtime.realtime_hub
    hub.connections[object()] = SimpleNamespace(user_id=players['first']['id'])
    sent = []
    async def capture(events):
        sent.extend(events)
    monkeypatch.setattr(realtime, 'send_events', capture)
    monkeypatch.setattr(host_presence, 'BOOT_GRACE_SECONDS', 0)
    monkeypatch.setattr(host_presence, 'HOST_AWAY_GRACE', timedelta(0))
    async def run():
        task = asyncio.create_task(host_presence.host_presence_loop(interval=0.02, session_factory=db))
        await asyncio.sleep(0.5)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert state(db, room)[0] == players['first']['id']
    assert any(event['payload']['type'] == 'room.host_changed' for event in sent)


def transferable(factory, **changes):
    room, host, players = started_room(factory, **changes)
    return room, host, players


def transfer(client, room, user, new_host, expected=200):
    return api(client, 'POST', f"/rooms/{room['id']}/transfer-host", user=user, body={'user_id': new_host['id']}, expected=expected)


def test_the_host_can_hand_the_room_to_an_accepted_player(client, factory, db):
    room, host, players = transferable(factory)
    first, second = players['first'], players['second']
    before = api(client, 'GET', f"/rooms/{room['id']}")
    moved = transfer(client, room, host, first)
    assert moved['host_id'] == first['id'] and moved['host_generation'] == 1 and moved['revision'] == before['revision'] + 1
    assert moved['slots_left'] == before['slots_left'] and 'venue_notes' in moved
    # The old host is an ordinary accepted player now and can see the room as one
    assert [row['status'] for row in api(client, 'GET', f"/rooms/{room['id']}/members", user=host) if row['user_id'] == host['id']] == ['accepted']
    assert room['id'] in [item['id'] for item in api(client, 'GET', '/rooms/joined', user=host)['items']]
    assert room['id'] in [item['id'] for item in api(client, 'GET', '/rooms/mine', user=first)['items']]
    # Only the new host controls the room now; the old host's tab gets 403
    mark = lambda user: api(client, 'PATCH', f"/rooms/{room['id']}/members/{second['id']}", user=user,
                            body={'attendance': 'present'}, expected=200 if user is first else 403)
    mark(host), mark(first)
    transfer(client, room, host, second, expected=403)
    with db() as session:
        notified = {row.user_id for row in session.query(NotificationModel).filter_by(kind='room.host_changed')}
        assert notified == {first['id'], second['id']}  # the person who asked is not notified
        assert session.query(MessageModel).filter_by(room_id=room['id'], type='system').count() == 1
    transfer(client, room, first, host)  # and they can hand it back


@pytest.mark.parametrize('case', ['self', 'stranger', 'pending', 'left', 'no_show', 'missing'])
def test_the_new_host_must_be_an_accepted_player(client, factory, db, case):
    room, host, players = transferable(factory, admitted=('first',))
    target = {'self': host, 'stranger': factory.user(), 'pending': factory.user(), 'left': factory.user(),
              'no_show': players['first'], 'missing': {'id': 999999}}[case]
    if case in ('pending', 'left'):
        factory.member(target, room=room, status=case)
    if case == 'no_show':
        with db() as session:
            session.query(MembershipModel).filter_by(user_id=target['id']).one().attendance = 'no_show'
            session.commit()
    transfer(client, room, host, target, expected=409)
    assert state(db, room)[0] == host['id']


@pytest.mark.parametrize('status', ['completed', 'cancelled'])
def test_finished_rooms_cannot_change_host(client, factory, status):
    room, host, players = transferable(factory)
    with factory.db() as session:
        session.get(RoomModel, room['id']).status = status
        session.commit()
    transfer(client, room, host, players['first'], expected=409)


def test_transfer_is_hidden_from_outsiders_and_needs_the_host(client, factory):
    room, host, players = transferable(factory, visibility='private')
    outsider = factory.user()
    transfer(client, room, outsider, players['first'], expected=404)
    transfer(client, room, players['second'], players['first'], expected=403)
    api(client, 'POST', '/rooms/999999/transfer-host', user=host, body={'user_id': players['first']['id']}, expected=404)
    api(client, 'POST', f"/rooms/{room['id']}/transfer-host", body={'user_id': 1}, expected=401)


def test_a_room_can_change_host_while_open(client, factory):
    host, player = factory.user(), factory.user()
    room = factory.room(host)
    factory.member(player, room=room)
    assert transfer(client, room, host, player)['host_id'] == player['id']


def test_ratings_follow_the_new_roles_after_a_transfer(client, factory, db):
    room, host, players = transferable(factory, admitted=('first',))
    first = players['first']
    transfer(client, room, host, first)
    with db() as session:
        session.get(RoomModel, room['id']).status = 'completed'
        session.commit()
    # The old host is a player now: they can rate the new host, who cannot use the player endpoint
    api(client, 'POST', f"/rooms/{room['id']}/ratings", user=host, body={'user_id': first['id'], 'stars': 5}, expected=201)
    api(client, 'POST', f"/rooms/{room['id']}/ratings", user=first, body={'user_id': host['id'], 'stars': 4}, expected=409)
    # The new host rates the old host through attendance like any other player
    api(client, 'PATCH', f"/rooms/{room['id']}/members/{host['id']}", user=first, body={'attendance': 'present', 'rating': 4})
