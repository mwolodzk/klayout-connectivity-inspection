import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pymacros"))

from klayout_connectivity.findings import BoundingBox, Finding, FindingTarget, FindingsModel  # noqa: E402
from klayout_connectivity.findings_selection import FindingsSelectionAdapter  # noqa: E402


class FindingsSelectionAdapterTest(unittest.TestCase):
    def test_dispatches_zoom_highlight_and_cross_probe_to_stubs(self):
        target = FindingTarget("instance", "top/X1")
        model = FindingsModel((Finding("one", "OPEN", "Open", bbox=BoundingBox(1, 2, 3, 4),
                                       highlight_targets=(target,), cross_probe_targets=(target,)),))
        selection = model.set_selection(("one",))
        calls = []
        adapter = FindingsSelectionAdapter(
            lambda bbox: calls.append(("zoom", bbox)),
            lambda targets: calls.append(("highlight", targets)),
            lambda targets: calls.append(("cross_probe", targets)),
        )

        adapter.apply(selection)

        self.assertEqual(calls, [
            ("zoom", BoundingBox(1, 2, 3, 4)),
            ("highlight", (target,)),
            ("cross_probe", (target,)),
        ])

    def test_dispatches_empty_targets_but_never_zooms_without_a_bbox(self):
        selection = FindingsModel((Finding("one", "MISSING", "Missing"),)).set_selection(("one",))
        calls = []
        FindingsSelectionAdapter(
            lambda bbox: calls.append(("zoom", bbox)),
            lambda targets: calls.append(("highlight", targets)),
            lambda targets: calls.append(("cross_probe", targets)),
        ).apply(selection)
        self.assertEqual(calls, [("highlight", ()), ("cross_probe", ())])
