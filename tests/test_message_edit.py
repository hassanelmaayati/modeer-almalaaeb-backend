"""Editing and deleting your own chat messages."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from models.message import MessageModel
from models.notification import NotificationModel
from services.messages import message_events
from tests.lib import api
from tests.test_realtime import receive, user_socket


def send(client, user, expected=201, **target):
    return api(client, 'POST', '/messages', user=user, expected=expected,
               body={**target, 'body': 'first draft', 'client_request_id': str(uuid4())})


def attempt(client, method, message_id, user, body=None):
    response = client.request(method, f'/api/v1/messages/{message_id}', headers=user['headers'], json=body)
    detail = response.json().get('detail') if response.status_code >= 400 else None
    return response.status_code, detail


def room_chat(factory, **changes):
    host, member = factory.user(), factory.user()
    room = factory.room(host, **changes)
    factory.member(member, room=room)
    return room, host, member


def test_a_sender_edits_their_own_message(client, factory, db):
    room, host, member = room_chat(factory)
    saved = send(client, member, room_id=room['id'])
    assert saved['edited_at'] is None and saved['deleted'] is False
    edited = api(client, 'PATCH', f"/messages/{saved['id']}", user=member, body={'body': '  fixed text  '})
    assert edited['body'] == 'fixed text' and edited['deleted'] is False and edited['id'] == saved['id']
    assert abs(datetime.fromisoformat(edited['edited_at']) - datetime.now(timezone.utc)) < timedelta(minutes=2)
    [shown] = api(client, 'GET', '/messages', user=host, params={'room_id': room['id']})
    assert (shown['body'], shown['edited_at']) == ('fixed text', edited['edited_at'])
    with db() as session:
        assert session.query(NotificationModel).filter(NotificationModel.kind.like('message.%')).count() == 1  # only the original


def test_saving_the_same_text_changes_nothing(client, factory):
    room, host, member = room_chat(factory)
    saved = send(client, member, room_id=room['id'])
    unchanged = api(client, 'PATCH', f"/messages/{saved['id']}", user=member, body={'body': 'first draft'})
    assert unchanged['edited_at'] is None


@pytest.mark.parametrize('body', [{}, {'body': ''}, {'body': '   '}, {'body': 'x' * 2001}, {'body': None}])
def test_edits_are_validated_like_new_messages(client, factory, body):
    room, host, member = room_chat(factory)
    saved = send(client, member, room_id=room['id'])
    api(client, 'PATCH', f"/messages/{saved['id']}", user=member, body=body, expected=422)
    api(client, 'PATCH', f"/messages/{saved['id']}", user=member, body={'body': 'x' * 2000})


def test_only_the_sender_can_change_a_message(client, factory):
    room, host, member = room_chat(factory)
    saved = send(client, member, room_id=room['id'])
    for method in ('PATCH', 'DELETE'):
        assert attempt(client, method, saved['id'], host, {'body': 'hijacked'}) == (404, 'Message not found')
        assert attempt(client, method, 999999, member, {'body': 'x'}) == (404, 'Message not found')
        assert client.request(method, f"/api/v1/messages/{saved['id']}", json={'body': 'x'}).status_code == 401
    assert api(client, 'GET', '/messages', user=member, params={'room_id': room['id']})[0]['body'] == 'first draft'


def test_deleting_keeps_the_row_but_hides_and_erases_the_text(client, factory, db):
    room, host, member = room_chat(factory)
    other = send(client, host, room_id=room['id'])
    saved = send(client, member, room_id=room['id'])
    gone = api(client, 'DELETE', f"/messages/{saved['id']}", user=member)
    assert gone['deleted'] is True and gone['body'] == '' and 'deleted_at' not in gone
    shown = {item['id']: item for item in api(client, 'GET', '/messages', user=host, params={'room_id': room['id']})}
    assert shown[saved['id']]['deleted'] is True and shown[saved['id']]['body'] == ''
    assert shown[other['id']]['deleted'] is False and shown[other['id']]['body'] == 'first draft'
    with db() as session:
        row = session.get(MessageModel, saved['id'])
        assert row.deleted_at is not None and row.body == '[deleted]' and row.sender_id == member['id']
    # Deleting again is harmless, and a deleted message cannot be edited back to life
    assert api(client, 'DELETE', f"/messages/{saved['id']}", user=member)['deleted'] is True
    assert attempt(client, 'PATCH', saved['id'], member, {'body': 'back again'}) == (409, 'This message was deleted')
    [last] = [c for c in api(client, 'GET', '/messages/conversations', user=host) if c['room_id'] == room['id']]
    assert last['last_message']['id'] == saved['id'] and last['last_message']['deleted'] is True and last['last_message']['body'] == ''


def test_system_messages_cannot_be_changed(client, factory, db):
    room, host, member = room_chat(factory)
    private, outsider = factory.room(host, visibility='private'), factory.user()
    notices = []
    with db() as session:
        for target in (room, private):
            notice = MessageModel(room_id=target['id'], type='system', body='Room cancelled: rain')
            session.add(notice)
            session.commit()
            notices.append(notice.id)
    for method in ('PATCH', 'DELETE'):
        assert attempt(client, method, notices[0], member, {'body': 'x'}) == (403, 'System messages cannot be changed')
        assert attempt(client, method, notices[0], host, {'body': 'x'}) == (403, 'System messages cannot be changed')
        # People who cannot even see the room learn nothing about it
        assert attempt(client, method, notices[1], outsider, {'body': 'x'}) == (404, 'Room not found')
        assert attempt(client, method, notices[0], outsider, {'body': 'x'}) == (403, 'You do not have access to this chat')
    with db() as session:
        assert session.get(MessageModel, notices[0]).body == 'Room cancelled: rain'


def refuse_like_sending(client, factory, db, make_chat, break_chat):
    """After break_chat, edit and delete must fail exactly like sending does."""
    sender, target, message_target = make_chat()
    saved = send(client, sender, **message_target)
    break_chat(sender, target)
    response = client.post('/api/v1/messages', headers=sender['headers'], json={**message_target, 'body': 'again', 'client_request_id': str(uuid4())})
    expected = (response.status_code, response.json()['detail'])
    assert expected[0] in (403, 404, 409)
    assert attempt(client, 'PATCH', saved['id'], sender, {'body': 'changed'}) == expected
    assert attempt(client, 'DELETE', saved['id'], sender) == expected
    with db() as session:
        row = session.get(MessageModel, saved['id'])
        assert row.body == 'first draft' and row.deleted_at is None and row.edited_at is None
    return expected


def set_member(db, user, **changes):
    from models.membership import MembershipModel
    with db() as session:
        for row in session.query(MembershipModel).filter_by(user_id=user['id']):
            for key, value in changes.items():
                setattr(row, key, value)
        session.commit()


def test_direct_messages_follow_friendship_and_blocks(client, factory, db):
    def make():
        first, second = factory.user(), factory.user()
        factory.friend(first, second)
        return first, second, {'recipient_id': second['id']}
    assert refuse_like_sending(client, factory, db, make, lambda sender, other: set_member(db, sender, status='left', accepted=False)) == (403, 'You can only message accepted friends')
    assert refuse_like_sending(client, factory, db, make, lambda sender, other: set_member(db, sender, user_blocked_other='true')) == (403, 'Messaging is blocked')
    assert refuse_like_sending(client, factory, db, make, lambda sender, other: set_member(db, sender, other_blocked_user='yes')) == (403, 'Messaging is blocked')


@pytest.mark.parametrize('visibility,status,detail', [('public', 'left', 'You do not have access to this chat'),
                                                       ('public', 'removed', 'You do not have access to this chat'),
                                                       ('private', 'removed', 'Room not found')])
def test_room_messages_follow_room_membership(client, factory, db, visibility, status, detail):
    def make():
        room, host, member = room_chat(factory, visibility=visibility)
        return member, room, {'room_id': room['id']}
    code = 404 if detail == 'Room not found' else 403
    assert refuse_like_sending(client, factory, db, make, lambda sender, room: set_member(db, sender, status=status, accepted=False)) == (code, detail)


def test_room_messages_stop_changing_when_the_room_is_cancelled(client, factory, db):
    def make():
        room, host, member = room_chat(factory)
        return member, room, {'room_id': room['id']}
    def cancel(sender, room):
        from models.room import RoomModel
        with db() as session:
            session.get(RoomModel, room['id']).status = 'cancelled'
            session.commit()
    assert refuse_like_sending(client, factory, db, make, cancel) == (409, 'This room is cancelled')


def test_group_messages_follow_group_membership(client, factory, db):
    def make():
        owner, member = factory.user(), factory.user()
        group = factory.group(owner)
        factory.member(member, group=group)
        return member, group, {'group_id': group['id']}
    assert refuse_like_sending(client, factory, db, make, lambda sender, group: set_member(db, sender, status='removed', accepted=False)) == (403, 'You do not have access to this chat')


def test_edits_and_deletes_are_announced_to_the_chat_audience(configured_app, factory, db):
    room, host, member = room_chat(factory)
    outsider = factory.user()
    saved = factory.message(member, room=room)
    with db() as session:
        message = session.get(MessageModel, saved['id'])
        created = message_events(session, message)
        message.body, message.edited_at = 'new text', datetime.now(timezone.utc).replace(tzinfo=None)
        updated = message_events(session, message, 'message.updated')
        message.body, message.deleted_at = '[deleted]', datetime.now(timezone.utc).replace(tzinfo=None)
        deleted = message_events(session, message, 'message.deleted')
    assert created[0]['user_ids'] == updated[0]['user_ids'] == deleted[0]['user_ids'] == sorted({host['id'], member['id']})
    assert created[0]['scope'] == updated[0]['scope'] == deleted[0]['scope'] == {'type': 'room', 'id': room['id']}
    assert outsider['id'] not in updated[0]['user_ids']
    assert updated[0]['payload']['type'] == 'message.updated' and updated[0]['payload']['message']['body'] == 'new text'
    assert deleted[0]['payload']['type'] == 'message.deleted'
    assert deleted[0]['payload']['message']['deleted'] is True and deleted[0]['payload']['message']['body'] == ''


def test_live_sockets_receive_message_updated_and_deleted(network, factory):
    room, host, member = room_chat(factory)
    removed = factory.user()
    saved = send(network.client, member, room_id=room['id'])
    with user_socket(network, host) as watcher, user_socket(network, member) as own:
        api(network.client, 'PATCH', f"/messages/{saved['id']}", user=member, body={'body': 'edited live'})
        for socket in (watcher, own):
            event = receive(socket, 'message.updated')
            assert event['message']['id'] == saved['id'] and event['message']['body'] == 'edited live'
        api(network.client, 'DELETE', f"/messages/{saved['id']}", user=member)
        for socket in (watcher, own):
            event = receive(socket, 'message.deleted')
            assert event['message']['deleted'] is True and event['message']['body'] == ''
    # Someone who is not in the room hears nothing
    with user_socket(network, removed) as outsider:
        other = send(network.client, member, room_id=room['id'])
        api(network.client, 'PATCH', f"/messages/{other['id']}", user=member, body={'body': 'quiet edit'})
        deadline = time.monotonic() + .3
        while time.monotonic() < deadline:
            try:
                event = json.loads(outsider.recv(timeout=max(.01, deadline - time.monotonic())))
            except TimeoutError:
                break
            assert not event['type'].startswith('message.'), event


def test_simultaneous_edit_and_delete_end_in_a_consistent_state(client, factory, db):
    room, host, member = room_chat(factory)
    saved = send(client, member, room_id=room['id'])
    barrier = Barrier(2)
    def run(call):
        barrier.wait(timeout=5)
        return call()
    edit = lambda: client.patch(f"/api/v1/messages/{saved['id']}", headers=member['headers'], json={'body': 'racing edit'}).status_code
    delete = lambda: client.delete(f"/api/v1/messages/{saved['id']}", headers=member['headers']).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(run, [edit, delete]))
    assert statuses[1] == 200 and statuses[0] in (200, 409)
    with db() as session:
        row = session.get(MessageModel, saved['id'])
        assert row.deleted_at is not None and row.body == '[deleted]'
