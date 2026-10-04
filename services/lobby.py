import asyncio
import logging
from abc import ABC, abstractmethod

from fastapi import WebSocket
from pydantic import BaseModel

from models.districts import DISTRICTS

logger = logging.getLogger(__name__)

# A client that cannot take a message in this time is treated as dead
SEND_TIMEOUT_SECONDS = 5


'''
What the rest of the app may use to talk to lobby sockets.
Callers only know this interface, so the in-memory hub below can later be
replaced by a Redis version that also reaches sockets on other workers.
Every method is async so a network-based version fits without changes.
A socket watches one district at a time. The socket route accepts and closes
the connection itself, the hub only keeps track of who gets which message.
'''
class LobbyHub(ABC):
    # Starts tracking a new socket (not watching any district yet)
    @abstractmethod
    async def connect(self, socket: WebSocket) -> None: ...

    # Makes the socket watch a district, leaving the one it watched before
    @abstractmethod
    async def subscribe(self, socket: WebSocket, district: str) -> None: ...

    # Stops the socket watching its district but keeps it tracked
    @abstractmethod
    async def unsubscribe(self, socket: WebSocket) -> None: ...

    # Forgets the socket completely (it closed or died)
    @abstractmethod
    async def disconnect(self, socket: WebSocket) -> None: ...

    # Sends an event to everyone watching the district
    @abstractmethod
    async def broadcast(self, district: str, event: BaseModel) -> None: ...


def _check_district(district: str) -> None:
    if district not in DISTRICTS:
        raise ValueError(f"district must be one of: {', '.join(DISTRICTS)}")


# Keeps everything in this process, so it only works with a single worker
class InMemoryLobbyHub(LobbyHub):
    def __init__(self):
        # district -> sockets watching it
        self._watchers: dict[str, set[WebSocket]] = {d: set() for d in DISTRICTS}
        # every tracked socket -> the district it watches (None if none)
        self._watching: dict[WebSocket, str | None] = {}

    async def connect(self, socket: WebSocket) -> None:
        self._watching.setdefault(socket, None)

    async def subscribe(self, socket: WebSocket, district: str) -> None:
        _check_district(district)
        # Only the district changes: no reconnect, and the old district is left first
        await self.unsubscribe(socket)
        self._watching[socket] = district
        self._watchers[district].add(socket)

    async def unsubscribe(self, socket: WebSocket) -> None:
        district = self._watching.get(socket)
        if district is not None:
            self._watchers[district].discard(socket)
            self._watching[socket] = None

    async def disconnect(self, socket: WebSocket) -> None:
        await self.unsubscribe(socket)
        self._watching.pop(socket, None)

    async def broadcast(self, district: str, event: BaseModel) -> None:
        _check_district(district)
        # Copy the set because it can change while we wait on slow sockets
        sockets = list(self._watchers[district])
        if not sockets:
            return

        # Turn the event into JSON once, not once per socket
        message = event.model_dump_json()
        results = await asyncio.gather(*(self._send(s, message) for s in sockets))

        # A failed send means the socket is dead: stop tracking it and close it
        for socket, delivered in zip(sockets, results):
            if not delivered:
                await self.disconnect(socket)
                await self._close_quietly(socket)

    async def _send(self, socket: WebSocket, message: str) -> bool:
        try:
            await asyncio.wait_for(socket.send_text(message), SEND_TIMEOUT_SECONDS)
            return True
        except Exception as error:
            # One bad socket must never stop the others from getting the message
            logger.info("Dropping lobby socket after failed send: %r", error)
            return False

    async def _close_quietly(self, socket: WebSocket) -> None:
        try:
            await asyncio.wait_for(socket.close(), SEND_TIMEOUT_SECONDS)
        except Exception:
            pass  # already closed or unreachable, nothing left to do

    # Counts for tests and for limiting connections later
    def connection_count(self) -> int:
        return len(self._watching)

    def watcher_count(self, district: str) -> int:
        _check_district(district)
        return len(self._watchers[district])


# The one hub the app shares. Import this, not the class.
lobby_hub: LobbyHub = InMemoryLobbyHub()
