from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from models.room import RoomModel
from tests.lib import login, get_user_id

# Seeded users all use the password "123" (see data/users_data.py)
# Seeded rooms (data/rooms_data.py): 1 Football/user1, 2 Basketball/user2,
# 3 Tennis group-only/user3, 4 Swimming/user4


def future(days=1, hours=0):
    return (datetime.now(timezone.utc) + timedelta(days=days, hours=hours)).isoformat()


def room_data(**overrides):
    # A valid Football 5v5 room; tests override only what they check
    data = {
        "sport_id": 1,
        "title": "Test room",
        "starts_at": future(days=1),
        "ends_at": future(days=1, hours=1),
        "capacity": 10,
        "public_area": "Manama",
        "venue_details": "Court 1",
    }
    data.update(overrides)
    return data


def create_room(test_app: TestClient, headers, **overrides):
    response = test_app.post("/api/v1/rooms", headers=headers, json=room_data(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


# ---------- discovery and details ----------


def test_get_rooms(test_app: TestClient, test_db: Session, override_get_db):
    response = test_app.get("/api/v1/rooms")
    assert response.status_code == 200
    rooms = response.json()
    assert len(rooms) >= 3

    ids = [room["id"] for room in rooms]
    assert 3 not in ids  # the group-only room is not listed
    for room in rooms:
        assert room["status"] == "open"
        assert room["visibility"] == "public"
        assert "venue_details" not in room  # exact venue stays private

    # Sorted by start time
    starts = [room["starts_at"] for room in rooms]
    assert starts == sorted(starts)


def test_get_rooms_filter_by_sport(test_app: TestClient, override_get_db):
    response = test_app.get("/api/v1/rooms?sport_id=2")
    assert response.status_code == 200
    rooms = response.json()
    assert len(rooms) >= 1
    assert all(room["sport_id"] == 2 for room in rooms)


def test_get_rooms_filter_by_difficulty(test_app: TestClient, override_get_db):
    response = test_app.get("/api/v1/rooms?difficulty=medium")
    assert response.status_code == 200
    assert all(room["difficulty"] == "medium" for room in response.json())


def test_get_room_hides_venue_from_visitors(test_app: TestClient, override_get_db):
    response = test_app.get("/api/v1/rooms/1")
    assert response.status_code == 200
    assert response.json()["title"] == "Friday 5-a-side"
    assert "venue_details" not in response.json()


def test_get_room_shows_venue_to_host(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    response = test_app.get("/api/v1/rooms/1", headers=headers)
    assert response.status_code == 200
    assert response.json()["venue_details"] == "Pitch 3, Bahrain Sports Hall"


def test_get_room_hides_venue_from_other_users(test_app: TestClient, override_get_db):
    headers = login(test_app, "user2@example.com", "123")
    response = test_app.get("/api/v1/rooms/1", headers=headers)
    assert response.status_code == 200
    assert "venue_details" not in response.json()


def test_get_room_not_found(test_app: TestClient, override_get_db):
    response = test_app.get("/api/v1/rooms/9999")
    assert response.status_code == 404


def test_get_group_room_hidden_from_non_host(test_app: TestClient, override_get_db):
    assert test_app.get("/api/v1/rooms/3").status_code == 404

    other = login(test_app, "user1@example.com", "123")
    assert test_app.get("/api/v1/rooms/3", headers=other).status_code == 404

    host = login(test_app, "user3@example.com", "123")
    response = test_app.get("/api/v1/rooms/3", headers=host)
    assert response.status_code == 200
    assert response.json()["venue_details"] == "Court 2"


# ---------- create ----------


def test_create_room(test_app: TestClient, test_db: Session, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    response = test_app.post("/api/v1/rooms", headers=headers, json=room_data())

    assert response.status_code == 201
    room = response.json()
    assert room["host_id"] == get_user_id(headers)
    assert room["status"] == "open"
    assert room["visibility"] == "public"
    assert room["difficulty"] == "beginners"
    assert room["revision"] == 0
    assert room["venue_details"] == "Court 1"

    db_room = test_db.query(RoomModel).filter(RoomModel.id == room["id"]).first()
    assert db_room is not None
    assert db_room.title == "Test room"
    assert db_room.capacity == 10


def test_create_room_requires_login(test_app: TestClient, override_get_db):
    response = test_app.post("/api/v1/rooms", json=room_data())
    assert response.status_code in (401, 403)


def test_create_room_ignores_server_fields(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    room = create_room(test_app, headers, host_id=4, status="cancelled", revision=9)
    assert room["host_id"] == get_user_id(headers)
    assert room["status"] == "open"
    assert room["revision"] == 0


def test_create_room_capacity_must_match_format(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    response = test_app.post(
        "/api/v1/rooms", headers=headers, json=room_data(capacity=9)
    )
    assert response.status_code == 422
    assert "does not match" in response.json()["detail"]


def test_create_room_sport_without_formats_accepts_any_capacity(
    test_app: TestClient, override_get_db
):
    headers = login(test_app, "user1@example.com", "123")
    room = create_room(test_app, headers, sport_id=4, capacity=3)
    assert room["capacity"] == 3


def test_create_room_unknown_sport(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    response = test_app.post(
        "/api/v1/rooms", headers=headers, json=room_data(sport_id=999)
    )
    assert response.status_code == 404


def test_create_room_start_too_soon(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    response = test_app.post(
        "/api/v1/rooms",
        headers=headers,
        json=room_data(
            starts_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        ),
    )
    assert response.status_code == 422


def test_create_room_start_too_far(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    response = test_app.post(
        "/api/v1/rooms",
        headers=headers,
        json=room_data(starts_at=future(days=30), ends_at=future(days=30, hours=1)),
    )
    assert response.status_code == 422


def test_create_room_requires_timezone(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    naive = (datetime.now() + timedelta(days=1)).replace(tzinfo=None).isoformat()
    response = test_app.post(
        "/api/v1/rooms", headers=headers, json=room_data(starts_at=naive)
    )
    assert response.status_code == 422


def test_create_room_end_before_start(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    response = test_app.post(
        "/api/v1/rooms",
        headers=headers,
        json=room_data(starts_at=future(days=2), ends_at=future(days=1)),
    )
    assert response.status_code == 422


def test_create_room_invalid_choices(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    for field, value in [
        ("difficulty", "expert"),
        ("visibility", "secret"),
        ("admission_policy", "anyone"),
    ]:
        response = test_app.post(
            "/api/v1/rooms", headers=headers, json=room_data(**{field: value})
        )
        assert response.status_code == 422, field


def test_create_room_group_visibility_needs_group(
    test_app: TestClient, override_get_db
):
    headers = login(test_app, "user1@example.com", "123")
    response = test_app.post(
        "/api/v1/rooms", headers=headers, json=room_data(visibility="group")
    )
    assert response.status_code == 422


def test_create_room_for_own_group(test_app: TestClient, override_get_db):
    # Group 1 is owned by user1
    headers = login(test_app, "user1@example.com", "123")
    room = create_room(test_app, headers, group_id=1, visibility="group")
    assert room["group_id"] == 1
    assert room["visibility"] == "group"


def test_create_room_for_someone_elses_group(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    response = test_app.post(
        "/api/v1/rooms", headers=headers, json=room_data(group_id=2)
    )
    assert response.status_code == 403


def test_create_room_unknown_group(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    response = test_app.post(
        "/api/v1/rooms", headers=headers, json=room_data(group_id=999)
    )
    assert response.status_code == 404


# ---------- update ----------


def test_update_room(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    room = create_room(test_app, headers)

    response = test_app.put(
        f"/api/v1/rooms/{room['id']}",
        headers=headers,
        json={"revision": room["revision"], "title": "New title", "capacity": 14},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "New title"
    assert response.json()["capacity"] == 14
    assert response.json()["public_area"] == "Manama"  # untouched
    assert response.json()["revision"] == room["revision"] + 1


def test_update_room_only_host(test_app: TestClient, override_get_db):
    host = login(test_app, "user1@example.com", "123")
    other = login(test_app, "user2@example.com", "123")
    room = create_room(test_app, host)

    response = test_app.put(
        f"/api/v1/rooms/{room['id']}",
        headers=other,
        json={"revision": 0, "title": "Hijacked"},
    )
    assert response.status_code == 403


def test_update_room_requires_login(test_app: TestClient, override_get_db):
    response = test_app.put("/api/v1/rooms/1", json={"revision": 0, "title": "x"})
    assert response.status_code in (401, 403)


def test_update_room_not_found(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    response = test_app.put(
        "/api/v1/rooms/9999", headers=headers, json={"revision": 0, "title": "x"}
    )
    assert response.status_code == 404


def test_update_room_stale_revision(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    room = create_room(test_app, headers)

    response = test_app.put(
        f"/api/v1/rooms/{room['id']}",
        headers=headers,
        json={"revision": 5, "title": "Stale"},
    )
    assert response.status_code == 409


def test_update_room_required_field_cannot_be_null(
    test_app: TestClient, override_get_db
):
    headers = login(test_app, "user1@example.com", "123")
    room = create_room(test_app, headers)

    response = test_app.put(
        f"/api/v1/rooms/{room['id']}",
        headers=headers,
        json={"revision": 0, "title": None},
    )
    assert response.status_code == 422


def test_update_room_end_before_stored_start(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    room = create_room(test_app, headers)

    # Only ends_at is sent, so it is compared with the stored start
    response = test_app.put(
        f"/api/v1/rooms/{room['id']}",
        headers=headers,
        json={"revision": 0, "ends_at": future(days=1, hours=-1)},
    )
    assert response.status_code == 422


def test_update_room_group_visibility_needs_group(
    test_app: TestClient, override_get_db
):
    headers = login(test_app, "user1@example.com", "123")
    room = create_room(test_app, headers)

    response = test_app.put(
        f"/api/v1/rooms/{room['id']}",
        headers=headers,
        json={"revision": 0, "visibility": "group"},
    )
    assert response.status_code == 422


def test_update_room_capacity_must_match_format(
    test_app: TestClient, test_db: Session, override_get_db
):
    headers = login(test_app, "user1@example.com", "123")
    room = create_room(test_app, headers)

    response = test_app.put(
        f"/api/v1/rooms/{room['id']}",
        headers=headers,
        json={"revision": 0, "capacity": 11},
    )
    assert response.status_code == 422

    # Nothing was saved
    test_db.expire_all()
    db_room = test_db.query(RoomModel).filter(RoomModel.id == room["id"]).first()
    assert db_room.capacity == 10
    assert db_room.revision == 0


def test_update_room_changing_sport_rechecks_capacity(
    test_app: TestClient, override_get_db
):
    headers = login(test_app, "user1@example.com", "123")
    room = create_room(test_app, headers)  # Football, capacity 10

    # Tennis only allows 2 or 4
    response = test_app.put(
        f"/api/v1/rooms/{room['id']}",
        headers=headers,
        json={"revision": 0, "sport_id": 3},
    )
    assert response.status_code == 422


def test_update_room_unknown_sport(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    room = create_room(test_app, headers)

    response = test_app.put(
        f"/api/v1/rooms/{room['id']}",
        headers=headers,
        json={"revision": 0, "sport_id": 999},
    )
    assert response.status_code == 404


# ---------- the 15 minute cutoff ----------


def add_room_starting_in(test_db: Session, minutes: int, host_id=1):
    now = datetime.now(timezone.utc)
    room = RoomModel(
        host_id=host_id,
        sport_id=4,
        title="Starting soon",
        starts_at=now + timedelta(minutes=minutes),
        ends_at=now + timedelta(minutes=minutes + 60),
        capacity=5,
        public_area="Manama",
        venue_details="Pool 1",
    )
    test_db.add(room)
    test_db.commit()
    test_db.refresh(room)
    return room.id


def test_rooms_past_cutoff_are_not_listed(
    test_app: TestClient, test_db: Session, override_get_db
):
    soon_id = add_room_starting_in(test_db, minutes=10)
    ids = [room["id"] for room in test_app.get("/api/v1/rooms").json()]
    assert soon_id not in ids

    # Still reachable by link
    assert test_app.get(f"/api/v1/rooms/{soon_id}").status_code == 200


def test_update_frozen_after_cutoff(
    test_app: TestClient, test_db: Session, override_get_db
):
    headers = login(test_app, "user1@example.com", "123")
    soon_id = add_room_starting_in(test_db, minutes=10)

    for change in [{"capacity": 6}, {"venue_details": "Pool 2"}, {"public_area": "X"}]:
        response = test_app.put(
            f"/api/v1/rooms/{soon_id}", headers=headers, json={"revision": 0, **change}
        )
        assert response.status_code == 409, change


def test_update_other_fields_allowed_after_cutoff(
    test_app: TestClient, test_db: Session, override_get_db
):
    headers = login(test_app, "user1@example.com", "123")
    soon_id = add_room_starting_in(test_db, minutes=10)

    response = test_app.put(
        f"/api/v1/rooms/{soon_id}",
        headers=headers,
        json={"revision": 0, "title": "Still editable"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Still editable"


# ---------- cancel ----------


def test_cancel_room(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    room = create_room(test_app, headers)

    response = test_app.post(
        f"/api/v1/rooms/{room['id']}/cancel",
        headers=headers,
        json={"reason": "Rain"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["revision"] == room["revision"] + 1

    # No longer listed
    ids = [r["id"] for r in test_app.get("/api/v1/rooms").json()]
    assert room["id"] not in ids


def test_cancel_room_requires_reason(test_app: TestClient, override_get_db):
    headers = login(test_app, "user1@example.com", "123")
    room = create_room(test_app, headers)

    response = test_app.post(
        f"/api/v1/rooms/{room['id']}/cancel", headers=headers, json={}
    )
    assert response.status_code == 422
    response = test_app.post(
        f"/api/v1/rooms/{room['id']}/cancel", headers=headers, json={"reason": ""}
    )
    assert response.status_code == 422


def test_cancel_room_only_host(test_app: TestClient, override_get_db):
    host = login(test_app, "user1@example.com", "123")
    other = login(test_app, "user2@example.com", "123")
    room = create_room(test_app, host)

    response = test_app.post(
        f"/api/v1/rooms/{room['id']}/cancel", headers=other, json={"reason": "No"}
    )
    assert response.status_code == 403


def test_cancel_room_requires_login(test_app: TestClient, override_get_db):
    response = test_app.post("/api/v1/rooms/1/cancel", json={"reason": "No"})
    assert response.status_code in (401, 403)


def test_cancelled_room_cannot_be_cancelled_or_edited(
    test_app: TestClient, override_get_db
):
    headers = login(test_app, "user1@example.com", "123")
    room = create_room(test_app, headers)
    url = f"/api/v1/rooms/{room['id']}"
    test_app.post(f"{url}/cancel", headers=headers, json={"reason": "Rain"})

    again = test_app.post(f"{url}/cancel", headers=headers, json={"reason": "Rain"})
    assert again.status_code == 409

    edit = test_app.put(url, headers=headers, json={"revision": 1, "title": "x"})
    assert edit.status_code == 409
