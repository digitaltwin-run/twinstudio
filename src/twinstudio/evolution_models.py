from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from twinstudio.domain import (
    ArtifactKind,
    ChangeOperation,
    ChangeOperationKind,
    LifecycleStage,
    Role,
    StrictModel,
    utcnow,
)
from twinstudio.model_validation import require_unique_attribute, validate_evaluation_weights


class EvolutionMethod(str, Enum):
    GOAL_LADDER = "goal_ladder"
    OBJECT_DECOMPOSITION = "object_decomposition"
    BIDIRECTIONAL_GRAPH = "bidirectional_graph"
    FEATURE_LENSES = "feature_lenses"
    ADJACENT_POSSIBLE = "adjacent_possible"
    BRAINSWARM = "brainswarm"
    ANALOGY = "analogy"
    ASSUMPTION_REVERSAL = "assumption_reversal"
    CONSTRAINT_RELAXATION = "constraint_relaxation"
    MUTATION = "mutation"
    RECOMBINATION = "recombination"
    EXPERIMENT = "experiment"


class EvolutionPhase(str, Enum):
    INTAKE = "intake"
    FRAME = "frame"
    GOAL_EXPANSION = "goal_expansion"
    ASSUMPTION_DISCOVERY = "assumption_discovery"
    RESOURCE_DECOMPOSITION = "resource_decomposition"
    BRIDGE_BUILDING = "bridge_building"
    DIVERGENCE = "divergence"
    ADJACENT_POSSIBLE = "adjacent_possible"
    CONVERGENCE = "convergence"
    PROTOTYPE = "prototype"
    EXPERIMENT = "experiment"
    SELECTION = "selection"
    REALIZATION = "realization"
    VERIFICATION = "verification"
    LEARNING = "learning"
    RELEASE = "release"
    ARCHIVE = "archive"


class EvolutionRunStatus(str, Enum):
    DRAFT = "draft"
    COMPILED = "compiled"
    RUNNING = "running"
    BLOCKED = "blocked"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ActionRelation(str, Enum):
    SEED = "seed"
    HYPERNYM = "hypernym"
    HYPONYM = "hyponym"
    SYNONYM = "synonym"
    SIBLING = "sibling"
    OPPOSITE = "opposite"
    RELATED = "related"
    CUSTOM = "custom"


class ResourceKind(str, Enum):
    OBJECT = "object"
    PART = "part"
    FEATURE = "feature"
    PARAMETER = "parameter"
    MATERIAL = "material"
    PROCESS = "process"
    ARTIFACT = "artifact"
    ENERGY = "energy"
    HUMAN_ACTION = "human_action"
    ENVIRONMENT = "environment"
    INTERFACE = "interface"
    REQUIREMENT = "requirement"
    EVIDENCE = "evidence"


class MutationOperatorKind(str, Enum):
    REFRAME_GOAL = "reframe_goal"
    REPURPOSE_FEATURE = "repurpose_feature"
    PARAMETER_SHIFT = "parameter_shift"
    INVERT_RELATION = "invert_relation"
    COMBINE_PARTS = "combine_parts"
    SPLIT_PART = "split_part"
    REMOVE_PART = "remove_part"
    DUPLICATE_FEATURE = "duplicate_feature"
    SUBSTITUTE_MATERIAL = "substitute_material"
    SUBSTITUTE_PROCESS = "substitute_process"
    CHANGE_STATE = "change_state"
    CHANGE_ENERGY = "change_energy"
    MOVE_FUNCTION = "move_function"
    MODULARIZE = "modularize"
    MAKE_REVERSIBLE = "make_reversible"
    ADD_OBSERVABILITY = "add_observability"
    ADJACENT_ASSOCIATION = "adjacent_association"
    CROSSOVER = "crossover"


