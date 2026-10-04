from fastapi.testclient import TestClient
from data.users_data import build_users
from data.sports_data import build_sports
from data.groups_data import build_groups
from data.rooms_data import build_rooms
from data.memberships_data import build_memberships


def seed_db(db):
    db.commit()
    db.add_all(build_users())
    db.commit()
    db.add_all(build_sports())
    db.commit()
    db.add_all(build_groups())
    db.commit()
    db.add_all(build_rooms())
    db.commit()
    db.add_all(build_memberships())
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
