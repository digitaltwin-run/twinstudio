from __future__ import annotations

import json
from pathlib import Path

from twinstudio.cad_regeneration import (
    CadChangeInvalid,
    dimension_overrides_for_change,
    housing_config_from_snapshot,
    physical_component_height,
    records_from_manifest,
    validate_parameter_change,
)
from twinstudio.domain import ProjectSnapshot

ROOT = Path(__file__).resolve().parents[1]


def _snapshot() -> ProjectSnapshot:
    return ProjectSnapshot.model_validate(
        json.loads((ROOT / "examples/rpi5-camera3/project.json").read_text(encoding="utf-8"))
    )


def test_housing_config_uses_current_project_parameters() -> None:
    snapshot = _snapshot()
    base = snapshot.objects["poa://demo/demo-rpi5@main/part/base"]
    lid = snapshot.objects["poa://demo/demo-rpi5@main/part/lid"]
    base.parameters["width"].value = 82
    base.parameters["wall_thickness"].value = 3.2
    lid.parameters["total_height"].value = 44
    snapshot.revision = "rev-test"

    config = housing_config_from_snapshot(snapshot)

    assert config.dimensions.external_width == 82
    assert config.dimensions.wall_thickness == 3.2
    assert config.dimensions.total_height == 44
    assert config.metadata.revision == "rev-test"
    assert config.artifacts.export_stl is True
    assert config.artifacts.export_svg is True
    assert config.artifacts.export_glb is False


def test_base_height_change_preserves_physical_lid_height() -> None:
    snapshot = _snapshot()
    base = snapshot.objects["poa://demo/demo-rpi5@main/part/base"]
    lid = snapshot.objects["poa://demo/demo-rpi5@main/part/lid"]
    patches = [{"object_uri": base.uri, "parameter": "height", "value": 21.0}]

    overrides = dimension_overrides_for_change(snapshot, patches)
    base.parameters["height"].value = 21.0
    config = housing_config_from_snapshot(snapshot, dimension_overrides=overrides)

    assert overrides == {"lid_height_mm": 15.0}
    assert config.dimensions.base_height == 21.0
    assert config.dimensions.lid_height == 15.0
    assert config.dimensions.total_height == 36.0
    assert lid.parameters["total_height"].value == 40.0


def test_lid_physical_height_change_does_not_resize_base() -> None:
    snapshot = _snapshot()
    base = snapshot.objects["poa://demo/demo-rpi5@main/part/base"]
    lid = snapshot.objects["poa://demo/demo-rpi5@main/part/lid"]
    patches = [{"object_uri": lid.uri, "parameter": "height", "value": 12.0}]

    assert physical_component_height(snapshot, lid.uri) == 15.0
    overrides = dimension_overrides_for_change(snapshot, patches)
    config = housing_config_from_snapshot(snapshot, dimension_overrides=overrides)

    assert overrides == {"lid_height_mm": 12.0}
    assert config.dimensions.base_height == 25.0
    assert config.dimensions.lid_height == 12.0
    assert config.dimensions.total_height == 37.0
    assert base.parameters["height"].value == 25.0


def test_invalid_lid_height_is_rejected_before_project_state_changes() -> None:
    snapshot = _snapshot()
    lid = snapshot.objects["poa://demo/demo-rpi5@main/part/lid"]
    patches = [{"object_uri": lid.uri, "parameter": "height", "value": 12.0, "unit": "mm"}]
    overrides = dimension_overrides_for_change(snapshot, patches)

    try:
        validate_parameter_change(snapshot, patches, dimension_overrides=overrides)
    except CadChangeInvalid as exc:
        assert [item["code"] for item in exc.warnings] == ["AUX_BOSS_TOP_ABOVE_LID"]
    else:
        raise AssertionError("invalid lid geometry was accepted")

    assert "height" not in lid.parameters
    assert lid.parameters["total_height"].value == 40.0


