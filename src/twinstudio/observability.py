from __future__ import annotations

import json
import logging
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
logger = logging.getLogger("twinstudio.observation")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ObservationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactUse(ObservationModel):
    uri: str
    purpose: str
    status: Literal["expected", "loading", "visible", "failed"] = "expected"
    path: str | None = None
    error_code: str | None = None


class UiContext(ObservationModel):
    """Small, explicit description of what one browser session currently shows."""

    kind: Literal["UIContext"] = "UIContext"
    schema_version: Literal["1.0"] = "1.0"
    session_id: str = Field(min_length=8, max_length=128)
    project_id: str = Field(min_length=1, max_length=200)
    route: str = Field(default="/", max_length=16000)
    active_tab: str = Field(default="view3d", max_length=100)
    selected_object_uri: str | None = None
    selection_uri: str | None = None
    active_tool: str | None = None
    viewer_state: Literal["idle", "loading", "ready", "partial", "error"] = "idle"
    loaded_mesh_count: int = Field(default=0, ge=0)
    expected_mesh_count: int = Field(default=0, ge=0)
    rendered_triangles: int = Field(default=0, ge=0)
    visible_artifact_uris: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactUse] = Field(default_factory=list)
    last_action: str | None = Field(default=None, max_length=200)
    error_code: str | None = None
    error_message: str | None = Field(default=None, max_length=4000)
    updated_at: datetime = Field(default_factory=_now)


class ProblemEnvelope(ObservationModel):
    """Stable error contract shared by REST responses, logs, UI context and LLM tools."""

    kind: Literal["ProblemEnvelope"] = "ProblemEnvelope"
    schema_version: Literal["1.0"] = "1.0"
    occurred_at: datetime = Field(default_factory=_now)
    level: Literal["warning", "error", "critical"] = "error"
    code: str = Field(pattern=ERROR_CODE_PATTERN.pattern)
    message: str
    source: str
    operation: str
    correlation_id: str
    project_id: str | None = None
    status_code: int | None = Field(default=None, ge=100, le=599)
    registry_uri: str
    retryable: bool = False
    ui_context: UiContext | None = None
    artifacts: list[ArtifactUse] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)

    def to_dsl(self) -> str:
        def line(name: str, value: Any) -> str:
            return f"{name} {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"

        lines = [
            "TWINOBS 1.0",
            line("KIND", self.kind),
            line("LEVEL", self.level),
            line("CODE", self.code),
            line("SOURCE", self.source),
            line("OPERATION", self.operation),
            line("CORRELATION", self.correlation_id),
            line("MESSAGE", self.message),
            line("REGISTRY", self.registry_uri),
            line("RETRYABLE", self.retryable),
        ]
        if self.project_id:
            lines.append(line("PROJECT", self.project_id))
        if self.status_code:
            lines.append(line("STATUS", self.status_code))
        for artifact in self.artifacts:
            lines.append(line("ARTIFACT", artifact.model_dump(mode="json", exclude_none=True)))
        if self.ui_context:
            lines.append(line("SCREEN", self.ui_context.model_dump(mode="json", exclude_none=True)))
        if self.details:
            lines.append(line("DETAILS", self.details))
        lines.append("END")
        return "\n".join(lines)


class UiContextStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._items: dict[tuple[str, str], UiContext] = {}
        self._latest: dict[str, str] = {}

    def put(self, context: UiContext) -> UiContext:
        refreshed = context.model_copy(update={"updated_at": _now()})
        with self._lock:
            self._items[(refreshed.project_id, refreshed.session_id)] = refreshed
            self._latest[refreshed.project_id] = refreshed.session_id
        return refreshed

    def get(self, project_id: str, session_id: str | None = None) -> UiContext | None:
        with self._lock:
            selected = session_id or self._latest.get(project_id)
            return self._items.get((project_id, selected)) if selected else None


class ObservationLogStore:
    """Thread-safe, bounded copy of emitted TWINOBS records for diagnostics."""

    def __init__(self, max_entries: int = 2000) -> None:
        self._lock = RLock()
        self._items: deque[dict[str, Any]] = deque(maxlen=max_entries)

    def append(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._items.append(dict(payload))

    def recent(self, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            matches = [
                dict(item)
                for item in self._items
                if project_id is None or item.get("project_id") == project_id
            ]
        return matches[-max(1, limit) :]

    def to_dsl(self, project_id: str | None = None, limit: int = 200) -> str:
        records = self.recent(project_id, limit)
        return "\n\n".join(str(item["dsl"]) for item in records if item.get("dsl"))


observation_logs = ObservationLogStore()


def error_playbook_path(error_root: Path, code: str) -> Path:
    if not ERROR_CODE_PATTERN.fullmatch(code):
        raise ValueError("Invalid error code")
    return error_root / f"{code}.md"


def load_error_playbook(error_root: Path, code: str) -> str:
    path = error_playbook_path(error_root, code)
    if not path.is_file():
        raise FileNotFoundError(code)
    return path.read_text(encoding="utf-8")


def make_problem(
    *,
    code: str,
    message: str,
    source: str,
    operation: str,
    correlation_id: str,
    project_id: str | None = None,
    status_code: int | None = None,
    retryable: bool = False,
    ui_context: UiContext | None = None,
    artifacts: list[ArtifactUse] | None = None,
    details: dict[str, Any] | None = None,
) -> ProblemEnvelope:
    return ProblemEnvelope(
        code=code,
        message=message,
        source=source,
        operation=operation,
        correlation_id=correlation_id,
        project_id=project_id,
        status_code=status_code,
        registry_uri=f"/api/v1/errors/{code}",
        retryable=retryable,
        ui_context=ui_context,
        artifacts=artifacts or [],
        details=details or {},
    )


def emit_problem(problem: ProblemEnvelope) -> None:
    payload = problem.model_dump(mode="json", exclude_none=True)
    payload["dsl"] = problem.to_dsl()
    observation_logs.append(payload)
    logger.error(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def emit_request_observation(
    *,
    correlation_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    project_id: str | None = None,
) -> None:
    payload = {
        "kind": "TwinObservation",
        "schema_version": "1.0",
        "occurred_at": _now().isoformat(),
        "level": "info",
        "code": "HTTP_REQUEST_COMPLETED",
        "correlation_id": correlation_id,
        "operation": f"{method} {path}",
        "status_code": status_code,
        "duration_ms": round(duration_ms, 3),
    }
    if project_id:
        payload["project_id"] = project_id
    dsl_lines = [
        "TWINOBS 1.0",
        'KIND "TwinObservation"',
        'LEVEL "info"',
        'CODE "HTTP_REQUEST_COMPLETED"',
        f"CORRELATION {json.dumps(correlation_id)}",
        f"OPERATION {json.dumps(payload['operation'])}",
    ]
    if project_id:
        dsl_lines.append(f"PROJECT {json.dumps(project_id)}")
    dsl_lines.extend(
        [
            f"STATUS {status_code}",
            f"DURATION_MS {payload['duration_ms']}",
            "END",
        ]
    )
    payload["dsl"] = "\n".join(dsl_lines)
    observation_logs.append(payload)
    logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
