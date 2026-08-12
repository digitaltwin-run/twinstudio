from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Iterable

from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen.canvas import Canvas
from svglib.svglib import svg2rlg

from twinstudio.domain import EventEnvelope, ProjectSnapshot
from twinstudio.specification import unified_specification


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
    with tempfile.TemporaryDirectory(prefix="twinstudio-export-") as temporary:
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
            "format": "twinstudio-project-bundle",
            "format_version": 2,
            "product": "TwinStudio",
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


def render_drawings_pdf(drawings: Iterable[tuple[str, Path]]) -> bytes:
    """Render ordered SVG drawing artifacts as one vector, multi-page PDF."""

    items = list(drawings)
    if not items:
        raise ValueError("Project has no SVG drawing views")
    page_width, page_height = landscape(A4)
    margin = 36.0
    header_height = 38.0
    footer_height = 20.0
    buffer = BytesIO()
    pdf = Canvas(buffer, pagesize=(page_width, page_height), pageCompression=1)
    pdf.setTitle("TwinStudio drawings")
    pdf.setAuthor("TwinStudio")
    for index, (view, path) in enumerate(items, start=1):
        drawing = svg2rlg(str(path))
        if drawing is None or not drawing.width or not drawing.height:
            raise ValueError(f"Cannot render SVG drawing: {path.name}")
        available_width = page_width - 2 * margin
        available_height = page_height - 2 * margin - header_height - footer_height
        scale = min(available_width / drawing.width, available_height / drawing.height)
        drawing.scale(scale, scale)
        drawing.width *= scale
        drawing.height *= scale
        x = (page_width - drawing.width) / 2
        y = margin + footer_height + (available_height - drawing.height) / 2
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(margin, page_height - margin - 10, f"View: {view.title()}")
        pdf.setFont("Helvetica", 9)
        pdf.drawRightString(page_width - margin, page_height - margin - 8, path.name)
        renderPDF.draw(drawing, pdf, x, y)
        pdf.setFont("Helvetica", 8)
        pdf.drawRightString(page_width - margin, margin, f"TwinStudio | {index}/{len(items)}")
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _safe_artifact_name(uri: str, name: str) -> str:
    prefix = hashlib.sha256(uri.encode("utf-8")).hexdigest()[:12]
    safe = "".join(character if character.isalnum() or character in "._-" else "_" for character in name)
    return f"{prefix}-{safe}"
