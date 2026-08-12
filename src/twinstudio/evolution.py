from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any, Iterable

import yaml
from pydantic import BaseModel, ConfigDict, Field

from twinstudio.domain import (
    ChangeOperation,
    ChangeOperationKind,
    ChangePlan,
    ImpactItem,
    LifecycleStage,
    ProjectSnapshot,
)
from twinstudio.evolution_models import (
    ActionRelation,
    CandidateEvaluation,
    CandidateStatus,
    DslDiagnostic,
    DslSeverity,
    EvaluationDimension,
    EvolutionCandidate,
    EvolutionCatalog,
    EvolutionGraph,
    EvolutionGraphEdge,
    EvolutionGraphNode,
    EvolutionMethod,
    EvolutionOperatorSpec,
    EvolutionPhase,
    EvolutionProgramSpec,
    EvolutionResource,
    EvolutionRun,
    EvolutionRunStatus,
    EvolutionStageRecord,
    GoalVariant,
    LifecycleBlueprint,
    LifecycleStageDefinition,
    LifecycleTransition,
    MutationOperatorKind,
    ResourceKind,
    StageRunStatus,
    TwinDslDocument,
)
from twinstudio.feature_lenses import load_feature_lens_catalog
from twinstudio.settings import Settings

_POLISH_VERB_ALIASES = {
    "popraw": "improve",
    "poprawić": "improve",
    "ulepsz": "improve",
    "ulepszyć": "improve",
    "zmniejsz": "reduce",
    "zmniejszyć": "reduce",
    "zwiększ": "increase",
    "zwiększyć": "increase",
    "połącz": "connect",
    "połączyć": "connect",
    "zamocuj": "mount",
    "zamocować": "mount",
    "otwórz": "open",
    "otworzyć": "open",
    "zamknij": "close",
    "zamknąć": "close",
    "chłodź": "cool",
    "schłódź": "cool",
    "uszczelnij": "seal",
    "przesuń": "move",
    "oddziel": "separate",
    "sprawdź": "inspect",
    "utrzymaj": "maintain",
    "zapobiegaj": "prevent",
    "zabezpiecz": "protect",
    "wspieraj": "support",
    "wyprodukuj": "manufacture",
    "uprość": "simplify",
    "obserwuj": "observe",
}


_DEFAULT_STAGE_PURPOSES: dict[LifecycleStage, str] = {
    LifecycleStage.OPPORTUNITY: "Identify a meaningful opportunity and affected stakeholders.",
    LifecycleStage.DISCOVERY: "Collect context, alternatives, existing solutions and constraints.",
    LifecycleStage.EVIDENCE: "Capture source material, measurements, claims and uncertainty.",
    LifecycleStage.PROBLEM_FRAMING: "Separate the desired outcome from the first wording or mechanism.",
    LifecycleStage.REQUIREMENTS: "Define verifiable needs, limits and interfaces.",
    LifecycleStage.CONCEPT: "Generate diverse architectures and mechanisms before fixation.",
    LifecycleStage.FEASIBILITY: "Reject impossible or uneconomic directions with inexpensive evidence.",
    LifecycleStage.ARCHITECTURE: "Allocate functions and interfaces across the system.",
    LifecycleStage.DETAILED_DESIGN: "Create controlled geometry, electronics, software and documentation.",
    LifecycleStage.DESIGN_REVIEW: "Review assumptions, risks, interfaces and evidence before build.",
    LifecycleStage.PROTOTYPE: "Build the cheapest representative prototype for the next uncertainty.",
    LifecycleStage.VERIFICATION: "Verify that implementation meets specified requirements.",
    LifecycleStage.VALIDATION: "Validate that the product solves the intended use problem.",
    LifecycleStage.COMPLIANCE: "Produce evidence for applicable regulatory and contractual obligations.",
    LifecycleStage.PILOT: "Run limited production and real-world use to expose process variation.",
    LifecycleStage.INDUSTRIALIZATION: "Stabilize tooling, process, supply, inspection and work instructions.",
    LifecycleStage.RELEASE: "Approve a controlled configuration and release package.",
    LifecycleStage.PRODUCTION: "Manufacture or deploy repeatably under configuration control.",
    LifecycleStage.QUALITY_CONTROL: "Inspect process outputs and react to nonconformity.",
    LifecycleStage.FULFILLMENT: "Package, label, deliver and record the product configuration.",
    LifecycleStage.OPERATION: "Use the product in its intended environment.",
    LifecycleStage.MONITORING: "Observe field state, performance, failures and user feedback.",
    LifecycleStage.MAINTENANCE: "Preserve performance through planned work.",
    LifecycleStage.SERVICE: "Diagnose and restore failed or degraded products.",
    LifecycleStage.IMPROVEMENT: "Feed evidence into a new controlled evolution cycle.",
    LifecycleStage.RECALL: "Contain and correct an unacceptable field risk.",
    LifecycleStage.END_OF_LIFE: "Stop support or production while protecting users and records.",
    LifecycleStage.RETIREMENT: "Remove the product from use and close responsibilities.",
    LifecycleStage.REUSE: "Recover components or assemblies for another controlled use.",
    LifecycleStage.RECYCLING: "Separate and recover materials with traceable disposal.",
}


@dataclass(frozen=True, slots=True)
class EvolutionResult:
    run: EvolutionRun
    mode: str
    message: str


@lru_cache(maxsize=1)
def load_evolution_catalog() -> EvolutionCatalog:
    source = files("twinstudio").joinpath("data/evolution_catalog.yaml")
    return EvolutionCatalog.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))


class _LlmCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=180)
    summary: str = Field(min_length=20, max_length=1600)
    operator_ids: list[str] = Field(min_length=1, max_length=4)
    goal_node_ids: list[str] = Field(default_factory=list, max_length=6)
    resource_node_ids: list[str] = Field(default_factory=list, max_length=8)
    lens_ids: list[str] = Field(default_factory=list, max_length=8)
    assumptions_challenged: list[str] = Field(default_factory=list, max_length=8)
    expected_benefits: list[str] = Field(default_factory=list, max_length=8)
    risks: list[str] = Field(default_factory=list, max_length=8)
    validation_steps: list[str] = Field(default_factory=list, max_length=8)


class _LlmCandidateBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[_LlmCandidate] = Field(default_factory=list, max_length=20)


