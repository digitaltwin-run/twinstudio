import json
import zipfile
from pathlib import Path

from twinstudio.artifacts import export_project_bundle


def test_export_bundle_contains_digital_thread(tmp_path: Path, project_snapshot) -> None:
    output = tmp_path / "project.twinstudio.zip"
    export_project_bundle(project_snapshot, [], output, project_root=Path(__file__).resolve().parents[1])
    assert output.exists()
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert "project.snapshot.json" in names
        assert "project.specification.json" in names
        assert "event-stream.ndjson" in names
        assert "manifest.json" in names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "twinstudio-project-bundle"
        assert manifest["format_version"] == 2
        assert manifest["product"] == "TwinStudio"
        assert any(name.startswith("artifacts/") for name in names)
