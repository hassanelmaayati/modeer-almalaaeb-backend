import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config.environment import CORS_ORIGINS
from models.districts import DISTRICTS
from services.lobby import lobby_hub

router = APIRouter()

# Safety limits, the lobby is public so nobody has to log in to use it
MAX_CONNECTIONS = 500
MAX_CONNECTIONS_PER_IP = 10
MAX_MESSAGE_BYTES = 1024

# Close codes from the WebSocket standard
CLOSE_POLICY_VIOLATION = 1008
CLOSE_MESSAGE_TOO_BIG = 1009
CLOSE_TRY_AGAIN_LATER = 1013

# How many sockets are open right now, in total and for each client address
open_total = 0
open_by_ip: dict[str, int] = {}


# Browsers always send Origin on a WebSocket, so a page on another site is refused.
# A request with no Origin comes from a script or tool, not from a web page.
def origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    return origin is None or origin in CORS_ORIGINS


def client_ip(websocket: WebSocket) -> str:
    return websocket.client.host if websocket.client else "unknown"


# Handles one message from the client and returns what to answer, or None to ignore it
async def handle_message(websocket: WebSocket, raw) -> dict | None:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    action = data.get("action")

    if action == "subscribe":
        district = data.get("district")
        if district is not None and district not in DISTRICTS:
            return {
                "type": "error",
                "detail": f"district must be one of: {', '.join(DISTRICTS)}",
            }
        # Replaces the district watched before, so switching needs no reconnect
        await lobby_hub.subscribe(websocket, district)
        return {"type": "subscribed", "district": district}

    if action == "unsubscribe":
        await lobby_hub.unsubscribe(websocket)
        return {"type": "unsubscribed"}

    if action == "ping":
        return {"type": "pong"}

    # Anything else is ignored on purpose
    return None


@router.websocket("/ws/lobby")
async def lobby_socket(websocket: WebSocket):
    global open_total

    if not origin_allowed(websocket):
        await websocket.close(code=CLOSE_POLICY_VIOLATION)
        return

    # Counted before accepting, with nothing awaited in between, so parallel
    # connection attempts cannot all slip past the limits
    ip = client_ip(websocket)
    if open_total >= MAX_CONNECTIONS or open_by_ip.get(ip, 0) >= MAX_CONNECTIONS_PER_IP:
        await websocket.close(code=CLOSE_TRY_AGAIN_LATER)
        return
    open_total += 1
    open_by_ip[ip] = open_by_ip.get(ip, 0) + 1

    try:
        await websocket.accept()
        await lobby_hub.connect(websocket)

        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            # Text is expected; binary frames are treated the same way
            payload = message.get("text")
            if payload is None:
                payload = message.get("bytes")
            if payload is None:
                continue

            size = len(payload.encode("utf-8")) if isinstance(payload, str) else len(payload)
            if size > MAX_MESSAGE_BYTES:
                await websocket.close(code=CLOSE_MESSAGE_TOO_BIG)
                break

            reply = await handle_message(websocket, payload)
            if reply is not None:
                await websocket.send_json(reply)
    except (WebSocketDisconnect, RuntimeError):
        # The client left or the socket was already closed
        pass
    finally:
        await lobby_hub.disconnect(websocket)
        open_total -= 1
        open_by_ip[ip] -= 1
        if open_by_ip[ip] <= 0:
            del open_by_ip[ip]
