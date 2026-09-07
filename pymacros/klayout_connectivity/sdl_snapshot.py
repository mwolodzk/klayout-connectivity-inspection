"""Read the public SDL sidecar without importing the SDL importer package."""

from __future__ import annotations

import json
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from klayout_connectivity.findings import (
    BoundingBox,
    Finding,
    FindingStatus,
    FindingTarget,
)
from klayout_connectivity.flight_overlay import SnapshotFlightLine


class SnapshotFormatError(ValueError):
    """The sidecar is present but cannot safely be displayed as findings."""


@dataclass(frozen=True)
class SnapshotState:
    kind: str
    message: str


@dataclass(frozen=True)
class SnapshotPinAccess:
    pin_id: str
    bbox: Tuple[float, float, float, float]
    point: Tuple[float, float]
    layer: str


def snapshot_state_for_layout(layout_path: str) -> SnapshotState:
    """Explain whether Findings/flight-lines are ready for this layout."""
    sidecar_path = sidecar_path_for_layout(layout_path)
    if not sidecar_path.is_file():
        return SnapshotState(
            "missing",
            "No SDL sidecar was found. Import the SG13G2 source netlist first, "
            "then run SDL Analysis.",
        )
    try:
        document = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SnapshotFormatError("Invalid SDL JSON in {}: {}".format(sidecar_path, error))
    if not isinstance(document, Mapping):
        raise SnapshotFormatError("SDL sidecar root must be an object")
    raw_warnings = document.get("source_warnings", [])
    if not isinstance(raw_warnings, list) or any(
        not isinstance(message, str) for message in raw_warnings
    ):
        raise SnapshotFormatError("SDL sidecar 'source_warnings' must be a list of strings")
    raw_analysis_warnings = document.get("analysis_warnings", [])
    if not isinstance(raw_analysis_warnings, list) or any(
        not isinstance(message, str) for message in raw_analysis_warnings
    ):
        raise SnapshotFormatError(
            "SDL sidecar 'analysis_warnings' must be a list of strings"
        )
    warning_suffix = ""
    if raw_warnings:
        warning_suffix = " SDL source warning: " + " | ".join(raw_warnings)
    if raw_analysis_warnings:
        warning_suffix += (
            " SDL analysis warning: " + " | ".join(raw_analysis_warnings)
        )
    snapshot = document.get("snapshot", document)
    if snapshot is None:
        return SnapshotState(
            "not_analyzed",
            "Expected connectivity is loaded, but the SDL snapshot is empty. "
            "The official PDK LVS/NET_ONLY extraction alone does not populate "
            "Findings. Save the layout and click Run SDL Analysis below "
            "to start the SDL adapter and comparison." + warning_suffix,
        )
    if not isinstance(snapshot, Mapping):
        raise SnapshotFormatError("SDL sidecar 'snapshot' must be an object or null")
    source_path = document.get("source_path")
    digest_mismatch = (
        document.get("layout_digest") != _file_digest(Path(layout_path))
        or not isinstance(source_path, str)
        or document.get("source_digest") != _file_digest(Path(source_path))
    )
    if bool(snapshot.get("stale", False)) or digest_mismatch:
        return SnapshotState(
            "stale",
            "The SDL result is stale because the layout or source netlist changed. "
            "Save the layout and run SDL Analysis again before using flight-lines.",
        )
    return SnapshotState("ready", "SDL analysis result loaded." + warning_suffix)


def _file_digest(path: Path) -> Optional[str]:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def sidecar_path_for_layout(layout_path: str) -> Path:
    """Return the SDL v1 sidecar path: ``<layout>.sdl.json``."""
    return Path(str(layout_path) + ".sdl.json")


def load_findings_for_layout(layout_path: str) -> Tuple[Finding, ...]:
    return load_findings_sidecar(sidecar_path_for_layout(layout_path))


def load_flight_lines_for_layout(layout_path: str) -> Tuple[SnapshotFlightLine, ...]:
    return load_flight_lines_sidecar(sidecar_path_for_layout(layout_path))


