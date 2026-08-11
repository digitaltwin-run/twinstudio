from pathlib import Path

import pytest

from living_product_studio.bus import CommandBus, QueryService
from living_product_studio.domain import CommandEnvelope
from living_product_studio.event_store import ConcurrencyError, EventStore
from living_product_studio.mqtt_bus import NullPublisher
from living_product_studio.seed import seed_from_file


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
