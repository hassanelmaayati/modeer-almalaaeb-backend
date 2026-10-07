from datetime import datetime, timedelta, timezone

from sqlalchemy import event

from models.notification import NotificationModel
from serializers.lobby import LobbyRoomSchema
from tests.lib import api, future


def aware(value):
    parsed = datetime.fromisoformat(value)
    assert parsed.utcoffset() == timedelta(0), value
    return parsed


def bahrain_session_timezone(db):
    # Make the database answer in +03:00, like a server not set to UTC
    engine = db.kw['bind']
    @event.listens_for(engine, 'connect')
    def set_timezone(dbapi_connection, record):
        cursor = dbapi_connection.cursor()
        cursor.execute("SET TIME ZONE 'Asia/Bahrain'")
        cursor.close()
    engine.dispose()


def test_every_response_timestamp_is_utc_whatever_the_database_timezone(client, factory, db):
    bahrain_session_timezone(db)
    host, player = factory.user(), factory.user()
    now = datetime.now(timezone.utc)
    # created_at is stamped by the application in UTC, not by the database clock
    assert abs(aware(api(client, 'GET', f"/users/{host['id']}")['created_at']) - now) < timedelta(minutes=2)
    assert abs(aware(api(client, 'GET', '/users/me', user=host)['created_at']) - now) < timedelta(minutes=2)

    room = factory.room(host, status='cancelled', cancellation_reason='Rain', cancelled_at=future(), starts_at=future(30), ends_at=future(31))
    shown = api(client, 'GET', f"/rooms/{room['id']}")
    assert abs(aware(shown['starts_at']) - future(30)) < timedelta(minutes=2)
    aware(shown['ends_at']), aware(shown['cancelled_at'])

    chat = factory.room(host)
    factory.member(player, room=chat)
    factory.message(host, room=chat)
    [message] = api(client, 'GET', '/messages', user=player, params={'room_id': chat['id']})
    assert abs(aware(message['created_at']) - now) < timedelta(minutes=2)

    with db() as session:
        session.add(NotificationModel(user_id=host['id'], kind='room.update', target={'type': 'room', 'id': chat['id']}, text='Updated'))
        session.commit()
    [notice] = api(client, 'GET', '/notifications', user=host)['items']
    assert abs(aware(notice['created_at']) - now) < timedelta(minutes=2)

    cup = factory.cup(host)
    assert abs(aware(api(client, 'GET', f"/cups/{cup['id']}", user=host)['created_at']) - now) < timedelta(minutes=2)


def test_lobby_events_carry_utc_start_times():
    bahrain = timezone(timedelta(hours=3))
    room = LobbyRoomSchema(id=1, title='t', sport_id=1, sport_name='s', district='capital', area='Manama',
                           starts_at=datetime(2030, 1, 1, 18, 0, tzinfo=bahrain), capacity=4, slots_left=2,
                           difficulty='beginners', revision=0)
    assert room.starts_at.utcoffset() == timedelta(0) and room.starts_at.hour == 15
    assert '2030-01-01T15:00:00' in room.model_dump_json()
    naive = LobbyRoomSchema(id=1, title='t', sport_id=1, sport_name='s', district='capital', area='Manama',
                            starts_at=datetime(2030, 1, 1, 15, 0), capacity=4, slots_left=2, difficulty='beginners', revision=0)
    assert naive.starts_at == room.starts_at
