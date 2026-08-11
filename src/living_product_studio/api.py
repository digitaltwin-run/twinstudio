from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from living_product_studio.artifacts import export_project_bundle
from living_product_studio.auth import AuthService
from living_product_studio.bus import CommandBus, CommandRejected, QueryService
from living_product_studio.change_planner import ChangePlanner
from living_product_studio.domain import (
    Annotation,
    AuthPrincipal,
    CommandEnvelope,
    InvitationRequest,
    RegionSelection,
    Role,
)
from living_product_studio.event_store import ConcurrencyError, EventStore
from living_product_studio.mcp_gateway import McpGateway
from living_product_studio.mcp_protocol import (
    McpHttpError,
    classify_mcp_era,
    origin_is_allowed,
    validate_modern_http_request,
)
from living_product_studio.mqtt_bus import publisher_from_settings
from living_product_studio.permissions import PermissionDenied, require_permission
from living_product_studio.projector import ProjectNotFound
from living_product_studio.seed import seed_from_file
from living_product_studio.selection_resolver import resolve_selection
from living_product_studio.settings import settings
from living_product_studio.simulations import (
    evaluate_human_scenario,
    mechanical_rule_checks,
    simulate_power,
    simulate_thermal,
)
from living_product_studio.specification import unified_specification


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
EXAMPLES_ROOT = PROJECT_ROOT / "examples"

store = EventStore(settings.database_url)
publisher = publisher_from_settings(settings)
queries = QueryService(store)
commands = CommandBus(store, publisher)
planner = ChangePlanner(settings)
auth = AuthService(settings, store, queries, commands, publisher)
mcp_gateway = McpGateway(queries, commands, planner, settings.data_dir / "artifacts", PROJECT_ROOT)

app = FastAPI(
    title="Living Product Studio",
    version="0.3.0",
    description="CQRS+ES living-product platform with scoped NL→2D→3D changes and lifecycle simulations.",
)
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")
if EXAMPLES_ROOT.exists():
    app.mount("/examples", StaticFiles(directory=EXAMPLES_ROOT), name="examples")


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CommandRequest(ApiModel):
    command_type: str
    expected_version: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AnnotationRequest(ApiModel):
    text: str = Field(min_length=1, max_length=30_000)
    selection: RegionSelection


class ChangePlanRequest(ApiModel):
    prompt: str = Field(min_length=1, max_length=30_000)
    selection: RegionSelection


class ThermalRequest(ApiModel):
    power_by_uri_w: dict[str, float]
    duration_s: float = Field(default=600.0, gt=0.0, le=86_400.0)
    sample_every_s: float = Field(default=10.0, gt=0.0, le=3600.0)


class AccessRequest(ApiModel):
    project_id: str
    requested_email: str
    requested_role: Role = Role.READER
    decision_email: str | None = None
    message: str = ""


