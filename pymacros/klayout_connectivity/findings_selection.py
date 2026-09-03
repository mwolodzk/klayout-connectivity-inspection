"""Testable dispatch of a browser finding selection to a layout UI."""

from __future__ import annotations

from typing import Callable, Tuple

from klayout_connectivity.findings import BoundingBox, FindingSelection, FindingTarget


class FindingsSelectionAdapter:
    """Apply a selection in a fixed, observable order.

    Callers provide KLayout-specific functions.  Supplying stubs gives tests
    the same contract without importing ``pya``.
    """

    def __init__(
        self,
        zoom_to_bbox: Callable[[BoundingBox], None],
        highlight_targets: Callable[[Tuple[FindingTarget, ...]], None],
        cross_probe_targets: Callable[[Tuple[FindingTarget, ...]], None],
    ) -> None:
        self._zoom_to_bbox = zoom_to_bbox
        self._highlight_targets = highlight_targets
        self._cross_probe_targets = cross_probe_targets

    def apply(self, selection: FindingSelection) -> None:
        if selection.zoom_bbox is not None:
            self._zoom_to_bbox(selection.zoom_bbox)
        self._highlight_targets(selection.highlight_targets)
        self._cross_probe_targets(selection.cross_probe_targets)
