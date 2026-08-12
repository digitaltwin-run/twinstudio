from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "src" / "twinstudio" / "static" / "index.html"
JAVASCRIPT = ROOT / "src" / "twinstudio" / "static" / "app.js"


def test_twinstudio_frontend_element_ids_are_synchronized() -> None:
    html = HTML.read_text(encoding="utf-8")
    javascript = JAVASCRIPT.read_text(encoding="utf-8")
    html_ids = set(re.findall(r'\bid="([^"]+)"', html))
    js_ids = set(re.findall(r"\$\(['\"]([^'\"]+)['\"]\)", javascript))
    assert js_ids <= html_ids


def test_twinstudio_javascript_module_syntax() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")
    subprocess.run(
        [node, "--input-type=module", "--check"],
        input=JAVASCRIPT.read_text(encoding="utf-8"),
        check=True,
        capture_output=True,
        text=True,
    )


def test_viewer_and_llm_context_contract_is_explicit() -> None:
    html = HTML.read_text(encoding="utf-8")
    javascript = JAVASCRIPT.read_text(encoding="utf-8")
    assert 'data-viewer-state="idle"' in html
    assert "host.dataset.loadedMeshes=String(state.meshes.size)" in javascript
    assert "host.dataset.renderedTriangles=String(state.renderedTriangles)" in javascript
    assert "async function reportUiContext" in javascript
    assert "UI_ARTIFACT_LOAD_FAILED" in javascript
    assert "/ui-context" in javascript


def test_actions_are_serialized_in_url_and_dsl_logs_can_be_copied() -> None:
    html = HTML.read_text(encoding="utf-8")
    javascript = JAVASCRIPT.read_text(encoding="utf-8")
    assert 'id="copyDslLogs"' in html
    assert "Kopiuj logi DSL" in html
    assert "searchParams.append('args'" in javascript
    assert "history.replaceState" in javascript
    assert "POSITION ${JSON.stringify" in javascript
    assert "CODE \"UI_ACTION_RECORDED\"" in javascript
    assert "/logs.dsl?limit=300" in javascript
    assert "navigator.clipboard?.writeText" in javascript
    assert "text_length=${element.value.length}" in javascript


def test_all_2d_drawings_replace_the_view_selector() -> None:
    html = HTML.read_text(encoding="utf-8")
    javascript = JAVASCRIPT.read_text(encoding="utf-8")
    assert 'id="drawingView"' not in html
    assert 'id="drawingList"' in html
    assert 'id="drawingCount"' in html
    assert 'id="downloadDrawingsPdf"' in html
    assert "Pobierz wszystkie jako PDF" in html
    assert "function loadDrawings()" in javascript
    assert "document.querySelectorAll('.drawing-canvas')" in javascript
    assert "state.activeDrawingView=canvas.dataset.view" in javascript
    assert "uiContextQueue:Promise.resolve()" in javascript
    assert "state.uiContextQueue=state.uiContextQueue.then" in javascript
    assert "/drawings.pdf" in javascript


def test_2d_projection_region_creates_a_real_selection_without_tree_click() -> None:
    javascript = JAVASCRIPT.read_text(encoding="utf-8")
    front_svg = (
        ROOT / "examples" / "rpi5-camera3" / "artifacts" / "2d" / "assembly_front.svg"
    ).read_text(encoding="utf-8")
    assert "drawingProjectionRegions:new Map()" in javascript
    assert "drawingProjectionPromises:new Map()" in javascript
    assert "async function loadDrawingProjectionRegions" in javascript
    assert "function inferDrawingProjection" in javascript
    assert "function polygonSelectionBbox" in javascript
    assert "projection-regions=2" in javascript
    assert "cache:'no-store'" in javascript
    assert "viewer2d.projection.ready" in javascript
    assert "viewer2d.projection.unavailable" in javascript
    assert "polygon-order-fallback" in javascript
    assert "object.inferred" in javascript
    assert "selection.rejected" in javascript
    assert 'src="/static/app.js?v=20260812-selection2"' in HTML.read_text(encoding="utf-8")
    assert 'data-projection-entity="front.base.outer-wall"' in front_svg
    assert 'data-projection-entity="front.lid.outer-slope"' in front_svg
    assert "data-selection-bbox" in front_svg


def test_compose_database_healthcheck_executes_authenticated_query() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "PGPASSWORD=$${POSTGRES_PASSWORD} psql" in compose
    assert "-tAc 'SELECT 1' | grep -qx 1" in compose