def test_valid_lid_height_passes_preflight_without_mutating_snapshot() -> None:
    snapshot = _snapshot()
    lid = snapshot.objects["poa://demo/demo-rpi5@main/part/lid"]
    patches = [{"object_uri": lid.uri, "parameter": "height", "value": 14.0, "unit": "mm"}]
    overrides = dimension_overrides_for_change(snapshot, patches)

    warnings = validate_parameter_change(snapshot, patches, dimension_overrides=overrides)

    assert warnings
    assert not any(item["severity"] == "error" for item in warnings)
    assert "height" not in lid.parameters


def test_last_generated_lid_height_survives_subsequent_base_changes() -> None:
    snapshot = _snapshot()
    base = snapshot.objects["poa://demo/demo-rpi5@main/part/base"]
    lid = snapshot.objects["poa://demo/demo-rpi5@main/part/lid"]
    generated = {
        "base_height_mm": 21.0,
        "lid_height_mm": 15.0,
        "total_height_mm": 36.0,
        "source_total_height_mm": 40.0,
    }
    base.metadata["cad_dimensions"] = generated
    lid.metadata["cad_dimensions"] = generated
    base.parameters["height"].value = 17.0

    config = housing_config_from_snapshot(snapshot)

    assert config.dimensions.base_height == 17.0
    assert config.dimensions.lid_height == 15.0
    assert config.dimensions.total_height == 32.0


def test_explicit_total_height_change_recomputes_lid_height() -> None:
    snapshot = _snapshot()
    base = snapshot.objects["poa://demo/demo-rpi5@main/part/base"]
    lid = snapshot.objects["poa://demo/demo-rpi5@main/part/lid"]
    generated = {
        "base_height_mm": 21.0,
        "lid_height_mm": 15.0,
        "total_height_mm": 36.0,
        "source_total_height_mm": 40.0,
    }
    base.metadata["cad_dimensions"] = generated
    lid.metadata["cad_dimensions"] = generated
    base.parameters["height"].value = 21.0
    lid.parameters["total_height"].value = 44.0

    config = housing_config_from_snapshot(snapshot)

    assert config.dimensions.total_height == 44.0
    assert config.dimensions.lid_height == 23.0


def test_dimension_override_detection_is_safe_for_non_housing_projects() -> None:
    snapshot = _snapshot()
    snapshot.objects = {
        uri: node
        for uri, node in snapshot.objects.items()
        if not uri.endswith(("/part/base", "/part/lid"))
    }

    assert dimension_overrides_for_change(snapshot, []) == {}


def test_generated_files_replace_stable_artifact_uris_and_viewer_paths(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot.revision = "rev-42"
    job_id = "cad-test-42"
    job_root = tmp_path / "cad-jobs" / job_id
    generated = [
        "3d/base.stl",
        "3d/lid.stl",
        "2d/assembly/assembly_front.svg",
        "2d/assembly/assembly_top.svg",
        "2d/assembly/assembly_side.svg",
    ]
    manifest_records = []
    for index, relative in enumerate(generated, start=1):
        path = job_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"generated-{relative}".encode())
        manifest_records.append(
            {
                "path": relative,
                "sha256": f"sha-{index}",
                "size_bytes": path.stat().st_size,
            }
        )

    result = records_from_manifest(
        snapshot,
        tmp_path,
        job_id,
        {"job_id": job_id, "artifacts": manifest_records},
        generated_dimensions={
            "base_height_mm": 21.0,
            "lid_height_mm": 15.0,
            "total_height_mm": 36.0,
            "source_total_height_mm": 40.0,
        },
    )

    by_key = {item.uri.rsplit("/", 1)[-1]: item for item in result.artifacts}
    assert set(by_key) == {
        "base-stl",
        "lid-stl",
        "assembly-front",
        "assembly-top",
        "assembly-side",
    }
    assert by_key["base-stl"].path == f"cad-jobs/{job_id}/3d/base.stl"
    assert by_key["base-stl"].revision == "rev-42"
    assert by_key["assembly-front"].sha256 == "sha-3"
    assert result.objects[0].metadata["viewer_mesh"] == by_key["base-stl"].path
    assert result.objects[1].metadata["viewer_mesh"] == by_key["lid-stl"].path
    assert result.objects[1].metadata["cad_dimensions"]["lid_height_mm"] == 15.0
    assert result.objects[1].parameters["height"].value == 15.0
    assert result.objects[1].parameters["height"].status == "derived"
