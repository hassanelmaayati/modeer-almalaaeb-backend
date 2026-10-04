import asyncio
import json

import pytest

from serializers.lobby import RoomRemovedEvent
from services import lobby


class Socket:
    def __init__(self, *, fail=False, slow=False, slow_close=False):
        self.sent, self.closed = [], False
        self.fail, self.slow, self.slow_close = fail, slow, slow_close
        self.started, self.delivered = asyncio.Event(), asyncio.Event()

    async def send_text(self, text):
        self.started.set()
        if self.fail:
            raise RuntimeError('Disconnected peer')
        if self.slow:
            await asyncio.Event().wait()
        self.sent.append(json.loads(text))
        self.delivered.set()

    async def close(self):
        self.closed = True
        if self.slow_close:
            await asyncio.Event().wait()


def event(room_id=1):
    return RoomRemovedEvent(room_id=room_id, reason='full')


def test_district_and_all_watchers_receive_once_and_can_switch():
    async def exercise():
        hub = lobby.InMemoryLobbyHub()
        capital, southern, all_districts = Socket(), Socket(), Socket()
        for socket, district in [(capital, 'capital'), (southern, 'southern'), (all_districts, None)]:
            await hub.connect(socket)
            await hub.subscribe(socket, district)
        await hub.subscribe(capital, 'capital')
        await hub.broadcast('capital', event(1))
        await hub.broadcast('southern', event(2))
        assert [row['room_id'] for row in capital.sent] == [1]
        assert [row['room_id'] for row in southern.sent] == [2]
        assert [row['room_id'] for row in all_districts.sent] == [1, 2]
        await hub.subscribe(all_districts, 'capital')
        await hub.broadcast('southern', event(3))
        assert [row['room_id'] for row in all_districts.sent] == [1, 2]
        assert hub.connection_count() == 3 and hub.watcher_count('capital') == 2
    asyncio.run(exercise())


def test_unsubscribed_and_disconnected_sockets_stop_receiving():
    async def exercise():
        hub, socket = lobby.InMemoryLobbyHub(), Socket()
        await hub.connect(socket)
        await hub.broadcast('capital', event())
        assert socket.sent == []
        await hub.subscribe(socket, None)
        await hub.unsubscribe(socket)
        await hub.broadcast('capital', event())
        assert socket.sent == [] and hub.connection_count() == 1
        await hub.subscribe(socket, 'capital')
        await hub.disconnect(socket)
        await hub.disconnect(socket)
        assert hub.connection_count() == 0 and hub.watcher_count('capital') == 0
    asyncio.run(exercise())


@pytest.mark.parametrize('district', ['mars', 3, ('capital',)])
def test_invalid_subscription_does_not_change_existing_watch(district):
    async def exercise():
        hub, socket = lobby.InMemoryLobbyHub(), Socket()
        await hub.subscribe(socket, 'capital')
        with pytest.raises(ValueError):
            await hub.subscribe(socket, district)
        with pytest.raises(ValueError):
            await hub.broadcast(district, event())
        await hub.broadcast('capital', event(7))
        assert socket.sent == [{'type': 'room_removed', 'room_id': 7, 'reason': 'full'}]
        assert hub.connection_count() == 1
    asyncio.run(exercise())


def test_failed_peer_is_closed_without_affecting_healthy_peer():
    async def exercise():
        hub, failed, healthy = lobby.InMemoryLobbyHub(), Socket(fail=True), Socket()
        for socket in (failed, healthy):
            await hub.subscribe(socket, 'capital')
        await hub.broadcast('capital', event(8))
        assert healthy.sent == [{'type': 'room_removed', 'room_id': 8, 'reason': 'full'}]
        assert failed.closed and hub.connection_count() == 1 and hub.watcher_count('capital') == 1
    asyncio.run(exercise())


def test_slow_sends_and_close_are_bounded_and_healthy_peer_is_prompt(monkeypatch):
    monkeypatch.setattr(lobby, 'SEND_TIMEOUT_SECONDS', .04)
    async def exercise():
        hub, slow, healthy = lobby.InMemoryLobbyHub(), Socket(slow=True, slow_close=True), Socket()
        for socket in (slow, healthy):
            await hub.subscribe(socket, 'capital')
        sends = [asyncio.create_task(hub.broadcast('capital', event(n))) for n in (1, 2)]
        await asyncio.wait_for(healthy.delivered.wait(), .2)
        await asyncio.wait_for(asyncio.gather(*sends), .4)
        assert {row['room_id'] for row in healthy.sent} == {1, 2}
        assert slow.closed and hub.connection_count() == 1 and hub.watcher_count('capital') == 1
    asyncio.run(exercise())


def test_subscription_change_during_broadcast_does_not_corrupt_watchers(monkeypatch):
    monkeypatch.setattr(lobby, 'SEND_TIMEOUT_SECONDS', .04)
    async def exercise():
        hub, slow, healthy = lobby.InMemoryLobbyHub(), Socket(slow=True), Socket()
        await hub.subscribe(slow, 'capital')
        await hub.subscribe(healthy, 'capital')
        task = asyncio.create_task(hub.broadcast('capital', event(1)))
        await slow.started.wait()
        await hub.subscribe(healthy, 'southern')
        await asyncio.wait_for(task, .4)
        await hub.broadcast('southern', event(2))
        assert [row['room_id'] for row in healthy.sent] == [1, 2]
        assert hub.watcher_count('capital') == 0 and hub.watcher_count('southern') == 1
    asyncio.run(exercise())


def test_broadcast_without_watchers_is_harmless():
    hub = lobby.InMemoryLobbyHub()
    asyncio.run(hub.broadcast('capital', event()))
    assert hub.connection_count() == 0 and hub.watcher_count('capital') == 0
