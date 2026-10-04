import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from models.room import RoomModel
from models.notification import NotificationModel
from services import lifecycle, realtime, lobby_events
from tests.lib import future
from tests.test_realtime import user_socket, receive
from tests.test_lobby_ws import lobby


def test_lifecycle_cutoff_start_complete_are_persisted_once_and_notify_members(factory,db):
    host,member=factory.user(),factory.user()
    now=datetime.now(timezone.utc)
    room=factory.room(host,starts_at=now+timedelta(minutes=20),ends_at=now+timedelta(minutes=80))
    factory.member(member,room=room)
    seen=set();private=[]
    with db() as session: before=lifecycle.run_lifecycle_tick(session,seen,now=now,private_events=private)
    assert before==[] and private==[]
    with db() as session: cutoff=lifecycle.run_lifecycle_tick(session,seen,now=now+timedelta(minutes=5),private_events=private)
    assert len(cutoff)==1 and cutoff[0][1].reason=='past_cutoff'
    with db() as session:
        assert session.get(RoomModel,room['id']).status=='open'
        assert lifecycle.run_lifecycle_tick(session,seen,now=now+timedelta(minutes=6),private_events=private)==[]
    with db() as session: lifecycle.run_lifecycle_tick(session,seen,now=now+timedelta(minutes=20),private_events=private)
    with db() as session:
        row=session.get(RoomModel,room['id']);assert row.status=='started' and row.revision==1
        assert session.query(NotificationModel).filter_by(user_id=member['id'],kind='room.started').count()==1
    with db() as session: lifecycle.run_lifecycle_tick(session,seen,now=now+timedelta(minutes=80),private_events=private)
    with db() as session:
        row=session.get(RoomModel,room['id']);assert row.status=='completed' and row.revision==2
        assert session.query(NotificationModel).filter_by(user_id=member['id'],kind='room.completed').count()==1
        lifecycle.run_lifecycle_tick(session,seen,now=now+timedelta(minutes=81),private_events=private)
    with db() as session: assert session.query(NotificationModel).count()==2


@pytest.mark.parametrize('visibility',['private','group'])
def test_private_lifecycle_changes_never_enter_public_lobby(factory,db,visibility):
    host,member=factory.user(),factory.user()
    group=factory.group(host) if visibility=='group' else None
    room=factory.room(host,visibility=visibility,group_id=group['id'] if group else None,starts_at=future(-1),ends_at=future(1))
    factory.member(member,room=room)
    private=[]
    with db() as session: events=lifecycle.run_lifecycle_tick(session,set(),private_events=private)
    assert events==[] and any(event['payload']['type']=='room.updated' for event in private)
    with db() as session: assert session.get(RoomModel,room['id']).status=='started'


def test_failed_tick_rolls_back_changes_and_does_not_poison_announcements(factory,db):
    host=factory.user();room=factory.room(host,starts_at=future(-1),ends_at=future(1))
    seen=set()
    class FailingSession:
        def __init__(self): self.session=db()
        def __getattr__(self,name): return getattr(self.session,name)
        def commit(self): raise RuntimeError('database commit failed')
        def close(self): self.session.close()
    with pytest.raises(RuntimeError,match='commit failed'): lifecycle._tick_in_thread(FailingSession,seen)
    assert seen==set()
    with db() as session:
        assert session.get(RoomModel,room['id']).status=='open'
        assert session.query(NotificationModel).count()==0
    events,private=lifecycle._tick_in_thread(db,seen)
    assert len(events)==1 and events[0][1].reason=='started'
    with db() as session: assert session.get(RoomModel,room['id']).status=='started'


def test_lifecycle_transaction_delivers_real_lobby_and_personal_notification(network,factory,db):
    host,member=factory.user(),factory.user()
    room=factory.room(host,starts_at=future(-1),ends_at=future(1))
    factory.member(member,room=room)
    with lobby(network) as public,user_socket(network,member) as personal:
        public_events,private_events=lifecycle._tick_in_thread(db,set())
        network.run(lobby_events.send_events(public_events))
        network.run(realtime.send_events(private_events))
        removal=receive(public,'room_removed')
        assert removal['room_id']==room['id'] and removal['reason']=='started'
        notice=receive(personal,'notification.created')['notification']
        assert notice['kind']=='room.started' and notice['target']=={'type':'room','id':room['id']}
        with db() as session: assert session.get(RoomModel,room['id']).status=='started'


def test_worker_uses_isolated_factory_and_cancels_without_sleep_driven_assertions(factory,db):
    host=factory.user();room=factory.room(host,starts_at=future(-1),ends_at=future(1))
    async def exercise():
        completed=asyncio.Event()
        original=lifecycle._tick_in_thread
        def tick(session_factory,announced):
            result=original(session_factory,announced)
            loop.call_soon_threadsafe(completed.set)
            return result
        loop=asyncio.get_running_loop()
        with patch.object(lifecycle,'_tick_in_thread',tick):
            task=asyncio.create_task(lifecycle.lifecycle_loop(interval=60,session_factory=db))
            await asyncio.wait_for(completed.wait(),2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(exercise())
    with db() as session: assert session.get(RoomModel,room['id']).status=='started'
