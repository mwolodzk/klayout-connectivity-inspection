"""Interactive KLayout smoke: open Findings and verify real marker/UI state.

The coordinator launches this only in an isolated profile, captures the whole
desktop, inspects every GNOME workspace for error dialogs, and then terminates
that exact GUI process.
"""

from __future__ import annotations

import time

import pya

from klayout_connectivity.flight_overlay import VisibilityMode
from klayout_connectivity.findings import FindingTarget
from klayout_connectivity.marker_emphasis import dim_color
from klayout_connectivity.marker_emphasis import emphasized_flight_line_ids
from klayout_connectivity.options import ConnectivityOptions
from klayout_connectivity.plugin import ConnectivityPluginFactory


def required(name):
    value = globals().get(name)
    if value in (None, ""):
        raise ValueError("Missing -rd %s=<value>" % name)
    return str(value)


expected_findings = int(required("expected_findings"))
expected_lines = int(required("expected_lines"))
expected_instances = int(required("expected_instances"))
expected_nets = int(str(globals().get("expected_nets") or 0))
expected_pins = int(str(globals().get("expected_pins") or 0))
show_manual = str(globals().get("show_manual") or "false").lower() == "true"
run_analysis = str(globals().get("run_analysis") or "false").lower() == "true"
expected_source_warning = str(
    globals().get("expected_source_warning") or "false"
).lower() == "true"

menu = pya.MainWindow.instance().menu()
import_action = menu.action("file_menu.import_menu.import_netlist")
assert import_action is not None and import_action.title == "Netlist", import_action
browser_action = menu.action("tools_menu.connectivity_menu.open_connectivity_browser")
assert browser_action is not None and browser_action.title == "Open Connectivity Browser", browser_action
analysis_action = menu.action("tools_menu.connectivity_menu.run_sg13g2_sdl_analysis")
assert analysis_action is not None and analysis_action.title == "Run SDL Analysis...", analysis_action
import_manual_action = menu.action("file_menu.import_menu.netlist_import_sdl_manual")
assert import_manual_action is not None and import_manual_action.title == "Netlist Import / SDL Manual...", import_manual_action
manual_action = menu.action("tools_menu.connectivity_menu.sdl_user_manual")
assert manual_action is not None and manual_action.title == "SDL / CAS User Manual...", manual_action

factory = ConnectivityPluginFactory.instance
if callable(factory):
    factory = factory()
assert factory is not None

options = ConnectivityOptions.load()
options.show_connectivity_panel = True
options.show_connectivity_info = True
options.show_flywires = True
options.show_terminals = True
options.flight_lines_mode = VisibilityMode.ALL_OPENS.value
options.save()
factory.update_connectivity_panel(options)
assert factory.setupDock is not None
assert factory.setupDock.setupWidget.page.run_sdl_analysis_pb.text == "Run SDL Analysis"

factory.refresh_connectivity_info()
infos = factory.conn_info.cell_infos[0].pcell_infos
assert len(infos) == expected_instances, len(infos)
print("SDL_GUI_COUNTS instances=%d pins=%d" % (
    len(infos), sum(len(info.pin_infos) for info in infos)
), flush=True)
if expected_pins:
    assert sum(len(info.pin_infos) for info in infos) == expected_pins
factory.open_connectivity_browser()
dialog = factory.connectivity_browser_dialog
assert dialog is not None and dialog.isVisible()
assert dialog.run_analysis_pb.text == "Run SDL Analysis"
for tree, columns in (
    (dialog.by_net_page.net_tw, 2),
    (dialog.by_net_page.detail_tw, 4),
    (dialog.by_instance_page.instance_tw, 2),
    (dialog.by_instance_page.detail_tw, 3),
    (dialog.findings_page.findings_tw, 4),
):
    assert all(
        tree.header.sectionResizeMode(column) == pya.QHeaderView.Interactive
        for column in range(columns)
    )

# Both instance-bearing browser tabs drive the same zoom/cross-probe seam.
instance_page = dialog.by_instance_page
def first_indexed_item(item):
    if item.data(0, int(pya.Qt.UserRole)) is not None:
        return item
    for child_index in range(item.childCount()):
        result = first_indexed_item(item.child(child_index))
        if result is not None:
            return result
    return None

instance_item = None
for root_index in range(instance_page.instance_tw.topLevelItemCount):
    instance_item = first_indexed_item(instance_page.instance_tw.topLevelItem(root_index))
    if instance_item is not None:
        break
assert instance_item is not None
instance_page.instance_tw.setCurrentItem(instance_item)
pya.Application.instance().process_events()
assert factory.last_focused_instance_id is not None
assert factory.last_focused_instance_bbox is not None

net_page = dialog.by_net_page
net_page.net_tw.setCurrentItem(net_page.net_tw.topLevelItem(0))
pya.Application.instance().process_events()
assert net_page.detail_tw.topLevelItemCount > 0
expected_net_instance = net_page._detail_entries_by_index[0].pcell
net_page.detail_tw.setCurrentItem(net_page.detail_tw.topLevelItem(0))
pya.Application.instance().process_events()
assert factory.last_focused_instance_id == factory._normalized_target_identifier(
    expected_net_instance.hierarchy_path or expected_net_instance.inst_name
)
assert factory.last_focused_instance_bbox is not None

