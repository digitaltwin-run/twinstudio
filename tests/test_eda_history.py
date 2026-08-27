from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

import twinstudio.api as api_module
from twinstudio.bus import CommandBus, QueryService
from twinstudio.domain import EventEnvelope
from twinstudio.eda_history import (
    TwinStudioProject,
    validate_hash_chain,
    wellmanifest_projection,
)
from twinstudio.event_store import EventStore
from twinstudio.mqtt_bus import NullPublisher

SCH = """(kicad_sch (version 20211123) (generator eeschema)
  (symbol (lib_id "local:R") (at 10 20 0) (unit 1)
    (uuid 11111111-1111-1111-1111-111111111111)
    (property "Reference" "R1" (id 0) (at 10 20 0))
    (property "Value" "1k" (id 1) (at 10 21 0))
    (property "Footprint" "local:R_0603" (id 2) (at 10 22 0) hide))
)\n"""

PCB = """(kicad_pcb (version 20221018) (generator pcbnew)
  (net 0 "")
  (net 1 "GND")
  (footprint "local:R" (layer "F.Cu") (tstamp 11111111-1111-1111-1111-111111111111)
    (at 10 20) (fp_text reference "R1" (at 0 0) (layer "F.SilkS"))
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "GND")))
)\n"""


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_project_contract_and_wellmanifest_hash_chain(tmp_path: Path) -> None:
    descriptor = TwinStudioProject(
        project_id="demo",
        stream_id="demo",
        stream_version=1,
        updated_at="2026-08-26T10:00:00Z",
    )
    assert descriptor.schema_id == "twinstudio.project/v1"
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "schemas" / "twinstudio-project.schema.json").read_text()
    )
    assert schema["properties"]["schema_id"]["const"] == descriptor.schema_id
    Draft202012Validator(schema).validate(descriptor.model_dump(mode="json"))
    event = EventEnvelope(
        stream_id="demo",
        stream_version=1,
        event_type="EdaChangePlanned",
        data={"prompt": "change R1"},
        actor="creator@example.test",
    )
    projection = wellmanifest_projection("demo", [event])
    assert projection[0]["schema"] == "wellmanifest.logs/event/v1"
    assert validate_hash_chain(projection) == []
    history_schema = json.loads(
        (Path(__file__).resolve().parents[1] / "schemas" / "eda-history-entry.schema.json").read_text()
    )
    Draft202012Validator(history_schema).validate(
        {
            "schema_id": "twinstudio.eda-history-entry/v1",
            "event_id": event.event_id,
            "stream_version": event.stream_version,
            "event_type": event.event_type,
            "actor": event.actor,
            "occurred_at": event.occurred_at.isoformat(),
            "correlation_id": event.correlation_id,
            "causation_id": event.causation_id,
            "data": event.data,
        }
    )


