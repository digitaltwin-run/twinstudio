from __future__ import annotations

import html
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal

import ezdxf
from reportlab.lib.pagesizes import A3, A4, landscape
from reportlab.pdfgen import canvas

from .models import DrawingLayerStyle, ProjectConfig
from .validation import (
    board_actual_clearances,
    board_hole_centers,
    board_origin,
    hinge_segments,
)

LayerKey = Literal[
    "visible_edges",
    "hidden_edges",
    "centerlines",
    "dimensions",
    "notes",
    "section_hatch",
    "pcb_reference",
    "construction",
    "datums",
]


@dataclass(slots=True)
class Line2D:
    p1: tuple[float, float]
    p2: tuple[float, float]
    layer: LayerKey = "visible_edges"


@dataclass(slots=True)
class Polyline2D:
    points: list[tuple[float, float]]
    closed: bool = False
    layer: LayerKey = "visible_edges"
    object_key: str | None = None
    projection_entity: str | None = None


@dataclass(slots=True)
class Circle2D:
    center: tuple[float, float]
    radius: float
    layer: LayerKey = "visible_edges"


@dataclass(slots=True)
class Text2D:
    position: tuple[float, float]
    text: str
    height: float = 2.8
    layer: LayerKey = "notes"
    align: Literal["left", "center", "right"] = "left"


@dataclass(slots=True)
class Dimension2D:
    p1: tuple[float, float]
    p2: tuple[float, float]
    offset: float
    text: str
    orientation: Literal["horizontal", "vertical"]
    layer: LayerKey = "dimensions"


Primitive = Line2D | Polyline2D | Circle2D | Text2D | Dimension2D


@dataclass(slots=True)
class View2D:
    name: str
    width: float
    height: float
    primitives: list[Primitive] = field(default_factory=list)

    def add(self, *items: Primitive) -> None:
        self.primitives.extend(items)


@dataclass(slots=True)
class DrawingSet:
    part_name: str
    views: dict[str, View2D]
    notes: list[str]


def _rect(x: float, y: float, width: float, height: float, layer: LayerKey) -> Polyline2D:
    return Polyline2D(
        [(x, y), (x + width, y), (x + width, y + height), (x, y + height)],
        closed=True,
        layer=layer,
    )


def _board_outline(config: ProjectConfig, which: str) -> Polyline2D:
    pos = config.board.position_a if which == "A" else config.board.position_b
    x, y = board_origin(config, pos)
    return _rect(x, y, config.board.width, config.board.length, "pcb_reference")


def _base_front_view(config: ProjectConfig) -> View2D:
    d = config.dimensions
    h = config.hinge
    view = View2D("Front", d.external_width, max(d.base_height, d.base_height + h.outer_diameter / 2.0 + 3.0))
    view.add(_rect(0, 0, d.external_width, d.base_height, "visible_edges"))
    view.add(
        Line2D((d.wall_thickness, d.floor_thickness), (d.wall_thickness, d.base_height), "hidden_edges"),
        Line2D((d.external_width - d.wall_thickness, d.floor_thickness), (d.external_width - d.wall_thickness, d.base_height), "hidden_edges"),
        Line2D((d.wall_thickness, d.floor_thickness), (d.external_width - d.wall_thickness, d.floor_thickness), "hidden_edges"),
    )
    if config.feature_layers.hinge.enabled:
        axis_z = d.base_height + h.axis_z_offset_from_base_top
        radius = h.outer_diameter / 2.0
        for seg in hinge_segments(config):
            if seg["owner"] == "base":
                view.add(
                    _rect(
                        float(seg["x_start"]),
                        axis_z - radius,
                        float(seg["length"]),
                        2.0 * radius,
                        "visible_edges",
                    )
                )
        view.add(Line2D((0, axis_z), (d.external_width, axis_z), "centerlines"))
    view.add(
        Dimension2D((0, 0), (d.external_width, 0), -10, f"{d.external_width:.2f}", "horizontal"),
        Dimension2D((0, 0), (0, d.base_height), -10, f"{d.base_height:.2f}", "vertical"),
        Text2D((d.external_width / 2, d.base_height + 8), "LOWER BASE - FRONT", align="center"),
    )
    return view


