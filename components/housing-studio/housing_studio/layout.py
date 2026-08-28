"""Canonical mechanical point placement shared by 2D and 3D projections."""
from __future__ import annotations

from collections.abc import Iterator

from .models import ProjectConfig


def camera_positions(config: ProjectConfig) -> Iterator[tuple[float, float]]:
    mounts = config.camera_mounts
    x0 = mounts.center_x - ((mounts.columns - 1) * mounts.x_pitch) / 2.0
    y0 = mounts.center_y - ((mounts.rows - 1) * mounts.y_pitch) / 2.0
    for row in range(mounts.rows):
        for column in range(mounts.columns):
            yield x0 + column * mounts.x_pitch, y0 + row * mounts.y_pitch


def auxiliary_boss_positions(config: ProjectConfig) -> list[tuple[float, float]]:
    bosses = config.auxiliary_lid_bosses
    return [
        (bosses.center_x - bosses.x_span / 2.0, bosses.center_y - bosses.y_span / 2.0),
        (bosses.center_x + bosses.x_span / 2.0, bosses.center_y - bosses.y_span / 2.0),
        (bosses.center_x - bosses.x_span / 2.0, bosses.center_y + bosses.y_span / 2.0),
        (bosses.center_x + bosses.x_span / 2.0, bosses.center_y + bosses.y_span / 2.0),
    ]
