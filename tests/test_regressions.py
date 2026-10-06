"""Regressions reproduced against the deployed application's existing contracts."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from database import get_db
from models.room import RoomModel
from models.user import UserModel, pwd_context as production_password_context
from tests.lib import PASSWORD, api, room_body


def synchronize_commits(app, db, parties=2):
    """Ensure requests pass their uniqueness queries before either commits."""
    barrier = Barrier(parties)
    previous = app.dependency_overrides[get_db]

    def session_for_request():
        with db() as session:
            original_commit = session.commit

            def commit():
                barrier.wait(timeout=5)
                original_commit()

            session.commit = commit
            yield session

    app.dependency_overrides[get_db] = session_for_request
    return previous


def test_explicit_null_clears_venue_pin_but_omission_preserves_it(client, factory, db):
    host, sport = factory.user(), factory.sport()
    pin = {'latitude': 26.2235, 'longitude': 50.5876}
    room = api(client, 'POST', '/rooms', user=host,
               body=room_body(sport['id'], venue_location=pin), expected=201)
    edited = api(client, 'PUT', f"/rooms/{room['id']}", user=host,
                 body={'revision': room['revision'], 'description': 'New description'})
    assert edited['venue_location'] == pin
    cleared = api(client, 'PUT', f"/rooms/{room['id']}", user=host,
                  body={'revision': edited['revision'], 'venue_location': None})
    assert cleared['venue_location'] is None
    with db() as session:
        stored = session.get(RoomModel, room['id'])
        assert stored.venue_point is None and stored.venue_location is None


@pytest.mark.parametrize('collision', ['username', 'email', 'both'])
def test_concurrent_signup_uniqueness_rolls_back_and_returns_client_error(
    client, configured_app, factory, db, collision,
):
    payloads = [
        {'user_name': 'first_player', 'email': 'first@example.test', 'password': PASSWORD},
        {'user_name': 'second_player', 'email': 'second@example.test', 'password': PASSWORD},
    ]
    if collision in ('username', 'both'):
        payloads[1]['user_name'] = payloads[0]['user_name']
    if collision in ('email', 'both'):
        payloads[1]['email'] = payloads[0]['email']
    previous = synchronize_commits(configured_app, db)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda body: client.post('/api/v1/auth/signup', json=body), payloads))
    finally:
        configured_app.dependency_overrides[get_db] = previous
    assert sorted(response.status_code for response in responses) == [201, 400]
    with db() as session:
        assert session.query(UserModel).count() == 1
    # An ordinary follow-up proves the error did not poison the database/session pool.
    payloads[0].update(user_name='after_race', email='after-race@example.test')
    api(client, 'POST', '/auth/signup', body=payloads[0], expected=201)


def test_concurrent_profile_username_collision_preserves_losing_profile(client, configured_app, factory, db):
    users = [factory.user(), factory.user()]
    previous = synchronize_commits(configured_app, db)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda user: client.put('/api/v1/users/me', headers=user['headers'],
                                  json={'user_name': 'shared_name', 'bio': 'Committed only for winner'}), users))
    finally:
        configured_app.dependency_overrides[get_db] = previous
    assert sorted(response.status_code for response in responses) == [200, 400]
    with db() as session:
        rows = [session.get(UserModel, user['id']) for user in users]
        assert sum(row.user_name == 'shared_name' for row in rows) == 1
        loser = next(row for row in rows if row.user_name != 'shared_name')
        assert loser.bio == ''


@pytest.mark.parametrize('password', ['a' * 73, 'ب' * 40, 'a' * 4096], ids=['ascii-tail', 'utf8-tail', 'long-password'])
def test_new_password_hashes_distinguish_the_entire_password(client, db, password):
    registered = api(client, 'POST', '/auth/signup', body={
        'user_name': 'long_password_player', 'email': 'long@example.test', 'password': password,
    }, expected=201)
    with db() as session:
        stored = session.get(UserModel, registered['user']['id'])
        assert stored.password.startswith('$bcrypt-sha256$v=2,')
        assert stored.verify_password(password)
        assert not stored.verify_password(password[:-1] + 'z')
    api(client, 'POST', '/auth/login', body={'email': 'long@example.test', 'password': password})
    api(client, 'POST', '/auth/login', body={'email': 'long@example.test', 'password': password[:-1] + 'z'}, expected=400)


def test_production_password_context_uses_v2_and_verifies_legacy_without_rewriting(monkeypatch):
    import models.user as users
    # Test the production context independently of the fast fixture's replacement.
    context = production_password_context
    monkeypatch.setattr(users, 'pwd_context', context)
    row = UserModel()
    row.set_password('A' * 72 + 'tail-one')
    assert row.password.startswith('$bcrypt-sha256$v=2,')
    assert row.verify_password('A' * 72 + 'tail-one')
    assert not row.verify_password('A' * 72 + 'tail-two')
    row.password = context.handler('bcrypt').hash(PASSWORD)
    before = row.password
    assert row.verify_password(PASSWORD) and not row.verify_password('wrong-password')
    assert row.password == before


@pytest.mark.parametrize('collision', ['same-subject', 'same-email', 'same-username'])
def test_google_signup_races_are_idempotent_or_explicit_conflicts(client, configured_app, factory, db, monkeypatch, collision):
    import controllers.google_auth as google
    claims = {
        'first': {'sub': 'first-subject', 'email': 'player@first.test', 'email_verified': True},
        'second': {'sub': 'second-subject', 'email': 'player@second.test', 'email_verified': True},
    }
    if collision == 'same-subject':
        claims['second'] = claims['first']
    elif collision == 'same-email':
        claims['second'] = {**claims['second'], 'email': claims['first']['email']}
    monkeypatch.setattr(google, 'verify_google_credential', lambda credential: claims[credential])
    # Only the initial commits need synchronization; username retry must be free to complete.
    barrier = Barrier(2)
    previous = configured_app.dependency_overrides[get_db]
    def controlled_session():
        with db() as session:
            original_commit = session.commit
            first_commit = True
            def commit():
                nonlocal first_commit
                if first_commit:
                    first_commit = False
                    barrier.wait(timeout=5)
                original_commit()
            session.commit = commit
            yield session
    configured_app.dependency_overrides[get_db] = controlled_session
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda credential: client.post('/api/v1/auth/google', json={'credential': credential}), claims))
    finally:
        configured_app.dependency_overrides[get_db] = previous
    expected = [200, 201] if collision == 'same-subject' else [201, 409] if collision == 'same-email' else [201, 201]
    assert sorted(response.status_code for response in responses) == expected
    with db() as session:
        rows = session.query(UserModel).all()
        assert len(rows) == (2 if collision == 'same-username' else 1)
        assert len({row.user_name for row in rows}) == len(rows)
    if collision == 'same-subject':
        assert responses[0].json()['user']['id'] == responses[1].json()['user']['id']


def test_google_link_race_has_one_owner_and_preserves_loser(client, configured_app, factory, db, monkeypatch):
    import controllers.google_auth as google
    users = [factory.user(), factory.user()]
    monkeypatch.setattr(google, 'verify_google_credential', lambda _: {
        'sub': 'one-google-account', 'email': 'google@example.test', 'email_verified': True,
    })
    previous = synchronize_commits(configured_app, db)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda user: client.post('/api/v1/auth/google/link',
                                  headers=user['headers'], json={'credential': 'verified'}), users))
    finally:
        configured_app.dependency_overrides[get_db] = previous
    assert sorted(response.status_code for response in responses) == [200, 400]
    with db() as session:
        rows = session.query(UserModel).filter(UserModel.id.in_([user['id'] for user in users])).all()
        assert sum(row.google_subject == 'one-google-account' for row in rows) == 1
        assert sum(row.google_subject is None for row in rows) == 1


def test_concurrent_google_links_to_the_same_account_cannot_overwrite_identity(client, factory, db, monkeypatch):
    import controllers.google_auth as google
    user = factory.user()
    barrier = Barrier(2)
    def verify(credential):
        barrier.wait(timeout=5)
        return {'sub': credential, 'email': 'google@example.test', 'email_verified': True}
    monkeypatch.setattr(google, 'verify_google_credential', verify)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda credential: client.post('/api/v1/auth/google/link',
                              headers=user['headers'], json={'credential': credential}), ['first-subject', 'second-subject']))
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = ['first-subject', 'second-subject'][next(index for index, response in enumerate(responses) if response.status_code == 200)]
    with db() as session:
        assert session.get(UserModel, user['id']).google_subject == winner


def test_legacy_bcrypt_account_can_log_in_without_hash_rewriting(client, factory, db):
    user = factory.user()
    legacy = production_password_context.handler('bcrypt').using(rounds=4).hash(PASSWORD)
    with db() as session:
        session.get(UserModel, user['id']).password = legacy
        session.commit()
    signed_in = api(client, 'POST', '/auth/login', body={'email': user['email'], 'password': PASSWORD})
    assert signed_in['user']['id'] == user['id']
    api(client, 'POST', '/auth/login', body={'email': user['email'], 'password': 'wrong-password'}, expected=400)
    with db() as session:
        assert session.get(UserModel, user['id']).password == legacy
