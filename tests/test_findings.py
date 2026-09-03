import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pymacros"))

from klayout_connectivity.findings import (  # noqa: E402
    BoundingBox,
    Finding,
    FindingKinds,
    FindingStatus,
    FindingTarget,
    FindingsFilter,
    FindingsModel,
)


def finding(identifier, kind=FindingKinds.OPEN, status=FindingStatus.ACTIVE, bbox=None,
            highlights=(), probes=(), title=None, message=""):
    return Finding(
        identifier=identifier,
        kind=kind,
        title=title or identifier,
        status=status,
        message=message,
        bbox=bbox,
        highlight_targets=highlights,
        cross_probe_targets=probes,
    )


class FindingsModelTest(unittest.TestCase):
    def test_filter_covers_status_kind_and_text_including_custom_kind(self):
        model = FindingsModel((
            finding("open-1", message="VDD disconnected"),
            finding("short-1", kind=FindingKinds.SHORT, status=FindingStatus.VISITED),
            finding("custom-1", kind="erc/custom", status=FindingStatus.WAIVED, title="Odd path"),
        ))

        model.set_filter(FindingsFilter(statuses=frozenset((FindingStatus.ACTIVE,))))
        self.assertEqual([f.identifier for f in model.visible_findings], ["open-1"])

        model.set_filter(FindingsFilter(kinds=frozenset(("erc/custom",)), text="odd"))
        self.assertEqual([f.identifier for f in model.visible_findings], ["custom-1"])

    def test_sdl_v1_kind_catalogue_is_complete(self):
        self.assertEqual(
            {kind.value for kind in FindingKinds},
            {
                "OPEN", "SHORT", "WRONG_NET", "UNBOUND", "MISSING",
                "MASTER_MISMATCH", "PARAMETER_MISMATCH",
            },
        )

    def test_two_finding_selection_unions_bbox_and_deduplicates_targets(self):
        instance_a = FindingTarget("instance", "top.XA")
        instance_b = FindingTarget("instance", "top.XB")
        net_vdd = FindingTarget("net", "VDD")
        model = FindingsModel((
            finding(
                "a", bbox=BoundingBox(10, 20, 30, 40),
                highlights=(instance_a,), probes=(net_vdd,),
            ),
            finding(
                "b", kind=FindingKinds.SHORT, bbox=BoundingBox(-2, 25, 15, 80),
                highlights=(instance_a, instance_b), probes=(net_vdd, instance_b),
            ),
        ))

        selection = model.set_selection(("a", "b"))

        self.assertEqual(selection.zoom_bbox, BoundingBox(-2, 20, 30, 80))
        self.assertEqual(selection.highlight_targets, (instance_a, instance_b))
        self.assertEqual(selection.cross_probe_targets, (net_vdd, instance_b))

    def test_selection_is_stable_through_filter_and_status_transitions(self):
        model = FindingsModel((finding("a"), finding("b", kind=FindingKinds.SHORT)))
        model.set_selection(("a", "b"))
        model.mark_visited(("a",))
        model.waive(("b",))
        model.set_filter(FindingsFilter(statuses=frozenset((FindingStatus.VISITED,))))

        self.assertEqual([f.identifier for f in model.visible_findings], ["a"])
        self.assertEqual([f.status for f in model.selected_findings],
                         [FindingStatus.VISITED, FindingStatus.WAIVED])
        model.reactivate(("a",))
        self.assertEqual(model.findings[0].status, FindingStatus.ACTIVE)

    def test_invalid_ids_and_duplicate_rows_are_rejected(self):
        with self.assertRaises(ValueError):
            FindingsModel((finding("same"), finding("same", kind=FindingKinds.SHORT)))
        model = FindingsModel((finding("known"),))
        with self.assertRaises(KeyError):
            model.set_selection(("missing",))

    def test_raw_status_is_normalized_for_generic_rule_adapters(self):
        result = Finding("raw", "FUTURE_KIND", "Future", status="waived")
        self.assertEqual(result.status, FindingStatus.WAIVED)


if __name__ == "__main__":
    unittest.main()
