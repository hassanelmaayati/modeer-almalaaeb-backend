"""?near_lat=&near_lng=&radius_km= on GET /rooms: sorted by distance, never revealing the venue pin."""
from datetime import datetime, timedelta, timezone

import pytest

from models.room import make_point
from tests.lib import api, future

ORIGIN = (26.2285, 50.5860)


def listed(client, user=None, **params):
    response = client.get('/api/v1/rooms', headers=user['headers'] if user else {}, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def near(client, lat=ORIGIN[0], lng=ORIGIN[1], radius=10, user=None, **params):
    return listed(client, user, near_lat=lat, near_lng=lng, radius_km=radius, **params)


def pinned(factory, host, lat, lng, **changes):
    return factory.room(host, venue_point=make_point(lat, lng), **changes)


def test_rooms_are_filtered_by_radius_and_sorted_nearest_first(client, factory):
    host = factory.user()
    far = pinned(factory, host, 26.1300, 50.5550, starts_at=future(30), ends_at=future(31))   # Riffa, about 10 km
    close = pinned(factory, host, 26.2255, 50.5805, starts_at=future(40), ends_at=future(41))
    nopin = factory.room(host)
    assert [room['id'] for room in near(client, radius=5)] == [close['id']]
    found = near(client, radius=20)
    assert [room['id'] for room in found] == [close['id'], far['id']]
    assert found[0]['km_away'] <= 2 and 8 <= found[1]['km_away'] <= 13
    assert all(isinstance(room['km_away'], int) for room in found)
    # Without the filter nothing changes: every listed room, no distance
    everything = listed(client)
    assert {room['id'] for room in everything} == {far['id'], close['id'], nopin['id']}
    assert all(room['km_away'] is None for room in everything)


def test_only_rooms_that_discovery_already_lists_can_be_found_by_distance(client, factory):
    host, member, outsider = factory.user(), factory.user(), factory.user()
    group = factory.group(host)
    factory.member(member, group=group)
    shown = pinned(factory, host, 26.2255, 50.5805)
    hidden = [
        pinned(factory, host, 26.2255, 50.5805, visibility='private'),
        pinned(factory, host, 26.2255, 50.5805, status='cancelled'),
        pinned(factory, host, 26.2255, 50.5805, status='started'),
        pinned(factory, host, 26.2255, 50.5805, starts_at=datetime.now(timezone.utc) + timedelta(minutes=10),
               ends_at=datetime.now(timezone.utc) + timedelta(hours=1)),
    ]
    group_room = pinned(factory, host, 26.2255, 50.5805, visibility='group', group_id=group['id'])
    assert [room['id'] for room in near(client)] == [shown['id']]
    assert {room['id'] for room in near(client, user=member)} == {shown['id'], group_room['id']}
    assert {room['id'] for room in near(client, user=outsider)} == {shown['id']}
    assert not {room['id'] for room in hidden} & {room['id'] for room in near(client, user=host)}


def test_the_filter_cannot_tell_two_pins_in_the_same_area_apart(client, factory):
    host = factory.user()
    # About 0.6 km apart, inside the same ~2 km grid cell
    first = pinned(factory, host, 26.2255, 50.5805, starts_at=future(30), ends_at=future(31))
    second = pinned(factory, host, 26.2285, 50.5845, starts_at=future(40), ends_at=future(41))
    origins = [(26.2285, 50.5860), (26.2100, 50.5700), (26.2500, 50.6100), (26.1900, 50.5400), (26.2400, 50.5600)]
    for lat, lng in origins:
        # Whatever the radius, both rooms come in and out of the results together,
        # so growing or shrinking the circle cannot home in on either exact pin
        for radius in range(1, 31):
            members = {room['id'] for room in near(client, lat=lat, lng=lng, radius=radius)}
            assert members in (set(), {first['id'], second['id']}), (lat, lng, radius)
        shown = near(client, lat=lat, lng=lng, radius=30)
        assert shown[0]['km_away'] == shown[1]['km_away']
        # Equal distance, so the order is the plain start-time order
        assert [room['id'] for room in shown] == [first['id'], second['id']]


def test_the_response_never_adds_location_detail(client, factory):
    host = factory.user()
    pinned(factory, host, 26.2255, 50.5805, venue_notes='Private court')
    [room] = near(client)
    assert {'venue_location', 'venue_notes', 'venue_point'}.isdisjoint(room)
    assert room['area'] == 'Manama' and isinstance(room['km_away'], int)
    assert not any(isinstance(value, float) and abs(value - 26.2255) < 0.01 for value in room.values())


@pytest.mark.parametrize('params', [
    {'near_lat': 26.2}, {'near_lng': 50.5}, {'near_lat': 91, 'near_lng': 50.5}, {'near_lat': 26.2, 'near_lng': 181},
    {'near_lat': 26.2, 'near_lng': 50.5, 'radius_km': 0.5}, {'near_lat': 26.2, 'near_lng': 50.5, 'radius_km': 51},
])
def test_distance_parameters_are_validated(client, params):
    assert client.get('/api/v1/rooms', params=params).status_code == 422


def test_distance_results_page_and_count(client, factory):
    host = factory.user()
    rooms = [pinned(factory, host, 26.2255, 50.5805, starts_at=future(30 + number), ends_at=future(31 + number)) for number in range(3)]
    response = client.get('/api/v1/rooms', params={'near_lat': ORIGIN[0], 'near_lng': ORIGIN[1], 'limit': 2, 'offset': 1})
    assert [room['id'] for room in response.json()] == [room['id'] for room in rooms[1:]]
    assert response.headers['X-Total-Count'] == '3'
    assert near(client, radius=5, sport_id=rooms[0]['sport_id'])[0]['id'] == rooms[0]['id']