def test_failed_eda_plan_is_projected_to_wellmanifest_logs(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "project"
    source_root.mkdir()
    (source_root / "panel.kicad_sch").write_text(SCH, encoding="utf-8")
    local_store = EventStore(f"sqlite:///{tmp_path / 'events.db'}")
    monkeypatch.setattr(api_module, "store", local_store)
    monkeypatch.setattr(api_module, "queries", QueryService(local_store))
    monkeypatch.setattr(api_module, "commands", CommandBus(local_store, NullPublisher()))
    monkeypatch.setattr(
        api_module,
        "settings",
        SimpleNamespace(
            kicad_root=source_root,
            data_dir=tmp_path / "data",
            litellm_model="",
            litellm_api_base="",
            litellm_api_key="",
        ),
    )
    client = TestClient(api_module.app)

    response = client.post(
        "/api/v1/projects/eda-failure/eda/nl2dsl",
        json={"path": "panel.kicad_sch", "prompt": "popraw szyny zasilania"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EDA-DSL-TARGET-REQUIRED-001"
    history = client.get("/api/v1/projects/eda-failure/eda/history")
    assert history.status_code == 200
    assert history.json()["events"][-1]["event_type"] == "EdaChangePlanFailed"
    log_entries = [
        json.loads(line)
        for line in (source_root / ".twinstudio" / "logs" / "eda.jsonl").read_text().splitlines()
    ]
    assert log_entries[-1]["code"] == "EDA-DSL-TARGET-REQUIRED-001"
    assert log_entries[-1]["outcome"] == "FAILED"
    assert log_entries[-1]["mode"] == "PLAN"
    assert validate_hash_chain(log_entries) == []


def test_project_eda_history_accept_promote_and_revert(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "project"
    source_root.mkdir()
    source = source_root / "panel.kicad_sch"
    source.write_text(SCH, encoding="utf-8")
    board = source_root / "panel.kicad_pcb"
    board.write_text(PCB, encoding="utf-8")
    data_dir = tmp_path / "data"
    local_store = EventStore(f"sqlite:///{tmp_path / 'events.db'}")
    local_publisher = NullPublisher()
    monkeypatch.setattr(api_module, "store", local_store)
    monkeypatch.setattr(api_module, "queries", QueryService(local_store))
    monkeypatch.setattr(api_module, "commands", CommandBus(local_store, local_publisher))
    monkeypatch.setattr(
        api_module,
        "settings",
        SimpleNamespace(
            kicad_root=source_root,
            data_dir=data_dir,
            litellm_model="",
            litellm_api_base="",
            litellm_api_key="",
        ),
    )
    client = TestClient(api_module.app)
    project_id = "eda-test"

    current_state = client.get(
        "/api/v1/eda/schematic-state", params={"path": source.name}
    )
    assert current_state.status_code == 200, current_state.text
    assert current_state.json()["status"] == "requires_follow_up"
    assert current_state.json()["codes"] == ["EDA-SCH-NETGRAPH-001"]
    network_state = client.post(
        "/api/v1/eda/schematic-state",
        json={
            "path": source.name,
            "netlist": {
                "source": source.name,
                "components": [
                    {
                        "reference": "R1",
                        "pins": [{"number": "1", "name": "~", "type": "passive"}],
                    }
                ],
                "nets": [
                    {
                        "name": "GND",
                        "nodes": [
                            {"reference": "R1", "pin": "1"},
                            {"reference": "#PWR01", "pin": "1"},
                        ],
                    }
                ],
            },
        },
    )
    assert network_state.status_code == 200, network_state.text
    assert network_state.json()["status"] == "ready"
    assert network_state.json()["summary"]["netlist_available"] is True
    assert network_state.json()["summary"]["nets"] == 1
    assert "EDA-SCH-NETGRAPH-001" not in network_state.json()["codes"]
    recorded_state = client.post(
        f"/api/v1/projects/{project_id}/eda/schematic-state",
        json={"path": source.name},
    )
    assert recorded_state.status_code == 200, recorded_state.text
    assert recorded_state.json()["history_event"]["event_type"] == "EdaSchematicAnalyzed"
    pcb_state = client.post(
        "/api/v1/eda/pcb-state",
        json={
            "path": board.name,
            "drc": {"violations": 1, "unconnected": 0, "categories": {"clearance": 1}},
        },
    )
    assert pcb_state.status_code == 200, pcb_state.text
    assert pcb_state.json()["codes"] == ["EDA-PCB-CLEARANCE-001"]
    recorded_pcb_state = client.post(
        f"/api/v1/projects/{project_id}/eda/pcb-state",
        json={
            "path": board.name,
            "drc": {"violations": 1, "unconnected": 0, "categories": {"clearance": 1}},
        },
    )
    assert recorded_pcb_state.status_code == 200, recorded_pcb_state.text
    assert recorded_pcb_state.json()["history_event"]["event_type"] == "EdaPcbAnalyzed"

    planned = client.post(
        f"/api/v1/projects/{project_id}/eda/nl2dsl",
        json={"path": source.name, "prompt": "ustaw wartość R1 na 10k"},
    )
    assert planned.status_code == 200, planned.text
    document = planned.json()["document"]
    candidate_response = client.post(
        f"/api/v1/projects/{project_id}/eda/apply",
        json={"document": document, "dry_run": False},
    )
    assert candidate_response.status_code == 200, candidate_response.text
    candidate_payload = candidate_response.json()
    decision = {
        "candidate_path": candidate_payload["candidate_path"],
        "source_sha256": sha(SCH),
        "candidate_sha256": candidate_payload["candidate_sha256"],
    }
    accepted = client.post(
        f"/api/v1/projects/{project_id}/eda/candidates/accept", json=decision
    )
    assert accepted.status_code == 200, accepted.text
    assert source.read_text(encoding="utf-8") == SCH

    promoted = client.post(
        f"/api/v1/projects/{project_id}/eda/candidates/promote", json=decision
    )
    assert promoted.status_code == 200, promoted.text
    assert '"10k"' in source.read_text(encoding="utf-8")
    promotion_event = promoted.json()["event"]
    reverted = client.post(
        f"/api/v1/projects/{project_id}/eda/revisions/revert",
        json={
            "promotion_event_id": promotion_event["event_id"],
            "expected_current_sha256": candidate_payload["candidate_sha256"],
        },
    )
    assert reverted.status_code == 200, reverted.text
    assert source.read_text(encoding="utf-8") == SCH

    history = client.get(f"/api/v1/projects/{project_id}/eda/history")
    assert history.status_code == 200
    event_types = [item["event_type"] for item in history.json()["events"]]
    assert event_types == [
        "EdaSchematicAnalyzed",
        "EdaPcbAnalyzed",
        "EdaChangePlanned",
        "EdaValidationCompleted",
        "EdaCandidateCreated",
        "EdaChangeAccepted",
        "EdaRevisionPromoted",
        "EdaChangeReverted",
    ]
    assert (source_root / "project.twinstudio.json").is_file()
    assert (source_root / ".twinstudio" / "event-stream.ndjson").is_file()
    assert (source_root / ".twinstudio" / "logs" / "eda.jsonl").is_file()
    log_entries = [
        json.loads(line)
        for line in (source_root / ".twinstudio" / "logs" / "eda.jsonl").read_text().splitlines()
    ]
    assert log_entries[0]["code"] == "EDA-SCH-NETGRAPH-001"
    assert log_entries[1]["code"] == "EDA-PCB-CLEARANCE-001"
    assert validate_hash_chain(log_entries) == []


def test_project_candidate_can_be_deleted_without_erasing_audit_history(
    tmp_path: Path, monkeypatch
) -> None:
    source_root = tmp_path / "project"
    source_root.mkdir()
    source = source_root / "panel.kicad_sch"
    source.write_text(SCH, encoding="utf-8")
    data_dir = tmp_path / "data"
    local_store = EventStore(f"sqlite:///{tmp_path / 'events.db'}")
    monkeypatch.setattr(api_module, "store", local_store)
    monkeypatch.setattr(api_module, "queries", QueryService(local_store))
    monkeypatch.setattr(api_module, "commands", CommandBus(local_store, NullPublisher()))
    monkeypatch.setattr(
        api_module,
        "settings",
        SimpleNamespace(kicad_root=source_root, data_dir=data_dir, litellm_model=""),
    )
    client = TestClient(api_module.app)
    project_id = "delete-test"
    planned = client.post(
        f"/api/v1/projects/{project_id}/eda/nl2dsl",
        json={"path": source.name, "prompt": "ustaw wartość R1 na 10k"},
    )
    created = client.post(
        f"/api/v1/projects/{project_id}/eda/apply",
        json={"document": planned.json()["document"], "dry_run": False},
    ).json()
    candidate = data_dir / "artifacts" / "kicad-edits" / created["candidate_path"]
    preview = source_root / ".twinstudio" / "previews" / f"{created['candidate_sha256']}.png"
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"png")

    deleted = client.post(
        f"/api/v1/projects/{project_id}/eda/candidates/delete",
        json={
            "candidate_path": created["candidate_path"],
            "source_sha256": sha(SCH),
            "candidate_sha256": created["candidate_sha256"],
            "reason": "cleanup",
        },
    )

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["event"]["event_type"] == "EdaCandidateDeleted"
    assert not candidate.exists()
    assert not preview.exists()
    history = client.get(f"/api/v1/projects/{project_id}/eda/history").json()["events"]
    assert [event["event_type"] for event in history][-2:] == [
        "EdaCandidateCreated",
        "EdaCandidateDeleted",
    ]
    assert history[-1]["data"]["candidate_sha256"] == created["candidate_sha256"]

    update_body = {
        "trigger": "automatic",
        "category": "duplicate",
        "summary": "Wykryto identyczne pliki",
        "source_paths": [source.name, "copy.kicad_sch"],
        "dedupe_key": "inventory:abc123",
        "details": {"duplicate_groups": 1},
    }
    recorded = client.post(f"/api/v1/projects/{project_id}/updates", json=update_body)
    repeated = client.post(f"/api/v1/projects/{project_id}/updates", json=update_body)
    assert recorded.json()["status"] == "recorded"
    assert recorded.json()["event"]["event_type"] == "ProjectUpdateRecorded"
    assert repeated.json()["status"] == "already_recorded"
    update_schema = json.loads(
        (Path(__file__).resolve().parents[1] / "schemas" / "project-update.schema.json").read_text()
    )
    Draft202012Validator(update_schema).validate(recorded.json()["event"]["data"])
    chronology = client.get(f"/api/v1/projects/{project_id}/updates").json()["events"]
    assert chronology[-1]["data"]["dedupe_key"] == "inventory:abc123"


def test_legacy_sidecars_migrate_without_changing_source(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "project"
    source_root.mkdir()
    source = source_root / "panel.kicad_sch"
    source.write_text(SCH, encoding="utf-8")
    source_hash = sha(SCH)
    candidate_text = SCH.replace('"1k"', '"10k"')
    candidate_hash = sha(candidate_text)
    data_dir = tmp_path / "data"
    candidate = data_dir / "artifacts" / "kicad-edits" / "legacy-1" / source.name
    candidate.parent.mkdir(parents=True)
    candidate.write_text(candidate_text, encoding="utf-8")
    manifest = {
        "schema_id": "twinstudio.eda-result/v1",
        "source": {"path": source.name, "sha256": source_hash, "kind": "schematic"},
        "candidate_path": f"legacy-1/{source.name}",
        "candidate_sha256": candidate_hash,
        "operations": [],
        "validation": {},
    }
    (candidate.parent / "change.json").write_text(json.dumps(manifest), encoding="utf-8")
    (candidate.parent / "approval.json").write_text(
        json.dumps({"status": "accepted", "candidate_sha256": candidate_hash}), encoding="utf-8"
    )
    local_store = EventStore(f"sqlite:///{tmp_path / 'events.db'}")
    monkeypatch.setattr(api_module, "store", local_store)
    monkeypatch.setattr(api_module, "queries", QueryService(local_store))
    monkeypatch.setattr(api_module, "commands", CommandBus(local_store, NullPublisher()))
    monkeypatch.setattr(
        api_module,
        "settings",
        SimpleNamespace(kicad_root=source_root, data_dir=data_dir),
    )
    client = TestClient(api_module.app)
    migrated = client.post("/api/v1/projects/legacy/eda/history/migrate", json={})
    assert migrated.status_code == 200, migrated.text
    assert {
        key: migrated.json()[key] for key in ("imported", "accepted", "originals_modified")
    } == {"imported": 1, "accepted": 1, "originals_modified": False}
    assert source.read_text(encoding="utf-8") == SCH
    history = client.get(
        "/api/v1/projects/legacy/eda/history", params={"artifact_path": source.name}
    ).json()["events"]
    assert [event["event_type"] for event in history] == [
        "EdaCandidateCreated",
        "EdaChangeAccepted",
    ]
    assert history[0]["data"]["candidate_sha256"] == candidate_hash
