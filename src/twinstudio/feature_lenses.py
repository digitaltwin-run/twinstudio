from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from twinstudio.domain import (
    DesignAlternative,
    DesignFixationReview,
    DesignIdeaSource,
    FeatureLens,
    FeatureLensCatalog,
    FeatureLensObservation,
    LensObservationStatus,
    ObjectNode,
    ProjectSnapshot,
)
from twinstudio.settings import Settings


@lru_cache(maxsize=1)
def load_feature_lens_catalog() -> FeatureLensCatalog:
    """Load the source-grounded feature-lens catalog bundled with TwinStudio."""

    source = files("twinstudio").joinpath("data/feature_lenses.yaml")
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    return FeatureLensCatalog.model_validate(payload)


class _IdeaPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=160)
    lens_ids: list[str] = Field(min_length=1, max_length=4)
    summary: str = Field(min_length=10, max_length=1200)
    proposed_changes: list[str] = Field(default_factory=list, max_length=8)
    expected_benefits: list[str] = Field(default_factory=list, max_length=8)
    risks: list[str] = Field(default_factory=list, max_length=8)
    validation_steps: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(default=0.55, ge=0.0, le=1.0)


class _IdeaBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ideas: list[_IdeaPayload] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True, slots=True)
class ScanResult:
    review: DesignFixationReview
    mode: str
    message: str


