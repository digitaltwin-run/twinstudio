from __future__ import annotations

from typing import Any

from twinstudio.domain import (
    Annotation,
    ArtifactRecord,
    ChangePlan,
    CommandEnvelope,
    DesignFixationReview,
    EcommerceOffer,
    EventEnvelope,
    EvidenceClaim,
    FailureMode,
    HumanUseScenario,
    LifecycleStage,
    ObjectNode,
    PowerModel,
    ProjectionMap,
    ProjectSnapshot,
    Requirement,
    Role,
    SelectionMap,
    TestPlan,
    ThermalModel,
)
from twinstudio.event_store import EventStore
from twinstudio.evolution_models import (
    DslExecutionRecord,
    EvolutionRun,
    LifecycleBlueprint,
    LifecycleHistoryEntry,
)
from twinstudio.mqtt_bus import EventPublisher
from twinstudio.permissions import require_permission
from twinstudio.projector import ProjectNotFound, object_tree, project_from_events


class CommandRejected(ValueError):
    pass


class QueryService:
    def __init__(self, store: EventStore):
        self.store = store

    def project(self, project_id: str) -> ProjectSnapshot:
        return project_from_events(self.store.load(project_id))

    def tree(self, project_id: str) -> list[dict]:
        return object_tree(self.project(project_id))

    def events(self, project_id: str) -> list[EventEnvelope]:
        return self.store.load(project_id)

    def projects(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for stream_id in self.store.list_streams():
            try:
                snapshot = self.project(stream_id)
            except ProjectNotFound:
                continue
            result.append(
                {
                    "project_id": snapshot.project_id,
                    "tenant": snapshot.tenant,
                    "name": snapshot.name,
                    "revision": snapshot.revision,
                    "lifecycle_stage": snapshot.lifecycle_stage,
                    "stream_version": snapshot.stream_version,
                    "updated_at": snapshot.updated_at.isoformat(),
                }
            )
        return result


class CommandBus:
    def __init__(self, store: EventStore, publisher: EventPublisher):
        self.store = store
        self.publisher = publisher
        self.queries = QueryService(store)

    def execute(self, command: CommandEnvelope) -> list[EventEnvelope]:
        if command.command_type == "project.create":
            events = self._create_project(command)
        else:
            snapshot = self.queries.project(command.project_id)
            role = snapshot.memberships.get(command.actor.lower())
            events = self._handle_existing(command, snapshot, role)
        stored = self.store.append(command.project_id, command.expected_version, events)
        self.publisher.publish_events(command.project_id, stored)
        return stored

    def _create_project(self, command: CommandEnvelope) -> list[EventEnvelope]:
        if self.store.current_version(command.project_id) != 0:
            raise CommandRejected("Project already exists")
        data = dict(command.payload)
        data.setdefault("project_id", command.project_id)
        data.setdefault("tenant", "default")
        data.setdefault("name", command.project_id)
        data.setdefault("memberships", {command.actor.lower(): Role.CREATOR.value})
        snapshot = ProjectSnapshot.model_validate(data)
        return [self._event(command, "ProjectCreated", snapshot.model_dump(mode="json"))]

    def _handle_existing(
        self,
        command: CommandEnvelope,
        snapshot: ProjectSnapshot,
        role: Role | None,
    ) -> list[EventEnvelope]:
        event_type: str
        data: dict[str, Any]
        permission: str
        payload = command.payload
        match command.command_type:
            case "object.upsert":
                permission = "change.apply"
                node = ObjectNode.model_validate(payload["object"])
                event_type, data = "ObjectUpserted", {"object": node.model_dump(mode="json")}
            case "object.remove":
                permission = "change.apply"
                event_type, data = "ObjectRemoved", {"object_uri": payload["object_uri"]}
            case "artifact.attach":
                permission = "artifact.generate"
                artifact = ArtifactRecord.model_validate(payload["artifact"])
                event_type, data = "ArtifactAttached", {"artifact": artifact.model_dump(mode="json")}
            case "annotation.create":
                permission = "annotation.create"
                annotation = Annotation.model_validate(payload["annotation"])
                event_type, data = "AnnotationCreated", {"annotation": annotation.model_dump(mode="json")}
            case "annotation.status":
                permission = "annotation.create"
                annotation = snapshot.annotations.get(payload["annotation_uri"])
                if annotation is None:
                    raise CommandRejected("Annotation not found")
                status = str(payload["status"])
                if status not in {"open", "resolved", "rejected"}:
                    raise CommandRejected("Invalid annotation status")
                event_type, data = "AnnotationStatusChanged", {
                    "annotation_uri": annotation.uri,
                    "status": status,
                }
            case "change.plan.record":
                permission = "change.plan"
                plan = ChangePlan.model_validate(payload["plan"])
                event_type, data = "ChangePlanCreated", {"plan": plan.model_dump(mode="json")}
            case "design_fixation.review.record":
                permission = "change.plan"
                review = DesignFixationReview.model_validate(payload["review"])
                event_type, data = "DesignFixationReviewRecorded", {
                    "review": review.model_dump(mode="json")
                }
            case "evolution.run.record":
                permission = "change.plan"
                run = EvolutionRun.model_validate(payload["run"])
                event_type, data = "EvolutionRunRecorded", {"run": run.model_dump(mode="json")}
            case "lifecycle.blueprint.upsert":
                permission = "change.apply"
                blueprint = LifecycleBlueprint.model_validate(payload["blueprint"])
                event_type, data = "LifecycleBlueprintUpserted", {
                    "blueprint": blueprint.model_dump(mode="json")
                }
            case "lifecycle.transition.record":
                permission = "approval.grant"
                transition = LifecycleHistoryEntry.model_validate(payload["transition"])
                event_type, data = "LifecycleTransitionRecorded", {
                    "transition": transition.model_dump(mode="json")
                }
            case "dsl.execution.record":
                permission = "change.plan"
                execution = DslExecutionRecord.model_validate(payload["execution"])
                event_type, data = "DslExecutionRecorded", {
                    "execution": execution.model_dump(mode="json")
                }
            case "change.apply":
                permission = "change.apply"
                event_type, data = "ChangeApplied", dict(payload)
            case "change.revert":
                permission = "change.apply"
                event_type, data = "ChangeReverted", dict(payload)
            case "membership.grant":
                permission = "membership.manage"
                event_type, data = "MembershipGranted", {
                    "email": payload["email"].lower(),
                    "role": Role(payload["role"]).value,
                }
            case "membership.revoke":
                permission = "membership.manage"
                if payload["email"].lower() == command.actor.lower():
                    raise CommandRejected("An actor cannot revoke their own membership")
                event_type, data = "MembershipRevoked", {"email": payload["email"].lower()}
            case "lifecycle.set":
                permission = "approval.grant"
                event_type, data = "LifecycleStageChanged", {"stage": LifecycleStage(payload["stage"]).value}
            case "requirement.upsert":
                permission = "change.apply"
                model = Requirement.model_validate(payload["requirement"])
                event_type, data = "RequirementUpserted", {"requirement": model.model_dump(mode="json")}
            case "claim.add":
                permission = "change.plan"
                model = EvidenceClaim.model_validate(payload["claim"])
                event_type, data = "EvidenceClaimed", {"claim": model.model_dump(mode="json")}
            case "projection_map.upsert":
                permission = "change.apply"
                model = ProjectionMap.model_validate(payload["projection_map"])
                event_type, data = "ProjectionMapUpserted", {"projection_map": model.model_dump(mode="json")}
            case "selection_map.record":
                permission = "change.plan"
                model = SelectionMap.model_validate(payload["selection_map"])
                event_type, data = "SelectionMapResolved", {"selection_map": model.model_dump(mode="json")}
            case "test_plan.upsert":
                permission = "change.apply"
                model = TestPlan.model_validate(payload["test_plan"])
                event_type, data = "TestPlanUpserted", {"test_plan": model.model_dump(mode="json")}
            case "power.set":
                permission = "change.apply"
                model = PowerModel.model_validate(payload["power_model"])
                event_type, data = "PowerModelSet", {"power_model": model.model_dump(mode="json")}
            case "thermal.set":
                permission = "change.apply"
                model = ThermalModel.model_validate(payload["thermal_model"])
                event_type, data = "ThermalModelSet", {"thermal_model": model.model_dump(mode="json")}
            case "failure_mode.add":
                permission = "change.apply"
                model = FailureMode.model_validate(payload["failure_mode"])
                event_type, data = "FailureModeAdded", {"failure_mode": model.model_dump(mode="json")}
            case "human_scenario.upsert":
                permission = "change.apply"
                model = HumanUseScenario.model_validate(payload["scenario"])
                event_type, data = "HumanScenarioUpserted", {"scenario": model.model_dump(mode="json")}
            case "ecommerce_offer.upsert":
                permission = "change.apply"
                model = EcommerceOffer.model_validate(payload["offer"])
                event_type, data = "EcommerceOfferUpserted", {"offer": model.model_dump(mode="json")}
            case "generation.request":
                permission = "artifact.generate"
                event_type, data = "GenerationRequested", dict(payload)
            case "generation.complete":
                permission = "artifact.generate"
                artifacts = [ArtifactRecord.model_validate(item) for item in payload.get("artifacts", [])]
                objects = [ObjectNode.model_validate(item) for item in payload.get("objects", [])]
                event_type, data = "GenerationCompleted", {
                    **dict(payload),
                    "artifacts": [item.model_dump(mode="json") for item in artifacts],
                    "objects": [item.model_dump(mode="json") for item in objects],
                }
            case "generation.fail":
                permission = "artifact.generate"
                event_type, data = "GenerationFailed", dict(payload)
            case "simulation.request":
                permission = "simulation.run"
                event_type, data = "SimulationRunRequested", dict(payload)
            case "approval.grant":
                permission = "approval.grant"
                event_type, data = "ApprovalGranted", dict(payload)
            case _:
                raise CommandRejected(f"Unknown command type: {command.command_type}")
        require_permission(role, permission)
        return [self._event(command, event_type, data)]

    @staticmethod
    def _event(command: CommandEnvelope, event_type: str, data: dict[str, Any]) -> EventEnvelope:
        return EventEnvelope(
            stream_id=command.project_id,
            event_type=event_type,
            data=data,
            actor=command.actor,
            correlation_id=command.correlation_id or command.command_id,
            causation_id=command.command_id,
        )