def _base_top_view(config: ProjectConfig) -> View2D:
    d = config.dimensions
    view = View2D("Top", d.external_width, d.external_depth)
    view.add(
        _rect(0, 0, d.external_width, d.external_depth, "visible_edges"),
        _rect(d.wall_thickness, d.wall_thickness, d.internal_width, d.internal_depth, "visible_edges"),
    )
    if config.feature_layers.pcb_reference.enabled:
        view.add(_board_outline(config, "A"), _board_outline(config, "B"))
    standoff_r = config.board.standoff.outer_diameter / 2.0
    if config.feature_layers.pcb_mount_a.enabled:
        for x, y in board_hole_centers(config, config.board.position_a):
            view.add(Circle2D((x, y), standoff_r, "visible_edges"), Circle2D((x, y), config.board.standoff.pilot_hole_diameter / 2.0, "centerlines"))
    if config.feature_layers.pcb_mount_b.enabled:
        for x, y in board_hole_centers(config, config.board.position_b):
            view.add(Circle2D((x, y), standoff_r, "visible_edges"), Circle2D((x, y), config.board.standoff.pilot_hole_diameter / 2.0, "centerlines"))
    if config.feature_layers.hinge.enabled:
        radius = config.hinge.outer_diameter / 2.0
        for seg in hinge_segments(config):
            if seg["owner"] == "base":
                view.add(
                    _rect(
                        float(seg["x_start"]),
                        config.hinge.axis_y - radius,
                        float(seg["length"]),
                        2.0 * radius,
                        "visible_edges",
                    )
                )
    for opening in config.connector_openings:
        if not opening.enabled or not config.feature_layers.connector_openings.enabled:
            continue
        if opening.wall in {"front", "rear"}:
            y = 0 if opening.wall == "front" else d.external_depth - d.wall_thickness
            view.add(
                _rect(
                    opening.center_horizontal - opening.width / 2.0,
                    y,
                    opening.width,
                    d.wall_thickness,
                    "visible_edges",
                )
            )
    clear_b = board_actual_clearances(config, config.board.position_b)
    view.add(
        Dimension2D((0, 0), (d.external_width, 0), -10, f"{d.external_width:.2f}", "horizontal"),
        Dimension2D((0, 0), (0, d.external_depth), -10, f"{d.external_depth:.2f}", "vertical"),
        Text2D((d.external_width / 2, d.external_depth + 8), "LOWER BASE - TOP", align="center"),
        Text2D(
            (d.external_width + 5, d.external_depth - 10),
            f"PCB B actual clearances: L {clear_b['left']:.2f}, R {clear_b['right']:.2f}",
            height=2.4,
        ),
    )
    return view


def _base_side_view(config: ProjectConfig) -> View2D:
    d = config.dimensions
    h = config.hinge
    view = View2D("Side", d.external_depth, max(d.base_height, d.base_height + h.outer_diameter / 2.0 + 3.0))
    chamfer_drop = h.base_front_chamfer_size
    chamfer_run = chamfer_drop / max(math.tan(math.radians(h.base_front_chamfer_angle_deg)), 1e-9)
    points = [
        (0, 0),
        (d.external_depth, 0),
        (d.external_depth, d.base_height),
        (chamfer_run, d.base_height),
        (0, d.base_height - chamfer_drop),
    ]
    view.add(Polyline2D(points, closed=True, layer="visible_edges"))
    view.add(
        Line2D((d.wall_thickness, d.floor_thickness), (d.external_depth - d.wall_thickness, d.floor_thickness), "hidden_edges"),
        Line2D((d.wall_thickness, d.floor_thickness), (d.wall_thickness, d.base_height - chamfer_drop), "hidden_edges"),
        Line2D((d.external_depth - d.wall_thickness, d.floor_thickness), (d.external_depth - d.wall_thickness, d.base_height), "hidden_edges"),
    )
    if config.feature_layers.hinge.enabled:
        center = (h.axis_y, d.base_height + h.axis_z_offset_from_base_top)
        view.add(
            Circle2D(center, h.outer_diameter / 2.0, "visible_edges"),
            Circle2D(center, h.bore_diameter / 2.0, "centerlines"),
            Line2D((center[0] - 7, center[1]), (center[0] + 7, center[1]), "centerlines"),
            Line2D((center[0], center[1] - 7), (center[0], center[1] + 7), "centerlines"),
        )
    for opening in config.connector_openings:
        if not opening.enabled or not config.feature_layers.connector_openings.enabled:
            continue
        if opening.wall == "rear":
            view.add(_rect(d.external_depth - d.wall_thickness, opening.bottom_z, d.wall_thickness, opening.height, "visible_edges"))
        elif opening.wall == "front":
            view.add(_rect(0, opening.bottom_z, d.wall_thickness, opening.height, "visible_edges"))
    view.add(
        Dimension2D((0, 0), (d.external_depth, 0), -10, f"{d.external_depth:.2f}", "horizontal"),
        Dimension2D((d.external_depth, 0), (d.external_depth, d.base_height), d.external_depth + 10, f"{d.base_height:.2f}", "vertical"),
        Text2D((d.external_depth / 2, d.base_height + 8), "LOWER BASE - SIDE", align="center"),
        Text2D((3, d.base_height - 5), f"{h.base_front_chamfer_angle_deg:.1f} deg chamfer, drop {chamfer_drop:.2f}, run {chamfer_run:.2f}", height=2.2),
    )
    return view


def _lid_front_polygon(config: ProjectConfig) -> list[tuple[float, float]]:
    d = config.dimensions
    return [
        (0, 0),
        (0, d.lid_vertical_lower_section),
        (d.lid_side_inset, d.lid_height),
        (d.external_width - d.lid_side_inset, d.lid_height),
        (d.external_width, d.lid_vertical_lower_section),
        (d.external_width, 0),
    ]


def _lid_side_polygon(config: ProjectConfig) -> list[tuple[float, float]]:
    d = config.dimensions
    return [
        (0, 0),
        (0, d.lid_vertical_lower_section),
        (d.lid_front_inset, d.lid_height),
        (d.external_depth - d.lid_rear_inset, d.lid_height),
        (d.external_depth, d.lid_vertical_lower_section),
        (d.external_depth, 0),
    ]


