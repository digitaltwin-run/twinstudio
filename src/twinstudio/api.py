from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from twinstudio import __version__
from twinstudio.artifacts import export_project_bundle
from twinstudio.auth import AuthService
from twinstudio.bus import CommandBus, CommandRejected, QueryService
from twinstudio.change_planner import ChangePlanner
from twinstudio.domain import (
    Annotation,
    ArtifactRecord,
    AuthPrincipal,
    ChangePlan,
    CommandEnvelope,
    InvitationRequest,
    RegionSelection,
    Role,
)
from twinstudio.dsl import (
    canonical_dsl_grammar,
    canonical_dsl_schema,
    compile_dsl,
    make_execution_record,
    parse_dsl,
    safe_parameter_patches,
    write_evolution_artifacts,
)
from twinstudio.evolution import ProjectEvolutionEngine, graph_to_dot, graph_to_mermaid, load_evolution_catalog
from twinstudio.evolution_models import (
    DslSeverity,
    EvolutionRun,
    LifecycleBlueprint,
    LifecycleHistoryEntry,
    LifecycleTransitionRequest,
    RealizationMode,
    TwinDslDocument,
)
from twinstudio.event_store import ConcurrencyError, EventStore
from twinstudio.feature_lenses import FeatureLensEngine
from twinstudio.mcp_gateway import McpGateway
from twinstudio.mcp_protocol import (
    McpHttpError,
    classify_mcp_era,
    origin_is_allowed,
    validate_modern_http_request,
)
from twinstudio.mqtt_bus import publisher_from_settings
from twinstudio.permissions import PermissionDenied, require_permission
from twinstudio.projector import ProjectNotFound
from twinstudio.seed import seed_from_file
from twinstudio.selection_resolver import resolve_selection
from twinstudio.settings import settings
from twinstudio.simulations import (
    evaluate_human_scenario,
    mechanical_rule_checks,
    simulate_power,
    simulate_thermal,
)
from twinstudio.specification import unified_specification


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
EXAMPLES_ROOT = PROJECT_ROOT / "examples"

