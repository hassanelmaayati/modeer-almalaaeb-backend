import importlib

from fastapi.testclient import TestClient
from data import users_data, sports_data, groups_data


def seed_db(db):
    # Reload the data modules so every test module seeds fresh objects
    for data_module in (users_data, sports_data, groups_data):
        importlib.reload(data_module)

    db.commit()
    db.add_all(users_data.user_list)
    db.commit()
    db.add_all(sports_data.sports_list)
    db.commit()
    db.add_all(groups_data.groups_list)
    db.commit()


def login(test_app: TestClient, email: str, password: str):
    # Log in using an existing mock user
    response = test_app.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )

    if response.status_code != 200:
        raise Exception(
            f"Login failed: {response.json().get('detail', 'Unknown error')}"
        )

    token = response.json().get("token")
    if not token:
        raise Exception("No token returned from login endpoint.")

    headers = {"Authorization": f"Bearer {token}"}
    return headers


def get_user_id(headers):
    from config.environment import JWT_SECRET
    import jwt

    token = headers["Authorization"].split()[-1]
    return int(jwt.decode(token, JWT_SECRET, algorithms=["HS256"])["sub"])
