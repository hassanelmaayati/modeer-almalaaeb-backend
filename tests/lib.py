from fastapi.testclient import TestClient
from data.tea_data import teas_list, comments_list
from data.user_data import user_list


def seed_db(db):
    db.commit()
    db.add_all(user_list)
    db.commit()
    db.add_all(teas_list)
    db.commit()
    db.add_all(comments_list)
    db.commit()


def login(test_app: TestClient, username: str, password: str):
    # Log in using an existing mock user
    response = test_app.post(
        "/api/login", json={"username": username, "password": password}
    )

    if response.status_code != 201:
        raise Exception(
            f"Login failed: {response.json().get('detail', 'Unknown error')}"
        )

    token = response.json().get("token")
    if not token:
        raise Exception("No token returned from login endpoint.")

    headers = {"Authorization": f"Bearer {token}"}
    return headers
