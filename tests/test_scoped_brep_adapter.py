from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("cadquery")

ROOT = Path(__file__).resolve().parents[1]
CAD_WORKER = ROOT / "services" / "cad-worker"
if str(CAD_WORKER) not in sys.path:
    sys.path.insert(0, str(CAD_WORKER))

from scoped_brep_adapter import ScopedCadError, apply_scoped_operation  # noqa: E402


def _selection() -> dict:
    return json.loads(
        (ROOT / "examples" / "rpi5-camera3" / "selections" / "example-selection.json").read_text(
            encoding="utf-8"
        )
    )


def test_scoped_hole_cut_creates_valid_derived_brep(tmp_path: Path) -> None:
    selection = _selection()
    operation = {
        "target_uri": selection["target_object_uris"][0],
        "kind": "boolean_cut",
        "arguments": {"feature_type": "hole", "diameter_mm": 3.0},
    }

    journal = apply_scoped_operation(
        input_step=ROOT / "examples" / "rpi5-camera3" / "artifacts" / "3d" / "base.step",
        output_dir=tmp_path,
        selection=selection,
        operation=operation,
    )

    assert journal["adapter"] == "cadquery-scoped-brep-v1"
    assert journal["result"]["valid"] is True
    assert journal["result"]["solid_count"] == 1
    assert journal["result"]["volume_delta_mm3"] < 0
    assert (tmp_path / "scoped-result.step").is_file()
    assert (tmp_path / "scoped-result.stl").is_file()
    assert (tmp_path / "operation-journal.json").is_file()
    assert journal["outputs"]["step"]["sha256"]
    assert journal["outputs"]["stl"]["sha256"]


def test_scoped_adapter_rejects_target_outside_selection(tmp_path: Path) -> None:
    selection = _selection()
    operation = {
        "target_uri": "poa://demo/demo-rpi5@main/part/lid",
        "kind": "boolean_cut",
        "arguments": {"feature_type": "hole", "diameter_mm": 3.0},
    }

    with pytest.raises(ScopedCadError, match="selected object URIs"):
        apply_scoped_operation(
            input_step=ROOT / "examples" / "rpi5-camera3" / "artifacts" / "3d" / "base.step",
            output_dir=tmp_path,
            selection=selection,
            operation=operation,
        )
