from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Iterable

import cadquery as cq

from .models import ConnectorOpening, ProjectConfig
from .validation import board_hole_centers, hinge_segments


EPS = 0.15


@dataclass(slots=True)
class ModelSet:
    base: cq.Workplane
    lid: cq.Workplane
    assembly: cq.Assembly
    hinge_axis: tuple[float, float, float]


def _wire_rect(x: float, y: float, z: float, width: float, depth: float) -> cq.Wire:
    return (
        cq.Workplane("XY", origin=(x, y, z))
        .rect(width, depth, centered=False)
        .val()
    )


def _cylinder_along_x(
    x_start: float,
    length: float,
    center_y: float,
    center_z: float,
    diameter: float,
) -> cq.Workplane:
    return (
        cq.Workplane("YZ", origin=(x_start, 0, 0))
        .center(center_y, center_z)
        .circle(diameter / 2.0)
        .extrude(length)
    )


def _cylinder_along_y(
    y_start: float,
    length: float,
    center_x: float,
    center_z: float,
    diameter: float,
) -> cq.Workplane:
    solid = cq.Solid.makeCylinder(
        diameter / 2.0,
        length,
        cq.Vector(center_x, y_start, center_z),
        cq.Vector(0.0, 1.0, 0.0),
    )
    return cq.Workplane(obj=solid)


def _add_vertical_boss(
    solid: cq.Workplane,
    x: float,
    y: float,
    z_bottom: float,
    height: float,
    outer_diameter: float,
    hole_diameter: float,
) -> cq.Workplane:
    boss = (
        cq.Workplane("XY", origin=(0, 0, z_bottom - EPS))
        .center(x, y)
        .circle(outer_diameter / 2.0)
        .extrude(height + EPS)
    )
    result = solid.union(boss)
    hole = (
        cq.Workplane("XY", origin=(0, 0, z_bottom - 2.0 * EPS))
        .center(x, y)
        .circle(hole_diameter / 2.0)
        .extrude(height + 4.0 * EPS)
    )
    return result.cut(hole)


def _opening_cut_box(config: ProjectConfig, opening: ConnectorOpening) -> cq.Workplane:
    d = config.dimensions
    wall = d.wall_thickness
    cut_thickness = wall + 2.0
    radius = min(opening.corner_radius, opening.width / 2.0, opening.height / 2.0)

    if opening.wall in {"front", "rear"}:
        y_start = -1.0 if opening.wall == "front" else d.external_depth - wall - 1.0
        x_left = opening.center_horizontal - opening.width / 2.0
        if radius <= 1e-9:
            return (
                cq.Workplane("XY")
                .box(opening.width, cut_thickness, opening.height, centered=False)
                .translate((x_left, y_start, opening.bottom_z))
            )
        result = (
            cq.Workplane("XY")
            .box(opening.width - 2.0 * radius, cut_thickness, opening.height, centered=False)
            .translate((x_left + radius, y_start, opening.bottom_z))
        )
        result = result.union(
            cq.Workplane("XY")
            .box(opening.width, cut_thickness, opening.height - 2.0 * radius, centered=False)
            .translate((x_left, y_start, opening.bottom_z + radius))
        )
        for x in (x_left + radius, x_left + opening.width - radius):
            for z in (opening.bottom_z + radius, opening.bottom_z + opening.height - radius):
                result = result.union(_cylinder_along_y(y_start, cut_thickness, x, z, 2.0 * radius))
        return result

    x_start = -1.0 if opening.wall == "left" else d.external_width - wall - 1.0
    y_left = opening.center_horizontal - opening.width / 2.0
    if radius <= 1e-9:
        return (
            cq.Workplane("XY")
            .box(cut_thickness, opening.width, opening.height, centered=False)
            .translate((x_start, y_left, opening.bottom_z))
        )
    result = (
        cq.Workplane("XY")
        .box(cut_thickness, opening.width - 2.0 * radius, opening.height, centered=False)
        .translate((x_start, y_left + radius, opening.bottom_z))
    )
    result = result.union(
        cq.Workplane("XY")
        .box(cut_thickness, opening.width, opening.height - 2.0 * radius, centered=False)
        .translate((x_start, y_left, opening.bottom_z + radius))
    )
    for y in (y_left + radius, y_left + opening.width - radius):
        for z in (opening.bottom_z + radius, opening.bottom_z + opening.height - radius):
            result = result.union(_cylinder_along_x(x_start, cut_thickness, y, z, 2.0 * radius))
    return result


