"""Pure helpers for selection-driven marker emphasis."""

from __future__ import annotations

from typing import Iterable, Tuple

from klayout_connectivity.findings import FindingTarget
from klayout_connectivity.flight_overlay import SnapshotFlightLine


def dim_color(color: int, factor: float = 0.35) -> int:
    """Return an RGB color with each channel reduced by ``factor``."""
    if not 0.0 <= factor <= 1.0:
        raise ValueError("factor must be between 0 and 1")
    red = int(((color >> 16) & 0xff) * factor)
    green = int(((color >> 8) & 0xff) * factor)
    blue = int((color & 0xff) * factor)
    return (red << 16) | (green << 8) | blue


def emphasized_flight_line_ids(
    lines: Iterable[SnapshotFlightLine], targets: Iterable[FindingTarget]
) -> Tuple[str, ...]:
    """Select lines related to the selected finding's most precise targets.

    Net targets take precedence.  An OPEN finding also carries its endpoint
    pins, and deriving instances from those pins would otherwise emphasize
    unrelated nets connected to the same transistor.
    """
    values = tuple(targets)
    nets = {target.identifier for target in values if target.target_type == "net"}
    components = {
        target.identifier for target in values if target.target_type == "component"
    }
    pins = {_normalized(target.identifier) for target in values if target.target_type == "pin"}
    instances = {
        _normalized(target.identifier)
        for target in values
        if target.target_type == "instance"
    }
    selected = []
    for line in lines:
        line_pins = (_normalized(line.pin_a), _normalized(line.pin_b))
        if nets:
            matches = line.expected_net in nets
        elif components:
            matches = bool({line.component_a, line.component_b} & components)
        elif pins:
            matches = bool(set(line_pins) & pins)
        else:
            matches = any(
                pin.startswith(instance + "/")
                for pin in line_pins
                for instance in instances
            )
        if matches:
            selected.append(line.line_id)
    return tuple(selected)


def _normalized(identifier: str) -> str:
    return str(identifier).strip().strip("/").replace(".", "/")


__all__ = ["dim_color", "emphasized_flight_line_ids"]
