"""Authenticated REST adapter for the external ``twin-projects`` component."""

from __future__ import annotations

import mimetypes
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from twin_projects import ProjectPackageError, ProjectPackageStore
from twin_projects.packages import MAX_ARCHIVE_BYTES, MAX_UPLOAD_BYTES


class WorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    project_id: str | None = Field(default=None, min_length=1, max_length=80)
    kind: Literal["mixed", "electronics", "software", "mechanical"] = "mixed"


class WorkspaceCloneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    project_id: str | None = Field(default=None, min_length=1, max_length=80)


class WorkspaceMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_project_id: str = Field(min_length=1, max_length=80)
    conflict_strategy: Literal["reject", "keep_both"] = "reject"
    apply: bool = False
    plan_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


_STATUS_BY_CODE = {
    "PROJECT_NOT_FOUND": 404,
    "PROJECT_FILE_NOT_FOUND": 404,
    "PROJECT_WRITE_DISABLED": 403,
    "PROJECT_LEGACY_MERGE_FORBIDDEN": 403,
    "PROJECT_EXISTS": 409,
    "PROJECT_FILE_EXISTS": 409,
    "PROJECT_FILE_CHANGED": 409,
    "PROJECT_EDA_CANDIDATE_REQUIRED": 409,
    "PROJECT_ARCHIVE_CONFLICT": 409,
    "PROJECT_MERGE_CONFLICT": 409,
    "PROJECT_MERGE_STALE": 409,
    "PROJECT_UPLOAD_TOO_LARGE": 413,
    "PROJECT_ARCHIVE_TOO_LARGE": 413,
    "PROJECT_ARCHIVE_TOO_MANY_FILES": 413,
    "PROJECT_ARCHIVE_EXPANDED_TOO_LARGE": 413,
    "PROJECT_ARCHIVE_RATIO": 413,
}


def _http_error(exc: ProjectPackageError) -> HTTPException:
    return HTTPException(
        _STATUS_BY_CODE.get(exc.code, 422),
        {"code": exc.code, "message": str(exc)},
    )


