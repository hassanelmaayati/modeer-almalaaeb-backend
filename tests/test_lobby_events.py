import asyncio

import pytest

from models.membership import MembershipModel
from models.room import RoomModel
from services import lobby_events
from services.room_rules import count_slots_left
from tests.lib import future


def test_slot_count_uses_accepted_players_and_counts_host_once(factory, db):
    host, accepted, pending, declined = [factory.user() for _ in range(4)]
    room = factory.room(host, capacity=4)
    factory.member(host, room=room)
    factory.member(accepted, room=room)
    factory.member(pending, room=room, status='pending')
    factory.member(declined, room=room, status='declined')
    with db() as session:
        row = session.get(RoomModel, room['id'])
        assert count_slots_left(session, row) == 2
        row.capacity = 1
        assert count_slots_left(session, row) == 0


def test_new_public_event_has_only_safe_projection_and_current_slots(factory, db):
    host, member = factory.user(), factory.user()
    room = factory.room(host, district='muharraq', venue_details='Secret private court')
    factory.member(member, room=room)
    with db() as session:
        events = lobby_events.events_for_change(session, session.get(RoomModel, room['id']), None)
    assert len(events) == 1 and events[0][0] == 'muharraq'
    event = events[0][1].model_dump(mode='json')
    assert event['type'] == 'room_created'
    assert event['room']['id'] == room['id'] and event['room']['slots_left'] == 2
    assert set(event['room']) == {'id', 'title', 'sport_id', 'sport_name', 'district', 'public_area', 'starts_at', 'capacity', 'slots_left', 'difficulty', 'revision'}
    assert 'Secret private court' not in str(event)


@pytest.mark.parametrize('change', [
    {'visibility': 'private'}, {'visibility': 'group'}, {'status': 'cancelled'},
    {'status': 'started'}, {'status': 'completed'}, {'capacity': 1},
    {'starts_at': future(.1), 'ends_at': future(1)},
])
def test_never_visible_rooms_produce_no_public_events(factory, db, change):
    host = factory.user()
    if change.get('visibility') == 'group':
        change = {**change, 'group_id': factory.group(host)['id']}
    room = factory.room(host, **change)
    with db() as session:
        row = session.get(RoomModel, room['id'])
        assert lobby_events.events_for_change(session, row, None) == []
        assert lobby_events.events_for_change(session, row, lobby_events.lobby_state(session, row)) == []


@pytest.mark.parametrize('change, reason', [
    ({'status': 'cancelled'}, 'cancelled'), ({'status': 'started'}, 'started'),
    ({'visibility': 'private'}, 'not_public'), ({'capacity': 1}, 'full'),
    ({'starts_at': future(.1)}, 'past_cutoff'),
])
def test_visible_room_removal_has_correct_reason(factory, db, change, reason):
    room = factory.room(factory.user())
    with db() as session:
        row = session.get(RoomModel, room['id'])
        before = lobby_events.lobby_state(session, row)
        for key, value in change.items():
            setattr(row, key, value)
        session.commit()
        events = lobby_events.events_for_change(session, row, before)
    assert [(district, event.type) for district, event in events] == [('capital', 'room_removed')]
    assert events[0][1].room_id == room['id'] and events[0][1].reason == reason


def test_move_update_and_visibility_return_use_current_version(factory, db):
    room = factory.room(factory.user())
    with db() as session:
        row = session.get(RoomModel, room['id'])
        before = lobby_events.lobby_state(session, row)
        row.title, row.revision = 'Changed', 1
        session.commit()
        update = lobby_events.events_for_change(session, row, before)
        assert update[0][1].type == 'room_updated' and update[0][1].room.revision == 1
        assert update[0][1].room.title == 'Changed'
        before = lobby_events.lobby_state(session, row)
        row.district = 'southern'
        session.commit()
        moved = lobby_events.events_for_change(session, row, before)
        assert [(district, event.type) for district, event in moved] == [('capital', 'room_removed'), ('southern', 'room_created')]
        assert moved[0][1].reason == 'moved'
        row.visibility = 'private'
        session.commit()
        before = lobby_events.lobby_state(session, row)
        row.visibility, row.revision = 'public', 2
        session.commit()
        returned = lobby_events.events_for_change(session, row, before)
        assert returned[0][1].type == 'room_created' and returned[0][1].room.revision == 2


def test_full_room_reappears_after_accepted_member_leaves(factory, db):
    host, player = factory.user(), factory.user()
    room = factory.room(host, capacity=2)
    with db() as session:
        row = session.get(RoomModel, room['id'])
        before = lobby_events.lobby_state(session, row)
    member = factory.member(player, room=room)
    with db() as session:
        row = session.get(RoomModel, room['id'])
        full = lobby_events.events_for_change(session, row, before)
        assert full[0][1].reason == 'full'
        before = lobby_events.lobby_state(session, row)
        session.get(MembershipModel, member['id']).status = 'left'
        session.commit()
        returned = lobby_events.events_for_change(session, row, before)
        assert returned[0][1].type == 'room_created' and returned[0][1].room.slots_left == 1


def test_pending_membership_or_private_details_do_not_change_projection(factory, db):
    host, player = factory.user(), factory.user()
    room = factory.room(host)
    with db() as session:
        row = session.get(RoomModel, room['id'])
        before = lobby_events.lobby_state(session, row)
    factory.member(player, room=room, status='pending')
    with db() as session:
        row = session.get(RoomModel, room['id'])
        row.venue_details = 'Updated private address'
        session.commit()
        assert lobby_events.events_for_change(session, row, before) == []


def test_event_preparation_and_delivery_failures_are_best_effort(factory, db, monkeypatch):
    room = factory.room(factory.user())
    def fail_prepare(*args):
        raise RuntimeError('Cannot prepare lobby projection')
    with db() as session:
        row = session.get(RoomModel, room['id'])
        events = lobby_events.events_for_change(session, row, None)
        monkeypatch.setattr(lobby_events, 'events_for_change', fail_prepare)
        assert lobby_events.prepare_room_events(session, row) == []
    class BrokenHub:
        async def broadcast(self, district, event):
            raise RuntimeError('Socket transport unavailable')
    asyncio.run(lobby_events.send_events(events, BrokenHub()))
