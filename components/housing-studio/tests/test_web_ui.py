from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from housing_studio.version import __version__


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = PROJECT_ROOT / "app" / "templates" / "index.html"
JS_PATH = PROJECT_ROOT / "app" / "static" / "app.js"


def test_frontend_element_ids_are_synchronized() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    javascript = JS_PATH.read_text(encoding="utf-8")
    html_ids = set(re.findall(r'\bid="([^"]+)"', html))
    js_ids = set(re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", javascript))
    assert js_ids == html_ids


def test_frontend_javascript_syntax() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")
    subprocess.run([node, "--check", str(JS_PATH)], check=True, capture_output=True, text=True)


def test_viewer_dependency_failure_is_non_blocking() -> None:
    javascript = JS_PATH.read_text(encoding="utf-8")
    assert "async function loadViewerDependencies()" in javascript
    assert "Generator, dokumentacja 2D i pobieranie plików nadal działają" in javascript
    assert "import * as THREE" not in javascript


def test_web_page_exposes_current_version() -> None:
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert f"v{__version__}" in response.text
    assert 'data-app-version="' + __version__ + '"' in response.text
    assert '<script type="module" src="/static/app.js"></script>' in response.text


def test_package_version_is_synchronized() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__
    assert app.version == __version__
