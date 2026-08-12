from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base model used for all persisted project configuration objects."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Units(str, Enum):
    MM = "mm"


class ProjectMetadata(StrictModel):
    name: str = "Raspberry Pi 5 housing"
    revision: str = "A"
    description: str = (
        "Parametric two-part FDM housing with a lower base, an upper lid, "
        "a front hinge, two Raspberry Pi mounting patterns, and layered 2D drawings."
    )
    units: Units = Units.MM
    author: str = "Housing Studio"


class FeatureLayer(StrictModel):
    enabled: bool = True
    label: str
    notes: str = ""


class FeatureLayers(StrictModel):
    base_shell: FeatureLayer = Field(
        default_factory=lambda: FeatureLayer(label="Lower base shell")
    )
    lid_shell: FeatureLayer = Field(
        default_factory=lambda: FeatureLayer(label="Upper lid shell")
    )
    hinge: FeatureLayer = Field(
        default_factory=lambda: FeatureLayer(label="Front hinge")
    )
    pcb_mount_a: FeatureLayer = Field(
        default_factory=lambda: FeatureLayer(label="PCB mounting pattern A")
    )
    pcb_mount_b: FeatureLayer = Field(
        default_factory=lambda: FeatureLayer(label="PCB mounting pattern B")
    )
    camera_mounts: FeatureLayer = Field(
        default_factory=lambda: FeatureLayer(label="Camera mounting bosses")
    )
    lid_aux_bosses: FeatureLayer = Field(
        default_factory=lambda: FeatureLayer(label="Four auxiliary lid bosses")
    )
    rear_tabs: FeatureLayer = Field(
        default_factory=lambda: FeatureLayer(label="Rear internal tabs")
    )
    connector_openings: FeatureLayer = Field(
        default_factory=lambda: FeatureLayer(label="Connector openings")
    )
    locating_lip: FeatureLayer = Field(
        default_factory=lambda: FeatureLayer(
            label="Internal locating lip",
            enabled=False,
            notes="Disabled by default because PCB position A is close to the right wall.",
        )
    )
    pcb_reference: FeatureLayer = Field(
        default_factory=lambda: FeatureLayer(
            label="PCB reference geometry",
            notes="Preview and 2D reference only; never merged into manufactured solids.",
        )
    )


class DrawingLayerStyle(StrictModel):
    enabled: bool = True
    dxf_name: str
    line_type: Literal["CONTINUOUS", "HIDDEN", "CENTER", "DASHED"] = "CONTINUOUS"
    line_weight_mm: float = Field(default=0.25, ge=0.05, le=2.0)
    color_index: int = Field(default=7, ge=1, le=255)


class DrawingLayers(StrictModel):
    visible_edges: DrawingLayerStyle = Field(
        default_factory=lambda: DrawingLayerStyle(
            dxf_name="VISIBLE_EDGES", line_weight_mm=0.50, color_index=7
        )
    )
    hidden_edges: DrawingLayerStyle = Field(
        default_factory=lambda: DrawingLayerStyle(
            dxf_name="HIDDEN_EDGES",
            line_type="HIDDEN",
            line_weight_mm=0.18,
            color_index=8,
        )
    )
    centerlines: DrawingLayerStyle = Field(
        default_factory=lambda: DrawingLayerStyle(
            dxf_name="CENTERLINES",
            line_type="CENTER",
            line_weight_mm=0.18,
            color_index=4,
        )
    )
    dimensions: DrawingLayerStyle = Field(
        default_factory=lambda: DrawingLayerStyle(
            dxf_name="DIMENSIONS", line_weight_mm=0.18, color_index=2
        )
    )
    notes: DrawingLayerStyle = Field(
        default_factory=lambda: DrawingLayerStyle(
            dxf_name="NOTES", line_weight_mm=0.18, color_index=7
        )
    )
    section_hatch: DrawingLayerStyle = Field(
        default_factory=lambda: DrawingLayerStyle(
            dxf_name="SECTION_HATCH",
            line_type="DASHED",
            line_weight_mm=0.13,
            color_index=8,
        )
    )
    pcb_reference: DrawingLayerStyle = Field(
        default_factory=lambda: DrawingLayerStyle(
            dxf_name="PCB_REFERENCE",
            line_type="DASHED",
            line_weight_mm=0.18,
            color_index=3,
        )
    )
    construction: DrawingLayerStyle = Field(
        default_factory=lambda: DrawingLayerStyle(
            dxf_name="CONSTRUCTION",
            line_type="DASHED",
            line_weight_mm=0.13,
            color_index=9,
        )
    )
    datums: DrawingLayerStyle = Field(
        default_factory=lambda: DrawingLayerStyle(
            dxf_name="DATUMS", line_weight_mm=0.25, color_index=6
        )
    )