def build_workspace_router(
    store: ProjectPackageStore,
    *,
    principal_dependency: Callable[..., Any],
    authorize: Callable[[str, Any, str], None],
    register_project: Callable[[str, Any], None],
    writes_enabled: bool,
) -> APIRouter:
    """Build the TwinStudio-owned transport around a framework-free store."""
    router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])

    def require_writes() -> None:
        if not writes_enabled:
            raise _http_error(ProjectPackageError("PROJECT_WRITE_DISABLED", "Workspace writes are disabled"))

    def readable_projects(user: Any) -> list[dict[str, object]]:
        result = []
        for project in store.list_projects():
            try:
                authorize(str(project["project_id"]), user, "project.read")
            except (HTTPException, PermissionError):
                continue
            result.append(project)
        return result

    @router.get("")
    def list_workspaces(user: Any = Depends(principal_dependency)) -> dict[str, object]:
        return {
            "schema_id": "twinstudio.workspaces/v1",
            "projects": readable_projects(user),
        }

    @router.post("", status_code=201)
    def create_workspace(
        body: WorkspaceCreateRequest,
        user: Any = Depends(principal_dependency),
    ) -> JSONResponse:
        require_writes()
        try:
            project = store.create(body.name, project_id=body.project_id, kind=body.kind)
            register_project(str(project["project_id"]), user)
        except ProjectPackageError as exc:
            raise _http_error(exc) from exc
        return JSONResponse(
            {"schema_id": "twinstudio.workspace-created/v1", "project": project},
            status_code=201,
        )

    @router.get("/{project_id}")
    def workspace_details(project_id: str, user: Any = Depends(principal_dependency)) -> dict[str, object]:
        authorize(project_id, user, "project.read")
        try:
            return {
                "schema_id": "twinstudio.workspace/v1",
                "project": store.describe(project_id),
                "files": store.files(project_id),
                "eda_candidates": store.eda_candidates(project_id),
                "planfile": store.planfile(project_id),
            }
        except ProjectPackageError as exc:
            raise _http_error(exc) from exc

    @router.get("/{project_id}/planfile")
    def workspace_planfile(project_id: str, user: Any = Depends(principal_dependency)) -> dict[str, object]:
        authorize(project_id, user, "project.read")
        try:
            return store.planfile(project_id)
        except ProjectPackageError as exc:
            raise _http_error(exc) from exc

    @router.post("/{project_id}/clone", status_code=201)
    def clone_workspace(
        project_id: str,
        body: WorkspaceCloneRequest,
        user: Any = Depends(principal_dependency),
    ) -> JSONResponse:
        require_writes()
        authorize(project_id, user, "project.read")
        try:
            project = store.clone(project_id, body.name, project_id=body.project_id)
            register_project(str(project["project_id"]), user)
        except ProjectPackageError as exc:
            raise _http_error(exc) from exc
        return JSONResponse(
            {"schema_id": "twinstudio.workspace-cloned/v1", "project": project},
            status_code=201,
        )

    @router.get("/{project_id}/export.zip")
    def export_workspace(project_id: str, user: Any = Depends(principal_dependency)) -> Response:
        authorize(project_id, user, "artifact.download")
        try:
            project = store.describe(project_id)
            content = store.export_zip(project_id)
        except ProjectPackageError as exc:
            raise _http_error(exc) from exc
        return Response(
            content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{project_id}.zip"',
                "X-Project-Fingerprint-SHA256": str(project["fingerprint_sha256"]),
                "X-Project-Content-Fingerprint-SHA256": str(project["content_fingerprint_sha256"]),
                "Cache-Control": "no-store",
            },
        )

    @router.post("/import", status_code=201)
    async def import_workspace(
        request: Request,
        name: str = Query(min_length=1, max_length=120),
        project_id: str | None = Query(default=None, min_length=1, max_length=80),
        segregate: bool = Query(default=False),
        user: Any = Depends(principal_dependency),
    ) -> JSONResponse:
        require_writes()
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_ARCHIVE_BYTES:
            raise _http_error(
                ProjectPackageError(
                    "PROJECT_ARCHIVE_TOO_LARGE",
                    "Archive exceeds the 256 MiB limit",
                )
            )
        try:
            project = store.import_zip(
                name,
                await request.body(),
                project_id=project_id,
                segregate=segregate,
            )
            register_project(str(project["project_id"]), user)
        except ProjectPackageError as exc:
            raise _http_error(exc) from exc
        return JSONResponse(
            {"schema_id": "twinstudio.workspace-imported/v1", "project": project},
            status_code=201,
        )

    @router.post("/{project_id}/files", status_code=201)
    async def upload_workspace_file(
        project_id: str,
        request: Request,
        path: str = Query(min_length=1, max_length=4_000),
        segregate: bool = Query(default=False),
        overwrite: bool = Query(default=False),
        expected_sha256: str | None = Query(default=None, pattern=r"^[0-9a-f]{64}$"),
        user: Any = Depends(principal_dependency),
    ) -> JSONResponse:
        require_writes()
        authorize(project_id, user, "change.apply")
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
            raise _http_error(
                ProjectPackageError("PROJECT_UPLOAD_TOO_LARGE", "File exceeds the 128 MiB limit")
            )
        try:
            uploaded = store.upload(
                project_id,
                path,
                await request.body(),
                segregate=segregate,
                overwrite=overwrite,
                expected_sha256=expected_sha256,
            )
        except ProjectPackageError as exc:
            raise _http_error(exc) from exc
        return JSONResponse(
            {"schema_id": "twinstudio.workspace-file/v1", "file": uploaded},
            status_code=201,
        )

    @router.post("/{target_project_id}/merge")
    def merge_workspaces(
        target_project_id: str,
        body: WorkspaceMergeRequest,
        user: Any = Depends(principal_dependency),
    ) -> dict[str, object]:
        permission = "change.apply" if body.apply else "project.read"
        authorize(target_project_id, user, permission)
        authorize(body.source_project_id, user, "project.read")
        try:
            if not body.apply:
                return store.merge_plan(
                    target_project_id,
                    body.source_project_id,
                    conflict_strategy=body.conflict_strategy,
                )
            require_writes()
            if body.plan_sha256 is None:
                raise HTTPException(
                    422,
                    {
                        "code": "PROJECT_MERGE_PLAN_REQUIRED",
                        "message": "Apply requires the previously displayed plan hash",
                    },
                )
            result = store.merge(
                target_project_id,
                body.source_project_id,
                conflict_strategy=body.conflict_strategy,
                expected_plan_sha256=body.plan_sha256,
            )
            return {"schema_id": "twinstudio.workspace-merge-result/v1", **result}
        except ProjectPackageError as exc:
            raise _http_error(exc) from exc

    @router.get("/{project_id}/files/{relative:path}")
    def workspace_file(
        project_id: str,
        relative: str,
        download: bool = Query(default=False),
        user: Any = Depends(principal_dependency),
    ) -> Response:
        authorize(project_id, user, "project.read")
        try:
            path = store.resolve_file(project_id, relative)
        except ProjectPackageError as exc:
            raise _http_error(exc) from exc
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        disposition = {"Content-Disposition": f'attachment; filename="{path.name}"'} if download else {}
        return Response(
            path.read_bytes(),
            media_type=media_type,
            headers={
                **disposition,
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
