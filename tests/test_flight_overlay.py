import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pymacros"))

from klayout_connectivity.flight_overlay import (  # noqa: E402
    FlightLineMarkerSeam,
    SnapshotFlightLine,
    VisibilityMode,
    visible_flight_lines,
)


def line(line_id, net="n", pin_a="TOP/A/P", pin_b="TOP/B/P"):
    return SnapshotFlightLine(line_id, net, "a", "b", pin_a, pin_b, (0.0, 0.0), (1.0, 0.0))


class FlightOverlayTest(unittest.TestCase):
    def test_all_visibility_modes_filter_only_existing_lines(self):
        n1 = line("n1", "net-1", "TOP/A/P", "TOP/B/P")
        n2 = line("n2", "net-2", "TOP/C/P", "TOP/D/P")
        lines = (n1, n2)
        self.assertEqual(visible_flight_lines(lines, VisibilityMode.OFF), ())
        self.assertEqual(visible_flight_lines(lines, VisibilityMode.ALL_OPENS), lines)
        self.assertEqual(visible_flight_lines(lines, VisibilityMode.SELECTED_NETS, ["net-2"]), (n2,))
        self.assertEqual(visible_flight_lines(lines, VisibilityMode.SELECTED_PINS, ["TOP/A/P"]), (n1,))
        self.assertEqual(
            visible_flight_lines(lines, VisibilityMode.SELECTED_INSTANCES, ["TOP/C"]),
            (n2,),
        )

    def test_marker_seam_destroys_previous_snapshot_before_replacing_it(self):
        calls = []
        seam = FlightLineMarkerSeam(
            lambda start, end: calls.append(("create", start, end)) or len(calls),
            lambda marker: calls.append(("destroy", marker)),
        )
        seam.render((line("first"),))
        seam.render(())
        self.assertEqual(calls[0][0], "create")
        self.assertEqual(calls[1], ("destroy", 1))
        self.assertEqual(seam.markers, ())


if __name__ == "__main__":
    unittest.main()
