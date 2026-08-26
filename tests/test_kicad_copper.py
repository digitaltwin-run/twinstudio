from __future__ import annotations

import pytest

from twinstudio.kicad_copper import (
    Bounds,
    Box,
    RoutingError,
    route_edge,
    route_net,
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


def _length(tracks) -> float:
    return sum(abs(t.x1 - t.x0) + abs(t.y1 - t.y0) for t in tracks)


def test_branch_taps_into_routed_copper_instead_of_returning_to_a_pad() -> None:
    bounds = Bounds(-20.0, -20.0, 120.0, 130.0)
    # The third pad sits beside the middle of the first leg: both existing pads
    # are 70 mm away, the copper between them only 20 mm.
    tracks = route_net(
        [(0.0, 0.0), (0.0, 100.0), (20.0, 50.0)],
        net=1,
        obstacles=[],
        bounds=bounds,
        width=0.2,
        clearance=0.2,
    )

    # Connecting every branch back to a pad costs 140 mm on this topology.
    assert _length(tracks) == pytest.approx(120.0)
    assert all(
        track_is_clear(track, 1, [], 0.1, 0.2) for track in tracks
    )


def test_collinear_pads_are_unaffected_by_the_tap_in_rule() -> None:
    bounds = Bounds(-20.0, -20.0, 260.0, 130.0)
    # panel9's +5V net: a tap-in cannot beat the straight run, and must not
    # make it worse either.
    tracks = route_net(
        [(101.59, 84.0), (229.2, 95.75), (229.2, 97.25)],
        net=1,
        obstacles=[],
        bounds=bounds,
        width=0.2,
        clearance=0.2,
    )

    assert _length(tracks) == pytest.approx(140.86, abs=0.01)
