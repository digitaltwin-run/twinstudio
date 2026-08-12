from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from twinstudio.domain import (
    Annotation,
    ArtifactRecord,
    ChangePlan,
    DesignFixationReview,
    EcommerceOffer,
    EventEnvelope,
    EvidenceClaim,
    FailureMode,
    HumanUseScenario,
    LifecycleStage,
    ObjectNode,
    ParameterValue,
    PowerModel,
    ProjectionMap,
    ProjectSnapshot,
    Requirement,
    Role,
    SelectionMap,
    TestPlan,
    ThermalModel,
    utcnow,
)
from twinstudio.evolution_models import (
    DslExecutionRecord,
    EvolutionRun,
    LifecycleBlueprint,
    LifecycleHistoryEntry,
)


class ProjectNotFound(KeyError):
    pass


def project_from_events(events: list[EventEnvelope]) -> ProjectSnapshot:
    snapshot: ProjectSnapshot | None = None
    for event in events:
        if event.event_type == "ProjectCreated":
            snapshot = ProjectSnapshot.model_validate(event.data)
            snapshot.stream_version = event.stream_version
            continue
        if snapshot is None:
            raise ProjectNotFound("Project stream does not begin with ProjectCreated")
        apply_event(snapshot, event)
    if snapshot is None:
        raise ProjectNotFound("Project stream is empty")
    return snapshot


def apply_event(snapshot: ProjectSnapshot, event: EventEnvelope) -> None:
    """Apply a single event through a small dispatch table.

    The previous long conditional was a complexity hotspot in the supplied code map.
    Isolating event handlers keeps each projection rule testable and makes new event
    types visible in one registry.
    """

    handler = _EVENT_HANDLERS.get(event.event_type)
    if handler:
        handler(snapshot, event.data)
    elif event.event_type not in _AUDIT_ONLY_EVENTS:
        snapshot.metadata.setdefault("unhandled_events", []).append(event.event_type)
    snapshot.stream_version = event.stream_version
    snapshot.updated_at = event.occurred_at or utcnow()


