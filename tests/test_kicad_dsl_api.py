import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import twinstudio.api as api_module
import twinstudio.scad_dsl as scad_dsl
from twinstudio.bus import CommandBus, QueryService
from twinstudio.eda_operation_planner import EdaOperationProposal
from twinstudio.event_store import EventStore
from twinstudio.kicad_dsl import KicadDslError
from twinstudio.mqtt_bus import NullPublisher

SCH = """(kicad_sch (version 20211123) (generator eeschema)
  (symbol (lib_id "local:R") (at 10 20 0) (unit 1)
    (uuid 11111111-1111-1111-1111-111111111111)
    (property "Reference" "R1" (id 0) (at 10 20 0))
    (property "Value" "1k" (id 1) (at 10 21 0))
    (property "Footprint" "local:R_0603" (id 2) (at 10 22 0) hide))
)\n"""

SVG = """<svg xmlns=\"http://www.w3.org/2000/svg\"><text x=\"1\" y=\"2\">Warstwa 2</text><rect width=\"4\" height=\"5\"/></svg>"""
SCAD = """// panel\nW = 148; H = 64; T = 3; R = 2.5;\nmodule plate() { cube([W, H, T]); }\nplate();\n"""


def test_eda_rest_vertical_slice(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "panel.kicad_sch").write_text(SCH, encoding="utf-8")
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

    inspected = client.get("/api/v1/eda/sch2dsl", params={"path": "panel.kicad_sch"})
    assert inspected.status_code == 200
    assert inspected.json()["items"][0]["reference"] == "R1"

    planned = client.post(
        "/api/v1/eda/nl2dsl",
        json={"path": "panel.kicad_sch", "prompt": "ustaw wartość R1 na 10k"},
    )
    assert planned.status_code == 200
    assert planned.json()["mode"] == "local"
    document = planned.json()["document"]

    checked = client.post(
        "/api/v1/eda/dsl2sch", json={"document": document, "dry_run": True}
    )
    assert checked.status_code == 200
    assert checked.json()["valid"] is True

    applied = client.post(
        "/api/v1/eda/dsl2sch", json={"document": document, "dry_run": False}
    )
    assert applied.status_code == 200
    result = applied.json()
    candidate = tmp_path / "data" / "artifacts" / "kicad-edits" / result["candidate_path"]
    assert '(property "Value" "10k"' in candidate.read_text(encoding="utf-8")
    assert json.loads(candidate.with_name("change.json").read_text())["schema_id"] == "twinstudio.eda-result/v1"


