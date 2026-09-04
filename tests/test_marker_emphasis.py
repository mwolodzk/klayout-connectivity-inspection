from klayout_connectivity.findings import FindingTarget
from klayout_connectivity.flight_overlay import SnapshotFlightLine
from klayout_connectivity.marker_emphasis import dim_color, emphasized_flight_line_ids


def _line(identifier, net, pin_a, pin_b):
    return SnapshotFlightLine(
        identifier, net, "a", "b", pin_a, pin_b, (0.0, 0.0), (1.0, 0.0)
    )


def test_dim_color_reduces_every_channel_to_35_percent():
    assert dim_color(0xffffff) == 0x595959
    assert dim_color(0xff0000) == 0x590000
    assert dim_color(0xffff00) == 0x595900


def test_emphasizes_lines_by_net_pin_and_instance_individually():
    lines = (
        _line("one", "TOP.OUT", "TOP/X1/D", "TOP/X2/D"),
        _line("two", "TOP.VDD", "TOP/X3/S", "TOP/X4/S"),
        _line("three", "TOP.GND", "TOP/X5/B", "TOP/X6/B"),
    )
    assert emphasized_flight_line_ids(
        lines, (FindingTarget("net", "TOP.OUT"),)
    ) == ("one",)
    assert emphasized_flight_line_ids(
        lines, (FindingTarget("pin", "TOP.X3.S"),)
    ) == ("two",)
    assert emphasized_flight_line_ids(
        lines, (FindingTarget("instance", "TOP/X5"),)
    ) == ("three",)


def test_net_target_prevents_unrelated_lines_on_same_instance_from_emphasis():
    lines = (
        _line("out", "TOP.OUT", "TOP/X1/D", "TOP/X2/D"),
        _line("vdd", "TOP.VDD", "TOP/X1/S", "TOP/X3/S"),
    )
    targets = (
        FindingTarget("net", "TOP.OUT"),
        FindingTarget("pin", "TOP/X1/D"),
        FindingTarget("instance", "TOP/X1"),
    )
    assert emphasized_flight_line_ids(lines, targets) == ("out",)
