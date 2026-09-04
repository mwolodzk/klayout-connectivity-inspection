"""Read-only GUI smoke for an existing project layout.

This intentionally requires no SDL sidecar.  It proves that both plugin menus,
the inspector scan, and the empty Findings state tolerate a real hierarchical
layout without writing it.
"""

from __future__ import annotations

import time
import sys

import pya

from klayout_connectivity.flight_overlay import VisibilityMode
from klayout_connectivity.options import ConnectivityOptions
from klayout_connectivity.plugin import ConnectivityPluginFactory


show_manual = str(globals().get("show_manual") or "false").lower() == "true"

menu = pya.MainWindow.instance().menu()
import_action = menu.action("file_menu.import_menu.import_netlist")
assert import_action is not None and import_action.title == "Netlist", import_action
browser_action = menu.action("tools_menu.connectivity_menu.open_connectivity_browser")
assert browser_action is not None and browser_action.title == "Open Connectivity Browser", browser_action
analysis_action = menu.action("tools_menu.connectivity_menu.run_sg13g2_sdl_analysis")
assert analysis_action is not None and analysis_action.title == "Run SG13G2 SDL Analysis...", analysis_action
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

factory.view.zoom_fit()
factory.refresh_connectivity_info()
assert factory.conn_info is not None and factory.conn_info.cell_infos
infos = factory.conn_info.cell_infos[0].pcell_infos

direct_instances = sum(1 for _inst in factory.cell_view.cell.each_inst())
assert direct_instances >= int(globals().get("min_layout_instances") or 1)

factory.open_connectivity_browser()
dialog = factory.connectivity_browser_dialog
assert dialog is not None and dialog.isVisible()
assert dialog.run_analysis_pb.text == "Run SG13G2 SDL Analysis"
main_window = pya.MainWindow.instance()
main_window.showNormal()
main_window.resize(1280, 850)
main_window.move(40, 80)
main_window.raise_()
main_window.activateWindow()
dialog.showNormal()
dialog.resize(1000, 560)
dialog.move(120, 150)
dialog.tabs.setCurrentIndex(2)
page = dialog.findings_page
assert page.findings_tw.topLevelItemCount == 0
assert not factory.markers_flywires
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

pcells = sum(1 for info in infos if getattr(info, "pcell_name", None))
with_pins = sum(1 for info in infos if info.pin_infos)
print("SDL_REAL_GUI_SMOKE_READY top=%s direct_instances=%d cells=%d inspected=%d pcells=%d with_pins=%d findings=0" % (
    factory.cell_view.cell.name,
    direct_instances,
    factory.layout.cells(),
    len(infos),
    pcells,
    with_pins,
))
sys.stdout.flush()

# Bounded evidence window.  The coordinator still stops the exact container
# immediately after the screenshot.
hold_seconds = float(globals().get("hold_seconds") or 0)
deadline = time.monotonic() + min(max(hold_seconds, 0), 45)
while time.monotonic() < deadline:
    pya.Application.instance().process_events()
    time.sleep(0.05)
