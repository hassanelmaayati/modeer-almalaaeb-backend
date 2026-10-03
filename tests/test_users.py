import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from models.user import UserModel
from tests.lib import login


@pytest.fixture(scope="module", autouse=True)
def other_player(test_db: Session):
    player = UserModel(
        display_name="Other Player", handle="other_player", email="other@example.com"
    )
    player.set_password("otherpass")
    test_db.add(player)
    test_db.commit()


def test_signup(test_app: TestClient, test_db: Session, override_get_db):
    user_data = {
        "display_name": "New Player",
        "handle": "New_Player",
        "email": "New@Example.com",
        "password": "strongpass",
    }
    response = test_app.post("/api/v1/auth/signup", json=user_data)

    assert response.status_code == 201
    body = response.json()
    assert body["token"]
    assert body["user"]["handle"] == "new_player"
    assert body["user"]["email"] == "new@example.com"
    assert body["user"]["has_password"] is True
    assert "password_hash" not in body["user"]

    user = test_db.query(UserModel).filter(UserModel.handle == "new_player").first()
    assert user is not None
    assert user.password_hash != "strongpass"


def test_signup_rejects_duplicate_handle(test_app: TestClient, override_get_db):
    user_data = {
        "display_name": "Copy",
        "handle": "new_player",
        "email": "copy@example.com",
        "password": "strongpass",
    }
    response = test_app.post("/api/v1/auth/signup", json=user_data)
    assert response.status_code == 400
    assert response.json()["detail"] == "Handle is already taken"


def test_signup_validates_fields(test_app: TestClient, override_get_db):
    user_data = {
        "display_name": "Bad",
        "handle": "a b",
        "email": "not-an-email",
        "password": "short",
    }
    response = test_app.post("/api/v1/auth/signup", json=user_data)
    assert response.status_code == 422


def test_login_with_handle_or_email(test_app: TestClient, override_get_db):
    assert login(test_app, "new_player", "strongpass")
    assert login(test_app, "NEW@example.com", "strongpass")

    response = test_app.post(
        "/api/v1/auth/login", json={"identifier": "new_player", "password": "wrong"}
    )
    assert response.status_code == 400


def test_get_and_update_me(test_app: TestClient, override_get_db):
    headers = login(test_app, "new_player", "strongpass")

    response = test_app.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["email"] == "new@example.com"

    response = test_app.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"display_name": "Renamed", "bio": "Midfielder"},
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "Renamed"
    assert response.json()["bio"] == "Midfielder"
    assert response.json()["handle"] == "new_player"


def test_update_me_rejects_taken_handle(test_app: TestClient, override_get_db):
    headers = login(test_app, "new_player", "strongpass")
    response = test_app.patch("/api/v1/users/me", headers=headers, json={"handle": "other_player"})
    assert response.status_code == 400


def test_get_public_profile(test_app: TestClient, test_db: Session, override_get_db):
    user = test_db.query(UserModel).filter(UserModel.handle == "new_player").first()
    response = test_app.get(f"/api/v1/users/{user.id}")
    assert response.status_code == 200
    assert response.json()["handle"] == "new_player"
    assert "email" not in response.json()

    response = test_app.get("/api/v1/users/99999")
    assert response.status_code == 404


def test_search_users_requires_auth(test_app: TestClient, override_get_db):
    response = test_app.get("/api/v1/users")
    assert response.status_code == 401

    headers = login(test_app, "new_player", "strongpass")
    response = test_app.get("/api/v1/users?search=other", headers=headers)
    assert response.status_code == 200
    assert [user["handle"] for user in response.json()] == ["other_player"]


def test_logout_revokes_token(test_app: TestClient, override_get_db):
    headers = login(test_app, "new_player", "strongpass")

    response = test_app.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 204

    response = test_app.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 401
