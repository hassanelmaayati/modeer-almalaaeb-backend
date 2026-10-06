from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy.exc import IntegrityError

from models.membership import MembershipModel
from models.notification import NotificationModel
from models.player_rating import PlayerRatingModel
from tests.lib import api


def rate(client, room, rater, ratee, stars=4, expected=201):
    return api(client, 'POST', f"/rooms/{room['id']}/ratings", user=rater,
               body={'user_id': ratee['id'], 'stars': stars}, expected=expected)


def finished_room(factory, players=2, **changes):
    """A completed public room: its host plus accepted members, with no attendance recorded yet."""
    host = factory.user()
    room = factory.room(host, **{'status': 'completed', **changes})
    members = [factory.user() for _ in range(players)]
    for member in members:
        factory.member(member, room=room)
    return room, host, members


def stored(db):
    with db() as session:
        return session.query(PlayerRatingModel).count()


def test_player_rates_another_player_and_the_host_and_sees_only_their_own(client, factory, db):
    room, host, (first, second) = finished_room(factory)
    assert rate(client, room, first, second, 5) == {'user_id': second['id'], 'stars': 5}
    rate(client, room, first, host, 3)
    rate(client, room, second, first, 1)
    assert api(client, 'GET', f"/rooms/{room['id']}/ratings/mine", user=first) == [
        {'user_id': second['id'], 'stars': 5}, {'user_id': host['id'], 'stars': 3}]
    assert api(client, 'GET', f"/rooms/{room['id']}/ratings/mine", user=second) == [{'user_id': first['id'], 'stars': 1}]
    assert api(client, 'GET', f"/rooms/{room['id']}/ratings/mine", user=host) == []
    with db() as session:
        row = session.query(PlayerRatingModel).filter_by(rater_id=first['id'], ratee_id=second['id']).one()
        assert (row.room_id, row.stars) == (room['id'], 5)


@pytest.mark.parametrize('status', ['open', 'started', 'cancelled'])
def test_only_a_completed_room_can_be_rated(client, factory, db, status):
    room, host, (first, second) = finished_room(factory, status=status)
    rejected = rate(client, room, first, second, expected=409)
    assert 'completed' in rejected['detail'] and stored(db) == 0


def test_the_host_cannot_rate_through_this_endpoint(client, factory, db):
    room, host, (player, _) = finished_room(factory)
    rejected = rate(client, room, host, player, expected=409)
    assert 'attendance' in rejected['detail']
    rate(client, room, host, host, expected=409)
    assert stored(db) == 0


def test_players_cannot_rate_themselves(client, factory, db):
    room, host, (player, _) = finished_room(factory)
    rate(client, room, player, player, expected=400)
    assert stored(db) == 0
    with db() as session, pytest.raises(IntegrityError):
        session.add(PlayerRatingModel(rater_id=player['id'], ratee_id=player['id'], room_id=room['id'], stars=3))
        session.commit()


def test_ratings_are_final_per_rater_ratee_and_room(client, factory, db):
    room, host, (first, second) = finished_room(factory)
    other_room = factory.room(host, status='completed')
    factory.member(first, room=other_room)
    factory.member(second, room=other_room)
    rate(client, room, first, second, 5)
    again = rate(client, room, first, second, 1, expected=409)
    assert 'already rated' in again['detail']
    rate(client, room, first, second, 5, expected=409)
    # A different ratee, the reverse direction and another room are separate ratings
    rate(client, room, first, host, 2)
    rate(client, room, second, first, 2)
    rate(client, other_room, first, second, 1)
    with db() as session:
        assert session.query(PlayerRatingModel).filter_by(rater_id=first['id'], ratee_id=second['id'], room_id=room['id']).one().stars == 5
        assert session.query(PlayerRatingModel).count() == 4
    # There is no way to change or remove a rating
    for method in ('PUT', 'PATCH', 'DELETE'):
        assert client.request(method, f"/api/v1/rooms/{room['id']}/ratings", headers=first['headers'],
                              json={'user_id': second['id'], 'stars': 1}).status_code == 405


