import hashlib
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from twinstudio import api as api_module
from twinstudio.bus import CommandBus, QueryService
from twinstudio.eda_chat import EdaChatMessage, respond_to_eda_chat
from twinstudio.event_store import EventStore
from twinstudio.mqtt_bus import NullPublisher


def _context() -> dict:
    return {
        "schema_id": "artifact-viewer.eda-chat-context/v1",
        "paths": ["pcb/panel.kicad_sch", "pcb/panel.kicad_pcb"],
        "parity": {"blocking": False, "counts": {"mismatches": 0}, "codes": []},
        "schematic_style": {"blocking": False, "findings": [{"code": "RULE_SPACING"}]},
        "pcb_style": {"blocking": False, "findings": []},
        "drc": {"blocking": False, "counts": {"violations": 0}},
    }


def test_chat_has_honest_deterministic_fallback() -> None:
    response = respond_to_eda_chat(
        _context(),
        [EdaChatMessage(role="user", content="Co poprawić, a czego nie ruszać?")],
        SimpleNamespace(subllm_enabled=False, litellm_model=""),
    )
    assert response.mode.startswith("local-fallback")
    assert response.requires_human_review is True
    assert any(fact.code == "parity_measured" for fact in response.facts)
    assert all(action.requires_candidate for action in response.proposed_actions)


def test_chat_endpoint_records_exchange_in_event_stream(tmp_path, monkeypatch) -> None:
    local_store = EventStore(f"sqlite:///{tmp_path / 'events.db'}")
    monkeypatch.setattr(api_module, "store", local_store)
    monkeypatch.setattr(api_module, "commands", CommandBus(local_store, NullPublisher()))
    monkeypatch.setattr(api_module, "queries", QueryService(local_store))
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(
        api_module,
        "settings",
        SimpleNamespace(
            data_dir=tmp_path / "data",
            kicad_root=project_root,
            subllm_enabled=False,
            litellm_model="",
        ),
    )
    context = _context()
    encoded = json.dumps(
        context, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    body = {
        "session_id": "chat-12345678",
        "sequence": 1,
        "paths": context["paths"],
        "context_sha256": hashlib.sha256(encoded).hexdigest(),
        "deterministic_context": context,
        "messages": [{"role": "user", "content": "Zdiagnozuj konflikt"}],
    }
    with TestClient(api_module.app) as client:
        first = client.post("/api/v1/projects/chat-project/eda/chat/respond", json=body)
        repeated = client.post("/api/v1/projects/chat-project/eda/chat/respond", json=body)
    assert first.status_code == 200
    assert first.json()["history_event"]["event_type"] == "ProjectUpdateRecorded"
    assert repeated.status_code == 200
    assert repeated.json()["history_event"]["event_id"] == first.json()["history_event"]["event_id"]
