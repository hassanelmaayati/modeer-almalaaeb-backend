import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from controllers import lobby_ws
from main import app
from services.lobby import lobby_hub

URL = "/api/v1/ws/lobby"


@pytest.fixture
def client():
    return TestClient(app)


def test_subscribe_and_unsubscribe(client):
    with client.websocket_connect(URL) as ws:
        ws.send_json({"action": "subscribe", "district": "capital"})
        assert ws.receive_json() == {"type": "subscribed", "district": "capital"}
        assert lobby_hub.watcher_count("capital") == 1

        ws.send_json({"action": "unsubscribe"})
        assert ws.receive_json() == {"type": "unsubscribed"}
        assert lobby_hub.watcher_count("capital") == 0


def test_new_subscribe_replaces_the_old_district(client):
    with client.websocket_connect(URL) as ws:
        ws.send_json({"action": "subscribe", "district": "capital"})
        ws.receive_json()
        ws.send_json({"action": "subscribe", "district": "southern"})
        assert ws.receive_json()["district"] == "southern"

        assert lobby_hub.watcher_count("capital") == 0
        assert lobby_hub.watcher_count("southern") == 1


def test_ping_gets_pong(client):
    with client.websocket_connect(URL) as ws:
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_unknown_district_is_rejected_but_connection_stays(client):
    with client.websocket_connect(URL) as ws:
        for bad in ["mars", None, 5, ["capital"]]:
            ws.send_json({"action": "subscribe", "district": bad})
            assert ws.receive_json()["type"] == "error"
        assert lobby_hub.watcher_count("capital") == 0

        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_anything_else_is_ignored(client):
    with client.websocket_connect(URL) as ws:
        ws.send_text("not json")
        ws.send_text("[1, 2, 3]")
        ws.send_text('"subscribe"')
        ws.send_json({"action": "delete_everything"})
        ws.send_json({"no_action": True})
        ws.send_bytes(b"\x00\x01")
        # No answer was sent for any of them, so the next reply is the pong
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_oversized_message_closes_the_socket(client):
    with client.websocket_connect(URL) as ws:
        ws.send_text("x" * (lobby_ws.MAX_MESSAGE_BYTES + 1))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == lobby_ws.CLOSE_MESSAGE_TOO_BIG


def test_message_at_the_size_limit_is_allowed(client):
    with client.websocket_connect(URL) as ws:
        ws.send_text("x" * lobby_ws.MAX_MESSAGE_BYTES)
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_origin_must_be_allowed(client, monkeypatch):
    monkeypatch.setattr(lobby_ws, "CORS_ORIGINS", ["http://localhost:5173"])

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(URL, headers={"origin": "http://evil.example"}):
            pass
    assert closed.value.code == lobby_ws.CLOSE_POLICY_VIOLATION

    with client.websocket_connect(URL, headers={"origin": "http://localhost:5173"}) as ws:
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_request_without_origin_is_allowed(client, monkeypatch):
    monkeypatch.setattr(lobby_ws, "CORS_ORIGINS", ["http://localhost:5173"])
    with client.websocket_connect(URL) as ws:
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_total_connection_cap(client, monkeypatch):
    monkeypatch.setattr(lobby_ws, "MAX_CONNECTIONS", 1)
    with client.websocket_connect(URL):
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect(URL):
                pass
        assert closed.value.code == lobby_ws.CLOSE_TRY_AGAIN_LATER

    # Once the first one is gone there is room again
    with client.websocket_connect(URL) as ws:
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_per_address_connection_cap(client, monkeypatch):
    monkeypatch.setattr(lobby_ws, "MAX_CONNECTIONS_PER_IP", 2)
    with client.websocket_connect(URL), client.websocket_connect(URL):
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect(URL):
                pass
        assert closed.value.code == lobby_ws.CLOSE_TRY_AGAIN_LATER


def test_disconnect_cleans_up(client):
    with client.websocket_connect(URL) as ws:
        ws.send_json({"action": "subscribe", "district": "northern"})
        ws.receive_json()
        assert lobby_ws.open_total == 1

    assert lobby_ws.open_total == 0
    assert lobby_ws.open_by_ip == {}
    assert lobby_hub.connection_count() == 0
    assert lobby_hub.watcher_count("northern") == 0
