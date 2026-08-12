from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "src" / "twinstudio" / "static" / "index.html"
JAVASCRIPT = ROOT / "src" / "twinstudio" / "static" / "app.js"
VENDORED_THREE = ROOT / "src" / "twinstudio" / "static" / "vendor" / "three"


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


def test_three_viewer_dependencies_are_pinned_and_self_hosted() -> None:
    html = HTML.read_text(encoding="utf-8")
    import_map_match = re.search(
        r'<script type="importmap">\s*(\{.*?\})\s*</script>',
        html,
        re.DOTALL,
    )
    assert import_map_match is not None
    imports = json.loads(import_map_match.group(1))["imports"]
    assert imports == {
        "three": "/static/vendor/three/three.module.js?v=0.185.1",
        "three/addons/controls/OrbitControls.js": (
            "/static/vendor/three/OrbitControls.js?v=0.185.1"
        ),
        "three/addons/loaders/STLLoader.js": (
            "/static/vendor/three/STLLoader.js?v=0.185.1"
        ),
    }
    assert "cdn.jsdelivr.net" not in html

    expected_hashes = {
        "LICENSE.txt": "8b378ebe60e2fe500158cb0ac71cb5e8b7d92953c2abcc63a0eb90499653b5bc",
        "OrbitControls.js": "faabb4e8dfd9235ee4a9fd7c9a3d75f90f1689dbd4944bd6fd32117dacec5f93",
        "STLLoader.js": "023ed97f848b633d8bcd53d4db3b996d29d0c644088700691297c552257d480b",
        "three.core.js": "3718df126d69c125362a03340913204470d8c50238605150e57f808840fb7759",
        "three.module.js": "bbf5ed13fe4373f5bd38b14ea8e62e9f157327da5638edc6d3863e08b167c9c7",
    }
    for name, expected_hash in expected_hashes.items():
        content = (VENDORED_THREE / name).read_bytes()
        assert hashlib.sha256(content).hexdigest() == expected_hash
    recorded_hashes = {
        name: digest
        for digest, name in (
            line.split()
            for line in (VENDORED_THREE / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        )
    }
    assert recorded_hashes == expected_hashes
    for module in VENDORED_THREE.glob("*.js"):
        relative_imports = re.findall(
            r"(?:from|import)\s*['\"]\./([^'\"]+)['\"]",
            module.read_text(encoding="utf-8"),
        )
        assert all((VENDORED_THREE / dependency).is_file() for dependency in relative_imports)

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = project["tool"]["setuptools"]["package-data"]["twinstudio"]
    assert "static/vendor/three/*" in package_data


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
    assert 'id="downloadDslLogs"' in html
    assert "Kopiuj logi DSL" in html
    assert "Pobierz logi DSL" in html
    assert "searchParams.append('args'" in javascript
    assert "history.replaceState" in javascript
    assert "POSITION ${JSON.stringify" in javascript
    assert "CODE \"UI_ACTION_RECORDED\"" in javascript
    assert "/logs.dsl?limit=300" in javascript
    assert "navigator.clipboard?.writeText" in javascript
    assert "execCommand('copy')" in javascript
    assert "method==='execCommand'" in javascript
    assert "$('downloadDslLogs').href" in javascript
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


def test_every_workspace_tab_can_be_downloaded_as_pdf() -> None:
    html = HTML.read_text(encoding="utf-8")
    javascript = JAVASCRIPT.read_text(encoding="utf-8")
    assert 'id="downloadTabPdf"' in html
    assert "Pobierz PDF: 3D" in html
    assert "const TAB_PDF_LABELS=" in javascript
    assert "function capture3dPng()" in javascript
    assert "capture.toDataURL('image/png')" in javascript
    assert "/tabs/${encodeURIComponent(tab)}.pdf" in javascript
    assert "tab.pdf.requested" in javascript
    assert "tab.pdf.downloaded" in javascript
    for tab in ("view3d", "view2d", "spec", "lifecycle", "tests", "fixation", "evolution"):
        assert f"{tab}:" in javascript


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
    assert "assembly-polygon-fallback" in javascript
    assert "object.inferred" in javascript
    assert "selection.rejected" in javascript
    assert 'src="/static/app.js?v=20260812-cad-regeneration1"' in HTML.read_text(
        encoding="utf-8"
    )
    assert 'data-projection-entity="front.base.outer-wall"' in front_svg
    assert 'data-projection-entity="front.lid.outer-slope"' in front_svg
    assert 'data-object-uri="poa://demo/demo-rpi5@main/part/base"' in front_svg
    assert "data-selection-bbox" in front_svg


def test_tree_object_selection_highlights_3d_and_all_mapped_2d_views() -> None:
    javascript = JAVASCRIPT.read_text(encoding="utf-8")
    style = (ROOT / "src" / "twinstudio" / "static" / "style.css").read_text(encoding="utf-8")
    assert "function objectBelongsToSelection" in javascript
    assert "function renderObjectHighlight3d" in javascript
    assert "function renderObjectHighlight2d" in javascript
    assert "function renderObjectHighlights" in javascript
    assert "highlightedMeshes" in javascript
    assert "data-highlight-regions" in javascript
    assert "object-highlight-overlay" in javascript
    assert ".object-highlight-overlay" in style
    for view in ("front", "top", "side"):
        svg = (
            ROOT / "examples" / "rpi5-camera3" / "artifacts" / "2d" / f"assembly_{view}.svg"
        ).read_text(encoding="utf-8")
        assert 'data-object-uri="poa://demo/demo-rpi5@main/part/base"' in svg
        assert 'data-object-uri="poa://demo/demo-rpi5@main/part/lid"' in svg
        assert svg.count("data-selection-bbox") >= 2


def test_planner_wait_and_non_geometry_outcome_are_explicit() -> None:
    html = HTML.read_text(encoding="utf-8")
    javascript = JAVASCRIPT.read_text(encoding="utf-8")
    assert 'id="plannerRuntime"' in html
    assert 'id="plannerProgress"' in html
    assert 'id="applyStatus"' in html
    assert 'id="changeHistory"' in html
    assert 'id="refreshChangeHistory"' in html
    assert 'id="changeQueue"' in html
    assert 'id="changeQueueCount"' in html
    assert "Zapisz i wykonaj uwagę" in html
    assert "litellm_configured" in javascript
    assert "function renderPlannerProgress" in javascript
    assert "Możesz przeglądać inne karty" in javascript
    assert "Odświeżenie strony nie jest potrzebne" in javascript
    assert "Ten plan nie zmieni bryły" in javascript
    assert "op.kind==='set_parameter'" in javascript
    assert "plan.completed" in javascript
    assert "plan.apply.completed" in javascript
    assert "function loadChangeHistory" in javascript
    assert "function undoChange" in javascript
    assert "/change-history/" in javascript
    assert "annotation.execution.deferred" in javascript
    assert "function loadChangeQueue" in javascript
    assert "function tasksForObject" in javascript
    assert "/change-queue" in javascript
    assert "task-pill" in javascript
    assert "taskGroups" in javascript
    assert "waiting_cad" in javascript


def test_compose_database_healthcheck_executes_authenticated_query() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "PGPASSWORD=$${POSTGRES_PASSWORD} psql" in compose
    assert "-tAc 'SELECT 1' | grep -qx 1" in compose