def make_base(config: ProjectConfig) -> cq.Workplane:
    d = config.dimensions
    layers = config.feature_layers

    if not layers.base_shell.enabled:
        return cq.Workplane("XY").box(0.1, 0.1, 0.1, centered=False)

    outer = cq.Workplane("XY").box(
        d.external_width,
        d.external_depth,
        d.base_height,
        centered=(False, False, False),
    )
    if d.edge_radius > 0.0:
        outer = outer.edges("|Z").fillet(d.edge_radius)

    inner = (
        cq.Workplane("XY")
        .box(
            d.internal_width,
            d.internal_depth,
            d.base_height - d.floor_thickness + 1.0,
            centered=(False, False, False),
        )
        .translate((d.wall_thickness, d.wall_thickness, d.floor_thickness))
    )
    result = outer.cut(inner)

    chamfer_drop = config.hinge.base_front_chamfer_size
    if chamfer_drop > 0.0:
        # Triangular prism removing the sharp top/front outer corner. The configured
        # angle is measured from the base plane; base_front_chamfer_size is the
        # vertical drop. At 45 degrees the horizontal run equals the drop.
        angle_rad = math.radians(config.hinge.base_front_chamfer_angle_deg)
        chamfer_run = chamfer_drop / max(math.tan(angle_rad), 1e-9)
        wedge = (
            cq.Workplane("YZ", origin=(0, 0, 0))
            .moveTo(0.0, d.base_height)
            .lineTo(chamfer_run, d.base_height)
            .lineTo(0.0, d.base_height - chamfer_drop)
            .close()
            .extrude(d.external_width)
        )
        result = result.cut(wedge)

    if layers.connector_openings.enabled:
        for opening in config.connector_openings:
            if opening.enabled:
                result = result.cut(_opening_cut_box(config, opening))

    standoff = config.board.standoff
    if layers.pcb_mount_a.enabled:
        for x, y in board_hole_centers(config, config.board.position_a):
            result = _add_vertical_boss(
                result,
                x,
                y,
                d.floor_thickness,
                standoff.height,
                standoff.outer_diameter,
                standoff.pilot_hole_diameter,
            )
    if layers.pcb_mount_b.enabled:
        for x, y in board_hole_centers(config, config.board.position_b):
            result = _add_vertical_boss(
                result,
                x,
                y,
                d.floor_thickness,
                standoff.height,
                standoff.outer_diameter,
                standoff.pilot_hole_diameter,
            )

    if layers.hinge.enabled:
        axis_z = d.base_height + config.hinge.axis_z_offset_from_base_top
        axis_y = config.hinge.axis_y

        # Lower the top edge of the base front wall in the two ranges occupied
        # by the lid knuckles. This implements the requested 1.5 mm class
        # rotational relief without cutting the base-owned knuckles.
        if config.hinge.base_wall_relief > 0.0:
            half_gap = config.hinge.inter_knuckle_gap / 2.0
            for segment in hinge_segments(config):
                if segment["owner"] != "lid":
                    continue
                x0 = max(0.0, float(segment["x_start"]) - half_gap)
                x1 = min(d.external_width, float(segment["x_end"]) + half_gap)
                relief = (
                    cq.Workplane("XY")
                    .box(
                        x1 - x0,
                        d.wall_thickness + 2.0 * EPS,
                        config.hinge.base_wall_relief + 2.0 * EPS,
                        centered=False,
                    )
                    .translate(
                        (
                            x0,
                            -EPS,
                            d.base_height - config.hinge.base_wall_relief - EPS,
                        )
                    )
                )
                result = result.cut(relief)

        for segment in hinge_segments(config):
            if segment["owner"] != "base":
                continue
            knuckle = _cylinder_along_x(
                float(segment["x_start"]),
                float(segment["length"]),
                axis_y,
                axis_z,
                config.hinge.outer_diameter,
            )
            result = result.union(knuckle)

        pin_hole = _cylinder_along_x(
            -1.0,
            d.external_width + 2.0,
            axis_y,
            axis_z,
            config.hinge.bore_diameter,
        )
        result = result.cut(pin_hole)

    return result.clean()


