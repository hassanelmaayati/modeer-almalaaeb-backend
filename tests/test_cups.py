from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from models.cup import CupModel
from models.group import GroupModel
from models.sport import SportModel
from models.user import UserModel
from tests.lib import login


def closes_in(days: int):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


@pytest.fixture(scope="module")
def cup_data(test_db: Session):
    users = {}
    for name in ("organizer", "captain", "outsider", "runner"):
        user = UserModel(user_name=f"cup_{name}", email=f"cup_{name}@example.com")
        user.set_password("cuppass123")
        test_db.add(user)
        users[name] = user

    # Lowercase on purpose: the sport-format lookup ignores case
    football = SportModel(name="football")
    basketball = SportModel(name="Basketball")
    running = SportModel(name="Running")
    walking = SportModel(name="Walking")
    chess = SportModel(name="Chess")
    test_db.add_all([football, basketball, running, walking, chess])
    test_db.commit()

    captain_groups = [
        GroupModel(
            name=f"Team {i}", owner_id=users["captain"].id, sports_id=football.id
        )
        for i in range(1, 6)
    ]
    outsider_group = GroupModel(
        name="Outsider FC", owner_id=users["outsider"].id, sports_id=football.id
    )
    basketball_group = GroupModel(
        name="Hoops", owner_id=users["captain"].id, sports_id=basketball.id
    )
    runner_groups = [
        GroupModel(
            name=f"Runner {i}", owner_id=users["runner"].id, sports_id=running.id
        )
        for i in range(1, 4)
    ]
    test_db.add_all([*captain_groups, outsider_group, basketball_group, *runner_groups])
    test_db.commit()

    return {
        "football_id": football.id,
        "basketball_id": basketball.id,
        "running_id": running.id,
        "walking_id": walking.id,
        "chess_id": chess.id,
        "group_ids": [group.id for group in captain_groups],
        "outsider_group_id": outsider_group.id,
        "basketball_group_id": basketball_group.id,
        "runner_group_ids": [group.id for group in runner_groups],
    }


@pytest.fixture(scope="module")
def headers(test_app: TestClient, override_get_db, cup_data):
    return {
        name: login(test_app, f"cup_{name}@example.com", "cuppass123")
        for name in ("organizer", "captain", "outsider", "runner")
    }


@pytest.fixture(scope="module")
def cup_state():
    return {}


def new_cup_data(sport_id: int, **overrides):
    data = {
        "sport_id": sport_id,
        "name": "Test Cup",
        "rules": "Knockout, penalties if level",
        "team_count": 4,
        "roster_limit": 8,
    }
    data.update(overrides)
    return data


def test_create_cup_requires_auth(test_app: TestClient, cup_data, override_get_db):
    response = test_app.post("/api/v1/cups", json=new_cup_data(cup_data["football_id"]))
    assert response.status_code == 401


def test_create_cup(
    test_app: TestClient, test_db: Session, cup_data, headers, cup_state
):
    response = test_app.post(
        "/api/v1/cups",
        headers=headers["organizer"],
        json=new_cup_data(cup_data["football_id"]),
    )
    assert response.status_code == 201
    cup = response.json()
    assert cup["status"] == "draft"
    assert cup["format"] == "knockout"
    assert cup["organizer"]["user_name"] == "cup_organizer"
    assert cup["entries"] == []
    assert cup["fixtures"] == []
    assert cup["revision"] == 0

    db_cup = test_db.query(CupModel).filter(CupModel.id == cup["id"]).first()
    assert db_cup is not None
    assert db_cup.organizer_user_id == cup["organizer_user_id"]
    cup_state["id"] = cup["id"]