def test_eda_plan_target_error_uses_stable_problem_code(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "panel.kicad_sch").write_text(SCH, encoding="utf-8")
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
    response = TestClient(api_module.app).post(
        "/api/v1/eda/nl2dsl",
        json={"path": "panel.kicad_sch", "prompt": "popraw szyny zasilania"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"] == "Prompt musi wskazać dokładnie jeden element, np. R1, SW3 lub RJ45."
    assert payload["error"]["code"] == "EDA-DSL-TARGET-REQUIRED-001"
    assert payload["error"]["operation"] == "POST /api/v1/eda/nl2dsl"


def test_eda_operation_plan_is_read_only_and_maps_planner_errors(monkeypatch) -> None:
    captured: dict = {}

    def propose(**kwargs):
        captured.update(kwargs)
        return (
            EdaOperationProposal(
                decision="propose",
                operation="optimize_placement_and_routing",
                why="Reduces routing cost.",
                interpretation="Search capacitor placement and reroute.",
                limitations=["Candidate only."],
            ),
            "subllm:zai/glm-5.3",
        )

    monkeypatch.setattr(api_module, "propose_eda_operation", propose)
    client = TestClient(api_module.app)
    body = {
        "prompt": "Zoptymalizuj routing",
        "source": {"path": "pcb/panel9.kicad_pcb", "kind": "pcb"},
        "operations": [{"id": "optimize_placement_and_routing"}],
        "project_context": {"placement_search": {"max_candidates": 5}},
    }

    response = client.post("/api/v1/eda/operation-plan", json=body)

    assert response.status_code == 200
    assert response.json()["mode"] == "subllm:zai/glm-5.3"
    assert response.json()["proposal"]["operation"] == "optimize_placement_and_routing"
    assert captured == {
        "prompt": body["prompt"],
        "source": body["source"],
        "operations": body["operations"],
        "project_context": body["project_context"],
        "settings": api_module.settings,
    }

    monkeypatch.setattr(
        api_module,
        "propose_eda_operation",
        lambda **_kwargs: (_ for _ in ()).throw(KicadDslError("route unavailable")),
    )
    rejected = client.post("/api/v1/eda/operation-plan", json=body)
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "route unavailable"
    assert rejected.json()["error"]["code"] == "EDA-DSL-VALIDATION-001"
    assert rejected.json()["error"]["details"]["operation"] == "eda.operation-plan"


def test_svg_rest_vertical_slice(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "drawing.svg").write_text(SVG, encoding="utf-8")
    monkeypatch.setattr(
        api_module,
        "settings",
        SimpleNamespace(
            kicad_root=source_root,
            data_dir=tmp_path / "data",
            litellm_model="",
            litellm_api_base="",
            litellm_api_key="",
            subllm_enabled=False,
        ),
    )
    client = TestClient(api_module.app)

    inspected = client.get("/api/v1/svg2dsl", params={"path": "drawing.svg"})
    assert inspected.status_code == 200
    assert inspected.json()["elements"][0]["text"] == "Warstwa 2"

    analyzed = client.post("/api/v1/svg/analyze", json={"path": "drawing.svg"})
    assert analyzed.status_code == 200
    assert analyzed.json()["renderer"] == "svg-structure"
    assert analyzed.json()["summary"]["text"] == 1
    assert any(item["code"] == "SVG-VIEWBOX-001" for item in analyzed.json()["findings"])

    planned = client.post(
        "/api/v1/svg/nl2dsl",
        json={"path": "drawing.svg", "prompt": 'zmień napis "Warstwa 2" na "Warstwa dolna"'},
    )
    assert planned.status_code == 200
    document = planned.json()["document"]
    assert document["operations"] == [{"op": "set_text", "target": "svg:text:0", "value": "Warstwa dolna"}]

    checked = client.post("/api/v1/svg/apply", json={"document": document, "dry_run": True})
    assert checked.status_code == 200
    assert checked.json()["valid"] is True

    applied = client.post("/api/v1/svg/apply", json={"document": document, "dry_run": False})
    assert applied.status_code == 200
    result = applied.json()
    candidate = tmp_path / "data" / "artifacts" / "kicad-edits" / result["candidate_path"]
    assert "Warstwa dolna" in candidate.read_text(encoding="utf-8")
    assert json.loads(candidate.with_name("change.json").read_text())["schema_id"] == "twinstudio.svg-result/v1"


def test_scad_rest_vertical_slice(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "panel.scad").write_text(SCAD, encoding="utf-8")
    monkeypatch.setattr(
        api_module,
        "settings",
        SimpleNamespace(
            kicad_root=source_root,
            data_dir=tmp_path / "data",
            litellm_model="",
            litellm_api_base="",
            litellm_api_key="",
            subllm_enabled=False,
        ),
    )
    client = TestClient(api_module.app)

    inspected = client.get("/api/v1/scad2dsl", params={"path": "panel.scad"})
    assert inspected.status_code == 200
    assert [item["name"] for item in inspected.json()["variables"]] == ["W", "H", "T", "R"]

    planned = client.post(
        "/api/v1/scad/nl2dsl",
        json={"path": "panel.scad", "prompt": "ustaw T na 4"},
    )
    assert planned.status_code == 200
    document = planned.json()["document"]
    assert document["operations"] == [{"op": "set_variable", "target": "scad:variable:T", "value": 4.0}]

    checked = client.post("/api/v1/scad/apply", json={"document": document, "dry_run": True})
    assert checked.status_code == 200
    assert checked.json()["valid"] is True

    rechecked = client.post("/api/v1/scad/validate", json={"source": SCAD})
    assert rechecked.status_code == 200
    assert "status" in rechecked.json()

    applied = client.post("/api/v1/scad/apply", json={"document": document, "dry_run": False})
    assert applied.status_code == 200
    result = applied.json()
    candidate = tmp_path / "data" / "artifacts" / "kicad-edits" / result["candidate_path"]
    assert "T = 4;" in candidate.read_text(encoding="utf-8")
    assert json.loads(candidate.with_name("change.json").read_text())["schema_id"] == "twinstudio.scad-result/v1"

    unsafe = document.copy()
    unsafe["operations"] = [{"op": "set_variable", "target": "scad:variable:unknown", "value": 5}]
    rejected = client.post("/api/v1/scad/apply", json={"document": unsafe, "dry_run": True})
    assert rejected.status_code == 422


@pytest.mark.parametrize(
    (
        "kind",
        "filename",
        "source",
        "prompt",
        "plan_schema",
        "candidate_schema",
        "result_schema",
    ),
    [
        (
            "svg",
            "drawing.svg",
            SVG,
            'zmień napis "Warstwa 2" na "Warstwa dolna"',
            "twinstudio.svg-event/change-planned/v1",
            "twinstudio.svg-event/candidate-created/v1",
            "twinstudio.svg-result/v1",
        ),
        (
            "scad",
            "panel.scad",
            SCAD,
            "ustaw T na 4",
            "twinstudio.scad-event/change-planned/v1",
            "twinstudio.scad-event/candidate-created/v1",
            "twinstudio.scad-result/v1",
        ),
    ],
)
def test_text_candidate_cycle_records_format_specific_project_history(
    tmp_path: Path,
    monkeypatch,
    kind: str,
    filename: str,
    source: str,
    prompt: str,
    plan_schema: str,
    candidate_schema: str,
    result_schema: str,
) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / filename).write_text(source, encoding="utf-8")
    data_dir = tmp_path / "data"
    local_store = EventStore(f"sqlite:///{tmp_path / 'events.db'}")
    monkeypatch.setattr(api_module, "store", local_store)
    monkeypatch.setattr(api_module, "queries", QueryService(local_store))
    monkeypatch.setattr(
        api_module,
        "commands",
        CommandBus(local_store, NullPublisher()),
    )
    monkeypatch.setattr(
        api_module,
        "settings",
        SimpleNamespace(
            kicad_root=source_root,
            data_dir=data_dir,
            litellm_model="",
            litellm_api_base="",
            litellm_api_key="",
            subllm_enabled=False,
        ),
    )
    client = TestClient(api_module.app)
    project_id = f"{kind}-candidate-test"

    planned = client.post(
        f"/api/v1/projects/{project_id}/{kind}/nl2dsl",
        json={"path": filename, "prompt": prompt},
    )
    assert planned.status_code == 200, planned.text
    assert planned.json()["history_event"]["data"]["schema_id"] == plan_schema

    applied = client.post(
        f"/api/v1/projects/{project_id}/{kind}/apply",
        json={
            "document": planned.json()["document"],
            "dry_run": False,
            "correlation_id": f"{kind}-candidate-cycle",
        },
    )
    assert applied.status_code == 200, applied.text
    payload = applied.json()
    assert payload["history_event"]["data"]["schema_id"] == candidate_schema
    assert payload["history_event"]["correlation_id"] == f"{kind}-candidate-cycle"
    manifest = json.loads(
        (data_dir / "artifacts" / "kicad-edits" / payload["candidate_path"])
        .with_name("change.json")
        .read_text(encoding="utf-8")
    )
    assert manifest["schema_id"] == result_schema
    assert manifest["project_id"] == project_id
    assert (source_root / "project.twinstudio.json").is_file()


def test_scad_validation_streams_source_to_configured_cad_runner(monkeypatch) -> None:
    captured = {}

    class Completed:
        returncode = 0
        stdout = "cube(size = [1, 1, 1], center = false);\n"
        stderr = ""

    monkeypatch.setenv("TWINSTUDIO_OPENSCAD_COMMAND", "cad-runner --isolated")
    monkeypatch.setattr(scad_dsl.shutil, "which", lambda executable: "/usr/bin/cad-runner")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return Completed()

    monkeypatch.setattr(scad_dsl.subprocess, "run", fake_run)

    validation = scad_dsl.validate_scad("cube(1);\n")

    assert validation["status"] == "validated"
    assert captured["command"] == ["cad-runner", "--isolated", "--export-format", "csg", "-o", "-", "-"]
    assert captured["input"] == "cube(1);\n"
