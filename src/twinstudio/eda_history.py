"""Portable, event-backed history for EDA artifacts in a Digital Twin project."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from twinstudio.domain import EventEnvelope


class HistoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactHead(HistoryModel):
    artifact_id: str = Field(pattern=r"^artifact:[a-z0-9][a-z0-9._:-]{2,159}$")
    path: str
    media_type: str
    head_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision_id: str
    object_ref: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class TwinStudioProject(HistoryModel):
    schema_id: Literal["twinstudio.project/v1"] = "twinstudio.project/v1"
    project_id: str = Field(min_length=1, max_length=160)
    stream_id: str = Field(min_length=1, max_length=255)
    stream_version: int = Field(ge=0)
    updated_at: datetime
    artifacts: dict[str, ArtifactHead] = Field(default_factory=dict)


class EdaRevisionRef(HistoryModel):
    project_id: str = Field(min_length=1, max_length=160)
    artifact_id: str = Field(pattern=r"^artifact:[a-z0-9][a-z0-9._:-]{2,159}$")
    revision_id: str = Field(pattern=r"^rev:[A-Za-z0-9._:-]+$")
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EdaHistoryEntry(HistoryModel):
    schema_id: Literal["twinstudio.eda-history-entry/v1"] = "twinstudio.eda-history-entry/v1"
    event_id: str
    stream_version: int = Field(ge=1)
    event_type: Literal[
        "EdaChangePlanned",
        "EdaChangePlanFailed",
        "EdaSchematicAnalyzed",
        "EdaPcbAnalyzed",
        "EdaNetlistAnalyzed",
        "EdaSimulationAnalyzed",
        "SvgAnalyzed",
        "EdaValidationCompleted",
        "EdaCandidateCreated",
        "EdaCandidateDeleted",
        "EdaChangeAccepted",
        "EdaChangeRejected",
        "EdaRevisionPromoted",
        "EdaChangeReverted",
        "EdaHistoryImported",
        "ProjectUpdateRecorded",
    ]
    actor: str
    occurred_at: datetime
    correlation_id: str | None = None
    causation_id: str | None = None
    data: dict[str, Any]


EDA_EVENT_TYPES = {
    "EdaChangePlanned",
    "EdaChangePlanFailed",
    "EdaSchematicAnalyzed",
    "EdaPcbAnalyzed",
    "EdaNetlistAnalyzed",
    "EdaSimulationAnalyzed",
    "SvgAnalyzed",
    "EdaValidationCompleted",
    "EdaCandidateCreated",
    "EdaCandidateDeleted",
    "EdaChangeAccepted",
    "EdaChangeRejected",
    "EdaRevisionPromoted",
    "EdaChangeReverted",
    "EdaHistoryImported",
    "ProjectUpdateRecorded",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_id(project_id: str, path: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in project_id).strip("-")
    digest = sha256_bytes(PurePosixPath(path).as_posix().encode("utf-8"))[:20]
    return f"artifact:{slug or 'project'}:{digest}"


def revision_id(candidate_path: str, candidate_sha256: str) -> str:
    first = PurePosixPath(candidate_path).parts[0] if PurePosixPath(candidate_path).parts else "revision"
    safe = "".join(char if char.isalnum() or char in "-_." else "-" for char in first)
    return f"rev:{safe}:{candidate_sha256[:12]}"


def store_object(data_dir: Path, source: Path) -> tuple[str, Path]:
    digest = sha256_file(source)
    target = data_dir / "artifacts" / "objects" / "sha256" / digest[:2] / digest
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    return f"sha256:{digest}", target


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_descriptor(project_root: Path, project_id: str) -> TwinStudioProject:
    path = project_root / "project.twinstudio.json"
    if path.is_file():
        descriptor = TwinStudioProject.model_validate_json(path.read_text(encoding="utf-8"))
        if descriptor.project_id != project_id:
            raise ValueError(f"project.twinstudio.json belongs to {descriptor.project_id!r}")
        return descriptor
    return TwinStudioProject(
        project_id=project_id,
        stream_id=project_id,
        stream_version=0,
        updated_at=datetime.now(UTC),
    )


def update_descriptor(
    project_root: Path,
    project_id: str,
    stream_version: int,
    *,
    source_path: str | None = None,
    source_sha256: str | None = None,
    revision: str | None = None,
    object_ref: str | None = None,
) -> TwinStudioProject:
    descriptor = load_descriptor(project_root, project_id)
    if source_path and source_sha256 and revision and object_ref:
        suffix = Path(source_path).suffix.lower()
        media = {
            ".kicad_sch": "application/vnd.kicad.schematic",
            ".kicad_pcb": "application/vnd.kicad.pcb",
        }.get(suffix, "application/octet-stream")
        identity = artifact_id(project_id, source_path)
        descriptor.artifacts[identity] = ArtifactHead(
            artifact_id=identity,
            path=PurePosixPath(source_path).as_posix(),
            media_type=media,
            head_sha256=source_sha256,
            revision_id=revision,
            object_ref=object_ref,
        )
    descriptor.stream_version = stream_version
    descriptor.updated_at = datetime.now(UTC)
    _atomic_text(
        project_root / "project.twinstudio.json",
        json.dumps(descriptor.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
    )
    return descriptor


def eda_events(events: list[EventEnvelope]) -> list[EventEnvelope]:
    return [event for event in events if event.event_type in EDA_EVENT_TYPES]


def write_event_stream(project_root: Path, events: list[EventEnvelope]) -> Path:
    path = project_root / ".twinstudio" / "event-stream.ndjson"
    body = "".join(event.model_dump_json() + "\n" for event in events)
    _atomic_text(path, body)
    return path


LOG_CODE_ALIASES = {
    "EDA_ROUTING_REQUIRED": "EDA-PCB-ROUTING-001",
    "EDA_DRC_NOT_RUN": "EDA-PCB-DRC-001",
    "EDA_CONNECTIVITY_NOT_RUN": "EDA-SCH-NET-001",
    "EDA_PARITY_NOT_RUN": "EDA-SCH-PCB-SYNC-001",
    "EDA_FOOTPRINT_PARITY_NOT_RUN": "EDA-SCH-PCB-SYNC-001",
    "EDA_ERC_NOT_RUN": "EDA-SCH-NETGRAPH-001",
}
LOG_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")


def _log_code(value: str) -> str | None:
    """Projection codes belong to logs DSL, not to an adopter's Python enum."""
    mapped = LOG_CODE_ALIASES.get(value, value)
    return mapped if LOG_CODE_PATTERN.fullmatch(mapped) else None