class EnclosureDimensions(StrictModel):
    external_width: float = Field(default=79.0, gt=20.0, le=500.0)
    external_depth: float = Field(default=95.0, gt=20.0, le=500.0)
    base_height: float = Field(default=25.0, gt=5.0, le=300.0)
    total_height: float = Field(default=40.0, gt=10.0, le=500.0)
    wall_thickness: float = Field(default=2.0, ge=0.8, le=10.0)
    floor_thickness: float = Field(default=2.0, ge=0.8, le=10.0)
    lid_top_thickness: float = Field(default=2.0, ge=0.8, le=10.0)
    lid_vertical_lower_section: float = Field(default=2.0, ge=0.0, le=20.0)
    lid_side_inset: float = Field(default=10.0, ge=0.0, le=100.0)
    lid_front_inset: float = Field(default=13.0, ge=0.0, le=100.0)
    lid_rear_inset: float = Field(default=2.0, ge=0.0, le=100.0)
    edge_radius: float = Field(default=0.8, ge=0.0, le=10.0)

    @property
    def lid_height(self) -> float:
        return self.total_height - self.base_height

    @property
    def top_width(self) -> float:
        return self.external_width - 2.0 * self.lid_side_inset

    @property
    def top_depth(self) -> float:
        return self.external_depth - self.lid_front_inset - self.lid_rear_inset

    @property
    def internal_width(self) -> float:
        return self.external_width - 2.0 * self.wall_thickness

    @property
    def internal_depth(self) -> float:
        return self.external_depth - 2.0 * self.wall_thickness

    @model_validator(mode="after")
    def validate_geometry(self) -> EnclosureDimensions:
        if self.total_height <= self.base_height:
            raise ValueError("total_height must be greater than base_height")
        if self.top_width <= 5.0:
            raise ValueError("lid_side_inset leaves no usable lid top width")
        if self.top_depth <= 5.0:
            raise ValueError("lid_front_inset + lid_rear_inset leaves no usable lid top depth")
        if self.internal_width <= 10.0 or self.internal_depth <= 10.0:
            raise ValueError("wall_thickness leaves no usable enclosure cavity")
        if self.floor_thickness >= self.base_height:
            raise ValueError("floor_thickness must be lower than base_height")
        if self.lid_top_thickness >= self.lid_height:
            raise ValueError("lid_top_thickness must be lower than lid height")
        if self.lid_vertical_lower_section >= self.lid_height:
            raise ValueError("lid_vertical_lower_section must be lower than lid height")
        if self.edge_radius > min(self.wall_thickness, self.lid_top_thickness):
            raise ValueError("edge_radius must not exceed wall_thickness or lid_top_thickness")
        return self


class MatingConfig(StrictModel):
    fit_clearance: float = Field(default=0.30, ge=0.0, le=2.0)
    locating_lip_height: float = Field(default=5.0, ge=0.0, le=20.0)
    locating_lip_thickness: float = Field(default=1.2, ge=0.5, le=5.0)
    front_gap_for_hinge: float = Field(default=10.0, ge=0.0, le=50.0)


