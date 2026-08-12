from dataclasses import replace

import pytest

from twinstudio.change_planner import ChangePlanner, LlmInvalidResponse, ScopeViolation
from twinstudio.domain import ChangeOperation, ChangeOperationProposal, ChangePlan, ChangePlanProposal
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


def test_selected_lid_context_resolves_lower_to_as_physical_component_height(
    project_snapshot,
    example_selection,
) -> None:
    lid_uri = "poa://demo/demo-rpi5@main/part/lid"
    selection_2d = example_selection.model_copy(
        update={
            "source_view": "2d",
            "tool": "pencil",
            "screen_path": [{"x": 1130, "y": 611}],
            "ray_hits": [],
            "world_aabb": None,
            "camera": None,
            "target_object_uris": [lid_uri],
            "projection_entity_ids": ["front.lid.outer-slope"],
        }
    )
    planner = ChangePlanner(replace(settings, litellm_model=""))

    plan = planner.plan(
        "obniż do 12mm",
        selection_2d,
        project_snapshot,
        "editor@example.test",
    ).plan

    assert plan.unresolved_questions == []
    assert len(plan.operations) == 1
    operation = plan.operations[0]
    assert operation.kind == "set_parameter"
    assert operation.target_uri == lid_uri
    assert operation.arguments == {"parameter": "height", "value": 12.0, "unit": "mm"}
    payload = planner.compile_apply_payload(plan, project_snapshot)
    assert payload["parameter_patches"][0]["previous_parameter"]["value"] == 15.0
    assert payload["parameter_patches"][0]["previous_parameter"]["status"] == "derived"


@pytest.mark.parametrize(
    ("prompt", "kind", "arguments", "applyable"),
    [
        ("zmniejsz wysokość o 4 mm", "set_parameter", {"parameter": "height", "value": 21.0, "unit": "mm"}, True),
        ("zwiększ wysokość o 4 mm", "set_parameter", {"parameter": "height", "value": 29.0, "unit": "mm"}, True),
        ("ustaw szerokość na 80 mm", "set_parameter", {"parameter": "width", "value": 80.0, "unit": "mm"}, True),
        ("dodaj otwór o średnicy 3 mm", "boolean_cut", {"feature_type": "hole", "diameter_mm": 3.0, "depth_mode": "through_selected_wall"}, False),
        ("dodaj fazę 45 stopni", "add_feature", {"feature_type": "chamfer", "angle_deg": 45.0}, False),
    ],
)
def test_simple_nl_examples_compile_to_typed_scoped_operations(
    project_snapshot,
    example_selection,
    prompt,
    kind,
    arguments,
    applyable,
) -> None:
    planner = ChangePlanner(replace(settings, litellm_model=""))
    plan = planner.plan(prompt, example_selection, project_snapshot, "editor@example.test").plan

    assert len(plan.operations) == 1
    assert plan.operations[0].kind == kind
    assert plan.operations[0].target_uri == "poa://demo/demo-rpi5@main/part/base"
    assert plan.operations[0].arguments == arguments
    assert ChangePlan.model_validate(plan.model_dump(mode="json")) == plan
    payload = planner.compile_apply_payload(plan, project_snapshot)
    assert bool(payload["parameter_patches"]) is applyable


def test_litellm_boundary_uses_typed_nl_source_and_propose_only_response(
    monkeypatch,
    project_snapshot,
    example_selection,
) -> None:
    import sys
    from types import ModuleType, SimpleNamespace

    proposal = ChangePlanProposal(
        operations=[
            ChangeOperationProposal(
                kind="set_parameter",
                target_uri="poa://demo/demo-rpi5@main/part/base",
                arguments={"parameter": "height", "value": 21.0, "unit": "mm"},
            )
        ]
    )

    def fake_completion(**kwargs):
        user_payload = __import__("json").loads(kwargs["messages"][1]["content"])
        assert user_payload["schema_version"] == "twinstudio.change-plan-request/v1"
        assert user_payload["source"]["schema_version"] == "twinstudio.nl-source/v1"
        assert user_payload["source"]["language"] == "pl"
        assert len(user_payload["source"]["sha256"]) == 64
        schema = kwargs["response_format"]["json_schema"]
        assert schema["name"] == "change_plan_proposal"
        assert schema["strict"] is True
        assert "plan_id" not in schema["schema"]["properties"]
        assert "created_by" not in schema["schema"]["properties"]
        operation_schema = schema["schema"]["$defs"]["ChangeOperationProposal"]
        assert "operation_id" not in operation_schema["properties"]
        assert "reversible" not in operation_schema["properties"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=proposal.model_dump_json()))]
        )

    fake_module = ModuleType("litellm")
    fake_module.completion = fake_completion
    monkeypatch.setitem(sys.modules, "litellm", fake_module)
    planner = ChangePlanner(replace(settings, litellm_model="test/model"))

    result = planner.plan(
        "ustaw wysokość na 21 mm",
        example_selection,
        project_snapshot,
        "editor@example.test",
    )

    assert result.mode == "litellm"
    assert result.plan.created_by == "editor@example.test"
    assert result.plan.requires_approval is True
    assert result.plan.planner == "litellm:test/model"


def test_invalid_litellm_response_is_explicit_and_never_silently_coerced(
    monkeypatch,
    project_snapshot,
    example_selection,
) -> None:
    import sys
    from types import ModuleType, SimpleNamespace

    fake_module = ModuleType("litellm")
    fake_module.completion = lambda **_: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"requires_approval": false}'))]
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_module)
    planner = ChangePlanner(replace(settings, litellm_model="test/model"))

    with pytest.raises(LlmInvalidResponse) as caught:
        planner.plan(
            "ustaw wysokość na 21 mm",
            example_selection,
            project_snapshot,
            "editor@example.test",
        )

    assert len(caught.value.response_sha256) == 64
    assert "operations" in caught.value.validation_error
    assert caught.value.artifact.schema_version == "twinstudio.invalid-llm-response/v1"
    assert caught.value.artifact.response_length > 0


def test_valid_litellm_proposal_outside_selected_scope_is_rejected_then_local_fallback_is_used(
    monkeypatch,
    project_snapshot,
    example_selection,
) -> None:
    import sys
    from types import ModuleType, SimpleNamespace

    proposal = ChangePlanProposal(
        operations=[
            ChangeOperationProposal(
                kind="set_parameter",
                target_uri="poa://demo/demo-rpi5@main/part/lid",
                arguments={"parameter": "height", "value": 21.0, "unit": "mm"},
            )
        ]
    )
    fake_module = ModuleType("litellm")
    fake_module.completion = lambda **_: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=proposal.model_dump_json()))]
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_module)
    planner = ChangePlanner(replace(settings, litellm_model="test/model"))

    result = planner.plan(
        "ustaw wysokość na 21 mm",
        example_selection,
        project_snapshot,
        "editor@example.test",
    )

    assert result.mode == "local-fallback"
    assert "outside selected scope" in result.message
    assert result.plan.operations[0].target_uri == "poa://demo/demo-rpi5@main/part/base"
