import pytest
from sqlalchemy.exc import IntegrityError

from database import get_db
from models.message import MessageModel
from models.notification import NotificationModel
from models.room import RoomModel
from services import lobby_events, realtime
from services.messages import message_events
from tests.lib import api, room_body
from tests.test_lobby_ws import lobby
from tests.test_realtime import assert_no_message, receive, user_socket


def test_rejected_http_commands_emit_nothing_and_leave_rows_unchanged(network, factory, db):
    owner, member, outsider = [factory.user() for _ in range(3)]
    room = factory.room(owner)
    factory.member(member, room=room)
    with lobby(network) as public, user_socket(network, member) as personal:
        path = f"/rooms/{room['id']}"
        api(network.client, 'PUT', path, user=outsider, body={'revision': 0, 'title': 'Denied'}, expected=403)
        api(network.client, 'PUT', path, user=owner, body={'revision': 10, 'title': 'Stale'}, expected=409)
        api(network.client, 'PUT', path, user=owner, body={'revision': 0, 'district': 'mars'}, expected=422)
        for socket in (public, personal):
            with pytest.raises(TimeoutError):
                socket.recv(timeout=.1)
    with db() as session:
        row = session.get(RoomModel, room['id'])
        assert row.title == room['title'] and row.revision == 0
        assert session.query(NotificationModel).count() == 0


def test_failed_commit_rolls_back_room_and_notices_without_publishing(network, configured_app, factory, db):
    owner, member = factory.user(), factory.user()
    room = factory.room(owner)
    factory.member(member, room=room)
    previous = configured_app.dependency_overrides[get_db]
    def rejected_session():
        with db() as session:
            def reject_commit():
                raise IntegrityError('COMMIT', {}, RuntimeError('Injected storage failure'))
            session.commit = reject_commit
            yield session
    with lobby(network) as public, user_socket(network, member) as personal:
        configured_app.dependency_overrides[get_db] = rejected_session
        try:
            api(network.client, 'PUT', f"/rooms/{room['id']}", user=owner, body={'revision': 0, 'title': 'Never committed'}, expected=409)
        finally:
            configured_app.dependency_overrides[get_db] = previous
        for socket in (public, personal):
            with pytest.raises(TimeoutError):
                socket.recv(timeout=.1)
    with db() as session:
        row = session.get(RoomModel, room['id'])
        assert row.title == room['title'] and row.revision == 0
        assert session.query(NotificationModel).count() == 0


@pytest.mark.parametrize('visibility', ['private', 'group'])
def test_private_room_updates_notify_admitted_members_and_never_public_lobby(network, factory, db, visibility):
    owner, member, outsider = [factory.user() for _ in range(3)]
    group = factory.group(owner) if visibility == 'group' else None
    room = factory.room(owner, visibility=visibility, group_id=group['id'] if group else None)
    factory.member(member, room=room)
    with lobby(network) as public, user_socket(network, member) as admitted, user_socket(network, outsider) as outside:
        updated = api(network.client, 'PUT', f"/rooms/{room['id']}", user=owner, body={'revision': 0, 'description': 'Updated activity'})
        event = receive(admitted, 'room.updated')
        assert event == {'type': 'room.updated', 'room_id': room['id']}
        notice = receive(admitted, 'notification.created')['notification']
        assert notice['target'] == {'type': 'room', 'id': room['id']} and notice['kind'] == 'room.updated'
        for socket in (public, outside):
            with pytest.raises(TimeoutError):
                socket.recv(timeout=.1)
        assert updated['revision'] == 1
    with db() as session:
        assert session.get(RoomModel, room['id']).description == 'Updated activity'
        assert session.query(NotificationModel).filter_by(user_id=member['id']).count() == 1


def test_broken_lobby_transport_does_not_lose_committed_update_or_private_alert(network, factory, db, monkeypatch):
    owner, member = factory.user(), factory.user()
    room = factory.room(owner)
    factory.member(member, room=room)
    async def broken_broadcast(*args):
        raise RuntimeError('Public transport unavailable')
    monkeypatch.setattr(lobby_events.lobby_hub, 'broadcast', broken_broadcast)
    with user_socket(network, member) as personal:
        updated = api(network.client, 'PUT', f"/rooms/{room['id']}", user=owner, body={'revision': 0, 'title': 'Committed despite transport failure'})
        assert receive(personal, 'room.updated')['room_id'] == room['id']
        assert receive(personal, 'notification.created')['notification']['kind'] == 'room.updated'
    with db() as session:
        row = session.get(RoomModel, room['id'])
        assert row.title == updated['title'] and row.revision == 1
        assert session.query(NotificationModel).count() == 1


def test_broken_event_projection_still_commits_http_creation(network, factory, db, monkeypatch):
    owner, sport = factory.user(), factory.sport()
    def broken_projection(*args):
        raise RuntimeError('Public projection unavailable')
    monkeypatch.setattr(lobby_events, 'events_for_change', broken_projection)
    with lobby(network) as socket:
        room = api(network.client, 'POST', '/rooms', user=owner, body=room_body(sport['id']), expected=201)
        with pytest.raises(TimeoutError):
            socket.recv(timeout=.1)
    with db() as session:
        assert session.get(RoomModel, room['id']).status == 'open'


@pytest.mark.parametrize('kind', ['room', 'group'])
def test_prepared_message_event_rechecks_access_after_membership_revocation(network, factory, db, kind):
    owner, member = factory.user(), factory.user()
    target = factory.room(owner, visibility='private') if kind == 'room' else factory.group(owner)
    factory.member(member, **{kind: target})
    saved = factory.message(owner, **{kind: target})
    with db() as session:
        prepared = message_events(session, session.get(MessageModel, saved['id']))
    with user_socket(network, member) as removed, user_socket(network, owner) as own:
        api(network.client, 'PATCH', f"/{kind}s/{target['id']}/members/{member['id']}", user=owner, body={'status': 'removed'})
        network.run(realtime.send_events(prepared))
        assert receive(own, 'message.created')['message']['id'] == saved['id']
        assert_no_message(removed)
        api(network.client, 'GET', '/messages', user=member, params={kind+'_id': target['id']}, expected=404 if kind == 'room' else 403)