def test_simultaneous_duplicate_requests_store_one_rating(client, factory, db):
    room, host, (first, second) = finished_room(factory)
    barrier = Barrier(2)
    def send(_):
        barrier.wait(timeout=5)
        return client.post(f"/api/v1/rooms/{room['id']}/ratings", headers=first['headers'],
                           json={'user_id': second['id'], 'stars': 4}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(send, range(2)))
    assert sorted(statuses) == [201, 409] and stored(db) == 1


@pytest.mark.parametrize('stars', [0, 6, -1, 4.5, '4', True, None, 4.0])
def test_stars_must_be_a_whole_number_from_one_to_five(client, factory, db, stars):
    room, host, (first, second) = finished_room(factory)
    api(client, 'POST', f"/rooms/{room['id']}/ratings", user=first,
        body={'user_id': second['id'], 'stars': stars}, expected=422)
    api(client, 'POST', f"/rooms/{room['id']}/ratings", user=first, body={'user_id': second['id']}, expected=422)
    api(client, 'POST', f"/rooms/{room['id']}/ratings", user=first, body={'stars': 3}, expected=422)
    assert stored(db) == 0


@pytest.mark.parametrize('stars', [1, 2, 3, 4, 5])
def test_every_valid_star_count_is_accepted(client, factory, stars):
    room, host, (first, second) = finished_room(factory)
    assert rate(client, room, first, second, stars)['stars'] == stars


def test_only_participants_can_rate_or_be_rated(client, factory, db):
    room, host, (player, _) = finished_room(factory)
    outsider, pending, left = factory.user(), factory.user(), factory.user()
    factory.member(pending, room=room, status='pending')
    factory.member(left, room=room, status='left')
    for stranger in (outsider, pending, left):
        rate(client, room, stranger, player, expected=403)
        rate(client, room, player, stranger, expected=400)
    assert 'did not take part' in rate(client, room, player, outsider, expected=400)['detail']
    api(client, 'POST', f"/rooms/{room['id']}/ratings", user=player, body={'user_id': 999999, 'stars': 3}, expected=404)
    api(client, 'POST', '/rooms/999999/ratings', user=player, body={'user_id': host['id'], 'stars': 3}, expected=404)
    assert stored(db) == 0


def test_private_rooms_stay_hidden_from_outsiders(client, factory):
    host, player, outsider = factory.user(), factory.user(), factory.user()
    room = factory.room(host, status='completed', visibility='private')
    factory.member(player, room=room)
    api(client, 'POST', f"/rooms/{room['id']}/ratings", user=outsider, body={'user_id': player['id'], 'stars': 3}, expected=404)
    api(client, 'GET', f"/rooms/{room['id']}/ratings/mine", user=outsider, expected=404)
    rate(client, room, player, host, 5)


@pytest.mark.parametrize('attendance,counts', [(None, True), ('unknown', True), ('present', True),
                                                ('excused', True), ('no_show', False)])
def test_no_shows_neither_rate_nor_get_rated(client, factory, db, attendance, counts):
    room, host, (player, marked) = finished_room(factory)
    with db() as session:
        session.query(MembershipModel).filter_by(room_id=room['id'], user_id=marked['id']).one().attendance = attendance
        session.commit()
    rate(client, room, player, marked, expected=201 if counts else 400)
    rate(client, room, marked, player, expected=201 if counts else 403)
    # The host still counts, and a no-show cannot rate even the host
    rate(client, room, player, host)
    rate(client, room, marked, host, expected=201 if counts else 403)
    assert stored(db) == 1 + 3 * counts


def test_no_show_message_names_the_missing_participation(client, factory, db):
    room, host, (player, absent) = finished_room(factory)
    with db() as session:
        session.query(MembershipModel).filter_by(user_id=absent['id']).one().attendance = 'no_show'
        session.commit()
    assert rate(client, room, player, absent, expected=400)['detail'] == 'That user did not take part in this room'