class HingeConfig(StrictModel):
    outer_diameter: float = Field(default=8.0, gt=2.0, le=30.0)
    pin_diameter: float = Field(default=3.0, gt=0.5, le=20.0)
    pin_bore_clearance: float = Field(
        default=0.2, ge=0.0, le=2.0, description="Diametral FDM clearance added to the pin bore"
    )
    axis_y: float = Field(default=0.5, ge=-20.0, le=30.0)
    axis_z_offset_from_base_top: float = Field(default=1.0, ge=-10.0, le=20.0)
    side_margin: float = Field(default=4.0, ge=0.0, le=30.0)
    inter_knuckle_gap: float = Field(default=0.8, ge=0.2, le=5.0)
    opening_angle_deg: float = Field(default=195.0, ge=0.0, le=270.0)
    base_wall_relief: float = Field(default=1.5, ge=0.0, le=10.0)
    lid_edge_relief: float = Field(default=2.0, ge=0.0, le=10.0)
    base_front_chamfer_angle_deg: float = Field(default=45.0, ge=10.0, le=80.0)
    base_front_chamfer_size: float = Field(default=2.0, ge=0.0, le=15.0)

    @property
    def bore_diameter(self) -> float:
        return self.pin_diameter + self.pin_bore_clearance

    @model_validator(mode="after")
    def validate_hinge(self) -> HingeConfig:
        if self.bore_diameter >= self.outer_diameter:
            raise ValueError("hinge pin bore diameter must be lower than hinge outer diameter")
        return self


class StandoffConfig(StrictModel):
    height: float = Field(default=3.0, ge=0.5, le=30.0)
    outer_diameter: float = Field(default=6.0, ge=2.0, le=30.0)
    pilot_hole_diameter: float = Field(default=1.0, ge=0.2, le=10.0)

    @model_validator(mode="after")
    def validate_standoff(self) -> StandoffConfig:
        if self.pilot_hole_diameter >= self.outer_diameter:
            raise ValueError("standoff pilot hole must be lower than outer diameter")
        return self


class BoardPosition(StrictModel):
    front_clearance: float = Field(default=2.0, ge=0.0, le=100.0)
    right_clearance: float = Field(default=1.0, ge=0.0, le=100.0)
    expected_left_clearance: float | None = Field(default=None, ge=0.0, le=100.0)
    anchor: Literal["right", "left", "center"] = "right"


class BoardConfig(StrictModel):
    length: float = Field(default=85.0, gt=10.0, le=300.0)
    width: float = Field(default=56.0, gt=10.0, le=300.0)
    thickness: float = Field(default=1.6, ge=0.5, le=10.0)
    hole_spacing_length: float = Field(default=58.0, gt=1.0, le=200.0)
    hole_spacing_width: float = Field(default=49.0, gt=1.0, le=200.0)
    first_hole_edge_offset: float = Field(default=3.5, ge=0.0, le=50.0)
    standoff: StandoffConfig = Field(default_factory=StandoffConfig)
    position_a: BoardPosition = Field(
        default_factory=lambda: BoardPosition(
            front_clearance=2.0,
            right_clearance=1.0,
            expected_left_clearance=None,
            anchor="right",
        )
    )
    position_b: BoardPosition = Field(
        default_factory=lambda: BoardPosition(
            front_clearance=2.0,
            right_clearance=7.5,
            expected_left_clearance=10.5,
            anchor="right",
        )
    )


class ConnectorOpening(StrictModel):
    name: str = "rear_connector"
    enabled: bool = True
    wall: Literal["front", "rear", "left", "right"] = "rear"
    center_horizontal: float = 39.5
    bottom_z: float = 7.0
    width: float = Field(default=20.0, gt=1.0, le=100.0)
    height: float = Field(default=8.0, gt=1.0, le=100.0)
    corner_radius: float = Field(default=1.0, ge=0.0, le=20.0)


class CameraMountConfig(StrictModel):
    columns: int = Field(default=2, ge=1, le=10)
    rows: int = Field(default=3, ge=1, le=10)
    center_x: float = 39.5
    center_y: float = 58.0
    x_pitch: float = Field(default=18.0, gt=0.1, le=100.0)
    y_pitch: float = Field(default=10.0, gt=0.1, le=100.0)
    outer_diameter: float = Field(default=6.0, gt=1.0, le=30.0)
    hole_diameter: float = Field(default=2.0, gt=0.1, le=20.0)
    boss_height_after_reduction: float = Field(default=4.0, gt=0.5, le=30.0)
    embed_depth: float = Field(default=1.0, ge=0.1, le=5.0)


