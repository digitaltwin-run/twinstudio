import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import twinstudio.api as api_module
import twinstudio.scad_dsl as scad_dsl

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
