import asyncio
import json
import time
from fastapi import APIRouter, Depends, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials
from config.environment import CORS_ORIGINS
from dependencies.get_current_user import decode_access_token, get_current_user, http_bearer, user_from_token
from models.user import UserModel
from services import realtime

router = APIRouter(tags=["Realtime"])
AUTH_CHECK_SECONDS = 30


def socket_identity(token: str):
    with realtime.session_factory() as db:
        user = user_from_token(db, token)
        return user.id, decode_access_token(token)["exp"]


@router.post("/socket-ticket")
def socket_ticket(response: Response, current_user: UserModel = Depends(get_current_user), token: HTTPAuthorizationCredentials = Depends(http_bearer)):
    response.headers["Cache-Control"] = "no-store"
    return {"ticket": realtime.tickets.issue(token.credentials), "expires_in": realtime.TICKET_TTL_SECONDS}


@router.websocket("/ws")
async def user_socket(websocket: WebSocket, ticket: str = ""):
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in CORS_ORIGINS:
        await websocket.close(code=1008)
        return
    token = realtime.tickets.consume(ticket)
    if not token:
        await websocket.close(code=1008)
        return
    ip = websocket.client.host if websocket.client else "unknown"
    if not realtime.realtime_hub.reserve(ip):
        await websocket.close(code=1013)
        return
    connection = None
    try:
        user_id, expires = await asyncio.to_thread(socket_identity, token)
        await websocket.accept()
        connection = realtime.realtime_hub.connect(websocket, user_id, token)
        await realtime.realtime_hub.send(connection, {"type": "ready"})
        while websocket in realtime.realtime_hub.connections:
            try:
                frame = await asyncio.wait_for(websocket.receive(), min(AUTH_CHECK_SECONDS, max(expires - time.time(), 0.01)))
            except asyncio.TimeoutError:
                await asyncio.to_thread(socket_identity, token)
                continue
            if frame["type"] == "websocket.disconnect":
                break
            await asyncio.to_thread(socket_identity, token)
            raw = frame.get("text")
            size = len(raw.encode("utf-8")) if raw is not None else len(frame.get("bytes") or b"")
            if size > realtime.MAX_MESSAGE_BYTES:
                await websocket.close(code=1009)
                break
            if raw is None:
                await realtime.realtime_hub.send(connection, {"type": "error", "detail": "Send a JSON text message"})
                continue
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                data = None
            response = {"type": "pong"} if isinstance(data, dict) and data.get("action") == "ping" else {"type": "error", "detail": "Only ping is supported; use REST to make changes"}
            await realtime.realtime_hub.send(connection, response)
    except HTTPException:
        if connection:
            await realtime.realtime_hub.disconnect(websocket, close=True)
        else:
            await websocket.close(code=1008)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await realtime.realtime_hub.disconnect(websocket)
        realtime.realtime_hub.release(ip)
