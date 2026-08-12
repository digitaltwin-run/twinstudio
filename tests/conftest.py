from __future__ import annotations

import json
from pathlib import Path

import pytest

from twinstudio.domain import ProjectSnapshot, RegionSelection


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def project_snapshot() -> ProjectSnapshot:
    return ProjectSnapshot.model_validate_json(
        (ROOT / "examples" / "rpi5-camera3" / "project.json").read_text(encoding="utf-8")
    )


@pytest.fixture()
def example_selection() -> RegionSelection:
    return RegionSelection.model_validate_json(
        (ROOT / "examples" / "rpi5-camera3" / "selections" / "example-selection.json").read_text(
            encoding="utf-8"
        )
    )
