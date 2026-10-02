from fastapi.testclient import TestClient
from main import app


def test_get_sports(test_app: TestClient):
    response = test_app.get("/api/v1/sports")
    assert response.status_code == 200
    sports = response.json()
    assert isinstance(sports, list)
    for sport in sports:
        assert "id" in sport
        assert "name" in sport