def _membership_granted(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    snapshot.memberships[data["email"].lower()] = Role(data["role"])


def _membership_revoked(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    snapshot.memberships.pop(data["email"].lower(), None)


def _object_upserted(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    node = ObjectNode.model_validate(data["object"])
    _synchronize_object_parameter_views(node)
    snapshot.objects[node.uri] = node


def _synchronize_object_parameter_views(node: ObjectNode) -> None:
    """Keep feature-level mirrors consistent with canonical object parameters."""

    boss_top = node.parameters.get("auxiliary_boss_top_z")
    if boss_top is None:
        return
    for feature in node.features:
        if not feature.uri.endswith("/feature/aux-bosses"):
            continue
        existing = feature.parameters.get("top_above_base")
        feature.parameters["top_above_base"] = (
            existing.model_copy(update={"value": boss_top.value, "unit": boss_top.unit or "mm"})
            if existing is not None
            else ParameterValue(
                value=boss_top.value,
                unit=boss_top.unit or "mm",
                status="derived",
                notes="Synchronized from the canonical object parameter.",
            )
        )


def _object_removed(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    snapshot.objects.pop(data["object_uri"], None)


def _artifact_attached(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    artifact = ArtifactRecord.model_validate(data["artifact"])
    snapshot.artifacts[artifact.uri] = artifact
    if artifact.object_uri and artifact.object_uri in snapshot.objects:
        node = snapshot.objects[artifact.object_uri]
        if artifact.uri not in node.artifact_uris:
            node.artifact_uris.append(artifact.uri)


def _generation_completed(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    for item in data.get("artifacts", []):
        _artifact_attached(snapshot, {"artifact": item})
    for item in data.get("objects", []):
        _object_upserted(snapshot, {"object": item})


def _annotation_created(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    annotation = Annotation.model_validate(data["annotation"])
    snapshot.annotations[annotation.uri] = annotation


def _annotation_status_changed(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    annotation = snapshot.annotations.get(data["annotation_uri"])
    if annotation:
        annotation.status = data["status"]


def _change_plan_created(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    plan = ChangePlan.model_validate(data["plan"])
    snapshot.change_plans[plan.plan_id] = plan


def _design_fixation_review_recorded(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    review = DesignFixationReview.model_validate(data["review"])
    snapshot.design_fixation_reviews[review.review_id] = review


def _evolution_run_recorded(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    run = EvolutionRun.model_validate(data["run"])
    snapshot.evolution_runs[run.run_id] = run.model_dump(mode="json")


def _lifecycle_blueprint_upserted(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    blueprint = LifecycleBlueprint.model_validate(data["blueprint"])
    snapshot.lifecycle_blueprints[blueprint.blueprint_id] = blueprint.model_dump(mode="json")


def _lifecycle_transition_recorded(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    transition = LifecycleHistoryEntry.model_validate(data["transition"])
    snapshot.lifecycle_history.append(transition.model_dump(mode="json"))
    if transition.status == "approved":
        snapshot.lifecycle_stage = transition.to_stage
        blueprint = snapshot.lifecycle_blueprints.get(transition.blueprint_id)
        if blueprint:
            blueprint["current_stage"] = transition.to_stage


def _dsl_execution_recorded(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    execution = DslExecutionRecord.model_validate(data["execution"])
    serialized = execution.model_dump(mode="json")
    snapshot.dsl_executions[execution.execution_id] = serialized
    # 0.4 development snapshots used ``dsl_programs`` for execution records.
    # Keep the mirror until that compatibility field can be removed in a major release.
    snapshot.dsl_programs[execution.execution_id] = serialized


def _change_applied(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    snapshot.revision = data["new_revision"]
    for patch in data.get("parameter_patches", []):
        target = snapshot.objects.get(patch["object_uri"])
        if not target:
            continue
        parameter = patch["parameter"]
        if patch.get("remove"):
            target.parameters.pop(parameter, None)
        elif patch.get("restore_parameter") is not None:
            target.parameters[parameter] = ParameterValue.model_validate(patch["restore_parameter"])
        elif parameter in target.parameters:
            target.parameters[parameter].value = patch["value"]
            if patch.get("unit") is not None:
                target.parameters[parameter].unit = patch["unit"]
        else:
            target.parameters[parameter] = ParameterValue(
                value=patch["value"], unit=patch.get("unit"), status="approved"
            )
        _synchronize_object_parameter_views(target)


def _requirement_upserted(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    requirement = Requirement.model_validate(data["requirement"])
    snapshot.requirements[requirement.uri] = requirement


def _evidence_claimed(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    claim = EvidenceClaim.model_validate(data["claim"])
    snapshot.claims[claim.claim_id] = claim


def _projection_map_upserted(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    projection = ProjectionMap.model_validate(data["projection_map"])
    snapshot.projection_maps[projection.uri] = projection


def _selection_map_resolved(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    selection_map = SelectionMap.model_validate(data["selection_map"])
    snapshot.selection_maps[selection_map.uri] = selection_map


def _test_plan_upserted(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    test_plan = TestPlan.model_validate(data["test_plan"])
    snapshot.test_plans[test_plan.uri] = test_plan


def _lifecycle_stage_changed(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    snapshot.lifecycle_stage = LifecycleStage(data["stage"])


def _power_model_set(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    snapshot.power_model = PowerModel.model_validate(data["power_model"])


def _thermal_model_set(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    snapshot.thermal_model = ThermalModel.model_validate(data["thermal_model"])


def _failure_mode_added(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    failure = FailureMode.model_validate(data["failure_mode"])
    snapshot.failure_modes = [item for item in snapshot.failure_modes if item.uri != failure.uri]
    snapshot.failure_modes.append(failure)


def _human_scenario_upserted(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    scenario = HumanUseScenario.model_validate(data["scenario"])
    snapshot.human_scenarios = [item for item in snapshot.human_scenarios if item.uri != scenario.uri]
    snapshot.human_scenarios.append(scenario)


def _ecommerce_offer_upserted(snapshot: ProjectSnapshot, data: dict[str, Any]) -> None:
    offer = EcommerceOffer.model_validate(data["offer"])
    snapshot.ecommerce_offers = [item for item in snapshot.ecommerce_offers if item.uri != offer.uri]
    snapshot.ecommerce_offers.append(offer)


EventHandler = Callable[[ProjectSnapshot, dict[str, Any]], None]
_EVENT_HANDLERS: dict[str, EventHandler] = {
    "MembershipGranted": _membership_granted,
    "MembershipRevoked": _membership_revoked,
    "ObjectUpserted": _object_upserted,
    "ObjectRemoved": _object_removed,
    "ArtifactAttached": _artifact_attached,
    "GenerationCompleted": _generation_completed,
    "AnnotationCreated": _annotation_created,
    "AnnotationStatusChanged": _annotation_status_changed,
    "ChangePlanCreated": _change_plan_created,
    "DesignFixationReviewRecorded": _design_fixation_review_recorded,
    "EvolutionRunRecorded": _evolution_run_recorded,
    "LifecycleBlueprintUpserted": _lifecycle_blueprint_upserted,
    "LifecycleTransitionRecorded": _lifecycle_transition_recorded,
    "DslExecutionRecorded": _dsl_execution_recorded,
    "DslProgramRecorded": _dsl_execution_recorded,
    "ChangeApplied": _change_applied,
    "ChangeReverted": _change_applied,
    "RequirementUpserted": _requirement_upserted,
    "EvidenceClaimed": _evidence_claimed,
    "ProjectionMapUpserted": _projection_map_upserted,
    "SelectionMapResolved": _selection_map_resolved,
    "TestPlanUpserted": _test_plan_upserted,
    "LifecycleStageChanged": _lifecycle_stage_changed,
    "PowerModelSet": _power_model_set,
    "ThermalModelSet": _thermal_model_set,
    "FailureModeAdded": _failure_mode_added,
    "HumanScenarioUpserted": _human_scenario_upserted,
    "EcommerceOfferUpserted": _ecommerce_offer_upserted,
}

_AUDIT_ONLY_EVENTS = {
    "InvitationRequested",
    "InvitationApproved",
    "ApprovalGranted",
    "SimulationRunRequested",
    "SimulationRunCompleted",
    "GenerationRequested",
    "GenerationFailed",
}


def object_tree(snapshot: ProjectSnapshot) -> list[dict]:
    nodes = {
        uri: {"object": deepcopy(node.model_dump(mode="json")), "children": []}
        for uri, node in snapshot.objects.items()
    }
    roots: list[dict] = []
    for container in nodes.values():
        parent_uri = container["object"].get("parent_uri")
        if parent_uri and parent_uri in nodes:
            nodes[parent_uri]["children"].append(container)
        else:
            roots.append(container)

    def sort_node(node: dict) -> None:
        node["children"].sort(key=lambda item: (item["object"]["kind"], item["object"]["name"]))
        for child in node["children"]:
            sort_node(child)

    roots.sort(key=lambda item: item["object"]["name"])
    for root in roots:
        sort_node(root)
    return roots
