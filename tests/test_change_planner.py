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


def test_safe_parameter_patch_keeps_previous_value_for_undo(project_snapshot, example_selection) -> None:
    selection_2d = example_selection.model_copy(
        update={
            "source_view": "2d",
            "tool": "rectangle",
            "ray_hits": [],
            "world_aabb": None,
            "camera": None,
            "projection_entity_ids": ["front.base.outer-wall"],
        }
    )
    planner = ChangePlanner(replace(settings, litellm_model=""))
    plan = planner.plan(
        "ustaw grubość ścian na 3 mm",
        selection_2d,
        project_snapshot,
        "editor@example.test",
    ).plan
    payload = planner.compile_apply_payload(plan, project_snapshot)
    assert payload["parameter_patches"][0]["value"] == 3
    assert payload["parameter_patches"][0]["previous_parameter"]["value"] == 2


def test_relative_polish_height_change_compiles_to_safe_parameter_patch(
    project_snapshot, example_selection
) -> None:
    selection_2d = example_selection.model_copy(
        update={
            "source_view": "2d",
            "tool": "rectangle",
            "ray_hits": [],
            "world_aabb": None,
            "camera": None,
            "projection_entity_ids": ["front.base.outer-wall"],
        }
    )
    planner = ChangePlanner(replace(settings, litellm_model=""))
    plan = planner.plan(
        "zmniejsz wysokosc o 4mm",
        selection_2d,
        project_snapshot,
        "editor@example.test",
    ).plan
    assert plan.unresolved_questions == []
    assert len(plan.operations) == 1
    operation = plan.operations[0]
    assert operation.kind == "set_parameter"
    assert operation.arguments == {"parameter": "height", "value": 21.0, "unit": "mm"}
    payload = planner.compile_apply_payload(plan, project_snapshot)
    assert payload["parameter_patches"][0]["value"] == 21
    assert payload["parameter_patches"][0]["previous_parameter"]["value"] == 25


def test_relative_wall_thickness_is_not_misread_as_absolute_value(
    project_snapshot, example_selection
) -> None:
    planner = ChangePlanner(replace(settings, litellm_model=""))
    plan = planner.plan(
        "zmniejsz grubość ścian o 0,5 mm",
        example_selection,
        project_snapshot,
        "editor@example.test",
    ).plan
    assert len(plan.operations) == 1
    assert plan.operations[0].arguments["parameter"] == "wall_thickness"
    assert plan.operations[0].arguments["value"] == 1.5


def test_absolute_polish_height_target_with_typo_compiles_to_safe_parameter_patch(
    project_snapshot, example_selection
) -> None:
    base_uri = "poa://demo/demo-rpi5@main/part/base"
    project_snapshot.objects[base_uri].parameters["height"].value = 9.0
    planner = ChangePlanner(replace(settings, litellm_model=""))

    plan = planner.plan(
        "zwiększ wysokośc podstawy do 21mm",
        example_selection,
        project_snapshot,
        "editor@example.test",
    ).plan

    assert plan.unresolved_questions == []
    assert len(plan.operations) == 1
    operation = plan.operations[0]
    assert operation.kind == "set_parameter"
    assert operation.selector["adjustment"] == "absolute"
    assert operation.arguments == {"parameter": "height", "value": 21.0, "unit": "mm"}
    payload = planner.compile_apply_payload(plan, project_snapshot)
    assert payload["parameter_patches"][0]["value"] == 21
    assert payload["parameter_patches"][0]["previous_parameter"]["value"] == 9


def test_absolute_depth_target_converts_centimetres(project_snapshot, example_selection) -> None:
    planner = ChangePlanner(replace(settings, litellm_model=""))

    plan = planner.plan(
        "ustaw głębokość na 10 cm",
        example_selection,
        project_snapshot,
        "editor@example.test",
    ).plan

    assert plan.operations[0].arguments == {"parameter": "depth", "value": 100.0, "unit": "mm"}
