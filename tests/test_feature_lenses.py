from __future__ import annotations

from copy import deepcopy

import pytest

from twinstudio.feature_lenses import FeatureLensEngine, load_feature_lens_catalog
from twinstudio.settings import Settings


def test_catalog_preserves_declared_count_and_source_gap() -> None:
    catalog = load_feature_lens_catalog()
    assert catalog.declared_lens_count == 50
    assert len(catalog.lenses) == 50
    assert catalog.active_lens_count == 49
    assert sum(1 for lens in catalog.lenses if lens.enabled) == 49
    unresolved = [lens for lens in catalog.lenses if lens.source_status == "unresolved"]
    assert len(unresolved) == 1
    assert unresolved[0].enabled is False
    external_relations = [lens for lens in catalog.lenses if lens.name == "External Relations"]
    assert len(external_relations) == 2
    assert all(lens.source_status == "duplicate_label" for lens in external_relations)


def test_local_scan_is_review_only_and_does_not_mutate_snapshot(project_snapshot) -> None:
    original = deepcopy(project_snapshot.model_dump(mode="json"))
    settings = Settings(litellm_model="")
    engine = FeatureLensEngine(settings)
    result = engine.scan(
        project_snapshot,
        target_uri="poa://demo/demo-rpi5@main/part/base",
        challenge="Improve printability without fixing on the present hinge shape.",
        actor="creator@example.test",
        max_alternatives=5,
        use_llm=False,
    )
    assert result.mode == "local"
    assert len(result.review.selected_lens_ids) == 49
    assert len(result.review.observations) == 49
    assert len(result.review.alternatives) == 5
    assert all(idea.target_uri == result.review.target_uri for idea in result.review.alternatives)
    assert project_snapshot.model_dump(mode="json") == original
    assert any("49 visible source rows" in warning for warning in result.review.warnings)


def test_scan_rejects_unknown_or_disabled_lens(project_snapshot) -> None:
    engine = FeatureLensEngine(Settings(litellm_model=""))
    with pytest.raises(ValueError, match="Unknown or disabled"):
        engine.scan(
            project_snapshot,
            target_uri="poa://demo/demo-rpi5@main/part/base",
            challenge="test",
            actor="creator@example.test",
            lens_ids=["unresolved_source_slot"],
            use_llm=False,
        )