def test_ratings_require_a_signed_in_user(client, factory):
    room, host, (player, _) = finished_room(factory)
    api(client, 'POST', f"/rooms/{room['id']}/ratings", body={'user_id': host['id'], 'stars': 3}, expected=401)
    api(client, 'GET', f"/rooms/{room['id']}/ratings/mine", expected=401)


def test_average_counts_player_ratings_and_host_ratings_once_each(client, factory, db):
    room, host, (first, second) = finished_room(factory)
    # Nobody has rated yet
    assert api(client, 'GET', f"/users/{first['id']}/rating") == {'user_id': first['id'], 'average_rating': None, 'rating_count': 0}
    rate(client, room, second, first, 5)
    assert api(client, 'GET', f"/users/{first['id']}/rating") == {'user_id': first['id'], 'average_rating': 5.0, 'rating_count': 1}
    third = factory.user()
    factory.member(third, room=room)
    rate(client, room, third, first, 4)
    # A host rating from the existing attendance flow adds one more rating
    with db() as session:
        row = session.query(MembershipModel).filter_by(room_id=room['id'], user_id=first['id']).one()
        row.attendance, row.rating = 'present', 4
        session.commit()
    result = api(client, 'GET', f"/users/{first['id']}/rating")
    assert result['rating_count'] == 3 and result['average_rating'] == 4.3
    # The host and a member nobody rated have no ratings; an unrated host rating (NULL) is not counted
    assert api(client, 'GET', f"/users/{host['id']}/rating")['rating_count'] == 0
    assert api(client, 'GET', f"/users/{third['id']}/rating")['average_rating'] is None


@pytest.mark.parametrize('stars,average', [([5, 4, 4, 4], 4.3), ([1, 1, 2], 1.3), ([5, 5, 4], 4.7), ([3, 4], 3.5), ([2], 2.0)])
def test_average_rounds_half_up_to_one_decimal(client, factory, stars, average):
    room, host, members = finished_room(factory, players=len(stars) + 1)
    ratee, raters = members[0], members[1:]
    for rater, value in zip(raters, stars):
        rate(client, room, rater, ratee, value)
    result = api(client, 'GET', f"/users/{ratee['id']}/rating")
    assert result == {'user_id': ratee['id'], 'average_rating': average, 'rating_count': len(stars)}


def test_the_average_spans_rooms_and_is_public(client, factory):
    first_room, host, (player, rater) = finished_room(factory)
    second_room = factory.room(host, status='completed')
    factory.member(player, room=second_room)
    factory.member(rater, room=second_room)
    rate(client, first_room, rater, player, 5)
    rate(client, second_room, rater, player, 2)
    assert api(client, 'GET', f"/users/{player['id']}/rating")['average_rating'] == 3.5
    api(client, 'GET', '/users/999999/rating', expected=404)


def test_nothing_reveals_who_rated_whom(client, factory, db):
    room, host, (first, second) = finished_room(factory)
    created = rate(client, room, first, second, 2)
    assert set(created) == {'user_id', 'stars'}
    public = api(client, 'GET', f"/users/{second['id']}/rating")
    assert set(public) == {'user_id', 'average_rating', 'rating_count'}
    # The rated player and the host see nothing about the rater anywhere
    for viewer in (second, host):
        assert api(client, 'GET', f"/rooms/{room['id']}/ratings/mine", user=viewer) == []
        assert 'rating' not in api(client, 'GET', f"/users/{second['id']}", user=viewer)
        assert set(api(client, 'GET', f"/users/{second['id']}/rating", user=viewer)) == {'user_id', 'average_rating', 'rating_count'}
    with db() as session:
        assert session.query(NotificationModel).count() == 0


def test_database_rejects_out_of_range_stars_and_duplicates(factory, db):
    room, host, (first, second) = finished_room(factory)
    def add(**values):
        with db() as session:
            session.add(PlayerRatingModel(**{'rater_id': first['id'], 'ratee_id': second['id'], 'room_id': room['id'], 'stars': 3, **values}))
            session.commit()
    for stars in (0, 6):
        with pytest.raises(IntegrityError):
            add(stars=stars)
    add()
    with pytest.raises(IntegrityError):
        add(stars=4)
