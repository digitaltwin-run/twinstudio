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


def test_compose_database_healthcheck_executes_authenticated_query() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "PGPASSWORD=$${POSTGRES_PASSWORD} psql" in compose
    assert "-tAc 'SELECT 1' | grep -qx 1" in compose