def test_create_cup_checks_sport(test_app: TestClient, cup_data, headers):
    response = test_app.post(
        "/api/v1/cups",
        headers=headers["organizer"],
        json=new_cup_data(cup_data["basketball_id"], team_count=8),
    )
    assert response.status_code == 201
    assert response.json()["format"] == "knockout"

    response = test_app.post(
        "/api/v1/cups",
        headers=headers["organizer"],
        json=new_cup_data(cup_data["basketball_id"], team_count=6),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Knockout cups need 4, 8 or 16 teams"

    response = test_app.post(
        "/api/v1/cups",
        headers=headers["organizer"],
        json=new_cup_data(cup_data["walking_id"]),
    )
    assert response.status_code == 400
    assert "Walking is a social outing" in response.json()["detail"]

    response = test_app.post(
        "/api/v1/cups",
        headers=headers["organizer"],
        json=new_cup_data(cup_data["chess_id"]),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Cups are not available for Chess yet"

    response = test_app.post(
        "/api/v1/cups", headers=headers["organizer"], json=new_cup_data(99999)
    )
    assert response.status_code == 404


def test_create_cup_validates_fields(test_app: TestClient, cup_data, headers):
    for overrides in ({"team_count": 1}, {"roster_limit": 0}, {"name": ""}):
        response = test_app.post(
            "/api/v1/cups",
            headers=headers["organizer"],
            json=new_cup_data(cup_data["football_id"], **overrides),
        )
        assert response.status_code == 422

    response = test_app.post(
        "/api/v1/cups",
        headers=headers["organizer"],
        json=new_cup_data(
            cup_data["football_id"], registration_closes_at=closes_in(-1)
        ),
    )
    assert response.status_code == 400


def test_drafts_are_private(test_app: TestClient, headers, cup_state):
    cup_id = cup_state["id"]

    response = test_app.get(f"/api/v1/cups/{cup_id}")
    assert response.status_code == 404
    response = test_app.get(f"/api/v1/cups/{cup_id}", headers=headers["outsider"])
    assert response.status_code == 404
    assert cup_id not in [cup["id"] for cup in test_app.get("/api/v1/cups").json()]

    response = test_app.get(f"/api/v1/cups/{cup_id}", headers=headers["organizer"])
    assert response.status_code == 200
    response = test_app.get("/api/v1/cups", headers=headers["organizer"])
    assert cup_id in [cup["id"] for cup in response.json()]


def test_only_organizer_can_edit(test_app: TestClient, headers, cup_state):
    cup_id = cup_state["id"]

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={"name": "Renamed Cup"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed Cup"
    assert response.json()["revision"] == 1

    # Drafts are hidden from everyone else, so they get 404 rather than 403
    response = test_app.patch(
        f"/api/v1/cups/{cup_id}", headers=headers["outsider"], json={"name": "Hijacked"}
    )
    assert response.status_code == 404


def test_stale_revision_is_rejected(test_app: TestClient, headers, cup_state):
    response = test_app.patch(
        f"/api/v1/cups/{cup_state['id']}",
        headers=headers["organizer"],
        json={"rules": "Updated rules", "revision": 0},
    )
    assert response.status_code == 409


def test_open_registration(test_app: TestClient, headers, cup_state):
    cup_id = cup_state["id"]

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={"status": "published"},
    )
    assert response.status_code == 400

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={"status": "registration"},
    )
    assert response.status_code == 400

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={"status": "registration", "registration_closes_at": closes_in(7)},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "registration"
    assert response.json()["registration_closes_at"].endswith("Z")

    # Now public, so other users get 403 instead of 404
    response = test_app.patch(
        f"/api/v1/cups/{cup_id}", headers=headers["outsider"], json={"name": "Hijacked"}
    )
    assert response.status_code == 403
    assert test_app.get(f"/api/v1/cups/{cup_id}").status_code == 200


def test_delete_only_drafts(test_app: TestClient, cup_data, headers, cup_state):
    response = test_app.delete(
        f"/api/v1/cups/{cup_state['id']}", headers=headers["organizer"]
    )
    assert response.status_code == 400

    response = test_app.post(
        "/api/v1/cups",
        headers=headers["organizer"],
        json=new_cup_data(cup_data["football_id"], name="Throwaway"),
    )
    draft_id = response.json()["id"]

    response = test_app.delete(f"/api/v1/cups/{draft_id}", headers=headers["outsider"])
    assert response.status_code == 404
    response = test_app.delete(f"/api/v1/cups/{draft_id}", headers=headers["organizer"])
    assert response.status_code == 204
    response = test_app.get(f"/api/v1/cups/{draft_id}", headers=headers["organizer"])
    assert response.status_code == 404


def test_enter_teams(test_app: TestClient, cup_data, headers, cup_state):
    cup_id = cup_state["id"]

    response = test_app.post(
        f"/api/v1/cups/{cup_id}/entries",
        headers=headers["captain"],
        json={"group_id": cup_data["outsider_group_id"]},
    )
    assert response.status_code == 403

    response = test_app.post(
        f"/api/v1/cups/{cup_id}/entries",
        headers=headers["captain"],
        json={"group_id": 99999},
    )
    assert response.status_code == 404

    response = test_app.post(
        f"/api/v1/cups/{cup_id}/entries",
        headers=headers["captain"],
        json={"group_id": cup_data["basketball_group_id"]},
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"] == "This group plays a different sport than this cup"
    )

    for group_id in cup_data["group_ids"]:
        response = test_app.post(
            f"/api/v1/cups/{cup_id}/entries",
            headers=headers["captain"],
            json={"group_id": group_id},
        )
        assert response.status_code == 201

    entries = response.json()["entries"]
    assert len(entries) == 5
    assert {entry["status"] for entry in entries} == {"pending"}
    assert entries[0]["group_name"] == "Team 1"

    response = test_app.post(
        f"/api/v1/cups/{cup_id}/entries",
        headers=headers["captain"],
        json={"group_id": cup_data["group_ids"][0]},
    )
    assert response.status_code == 400


def test_review_entries(test_app: TestClient, cup_data, headers, cup_state):
    cup_id = cup_state["id"]
    first, *others = cup_data["group_ids"]

    response = test_app.put(
        f"/api/v1/cups/{cup_id}/entries/{first}",
        headers=headers["captain"],
        json={"status": "accepted"},
    )
    assert response.status_code == 403

    response = test_app.put(
        f"/api/v1/cups/{cup_id}/entries/{first}",
        headers=headers["organizer"],
        json={"status": "withdrawn"},
    )
    assert response.status_code == 403

    for group_id in cup_data["group_ids"][:4]:
        response = test_app.put(
            f"/api/v1/cups/{cup_id}/entries/{group_id}",
            headers=headers["organizer"],
            json={"status": "accepted"},
        )
        assert response.status_code == 200

    response = test_app.put(
        f"/api/v1/cups/{cup_id}/entries/{others[-1]}",
        headers=headers["organizer"],
        json={"status": "accepted"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "All team places are taken"

    response = test_app.put(
        f"/api/v1/cups/{cup_id}/entries/{others[-1]}",
        headers=headers["captain"],
        json={"status": "withdrawn"},
    )
    assert response.status_code == 200

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}", headers=headers["organizer"], json={"team_count": 4}
    )
    assert response.status_code == 200


def test_publish_draws_bracket(
    test_app: TestClient, test_db: Session, cup_data, headers, cup_state
):
    cup_id = cup_state["id"]

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={"status": "published"},
    )
    assert response.status_code == 200
    cup = response.json()
    assert cup["status"] == "published"
    assert cup["rosters_locked_at"] is not None
    assert [fixture["id"] for fixture in cup["fixtures"]] == ["R1-M1", "R1-M2", "R2-M1"]

    round_one_teams = {
        fixture[side]
        for fixture in cup["fixtures"][:2]
        for side in ("home_group_id", "away_group_id")
    }
    assert round_one_teams == set(cup_data["group_ids"][:4])
    cup_state["fixtures"] = cup["fixtures"]

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={"name": "Too late"},
    )
    assert response.status_code == 400

    response = test_app.post(
        f"/api/v1/cups/{cup_id}/entries",
        headers=headers["outsider"],
        json={"group_id": cup_data["outsider_group_id"]},
    )
    assert response.status_code == 400


