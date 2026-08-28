from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=True)


class Role(str, Enum):
    READER = "reader"
    EDITOR = "editor"
    ADMIN = "admin"
    CREATOR = "creator"


class ObjectKind(str, Enum):
    DEVICE = "device"
    ASSEMBLY = "assembly"
    PART = "part"
    PURCHASED_COMPONENT = "purchased_component"
    PCB = "pcb"
    SCHEMATIC = "schematic"
    CAMERA = "camera"
    FASTENER = "fastener"
    POWER_SUPPLY = "power_supply"
    SOFTWARE = "software"
    CONTAINER_IMAGE = "container_image"
    TEST_FIXTURE = "test_fixture"
    PACKAGING = "packaging"
    DOCUMENT = "document"
    ECOMMERCE_OFFER = "ecommerce_offer"
    SIMULATION_MODEL = "simulation_model"
    REFERENCE = "reference"


class MakeBuy(str, Enum):
    MAKE = "make"
    BUY = "buy"
    OUTSOURCE = "outsource"
    VIRTUAL = "virtual"
    REFERENCE_ONLY = "reference_only"


class ProcessKind(str, Enum):
    FDM_PRINT = "fdm_print"
    SLA_PRINT = "sla_print"
    CNC_MILLING = "cnc_milling"
    LASER_CUT = "laser_cut"
    INJECTION_MOLD = "injection_mold"
    PCB_FAB = "pcb_fab"
    ASSEMBLY = "assembly"
    PURCHASE = "purchase"
    SOFTWARE_BUILD = "software_build"
    PACKAGING = "packaging"
    NONE = "none"


class LifecycleStage(str, Enum):
    EVIDENCE = "evidence_intake"
    DISCOVERY = "discovery"
    PROBLEM_FRAMING = "problem_framing"
    OPPORTUNITY = "opportunity"
    REQUIREMENTS = "requirements"
    GOAL_REFRAMING = "goal_reframing"
    IDEATION = "ideation"
    CONCEPT = "concept"
    FEASIBILITY = "feasibility"
    ARCHITECTURE = "architecture"
    DETAILED_DESIGN = "detailed_design"
    DESIGN_REVIEW = "design_review"
    PROTOTYPE = "prototype"
    INTEGRATION = "integration"
    ENGINEERING_VERIFICATION = "engineering_verification"
    VERIFICATION = "verification"
    VALIDATION = "validation"
    COMPLIANCE = "compliance"
    PILOT = "pilot"
    PILOT_PRODUCTION = "pilot_production"
    INDUSTRIALIZATION = "industrialization"
    RELEASE = "release"
    PRODUCTION = "production"
    QUALITY_CONTROL = "quality_control"
    FULFILLMENT = "fulfillment"
    DEPLOYMENT = "deployment"
    OPERATION = "operation"
    OBSERVATION = "observation"
    MONITORING = "monitoring"
    MAINTENANCE = "maintenance"
    SERVICE = "service"
    IMPROVEMENT = "improvement"
    EVOLUTION = "evolution"
    UPGRADE = "upgrade"
    RECALL = "recall"
    REUSE = "reuse"
    REUSE_REMANUFACTURE = "reuse_remanufacture"
    RETIREMENT = "retirement"
    DECOMMISSION = "decommission"
    RECYCLING = "recycling"
    CIRCULAR_RECOVERY = "circular_recovery"
    END_OF_LIFE = "end_of_life"

class ArtifactKind(str, Enum):
    PHOTO = "photo"
    VIDEO = "video"
    PDF = "pdf"
    DRAWING_2D = "drawing_2d"
    CAD_SOURCE = "cad_source"
    STEP = "step"
    STL = "stl"
    OBJ = "obj"
    GLB = "glb"
    PCB = "pcb"
    SCHEMATIC = "schematic"
    GERBER = "gerber"
    BOM = "bom"
    SOFTWARE_SOURCE = "software_source"
    CONTAINER_IMAGE = "container_image"
    TEST_RESULT = "test_result"
    SIMULATION_RESULT = "simulation_result"
    PRODUCT_LISTING = "product_listing"
    OTHER = "other"


class SelectionTool(str, Enum):
    POINTER = "pointer"
    PENCIL = "pencil"
    LASSO = "lasso"
    RECTANGLE = "rectangle"
    BRUSH = "brush"


class SourceView(str, Enum):
    VIEW_3D = "3d"
    DRAWING_2D = "2d"
    PHOTO = "photo"
    PCB = "pcb"
    SCHEMATIC = "schematic"


