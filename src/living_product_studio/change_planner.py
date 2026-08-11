from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from living_product_studio.domain import (
    ChangeOperation,
    ChangeOperationKind,
    ChangePlan,
    ImpactItem,
    ObjectNode,
    ProjectSnapshot,
    RegionSelection,
)
from living_product_studio.settings import Settings
from living_product_studio.uri import is_within_scope, parse_poa_uri


@dataclass(slots=True)
class PlannerResult:
    plan: ChangePlan
    mode: str
    message: str


class ScopeViolation(ValueError):
    pass


class ChangePlanner:
    """Compile a natural-language request into a scoped declarative change plan.

    The planner never executes generated Python or CAD code. A plan consists only of
    allow-listed operations and POA targets. Every target must be equal to or below
    one of the selected scope URIs.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def plan(
        self,
        prompt: str,
        selection: RegionSelection,
        project: ProjectSnapshot,
        actor: str,
    ) -> PlannerResult:
        if self.settings.litellm_model:
            try:
                plan = self._litellm_plan(prompt, selection, project, actor)
                self.validate_scope(plan)
                return PlannerResult(plan, "litellm", "Structured plan produced by LiteLLM and scope-validated.")
            except Exception as exc:
                local = self._local_plan(prompt, selection, project, actor)
                return PlannerResult(local, "local-fallback", f"LiteLLM failed; local plan used: {exc}")
        return PlannerResult(
            self._local_plan(prompt, selection, project, actor),
            "local",
            "Deterministic local planner used because LITELLM_MODEL is empty.",
        )

    def _selected_context(self, selection: RegionSelection, project: ProjectSnapshot) -> list[dict[str, Any]]:
        context: list[dict[str, Any]] = []
        for uri in selection.target_object_uris:
            node = project.objects.get(uri)
            if node:
                context.append(
                    {
                        "uri": node.uri,
                        "name": node.name,
                        "kind": node.kind,
                        "parameters": {key: value.model_dump(mode="json") for key, value in node.parameters.items()},
                        "features": [feature.model_dump(mode="json") for feature in node.features],
                        "manufacturing": node.manufacturing.model_dump(mode="json"),
                    }
                )
        return context

    def _litellm_plan(
        self,
        prompt: str,
        selection: RegionSelection,
        project: ProjectSnapshot,
        actor: str,
    ) -> ChangePlan:
        from litellm import completion

        schema = ChangePlan.model_json_schema()
        selected_context = self._selected_context(selection, project)
        system = (
            "You are a product CAD change compiler. Return JSON only. Never emit code. "
            "Every operation target_uri MUST be one of the selected scope URIs or a semantic child of one. "
            "Do not change unselected objects. Prefer a local additive/cut/offset feature for a lasso/brush region. "
            "Use set_parameter only when the selection identifies a named parametric feature or the complete object. "
            "For a 2D/photo selection without a projection map, create an annotation/test or ask a question rather than "
            "inventing a 3D location. The result must validate against the supplied JSON Schema."
        )
        user_payload = {
            "project_id": project.project_id,
            "base_revision": project.revision,
            "request": prompt,
            "selection": selection.model_dump(mode="json"),
            "selected_context": selected_context,
            "allowed_operations": [item.value for item in ChangeOperationKind],
        }
        kwargs: dict[str, Any] = {
            "model": self.settings.litellm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "change_plan", "strict": True, "schema": schema},
            },
        }
        if self.settings.litellm_api_base:
            kwargs["api_base"] = self.settings.litellm_api_base
        if self.settings.litellm_api_key:
            kwargs["api_key"] = self.settings.litellm_api_key
        response = completion(**kwargs)
        content = response.choices[0].message.content
        if isinstance(content, list):
            content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        data = json.loads(content)
        data["project_id"] = project.project_id
        data["base_revision"] = project.revision
        data["prompt"] = prompt
        data["selection_uri"] = selection.uri
        data["selected_scope_uris"] = selection.target_object_uris
        data["created_by"] = actor
        data["planner"] = f"litellm:{self.settings.litellm_model}"
        return ChangePlan.model_validate(data)

    def _local_plan(
        self,
        prompt: str,
        selection: RegionSelection,
        project: ProjectSnapshot,
        actor: str,
    ) -> ChangePlan:
        lowered = prompt.lower()
        target = selection.target_object_uris[0]
        node = project.objects.get(target)
        semantic_faces = [hit.semantic_face_uri for hit in selection.ray_hits if hit.semantic_face_uri]
        operations: list[ChangeOperation] = []
        assumptions: list[str] = []
        questions: list[str] = []
        impact: list[ImpactItem] = []

        thickness = _number_near(lowered, ("wall thickness", "grubość ścian", "grubosc scian", "thickness"))
        if thickness is not None:
            if semantic_faces:
                operations.append(
                    ChangeOperation(
                        kind=ChangeOperationKind.ADD_FEATURE,
                        target_uri=target,
                        selector={
                            "region_uri": selection.uri,
                            "semantic_faces": semantic_faces,
                            "mode": "local_offset_or_rebuild",
                        },
                        arguments={"feature_type": "local_wall_thickness_patch", "thickness_mm": thickness},
                        rationale="The request concerns a selected face region, so the change is local rather than global.",
                        confidence=0.72,
                        validation_steps=[
                            "Resolve selected mesh faces to persistent B-Rep/feature tags.",
                            "Regenerate the part and verify no adjacent unselected wall changed.",
                            "Run minimum-thickness and collision checks.",
                        ],
                    )
                )
                questions.append(
                    "Confirm whether the boundary should be blended, chamfered, or left as a sharp local transition."
                )
            else:
                operations.append(
                    ChangeOperation(
                        kind=ChangeOperationKind.SET_PARAMETER,
                        target_uri=target,
                        selector={"parameter": "wall_thickness", "scope": "selected_object"},
                        arguments={"parameter": "wall_thickness", "value": thickness, "unit": "mm"},
                        rationale="Explicit wall-thickness value detected in the natural-language request.",
                        confidence=0.9,
                        validation_steps=["Regenerate 2D drawings and 3D geometry.", "Check cavity and mating clearances."],
                    )
                )
            impact.append(ImpactItem(uri=target, impact="direct", summary="Wall geometry changes in selected scope."))

        diameter = _diameter(lowered)
        if any(token in lowered for token in ("hole", "otwór", "otwor")):
            operations.append(
                ChangeOperation(
                    kind=ChangeOperationKind.BOOLEAN_CUT,
                    target_uri=target,
                    selector={"region_uri": selection.uri, "ray_hits": len(selection.ray_hits)},
                    arguments={
                        "feature_type": "hole",
                        "diameter_mm": diameter or 3.0,
                        "depth_mode": "through_selected_wall",
                    },
                    rationale="A hole was requested inside the selected region.",
                    confidence=0.78 if diameter else 0.52,
                    validation_steps=["Check edge distance.", "Check collision with internal components."],
                )
            )
            if diameter is None:
                assumptions.append("No diameter was provided; 3.0 mm is a provisional value requiring approval.")
            impact.append(ImpactItem(uri=target, impact="manufacturing", summary="New cut affects print/CNC toolpath."))

        angle = _angle(lowered)
        if any(token in lowered for token in ("chamfer", "faz", "ścię", "scie")):
            operations.append(
                ChangeOperation(
                    kind=ChangeOperationKind.ADD_FEATURE,
                    target_uri=target,
                    selector={"region_uri": selection.uri, "boundary": "selected_region_boundary"},
                    arguments={"feature_type": "chamfer", "angle_deg": angle or 45.0},
                    rationale="A chamfer was requested on the selected boundary.",
                    confidence=0.8 if angle else 0.65,
                    validation_steps=["Verify print overhang angle.", "Verify hinge motion if the target is near the hinge."],
                )
            )

        if any(token in lowered for token in ("move", "shift", "przesuń", "przesun")):
            distance = _first_number(lowered) or 1.0
            operations.append(
                ChangeOperation(
                    kind=ChangeOperationKind.TRANSFORM_FEATURE,
                    target_uri=target,
                    selector={"region_uri": selection.uri},
                    arguments={"distance_mm": distance, "direction": "requires_user_gizmo_or_axis_confirmation"},
                    rationale="A local move was requested, but direction must come from a 3D gizmo or explicit axis.",
                    confidence=0.45,
                    validation_steps=["Confirm axis/direction in the viewer before applying."],
                )
            )
            questions.append("Select or state the movement direction/axis.")

        if selection.source_view in {"2d", "photo"} and not selection.projection_entity_ids:
            questions.append(
                "The marked 2D/photo region has no projection/calibration mapping to 3D; approval must define its 3D plane."
            )

        if not operations:
            operations.append(
                ChangeOperation(
                    kind=ChangeOperationKind.ADD_ANNOTATION,
                    target_uri=target,
                    selector={"region_uri": selection.uri},
                    arguments={"text": prompt},
                    rationale="The local parser could not safely infer a geometry operation; the request is preserved as a scoped note.",
                    confidence=1.0,
                    validation_steps=["Review the annotation and choose a supported operation."],
                )
            )
            questions.append("Choose a concrete operation: dimension, hole/cut, pad, chamfer, move, suppress, or replacement.")

        plan = ChangePlan(
            project_id=project.project_id,
            base_revision=project.revision,
            prompt=prompt,
            selection_uri=selection.uri,
            selected_scope_uris=selection.target_object_uris,
            operations=operations,
            impact=impact,
            assumptions=assumptions,
            unresolved_questions=questions,
            requires_approval=True,
            planner="local-rule-compiler",
            created_by=actor,
        )
        self.validate_scope(plan)
        return plan

    @staticmethod
    def validate_scope(plan: ChangePlan) -> None:
        if not plan.selected_scope_uris:
            raise ScopeViolation("A change plan requires selected scope URIs")
        for operation in plan.operations:
            if not is_within_scope(operation.target_uri, plan.selected_scope_uris, ignore_revision=True):
                raise ScopeViolation(
                    f"Operation {operation.operation_id} targets {operation.target_uri}, outside selected scope"
                )

    @staticmethod
    def compile_apply_payload(plan: ChangePlan, project: ProjectSnapshot) -> dict[str, Any]:
        """Compile immediately safe operations into an event payload.

        Only scalar parameter patches are applied in the core MVP. Geometry operations
        remain deferred for the CAD adapter, which must resolve selection maps to stable
        B-Rep/feature identifiers before modifying a solid.
        """

        parameter_patches: list[dict[str, Any]] = []
        deferred: list[dict[str, Any]] = []
        for operation in plan.operations:
            if operation.kind == ChangeOperationKind.SET_PARAMETER:
                object_uri = _owning_object_uri(operation.target_uri, project)
                parameter_patches.append(
                    {
                        "object_uri": object_uri,
                        "parameter": operation.arguments["parameter"],
                        "value": operation.arguments["value"],
                        "unit": operation.arguments.get("unit"),
                        "operation_id": operation.operation_id,
                    }
                )
            elif operation.kind == ChangeOperationKind.ADD_ANNOTATION:
                deferred.append(operation.model_dump(mode="json"))
            else:
                deferred.append(operation.model_dump(mode="json"))
        return {
            "plan_id": plan.plan_id,
            "base_revision": plan.base_revision,
            "new_revision": f"rev-{project.stream_version + 2}",
            "parameter_patches": parameter_patches,
            "deferred_operations": deferred,
            "scope_uris": plan.selected_scope_uris,
        }


def _owning_object_uri(target_uri: str, project: ProjectSnapshot) -> str:
    if target_uri in project.objects:
        return target_uri
    parsed = parse_poa_uri(target_uri)
    candidates: list[tuple[int, str]] = []
    for object_uri in project.objects:
        object_ref = parse_poa_uri(object_uri)
        if object_ref.tenant != parsed.tenant or object_ref.project != parsed.project:
            continue
        if parsed.segments[: len(object_ref.segments)] == object_ref.segments:
            candidates.append((len(object_ref.segments), object_uri))
    if candidates:
        return max(candidates)[1]
    raise ValueError(f"No owning object found for {target_uri}")


def _first_number(text: str) -> float | None:
    match = re.search(r"(?<![\w.])(\d+(?:[.,]\d+)?)", text)
    return float(match.group(1).replace(",", ".")) if match else None


def _number_near(text: str, terms: tuple[str, ...]) -> float | None:
    for term in terms:
        index = text.find(term)
        if index >= 0:
            window = text[max(0, index - 30) : index + len(term) + 40]
            value = _first_number(window)
            if value is not None:
                return value
    return None


def _diameter(text: str) -> float | None:
    patterns = [r"(?:ø|⌀|diameter|średnic\w*|srednic\w*)\s*[:=]?\s*(\d+(?:[.,]\d+)?)"]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1).replace(",", "."))
    return None


def _angle(text: str) -> float | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:°|deg|degree|stopni)", text)
    return float(match.group(1).replace(",", ".")) if match else None