def load_pin_access_for_layout(layout_path: str) -> Tuple[SnapshotPinAccess, ...]:
    """Load deduplicated physical pin access points from a ready snapshot."""
    snapshot = _read_snapshot(sidecar_path_for_layout(layout_path))
    if snapshot is None or bool(snapshot.get("stale", False)):
        return ()
    observed = snapshot.get("observed", {})
    if not isinstance(observed, Mapping):
        raise SnapshotFormatError("SDL sidecar 'observed' must be an object")
    result: Dict[str, SnapshotPinAccess] = {}
    for component in observed.values():
        if not isinstance(component, Mapping):
            raise SnapshotFormatError("SDL observed component must be an object")
        access_points = component.get("access_points", ())
        if not isinstance(access_points, list):
            raise SnapshotFormatError("SDL component 'access_points' must be a list")
        for raw in access_points:
            if not isinstance(raw, Mapping):
                raise SnapshotFormatError("SDL pin access point must be an object")
            pin_id = raw.get("pin_id")
            layer = raw.get("layer", "")
            if not isinstance(pin_id, str) or not pin_id:
                raise SnapshotFormatError("SDL pin access point requires non-empty 'pin_id'")
            bbox = _bbox_tuple(raw.get("bbox"), "pin access bbox")
            point = _point_tuple(raw.get("point"), "pin access point")
            result.setdefault(pin_id, SnapshotPinAccess(pin_id, bbox, point, str(layer)))
    return tuple(result[key] for key in sorted(result))


def _point_tuple(value: Any, label: str) -> Tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise SnapshotFormatError("{} must be [x, y]".format(label))
    if not all(isinstance(coordinate, (int, float)) for coordinate in value):
        raise SnapshotFormatError("{} coordinates must be numbers".format(label))
    return float(value[0]), float(value[1])


def _bbox_tuple(value: Any, label: str) -> Tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise SnapshotFormatError("{} must be [left, bottom, right, top]".format(label))
    if not all(isinstance(coordinate, (int, float)) for coordinate in value):
        raise SnapshotFormatError("{} coordinates must be numbers".format(label))
    return tuple(float(coordinate) for coordinate in value)


def load_findings_sidecar(sidecar_path: Path) -> Tuple[Finding, ...]:
    """Load a JSON sidecar emitted by SDL v1 into browser-owned findings.

    Only the documented JSON structure is consumed; this adapter intentionally
    does not import ``klayout_netlist_importer`` so the inspection plugin can
    be installed on its own.
    """
    snapshot = _read_snapshot(sidecar_path)
    if snapshot is None:
        return ()
    raw_findings = snapshot.get("findings", ())
    if not isinstance(raw_findings, list):
        raise SnapshotFormatError("SDL sidecar 'findings' must be a list")
    return tuple(_finding_from_raw(raw, index) for index, raw in enumerate(raw_findings))


def load_flight_lines_sidecar(sidecar_path: Path) -> Tuple[SnapshotFlightLine, ...]:
    """Load only lines backed by an actual OPEN finding in the same snapshot.

    The producer normally emits lines for OPEN findings, but the sidecar is a
    public interchange format.  Requiring the matching finding here prevents
    stale/adversarial SHORT or WRONG_NET records from becoming visual hints.
    """
    snapshot = _read_snapshot(sidecar_path)
    if snapshot is None:
        return ()
    # A stale extraction can still be reviewed in Findings, but its geometry
    # must not guide routing after either the layout or source has changed.
    if bool(snapshot.get("stale", False)):
        return ()
    raw_findings = snapshot.get("findings", ())
    if not isinstance(raw_findings, list):
        raise SnapshotFormatError("SDL sidecar 'findings' must be a list")
    raw_lines = snapshot.get("flight_lines", ())
    if not isinstance(raw_lines, list):
        raise SnapshotFormatError("SDL sidecar 'flight_lines' must be a list")

    open_findings = []
    blocked_components = set()
    blocked_pins = set()
    for index, raw in enumerate(raw_findings):
        if not isinstance(raw, Mapping):
            raise SnapshotFormatError("Finding #{} must be an object".format(index))
        kind = raw.get("kind")
        components = _string_list(raw.get("component_ids", ()), "component_ids", index)
        if kind in ("SHORT", "WRONG_NET"):
            blocked_components.update(components)
            blocked_pins.update(_string_list(raw.get("pin_ids", ()), "pin_ids", index))
        if kind == "OPEN":
            open_findings.append(raw)

    result = []
    for index, raw in enumerate(raw_lines):
        result.append(_flight_line_from_raw(raw, index))
    accepted = []
    for line in result:
        if (
            line.component_a in blocked_components
            or line.component_b in blocked_components
            or line.pin_a in blocked_pins
            or line.pin_b in blocked_pins
        ):
            continue
        if any(_line_belongs_to_open(line, finding) for finding in open_findings):
            accepted.append(line)
    return tuple(sorted(accepted, key=lambda line: line.line_id))


