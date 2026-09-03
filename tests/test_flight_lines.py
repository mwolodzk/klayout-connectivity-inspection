import unittest

from pymacros.klayout_connectivity.flight_lines import (
    PinAccessPoint,
    build_flight_lines,
)


class FlightLinesTest(unittest.TestCase):
    def test_three_components_use_nearest_access_points_and_have_k_minus_one_lines(self):
        points = [
            # Component A has two access points; B-A must use A.near, not A.far.
            PinAccessPoint("A", "far", 0.0, 100.0, "VDD", "VDD"),
            PinAccessPoint("A", "near", 0.0, 0.0, "VDD", "VDD"),
            PinAccessPoint("B", "pad", 3.0, 0.0, "VDD", "VDD"),
            PinAccessPoint("C", "pad", 10.0, 0.0, "VDD", "VDD"),
        ]

        lines = build_flight_lines(points, "VDD")

        self.assertEqual(len(lines), 2)
        self.assertEqual(
            {(line.component_a, line.component_b) for line in lines},
            {("A", "B"), ("B", "C")},
        )
        ab = next(line for line in lines if (line.component_a, line.component_b) == ("A", "B"))
        self.assertEqual(ab.point_a.pin_id, "near")
        self.assertAlmostEqual(ab.distance, 3.0)

    def test_result_is_independent_of_input_order_and_ties_are_stable(self):
        points = [
            PinAccessPoint("C", "p", 2.0, 0.0, "N", "N"),
            PinAccessPoint("A", "p", 0.0, 0.0, "N", "N"),
            PinAccessPoint("B", "p", 1.0, 0.0, "N", "N"),
        ]
        forward = build_flight_lines(points, "N")
        reverse = build_flight_lines(reversed(points), "N")
        self.assertEqual(forward, reverse)

    def test_wrong_net_and_short_points_never_create_lines(self):
        points = [
            PinAccessPoint("good", "p", 0.0, 0.0, "N", "N"),
            PinAccessPoint("wrong", "p", 1.0, 0.0, "N", "OTHER"),
            PinAccessPoint("short", "p", 2.0, 0.0, "N", "N", is_short=True),
            # A point for another expected net must also be ignored.
            PinAccessPoint("other-net", "p", 3.0, 0.0, "OTHER", "OTHER"),
        ]

        self.assertEqual(build_flight_lines(points, "N"), ())

    def test_single_component_has_no_line(self):
        point = PinAccessPoint("only", "p", 1.0, 2.0, "N", "N")
        self.assertEqual(build_flight_lines([point], "N"), ())


if __name__ == "__main__":
    unittest.main()
