from __future__ import annotations

import tomllib
from pathlib import Path

from app.main import app
from housing_studio.version import __version__ as housing_version

from living_product_studio import __version__ as platform_version
from living_product_studio.api import app as platform_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_package_versions_are_synchronized() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == platform_version
    assert platform_app.version == platform_version
    assert app.version == housing_version
