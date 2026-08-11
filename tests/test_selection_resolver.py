from copy import deepcopy

from living_product_studio.domain import RegionSelection
from living_product_studio.selection_resolver import resolve_selection


def test_3d_semantic_selection_resolves_feature(project_snapshot, example_selection) -> None:
    result = resolve_selection(example_selection, project_snapshot, actor="editor@example.test")
    assert result.status in {"resolved", "partial"}
    assert result.resolved_object_uris == ["poa://demo/demo-rpi5@main/part/base"]
    assert "poa://demo/demo-rpi5@main/part/base/feature/shell" in result.resolved_feature_uris
    assert "poa://demo/demo-rpi5@main/part/base/face/front" in result.resolved_semantic_face_uris


def test_2d_selection_without_projection_is_not_invented(project_snapshot) -> None:
    data = {
        "selection_id": "s2d",
        "uri": "poa://demo/demo-rpi5@main/region/s2d",
        "project_id": "demo-rpi5",
        "project_revision": "main",
        "source_view": "2d",
        "tool": "pencil",
        "target_object_uris": ["poa://demo/demo-rpi5@main/part/lid"],
        "screen_path": [{"x": 1, "y": 1}, {"x": 10, "y": 10}],
        "ray_hits": [],
        "source_artifact_uri": "poa://demo/demo-rpi5@main/artifact/assembly-front",
        "projection_entity_ids": [],
        "created_by": "editor@example.test",
    }
    result = resolve_selection(RegionSelection.model_validate(data), project_snapshot, actor="editor@example.test")
    assert result.status == "partial"
    assert any(item.code == "SCREEN_REGION_ONLY" for item in result.diagnostics)


def test_projection_entity_resolves_to_lid(project_snapshot) -> None:
    data = {
        "selection_id": "s-proj",
        "uri": "poa://demo/demo-rpi5@main/region/s-proj",
        "project_id": "demo-rpi5",
        "project_revision": "main",
        "source_view": "2d",
        "tool": "rectangle",
        "target_object_uris": ["poa://demo/demo-rpi5@main/part/lid"],
        "screen_path": [{"x": 1, "y": 1}, {"x": 10, "y": 10}],
        "ray_hits": [],
        "source_artifact_uri": "poa://demo/demo-rpi5@main/artifact/assembly-front",
        "projection_entity_ids": ["front.lid.outer-slope"],
        "created_by": "editor@example.test",
    }
    result = resolve_selection(RegionSelection.model_validate(data), project_snapshot, actor="editor@example.test")
    assert result.status == "resolved"
    assert result.resolved_feature_uris == ["poa://demo/demo-rpi5@main/part/lid/feature/shell"]
