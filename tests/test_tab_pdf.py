from __future__ import annotations

from base64 import b64decode
from pathlib import Path

import pytest

from twinstudio.artifacts import TAB_PDF_TITLES, render_tab_pdf
from twinstudio.domain import ProjectSnapshot

PNG_1X1 = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_data_tab_pdf_supports_polish_text(project_snapshot: ProjectSnapshot) -> None:
    content = render_tab_pdf(
        project_snapshot,
        "spec",
        content_text="Zażółć gęślą jaźń\nSpecyfikacja części i materiałów",
    )

    assert content.startswith(b"%PDF-")
    assert len(content) > 1_000


def test_3d_tab_pdf_contains_browser_frame_and_selected_object(
    project_snapshot: ProjectSnapshot,
) -> None:
    selected_uri = "poa://demo/demo-rpi5@main/part/base"
    content = render_tab_pdf(
        project_snapshot,
        "view3d",
        content_text="Stan kamery: perspektywa",
        screenshot_png=PNG_1X1,
        selected_object_uri=selected_uri,
    )

    assert content.startswith(b"%PDF-")
    assert len(content) > 1_500


def test_2d_tab_pdf_remains_a_vector_multipage_document(
    project_snapshot: ProjectSnapshot,
) -> None:
    root = Path(__file__).resolve().parents[1]
    drawing_root = root / "examples" / "rpi5-camera3" / "artifacts" / "2d"
    drawings = [
        (view, drawing_root / f"assembly_{view}.svg")
        for view in ("front", "top", "side")
    ]

    content = render_tab_pdf(project_snapshot, "view2d", drawings=drawings)

    assert content.startswith(b"%PDF-")
    assert content.count(b"/Type /Page") >= 3
    assert len(content) > 2_000


def test_tab_pdf_rejects_unknown_tab(project_snapshot: ProjectSnapshot) -> None:
    assert len(TAB_PDF_TITLES) == 7
    with pytest.raises(ValueError, match="Unsupported tab"):
        render_tab_pdf(project_snapshot, "unknown")
