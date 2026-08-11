from __future__ import annotations

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
    REQUIREMENTS = "requirements"
    CONCEPT = "concept"
    ARCHITECTURE = "architecture"
    DETAILED_DESIGN = "detailed_design"
    PROTOTYPE = "prototype"
    VERIFICATION = "verification"
    VALIDATION = "validation"
    INDUSTRIALIZATION = "industrialization"
    PRODUCTION = "production"
    FULFILLMENT = "fulfillment"
    OPERATION = "operation"
    MAINTENANCE = "maintenance"
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


class ImpactItem(StrictModel):
    uri: str
    impact: Literal["direct", "dependent", "manufacturing", "test", "software", "commercial"]
    summary: str


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
