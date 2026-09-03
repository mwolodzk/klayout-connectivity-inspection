"""Pure selection and rendering seam for SDL snapshot flight-lines."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable, Sequence, Tuple


Point = Tuple[float, float]


class VisibilityMode(str, Enum):
    OFF = "Off"
    SELECTED_NETS = "Selected Nets"
    SELECTED_PINS = "Selected Pins"
    SELECTED_INSTANCES = "Selected Instances"
    ALL_OPENS = "All Opens"


@dataclass(frozen=True)
class SnapshotFlightLine:
    """The public ``snapshot.flight_lines`` record consumed by the plugin."""

    line_id: str
    expected_net: str
    component_a: str
    component_b: str
    pin_a: str
    pin_b: str
    start: Point
    end: Point


def _normalized_identifier(identifier: str) -> str:
    return str(identifier).strip().strip("/").replace(".", "/")


def visible_flight_lines(
    lines: Iterable[SnapshotFlightLine],
    mode: VisibilityMode,
    selected: Iterable[str] = (),
) -> Tuple[SnapshotFlightLine, ...]:
    """Filter existing, open-only lines for one UI visibility mode."""

    values = tuple(lines)
    if mode == VisibilityMode.OFF:
        return ()
    if mode == VisibilityMode.ALL_OPENS:
        return values

    selected_values = {str(value) for value in selected}
    if mode == VisibilityMode.SELECTED_NETS:
        return tuple(line for line in values if line.expected_net in selected_values)
    selected_set = {_normalized_identifier(value) for value in selected_values}
    if mode == VisibilityMode.SELECTED_PINS:
        return tuple(
            line for line in values
            if {_normalized_identifier(line.pin_a), _normalized_identifier(line.pin_b)}
            & selected_set
        )
    if mode == VisibilityMode.SELECTED_INSTANCES:
        return tuple(
            line for line in values
            if any(
                _normalized_identifier(pin).startswith(instance + "/")
                for instance in selected_set
                for pin in (line.pin_a, line.pin_b)
            )
        )
    return ()


class FlightLineMarkerSeam:
    """KLayout-facing lifecycle seam, testable with two ordinary callbacks.

    ``create`` receives two coordinate tuples and returns an opaque marker;
    ``destroy`` receives markers created by the previous render.  Replacing a
    snapshot therefore always removes old lines, including when the new
    snapshot has no lines after a fixed open is refreshed.
    """

    def __init__(
        self,
        create: Callable[[Point, Point], object],
        destroy: Callable[[object], None],
    ) -> None:
        self._create = create
        self._destroy = destroy
        self._markers = []

    @property
    def markers(self) -> Tuple[object, ...]:
        return tuple(self._markers)

    def render(self, lines: Sequence[SnapshotFlightLine]) -> Tuple[object, ...]:
        for marker in self._markers:
            self._destroy(marker)
        self._markers = [self._create(line.start, line.end) for line in lines]
        return self.markers


__all__ = [
    "FlightLineMarkerSeam",
    "Point",
    "SnapshotFlightLine",
    "VisibilityMode",
    "visible_flight_lines",
]
