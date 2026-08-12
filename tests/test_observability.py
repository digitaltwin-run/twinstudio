from __future__ import annotations

from pathlib import Path

import pytest

from twinstudio.observability import (
    ArtifactUse,
    UiContext,
    UiContextStore,
    error_playbook_path,
    load_error_playbook,
    make_problem,
)


def test_problem_envelope_has_json_and_compact_dsl_contract() -> None:
    context = UiContext(
        session_id="browser-1234",
        project_id="demo-rpi5",
        viewer_state="error",
        artifacts=[
            ArtifactUse(
                uri="poa://demo/demo-rpi5@main/artifact/base-stl",
                purpose="viewer3d:base",
                status="failed",
                error_code="UI_ARTIFACT_LOAD_FAILED",
            )
        ],
    )
    problem = make_problem(
        code="UI_ARTIFACT_LOAD_FAILED",
        message="STL unavailable",
        source="twinstudio.ui",
        operation="viewer3d.load",
        correlation_id="corr-1",
        project_id="demo-rpi5",
        status_code=404,
        ui_context=context,
        artifacts=context.artifacts,
    )
    dsl = problem.to_dsl()
    assert dsl.startswith("TWINOBS 1.0\n")
    assert 'CODE "UI_ARTIFACT_LOAD_FAILED"' in dsl
    assert 'SCREEN {"kind":"UIContext"' in dsl
    assert dsl.endswith("\nEND")
    assert problem.registry_uri == "/api/v1/errors/UI_ARTIFACT_LOAD_FAILED"


def test_ui_context_store_returns_latest_session() -> None:
    store = UiContextStore()
    first = store.put(UiContext(session_id="browser-1111", project_id="demo-rpi5"))
    second = store.put(UiContext(session_id="browser-2222", project_id="demo-rpi5", active_tab="spec"))
    assert store.get("demo-rpi5", first.session_id) == first
    assert store.get("demo-rpi5") == second


def test_error_registry_rejects_path_traversal_and_reads_known_code() -> None:
    root = Path(__file__).resolve().parents[1] / "error"
    assert "REPAIR 1.0" in load_error_playbook(root, "UI_ARTIFACT_LOAD_FAILED")
    with pytest.raises(ValueError):
        error_playbook_path(root, "../README")