class WsHub:
    def __init__(self) -> None:
        self.clients: dict[str, set[WebSocket]] = {}

    async def connect(self, project_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.clients.setdefault(project_id, set()).add(websocket)

    def disconnect(self, project_id: str, websocket: WebSocket) -> None:
        self.clients.get(project_id, set()).discard(websocket)

    async def broadcast(self, project_id: str, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for client in self.clients.get(project_id, set()):
            try:
                await client.send_json(payload)
            except Exception:
                stale.append(client)
        for client in stale:
            self.disconnect(project_id, client)


hub = WsHub()


@app.on_event("startup")
def startup_seed() -> None:
    example = EXAMPLES_ROOT / "rpi5-camera3" / "project.json"
    if example.exists() and store.current_version("demo-rpi5") == 0:
        seed_from_file(store, publisher, example)


@app.exception_handler(ProjectNotFound)
def project_not_found(_: Request, exc: ProjectNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(PermissionDenied)
def permission_denied(_: Request, exc: PermissionDenied) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(ConcurrencyError)
def concurrency_error(_: Request, exc: ConcurrencyError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(CommandRejected)
def command_rejected(_: Request, exc: CommandRejected) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


def principal(request: Request) -> AuthPrincipal:
    return auth.principal_from_request(request)


def authorize_project(project_id: str, principal_value: AuthPrincipal, permission: str) -> Role:
    snapshot = queries.project(project_id)
    role = snapshot.memberships.get(principal_value.email.lower())
    require_permission(role, permission)
    return Role(role)


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": "0.3.0",
        "database": settings.database_url.split(":", 1)[0],
        "mqtt_enabled": settings.mqtt_enabled,
        "litellm_configured": bool(settings.litellm_model),
        "dev_auth_bypass": settings.dev_auth_bypass,
    }


@app.get("/api/v1/me")
def me(user: AuthPrincipal = Depends(principal)) -> dict[str, Any]:
    return user.model_dump(mode="json")


@app.get("/api/v1/projects")
def list_projects(user: AuthPrincipal = Depends(principal)) -> list[dict[str, Any]]:
    result = []
    for item in queries.projects():
        snapshot = queries.project(item["project_id"])
        role = snapshot.memberships.get(user.email.lower())
        if role:
            result.append({**item, "role": role})
    return result


@app.get("/api/v1/projects/{project_id}")
def get_project(project_id: str, user: AuthPrincipal = Depends(principal)) -> dict[str, Any]:
    role = authorize_project(project_id, user, "project.read")
    snapshot = queries.project(project_id)
    return {"role": role, "project": snapshot.model_dump(mode="json")}


@app.get("/api/v1/projects/{project_id}/tree")
def get_tree(project_id: str, user: AuthPrincipal = Depends(principal)) -> dict[str, Any]:
    role = authorize_project(project_id, user, "project.read")
    return {"role": role, "tree": queries.tree(project_id)}


@app.get("/api/v1/projects/{project_id}/specification")
def get_specification(project_id: str, user: AuthPrincipal = Depends(principal)) -> dict[str, Any]:
    authorize_project(project_id, user, "project.read")
    return unified_specification(queries.project(project_id))


@app.get("/api/v1/projects/{project_id}/events")
def get_events(project_id: str, user: AuthPrincipal = Depends(principal)) -> list[dict[str, Any]]:
    authorize_project(project_id, user, "project.read")
    return [item.model_dump(mode="json") for item in queries.events(project_id)]


@app.post("/api/v1/projects/{project_id}/commands")
async def execute_command(
    project_id: str,
    body: CommandRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    expected = body.expected_version
    if expected is None and body.command_type != "project.create":
        expected = store.current_version(project_id)
    stored = commands.execute(
        CommandEnvelope(
            command_type=body.command_type,
            project_id=project_id,
            expected_version=expected,
            actor=user.email,
            payload=body.payload,
        )
    )
    payload = {"events": [event.model_dump(mode="json") for event in stored]}
    await hub.broadcast(project_id, payload)
    return payload


@app.post("/api/v1/projects/{project_id}/selections/resolve")
async def resolve_project_selection(
    project_id: str,
    body: RegionSelection,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "change.plan")
    snapshot = queries.project(project_id)
    selection = body.model_copy(update={"created_by": user.email, "project_id": project_id})
    resolved = resolve_selection(selection, snapshot, actor=user.email)
    stored = commands.execute(
        CommandEnvelope(
            command_type="selection_map.record",
            project_id=project_id,
            expected_version=snapshot.stream_version,
            actor=user.email,
            payload={"selection_map": resolved.model_dump(mode="json")},
        )
    )
    await hub.broadcast(project_id, {"events": [item.model_dump(mode="json") for item in stored]})
    return resolved.model_dump(mode="json")


@app.post("/api/v1/projects/{project_id}/annotations")
async def create_annotation(
    project_id: str,
    body: AnnotationRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "annotation.create")
    snapshot = queries.project(project_id)
    selection = body.selection.model_copy(update={"created_by": user.email, "project_id": project_id})
    annotation = Annotation(
        uri=selection.uri.replace("/region/", "/annotation/"),
        selection=selection,
        text=body.text,
        created_by=user.email,
    )
    stored = commands.execute(
        CommandEnvelope(
            command_type="annotation.create",
            project_id=project_id,
            expected_version=snapshot.stream_version,
            actor=user.email,
            payload={"annotation": annotation.model_dump(mode="json")},
        )
    )
    await hub.broadcast(project_id, {"events": [item.model_dump(mode="json") for item in stored]})
    return annotation.model_dump(mode="json")


@app.post("/api/v1/projects/{project_id}/change-plans")
async def create_change_plan(
    project_id: str,
    body: ChangePlanRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "change.plan")
    snapshot = queries.project(project_id)
    selection = body.selection.model_copy(update={"created_by": user.email, "project_id": project_id})
    result = planner.plan(body.prompt, selection, snapshot, user.email)
    stored = commands.execute(
        CommandEnvelope(
            command_type="change.plan.record",
            project_id=project_id,
            expected_version=snapshot.stream_version,
            actor=user.email,
            payload={"plan": result.plan.model_dump(mode="json")},
        )
    )
    await hub.broadcast(project_id, {"events": [item.model_dump(mode="json") for item in stored]})
    return {"mode": result.mode, "message": result.message, "plan": result.plan.model_dump(mode="json")}


@app.post("/api/v1/projects/{project_id}/change-plans/{plan_id}/apply")
async def apply_change_plan(
    project_id: str,
    plan_id: str,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    role = authorize_project(project_id, user, "change.apply")
    snapshot = queries.project(project_id)
    if plan_id not in snapshot.change_plans:
        raise HTTPException(status_code=404, detail="Change plan not found")
    plan = snapshot.change_plans[plan_id]
    payload = planner.compile_apply_payload(plan, snapshot)
    payload["approval_state"] = "approved" if role in {Role.ADMIN, Role.CREATOR} else "draft"
    stored = commands.execute(
        CommandEnvelope(
            command_type="change.apply",
            project_id=project_id,
            expected_version=snapshot.stream_version,
            actor=user.email,
            payload=payload,
        )
    )
    await hub.broadcast(project_id, {"events": [item.model_dump(mode="json") for item in stored]})
    return {"result": payload, "events": [item.model_dump(mode="json") for item in stored]}


@app.post("/api/v1/projects/{project_id}/simulations/power")
def run_power(project_id: str, user: AuthPrincipal = Depends(principal)) -> dict[str, Any]:
    authorize_project(project_id, user, "simulation.run")
    snapshot = queries.project(project_id)
    if not snapshot.power_model:
        raise HTTPException(status_code=422, detail="Project has no power model")
    return simulate_power(snapshot.power_model)


@app.post("/api/v1/projects/{project_id}/simulations/thermal")
def run_thermal(
    project_id: str,
    body: ThermalRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "simulation.run")
    snapshot = queries.project(project_id)
    if not snapshot.thermal_model:
        raise HTTPException(status_code=422, detail="Project has no thermal model")
    return simulate_thermal(
        snapshot.thermal_model,
        body.power_by_uri_w,
        duration_s=body.duration_s,
        sample_every_s=body.sample_every_s,
    )


@app.get("/api/v1/projects/{project_id}/simulations/human")
def run_human(project_id: str, user: AuthPrincipal = Depends(principal)) -> list[dict[str, Any]]:
    authorize_project(project_id, user, "simulation.run")
    return [evaluate_human_scenario(item) for item in queries.project(project_id).human_scenarios]


@app.get("/api/v1/projects/{project_id}/checks/mechanical")
def mechanical_checks(project_id: str, user: AuthPrincipal = Depends(principal)) -> list[dict[str, Any]]:
    authorize_project(project_id, user, "project.read")
    return mechanical_rule_checks(queries.project(project_id).model_dump(mode="json"))


@app.get("/api/v1/projects/{project_id}/artifacts/{artifact_key:path}")
def download_artifact(
    project_id: str,
    artifact_key: str,
    user: AuthPrincipal = Depends(principal),
) -> FileResponse:
    authorize_project(project_id, user, "artifact.download")
    snapshot = queries.project(project_id)
    artifact_uri = next((uri for uri in snapshot.artifacts if uri.endswith("/artifact/" + artifact_key)), None)
    if not artifact_uri:
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact = snapshot.artifacts[artifact_uri]
    path = _resolved_artifact_path(artifact.path)
    return FileResponse(path, media_type=artifact.media_type, filename=artifact.name)


@app.get("/api/v1/projects/{project_id}/export")
def export_project(project_id: str, user: AuthPrincipal = Depends(principal)) -> FileResponse:
    authorize_project(project_id, user, "artifact.download")
    snapshot = queries.project(project_id)
    path = settings.data_dir / "artifacts" / f"{project_id}-{snapshot.revision}.lps.zip"
    export_project_bundle(snapshot, queries.events(project_id), path, project_root=PROJECT_ROOT)
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.post("/api/v1/access-requests", status_code=202)
def request_access(body: AccessRequest) -> dict[str, Any]:
    result = auth.request_access(
        InvitationRequest(
            project_id=body.project_id,
            requested_email=body.requested_email,
            requested_role=body.requested_role,
            message=body.message,
        ),
        requested_by=body.requested_email,
        decision_email=body.decision_email,
    )
    return result.__dict__


@app.get("/auth/invitations/approve")
def approve_invitation(token: str) -> HTMLResponse:
    row = auth.approve(token)
    return HTMLResponse(f"<h1>Access approved</h1><p>An access link was sent to {row['requested_email']}.</p>")


@app.get("/auth/invitations/reject")
def reject_invitation(token: str) -> HTMLResponse:
    row = auth.reject(token)
    return HTMLResponse(f"<h1>Access rejected</h1><p>Request for {row['requested_email']} was rejected.</p>")


@app.get("/auth/invitations/accept")
def accept_invitation(token: str) -> Response:
    result = auth.accept(token)
    response = HTMLResponse(
        "<h1>Access granted</h1>"
        f"<p>Account: {result['email']}</p>"
        f"<p>Role: {result['role']}</p>"
        "<p>Your API token is shown once below. Store it securely:</p>"
        f"<pre>{result['api_token']}</pre><p><a href='/'>Open Living Product Studio</a></p>"
    )
    response.set_cookie("lps_session", result["session"], httponly=True, secure=False, samesite="lax")
    return response


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> Response:
    origin = request.headers.get("Origin")
    if origin and not origin_is_allowed(origin, settings.mcp_allowed_origins):
        return JSONResponse(
            status_code=403,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32000, "message": "Forbidden Origin"},
            },
        )

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid Request"},
            },
        )

    era = classify_mcp_era(payload, request.headers)
    if era == "modern":
        try:
            validate_modern_http_request(payload, request.headers)
        except McpHttpError as exc:
            return JSONResponse(status_code=exc.status_code, content=exc.as_response(payload.get("id")))
    else:
        header_method = request.headers.get("Mcp-Method")
        header_name = request.headers.get("Mcp-Name")
        body_method = payload.get("method")
        if header_method and header_method != body_method:
            return JSONResponse(
                status_code=400,
                content={
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "error": {"code": -32020, "message": "Mcp-Method header does not match JSON-RPC method"},
                },
            )
        if body_method == "tools/call" and header_name and header_name != (payload.get("params") or {}).get("name"):
            return JSONResponse(
                status_code=400,
                content={
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "error": {"code": -32020, "message": "Mcp-Name header does not match tool name"},
                },
            )

    user = auth.principal_from_request(request)
    result = mcp_gateway.handle(payload, user, modern=era == "modern")
    if not result:
        return Response(status_code=202)

    status_code = 200
    error_code = (result.get("error") or {}).get("code")
    if era == "modern":
        if error_code == -32601:
            status_code = 404
        elif error_code in {-32600, -32602, -32020, -32021, -32022}:
            status_code = 400
        elif error_code == -32603:
            status_code = 500
    return JSONResponse(result, status_code=status_code)


@app.websocket("/ws/projects/{project_id}")
async def project_socket(websocket: WebSocket, project_id: str) -> None:
    await hub.connect(project_id, websocket)
    try:
        await websocket.send_json({"type": "connected", "project_id": project_id})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(project_id, websocket)


def _resolved_artifact_path(raw: str) -> Path:
    path = Path(raw)
    candidates = [path] if path.is_absolute() else [PROJECT_ROOT / path, settings.data_dir / path]
    roots = [PROJECT_ROOT.resolve(), settings.data_dir.resolve()]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and any(resolved == root or root in resolved.parents for root in roots):
            return resolved
    raise HTTPException(status_code=404, detail="Artifact file is unavailable")