def _lid_front_view(config: ProjectConfig) -> View2D:
    d = config.dimensions
    view = View2D("Front", d.external_width, d.lid_height)
    view.add(Polyline2D(_lid_front_polygon(config), closed=True, layer="visible_edges"))
    w = d.wall_thickness
    view.add(
        Polyline2D(
            [
                (w, 0),
                (w, d.lid_vertical_lower_section),
                (d.lid_side_inset + w, d.lid_height - d.lid_top_thickness),
                (d.external_width - d.lid_side_inset - w, d.lid_height - d.lid_top_thickness),
                (d.external_width - w, d.lid_vertical_lower_section),
                (d.external_width - w, 0),
            ],
            closed=False,
            layer="hidden_edges",
        )
    )
    if config.feature_layers.hinge.enabled:
        axis_z_local = config.hinge.axis_z_offset_from_base_top
        radius = config.hinge.outer_diameter / 2.0
        for seg in hinge_segments(config):
            if seg["owner"] == "lid":
                view.add(
                    _rect(
                        float(seg["x_start"]),
                        axis_z_local - radius,
                        float(seg["length"]),
                        2.0 * radius,
                        "visible_edges",
                    )
                )
        view.add(Line2D((0, axis_z_local), (d.external_width, axis_z_local), "centerlines"))
    view.add(
        Dimension2D((0, 0), (d.external_width, 0), -10, f"{d.external_width:.2f}", "horizontal"),
        Dimension2D((0, 0), (0, d.lid_height), -10, f"{d.lid_height:.2f}", "vertical"),
        Dimension2D((d.external_width, 0), (d.external_width, d.lid_vertical_lower_section), d.external_width + 6, f"{d.lid_vertical_lower_section:.2f}", "vertical"),
        Text2D((d.external_width / 2, d.lid_height + 8), "UPPER LID - FRONT", align="center"),
    )
    return view


def _camera_positions(config: ProjectConfig) -> Iterable[tuple[float, float]]:
    c = config.camera_mounts
    x0 = c.center_x - ((c.columns - 1) * c.x_pitch) / 2.0
    y0 = c.center_y - ((c.rows - 1) * c.y_pitch) / 2.0
    for row in range(c.rows):
        for col in range(c.columns):
            yield x0 + col * c.x_pitch, y0 + row * c.y_pitch


def _aux_positions(config: ProjectConfig) -> list[tuple[float, float]]:
    b = config.auxiliary_lid_bosses
    return [
        (b.center_x - b.x_span / 2.0, b.center_y - b.y_span / 2.0),
        (b.center_x + b.x_span / 2.0, b.center_y - b.y_span / 2.0),
        (b.center_x - b.x_span / 2.0, b.center_y + b.y_span / 2.0),
        (b.center_x + b.x_span / 2.0, b.center_y + b.y_span / 2.0),
    ]


def _lid_top_view(config: ProjectConfig) -> View2D:
    d = config.dimensions
    view = View2D("Top", d.external_width, d.external_depth)
    view.add(
        _rect(0, 0, d.external_width, d.external_depth, "visible_edges"),
        _rect(d.lid_side_inset, d.lid_front_inset, d.top_width, d.top_depth, "visible_edges"),
    )
    if config.feature_layers.camera_mounts.enabled:
        for p in _camera_positions(config):
            view.add(
                Circle2D(p, config.camera_mounts.outer_diameter / 2.0, "hidden_edges"),
                Circle2D(p, config.camera_mounts.hole_diameter / 2.0, "centerlines"),
            )
    if config.feature_layers.lid_aux_bosses.enabled:
        for p in _aux_positions(config):
            view.add(
                Circle2D(p, config.auxiliary_lid_bosses.outer_diameter / 2.0, "hidden_edges"),
                Circle2D(p, config.auxiliary_lid_bosses.hole_diameter / 2.0, "centerlines"),
            )
    if config.feature_layers.hinge.enabled:
        radius = config.hinge.outer_diameter / 2.0
        for seg in hinge_segments(config):
            if seg["owner"] == "lid":
                view.add(_rect(float(seg["x_start"]), config.hinge.axis_y - radius, float(seg["length"]), 2 * radius, "visible_edges"))
    view.add(
        Dimension2D((0, 0), (d.external_width, 0), -10, f"{d.external_width:.2f}", "horizontal"),
        Dimension2D((0, 0), (0, d.external_depth), -10, f"{d.external_depth:.2f}", "vertical"),
        Dimension2D((d.lid_side_inset, d.external_depth), (d.external_width - d.lid_side_inset, d.external_depth), d.external_depth + 10, f"top width {d.top_width:.2f}", "horizontal"),
        Dimension2D((d.external_width, d.lid_front_inset), (d.external_width, d.external_depth - d.lid_rear_inset), d.external_width + 10, f"top depth {d.top_depth:.2f}", "vertical"),
        Text2D((d.external_width / 2, d.external_depth + 18), "UPPER LID - TOP", align="center"),
    )
    return view


