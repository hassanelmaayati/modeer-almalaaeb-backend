import asyncio
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field

from fastapi import BackgroundTasks, HTTPException, WebSocket
from database import SessionLocal
from dependencies.get_current_user import decode_access_token, user_from_token
from services.chat_access import group_user_ids, require_chat_access, room_user_ids

logger = logging.getLogger(__name__)
session_factory = SessionLocal
TICKET_TTL_SECONDS = 30
SEND_TIMEOUT_SECONDS = 5
MAX_CONNECTIONS = 500
MAX_CONNECTIONS_PER_IP = 10
MAX_MESSAGE_BYTES = 1024
MAX_TICKETS = 1000


class SocketTickets:
    """Single-use tickets; neither token nor ticket is written to logs."""
    def __init__(self):
        self.values = {}
        self.lock = threading.Lock()

    def issue(self, token: str) -> str:
        with self.lock:
            now = time.monotonic()
            self.values = {key: value for key, value in self.values.items() if value[1] > now}
            if len(self.values) >= MAX_TICKETS:
                raise HTTPException(status_code=503, detail="Too many pending socket connections")
            ticket = secrets.token_urlsafe(32)
            self.values[ticket] = (token, now + TICKET_TTL_SECONDS)
            return ticket

    def consume(self, ticket: str) -> str | None:
        with self.lock:
            value = self.values.pop(ticket, None)
        return value[0] if value and value[1] > time.monotonic() else None

    def clear(self):
        with self.lock:
            self.values.clear()


tickets = SocketTickets()


@dataclass(eq=False)
class Connection:
    socket: WebSocket
    user_id: int
    token: str
    token_version: int
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RealtimeHub:
    """Process-local user channels; deploy with one serving worker."""
    def __init__(self):
        self.connections = {}
        self.by_ip = {}

    def reserve(self, ip: str) -> bool:
        if sum(self.by_ip.values()) >= MAX_CONNECTIONS or self.by_ip.get(ip, 0) >= MAX_CONNECTIONS_PER_IP:
            return False
        self.by_ip[ip] = self.by_ip.get(ip, 0) + 1
        return True

    def release(self, ip: str):
        remaining = self.by_ip.get(ip, 0) - 1
        if remaining > 0:
            self.by_ip[ip] = remaining
        else:
            self.by_ip.pop(ip, None)

    def connect(self, socket: WebSocket, user_id: int, token: str) -> Connection:
        connection = Connection(socket, user_id, token, decode_access_token(token)["ver"])
        self.connections[socket] = connection
        return connection

    async def send(self, connection: Connection, payload: dict):
        async def write():
            async with connection.lock:
                await connection.socket.send_json(payload)
        try:
            await asyncio.wait_for(write(), SEND_TIMEOUT_SECONDS)
        except Exception:
            await self.disconnect(connection.socket, close=True)

    async def disconnect(self, socket: WebSocket, close: bool = False, code: int = 1008):
        self.connections.pop(socket, None)
        if close:
            try:
                await asyncio.wait_for(socket.close(code=code), SEND_TIMEOUT_SECONDS)
            except Exception:
                pass

    async def close_user(self, user_id: int, token_version: int | None = None):
        await asyncio.gather(*(self.disconnect(item.socket, close=True) for item in list(self.connections.values())
                               if item.user_id == user_id and (token_version is None or item.token_version <= token_version)))

    async def close(self):
        await asyncio.gather(*(self.disconnect(item.socket, close=True, code=1001) for item in list(self.connections.values())))
        tickets.clear()


realtime_hub = RealtimeHub()


def user_event(user_ids, payload: dict, scope: dict | None = None) -> dict:
    """Internal envelope; only payload is sent to the browser."""
    return {"user_ids": sorted(set(user_ids)), "payload": payload, "scope": scope}


def _allowed_deliveries(events: list[dict], connections: list[Connection]):
    deliveries, revoked = [], set()
    with session_factory() as db:
        for connection in connections:
            try:
                user_from_token(db, connection.token)
            except HTTPException:
                revoked.add(connection)
                continue
            for event in events:
                if connection.user_id not in event["user_ids"]:
                    continue
                try:
                    if event.get("scope"):
                        require_chat_access(db, connection.user_id, event["scope"])
                except HTTPException:
                    continue
                deliveries.append((connection, event["payload"]))
    return deliveries, revoked


async def send_events(events: list[dict]):
    """Best effort after commit: fresh token/access checks, bounded socket writes."""
    if not events or not realtime_hub.connections:
        return
    try:
        deliveries, revoked = await asyncio.to_thread(_allowed_deliveries, events, list(realtime_hub.connections.values()))
        await asyncio.gather(*(realtime_hub.disconnect(item.socket, close=True) for item in revoked))
        await asyncio.gather(*(realtime_hub.send(connection, payload) for connection, payload in deliveries if connection.socket in realtime_hub.connections))
    except Exception:
        logger.exception("Realtime event delivery failed")


def queue_events(background_tasks: BackgroundTasks, events: list[dict]):
    """Call only after a successful commit; never retain a request DB session."""
    if events:
        background_tasks.add_task(send_events, events)
