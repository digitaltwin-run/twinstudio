from __future__ import annotations

from pathlib import Path

import pytest

from twinstudio.observability import (
    ArtifactUse,
    ObservationLogStore,
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


def test_observation_log_store_is_bounded_and_filters_project_dsl() -> None:
    store = ObservationLogStore(max_entries=2)
    store.append(
        {
            "project_id": "other-project",
            "operation": "GET /api/v1/projects/other-project",
            "dsl": 'TWINOBS 1.0\nPROJECT "other-project"\nEND',
        }
    )
    store.append(
        {
            "project_id": "demo-rpi5",
            "operation": "GET /api/v1/projects/demo-rpi5/tree",
            "dsl": 'TWINOBS 1.0\nCODE "FIRST"\nEND',
        }
    )
    store.append(
        {
            "project_id": "demo-rpi5",
            "operation": "GET /api/v1/projects/demo-rpi5/ui-context",
            "dsl": 'TWINOBS 1.0\nCODE "SECOND"\nEND',
        }
    )
    dsl = store.to_dsl("demo-rpi5", limit=10)
    assert 'CODE "FIRST"' in dsl
    assert 'CODE "SECOND"' in dsl
    assert "other-project" not in dsl
    assert store.to_dsl("demo", limit=10) == ""


def test_error_registry_rejects_path_traversal_and_reads_known_code() -> None:
    root = Path(__file__).resolve().parents[1] / "error"
    assert "REPAIR 1.0" in load_error_playbook(root, "UI_ARTIFACT_LOAD_FAILED")
    with pytest.raises(ValueError):
        error_playbook_path(root, "../README")