class EvaluationDimension(str, Enum):
    FEASIBILITY = "feasibility"
    NOVELTY = "novelty"
    MANUFACTURABILITY = "manufacturability"
    EVIDENCE = "evidence"
    RISK_CONTROL = "risk_control"
    REVERSIBILITY = "reversibility"
    SUSTAINABILITY = "sustainability"
    COST_VALUE = "cost_value"
    USER_VALUE = "user_value"
    LIFECYCLE_FIT = "lifecycle_fit"


class RealizationMode(str, Enum):
    ANALYSIS_ONLY = "analysis_only"
    CHANGE_PLAN = "change_plan"
    AUTO_APPLY_SAFE = "auto_apply_safe"


class CandidateStatus(str, Enum):
    PROPOSED = "proposed"
    SHORTLISTED = "shortlisted"
    SELECTED = "selected"
    REJECTED = "rejected"
    REALIZED = "realized"
    VERIFIED = "verified"


class StageRunStatus(str, Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class DslSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKING = "blocking"


class EvolutionGoal(StrictModel):
    statement: str = Field(min_length=3, max_length=30_000)
    verb: str | None = None
    object_phrase: str = ""
    outcomes: list[str] = Field(default_factory=list)
    preserve: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class ActionSearchSpec(StrictModel):
    seed_verbs: list[str] = Field(default_factory=list)
    up_depth: int = Field(default=1, ge=0, le=5)
    down_depth: int = Field(default=2, ge=0, le=5)
    sideways_depth: int = Field(default=1, ge=0, le=5)
    include_opposites: bool = True
    max_terms: int = Field(default=40, ge=1, le=250)


class ResourceSearchSpec(StrictModel):
    include_descendants: bool = True
    include_features: bool = True
    include_parameters: bool = True
    include_materials: bool = True
    include_processes: bool = True
    include_artifacts: bool = True
    include_requirements: bool = True
    include_evidence: bool = True
    include_human_actions: bool = True
    include_environment: bool = True
    max_resources: int = Field(default=250, ge=1, le=5000)


class LensSearchSpec(StrictModel):
    include_source_lenses: bool = True
    include_extension_dimensions: bool = True
    source_lens_ids: list[str] = Field(default_factory=list)
    extension_dimension_ids: list[str] = Field(default_factory=list)
    ask_hidden_assumptions: bool = True
    max_lenses: int = Field(default=100, ge=1, le=250)


class EvolutionOperatorSpec(StrictModel):
    operator: MutationOperatorKind
    weight: float = Field(default=1.0, gt=0.0, le=100.0)
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


def default_evolution_operators() -> list[EvolutionOperatorSpec]:
    return [
        EvolutionOperatorSpec(operator=MutationOperatorKind.REFRAME_GOAL, weight=1.0),
        EvolutionOperatorSpec(operator=MutationOperatorKind.REPURPOSE_FEATURE, weight=1.0),
        EvolutionOperatorSpec(operator=MutationOperatorKind.PARAMETER_SHIFT, weight=0.9),
        EvolutionOperatorSpec(operator=MutationOperatorKind.MODULARIZE, weight=0.8),
        EvolutionOperatorSpec(operator=MutationOperatorKind.MAKE_REVERSIBLE, weight=0.7),
        EvolutionOperatorSpec(operator=MutationOperatorKind.SUBSTITUTE_PROCESS, weight=0.6),
        EvolutionOperatorSpec(operator=MutationOperatorKind.ADJACENT_ASSOCIATION, weight=1.0),
        EvolutionOperatorSpec(operator=MutationOperatorKind.CROSSOVER, weight=0.4),
    ]


class EvolutionPolicy(StrictModel):
    generations: int = Field(default=3, ge=1, le=20)
    population_size: int = Field(default=12, ge=1, le=200)
    offspring_per_candidate: int = Field(default=2, ge=1, le=20)
    mutation_rate: float = Field(default=0.8, ge=0.0, le=1.0)
    crossover_rate: float = Field(default=0.25, ge=0.0, le=1.0)
    adjacent_possible_depth: int = Field(default=2, ge=0, le=5)
    deterministic_seed: int = 17
    operators: list[EvolutionOperatorSpec] = Field(default_factory=default_evolution_operators)


class EvaluationPolicy(StrictModel):
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            EvaluationDimension.FEASIBILITY.value: 0.20,
            EvaluationDimension.NOVELTY.value: 0.12,
            EvaluationDimension.MANUFACTURABILITY.value: 0.18,
            EvaluationDimension.EVIDENCE.value: 0.10,
            EvaluationDimension.RISK_CONTROL.value: 0.12,
            EvaluationDimension.REVERSIBILITY.value: 0.08,
            EvaluationDimension.SUSTAINABILITY.value: 0.06,
            EvaluationDimension.COST_VALUE.value: 0.06,
            EvaluationDimension.USER_VALUE.value: 0.04,
            EvaluationDimension.LIFECYCLE_FIT.value: 0.04,
        }
    )
    hard_constraints: list[str] = Field(default_factory=list)
    select_top: int = Field(default=5, ge=1, le=50)
    minimum_overall_score: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("weights")
    @classmethod
    def validate_weights(cls, value: dict[str, float]) -> dict[str, float]:
        return validate_evaluation_weights(value, {item.value for item in EvaluationDimension})


