import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import twinstudio.api as api_module

SCH = """(kicad_sch (version 20211123) (generator eeschema)
  (symbol (lib_id "local:R") (at 10 20 0) (unit 1)
    (uuid 11111111-1111-1111-1111-111111111111)
    (property "Reference" "R1" (id 0) (at 10 20 0))
    (property "Value" "1k" (id 1) (at 10 21 0))
    (property "Footprint" "local:R_0603" (id 2) (at 10 22 0) hide))
)\n"""


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