def _lid_side_view(config: ProjectConfig) -> View2D:
    d = config.dimensions
    view = View2D("Side", d.external_depth, d.lid_height)
    view.add(Polyline2D(_lid_side_polygon(config), closed=True, layer="visible_edges"))
    w = d.wall_thickness
    view.add(
        Polyline2D(
            [
                (w, 0),
                (w, d.lid_vertical_lower_section),
                (d.lid_front_inset + w, d.lid_height - d.lid_top_thickness),
                (d.external_depth - d.lid_rear_inset - w, d.lid_height - d.lid_top_thickness),
                (d.external_depth - w, d.lid_vertical_lower_section),
                (d.external_depth - w, 0),
            ],
            closed=False,
            layer="hidden_edges",
        )
    )
    if config.feature_layers.hinge.enabled:
        center = (config.hinge.axis_y, config.hinge.axis_z_offset_from_base_top)
        view.add(
            Circle2D(center, config.hinge.outer_diameter / 2.0, "visible_edges"),
            Circle2D(center, config.hinge.bore_diameter / 2.0, "centerlines"),
        )
    rise = d.lid_height - d.lid_vertical_lower_section
    front_angle = math.degrees(math.atan2(rise, max(d.lid_front_inset, 1e-9)))
    view.add(
        Dimension2D((0, 0), (d.external_depth, 0), -10, f"{d.external_depth:.2f}", "horizontal"),
        Dimension2D((d.external_depth, 0), (d.external_depth, d.lid_height), d.external_depth + 10, f"{d.lid_height:.2f}", "vertical"),
        Text2D((d.external_depth / 2, d.lid_height + 8), "UPPER LID - SIDE", align="center"),
        Text2D((d.lid_front_inset / 2.0, d.lid_height / 2.0), f"{front_angle:.1f} deg", height=2.3, align="center"),
        Text2D((d.external_depth / 2.0, 3.0), f"2 mm wall; lower vertical section {d.lid_vertical_lower_section:.2f} mm", height=2.2, align="center"),
    )
    return view


def _assembly_front_view(config: ProjectConfig) -> View2D:
    d = config.dimensions
    view = View2D("Front", d.external_width, d.total_height)
    base_outline = _rect(0, 0, d.external_width, d.base_height, "visible_edges")
    base_outline.object_key = "part/base"
    base_outline.projection_entity = "front.base.outer-wall"
    view.add(base_outline)
    lid_points = [(x, y + d.base_height) for x, y in _lid_front_polygon(config)]
    view.add(
        Polyline2D(
            lid_points,
            closed=True,
            layer="visible_edges",
            object_key="part/lid",
            projection_entity="front.lid.outer-slope",
        )
    )
    view.add(Line2D((0, d.base_height), (d.external_width, d.base_height), "datums"))
    view.add(
        Dimension2D((0, 0), (d.external_width, 0), -10, f"{d.external_width:.2f}", "horizontal"),
        Dimension2D((0, 0), (0, d.total_height), -10, f"{d.total_height:.2f}", "vertical"),
        Text2D((d.external_width / 2, d.total_height + 8), "ASSEMBLY - FRONT", align="center"),
    )
    return view


def _assembly_top_view(config: ProjectConfig) -> View2D:
    d = config.dimensions
    view = View2D("Top", d.external_width, d.external_depth)
    base_outline = _rect(0, 0, d.external_width, d.external_depth, "visible_edges")
    base_outline.object_key = "part/base"
    base_outline.projection_entity = "top.base.outer-footprint"
    lid_outline = _rect(
        d.lid_side_inset,
        d.lid_front_inset,
        d.top_width,
        d.top_depth,
        "visible_edges",
    )
    lid_outline.object_key = "part/lid"
    lid_outline.projection_entity = "top.lid.outer-top"
    view.add(base_outline, lid_outline)
    if config.feature_layers.pcb_reference.enabled:
        view.add(_board_outline(config, "A"), _board_outline(config, "B"))
    view.add(
        Dimension2D((0, 0), (d.external_width, 0), -10, f"{d.external_width:.2f}", "horizontal"),
        Dimension2D((0, 0), (0, d.external_depth), -10, f"{d.external_depth:.2f}", "vertical"),
        Text2D((d.external_width / 2, d.external_depth + 8), "ASSEMBLY - TOP", align="center"),
    )
    return view


def _assembly_side_view(config: ProjectConfig) -> View2D:
    d = config.dimensions
    view = View2D("Side", d.external_depth, d.total_height)
    base_outline = _rect(0, 0, d.external_depth, d.base_height, "visible_edges")
    base_outline.object_key = "part/base"
    base_outline.projection_entity = "side.base.outer-wall"
    view.add(base_outline)
    lid_points = [(x, y + d.base_height) for x, y in _lid_side_polygon(config)]
    view.add(
        Polyline2D(
            lid_points,
            closed=True,
            layer="visible_edges",
            object_key="part/lid",
            projection_entity="side.lid.outer-slope",
        )
    )
    center = (config.hinge.axis_y, d.base_height + config.hinge.axis_z_offset_from_base_top)
    if config.feature_layers.hinge.enabled:
        view.add(
            Circle2D(center, config.hinge.outer_diameter / 2.0, "visible_edges"),
            Circle2D(center, config.hinge.bore_diameter / 2.0, "centerlines"),
        )
    view.add(
        Dimension2D((0, 0), (d.external_depth, 0), -10, f"{d.external_depth:.2f}", "horizontal"),
        Dimension2D((d.external_depth, 0), (d.external_depth, d.total_height), d.external_depth + 10, f"{d.total_height:.2f}", "vertical"),
        Text2D((d.external_depth / 2, d.total_height + 8), "ASSEMBLY - SIDE", align="center"),
        Text2D((d.external_depth / 2, d.total_height - 5), f"Hinge target opening >190 deg; configured {config.hinge.opening_angle_deg:.1f} deg", height=2.2, align="center"),
    )
    return view