def _make_lid_shell(config: ProjectConfig) -> cq.Workplane:
    d = config.dimensions
    z0 = d.base_height
    z1 = z0 + d.lid_vertical_lower_section
    z2 = d.total_height

    outer_wires = [
        _wire_rect(0.0, 0.0, z0, d.external_width, d.external_depth),
        _wire_rect(0.0, 0.0, z1, d.external_width, d.external_depth),
        _wire_rect(
            d.lid_side_inset,
            d.lid_front_inset,
            z2,
            d.top_width,
            d.top_depth,
        ),
    ]
    outer = cq.Solid.makeLoft(outer_wires, True)
    if d.edge_radius > 0.0:
        outer = cq.Workplane(obj=outer).edges(">Z").fillet(d.edge_radius).val()

    inner_bottom_z = z0 - EPS
    inner_mid_z = z1
    inner_top_z = z2 - d.lid_top_thickness

    sloped_height = max(z2 - z1, 1e-9)
    fraction = max(0.0, min(1.0, (inner_top_z - z1) / sloped_height))
    side_inset_at_inner_top = d.lid_side_inset * fraction
    front_inset_at_inner_top = d.lid_front_inset * fraction
    rear_inset_at_inner_top = d.lid_rear_inset * fraction
    outer_width_at_inner_top = d.external_width - 2.0 * side_inset_at_inner_top
    outer_depth_at_inner_top = (
        d.external_depth - front_inset_at_inner_top - rear_inset_at_inner_top
    )

    inner_wires = [
        _wire_rect(
            d.wall_thickness,
            d.wall_thickness,
            inner_bottom_z,
            d.internal_width,
            d.internal_depth,
        ),
        _wire_rect(
            d.wall_thickness,
            d.wall_thickness,
            inner_mid_z,
            d.internal_width,
            d.internal_depth,
        ),
        _wire_rect(
            side_inset_at_inner_top + d.wall_thickness,
            front_inset_at_inner_top + d.wall_thickness,
            inner_top_z,
            outer_width_at_inner_top - 2.0 * d.wall_thickness,
            outer_depth_at_inner_top - 2.0 * d.wall_thickness,
        ),
    ]
    inner = cq.Solid.makeLoft(inner_wires, True)
    return cq.Workplane(obj=outer.cut(inner))


def _camera_positions(config: ProjectConfig) -> Iterable[tuple[float, float]]:
    c = config.camera_mounts
    x0 = c.center_x - ((c.columns - 1) * c.x_pitch) / 2.0
    y0 = c.center_y - ((c.rows - 1) * c.y_pitch) / 2.0
    for row in range(c.rows):
        for column in range(c.columns):
            yield x0 + column * c.x_pitch, y0 + row * c.y_pitch


def _auxiliary_boss_positions(config: ProjectConfig) -> list[tuple[float, float]]:
    b = config.auxiliary_lid_bosses
    return [
        (b.center_x - b.x_span / 2.0, b.center_y - b.y_span / 2.0),
        (b.center_x + b.x_span / 2.0, b.center_y - b.y_span / 2.0),
        (b.center_x - b.x_span / 2.0, b.center_y + b.y_span / 2.0),
        (b.center_x + b.x_span / 2.0, b.center_y + b.y_span / 2.0),
    ]


def _add_locating_lip(result: cq.Workplane, config: ProjectConfig) -> cq.Workplane:
    d = config.dimensions
    mating = config.mating
    z_bottom = d.base_height - mating.locating_lip_height
    z_height = mating.locating_lip_height + EPS
    x0 = d.wall_thickness + mating.fit_clearance
    y0 = d.wall_thickness + mating.fit_clearance
    outer_w = d.internal_width - 2.0 * mating.fit_clearance
    outer_d = d.internal_depth - 2.0 * mating.fit_clearance
    t = mating.locating_lip_thickness

    if min(outer_w, outer_d) <= 2.0 * t:
        return result

    strips = [
        # Left and right strips.
        cq.Workplane("XY")
        .box(t, outer_d - mating.front_gap_for_hinge, z_height, centered=False)
        .translate((x0, y0 + mating.front_gap_for_hinge, z_bottom)),
        cq.Workplane("XY")
        .box(t, outer_d - mating.front_gap_for_hinge, z_height, centered=False)
        .translate((x0 + outer_w - t, y0 + mating.front_gap_for_hinge, z_bottom)),
        # Rear strip.
        cq.Workplane("XY")
        .box(outer_w, t, z_height, centered=False)
        .translate((x0, y0 + outer_d - t, z_bottom)),
    ]
    for strip in strips:
        result = result.union(strip)
    return result


