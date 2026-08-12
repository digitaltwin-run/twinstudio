from fastapi.testclient import TestClient

from app.main import GENERATED_ROOT, app
from housing_studio.artifacts import generate_artifacts
from housing_studio.models import default_project_config

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


def test_validate_and_interpret_change_audit() -> None:
    default_payload = client.get("/api/default-config").json()
    response = client.post(
        "/api/validate",
        json={"config": default_payload["config"]},
    )
    assert response.status_code == 200
    assert response.json()["layers"]["feature_layers"]["hinge"]["enabled"] is True

    interpretation = client.post(
        "/api/interpret",
        json={"prompt": "Ustaw grubość ścian na 2.7 mm", "config": default_payload["config"]},
    )
    assert interpretation.status_code == 200
    changes = interpretation.json()["changes"]
    assert any(change["path"] == "dimensions.wall_thickness" for change in changes)


def test_jobs_endpoint_returns_a_list() -> None:
    response = client.get("/api/jobs?limit=5")
    assert response.status_code == 200
    assert isinstance(response.json()["jobs"], list)


def test_stored_job_configuration_can_be_reloaded() -> None:
    job_id = "api-config-reload-test"
    try:
        generate_artifacts(default_project_config(), GENERATED_ROOT, job_id=job_id)
        response = client.get(f"/api/jobs/{job_id}/config")
        assert response.status_code == 200
        payload = response.json()
        assert payload["job_id"] == job_id
        assert payload["config"]["dimensions"]["wall_thickness"] == 2.0
    finally:
        import shutil

        shutil.rmtree(GENERATED_ROOT / job_id, ignore_errors=True)