def test_record_results(test_app: TestClient, headers, cup_state):
    cup_id = cup_state["id"]
    semi_one, semi_two, _ = cup_state["fixtures"]

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={"result": {"fixture_id": "R2-M1", "home_score": 1, "away_score": 0}},
    )
    assert response.status_code == 400

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={"result": {"fixture_id": "R1-M1", "home_score": 2, "away_score": 2}},
    )
    assert response.status_code == 400

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["captain"],
        json={"result": {"fixture_id": "R1-M1", "home_score": 2, "away_score": 0}},
    )
    assert response.status_code == 403

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={
            "result": {
                "fixture_id": "R1-M1",
                "home_score": 2,
                "away_score": 2,
                "winner_group_id": semi_one["away_group_id"],
            }
        },
    )
    assert response.status_code == 200
    final = response.json()["fixtures"][2]
    assert final["home_group_id"] == semi_one["away_group_id"]

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={"result": {"fixture_id": "R1-M2", "home_score": 3, "away_score": 1}},
    )
    final = response.json()["fixtures"][2]
    assert final["away_group_id"] == semi_two["home_group_id"]

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={"result": {"fixture_id": "R2-M1", "home_score": 0, "away_score": 1}},
    )
    assert response.status_code == 200
    cup = response.json()
    assert cup["status"] == "completed"
    assert cup["fixtures"][2]["winner_group_id"] == semi_two["home_group_id"]


