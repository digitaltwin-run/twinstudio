from __future__ import annotations

import pytest

from twinstudio.kicad_copper import (
    Bounds,
    Box,
    RoutingError,
    route_edge,
    track_is_clear,
)


def test_route_edge_returns_clear_path_around_foreign_pad() -> None:
    obstacle = Box(net=2, x0=4.0, y0=-1.0, x1=6.0, y1=1.0)
    path = route_edge(
        (0.0, 0.0),
        (10.0, 0.0),
        net=1,
        obstacles=[obstacle],
        bounds=Bounds(-2.0, -3.0, 12.0, 3.0),
        width=0.2,
        clearance=0.2,
    )

    assert path[0].x0 == 0.0 and path[0].y0 == 0.0
    assert path[-1].x1 == 10.0 and path[-1].y1 == 0.0
    assert all(track_is_clear(track, 1, [obstacle], 0.1, 0.2) for track in path)
    assert any(abs(track.y0) > 1.0 or abs(track.y1) > 1.0 for track in path)


def test_route_edge_fails_when_foreign_copper_blocks_bounds() -> None:
    wall = Box(net=2, x0=4.0, y0=-3.0, x1=6.0, y1=3.0)

    with pytest.raises(RoutingError):
        route_edge(
            (0.0, 0.0),
            (10.0, 0.0),
            net=1,
            obstacles=[wall],
            bounds=Bounds(-2.0, -3.0, 12.0, 3.0),
            width=0.2,
            clearance=0.2,
        )
