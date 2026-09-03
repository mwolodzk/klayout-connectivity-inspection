# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2026 Martin Jan Köhler
# SPDX-License-Identifier: GPL-3.0-or-later
# --------------------------------------------------------------------------------
"""Pure-Python state model for connectivity-inspection findings.

The model deliberately has no KLayout or Qt dependency.  The UI can render
``visible_findings`` and hand a :class:`FindingSelection` to a KLayout adapter:
``zoom_bbox`` is the rectangle to zoom to, while the two target lists identify
objects to highlight and cross-probe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet, Iterable, List, Optional, Sequence, Tuple


class FindingStatus(str, Enum):
    """Review state; it is intentionally independent of severity/kind."""

    ACTIVE = "active"
    VISITED = "visited"
    WAIVED = "waived"


class FindingKind(str, Enum):
    """All SDL v1 finding kinds emitted by the connectivity engine."""

    OPEN = "OPEN"
    SHORT = "SHORT"
    WRONG_NET = "WRONG_NET"
    UNBOUND = "UNBOUND"
    MISSING = "MISSING"
    MASTER_MISMATCH = "MASTER_MISMATCH"
    PARAMETER_MISMATCH = "PARAMETER_MISMATCH"


# Kept as a readable plural for callers that only need constants.  ``kind`` in
# Finding remains open to permit a future engine to add a kind without making
# old browsers unable to show or filter the result.
FindingKinds = FindingKind


@dataclass(frozen=True)
class BoundingBox:
    """Layout-independent axis-aligned rectangle, in the caller's units."""

    left: float
    bottom: float
    right: float
    top: float

    def __post_init__(self) -> None:
        if self.left > self.right or self.bottom > self.top:
            raise ValueError("BoundingBox must have left <= right and bottom <= top")

    def union(self, other: "BoundingBox") -> "BoundingBox":
        return BoundingBox(
            left=min(self.left, other.left),
            bottom=min(self.bottom, other.bottom),
            right=max(self.right, other.right),
            top=max(self.top, other.top),
        )


@dataclass(frozen=True)
class FindingTarget:
    """Stable, renderer-independent reference to an inspectable object."""

    target_type: str
    identifier: str

    def __post_init__(self) -> None:
        if not self.target_type or not self.identifier:
            raise ValueError("FindingTarget requires target_type and identifier")


