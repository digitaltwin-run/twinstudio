from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
from base64 import b64decode
from binascii import Error as Base64Error
from contextlib import asynccontextmanager
from importlib.metadata import version as package_version
from pathlib import Path, PurePosixPath
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from twin_projects import ProjectPackageStore

from twinstudio import __version__
from twinstudio.artifact_group_review import ArtifactGroupReview, review_artifact_group
from twinstudio.artifacts import (
    TAB_PDF_TITLES,
    export_project_bundle,
    render_drawings_pdf,
    render_tab_pdf,
)
from twinstudio.auth import AuthService
from twinstudio.bus import CommandBus, CommandRejected, QueryService
from twinstudio.cad_regeneration import (
    CadChangeInvalid,
    dimension_overrides_for_change,
    generate_project_preview,
    validate_parameter_change,
)
from twinstudio.change_planner import ChangePlanner, LlmInvalidResponse
from twinstudio.domain import (
    Annotation,
    ArtifactRecord,
    AuthPrincipal,
    ChangePlan,
    CommandEnvelope,
    EventEnvelope,
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
from twinstudio.eda_chat import EdaChatMessage, EdaChatResponse, respond_to_eda_chat
from twinstudio.eda_history import (
    EDA_EVENT_TYPES,
    EdaHistoryEntry,
    load_descriptor,
    remove_descriptor_artifact,
    store_object,
    update_descriptor,
    update_source_descriptor,
    write_event_stream,
    write_wellmanifest_projection,
)
from twinstudio.eda_history import (
    artifact_id as eda_artifact_id,
)
from twinstudio.eda_history import (
    revision_id as eda_revision_id,
)
from twinstudio.eda_operation_planner import propose_eda_operation
from twinstudio.event_store import ConcurrencyError, EventStore
from twinstudio.evolution import (
    ProjectEvolutionEngine,
    graph_to_dot,
    graph_to_mermaid,
)
from twinstudio.evolution_models import (
    EvolutionRun,
    LifecycleBlueprint,
    LifecycleHistoryEntry,
    LifecycleTransitionRequest,
    RealizationMode,
    TwinDslDocument,
)
from twinstudio.feature_lenses import FeatureLensEngine
from twinstudio.hashing import sha256_file
from twinstudio.kicad_audit import netlist_state, simulation_state
from twinstudio.kicad_dsl import (
    EdaChangeDocument,
    EdaDocument,
    EdaOperation,
    KicadDslError,
    apply_changes_with_repair,
    change_validation,
    eda_llm_status,
    inspect_file,
    nl_to_dsl,
    pcb_state,
    resolve_source,
    schematic_state,
    write_candidate,
)
from twinstudio.mcp_gateway import McpGateway
from twinstudio.mcp_protocol import (
    McpHttpError,
    classify_mcp_era,
    origin_is_allowed,
    validate_modern_http_request,
)
from twinstudio.mqtt_bus import publisher_from_settings
from twinstudio.observability import (
    UiContext,
    UiContextStore,
    emit_generation_observation,
    emit_problem,
    emit_request_observation,
    load_error_playbook,
    make_problem,
    observation_logs,
)
from twinstudio.permissions import PermissionDenied, require_permission
from twinstudio.projector import ProjectNotFound
from twinstudio.scad_dsl import (
    ScadChangeDocument,
    ScadDslError,
    apply_scad_changes,
    inspect_scad_file,
    nl_to_scad_dsl,
    resolve_scad_source,
    validate_scad,
    write_scad_candidate,
)
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
from twinstudio.svg_dsl import (
    SvgChangeDocument,
    SvgDslError,
    analyze_svg_with_llm,
    apply_svg_changes,
    inspect_svg_file,
    nl_to_svg_dsl,
    resolve_svg_source,
    write_svg_candidate,
)
from twinstudio.workspace_api import build_workspace_router

PROJECT_ROOT = settings.project_root
STATIC_ROOT = Path(__file__).resolve().parent / "static"
EXAMPLES_ROOT = PROJECT_ROOT / "examples"
ERROR_ROOT = PROJECT_ROOT / "error"

store = EventStore(settings.database_url)
workspace_store = ProjectPackageStore(
    settings.workspaces_root,
    candidates_root=settings.eda_candidates_root,
)
publisher = publisher_from_settings(settings)
queries = QueryService(store)
commands = CommandBus(store, publisher)
planner = ChangePlanner(settings)
feature_lenses = FeatureLensEngine(settings)
evolution_engine = ProjectEvolutionEngine(settings)
auth = AuthService(settings, store, queries, commands, publisher)
ui_contexts = UiContextStore()
mcp_gateway = McpGateway(
    queries,
    commands,
    planner,
    feature_lenses,
    evolution_engine,
    settings.data_dir / "artifacts",
    PROJECT_ROOT,
    ui_contexts,
    ERROR_ROOT,
)
_cad_tasks: set[asyncio.Task[Any]] = set()


@asynccontextmanager
async def lifespan(_: FastAPI):
    example = EXAMPLES_ROOT / "rpi5-camera3" / "project.json"
    if example.exists() and store.current_version("demo-rpi5") == 0:
        seed_from_file(store, publisher, example)
    try:
        yield
    finally:
        pending = list(_cad_tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


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


def _correlation_id(request: Request) -> str:
    value = getattr(request.state, "correlation_id", None)
    return str(value or uuid4())


def _request_project_id(request: Request) -> str | None:
    value = request.path_params.get("project_id")
    return str(value) if value else None


def _problem_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    project_id = _request_project_id(request)
    context = ui_contexts.get(project_id) if project_id else None
    problem = make_problem(
        code=code,
        message=message,
        source="twinstudio.api",
        operation=f"{request.method} {request.url.path}",
        correlation_id=_correlation_id(request),
        project_id=project_id,
        status_code=status_code,
        retryable=retryable,
        ui_context=context,
        artifacts=context.artifacts if context else [],
        details=details,
    )
    emit_problem(problem)
    payload = problem.model_dump(mode="json", exclude_none=True)
    payload["dsl"] = problem.to_dsl()
    return JSONResponse(
        status_code=status_code,
        content={"detail": message, "error": payload},
        headers={"X-Correlation-ID": problem.correlation_id},
    )


@app.middleware("http")
async def observe_http_request(request: Request, call_next):
    candidate = request.headers.get("X-Correlation-ID", "").strip()
    request.state.correlation_id = candidate[:128] if candidate else str(uuid4())
    started = perf_counter()
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = request.state.correlation_id
    if request.url.path != "/health":
        emit_request_observation(
            correlation_id=request.state.correlation_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=(perf_counter() - started) * 1000,
            project_id=_request_project_id(request),
        )
    return response


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


class ApplyChangePlanRequest(ApiModel):
    annotation_uri: str | None = Field(default=None, max_length=2000)


class TabPdfRequest(ApiModel):
    content_text: str = Field(default="", max_length=100_000)
    screenshot_png_data_url: str | None = Field(default=None, max_length=8_000_000)
    selected_object_uri: str | None = Field(default=None, max_length=2000)


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


class EdaNlRequest(ApiModel):
    path: str = Field(min_length=1, max_length=2000)
    prompt: str = Field(min_length=1, max_length=30_000)
    project_id: str | None = Field(default=None, min_length=1, max_length=160)
    expected_version: int | None = Field(default=None, ge=0)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    context_signature: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    context_sources: list[dict[str, Any]] = Field(default_factory=list, max_length=24)
    atomic: bool = False


class EdaOperationPlanRequest(ApiModel):
    prompt: str = Field(min_length=1, max_length=30_000)
    source: dict[str, Any]
    operations: list[dict[str, Any]] = Field(min_length=1, max_length=40)
    project_context: dict[str, Any] = Field(default_factory=dict)


class ArtifactGroupPromptRequest(ApiModel):
    group: str = Field(min_length=1, max_length=2_000)
    paths: list[str] = Field(min_length=1, max_length=40)
    prompt: str = Field(min_length=1, max_length=30_000)


class EdaChatRequest(ApiModel):
    session_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{7,79}$")
    sequence: int = Field(ge=1)
    paths: list[str] = Field(min_length=1, max_length=40)
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deterministic_context: dict[str, Any]
    messages: list[EdaChatMessage] = Field(min_length=1, max_length=40)


class EdaAnalysisRequest(ApiModel):
    path: str = Field(min_length=1, max_length=2000)
    expected_version: int | None = Field(default=None, ge=0)


class EdaSchematicAnalysisRequest(EdaAnalysisRequest):
    netlist: dict[str, Any] | None = None
    netlist_error: str | None = Field(default=None, max_length=2000)


class EdaPcbAnalysisRequest(EdaAnalysisRequest):
    drc: dict[str, Any] = Field(default_factory=dict)
    geometry: dict[str, Any] | None = None


class EdaNetlistAnalysisRequest(EdaAnalysisRequest):
    netlist: dict[str, Any] = Field(default_factory=dict)
    pcb: dict[str, Any] | None = None


class EdaSimulationAnalysisRequest(EdaAnalysisRequest):
    simulation: dict[str, Any] = Field(default_factory=dict)


class EdaApplyRequest(ApiModel):
    document: EdaChangeDocument
    dry_run: bool = True
    project_id: str | None = Field(default=None, min_length=1, max_length=160)
    expected_version: int | None = Field(default=None, ge=0)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    causation_id: str | None = Field(default=None, min_length=1, max_length=128)
    atomic: bool = False


class SvgNlRequest(ApiModel):
    path: str = Field(min_length=1, max_length=2000)
    prompt: str = Field(min_length=1, max_length=30_000)
    project_id: str | None = Field(default=None, min_length=1, max_length=160)
    expected_version: int | None = Field(default=None, ge=0)


class SvgApplyRequest(ApiModel):
    document: SvgChangeDocument
    dry_run: bool = True
    project_id: str | None = Field(default=None, min_length=1, max_length=160)
    expected_version: int | None = Field(default=None, ge=0)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)


class SvgAnalysisRequest(ApiModel):
    path: str = Field(min_length=1, max_length=2000)
    use_llm: bool = False
    expected_version: int | None = Field(default=None, ge=0)


class ScadNlRequest(ApiModel):
    path: str = Field(min_length=1, max_length=2000)
    prompt: str = Field(min_length=1, max_length=30_000)
    project_id: str | None = Field(default=None, min_length=1, max_length=160)
    expected_version: int | None = Field(default=None, ge=0)


class ScadApplyRequest(ApiModel):
    document: ScadChangeDocument
    dry_run: bool = True
    project_id: str | None = Field(default=None, min_length=1, max_length=160)
    expected_version: int | None = Field(default=None, ge=0)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)


class ScadValidationRequest(ApiModel):
    """SCAD content supplied by a trusted Viewer candidate review."""

    source: str = Field(min_length=1, max_length=2_000_000)


class EdaDecisionRequest(ApiModel):
    candidate_path: str = Field(min_length=1, max_length=2000)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_version: int | None = Field(default=None, ge=0)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    causation_id: str | None = Field(default=None, min_length=1, max_length=128)
    reason: str = Field(default="", max_length=2000)
    render_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class EdaRevertRequest(ApiModel):
    promotion_event_id: str = Field(min_length=1, max_length=128)
    expected_current_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_version: int | None = Field(default=None, ge=0)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    reason: str = Field(default="", max_length=2000)


class EdaMigrationRequest(ApiModel):
    expected_version: int | None = Field(default=None, ge=0)


class ProjectUpdateRequest(ApiModel):
    trigger: str = Field(pattern=r"^(automatic|user_prompt|validation|manual)$")
    category: str = Field(pattern=r"^(change|error|recommendation|duplicate|source_truth_conflict|inventory)$")
    summary: str = Field(min_length=1, max_length=4000)
    source_paths: list[str] = Field(default_factory=list, max_length=200)
    dedupe_key: str = Field(min_length=1, max_length=256)
    details: dict[str, Any] = Field(default_factory=dict)
    expected_version: int | None = Field(default=None, ge=0)


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


