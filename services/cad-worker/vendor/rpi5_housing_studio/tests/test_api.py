from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_and_default_config() -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    response = client.get("/api/default-config")
    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["dimensions"]["wall_thickness"] == 2.0


def test_interpret_fallback() -> None:
    response = client.post(
        "/api/interpret",
        json={"prompt": "Ustaw grubość ścian na 2.3 mm", "config": None},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["dimensions"]["wall_thickness"] == 2.3


def test_invalid_job_identifier_is_rejected() -> None:
    response = client.get("/api/jobs/..")
    assert response.status_code in {400, 404}