class LifecycleProgramSpec(StrictModel):
    template_id: str = "hardware-product"
    start_stage: LifecycleStage = LifecycleStage.PROBLEM_FRAMING
    target_stage: LifecycleStage = LifecycleStage.RELEASE
    enabled_stages: list[LifecycleStage] = Field(default_factory=list)
    disabled_stages: list[LifecycleStage] = Field(default_factory=list)
    auto_advance: bool = False
    approval_required: bool = True


class EvolutionGateSpec(StrictModel):
    phase: EvolutionPhase
    expressions: list[str] = Field(default_factory=list)
    approver_roles: list[Role] = Field(default_factory=lambda: [Role.CREATOR, Role.ADMIN])
    blocking: bool = True
    notes: str = ""


class RealizationPolicy(StrictModel):
    mode: RealizationMode = RealizationMode.CHANGE_PLAN
    dry_run: bool = True
    allowed_operations: list[ChangeOperationKind] = Field(
        default_factory=lambda: [
            ChangeOperationKind.SET_PARAMETER,
            ChangeOperationKind.ADD_FEATURE,
            ChangeOperationKind.SUPPRESS_FEATURE,
            ChangeOperationKind.TRANSFORM_FEATURE,
            ChangeOperationKind.BOOLEAN_CUT,
            ChangeOperationKind.BOOLEAN_ADD,
            ChangeOperationKind.UPDATE_MANUFACTURING,
            ChangeOperationKind.ADD_TEST,
            ChangeOperationKind.ATTACH_REQUIREMENT,
            ChangeOperationKind.ADD_ANNOTATION,
        ]
    )
    max_change_plans: int = Field(default=3, ge=0, le=20)
    require_approval: bool = True


class EvolutionOutputSpec(StrictModel):
    graph_formats: list[Literal["json", "dot", "mermaid"]] = Field(
        default_factory=lambda: ["json", "dot", "mermaid"]
    )
    report_formats: list[Literal["json", "markdown", "csv"]] = Field(
        default_factory=lambda: ["json", "markdown", "csv"]
    )
    include_change_plans: bool = True
    persist_artifacts: bool = True


