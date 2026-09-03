"""Bounded GUI smoke for the in-application SDL/CAS manual menu entries."""

from __future__ import annotations

import time

import pya

from klayout_connectivity.plugin import ConnectivityPluginFactory


expect_importer = str(globals().get("expect_importer") or "true").lower() == "true"
standalone = str(globals().get("standalone") or "false").lower() == "true"

menu = pya.MainWindow.instance().menu()
manual_path = (
    "tools_menu.sdl_cas_user_manual"
    if standalone
    else "tools_menu.connectivity_menu.sdl_user_manual"
)
manual_action = menu.action(manual_path)
assert manual_action is not None and manual_action.title == "SDL / CAS User Manual..."

import_manual_action = menu.action("file_menu.import_menu.netlist_import_sdl_manual")
if expect_importer:
    assert import_manual_action is not None
    assert import_manual_action.title == "Netlist Import / SDL Manual..."
else:
    assert import_manual_action is None

factory = ConnectivityPluginFactory.instance
if callable(factory):
    factory = factory()
assert factory is not None

manual_action.trigger()
pya.Application.instance().process_events()
if standalone:
    manual = next(
        (
            widget
            for widget in pya.QApplication.topLevelWidgets()
            if widget.windowTitle == "SDL / CAS User Manual"
        ),
        None,
    )
else:
    manual = factory.manual_dialog
assert manual is not None and manual.isVisible()
text = manual.browser.toPlainText()
for phrase in ("Source File", "Netlist Node Order", "All Opens", "okno CAS"):
    assert phrase in text

manual.showNormal()
manual.resize(940, 760)
manual.raise_()
manual.activateWindow()
pya.Application.instance().process_events()
print("SDL_MANUAL_GUI_SMOKE_READY importer=%s standalone=%s" % (
    str(expect_importer).lower(),
    str(standalone).lower(),
))

hold_seconds = float(globals().get("hold_seconds") or 0)
deadline = time.monotonic() + min(max(hold_seconds, 0), 45)
while time.monotonic() < deadline:
    pya.Application.instance().process_events()
    time.sleep(0.05)