def make_lid(config: ProjectConfig) -> cq.Workplane:
    d = config.dimensions
    layers = config.feature_layers

    if not layers.lid_shell.enabled:
        return cq.Workplane("XY").box(0.1, 0.1, 0.1, centered=False)

    result = _make_lid_shell(config)

    if layers.hinge.enabled:
        axis_z = d.base_height + config.hinge.axis_z_offset_from_base_top
        axis_y = config.hinge.axis_y

        # Remove the lower front edge in the three ranges occupied by the
        # base knuckles. The relief is applied along the complete segment
        # length, which gives the lid rotational clearance requested in the brief.
        if config.hinge.lid_edge_relief > 0.0:
            half_gap = config.hinge.inter_knuckle_gap / 2.0
            for segment in hinge_segments(config):
                if segment["owner"] != "base":
                    continue
                x0 = max(0.0, float(segment["x_start"]) - half_gap)
                x1 = min(d.external_width, float(segment["x_end"]) + half_gap)
                relief = (
                    cq.Workplane("XY")
                    .box(
                        x1 - x0,
                        d.wall_thickness + 2.0 * EPS,
                        config.hinge.lid_edge_relief + 2.0 * EPS,
                        centered=False,
                    )
                    .translate((x0, -EPS, d.base_height - EPS))
                )
                result = result.cut(relief)

        for segment in hinge_segments(config):
            if segment["owner"] != "lid":
                continue
            knuckle = _cylinder_along_x(
                float(segment["x_start"]),
                float(segment["length"]),
                axis_y,
                axis_z,
                config.hinge.outer_diameter,
            )
            result = result.union(knuckle)

        pin_hole = _cylinder_along_x(
            -1.0,
            d.external_width + 2.0,
            axis_y,
            axis_z,
            config.hinge.bore_diameter,
        )
        result = result.cut(pin_hole)

    if layers.camera_mounts.enabled:
        c = config.camera_mounts
        z_top = d.total_height - d.lid_top_thickness + c.embed_depth
        z_bottom = z_top - c.boss_height_after_reduction
        for x, y in _camera_positions(config):
            result = _add_vertical_boss(
                result,
                x,
                y,
                z_bottom,
                c.boss_height_after_reduction,
                c.outer_diameter,
                c.hole_diameter,
            )

    if layers.lid_aux_bosses.enabled:
        b = config.auxiliary_lid_bosses
        z_top = d.base_height + b.top_z_from_base_mating_plane
        z_bottom = z_top - b.boss_height
        for x, y in _auxiliary_boss_positions(config):
            result = _add_vertical_boss(
                result,
                x,
                y,
                z_bottom,
                b.boss_height,
                b.outer_diameter,
                b.hole_diameter,
            )

    if layers.rear_tabs.enabled and config.rear_tabs.count > 0:
        tabs = config.rear_tabs
        inner_rear_y = d.external_depth - d.wall_thickness
        y0 = inner_rear_y - tabs.thickness
        usable_x = d.internal_width
        spacing = usable_x / (tabs.count + 1)
        z0 = d.base_height + d.lid_vertical_lower_section
        inner_roof_z = d.total_height - d.lid_top_thickness
        target_height = max(
            0.5,
            inner_roof_z - tabs.clearance_to_inner_wall - z0,
        )
        effective_height = max(tabs.height, target_height)
        effective_height = min(effective_height, inner_roof_z - z0)
        for index in range(tabs.count):
            center_x = d.wall_thickness + spacing * (index + 1)
            tab = (
                cq.Workplane("XY")
                .box(tabs.width, tabs.thickness + EPS, effective_height, centered=False)
                .translate((center_x - tabs.width / 2.0, y0, z0))
            )
            result = result.union(tab)

    if layers.locating_lip.enabled and config.mating.locating_lip_height > 0.0:
        result = _add_locating_lip(result, config)

    return result.clean()


def make_models(config: ProjectConfig) -> ModelSet:
    base = make_base(config)
    lid = make_lid(config)
    assembly = cq.Assembly(name=config.metadata.name)
    assembly.add(base, name="base")
    assembly.add(lid, name="lid")
    hinge_axis = (
        0.0,
        config.hinge.axis_y,
        config.dimensions.base_height + config.hinge.axis_z_offset_from_base_top,
    )
    return ModelSet(base=base, lid=lid, assembly=assembly, hinge_axis=hinge_axis)


def export_part(
    part: cq.Workplane,
    step_path: Path | None = None,
    stl_path: Path | None = None,
    mesh_tolerance: float = 0.08,
    angular_tolerance: float = 0.15,
) -> None:
    if step_path is not None:
        step_path.parent.mkdir(parents=True, exist_ok=True)
        cq.exporters.export(part, str(step_path), exportType="STEP")
    if stl_path is not None:
        stl_path.parent.mkdir(parents=True, exist_ok=True)
        cq.exporters.export(
            part,
            str(stl_path),
            exportType="STL",
            tolerance=mesh_tolerance,
            angularTolerance=angular_tolerance,
        )


def export_assembly_step(assembly: cq.Assembly, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Assembly.save is the CadQuery-supported route for multi-part STEP output.
    assembly.save(str(path))


def shape_stats(part: cq.Workplane) -> dict[str, float | list[float]]:
    shape = part.val()
    bb = shape.BoundingBox()
    return {
        "volume_mm3": float(shape.Volume()),
        "bounding_box_mm": [
            float(bb.xlen),
            float(bb.ylen),
            float(bb.zlen),
        ],
    }
