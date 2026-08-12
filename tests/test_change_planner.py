from dataclasses import replace

import pytest

from twinstudio.change_planner import ChangePlanner, ScopeViolation
from twinstudio.domain import ChangeOperation, ChangePlan
from twinstudio.settings import settings


def test_local_planner_keeps_chamfer_in_selected_scope(project_snapshot, example_selection) -> None:
    planner = ChangePlanner(replace(settings, litellm_model=""))
    result = planner.plan("Add a 45 degree chamfer only on this marked edge", example_selection, project_snapshot, "editor@example.test")
    assert result.mode == "local"
    assert result.plan.operations
    assert all(op.target_uri == "poa://demo/demo-rpi5@main/part/base" for op in result.plan.operations)
    assert any(op.kind == "add_feature" for op in result.plan.operations)


def test_scope_violation_is_rejected(project_snapshot, example_selection) -> None:
    plan = ChangePlan(
        project_id="demo-rpi5",
        base_revision="main",
        prompt="malicious cross-part edit",
        selection_uri=example_selection.uri,
        selected_scope_uris=["poa://demo/demo-rpi5@main/part/base"],
        operations=[
            ChangeOperation(
                kind="set_parameter",
                target_uri="poa://demo/demo-rpi5@main/part/lid",
                arguments={"parameter": "wall_thickness", "value": 4},
            )
        ],
        created_by="editor@example.test",
    )
    with pytest.raises(ScopeViolation):
        ChangePlanner.validate_scope(plan)


def test_local_wall_request_on_face_is_deferred_geometry(project_snapshot, example_selection) -> None:
    planner = ChangePlanner(replace(settings, litellm_model=""))
    plan = planner.plan("Set wall thickness in this area to 2.5 mm", example_selection, project_snapshot, "editor@example.test").plan
    payload = planner.compile_apply_payload(plan, project_snapshot)
    assert payload["parameter_patches"] == []
    assert payload["deferred_operations"]
