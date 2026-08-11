from __future__ import annotations

from collections import OrderedDict

from living_product_studio.domain import (
    ProjectSnapshot,
    RegionSelection,
    SelectionDiagnostic,
    SelectionMap,
    SourceView,
)
from living_product_studio.uri import is_within_scope


def resolve_selection(
    selection: RegionSelection,
    project: ProjectSnapshot,
    *,
    actor: str,
) -> SelectionMap:
    """Resolve ephemeral screen/mesh evidence to persistent product identifiers.

    The resolver deliberately does not invent topology. A selection can resolve to:
    object URIs, parametric feature URIs, semantic face URIs, and native B-Rep face IDs.
    Mesh triangle indices are retained as evidence but are not treated as stable IDs.
    """

    objects: OrderedDict[str, None] = OrderedDict()
    features: OrderedDict[str, None] = OrderedDict()
    semantic_faces: OrderedDict[str, None] = OrderedDict()
    brep_faces: OrderedDict[str, None] = OrderedDict()
    diagnostics: list[SelectionDiagnostic] = []

    if selection.project_id != project.project_id:
        diagnostics.append(
            SelectionDiagnostic(
                severity="blocking",
                code="PROJECT_MISMATCH",
                message="Selection belongs to a different project.",
                target_uris=selection.target_object_uris,
            )
        )

    if selection.project_revision != project.revision:
        diagnostics.append(
            SelectionDiagnostic(
                severity="warning",
                code="REVISION_MISMATCH",
                message=(
                    f"Selection was created at revision {selection.project_revision}; "
                    f"current project revision is {project.revision}. Re-pick before destructive geometry edits."
                ),
                target_uris=selection.target_object_uris,
            )
        )

    for uri in selection.target_object_uris:
        if uri in project.objects:
            objects[uri] = None
        else:
            diagnostics.append(
                SelectionDiagnostic(
                    severity="blocking",
                    code="MISSING_TARGET_OBJECT",
                    message="Selected target object does not exist in the current project snapshot.",
                    target_uris=[uri],
                )
            )

    feature_by_semantic: dict[str, str] = {}
    feature_uris: set[str] = set()
    for node in project.objects.values():
        for feature in node.features:
            feature_uris.add(feature.uri)
            for semantic_face in feature.semantic_faces:
                feature_by_semantic[semantic_face] = feature.uri

    for hit in selection.ray_hits:
        if hit.object_uri not in project.objects:
            diagnostics.append(
                SelectionDiagnostic(
                    severity="error",
                    code="RAY_HIT_OBJECT_MISSING",
                    message="A ray hit refers to an object unavailable in this revision.",
                    target_uris=[hit.object_uri],
                )
            )
            continue
        if not is_within_scope(hit.object_uri, selection.target_object_uris, ignore_revision=True):
            diagnostics.append(
                SelectionDiagnostic(
                    severity="blocking",
                    code="RAY_HIT_OUTSIDE_SCOPE",
                    message="A ray hit is outside the explicitly selected object scope.",
                    target_uris=[hit.object_uri],
                )
            )
            continue
        objects[hit.object_uri] = None
        if hit.semantic_face_uri:
            semantic_faces[hit.semantic_face_uri] = None
            mapped_feature = feature_by_semantic.get(hit.semantic_face_uri)
            if mapped_feature:
                features[mapped_feature] = None
        if hit.brep_face_id:
            brep_faces[hit.brep_face_id] = None
        if hit.face_index is not None and not hit.brep_face_id and not hit.semantic_face_uri:
            diagnostics.append(
                SelectionDiagnostic(
                    severity="warning",
                    code="EPHEMERAL_MESH_FACE",
                    message=(
                        "Triangle index is available, but no semantic/B-Rep identity is attached. "
                        "The CAD adapter must re-resolve it against the exact mesh hash."
                    ),
                    target_uris=[hit.object_uri],
                    data={"face_index": hit.face_index, "mesh_hash": hit.mesh_hash},
                )
            )

    if selection.projection_entity_ids:
        matching_maps = [
            item
            for item in project.projection_maps.values()
            if not selection.source_artifact_uri or item.source_artifact_uri == selection.source_artifact_uri
        ]
        if not matching_maps:
            diagnostics.append(
                SelectionDiagnostic(
                    severity="blocking",
                    code="PROJECTION_MAP_MISSING",
                    message="No 2D/photo-to-3D projection map is available for the selected source artifact.",
                    target_uris=selection.target_object_uris,
                )
            )
        for entity_id in selection.projection_entity_ids:
            binding = next(
                (projection.entities.get(entity_id) for projection in matching_maps if entity_id in projection.entities),
                None,
            )
            if binding is None:
                diagnostics.append(
                    SelectionDiagnostic(
                        severity="error",
                        code="PROJECTION_ENTITY_UNRESOLVED",
                        message=f"Projection entity {entity_id!r} has no mapping.",
                        target_uris=selection.target_object_uris,
                    )
                )
                continue
            if not is_within_scope(binding.object_uri, selection.target_object_uris, ignore_revision=True):
                diagnostics.append(
                    SelectionDiagnostic(
                        severity="blocking",
                        code="PROJECTION_TARGET_OUTSIDE_SCOPE",
                        message="Projection mapping points outside the selected object scope.",
                        target_uris=[binding.object_uri],
                    )
                )
                continue
            objects[binding.object_uri] = None
            if binding.feature_uri:
                features[binding.feature_uri] = None
            if binding.semantic_face_uri:
                semantic_faces[binding.semantic_face_uri] = None
            if binding.brep_face_id:
                brep_faces[binding.brep_face_id] = None

    if selection.source_view in {SourceView.DRAWING_2D, SourceView.PHOTO} and not selection.projection_entity_ids:
        diagnostics.append(
            SelectionDiagnostic(
                severity="warning",
                code="SCREEN_REGION_ONLY",
                message=(
                    "The 2D/photo mark is stored, but it is not yet tied to projection entities. "
                    "Use calibration/entity picking before automatic 3D modification."
                ),
                target_uris=selection.target_object_uris,
            )
        )

    blocking = any(item.severity == "blocking" for item in diagnostics)
    useful_geometry = bool(features or semantic_faces or brep_faces)
    if blocking:
        status = "unresolved"
    elif useful_geometry and not any(item.severity in {"error", "warning"} for item in diagnostics):
        status = "resolved"
    elif objects:
        status = "partial"
    else:
        status = "unresolved"

    uri = selection.uri.replace("/region/", "/selection-map/")
    if uri == selection.uri:
        uri = f"{selection.uri}/selection-map"
    return SelectionMap(
        uri=uri,
        selection_uri=selection.uri,
        target_revision=project.revision,
        resolved_object_uris=list(objects),
        resolved_feature_uris=[uri for uri in features if uri in feature_uris],
        resolved_semantic_face_uris=list(semantic_faces),
        resolved_brep_face_ids=list(brep_faces),
        status=status,
        diagnostics=diagnostics,
        created_by=actor,
        metadata={
            "source_view": selection.source_view,
            "tool": selection.tool,
            "ray_hit_count": len(selection.ray_hits),
            "projection_entity_count": len(selection.projection_entity_ids),
        },
    )
