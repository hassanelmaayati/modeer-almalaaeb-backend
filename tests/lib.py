from fastapi.testclient import TestClient
from data.users_data import user_list
from data.sports_data import sports_list
from data.groups_data import groups_list


def seed_db(db):
    db.commit()
    for user in user_list:
        user.set_password(user.password)
    db.add_all(user_list)
    db.commit()
    db.add_all(sports_list)
    db.commit()
    db.add_all(groups_list)
    db.commit()


def login(test_app: TestClient, username: str, password: str):
    # Log in using an existing mock user
    response = test_app.post(
        "/api/v1/login", json={"username": username, "password": password}
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


def get_user_id(headers):
    from config.environment import JWT_SECRET
    import jwt

    token = headers["Authorization"].split()[-1]
    return int(jwt.decode(token, JWT_SECRET, algorithms=["HS256"])["sub"])
