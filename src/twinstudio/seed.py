from __future__ import annotations

from pathlib import Path

from twinstudio.domain import EventEnvelope, ProjectSnapshot
from twinstudio.event_store import EventStore
from twinstudio.mqtt_bus import EventPublisher


def seed_from_file(store: EventStore, publisher: EventPublisher, path: Path, *, force: bool = False) -> ProjectSnapshot:
    snapshot = ProjectSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    if store.current_version(snapshot.project_id):
        if not force:
            return snapshot
        store.delete_stream(snapshot.project_id)
    actor = next(
        (email for email, role in snapshot.memberships.items() if str(role) == "creator"),
        "creator@example.test",
    )
    initial = snapshot.model_copy(
        update={
            "objects": {},
            "artifacts": {},
            "annotations": {},
            "change_plans": {},
            "design_fixation_reviews": {},
            "evolution_runs": {},
            "lifecycle_blueprints": {},
            "lifecycle_history": [],
            "dsl_programs": {},
            "dsl_executions": {},
            "requirements": {},
            "claims": {},
            "projection_maps": {},
            "selection_maps": {},
            "failure_modes": [],
            "human_scenarios": [],
            "test_plans": {},
            "power_model": None,
            "thermal_model": None,
            "ecommerce_offers": [],
            "stream_version": 0,
        }
    )
    events: list[EventEnvelope] = [
        EventEnvelope(
            stream_id=snapshot.project_id,
            event_type="ProjectCreated",
            actor=actor,
            data=initial.model_dump(mode="json"),
        )
    ]
    for node in snapshot.objects.values():
        events.append(
            EventEnvelope(
                stream_id=snapshot.project_id,
                event_type="ObjectUpserted",
                actor=actor,
                data={"object": node.model_dump(mode="json")},
            )
        )
    for artifact in snapshot.artifacts.values():
        events.append(
            EventEnvelope(
                stream_id=snapshot.project_id,
                event_type="ArtifactAttached",
                actor=actor,
                data={"artifact": artifact.model_dump(mode="json")},
            )
        )
    for requirement in snapshot.requirements.values():
        events.append(
            EventEnvelope(
                stream_id=snapshot.project_id,
                event_type="RequirementUpserted",
                actor=actor,
                data={"requirement": requirement.model_dump(mode="json")},
            )
        )
    for claim in snapshot.claims.values():
        events.append(
            EventEnvelope(
                stream_id=snapshot.project_id,
                event_type="EvidenceClaimed",
                actor=actor,
                data={"claim": claim.model_dump(mode="json")},
            )
        )
    for projection in snapshot.projection_maps.values():
        events.append(
            EventEnvelope(
                stream_id=snapshot.project_id,
                event_type="ProjectionMapUpserted",
                actor=actor,
                data={"projection_map": projection.model_dump(mode="json")},
            )
        )
    for selection_map in snapshot.selection_maps.values():
        events.append(
            EventEnvelope(
                stream_id=snapshot.project_id,
                event_type="SelectionMapResolved",
                actor=actor,
                data={"selection_map": selection_map.model_dump(mode="json")},
            )
        )
    for test_plan in snapshot.test_plans.values():
        events.append(
            EventEnvelope(
                stream_id=snapshot.project_id,
                event_type="TestPlanUpserted",
                actor=actor,
                data={"test_plan": test_plan.model_dump(mode="json")},
            )
        )
    for review in snapshot.design_fixation_reviews.values():
        events.append(
            EventEnvelope(
                stream_id=snapshot.project_id,
                event_type="DesignFixationReviewRecorded",
                actor=actor,
                data={"review": review.model_dump(mode="json")},
            )
        )
    if snapshot.power_model:
        events.append(
            EventEnvelope(
                stream_id=snapshot.project_id,
                event_type="PowerModelSet",
                actor=actor,
                data={"power_model": snapshot.power_model.model_dump(mode="json")},
            )
        )
    if snapshot.thermal_model:
        events.append(
            EventEnvelope(
                stream_id=snapshot.project_id,
                event_type="ThermalModelSet",
                actor=actor,
                data={"thermal_model": snapshot.thermal_model.model_dump(mode="json")},
            )
        )
    for failure in snapshot.failure_modes:
        events.append(
            EventEnvelope(
                stream_id=snapshot.project_id,
                event_type="FailureModeAdded",
                actor=actor,
                data={"failure_mode": failure.model_dump(mode="json")},
            )
        )
    for scenario in snapshot.human_scenarios:
        events.append(
            EventEnvelope(
                stream_id=snapshot.project_id,
                event_type="HumanScenarioUpserted",
                actor=actor,
                data={"scenario": scenario.model_dump(mode="json")},
            )
        )
    for offer in snapshot.ecommerce_offers:
        events.append(
            EventEnvelope(
                stream_id=snapshot.project_id,
                event_type="EcommerceOfferUpserted",
                actor=actor,
                data={"offer": offer.model_dump(mode="json")},
            )
        )
    stored = store.append(snapshot.project_id, 0, events)
    publisher.publish_events(snapshot.project_id, stored)
    return snapshot
