import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pymacros"))

from klayout_connectivity.findings import BoundingBox, FindingStatus, FindingTarget  # noqa: E402
from klayout_connectivity.sdl_snapshot import (  # noqa: E402
    SnapshotFormatError,
    load_flight_lines_for_layout,
    load_flight_lines_sidecar,
    load_findings_for_layout,
    load_findings_sidecar,
    sidecar_path_for_layout,
)


class SdlSnapshotTest(unittest.TestCase):
    def test_loads_public_sidecar_without_importer_and_maps_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            layout = Path(directory) / "chip.gds"
            sidecar = sidecar_path_for_layout(str(layout))
            sidecar.write_text(json.dumps({"findings": [{
                "finding_id": "open:1", "kind": "OPEN", "message": "VDD split",
                "status": "visited", "bbox": [1, 2, 4, 8],
                "pin_ids": ["top/X1/A"], "component_ids": ["component-7"],
                "instance_ids": ["top/X1"], "expected_net": "VDD",
                "observed_nets": ["VDD_A"],
            }]}), encoding="utf-8")

            findings = load_findings_for_layout(str(layout))

        self.assertEqual(findings[0].identifier, "open:1")
        self.assertEqual(findings[0].status, FindingStatus.VISITED)
        self.assertEqual(findings[0].bbox, BoundingBox(1, 2, 4, 8))
        self.assertEqual(
            findings[0].highlight_targets,
            (FindingTarget("component", "component-7"), FindingTarget("pin", "top/X1/A"),
             FindingTarget("instance", "top/X1")),
        )
        self.assertEqual(
            findings[0].cross_probe_targets,
            (FindingTarget("instance", "top/X1"), FindingTarget("pin", "top/X1/A"),
             FindingTarget("net", "VDD"), FindingTarget("net", "VDD_A")),
        )

    def test_rejects_malformed_bbox_and_unknown_status(self):
        with tempfile.TemporaryDirectory() as directory:
            sidecar = Path(directory) / "bad.sdl.json"
            sidecar.write_text(json.dumps({"findings": [{
                "finding_id": "f", "kind": "OPEN", "message": "bad",
                "status": "ignored", "bbox": [4, 0, 2, 1],
            }]}), encoding="utf-8")
            with self.assertRaises(SnapshotFormatError):
                load_findings_sidecar(sidecar)

    def test_loads_findings_from_importer_sidecar_snapshot_member(self):
        with tempfile.TemporaryDirectory() as directory:
            sidecar = Path(directory) / "chip.gds.sdl.json"
            sidecar.write_text(json.dumps({
                "schema": "1.0",
                "expected": {"VDD": ["TOP/X1/D"]},
                "snapshot": {"stale": False, "findings": [{
                    "finding_id": "open:nested",
                    "kind": "OPEN",
                    "message": "nested snapshot",
                    "pin_ids": [],
                    "component_ids": [],
                    "instance_ids": [],
                    "observed_nets": [],
                }]},
            }), encoding="utf-8")

            findings = load_findings_sidecar(sidecar)

        self.assertEqual([finding.identifier for finding in findings], ["open:nested"])

    def test_importer_sidecar_without_snapshot_has_no_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            sidecar = Path(directory) / "chip.gds.sdl.json"
            sidecar.write_text(json.dumps({"schema": "1.0", "snapshot": None}), encoding="utf-8")
            self.assertEqual(load_findings_sidecar(sidecar), ())

    def test_loads_only_flight_lines_backed_by_open_and_rejects_short_or_wrong_net(self):
        with tempfile.TemporaryDirectory() as directory:
            layout = Path(directory) / "chip.gds"
            sidecar = sidecar_path_for_layout(str(layout))
            sidecar.write_text(json.dumps({"snapshot": {
                "findings": [
                    {"finding_id": "o", "kind": "OPEN", "message": "split",
                     "expected_net": "VDD", "component_ids": ["a", "b"],
                     "pin_ids": ["TOP/A/P", "TOP/B/P"]},
                    {"finding_id": "s", "kind": "SHORT", "message": "short",
                     "component_ids": ["c"]},
                    {"finding_id": "w", "kind": "WRONG_NET", "message": "wrong",
                     "component_ids": ["d"]},
                ],
                "flight_lines": [
                    {"line_id": "good", "expected_net": "VDD", "component_a": "a",
                     "component_b": "b", "pin_a": "TOP/A/P", "pin_b": "TOP/B/P",
                     "start": [1, 2], "end": [3, 4]},
                    {"line_id": "short", "expected_net": "VDD", "component_a": "a",
                     "component_b": "c", "pin_a": "TOP/A/P", "pin_b": "TOP/C/P",
                     "start": [1, 2], "end": [5, 6]},
                    {"line_id": "wrong", "expected_net": "VDD", "component_a": "a",
                     "component_b": "d", "pin_a": "TOP/A/P", "pin_b": "TOP/D/P",
                     "start": [1, 2], "end": [7, 8]},
                    {"line_id": "orphan", "expected_net": "VDD", "component_a": "a",
                     "component_b": "z", "pin_a": "TOP/A/P", "pin_b": "TOP/Z/P",
                     "start": [1, 2], "end": [9, 10]},
                ],
            }}), encoding="utf-8")

            lines = load_flight_lines_for_layout(str(layout))

        self.assertEqual([line.line_id for line in lines], ["good"])
        self.assertEqual(lines[0].start, (1.0, 2.0))

    def test_malformed_flight_line_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            sidecar = Path(directory) / "bad.sdl.json"
            sidecar.write_text(json.dumps({"findings": [], "flight_lines": [{
                "line_id": "bad", "expected_net": "N", "component_a": "a",
                "component_b": "b", "pin_a": "a/p", "pin_b": "b/p",
                "start": [0, 0], "end": [1],
            }]}), encoding="utf-8")
            with self.assertRaises(SnapshotFormatError):
                load_flight_lines_sidecar(sidecar)

    def test_stale_snapshot_never_renders_flight_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            sidecar = Path(directory) / "stale.sdl.json"
            sidecar.write_text(json.dumps({"snapshot": {
                "stale": True,
                "findings": [{
                    "finding_id": "o", "kind": "OPEN", "message": "old",
                    "expected_net": "N", "component_ids": ["a", "b"],
                    "pin_ids": ["TOP/A/P", "TOP/B/P"],
                }],
                "flight_lines": [{
                    "line_id": "old", "expected_net": "N",
                    "component_a": "a", "component_b": "b",
                    "pin_a": "TOP/A/P", "pin_b": "TOP/B/P",
                    "start": [0, 0], "end": [1, 0],
                }],
            }}), encoding="utf-8")

            self.assertEqual(load_flight_lines_sidecar(sidecar), ())
