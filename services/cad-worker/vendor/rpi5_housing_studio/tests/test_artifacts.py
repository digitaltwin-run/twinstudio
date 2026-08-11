import zipfile
from pathlib import Path

from housing_studio.artifacts import generate_artifacts
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


def test_job_id_cannot_escape_output_directory(tmp_path: Path) -> None:
    try:
        generate_artifacts(default_project_config(), tmp_path, job_id="../escape")
    except ValueError as exc:
        assert "job_id" in str(exc)
    else:
        raise AssertionError("unsafe job_id was accepted")
