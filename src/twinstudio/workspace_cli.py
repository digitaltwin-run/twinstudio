"""HTTP CLI for portable TwinStudio workspaces.

The commands intentionally use the public REST boundary instead of opening the
workspace directory.  This keeps authorization, project registration and write
policy identical for Viewer, shell users and other clients.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
import typer

workspace_app = typer.Typer(
    help="Create, inspect and transfer portable workspaces through the TwinStudio API."
)


class WorkspaceApiError(RuntimeError):
    """A stable, human-readable representation of an API failure."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class WorkspaceCliConfig:
    base_url: str
    email: str
    token: str
    timeout_seconds: float


class WorkspaceApiClient:
    """Small synchronous client shared by the workspace shell commands."""

    def __init__(
        self,
        config: WorkspaceCliConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json_body: dict[str, object] | None = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        auth = None
        if self.config.email or self.config.token:
            if not self.config.email or not self.config.token:
                raise WorkspaceApiError(
                    0,
                    "CLI_AUTH_INCOMPLETE",
                    "Both --email and --token are required when authentication is enabled",
                )
            auth = (self.config.email, self.config.token)
        with httpx.Client(
            base_url=self.config.base_url.rstrip("/"),
            timeout=self.config.timeout_seconds,
            auth=auth,
            transport=self.transport,
        ) as client:
            response = client.request(
                method,
                path,
                params=params,
                json=json_body,
                content=content,
            )
        if response.is_error:
            code = f"HTTP_{response.status_code}"
            message = response.text.strip() or response.reason_phrase
            try:
                body = response.json()
                problem = body.get("error") if isinstance(body, dict) else None
                if isinstance(problem, dict):
                    code = str(problem.get("code") or code)
                    message = str(problem.get("message") or body.get("detail") or problem)
                else:
                    detail = body.get("detail", body) if isinstance(body, dict) else body
                    if isinstance(detail, dict):
                        code = str(detail.get("code") or code)
                        message = str(detail.get("message") or detail)
                    elif isinstance(detail, str):
                        message = detail
            except (ValueError, TypeError):
                pass
            raise WorkspaceApiError(response.status_code, code, message)
        return response

    def json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json_body: dict[str, object] | None = None,
        content: bytes | None = None,
    ) -> dict[str, Any]:
        response = self._request(
            method,
            path,
            params=params,
            json_body=json_body,
            content=content,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise WorkspaceApiError(
                response.status_code,
                "CLI_RESPONSE_INVALID",
                "TwinStudio returned a non-JSON response",
            ) from exc
        if not isinstance(payload, dict):
            raise WorkspaceApiError(
                response.status_code,
                "CLI_RESPONSE_INVALID",
                "TwinStudio returned JSON with an unexpected shape",
            )
        return payload

    def bytes(self, path: str) -> bytes:
        return self._request("GET", path).content


def _emit(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


def _config(ctx: typer.Context) -> WorkspaceCliConfig:
    value = ctx.obj
    if not isinstance(value, WorkspaceCliConfig):
        raise RuntimeError("workspace CLI configuration was not initialized")
    return value


def _client(ctx: typer.Context) -> WorkspaceApiClient:
    return WorkspaceApiClient(_config(ctx))


def _run(action: Any) -> None:
    try:
        result = action()
    except WorkspaceApiError as exc:
        typer.echo(
            f"TwinStudio workspace error [{exc.code}] (HTTP {exc.status_code}): {exc}",
            err=True,
        )
        raise typer.Exit(1) from exc
    if result is not None:
        _emit(result)


@workspace_app.callback()
def workspace_callback(
    ctx: typer.Context,
    url: str = typer.Option(
        os.getenv("TWINSTUDIO_API_BASE", "http://127.0.0.1:8000"),
        "--url",
        help="TwinStudio API base URL (env: TWINSTUDIO_API_BASE).",
    ),
    email: str = typer.Option(
        os.getenv("TWINSTUDIO_API_EMAIL", ""),
        "--email",
        help="HTTP Basic account email (env: TWINSTUDIO_API_EMAIL).",
    ),
    token: str = typer.Option(
        os.getenv("TWINSTUDIO_API_TOKEN", ""),
        "--token",
        help="HTTP Basic personal token (env: TWINSTUDIO_API_TOKEN).",
        hide_input=True,
    ),
    timeout: float = typer.Option(180.0, "--timeout", min=1.0),
) -> None:
    ctx.obj = WorkspaceCliConfig(url, email, token, timeout)


@workspace_app.command("list")
def list_workspaces(ctx: typer.Context) -> None:
    """List workspaces visible to the current user."""
    _run(lambda: _client(ctx).json("GET", "/api/v1/workspaces"))


@workspace_app.command("show")
def show_workspace(ctx: typer.Context, project_id: str) -> None:
    """Show one workspace, its files, candidates and normalized Planfile."""
    _run(lambda: _client(ctx).json("GET", f"/api/v1/workspaces/{project_id}"))


@workspace_app.command("plan")
def show_plan(ctx: typer.Context, project_id: str) -> None:
    """Show board/table/stage data derived from planfile.yaml."""
    _run(lambda: _client(ctx).json("GET", f"/api/v1/workspaces/{project_id}/planfile"))


@workspace_app.command("create")
def create_workspace(
    ctx: typer.Context,
    name: str,
    project_id: str | None = typer.Option(None, "--project-id"),
    kind: Literal["mixed", "electronics", "software", "mechanical"] = "mixed",
) -> None:
    """Create an isolated Apache-2.0 workspace."""
    body: dict[str, object] = {"name": name, "kind": kind}
    if project_id:
        body["project_id"] = project_id
    _run(lambda: _client(ctx).json("POST", "/api/v1/workspaces", json_body=body))


@workspace_app.command("clone")
def clone_workspace(
    ctx: typer.Context,
    source_project_id: str,
    name: str,
    project_id: str | None = typer.Option(None, "--project-id"),
) -> None:
    """Clone one workspace under a new identity."""
    body: dict[str, object] = {"name": name}
    if project_id:
        body["project_id"] = project_id
    _run(
        lambda: _client(ctx).json(
            "POST",
            f"/api/v1/workspaces/{source_project_id}/clone",
            json_body=body,
        )
    )


@workspace_app.command("upload")
def upload_file(
    ctx: typer.Context,
    project_id: str,
    source: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    path: str = typer.Option(..., "--path", help="Relative path inside the workspace."),
    segregate: bool = typer.Option(False, "--segregate"),
    overwrite: bool = typer.Option(False, "--overwrite"),
    expected_sha256: str | None = typer.Option(None, "--expected-sha256"),
) -> None:
    """Upload one file; EDA sources remain protected by candidate flow."""
    params: dict[str, object] = {
        "path": path,
        "segregate": segregate,
        "overwrite": overwrite,
    }
    if expected_sha256:
        params["expected_sha256"] = expected_sha256
    _run(
        lambda: _client(ctx).json(
            "POST",
            f"/api/v1/workspaces/{project_id}/files",
            params=params,
            content=source.read_bytes(),
        )
    )


@workspace_app.command("download")
def download_file(
    ctx: typer.Context,
    project_id: str,
    path: str,
    out: Path = typer.Option(..., "--out", dir_okay=False),
) -> None:
    """Download one workspace file."""

    def action() -> None:
        content = _client(ctx).bytes(f"/api/v1/workspaces/{project_id}/files/{path}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
        typer.echo(str(out))

    _run(action)


@workspace_app.command("export")
def export_workspace(
    ctx: typer.Context,
    project_id: str,
    out: Path | None = typer.Option(None, "--out", dir_okay=False),
) -> None:
    """Export a deterministic portable ZIP."""
    destination = out or Path(f"{project_id}.zip")

    def action() -> None:
        content = _client(ctx).bytes(f"/api/v1/workspaces/{project_id}/export.zip")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        typer.echo(str(destination))

    _run(action)


@workspace_app.command("import")
def import_workspace(
    ctx: typer.Context,
    archive: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    name: str = typer.Option(..., "--name"),
    project_id: str | None = typer.Option(None, "--project-id"),
    segregate: bool = typer.Option(False, "--segregate"),
) -> None:
    """Import a portable ZIP into a new isolated workspace."""
    params: dict[str, object] = {"name": name, "segregate": segregate}
    if project_id:
        params["project_id"] = project_id
    _run(
        lambda: _client(ctx).json(
            "POST",
            "/api/v1/workspaces/import",
            params=params,
            content=archive.read_bytes(),
        )
    )


@workspace_app.command("merge-plan")
def merge_plan(
    ctx: typer.Context,
    target_project_id: str,
    source_project_id: str,
    strategy: Literal["reject", "keep_both"] = typer.Option("reject", "--strategy"),
) -> None:
    """Calculate a merge plan without changing either workspace."""
    _run(
        lambda: _client(ctx).json(
            "POST",
            f"/api/v1/workspaces/{target_project_id}/merge",
            json_body={
                "source_project_id": source_project_id,
                "conflict_strategy": strategy,
                "apply": False,
            },
        )
    )


@workspace_app.command("merge-apply")
def merge_apply(
    ctx: typer.Context,
    target_project_id: str,
    source_project_id: str,
    plan_sha256: str = typer.Option(..., "--plan-sha256"),
    strategy: Literal["reject", "keep_both"] = typer.Option("reject", "--strategy"),
) -> None:
    """Apply an unchanged merge plan identified by its SHA-256."""
    _run(
        lambda: _client(ctx).json(
            "POST",
            f"/api/v1/workspaces/{target_project_id}/merge",
            json_body={
                "source_project_id": source_project_id,
                "conflict_strategy": strategy,
                "apply": True,
                "plan_sha256": plan_sha256,
            },
        )
    )
