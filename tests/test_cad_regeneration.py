from __future__ import annotations

import json
from pathlib import Path

from twinstudio.cad_regeneration import housing_config_from_snapshot, records_from_manifest
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