class EvolutionProgramSpec(StrictModel):
    project_id: str
    base_revision: str = "main"
    targets: list[str] = Field(min_length=1)
    goal: EvolutionGoal
    methods: list[EvolutionMethod] = Field(
        default_factory=lambda: [
            EvolutionMethod.GOAL_LADDER,
            EvolutionMethod.OBJECT_DECOMPOSITION,
            EvolutionMethod.BIDIRECTIONAL_GRAPH,
            EvolutionMethod.FEATURE_LENSES,
            EvolutionMethod.ADJACENT_POSSIBLE,
            EvolutionMethod.BRAINSWARM,
            EvolutionMethod.MUTATION,
            EvolutionMethod.RECOMBINATION,
            EvolutionMethod.EXPERIMENT,
        ]
    )
    action_search: ActionSearchSpec = Field(default_factory=ActionSearchSpec)
    resources: ResourceSearchSpec = Field(default_factory=ResourceSearchSpec)
    lenses: LensSearchSpec = Field(default_factory=LensSearchSpec)
    evolution: EvolutionPolicy = Field(default_factory=EvolutionPolicy)
    evaluation: EvaluationPolicy = Field(default_factory=EvaluationPolicy)
    lifecycle: LifecycleProgramSpec = Field(default_factory=LifecycleProgramSpec)
    gates: list[EvolutionGateSpec] = Field(default_factory=list)
    explicit_changes: list[ChangeOperation] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    realization: RealizationPolicy = Field(default_factory=RealizationPolicy)
    outputs: EvolutionOutputSpec = Field(default_factory=EvolutionOutputSpec)
    notes: list[str] = Field(default_factory=list)


class DslMetadata(StrictModel):
    name: str = Field(min_length=3, max_length=200)
    namespace: str = "default"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)


class TwinDslDocument(StrictModel):
    api_version: Literal["twinstudio.io/v1alpha1"] = "twinstudio.io/v1alpha1"
    kind: Literal["EvolutionProgram"] = "EvolutionProgram"
    metadata: DslMetadata
    spec: EvolutionProgramSpec


class GoalVariant(StrictModel):
    node_id: str
    phrase: str
    verb: str
    relation: ActionRelation
    parent_id: str | None = None
    depth: int = 0
    assumptions: list[str] = Field(default_factory=list)
    source: Literal["catalog", "human", "litellm", "derived"] = "derived"


class EvolutionResource(StrictModel):
    node_id: str
    kind: ResourceKind
    label: str
    uri: str | None = None
    parent_id: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    associations: list[str] = Field(default_factory=list)
    evidence_uris: list[str] = Field(default_factory=list)


class EvolutionGraphNode(StrictModel):
    node_id: str
    side: Literal["goal", "resource", "bridge", "idea"]
    label: str
    kind: str
    data: dict[str, Any] = Field(default_factory=dict)


class EvolutionGraphEdge(StrictModel):
    source: str
    target: str
    relation: str
    score: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = ""


class EvolutionGraph(StrictModel):
    nodes: list[EvolutionGraphNode] = Field(default_factory=list)
    edges: list[EvolutionGraphEdge] = Field(default_factory=list)


class CandidateEvaluation(StrictModel):
    dimension: EvaluationDimension
    score: float = Field(ge=0.0, le=1.0)
    rationale: str = ""
    evidence_uris: list[str] = Field(default_factory=list)


class EvolutionCandidate(StrictModel):
    candidate_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    summary: str
    generation: int = Field(default=0, ge=0)
    parent_ids: list[str] = Field(default_factory=list)
    methods: list[EvolutionMethod] = Field(default_factory=list)
    goal_node_ids: list[str] = Field(default_factory=list)
    resource_node_ids: list[str] = Field(default_factory=list)
    bridge_edge_ids: list[str] = Field(default_factory=list)
    lens_ids: list[str] = Field(default_factory=list)
    operators: list[EvolutionOperatorSpec] = Field(default_factory=list)
    assumptions_challenged: list[str] = Field(default_factory=list)
    proposed_changes: list[ChangeOperation] = Field(default_factory=list)
    expected_benefits: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    evaluations: list[CandidateEvaluation] = Field(default_factory=list)
    overall_score: float = Field(default=0.0, ge=0.0, le=1.0)
    constraint_violations: list[str] = Field(default_factory=list)
    status: CandidateStatus = CandidateStatus.PROPOSED
    source: Literal["local", "litellm", "human", "dsl"] = "local"