def _event_code(data: dict[str, Any]) -> str | None:
    """Map internal validation labels to documented wellmanifest error codes."""
    error = data.get("error")
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        return _log_code(error["code"])
    if isinstance(data.get("code"), str):
        return _log_code(data["code"])
    for container in (data.get("analysis"), data.get("validation")):
        if not isinstance(container, dict):
            continue
        findings = container.get("findings")
        if isinstance(findings, list):
            for finding in findings:
                if not isinstance(finding, dict) or finding.get("severity") != "ERROR":
                    continue
                value = finding.get("code")
                if isinstance(value, str):
                    projected = _log_code(value)
                    if projected is not None:
                        return projected
        codes = container.get("codes")
        if not isinstance(codes, list):
            continue
        for value in codes:
            if not isinstance(value, str):
                continue
            projected = _log_code(value)
            if projected is not None:
                return projected
    return None


def _logs_outcome(event_type: str, data: dict[str, Any]) -> tuple[str, str, str]:
    if event_type == "EdaChangePlanFailed":
        return "FAILED", "validation_failed", "WARNING"
    if event_type == "ProjectUpdateRecorded":
        severity = "WARNING" if data.get("category") in {
            "error", "recommendation", "duplicate", "source_truth_conflict"
        } else "INFO"
        return "OBSERVED", str(data.get("category", "update")), severity
    if event_type == "EdaCandidateDeleted":
        return "SUCCEEDED", "deleted", "WARNING"
    if event_type == "EdaChangeRejected":
        return "REJECTED", "rejected", "WARNING"
    if event_type in {"EdaChangeAccepted", "EdaRevisionPromoted"}:
        return "ACCEPTED", "accepted", "INFO"
    if event_type == "EdaChangeReverted":
        return "SUCCEEDED", "reverted", "WARNING"
    if event_type == "EdaCandidateCreated":
        return "SUCCEEDED", "candidate", "INFO"
    if event_type in {"EdaSchematicAnalyzed", "EdaPcbAnalyzed", "EdaNetlistAnalyzed", "EdaSimulationAnalyzed"}:
        analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
        status = str(analysis.get("status", "ready"))
        return "OBSERVED", status, "WARNING" if _event_code(data) else "INFO"
    return "OBSERVED", "planned", "INFO"