def build_drawing_sets(config: ProjectConfig) -> dict[str, DrawingSet]:
    notes_common = [
        "All dimensions are in millimetres.",
        f"General wall thickness: {config.dimensions.wall_thickness:.2f} mm.",
        f"Nominal external edge radius: {config.dimensions.edge_radius:.2f} mm.",
        "PCB outlines and alternate mounting patterns are reference geometry only.",
        "Verify hinge and fit clearances with a physical FDM prototype.",
    ]
    if config.drawing.include_isometric_note:
        notes_common.append("Interactive isometric preview is available in the web viewer and GLB artifact.")
    return {
        "base": DrawingSet(
            part_name="Part 01 - Lower Base",
            views={
                "front": _base_front_view(config),
                "top": _base_top_view(config),
                "side": _base_side_view(config),
            },
            notes=notes_common
            + [
                f"Standoffs: Ø{config.board.standoff.outer_diameter:.2f} x {config.board.standoff.height:.2f} high; pilot Ø{config.board.standoff.pilot_hole_diameter:.2f}.",
                f"Front hinge-side chamfer: {config.hinge.base_front_chamfer_angle_deg:.1f} deg, nominal size {config.hinge.base_front_chamfer_size:.2f}.",
            ],
        ),
        "lid": DrawingSet(
            part_name="Part 02 - Upper Lid",
            views={
                "front": _lid_front_view(config),
                "top": _lid_top_view(config),
                "side": _lid_side_view(config),
            },
            notes=notes_common
            + [
                f"Auxiliary bosses: Ø{config.auxiliary_lid_bosses.outer_diameter:.2f}, hole Ø{config.auxiliary_lid_bosses.hole_diameter:.2f}; top datum {config.auxiliary_lid_bosses.top_z_from_base_mating_plane:.2f} above the upper base mating plane (Datum A).",
                f"Camera boss final height: {config.camera_mounts.boss_height_after_reduction:.2f}.",
            ],
        ),
        "assembly": DrawingSet(
            part_name="Assembly - Complete Housing",
            views={
                "front": _assembly_front_view(config),
                "top": _assembly_top_view(config),
                "side": _assembly_side_view(config),
            },
            notes=notes_common
            + [
                f"Nominal closed dimensions: {config.dimensions.external_width:.2f} x {config.dimensions.external_depth:.2f} x {config.dimensions.total_height:.2f}.",
                f"Configured hinge opening preview: {config.hinge.opening_angle_deg:.1f} deg.",
            ],
        ),
    }


def _layer_style(config: ProjectConfig, key: LayerKey) -> DrawingLayerStyle:
    return getattr(config.drawing.layers, key)


def _lineweight_dxf(style: DrawingLayerStyle) -> int:
    # DXF lineweight is stored in hundredths of a millimetre.
    return max(5, min(211, int(round(style.line_weight_mm * 100))))


def _ensure_dxf_layers(doc: ezdxf.document.Drawing, config: ProjectConfig) -> None:
    for key in DrawingLayerStyle.__mro__:  # no-op to satisfy static analyzers about imported type
        break
    for layer_key in (
        "visible_edges",
        "hidden_edges",
        "centerlines",
        "dimensions",
        "notes",
        "section_hatch",
        "pcb_reference",
        "construction",
        "datums",
    ):
        style = _layer_style(config, layer_key)  # type: ignore[arg-type]
        if style.dxf_name not in doc.layers:
            doc.layers.add(
                name=style.dxf_name,
                color=style.color_index,
                linetype=style.line_type,
                lineweight=_lineweight_dxf(style),
            )


def _dimension_segments(dim: Dimension2D) -> tuple[list[Line2D], Text2D]:
    arrow = 1.8
    lines: list[Line2D] = []
    if dim.orientation == "horizontal":
        y = dim.offset
        lines.extend(
            [
                Line2D(dim.p1, (dim.p1[0], y), dim.layer),
                Line2D(dim.p2, (dim.p2[0], y), dim.layer),
                Line2D((dim.p1[0], y), (dim.p2[0], y), dim.layer),
                Line2D((dim.p1[0], y), (dim.p1[0] + arrow, y + arrow / 2), dim.layer),
                Line2D((dim.p1[0], y), (dim.p1[0] + arrow, y - arrow / 2), dim.layer),
                Line2D((dim.p2[0], y), (dim.p2[0] - arrow, y + arrow / 2), dim.layer),
                Line2D((dim.p2[0], y), (dim.p2[0] - arrow, y - arrow / 2), dim.layer),
            ]
        )
        text = Text2D(((dim.p1[0] + dim.p2[0]) / 2.0, y + 1.5), dim.text, 2.5, dim.layer, "center")
    else:
        x = dim.offset
        lines.extend(
            [
                Line2D(dim.p1, (x, dim.p1[1]), dim.layer),
                Line2D(dim.p2, (x, dim.p2[1]), dim.layer),
                Line2D((x, dim.p1[1]), (x, dim.p2[1]), dim.layer),
                Line2D((x, dim.p1[1]), (x + arrow / 2, dim.p1[1] + arrow), dim.layer),
                Line2D((x, dim.p1[1]), (x - arrow / 2, dim.p1[1] + arrow), dim.layer),
                Line2D((x, dim.p2[1]), (x + arrow / 2, dim.p2[1] - arrow), dim.layer),
                Line2D((x, dim.p2[1]), (x - arrow / 2, dim.p2[1] - arrow), dim.layer),
            ]
        )
        text = Text2D((x + 2.0, (dim.p1[1] + dim.p2[1]) / 2.0), dim.text, 2.5, dim.layer, "left")
    return lines, text


