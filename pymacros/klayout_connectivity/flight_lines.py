"""Pure-Python flight-line planning.

The KLayout plugin owns rendering (``pya.Marker``) and connectivity
extraction.  This module only turns already validated pin access points into
line segments, which keeps the geometry policy testable without KLayout.

An access point is eligible only when both its expected and observed net are
the requested net and it is not marked as a short.  Eligible points are
grouped by ``component_id``.  For each pair of components the closest pair of
access points is retained, then Kruskal's algorithm selects a deterministic
minimum spanning tree.  Consequently, ``k`` eligible components produce
exactly ``k - 1`` lines (or no lines for zero/one component).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Iterable, Optional, Tuple


@dataclass(frozen=True)
class PinAccessPoint:
    """A candidate endpoint supplied by the connectivity adapter.

    ``actual_net`` is intentionally explicit.  A missing observation is not
    considered safe to draw: callers should pass only points whose net was
    validated by the connectivity importer.  ``is_short`` identifies an
    access point involved in a short and excludes it from flight lines.
    """

    component_id: str
    pin_id: str
    x: float
    y: float
    expected_net: str
    actual_net: Optional[str]
    is_short: bool = False


@dataclass(frozen=True)
class FlightLine:
    """One selected MST edge, including its selected access-point endpoints."""

    component_a: str
    component_b: str
    point_a: PinAccessPoint
    point_b: PinAccessPoint
    distance: float


def _point_key(point: PinAccessPoint) -> Tuple[str, str, float, float]:
    """Stable key used to resolve equal-distance access points."""

    return (point.component_id, point.pin_id, point.x, point.y)


def _nearest_pair(
    left: Tuple[PinAccessPoint, ...], right: Tuple[PinAccessPoint, ...]
) -> Tuple[PinAccessPoint, PinAccessPoint, float]:
    """Return the closest pair, resolving geometric ties deterministically."""

    candidates = []
    for point_a in left:
        for point_b in right:
            distance = hypot(point_a.x - point_b.x, point_a.y - point_b.y)
            candidates.append(
                (distance, _point_key(point_a), _point_key(point_b), point_a, point_b)
            )
    # Use an explicit key so duplicate coordinates/IDs cannot make Python
    # compare the non-orderable PinAccessPoint objects themselves.
    distance, _key_a, _key_b, point_a, point_b = min(
        candidates, key=lambda candidate: candidate[:3]
    )
    return point_a, point_b, distance


def build_flight_lines(
    access_points: Iterable[PinAccessPoint], expected_net: str
) -> Tuple[FlightLine, ...]:
    """Build a deterministic nearest-access-point MST for one expected net.

    The input may contain points for multiple nets, shorts, and multiple
    points in one physical component.  Such points are filtered before the
    graph is built.  One candidate edge is made for every component pair,
    using that pair's nearest access points; Kruskal then chooses the MST.

    The returned tuple is sorted by the same total-order key used by
    Kruskal, so output is independent of input iteration order.
    """

    components = {}
    for point in access_points:
        if (
            point.expected_net != expected_net
            or point.actual_net != expected_net
            or point.is_short
        ):
            continue
        components.setdefault(point.component_id, []).append(point)

    grouped = {
        component_id: tuple(sorted(points, key=_point_key))
        for component_id, points in components.items()
    }
    component_ids = sorted(grouped)
    if len(component_ids) < 2:
        return ()

    # Every pair gets its closest endpoint pair.  Candidate ordering is
    # explicit, including endpoint IDs, to make equal-length MSTs stable.
    candidates = []
    for index, component_a in enumerate(component_ids):
        for component_b in component_ids[index + 1 :]:
            point_a, point_b, distance = _nearest_pair(
                grouped[component_a], grouped[component_b]
            )
            candidates.append(
                (
                    distance,
                    component_a,
                    component_b,
                    _point_key(point_a),
                    _point_key(point_b),
                    point_a,
                    point_b,
                )
            )
    candidates.sort(key=lambda candidate: candidate[:5])

    parent = {component_id: component_id for component_id in component_ids}

    def find(component_id: str) -> str:
        root = component_id
        while parent[root] != root:
            root = parent[root]
        while parent[component_id] != component_id:
            next_id = parent[component_id]
            parent[component_id] = root
            component_id = next_id
        return root

    selected = []
    for distance, component_a, component_b, _key_a, _key_b, point_a, point_b in candidates:
        root_a = find(component_a)
        root_b = find(component_b)
        if root_a == root_b:
            continue
        # Component IDs are already sorted; attaching root B to root A keeps
        # the union-find state deterministic as well.
        parent[root_b] = root_a
        selected.append(
            FlightLine(
                component_a=component_a,
                component_b=component_b,
                point_a=point_a,
                point_b=point_b,
                distance=distance,
            )
        )
        if len(selected) == len(component_ids) - 1:
            break

    return tuple(selected)


__all__ = ["FlightLine", "PinAccessPoint", "build_flight_lines"]
