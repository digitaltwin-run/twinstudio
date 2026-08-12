from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from twinstudio.cad_regeneration import physical_component_height
from twinstudio.domain import (
    ChangeOperation,
    ChangeOperationKind,
    ChangePlan,
    ChangePlanLlmRequest,
    ChangePlanProposal,
    ImpactItem,
    InvalidLlmResponseArtifact,
    NaturalLanguageSource,
    ProjectSnapshot,
    RegionSelection,
)
from twinstudio.settings import Settings
from twinstudio.uri import is_within_scope, parse_poa_uri


@dataclass(slots=True)
class PlannerResult:
    plan: ChangePlan
    mode: str
    message: str


class ScopeViolation(ValueError):
    pass


class LlmInvalidResponse(ValueError):
    """A strict LLM response failed the proposal schema and must not be coerced."""

    def __init__(self, content: str, cause: Exception):
        self.artifact = InvalidLlmResponseArtifact.from_content(content, str(cause))
        self.response_sha256 = self.artifact.response_sha256
        self.validation_error = self.artifact.validation_error
        super().__init__("LLM response does not conform to ChangePlanProposal")


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
            except LlmInvalidResponse:
                raise
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

        schema = ChangePlanProposal.model_json_schema()
        selected_context = self._selected_context(selection, project)
        system = (
            "You are a product CAD change compiler. Return JSON only. Never emit code. "
            "Every operation target_uri MUST be one of the selected scope URIs or a semantic child of one. "
            "Do not change unselected objects. Prefer a local additive/cut/offset feature for a lasso/brush region. "
            "Use set_parameter only when the selection identifies a named parametric feature or the complete object. "
            "For a 2D/photo selection without a projection map, create an annotation/test or ask a question rather than "
            "inventing a 3D location. The result must validate against the supplied JSON Schema."
        )
        source = NaturalLanguageSource.from_text(
            prompt,
            language=_language_hint(prompt),
            provenance=f"ui-selection:{selection.uri}",
        )
        user_payload = ChangePlanLlmRequest(
            project_id=project.project_id,
            base_revision=project.revision,
            source=source,
            selection=selection,
            selected_context=selected_context,
            allowed_operations=list(ChangeOperationKind),
        )
        kwargs: dict[str, Any] = {
            "model": self.settings.litellm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_payload.model_dump_json()},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "change_plan_proposal", "strict": True, "schema": schema},
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
        raw_content = content if isinstance(content, str) else str(content)
        try:
            proposal = ChangePlanProposal.model_validate_json(raw_content)
        except Exception as exc:
            raise LlmInvalidResponse(raw_content, exc) from exc
        return ChangePlan(
            project_id=project.project_id,
            base_revision=project.revision,
            prompt=prompt,
            selection_uri=selection.uri,
            selected_scope_uris=selection.target_object_uris,
            operations=[
                ChangeOperation.model_validate(operation.model_dump(mode="json"))
                for operation in proposal.operations
            ],
            impact=proposal.impact,
            assumptions=proposal.assumptions,
            unresolved_questions=proposal.unresolved_questions,
            requires_approval=True,
            planner=f"litellm:{self.settings.litellm_model}",
            created_by=actor,
        )

    def _local_plan(
        self,
        prompt: str,
        selection: RegionSelection,
        project: ProjectSnapshot,
        actor: str,
    ) -> ChangePlan:
        lowered = prompt.lower()
        target = selection.target_object_uris[0]
        semantic_faces = [hit.semantic_face_uri for hit in selection.ray_hits if hit.semantic_face_uri]
        operations: list[ChangeOperation] = []
        assumptions: list[str] = []
        questions: list[str] = []
        impact: list[ImpactItem] = []

        relative_parameter = _relative_parameter_change(lowered, target, project)
        if relative_parameter is not None:
            parameter, previous_value, new_value, delta, unit = relative_parameter
            operations.append(
                ChangeOperation(
                    kind=ChangeOperationKind.SET_PARAMETER,
                    target_uri=target,
                    selector={
                        "parameter": parameter,
                        "scope": "selected_object",
                        "adjustment": "relative",
                    },
                    arguments={"parameter": parameter, "value": new_value, "unit": unit},
                    rationale=(
                        f"Explicit relative change detected: {parameter} {previous_value:g} {unit} "
                        f"{'+' if delta > 0 else '-'} {abs(delta):g} {unit} = {new_value:g} {unit}."
                    ),
                    confidence=0.96,
                    validation_steps=[
                        "Verify the resulting dimension remains positive and compatible with adjacent features.",
                        "Regenerate 2D drawings and 3D geometry before manufacturing.",
                    ],
                )
            )
            impact.append(
                ImpactItem(
                    uri=target,
                    impact="direct",
                    summary=f"Parameter {parameter} changes from {previous_value:g} to {new_value:g} {unit}.",
                )
            )
        else:
            absolute_parameter = _absolute_parameter_change(lowered, target, project)
            if absolute_parameter is not None:
                parameter, previous_value, new_value, unit = absolute_parameter
                operations.append(
                    ChangeOperation(
                        kind=ChangeOperationKind.SET_PARAMETER,
                        target_uri=target,
                        selector={
                            "parameter": parameter,
                            "scope": "selected_object",
                            "adjustment": "absolute",
                        },
                        arguments={"parameter": parameter, "value": new_value, "unit": unit},
                        rationale=(
                            f"Explicit target value detected: {parameter} changes from "
                            f"{previous_value:g} {unit} to {new_value:g} {unit}."
                        ),
                        confidence=0.97,
                        validation_steps=[
                            "Verify the target dimension remains compatible with adjacent features.",
                            "Regenerate 2D drawings and 3D geometry before manufacturing.",
                        ],
                    )
                )
                impact.append(
                    ImpactItem(
                        uri=target,
                        impact="direct",
                        summary=f"Parameter {parameter} changes from {previous_value:g} to {new_value:g} {unit}.",
                    )
                )

        thickness = None
        if _relative_direction(lowered) is None:
            thickness = _number_near(
                lowered,
                ("wall thickness", "grubość ścian", "grubosc scian", "thickness"),
            )
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
                existing = project.objects[object_uri].parameters.get(operation.arguments["parameter"])
                previous_parameter = existing.model_dump(mode="json") if existing is not None else None
                if previous_parameter is None and operation.arguments["parameter"] == "height":
                    physical_height = physical_component_height(project, object_uri)
                    if physical_height is not None:
                        previous_parameter = {
                            "value": physical_height,
                            "unit": "mm",
                            "status": "derived",
                            "source_uri": None,
                            "confidence": 1.0,
                            "notes": "Physical component height inferred from current CAD state.",
                        }
                parameter_patches.append(
                    {
                        "object_uri": object_uri,
                        "parameter": operation.arguments["parameter"],
                        "value": operation.arguments["value"],
                        "unit": operation.arguments.get("unit"),
                        "operation_id": operation.operation_id,
                        "previous_parameter": previous_parameter,
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


def _language_hint(text: str) -> str:
    normalized = _normalized_text(text)
    polish_tokens = (
        "ustaw",
        "zmniejsz",
        "zwieksz",
        "obniz",
        "podnies",
        "wysokosc",
        "szerokosc",
        "glebokosc",
        "grubosc",
        "otwor",
        "przesun",
    )
    return "pl" if any(re.search(rf"\b{token}\b", normalized) for token in polish_tokens) else "en"


_PARAMETER_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("wall_thickness", ("grubosc scian", "grubosc scianki", "wall thickness")),
    ("floor_thickness", ("grubosc dna", "grubosc podlogi", "floor thickness")),
    ("height", ("wysokosc", "height")),
    ("width", ("szerokosc", "width")),
    ("depth", ("glebokosc", "depth")),
)


def _normalized_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_marks = "".join(character for character in decomposed if not unicodedata.combining(character))
    # Unicode NFKD removes combining accents, but Polish ł is a distinct letter.
    return without_marks.translate(str.maketrans({"ł": "l"}))


def _relative_direction(text: str) -> int | None:
    normalized = _normalized_text(text)
    if re.search(r"\b(?:zmniejsz|zmniejszyc|obniz|skroc|reduce|decrease|lower)\b", normalized):
        return -1
    if re.search(r"\b(?:zwieksz|zwiekszyc|podnies|wydluz|increase|raise)\b", normalized):
        return 1
    return None


def _relative_parameter_change(
    text: str,
    target_uri: str,
    project: ProjectSnapshot,
) -> tuple[str, float, float, float, str] | None:
    direction = _relative_direction(text)
    node = project.objects.get(target_uri)
    if direction is None or node is None:
        return None
    normalized = _normalized_text(text)
    parameter = next(
        (
            name
            for name, aliases in _PARAMETER_ALIASES
            if name in node.parameters and any(alias in normalized for alias in aliases)
        ),
        None,
    )
    amount_match = re.search(r"\b(?:o|by)\s*(\d+(?:[.,]\d+)?)\s*(mm|cm)\b", normalized)
    if parameter is None and _implies_selected_height(normalized):
        parameter = "height"
    if parameter is None or amount_match is None:
        return None
    measurement = _parameter_measurement(project, target_uri, parameter)
    if measurement is None:
        return None
    previous_value, existing_unit = measurement
    if existing_unit != "mm":
        return None
    amount = float(amount_match.group(1).replace(",", "."))
    if amount_match.group(2) == "cm":
        amount *= 10
    delta = direction * amount
    new_value = round(previous_value + delta, 6)
    if amount <= 0 or new_value <= 0:
        return None
    return parameter, previous_value, new_value, delta, existing_unit


def _absolute_parameter_change(
    text: str,
    target_uri: str,
    project: ProjectSnapshot,
) -> tuple[str, float, float, str] | None:
    """Parse an explicit target such as ``wysokość do 21 mm`` for a selected object."""

    node = project.objects.get(target_uri)
    if node is None:
        return None
    normalized = _normalized_text(text)
    parameter = next(
        (
            name
            for name, aliases in _PARAMETER_ALIASES
            if name != "wall_thickness"
            and name in node.parameters
            and any(alias in normalized for alias in aliases)
        ),
        None,
    )
    target_match = re.search(
        r"\b(?:do|na|to|at)\s*(\d+(?:[.,]\d+)?)\s*(mm|cm)\b",
        normalized,
    )
    if parameter is None and _implies_selected_height(normalized):
        parameter = "height"
    if parameter is None or target_match is None:
        return None
    measurement = _parameter_measurement(project, target_uri, parameter)
    if measurement is None:
        return None
    previous_value, existing_unit = measurement
    if existing_unit != "mm":
        return None
    target_value = float(target_match.group(1).replace(",", "."))
    if target_match.group(2) == "cm":
        target_value *= 10
    target_value = round(target_value, 6)
    if target_value <= 0:
        return None
    return parameter, previous_value, target_value, existing_unit


def _implies_selected_height(normalized: str) -> bool:
    return bool(re.search(r"\b(?:obniz|podnies|lower|raise)\b", normalized))


def _parameter_measurement(
    project: ProjectSnapshot,
    target_uri: str,
    parameter: str,
) -> tuple[float, str] | None:
    node = project.objects.get(target_uri)
    if node is None:
        return None
    existing = node.parameters.get(parameter)
    if existing is not None:
        if isinstance(existing.value, bool) or not isinstance(existing.value, (int, float)):
            return None
        return float(existing.value), existing.unit or "mm"
    if parameter == "height":
        physical_height = physical_component_height(project, target_uri)
        if physical_height is not None:
            return physical_height, "mm"
    return None


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
