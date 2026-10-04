import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from models.user import UserModel
from tests.lib import login


@pytest.fixture(scope="module", autouse=True)
def other_player(test_db: Session):
    player = UserModel(user_name="other_player", email="other@example.com")
    player.set_password("otherpass")
    test_db.add(player)
    test_db.commit()


def test_signup(test_app: TestClient, test_db: Session, override_get_db):
    user_data = {
        "user_name": "new_player",
        "email": "new@example.com",
        "password": "strongpass",
        "bio": "Striker",
    }
    response = test_app.post("/api/v1/auth/signup", json=user_data)

    assert response.status_code == 201
    body = response.json()
    assert body["token"]
    assert body["user"]["user_name"] == "new_player"
    assert body["user"]["bio"] == "Striker"
    assert "password" not in body["user"]
    assert "email" not in body["user"]

    user = test_db.query(UserModel).filter(UserModel.user_name == "new_player").first()
    assert user is not None
    assert user.password != "strongpass"


def test_signup_rejects_duplicate_user_name(test_app: TestClient, override_get_db):
    user_data = {
        "user_name": "other_player",
        "email": "copy@example.com",
        "password": "strongpass",
    }
    response = test_app.post("/api/v1/auth/signup", json=user_data)
    assert response.status_code == 400
    assert response.json()["detail"] == "user name is already taken"


def test_signup_rejects_duplicate_email(test_app: TestClient, override_get_db):
    user_data = {
        "user_name": "copy_player",
        "email": "other@example.com",
        "password": "strongpass",
    }
    response = test_app.post("/api/v1/auth/signup", json=user_data)
    assert response.status_code == 400
    assert response.json()["detail"] == "Email is already registered"


def test_signup_validates_fields(test_app: TestClient, override_get_db):
    user_data = {
        "user_name": "ab",
        "email": "not-an-email",
        "password": "short",
    }
    response = test_app.post("/api/v1/auth/signup", json=user_data)
    assert response.status_code == 422


def test_login_with_email(test_app: TestClient, override_get_db):
    assert login(test_app, "other@example.com", "otherpass")

    response = test_app.post(
        "/api/v1/auth/login", json={"email": "other@example.com", "password": "wrong"}
    )
    assert response.status_code == 400


def test_get_and_update_me(test_app: TestClient, override_get_db):
    headers = login(test_app, "other@example.com", "otherpass")

    response = test_app.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["user_name"] == "other_player"

    response = test_app.put(
        "/api/v1/users/me",
        headers=headers,
        json={"user_name": "renamed_player", "bio": "Midfielder"},
    )
    assert response.status_code == 200
    assert response.json()["user_name"] == "renamed_player"
    assert response.json()["bio"] == "Midfielder"


def test_signup_with_home_district(test_app: TestClient, test_db: Session, override_get_db):
    user_data = {
        "user_name": "district_player",
        "email": "district@example.com",
        "password": "strongpass",
        "district": "northern",
    }
    response = test_app.post("/api/v1/auth/signup", json=user_data)
    assert response.status_code == 201
    assert response.json()["user"]["district"] == "northern"

    user = test_db.query(UserModel).filter(UserModel.user_name == "district_player").first()
    assert user.district == "northern"


def test_signup_without_district_leaves_it_empty(test_app: TestClient, override_get_db):
    user_data = {
        "user_name": "no_district_player",
        "email": "nodistrict@example.com",
        "password": "strongpass",
    }
    response = test_app.post("/api/v1/auth/signup", json=user_data)
    assert response.status_code == 201
    assert response.json()["user"]["district"] is None


def test_signup_rejects_invalid_district(test_app: TestClient, override_get_db):
    user_data = {
        "user_name": "mars_player",
        "email": "mars@example.com",
        "password": "strongpass",
        "district": "mars",
    }
    response = test_app.post("/api/v1/auth/signup", json=user_data)
    assert response.status_code == 422


def test_update_home_district(test_app: TestClient, override_get_db):
    headers = login(test_app, "other@example.com", "otherpass")

    response = test_app.put(
        "/api/v1/users/me",
        headers=headers,
        json={"user_name": "renamed_player", "district": "muharraq"},
    )
    assert response.status_code == 200
    assert response.json()["district"] == "muharraq"
    assert test_app.get("/api/v1/users/me", headers=headers).json()["district"] == "muharraq"

    # Changing the district can be undone by sending null
    response = test_app.put(
        "/api/v1/users/me",
        headers=headers,
        json={"user_name": "renamed_player", "district": None},
    )
    assert response.status_code == 200
    assert response.json()["district"] is None


def test_update_home_district_must_be_valid(test_app: TestClient, override_get_db):
    headers = login(test_app, "other@example.com", "otherpass")

    response = test_app.put(
        "/api/v1/users/me",
        headers=headers,
        json={"user_name": "renamed_player", "district": "mars"},
    )
    assert response.status_code == 422


def test_get_users(test_app: TestClient, override_get_db):
    response = test_app.get("/api/v1/users")
    assert response.status_code == 200
    user_names = [user["user_name"] for user in response.json()]
    assert "renamed_player" in user_names
    assert all("email" not in user for user in response.json())


def test_get_public_profile(test_app: TestClient, test_db: Session, override_get_db):
    user = (
        test_db.query(UserModel).filter(UserModel.user_name == "renamed_player").first()
    )
    response = test_app.get(f"/api/v1/users/{user.id}")
    assert response.status_code == 200
    assert response.json()["user_name"] == "renamed_player"
    assert "email" not in response.json()

    response = test_app.get("/api/v1/users/99999")
    assert response.status_code == 404


def test_me_requires_auth(test_app: TestClient, override_get_db):
    response = test_app.get("/api/v1/users/me")
    assert response.status_code == 401


def test_logout_revokes_token(test_app: TestClient, override_get_db):
    headers = login(test_app, "other@example.com", "otherpass")

    response = test_app.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 204

    response = test_app.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 401
