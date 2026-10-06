"""HTTP boundaries, private projections and error paths absent from happy paths."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from models.group import GroupModel
from models.message import MessageModel
from models.notification import NotificationModel
from models.user import UserModel
from tests.lib import PASSWORD, api


@pytest.mark.parametrize('header', [None, '', 'Bearer', 'Basic abc', 'Bearer junk', 'Bearer a.b.c'])
def test_bad_authorization_headers_never_mutate_accounts(client, factory, db, header):
    user = factory.user()
    headers = {} if header is None else {'Authorization': header}
    response = client.put('/api/v1/users/me', headers=headers, json={'user_name': 'attempted_change'})
    assert response.status_code == 401
    with db() as session:
        assert session.get(UserModel, user['id']).user_name == user['user_name']


@pytest.mark.parametrize('change', [
    {'sub': True}, {'sub': 1}, {'sub': []}, {'sub': {}}, {'sub': '0'}, {'sub': '-1'},
    {'ver': True}, {'ver': '0'}, {'ver': None}, {'exp': 'invalid'}, {'exp': None},
    {'iat': int(datetime.now(timezone.utc).timestamp()) + 86400},
])
def test_malformed_jwt_claims_return_401_for_http_and_socket_ticket(client, factory, change):
    user = factory.user()
    claims = {'sub': str(user['id']), 'ver': 0, 'exp': datetime.now(timezone.utc) + timedelta(hours=1), **change}
    token = jwt.encode(claims, 'modeer-isolated-backend-test-secret-2026', algorithm='HS256')
    headers = {'Authorization': 'Bearer ' + token}
    assert client.get('/api/v1/users/me', headers=headers).status_code == 401
    assert client.post('/api/v1/socket-ticket', headers=headers).status_code == 401


@pytest.mark.parametrize('algorithm,secret', [('HS256', 'a-different-signing-secret-long-enough'), ('HS512', 'x' * 64)])
def test_wrong_signature_and_algorithm_cannot_access_private_data(client, factory, algorithm, secret):
    user = factory.user()
    token = jwt.encode({'sub': str(user['id']), 'ver': 0, 'exp': datetime.now(timezone.utc) + timedelta(hours=1)}, secret, algorithm=algorithm)
    assert client.get('/api/v1/users/me', headers={'Authorization': 'Bearer ' + token}).status_code == 401


@pytest.mark.parametrize('change', [
    {'user_name': ''}, {'user_name': '   '}, {'user_name': 'x' * 61}, {'user_name': None},
    {'email': ''}, {'email': 'two@@example.test'}, {'email': 'space @example.test'}, {'email': None},
    {'password': 'x' * 7}, {'password': ''}, {'password': None},
    {'bio': 'x' * 501}, {'district': ''}, {'district': 'CAPITAL'},
], ids=['empty-name', 'blank-name', 'long-name', 'null-name', 'empty-email', 'double-at', 'spaced-email', 'null-email',
        'short-password', 'empty-password', 'null-password', 'long-bio', 'empty-district', 'district-case'])
def test_signup_boundary_errors_leave_every_account_table_empty(client, db, change):
    api(client, 'POST', '/auth/signup', body={'user_name': 'valid_player', 'email': 'valid@example.test', 'password': PASSWORD, **change}, expected=422)
    with db() as session:
        assert session.query(UserModel).count() == 0
        assert session.query(NotificationModel).count() == 0


def test_signup_normalization_boundaries_and_server_fields_are_canonical(client, db):
    name = 'x' * 60
    body = {'user_name': ' ' + name + ' ', 'email': '  UPPER@EXAMPLE.TEST ', 'password': 'x' * 8,
            'bio': 'b' * 500, 'district': None, 'id': 9876, 'token_version': 9876,
            'google_subject': 'attacker-supplied-subject', 'password_hash': 'pretend-hash'}
    created = api(client, 'POST', '/auth/signup', body=body, expected=201)
    assert created['user']['user_name'] == name
    assert created['user']['email'] == 'upper@example.test' and not created['user']['google_linked']
    with db() as session:
        stored = session.get(UserModel, created['user']['id'])
        assert stored.id != 9876 and stored.token_version == 0 and stored.google_subject is None
        assert stored.bio == 'b' * 500 and stored.verify_password('x' * 8)
    logged_in = api(client, 'POST', '/auth/login', body={'email': ' UPPER@EXAMPLE.TEST ', 'password': 'x' * 8})
    assert logged_in['user']['id'] == created['user']['id']
    api(client, 'POST', '/auth/signup', body={**body, 'user_name': 'another_name'}, expected=400)


@pytest.mark.parametrize('change', [{'user_name': None}, {'user_name': '  '}, {'user_name': 'x' * 61}, {'bio': 'b' * 501}, {'district': 'unknown'}],
                         ids=['null-name', 'blank-name', 'long-name', 'long-bio', 'unknown-district'])
def test_profile_invalid_update_is_atomic(client, factory, db, change):
    user = factory.user()
    api(client, 'PUT', '/users/me', user=user, body={'user_name': 'new_name', 'bio': 'uncommitted', **change}, expected=422)
    with db() as session:
        stored = session.get(UserModel, user['id'])
        assert stored.user_name == user['user_name'] and stored.bio == ''


def test_profile_optional_fields_clear_and_identity_fields_cannot_be_spoofed(client, factory, db):
    user = factory.user(bio='original bio', photo_url='https://example.test/picture')
    updated = api(client, 'PUT', '/users/me', user=user, body={
        'user_name': '  edited_name  ', 'bio': None, 'photo_url': None, 'district': None,
        'email': 'different@example.test', 'id': 99999, 'token_version': 12, 'google_subject': 'spoofed', 'password': 'Changed123!',
    })
    assert updated['user_name'] == 'edited_name'
    assert updated['bio'] is None and updated['photo_url'] is None and updated['district'] is None
    with db() as session:
        stored = session.get(UserModel, user['id'])
        assert stored.email == user['email'] and stored.token_version == 0 and stored.google_subject is None
        assert stored.verify_password(PASSWORD)


@pytest.mark.parametrize('change,status', [
    ({'name': ''}, 422), ({'name': '  '}, 422), ({'name': 'x' * 121}, 422), ({'name': None}, 422),
    ({'sports_id': None}, 422), ({'sports_id': 99999}, 404),
], ids=['empty-name', 'blank-name', 'long-name', 'null-name', 'null-sport', 'missing-sport'])
def test_invalid_groups_do_not_create_groups_or_notifications(client, factory, db, change, status):
    owner, sport = factory.user(), factory.sport()
    api(client, 'POST', '/groups', user=owner, body={'name': 'A team', 'sports_id': sport['id'], **change}, expected=status)
    with db() as session:
        assert session.query(GroupModel).count() == 0 and session.query(NotificationModel).count() == 0


def test_group_input_limits_normalize_and_preserve_server_owned_fields(client, factory, db):
    owner, other, sport = factory.user(), factory.user(), factory.sport()
    group = api(client, 'POST', '/groups', user=owner,
                body={'name': ' ' + 'x' * 118 + ' ', 'sports_id': sport['id'], 'owner_id': other['id'], 'id': 9999}, expected=201)
    assert group['name'] == 'x' * 118 and group['owner_id'] == owner['id'] and group['id'] != 9999
    updated = api(client, 'PUT', f"/groups/{group['id']}", user=owner,
                  body={'name': 'Renamed', 'description': None, 'photo_url': None, 'owner_id': other['id'], 'sports_id': 9999})
    assert updated['owner_id'] == owner['id'] and updated['sports_id'] == sport['id']
    assert updated['description'] is None and updated['photo_url'] is None


@pytest.mark.parametrize('kind', ['room', 'group', 'direct'])
@pytest.mark.parametrize('character', ['x', 'م', '💪'], ids=['ascii', 'arabic', 'non-bmp'])
def test_message_maximum_boundary_missing_target_and_retry_do_not_duplicate(client, factory, db, kind, character):
    from uuid import uuid4
    owner, member = factory.user(), factory.user()
    if kind == 'direct':
        factory.friend(owner, member)
        target = {'recipient_id': member['id']}
    else:
        container = factory.room(owner) if kind == 'room' else factory.group(owner)
        factory.member(member, **{kind: container})
        target = {kind + '_id': container['id']}
    payload = {**target, 'body': character * 2000, 'client_request_id': str(uuid4())}
    created = api(client, 'POST', '/messages', user=owner, body=payload, expected=201)
    assert created['body'] == character * 2000 and len(created['body']) == 2000
    api(client, 'POST', '/messages', user=owner, body={**payload, 'body': character * 2001}, expected=422)
    api(client, 'POST', '/messages', user=owner, body={'body': 'No target', 'client_request_id': str(uuid4())}, expected=422)
    missing = {'recipient_id' if kind == 'direct' else kind + '_id': 999999}
    api(client, 'POST', '/messages', user=owner, body={**payload, **missing, 'client_request_id': str(uuid4())}, expected=404)
    with db() as session:
        assert session.query(MessageModel).count() == 1 and session.query(NotificationModel).count() == 1
        assert session.query(MessageModel).one().body == character * 2000


@pytest.mark.parametrize('origin,allowed', [('http://localhost:5174', True), ('https://untrusted.example', False)])
def test_http_cors_preflight_respects_exact_configured_origins(client, origin, allowed):
    response = client.options('/api/v1/rooms', headers={'Origin': origin,
                                'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type'})
    assert response.status_code == (200 if allowed else 400)
    assert response.headers.get('access-control-allow-origin') == (origin if allowed else None)


def test_socket_ticket_is_uncacheable_and_notification_empty_pagination_is_exact(client, factory):
    user = factory.user()
    ticket = client.post('/api/v1/socket-ticket', headers=user['headers'])
    assert ticket.status_code == 200 and ticket.headers['cache-control'] == 'no-store'
    assert ticket.json()['expires_in'] == 30 and len(ticket.json()['ticket']) >= 32
    for params in ({'limit': 1}, {'limit': 100, 'before': 99999}, {'unread_only': True}):
        assert api(client, 'GET', '/notifications', user=user, params=params) == {'items': [], 'unread_count': 0}