class ProjectEvolutionEngine:
    """Compile goals, project resources and design lenses into auditable variants.

    The engine deliberately separates idea generation from geometry execution. It can
    produce typed change operations, but those still require the existing scope,
    approval and adapter rules before they affect CAD or other source artifacts.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.catalog = load_evolution_catalog()
        self.physical_lenses = load_feature_lens_catalog()

    def run(
        self,
        snapshot: ProjectSnapshot,
        document: TwinDslDocument,
        *,
        actor: str,
    ) -> EvolutionResult:
        spec = document.spec
        self._validate_program(snapshot, spec)
        warnings: list[str] = []
        goal_variants = self._expand_goal(spec)
        resources = self._collect_resources(snapshot, spec)
        graph = self._build_bidirectional_graph(spec, goal_variants, resources)
        local_candidates = self._generate_candidates(snapshot, spec, goal_variants, resources, graph)
        mode = "local"
        message = "Deterministic local evolution engine generated and scored the candidate set."
        if self.settings.litellm_model and spec.evolution.population_size > len(local_candidates):
            llm_candidates, llm_message = self._llm_candidates(spec, goal_variants, resources, graph)
            if llm_candidates:
                local_candidates.extend(llm_candidates)
                mode = "litellm+local"
                message = llm_message
            elif llm_message:
                warnings.append(llm_message)
        candidates = self._evolve_and_score(snapshot, spec, local_candidates)
        selected = [candidate.candidate_id for candidate in candidates if candidate.status == CandidateStatus.SHORTLISTED]
        run_id = _stable_id(
            "run",
            snapshot.project_id,
            snapshot.revision,
            document.metadata.name,
            spec.goal.statement,
            str(snapshot.stream_version),
        )
        stages = [
            EvolutionStageRecord(
                phase=phase,
                status=StageRunStatus.COMPLETED,
                output_ids=_phase_outputs(phase, goal_variants, resources, graph, candidates),
                started_at=snapshot.updated_at,
                completed_at=snapshot.updated_at,
            )
            for phase in _program_phases(spec)
        ]
        run = EvolutionRun(
            run_id=run_id,
            uri=f"poa://{snapshot.tenant}/{snapshot.project_id}@{snapshot.revision}/evolution-run/{run_id}",
            project_id=snapshot.project_id,
            base_revision=snapshot.revision,
            program=document,
            goal_variants=goal_variants,
            resources=resources,
            graph=graph,
            candidates=candidates,
            selected_candidate_ids=selected,
            stages=stages,
            lifecycle_stage=spec.lifecycle.start_stage,
            status=(
                EvolutionRunStatus.AWAITING_APPROVAL
                if spec.realization.require_approval
                else EvolutionRunStatus.COMPLETED
            ),
            planner="litellm+local-evolution-engine" if mode.startswith("litellm") else "local-evolution-engine",
            warnings=warnings + list(self.catalog.source_notes),
            created_by=actor,
        )
        return EvolutionResult(run=run, mode=mode, message=message)

    def lifecycle_blueprint(
        self,
        spec: EvolutionProgramSpec,
        *,
        actor: str,
    ) -> LifecycleBlueprint:
        template = self.catalog.lifecycle_templates.get(spec.lifecycle.template_id)
        if template is None:
            raise ValueError(f"Unknown lifecycle template: {spec.lifecycle.template_id}")
        stages = list(template.stages)
        if spec.lifecycle.enabled_stages:
            enabled = set(spec.lifecycle.enabled_stages)
            stages = [stage for stage in stages if stage in enabled]
        if spec.lifecycle.disabled_stages:
            disabled = set(spec.lifecycle.disabled_stages)
            stages = [stage for stage in stages if stage not in disabled]
        required = {spec.lifecycle.start_stage, spec.lifecycle.target_stage}
        missing = required - set(stages)
        if missing:
            raise ValueError("Lifecycle configuration removes required start/target stages: " + ", ".join(sorted(_enum_value(x) for x in missing)))
        definitions = [self._stage_definition(stage) for stage in stages]
        transitions = [
            LifecycleTransition(
                from_stage=current,
                to_stage=following,
                conditions=[f"Exit criteria for {_enum_value(current)} are approved."],
            )
            for current, following in zip(stages, stages[1:])
        ]
        return LifecycleBlueprint(
            blueprint_id=spec.lifecycle.template_id,
            name=template.name,
            version=self.catalog.catalog_version,
            stages=definitions,
            transitions=transitions,
            current_stage=spec.lifecycle.start_stage,
            tailored=bool(spec.lifecycle.enabled_stages or spec.lifecycle.disabled_stages),
            notes=[
                f"Target stage: {_enum_value(spec.lifecycle.target_stage)}",
                "Lifecycle advancement is evidence- and approval-gated; auto_advance does not bypass gate checks.",
            ],
        )

    def candidate_change_plan(
        self,
        snapshot: ProjectSnapshot,
        run: EvolutionRun,
        candidate_id: str,
        *,
        actor: str,
    ) -> ChangePlan:
        candidate = next((item for item in run.candidates if item.candidate_id == candidate_id), None)
        if candidate is None:
            raise ValueError(f"Unknown candidate: {candidate_id}")
        if not candidate.proposed_changes:
            raise ValueError("Candidate has no typed change operations")
        targets = run.program.spec.targets
        impact = [
            ImpactItem(uri=uri, impact="direct", summary=f"Candidate {candidate.title} proposes scoped changes.")
            for uri in targets
        ]
        return ChangePlan(
            project_id=snapshot.project_id,
            base_revision=snapshot.revision,
            prompt=f"Evolution candidate: {candidate.title}\n{candidate.summary}",
            selection_uri=f"dsl://{run.run_id}/{candidate.candidate_id}",
            selected_scope_uris=targets,
            operations=candidate.proposed_changes,
            impact=impact,
            assumptions=candidate.assumptions_challenged,
            unresolved_questions=[
                "Candidate scores are screening estimates; execute the listed validation steps before release."
            ],
            requires_approval=True,
            planner="twinstudio-evolution-candidate",
            created_by=actor,
        )

    def _validate_program(self, snapshot: ProjectSnapshot, spec: EvolutionProgramSpec) -> None:
        if spec.project_id != snapshot.project_id:
            raise ValueError(f"DSL project {spec.project_id!r} does not match requested project {snapshot.project_id!r}")
        if spec.base_revision != snapshot.revision:
            raise ValueError(
                f"DSL base revision {spec.base_revision!r} is stale; current revision is {snapshot.revision!r}"
            )
        unknown_targets = [uri for uri in spec.targets if uri not in snapshot.objects]
        if unknown_targets:
            raise ValueError("Unknown target URI(s): " + ", ".join(unknown_targets))
        source_ids = {lens.id for lens in self.physical_lenses.lenses if lens.enabled}
        unknown_lenses = sorted(set(spec.lenses.source_lens_ids) - source_ids)
        if unknown_lenses:
            raise ValueError("Unknown source feature lens IDs: " + ", ".join(unknown_lenses))
        extension_ids = {item.id for item in self.catalog.extension_dimensions}
        unknown_dimensions = sorted(set(spec.lenses.extension_dimension_ids) - extension_ids)
        if unknown_dimensions:
            raise ValueError("Unknown extension dimension IDs: " + ", ".join(unknown_dimensions))
        allowed_ops = set(spec.realization.allowed_operations)
        disallowed = [item.kind for item in spec.explicit_changes if item.kind not in allowed_ops]
        if disallowed:
            raise ValueError("Explicit DSL changes contain operations not allowed by realization policy")
        for operation in spec.explicit_changes:
            if not _uri_in_scope(operation.target_uri, spec.targets):
                raise ValueError(f"Explicit change target is outside DSL scope: {operation.target_uri}")

    def _expand_goal(self, spec: EvolutionProgramSpec) -> list[GoalVariant]:
        verb = _normalize_verb(spec.goal.verb or _first_word(spec.goal.statement))
        seed_verbs = [_normalize_verb(value) for value in (spec.action_search.seed_verbs or [verb])]
        result: list[GoalVariant] = []
        seen: set[tuple[str, ActionRelation]] = set()
        root_id = _stable_id("goal", spec.goal.statement)
        result.append(
            GoalVariant(
                node_id=root_id,
                phrase=spec.goal.statement,
                verb=verb,
                relation=ActionRelation.SEED,
                depth=0,
                assumptions=list(spec.goal.assumptions),
                source="human",
            )
        )
        seen.add((verb, ActionRelation.SEED))
        for seed in seed_verbs:
            self._walk_action_relation(
                seed,
                ActionRelation.HYPERNYM,
                spec.action_search.up_depth,
                root_id,
                result,
                seen,
                spec.action_search.max_terms,
            )
            self._walk_action_relation(
                seed,
                ActionRelation.HYPONYM,
                spec.action_search.down_depth,
                root_id,
                result,
                seen,
                spec.action_search.max_terms,
            )
            relation_set = self.catalog.verb_graph.get(seed)
            if relation_set:
                for value in relation_set.synonyms[: spec.action_search.sideways_depth * 4]:
                    self._append_goal_variant(value, ActionRelation.SYNONYM, root_id, 1, result, seen)
                if spec.action_search.include_opposites:
                    for value in relation_set.opposites[:4]:
                        self._append_goal_variant(value, ActionRelation.OPPOSITE, root_id, 1, result, seen)
        return result[: spec.action_search.max_terms]

    def _walk_action_relation(
        self,
        verb: str,
        relation: ActionRelation,
        depth: int,
        parent_id: str,
        result: list[GoalVariant],
        seen: set[tuple[str, ActionRelation]],
        limit: int,
    ) -> None:
        if depth <= 0 or len(result) >= limit:
            return
        relations = self.catalog.verb_graph.get(verb)
        if not relations:
            return
        values = relations.hypernyms if relation == ActionRelation.HYPERNYM else relations.hyponyms
        for value in values:
            if len(result) >= limit:
                break
            child_id = self._append_goal_variant(value, relation, parent_id, depth, result, seen)
            if child_id:
                self._walk_action_relation(value, relation, depth - 1, child_id, result, seen, limit)

    def _append_goal_variant(
        self,
        verb: str,
        relation: ActionRelation,
        parent_id: str,
        depth: int,
        result: list[GoalVariant],
        seen: set[tuple[str, ActionRelation]],
    ) -> str | None:
        normalized = _normalize_verb(verb)
        key = (normalized, relation)
        if key in seen:
            return None
        seen.add(key)
        relation_set = self.catalog.verb_graph.get(normalized)
        assumptions = relation_set.assumptions if relation_set else []
        node_id = _stable_id("goal", parent_id, _enum_value(relation), normalized)
        result.append(
            GoalVariant(
                node_id=node_id,
                phrase=normalized.replace("_", " "),
                verb=normalized,
                relation=relation,
                parent_id=parent_id,
                depth=depth,
                assumptions=list(assumptions),
                source="catalog" if relation_set else "derived",
            )
        )
        return node_id

    def _collect_resources(self, snapshot: ProjectSnapshot, spec: EvolutionProgramSpec) -> list[EvolutionResource]:
        resources: list[EvolutionResource] = []
        object_uris = _scope_objects(snapshot, spec.targets, spec.resources.include_descendants)
        for uri in object_uris:
            node = snapshot.objects[uri]
            object_id = _stable_id("resource", uri)
            resources.append(
                EvolutionResource(
                    node_id=object_id,
                    kind=ResourceKind.PART if _enum_value(node.kind) == "part" else ResourceKind.OBJECT,
                    label=node.name,
                    uri=uri,
                    properties={
                        "kind": node.kind,
                        "description": node.description,
                        "tags": node.tags,
                        "quantity": node.quantity,
                    },
                    associations=_tokens(node.name, node.description, *node.tags),
                )
            )
            if spec.resources.include_features:
                for feature in node.features:
                    resources.append(
                        EvolutionResource(
                            node_id=_stable_id("feature", feature.uri),
                            kind=ResourceKind.FEATURE,
                            label=feature.name,
                            uri=feature.uri,
                            parent_id=object_id,
                            properties={"feature_type": feature.feature_type, "enabled": feature.enabled},
                            associations=_tokens(feature.name, feature.feature_type, feature.notes),
                        )
                    )
            if spec.resources.include_parameters:
                for name, value in node.parameters.items():
                    resources.append(
                        EvolutionResource(
                            node_id=_stable_id("parameter", uri, name),
                            kind=ResourceKind.PARAMETER,
                            label=name,
                            uri=f"{uri}/parameter/{name}",
                            parent_id=object_id,
                            properties=value.model_dump(mode="json"),
                            associations=_tokens(name, value.unit or "", value.notes),
                        )
                    )
            if spec.resources.include_materials and node.manufacturing.material:
                resources.append(
                    EvolutionResource(
                        node_id=_stable_id("material", uri, node.manufacturing.material),
                        kind=ResourceKind.MATERIAL,
                        label=node.manufacturing.material,
                        uri=f"{uri}/manufacturing/material",
                        parent_id=object_id,
                        associations=_tokens(node.manufacturing.material, "material", "strength", "thermal"),
                    )
                )
            if spec.resources.include_processes and _enum_value(node.manufacturing.process) != "none":
                resources.append(
                    EvolutionResource(
                        node_id=_stable_id("process", uri, _enum_value(node.manufacturing.process)),
                        kind=ResourceKind.PROCESS,
                        label=_enum_value(node.manufacturing.process),
                        uri=f"{uri}/manufacturing/process",
                        parent_id=object_id,
                        associations=_tokens(_enum_value(node.manufacturing.process), "manufacture", "tolerance"),
                    )
                )
            if spec.resources.include_artifacts:
                for artifact_uri in node.artifact_uris:
                    artifact = snapshot.artifacts.get(artifact_uri)
                    if artifact:
                        resources.append(
                            EvolutionResource(
                                node_id=_stable_id("artifact", artifact.uri),
                                kind=ResourceKind.ARTIFACT,
                                label=artifact.name,
                                uri=artifact.uri,
                                parent_id=object_id,
                                properties={"kind": artifact.kind, "source": artifact.source},
                                associations=_tokens(artifact.name, _enum_value(artifact.kind)),
                                evidence_uris=[artifact.uri],
                            )
                        )
        if spec.resources.include_requirements:
            for requirement in snapshot.requirements.values():
                if any(_uri_in_scope(uri, object_uris) for uri in requirement.target_uris) or not requirement.target_uris:
                    resources.append(
                        EvolutionResource(
                            node_id=_stable_id("requirement", requirement.uri),
                            kind=ResourceKind.REQUIREMENT,
                            label=requirement.statement,
                            uri=requirement.uri,
                            properties={"status": requirement.status, "verification_method": requirement.verification_method},
                            associations=_tokens(requirement.statement, requirement.verification_method or ""),
                        )
                    )
        if spec.resources.include_evidence:
            for claim in snapshot.claims.values():
                if _uri_in_scope(claim.subject_uri, object_uris):
                    resources.append(
                        EvolutionResource(
                            node_id=_stable_id("evidence", claim.claim_id),
                            kind=ResourceKind.EVIDENCE,
                            label=f"{claim.predicate}: {claim.value}",
                            uri=claim.source_artifact_uri,
                            properties={"confidence": claim.confidence, "status": claim.status},
                            associations=_tokens(claim.predicate, str(claim.value), claim.unit or ""),
                            evidence_uris=[claim.source_artifact_uri],
                        )
                    )
        if spec.resources.include_human_actions:
            for scenario in snapshot.human_scenarios:
                for step in scenario.steps:
                    if step.target_uri and _uri_in_scope(step.target_uri, object_uris):
                        resources.append(
                            EvolutionResource(
                                node_id=_stable_id("human", scenario.uri, step.step_id),
                                kind=ResourceKind.HUMAN_ACTION,
                                label=step.action,
                                uri=step.target_uri,
                                properties={"instruction": step.instruction, "hazards": step.hazards},
                                associations=_tokens(step.action, step.instruction, *step.hazards),
                            )
                        )
        if spec.resources.include_environment:
            resources.append(
                EvolutionResource(
                    node_id=_stable_id("environment", snapshot.project_id),
                    kind=ResourceKind.ENVIRONMENT,
                    label="intended environment",
                    properties={"lifecycle_stage": snapshot.lifecycle_stage},
                    associations=["temperature", "humidity", "dust", "vibration", "user", "space"],
                )
            )
        return _dedupe_resources(resources)[: spec.resources.max_resources]

    def _build_bidirectional_graph(
        self,
        spec: EvolutionProgramSpec,
        goals: list[GoalVariant],
        resources: list[EvolutionResource],
    ) -> EvolutionGraph:
        nodes: list[EvolutionGraphNode] = []
        edges: list[EvolutionGraphEdge] = []
        for goal in goals:
            nodes.append(
                EvolutionGraphNode(
                    node_id=goal.node_id,
                    side="goal",
                    label=goal.phrase,
                    kind=_enum_value(goal.relation),
                    data={"verb": goal.verb, "assumptions": goal.assumptions},
                )
            )
            if goal.parent_id:
                edges.append(
                    EvolutionGraphEdge(
                        source=goal.parent_id,
                        target=goal.node_id,
                        relation=_enum_value(goal.relation),
                        score=0.75,
                    )
                )
        for resource in resources:
            nodes.append(
                EvolutionGraphNode(
                    node_id=resource.node_id,
                    side="resource",
                    label=resource.label,
                    kind=_enum_value(resource.kind),
                    data={"uri": resource.uri, "properties": resource.properties},
                )
            )
            if resource.parent_id:
                edges.append(
                    EvolutionGraphEdge(
                        source=resource.node_id,
                        target=resource.parent_id,
                        relation="part_of",
                        score=0.9,
                    )
                )
        bridge_count = 0
        for goal in goals:
            action = self.catalog.verb_graph.get(goal.verb)
            goal_terms = set(_tokens(goal.verb, goal.phrase, *(action.associations if action else [])))
            ranked: list[tuple[float, EvolutionResource, list[str]]] = []
            for resource in resources:
                terms = set(resource.associations) | set(_tokens(resource.label, _enum_value(resource.kind)))
                overlap = sorted(goal_terms & terms)
                score = len(overlap) / max(1, math.sqrt(len(goal_terms) * len(terms)))
                if resource.kind in {ResourceKind.FEATURE, ResourceKind.PARAMETER, ResourceKind.MATERIAL, ResourceKind.PROCESS}:
                    score += 0.06
                if score > 0:
                    ranked.append((min(score, 1.0), resource, overlap))
            ranked.sort(key=lambda item: (-item[0], item[1].label))
            if not ranked and resources:
                ranked = [(0.18, resources[0], [])]
            for score, resource, overlap in ranked[:3]:
                edge_id = _stable_id("bridge", goal.node_id, resource.node_id)
                nodes.append(
                    EvolutionGraphNode(
                        node_id=edge_id,
                        side="bridge",
                        label=f"{goal.verb} ↔ {resource.label}",
                        kind="solution_bridge",
                        data={"overlap": overlap},
                    )
                )
                edges.append(
                    EvolutionGraphEdge(
                        source=goal.node_id,
                        target=edge_id,
                        relation="can_be_realized_by",
                        score=max(0.15, score),
                        rationale=(
                            "Shared associations: " + ", ".join(overlap)
                            if overlap
                            else "Low-confidence adjacent bridge retained for review rather than silently discarded."
                        ),
                    )
                )
                edges.append(
                    EvolutionGraphEdge(
                        source=edge_id,
                        target=resource.node_id,
                        relation="uses_resource",
                        score=max(0.15, score),
                    )
                )
                bridge_count += 1
        if bridge_count == 0:
            raise ValueError("No goal/resource bridge could be constructed")
        return EvolutionGraph(nodes=nodes, edges=edges)

    def _generate_candidates(
        self,
        snapshot: ProjectSnapshot,
        spec: EvolutionProgramSpec,
        goals: list[GoalVariant],
        resources: list[EvolutionResource],
        graph: EvolutionGraph,
    ) -> list[EvolutionCandidate]:
        bridge_nodes = [node for node in graph.nodes if node.side == "bridge"]
        source_lenses = spec.lenses.source_lens_ids
        if spec.lenses.include_source_lenses and not source_lenses:
            source_lenses = [
                "shape",
                "connectivity_among_parts",
                "spatial_relations_among_parts",
                "force_characteristics",
                "side_effects",
                "human_use",
                "causal_relations",
                "aesthetics",
            ]
        extension_ids = spec.lenses.extension_dimension_ids
        if spec.lenses.include_extension_dimensions and not extension_ids:
            extension_ids = [
                "manufacturability",
                "serviceability",
                "testability",
                "reliability",
                "observability",
                "reversibility",
                "adjacent_possible",
            ]
        lens_ids = (source_lenses + extension_ids)[: spec.lenses.max_lenses]
        operators = [item for item in spec.evolution.operators if item.enabled]
        if not operators:
            raise ValueError("Evolution policy contains no enabled operators")
        result: list[EvolutionCandidate] = []
        desired = min(spec.evolution.population_size, max(1, len(bridge_nodes) * max(1, len(operators))))
        for index in range(desired):
            bridge = bridge_nodes[index % len(bridge_nodes)]
            operator = operators[index % len(operators)]
            goal_id, resource_id = _bridge_endpoints(graph, bridge.node_id)
            goal = next((item for item in goals if item.node_id == goal_id), goals[0])
            resource = next((item for item in resources if item.node_id == resource_id), resources[0])
            selected_lenses = [lens_ids[index % len(lens_ids)]] if lens_ids else []
            if len(lens_ids) > 1 and index % 3 == 0:
                selected_lenses.append(lens_ids[(index + 1) % len(lens_ids)])
            candidate_id = _stable_id(
                "candidate",
                spec.project_id,
                spec.goal.statement,
                goal.node_id,
                resource.node_id,
                _enum_value(operator.operator),
                str(index),
            )
            changes = [self._operation_for(operator, resource, spec, index)]
            result.append(
                EvolutionCandidate(
                    candidate_id=candidate_id,
                    title=f"{goal.verb.replace('_', ' ').title()} {resource.label} via {_enum_value(operator.operator).replace('_', ' ')}",
                    summary=(
                        f"Connect the reframed action '{goal.phrase}' to the available resource '{resource.label}', "
                        f"then apply the {_enum_value(operator.operator).replace('_', ' ')} operator. The proposal is a "
                        "screening candidate and must be tested before implementation."
                    ),
                    generation=0,
                    methods=[
                        EvolutionMethod.GOAL_LADDER,
                        EvolutionMethod.BIDIRECTIONAL_GRAPH,
                        EvolutionMethod.FEATURE_LENSES,
                        EvolutionMethod.ADJACENT_POSSIBLE,
                    ],
                    goal_node_ids=[goal.node_id],
                    resource_node_ids=[resource.node_id],
                    bridge_edge_ids=[bridge.node_id],
                    lens_ids=selected_lenses,
                    operators=[operator],
                    assumptions_challenged=list(goal.assumptions[:3]) + list(spec.goal.assumptions[:3]),
                    proposed_changes=changes,
                    expected_benefits=[
                        f"Explores {_enum_value(operator.operator).replace('_', ' ')} without treating the current mechanism as fixed.",
                        f"Uses an existing project resource: {resource.label}.",
                    ],
                    risks=[
                        "The conceptual bridge may conflict with verified interfaces or manufacturing limits.",
                        "Heuristic scores are not physical test results.",
                    ],
                    validation_steps=_candidate_validation_steps(spec, resource),
                    source="local",
                )
            )
        return result

    def _operation_for(
        self,
        operator: EvolutionOperatorSpec,
        resource: EvolutionResource,
        spec: EvolutionProgramSpec,
        index: int,
    ) -> ChangeOperation:
        target_uri = _nearest_scope_uri(resource.uri, spec.targets)
        kind = operator.operator
        if kind == MutationOperatorKind.PARAMETER_SHIFT:
            return ChangeOperation(
                operation_id=_stable_id("op", target_uri, _enum_value(kind), str(index)),
                kind=ChangeOperationKind.SET_PARAMETER,
                target_uri=target_uri,
                selector={"resource_uri": resource.uri},
                arguments={"mode": "explore_range", "delta_percent": 10, **operator.parameters},
                rationale="Explore a bounded parameter variation rather than fixing the current value.",
                confidence=0.62,
                validation_steps=["Regenerate dependent artifacts and rerun affected checks."],
            )
        if kind in {MutationOperatorKind.SUBSTITUTE_MATERIAL, MutationOperatorKind.SUBSTITUTE_PROCESS}:
            return ChangeOperation(
                operation_id=_stable_id("op", target_uri, _enum_value(kind), str(index)),
                kind=ChangeOperationKind.UPDATE_MANUFACTURING,
                target_uri=target_uri,
                selector={"resource_uri": resource.uri},
                arguments={"mode": _enum_value(kind), "candidate_set": "catalog_or_supplier_search", **operator.parameters},
                rationale="Evaluate an alternative realization route; do not overwrite the approved route without review.",
                confidence=0.55,
                validation_steps=["Compare tolerance, cost, lead time, material properties and supplier evidence."],
            )
        if kind == MutationOperatorKind.ADD_OBSERVABILITY:
            return ChangeOperation(
                operation_id=_stable_id("op", target_uri, _enum_value(kind), str(index)),
                kind=ChangeOperationKind.ADD_TEST,
                target_uri=target_uri,
                arguments={"test_type": "inspection", "purpose": "make hidden state observable", **operator.parameters},
                rationale="Create evidence before committing to a difficult-to-reverse design choice.",
                confidence=0.72,
                validation_steps=["Define measurable expected results and evidence retention."],
            )
        if kind in {
            MutationOperatorKind.SPLIT_PART,
            MutationOperatorKind.DUPLICATE_FEATURE,
            MutationOperatorKind.MODULARIZE,
            MutationOperatorKind.MOVE_FUNCTION,
        }:
            return ChangeOperation(
                operation_id=_stable_id("op", target_uri, _enum_value(kind), str(index)),
                kind=ChangeOperationKind.ADD_FEATURE,
                target_uri=target_uri,
                selector={"resource_uri": resource.uri},
                arguments={"conceptual_feature": _enum_value(kind), "deferred_adapter": True, **operator.parameters},
                rationale="Record a typed conceptual feature; geometry remains deferred until an adapter and interface review exist.",
                confidence=0.48,
                validation_steps=["Review interfaces, part count, assembly sequence and service access."],
            )
        if kind in {MutationOperatorKind.REMOVE_PART, MutationOperatorKind.COMBINE_PARTS}:
            return ChangeOperation(
                operation_id=_stable_id("op", target_uri, _enum_value(kind), str(index)),
                kind=ChangeOperationKind.SUPPRESS_FEATURE,
                target_uri=target_uri,
                selector={"resource_uri": resource.uri},
                arguments={"conceptual_operator": _enum_value(kind), "transfer_function_first": True, **operator.parameters},
                rationale="Do not delete a resource until every function and interface has a new owner.",
                confidence=0.45,
                validation_steps=["Build a function-to-component allocation and check orphaned requirements."],
            )
        if kind in {MutationOperatorKind.INVERT_RELATION, MutationOperatorKind.CHANGE_STATE, MutationOperatorKind.CHANGE_ENERGY}:
            return ChangeOperation(
                operation_id=_stable_id("op", target_uri, _enum_value(kind), str(index)),
                kind=ChangeOperationKind.TRANSFORM_FEATURE,
                target_uri=target_uri,
                selector={"resource_uri": resource.uri},
                arguments={"conceptual_transform": _enum_value(kind), "deferred_adapter": True, **operator.parameters},
                rationale="Challenge the current relation, state or energy mechanism before modifying source geometry.",
                confidence=0.42,
                validation_steps=["Create a physical or simulation experiment for the transformed mechanism."],
            )
        return ChangeOperation(
            operation_id=_stable_id("op", target_uri, _enum_value(kind), str(index)),
            kind=ChangeOperationKind.ADD_ANNOTATION,
            target_uri=target_uri,
            selector={"resource_uri": resource.uri},
            arguments={"idea_operator": _enum_value(kind), "review_required": True, **operator.parameters},
            rationale="Keep the idea in the product thread without pretending it is an executable CAD change.",
            confidence=0.58,
            validation_steps=["Review the idea and convert it into adapter-supported operations if selected."],
        )

    def _evolve_and_score(
        self,
        snapshot: ProjectSnapshot,
        spec: EvolutionProgramSpec,
        seeds: list[EvolutionCandidate],
    ) -> list[EvolutionCandidate]:
        candidates = list(seeds)
        current = list(seeds)
        for generation in range(1, spec.evolution.generations):
            offspring: list[EvolutionCandidate] = []
            for index, parent in enumerate(current):
                if len(candidates) + len(offspring) >= spec.evolution.population_size * spec.evolution.generations:
                    break
                operator = spec.evolution.operators[(index + generation) % len(spec.evolution.operators)]
                child = parent.model_copy(deep=True)
                child.candidate_id = _stable_id("offspring", parent.candidate_id, str(generation), _enum_value(operator.operator))
                child.parent_ids = [parent.candidate_id]
                child.generation = generation
                child.title = f"{parent.title} · {_enum_value(operator.operator).replace('_', ' ')}"
                child.summary = parent.summary + f" Generation {generation} applies an additional {_enum_value(operator.operator).replace('_', ' ')} mutation."
                child.operators = parent.operators + [operator]
                child.assumptions_challenged = _dedupe(parent.assumptions_challenged + [
                    f"The current {_enum_value(operator.operator).replace('_', ' ')} choice is necessary."
                ])
                child.source = "local"
                offspring.append(child)
            if spec.evolution.crossover_rate > 0 and len(current) >= 2 and len(candidates) + len(offspring) < spec.evolution.population_size * spec.evolution.generations:
                a, b = current[0], current[-1]
                child = a.model_copy(deep=True)
                child.candidate_id = _stable_id("crossover", a.candidate_id, b.candidate_id, str(generation))
                child.parent_ids = [a.candidate_id, b.candidate_id]
                child.generation = generation
                child.title = f"Crossover: {a.title} × {b.title}"
                child.summary = "Combine complementary traits from two candidate lineages and re-check all interfaces."
                child.goal_node_ids = _dedupe(a.goal_node_ids + b.goal_node_ids)
                child.resource_node_ids = _dedupe(a.resource_node_ids + b.resource_node_ids)
                child.lens_ids = _dedupe(a.lens_ids + b.lens_ids)
                child.operators = _dedupe_models(a.operators + b.operators)
                child.proposed_changes = _dedupe_models(a.proposed_changes + b.proposed_changes)
                child.risks = _dedupe(a.risks + b.risks + ["Crossover can combine incompatible interfaces or assumptions."])
                child.validation_steps = _dedupe(a.validation_steps + b.validation_steps)
                offspring.append(child)
            candidates.extend(offspring)
            current = offspring or current
        for candidate in candidates:
            candidate.evaluations = self._score_candidate(snapshot, spec, candidate)
            weighted = 0.0
            total_weight = 0.0
            for evaluation in candidate.evaluations:
                weight = spec.evaluation.weights.get(_enum_value(evaluation.dimension), 0.0)
                weighted += evaluation.score * weight
                total_weight += weight
            candidate.overall_score = round(weighted / total_weight if total_weight else 0.0, 4)
            candidate.constraint_violations = _constraint_findings(snapshot, spec, candidate)
            if any(item.startswith("blocking:") for item in candidate.constraint_violations):
                candidate.status = CandidateStatus.REJECTED
                candidate.overall_score = min(candidate.overall_score, 0.2)
        ranked = sorted(candidates, key=lambda item: (-item.overall_score, item.candidate_id))
        shortlist = 0
        for candidate in ranked:
            if candidate.status == CandidateStatus.REJECTED:
                continue
            if candidate.overall_score < spec.evaluation.minimum_overall_score:
                candidate.status = CandidateStatus.REJECTED
                continue
            if shortlist < spec.evaluation.select_top:
                candidate.status = CandidateStatus.SHORTLISTED
                shortlist += 1
        return ranked

    def _score_candidate(
        self,
        snapshot: ProjectSnapshot,
        spec: EvolutionProgramSpec,
        candidate: EvolutionCandidate,
    ) -> list[CandidateEvaluation]:
        evidence_count = sum(len(item.evidence_uris) for item in self._collect_resources(snapshot, spec))
        operator_values = {item.operator for item in candidate.operators}
        results: list[CandidateEvaluation] = []
        for dimension in EvaluationDimension:
            base = _stable_score(candidate.candidate_id, _enum_value(dimension), str(spec.evolution.deterministic_seed))
            rationale = "Deterministic screening score; replace with measured or simulated evidence when available."
            if dimension == EvaluationDimension.EVIDENCE:
                base = min(1.0, 0.32 + 0.08 * evidence_count + 0.04 * len(candidate.validation_steps))
                rationale = f"Project resources expose {evidence_count} evidence links and {len(candidate.validation_steps)} validation steps."
            elif dimension == EvaluationDimension.REVERSIBILITY:
                base = 0.86 if MutationOperatorKind.MAKE_REVERSIBLE in operator_values else 0.48
            elif dimension == EvaluationDimension.MANUFACTURABILITY:
                base = 0.72 if any(lens in candidate.lens_ids for lens in {"manufacturability", "shape", "force_characteristics"}) else 0.46
            elif dimension == EvaluationDimension.NOVELTY:
                base = min(1.0, 0.45 + 0.08 * len(candidate.goal_node_ids) + 0.06 * len(candidate.operators))
            elif dimension == EvaluationDimension.RISK_CONTROL:
                base = min(1.0, 0.40 + 0.06 * len(candidate.validation_steps) + 0.04 * len(candidate.risks))
            elif dimension == EvaluationDimension.LIFECYCLE_FIT:
                base = 0.75 if spec.lifecycle.start_stage in {LifecycleStage.CONCEPT, LifecycleStage.FEASIBILITY, LifecycleStage.DETAILED_DESIGN, LifecycleStage.IMPROVEMENT} else 0.55
            results.append(
                CandidateEvaluation(
                    dimension=dimension,
                    score=round(max(0.0, min(1.0, base)), 4),
                    rationale=rationale,
                )
            )
        return results

    def _llm_candidates(
        self,
        spec: EvolutionProgramSpec,
        goals: list[GoalVariant],
        resources: list[EvolutionResource],
        graph: EvolutionGraph,
    ) -> tuple[list[EvolutionCandidate], str]:
        try:
            from litellm import completion
        except Exception as exc:  # pragma: no cover - optional dependency
            return [], f"LiteLLM is unavailable: {exc}"
        allowed_operators = {item.id: item for item in self.catalog.operators}
        allowed_goals = {item.node_id for item in goals}
        allowed_resources = {item.node_id for item in resources}
        allowed_lenses = {
            lens.id for lens in self.physical_lenses.lenses if lens.enabled
        } | {item.id for item in self.catalog.extension_dimensions}
        system = (
            "You are TwinStudio's controlled project-evolution planner. Generate diverse reviewable candidates. "
            "Use only supplied IDs. Do not output executable code or claim that a candidate is verified. "
            "Every candidate needs risks and validation steps. Return strict JSON."
        )
        user = json.dumps(
            {
                "goal": spec.goal.model_dump(mode="json"),
                "goal_nodes": [item.model_dump(mode="json") for item in goals[:30]],
                "resources": [item.model_dump(mode="json") for item in resources[:80]],
                "bridge_edges": [item.model_dump(mode="json") for item in graph.edges if item.relation == "can_be_realized_by"][:50],
                "operator_ids": list(allowed_operators),
                "lens_ids": sorted(allowed_lenses),
                "maximum_candidates": max(1, spec.evolution.population_size // 2),
            },
            ensure_ascii=False,
        )
        kwargs: dict[str, Any] = {
            "model": self.settings.litellm_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.65,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "twinstudio_evolution_candidates",
                    "strict": True,
                    "schema": _LlmCandidateBatch.model_json_schema(),
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
            if isinstance(content, list):
                content = "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
            payload = _LlmCandidateBatch.model_validate_json(str(content))
        except Exception as exc:  # pragma: no cover - provider specific
            return [], f"LiteLLM evolution planning failed; local candidates retained: {exc}"
        result: list[EvolutionCandidate] = []
        for index, item in enumerate(payload.candidates):
            if not set(item.operator_ids) <= set(allowed_operators):
                continue
            if not set(item.goal_node_ids) <= allowed_goals:
                continue
            if not set(item.resource_node_ids) <= allowed_resources:
                continue
            if not set(item.lens_ids) <= allowed_lenses:
                continue
            operators = [
                EvolutionOperatorSpec(operator=allowed_operators[operator_id].kind)
                for operator_id in item.operator_ids
            ]
            candidate_id = _stable_id("llm-candidate", spec.project_id, item.title, str(index))
            result.append(
                EvolutionCandidate(
                    candidate_id=candidate_id,
                    title=item.title,
                    summary=item.summary,
                    methods=[EvolutionMethod.ADJACENT_POSSIBLE, EvolutionMethod.BRAINSWARM],
                    goal_node_ids=item.goal_node_ids,
                    resource_node_ids=item.resource_node_ids,
                    lens_ids=item.lens_ids,
                    operators=operators,
                    assumptions_challenged=item.assumptions_challenged,
                    expected_benefits=item.expected_benefits,
                    risks=item.risks,
                    validation_steps=item.validation_steps,
                    source="litellm",
                )
            )
        return result, f"LiteLLM added {len(result)} schema-validated candidates; local scoring and scope controls remain authoritative."

    def _stage_definition(self, stage: LifecycleStage) -> LifecycleStageDefinition:
        purpose = _DEFAULT_STAGE_PURPOSES.get(stage, _enum_value(stage).replace("_", " ").title())
        artifacts: list[Any] = []
        tests: list[str] = []
        methods: list[EvolutionMethod] = []
        if stage in {LifecycleStage.EVIDENCE, LifecycleStage.DISCOVERY, LifecycleStage.PROBLEM_FRAMING}:
            artifacts = ["photo", "pdf", "other"]
            methods = [EvolutionMethod.GOAL_LADDER, EvolutionMethod.FEATURE_LENSES]
        elif stage in {LifecycleStage.CONCEPT, LifecycleStage.FEASIBILITY, LifecycleStage.ARCHITECTURE}:
            artifacts = ["drawing_2d", "cad_source", "simulation_result"]
            methods = [
                EvolutionMethod.BIDIRECTIONAL_GRAPH,
                EvolutionMethod.ADJACENT_POSSIBLE,
                EvolutionMethod.BRAINSWARM,
                EvolutionMethod.MUTATION,
            ]
        elif stage in {LifecycleStage.PROTOTYPE, LifecycleStage.VERIFICATION, LifecycleStage.VALIDATION}:
            artifacts = ["test_result", "simulation_result", "drawing_2d"]
            tests = ["inspection", "mechanical", "human_use"]
            methods = [EvolutionMethod.EXPERIMENT]
        elif stage in {LifecycleStage.PRODUCTION, LifecycleStage.QUALITY_CONTROL, LifecycleStage.INDUSTRIALIZATION}:
            artifacts = ["bom", "drawing_2d", "test_result"]
            tests = ["manufacturing", "inspection"]
        elif stage in {LifecycleStage.MONITORING, LifecycleStage.IMPROVEMENT, LifecycleStage.SERVICE}:
            artifacts = ["test_result", "other"]
            methods = [EvolutionMethod.FEATURE_LENSES, EvolutionMethod.ASSUMPTION_REVERSAL, EvolutionMethod.EXPERIMENT]
        from twinstudio.domain import ArtifactKind

        return LifecycleStageDefinition(
            stage=stage,
            name=_enum_value(stage).replace("_", " ").title(),
            purpose=purpose,
            entry_criteria=[f"Inputs for {_enum_value(stage)} are identified and versioned."],
            exit_criteria=[f"Evidence and decisions for {_enum_value(stage)} are reviewed."],
            required_artifact_kinds=[ArtifactKind(value) for value in artifacts],
            required_test_types=tests,
            recommended_evolution_methods=methods,
            allowed_change_operations=list(ChangeOperationKind),
            optional=stage in {LifecycleStage.RECALL, LifecycleStage.REUSE, LifecycleStage.RECYCLING},
            repeatable=stage in {LifecycleStage.PROTOTYPE, LifecycleStage.VERIFICATION, LifecycleStage.IMPROVEMENT, LifecycleStage.SERVICE},
        )


def graph_to_dot(graph: EvolutionGraph) -> str:
    lines = ["digraph TwinStudioEvolution {", "  rankdir=TB;"]
    for node in graph.nodes:
        label = node.label.replace('"', "'")
        shape = {"goal": "box", "resource": "ellipse", "bridge": "diamond", "idea": "note"}.get(node.side, "ellipse")
        lines.append(f'  "{node.node_id}" [label="{label}", shape={shape}];')
    for edge in graph.edges:
        label = edge.relation.replace('"', "'")
        lines.append(f'  "{edge.source}" -> "{edge.target}" [label="{label}"];')
    lines.append("}")
    return "\n".join(lines)


def graph_to_mermaid(graph: EvolutionGraph) -> str:
    lines = ["flowchart TB"]
    for node in graph.nodes:
        label = node.label.replace('"', "'").replace("[", "(").replace("]", ")")
        lines.append(f'  {node.node_id}["{label}"]')
    for edge in graph.edges:
        lines.append(f"  {edge.source} -->|{edge.relation}| {edge.target}")
    return "\n".join(lines)


def diagnostics_for_program(snapshot: ProjectSnapshot, document: TwinDslDocument, engine: ProjectEvolutionEngine) -> list[DslDiagnostic]:
    diagnostics: list[DslDiagnostic] = []
    try:
        engine._validate_program(snapshot, document.spec)
    except ValueError as exc:
        diagnostics.append(DslDiagnostic(severity=DslSeverity.BLOCKING, code="program.invalid", message=str(exc)))
        return diagnostics
    if not document.spec.goal.assumptions:
        diagnostics.append(
            DslDiagnostic(
                severity=DslSeverity.WARNING,
                code="goal.assumptions.empty",
                message="No explicit hidden assumptions were supplied; the engine will derive a limited set from the verb catalog and lenses.",
                path="spec.goal.assumptions",
            )
        )
    if _enum_value(document.spec.realization.mode) == "auto_apply_safe" and not document.spec.realization.dry_run:
        diagnostics.append(
            DslDiagnostic(
                severity=DslSeverity.WARNING,
                code="realization.auto_apply",
                message="Only scalar parameter patches may be auto-applied; geometry and manufacturing changes remain queued for adapters/review.",
                path="spec.realization",
            )
        )
    if not document.spec.validation_steps:
        diagnostics.append(
            DslDiagnostic(
                severity=DslSeverity.WARNING,
                code="validation.missing",
                message="The program has no additional project-specific validation steps.",
                path="spec.validation_steps",
            )
        )
    diagnostics.append(
        DslDiagnostic(
            severity=DslSeverity.INFO,
            code="program.valid",
            message="The program is schema-valid, scope-valid and ready for evolution preview.",
        )
    )
    return diagnostics


def _program_phases(spec: EvolutionProgramSpec) -> list[EvolutionPhase]:
    phases = [
        EvolutionPhase.INTAKE,
        EvolutionPhase.FRAME,
        EvolutionPhase.GOAL_EXPANSION,
        EvolutionPhase.ASSUMPTION_DISCOVERY,
        EvolutionPhase.RESOURCE_DECOMPOSITION,
        EvolutionPhase.BRIDGE_BUILDING,
        EvolutionPhase.DIVERGENCE,
        EvolutionPhase.ADJACENT_POSSIBLE,
        EvolutionPhase.CONVERGENCE,
        EvolutionPhase.SELECTION,
    ]
    if EvolutionMethod.EXPERIMENT in spec.methods:
        phases.extend([EvolutionPhase.PROTOTYPE, EvolutionPhase.EXPERIMENT])
    if _enum_value(spec.realization.mode) != "analysis_only":
        phases.append(EvolutionPhase.REALIZATION)
    phases.extend([EvolutionPhase.VERIFICATION, EvolutionPhase.LEARNING])
    return phases


def _phase_outputs(
    phase: EvolutionPhase,
    goals: list[GoalVariant],
    resources: list[EvolutionResource],
    graph: EvolutionGraph,
    candidates: list[EvolutionCandidate],
) -> list[str]:
    if phase in {EvolutionPhase.FRAME, EvolutionPhase.GOAL_EXPANSION, EvolutionPhase.ASSUMPTION_DISCOVERY}:
        return [item.node_id for item in goals]
    if phase == EvolutionPhase.RESOURCE_DECOMPOSITION:
        return [item.node_id for item in resources]
    if phase == EvolutionPhase.BRIDGE_BUILDING:
        return [item.node_id for item in graph.nodes if item.side == "bridge"]
    if phase in {EvolutionPhase.DIVERGENCE, EvolutionPhase.ADJACENT_POSSIBLE, EvolutionPhase.CONVERGENCE}:
        return [item.candidate_id for item in candidates]
    if phase == EvolutionPhase.SELECTION:
        return [item.candidate_id for item in candidates if item.status == CandidateStatus.SHORTLISTED]
    return []


def _first_word(text: str) -> str:
    match = re.search(r"[\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ-]+", text, flags=re.UNICODE)
    return match.group(0) if match else "improve"


def _normalize_verb(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    return _POLISH_VERB_ALIASES.get(normalized, normalized)


def _tokens(*values: str) -> list[str]:
    tokens: list[str] = []
    for value in values:
        for token in re.findall(r"[a-zA-Z0-9_ąćęłńóśźż]+", str(value).lower()):
            if len(token) > 2:
                tokens.append(_POLISH_VERB_ALIASES.get(token, token))
    return _dedupe(tokens)



def _enum_value(value: Any) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)

def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _stable_score(*parts: str) -> float:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    integer = int.from_bytes(digest[:8], "big")
    return round(0.25 + (integer / (2**64 - 1)) * 0.7, 4)


def _scope_objects(snapshot: ProjectSnapshot, targets: list[str], include_descendants: bool) -> list[str]:
    selected = set(targets)
    if include_descendants:
        changed = True
        while changed:
            changed = False
            for uri, node in snapshot.objects.items():
                if node.parent_uri in selected and uri not in selected:
                    selected.add(uri)
                    changed = True
    return sorted(selected)


def _uri_in_scope(uri: str | None, scopes: Iterable[str]) -> bool:
    if not uri:
        return False
    return any(uri == scope or uri.startswith(scope.rstrip("/") + "/") for scope in scopes)


def _nearest_scope_uri(uri: str | None, scopes: list[str]) -> str:
    if uri:
        matches = [scope for scope in scopes if _uri_in_scope(uri, [scope])]
        if matches:
            return max(matches, key=len)
    return scopes[0]


def _bridge_endpoints(graph: EvolutionGraph, bridge_id: str) -> tuple[str, str]:
    goal = next(edge.source for edge in graph.edges if edge.target == bridge_id and edge.relation == "can_be_realized_by")
    resource = next(edge.target for edge in graph.edges if edge.source == bridge_id and edge.relation == "uses_resource")
    return goal, resource


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _dedupe_resources(values: list[EvolutionResource]) -> list[EvolutionResource]:
    by_id: dict[str, EvolutionResource] = {}
    for value in values:
        by_id.setdefault(value.node_id, value)
    return list(by_id.values())


def _dedupe_models(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if hasattr(value, "model_dump_json"):
            key = value.model_dump_json(exclude_none=True)
        else:
            key = json.dumps(value, sort_keys=True, default=str)
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result


def _candidate_validation_steps(spec: EvolutionProgramSpec, resource: EvolutionResource) -> list[str]:
    steps = [
        "Check the candidate against approved requirements and every adjacent interface.",
        "Run the cheapest safe experiment that can reject the candidate.",
        "Record measured evidence separately from heuristic screening scores.",
    ]
    if resource.kind in {ResourceKind.FEATURE, ResourceKind.PARAMETER, ResourceKind.PART, ResourceKind.OBJECT}:
        steps.append("Regenerate 2D/3D artifacts and run geometric/manufacturing checks.")
    return _dedupe(steps + spec.validation_steps)


def _constraint_findings(
    snapshot: ProjectSnapshot,
    spec: EvolutionProgramSpec,
    candidate: EvolutionCandidate,
) -> list[str]:
    findings: list[str] = []
    expressions = list(spec.evaluation.hard_constraints) + list(spec.goal.constraints)
    for expression in expressions:
        match = re.fullmatch(
            r"\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*(>=|<=|==|>|<)\s*(-?\d+(?:[.,]\d+)?)\s*([A-Za-z°%/_-]+)?\s*",
            expression,
        )
        if not match:
            findings.append(f"unresolved: {expression}")
            continue
        parameter, operator, raw, _unit = match.groups()
        expected = float(raw.replace(",", "."))
        values: list[float] = []
        for uri in spec.targets:
            node = snapshot.objects.get(uri)
            if not node:
                continue
            key = parameter.rsplit(".", 1)[-1]
            if key in node.parameters and isinstance(node.parameters[key].value, (int, float)):
                values.append(float(node.parameters[key].value))
        if not values:
            findings.append(f"unresolved: {expression}")
            continue
        if not all(_compare(value, operator, expected) for value in values):
            findings.append(f"blocking: {expression}")
    for operation in candidate.proposed_changes:
        if not _uri_in_scope(operation.target_uri, spec.targets):
            findings.append(f"blocking: operation target outside scope: {operation.target_uri}")
    return findings


def _compare(value: float, operator: str, expected: float) -> bool:
    return {
        ">=": value >= expected,
        "<=": value <= expected,
        "==": math.isclose(value, expected),
        ">": value > expected,
        "<": value < expected,
    }[operator]
