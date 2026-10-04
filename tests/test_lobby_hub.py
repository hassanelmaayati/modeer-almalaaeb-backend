import asyncio
import json

import pytest

from serializers.lobby import RoomRemovedEvent
from services import lobby
from services.lobby import InMemoryLobbyHub


# Stands in for a WebSocket: records messages, and can fail or hang on send
class FakeSocket:
    def __init__(self, fail=False, hang=False):
        self.sent = []
        self.fail = fail
        self.hang = hang
        self.closed = False

    async def send_text(self, message):
        if self.fail:
            raise RuntimeError("socket is closed")
        if self.hang:
            await asyncio.sleep(60)
        self.sent.append(json.loads(message))

    async def close(self):
        self.closed = True


def event(room_id=1):
    return RoomRemovedEvent(room_id=room_id, reason="full")


def run(coro):
    return asyncio.run(coro)


def test_broadcast_reaches_only_that_district():
    async def scenario():
        hub = InMemoryLobbyHub()
        capital, muharraq = FakeSocket(), FakeSocket()
        for socket, district in [(capital, "capital"), (muharraq, "muharraq")]:
            await hub.connect(socket)
            await hub.subscribe(socket, district)

        await hub.broadcast("capital", event(7))
        assert capital.sent == [{"type": "room_removed", "room_id": 7, "reason": "full"}]
        assert muharraq.sent == []

    run(scenario())


def test_connected_but_unsubscribed_socket_gets_nothing():
    async def scenario():
        hub = InMemoryLobbyHub()
        socket = FakeSocket()
        await hub.connect(socket)
        await hub.broadcast("capital", event())
        assert socket.sent == []
        assert hub.connection_count() == 1

    run(scenario())


def test_subscribe_switches_district_without_reconnecting():
    async def scenario():
        hub = InMemoryLobbyHub()
        socket = FakeSocket()
        await hub.connect(socket)
        await hub.subscribe(socket, "capital")
        await hub.subscribe(socket, "southern")

        assert hub.watcher_count("capital") == 0
        assert hub.watcher_count("southern") == 1
        assert hub.connection_count() == 1

        await hub.broadcast("capital", event(1))
        await hub.broadcast("southern", event(2))
        assert [m["room_id"] for m in socket.sent] == [2]

    run(scenario())


def test_subscribe_twice_to_same_district_counts_once():
    async def scenario():
        hub = InMemoryLobbyHub()
        socket = FakeSocket()
        await hub.subscribe(socket, "capital")
        await hub.subscribe(socket, "capital")
        await hub.broadcast("capital", event())
        assert len(socket.sent) == 1

    run(scenario())


def test_unsubscribe_stops_messages_but_keeps_the_socket():
    async def scenario():
        hub = InMemoryLobbyHub()
        socket = FakeSocket()
        await hub.connect(socket)
        await hub.subscribe(socket, "northern")
        await hub.unsubscribe(socket)
        await hub.broadcast("northern", event())

        assert socket.sent == []
        assert hub.connection_count() == 1
        assert hub.watcher_count("northern") == 0

    run(scenario())


def test_disconnect_forgets_the_socket():
    async def scenario():
        hub = InMemoryLobbyHub()
        socket = FakeSocket()
        await hub.connect(socket)
        await hub.subscribe(socket, "capital")
        await hub.disconnect(socket)
        await hub.disconnect(socket)  # a second call is harmless

        assert hub.connection_count() == 0
        assert hub.watcher_count("capital") == 0

    run(scenario())


def test_dead_socket_is_removed_and_others_still_receive():
    async def scenario():
        hub = InMemoryLobbyHub()
        dead, alive = FakeSocket(fail=True), FakeSocket()
        for socket in (dead, alive):
            await hub.connect(socket)
            await hub.subscribe(socket, "capital")

        await hub.broadcast("capital", event())

        assert len(alive.sent) == 1
        assert dead.closed
        assert hub.watcher_count("capital") == 1
        assert hub.connection_count() == 1

    run(scenario())


def test_hanging_socket_times_out_and_is_removed(monkeypatch):
    monkeypatch.setattr(lobby, "SEND_TIMEOUT_SECONDS", 0.05)

    async def scenario():
        hub = InMemoryLobbyHub()
        slow, alive = FakeSocket(hang=True), FakeSocket()
        for socket in (slow, alive):
            await hub.subscribe(socket, "capital")

        await hub.broadcast("capital", event())

        assert len(alive.sent) == 1
        assert hub.watcher_count("capital") == 1

    run(scenario())


def test_broadcast_with_no_watchers_does_nothing():
    run(InMemoryLobbyHub().broadcast("capital", event()))


def test_unknown_district_is_rejected():
    async def scenario():
        hub = InMemoryLobbyHub()
        with pytest.raises(ValueError):
            await hub.subscribe(FakeSocket(), "mars")
        with pytest.raises(ValueError):
            await hub.broadcast("mars", event())

    run(scenario())
