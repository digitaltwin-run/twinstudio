from __future__ import annotations

from collections import Counter
from typing import Any

from twinstudio.domain import ProjectSnapshot
from twinstudio.projector import object_tree


def unified_specification(snapshot: ProjectSnapshot) -> dict[str, Any]:
    process_counts = Counter(str(node.manufacturing.process) for node in snapshot.objects.values())
    kind_counts = Counter(str(node.kind) for node in snapshot.objects.values())
    return {
        "project": {
            "project_id": snapshot.project_id,
            "tenant": snapshot.tenant,
            "name": snapshot.name,
            "description": snapshot.description,
            "revision": snapshot.revision,
            "lifecycle_stage": snapshot.lifecycle_stage,
            "stream_version": snapshot.stream_version,
        },
        "assembly_tree": object_tree(snapshot),
        "objects": [node.model_dump(mode="json") for node in snapshot.objects.values()],
        "features": [
            {
                "object_uri": node.uri,
                "object_name": node.name,
                "feature": feature.model_dump(mode="json"),
            }
            for node in snapshot.objects.values()
            for feature in node.features
        ],
        "requirements": [item.model_dump(mode="json") for item in snapshot.requirements.values()],
        "evidence_claims": [item.model_dump(mode="json") for item in snapshot.claims.values()],
        "geometry_mapping": {
            "projection_maps": [item.model_dump(mode="json") for item in snapshot.projection_maps.values()],
            "selection_maps": [item.model_dump(mode="json") for item in snapshot.selection_maps.values()],
        },
        "design_fixation": {
            "reviews": [
                item.model_dump(mode="json")
                for item in snapshot.design_fixation_reviews.values()
            ],
            "review_count": len(snapshot.design_fixation_reviews),
        },
        "artifacts": [item.model_dump(mode="json") for item in snapshot.artifacts.values()],
        "manufacturing_views": manufacturing_views(snapshot),
        "software_bill": [
            node.model_dump(mode="json")
            for node in snapshot.objects.values()
            if node.inclusion.software_release or str(node.kind) in {"software", "container_image"}
        ],
        "test_and_simulation": {
            "failure_modes": [
                {**item.model_dump(mode="json"), "rpn": item.rpn} for item in snapshot.failure_modes
            ],
            "human_scenarios": [item.model_dump(mode="json") for item in snapshot.human_scenarios],
            "test_plans": [item.model_dump(mode="json") for item in snapshot.test_plans.values()],
            "power_model": snapshot.power_model.model_dump(mode="json") if snapshot.power_model else None,
            "thermal_model": snapshot.thermal_model.model_dump(mode="json") if snapshot.thermal_model else None,
        },
        "commercial": {
            "offers": [item.model_dump(mode="json") for item in snapshot.ecommerce_offers],
        },
        "summary": {
            "object_count": len(snapshot.objects),
            "artifact_count": len(snapshot.artifacts),
            "annotation_count": len(snapshot.annotations),
            "design_fixation_review_count": len(snapshot.design_fixation_reviews),
            "kind_counts": dict(kind_counts),
            "process_counts": dict(process_counts),
        },
    }


def manufacturing_views(snapshot: ProjectSnapshot) -> dict[str, list[dict[str, Any]]]:
    views: dict[str, list[dict[str, Any]]] = {
        "engineering_bom": [],
        "print_job": [],
        "cnc_job": [],
        "purchase_order": [],
        "pcb_fabrication": [],
        "software_release": [],
        "packaging": [],
        "reference_only": [],
    }
    for node in snapshot.objects.values():
        row = {
            "uri": node.uri,
            "name": node.name,
            "kind": node.kind,
            "quantity": node.quantity,
            "manufacturing": node.manufacturing.model_dump(mode="json"),
            "parameters": {key: value.model_dump(mode="json") for key, value in node.parameters.items()},
        }
        if node.inclusion.physical_product:
            views["engineering_bom"].append(row)
        if node.inclusion.print_job:
            views["print_job"].append(row)
        if node.inclusion.cnc_job:
            views["cnc_job"].append(row)
        if node.inclusion.purchase_order:
            views["purchase_order"].append(row)
        if node.inclusion.pcb_fabrication:
            views["pcb_fabrication"].append(row)
        if node.inclusion.software_release:
            views["software_release"].append(row)
        if node.inclusion.ecommerce_package or str(node.kind) == "packaging":
            views["packaging"].append(row)
        if node.inclusion.reference_only:
            views["reference_only"].append(row)
    return views