class FeatureLensEngine:
    """Detect design-fixation blind spots without directly mutating product geometry.

    The engine first creates a deterministic evidence scan. When LiteLLM is configured,
    it can ask a model for additional *reviewable* alternatives constrained to the
    selected target and lens IDs. Generated ideas never execute code or CAD operations.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.catalog = load_feature_lens_catalog()

    def scan(
        self,
        snapshot: ProjectSnapshot,
        *,
        target_uri: str,
        challenge: str,
        actor: str,
        lens_ids: list[str] | None = None,
        max_alternatives: int = 8,
        use_llm: bool = True,
    ) -> ScanResult:
        if target_uri not in snapshot.objects:
            raise ValueError("target_uri must identify an object in the project snapshot")
        if not 1 <= max_alternatives <= 20:
            raise ValueError("max_alternatives must be between 1 and 20")

        selected_lenses = self._select_lenses(lens_ids)
        target = snapshot.objects[target_uri]
        observations = [self._observe(lens, target, snapshot) for lens in selected_lenses]
        applicable = [item for item in observations if item.status != LensObservationStatus.NOT_APPLICABLE]
        observed = [item for item in applicable if item.status == LensObservationStatus.OBSERVED]
        underexplored = [
            item.lens_id
            for item in applicable
            if item.status in {LensObservationStatus.UNKNOWN, LensObservationStatus.PARTLY_OBSERVED}
        ]

        local_ideas = self._local_alternatives(
            target,
            selected_lenses,
            observations,
            challenge=challenge,
            limit=max_alternatives,
        )
        mode = "local"
        message = "Deterministic feature-lens scan completed."
        alternatives = local_ideas
        if use_llm and self.settings.litellm_model:
            llm_ideas, llm_message = self._llm_alternatives(
                target=target,
                challenge=challenge,
                lenses=selected_lenses,
                observations=observations,
                limit=max_alternatives,
            )
            if llm_ideas:
                alternatives = llm_ideas[:max_alternatives]
                mode = "litellm"
                message = llm_message
            else:
                message = f"{message} LiteLLM fallback: {llm_message}"

        warnings = list(self.catalog.source_notes)
        if any(lens.source_status == "duplicate_label" for lens in selected_lenses):
            warnings.append(
                "The supplied source pages contain two visible rows named External Relations; "
                "TwinStudio keeps both as separate review passes."
            )
        if any(not lens.enabled for lens in self.catalog.lenses):
            warnings.append(
                "One disabled catalog slot records the unresolved gap between the declared total of 50 "
                "and the 49 visible source rows; no missing lens content was invented."
            )

        review = DesignFixationReview(
            uri=(
                f"poa://{snapshot.tenant}/{snapshot.project_id}@{snapshot.revision}"
                f"/design-fixation-review/{_slug(target.name)}"
            ),
            project_id=snapshot.project_id,
            base_revision=snapshot.revision,
            target_uri=target_uri,
            challenge=challenge.strip(),
            catalog_version=self.catalog.catalog_version,
            selected_lens_ids=[lens.id for lens in selected_lenses],
            observations=observations,
            coverage_ratio=(len(observed) / len(applicable)) if applicable else 0.0,
            observed_count=len(observed),
            applicable_count=len(applicable),
            underexplored_lens_ids=underexplored,
            alternatives=alternatives,
            warnings=_dedupe(warnings),
            planner=("litellm-feature-lens-engine" if mode == "litellm" else "local-feature-lens-engine"),
            created_by=actor,
        )
        review.uri = f"{review.uri}-{review.review_id[:8]}"
        return ScanResult(review=review, mode=mode, message=message)

    def _select_lenses(self, requested: list[str] | None) -> list[FeatureLens]:
        enabled = {lens.id: lens for lens in self.catalog.lenses if lens.enabled}
        if not requested:
            return sorted(enabled.values(), key=lambda item: item.order)
        unknown = sorted(set(requested) - set(enabled))
        if unknown:
            raise ValueError(f"Unknown or disabled feature lens IDs: {', '.join(unknown)}")
        return [enabled[lens_id] for lens_id in requested]

    def _observe(
        self,
        lens: FeatureLens,
        target: ObjectNode,
        snapshot: ProjectSnapshot,
    ) -> FeatureLensObservation:
        direct, indirect, evidence = _evidence_for_lens(lens.id, target, snapshot)
        if lens.id in {"taste", "aroma", "radioactive_characteristics"} and not direct and not indirect:
            return FeatureLensObservation(
                lens_id=lens.id,
                status=LensObservationStatus.NOT_APPLICABLE,
                note="No project evidence currently makes this specialist lens applicable; review manually if the use context changes.",
                evidence_uris=[],
                confidence=0.7,
            )
        if direct:
            status = LensObservationStatus.OBSERVED
            confidence = min(0.98, 0.72 + 0.06 * len(direct))
            note = "Explicit project evidence addresses this lens: " + "; ".join(direct[:3])
        elif indirect:
            status = LensObservationStatus.PARTLY_OBSERVED
            confidence = min(0.82, 0.48 + 0.06 * len(indirect))
            note = "The lens is only indirectly represented: " + "; ".join(indirect[:3])
        else:
            status = LensObservationStatus.UNKNOWN
            confidence = 0.25
            note = "No explicit evidence was found in the selected object or current project snapshot."
        return FeatureLensObservation(
            lens_id=lens.id,
            status=status,
            note=note,
            evidence_uris=_dedupe(evidence)[:12],
            confidence=confidence,
        )

    def _local_alternatives(
        self,
        target: ObjectNode,
        lenses: list[FeatureLens],
        observations: list[FeatureLensObservation],
        *,
        challenge: str,
        limit: int,
    ) -> list[DesignAlternative]:
        observation_by_id = {item.lens_id: item for item in observations}
        priority = sorted(
            lenses,
            key=lambda lens: (
                _status_rank(observation_by_id[lens.id].status),
                lens.order,
            ),
        )
        result: list[DesignAlternative] = []
        context = challenge.strip() or "Improve the product without assuming the current solution is fixed."
        for lens in priority:
            observation = observation_by_id[lens.id]
            if observation.status == LensObservationStatus.NOT_APPLICABLE:
                continue
            prompt = lens.prompts[0] if lens.prompts else lens.summary
            result.append(
                DesignAlternative(
                    target_uri=target.uri,
                    title=f"Reframe {target.name} through {lens.name}",
                    lens_ids=[lens.id],
                    summary=(
                        f"Use the {lens.name} lens to challenge the current design. "
                        f"Project challenge: {context} Review question: {prompt}"
                    ),
                    proposed_changes=[
                        f"Create at least two variants that answer: {prompt}",
                        "Keep the proposal scoped to the selected object until interfaces and dependencies are reviewed.",
                    ],
                    expected_benefits=[
                        "Makes an under-documented design assumption explicit.",
                        "Creates alternatives before committing to a CAD change.",
                    ],
                    risks=[
                        "A conceptual alternative may conflict with interfaces, manufacturing constraints, or verified requirements."
                    ],
                    validation_steps=[
                        "Compare the variant against approved requirements and adjacent object interfaces.",
                        "Record evidence before converting the idea into a scoped change plan.",
                    ],
                    source=DesignIdeaSource.LOCAL,
                    confidence=0.58 if observation.status == LensObservationStatus.UNKNOWN else 0.64,
                )
            )
            if len(result) >= limit:
                break
        return result

    def _llm_alternatives(
        self,
        *,
        target: ObjectNode,
        challenge: str,
        lenses: list[FeatureLens],
        observations: list[FeatureLensObservation],
        limit: int,
    ) -> tuple[list[DesignAlternative], str]:
        try:
            from litellm import completion
        except Exception as exc:  # pragma: no cover - optional dependency
            return [], f"LiteLLM is not importable: {exc}"

        allowed = {lens.id for lens in lenses}
        compact_lenses = [
            {
                "id": lens.id,
                "name": lens.name,
                "summary": lens.summary,
                "prompts": lens.prompts,
                "status": next(item.status for item in observations if item.lens_id == lens.id),
            }
            for lens in lenses
        ]
        system = (
            "You are TwinStudio's design-fixation reviewer. Generate diverse, reviewable product-design "
            "alternatives. Do not output code, commands, or direct CAD operations. Use only the supplied "
            "lens IDs and keep every idea scoped to the selected target. Return JSON matching the schema."
        )
        user = json.dumps(
            {
                "target": target.model_dump(mode="json"),
                "challenge": challenge,
                "lenses": compact_lenses,
                "maximum_ideas": limit,
            },
            ensure_ascii=False,
        )
        kwargs: dict[str, Any] = {
            "model": self.settings.litellm_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.55,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "twinstudio_design_alternatives",
                    "strict": True,
                    "schema": _IdeaBatch.model_json_schema(),
                },
            },
        }
        if self.settings.litellm_api_base:
            kwargs["api_base"] = self.settings.litellm_api_base
        if self.settings.litellm_api_key:
            kwargs["api_key"] = self.settings.litellm_api_key
        try:
            response = completion(**kwargs)
            content = response.choices[0].message.content
            payload = _IdeaBatch.model_validate_json(content)
        except Exception as strict_exc:  # pragma: no cover - provider-dependent
            try:
                kwargs["response_format"] = {"type": "json_object"}
                response = completion(**kwargs)
                content = response.choices[0].message.content
                payload = _IdeaBatch.model_validate_json(content)
            except (Exception, ValidationError) as fallback_exc:
                return [], f"structured output failed ({strict_exc}); JSON fallback failed ({fallback_exc})"

        ideas: list[DesignAlternative] = []
        for item in payload.ideas:
            if not item.lens_ids or not set(item.lens_ids).issubset(allowed):
                continue
            ideas.append(
                DesignAlternative(
                    target_uri=target.uri,
                    title=item.title,
                    lens_ids=item.lens_ids,
                    summary=item.summary,
                    proposed_changes=item.proposed_changes,
                    expected_benefits=item.expected_benefits,
                    risks=item.risks,
                    validation_steps=item.validation_steps,
                    source=DesignIdeaSource.LITELLM,
                    confidence=item.confidence,
                )
            )
        return ideas, f"LiteLLM generated {len(ideas)} validated alternatives."


_DIRECT_SIGNALS: dict[str, tuple[str, ...]] = {
    "color": ("color", "colour", "ral", "pigment"),
    "mass": ("mass", "density", "grams", "kg"),
    "weight": ("weight", "load", "payload"),
    "symmetry": ("symmetry", "symmetric", "mirrored"),
    "texture": ("texture", "rough", "smooth", "ribbed", "knurl", "finish"),
    "taste": ("food", "oral", "mouth", "taste"),
    "aroma": ("odor", "odour", "aroma", "smell", "off-gassing"),
    "optical_characteristics": ("optical", "transparent", "camera", "light", "lens", "reflect"),
    "acoustic_characteristics": ("acoustic", "sound", "noise", "resonance", "speaker"),
    "chemical_characteristics": ("chemical", "corrosion", "cleaning", "solvent", "uv"),
    "electrical_characteristics": ("voltage", "current", "resistance", "ground", "esd", "electrical", "usb"),
    "magnetic_characteristics": ("magnet", "magnetic", "polarity"),
    "radioactive_characteristics": ("radiation", "radioactive", "decay"),
    "fluid_characteristics": ("fluid", "airflow", "vent", "water", "drain", "pressure", "fan"),
    "side_effects": ("side effect", "unintended", "nuisance", "hazard"),
    "synonyms_by_use": ("alternative", "substitute", "same use", "benchmark"),
    "equipmental_partners": ("tool", "accessory", "partner", "fixture", "cable", "charger"),
    "place_where": ("location", "indoor", "outdoor", "desk", "wall", "vehicle"),
    "occasion_when": ("installation", "normal use", "emergency", "cleaning", "transport"),
    "energy_types": ("energy", "power", "thermal", "electrical", "mechanical"),
    "force_types": ("gravity", "centrifugal", "contact force", "force"),
    "proximity_in_space": ("clearance", "distance", "offset", "spacing", "near"),
    "orientation_in_space": ("orientation", "upright", "vertical", "horizontal", "mount"),
    "time_temporal_relations": ("duration", "cycle", "latency", "interval", "time"),
    "motion": ("motion", "rotate", "hinge", "open", "movement"),
    "permanence_transience": ("service life", "replace", "disposable", "repair", "upgrade"),
    "perspective_of_human_user": ("view", "visible", "operator", "installer", "customer"),
    "environmental_conditions": ("humidity", "temperature", "weather", "dust", "vibration", "ip"),
    "emotional_response": ("friendly", "trust", "feel", "emotion", "appearance"),
    "causal_relations": ("cause", "effect", "because", "failure mode"),
    "superordinate": ("product class", "system", "appliance", "device"),
    "subordinates": ("variant", "version", "sku", "specialized"),
    "external_relations_primary": ("environment", "interface", "external", "adjacent"),
    "external_relations_secondary": ("environment", "interface", "external", "adjacent"),
    "aesthetics": ("aesthetic", "appearance", "visible surface", "beautiful", "quality"),
}


def _evidence_for_lens(
    lens_id: str,
    target: ObjectNode,
    snapshot: ProjectSnapshot,
) -> tuple[list[str], list[str], list[str]]:
    direct: list[str] = []
    indirect: list[str] = []
    evidence: list[str] = []
    children = [node for node in snapshot.objects.values() if node.parent_uri == target.uri]
    target_context = _node_text(target)
    project_context = " ".join(
        [snapshot.name, snapshot.description]
        + [requirement.statement for requirement in snapshot.requirements.values()]
        + [failure.failure + " " + failure.effect + " " + failure.cause for failure in snapshot.failure_modes]
        + [scenario.name + " " + scenario.actor + " " + " ".join(step.instruction for step in scenario.steps) for scenario in snapshot.human_scenarios]
    ).lower()

    def add_direct(message: str, *uris: str) -> None:
        direct.append(message)
        evidence.extend(uri for uri in uris if uri)

    def add_indirect(message: str, *uris: str) -> None:
        indirect.append(message)
        evidence.extend(uri for uri in uris if uri)

    parameters = target.parameters
    features = target.features
    manufacturing = target.manufacturing

    if lens_id == "parts":
        if children:
            add_direct(f"{len(children)} child objects are explicitly modeled", target.uri, *(n.uri for n in children))
        if features:
            add_direct(f"{len(features)} CAD/product features are identified", target.uri)
    elif lens_id == "material":
        if manufacturing.material:
            add_direct(f"material is {manufacturing.material}", target.uri)
    elif lens_id == "shape":
        if features:
            add_direct("named geometric/product features describe form", target.uri)
        if any(key in parameters for key in ("width", "depth", "height", "diameter", "radius")):
            add_indirect("dimensional parameters imply a defined shape", target.uri)
    elif lens_id == "size":
        dimensional = [key for key, value in parameters.items() if value.unit in {"mm", "cm", "m", "in"}]
        if dimensional:
            add_direct("dimensional parameters: " + ", ".join(dimensional[:8]), target.uri)
    elif lens_id == "state_of_matter":
        if manufacturing.material:
            add_indirect("a physical material is declared but state behavior is not explicitly analyzed", target.uri)
    elif lens_id == "connectivity_among_parts":
        if target.parent_uri or children:
            add_direct("assembly parent/child connectivity is modeled", target.uri, target.parent_uri or "")
        if any(_contains(_feature_text(item), ("hinge", "joint", "fastener", "boss", "standoff")) for item in features):
            add_direct("connection features are represented", target.uri)
    elif lens_id == "spatial_relations_among_parts":
        keys = [key for key in parameters if any(token in key.lower() for token in ("offset", "spacing", "clearance", "position"))]
        if keys:
            add_direct("spatial parameters: " + ", ".join(keys[:8]), target.uri)
        elif target.parent_uri or children:
            add_indirect("hierarchy exists but relative spatial relations are not fully specified", target.uri)
    elif lens_id in {"mass", "weight"}:
        keys = [key for key in parameters if lens_id in key.lower() or "density" in key.lower() or "load" in key.lower()]
        if keys:
            add_direct("relevant parameters: " + ", ".join(keys), target.uri)
        elif manufacturing.material:
            add_indirect("material is known, but mass/weight is not explicitly calculated", target.uri)
    elif lens_id == "number":
        if target.quantity != 1 or children or features:
            add_direct(
                f"quantity={target.quantity}, child_count={len(children)}, feature_count={len(features)}",
                target.uri,
            )
    elif lens_id == "variety_homogeneity":
        materials = {node.manufacturing.material for node in [target, *children] if node.manufacturing.material}
        if len(materials) > 1:
            add_direct("multiple materials occur in the target subtree", target.uri, *(n.uri for n in children))
        elif materials:
            add_indirect("the target subtree appears materially homogeneous", target.uri)
    elif lens_id == "inside_outside":
        if _contains(target_context, ("enclosure", "shell", "inside", "outside", "interior", "lid", "base")):
            add_direct("the object defines an internal/external boundary", target.uri)
    elif lens_id == "thermal_characteristics":
        thermal_uri = _project_model_uri(snapshot, "thermal")
        if snapshot.thermal_model and any(node.uri == target.uri for node in snapshot.thermal_model.nodes):
            add_direct("the target has a thermal-model node", target.uri, thermal_uri)
        elif snapshot.thermal_model:
            add_indirect("a project thermal model exists but does not directly reference this target", thermal_uri)
    elif lens_id == "force_characteristics":
        if any(_contains(_feature_text(item), ("hinge", "snap", "latch", "fastener", "wall", "boss")) for item in features):
            add_indirect("load-bearing or moving features exist", target.uri)
        if any(target.uri == item.target_uri for item in snapshot.failure_modes):
            add_direct("failure modes explicitly address this object", target.uri)
    elif lens_id == "durability_characteristics":
        failures = [item for item in snapshot.failure_modes if item.target_uri == target.uri]
        if failures:
            add_direct(f"{len(failures)} failure modes address durability", target.uri, *(item.uri for item in failures))
        elif manufacturing.material:
            add_indirect("material and process are declared, but durability evidence is limited", target.uri)
    elif lens_id == "human_use":
        scenarios = [
            scenario
            for scenario in snapshot.human_scenarios
            if any(step.target_uri == target.uri for step in [*scenario.steps, *scenario.recovery_steps])
        ]
        if scenarios:
            add_direct(f"{len(scenarios)} human-use scenarios reference the target", target.uri, *(s.uri for s in scenarios))
        elif snapshot.human_scenarios:
            add_indirect("human-use scenarios exist at project level", *(s.uri for s in snapshot.human_scenarios))
    elif lens_id == "causal_relations":
        failures = [item for item in snapshot.failure_modes if item.target_uri == target.uri]
        if failures:
            add_direct("FMEA cause/effect chains reference the target", target.uri, *(item.uri for item in failures))
    elif lens_id == "energy_types":
        if snapshot.power_model:
            add_direct("a project power model represents energy flow", _project_model_uri(snapshot, "power"))
        if snapshot.thermal_model:
            add_direct("a project thermal model represents heat flow", _project_model_uri(snapshot, "thermal"))
    elif lens_id == "time_temporal_relations":
        if snapshot.thermal_model:
            add_indirect("the thermal model includes time-dependent behavior", _project_model_uri(snapshot, "thermal"))
        if snapshot.test_plans:
            add_indirect("test plans may contain sequences and durations", *(snapshot.test_plans.keys()))
    elif lens_id == "permanence_transience":
        if manufacturing.make_buy or manufacturing.process:
            add_indirect("make/buy and process are specified, but service-life intent may remain implicit", target.uri)
    elif lens_id in {"superordinate", "subordinates"}:
        if target.parent_uri:
            add_direct("product hierarchy supplies a broader classification", target.uri, target.parent_uri)
        if children:
            add_direct("child objects provide more specific subordinate forms", target.uri, *(n.uri for n in children))
    elif lens_id in {"external_relations_primary", "external_relations_secondary", "equipmental_partners"}:
        if target.parent_uri or target.artifact_uris:
            add_indirect("project interfaces are represented through hierarchy or linked artifacts", target.uri)
        if children:
            add_indirect("adjacent child objects create external relations", *(n.uri for n in children))
    elif lens_id == "environmental_conditions":
        requirements = [item for item in snapshot.requirements.values() if target.uri in item.target_uris]
        if any(_contains(item.statement.lower(), _DIRECT_SIGNALS[lens_id]) for item in requirements):
            add_direct("environmental requirements reference the target", target.uri, *(i.uri for i in requirements))
    elif lens_id == "orientation_in_space":
        if any(_contains(_feature_text(item), ("hinge", "mount", "orientation")) for item in features):
            add_indirect("mounting or hinge features imply orientation constraints", target.uri)
    elif lens_id == "motion":
        if any(_contains(_feature_text(item), ("hinge", "rotate", "slide", "motion")) for item in features):
            add_direct("moving features are modeled", target.uri)
    elif lens_id == "aesthetics":
        if manufacturing.finish or _contains(target_context, _DIRECT_SIGNALS[lens_id]):
            add_direct("finish or visible-surface quality is declared", target.uri)
    elif lens_id == "perspective_of_human_user":
        if target.artifact_uris:
            add_indirect("linked visual artifacts provide user viewpoints", target.uri, *target.artifact_uris)
    elif lens_id == "emotional_response":
        if manufacturing.finish or target.tags:
            add_indirect("finish/tags may encode intended perception, but no user evidence is recorded", target.uri)

    signals = _DIRECT_SIGNALS.get(lens_id, ())
    if signals:
        target_matches = [signal for signal in signals if signal in target_context]
        project_matches = [signal for signal in signals if signal in project_context]
        if target_matches and not direct:
            add_direct("target text contains: " + ", ".join(target_matches[:5]), target.uri)
        elif project_matches and not direct and not indirect:
            add_indirect("project context contains: " + ", ".join(project_matches[:5]), target.uri)

    return _dedupe(direct), _dedupe(indirect), _dedupe(evidence)


def _project_model_uri(snapshot: ProjectSnapshot, name: str) -> str:
    return f"poa://{snapshot.tenant}/{snapshot.project_id}@{snapshot.revision}/simulation-model/{name}"


def _node_text(node: ObjectNode) -> str:
    values: list[str] = [
        node.name,
        node.description,
        str(node.kind),
        node.manufacturing.material or "",
        node.manufacturing.finish or "",
        node.manufacturing.notes,
        " ".join(node.tags),
        json.dumps(node.metadata, ensure_ascii=False, default=str),
    ]
    values.extend(node.parameters.keys())
    values.extend(str(value.value) for value in node.parameters.values())
    values.extend(_feature_text(feature) for feature in node.features)
    return " ".join(values).lower()


def _feature_text(feature: Any) -> str:
    return " ".join(
        [
            getattr(feature, "name", ""),
            getattr(feature, "feature_type", ""),
            getattr(feature, "notes", ""),
            json.dumps(getattr(feature, "parameters", {}), ensure_ascii=False, default=str),
        ]
    ).lower()


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _status_rank(status: LensObservationStatus) -> int:
    return {
        LensObservationStatus.UNKNOWN: 0,
        LensObservationStatus.PARTLY_OBSERVED: 1,
        LensObservationStatus.OBSERVED: 2,
        LensObservationStatus.NOT_APPLICABLE: 3,
    }[status]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "target"


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))
