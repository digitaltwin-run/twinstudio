from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

from .models import ProjectConfig
from .validation import board_origin


def _load_mesh(path: Path) -> trimesh.Trimesh:
    loaded = trimesh.load(path, force="mesh", process=False)
    if isinstance(loaded, trimesh.Scene):
        mesh = loaded.dump(concatenate=True)
    else:
        mesh = loaded
    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError(f"Could not load mesh from {path}")
    return mesh


def export_obj_from_stl(stl_path: Path, obj_path: Path) -> None:
    obj_path.parent.mkdir(parents=True, exist_ok=True)
    mesh = _load_mesh(stl_path)
    mesh.export(obj_path)


def _set_rgba(mesh: trimesh.Trimesh, rgba: tuple[int, int, int, int]) -> None:
    mesh.visual.face_colors = np.tile(np.asarray(rgba, dtype=np.uint8), (len(mesh.faces), 1))


def _board_mesh(config: ProjectConfig, which: str) -> trimesh.Trimesh:
    position = config.board.position_a if which == "A" else config.board.position_b
    x0, y0 = board_origin(config, position)
    z0 = (
        config.dimensions.floor_thickness
        + config.board.standoff.height
        + config.board.thickness / 2.0
    )
    board = trimesh.creation.box(
        extents=(config.board.width, config.board.length, config.board.thickness)
    )
    board.apply_translation(
        (
            x0 + config.board.width / 2.0,
            y0 + config.board.length / 2.0,
            z0,
        )
    )
    return board


def export_preview_scenes(
    config: ProjectConfig,
    base_stl: Path,
    lid_stl: Path,
    closed_glb: Path,
    open_glb: Path | None = None,
) -> dict[str, list[float]]:
    base = _load_mesh(base_stl)
    lid = _load_mesh(lid_stl)
    _set_rgba(base, (150, 155, 165, 255))
    _set_rgba(lid, (210, 212, 218, 255))

    closed = trimesh.Scene()
    closed.add_geometry(base.copy(), node_name="base", geom_name="base")
    closed.add_geometry(lid.copy(), node_name="lid", geom_name="lid")

    if config.feature_layers.pcb_reference.enabled:
        board_a = _board_mesh(config, "A")
        board_b = _board_mesh(config, "B")
        _set_rgba(board_a, (55, 145, 85, 170))
        _set_rgba(board_b, (70, 105, 190, 130))
        closed.add_geometry(board_a, node_name="pcb_position_a", geom_name="pcb_position_a")
        closed.add_geometry(board_b, node_name="pcb_position_b", geom_name="pcb_position_b")

    closed_glb.parent.mkdir(parents=True, exist_ok=True)
    closed.export(closed_glb)

    if open_glb is not None:
        open_scene = trimesh.Scene()
        open_scene.add_geometry(base.copy(), node_name="base", geom_name="base")
        angle = np.deg2rad(config.hinge.opening_angle_deg)
        axis_point = np.array(
            [
                0.0,
                config.hinge.axis_y,
                config.dimensions.base_height
                + config.hinge.axis_z_offset_from_base_top,
            ]
        )
        transform = trimesh.transformations.rotation_matrix(
            angle=angle,
            direction=[1.0, 0.0, 0.0],
            point=axis_point,
        )
        opened_lid = lid.copy()
        opened_lid.apply_transform(transform)
        open_scene.add_geometry(opened_lid, node_name="lid_open", geom_name="lid_open")
        open_scene.export(open_glb)

    bounds = closed.bounds
    return {
        "min": [float(v) for v in bounds[0]],
        "max": [float(v) for v in bounds[1]],
    }