class EvolutionStageRecord(StrictModel):
    phase: EvolutionPhase
    status: StageRunStatus = StageRunStatus.NOT_STARTED
    input_ids: list[str] = Field(default_factory=list)
    output_ids: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class EvolutionRun(StrictModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    uri: str
    project_id: str
    base_revision: str
    program: TwinDslDocument
    goal_variants: list[GoalVariant] = Field(default_factory=list)
    resources: list[EvolutionResource] = Field(default_factory=list)
    graph: EvolutionGraph = Field(default_factory=EvolutionGraph)
    candidates: list[EvolutionCandidate] = Field(default_factory=list)
    selected_candidate_ids: list[str] = Field(default_factory=list)
    stages: list[EvolutionStageRecord] = Field(default_factory=list)
    lifecycle_stage: LifecycleStage = LifecycleStage.CONCEPT
    status: EvolutionRunStatus = EvolutionRunStatus.COMPILED
    planner: str = "local-evolution-engine"
    warnings: list[str] = Field(default_factory=list)
    created_by: str
    created_at: datetime = Field(default_factory=utcnow)


class LifecycleStageDefinition(StrictModel):
    stage: LifecycleStage
    name: str
    purpose: str = ""
    entry_criteria: list[str] = Field(default_factory=list)
    exit_criteria: list[str] = Field(default_factory=list)
    required_artifact_kinds: list[ArtifactKind] = Field(default_factory=list)
    required_test_types: list[str] = Field(default_factory=list)
    recommended_evolution_methods: list[EvolutionMethod] = Field(default_factory=list)
    allowed_change_operations: list[ChangeOperationKind] = Field(default_factory=list)
    approver_roles: list[Role] = Field(default_factory=lambda: [Role.ADMIN, Role.CREATOR])
    optional: bool = False
    repeatable: bool = False


class LifecycleTransition(StrictModel):
    from_stage: LifecycleStage
    to_stage: LifecycleStage
    conditions: list[str] = Field(default_factory=list)
    required_gate_status: Literal["not_started", "in_progress", "blocked", "approved", "rejected"] = "approved"
    approver_roles: list[Role] = Field(default_factory=lambda: [Role.ADMIN, Role.CREATOR])


class LifecycleBlueprint(StrictModel):
    blueprint_id: str
    name: str
    version: str = "1"
    stages: list[LifecycleStageDefinition]
    transitions: list[LifecycleTransition] = Field(default_factory=list)
    current_stage: LifecycleStage = LifecycleStage.EVIDENCE
    tailored: bool = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_stage_graph(self) -> "LifecycleBlueprint":
        stage_ids = [item.stage for item in self.stages]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("LifecycleBlueprint stages must be unique")
        if self.current_stage not in set(stage_ids):
            raise ValueError("LifecycleBlueprint current_stage must exist in stages")
        allowed = set(stage_ids)
        for transition in self.transitions:
            if transition.from_stage not in allowed or transition.to_stage not in allowed:
                raise ValueError("Lifecycle transition references a stage outside the blueprint")
        return self


class LifecycleTransitionRequest(StrictModel):
    blueprint_id: str = "hardware-product"
    to_stage: LifecycleStage
    evidence_artifact_uris: list[str] = Field(default_factory=list)
    rationale: str = ""
    approve: bool = False


class LifecycleHistoryEntry(StrictModel):
    transition_id: str = Field(default_factory=lambda: str(uuid4()))
    blueprint_id: str
    from_stage: LifecycleStage
    to_stage: LifecycleStage
    rationale: str = ""
    evidence_artifact_uris: list[str] = Field(default_factory=list)
    unmet_criteria: list[str] = Field(default_factory=list)
    approved_by: str | None = None
    status: Literal["requested", "approved", "blocked", "rejected"] = "requested"
    occurred_at: datetime = Field(default_factory=utcnow)


class DslDiagnostic(StrictModel):
    severity: DslSeverity
    code: str
    message: str
    line: int | None = None
    column: int | None = None
    path: str = ""
    hint: str = ""


class DslCompilation(StrictModel):
    document: TwinDslDocument | None = None
    diagnostics: list[DslDiagnostic] = Field(default_factory=list)
    evolution_run: EvolutionRun | None = None
    change_plans: list[dict[str, Any]] = Field(default_factory=list)
    lifecycle_blueprint: LifecycleBlueprint | None = None
    event_previews: list[dict[str, Any]] = Field(default_factory=list)
    valid: bool = False


class DslExecutionRecord(StrictModel):
    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    uri: str
    document_name: str
    document_hash: str
    api_version: str
    kind: str
    project_id: str
    base_revision: str
    source_format: Literal["twin", "yaml", "json"]
    source_text: str
    dry_run: bool = True
    status: Literal["validated", "compiled", "executed", "partially_executed", "rejected"] = "compiled"
    command_types: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    created_by: str
    created_at: datetime = Field(default_factory=utcnow)

class VerbRelationSet(StrictModel):
    synonyms: list[str] = Field(default_factory=list)
    hypernyms: list[str] = Field(default_factory=list)
    hyponyms: list[str] = Field(default_factory=list)
    opposites: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    associations: list[str] = Field(default_factory=list)


class ExtensionDimension(StrictModel):
    id: str
    name: str
    category: str
    summary: str
    associations: list[str] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)
    origin: Literal["twinstudio_extension"] = "twinstudio_extension"