class AuxiliaryLidBossConfig(StrictModel):
    outer_diameter: float = Field(default=8.0, gt=1.0, le=30.0)
    hole_diameter: float = Field(default=2.0, gt=0.1, le=20.0)
    top_z_from_base_mating_plane: float = Field(default=14.0, ge=0.0, le=50.0)
    boss_height: float = Field(default=8.0, gt=0.5, le=30.0)
    x_span: float = Field(default=55.0, gt=1.0, le=200.0)
    y_span: float = Field(default=71.0, gt=1.0, le=300.0)
    center_x: float = 39.5
    center_y: float = 47.5


class RearTabsConfig(StrictModel):
    count: int = Field(default=2, ge=0, le=10)
    width: float = Field(default=8.0, gt=0.5, le=50.0)
    thickness: float = Field(default=3.0, gt=0.5, le=20.0)
    height: float = Field(default=8.0, gt=0.5, le=50.0)
    clearance_to_inner_wall: float = Field(default=1.0, ge=0.0, le=20.0)
    middle_wall_reduction: float = Field(default=4.0, ge=0.0, le=20.0)


class DrawingConfig(StrictModel):
    projection: Literal["first_angle", "third_angle"] = "first_angle"
    sheet_size: Literal["A4", "A3"] = "A3"
    include_front: bool = True
    include_top: bool = True
    include_side: bool = True
    include_isometric_note: bool = True
    layers: DrawingLayers = Field(default_factory=DrawingLayers)


class ArtifactConfig(StrictModel):
    export_step: bool = True
    export_stl: bool = True
    export_obj: bool = True
    export_glb: bool = True
    export_dxf: bool = True
    export_svg: bool = True
    export_pdf: bool = True
    export_open_preview: bool = True
    create_zip: bool = True
    mesh_tolerance: float = Field(default=0.08, ge=0.01, le=1.0)
    angular_tolerance: float = Field(default=0.15, ge=0.01, le=1.0)


class ProjectConfig(StrictModel):
    metadata: ProjectMetadata = Field(default_factory=ProjectMetadata)
    dimensions: EnclosureDimensions = Field(default_factory=EnclosureDimensions)
    mating: MatingConfig = Field(default_factory=MatingConfig)
    hinge: HingeConfig = Field(default_factory=HingeConfig)
    board: BoardConfig = Field(default_factory=BoardConfig)
    connector_openings: list[ConnectorOpening] = Field(
        default_factory=lambda: [ConnectorOpening()]
    )
    camera_mounts: CameraMountConfig = Field(default_factory=CameraMountConfig)
    auxiliary_lid_bosses: AuxiliaryLidBossConfig = Field(
        default_factory=AuxiliaryLidBossConfig
    )
    rear_tabs: RearTabsConfig = Field(default_factory=RearTabsConfig)
    feature_layers: FeatureLayers = Field(default_factory=FeatureLayers)
    drawing: DrawingConfig = Field(default_factory=DrawingConfig)
    artifacts: ArtifactConfig = Field(default_factory=ArtifactConfig)

    @model_validator(mode="after")
    def validate_project(self) -> ProjectConfig:
        d = self.dimensions
        board = self.board
        if board.width > d.internal_width + 1e-6:
            raise ValueError("board width does not fit the internal enclosure width")
        if board.length > d.internal_depth + 1e-6:
            raise ValueError("board length does not fit the internal enclosure depth")
        if board.hole_spacing_width >= board.width:
            raise ValueError("board hole_spacing_width must be lower than board width")
        if board.hole_spacing_length >= board.length:
            raise ValueError("board hole_spacing_length must be lower than board length")
        return self


def default_project_config() -> ProjectConfig:
    return ProjectConfig()