class FeatureLensCategory(str, Enum):
    STATIC_PHYSICAL = "static_physical"
    DYNAMIC_PHYSICAL = "dynamic_physical"
    RELATIONAL_PHYSICAL = "relational_physical"
    FUNCTIONAL_BEHAVIORAL = "functional_behavioral"
    INTERFACE_SYSTEM = "interface_system"
    LIFECYCLE_VALUE = "lifecycle_value"
    DIGITAL_CONTROL = "digital_control"
    SAFETY_RISK = "safety_risk"
    SUSTAINABILITY_COMPLIANCE = "sustainability_compliance"
    EVIDENCE_DECISION = "evidence_decision"
    SYSTEMIC = "systemic"
    LIFECYCLE = "lifecycle"
    MANUFACTURING = "manufacturing"
    HUMAN = "human"
    DIGITAL = "digital"
    COMMERCIAL = "commercial"
    GOVERNANCE = "governance"
    SUSTAINABILITY = "sustainability"
    SOURCE_GAP = "source_gap"

class LensObservationStatus(str, Enum):
    OBSERVED = "observed"
    PARTLY_OBSERVED = "partly_observed"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class DesignIdeaSource(str, Enum):
    LOCAL = "local"
    LITELLM = "litellm"
    HUMAN = "human"


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


class ChangeOperationKind(str, Enum):
    SET_PARAMETER = "set_parameter"
    ADD_FEATURE = "add_feature"
    SUPPRESS_FEATURE = "suppress_feature"
    TRANSFORM_FEATURE = "transform_feature"
    BOOLEAN_CUT = "boolean_cut"
    BOOLEAN_ADD = "boolean_add"
    REPLACE_COMPONENT = "replace_component"
    UPDATE_MANUFACTURING = "update_manufacturing"
    ATTACH_REQUIREMENT = "attach_requirement"
    ADD_TEST = "add_test"
    ADD_ANNOTATION = "add_annotation"


class Quantity(StrictModel):
    value: float
    unit: str = "mm"
    tolerance_plus: float | None = None
    tolerance_minus: float | None = None


class ParameterValue(StrictModel):
    value: str | int | float | bool
    unit: str | None = None
    status: Literal["proposed", "approved", "measured", "derived", "deprecated"] = "approved"
    source_uri: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    notes: str = ""


class EvidenceClaim(StrictModel):
    claim_id: str = Field(default_factory=lambda: str(uuid4()))
    subject_uri: str
    predicate: str
    value: Any
    unit: str | None = None
    source_artifact_uri: str
    source_region_uri: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: Literal["proposed", "approved", "rejected", "superseded"] = "proposed"
    extracted_by: str = "human"
    created_at: datetime = Field(default_factory=utcnow)


class ManufacturingSpec(StrictModel):
    make_buy: MakeBuy = MakeBuy.MAKE
    process: ProcessKind = ProcessKind.NONE
    material: str | None = None
    finish: str | None = None
    machine_profile: str | None = None
    supplier: str | None = None
    supplier_part_number: str | None = None
    lead_time_days: float | None = None
    unit_cost: float | None = None
    currency: str = "EUR"
    notes: str = ""


class InclusionSpec(StrictModel):
    physical_product: bool = True
    print_job: bool = False
    cnc_job: bool = False
    purchase_order: bool = False
    pcb_fabrication: bool = False
    software_release: bool = False
    ecommerce_package: bool = False
    documentation: bool = True
    simulation: bool = True
    reference_only: bool = False


class FeatureSpec(StrictModel):
    uri: str
    name: str
    feature_type: str
    parameters: dict[str, ParameterValue] = Field(default_factory=dict)
    semantic_faces: list[str] = Field(default_factory=list)
    enabled: bool = True
    generated_by: str = "parametric"
    notes: str = ""


class ObjectNode(StrictModel):
    uri: str
    parent_uri: str | None = None
    name: str
    kind: ObjectKind
    description: str = ""
    quantity: float = 1.0
    revision: str = "main"
    parameters: dict[str, ParameterValue] = Field(default_factory=dict)
    features: list[FeatureSpec] = Field(default_factory=list)
    manufacturing: ManufacturingSpec = Field(default_factory=ManufacturingSpec)
    inclusion: InclusionSpec = Field(default_factory=InclusionSpec)
    artifact_uris: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactRecord(StrictModel):
    uri: str
    name: str
    kind: ArtifactKind
    path: str
    media_type: str = "application/octet-stream"
    object_uri: str | None = None
    revision: str = "main"
    sha256: str | None = None
    size_bytes: int | None = None
    generated: bool = False
    source: bool = False
    downloadable: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScreenPoint(StrictModel):
    x: float
    y: float