dialog.tabs.setCurrentIndex(2)
page = dialog.findings_page
print("SDL_GUI_BROWSER nets=%d findings=%d" % (
    dialog.by_net_page.net_tw.topLevelItemCount,
    page.findings_tw.topLevelItemCount,
), flush=True)
assert page.findings_tw.topLevelItemCount == expected_findings
if expected_nets:
    assert dialog.by_net_page.net_tw.topLevelItemCount == expected_nets
if expected_source_warning:
    assert not dialog.snapshot_status_label.isHidden()
    assert "SDL source warning:" in dialog.snapshot_status_label.text
else:
    assert dialog.snapshot_status_label.isHidden(), dialog.snapshot_status_label.text
if run_analysis:
    dialog.on_run_analysis()
    assert factory.sdl_analysis_process is not None
    assert factory.sdl_analysis_timer is not None
    assert not dialog.run_analysis_pb.enabled
    analysis_deadline = time.monotonic() + 30
    while factory.sdl_analysis_process is not None and time.monotonic() < analysis_deadline:
        pya.Application.instance().process_events()
        time.sleep(0.05)
    assert factory.sdl_analysis_process is None, "SDL analysis did not finish"
    assert factory.sdl_snapshot_state[0] == "ready", factory.sdl_snapshot_state
    assert dialog.findings_page.findings_tw.topLevelItemCount == expected_findings
    assert dialog.run_analysis_pb.enabled
for index in range(min(2, expected_findings)):
    page.findings_tw.topLevelItem(index).setSelected(True)
pya.Application.instance().process_events()
assert len(page.findings_tw.selectedItems()) == min(2, expected_findings)
if expected_findings:
    assert factory.markers_terminals
    print("SDL_GUI_EMPHASIS terminal_colors=%r instance_colors=%r flight_colors=%r" % (
        sorted({marker.color for marker in factory.markers_terminals}),
        sorted({marker.color for marker in factory.markers_instance_names}),
        sorted({marker.color for marker in factory.markers_flywires}),
    ), flush=True)
    selected_targets = tuple(factory.active_finding_selection.highlight_targets) + tuple(
        factory.active_finding_selection.cross_probe_targets
    )
    print("SDL_GUI_EMPHASIZED_LINES %r" % (
        emphasized_flight_line_ids(factory.rendered_flight_lines, selected_targets),
    ), flush=True)
    assert all((marker.color & 0xffffff) == dim_color(0xff0000) for marker in factory.markers_terminals)
    assert all((marker.color & 0xffffff) == dim_color(0xffffff) for marker in factory.markers_instance_names)
    flight_colors = {marker.color & 0xffffff for marker in factory.markers_flywires}
    assert 0xffff00 in flight_colors and dim_color(0xffff00) in flight_colors

    page.findings_tw.clearSelection()
    pya.Application.instance().process_events()
    assert not factory.active_finding_selection.findings
    assert all((marker.color & 0xffffff) == 0xff0000 for marker in factory.markers_terminals)
    assert all((marker.color & 0xffffff) == 0xffffff for marker in factory.markers_instance_names)
    assert all((marker.color & 0xffffff) == 0xffff00 for marker in factory.markers_flywires)

    page.findings_tw.topLevelItem(0).setSelected(True)
    pya.Application.instance().process_events()

    dialog.close()
    pya.Application.instance().process_events()
    assert not factory.active_finding_selection.findings
    assert all((marker.color & 0xffffff) == 0xff0000 for marker in factory.markers_terminals)
    assert all((marker.color & 0xffffff) == 0xffffff for marker in factory.markers_instance_names)
    assert all((marker.color & 0xffffff) == 0xffff00 for marker in factory.markers_flywires)
    dialog.show()
    dialog.raise_()
    page.findings_tw.topLevelItem(0).setSelected(True)
    pya.Application.instance().process_events()

factory.set_flight_lines_visibility(VisibilityMode.ALL_OPENS)
assert len(factory.markers_flywires) == expected_lines, len(factory.markers_flywires)
factory._clear_markers_flywires()
assert not factory.markers_flywires
factory.update()
assert len(factory.markers_flywires) == expected_lines
dialog.raise_()
dialog.activateWindow()
if show_manual:
    manual_action.trigger()
    pya.Application.instance().process_events()
    manual = factory.manual_dialog
    assert manual is not None and manual.isVisible()
    text = manual.browser.toPlainText()
    assert "Source File" in text and "All Opens" in text and "okno CAS" in text
    manual.raise_()
    manual.activateWindow()
pya.Application.instance().process_events()
print("SDL_GUI_SMOKE_READY findings=%d selected=%d instances=%d lines=%d" % (
    expected_findings,
    len(page.findings_tw.selectedItems()),
    len(infos),
    len(factory.markers_flywires),
))

# Optional evidence window.  It is bounded so an interrupted coordinator can
# never leave a long-lived KLayout instance behind.
hold_seconds = float(globals().get("hold_seconds") or 0)
deadline = time.monotonic() + min(max(hold_seconds, 0), 45)
while time.monotonic() < deadline:
    pya.Application.instance().process_events()
    time.sleep(0.05)
