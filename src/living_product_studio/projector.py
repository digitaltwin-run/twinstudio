from __future__ import annotations

from copy import deepcopy

from living_product_studio.domain import (
    Annotation,
    ArtifactRecord,
    ChangePlan,
    EcommerceOffer,
    EvidenceClaim,
    EventEnvelope,
    FailureMode,
    HumanUseScenario,
    LifecycleStage,
    ObjectNode,
    PowerModel,
    ProjectSnapshot,
    Requirement,
    Role,
    ProjectionMap,
    SelectionMap,
    TestPlan,
    ThermalModel,
    utcnow,
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
    data = event.data
    event_type = event.event_type
    if event_type == "MembershipGranted":
        snapshot.memberships[data["email"].lower()] = Role(data["role"])
    elif event_type == "MembershipRevoked":
        snapshot.memberships.pop(data["email"].lower(), None)
    elif event_type == "ObjectUpserted":
        node = ObjectNode.model_validate(data["object"])
        snapshot.objects[node.uri] = node
    elif event_type == "ObjectRemoved":
        snapshot.objects.pop(data["object_uri"], None)
    elif event_type == "ArtifactAttached":
        artifact = ArtifactRecord.model_validate(data["artifact"])
        snapshot.artifacts[artifact.uri] = artifact
        if artifact.object_uri and artifact.object_uri in snapshot.objects:
            node = snapshot.objects[artifact.object_uri]
            if artifact.uri not in node.artifact_uris:
                node.artifact_uris.append(artifact.uri)
    elif event_type == "AnnotationCreated":
        annotation = Annotation.model_validate(data["annotation"])
        snapshot.annotations[annotation.uri] = annotation
    elif event_type == "AnnotationStatusChanged":
        uri = data["annotation_uri"]
        if uri in snapshot.annotations:
            snapshot.annotations[uri].status = data["status"]
    elif event_type == "ChangePlanCreated":
        plan = ChangePlan.model_validate(data["plan"])
        snapshot.change_plans[plan.plan_id] = plan
    elif event_type == "ChangeApplied":
        snapshot.revision = data["new_revision"]
        for patch in data.get("parameter_patches", []):
            target = snapshot.objects.get(patch["object_uri"])
            if target and patch["parameter"] in target.parameters:
                target.parameters[patch["parameter"]].value = patch["value"]
            elif target:
                from living_product_studio.domain import ParameterValue

                target.parameters[patch["parameter"]] = ParameterValue(
                    value=patch["value"], unit=patch.get("unit"), status="approved"
                )
    elif event_type == "RequirementUpserted":
        requirement = Requirement.model_validate(data["requirement"])
        snapshot.requirements[requirement.uri] = requirement
    elif event_type == "EvidenceClaimed":
        claim = EvidenceClaim.model_validate(data["claim"])
        snapshot.claims[claim.claim_id] = claim
    elif event_type == "ProjectionMapUpserted":
        projection = ProjectionMap.model_validate(data["projection_map"])
        snapshot.projection_maps[projection.uri] = projection
    elif event_type == "SelectionMapResolved":
        selection_map = SelectionMap.model_validate(data["selection_map"])
        snapshot.selection_maps[selection_map.uri] = selection_map
    elif event_type == "TestPlanUpserted":
        test_plan = TestPlan.model_validate(data["test_plan"])
        snapshot.test_plans[test_plan.uri] = test_plan
    elif event_type == "LifecycleStageChanged":
        snapshot.lifecycle_stage = LifecycleStage(data["stage"])
    elif event_type == "PowerModelSet":
        snapshot.power_model = PowerModel.model_validate(data["power_model"])
    elif event_type == "ThermalModelSet":
        snapshot.thermal_model = ThermalModel.model_validate(data["thermal_model"])
    elif event_type == "FailureModeAdded":
        failure = FailureMode.model_validate(data["failure_mode"])
        snapshot.failure_modes = [item for item in snapshot.failure_modes if item.uri != failure.uri]
        snapshot.failure_modes.append(failure)
    elif event_type == "HumanScenarioUpserted":
        scenario = HumanUseScenario.model_validate(data["scenario"])
        snapshot.human_scenarios = [item for item in snapshot.human_scenarios if item.uri != scenario.uri]
        snapshot.human_scenarios.append(scenario)
    elif event_type == "EcommerceOfferUpserted":
        offer = EcommerceOffer.model_validate(data["offer"])
        snapshot.ecommerce_offers = [item for item in snapshot.ecommerce_offers if item.uri != offer.uri]
        snapshot.ecommerce_offers.append(offer)
    elif event_type in {
        "InvitationRequested",
        "InvitationApproved",
        "ApprovalGranted",
        "SimulationRunRequested",
        "SimulationRunCompleted",
        "GenerationRequested",
        "GenerationCompleted",
    }:
        # Audit-only events are intentionally retained in the stream and do not need
        # extra fields in the compact read model.
        pass
    else:
        snapshot.metadata.setdefault("unhandled_events", []).append(event_type)
    snapshot.stream_version = event.stream_version
    snapshot.updated_at = event.occurred_at or utcnow()


def object_tree(snapshot: ProjectSnapshot) -> list[dict]:
    nodes = {uri: {"object": deepcopy(node.model_dump(mode="json")), "children": []} for uri, node in snapshot.objects.items()}
    roots: list[dict] = []
    for uri, container in nodes.items():
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