def _latest_cad_job(project_id: str) -> str | None:
    requests = [item for item in store.load(project_id) if item.event_type == "GenerationRequested"]
    return str(requests[-1].data.get("job_id")) if requests else None


def _cad_job_context(project_id: str, job_id: str) -> dict[str, Any]:
    request = next(
        (
            item
            for item in reversed(store.load(project_id))
            if item.event_type == "GenerationRequested" and item.data.get("job_id") == job_id
        ),
        None,
    )
    if request is None:
        return {}
    return {
        key: request.data.get(key)
        for key in (
            "plan_id",
            "source_event_id",
            "target_uris",
            "prompt",
            "dimension_overrides",
        )
    }


async def _complete_cad_regeneration(
    project_id: str,
    actor: str,
    job_id: str,
    snapshot,
    prompt: str,
    dimension_overrides: dict[str, float],
) -> None:
    try:
        result = await asyncio.to_thread(
            generate_project_preview,
            snapshot,
            settings.data_dir,
            job_id,
            prompt=prompt,
            dimension_overrides=dimension_overrides,
        )
        latest = _latest_cad_job(project_id)
        context = _cad_job_context(project_id, job_id)
        if latest != job_id:
            stored = _run_command(
                project_id,
                "generation.complete",
                actor,
                {
                    "job_id": job_id,
                    "status": "superseded",
                    "superseded_by": latest,
                    "artifacts": [],
                    "objects": [],
                    "manifest_path": result.manifest_path,
                    **context,
                },
            )
        else:
            stored = _run_command(
                project_id,
                "generation.complete",
                actor,
                {
                    "job_id": job_id,
                    "status": "completed",
                    "revision": snapshot.revision,
                    "manifest_path": result.manifest_path,
                    "mapped_parameters": result.mapped_parameters,
                    "artifacts": [item.model_dump(mode="json") for item in result.artifacts],
                    "objects": [item.model_dump(mode="json") for item in result.objects],
                    **context,
                },
            )
        await hub.broadcast(project_id, {"events": [item.model_dump(mode="json") for item in stored]})
        emit_generation_observation(
            code=("CAD_REGENERATION_SUPERSEDED" if latest != job_id else "CAD_REGENERATION_COMPLETED"),
            project_id=project_id,
            job_id=job_id,
            status=("superseded" if latest != job_id else "completed"),
            details={
                "revision": snapshot.revision,
                "artifact_count": len(result.artifacts),
                "manifest": result.manifest_path,
                "superseded_by": latest if latest != job_id else None,
                "dimension_overrides": dimension_overrides,
                "generated_dimensions": (
                    result.objects[0].metadata.get("cad_dimensions") if result.objects else None
                ),
            },
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        problem = make_problem(
            code="CAD_REGENERATION_FAILED",
            message=str(exc),
            source="twinstudio.cad_regeneration",
            operation="generate_project_preview",
            correlation_id=job_id,
            project_id=project_id,
            retryable=True,
            ui_context=ui_contexts.get(project_id),
            details={"job_id": job_id, "exception_type": type(exc).__name__},
        )
        emit_problem(problem)
        try:
            stored = _run_command(
                project_id,
                "generation.fail",
                actor,
                {
                    "job_id": job_id,
                    "status": "failed",
                    "code": "CAD_REGENERATION_FAILED",
                    "error": str(exc)[:4000],
                    "registry_uri": problem.registry_uri,
                    **_cad_job_context(project_id, job_id),
                },
            )
            await hub.broadcast(project_id, {"events": [item.model_dump(mode="json") for item in stored]})
        except Exception:
            return


def _queue_cad_regeneration(
    project_id: str,
    actor: str,
    *,
    source_event_id: str,
    plan_id: str | None,
    target_uris: list[str],
    prompt: str,
    dimension_overrides: dict[str, float] | None = None,
) -> tuple[dict[str, Any], list[Any]]:
    if not settings.cad_regeneration_enabled:
        return {"status": "disabled", "code": "CAD_REGENERATION_DISABLED"}, []
    snapshot = queries.project(project_id)
    job_id = f"cad-{project_id}-{snapshot.stream_version + 1}-{uuid4().hex[:8]}"
    request = {
        "job_id": job_id,
        "status": "queued",
        "revision": snapshot.revision,
        "source_event_id": source_event_id,
        "plan_id": plan_id,
        "target_uris": target_uris,
        "prompt": prompt,
        "generator": "housing-studio",
        "dimension_overrides": dimension_overrides or {},
    }
    stored = _run_command(project_id, "generation.request", actor, request)
    emit_generation_observation(
        code="CAD_REGENERATION_QUEUED",
        project_id=project_id,
        job_id=job_id,
        status="queued",
        details={
            "revision": snapshot.revision,
            "source_event_id": source_event_id,
            "target_uris": target_uris,
            "dimension_overrides": dimension_overrides or {},
        },
    )
    generation_snapshot = queries.project(project_id)
    task = asyncio.create_task(
        _complete_cad_regeneration(
            project_id,
            actor,
            job_id,
            generation_snapshot,
            prompt,
            dimension_overrides or {},
        ),
        name=f"cad-regeneration:{job_id}",
    )
    _cad_tasks.add(task)
    task.add_done_callback(_cad_tasks.discard)
    return request, stored


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
def project_not_found(request: Request, exc: ProjectNotFound) -> JSONResponse:
    return _problem_response(
        request, status_code=404, code="PROJECT_NOT_FOUND", message=str(exc)
    )


@app.exception_handler(PermissionDenied)
def permission_denied(request: Request, exc: PermissionDenied) -> JSONResponse:
    return _problem_response(
        request, status_code=403, code="PERMISSION_DENIED", message=str(exc)
    )


@app.exception_handler(ConcurrencyError)
def concurrency_error(request: Request, exc: ConcurrencyError) -> JSONResponse:
    return _problem_response(
        request,
        status_code=409,
        code="CONCURRENCY_CONFLICT",
        message=str(exc),
        retryable=True,
    )


@app.exception_handler(CadChangeInvalid)
def cad_change_invalid(request: Request, exc: CadChangeInvalid) -> JSONResponse:
    return _problem_response(
        request,
        status_code=422,
        code="CAD-CHANGE-INVALID",
        message=str(exc),
        details={"warnings": exc.warnings},
    )


@app.exception_handler(LlmInvalidResponse)
def llm_invalid_response(request: Request, exc: LlmInvalidResponse) -> JSONResponse:
    return _problem_response(
        request,
        status_code=502,
        code="LLM-INVALID-RESPONSE",
        message=str(exc),
        retryable=True,
        details={
            "invalid_response_artifact": exc.artifact.model_dump(mode="json"),
        },
    )


@app.exception_handler(CommandRejected)
def command_rejected(request: Request, exc: CommandRejected) -> JSONResponse:
    return _problem_response(
        request, status_code=422, code="COMMAND_REJECTED", message=str(exc)
    )


@app.exception_handler(RequestValidationError)
def request_validation_failed(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {key: str(value) if key == "ctx" else value for key, value in item.items()}
        for item in exc.errors()
    ]
    return _problem_response(
        request,
        status_code=422,
        code="REQUEST_VALIDATION_FAILED",
        message="Request validation failed",
        details={"errors": errors},
    )


@app.exception_handler(HTTPException)
def http_request_error(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    supplied_code = detail.get("code") if isinstance(detail, dict) else None
    code = supplied_code if isinstance(supplied_code, str) else {
        403: "PERMISSION_DENIED",
        404: "RESOURCE_NOT_FOUND",
        409: "CONCURRENCY_CONFLICT",
        422: "REQUEST_VALIDATION_FAILED",
    }.get(exc.status_code, "HTTP_REQUEST_ERROR")
    message = (
        str(detail.get("message", detail.get("detail", code)))
        if isinstance(detail, dict)
        else str(detail)
    )
    details = detail.get("details") if isinstance(detail, dict) and isinstance(detail.get("details"), dict) else None
    return _problem_response(
        request,
        status_code=exc.status_code,
        code=code,
        message=message,
        retryable=exc.status_code in {408, 409, 429, 502, 503, 504},
        details=details,
    )


@app.exception_handler(Exception)
def internal_error(request: Request, exc: Exception) -> JSONResponse:
    return _problem_response(
        request,
        status_code=500,
        code="INTERNAL_ERROR",
        message="Internal server error",
        details={"exception_type": type(exc).__name__},
    )


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
        "revision": settings.build_sha,
        "database": settings.database_url.split(":", 1)[0],
        "mqtt_enabled": settings.mqtt_enabled,
        "cad_regeneration_enabled": settings.cad_regeneration_enabled,
        "cad_regeneration_in_flight": len(_cad_tasks),
        "litellm_configured": bool(settings.litellm_model),
        "subllm": eda_llm_status(settings),
        "eda_dsl_version": "twinstudio.eda/v1",
        "twin_kicad_version": package_version("twin-kicad"),
        "kicad_root": str(settings.kicad_root),
        "workspaces_root": str(settings.workspaces_root),
        "dev_auth_bypass": settings.dev_auth_bypass,
        "feature_lens_catalog": feature_lenses.catalog.catalog_version,
        "feature_lens_count": feature_lenses.catalog.active_lens_count,
        "evolution_catalog": evolution_engine.catalog.catalog_version,
        "evolution_dimensions": len(evolution_engine.catalog.extension_dimensions),
        "dsl_api_version": "twinstudio.io/v1alpha1",
        "observation_dsl_version": "TWINOBS 1.0",
    }


def _eda_document(path: str, expected_kind: str | None = None):
    try:
        document = inspect_file(settings.kicad_root, path)
    except KicadDslError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if expected_kind and document.source.kind != expected_kind:
        raise HTTPException(status_code=422, detail=f"expected a {expected_kind} KiCad document")
    return document


def _schematic_state(
    path: str,
    netlist: dict[str, Any] | None = None,
    netlist_error: str | None = None,
) -> dict[str, Any]:
    document = _eda_document(path, "schematic")
    paired_board: EdaDocument | None = None
    board_relative = Path(path).with_suffix(".kicad_pcb").as_posix()
    try:
        paired_board = inspect_file(settings.kicad_root, board_relative)
    except KicadDslError:
        paired_board = None
    return schematic_state(document, paired_board, netlist, netlist_error)


def _pcb_state(
    path: str, drc: dict[str, Any], geometry: dict[str, Any] | None = None
) -> dict[str, Any]:
    return pcb_state(_eda_document(path, "pcb"), drc, geometry)


def _ensure_eda_project(project_id: str, user: AuthPrincipal) -> None:
    try:
        queries.project(project_id)
    except ProjectNotFound:
        try:
            commands.execute(
                CommandEnvelope(
                    command_type="project.create",
                    project_id=project_id,
                    expected_version=0,
                    actor=user.email,
                    payload={
                        "tenant": "local",
                        "name": project_id,
                        "description": "Project history created by the TwinStudio EDA adapter",
                    },
                )
            )
        except (CommandRejected, ConcurrencyError):
            queries.project(project_id)


def _authorize_workspace(
    project_id: str, user: AuthPrincipal, permission: str
) -> None:
    try:
        authorize_project(project_id, user, permission)
    except ProjectNotFound as exc:
        if settings.dev_auth_bypass:
            return
        raise HTTPException(status_code=404, detail="Workspace not found") from exc
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


app.include_router(
    build_workspace_router(
        workspace_store,
        principal_dependency=principal,
        authorize=_authorize_workspace,
        register_project=_ensure_eda_project,
        writes_enabled=settings.workspace_writes_enabled,
    )
)


def _sync_eda_project_files(project_id: str) -> int:
    events = queries.events(project_id)
    version = events[-1].stream_version if events else 0
    update_descriptor(settings.kicad_root, project_id, version)
    write_event_stream(settings.kicad_root, events)
    write_wellmanifest_projection(settings.kicad_root, project_id, events)
    return version


def _eda_candidates_root() -> Path:
    """Return the configured shared store with a legacy-test fallback."""
    configured = getattr(settings, "eda_candidates_root", None)
    if configured is not None:
        return Path(configured).resolve()
    return (settings.data_dir / "artifacts" / "kicad-edits").resolve()


def _eda_event_evidence(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Freeze mutable EDA inputs as content-addressed wellmanifest evidence."""
    project_root = settings.kicad_root.resolve()
    candidate_root = _eda_candidates_root()
    candidates: list[tuple[Path, str]] = []

    source = payload.get("source")
    if isinstance(source, dict) and isinstance(source.get("path"), str):
        digest = source.get("sha256")
        if isinstance(digest, str):
            candidates.append((project_root / source["path"], digest))

    relative = payload.get("path")
    if isinstance(relative, str):
        digest = next(
            (
                payload.get(key)
                for key in ("restored_sha256", "promoted_sha256", "source_sha256")
                if isinstance(payload.get(key), str)
            ),
            None,
        )
        if isinstance(digest, str):
            candidates.append((project_root / relative, digest))

    candidate_path = payload.get("candidate_path")
    candidate_sha256 = payload.get("candidate_sha256")
    if isinstance(candidate_path, str) and isinstance(candidate_sha256, str):
        candidates.append((candidate_root / candidate_path, candidate_sha256))

    render_sha256 = payload.get("render_sha256")
    if isinstance(render_sha256, str) and isinstance(candidate_sha256, str):
        candidates.append(
            (project_root / ".twinstudio" / "previews" / f"{candidate_sha256}.png", render_sha256)
        )

    evidence_root = project_root / ".twinstudio" / "evidence" / "sha256"
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for unresolved, digest in candidates:
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            continue
        path = unresolved.resolve()
        if not (
            path.is_relative_to(project_root)
            or path.is_relative_to(candidate_root)
        ):
            continue
        if not path.is_file() or path.is_symlink() or sha256_file(path) != digest:
            continue
        if digest in seen:
            continue
        destination = evidence_root / digest[:2] / digest
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            temporary = destination.with_name(f".{digest}.{uuid4().hex}.tmp")
            try:
                shutil.copyfile(path, temporary)
                if sha256_file(temporary) != digest:
                    raise OSError("EDA evidence digest changed while copying")
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        elif not destination.is_file() or destination.is_symlink() or sha256_file(destination) != digest:
            raise OSError("content-addressed EDA evidence is invalid")
        seen.add(digest)
        result.append({
            "path": destination.relative_to(project_root).as_posix(),
            "sha256": digest,
        })
    return result


def _record_eda_event(
    project_id: str,
    user: AuthPrincipal,
    command_type: str,
    payload: dict[str, Any],
    *,
    expected_version: int | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> EventEnvelope:
    _ensure_eda_project(project_id, user)
    snapshot = queries.project(project_id)
    payload = {key: value for key, value in payload.items() if key != "evidence"}
    evidence = _eda_event_evidence(payload)
    if evidence:
        payload["evidence"] = evidence
    stored = commands.execute(
        CommandEnvelope(
            command_type=command_type,
            project_id=project_id,
            expected_version=snapshot.stream_version if expected_version is None else expected_version,
            actor=user.email,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=payload,
        )
    )
    _sync_eda_project_files(project_id)
    return stored[-1]


def _eda_event_json(event: EventEnvelope) -> dict[str, Any]:
    return EdaHistoryEntry(
        event_id=event.event_id,
        stream_version=event.stream_version,
        event_type=event.event_type,
        actor=event.actor,
        occurred_at=event.occurred_at,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
        data=event.data,
    ).model_dump(mode="json")


def _candidate_file(relative: str) -> tuple[Path, dict[str, Any]]:
    root = _eda_candidates_root()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file() or candidate.is_symlink():
        raise HTTPException(status_code=404, detail="candidate not found")
    manifest_path = candidate.with_name("change.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="candidate manifest is invalid") from exc
    if manifest.get("candidate_path") != candidate.relative_to(root).as_posix():
        raise HTTPException(status_code=422, detail="candidate manifest path mismatch")
    return candidate, manifest


def _candidate_hash_in_use(root: Path, candidate_sha256: str) -> bool:
    for manifest_path in root.rglob("change.json"):
        if any(part.startswith(".deleted-") for part in manifest_path.relative_to(root).parts):
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            relative = manifest.get("candidate_path")
        except (OSError, json.JSONDecodeError):
            continue
        if (
            manifest.get("candidate_sha256") == candidate_sha256
            and isinstance(relative, str)
            and (root / relative).is_file()
        ):
            return True
    return False


@app.get("/api/v1/eda/documents")
def eda_document(
    path: str = Query(min_length=1, max_length=2000),
    _user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Convert an allow-listed native KiCad document to the shared EDA IR."""
    return _eda_document(path).model_dump(mode="json")


@app.get("/api/v1/eda/capabilities")
def eda_capabilities(
    _user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Publish the exact operation union accepted by the deployed adapter."""
    operation_schema = TypeAdapter(EdaOperation).json_schema()
    definitions = operation_schema.get("$defs", {})
    operations: list[dict[str, Any]] = []
    for variant in operation_schema.get("oneOf", []):
        reference = variant.get("$ref") if isinstance(variant, dict) else None
        name = reference.rsplit("/", 1)[-1] if isinstance(reference, str) else ""
        definition = definitions.get(name, {})
        properties = definition.get("properties", {}) if isinstance(definition, dict) else {}
        op = properties.get("op", {}).get("const")
        if not isinstance(op, str):
            continue
        entity_schema = properties.get("entity", {})
        entity = entity_schema.get("const") or entity_schema.get("default")
        operations.append({
            "id": op,
            "entity": entity if isinstance(entity, str) else None,
            "required_fields": [
                field for field in definition.get("required", [])
                if field not in {"op", "entity"}
            ],
            "fields": sorted(field for field in properties if field not in {"op", "entity"}),
        })
    operations.sort(key=lambda item: item["id"])
    return {
        "schema_id": "twinstudio.eda-capabilities/v1",
        "adapter": "twinstudio-kicad",
        "dsl_version": "twinstudio.eda/v1",
        "operations": operations,
        "limits": {
            "max_operations": 50,
            "atomic_supported": True,
            "source_hash_required": True,
            "candidate_only": True,
        },
    }


@app.get("/api/v1/eda/sch2dsl")
def sch2dsl(
    path: str = Query(min_length=1, max_length=2000),
    _user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    return _eda_document(path, "schematic").model_dump(mode="json")


@app.get("/api/v1/eda/schematic-state")
def eda_schematic_state(
    path: str = Query(min_length=1, max_length=2000),
    _user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Read the current deterministic state of a schematic without mutating history."""
    return _schematic_state(path)


@app.post("/api/v1/eda/schematic-state")
def analyze_eda_schematic_state(
    body: EdaSchematicAnalysisRequest,
    _user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Analyze a schematic with Eeschema's authoritative logical netlist."""
    return _schematic_state(body.path, body.netlist, body.netlist_error)


@app.post("/api/v1/projects/{project_id}/eda/schematic-state")
def record_eda_schematic_state(
    project_id: str,
    body: EdaSchematicAnalysisRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Record a user-requested schematic analysis in the project EDA audit stream."""
    analysis = _schematic_state(body.path, body.netlist, body.netlist_error)
    event = _record_eda_event(
        project_id,
        user,
        "eda.schematic.analysis.record",
        {
            "schema_id": "twinstudio.eda-event/schematic-analyzed/v1",
            "source": analysis["source"],
            "analysis": analysis,
        },
        expected_version=body.expected_version,
    )
    return {"analysis": analysis, "history_event": _eda_event_json(event)}


@app.post("/api/v1/eda/pcb-state")
def eda_pcb_state(
    body: EdaPcbAnalysisRequest,
    _user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Classify KiCad DRC facts without changing the audit history."""
    return _pcb_state(body.path, body.drc, body.geometry)


@app.post("/api/v1/projects/{project_id}/eda/pcb-state")
def record_eda_pcb_state(
    project_id: str,
    body: EdaPcbAnalysisRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Record a user-requested PCB DRC analysis in the EDA audit stream."""
    analysis = _pcb_state(body.path, body.drc, body.geometry)
    event = _record_eda_event(
        project_id,
        user,
        "eda.pcb.analysis.record",
        {
            "schema_id": "twinstudio.eda-event/pcb-analyzed/v1",
            "source": analysis["source"],
            "analysis": analysis,
        },
        expected_version=body.expected_version,
    )
    return {"analysis": analysis, "history_event": _eda_event_json(event)}


def _netlist_state(path: str, netlist: dict[str, Any], pcb: dict[str, Any] | None) -> dict[str, Any]:
    state = netlist_state(netlist, pcb)
    state["source"] = {"path": path, "kind": "schematic"}
    return state


@app.post("/api/v1/eda/netlist-state")
def eda_netlist_state(
    body: EdaNetlistAnalysisRequest,
    _user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Classify schematic connectivity facts without changing the audit history."""
    return _netlist_state(body.path, body.netlist, body.pcb)


@app.post("/api/v1/projects/{project_id}/eda/netlist-state")
def record_eda_netlist_state(
    project_id: str,
    body: EdaNetlistAnalysisRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Record a user-requested connectivity audit in the EDA audit stream."""
    analysis = _netlist_state(body.path, body.netlist, body.pcb)
    event = _record_eda_event(
        project_id,
        user,
        "eda.netlist.analysis.record",
        {
            "schema_id": "twinstudio.eda-event/netlist-analyzed/v1",
            "source": analysis["source"],
            "analysis": analysis,
        },
        expected_version=body.expected_version,
    )
    return {"analysis": analysis, "history_event": _eda_event_json(event)}


@app.post("/api/v1/eda/simulation-state")
def eda_simulation_state(
    body: EdaSimulationAnalysisRequest,
    _user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Classify ngspice operating-point facts without changing the audit history."""
    return simulation_state(body.simulation, body.path)


@app.post("/api/v1/projects/{project_id}/eda/simulation-state")
def record_eda_simulation_state(
    project_id: str,
    body: EdaSimulationAnalysisRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Record a user-requested DC operating point in the EDA audit stream."""
    analysis = simulation_state(body.simulation, body.path)
    event = _record_eda_event(
        project_id,
        user,
        "eda.simulation.analysis.record",
        {
            "schema_id": "twinstudio.eda-event/simulation-analyzed/v1",
            "source": analysis["source"],
            "analysis": analysis,
        },
        expected_version=body.expected_version,
    )
    return {"analysis": analysis, "history_event": _eda_event_json(event)}


@app.get("/api/v1/eda/pcb2dsl")
def pcb2dsl(
    path: str = Query(min_length=1, max_length=2000),
    _user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    return _eda_document(path, "pcb").model_dump(mode="json")


@app.post("/api/v1/eda/nl2dsl")
def eda_nl2dsl(
    body: EdaNlRequest,
    request: Request,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    return _plan_eda(body, user, request)


@app.post("/api/v1/eda/operation-plan")
def eda_operation_plan(
    body: EdaOperationPlanRequest,
    _user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Translate a prompt to one advertised operation; never execute it."""
    try:
        proposal, mode = propose_eda_operation(
            prompt=body.prompt,
            source=body.source,
            operations=body.operations,
            project_context=body.project_context,
            settings=settings,
        )
    except KicadDslError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": exc.code,
                "message": str(exc),
                "details": {"operation": "eda.operation-plan", "retryable": False},
            },
        ) from exc
    return {"mode": mode, "proposal": proposal.model_dump(mode="json")}


def _plan_eda(body: EdaNlRequest, user: AuthPrincipal, request: Request) -> dict[str, Any]:
    document = _eda_document(body.path)
    correlation_id = body.correlation_id or _correlation_id(request)
    prompt = body.prompt
    if body.atomic:
        prompt = (
            "Wykonaj dokładnie jedną atomową operację EDA. Nie łącz zmian i nie "
            "zmieniaj niezwiązanych elementów. Jeśli zadanie wymaga wielu operacji, "
            "nie twórz planu.\n\n"
            f"Zadanie użytkownika: {body.prompt}"
        )
    rejection: dict[str, Any] = {}
    try:
        change, mode = nl_to_dsl(
            prompt, document, settings, body.context_sources, diagnostics=rejection
        )
    except KicadDslError as exc:
        if body.project_id:
            _record_eda_event(
                body.project_id,
                user,
                "eda.change.plan.failed",
                {
                    "schema_id": "twinstudio.eda-event/change-plan-failed/v1",
                    "source": document.source.model_dump(mode="json"),
                    "prompt": body.prompt,
                    "trigger": "user_prompt",
                    "context_signature": body.context_signature,
                    "context_sources": [
                        {key: source.get(key) for key in ("path", "sha256", "role", "logical_key")}
                        for source in body.context_sources
                    ],
                    "error": {
                        "code": exc.code,
                        "message": str(exc),
                        "operation": "eda.nl2dsl",
                        "retryable": False,
                    },
                },
                expected_version=body.expected_version,
                correlation_id=correlation_id,
            )
        raise HTTPException(
            status_code=422,
            detail={
                "code": exc.code,
                "message": str(exc),
                "details": {"operation": "eda.nl2dsl", "retryable": False},
                # Bez tego odmowa mówi tylko, że schemat czegoś nie przyjął,
                # a nie czego — i poprawianie promptu znów jest zgadywaniem.
                **({"rejected_response": rejection} if rejection else {}),
            },
        ) from exc
    if body.atomic and len(change.operations) != 1:
        raise HTTPException(status_code=422, detail="atomic EDA plan requires exactly one DSL operation")
    result: dict[str, Any] = {
        "mode": mode,
        "document": change.model_dump(mode="json"),
        "correlation_id": correlation_id,
    }
    if rejection:
        # Bez tego edytor wie tylko, że coś odrzucono, i nie ma czego poprawić.
        result["rejected_response"] = rejection
    if body.project_id:
        event = _record_eda_event(
            body.project_id,
            user,
            "eda.change.plan",
            {
                "schema_id": "twinstudio.eda-event/change-planned/v1",
                "source": change.source.model_dump(mode="json"),
                "prompt": change.prompt,
                "trigger": "user_prompt",
                "context_signature": body.context_signature,
                "context_sources": [
                    {key: source.get(key) for key in ("path", "sha256", "role", "logical_key")}
                    for source in body.context_sources
                ],
                "mode": mode,
                "operations": [item.model_dump(mode="json") for item in change.operations],
            },
            expected_version=body.expected_version,
            correlation_id=correlation_id,
        )
        result["history_event"] = _eda_event_json(event)
    return result


@app.post("/api/v1/projects/{project_id}/eda/nl2dsl")
def project_eda_nl2dsl(
    project_id: str,
    body: EdaNlRequest,
    request: Request,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    return _plan_eda(body.model_copy(update={"project_id": project_id}), user, request)


@app.post("/api/v1/projects/{project_id}/artifact-groups/prompt")
def project_artifact_group_prompt(
    project_id: str,
    body: ArtifactGroupPromptRequest,
    _user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Run a bounded, read-only LLM review over files chosen by one Viewer group."""
    try:
        review: ArtifactGroupReview = review_artifact_group(
            settings.kicad_root, body.group, body.paths, body.prompt, settings
        )
    except KicadDslError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return review.model_dump(mode="json")


@app.post("/api/v1/projects/{project_id}/eda/chat/respond")
def project_eda_chat_respond(
    project_id: str,
    body: EdaChatRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Explain deterministic SCH/PCB conflicts and record the exchange.

    This endpoint deliberately has no apply/promote branch.  Mutations remain
    typed candidate operations handled by the existing EDA lifecycle.
    """
    encoded_context = json.dumps(
        body.deterministic_context,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded_context) > 240_000:
        raise HTTPException(status_code=422, detail="deterministic EDA chat context exceeds 240 KB")
    if hashlib.sha256(encoded_context).hexdigest() != body.context_sha256:
        raise HTTPException(status_code=409, detail="EDA chat context hash does not match the payload")
    response: EdaChatResponse = respond_to_eda_chat(
        body.deterministic_context, body.messages, settings
    )
    dedupe_key = f"eda-chat:{body.session_id}:{body.sequence}:{body.context_sha256[:16]}"
    previous = next(
        (
            event for event in reversed(queries.events(project_id))
            if event.event_type == "ProjectUpdateRecorded"
            and event.data.get("dedupe_key") == dedupe_key
        ),
        None,
    )
    if previous is None:
        event = _record_eda_event(
            project_id,
            user,
            "project.update.record",
            {
                "schema_id": "twinstudio.project-update/v1",
                "trigger": "user_prompt",
                "category": "recommendation",
                "summary": response.summary,
                "source_paths": body.paths,
                "dedupe_key": dedupe_key,
                "details": {
                    "kind": "eda_chat_exchange",
                    "session_id": body.session_id,
                    "sequence": body.sequence,
                    "context_sha256": body.context_sha256,
                    "user_message": body.messages[-1].content,
                    "assistant": response.model_dump(mode="json"),
                },
            },
            correlation_id=body.session_id,
        )
    else:
        event = previous
    return {
        "schema_id": "twinstudio.eda-chat-exchange/v1",
        "response": response.model_dump(mode="json"),
        "history_event": _eda_event_json(event),
    }


def _apply_eda(
    body: EdaApplyRequest,
    user: AuthPrincipal,
    expected_kind: str | None = None,
) -> dict[str, Any]:
    if expected_kind and body.document.source.kind != expected_kind:
        raise HTTPException(status_code=422, detail=f"expected a {expected_kind} change document")
    if body.atomic and len(body.document.operations) != 1:
        raise HTTPException(status_code=422, detail="atomic EDA apply requires exactly one DSL operation")
    try:
        source_path = resolve_source(settings.kicad_root, body.document.source.path)
        source = source_path.read_text(encoding="utf-8")
        candidate, repair = apply_changes_with_repair(source, body.document)
        candidate_sha256 = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        validation = change_validation(body.document, repair)
        validation_event: EventEnvelope | None = None
        if body.project_id:
            validation_event = _record_eda_event(
                body.project_id,
                user,
                "eda.validation.record",
                {
                    "schema_id": "twinstudio.eda-event/validation-completed/v1",
                    "source": body.document.source.model_dump(mode="json"),
                    "candidate_sha256": candidate_sha256,
                    "operations": len(body.document.operations),
                    "validation": validation,
                },
                expected_version=body.expected_version,
                correlation_id=body.correlation_id,
                causation_id=body.causation_id,
            )
        if body.dry_run:
            result: dict[str, Any] = {
                "valid": True,
                "dry_run": True,
                "source_sha256": body.document.source.sha256,
                "candidate_sha256": candidate_sha256,
                "changed": source != candidate,
                "operations": len(body.document.operations),
                "validation": validation,
            }
            if validation_event is not None:
                result["history_event"] = _eda_event_json(validation_event)
            return result
        output_root = _eda_candidates_root()
        manifest = write_candidate(settings.kicad_root, output_root, body.document)
        manifest.update(
            {
                "correlation_id": body.correlation_id,
                "causation_id": body.causation_id,
                "validation_event_id": validation_event.event_id if validation_event else None,
            }
        )
    except (KicadDslError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = {
        "valid": True,
        "dry_run": False,
        **manifest,
        "candidate_url": f"/api/v1/eda/candidates/{manifest['candidate_path']}",
    }
    if body.project_id:
        candidate_path = output_root / manifest["candidate_path"]
        object_ref, _object_path = store_object(settings.data_dir, candidate_path)
        revision = eda_revision_id(manifest["candidate_path"], manifest["candidate_sha256"])
        identity = eda_artifact_id(body.project_id, body.document.source.path)
        manifest.update(
            {
                "project_id": body.project_id,
                "artifact_id": identity,
                "revision_id": revision,
                "object_ref": object_ref,
            }
        )
        candidate_path.with_name("change.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        event = _record_eda_event(
            body.project_id,
            user,
            "eda.candidate.record",
            {
                "schema_id": "twinstudio.eda-event/candidate-created/v1",
                "project_id": body.project_id,
                "artifact_id": identity,
                "revision_id": revision,
                "source": body.document.source.model_dump(mode="json"),
                "candidate_path": manifest["candidate_path"],
                "candidate_sha256": manifest["candidate_sha256"],
                "object_ref": object_ref,
                "operations": manifest["operations"],
                "validation": manifest["validation"],
            },
            expected_version=validation_event.stream_version if validation_event else body.expected_version,
            correlation_id=body.correlation_id,
            causation_id=validation_event.event_id if validation_event else body.causation_id,
        )
        manifest["candidate_event_id"] = event.event_id
        candidate_path.with_name("change.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        source_ref, _ = store_object(settings.data_dir, source_path)
        update_source_descriptor(
            settings.kicad_root,
            body.project_id,
            event.stream_version,
            source_path=body.document.source.path,
            source_sha256=body.document.source.sha256,
            object_ref=source_ref,
        )
        result.update(manifest)
        if validation_event is not None:
            result["validation_history_event"] = _eda_event_json(validation_event)
        result["history_event"] = _eda_event_json(event)
    return result


@app.post("/api/v1/eda/apply")
def apply_eda(
    body: EdaApplyRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    return _apply_eda(body, user)


@app.post("/api/v1/eda/dsl2sch")
def dsl2sch(
    body: EdaApplyRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    return _apply_eda(body, user, "schematic")


@app.post("/api/v1/eda/dsl2pcb")
def dsl2pcb(
    body: EdaApplyRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    return _apply_eda(body, user, "pcb")


@app.post("/api/v1/projects/{project_id}/eda/apply")
def project_apply_eda(
    project_id: str,
    body: EdaApplyRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    return _apply_eda(body.model_copy(update={"project_id": project_id}), user)


def _inspect_text_dsl(
    path: str,
    *,
    inspect: Callable[[Path, str], Any],
) -> dict[str, Any]:
    try:
        return inspect(settings.kicad_root, path).model_dump(mode="json")
    except (SvgDslError, ScadDslError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/svg2dsl")
def svg2dsl(
    path: str = Query(min_length=1, max_length=2000),
    _user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Expose an allow-listed SVG document as typed, stable-target vector DSL."""
    return _inspect_text_dsl(path, inspect=inspect_svg_file)


def _planned_text_change(
    body: SvgNlRequest | ScadNlRequest,
    user: AuthPrincipal,
    change: SvgChangeDocument | ScadChangeDocument,
    mode: str,
    *,
    event_schema: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "mode": mode,
        "document": change.model_dump(mode="json"),
        "atomic": True,
    }
    if body.project_id:
        event = _record_eda_event(
            body.project_id,
            user,
            "eda.change.plan",
            {
                "schema_id": event_schema,
                "source": change.source.model_dump(mode="json"),
                "prompt": change.prompt,
                "trigger": "user_prompt",
                "mode": mode,
                "operations": [item.model_dump(mode="json") for item in change.operations],
            },
            expected_version=body.expected_version,
        )
        result["history_event"] = _eda_event_json(event)
    return result


def _text_change_dry_run(
    body: SvgApplyRequest | ScadApplyRequest,
    source: str,
    candidate: str,
    validation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "valid": True,
        "dry_run": True,
        "source_sha256": body.document.source.sha256,
        "candidate_sha256": hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
        "changed": source != candidate,
        "operations": len(body.document.operations),
        "validation": validation,
    }


def _record_text_candidate(
    body: SvgApplyRequest | ScadApplyRequest,
    user: AuthPrincipal,
    source_path: Path,
    manifest: dict[str, Any],
    *,
    event_schema: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "valid": True,
        "dry_run": False,
        **manifest,
        "candidate_url": f"/api/v1/eda/candidates/{manifest['candidate_path']}",
    }
    if not body.project_id:
        return result

    output_root = _eda_candidates_root()
    candidate_path = output_root / manifest["candidate_path"]
    object_ref, _ = store_object(settings.data_dir, candidate_path)
    revision = eda_revision_id(manifest["candidate_path"], manifest["candidate_sha256"])
    identity = eda_artifact_id(body.project_id, body.document.source.path)
    manifest.update(
        {
            "project_id": body.project_id,
            "artifact_id": identity,
            "revision_id": revision,
            "object_ref": object_ref,
        }
    )
    candidate_path.with_name("change.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    event = _record_eda_event(
        body.project_id,
        user,
        "eda.candidate.record",
        {
            "schema_id": event_schema,
            "project_id": body.project_id,
            "artifact_id": identity,
            "revision_id": revision,
            "source": body.document.source.model_dump(mode="json"),
            "candidate_path": manifest["candidate_path"],
            "candidate_sha256": manifest["candidate_sha256"],
            "object_ref": object_ref,
            "operations": manifest["operations"],
            "validation": manifest["validation"],
        },
        expected_version=body.expected_version,
        correlation_id=body.correlation_id,
    )
    source_ref, _ = store_object(settings.data_dir, source_path)
    update_source_descriptor(
        settings.kicad_root,
        body.project_id,
        event.stream_version,
        source_path=body.document.source.path,
        source_sha256=body.document.source.sha256,
        object_ref=source_ref,
    )
    result.update(manifest)
    result["history_event"] = _eda_event_json(event)
    return result


def _plan_text_dsl(
    body: SvgNlRequest | ScadNlRequest,
    user: AuthPrincipal,
    *,
    inspect: Callable[[Path, str], Any],
    translate: Callable[[str, Any, Any], tuple[Any, str]],
    event_schema: str,
) -> dict[str, Any]:
    try:
        document = inspect(settings.kicad_root, body.path)
        change, mode = translate(body.prompt, document, settings)
    except (SvgDslError, ScadDslError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _planned_text_change(
        body,
        user,
        change,
        mode,
        event_schema=event_schema,
    )


def _plan_svg(body: SvgNlRequest, user: AuthPrincipal) -> dict[str, Any]:
    return _plan_text_dsl(
        body,
        user,
        inspect=inspect_svg_file,
        translate=nl_to_svg_dsl,
        event_schema="twinstudio.svg-event/change-planned/v1",
    )


@app.post("/api/v1/svg/nl2dsl")
def svg_nl2dsl(body: SvgNlRequest, user: AuthPrincipal = Depends(principal)) -> dict[str, Any]:
    return _plan_svg(body, user)


@app.post("/api/v1/projects/{project_id}/svg/nl2dsl")
def project_svg_nl2dsl(
    project_id: str, body: SvgNlRequest, user: AuthPrincipal = Depends(principal)
) -> dict[str, Any]:
    return _plan_svg(body.model_copy(update={"project_id": project_id}), user)


def _analyze_svg(body: SvgAnalysisRequest) -> dict[str, Any]:
    try:
        source = resolve_svg_source(settings.kicad_root, body.path).read_text(encoding="utf-8")
        return analyze_svg_with_llm(source, body.path, settings, use_llm=body.use_llm).model_dump(mode="json")
    except (SvgDslError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/svg/analyze")
def svg_analyze(body: SvgAnalysisRequest, _user: AuthPrincipal = Depends(principal)) -> dict[str, Any]:
    """Visual/structural SVG audit. It is observation-only and never mutates SVG."""
    return _analyze_svg(body)


@app.post("/api/v1/projects/{project_id}/svg/analyze")
def project_svg_analyze(
    project_id: str, body: SvgAnalysisRequest, user: AuthPrincipal = Depends(principal)
) -> dict[str, Any]:
    analysis = _analyze_svg(body)
    event = _record_eda_event(
        project_id, user, "svg.analysis.record",
        {"schema_id": "twinstudio.svg-event/analyzed/v1", "source": analysis["source"], "analysis": analysis},
        expected_version=body.expected_version,
    )
    return {"analysis": analysis, "history_event": _eda_event_json(event)}


def _apply_svg(body: SvgApplyRequest, user: AuthPrincipal) -> dict[str, Any]:
    try:
        source_path = resolve_svg_source(settings.kicad_root, body.document.source.path)
        source = source_path.read_text(encoding="utf-8")
        candidate = apply_svg_changes(source, body.document)
    except (SvgDslError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    validation = {"status": "structurally_valid", "codes": [], "requires_routing": False, "svg_xml": "valid"}
    if body.dry_run:
        return _text_change_dry_run(body, source, candidate, validation)
    try:
        output_root = _eda_candidates_root()
        manifest = write_svg_candidate(settings.kicad_root, output_root, body.document)
    except (SvgDslError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _record_text_candidate(
        body,
        user,
        source_path,
        manifest,
        event_schema="twinstudio.svg-event/candidate-created/v1",
    )


@app.post("/api/v1/svg/apply")
def apply_svg(body: SvgApplyRequest, user: AuthPrincipal = Depends(principal)) -> dict[str, Any]:
    return _apply_svg(body, user)


@app.post("/api/v1/projects/{project_id}/svg/apply")
def project_apply_svg(
    project_id: str, body: SvgApplyRequest, user: AuthPrincipal = Depends(principal)
) -> dict[str, Any]:
    return _apply_svg(body.model_copy(update={"project_id": project_id}), user)


@app.get("/api/v1/scad2dsl")
def scad2dsl(
    path: str = Query(min_length=1, max_length=2000),
    _user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Expose only editable, top-level numeric OpenSCAD parameters."""
    return _inspect_text_dsl(path, inspect=inspect_scad_file)


def _plan_scad(body: ScadNlRequest, user: AuthPrincipal) -> dict[str, Any]:
    return _plan_text_dsl(
        body,
        user,
        inspect=inspect_scad_file,
        translate=nl_to_scad_dsl,
        event_schema="twinstudio.scad-event/change-planned/v1",
    )


@app.post("/api/v1/scad/nl2dsl")
def scad_nl2dsl(body: ScadNlRequest, user: AuthPrincipal = Depends(principal)) -> dict[str, Any]:
    return _plan_scad(body, user)


@app.post("/api/v1/projects/{project_id}/scad/nl2dsl")
def project_scad_nl2dsl(
    project_id: str, body: ScadNlRequest, user: AuthPrincipal = Depends(principal)
) -> dict[str, Any]:
    return _plan_scad(body.model_copy(update={"project_id": project_id}), user)


def _apply_scad(body: ScadApplyRequest, user: AuthPrincipal) -> dict[str, Any]:
    try:
        source_path = resolve_scad_source(settings.kicad_root, body.document.source.path)
        source = source_path.read_text(encoding="utf-8")
        candidate = apply_scad_changes(source, body.document)
        validation = validate_scad(candidate)
    except (ScadDslError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.dry_run:
        return _text_change_dry_run(body, source, candidate, validation)
    try:
        output_root = _eda_candidates_root()
        manifest = write_scad_candidate(settings.kicad_root, output_root, body.document)
    except (ScadDslError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _record_text_candidate(
        body,
        user,
        source_path,
        manifest,
        event_schema="twinstudio.scad-event/candidate-created/v1",
    )


@app.post("/api/v1/scad/apply")
def apply_scad(body: ScadApplyRequest, user: AuthPrincipal = Depends(principal)) -> dict[str, Any]:
    return _apply_scad(body, user)


@app.post("/api/v1/projects/{project_id}/scad/apply")
def project_apply_scad(
    project_id: str, body: ScadApplyRequest, user: AuthPrincipal = Depends(principal)
) -> dict[str, Any]:
    return _apply_scad(body.model_copy(update={"project_id": project_id}), user)


@app.post("/api/v1/scad/validate")
def validate_scad_source(
    body: ScadValidationRequest, _user: AuthPrincipal = Depends(principal)
) -> dict[str, Any]:
    """Recheck an existing SCAD candidate without creating another revision."""
    try:
        return validate_scad(body.source)
    except ScadDslError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/eda/candidates/{relative:path}")
def eda_candidate(
    relative: str,
    _user: AuthPrincipal = Depends(principal),
) -> FileResponse:
    root = _eda_candidates_root()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise HTTPException(status_code=404, detail="candidate not found")
    return FileResponse(path, media_type="text/plain; charset=utf-8", filename=None)


def _validated_candidate_decision(
    project_id: str, body: EdaDecisionRequest
) -> tuple[Path, Path, dict[str, Any], str, str]:
    candidate, manifest = _candidate_file(body.candidate_path)
    source_data = manifest.get("source")
    if not isinstance(source_data, dict) or not isinstance(source_data.get("path"), str):
        raise HTTPException(status_code=422, detail="candidate source is invalid")
    if manifest.get("project_id") not in {None, project_id}:
        raise HTTPException(status_code=422, detail="candidate belongs to another project")
    source_kind = str(source_data.get("kind") or "")
    source_is_new = source_data.get("exists") is False
    if source_is_new:
        source = _resolve_new_candidate_source(source_kind, source_data["path"])
        source_hash = hashlib.sha256(b"").hexdigest()
        if source.is_file() or source.is_symlink():
            raise HTTPException(
                status_code=409,
                detail="new candidate source was created after candidate creation",
            )
    else:
        try:
            source = _resolve_editable_source(source_kind, source_data["path"])
        except (KicadDslError, SvgDslError, ScadDslError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        source_hash = sha256_file(source)
    candidate_hash = sha256_file(candidate)
    if source_hash != body.source_sha256 or source_data.get("sha256") != body.source_sha256:
        raise HTTPException(status_code=409, detail="source hash changed since candidate creation")
    if candidate_hash != body.candidate_sha256 or manifest.get("candidate_sha256") != body.candidate_sha256:
        raise HTTPException(status_code=409, detail="candidate hash does not match its manifest")
    revision = str(
        manifest.get("revision_id") or eda_revision_id(body.candidate_path, body.candidate_sha256)
    )
    identity = str(manifest.get("artifact_id") or eda_artifact_id(project_id, source_data["path"]))
    return candidate, source, manifest, revision, identity


def _resolve_editable_source(kind: str, path: str) -> Path:
    if kind == "svg":
        return resolve_svg_source(settings.kicad_root, path)
    if kind == "scad":
        return resolve_scad_source(settings.kicad_root, path)
    return resolve_source(settings.kicad_root, path)


def _resolve_new_candidate_source(kind: str, path: str) -> Path:
    """Resolve an absent candidate target without weakening path or type checks."""
    expected_suffix = {"schematic": ".kicad_sch", "pcb": ".kicad_pcb"}.get(kind)
    if expected_suffix is None:
        raise HTTPException(status_code=422, detail="new source bootstrap supports only KiCad SCH/PCB")
    normalized = path.strip().replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (
        not normalized
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or any("\x00" in part or ":" in part for part in relative.parts)
        or relative.suffix.casefold() != expected_suffix
    ):
        raise HTTPException(status_code=422, detail="new candidate source path is invalid")
    root = settings.kicad_root.resolve()
    source = (root / Path(*relative.parts)).resolve()
    if not source.is_relative_to(root) or source == root or source.parent.is_symlink():
        raise HTTPException(status_code=422, detail="new candidate source path escapes the project")
    return source


def _revision_events(project_id: str, revision: str) -> list[EventEnvelope]:
    return [
        event
        for event in queries.events(project_id)
        if event.event_type in EDA_EVENT_TYPES and event.data.get("revision_id") == revision
    ]


def _promotion_bundle(candidate: Path, source: Path) -> list[tuple[Path, Path]]:
    """Return the reviewed KiCad file together with its measured project context."""
    files = [(candidate, source)]
    if candidate.suffix not in {".kicad_pcb", ".kicad_sch"}:
        return files
    candidate_dir = candidate.parent
    source_dir = source.parent
    allowed = {
        f"{candidate.stem}.kicad_pcb",
        f"{candidate.stem}.kicad_sch",
        f"{candidate.stem}.kicad_pro",
        "fp-lib-table",
        "sym-lib-table",
    }
    for item in sorted(candidate_dir.iterdir()):
        if item.is_symlink():
            continue
        if item.is_file() and item.name in allowed:
            pair = (item, source_dir / item.name)
            if pair not in files:
                files.append(pair)
        elif item.is_dir() and (item.name.endswith(".pretty") or item.name == "components"):
            for member in sorted(item.rglob("*")):
                if member.is_file() and not member.is_symlink():
                    files.append((member, source_dir / member.relative_to(candidate_dir)))
    return files


def _promote_bundle(candidate: Path, source: Path) -> list[dict[str, Any]]:
    """Atomically replace each file and retain content-addressed rollback evidence."""
    staged: list[tuple[Path, Path]] = []
    records: list[dict[str, Any]] = []
    try:
        for candidate_file, target in _promotion_bundle(candidate, source):
            target.parent.mkdir(parents=True, exist_ok=True)
            previous_ref = store_object(settings.data_dir, target)[0] if target.is_file() else None
            promoted_ref, _ = store_object(settings.data_dir, candidate_file)
            with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=f".{target.name}.", delete=False
            ) as stream:
                temporary = Path(stream.name)
                with candidate_file.open("rb") as candidate_stream:
                    shutil.copyfileobj(candidate_stream, stream)
                stream.flush()
                os.fsync(stream.fileno())
            staged.append((temporary, target))
            records.append({
                "path": target.relative_to(settings.kicad_root).as_posix(),
                "previous_object_ref": previous_ref,
                "promoted_object_ref": promoted_ref,
                "promoted_sha256": promoted_ref.removeprefix("sha256:"),
            })
        for temporary, target in staged:
            os.replace(temporary, target)
    finally:
        for temporary, _target in staged:
            temporary.unlink(missing_ok=True)
    return records


def _revert_bundle(records: list[dict[str, Any]]) -> None:
    """Restore every file measured during promotion, refusing partial stale state."""
    root = settings.kicad_root.resolve()
    prepared: list[tuple[Path | None, Path]] = []
    try:
        for record in records:
            relative = record.get("path")
            promoted_sha256 = record.get("promoted_sha256")
            if not isinstance(relative, str) or not isinstance(promoted_sha256, str):
                raise ValueError("promotion bundle is incomplete")
            target = (root / relative).resolve()
            if not target.is_relative_to(root) or target.is_symlink():
                raise ValueError("promotion bundle path escapes the project")
            if not target.is_file() or sha256_file(target) != promoted_sha256:
                raise ValueError(f"current artifact no longer matches promoted file: {relative}")
            previous_ref = record.get("previous_object_ref")
            if previous_ref is None:
                prepared.append((None, target))
                continue
            digest = str(previous_ref).removeprefix("sha256:")
            previous = settings.data_dir / "artifacts" / "objects" / "sha256" / digest[:2] / digest
            if not previous.is_file() or sha256_file(previous) != digest:
                raise ValueError(f"previous content-addressed object is unavailable: {relative}")
            with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=f".{target.name}.", delete=False
            ) as stream:
                temporary = Path(stream.name)
                with previous.open("rb") as previous_stream:
                    shutil.copyfileobj(previous_stream, stream)
                stream.flush()
                os.fsync(stream.fileno())
            prepared.append((temporary, target))
        for temporary, target in prepared:
            if temporary is None:
                target.unlink()
            else:
                os.replace(temporary, target)
    finally:
        for temporary, _target in prepared:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _candidate_case(
    body: EdaDecisionRequest,
    manifest: dict[str, Any],
    events: list[EventEnvelope],
) -> tuple[str | None, str | None]:
    """Resolve one stable case and the immediately preceding lifecycle event."""
    latest = events[-1] if events else None
    correlation_id = (
        body.correlation_id
        or manifest.get("correlation_id")
        or (latest.correlation_id if latest else None)
    )
    causation_id = (
        body.causation_id
        or (latest.event_id if latest else None)
        or manifest.get("candidate_event_id")
        or manifest.get("validation_event_id")
        or manifest.get("causation_id")
    )
    return correlation_id, causation_id


@app.post("/api/v1/projects/{project_id}/updates")
def record_project_update(
    project_id: str,
    body: ProjectUpdateRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    _ensure_eda_project(project_id, user)
    previous = next(
        (
            event for event in reversed(queries.events(project_id))
            if event.event_type == "ProjectUpdateRecorded"
            and event.data.get("dedupe_key") == body.dedupe_key
        ),
        None,
    )
    if previous is not None:
        return {"status": "already_recorded", "event": _eda_event_json(previous)}
    event = _record_eda_event(
        project_id,
        user,
        "project.update.record",
        {
            "schema_id": "twinstudio.project-update/v1",
            "trigger": body.trigger,
            "category": body.category,
            "summary": body.summary,
            "source_paths": body.source_paths,
            "dedupe_key": body.dedupe_key,
            "details": body.details,
        },
        expected_version=body.expected_version,
    )
    return {"status": "recorded", "event": _eda_event_json(event)}


@app.get("/api/v1/projects/{project_id}/updates")
def project_updates(
    project_id: str,
    limit: int = Query(default=200, ge=1, le=2000),
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "project.read")
    events = [event for event in queries.events(project_id) if event.event_type in EDA_EVENT_TYPES]
    return {
        "schema_id": "twinstudio.project-chronology/v1",
        "events": [_eda_event_json(event) for event in events[-limit:]],
    }


@app.get("/api/v1/projects/{project_id}/eda/history")
def project_eda_history(
    project_id: str,
    artifact_path: str | None = Query(default=None, max_length=2000),
    limit: int = Query(default=200, ge=1, le=2000),
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "project.read")
    events = [event for event in queries.events(project_id) if event.event_type in EDA_EVENT_TYPES]
    if artifact_path:
        events = [
            event
            for event in events
            if event.data.get("source", {}).get("path") == artifact_path
            or event.data.get("path") == artifact_path
            or artifact_path in event.data.get("source_paths", [])
        ]
    stream_version = queries.project(project_id).stream_version
    descriptor = load_descriptor(settings.kicad_root, project_id).model_copy(
        update={"stream_version": stream_version}
    )
    return {
        "schema_id": "twinstudio.eda-history/v1",
        "project": descriptor.model_dump(mode="json"),
        "events": [_eda_event_json(event) for event in events[-limit:]],
    }


def _decide_project_eda_candidate(
    project_id: str,
    body: EdaDecisionRequest,
    user: AuthPrincipal,
    *,
    decision: str,
) -> dict[str, Any]:
    _candidate, _source, manifest, revision, identity = _validated_candidate_decision(project_id, body)
    prior = _revision_events(project_id, revision)
    if decision == "accept" and prior and prior[-1].event_type == "EdaChangeAccepted":
        return {"status": "accepted", "already_recorded": True, "event": _eda_event_json(prior[-1])}
    correlation_id, causation_id = _candidate_case(body, manifest, prior)
    payload = {
        "schema_id": f"twinstudio.eda-event/change-{decision}ed/v1",
        "project_id": project_id,
        "artifact_id": identity,
        "revision_id": revision,
        "candidate_path": body.candidate_path,
        "path": manifest["source"]["path"],
        "source_sha256": body.source_sha256,
        "candidate_sha256": body.candidate_sha256,
        "render_sha256": body.render_sha256,
        "reason": body.reason,
    }
    if decision == "accept":
        payload["validation"] = manifest.get("validation", {})
    event = _record_eda_event(
        project_id,
        user,
        f"eda.candidate.{decision}",
        payload,
        expected_version=body.expected_version,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
    return {"status": f"{decision}ed", "event": _eda_event_json(event)}


@app.post("/api/v1/projects/{project_id}/eda/candidates/accept")
def accept_project_eda_candidate(
    project_id: str,
    body: EdaDecisionRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    return _decide_project_eda_candidate(project_id, body, user, decision="accept")


@app.post("/api/v1/projects/{project_id}/eda/candidates/reject")
def reject_project_eda_candidate(
    project_id: str,
    body: EdaDecisionRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    return _decide_project_eda_candidate(project_id, body, user, decision="reject")


@app.post("/api/v1/projects/{project_id}/eda/candidates/delete")
def delete_project_eda_candidate(
    project_id: str,
    body: EdaDecisionRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    candidate, _source, manifest, revision, identity = _validated_candidate_decision(project_id, body)
    root = _eda_candidates_root()
    relative = candidate.relative_to(root)
    revision_root = (root / relative.parts[0]).resolve()
    if revision_root.parent != root or not revision_root.is_dir() or revision_root.is_symlink():
        raise HTTPException(status_code=422, detail="candidate revision directory is invalid")
    staged = root / f".deleted-{relative.parts[0]}-{uuid4().hex}"
    os.replace(revision_root, staged)
    try:
        prior = _revision_events(project_id, revision)
        correlation_id, causation_id = _candidate_case(body, manifest, prior)
        event = _record_eda_event(
            project_id,
            user,
            "eda.candidate.delete",
            {
                "schema_id": "twinstudio.eda-event/candidate-deleted/v1",
                "project_id": project_id,
                "artifact_id": identity,
                "revision_id": revision,
                "candidate_path": body.candidate_path,
                "path": manifest["source"]["path"],
                "source_sha256": body.source_sha256,
                "candidate_sha256": body.candidate_sha256,
                "render_sha256": body.render_sha256,
                "reason": body.reason,
            },
            expected_version=body.expected_version,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
    except Exception:
        os.replace(staged, revision_root)
        raise
    shutil.rmtree(staged)
    preview = settings.kicad_root / ".twinstudio" / "previews" / f"{body.candidate_sha256}.png"
    if not _candidate_hash_in_use(root, body.candidate_sha256):
        preview.unlink(missing_ok=True)
    return {"status": "deleted", "event": _eda_event_json(event)}


@app.post("/api/v1/projects/{project_id}/eda/candidates/promote")
def promote_project_eda_candidate(
    project_id: str,
    body: EdaDecisionRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    candidate, source, manifest, revision, identity = _validated_candidate_decision(project_id, body)
    revision_events = _revision_events(project_id, revision)
    latest_decision = next(
        (event for event in reversed(revision_events) if event.event_type in {"EdaChangeAccepted", "EdaChangeRejected"}),
        None,
    )
    if latest_decision is None or latest_decision.event_type != "EdaChangeAccepted":
        raise HTTPException(status_code=409, detail="candidate must be accepted before promotion")
    promoted_files = _promote_bundle(candidate, source)
    primary = next(
        item
        for item in promoted_files
        if item["path"] == source.relative_to(settings.kicad_root).as_posix()
    )
    previous_ref = primary["previous_object_ref"]
    candidate_ref = str(primary["promoted_object_ref"])
    event = _record_eda_event(
        project_id,
        user,
        "eda.revision.promote",
        {
            "schema_id": "twinstudio.eda-event/revision-promoted/v1",
            "project_id": project_id,
            "artifact_id": identity,
            "revision_id": revision,
            "path": source.relative_to(settings.kicad_root).as_posix(),
            "source_kind": manifest.get("source", {}).get("kind"),
            "previous_sha256": body.source_sha256,
            "previous_object_ref": previous_ref,
            "promoted_sha256": body.candidate_sha256,
            "promoted_object_ref": candidate_ref,
            "candidate_path": body.candidate_path,
            "files": promoted_files,
        },
        expected_version=body.expected_version,
        correlation_id=body.correlation_id or latest_decision.correlation_id or manifest.get("correlation_id"),
        causation_id=latest_decision.event_id,
    )
    update_descriptor(
        settings.kicad_root,
        project_id,
        event.stream_version,
        source_path=source.relative_to(settings.kicad_root).as_posix(),
        source_sha256=body.candidate_sha256,
        revision=revision,
        object_ref=candidate_ref,
    )
    return {"status": "promoted", "event": _eda_event_json(event)}


@app.post("/api/v1/projects/{project_id}/eda/revisions/revert")
def revert_project_eda_revision(
    project_id: str,
    body: EdaRevertRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    events = queries.events(project_id)
    promotion = next(
        (event for event in events if event.event_id == body.promotion_event_id and event.event_type == "EdaRevisionPromoted"),
        None,
    )
    if promotion is None:
        raise HTTPException(status_code=404, detail="promotion event not found")
    try:
        source = _resolve_editable_source(
            str(promotion.data.get("source_kind") or ""), str(promotion.data["path"])
        )
    except (KicadDslError, SvgDslError, ScadDslError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if sha256_file(source) != body.expected_current_sha256:
        raise HTTPException(status_code=409, detail="current artifact no longer matches the promoted revision")
    previous_ref = promotion.data.get("previous_object_ref")
    digest = (
        str(previous_ref).removeprefix("sha256:")
        if previous_ref is not None
        else hashlib.sha256(b"").hexdigest()
    )
    promoted_files = promotion.data.get("files")
    if isinstance(promoted_files, list) and promoted_files:
        try:
            _revert_bundle(promoted_files)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    else:
        if previous_ref is None:
            raise HTTPException(status_code=409, detail="new-source promotion has no bundle metadata")
        previous = settings.data_dir / "artifacts" / "objects" / "sha256" / digest[:2] / digest
        if not previous.is_file() or sha256_file(previous) != digest:
            raise HTTPException(status_code=409, detail="previous content-addressed object is unavailable")
        temporary = source.with_name(f".{source.name}.{uuid4()}.tmp")
        try:
            shutil.copyfile(previous, temporary)
            os.replace(temporary, source)
        finally:
            temporary.unlink(missing_ok=True)
    event = _record_eda_event(
        project_id,
        user,
        "eda.revision.revert",
        {
            "schema_id": "twinstudio.eda-event/change-reverted/v1",
            "project_id": project_id,
            "artifact_id": promotion.data["artifact_id"],
            "revision_id": promotion.data["revision_id"],
            "path": promotion.data["path"],
            "reverts_event_id": promotion.event_id,
            "restored_sha256": digest,
            "restored_object_ref": previous_ref,
            "restored_exists": previous_ref is not None,
            "reason": body.reason,
        },
        expected_version=body.expected_version,
        correlation_id=body.correlation_id or promotion.correlation_id,
        causation_id=promotion.event_id,
    )
    if previous_ref is None:
        remove_descriptor_artifact(
            settings.kicad_root,
            project_id,
            event.stream_version,
            source_path=str(promotion.data["path"]),
        )
    else:
        update_descriptor(
            settings.kicad_root,
            project_id,
            event.stream_version,
            source_path=str(promotion.data["path"]),
            source_sha256=digest,
            revision=f"revert:{promotion.event_id}",
            object_ref=str(previous_ref),
        )
    return {"status": "reverted", "event": _eda_event_json(event)}


@app.post("/api/v1/projects/{project_id}/eda/history/migrate")
def migrate_project_eda_history(
    project_id: str,
    body: EdaMigrationRequest,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    _ensure_eda_project(project_id, user)
    authorize_project(project_id, user, "change.apply")
    root = _eda_candidates_root()
    known = {
        str(event.data.get("candidate_path"))
        for event in queries.events(project_id)
        if event.event_type in {"EdaCandidateCreated", "EdaHistoryImported"}
    }
    imported: list[str] = []
    accepted: list[str] = []
    expected = body.expected_version
    for manifest_path in sorted(root.rglob("change.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            candidate_relative = str(manifest["candidate_path"])
            candidate, checked = _candidate_file(candidate_relative)
            source_data = checked["source"]
            candidate_hash = sha256_file(candidate)
            if candidate_relative in known or candidate_hash != checked.get("candidate_sha256"):
                continue
            identity = str(
                checked.get("artifact_id") or eda_artifact_id(project_id, str(source_data["path"]))
            )
            revision = str(
                checked.get("revision_id") or eda_revision_id(candidate_relative, candidate_hash)
            )
            object_ref, _ = store_object(settings.data_dir, candidate)
            _record_eda_event(
                project_id,
                user,
                "eda.candidate.record",
                {
                    "schema_id": "twinstudio.eda-event/candidate-created/v1",
                    "project_id": project_id,
                    "artifact_id": identity,
                    "revision_id": revision,
                    "source": source_data,
                    "candidate_path": candidate_relative,
                    "candidate_sha256": candidate_hash,
                    "object_ref": object_ref,
                    "operations": checked.get("operations", []),
                    "validation": checked.get("validation", {}),
                    "imported": True,
                    "legacy_manifest": manifest_path.relative_to(root).as_posix(),
                },
                expected_version=expected,
            )
            expected = None
            imported.append(revision)
            approval_path = manifest_path.with_name("approval.json")
            if approval_path.is_file():
                approval = json.loads(approval_path.read_text(encoding="utf-8"))
                if approval.get("status") == "accepted" and approval.get("candidate_sha256") == candidate_hash:
                    _record_eda_event(
                        project_id,
                        user,
                        "eda.candidate.accept",
                        {
                            "schema_id": "twinstudio.eda-event/change-accepted/v1",
                            "project_id": project_id,
                            "artifact_id": identity,
                            "revision_id": revision,
                            "candidate_path": candidate_relative,
                            "path": source_data["path"],
                            "source_sha256": source_data["sha256"],
                            "candidate_sha256": candidate_hash,
                            "render_sha256": None,
                            "validation": checked.get("validation", {}),
                            "reason": "Imported from legacy approval.json",
                            "legacy_approval": approval_path.relative_to(root).as_posix(),
                        },
                    )
                    accepted.append(revision)
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            continue
    summary = _record_eda_event(
        project_id,
        user,
        "eda.history.import",
        {
            "schema_id": "twinstudio.eda-event/history-imported/v1",
            "project_id": project_id,
            "imported_revisions": imported,
            "accepted_revisions": accepted,
            "originals_modified": False,
        },
    )
    return {
        "status": "completed",
        "imported": len(imported),
        "accepted": len(accepted),
        "originals_modified": False,
        "event": _eda_event_json(summary),
    }


@app.get("/api/v1/errors/{code}")
def get_error_playbook(code: str) -> dict[str, str]:
    try:
        markdown = load_error_playbook(ERROR_ROOT, code)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Error playbook not found") from exc
    return {"code": code, "registry_path": f"error/{code}.md", "markdown": markdown}


@app.put("/api/v1/projects/{project_id}/ui-context")
def put_ui_context(
    project_id: str,
    body: UiContext,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "project.read")
    if body.project_id != project_id:
        raise HTTPException(status_code=422, detail="UI context project_id does not match API path")
    return ui_contexts.put(body).model_dump(mode="json")


@app.get("/api/v1/projects/{project_id}/ui-context")
def get_ui_context(
    project_id: str,
    session_id: str | None = None,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "project.read")
    context = ui_contexts.get(project_id, session_id)
    if context is None:
        raise HTTPException(status_code=404, detail="UI context not found")
    return context.model_dump(mode="json")


@app.get("/api/v1/projects/{project_id}/logs.dsl", response_class=Response)
def get_observation_logs(
    project_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    user: AuthPrincipal = Depends(principal),
) -> Response:
    authorize_project(project_id, user, "project.read")
    content = observation_logs.to_dsl(project_id, limit)
    safe_project_id = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in project_id
    )[:100]
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{safe_project_id or "project"}-observations.twinobs"'
            ),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


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


def _change_history(project_id: str) -> tuple[list[Any], set[str]]:
    events = queries.events(project_id)
    reverted = {
        str(event.data.get("reverts_event_id"))
        for event in events
        if event.event_type == "ChangeReverted" and event.data.get("reverts_event_id")
    }
    return events, reverted


def _change_is_latest_for_parameters(target_event: Any, events: list[Any]) -> bool:
    patches = target_event.data.get("parameter_patches", [])
    keys = {(patch.get("object_uri"), patch.get("parameter")) for patch in patches}
    if not keys:
        return False
    reverted = {
        str(event.data.get("reverts_event_id"))
        for event in events
        if event.event_type == "ChangeReverted" and event.data.get("reverts_event_id")
    }
    for event in events:
        if event.stream_version <= target_event.stream_version:
            continue
        if event.event_type != "ChangeApplied" or event.event_id in reverted:
            continue
        later_keys = {
            (patch.get("object_uri"), patch.get("parameter"))
            for patch in event.data.get("parameter_patches", [])
        }
        if keys & later_keys:
            return False
    return True


@app.get("/api/v1/projects/{project_id}/change-history")
def get_change_history(
    project_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthPrincipal = Depends(principal),
) -> list[dict[str, Any]]:
    authorize_project(project_id, user, "project.read")
    snapshot = queries.project(project_id)
    events, reverted = _change_history(project_id)
    relevant = {
        "AnnotationCreated",
        "AnnotationStatusChanged",
        "ChangePlanCreated",
        "ChangeApplied",
        "ChangeReverted",
        "GenerationRequested",
        "GenerationCompleted",
        "GenerationFailed",
    }
    result: list[dict[str, Any]] = []
    for event in reversed([item for item in events if item.event_type in relevant][-limit:]):
        data = dict(event.data)
        if event.event_type == "AnnotationCreated":
            annotation = dict(data.get("annotation", {}))
            current = snapshot.annotations.get(annotation.get("uri", ""))
            if current is not None:
                annotation["status"] = current.status
            data["annotation"] = annotation
        undo_available = (
            event.event_type == "ChangeApplied"
            and event.event_id not in reverted
            and all("previous_parameter" in patch for patch in data.get("parameter_patches", []))
            and _change_is_latest_for_parameters(event, events)
        )
        result.append(
            {
                "event_id": event.event_id,
                "stream_version": event.stream_version,
                "event_type": event.event_type,
                "actor": event.actor,
                "occurred_at": event.occurred_at.isoformat(),
                "data": data,
                "undo_available": undo_available,
                "reverted": event.event_id in reverted,
            }
        )
    return result


@app.get("/api/v1/projects/{project_id}/change-queue")
def get_change_queue(
    project_id: str,
    include_completed: bool = False,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    """Project event-backed plans into the active implementation queue."""

    authorize_project(project_id, user, "project.read")
    snapshot = queries.project(project_id)
    events, reverted = _change_history(project_id)
    applications: dict[str, list[Any]] = {}
    generations_by_plan: dict[str, list[Any]] = {}
    for event in events:
        if event.event_type == "ChangeApplied" and event.data.get("plan_id"):
            applications.setdefault(str(event.data["plan_id"]), []).append(event)
        if event.event_type in {"GenerationRequested", "GenerationCompleted", "GenerationFailed"}:
            generation_plan_id = event.data.get("plan_id")
            if generation_plan_id:
                generations_by_plan.setdefault(str(generation_plan_id), []).append(event)
    active_statuses = {"ready", "needs_detail", "waiting_cad", "cad_failed"}
    tasks: list[dict[str, Any]] = []
    for plan in snapshot.change_plans.values():
        plan_applications = applications.get(plan.plan_id, [])
        active_application = next(
            (event for event in reversed(plan_applications) if event.event_id not in reverted),
            None,
        )
        operation_kinds = [str(getattr(operation.kind, "value", operation.kind)) for operation in plan.operations]
        deferred_count = 0
        generation_events = generations_by_plan.get(plan.plan_id, [])
        latest_generation = generation_events[-1] if generation_events else None
        if active_application is not None:
            deferred_count = len(active_application.data.get("deferred_operations", []))
            if latest_generation and latest_generation.event_type == "GenerationRequested":
                status = "waiting_cad"
                updated_at = latest_generation.occurred_at.isoformat()
            elif latest_generation and latest_generation.event_type == "GenerationFailed":
                status = "cad_failed"
                updated_at = latest_generation.occurred_at.isoformat()
            else:
                status = "waiting_cad" if deferred_count else "completed"
                updated_at = (
                    latest_generation.occurred_at.isoformat()
                    if latest_generation
                    else active_application.occurred_at.isoformat()
                )
        elif plan_applications:
            if latest_generation and latest_generation.event_type == "GenerationRequested":
                status = "waiting_cad"
                updated_at = latest_generation.occurred_at.isoformat()
            elif latest_generation and latest_generation.event_type == "GenerationFailed":
                status = "cad_failed"
                updated_at = latest_generation.occurred_at.isoformat()
            else:
                status = "undone"
                updated_at = (
                    latest_generation.occurred_at.isoformat()
                    if latest_generation
                    else plan_applications[-1].occurred_at.isoformat()
                )
        elif plan.base_revision != snapshot.revision:
            status = "stale"
            updated_at = plan.created_at.isoformat()
        elif plan.unresolved_questions:
            status = "needs_detail"
            updated_at = plan.created_at.isoformat()
        elif operation_kinds and all(kind == "set_parameter" for kind in operation_kinds):
            status = "ready"
            updated_at = plan.created_at.isoformat()
        else:
            status = "waiting_cad"
            deferred_count = len(plan.operations)
            updated_at = plan.created_at.isoformat()
        if not include_completed and status not in active_statuses:
            continue
        tasks.append(
            {
                "task_id": plan.plan_id,
                "plan_id": plan.plan_id,
                "prompt": plan.prompt,
                "status": status,
                "target_uris": plan.selected_scope_uris,
                "selection_uri": plan.selection_uri,
                "operation_kinds": operation_kinds,
                "unresolved_questions": plan.unresolved_questions,
                "deferred_count": deferred_count,
                "created_at": plan.created_at.isoformat(),
                "updated_at": updated_at,
                "cad_job_id": (
                    str(latest_generation.data.get("job_id"))
                    if latest_generation is not None
                    else None
                ),
            }
        )
    tasks.sort(key=lambda task: (task["updated_at"], task["task_id"]), reverse=True)
    return {
        "project_id": project_id,
        "active_count": sum(task["status"] in active_statuses for task in tasks),
        "tasks": tasks,
    }


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
        reversible_patches: list[dict[str, Any]] = []
        for patch in safe_patches:
            target = current.objects.get(patch["object_uri"])
            previous = target.parameters.get(patch["parameter"]) if target else None
            reversible_patches.append(
                {
                    **patch,
                    "previous_parameter": previous.model_dump(mode="json") if previous else None,
                }
            )
        dimension_overrides = dimension_overrides_for_change(current, reversible_patches)
        applied_events = _run_command(
            project_id,
            "change.apply",
            user.email,
            {
                "new_revision": f"{current.revision}-dsl-{execution.execution_id[-8:]}",
                "parameter_patches": reversible_patches,
                "approval_state": "approved",
                "dsl_execution_id": execution.execution_id,
            },
        )
        stored_events.extend(applied_events)
        applied_event = next(item for item in applied_events if item.event_type == "ChangeApplied")
        generation, generation_events = _queue_cad_regeneration(
            project_id,
            user.email,
            source_event_id=applied_event.event_id,
            plan_id=None,
            target_uris=sorted({item["object_uri"] for item in reversible_patches}),
            prompt=f"TwinScript: {parsed.document.metadata.name}",
            dimension_overrides=dimension_overrides,
        )
        stored_events.extend(generation_events)
    else:
        generation = {"status": "not_required"}

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
            "generation": generation,
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
    body: ApplyChangePlanRequest | None = None,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    role = authorize_project(project_id, user, "change.apply")
    snapshot = queries.project(project_id)
    if plan_id not in snapshot.change_plans:
        raise HTTPException(status_code=404, detail="Change plan not found")
    plan = snapshot.change_plans[plan_id]
    if plan.base_revision != snapshot.revision:
        raise ConcurrencyError(
            f"Change plan {plan_id} is stale: base revision {plan.base_revision!r}, "
            f"current revision {snapshot.revision!r}; create a new plan"
        )
    payload = planner.compile_apply_payload(plan, snapshot)
    dimension_overrides = dimension_overrides_for_change(snapshot, payload["parameter_patches"])
    validate_parameter_change(
        snapshot,
        payload["parameter_patches"],
        dimension_overrides=dimension_overrides,
    )
    annotation_uri = body.annotation_uri if body else None
    if annotation_uri:
        annotation = snapshot.annotations.get(annotation_uri)
        if annotation is None or annotation.selection.uri != plan.selection_uri:
            raise HTTPException(status_code=409, detail="Annotation does not match the change plan selection")
        payload["annotation_uri"] = annotation_uri
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
    if annotation_uri and payload["parameter_patches"]:
        stored.extend(
            commands.execute(
                CommandEnvelope(
                    command_type="annotation.status",
                    project_id=project_id,
                    expected_version=store.current_version(project_id),
                    actor=user.email,
                    payload={"annotation_uri": annotation_uri, "status": "resolved"},
                )
            )
        )
    generation: dict[str, Any] = {"status": "not_required"}
    if payload["parameter_patches"]:
        applied_event = next(item for item in stored if item.event_type == "ChangeApplied")
        generation, generation_events = _queue_cad_regeneration(
            project_id,
            user.email,
            source_event_id=applied_event.event_id,
            plan_id=plan.plan_id,
            target_uris=sorted({item["object_uri"] for item in payload["parameter_patches"]}),
            prompt=plan.prompt,
            dimension_overrides=dimension_overrides,
        )
        stored.extend(generation_events)
    await hub.broadcast(project_id, {"events": [item.model_dump(mode="json") for item in stored]})
    return {
        "result": payload,
        "generation": generation,
        "events": [item.model_dump(mode="json") for item in stored],
    }


@app.post("/api/v1/projects/{project_id}/change-history/{event_id}/undo")
async def undo_change(
    project_id: str,
    event_id: str,
    user: AuthPrincipal = Depends(principal),
) -> dict[str, Any]:
    authorize_project(project_id, user, "change.apply")
    snapshot = queries.project(project_id)
    events, reverted = _change_history(project_id)
    target = next((event for event in events if event.event_id == event_id), None)
    if target is None or target.event_type != "ChangeApplied":
        raise HTTPException(status_code=404, detail="Applied change not found")
    if event_id in reverted:
        raise HTTPException(status_code=409, detail="Change has already been undone")
    if not _change_is_latest_for_parameters(target, events):
        raise HTTPException(
            status_code=409,
            detail="A newer change touches the same parameter; undo the newer change first",
        )
    inverse: list[dict[str, Any]] = []
    for patch in target.data.get("parameter_patches", []):
        if "previous_parameter" not in patch:
            raise HTTPException(status_code=409, detail="Legacy change has no reversible parameter snapshot")
        inverse_patch: dict[str, Any] = {
            "object_uri": patch["object_uri"],
            "parameter": patch["parameter"],
            "operation_id": f"undo:{patch.get('operation_id', event_id)}",
        }
        previous = patch["previous_parameter"]
        if previous is None:
            inverse_patch["remove"] = True
        else:
            inverse_patch.update(
                {
                    "value": previous["value"],
                    "unit": previous.get("unit"),
                    "restore_parameter": previous,
                }
            )
        inverse.append(inverse_patch)
    if not inverse:
        raise HTTPException(status_code=409, detail="Change contains no parameter updates to undo")
    payload = {
        "plan_id": target.data.get("plan_id"),
        "reverts_event_id": event_id,
        "new_revision": f"rev-{snapshot.stream_version + 1}",
        "parameter_patches": inverse,
        "deferred_operations": [],
        "scope_uris": target.data.get("scope_uris", []),
        "approval_state": "approved",
    }
    if target.data.get("annotation_uri"):
        payload["annotation_uri"] = target.data["annotation_uri"]
    stored = commands.execute(
        CommandEnvelope(
            command_type="change.revert",
            project_id=project_id,
            expected_version=snapshot.stream_version,
            actor=user.email,
            payload=payload,
        )
    )
    annotation_uri = payload.get("annotation_uri")
    if annotation_uri:
        stored.extend(
            commands.execute(
                CommandEnvelope(
                    command_type="annotation.status",
                    project_id=project_id,
                    expected_version=store.current_version(project_id),
                    actor=user.email,
                    payload={"annotation_uri": annotation_uri, "status": "open"},
                )
            )
        )
    reverted_event = next(item for item in stored if item.event_type == "ChangeReverted")
    generation, generation_events = _queue_cad_regeneration(
        project_id,
        user.email,
        source_event_id=reverted_event.event_id,
        plan_id=payload.get("plan_id"),
        target_uris=sorted({item["object_uri"] for item in inverse}),
        prompt=f"Undo change {event_id}",
    )
    stored.extend(generation_events)
    await hub.broadcast(project_id, {"events": [item.model_dump(mode="json") for item in stored]})
    return {
        "result": payload,
        "generation": generation,
        "events": [item.model_dump(mode="json") for item in stored],
    }


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


@app.get("/api/v1/projects/{project_id}/drawings.pdf")
def download_drawings_pdf(
    project_id: str,
    user: AuthPrincipal = Depends(principal),
) -> Response:
    authorize_project(project_id, user, "artifact.download")
    snapshot = queries.project(project_id)
    drawings = _project_drawings(snapshot)
    if not drawings:
        raise HTTPException(status_code=404, detail="Project has no downloadable SVG drawing views")
    try:
        content = render_drawings_pdf(drawings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    filename = f"{project_id}-{snapshot.revision}-drawings.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _project_drawings(snapshot: Any) -> list[tuple[str, Path]]:
    drawings: list[tuple[str, Path]] = []
    for view, artifact_uri in snapshot.metadata.get("default_2d_views", {}).items():
        artifact = snapshot.artifacts.get(str(artifact_uri))
        if artifact is not None and artifact.media_type == "image/svg+xml":
            drawings.append((str(view), _resolved_artifact_path(artifact.path)))
    return drawings


def _decode_tab_screenshot(value: str | None) -> bytes | None:
    if value is None:
        return None
    prefix = "data:image/png;base64,"
    if not value.startswith(prefix):
        raise ValueError("screenshot_png_data_url must contain a base64 PNG data URL")
    try:
        content = b64decode(value[len(prefix) :], validate=True)
    except (Base64Error, ValueError) as exc:
        raise ValueError("screenshot_png_data_url is not valid base64") from exc
    if len(content) > 5_000_000:
        raise ValueError("Decoded PNG exceeds the 5 MB limit")
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("screenshot_png_data_url does not contain a PNG")
    return content


@app.post("/api/v1/projects/{project_id}/tabs/{tab}.pdf")
def download_tab_pdf(
    project_id: str,
    tab: str,
    body: TabPdfRequest,
    user: AuthPrincipal = Depends(principal),
) -> Response:
    authorize_project(project_id, user, "artifact.download")
    if tab not in TAB_PDF_TITLES:
        raise HTTPException(status_code=422, detail=f"Unsupported tab: {tab}")
    snapshot = queries.project(project_id)
    if body.selected_object_uri and body.selected_object_uri not in snapshot.objects:
        raise HTTPException(status_code=422, detail="Selected object does not exist in this project")
    try:
        screenshot = _decode_tab_screenshot(body.screenshot_png_data_url)
        content = render_tab_pdf(
            snapshot,
            tab,
            content_text=body.content_text,
            screenshot_png=screenshot,
            selected_object_uri=body.selected_object_uri,
            drawings=_project_drawings(snapshot),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    slug = {
        "view3d": "3d",
        "view2d": "2d",
        "spec": "specification-xbom",
        "lifecycle": "lifecycle",
        "tests": "tests-simulations",
        "fixation": "feature-lenses",
        "evolution": "evolution-dsl",
    }[tab]
    filename = f"{project_id}-{snapshot.revision}-{slug}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/v1/projects/{project_id}/export")
def export_project(project_id: str, user: AuthPrincipal = Depends(principal)) -> FileResponse:
    authorize_project(project_id, user, "artifact.download")
    snapshot = queries.project(project_id)
    path = settings.data_dir / "artifacts" / f"{project_id}-{snapshot.revision}{settings.export_extension}"
    export_project_bundle(
        snapshot,
        queries.events(project_id),
        path,
        project_root=PROJECT_ROOT,
        digital_twin_root=settings.kicad_root,
        object_root=settings.data_dir / "artifacts" / "objects" / "sha256",
    )
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