def _read_snapshot(sidecar_path: Path) -> Optional[Mapping[str, Any]]:
    try:
        with sidecar_path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except json.JSONDecodeError as error:
        raise SnapshotFormatError("Invalid SDL JSON in {}: {}".format(sidecar_path, error))
    if not isinstance(document, Mapping):
        raise SnapshotFormatError("SDL sidecar root must be an object")
    # NetlistImportPlugin stores checker output under the public sidecar's
    # ``snapshot`` member.  Accept a bare snapshot for adapter/debug fixtures.
    snapshot = document.get("snapshot", document)
    if snapshot is None:
        return None
    if not isinstance(snapshot, Mapping):
        raise SnapshotFormatError("SDL sidecar 'snapshot' must be an object or null")
    return snapshot


def _flight_line_from_raw(raw: Any, index: int) -> SnapshotFlightLine:
    if not isinstance(raw, Mapping):
        raise SnapshotFormatError("Flight line #{} must be an object".format(index))
    values = {}
    for key in ("line_id", "expected_net", "component_a", "component_b", "pin_a", "pin_b"):
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise SnapshotFormatError("Flight line #{} requires non-empty '{}'".format(index, key))
        values[key] = value
    start = _point_from_raw(raw.get("start"), "start", index)
    end = _point_from_raw(raw.get("end"), "end", index)
    return SnapshotFlightLine(start=start, end=end, **values)


def _point_from_raw(value: Any, key: str, index: int) -> Tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise SnapshotFormatError("Flight line #{} {} must be [x, y]".format(index, key))
    if not all(isinstance(coordinate, (int, float)) for coordinate in value):
        raise SnapshotFormatError("Flight line #{} {} coordinates must be numbers".format(index, key))
    return float(value[0]), float(value[1])


def _line_belongs_to_open(line: SnapshotFlightLine, finding: Mapping[str, Any]) -> bool:
    if finding.get("expected_net") != line.expected_net:
        return False
    components = set(finding.get("component_ids", ()))
    if not {line.component_a, line.component_b} <= components:
        return False
    pins = set(finding.get("pin_ids", ()))
    return not pins or {line.pin_a, line.pin_b} <= pins


def _finding_from_raw(raw: Any, index: int) -> Finding:
    if not isinstance(raw, Mapping):
        raise SnapshotFormatError("Finding #{} must be an object".format(index))
    identifier = _required_string(raw, "finding_id", index)
    kind = _required_string(raw, "kind", index)
    message = _required_string(raw, "message", index)
    try:
        status = FindingStatus(raw.get("status", FindingStatus.ACTIVE.value))
    except ValueError:
        raise SnapshotFormatError("Finding #{} has invalid status".format(index))

    bbox = _bbox_from_raw(raw.get("bbox"), index)
    pins = _string_list(raw.get("pin_ids", ()), "pin_ids", index)
    components = _string_list(raw.get("component_ids", ()), "component_ids", index)
    instances = _string_list(raw.get("instance_ids", ()), "instance_ids", index)
    expected_net = raw.get("expected_net")
    observed_nets = _string_list(raw.get("observed_nets", ()), "observed_nets", index)

    highlight_targets = tuple(
        [FindingTarget("component", component) for component in components]
        + [FindingTarget("pin", pin) for pin in pins]
        + [FindingTarget("instance", instance) for instance in instances]
    )
    cross_probe_targets = tuple(
        [FindingTarget("instance", instance) for instance in instances]
        + [FindingTarget("pin", pin) for pin in pins]
        + ([FindingTarget("net", expected_net)] if isinstance(expected_net, str) and expected_net else [])
        + [FindingTarget("net", net) for net in observed_nets]
    )
    return Finding(
        identifier=identifier,
        kind=kind,
        title=kind.replace("_", " ").title(),
        message=message,
        status=status,
        bbox=bbox,
        highlight_targets=highlight_targets,
        cross_probe_targets=cross_probe_targets,
    )


def _required_string(raw: Mapping[str, Any], key: str, index: int) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise SnapshotFormatError("Finding #{} requires non-empty '{}'".format(index, key))
    return value


def _string_list(value: Any, key: str, index: int) -> List[str]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) and item for item in value):
        raise SnapshotFormatError("Finding #{} '{}' must be a list of non-empty strings".format(index, key))
    return list(value)


def _bbox_from_raw(value: Any, index: int) -> Optional[BoundingBox]:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise SnapshotFormatError("Finding #{} bbox must be [left, bottom, right, top]".format(index))
    if not all(isinstance(coordinate, (int, float)) for coordinate in value):
        raise SnapshotFormatError("Finding #{} bbox coordinates must be numbers".format(index))
    try:
        return BoundingBox(*value)
    except ValueError as error:
        raise SnapshotFormatError("Finding #{} has invalid bbox: {}".format(index, error))
