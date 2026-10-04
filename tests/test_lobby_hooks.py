import pytest
from fastapi.testclient import TestClient

from services import lobby_events
from services.lobby import LobbyHub
from tests.lib import login


# Records what the controllers asked the lobby to send
class RecordingHub(LobbyHub):
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def connect(self, socket): ...
    async def subscribe(self, socket, district): ...
    async def unsubscribe(self, socket): ...
    async def disconnect(self, socket): ...

    async def broadcast(self, district, event):
        if self.fail:
            raise RuntimeError("hub is down")
        self.sent.append((district, event))

    def summary(self):
        return [(district, event.type) for district, event in self.sent]

    def clear(self):
        self.sent.clear()


@pytest.fixture
def hub(monkeypatch):
    recording = RecordingHub()
    monkeypatch.setattr(lobby_events, "lobby_hub", recording)
    return recording


def when(hours=24):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def room_body(**overrides):
    # Swimming accepts any capacity, so the number of places is easy to control
    body = {
        "sport_id": 4,
        "title": "Hook room",
        "starts_at": when(24),
        "ends_at": when(25),
        "capacity": 4,
        "district": "capital",
        "area": "Manama",
        "venue_notes": "Pool 7, side door",
    }
    body.update(overrides)
    return body


def make_room(test_app, headers, **overrides):
    response = test_app.post("/api/v1/rooms", headers=headers, json=room_body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def put(test_app, headers, room, **changes):
    response = test_app.put(
        f"/api/v1/rooms/{room['id']}",
        headers=headers,
        json={"revision": room["revision"], **changes},
    )
    assert response.status_code == 200, response.text
    return response.json()


def host(test_app):
    return login(test_app, "user1@example.com", "123")


def player(test_app, n=2):
    return login(test_app, f"user{n}@example.com", "123")


# ---------- create, update, cancel ----------


def test_creating_a_public_room_publishes_it(test_app: TestClient, override_get_db, hub):
    make_room(test_app, host(test_app), district="northern", area="Budaiya")
    assert hub.summary() == [("northern", "room_created")]


def test_creating_a_private_room_publishes_nothing(
    test_app: TestClient, override_get_db, hub
):
    make_room(test_app, host(test_app), visibility="private")
    assert hub.sent == []


def test_what_is_published_never_includes_the_venue(
    test_app: TestClient, override_get_db, hub
):
    make_room(test_app, host(test_app))
    assert "Pool 7" not in hub.sent[0][1].model_dump_json()


def test_editing_a_room_publishes_an_update(test_app: TestClient, override_get_db, hub):
    headers = host(test_app)
    room = make_room(test_app, headers)
    hub.clear()

    put(test_app, headers, room, title="Renamed")
    assert hub.summary() == [("capital", "room_updated")]
    assert hub.sent[0][1].room.title == "Renamed"


def test_moving_a_room_to_another_district(test_app: TestClient, override_get_db, hub):
    headers = host(test_app)
    room = make_room(test_app, headers, district="capital")
    hub.clear()

    put(test_app, headers, room, district="southern", area="Riffa")
    assert hub.summary() == [("capital", "room_removed"), ("southern", "room_created")]
    assert hub.sent[0][1].reason == "moved"


def test_making_a_room_private_and_public_again(
    test_app: TestClient, override_get_db, hub
):
    headers = host(test_app)
    room = make_room(test_app, headers)
    hub.clear()

    room = put(test_app, headers, room, visibility="private")
    assert hub.summary() == [("capital", "room_removed")]
    assert hub.sent[0][1].reason == "not_public"
    hub.clear()

    room = put(test_app, headers, room, title="Quiet edit")
    assert hub.sent == []  # a private room stays silent

    put(test_app, headers, room, visibility="public")
    assert hub.summary() == [("capital", "room_created")]


def test_cancelling_a_room_removes_it(test_app: TestClient, override_get_db, hub):
    headers = host(test_app)
    room = make_room(test_app, headers)
    hub.clear()

    response = test_app.post(
        f"/api/v1/rooms/{room['id']}/cancel", headers=headers, json={"reason": "Rain"}
    )
    assert response.status_code == 200
    assert hub.summary() == [("capital", "room_removed")]
    assert hub.sent[0][1].reason == "cancelled"


# ---------- members ----------


def request_to_join(test_app, room, n=2):
    response = test_app.post(
        f"/api/v1/rooms/{room['id']}/members", headers=player(test_app, n), json={}
    )
    assert response.status_code == 201, response.text


def set_status(test_app, room, user_id, status, headers):
    return test_app.patch(
        f"/api/v1/rooms/{room['id']}/members/{user_id}",
        headers=headers,
        json={"status": status},
    )


def test_join_request_alone_publishes_nothing(test_app: TestClient, override_get_db, hub):
    room = make_room(test_app, host(test_app))
    hub.clear()

    request_to_join(test_app, room)
    assert hub.sent == []


def test_accepting_a_player_updates_the_free_places(
    test_app: TestClient, override_get_db, hub
):
    headers = host(test_app)
    room = make_room(test_app, headers, capacity=4)
    request_to_join(test_app, room, n=2)
    hub.clear()

    assert set_status(test_app, room, 2, "accepted", headers).status_code == 200
    assert hub.summary() == [("capital", "room_updated")]
    assert hub.sent[0][1].room.slots_left == 2


def test_kicking_a_player_frees_a_place(test_app: TestClient, override_get_db, hub):
    headers = host(test_app)
    room = make_room(test_app, headers, capacity=4)
    request_to_join(test_app, room, n=2)
    set_status(test_app, room, 2, "accepted", headers)
    hub.clear()

    assert set_status(test_app, room, 2, "removed", headers).status_code == 200
    assert hub.summary() == [("capital", "room_updated")]
    assert hub.sent[0][1].room.slots_left == 3


def test_room_that_fills_up_is_removed_and_comes_back_when_someone_leaves(
    test_app: TestClient, override_get_db, hub
):
    headers = host(test_app)
    room = make_room(test_app, headers, capacity=2)  # host + one player
    request_to_join(test_app, room, n=2)
    hub.clear()

    set_status(test_app, room, 2, "accepted", headers)
    assert hub.summary() == [("capital", "room_removed")]
    assert hub.sent[0][1].reason == "full"
    hub.clear()

    response = test_app.delete(
        f"/api/v1/rooms/{room['id']}/members/me", headers=player(test_app, 2)
    )
    assert response.status_code == 204
    assert hub.summary() == [("capital", "room_created")]
    assert hub.sent[0][1].room.slots_left == 1


def test_changes_to_a_private_rooms_members_publish_nothing(
    test_app: TestClient, override_get_db, hub
):
    headers = host(test_app)
    room = make_room(test_app, headers, visibility="private", capacity=2)
    request_to_join(test_app, room, n=3)
    set_status(test_app, room, 3, "accepted", headers)
    assert hub.sent == []


# ---------- a broken lobby never breaks the request ----------


def test_a_failing_hub_does_not_break_the_requests(
    test_app: TestClient, override_get_db, monkeypatch
):
    monkeypatch.setattr(lobby_events, "lobby_hub", RecordingHub(fail=True))
    headers = host(test_app)

    room = make_room(test_app, headers)  # still 201
    put(test_app, headers, room, title="Still works")  # still 200
    response = test_app.post(
        f"/api/v1/rooms/{room['id']}/cancel", headers=headers, json={"reason": "Test"}
    )
    assert response.status_code == 200


def test_events_that_cannot_be_prepared_do_not_break_the_request(
    test_app: TestClient, override_get_db, monkeypatch
):
    def explode(*args, **kwargs):
        raise RuntimeError("cannot build events")

    monkeypatch.setattr(lobby_events, "events_for_change", explode)
    make_room(test_app, host(test_app))  # still 201
