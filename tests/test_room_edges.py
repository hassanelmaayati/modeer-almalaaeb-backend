"""Admission, slots, leaving and edit failures preserve room state atomically."""
import pytest

from models.membership import MembershipModel
from models.notification import NotificationModel
from models.room import RoomModel, make_point
from services.room_search import rooms_near
from tests.lib import api, future


@pytest.mark.parametrize('radius,expected', [(0, ['at-origin']), (500, ['at-origin', 'near']), (7000, ['at-origin', 'near', 'far'])])
def test_postgis_internal_proximity_search_filters_in_metres_and_orders_nearest_first(factory, db, radius, expected):
    host, sport = factory.user(), factory.sport()
    origin = (26.2235, 50.5876)
    for name, latitude in [('at-origin', origin[0]), ('near', origin[0] + .001), ('far', origin[0] + .05)]:
        factory.room(host, sport, title=name, venue_point=make_point(latitude, origin[1]), visibility='private')
    factory.room(host, sport, title='cancelled', status='cancelled', venue_point=make_point(*origin))
    factory.room(host, sport, title='started', status='started', venue_point=make_point(*origin))
    factory.room(host, sport, title='missing-pin')
    with db() as session:
        rows = rooms_near(session, *origin, radius)
        assert [row.title for row in rows] == expected
        assert session.query(RoomModel).count() == 6


@pytest.mark.parametrize('case,status', [('invite-other', 403), ('private-request', 404), ('full', 409), ('unknown-user', 404), ('closed', 409)])
def test_admission_rejections_create_neither_memberships_nor_notifications(client, factory, db, case, status):
    host, player, outsider = factory.user(), factory.user(), factory.user()
    room = factory.room(host, visibility='private' if case == 'private-request' else 'public',
                        capacity=1 if case == 'full' else 4, status='completed' if case == 'closed' else 'open')
    user = host if case == 'unknown-user' else player
    body = {'user_id': outsider['id']} if case == 'invite-other' else {'user_id': 99999} if case == 'unknown-user' else {}
    api(client, 'POST', f"/rooms/{room['id']}/members", user=user, body=body, expected=status)
    with db() as session:
        assert session.query(MembershipModel).count() == 0 and session.query(NotificationModel).count() == 0
        assert session.get(RoomModel, room['id']).revision == 0


@pytest.mark.parametrize('case,expected', [('pending', 409), ('completed', 409), ('started-time', 409), ('blank', 422), ('long', 422), ('clear', 200)])
def test_slot_state_and_string_boundaries_preserve_old_position_on_rejection(client, factory, db, case, expected):
    host, player = factory.user(), factory.user()
    room = factory.room(host, status='completed' if case == 'completed' else 'open',
                        starts_at=future(-1) if case == 'started-time' else future())
    row = factory.member(player, room=room, status='pending' if case == 'pending' else 'accepted',
                         position=None if case == 'pending' else 'existing-slot')
    position = ' ' if case == 'blank' else 'x' * 51 if case == 'long' else None if case == 'clear' else 'new-slot'
    api(client, 'PATCH', f"/rooms/{room['id']}/members/{player['id']}", user=player, body={'position': position}, expected=expected)
    with db() as session:
        stored = session.get(MembershipModel, row['id'])
        assert stored.position == (None if case in ('pending', 'clear') else 'existing-slot')
        if expected != 200:
            assert session.query(NotificationModel).count() == 0 and session.get(RoomModel, room['id']).revision == 0


@pytest.mark.parametrize('state,expected', [('pending', 204), ('accepted', 204), ('left', 204), ('declined', 409), ('removed', 409)])
def test_leave_room_is_idempotent_and_closed_memberships_stay_closed(client, factory, db, state, expected):
    host, player = factory.user(), factory.user()
    room = factory.room(host)
    row = factory.member(player, room=room, status=state)
    api(client, 'DELETE', f"/rooms/{room['id']}/members/me", user=player, expected=expected)
    with db() as session:
        assert session.get(MembershipModel, row['id']).status == ('left' if expected == 204 else state)
        expected_revision = 1 if state in ('pending', 'accepted') else 0
        assert session.get(RoomModel, room['id']).revision == expected_revision


def test_host_cannot_leave_and_unknown_room_members_remain_404(client, factory):
    host, player = factory.user(), factory.user()
    room = factory.room(host)
    api(client, 'DELETE', f"/rooms/{room['id']}/members/me", user=host, expected=409)
    api(client, 'DELETE', f"/rooms/{room['id']}/members/me", user=player, expected=404)
    api(client, 'PATCH', f"/rooms/{room['id']}/members/{player['id']}", user=host, body={'status': 'accepted'}, expected=404)


@pytest.mark.parametrize('change,expected', [({'visibility': 'group'}, 422), ({'sport_id': 99999}, 404)])
def test_room_edit_requires_valid_relations_and_group_visibility(client, factory, db, change, expected):
    host = factory.user()
    room = factory.room(host)
    api(client, 'PUT', f"/rooms/{room['id']}", user=host, body={'revision': 0, **change}, expected=expected)
    with db() as session:
        stored = session.get(RoomModel, room['id'])
        assert stored.revision == 0 and stored.visibility == 'public' and stored.sport_id == room['sport_id']


def test_room_partial_schedule_updates_compare_with_stored_times(client, factory, db):
    host = factory.user()
    room = factory.room(host)
    for change in ({'ends_at': future(23).isoformat()}, {'starts_at': future(26).isoformat()}):
        api(client, 'PUT', f"/rooms/{room['id']}", user=host, body={'revision': 0, **change}, expected=422)
    with db() as session:
        stored = session.get(RoomModel, room['id'])
        assert stored.revision == 0 and stored.starts_at == room['starts_at'] and stored.ends_at == room['ends_at']