def wellmanifest_projection(project_id: str, events: list[EventEnvelope]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    previous_hash = "0" * 64
    for sequence, source_event in enumerate(eda_events(events), start=1):
        outcome, state, severity = _logs_outcome(source_event.event_type, source_event.data)
        data_hash = sha256_bytes(canonical_json(source_event.data).encode("utf-8"))
        actor = source_event.actor.replace("@", "-")
        producer = f"human:{actor}" if "@" in source_event.actor else f"service:{actor}"
        occurred_at = source_event.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        evidence = source_event.data.get("evidence")
        if not isinstance(evidence, list):
            evidence = []
        evidence = [
            {"path": item["path"], "sha256": item["sha256"]}
            for item in evidence[:16]
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and isinstance(item.get("sha256"), str)
        ]
        event = {
            "schema": "wellmanifest.logs/event/v1",
            "eventId": f"event:twinstudio:{source_event.event_id}",
            "stream": "eda",
            "sequence": sequence,
            "eventType": "eda." + _snake(source_event.event_type.removeprefix("Eda")),
            "severity": severity,
            "mode": "PLAN" if source_event.event_type in {"EdaChangePlanned", "EdaChangePlanFailed"} else "APPLY",
            "occurredAt": occurred_at,
            "correlationId": source_event.correlation_id or source_event.event_id,
            "causationId": source_event.causation_id,
            "producer": producer,
            "source": "twinstudio.eda",
            "code": _event_code(source_event.data),
            "subjectRef": f"twinstudio:project/{project_id}/eda",
            "outcome": outcome,
            "subjectState": state,
            "evidence": evidence,
            "inputHash": data_hash,
            "receiptRef": None,
            "previousHash": previous_hash,
            "eventHash": "",
            "rawOutputIncluded": False,
            "secretMaterialIncluded": False,
        }
        event["eventHash"] = sha256_bytes(
            canonical_json({key: value for key, value in event.items() if key != "eventHash"}).encode("utf-8")
        )
        previous_hash = event["eventHash"]
        result.append(event)
    return result


def _snake(value: str) -> str:
    output = []
    for index, char in enumerate(value):
        if char.isupper() and index:
            output.append("_")
        output.append(char.lower())
    return "".join(output)


def write_wellmanifest_projection(project_root: Path, project_id: str, events: list[EventEnvelope]) -> Path:
    path = project_root / ".twinstudio" / "logs" / "eda.jsonl"
    body = "".join(canonical_json(event) + "\n" for event in wellmanifest_projection(project_id, events))
    _atomic_text(path, body)
    return path


def validate_hash_chain(events: list[dict[str, Any]]) -> list[str]:
    findings: list[str] = []
    previous = "0" * 64
    for expected, event in enumerate(events, start=1):
        if event.get("sequence") != expected:
            findings.append(f"sequence:{expected}")
        if event.get("previousHash") != previous:
            findings.append(f"previousHash:{expected}")
        calculated = sha256_bytes(
            canonical_json({key: value for key, value in event.items() if key != "eventHash"}).encode("utf-8")
        )
        if event.get("eventHash") != calculated:
            findings.append(f"eventHash:{expected}")
        previous = str(event.get("eventHash", ""))
    return findings
