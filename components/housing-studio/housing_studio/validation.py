from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .models import BoardPosition, ProjectConfig


@dataclass(slots=True)
class DesignWarning:
    code: str
    severity: str
    message: str
    suggestion: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


def board_origin(config: ProjectConfig, position: BoardPosition) -> tuple[float, float]:
    """Return the PCB lower-left XY coordinate in the global enclosure coordinate system.

    X is left-to-right, Y is front-to-rear, and the internal wall surfaces are located at
    wall_thickness and external_size - wall_thickness.
    """

    d = config.dimensions
    b = config.board
    inner_left = d.wall_thickness
    inner_front = d.wall_thickness
    inner_right = d.external_width - d.wall_thickness

    if position.anchor == "right":
        x = inner_right - position.right_clearance - b.width
    elif position.anchor == "left":
        left_clearance = position.expected_left_clearance or 0.0
        x = inner_left + left_clearance
    else:
        x = inner_left + (d.internal_width - b.width) / 2.0

    y = inner_front + position.front_clearance
    return x, y


def board_actual_clearances(
    config: ProjectConfig, position: BoardPosition
) -> dict[str, float]:
    x, y = board_origin(config, position)
    d = config.dimensions
    b = config.board
    inner_left = d.wall_thickness
    inner_front = d.wall_thickness
    inner_right = d.external_width - d.wall_thickness
    inner_rear = d.external_depth - d.wall_thickness
    return {
        "left": x - inner_left,
        "right": inner_right - (x + b.width),
        "front": y - inner_front,
        "rear": inner_rear - (y + b.length),
    }


def board_hole_centers(config: ProjectConfig, position: BoardPosition) -> list[tuple[float, float]]:
    """Return four Raspberry Pi mounting-hole centres for a board position."""

    b = config.board
    x0, y0 = board_origin(config, position)
    o = b.first_hole_edge_offset
    x_positions = [x0 + o, x0 + o + b.hole_spacing_width]
    y_positions = [y0 + o, y0 + o + b.hole_spacing_length]
    return [(x, y) for y in y_positions for x in x_positions]


def hinge_segments(config: ProjectConfig) -> list[dict[str, float | str | int]]:
    """Compute five interleaved hinge knuckle segments across enclosure width."""

    width = config.dimensions.external_width
    hinge = config.hinge
    usable = width - 2.0 * hinge.side_margin - 4.0 * hinge.inter_knuckle_gap
    segment_length = usable / 5.0
    segments: list[dict[str, float | str | int]] = []
    x = hinge.side_margin
    for index in range(5):
        owner = "base" if index % 2 == 0 else "lid"
        segments.append(
            {
                "index": index,
                "owner": owner,
                "x_start": x,
                "length": segment_length,
                "x_end": x + segment_length,
            }
        )
        x += segment_length + hinge.inter_knuckle_gap
    return segments


