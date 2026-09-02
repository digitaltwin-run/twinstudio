from __future__ import annotations

import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

from twinstudio.cli import app
from twinstudio.workspace_cli import (
    WorkspaceApiClient,
    WorkspaceApiError,
    WorkspaceCliConfig,
)


def test_workspace_api_client_uses_basic_auth_and_decodes_error() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            409,
            json={"detail": {"code": "PROJECT_EXISTS", "message": "already exists"}},
        )

    client = WorkspaceApiClient(
        WorkspaceCliConfig("http://studio.test", "user@example.test", "secret", 5),
        transport=httpx.MockTransport(handler),
    )
    try:
        client.json("GET", "/api/v1/workspaces")
    except WorkspaceApiError as exc:
        assert exc.status_code == 409
        assert exc.code == "PROJECT_EXISTS"
        assert str(exc) == "already exists"
    else:
        raise AssertionError("expected WorkspaceApiError")
    assert requests[0].headers["authorization"].startswith("Basic ")


def test_workspace_api_client_decodes_twinstudio_problem() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "detail": "existing KiCad source requires candidate flow",
                "error": {
                    "code": "PROJECT_EDA_CANDIDATE_REQUIRED",
                    "message": "existing KiCad source requires candidate flow",
                },
            },
        )

    client = WorkspaceApiClient(
        WorkspaceCliConfig("http://studio.test", "", "", 5),
        transport=httpx.MockTransport(handler),
    )
    try:
        client.json("POST", "/api/v1/workspaces/mouse/files")
    except WorkspaceApiError as exc:
        assert exc.status_code == 409
        assert exc.code == "PROJECT_EDA_CANDIDATE_REQUIRED"
    else:
        raise AssertionError("expected WorkspaceApiError")


def test_workspace_cli_create_and_export_via_public_api(monkeypatch, tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v1/workspaces" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "schema_id": "twinstudio.workspace-created/v1",
                    "project": {"project_id": "mouse-cli", "license": {"spdx": "Apache-2.0"}},
                },
            )
        if request.url.path == "/api/v1/workspaces/mouse-cli/export.zip":
            return httpx.Response(200, content=b"PK\x03\x04portable")
        return httpx.Response(404, json={"detail": "not found"})

    transport = httpx.MockTransport(handler)
    original_init = WorkspaceApiClient.__init__

    def patched_init(self, config, *, transport=None):
        original_init(self, config, transport=transport or globals_transport)

    globals_transport = transport
    monkeypatch.setattr(WorkspaceApiClient, "__init__", patched_init)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "workspace",
            "--url",
            "http://studio.test",
            "create",
            "Mouse CLI",
            "--project-id",
            "mouse-cli",
            "--kind",
            "electronics",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["project"]["license"]["spdx"] == "Apache-2.0"
    assert json.loads(requests[0].content)["kind"] == "electronics"

    archive = tmp_path / "mouse.zip"
    result = runner.invoke(
        app,
        [
            "workspace",
            "--url",
            "http://studio.test",
            "export",
            "mouse-cli",
            "--out",
            str(archive),
        ],
    )
    assert result.exit_code == 0, result.output
    assert archive.read_bytes() == b"PK\x03\x04portable"


def test_workspace_cli_requires_complete_auth() -> None:
    client = WorkspaceApiClient(
        WorkspaceCliConfig("http://studio.test", "user@example.test", "", 5),
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    try:
        client.json("GET", "/api/v1/workspaces")
    except WorkspaceApiError as exc:
        assert exc.code == "CLI_AUTH_INCOMPLETE"
    else:
        raise AssertionError("expected WorkspaceApiError")
