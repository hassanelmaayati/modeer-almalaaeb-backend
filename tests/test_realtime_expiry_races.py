import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import jwt
import pytest
from fastapi import Request
from sqlalchemy import text
from websockets.exceptions import ConnectionClosed

from config.environment import JWT_SECRET
from database import get_db
from models.membership import MembershipModel
from models.message import MessageModel
from models.notification import NotificationModel
from models.room import RoomModel
from models.user import UserModel
from services import realtime
from tests.lib import api
from tests.test_realtime import receive, user_socket


def test_ready_idle_socket_closes_when_its_access_token_expires(network, factory, db):
    user = factory.user()
    expires = int(time.time()) + 2
    token = jwt.encode({'sub': str(user['id']), 'ver': user['token_version'], 'exp': expires}, JWT_SECRET, algorithm='HS256')
    expiring_user = {**user, 'headers': {'Authorization': 'Bearer ' + token}}
    with user_socket(network, expiring_user) as socket:
        assert time.time() < expires, 'Socket must be ready before its token expires'
        # No application traffic or logout wakes the server: its expiry timer must close it.
        with pytest.raises(ConnectionClosed) as closed:
            socket.recv(timeout=4)
        assert closed.value.rcvd.code == 1008 and time.time() >= expires
    api(network.client, 'GET', '/users/me', user=expiring_user, expected=401)
    deadline = time.monotonic() + 2
    while realtime.realtime_hub.by_ip and time.monotonic() < deadline:
        time.sleep(.01)
    assert realtime.realtime_hub.connections == {} and realtime.realtime_hub.by_ip == {}
    with db() as session:
        assert session.get(UserModel, user['id']).token_version == user['token_version']
        assert session.query(NotificationModel).count() == 0


def wait_for_row_lock(db, application_name, pending):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with db() as session:
            waiting = session.execute(text(
                "SELECT query, cardinality(pg_blocking_pids(pid)) FROM pg_stat_activity "
                "WHERE application_name = :name AND wait_event_type = 'Lock'"
            ), {'name': application_name}).first()
        if waiting:
            # pg_stat_activity truncates long membership SELECTs before their FOR UPDATE suffix.
            assert waiting[0].lstrip().startswith('SELECT') and waiting[1] > 0
            return
        if pending.done():
            response = pending.result()
            pytest.fail(f'Competing write did not wait for the parent lock: {response.status_code} {response.text}')
        time.sleep(.005)
    pytest.fail('Competing HTTP request never reached the PostgreSQL row lock')


def race_case(factory, case):
    owner, member = factory.user(), factory.user()
    if case == 'direct-block':
        membership = factory.friend(owner, member)
        return owner, member, membership, {'recipient_id': owner['id']}, (
            'PATCH', f"/friends/{member['id']}", {'user_blocked_other': 'true'}), 403
    kind = 'group' if case == 'group-remove' else 'room'
    target = factory.group(owner) if kind == 'group' else factory.room(owner, visibility='private')
    membership = factory.member(member, **{kind: target})
    if case == 'room-cancel':
        change = ('POST', f"/rooms/{target['id']}/cancel", {'reason': 'Concurrent cancellation'})
        denied_status = 409
    else:
        change = ('PATCH', f"/{kind}s/{target['id']}/members/{member['id']}", {'status': 'removed'})
        # A removed member of a private room cannot see it any more (404); group chat stays 403
        denied_status = 404 if kind == 'room' else 403
    return owner, member, membership, {kind + '_id': target['id']}, change, denied_status


@pytest.mark.parametrize('case', ['room-remove', 'group-remove', 'direct-block', 'room-cancel'])
@pytest.mark.parametrize('first', ['message', 'change'])
def test_chat_write_serializes_with_permission_or_room_change(network, configured_app, factory, db, case, first):
    owner, member, membership, target, change, denied_status = race_case(factory, case)
    request_id = uuid4()
    message = ('POST', '/messages', {**target, 'body': 'Transaction-order message', 'client_request_id': str(request_id)})
    at_commit, release = Event(), Event()
    label = 'modeer-race-' + uuid4().hex
    labels = {'message': label + '-message', 'change': label + '-change'}
    previous = configured_app.dependency_overrides[get_db]

    def controlled_session(request: Request):
        with db() as session:
            name = request.headers.get('x-test-transaction', '')
            if name:
                session.execute(text("SELECT set_config('application_name', :name, true)"), {'name': name})
            original_commit = session.commit
            def commit():
                if name == labels[first]:
                    at_commit.set()
                    if not release.wait(timeout=3):
                        raise AssertionError('Test did not release the first transaction')
                original_commit()
            session.commit = commit
            yield session

    def request(action):
        method, path, body = message if action == 'message' else change
        user = member if action == 'message' else owner
        return network.client.request(method, '/api/v1' + path, json=body,
                                      headers={**user['headers'], 'x-test-transaction': labels[action]})

    with user_socket(network, owner) as socket:
        configured_app.dependency_overrides[get_db] = controlled_session
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first_result = pool.submit(request, first)
                try:
                    assert at_commit.wait(timeout=2), 'First HTTP mutation did not reach commit'
                    second = 'change' if first == 'message' else 'message'
                    second_result = pool.submit(request, second)
                    wait_for_row_lock(db, labels[second], second_result)
                finally:
                    release.set()
                responses = {first: first_result.result(timeout=3), second: second_result.result(timeout=3)}
        finally:
            release.set()
            configured_app.dependency_overrides[get_db] = previous

        assert responses['change'].status_code == 200, responses['change'].text
        expected = 201 if first == 'message' else denied_status
        assert responses['message'].status_code == expected, responses['message'].text
        if first == 'message':
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                event = receive(socket, 'message.created')
                if event['message']['client_request_id'] == str(request_id):
                    assert event['message']['id'] == responses['message'].json()['id']
                    break
            else:
                pytest.fail('Committed chat message was not delivered to its authorized owner')
        else:
            # Cancellation may send a system notice, but the rejected user message must never appear.
            deadline = time.monotonic() + .15
            while time.monotonic() < deadline:
                try:
                    event = json.loads(socket.recv(timeout=max(.001, deadline - time.monotonic())))
                except TimeoutError:
                    break
                if event['type'] == 'message.created':
                    assert event['message']['client_request_id'] != str(request_id)

    with db() as session:
        sent = session.query(MessageModel).filter_by(client_request_id=request_id).all()
        assert len(sent) == (1 if first == 'message' else 0)
        assert session.query(NotificationModel).filter(NotificationModel.kind.like('message.%')).count() == len(sent)
        row = session.get(MembershipModel, membership['id'])
        if case == 'direct-block':
            assert row.user_blocked_other == 'true'
        elif case == 'room-cancel':
            assert session.get(RoomModel, target['room_id']).status == 'cancelled'
            assert session.query(MessageModel).filter_by(type='system').count() == 1
        else:
            assert row.status == 'removed' and row.accepted is False