@dataclass(frozen=True)
class Finding:
    """One result emitted by any connectivity rule or import diagnostic.

    ``kind`` is an open string rather than a closed enum: new rule classes can
    be displayed and filtered before the browser itself learns their semantics.
    """

    identifier: str
    kind: str
    title: str
    message: str = ""
    status: FindingStatus = FindingStatus.ACTIVE
    bbox: Optional[BoundingBox] = None
    highlight_targets: Tuple[FindingTarget, ...] = field(default_factory=tuple)
    cross_probe_targets: Tuple[FindingTarget, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.identifier or not self.kind or not self.title:
            raise ValueError("Finding requires identifier, kind, and title")
        # Accept lists from rule adapters while keeping values immutable and
        # hash/equality friendly for UI state and tests.
        object.__setattr__(self, "highlight_targets", tuple(self.highlight_targets))
        object.__setattr__(self, "cross_probe_targets", tuple(self.cross_probe_targets))


@dataclass(frozen=True)
class FindingsFilter:
    """Conjunctive filter. Empty status/kind sets mean 'all'."""

    statuses: FrozenSet[FindingStatus] = field(default_factory=frozenset)
    kinds: FrozenSet[str] = field(default_factory=frozenset)
    text: str = ""

    def matches(self, finding: Finding) -> bool:
        if self.statuses and finding.status not in self.statuses:
            return False
        if self.kinds and finding.kind not in self.kinds:
            return False
        if self.text:
            haystack = " ".join(
                (finding.identifier, finding.kind, finding.title, finding.message)
            ).casefold()
            if self.text.casefold() not in haystack:
                return False
        return True


@dataclass(frozen=True)
class FindingSelection:
    """Presentation-neutral result of one or more selected findings."""

    findings: Tuple[Finding, ...]
    zoom_bbox: Optional[BoundingBox]
    highlight_targets: Tuple[FindingTarget, ...]
    cross_probe_targets: Tuple[FindingTarget, ...]


class FindingsModel:
    """Filterable, multi-selectable model used by a findings browser.

    Selection is retained while a filter temporarily hides a finding.  This is
    useful when an engineer narrows a large result set without losing a review
    comparison; :meth:`selection` always represents the actual selected set.
    """

    def __init__(self, findings: Iterable[Finding] = ()) -> None:
        self._findings: Tuple[Finding, ...] = ()
        self._by_identifier = {}
        self._selected_identifiers: FrozenSet[str] = frozenset()
        self.filter = FindingsFilter()
        self.replace_findings(findings)

    @property
    def findings(self) -> Tuple[Finding, ...]:
        return self._findings

    @property
    def visible_findings(self) -> Tuple[Finding, ...]:
        return tuple(f for f in self._findings if self.filter.matches(f))

    @property
    def selected_identifiers(self) -> FrozenSet[str]:
        return self._selected_identifiers

    @property
    def selected_findings(self) -> Tuple[Finding, ...]:
        # Preserve the rule engine's result ordering, not set ordering.
        return tuple(f for f in self._findings if f.identifier in self._selected_identifiers)

    def replace_findings(self, findings: Iterable[Finding]) -> None:
        values = tuple(findings)
        identifiers = [finding.identifier for finding in values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Finding identifiers must be unique")
        self._findings = values
        self._by_identifier = {finding.identifier: finding for finding in values}
        self._selected_identifiers = frozenset(
            identifier for identifier in self._selected_identifiers
            if identifier in self._by_identifier
        )

    def set_filter(self, findings_filter: FindingsFilter) -> None:
        self.filter = findings_filter

    def set_selection(self, identifiers: Iterable[str]) -> FindingSelection:
        selected = frozenset(identifiers)
        unknown = selected.difference(self._by_identifier)
        if unknown:
            raise KeyError("Unknown finding identifier(s): {}".format(", ".join(sorted(unknown))))
        self._selected_identifiers = selected
        return self.selection()

    def toggle_selection(self, identifier: str) -> FindingSelection:
        if identifier not in self._by_identifier:
            raise KeyError("Unknown finding identifier: {}".format(identifier))
        selected = set(self._selected_identifiers)
        if identifier in selected:
            selected.remove(identifier)
        else:
            selected.add(identifier)
        return self.set_selection(selected)

    def set_status(self, identifiers: Iterable[str], status: FindingStatus) -> None:
        requested = frozenset(identifiers)
        unknown = requested.difference(self._by_identifier)
        if unknown:
            raise KeyError("Unknown finding identifier(s): {}".format(", ".join(sorted(unknown))))
        self.replace_findings(
            Finding(
                identifier=finding.identifier,
                kind=finding.kind,
                title=finding.title,
                message=finding.message,
                status=status if finding.identifier in requested else finding.status,
                bbox=finding.bbox,
                highlight_targets=finding.highlight_targets,
                cross_probe_targets=finding.cross_probe_targets,
            )
            for finding in self._findings
        )

    def mark_visited(self, identifiers: Iterable[str]) -> None:
        self.set_status(identifiers, FindingStatus.VISITED)

    def waive(self, identifiers: Iterable[str]) -> None:
        self.set_status(identifiers, FindingStatus.WAIVED)

    def reactivate(self, identifiers: Iterable[str]) -> None:
        self.set_status(identifiers, FindingStatus.ACTIVE)

    def selection(self) -> FindingSelection:
        selected = self.selected_findings
        bbox: Optional[BoundingBox] = None
        highlight_targets: List[FindingTarget] = []
        cross_probe_targets: List[FindingTarget] = []
        seen_highlights = set()
        seen_cross_probes = set()

        for finding in selected:
            if finding.bbox is not None:
                bbox = finding.bbox if bbox is None else bbox.union(finding.bbox)
            _append_unique(highlight_targets, seen_highlights, finding.highlight_targets)
            _append_unique(cross_probe_targets, seen_cross_probes, finding.cross_probe_targets)

        return FindingSelection(
            findings=selected,
            zoom_bbox=bbox,
            highlight_targets=tuple(highlight_targets),
            cross_probe_targets=tuple(cross_probe_targets),
        )


def _append_unique(destination: List[FindingTarget], seen: set, targets: Sequence[FindingTarget]) -> None:
    for target in targets:
        if target not in seen:
            destination.append(target)
            seen.add(target)