class OperatorDefinition(StrictModel):
    id: str
    kind: MutationOperatorKind
    description: str


class LifecycleTemplate(StrictModel):
    name: str
    stages: list[LifecycleStage]


class EvolutionLifecyclePhaseDefinition(StrictModel):
    phase: EvolutionPhase
    name: str
    objective: str = ""
    entry_criteria: list[str] = Field(default_factory=list)
    exit_criteria: list[str] = Field(default_factory=list)
    required_outputs: list[str] = Field(default_factory=list)
    approver_roles: list[Role] = Field(default_factory=list)


class LifecycleFeedbackLoop(StrictModel):
    from_phase: EvolutionPhase = Field(alias="from")
    to_phase: EvolutionPhase = Field(alias="to")


class EvolutionLifecycleTemplate(StrictModel):
    template_id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    feedback_loops: list[LifecycleFeedbackLoop] = Field(default_factory=list)
    stages: list[EvolutionLifecyclePhaseDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_phases(self) -> "EvolutionLifecycleTemplate":
        phases = [item.phase for item in self.stages]
        if len(phases) != len(set(phases)):
            raise ValueError("Evolution lifecycle phases must be unique")
        known = set(phases)
        for loop in self.feedback_loops:
            if loop.from_phase not in known or loop.to_phase not in known:
                raise ValueError("Lifecycle feedback loop references an unknown phase")
        return self


class LifecycleTemplateCatalog(StrictModel):
    catalog_version: str
    templates: list[EvolutionLifecycleTemplate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_template_ids(self) -> "LifecycleTemplateCatalog":
        require_unique_attribute(self.templates, "template_id", "Lifecycle template IDs")
        return self


class EvolutionCatalog(StrictModel):
    catalog_version: str
    title: str
    source_notes: list[str] = Field(default_factory=list)
    verb_graph: dict[str, VerbRelationSet] = Field(default_factory=dict)
    extension_dimensions: list[ExtensionDimension] = Field(default_factory=list)
    operators: list[OperatorDefinition] = Field(default_factory=list)
    lifecycle_templates: dict[str, LifecycleTemplate] = Field(default_factory=dict)
