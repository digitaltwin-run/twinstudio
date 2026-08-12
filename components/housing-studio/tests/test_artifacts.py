import hashlib
import json
import zipfile
from pathlib import Path

from housing_studio.artifacts import GENERATOR_VERSION, generate_artifacts
from housing_studio.models import default_project_config


def test_complete_bundle(tmp_path: Path) -> None:
    manifest = generate_artifacts(default_project_config(), tmp_path, job_id="test-job")
    job_dir = tmp_path / "test-job"
    assert manifest["bundle"] == "housing_project_bundle.zip"
    assert (job_dir / "3d" / "base.step").exists()
    assert (job_dir / "2d" / "lid" / "lid_views.dxf").exists()
    assert (job_dir / "manifest.json").exists()

    with zipfile.ZipFile(job_dir / manifest["bundle"]) as archive:
        names = set(archive.namelist())
    assert "3d/base.stl" in names
    assert "2d/base/base_drawing.pdf" in names
    assert "project_layers.json" in names
    assert "rebuild_project.py" in names
    assert "bill_of_materials.csv" in names


def test_job_id_cannot_escape_output_directory(tmp_path: Path) -> None:
    try:
        generate_artifacts(default_project_config(), tmp_path, job_id="../escape")
    except ValueError as exc:
        assert "job_id" in str(exc)
    else:
        raise AssertionError("unsafe job_id was accepted")


def test_change_audit_is_persisted(tmp_path: Path) -> None:
    changes = [
        {
            "path": "dimensions.wall_thickness",
            "before": 2.0,
            "after": 2.2,
            "kind": "changed",
        }
    ]
    manifest = generate_artifacts(
        default_project_config(),
        tmp_path,
        job_id="audit-job",
        source_prompt="Set wall thickness to 2.2 mm",
        interpretation_mode="fallback",
        configuration_changes=changes,
    )
    assert manifest["generator"]["version"] == GENERATOR_VERSION
    assert manifest["interpretation"]["change_count"] == 1
    assert (tmp_path / "audit-job" / "configuration_changes.json").exists()
    assert (tmp_path / "audit-job" / "configuration_changes.md").exists()
    rebuild = (tmp_path / "audit-job" / "rebuild_project.py").read_text(encoding="utf-8")
    compile(rebuild, "rebuild_project.py", "exec")


def test_manifest_matches_copy_inside_zip_and_artifact_hashes(tmp_path: Path) -> None:
    manifest = generate_artifacts(default_project_config(), tmp_path, job_id="consistent-manifest")
    job_dir = tmp_path / "consistent-manifest"
    outer_bytes = (job_dir / "manifest.json").read_bytes()

    with zipfile.ZipFile(job_dir / manifest["bundle"]) as archive:
        inner_bytes = archive.read("manifest.json")

    assert inner_bytes == outer_bytes
    persisted = json.loads(outer_bytes)
    assert persisted["manifest"] == "manifest.json"
    assert persisted["bundle"] == "housing_project_bundle.zip"

    for artifact in persisted["artifacts"]:
        path = job_dir / artifact["path"]
        assert path.exists()
        assert path.stat().st_size == artifact["size_bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
