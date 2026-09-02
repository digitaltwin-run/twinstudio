from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from twin_projects import MANIFEST_RELATIVE, ProjectPackageStore

from twinstudio.workspace_api import build_workspace_router


def _workspace_store(tmp_path: Path) -> ProjectPackageStore:
    root = tmp_path / "artifacts"
    (root / ".wellmanifest").mkdir(parents=True)
    (root / MANIFEST_RELATIVE).write_text(
        json.dumps(
            {
                "schema_id": "wellmanifest.project-package/v1",
                "schema_version": "1.0.0",
                "project_id": "legacy",
                "name": "Legacy",
                "kind": "mixed",
                "root_mode": "legacy",
            }
        ),
        encoding="utf-8",
    )
    return ProjectPackageStore(root)


def test_workspace_api_owns_storage_and_requires_authorization(
    tmp_path: Path,
) -> None:
    registered: list[str] = []
    authorized: list[tuple[str, str]] = []

    def current_user() -> str:
        return "creator@example.test"

    def authorize(project_id: str, _user: str, permission: str) -> None:
        authorized.append((project_id, permission))

    app = FastAPI()
    app.include_router(
        build_workspace_router(
            _workspace_store(tmp_path),
            principal_dependency=current_user,
            authorize=authorize,
            register_project=lambda project_id, _user: registered.append(project_id),
            writes_enabled=True,
        )
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/workspaces",
            json={"name": "Mouse RP2040", "project_id": "mouse-rp2040"},
        )
        details = client.get("/api/v1/workspaces/mouse-rp2040")
        exported = client.get("/api/v1/workspaces/mouse-rp2040/export.zip")

    assert created.status_code == 201
    assert registered == ["mouse-rp2040"]
    assert details.json()["planfile"]["counts"]["planned"] == 3
    assert exported.headers["content-type"] == "application/zip"
    assert ("mouse-rp2040", "project.read") in authorized
    assert ("mouse-rp2040", "artifact.download") in authorized


def test_workspace_writes_are_fail_closed(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(
        build_workspace_router(
            _workspace_store(tmp_path),
            principal_dependency=lambda: "user",
            authorize=lambda _project_id, _user, _permission: None,
            register_project=lambda _project_id, _user: None,
            writes_enabled=False,
        )
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/workspaces", json={"name": "Denied"})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PROJECT_WRITE_DISABLED"