def test_knockout_rejects_race_results(test_app: TestClient, headers, cup_state):
    response = test_app.patch(
        f"/api/v1/cups/{cup_state['id']}",
        headers=headers["organizer"],
        json={"race_results": [{"group_id": 1, "finish_time_seconds": 60}]},
    )
    assert response.status_code == 400
    assert "knockout cup" in response.json()["detail"]


def test_race_cup_flow(test_app: TestClient, cup_data, headers, cup_state):
    response = test_app.post(
        "/api/v1/cups",
        headers=headers["organizer"],
        json=new_cup_data(
            cup_data["running_id"],
            name="10K",
            team_count=6,
            roster_limit=1,
            registration_closes_at=closes_in(7),
        ),
    )
    assert response.status_code == 201
    assert response.json()["format"] == "race"
    cup_id = response.json()["id"]
    cup_state["race_id"] = cup_id

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={"status": "registration"},
    )
    assert response.status_code == 200

    first, second, third = cup_data["runner_group_ids"]
    for group_id in (first, second, third):
        response = test_app.post(
            f"/api/v1/cups/{cup_id}/entries",
            headers=headers["runner"],
            json={"group_id": group_id},
        )
        assert response.status_code == 201

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={"status": "published"},
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "Publishing a race needs at least 2 accepted entrants"
    )

    for group_id in (first, second, third):
        test_app.put(
            f"/api/v1/cups/{cup_id}/entries/{group_id}",
            headers=headers["organizer"],
            json={"status": "accepted"},
        )

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={"status": "published"},
    )
    assert response.status_code == 200
    assert response.json()["fixtures"] == []
    assert response.json()["rosters_locked_at"] is not None

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={"result": {"fixture_id": "R1-M1", "home_score": 1, "away_score": 0}},
    )
    assert response.status_code == 400
    assert "race cup" in response.json()["detail"]

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={
            "race_results": [
                {"group_id": first, "finish_time_seconds": 60, "position": 1}
            ]
        },
    )
    assert response.status_code == 422

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={
            "race_results": [
                {"group_id": first, "finish_time_seconds": 1900},
                {"group_id": second, "position": 1},
            ]
        },
    )
    assert response.status_code == 400

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={
            "race_results": [
                {"group_id": first, "finish_time_seconds": 1900},
                {"group_id": second, "finish_time_seconds": 1834.5},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "published"

    response = test_app.patch(
        f"/api/v1/cups/{cup_id}",
        headers=headers["organizer"],
        json={"race_results": [{"group_id": third, "did_not_finish": True}]},
    )
    assert response.status_code == 200
    cup = response.json()
    assert cup["status"] == "completed"
    positions = {entry["group_id"]: entry["position"] for entry in cup["entries"]}
    assert positions == {first: 2, second: 1, third: None}


def test_list_cups_by_status(test_app: TestClient, cup_state, override_get_db):
    response = test_app.get("/api/v1/cups?status=completed")
    assert response.status_code == 200
    assert {cup["id"] for cup in response.json()} == {
        cup_state["id"],
        cup_state["race_id"],
    }

    response = test_app.get("/api/v1/cups?status=cancelled")
    assert response.status_code == 422
