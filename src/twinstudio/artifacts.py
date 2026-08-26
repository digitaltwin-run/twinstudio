from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import textwrap
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Iterable

import reportlab
from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from svglib.svglib import svg2rlg

from twinstudio.domain import EventEnvelope, ProjectSnapshot
from twinstudio.specification import unified_specification

TAB_PDF_TITLES = {
    "view3d": "Widok 3D",
    "view2d": "Rzuty 2D",
    "spec": "Specyfikacja / xBOM",
    "lifecycle": "Lifecycle",
    "tests": "Testy i symulacje",
    "fixation": "Feature lenses",
    "evolution": "Evolution / DSL",
}

_PDF_FONT = "Helvetica"
_PDF_FONT_BOLD = "Helvetica-Bold"
try:
    _reportlab_fonts = Path(reportlab.__file__).resolve().parent / "fonts"
    pdfmetrics.registerFont(TTFont("TwinStudio", str(_reportlab_fonts / "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("TwinStudio-Bold", str(_reportlab_fonts / "VeraBd.ttf")))
    _PDF_FONT = "TwinStudio"
    _PDF_FONT_BOLD = "TwinStudio-Bold"
except Exception:  # pragma: no cover - ReportLab packages normally include Vera
    pass


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
    digital_twin_root: Path | None = None,
    object_root: Path | None = None,
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
        descriptor_source = digital_twin_root / "project.twinstudio.json" if digital_twin_root else None
        if descriptor_source is not None and descriptor_source.is_file():
            shutil.copyfile(descriptor_source, root / "project.twinstudio.json")
        else:
            (root / "project.twinstudio.json").write_text(
                json.dumps(
                    {
                        "schema_id": "twinstudio.project/v1",
                        "project_id": snapshot.project_id,
                        "stream_id": snapshot.project_id,
                        "stream_version": snapshot.stream_version,
                        "updated_at": snapshot.updated_at.isoformat(),
                        "artifacts": {},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        if digital_twin_root is not None:
            preview_root = digital_twin_root / ".twinstudio" / "previews"
            if preview_root.is_dir():
                for preview in sorted(item for item in preview_root.rglob("*") if item.is_file()):
                    destination = root / "previews" / preview.relative_to(preview_root)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(preview, destination)
            eda_log = digital_twin_root / ".twinstudio" / "logs" / "eda.jsonl"
            if eda_log.is_file():
                destination = root / "logs" / "eda.jsonl"
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(eda_log, destination)
        referenced_objects = {
            str(value).removeprefix("sha256:")
            for event in event_list
            for key, value in event.data.items()
            if key.endswith("object_ref") and isinstance(value, str) and value.startswith("sha256:")
        }
        if object_root is not None:
            for digest in sorted(referenced_objects):
                source = object_root / digest[:2] / digest
                if source.is_file():
                    destination = root / "objects" / "sha256" / digest[:2] / digest
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
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
            "format_version": 3,
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


def render_tab_pdf(
    snapshot: ProjectSnapshot,
    tab: str,
    *,
    content_text: str = "",
    screenshot_png: bytes | None = None,
    selected_object_uri: str | None = None,
    drawings: Iterable[tuple[str, Path]] = (),
) -> bytes:
    """Render one UI tab as a deterministic downloadable PDF.

    The 2D tab stays vector-native. The 3D tab may include a browser-captured PNG,
    while data tabs use the current visible text supplied by the trusted UI.
    """

    if tab not in TAB_PDF_TITLES:
        raise ValueError(f"Unsupported tab: {tab}")
    if tab == "view2d":
        return render_drawings_pdf(drawings)

    page_size = landscape(A4) if tab == "view3d" else A4
    page_width, page_height = page_size
    margin = 38.0
    footer_height = 24.0
    buffer = BytesIO()
    pdf = Canvas(buffer, pagesize=page_size, pageCompression=1)
    title = TAB_PDF_TITLES[tab]
    pdf.setTitle(f"TwinStudio - {title}")
    pdf.setAuthor("TwinStudio")
    page_number = 0
    y = 0.0

    def new_page() -> None:
        nonlocal page_number, y
        if page_number:
            pdf.showPage()
        page_number += 1
        pdf.setFont(_PDF_FONT_BOLD, 16)
        pdf.drawString(margin, page_height - margin, title)
        pdf.setFont(_PDF_FONT, 8)
        pdf.drawRightString(
            page_width - margin,
            page_height - margin + 2,
            f"{snapshot.project_id} | {snapshot.revision}",
        )
        pdf.setStrokeColorRGB(0.35, 0.5, 0.75)
        pdf.line(margin, page_height - margin - 9, page_width - margin, page_height - margin - 9)
        pdf.setFillColorRGB(0.35, 0.35, 0.4)
        pdf.setFont(_PDF_FONT, 8)
        pdf.drawString(margin, margin - 12, "TwinStudio | eksport zakładki")
        pdf.drawRightString(page_width - margin, margin - 12, f"strona {page_number}")
        pdf.setFillColorRGB(0, 0, 0)
        y = page_height - margin - 30

    def draw_lines(lines: Iterable[str], *, font: str = _PDF_FONT, size: float = 9.0) -> None:
        nonlocal y
        pdf.setFont(font, size)
        leading = size * 1.42
        max_chars = 126 if page_width > page_height else 94
        for raw in lines:
            raw = raw.replace("\t", "    ")
            wrapped = textwrap.wrap(
                raw,
                width=max_chars,
                replace_whitespace=False,
                drop_whitespace=False,
                break_long_words=True,
                break_on_hyphens=False,
            ) or [""]
            for line in wrapped:
                if y < margin + footer_height:
                    new_page()
                    pdf.setFont(font, size)
                pdf.drawString(margin, y, line.rstrip())
                y -= leading

    new_page()
    if screenshot_png:
        try:
            image = ImageReader(BytesIO(screenshot_png))
            image_width, image_height = image.getSize()
            available_width = page_width - 2 * margin
            available_height = page_height - 2 * margin - 90
            scale = min(available_width / image_width, available_height / image_height)
            draw_width = image_width * scale
            draw_height = image_height * scale
            x = (page_width - draw_width) / 2
            image_y = y - draw_height
            pdf.drawImage(
                image,
                x,
                image_y,
                width=draw_width,
                height=draw_height,
                preserveAspectRatio=True,
                mask="auto",
            )
            y = image_y - 16
        except Exception as exc:
            draw_lines([f"Nie udało się osadzić kadru 3D: {exc}"])

    if selected_object_uri:
        selected = snapshot.objects.get(selected_object_uri)
        draw_lines(
            [
                f"Wybrany obiekt: {selected.name if selected else selected_object_uri}",
                f"URI: {selected_object_uri}",
            ],
            font=_PDF_FONT_BOLD,
        )

    normalized = content_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if normalized:
        if y < margin + footer_height + 30:
            new_page()
        draw_lines(normalized[:100_000].splitlines())
    elif not screenshot_png and not selected_object_uri:
        draw_lines(["Zakładka nie zawiera obecnie danych do wydruku."])

    pdf.save()
    return buffer.getvalue()


def _safe_artifact_name(uri: str, name: str) -> str:
    prefix = hashlib.sha256(uri.encode("utf-8")).hexdigest()[:12]
    safe = "".join(character if character.isalnum() or character in "._-" else "_" for character in name)
    return f"{prefix}-{safe}"
