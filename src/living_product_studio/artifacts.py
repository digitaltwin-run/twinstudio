from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

from living_product_studio.domain import EventEnvelope, ProjectSnapshot
from living_product_studio.specification import unified_specification


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_project_bundle(
    snapshot: ProjectSnapshot,
    events: Iterable[EventEnvelope],
    output_path: Path,
    *,
    project_root: Path | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    event_list = list(events)
    with tempfile.TemporaryDirectory(prefix="lps-export-") as temporary:
        root = Path(temporary)
        (root / "project.snapshot.json").write_text(
            snapshot.model_dump_json(indent=2), encoding="utf-8"
        )
        (root / "project.specification.json").write_text(
            json.dumps(unified_specification(snapshot), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with (root / "event-stream.ndjson").open("w", encoding="utf-8") as stream:
            for event in event_list:
                stream.write(event.model_dump_json() + "\n")
        artifact_root = root / "artifacts"
        artifact_root.mkdir()
        missing: list[str] = []
        for artifact in snapshot.artifacts.values():
            source = Path(artifact.path)
            if not source.is_absolute() and project_root is not None:
                source = project_root / source
            if not source.exists() or not source.is_file():
                missing.append(artifact.uri)
                continue
            destination = artifact_root / _safe_artifact_name(artifact.uri, source.name)
            destination.write_bytes(source.read_bytes())
        manifest = {
            "format": "twinstudio-bundle",
            "format_version": 1,
            "project_id": snapshot.project_id,
            "revision": snapshot.revision,
            "stream_version": snapshot.stream_version,
            "missing_artifacts": missing,
            "files": [],
        }
        for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "manifest.json"):
            manifest["files"].append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                archive.write(path, path.relative_to(root).as_posix())
    return output_path


def _safe_artifact_name(uri: str, name: str) -> str:
    prefix = hashlib.sha256(uri.encode("utf-8")).hexdigest()[:12]
    safe = "".join(character if character.isalnum() or character in "._-" else "_" for character in name)
    return f"{prefix}-{safe}"
