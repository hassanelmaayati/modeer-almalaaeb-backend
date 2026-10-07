"""Host ratings: one final rating per accepted, present player, after the room completed."""
import pytest

from models.membership import MembershipModel
from tests.lib import api


def setup_room(factory, room_status='completed', **member_changes):
    host, player = factory.user(), factory.user()
    room = factory.room(host, status=room_status)
    factory.member(player, room=room, **member_changes)
    return room, host, player


def patch(client, room, host, player, body, expected=200):
    return api(client, 'PATCH', f"/rooms/{room['id']}/members/{player['id']}", user=host, body=body, expected=expected)


def stored(db, player):
    with db() as session:
        row = session.query(MembershipModel).filter_by(user_id=player['id']).one()
        return row.rating


@pytest.mark.parametrize('status', ['open', 'started', 'cancelled'])
def test_host_ratings_wait_for_a_completed_room(client, factory, db, status):
    room, host, player = setup_room(factory, status, attendance='present')
    patch(client, room, host, player, {'rating': 5}, expected=409)
    assert stored(db, player) is None


@pytest.mark.parametrize('member_status', ['pending', 'left', 'removed', 'declined'])
def test_only_accepted_players_can_be_rated(client, factory, db, member_status):
    room, host, player = setup_room(factory, status=member_status, attendance='present')
    patch(client, room, host, player, {'rating': 5}, expected=409)
    assert stored(db, player) is None


@pytest.mark.parametrize('attendance', [None, 'unknown', 'excused', 'no_show'])
def test_only_players_marked_present_can_be_rated(client, factory, db, attendance):
    room, host, player = setup_room(factory, attendance=attendance)
    patch(client, room, host, player, {'rating': 5}, expected=409)
    assert stored(db, player) is None


def test_a_present_accepted_player_is_rated_once_and_it_is_final(client, factory, db):
    room, host, player = setup_room(factory, attendance='present')
    assert patch(client, room, host, player, {'rating': 4})['rating'] == 4
    patch(client, room, host, player, {'rating': 1}, expected=409)
    patch(client, room, host, player, {'rating': 4}, expected=409)
    assert stored(db, player) == 4
    # Other fields can still be updated without touching the rating
    patch(client, room, host, player, {'attendance': 'present'})
    assert stored(db, player) == 4


def test_attendance_and_rating_can_arrive_together(client, factory, db):
    room, host, player = setup_room(factory)
    assert patch(client, room, host, player, {'attendance': 'present', 'rating': 5})['rating'] == 5
    assert stored(db, player) == 5


def test_only_the_host_rates_and_never_themselves(client, factory, db):
    room, host, player = setup_room(factory, attendance='present')
    patch(client, room, player, player, {'rating': 5}, expected=403)
    patch(client, room, factory.user(), player, {'rating': 5}, expected=403)
    assert stored(db, player) is None
