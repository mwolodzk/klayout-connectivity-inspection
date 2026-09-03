"""Interactive KLayout smoke: open Findings and verify real marker/UI state.

The coordinator launches this only in an isolated profile, captures the whole
desktop, inspects every GNOME workspace for error dialogs, and then terminates
that exact GUI process.
"""

from __future__ import annotations

import time

import pya

from klayout_connectivity.flight_overlay import VisibilityMode
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
expect_static = str(globals().get("expect_static") or "false").lower() == "true"
show_manual = str(globals().get("show_manual") or "false").lower() == "true"

menu = pya.MainWindow.instance().menu()
import_action = menu.action("file_menu.import_menu.import_netlist")
assert import_action is not None and import_action.title == "Netlist", import_action
browser_action = menu.action("tools_menu.connectivity_menu.open_connectivity_browser")
assert browser_action is not None and browser_action.title == "Open Connectivity Browser", browser_action
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

factory.refresh_connectivity_info()
infos = factory.conn_info.cell_infos[0].pcell_infos
assert len(infos) == expected_instances, len(infos)
print("SDL_GUI_COUNTS instances=%d pins=%d" % (
    len(infos), sum(len(info.pin_infos) for info in infos)
), flush=True)
if expected_pins:
    assert sum(len(info.pin_infos) for info in infos) == expected_pins
if expect_static:
    static = next(info for info in infos if info.hierarchy_path == "TOP.XQ1")
    assert {pin.name for pin in static.pin_infos} == {"C", "B", "E"}

factory.open_connectivity_browser()
dialog = factory.connectivity_browser_dialog
assert dialog is not None and dialog.isVisible()
dialog.tabs.setCurrentIndex(2)
page = dialog.findings_page
print("SDL_GUI_BROWSER nets=%d findings=%d" % (
    dialog.by_net_page.net_tw.topLevelItemCount,
    page.findings_tw.topLevelItemCount,
), flush=True)
assert page.findings_tw.topLevelItemCount == expected_findings
if expected_nets:
    assert dialog.by_net_page.net_tw.topLevelItemCount == expected_nets
assert dialog.snapshot_status_label.isHidden(), dialog.snapshot_status_label.text
for index in range(min(2, expected_findings)):
    page.findings_tw.topLevelItem(index).setSelected(True)
pya.Application.instance().process_events()
assert len(page.findings_tw.selectedItems()) == min(2, expected_findings)

factory.set_flight_lines_visibility(VisibilityMode.ALL_OPENS)
assert len(factory.markers_flywires) == expected_lines, len(factory.markers_flywires)
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
print("SDL_GUI_SMOKE_READY findings=%d selected=%d instances=%d lines=%d static=%s" % (
    expected_findings,
    len(page.findings_tw.selectedItems()),
    len(infos),
    len(factory.markers_flywires),
    str(expect_static).lower(),
))

# Optional evidence window.  It is bounded so an interrupted coordinator can
# never leave a long-lived KLayout instance behind.
hold_seconds = float(globals().get("hold_seconds") or 0)
deadline = time.monotonic() + min(max(hold_seconds, 0), 45)
while time.monotonic() < deadline:
    pya.Application.instance().process_events()
    time.sleep(0.05)