class WorldPoint(StrictModel):
    x: float
    y: float
    z: float


class CameraState(StrictModel):
    projection: Literal["perspective", "orthographic"] = "perspective"
    position: WorldPoint
    target: WorldPoint
    up: WorldPoint
    fov: float | None = None
    zoom: float | None = None
    viewport_width: int = Field(gt=0)
    viewport_height: int = Field(gt=0)


class RayHit(StrictModel):
    object_uri: str
    mesh_hash: str | None = None
    face_index: int | None = None
    semantic_face_uri: str | None = None
    brep_face_id: str | None = None
    point: WorldPoint
    normal: WorldPoint | None = None
    distance: float | None = None


class WorldAabb(StrictModel):
    minimum: WorldPoint
    maximum: WorldPoint


class ProjectionEntityBinding(StrictModel):
    entity_id: str
    source_artifact_uri: str
    object_uri: str
    feature_uri: str | None = None
    semantic_face_uri: str | None = None
    brep_face_id: str | None = None
    mapping_type: Literal["orthographic", "calibrated_photo", "manual", "derived"] = "manual"
    source_to_world_matrix: list[float] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectionMap(StrictModel):
    uri: str
    source_artifact_uri: str
    source_view: SourceView
    target_revision: str
    entities: dict[str, ProjectionEntityBinding] = Field(default_factory=dict)
    calibration: dict[str, Any] = Field(default_factory=dict)
    status: Literal["draft", "calibrated", "verified", "stale"] = "draft"
    created_by: str
    created_at: datetime = Field(default_factory=utcnow)


class SelectionDiagnostic(StrictModel):
    severity: Literal["info", "warning", "error", "blocking"]
    code: str
    message: str
    target_uris: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class SelectionMap(StrictModel):
    uri: str
    selection_uri: str
    target_revision: str
    resolved_object_uris: list[str] = Field(default_factory=list)
    resolved_feature_uris: list[str] = Field(default_factory=list)
    resolved_semantic_face_uris: list[str] = Field(default_factory=list)
    resolved_brep_face_ids: list[str] = Field(default_factory=list)
    algorithm: str = "semantic-plus-projection"
    status: Literal["resolved", "partial", "unresolved", "stale"] = "unresolved"
    diagnostics: list[SelectionDiagnostic] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: str
    created_at: datetime = Field(default_factory=utcnow)


class RegionSelection(StrictModel):
    selection_id: str = Field(default_factory=lambda: str(uuid4()))
    uri: str
    project_id: str
    project_revision: str
    source_view: SourceView
    tool: SelectionTool
    target_object_uris: list[str] = Field(min_length=1)
    screen_path: list[ScreenPoint] = Field(default_factory=list)
    ray_hits: list[RayHit] = Field(default_factory=list)
    world_aabb: WorldAabb | None = None
    camera: CameraState | None = None
    source_artifact_uri: str | None = None
    projection_entity_ids: list[str] = Field(default_factory=list)
    notes: str = ""
    created_by: str
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def validate_evidence(self) -> "RegionSelection":
        if self.source_view == SourceView.VIEW_3D and not self.ray_hits:
            raise ValueError("A 3D selection requires at least one ray hit")
        if self.source_view in {SourceView.DRAWING_2D, SourceView.PHOTO} and not self.screen_path:
            raise ValueError("A 2D/photo selection requires a screen path")
        return self


class Annotation(StrictModel):
    uri: str
    selection: RegionSelection
    text: str
    status: Literal["open", "resolved", "rejected"] = "open"
    created_by: str
    created_at: datetime = Field(default_factory=utcnow)


class NaturalLanguageSource(StrictModel):
    """Typed, integrity-bound natural-language input at the planner boundary."""

    schema_version: Literal["twinstudio.nl-source/v1"] = "twinstudio.nl-source/v1"
    text: str = Field(min_length=1, max_length=20_000)
    language: str = Field(default="und", pattern=r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$|^und$")
    media_type: Literal["text/plain"] = "text/plain"
    provenance: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        language: str = "und",
        provenance: str,
    ) -> "NaturalLanguageSource":
        return cls(
            text=text,
            language=language,
            provenance=provenance,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )

    @model_validator(mode="after")
    def validate_digest(self) -> "NaturalLanguageSource":
        observed = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if observed != self.sha256:
            raise ValueError("sha256 does not match the UTF-8 natural-language source")
        return self


