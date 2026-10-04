from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from models.membership import MembershipModel
from tests.lib import login


def auth(test_app: TestClient, n: int):
    return login(test_app, f"user{n}@example.com", "123")


def row(db: Session, **filters):
    db.expire_all()
    return db.query(MembershipModel).filter_by(**filters).first()


# ---------- Friends ----------


def test_get_friends(test_app: TestClient, test_db: Session, override_get_db):
    response = test_app.get("/api/v1/friends", headers=auth(test_app, 2))
    assert response.status_code == 200
    ids = {(f["user_id"], f["other_user_id"]) for f in response.json()}
    assert (1, 2) in ids


def test_send_friend_request(test_app: TestClient, test_db: Session, override_get_db):
    response = test_app.post(
        "/api/v1/friends", headers=auth(test_app, 2), json={"other_user_id": 4}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == 2
    assert body["other_user_id"] == 4
    assert body["status"] == "pending"
    assert row(test_db, user_id=2, other_user_id=4) is not None


def test_friend_request_errors(test_app: TestClient, test_db: Session, override_get_db):
    headers = auth(test_app, 2)
    assert (
        test_app.post(
            "/api/v1/friends", headers=headers, json={"other_user_id": 2}
        ).status_code
        == 400
    )
    assert (
        test_app.post(
            "/api/v1/friends", headers=headers, json={"other_user_id": 999}
        ).status_code
        == 404
    )
    # Reverse pair already exists (user1 -> user2)
    assert (
        test_app.post(
            "/api/v1/friends", headers=headers, json={"other_user_id": 1}
        ).status_code
        == 409
    )


def test_friend_requester_cannot_accept(
    test_app: TestClient, test_db: Session, override_get_db
):
    response = test_app.patch(
        "/api/v1/friends/3", headers=auth(test_app, 1), json={"status": "accepted"}
    )
    assert response.status_code == 403


def test_friend_target_accepts(test_app: TestClient, test_db: Session, override_get_db):
    response = test_app.patch(
        "/api/v1/friends/1", headers=auth(test_app, 3), json={"status": "accepted"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert row(test_db, user_id=1, other_user_id=3).accepted is True


def test_friend_block_flags(test_app: TestClient, test_db: Session, override_get_db):
    # user1 is the requester, so owns user_blocked_other
    response = test_app.patch(
        "/api/v1/friends/2",
        headers=auth(test_app, 1),
        json={"user_blocked_other": "true"},
    )
    assert response.status_code == 200
    assert response.json()["user_blocked_other"] == "true"

    # user1 may not set the other side's flag
    response = test_app.patch(
        "/api/v1/friends/2",
        headers=auth(test_app, 1),
        json={"other_blocked_user": "true"},
    )
    assert response.status_code == 403

    # user2 sets their own flag
    response = test_app.patch(
        "/api/v1/friends/1",
        headers=auth(test_app, 2),
        json={"other_blocked_user": "true"},
    )
    assert response.status_code == 200


def test_friend_not_found(test_app: TestClient, test_db: Session, override_get_db):
    response = test_app.patch(
        "/api/v1/friends/4", headers=auth(test_app, 1), json={"status": "removed"}
    )
    assert response.status_code == 404


# ---------- Group members ----------


def test_owner_sees_all_group_members(
    test_app: TestClient, test_db: Session, override_get_db
):
    response = test_app.get("/api/v1/groups/1/members", headers=auth(test_app, 1))
    assert response.status_code == 200
    assert {m["user_id"] for m in response.json()} == {2, 3}


def test_member_sees_accepted_and_own(
    test_app: TestClient, test_db: Session, override_get_db
):
    response = test_app.get("/api/v1/groups/1/members", headers=auth(test_app, 3))
    assert {m["user_id"] for m in response.json()} == {2, 3}
    response = test_app.get("/api/v1/groups/1/members", headers=auth(test_app, 4))
    assert response.json() == [m for m in response.json() if m["status"] == "accepted"]


def test_group_not_found(test_app: TestClient, test_db: Session, override_get_db):
    response = test_app.get("/api/v1/groups/999/members", headers=auth(test_app, 1))
    assert response.status_code == 404


def test_invite_group_member(test_app: TestClient, test_db: Session, override_get_db):
    response = test_app.post(
        "/api/v1/groups/1/members", headers=auth(test_app, 1), json={"user_id": 4}
    )
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert row(test_db, user_id=4, group_id=1) is not None


def test_invite_group_member_errors(
    test_app: TestClient, test_db: Session, override_get_db
):
    assert (
        test_app.post(
            "/api/v1/groups/1/members", headers=auth(test_app, 2), json={"user_id": 4}
        ).status_code
        == 403
    )
    assert (
        test_app.post(
            "/api/v1/groups/1/members", headers=auth(test_app, 1), json={"user_id": 4}
        ).status_code
        == 409
    )
    assert (
        test_app.post(
            "/api/v1/groups/1/members", headers=auth(test_app, 1), json={"user_id": 999}
        ).status_code
        == 404
    )


def test_group_invitee_accepts(test_app: TestClient, test_db: Session, override_get_db):
    response = test_app.patch(
        "/api/v1/groups/1/members/3",
        headers=auth(test_app, 3),
        json={"status": "accepted"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert row(test_db, user_id=3, group_id=1).accepted is True


def test_group_update_permissions(
    test_app: TestClient, test_db: Session, override_get_db
):
    # A stranger cannot change anyone
    assert (
        test_app.patch(
            "/api/v1/groups/1/members/2",
            headers=auth(test_app, 4),
            json={"status": "removed"},
        ).status_code
        == 403
    )
    # The owner cannot accept on behalf of the invitee
    assert (
        test_app.patch(
            "/api/v1/groups/1/members/4",
            headers=auth(test_app, 1),
            json={"status": "accepted"},
        ).status_code
        == 403
    )
    # Missing status
    assert (
        test_app.patch(
            "/api/v1/groups/1/members/2", headers=auth(test_app, 1), json={}
        ).status_code
        == 422
    )


def test_group_owner_removes_and_member_leaves(
    test_app: TestClient, test_db: Session, override_get_db
):
    response = test_app.patch(
        "/api/v1/groups/1/members/2",
        headers=auth(test_app, 1),
        json={"status": "removed"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "removed"

    response = test_app.patch(
        "/api/v1/groups/1/members/3",
        headers=auth(test_app, 3),
        json={"status": "left"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "left"


# ---------- Cup roster ----------


def test_cup_invite_errors(test_app: TestClient, test_db: Session, override_get_db):
    # Not the team owner
    assert (
        test_app.post(
            "/api/v1/cups/2/roster",
            headers=auth(test_app, 1),
            json={"user_id": 1, "group_id": 4},
        ).status_code
        == 403
    )
    # Unknown team
    assert (
        test_app.post(
            "/api/v1/cups/2/roster",
            headers=auth(test_app, 4),
            json={"user_id": 1, "group_id": 999},
        ).status_code
        == 404
    )
    # User 3 is not a member of group 4
    assert (
        test_app.post(
            "/api/v1/cups/2/roster",
            headers=auth(test_app, 4),
            json={"user_id": 3, "group_id": 4},
        ).status_code
        == 400
    )


def test_cup_invite_and_accept(test_app: TestClient, test_db: Session, override_get_db):
    response = test_app.post(
        "/api/v1/cups/2/roster",
        headers=auth(test_app, 4),
        json={"user_id": 1, "group_id": 4},
    )
    assert response.status_code == 201
    assert response.json()["cup_id"] == 2
    assert response.json()["status"] == "pending"

    # Duplicate invitation
    assert (
        test_app.post(
            "/api/v1/cups/2/roster",
            headers=auth(test_app, 4),
            json={"user_id": 1, "group_id": 4},
        ).status_code
        == 409
    )

    # Only the invitee accepts
    assert (
        test_app.patch(
            "/api/v1/cups/2/roster/1",
            headers=auth(test_app, 4),
            json={"status": "accepted"},
        ).status_code
        == 403
    )
    response = test_app.patch(
        "/api/v1/cups/2/roster/1",
        headers=auth(test_app, 1),
        json={"status": "accepted"},
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True


def test_cup_owner_removes_and_not_found(
    test_app: TestClient, test_db: Session, override_get_db
):
    response = test_app.patch(
        "/api/v1/cups/2/roster/1",
        headers=auth(test_app, 4),
        json={"status": "removed"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "removed"

    assert (
        test_app.patch(
            "/api/v1/cups/2/roster/3",
            headers=auth(test_app, 4),
            json={"status": "removed"},
        ).status_code
        == 404
    )


# ---------- Room members (host of room 1 is user1) ----------


def test_get_room_members(test_app: TestClient, test_db: Session, override_get_db):
    response = test_app.get("/api/v1/rooms/1/members")
    assert response.status_code == 200
    assert {m["user_id"] for m in response.json()} == {2, 3}


def test_room_join_request(test_app: TestClient, test_db: Session, override_get_db):
    response = test_app.post(
        "/api/v1/rooms/1/members", headers=auth(test_app, 4), json={}
    )
    assert response.status_code == 201
    assert response.json()["user_id"] == 4
    assert response.json()["requested"] is True
    assert response.json()["status"] == "pending"

    assert (
        test_app.post(
            "/api/v1/rooms/1/members", headers=auth(test_app, 4), json={}
        ).status_code
        == 409
    )


def test_room_host_invites(test_app: TestClient, test_db: Session, override_get_db):
    # Non-host cannot invite another user
    assert (
        test_app.post(
            "/api/v1/rooms/1/members", headers=auth(test_app, 3), json={"user_id": 1}
        ).status_code
        == 403
    )
    assert (
        test_app.post(
            "/api/v1/rooms/1/members", headers=auth(test_app, 1), json={"user_id": 999}
        ).status_code
        == 404
    )

    response = test_app.post(
        "/api/v1/rooms/1/members", headers=auth(test_app, 1), json={"user_id": 1}
    )
    assert response.status_code == 201
    assert response.json()["requested"] is True  # host joining themselves


def test_room_host_approves_request(
    test_app: TestClient, test_db: Session, override_get_db
):
    # Only the host approves a join request
    assert (
        test_app.patch(
            "/api/v1/rooms/1/members/2",
            headers=auth(test_app, 2),
            json={"status": "accepted"},
        ).status_code
        == 403
    )
    response = test_app.patch(
        "/api/v1/rooms/1/members/2",
        headers=auth(test_app, 1),
        json={"status": "accepted"},
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True


def test_room_slots_are_unique(test_app: TestClient, test_db: Session, override_get_db):
    # A1 is held by user3
    response = test_app.patch(
        "/api/v1/rooms/1/members/2",
        headers=auth(test_app, 2),
        json={"position": "A1"},
    )
    assert response.status_code == 409
    response = test_app.patch(
        "/api/v1/rooms/1/members/2",
        headers=auth(test_app, 2),
        json={"position": "B1"},
    )
    assert response.status_code == 200
    assert response.json()["position"] == "B1"


def test_room_attendance_and_rating(
    test_app: TestClient, test_db: Session, override_get_db
):
    host = auth(test_app, 1)
    # Cannot rate before attendance is present
    assert (
        test_app.patch(
            "/api/v1/rooms/1/members/2", headers=host, json={"rating": 4}
        ).status_code
        == 409
    )
    # Players cannot record attendance
    assert (
        test_app.patch(
            "/api/v1/rooms/1/members/2",
            headers=auth(test_app, 2),
            json={"attendance": "present"},
        ).status_code
        == 403
    )
    response = test_app.patch(
        "/api/v1/rooms/1/members/2", headers=host, json={"attendance": "present"}
    )
    assert response.status_code == 200
    assert response.json()["attendance"] == "present"

    response = test_app.patch(
        "/api/v1/rooms/1/members/2", headers=host, json={"rating": 5}
    )
    assert response.status_code == 200
    assert response.json()["rating"] == 5

    # Out of range and invalid values are rejected by validation
    assert (
        test_app.patch(
            "/api/v1/rooms/1/members/2", headers=host, json={"rating": 9}
        ).status_code
        == 422
    )
    assert (
        test_app.patch(
            "/api/v1/rooms/1/members/2", headers=host, json={"attendance": "late"}
        ).status_code
        == 422
    )


def test_room_host_cannot_rate_self(
    test_app: TestClient, test_db: Session, override_get_db
):
    host = auth(test_app, 1)
    test_app.patch(
        "/api/v1/rooms/1/members/1", headers=host, json={"attendance": "present"}
    )
    response = test_app.patch(
        "/api/v1/rooms/1/members/1", headers=host, json={"rating": 5}
    )
    assert response.status_code == 403


def test_room_update_permissions(
    test_app: TestClient, test_db: Session, override_get_db
):
    # Stranger cannot touch another player's membership
    assert (
        test_app.patch(
            "/api/v1/rooms/1/members/2",
            headers=auth(test_app, 3),
            json={"status": "removed"},
        ).status_code
        == 403
    )
    assert (
        test_app.patch(
            "/api/v1/rooms/1/members/999",
            headers=auth(test_app, 1),
            json={"status": "removed"},
        ).status_code
        == 404
    )


def test_room_host_removes_member(
    test_app: TestClient, test_db: Session, override_get_db
):
    response = test_app.patch(
        "/api/v1/rooms/1/members/4",
        headers=auth(test_app, 1),
        json={"status": "declined"},
    )
    assert response.status_code == 200
    response = test_app.patch(
        "/api/v1/rooms/1/members/2",
        headers=auth(test_app, 1),
        json={"status": "removed"},
    )
    assert response.status_code == 200
    assert response.json()["position"] is None


def test_room_leave(test_app: TestClient, test_db: Session, override_get_db):
    response = test_app.delete("/api/v1/rooms/1/members/me", headers=auth(test_app, 3))
    assert response.status_code == 204
    member = row(test_db, user_id=3, room_id=1)
    assert member.status == "left"
    assert member.position is None

    assert (
        test_app.delete(
            "/api/v1/rooms/1/members/me", headers=auth(test_app, 4)
        ).status_code
        == 204
    )
    assert (
        test_app.delete("/api/v1/rooms/9/members/me", headers=auth(test_app, 4)).status_code
        == 404
    )
