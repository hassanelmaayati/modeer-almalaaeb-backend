"""Input bounds, safe failures and health checks."""
import logging

import pytest

from tests.lib import api, room_body


def post_room(client, user, sport, expected=201, **changes):
    return api(client, 'POST', '/rooms', user=user, body=room_body(sport['id'], **changes), expected=expected)


def test_signup_password_and_email_have_maximums(client):
    body = {'user_name': 'longpass', 'email': 'lp@example.test', 'password': 'p' * 129}
    api(client, 'POST', '/auth/signup', body=body, expected=422)
    api(client, 'POST', '/auth/signup', body={**body, 'email': 'a' * 250 + '@x.co'}, expected=422)
    api(client, 'POST', '/auth/signup', body={**body, 'password': 'p' * 128}, expected=201)


def test_over_long_login_passwords_fail_like_any_wrong_password(client, factory):
    user = factory.user()
    def attempt(email, password):
        return client.post('/api/v1/auth/login', json={'email': email, 'password': password})
    known, unknown = attempt(user['email'], 'p' * 5000), attempt('nobody@example.test', 'p' * 5000)
    wrong = attempt(user['email'], 'wrong-password')
    assert known.status_code == unknown.status_code == wrong.status_code == 401
    assert known.json() == unknown.json() == wrong.json() == {'detail': 'Invalid credentials'}


@pytest.mark.parametrize('capacity,expected', [(1000, 201), (1001, 422)])
def test_room_capacity_is_bounded(client, factory, capacity, expected):
    post_room(client, factory.user(), factory.sport('Swimming'), expected=expected, capacity=capacity)


@pytest.mark.parametrize('limit,expected', [(100, 201), (101, 422)])
def test_cup_roster_limit_is_bounded(client, factory, limit, expected):
    sport = factory.sport('Football')
    api(client, 'POST', '/cups', user=factory.user(), expected=expected,
        body={'sport_id': sport['id'], 'name': 'Cup', 'rules': 'Fair', 'team_count': 4, 'roster_limit': limit})


@pytest.mark.parametrize('path', ['/users', '/cups', '/rooms/mine', '/rooms/joined'])
def test_offsets_are_bounded_instead_of_crashing(client, factory, path):
    user = factory.user()
    api(client, 'GET', f'{path}?offset=1000000', user=user)
    api(client, 'GET', f'{path}?offset=1000001', user=user, expected=422)
    api(client, 'GET', f'{path}?offset={10 ** 20}', user=user, expected=422)


@pytest.mark.parametrize('field,limit', [('title', 120), ('description', 2000), ('notes', 1000), ('venue_notes', 1000),
                                         ('pace_notes', 500), ('route_notes', 1000)])
def test_room_text_fields_have_maximum_lengths(client, factory, db, field, limit):
    user, sport = factory.user(), factory.sport('Swimming')
    post_room(client, user, sport, **{field: 'x' * limit})
    post_room(client, user, sport, expected=422, **{field: 'x' * (limit + 1)})


def test_other_text_and_number_fields_have_limits(client, factory):
    user, sport = factory.user(), factory.sport('Swimming')
    post_room(client, user, sport, expected=422, distance_km=1001)
    room = post_room(client, user, sport)
    api(client, 'POST', f"/rooms/{room['id']}/cancel", user=user, body={'reason': 'x' * 501}, expected=422)
    api(client, 'POST', '/groups', user=user, body={'name': 'Team', 'sports_id': sport['id'], 'description': 'x' * 1001}, expected=422)
    football = factory.sport('Football')
    api(client, 'POST', '/cups', user=user, expected=422,
        body={'sport_id': football['id'], 'name': 'Cup', 'rules': 'x' * 5001, 'team_count': 4, 'roster_limit': 8})