def _flatten_primitives(primitives: Iterable[Primitive]) -> Iterable[Line2D | Polyline2D | Circle2D | Text2D]:
    for primitive in primitives:
        if isinstance(primitive, Dimension2D):
            lines, text = _dimension_segments(primitive)
            yield from lines
            yield text
        else:
            yield primitive


def _shift_primitive(primitive: Primitive, dx: float, dy: float) -> Primitive:
    def p(point: tuple[float, float]) -> tuple[float, float]:
        return point[0] + dx, point[1] + dy

    if isinstance(primitive, Line2D):
        return Line2D(p(primitive.p1), p(primitive.p2), primitive.layer)
    if isinstance(primitive, Polyline2D):
        return Polyline2D([p(v) for v in primitive.points], primitive.closed, primitive.layer)
    if isinstance(primitive, Circle2D):
        return Circle2D(p(primitive.center), primitive.radius, primitive.layer)
    if isinstance(primitive, Text2D):
        return Text2D(p(primitive.position), primitive.text, primitive.height, primitive.layer, primitive.align)
    # Dimension offset is a coordinate and must be shifted along its dimension direction.
    if primitive.orientation == "horizontal":
        return Dimension2D(p(primitive.p1), p(primitive.p2), primitive.offset + dy, primitive.text, primitive.orientation, primitive.layer)
    return Dimension2D(p(primitive.p1), p(primitive.p2), primitive.offset + dx, primitive.text, primitive.orientation, primitive.layer)


def export_dxf(drawing: DrawingSet, config: ProjectConfig, path: Path) -> None:
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    _ensure_dxf_layers(doc, config)
    msp = doc.modelspace()

    ordered_names = [name for name in ("front", "top", "side") if name in drawing.views]
    if not ordered_names:
        raise ValueError("At least one 2D view must be enabled")

    placements: dict[str, tuple[float, float]] = {}
    front = drawing.views.get("front")
    top = drawing.views.get("top")
    side = drawing.views.get("side")

    if front is not None and top is not None:
        if config.drawing.projection == "first_angle":
            placements["top"] = (0.0, 0.0)
            placements["front"] = (0.0, top.height + 45.0)
        else:
            placements["front"] = (0.0, 0.0)
            placements["top"] = (0.0, front.height + 45.0)
    elif front is not None:
        placements["front"] = (0.0, 0.0)
    elif top is not None:
        placements["top"] = (0.0, 0.0)

    left_width = max(
        [view.width for name, view in drawing.views.items() if name != "side"] or [0.0]
    )
    if side is not None:
        placements["side"] = (left_width + 55.0, placements.get("front", placements.get("top", (0.0, 0.0)))[1])

    for name in ordered_names:
        view = drawing.views[name]
        dx, dy = placements[name]
        for primitive in _flatten_primitives(_shift_primitive(p, dx, dy) for p in view.primitives):
            style = _layer_style(config, primitive.layer)
            if not style.enabled:
                continue
            attribs = {"layer": style.dxf_name}
            if isinstance(primitive, Line2D):
                msp.add_line(primitive.p1, primitive.p2, dxfattribs=attribs)
            elif isinstance(primitive, Polyline2D):
                msp.add_lwpolyline(primitive.points, close=primitive.closed, dxfattribs=attribs)
            elif isinstance(primitive, Circle2D):
                msp.add_circle(primitive.center, primitive.radius, dxfattribs=attribs)
            elif isinstance(primitive, Text2D):
                text = msp.add_text(primitive.text, dxfattribs={**attribs, "height": primitive.height})
                align = {
                    "left": ezdxf.enums.TextEntityAlignment.LEFT,
                    "center": ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER,
                    "right": ezdxf.enums.TextEntityAlignment.RIGHT,
                }[primitive.align]
                text.set_placement(primitive.position, align=align)

    notes_style = config.drawing.layers.notes
    max_x = max(placements[name][0] + drawing.views[name].width for name in ordered_names)
    max_y = max(placements[name][1] + drawing.views[name].height for name in ordered_names)
    notes_x = max_x + 15.0
    notes_y = max_y + 15.0
    msp.add_text(
        drawing.part_name,
        dxfattribs={"layer": notes_style.dxf_name, "height": 5.0},
    ).set_placement((notes_x, notes_y))
    for index, note in enumerate(drawing.notes):
        msp.add_text(
            f"- {note}",
            dxfattribs={"layer": notes_style.dxf_name, "height": 2.5},
        ).set_placement((notes_x, notes_y - 7.0 - index * 4.0))

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)


