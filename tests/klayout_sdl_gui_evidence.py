"""Arrange a bounded, real-project KLayout view for documentation capture."""

from __future__ import annotations

import time

import pya

from klayout_connectivity.flight_overlay import VisibilityMode
from klayout_connectivity.options import ConnectivityOptions
from klayout_connectivity.plugin import ConnectivityPluginFactory


mode = str(globals().get("evidence_mode") or "findings")
hold_seconds = min(max(float(globals().get("hold_seconds") or 30), 0), 120)

factory = ConnectivityPluginFactory.instance
if callable(factory):
    factory = factory()
assert factory is not None

options = ConnectivityOptions.load()
options.show_connectivity_panel = True
options.show_connectivity_info = True
options.show_flywires = True
options.show_terminals = True
options.show_instance_names = True
options.flight_lines_mode = VisibilityMode.ALL_OPENS.value
options.save()

factory.refresh_connectivity_info()
factory.open_connectivity_browser()
dialog = factory.connectivity_browser_dialog
assert dialog is not None and dialog.isVisible()

main_window = pya.MainWindow.instance()
main_window.showNormal()
main_window.resize(1880, 1000)
main_window.move(10, 35)
main_window.raise_()
main_window.activateWindow()

dialog.showNormal()
dialog.resize(920, 560)
dialog.move(30, 125)

if mode == "findings":
    dialog.tabs.setCurrentIndex(2)
    page = dialog.findings_page
    finding_count = page.findings_tw.topLevelItemCount
    assert finding_count >= 1
    # Prefer the third finding when present (the SG13G2 evidence fixture);
    # otherwise select the final real-project row (XH018 has OPEN and SHORT).
    page.findings_tw.clearSelection()
    page.findings_tw.topLevelItem(min(2, finding_count - 1)).setSelected(True)
elif mode == "by_net":
    dialog.tabs.setCurrentIndex(0)
    page = dialog.by_net_page
    assert page.net_tw.topLevelItemCount
    best_index = 0
    best_count = -1
    for index in range(page.net_tw.topLevelItemCount):
        page.net_tw.setCurrentItem(page.net_tw.topLevelItem(index))
        pya.Application.instance().process_events()
        if page.detail_tw.topLevelItemCount > best_count:
            best_index = index
            best_count = page.detail_tw.topLevelItemCount
    page.net_tw.setCurrentItem(page.net_tw.topLevelItem(best_index))
    pya.Application.instance().process_events()
    assert page.detail_tw.topLevelItemCount
    page.detail_tw.setCurrentItem(page.detail_tw.topLevelItem(0))
    assert factory.last_focused_instance_bbox is not None
else:
    raise ValueError("Unsupported evidence_mode: %s" % mode)

pya.Application.instance().process_events()
dialog.raise_()
dialog.activateWindow()
print("SDL_GUI_EVIDENCE_READY mode=%s" % mode, flush=True)

deadline = time.monotonic() + hold_seconds
while time.monotonic() < deadline:
    pya.Application.instance().process_events()
    time.sleep(0.05)
