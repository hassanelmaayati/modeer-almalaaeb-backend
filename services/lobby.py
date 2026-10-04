import asyncio
import logging

from models.districts import DISTRICTS

logger = logging.getLogger(__name__)
SEND_TIMEOUT_SECONDS = 5


class InMemoryLobbyHub:
    """Public district subscriptions in one process; None subscribes to all districts."""
    def __init__(self):
        self._watching = {}
        self._locks = {}

    async def connect(self, socket):
        self._watching.setdefault(socket, set())
        self._locks.setdefault(socket, asyncio.Lock())

    async def subscribe(self, socket, district=None):
        if district is not None and district not in DISTRICTS:
            raise ValueError("Unknown district")
        await self.connect(socket)
        self._watching[socket] = set(DISTRICTS) if district is None else {district}

    async def unsubscribe(self, socket):
        if socket in self._watching:
            self._watching[socket] = set()

    async def disconnect(self, socket):
        self._watching.pop(socket, None)
        self._locks.pop(socket, None)

    async def broadcast(self, district, event):
        if district not in DISTRICTS:
            raise ValueError("Unknown district")
        message = event.model_dump_json()
        sockets = [socket for socket, districts in self._watching.items() if district in districts]
        await asyncio.gather(*(self._send(socket, message) for socket in sockets))

    async def _send(self, socket, message):
        async def write():
            async with self._locks[socket]:
                if socket in self._watching:
                    await socket.send_text(message)
        try:
            await asyncio.wait_for(write(), SEND_TIMEOUT_SECONDS)
        except Exception:
            logger.info("Dropping an unreachable lobby connection")
            await self.disconnect(socket)
            try:
                await asyncio.wait_for(socket.close(), SEND_TIMEOUT_SECONDS)
            except Exception:
                pass

    def connection_count(self):
        return len(self._watching)

    def watcher_count(self, district):
        if district is not None and district not in DISTRICTS:
            raise ValueError("Unknown district")
        return sum((set(DISTRICTS) <= watching) if district is None else district in watching
                   for watching in self._watching.values())


LobbyHub = InMemoryLobbyHub
lobby_hub = InMemoryLobbyHub()