def _svg_dash(style: DrawingLayerStyle) -> str:
    if style.line_type == "HIDDEN":
        return "5,3"
    if style.line_type == "CENTER":
        return "8,2,2,2"
    if style.line_type == "DASHED":
        return "3,2"
    return ""


def export_svg(view: View2D, config: ProjectConfig, path: Path) -> None:
    margin = 16.0
    width = view.width + 2.0 * margin
    height = view.height + 2.0 * margin

    def sx(x: float) -> float:
        return x + margin

    def sy(y: float) -> float:
        return height - (y + margin)

    grouped: dict[LayerKey, list[Line2D | Polyline2D | Circle2D | Text2D]] = {}
    for primitive in _flatten_primitives(view.primitives):
        grouped.setdefault(primitive.layer, []).append(primitive)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.3f} {height:.3f}" width="100%" height="100%">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<title>{html.escape(view.name)}</title>',
    ]
    for layer_key, primitives in grouped.items():
        style = _layer_style(config, layer_key)
        dash = _svg_dash(style)
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        display_attr = "" if style.enabled else ' style="display:none"'
        parts.append(
            f'<g id="{html.escape(style.dxf_name)}" data-layer-key="{html.escape(layer_key)}" '
            f'data-layer-name="{html.escape(style.dxf_name)}" '
            f'data-default-enabled="{str(style.enabled).lower()}" fill="none" stroke="black" '
            f'stroke-width="{max(0.15, style.line_weight_mm):.3f}"{dash_attr}{display_attr}>'
        )
        for primitive in primitives:
            if isinstance(primitive, Line2D):
                parts.append(f'<line x1="{sx(primitive.p1[0]):.3f}" y1="{sy(primitive.p1[1]):.3f}" x2="{sx(primitive.p2[0]):.3f}" y2="{sy(primitive.p2[1]):.3f}"/>')
            elif isinstance(primitive, Polyline2D):
                pts = " ".join(f"{sx(x):.3f},{sy(y):.3f}" for x, y in primitive.points)
                tag = "polygon" if primitive.closed else "polyline"
                metadata = ""
                if primitive.object_key:
                    xs = [sx(x) for x, _ in primitive.points]
                    ys = [sy(y) for _, y in primitive.points]
                    bbox = f"{min(xs):.3f},{min(ys):.3f},{max(xs):.3f},{max(ys):.3f}"
                    metadata += f' data-object-key="{html.escape(primitive.object_key)}"'
                    metadata += f' data-selection-bbox="{bbox}"'
                if primitive.projection_entity:
                    metadata += (
                        f' data-projection-entity="{html.escape(primitive.projection_entity)}"'
                    )
                parts.append(f'<{tag}{metadata} points="{pts}"/>')
            elif isinstance(primitive, Circle2D):
                parts.append(f'<circle cx="{sx(primitive.center[0]):.3f}" cy="{sy(primitive.center[1]):.3f}" r="{primitive.radius:.3f}"/>')
            elif isinstance(primitive, Text2D):
                anchor = {"left": "start", "center": "middle", "right": "end"}[primitive.align]
                parts.append(
                    f'<text x="{sx(primitive.position[0]):.3f}" y="{sy(primitive.position[1]):.3f}" '
                    f'font-size="{primitive.height:.3f}" text-anchor="{anchor}" fill="black" stroke="none">'
                    f'{html.escape(primitive.text)}</text>'
                )
        parts.append("</g>")
    parts.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def _pdf_dash(c: canvas.Canvas, style: DrawingLayerStyle) -> None:
    if style.line_type == "HIDDEN":
        c.setDash(5, 3)
    elif style.line_type == "CENTER":
        c.setDash([8, 2, 2, 2])
    elif style.line_type == "DASHED":
        c.setDash(3, 2)
    else:
        c.setDash()


def _draw_view_pdf(
    c: canvas.Canvas,
    view: View2D,
    config: ProjectConfig,
    box: tuple[float, float, float, float],
) -> None:
    bx, by, bw, bh = box
    margin_mm = 18.0
    full_w = view.width + 2.0 * margin_mm
    full_h = view.height + 2.0 * margin_mm
    scale = min(bw / full_w, bh / full_h)
    ox = bx + (bw - full_w * scale) / 2.0 + margin_mm * scale
    oy = by + (bh - full_h * scale) / 2.0 + margin_mm * scale

    def tx(x: float) -> float:
        return ox + x * scale

    def ty(y: float) -> float:
        return oy + y * scale

    for primitive in _flatten_primitives(view.primitives):
        style = _layer_style(config, primitive.layer)
        if not style.enabled:
            continue
        c.setStrokeColorRGB(0, 0, 0)
        c.setFillColorRGB(0, 0, 0)
        c.setLineWidth(max(0.3, style.line_weight_mm * 2.2))
        _pdf_dash(c, style)
        if isinstance(primitive, Line2D):
            c.line(tx(primitive.p1[0]), ty(primitive.p1[1]), tx(primitive.p2[0]), ty(primitive.p2[1]))
        elif isinstance(primitive, Polyline2D):
            p = c.beginPath()
            first = primitive.points[0]
            p.moveTo(tx(first[0]), ty(first[1]))
            for x, y in primitive.points[1:]:
                p.lineTo(tx(x), ty(y))
            if primitive.closed:
                p.close()
            c.drawPath(p, stroke=1, fill=0)
        elif isinstance(primitive, Circle2D):
            c.circle(tx(primitive.center[0]), ty(primitive.center[1]), primitive.radius * scale, stroke=1, fill=0)
        elif isinstance(primitive, Text2D):
            size = max(5.5, primitive.height * scale * 0.75)
            c.setFont("Helvetica", size)
            text_x = tx(primitive.position[0])
            text_y = ty(primitive.position[1])
            if primitive.align == "center":
                c.drawCentredString(text_x, text_y, primitive.text)
            elif primitive.align == "right":
                c.drawRightString(text_x, text_y, primitive.text)
            else:
                c.drawString(text_x, text_y, primitive.text)
    c.setDash()


