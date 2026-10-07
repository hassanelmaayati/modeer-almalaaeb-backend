"""Case-insensitive user names and login/signup rate limits."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy.exc import IntegrityError

from controllers.google_auth import unique_user_name
from models.user import UserModel
from services.rate_limit import RateLimiter
from tests.lib import PASSWORD, api


def signup(client, name, email=None, expected=201):
    return api(client, 'POST', '/auth/signup', expected=expected,
               body={'user_name': name, 'email': email or f'{name.lower()}@example.test', 'password': PASSWORD})


def login(client, email, password, expected):
    return client.post('/api/v1/auth/login', json={'email': email, 'password': password}), expected


def test_user_names_are_unique_ignoring_case(client, factory, db):
    signup(client, 'CaseName')
    assert signup(client, 'casename', 'other@example.test', expected=400)['detail'] == 'user name is already taken'
    signup(client, 'CASENAME', 'third@example.test', expected=400)
    other = factory.user('another_player')
    api(client, 'PUT', '/users/me', user=other, body={'user_name': 'CASEname'}, expected=400)
    # Changing only the case of your own name is allowed
    renamed = api(client, 'PUT', '/users/me', user=other, body={'user_name': 'Another_Player'})
    assert renamed['user_name'] == 'Another_Player'
    with db() as session:
        session.add(UserModel(user_name='cASEnAME', email='direct@example.test', password='hash'))
        with pytest.raises(IntegrityError):
            session.commit()


def test_google_generated_names_avoid_case_variants(factory, db):
    factory.user('CaseName')
    with db() as session:
        assert unique_user_name(session, 'casename@example.test') == 'casename2'


def test_simultaneous_case_variant_signups_create_one_account(client, db):
    barrier = Barrier(2)
    def attempt(name):
        barrier.wait(timeout=5)
        return client.post('/api/v1/auth/signup', json={'user_name': name, 'email': f'{name}@example.test', 'password': PASSWORD}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(attempt, ['Racer', 'racer']))
    assert sorted(statuses) == [201, 400]
    with db() as session:
        assert session.query(UserModel).count() == 1


def test_login_is_limited_per_email_and_a_success_resets_it(client, factory):
    user, other = factory.user(), factory.user()
    for _ in range(9):
        assert client.post('/api/v1/auth/login', json={'email': user['email'], 'password': 'wrong-password'}).status_code == 401
    assert client.post('/api/v1/auth/login', json={'email': user['email'], 'password': PASSWORD}).status_code == 200
    for _ in range(10):
        assert client.post('/api/v1/auth/login', json={'email': user['email'], 'password': 'wrong-password'}).status_code == 401
    blocked = client.post('/api/v1/auth/login', json={'email': user['email'], 'password': PASSWORD})
    assert blocked.status_code == 429 and int(blocked.headers['Retry-After']) > 0
    # Other emails are not affected
    assert client.post('/api/v1/auth/login', json={'email': other['email'], 'password': PASSWORD}).status_code == 200


def test_login_is_limited_per_ip_across_emails(client):
    for index in range(60):
        assert client.post('/api/v1/auth/login', json={'email': f'nobody{index}@example.test', 'password': 'wrong-password'}).status_code == 401
    assert client.post('/api/v1/auth/login', json={'email': 'nobody99@example.test', 'password': 'wrong-password'}).status_code == 429


def test_signup_is_limited_per_email_and_per_ip(client):
    signup(client, 'first_player', 'same@example.test')
    for _ in range(4):
        signup(client, 'first_player', 'same@example.test', expected=400)
    blocked = signup(client, 'first_player', 'same@example.test', expected=429)
    assert blocked['detail'] == 'Too many attempts, try again later'
    from services import rate_limit
    rate_limit.reset_all()
    for index in range(20):
        signup(client, f'player_{index}')
    signup(client, 'player_over_limit', expected=429)


def test_rate_limiter_window_expiry_reset_and_bounded_memory():
    now = [0.0]
    limiter = RateLimiter(2, 10, max_keys=3, clock=lambda: now[0])
    limiter.hit('a'); limiter.hit('a')
    with pytest.raises(Exception) as limited:
        limiter.hit('a')
    assert limited.value.status_code == 429 and limited.value.headers['Retry-After'] == '11'
    now[0] = 10.5
    limiter.hit('a')
    limiter.hit('b'); limiter.hit('c')
    limiter.hit('d')
    assert len(limiter.events) <= 3 and 'a' not in limiter.events
    limiter.reset('d')
    assert 'd' not in limiter.events
    limiter.clear()
    assert limiter.events == {}