def collect_warnings(config: ProjectConfig) -> list[DesignWarning]:
    warnings: list[DesignWarning] = []
    d = config.dimensions
    b = config.board

    # The source material fixes the 80 mm flat top section, but not the total
    # enclosure depth. The default 95 mm depth is therefore a transparent
    # working assumption: 13 mm front inset + 80 mm flat section + 2 mm rear inset.
    if (
        abs(d.external_depth - 95.0) <= 0.01
        and abs(d.top_depth - 80.0) <= 0.01
        and abs(d.lid_front_inset - 13.0) <= 0.01
        and abs(d.lid_rear_inset - 2.0) <= 0.01
    ):
        warnings.append(
            DesignWarning(
                code="EXTERNAL_DEPTH_WORKING_ASSUMPTION",
                severity="info",
                message=(
                    "The 95.00 mm total external depth is a working assumption derived from "
                    "the 80.00 mm flat lid section plus configured 13.00 mm front and 2.00 mm rear insets. "
                    "The supplied source did not independently dimension the total depth."
                ),
                suggestion="Confirm the total external depth before production or edit dimensions.external_depth.",
            )
        )

    if config.feature_layers.connector_openings.enabled and any(
        opening.enabled for opening in config.connector_openings
    ):
        warnings.append(
            DesignWarning(
                code="CONNECTOR_OPENING_REQUIRES_VERIFICATION",
                severity="info",
                message=(
                    "Connector openings are configurable reference geometry. Their exact dimensions and positions "
                    "must be checked against the final Raspberry Pi/component assembly and plug bodies."
                ),
            )
        )

    # The source dimensions 7.5 + 56 + 10.5 = 74 mm conflict with a 79 mm
    # external width and 2 mm walls, which create a 75 mm internal width.
    clear_b = board_actual_clearances(config, b.position_b)
    expected_left = b.position_b.expected_left_clearance
    if expected_left is not None and abs(clear_b["left"] - expected_left) > 0.05:
        warnings.append(
            DesignWarning(
                code="PCB_B_CLEARANCE_MISMATCH",
                severity="warning",
                message=(
                    f"Mounting position B is anchored to the requested right clearance "
                    f"({b.position_b.right_clearance:.2f} mm), which produces an actual left "
                    f"clearance of {clear_b['left']:.2f} mm instead of {expected_left:.2f} mm."
                ),
                suggestion=(
                    "Change the external width, wall thickness, PCB width, or choose which side "
                    "clearance is authoritative. The generator does not silently average them."
                ),
            )
        )

    for label, position in (("A", b.position_a), ("B", b.position_b)):
        actual = board_actual_clearances(config, position)
        for side, value in actual.items():
            if value < -0.01:
                warnings.append(
                    DesignWarning(
                        code=f"PCB_{label}_OUTSIDE_{side.upper()}",
                        severity="error",
                        message=f"PCB mounting position {label} exceeds the {side} internal wall by {-value:.2f} mm.",
                        suggestion="Increase the enclosure size or change the PCB position.",
                    )
                )

    chamfer_run = config.hinge.base_front_chamfer_size / max(
        math.tan(math.radians(config.hinge.base_front_chamfer_angle_deg)), 1e-9
    )
    if chamfer_run > d.wall_thickness + 0.05:
        warnings.append(
            DesignWarning(
                code="BASE_CHAMFER_REACHES_CAVITY",
                severity="warning",
                message=(
                    f"The front base chamfer has a {chamfer_run:.2f} mm horizontal run, "
                    f"which is greater than the {d.wall_thickness:.2f} mm front wall thickness."
                ),
                suggestion="Increase the chamfer angle, reduce its drop, or verify the intended internal transition.",
            )
        )

    rise = d.lid_height - d.lid_vertical_lower_section
    front_angle = math.degrees(math.atan2(rise, max(d.lid_front_inset, 1e-9)))
    side_angle = math.degrees(math.atan2(rise, max(d.lid_side_inset, 1e-9)))
    if front_angle < 45.0 - 0.1:
        warnings.append(
            DesignWarning(
                code="FRONT_OVERHANG_BELOW_45",
                severity="warning",
                message=f"The front lid wall angle is {front_angle:.1f}°, below the requested 45° support-free target.",
                suggestion="Reduce lid_front_inset or increase lid height.",
            )
        )
    if side_angle < 45.0 - 0.1:
        warnings.append(
            DesignWarning(
                code="SIDE_OVERHANG_BELOW_45",
                severity="warning",
                message=f"The side lid wall angle is {side_angle:.1f}°, below 45°.",
                suggestion="Reduce lid_side_inset or increase lid height.",
            )
        )

    boss = config.auxiliary_lid_bosses
    inner_roof_z = d.lid_height - d.lid_top_thickness
    if boss.top_z_from_base_mating_plane > d.lid_height:
        warnings.append(
            DesignWarning(
                code="AUX_BOSS_TOP_ABOVE_LID",
                severity="error",
                message=(
                    f"Auxiliary boss top datum ({boss.top_z_from_base_mating_plane:.2f} mm) "
                    f"is above the lid height ({d.lid_height:.2f} mm)."
                ),
                suggestion="Lower the boss top datum or increase the lid height.",
            )
        )
    elif boss.top_z_from_base_mating_plane > inner_roof_z:
        warnings.append(
            DesignWarning(
                code="AUX_BOSS_EMBEDDED_IN_ROOF",
                severity="info",
                message=(
                    f"Auxiliary bosses extend {boss.top_z_from_base_mating_plane - inner_roof_z:.2f} mm "
                    "into the lid roof to create a structural attachment."
                ),
            )
        )

    if config.hinge.opening_angle_deg <= 190.0:
        warnings.append(
            DesignWarning(
                code="HINGE_OPENING_TOO_SMALL",
                severity="warning",
                message=(
                    f"Configured hinge opening is {config.hinge.opening_angle_deg:.1f}°, "
                    "but the requirement is greater than 190°."
                ),
                suggestion="Set hinge.opening_angle_deg above 190.",
            )
        )

    if config.feature_layers.rear_tabs.enabled and config.rear_tabs.middle_wall_reduction > 0.0:
        warnings.append(
            DesignWarning(
                code="REAR_MIDDLE_WALL_DETAIL_SIMPLIFIED",
                severity="info",
                message=(
                    "The rear tabs are generated and extended toward the inner roof using the configured clearance, "
                    "but the separate wall section between the tabs is represented only as a documented simplified detail."
                ),
                suggestion="Confirm the exact cross-section of the 4 mm reduced middle wall before production.",
            )
        )

    if config.feature_layers.locating_lip.enabled:
        a = board_actual_clearances(config, b.position_a)
        occupied = config.mating.locating_lip_thickness + config.mating.fit_clearance
        if a["right"] < occupied:
            warnings.append(
                DesignWarning(
                    code="LOCATING_LIP_PCB_INTERFERENCE",
                    severity="warning",
                    message=(
                        "The enabled locating lip may overlap PCB position A near the right wall: "
                        f"available clearance {a['right']:.2f} mm, nominal lip zone {occupied:.2f} mm."
                    ),
                    suggestion="Disable the right lip segment, reduce lip thickness, or move the PCB.",
                )
            )

    if d.top_depth < b.length - 5.0:
        warnings.append(
            DesignWarning(
                code="TOP_FLAT_SHORTER_THAN_BOARD",
                severity="info",
                message=(
                    f"The flat lid top is {d.top_depth:.2f} mm long while the PCB is {b.length:.2f} mm. "
                    "This is acceptable only if components clear the sloped regions."
                ),
            )
        )

    warnings.append(
        DesignWarning(
            code="PHYSICAL_PROTOTYPE_REQUIRED",
            severity="info",
            message=(
                "The generated hinge, connector opening, tolerances, and support-free angles are parametric CAD assumptions. "
                "Verify them with a printed prototype before production."
            ),
        )
    )

    return warnings


def design_metrics(config: ProjectConfig) -> dict[str, float | dict[str, float]]:
    d = config.dimensions
    rise = d.lid_height - d.lid_vertical_lower_section
    return {
        "internal_width": d.internal_width,
        "internal_depth": d.internal_depth,
        "lid_height": d.lid_height,
        "top_width": d.top_width,
        "top_depth": d.top_depth,
        "front_lid_angle_deg": math.degrees(math.atan2(rise, max(d.lid_front_inset, 1e-9))),
        "rear_lid_angle_deg": math.degrees(math.atan2(rise, max(d.lid_rear_inset, 1e-9))),
        "side_lid_angle_deg": math.degrees(math.atan2(rise, max(d.lid_side_inset, 1e-9))),
        "board_position_a_clearances": board_actual_clearances(config, config.board.position_a),
        "board_position_b_clearances": board_actual_clearances(config, config.board.position_b),
    }