@pytest.mark.parametrize('layout', [
    {'x': 1}, {'slots': 'GK'}, {'slots': [1]}, {'slots': ['a', 'a']}, {'slots': ['']}, {'slots': ['x' * 51]},
    {'slots': [str(index) for index in range(101)]}, {'teams': [{}] * 5}, {'teams': 'A'},
    {'teams': [{'slots': ['a'], 'extra': 1}]}, {'teams': [{'name': 1, 'slots': []}]},
    {'slots': ['A'], 'teams': [{'slots': ['A']}]}, {'slots': [[[[[]]]]]}, None,
])
def test_invalid_slot_layouts_are_rejected_with_422(client, factory, layout):
    post_room(client, factory.user(), factory.sport('Swimming'), expected=422, capacity=200, slot_layout=layout)


def test_deeply_nested_slot_layout_never_crashes(client, factory):
    nested = current = []
    for _ in range(900):
        inner = []
        current.append(inner)
        current = inner
    post_room(client, factory.user(), factory.sport('Swimming'), expected=422, slot_layout={'slots': nested})


def test_valid_slot_layouts_are_stored_trimmed(client, factory, db):
    user, sport = factory.user(), factory.sport('Swimming')
    assert post_room(client, user, sport, slot_layout={})['slot_layout'] == {}
    assert post_room(client, user, sport, slot_layout={'slots': [' GK ', 'D1']})['slot_layout'] == {'slots': ['GK', 'D1']}
    teams = {'teams': [{'name': 'A', 'slots': ['A1']}, {'name': 'B', 'slots': ['B1']}]}
    assert post_room(client, user, sport, slot_layout=teams)['slot_layout'] == teams
    post_room(client, user, sport, expected=422, capacity=2, slot_layout={'slots': ['a', 'b', 'c']})


def test_layout_and_capacity_must_still_fit_when_only_one_is_edited(client, factory):
    user, sport = factory.user(), factory.sport('Swimming')
    room = post_room(client, user, sport, capacity=4, slot_layout={'slots': ['a', 'b', 'c']})
    url = f"/rooms/{room['id']}"
    api(client, 'PUT', url, user=user, body={'revision': 0, 'slot_layout': {'slots': ['a', 'b', 'c', 'd', 'e']}}, expected=422)
    api(client, 'PUT', url, user=user, body={'revision': 0, 'capacity': 2}, expected=422)
    edited = api(client, 'PUT', url, user=user, body={'revision': 0, 'slot_layout': {'slots': ['a', 'b']}})
    assert edited['slot_layout'] == {'slots': ['a', 'b']}


def test_oversized_bodies_are_refused_before_parsing(client):
    big = b'{"email":"' + b'x' * 70_000 + b'"}'
    assert client.post('/api/v1/auth/login', content=big, headers={'content-type': 'application/json'}).status_code == 413
    chunks = iter([b'x' * 40_000, b'x' * 40_000])
    assert client.post('/api/v1/auth/login', content=chunks, headers={'content-type': 'application/json'}).status_code == 413
    assert client.post('/api/v1/auth/login', json={'email': 'a@b.co', 'password': 'x'}).status_code == 401


def test_short_jwt_secret_only_warns(monkeypatch, caplog):
    import config.environment as environment
    monkeypatch.setattr(environment, 'JWT_SECRET', 'short-secret')
    with caplog.at_level(logging.WARNING):
        environment.require_settings()
    assert 'JWT_SECRET is shorter than 32' in caplog.text
    caplog.clear()
    monkeypatch.setattr(environment, 'JWT_SECRET', 'x' * 32)
    with caplog.at_level(logging.WARNING):
        environment.require_settings()
    assert 'JWT_SECRET' not in caplog.text


def test_health_stays_fast_and_readiness_pings_the_database(client, configured_app):
    assert client.get('/health').json() == {'ok': True}
    assert client.get('/health/ready').json() == {'ok': True, 'database': 'up'}
    import database

    class Broken:
        def execute(self, *args, **kwargs):
            raise RuntimeError('database down')

    configured_app.dependency_overrides[database.get_db] = lambda: Broken()
    assert client.get('/health').status_code == 200
    response = client.get('/health/ready')
    assert response.status_code == 503 and response.json() == {'ok': False, 'database': 'down'}
