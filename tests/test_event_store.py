from pathlib import Path

import pytest

from twinstudio.bus import CommandBus, QueryService
from twinstudio.domain import CommandEnvelope, EventEnvelope, ParameterValue
from twinstudio.event_store import ConcurrencyError, EventStore
from twinstudio.mqtt_bus import NullPublisher
from twinstudio.seed import seed_from_file


def test_projection_synchronizes_canonical_boss_parameter_into_feature(
    project_snapshot,
) -> None:
    from twinstudio.projector import apply_event

    lid_uri = "poa://demo/demo-rpi5@main/part/lid"
    lid = project_snapshot.objects[lid_uri].model_copy(deep=True)
    lid.parameters["auxiliary_boss_top_z"] = ParameterValue(
        value=11.0,
        unit="mm",
        status="approved",
    )
    apply_event(
        project_snapshot,
        EventEnvelope(
            stream_id=project_snapshot.project_id,
            stream_version=project_snapshot.stream_version + 1,
            event_type="ObjectUpserted",
            data={"object": lid.model_dump(mode="json")},
            actor="cad-worker@example.test",
        ),
    )

    projected_lid = project_snapshot.objects[lid_uri]
    auxiliary_bosses = next(
        feature
        for feature in projected_lid.features
        if feature.uri.endswith("/feature/aux-bosses")
    )
    assert auxiliary_bosses.parameters["top_above_base"].value == 11.0


def test_seed_reconstructs_full_project(tmp_path: Path) -> None:
    store = EventStore(f"sqlite:///{tmp_path / 'events.db'}")
    source = Path(__file__).resolve().parents[1] / "examples" / "rpi5-camera3" / "project.json"
    seed_from_file(store, NullPublisher(), source)
    snapshot = QueryService(store).project("demo-rpi5")
    assert len(snapshot.objects) == 15
    assert snapshot.projection_maps
    assert snapshot.selection_maps
    assert snapshot.test_plans
    assert snapshot.stream_version == store.current_version("demo-rpi5")


def test_optimistic_concurrency(tmp_path: Path, project_snapshot) -> None:
    store = EventStore(f"sqlite:///{tmp_path / 'events.db'}")
    bus = CommandBus(store, NullPublisher())
    bus.execute(
        CommandEnvelope(
            command_type="project.create",
            project_id="p",
            expected_version=0,
            actor="creator@example.test",
            payload={"project_id": "p", "tenant": "demo", "name": "P"},
        )
    )
    with pytest.raises(ConcurrencyError):
        bus.execute(
            CommandEnvelope(
                command_type="lifecycle.set",
                project_id="p",
                expected_version=0,
                actor="creator@example.test",
                payload={"stage": "requirements"},
            )
        )


def test_design_fixation_review_event_reconstructs(tmp_path: Path, project_snapshot) -> None:
    from twinstudio.feature_lenses import FeatureLensEngine
    from twinstudio.settings import Settings

    store = EventStore(f"sqlite:///{tmp_path / 'reviews.db'}")
    bus = CommandBus(store, NullPublisher())
    bus.execute(
        CommandEnvelope(
            command_type="project.create",
            project_id="review-project",
            expected_version=0,
            actor="creator@example.test",
            payload={
                "project_id": "review-project",
                "tenant": "demo",
                "name": "Review project",
                "memberships": {"creator@example.test": "creator"},
                "objects": project_snapshot.objects,
            },
        )
    )
    snapshot = QueryService(store).project("review-project")
    result = FeatureLensEngine(Settings(litellm_model="")).scan(
        snapshot,
        target_uri="poa://demo/demo-rpi5@main/part/base",
        challenge="challenge current hinge assumptions",
        actor="creator@example.test",
        lens_ids=["shape", "connectivity_among_parts"],
        max_alternatives=2,
        use_llm=False,
    )
    bus.execute(
        CommandEnvelope(
            command_type="design_fixation.review.record",
            project_id="review-project",
            expected_version=snapshot.stream_version,
            actor="creator@example.test",
            payload={"review": result.review.model_dump(mode="json")},
        )
    )
    reconstructed = QueryService(store).project("review-project")
    assert result.review.review_id in reconstructed.design_fixation_reviews
    assert reconstructed.design_fixation_reviews[result.review.review_id].selected_lens_ids == [
        "shape",
        "connectivity_among_parts",
    ]