class ChangeOperation(StrictModel):
    operation_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: ChangeOperationKind
    target_uri: str
    selector: dict[str, Any] = Field(default_factory=dict)
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reversible: bool = True
    validation_steps: list[str] = Field(default_factory=list)


class ChangeOperationProposal(StrictModel):
    """Operation fields an LLM may propose before runtime elevation."""

    kind: ChangeOperationKind
    target_uri: str
    selector: dict[str, Any] = Field(default_factory=dict)
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    validation_steps: list[str] = Field(default_factory=list)


class ImpactItem(StrictModel):
    uri: str
    impact: Literal["direct", "dependent", "manufacturing", "test", "software", "commercial"]
    summary: str


class ChangePlanProposal(StrictModel):
    """Schema-constrained LLM output; runtime-owned identity and authority are absent."""

    operations: list[ChangeOperationProposal]
    impact: list[ImpactItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


class ChangePlanLlmRequest(StrictModel):
    """Complete semantic payload sent to an LLM change planner."""

    schema_version: Literal["twinstudio.change-plan-request/v1"] = (
        "twinstudio.change-plan-request/v1"
    )
    project_id: str
    base_revision: str
    source: NaturalLanguageSource
    selection: RegionSelection
    selected_context: list[dict[str, Any]]
    allowed_operations: list[ChangeOperationKind]


class InvalidLlmResponseArtifact(StrictModel):
    """Integrity-safe evidence that an LLM response failed strict validation."""

    schema_version: Literal["twinstudio.invalid-llm-response/v1"] = (
        "twinstudio.invalid-llm-response/v1"
    )
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_length: int = Field(ge=0)
    validation_error: str
    received_at: datetime = Field(default_factory=utcnow)

    @classmethod
    def from_content(cls, content: str, validation_error: str) -> "InvalidLlmResponseArtifact":
        return cls(
            response_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            response_length=len(content),
            validation_error=validation_error,
        )


class ChangeExecutionAuthority(StrictModel):
    """Runtime-minted authorization receipt for a controlled change effect."""

    schema_version: Literal["twinstudio.change-authority/v1"] = (
        "twinstudio.change-authority/v1"
    )
    actor: str
    role: Role
    permission: Literal["change.apply"] = "change.apply"
    project_id: str
    plan_id: str
    decision: Literal["authorized"] = "authorized"
    authorization_source: Literal["project_membership"] = "project_membership"
    issued_at: datetime = Field(default_factory=utcnow)


class ChangePlan(StrictModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    base_revision: str
    prompt: str
    selection_uri: str
    selected_scope_uris: list[str]
    operations: list[ChangeOperation]
    impact: list[ImpactItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    requires_approval: bool = True
    planner: str = "local"
    created_by: str
    created_at: datetime = Field(default_factory=utcnow)


class FeatureLens(StrictModel):
    id: str
    order: int = Field(ge=1)
    name: str
    category: FeatureLensCategory
    summary: str
    prompts: list[str] = Field(default_factory=list)
    enabled: bool = True
    source_status: Literal["transcribed", "duplicate_label", "unresolved", "extension", "twinstudio_extension"] = "transcribed"
    provenance: str = "source_material"
    tags: list[str] = Field(default_factory=list)

class FeatureLensCatalog(StrictModel):
    catalog_version: str
    title: str
    declared_lens_count: int = Field(ge=1)
    active_lens_count: int = Field(ge=0)
    catalog_kind: Literal["source_grounded", "twinstudio_extension", "combined"] = "source_grounded"
    source_notes: list[str] = Field(default_factory=list)
    lenses: list[FeatureLens] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_catalog_counts(self) -> "FeatureLensCatalog":
        active = sum(1 for lens in self.lenses if lens.enabled)
        if len(self.lenses) != self.declared_lens_count:
            raise ValueError("declared_lens_count does not match catalog slots")
        if active != self.active_lens_count:
            raise ValueError("active_lens_count does not match enabled lens rows")
        if len({lens.id for lens in self.lenses}) != len(self.lenses):
            raise ValueError("Feature lens IDs must be unique")
        if len({lens.order for lens in self.lenses}) != len(self.lenses):
            raise ValueError("Feature lens order values must be unique")
        return self


class FeatureLensObservation(StrictModel):
    lens_id: str
    status: LensObservationStatus = LensObservationStatus.UNKNOWN
    note: str = ""
    evidence_uris: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    generated_by: str = "twinstudio:auto-scan"


class DesignAlternative(StrictModel):
    idea_id: str = Field(default_factory=lambda: str(uuid4()))
    target_uri: str
    title: str
    lens_ids: list[str] = Field(min_length=1)
    summary: str
    proposed_changes: list[str] = Field(default_factory=list)
    expected_benefits: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    source: DesignIdeaSource = DesignIdeaSource.LOCAL
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class DesignFixationReview(StrictModel):
    review_id: str = Field(default_factory=lambda: str(uuid4()))
    uri: str
    project_id: str
    base_revision: str
    target_uri: str
    challenge: str = ""
    catalog_version: str
    selected_lens_ids: list[str] = Field(default_factory=list)
    observations: list[FeatureLensObservation] = Field(default_factory=list)
    coverage_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    observed_count: int = Field(default=0, ge=0)
    applicable_count: int = Field(default=0, ge=0)
    underexplored_lens_ids: list[str] = Field(default_factory=list)
    alternatives: list[DesignAlternative] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    planner: str = "local-feature-lens-engine"
    created_by: str
    created_at: datetime = Field(default_factory=utcnow)


class DslDiagnostic(StrictModel):
    severity: DslSeverity
    code: str
    message: str
    line: int | None = None
    column: int | None = None
    hint: str = ""


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
    include_extension_lenses: bool = True
    source_lens_ids: list[str] = Field(default_factory=list)
    extension_lens_ids: list[str] = Field(default_factory=list)
    ask_hidden_assumptions: bool = True
    max_lenses: int = Field(default=80, ge=1, le=250)


class EvolutionOperatorSpec(StrictModel):
    operator: MutationOperatorKind
    weight: float = Field(default=1.0, gt=0.0, le=100.0)
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


def _default_evolution_operators() -> list[EvolutionOperatorSpec]:
    return [
        EvolutionOperatorSpec(operator=MutationOperatorKind.REFRAME_GOAL, weight=1.0),
        EvolutionOperatorSpec(operator=MutationOperatorKind.REPURPOSE_FEATURE, weight=1.0),
        EvolutionOperatorSpec(operator=MutationOperatorKind.PARAMETER_SHIFT, weight=0.9),
        EvolutionOperatorSpec(operator=MutationOperatorKind.MODULARIZE, weight=0.8),
        EvolutionOperatorSpec(operator=MutationOperatorKind.MAKE_REVERSIBLE, weight=0.7),
        EvolutionOperatorSpec(operator=MutationOperatorKind.SUBSTITUTE_PROCESS, weight=0.6),
        EvolutionOperatorSpec(operator=MutationOperatorKind.ADJACENT_ASSOCIATION, weight=1.0),
    ]


class EvolutionPolicy(StrictModel):
    generations: int = Field(default=3, ge=1, le=20)
    population_size: int = Field(default=12, ge=1, le=200)
    offspring_per_candidate: int = Field(default=2, ge=1, le=20)
    mutation_rate: float = Field(default=0.8, ge=0.0, le=1.0)
    crossover_rate: float = Field(default=0.25, ge=0.0, le=1.0)
    adjacent_possible_depth: int = Field(default=2, ge=0, le=5)
    deterministic_seed: int = 17
    operators: list[EvolutionOperatorSpec] = Field(default_factory=_default_evolution_operators)


class EvaluationPolicy(StrictModel):
    weights: dict[str, float] = Field(default_factory=lambda: {
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
    })
    hard_constraints: list[str] = Field(default_factory=list)
    select_top: int = Field(default=5, ge=1, le=50)
    minimum_overall_score: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("weights")
    @classmethod
    def validate_weights(cls, value: dict[str, float]) -> dict[str, float]:
        allowed = {item.value for item in EvaluationDimension}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"Unknown evaluation dimensions: {', '.join(unknown)}")
        if not value or sum(value.values()) <= 0:
            raise ValueError("At least one positive evaluation weight is required")
        if any(weight < 0 for weight in value.values()):
            raise ValueError("Evaluation weights cannot be negative")
        return value


class LifecycleTemplateStage(StrictModel):
    phase: EvolutionPhase
    name: str
    objective: str
    entry_criteria: list[str] = Field(default_factory=list)
    exit_criteria: list[str] = Field(default_factory=list)
    required_outputs: list[str] = Field(default_factory=list)
    approver_roles: list[Role] = Field(default_factory=list)
    parallel_allowed: bool = False


class EvolutionLifecycleTemplate(StrictModel):
    template_id: str
    name: str
    description: str = ""
    stages: list[LifecycleTemplateStage] = Field(min_length=1)
    feedback_loops: list[dict[str, str]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class LifecycleTemplateCatalog(StrictModel):
    catalog_version: str
    templates: list[EvolutionLifecycleTemplate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_template_ids(self) -> "LifecycleTemplateCatalog":
        ids = [item.template_id for item in self.templates]
        if len(ids) != len(set(ids)):
            raise ValueError("Lifecycle template IDs must be unique")
        return self


class LifecycleProgramSpec(StrictModel):
    template_id: str = "product-evolution"
    start_phase: EvolutionPhase = EvolutionPhase.INTAKE
    stop_phase: EvolutionPhase = EvolutionPhase.RELEASE
    enabled_phases: list[EvolutionPhase] = Field(default_factory=list)
    disabled_phases: list[EvolutionPhase] = Field(default_factory=list)
    auto_advance: bool = True
    approval_required: bool = True


class EvolutionGateSpec(StrictModel):
    stage: EvolutionPhase
    expressions: list[str] = Field(default_factory=list)
    approver_roles: list[Role] = Field(default_factory=lambda: [Role.CREATOR, Role.ADMIN])
    blocking: bool = True
    notes: str = ""


class RealizationPolicy(StrictModel):
    mode: RealizationMode = RealizationMode.CHANGE_PLAN
    dry_run: bool = True
    allowed_operations: list[ChangeOperationKind] = Field(default_factory=lambda: [
        ChangeOperationKind.SET_PARAMETER,
        ChangeOperationKind.ADD_FEATURE,
        ChangeOperationKind.SUPPRESS_FEATURE,
        ChangeOperationKind.TRANSFORM_FEATURE,
        ChangeOperationKind.BOOLEAN_CUT,
        ChangeOperationKind.BOOLEAN_ADD,
        ChangeOperationKind.UPDATE_MANUFACTURING,
        ChangeOperationKind.ADD_TEST,
        ChangeOperationKind.ATTACH_REQUIREMENT,
    ])
    max_change_plans: int = Field(default=3, ge=0, le=20)
    require_approval: bool = True


class EvolutionOutputSpec(StrictModel):
    graph_formats: list[Literal["json", "dot", "mermaid"]] = Field(default_factory=lambda: ["json", "dot", "mermaid"])
    report_formats: list[Literal["json", "markdown", "csv"]] = Field(default_factory=lambda: ["json", "markdown", "csv"])
    include_change_plans: bool = True
    persist_artifacts: bool = True


class EvolutionProgram(StrictModel):
    schema_version: Literal["twinstudio.evolution/v1"] = "twinstudio.evolution/v1"
    program_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=3, max_length=200)
    project_id: str
    base_revision: str = "main"
    targets: list[str] = Field(min_length=1)
    goal: EvolutionGoal
    action_search: ActionSearchSpec = Field(default_factory=ActionSearchSpec)
    resources: ResourceSearchSpec = Field(default_factory=ResourceSearchSpec)
    lenses: LensSearchSpec = Field(default_factory=LensSearchSpec)
    evolution: EvolutionPolicy = Field(default_factory=EvolutionPolicy)
    evaluation: EvaluationPolicy = Field(default_factory=EvaluationPolicy)
    lifecycle: LifecycleProgramSpec = Field(default_factory=LifecycleProgramSpec)
    gates: list[EvolutionGateSpec] = Field(default_factory=list)
    realization: RealizationPolicy = Field(default_factory=RealizationPolicy)
    outputs: EvolutionOutputSpec = Field(default_factory=EvolutionOutputSpec)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GoalVariant(StrictModel):
    variant_id: str
    text: str
    verb: str
    relation: ActionRelation = ActionRelation.SEED
    source_verb: str | None = None
    depth: int = Field(default=0, ge=0)
    rationale: str = ""


class EvolutionResource(StrictModel):
    resource_id: str
    kind: ResourceKind
    label: str
    uri: str | None = None
    source_uri: str | None = None
    parent_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence_uris: list[str] = Field(default_factory=list)


class EvolutionGraphNode(StrictModel):
    node_id: str
    kind: Literal["goal", "action", "resource", "bridge", "candidate", "evidence", "test", "stage"]
    label: str
    data: dict[str, Any] = Field(default_factory=dict)


class EvolutionGraphEdge(StrictModel):
    source: str
    target: str
    relation: str
    label: str = ""
    weight: float = Field(default=1.0, ge=0.0)
    data: dict[str, Any] = Field(default_factory=dict)


class EvolutionGraph(StrictModel):
    graph_id: str = Field(default_factory=lambda: str(uuid4()))
    nodes: list[EvolutionGraphNode] = Field(default_factory=list)
    edges: list[EvolutionGraphEdge] = Field(default_factory=list)


class EvolutionCandidate(StrictModel):
    candidate_id: str = Field(default_factory=lambda: str(uuid4()))
    generation: int = Field(default=0, ge=0)
    parent_ids: list[str] = Field(default_factory=list)
    title: str
    summary: str
    target_uri: str
    goal_variant_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    lens_ids: list[str] = Field(default_factory=list)
    operator: MutationOperatorKind
    proposed_changes: list[str] = Field(default_factory=list)
    operations: list[ChangeOperation] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    overall_score: float = Field(default=0.0, ge=0.0, le=1.0)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    status: CandidateStatus = CandidateStatus.PROPOSED
    provenance: dict[str, Any] = Field(default_factory=dict)


class GateEvaluation(StrictModel):
    stage: EvolutionPhase
    expression: str
    passed: bool
    actual: Any | None = None
    message: str = ""
    blocking: bool = True


class EvolutionStageRecord(StrictModel):
    phase: EvolutionPhase
    status: StageRunStatus = StageRunStatus.NOT_STARTED
    objective: str = ""
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    gate_evaluations: list[GateEvaluation] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    notes: list[str] = Field(default_factory=list)


class EvolutionRun(StrictModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    uri: str
    project_id: str
    base_revision: str
    program: EvolutionProgram
    status: EvolutionRunStatus = EvolutionRunStatus.COMPILED
    goal_variants: list[GoalVariant] = Field(default_factory=list)
    resources: list[EvolutionResource] = Field(default_factory=list)
    graph: EvolutionGraph = Field(default_factory=EvolutionGraph)
    candidates: list[EvolutionCandidate] = Field(default_factory=list)
    shortlisted_candidate_ids: list[str] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    stages: list[EvolutionStageRecord] = Field(default_factory=list)
    gate_evaluations: list[GateEvaluation] = Field(default_factory=list)
    generated_change_plan_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    diagnostics: list[DslDiagnostic] = Field(default_factory=list)
    mode: str = "local"
    created_by: str
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None


class Requirement(StrictModel):
    uri: str
    statement: str
    status: Literal["proposed", "approved", "verified", "rejected"] = "proposed"
    verification_method: str | None = None
    target_uris: list[str] = Field(default_factory=list)
    source_uri: str | None = None


class LifecycleGate(StrictModel):
    stage: LifecycleStage
    status: Literal["not_started", "in_progress", "blocked", "approved", "rejected"] = "not_started"
    entry_criteria: list[str] = Field(default_factory=list)
    exit_criteria: list[str] = Field(default_factory=list)
    approver_roles: list[Role] = Field(default_factory=lambda: [Role.CREATOR, Role.ADMIN])
    evidence_artifact_uris: list[str] = Field(default_factory=list)


class FailureMode(StrictModel):
    uri: str
    target_uri: str
    failure: str
    effect: str
    cause: str
    severity: int = Field(ge=1, le=10)
    occurrence: int = Field(ge=1, le=10)
    detection: int = Field(ge=1, le=10)
    controls: list[str] = Field(default_factory=list)

    @property
    def rpn(self) -> int:
        return self.severity * self.occurrence * self.detection


class HumanTaskStep(StrictModel):
    step_id: str
    instruction: str
    action: str
    target_uri: str | None = None
    preconditions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    possible_errors: list[str] = Field(default_factory=list)
    hazards: list[str] = Field(default_factory=list)
    expected_duration_s: float | None = None
    expected_force_n: float | None = None


class HumanUseScenario(StrictModel):
    uri: str
    name: str
    actor: str
    stage: LifecycleStage = LifecycleStage.OPERATION
    steps: list[HumanTaskStep]
    recovery_steps: list[HumanTaskStep] = Field(default_factory=list)


class TestCase(StrictModel):
    uri: str
    name: str
    test_type: Literal[
        "inspection", "mechanical", "electrical", "thermal", "software",
        "camera", "human_use", "transport", "manufacturing", "commercial"
    ]
    target_uris: list[str] = Field(default_factory=list)
    lifecycle_stage: LifecycleStage = LifecycleStage.VERIFICATION
    procedure: list[str] = Field(default_factory=list)
    input_artifact_uris: list[str] = Field(default_factory=list)
    expected_results: dict[str, Any] = Field(default_factory=dict)
    execution_adapter: str = "manual"
    container_image_uri: str | None = None
    status: Literal["draft", "ready", "running", "passed", "failed", "blocked"] = "draft"
    result_artifact_uris: list[str] = Field(default_factory=list)
    notes: str = ""


class TestPlan(StrictModel):
    uri: str
    name: str
    stage: LifecycleStage = LifecycleStage.VERIFICATION
    cases: list[TestCase] = Field(default_factory=list)
    approval_required: bool = True
    owner_role: Role = Role.EDITOR


class PowerLoadCase(StrictModel):
    name: str
    current_a: float = Field(ge=0.0)
    duration_s: float = Field(gt=0.0)
    component_uri: str | None = None
    heat_fraction: float = Field(default=0.95, ge=0.0, le=1.0)


class PowerModel(StrictModel):
    supply_voltage_v: float = Field(gt=0.0)
    supply_current_limit_a: float = Field(gt=0.0)
    cable_resistance_ohm: float = Field(default=0.08, ge=0.0)
    connector_resistance_ohm: float = Field(default=0.03, ge=0.0)
    board_path_resistance_ohm: float = Field(default=0.02, ge=0.0)
    brownout_voltage_v: float = Field(default=4.63, gt=0.0)
    load_cases: list[PowerLoadCase]


class ThermalNode(StrictModel):
    uri: str
    ambient_c: float = 25.0
    initial_c: float = 25.0
    thermal_resistance_c_per_w: float = Field(gt=0.0)
    thermal_capacitance_j_per_c: float = Field(gt=0.0)


class ThermalModel(StrictModel):
    nodes: list[ThermalNode]
    timestep_s: float = Field(default=0.5, gt=0.0)


class EcommerceOffer(StrictModel):
    uri: str
    sku: str
    gtin: str | None = None
    gtin_status: Literal["unassigned", "reserved", "assigned", "verified"] = "unassigned"
    title: str
    description: str
    currency: str = "EUR"
    price: float | None = None
    tax_category: str | None = None
    stock_status: Literal["draft", "preorder", "in_stock", "out_of_stock"] = "draft"
    media_artifact_uris: list[str] = Field(default_factory=list)
    package_object_uri: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)


class ProjectSnapshot(StrictModel):
    project_id: str
    tenant: str
    name: str
    description: str = ""
    revision: str = "main"
    stream_version: int = 0
    lifecycle_stage: LifecycleStage = LifecycleStage.EVIDENCE
    objects: dict[str, ObjectNode] = Field(default_factory=dict)
    artifacts: dict[str, ArtifactRecord] = Field(default_factory=dict)
    annotations: dict[str, Annotation] = Field(default_factory=dict)
    change_plans: dict[str, ChangePlan] = Field(default_factory=dict)
    design_fixation_reviews: dict[str, DesignFixationReview] = Field(default_factory=dict)
    evolution_runs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    lifecycle_blueprints: dict[str, dict[str, Any]] = Field(default_factory=dict)
    lifecycle_history: list[dict[str, Any]] = Field(default_factory=list)
    dsl_programs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    dsl_executions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    requirements: dict[str, Requirement] = Field(default_factory=dict)
    claims: dict[str, EvidenceClaim] = Field(default_factory=dict)
    memberships: dict[str, Role] = Field(default_factory=dict)
    projection_maps: dict[str, ProjectionMap] = Field(default_factory=dict)
    selection_maps: dict[str, SelectionMap] = Field(default_factory=dict)
    lifecycle_gates: list[LifecycleGate] = Field(default_factory=list)
    failure_modes: list[FailureMode] = Field(default_factory=list)
    human_scenarios: list[HumanUseScenario] = Field(default_factory=list)
    test_plans: dict[str, TestPlan] = Field(default_factory=dict)
    power_model: PowerModel | None = None
    thermal_model: ThermalModel | None = None
    ecommerce_offers: list[EcommerceOffer] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class EventEnvelope(StrictModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    stream_id: str
    stream_version: int = 0
    event_type: str
    data: dict[str, Any]
    actor: str
    correlation_id: str | None = None
    causation_id: str | None = None
    occurred_at: datetime = Field(default_factory=utcnow)
    schema_version: int = 1


class CommandEnvelope(StrictModel):
    command_id: str = Field(default_factory=lambda: str(uuid4()))
    command_type: str
    project_id: str
    expected_version: int | None = None
    payload: dict[str, Any]
    actor: str
    correlation_id: str | None = None
    causation_id: str | None = None
    issued_at: datetime = Field(default_factory=utcnow)


class InvitationRequest(StrictModel):
    project_id: str
    requested_email: str
    requested_role: Role = Role.READER
    message: str = ""

    @field_validator("requested_email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Invalid email")
        return normalized


class AuthPrincipal(StrictModel):
    email: str
    role: Role | None = None
    project_id: str | None = None
    auth_method: Literal["dev", "basic", "session", "mcp", "mqtt"] = "dev"
