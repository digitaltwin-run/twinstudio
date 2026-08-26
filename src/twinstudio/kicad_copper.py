"""Deterministyczne naprawy miedzi dla kandydatów EDA.

Zmiana netu na padzie nie przesuwa miedzi: ścieżka, która kończyła się na
padzie sygnałowym, po przepięciu pinoutu leży na padzie o innym necie i
KiCad zgłasza `clearance`, `solder_mask_bridge` oraz `unconnected_items`.
Ten moduł operuje wyłącznie na geometrii (bez S-wyrażeń) i dostarcza dwie
operacje: przepięcie kikutów oraz trasowanie nowo utworzonego netu.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class Capsule:
    """Ścieżka lub przelotka: odcinek o zadanym promieniu."""

    net: int
    ax: float
    ay: float
    bx: float
    by: float
    radius: float


@dataclass(frozen=True, slots=True)
class Box:
    """Pad przybliżony prostokątem opisanym na jego obrysie."""

    net: int
    x0: float
    y0: float
    x1: float
    y1: float


Obstacle = Capsule | Box


@dataclass(frozen=True, slots=True)
class Bounds:
    x0: float
    y0: float
    x1: float
    y1: float

    def contains(self, x: float, y: float, margin: float) -> bool:
        return (
            self.x0 + margin <= x <= self.x1 - margin
            and self.y0 + margin <= y <= self.y1 - margin
        )


@dataclass(frozen=True, slots=True)
class Track:
    x0: float
    y0: float
    x1: float
    y1: float


class RoutingError(RuntimeError):
    """Nie udało się poprowadzić ścieżki w zadanym budżecie."""


_EPS = 1e-9


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def _point_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq < _EPS:
        return math.hypot(px - ax, py - ay)
    t = _clamp(((px - ax) * dx + (py - ay) * dy) / length_sq, 0.0, 1.0)
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _segments_intersect(
    ax: float, ay: float, bx: float, by: float,
    cx: float, cy: float, dx: float, dy: float,
) -> bool:
    def cross(ox: float, oy: float, px: float, py: float, qx: float, qy: float) -> float:
        return (px - ox) * (qy - oy) - (py - oy) * (qx - ox)

    d1 = cross(cx, cy, dx, dy, ax, ay)
    d2 = cross(cx, cy, dx, dy, bx, by)
    d3 = cross(ax, ay, bx, by, cx, cy)
    d4 = cross(ax, ay, bx, by, dx, dy)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _segment_distance(
    ax: float, ay: float, bx: float, by: float,
    cx: float, cy: float, dx: float, dy: float,
) -> float:
    if _segments_intersect(ax, ay, bx, by, cx, cy, dx, dy):
        return 0.0
    return min(
        _point_segment_distance(ax, ay, cx, cy, dx, dy),
        _point_segment_distance(bx, by, cx, cy, dx, dy),
        _point_segment_distance(cx, cy, ax, ay, bx, by),
        _point_segment_distance(dx, dy, ax, ay, bx, by),
    )


def _segment_box_distance(
    ax: float, ay: float, bx: float, by: float, box: Box
) -> float:
    inside_a = box.x0 <= ax <= box.x1 and box.y0 <= ay <= box.y1
    inside_b = box.x0 <= bx <= box.x1 and box.y0 <= by <= box.y1
    if inside_a or inside_b:
        return 0.0
    corners = (
        (box.x0, box.y0), (box.x1, box.y0), (box.x1, box.y1), (box.x0, box.y1)
    )
    return min(
        _segment_distance(ax, ay, bx, by, corners[i][0], corners[i][1],
                          corners[(i + 1) % 4][0], corners[(i + 1) % 4][1])
        for i in range(4)
    )


def track_is_clear(
    track: Track,
    net: int,
    obstacles: Iterable[Obstacle],
    half_width: float,
    clearance: float,
) -> bool:
    """Czy odcinek zachowuje `clearance` od każdej miedzi o innym necie."""
    for obstacle in obstacles:
        if obstacle.net == net:
            continue
        if isinstance(obstacle, Capsule):
            gap = _segment_distance(
                track.x0, track.y0, track.x1, track.y1,
                obstacle.ax, obstacle.ay, obstacle.bx, obstacle.by,
            ) - half_width - obstacle.radius
        else:
            gap = _segment_box_distance(
                track.x0, track.y0, track.x1, track.y1, obstacle
            ) - half_width
        if gap < clearance:
            return False
    return True


def _obstacle_edges(obstacles: Iterable[Obstacle]) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for obstacle in obstacles:
        if isinstance(obstacle, Capsule):
            xs += [min(obstacle.ax, obstacle.bx) - obstacle.radius,
                   max(obstacle.ax, obstacle.bx) + obstacle.radius]
            ys += [min(obstacle.ay, obstacle.by) - obstacle.radius,
                   max(obstacle.ay, obstacle.by) + obstacle.radius]
        else:
            xs += [obstacle.x0, obstacle.x1]
            ys += [obstacle.y0, obstacle.y1]
    return xs, ys


def _candidates(
    edges: list[float],
    anchors: tuple[float, float],
    low: float,
    high: float,
    offset: float,
    limit: int,
) -> list[float]:
    """Siatka Hanana: krawędzie przeszkód odsunięte o wymaganą izolację."""
    values = {round(_clamp(value, low, high), 4) for value in anchors}
    for edge in edges:
        for candidate in (edge - offset, edge + offset):
            if low <= candidate <= high:
                values.add(round(candidate, 4))
    first, second = anchors
    cost = lambda value: abs(value - first) + abs(second - value)  # noqa: E731
    return sorted(values, key=cost)[:limit]


def route_edge(
    start: tuple[float, float],
    end: tuple[float, float],
    net: int,
    obstacles: list[Obstacle],
    bounds: Bounds,
    width: float,
    clearance: float,
    budget: int = 40_000,
) -> list[Track]:
    """Trasuje jedno połączenie schodkiem pion-poziom-pion-poziom.

    Rodzina tras ma dwa stopnie swobody (Y pierwszej poziomej i X drugiej
    pionowej), więc obejmuje też trasy proste i typu L. Kandydaci są
    przeglądani rosnąco względem długości Manhattan, czyli najkrótsza
    poprawna trasa wygrywa.
    """
    px, py = start
    qx, qy = end
    half_width = width / 2.0
    offset = half_width + clearance
    margin = half_width
    xs, ys = _obstacle_edges(obstacles)
    x_values = _candidates(xs, (px, qx), bounds.x0 + margin, bounds.x1 - margin, offset, 260)
    y_values = _candidates(ys, (py, qy), bounds.y0 + margin, bounds.y1 - margin, offset, 260)

    def legs(x: float, y: float) -> list[Track]:
        raw = [
            Track(px, py, px, y),
            Track(px, y, x, y),
            Track(x, y, x, qy),
            Track(x, qy, qx, qy),
        ]
        return [
            leg for leg in raw
            if abs(leg.x0 - leg.x1) > _EPS or abs(leg.y0 - leg.y1) > _EPS
        ]

    pairs = sorted(
        ((abs(y - py) + abs(qy - y) + abs(x - px) + abs(qx - x), y, x)
         for y in y_values for x in x_values),
        key=lambda item: item[0],
    )
    for index, (_cost, y, x) in enumerate(pairs):
        if index >= budget:
            break
        path = legs(x, y)
        if all(track_is_clear(leg, net, obstacles, half_width, clearance) for leg in path):
            return path
    raise RoutingError(
        f"no clear rectilinear path from {start} to {end} on net {net}"
    )


def route_net(
    terminals: list[tuple[float, float]],
    net: int,
    obstacles: list[Obstacle],
    bounds: Bounds,
    width: float,
    clearance: float,
) -> list[Track]:
    """Łączy wszystkie pady netu drzewem rozpinającym (Prim, metryka Manhattan)."""
    if len(terminals) < 2:
        return []
    connected = [terminals[0]]
    pending = list(terminals[1:])
    tracks: list[Track] = []
    while pending:
        best = min(
            ((abs(a[0] - b[0]) + abs(a[1] - b[1]), i, j)
             for i, a in enumerate(connected) for j, b in enumerate(pending)),
            key=lambda item: (item[0], item[1], item[2]),
        )
        _distance, source_index, target_index = best
        target = pending.pop(target_index)
        tracks += route_edge(
            connected[source_index], target, net, obstacles, bounds, width, clearance
        )
        connected.append(target)
    return tracks