store = EventStore(settings.database_url)
publisher = publisher_from_settings(settings)
queries = QueryService(store)
commands = CommandBus(store, publisher)
planner = ChangePlanner(settings)
feature_lenses = FeatureLensEngine(settings)
evolution_engine = ProjectEvolutionEngine(settings)
auth = AuthService(settings, store, queries, commands, publisher)
mcp_gateway = McpGateway(
    queries, commands, planner, feature_lenses, evolution_engine, settings.data_dir / "artifacts", PROJECT_ROOT
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    example = EXAMPLES_ROOT / "rpi5-camera3" / "project.json"
    if example.exists() and store.current_version("demo-rpi5") == 0:
        seed_from_file(store, publisher, example)
    yield


app = FastAPI(
    title="TwinStudio",
    version=__version__,
    description=(
        "CQRS+ES digital-thread platform with scoped NL→2D→3D changes, source-grounded "
        "design-fixation reviews, lifecycle simulations and artifact generation."
    ),
    lifespan=lifespan,
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


class DesignFixationScanRequest(ApiModel):
    target_uri: str = Field(min_length=8, max_length=2000)
    challenge: str = Field(default="", max_length=30_000)
    lens_ids: list[str] = Field(default_factory=list, max_length=50)
    max_alternatives: int = Field(default=8, ge=1, le=20)
    use_llm: bool = True
    record: bool = True


class DslSourceRequest(ApiModel):
    source: str = Field(min_length=1, max_length=500_000)
    source_format: str = Field(default="auto", pattern="^(auto|twin|yaml|json)$")


class DslApplyRequest(DslSourceRequest):
    dry_run: bool = True
    generate_artifacts: bool = True


class EvolutionDocumentRequest(ApiModel):
    document: TwinDslDocument
    record: bool = False
    generate_artifacts: bool = False


class CandidatePlanRequest(ApiModel):
    record: bool = True


class LifecycleTransitionApiRequest(LifecycleTransitionRequest):
    force: bool = False


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


def _compilation_payload(compilation, execution=None) -> dict[str, Any]:
    payload = compilation.model_dump(mode="json")
    if execution is not None:
        payload["execution"] = execution.model_dump(mode="json")
    return payload


def _run_command(
    project_id: str,
    command_type: str,
    actor: str,
    payload: dict[str, Any],
) -> list[Any]:
    return commands.execute(
        CommandEnvelope(
            command_type=command_type,
            project_id=project_id,
            expected_version=store.current_version(project_id),
            actor=actor,
            payload=payload,
        )
    )


def _transition_evidence_gaps(
    snapshot,
    blueprint: LifecycleBlueprint,
    request: LifecycleTransitionApiRequest,
) -> tuple[Any, list[str]]:
    current = blueprint.current_stage
    transition = next(
        (item for item in blueprint.transitions if item.from_stage == current and item.to_stage == request.to_stage),
        None,
    )
    if transition is None:
        raise HTTPException(
            status_code=422,
            detail=f"No lifecycle transition from {current!s} to {request.to_stage!s} in blueprint {blueprint.blueprint_id}.",
        )
    supplied = [uri for uri in request.evidence_artifact_uris if uri in snapshot.artifacts]
    unknown = [uri for uri in request.evidence_artifact_uris if uri not in snapshot.artifacts]
    gaps: list[str] = []
    if transition.conditions and not supplied:
        gaps.extend(transition.conditions)
    if unknown:
        gaps.append("Unknown evidence artifact URIs: " + ", ".join(unknown))
    stage = next((item for item in blueprint.stages if item.stage == current), None)
    if stage and stage.required_artifact_kinds:
        present_kinds = {snapshot.artifacts[uri].kind for uri in supplied}
        missing_kinds = [kind for kind in stage.required_artifact_kinds if kind not in present_kinds]
        if missing_kinds:
            gaps.append("Missing evidence artifact kinds: " + ", ".join(str(item) for item in missing_kinds))
    return transition, gaps


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
        "version": __version__,
        "database": settings.database_url.split(":", 1)[0],
        "mqtt_enabled": settings.mqtt_enabled,
        "litellm_configured": bool(settings.litellm_model),
        "dev_auth_bypass": settings.dev_auth_bypass,
        "feature_lens_catalog": feature_lenses.catalog.catalog_version,
        "feature_lens_count": feature_lenses.catalog.active_lens_count,
        "evolution_catalog": evolution_engine.catalog.catalog_version,
        "evolution_dimensions": len(evolution_engine.catalog.extension_dimensions),
        "dsl_api_version": "twinstudio.io/v1alpha1",
    }


@app.get("/api/v1/me")
def me(user: AuthPrincipal = Depends(principal)) -> dict[str, Any]:
    return user.model_dump(mode="json")


@app.get("/api/v1/feature-lenses")
def get_feature_lenses(
    include_disabled: bool = False,
    _: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    payload = feature_lenses.catalog.model_dump(mode="json")
    if not include_disabled:
        payload["lenses"] = [item for item in payload["lenses"] if item["enabled"]]
    return payload


@app.get("/api/v1/evolution/catalog")
def get_evolution_catalog(_: AuthPrincipal = Depends(principal)) -> dict[str, Any]:
    return evolution_engine.catalog.model_dump(mode="json")


@app.get("/api/v1/dsl/schema")
def get_dsl_schema(_: AuthPrincipal = Depends(principal)) -> dict[str, Any]:
    return canonical_dsl_schema()


@app.get("/api/v1/dsl/grammar", response_class=Response)
def get_dsl_grammar(_: AuthPrincipal = Depends(principal)) -> Response:
    try:
        content = canonical_dsl_grammar()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=content, media_type="text/plain; charset=utf-8")


@app.post("/api/v1/dsl/parse")
def parse_dsl_endpoint(
    body: DslSourceRequest,
    _: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    parsed = parse_dsl(body.source, source_format=body.source_format)
    return {
        "valid": parsed.valid,
        "source_format": parsed.source_format,
        "document": parsed.document.model_dump(mode="json") if parsed.document else None,
        "diagnostics": [item.model_dump(mode="json") for item in parsed.diagnostics],
    }


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


@app.get("/api/v1/projects/{project_id}/design-fixation/reviews")
def get_design_fixation_reviews(
    project_id: str,
    user: AuthPrincipal = Depends(principal),
) -> list[dict[str, Any]]:
    authorize_project(project_id, user, "project.read")
    snapshot = queries.project(project_id)
    return [item.model_dump(mode="json") for item in snapshot.design_fixation_reviews.values()]


@app.post("/api/v1/projects/{project_id}/design-fixation/scan")
async def run_design_fixation_scan(
    project_id: str,
    body: DesignFixationScanRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "change.plan")
    snapshot = queries.project(project_id)
    result = feature_lenses.scan(
        snapshot,
        target_uri=body.target_uri,
        challenge=body.challenge,
        actor=user.email,
        lens_ids=body.lens_ids or None,
        max_alternatives=body.max_alternatives,
        use_llm=body.use_llm,
    )
    events: list[dict[str, Any]] = []
    if body.record:
        stored = commands.execute(
            CommandEnvelope(
                command_type="design_fixation.review.record",
                project_id=project_id,
                expected_version=snapshot.stream_version,
                actor=user.email,
                payload={"review": result.review.model_dump(mode="json")},
            )
        )
        events = [item.model_dump(mode="json") for item in stored]
        await hub.broadcast(project_id, {"events": events})
    return {
        "mode": result.mode,
        "message": result.message,
        "review": result.review.model_dump(mode="json"),
        "events": events,
    }


@app.get("/api/v1/projects/{project_id}/evolution/runs")
def list_evolution_runs(
    project_id: str,
    user: AuthPrincipal = Depends(principal),
) -> list[dict[str, Any]]:
    authorize_project(project_id, user, "project.read")
    snapshot = queries.project(project_id)
    return list(snapshot.evolution_runs.values())


@app.get("/api/v1/projects/{project_id}/evolution/runs/{run_id}")
def get_evolution_run(
    project_id: str,
    run_id: str,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "project.read")
    run = queries.project(project_id).evolution_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Evolution run not found")
    return run


@app.post("/api/v1/projects/{project_id}/evolution/preview")
def preview_evolution_document(
    project_id: str,
    body: EvolutionDocumentRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "change.plan")
    if body.document.spec.project_id != project_id:
        raise HTTPException(status_code=422, detail="Document project_id does not match API path")
    snapshot = queries.project(project_id)
    compilation = compile_dsl(snapshot, body.document, evolution_engine, actor=user.email)
    execution = make_execution_record(
        snapshot,
        body.document.model_dump_json(indent=2),
        "json",
        body.document,
        compilation,
        actor=user.email,
        dry_run=True,
    )
    return _compilation_payload(compilation, execution)


@app.post("/api/v1/projects/{project_id}/dsl/preview")
def preview_project_dsl(
    project_id: str,
    body: DslSourceRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "change.plan")
    parsed = parse_dsl(body.source, source_format=body.source_format)
    if not parsed.document:
        return {
            "valid": False,
            "source_format": parsed.source_format,
            "diagnostics": [item.model_dump(mode="json") for item in parsed.diagnostics],
        }
    if parsed.document.spec.project_id != project_id:
        return {
            "valid": False,
            "source_format": parsed.source_format,
            "diagnostics": [
                *[item.model_dump(mode="json") for item in parsed.diagnostics],
                {
                    "severity": "blocking",
                    "code": "project.path_mismatch",
                    "message": f"DSL project {parsed.document.spec.project_id!r} does not match API path {project_id!r}.",
                    "path": "spec.project_id",
                    "hint": "Change PROJECT in TwinScript or spec.project_id in YAML/JSON.",
                },
            ],
        }
    snapshot = queries.project(project_id)
    compilation = compile_dsl(snapshot, parsed.document, evolution_engine, actor=user.email)
    execution = make_execution_record(
        snapshot,
        body.source,
        parsed.source_format,
        parsed.document,
        compilation,
        actor=user.email,
        dry_run=True,
    )
    payload = _compilation_payload(compilation, execution)
    payload["source_format"] = parsed.source_format
    return payload


@app.post("/api/v1/projects/{project_id}/dsl/apply")
async def apply_project_dsl(
    project_id: str,
    body: DslApplyRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "change.plan")
    parsed = parse_dsl(body.source, source_format=body.source_format)
    if not parsed.document:
        return {
            "valid": False,
            "source_format": parsed.source_format,
            "diagnostics": [item.model_dump(mode="json") for item in parsed.diagnostics],
            "events": [],
        }
    if parsed.document.spec.project_id != project_id:
        raise HTTPException(status_code=422, detail="DSL project_id does not match API path")
    snapshot = queries.project(project_id)
    compilation = compile_dsl(snapshot, parsed.document, evolution_engine, actor=user.email)
    execution = make_execution_record(
        snapshot,
        body.source,
        parsed.source_format,
        parsed.document,
        compilation,
        actor=user.email,
        dry_run=body.dry_run,
    )
    if body.dry_run or not compilation.valid:
        payload = _compilation_payload(compilation, execution)
        payload["source_format"] = parsed.source_format
        payload["events"] = []
        return payload

    stored_events: list[Any] = []
    if compilation.evolution_run:
        stored_events.extend(
            _run_command(
                project_id,
                "evolution.run.record",
                user.email,
                {"run": compilation.evolution_run.model_dump(mode="json")},
            )
        )
    if compilation.lifecycle_blueprint:
        stored_events.extend(
            _run_command(
                project_id,
                "lifecycle.blueprint.upsert",
                user.email,
                {"blueprint": compilation.lifecycle_blueprint.model_dump(mode="json")},
            )
        )
    for plan_data in compilation.change_plans:
        plan = ChangePlan.model_validate(plan_data)
        stored_events.extend(
            _run_command(project_id, "change.plan.record", user.email, {"plan": plan.model_dump(mode="json")})
        )

    safe_patches = safe_parameter_patches(parsed.document)
    auto_apply = (
        parsed.document.spec.realization.mode == RealizationMode.AUTO_APPLY_SAFE
        and not parsed.document.spec.realization.dry_run
        and not parsed.document.spec.realization.require_approval
        and bool(safe_patches)
        and len(safe_patches) == len(parsed.document.spec.explicit_changes)
    )
    if auto_apply:
        authorize_project(project_id, user, "change.apply")
        current = queries.project(project_id)
        stored_events.extend(
            _run_command(
                project_id,
                "change.apply",
                user.email,
                {
                    "new_revision": f"{current.revision}-dsl-{execution.execution_id[-8:]}",
                    "parameter_patches": safe_patches,
                    "approval_state": "approved",
                    "dsl_execution_id": execution.execution_id,
                },
            )
        )

    execution = execution.model_copy(
        update={
            "status": "executed" if not compilation.change_plans or auto_apply else "partially_executed",
            "event_ids": [item.event_id for item in stored_events],
        }
    )
    artifacts: list[ArtifactRecord] = []
    artifact_keys: dict[str, str] = {}
    if body.generate_artifacts and parsed.document.spec.outputs.persist_artifacts:
        artifacts, artifact_keys = write_evolution_artifacts(
            settings.data_dir / "artifacts", snapshot, compilation, execution
        )
        for artifact in artifacts:
            attached = _run_command(
                project_id,
                "artifact.attach",
                user.email,
                {"artifact": artifact.model_dump(mode="json")},
            )
            stored_events.extend(attached)
    stored_events.extend(
        _run_command(
            project_id,
            "dsl.execution.record",
            user.email,
            {"execution": execution.model_dump(mode="json")},
        )
    )
    events_payload = [item.model_dump(mode="json") for item in stored_events]
    await hub.broadcast(project_id, {"events": events_payload})
    payload = _compilation_payload(compilation, execution)
    payload.update(
        {
            "source_format": parsed.source_format,
            "events": events_payload,
            "artifact_keys": artifact_keys,
            "auto_applied_parameter_patches": safe_patches if auto_apply else [],
        }
    )
    return payload


@app.get("/api/v1/projects/{project_id}/evolution/runs/{run_id}/graph")
def get_evolution_graph(
    project_id: str,
    run_id: str,
    format: str = "json",
    user: AuthPrincipal = Depends(principal),
) -> Response:
    authorize_project(project_id, user, "project.read")
    raw = queries.project(project_id).evolution_runs.get(run_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Evolution run not found")
    run = EvolutionRun.model_validate(raw)
    normalized = format.lower()
    if normalized == "json":
        return JSONResponse(run.graph.model_dump(mode="json"))
    if normalized == "dot":
        return Response(graph_to_dot(run.graph), media_type="text/vnd.graphviz; charset=utf-8")
    if normalized == "mermaid":
        return Response(graph_to_mermaid(run.graph), media_type="text/plain; charset=utf-8")
    raise HTTPException(status_code=422, detail="format must be json, dot or mermaid")


@app.post("/api/v1/projects/{project_id}/evolution/runs/{run_id}/candidates/{candidate_id}/change-plan")
async def candidate_to_change_plan(
    project_id: str,
    run_id: str,
    candidate_id: str,
    body: CandidatePlanRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "change.plan")
    snapshot = queries.project(project_id)
    raw = snapshot.evolution_runs.get(run_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Evolution run not found")
    run = EvolutionRun.model_validate(raw)
    plan = evolution_engine.candidate_change_plan(snapshot, run, candidate_id, actor=user.email)
    events: list[dict[str, Any]] = []
    if body.record:
        stored = _run_command(
            project_id, "change.plan.record", user.email, {"plan": plan.model_dump(mode="json")}
        )
        events = [item.model_dump(mode="json") for item in stored]
        await hub.broadcast(project_id, {"events": events})
    return {"plan": plan.model_dump(mode="json"), "events": events}


@app.get("/api/v1/projects/{project_id}/lifecycles")
def list_lifecycle_blueprints(
    project_id: str,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "project.read")
    snapshot = queries.project(project_id)
    return {
        "current_project_stage": snapshot.lifecycle_stage,
        "blueprints": list(snapshot.lifecycle_blueprints.values()),
        "history": snapshot.lifecycle_history,
    }


@app.post("/api/v1/projects/{project_id}/lifecycles/transition")
async def transition_lifecycle(
    project_id: str,
    body: LifecycleTransitionApiRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    permission = "approval.grant" if body.approve or body.force else "change.plan"
    authorize_project(project_id, user, permission)
    snapshot = queries.project(project_id)
    raw = snapshot.lifecycle_blueprints.get(body.blueprint_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Lifecycle blueprint not found")
    blueprint = LifecycleBlueprint.model_validate(raw)
    _, gaps = _transition_evidence_gaps(snapshot, blueprint, body)
    status = "requested"
    approved_by = None
    if body.approve:
        if gaps and not body.force:
            status = "blocked"
        else:
            status = "approved"
            approved_by = user.email
    entry = LifecycleHistoryEntry(
        blueprint_id=blueprint.blueprint_id,
        from_stage=blueprint.current_stage,
        to_stage=body.to_stage,
        rationale=body.rationale,
        evidence_artifact_uris=body.evidence_artifact_uris,
        unmet_criteria=gaps,
        approved_by=approved_by,
        status=status,
    )
    stored = _run_command(
        project_id,
        "lifecycle.transition.record",
        user.email,
        {"transition": entry.model_dump(mode="json")},
    )
    events = [item.model_dump(mode="json") for item in stored]
    await hub.broadcast(project_id, {"events": events})
    return {"transition": entry.model_dump(mode="json"), "events": events}


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
    path = settings.data_dir / "artifacts" / f"{project_id}-{snapshot.revision}{settings.export_extension}"
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
        f"<pre>{result['api_token']}</pre><p><a href='/'>Open TwinStudio</a></p>"
    )
    response.set_cookie("twinstudio_session", result["session"], httponly=True, secure=False, samesite="lax")
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