def export_pdf(drawing: DrawingSet, config: ProjectConfig, path: Path) -> None:
    page_size = landscape(A3 if config.drawing.sheet_size == "A3" else A4)
    page_w, page_h = page_size
    c = canvas.Canvas(str(path), pagesize=page_size, pageCompression=1)
    c.setTitle(f"{drawing.part_name} - 2D technical drawing")

    margin = 24.0
    title_h = 36.0
    notes_h = 90.0
    content_h = page_h - 2 * margin - title_h - notes_h
    left_w = (page_w - 2 * margin) * 0.48
    right_w = (page_w - 2 * margin) - left_w - 12.0

    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, page_h - margin - 4, drawing.part_name)
    c.setFont("Helvetica", 9)
    c.drawRightString(page_w - margin, page_h - margin - 2, f"Revision {config.metadata.revision} | Units: mm | Projection: {config.drawing.projection.replace(chr(95), chr(32))}")
    c.line(margin, page_h - margin - 12, page_w - margin, page_h - margin - 12)

    content_y = margin + notes_h
    ordered_names = [name for name in ("front", "top", "side") if name in drawing.views]
    if not ordered_names:
        raise ValueError("At least one 2D view must be enabled")
    if len(ordered_names) == 3:
        _draw_view_pdf(c, drawing.views["front"], config, (margin, content_y + content_h * 0.52, left_w, content_h * 0.48))
        _draw_view_pdf(c, drawing.views["top"], config, (margin, content_y, left_w, content_h * 0.49))
        _draw_view_pdf(c, drawing.views["side"], config, (margin + left_w + 12.0, content_y, right_w, content_h))
    elif len(ordered_names) == 2:
        gap = 12.0
        view_w = (page_w - 2 * margin - gap) / 2.0
        for index, name in enumerate(ordered_names):
            _draw_view_pdf(c, drawing.views[name], config, (margin + index * (view_w + gap), content_y, view_w, content_h))
    else:
        _draw_view_pdf(c, drawing.views[ordered_names[0]], config, (margin, content_y, page_w - 2 * margin, content_h))

    c.line(margin, margin + notes_h, page_w - margin, margin + notes_h)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(margin, margin + notes_h - 14, "Technical notes")
    c.setFont("Helvetica", 8)
    y = margin + notes_h - 28
    for note in drawing.notes:
        c.drawString(margin + 8, y, f"- {note}")
        y -= 12

    # Simple title block.
    block_w = 250.0
    block_h = 44.0
    block_x = page_w - margin - block_w
    block_y = margin
    c.rect(block_x, block_y, block_w, block_h, stroke=1, fill=0)
    c.line(block_x + 150, block_y, block_x + 150, block_y + block_h)
    c.line(block_x, block_y + 22, block_x + block_w, block_y + 22)
    c.setFont("Helvetica", 7)
    c.drawString(block_x + 5, block_y + 29, config.metadata.name)
    c.drawString(block_x + 5, block_y + 8, drawing.part_name)
    c.drawString(block_x + 155, block_y + 29, f"REV: {config.metadata.revision}")
    c.drawString(block_x + 155, block_y + 8, "SCALE: FIT")

    c.showPage()
    c.save()


def export_all_2d(config: ProjectConfig, output_dir: Path) -> list[Path]:
    generated: list[Path] = []
    drawings = build_drawing_sets(config)
    enabled_views = {
        "front": config.drawing.include_front,
        "top": config.drawing.include_top,
        "side": config.drawing.include_side,
    }
    if not any(enabled_views.values()):
        raise ValueError("At least one of front, top, or side drawing views must be enabled")

    for slug, full_drawing in drawings.items():
        drawing = DrawingSet(
            part_name=full_drawing.part_name,
            views={name: view for name, view in full_drawing.views.items() if enabled_views[name]},
            notes=full_drawing.notes,
        )
        part_dir = output_dir / slug
        part_dir.mkdir(parents=True, exist_ok=True)
        if config.artifacts.export_dxf:
            path = part_dir / f"{slug}_views.dxf"
            export_dxf(drawing, config, path)
            generated.append(path)
        if config.artifacts.export_svg:
            for view_name, view in drawing.views.items():
                path = part_dir / f"{slug}_{view_name}.svg"
                export_svg(view, config, path)
                generated.append(path)
        if config.artifacts.export_pdf:
            path = part_dir / f"{slug}_drawing.pdf"
            export_pdf(drawing, config, path)
            generated.append(path)
    return generated
