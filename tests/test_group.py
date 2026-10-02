from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from models.user import UserModel
from models.group import GroupModel
from tests.lib import login, get_user_id
from main import app


def test_login(test_app: TestClient, test_db: Session, override_get_db):

    new_user = UserModel(username="test", email="test@example.com", password="123")
    new_user.set_password(new_user.password)
    test_db.add(new_user)
    test_db.commit()

    # Use the login helper to generate authentication headers for the new mock user
    headers = login(test_app, "test", "123")
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Bearer ")


def test_create_group(test_app: TestClient, test_db: Session, override_get_db):

    # Use the login helper to generate authentication headers for the new mock user
    headers = login(test_app, "test", "123")

    # Data for creating a new group
    group_data = {
        "name": "Test Group",
        "description": "A test group",
        "photo_url": "http://example.com/photo.jpg",
        "sports_id": 1,
    }

    # Send a POST request to create a new group
    response = test_app.post("/api/v1/groups", headers=headers, json=group_data)

    user_id = get_user_id(headers)
    # Verify that the response is successful
    assert response.status_code == 201
    assert response.json()["name"] == group_data["name"]
    assert response.json()["sports_id"] == group_data["sports_id"]
    assert response.json()["description"] == group_data["description"]
    assert response.json()["photo_url"] == group_data["photo_url"]
    assert response.json()["owner_id"] == user_id
    assert "id" in response.json()  # Ensure an ID is returned
    # Verify the group was created in the database
    group_id = response.json()["id"]
    group = test_db.query(GroupModel).filter(GroupModel.id == group_id).first()
    assert group is not None
    assert group.name == group_data["name"]
    assert group.sports_id == group_data["sports_id"]
    assert group.owner_id == user_id
    assert group.description == group_data["description"]
    assert group.photo_url == group_data["photo_url"]


def test_get_groups(test_app: TestClient, override_get_db):
    response = test_app.get("/api/v1/groups")
    assert response.status_code == 200
    groups = response.json()
    assert isinstance(groups, list)
    assert len(groups) >= 2  # Ensure there are at least two groups in the test database
    for group in groups:
        assert "id" in group
        assert "name" in group
        assert "sports_id" in group
        assert "owner_id" in group
        assert "description" in group
        assert "photo_url" in group


def test_put_group(test_app: TestClient, test_db: Session, override_get_db):
    # Use the login helper to generate authentication headers for the new mock user
    headers = login(test_app, "test", "123")

    # First, create a new group to update
    group_data = {
        "name": "Test Group to Update",
        "description": "A test group",
        "photo_url": "http://example.com/photo.jpg",
        "sports_id": 1,
    }
    response = test_app.post("/api/v1/groups", headers=headers, json=group_data)
    assert response.status_code == 201
    group_id = response.json()["id"]

    # Data for updating the group
    updated_group_data = {
        "name": "Updated Test Group",
        "description": "An updated test group",
        "photo_url": "http://example.com/updated_photo.jpg",
    }

    # Send a PUT request to update the group
    response = test_app.put(
        f"/api/v1/groups/{group_id}", headers=headers, json=updated_group_data
    )
    assert response.status_code == 200
    assert response.json()["name"] == updated_group_data["name"]
    assert response.json()["description"] == updated_group_data["description"]
    assert response.json()["photo_url"] == updated_group_data["photo_url"]

    # Verify the group was updated in the database
    group = test_db.query(GroupModel).filter(GroupModel.id == group_id).first()
    assert group is not None
    assert group.name == updated_group_data["name"]
    assert group.description == updated_group_data["description"]
    assert group.photo_url == updated_group_data["photo_url"]
    assert group.owner_id == get_user_id(headers)


def test_get_group_by_id(test_app: TestClient, test_db: Session, override_get_db):
    # Use the login helper to generate authentication headers for the new mock user
    headers = login(test_app, "test", "123")

    # First, create a new group to retrieve
    group_data = {
        "name": "Test Group to Retrieve",
        "description": "A test group",
        "photo_url": "http://example.com/photo.jpg",
        "sports_id": 1,
    }
    response = test_app.post("/api/v1/groups", headers=headers, json=group_data)
    assert response.status_code == 201
    group_id = response.json()["id"]

    # Send a GET request to retrieve the group by ID
    response = test_app.get(f"/api/v1/groups/{group_id}", headers=headers)
    assert response.status_code == 200
    group = response.json()
    assert group["id"] == group_id
    assert group["name"] == group_data["name"]
    assert group["description"] == group_data["description"]
    assert group["photo_url"] == group_data["photo_url"]
    assert group["sports_id"] == group_data["sports_id"]
    assert group["owner_id"] == get_user_id(headers)
