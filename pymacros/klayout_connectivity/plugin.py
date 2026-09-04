# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2026 Martin Jan Köhler
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
#--------------------------------------------------------------------------------


from __future__ import annotations

import os 
import subprocess
import traceback
from typing import *

import pya

from klayout_plugin_utils.debugging import debug, Debugging
from klayout_plugin_utils.event_loop import EventLoop
from klayout_plugin_utils.layout_connectivity_info import (
    CellConnectivityInfo,
    CellInstanceConnectivityInfo,
    Context,
    LayoutConnectivityInfo,
    PinInfo,
    PROPERTY_KEY__INSTANCE_INFO__CELL_NAME,
    PROPERTY_KEY__INSTANCE_INFO__HIERARCHY_PATH,
    PROPERTY_KEY__INSTANCE_INFO__INSTANCE_NAME,
    PROPERTY_KEY__INSTANCE_INFO__LIB_NAME,
    PROPERTY_KEY__INSTANCE_INFO__LOCAL_NET_MAP,
    PROPERTY_KEY__INSTANCE_INFO__VERSION,
)
from klayout_plugin_utils.qt_helpers import qmessagebox_critical

from klayout_connectivity.browser import ConnectivityBrowserDialog
from klayout_connectivity.findings import BoundingBox, FindingSelection, FindingTarget
from klayout_connectivity.findings_selection import FindingsSelectionAdapter
from klayout_connectivity.marker_emphasis import dim_color, emphasized_flight_line_ids
from klayout_connectivity.flight_overlay import (
    FlightLineMarkerSeam,
    VisibilityMode,
    selected_identifiers_for_mode,
    visible_flight_lines,
)
from klayout_connectivity.options import ConnectivityOptions, CONFIG_KEY__CONNECTIVITY_OPTIONS
from klayout_connectivity.sdl_snapshot import (
    SnapshotFormatError,
    SnapshotState,
    load_browser_instances_for_layout,
    load_findings_for_layout,
    load_flight_lines_for_layout,
    load_pin_access_for_layout,
    snapshot_state_for_layout,
)
from klayout_connectivity.sdl_analysis_launcher import (
    adapter_for_technology,
    build_attach_source_command,
    build_sdl_command,
    find_batch_script,
    find_source_attach_script,
)
from klayout_connectivity.user_manual import SDLUserManualDialog

#--------------------------------------------------------------------------------

path_containing_this_script = os.path.realpath(os.path.dirname(__file__))

_INSTANCE_INFO_KEYS = (
    PROPERTY_KEY__INSTANCE_INFO__VERSION,
    PROPERTY_KEY__INSTANCE_INFO__LIB_NAME,
    PROPERTY_KEY__INSTANCE_INFO__CELL_NAME,
    PROPERTY_KEY__INSTANCE_INFO__INSTANCE_NAME,
    PROPERTY_KEY__INSTANCE_INFO__HIERARCHY_PATH,
    PROPERTY_KEY__INSTANCE_INFO__LOCAL_NET_MAP,
)

#--------------------------------------------------------------------------------


class ConnectivitySetupDock(pya.QDockWidget):
    def __init__(self, 
                 refresh_callback: Callable,
                 open_connectivity_browser_callback: Callable,
                 attach_source_callback: Callable,
                 run_analysis_callback: Callable,
                 hide_callback: Callable):
        super().__init__()
        self.setupWidget = ConnectivitySetupWidget(refresh_callback, 
                                                   open_connectivity_browser_callback,
                                                   attach_source_callback,
                                                   run_analysis_callback,
                                                   hide_callback)
        self.setWidget(self.setupWidget)
        self.setWindowTitle("Connectivity Inspection")

    def closeEvent(self, event):
        self.setupWidget.hide_callback()
        event.accept()
    
    def update_ui_from_config(self, config: ConnectivityOptions):
        self.setupWidget.update_ui_from_config(config)
    
    def config_from_ui(self) -> ConnectivityOptions:
        return self.setupWidget.config_from_ui()

    def set_analysis_running(self, running: bool):
        self.setupWidget.set_analysis_running(running)

    def set_source_attaching(self, running: bool):
        self.setupWidget.set_source_attaching(running)
        
        
class ConnectivitySetupWidget(pya.QWidget):
    def __init__(self, 
                 refresh_callback: Callable,
                 open_connectivity_browser_callback: Callable, 
                 attach_source_callback: Callable,
                 run_analysis_callback: Callable,
                 hide_callback: Callable):
        super().__init__()
        
        self.hide_callback = hide_callback
        
        loader = pya.QUiLoader()
        ui_path = os.path.join(path_containing_this_script, "ConnectivitySetupPage.ui")
        ui_file = pya.QFile(ui_path)
        try:
            ui_file.open(pya.QFile.ReadOnly)
            self.page = loader.load(ui_file, self)
        finally:
            ui_file.close()

        self._layout = pya.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self.page)
        self.setLayout(self._layout)

        self.page.open_connectivity_browser_pb.clicked(open_connectivity_browser_callback)
        self.page.refresh_pb.clicked(refresh_callback)
        self.page.attach_sdl_source_pb.clicked(attach_source_callback)
        self.page.run_sdl_analysis_pb.clicked(run_analysis_callback)

        for cbx in (
            self.page.show_connectivity_cbx,
            self.page.show_flywires_cbx,
            self.page.show_instance_names_cbx,
            self.page.show_terminals_cbx,
        ):
            cbx.toggled(self.save_config)        
        self.page.flight_lines_mode_cb.currentIndexChanged(self.save_config)

    def set_analysis_running(self, running: bool):
        self.page.run_sdl_analysis_pb.setEnabled(not running)
        self.page.attach_sdl_source_pb.setEnabled(not running)
        self.page.run_sdl_analysis_pb.setText(
            "SDL Analysis is running..." if running else "Run SDL Analysis"
        )

    def set_source_attaching(self, running: bool):
        self.page.attach_sdl_source_pb.setEnabled(not running)
        self.page.run_sdl_analysis_pb.setEnabled(not running)
        self.page.attach_sdl_source_pb.setText(
            "Attaching SDL Source..." if running else "Attach SDL Source..."
        )
         
    def update_ui_from_config(self, config: ConnectivityOptions):
        cbx_and_value = (
            (self.page.show_connectivity_cbx, config.show_connectivity_info),
            (self.page.show_flywires_cbx, config.show_flywires),
            (self.page.show_instance_names_cbx, config.show_instance_names),
            (self.page.show_terminals_cbx, config.show_terminals),
        )
        
        previous = [(cbx, cbx.blockSignals(True)) for cbx, _ in cbx_and_value]
        try:
            for cbx, checked in cbx_and_value:
                cbx.setChecked(checked)
            self.page.flight_lines_mode_cb.setCurrentText(config.flight_lines_mode)
        finally:
            for cbx, was_blocked in previous:
                cbx.blockSignals(was_blocked)            
    
    def config_from_ui(self) -> ConnectivityOptions:
        o = ConnectivityOptions.load()
        o.show_connectivity_info = self.page.show_connectivity_cbx.checked
        o.show_flywires = self.page.show_flywires_cbx.checked
        o.flight_lines_mode = self.page.flight_lines_mode_cb.currentText
        o.show_instance_names = self.page.show_instance_names_cbx.checked
        o.show_terminals = self.page.show_terminals_cbx.checked
        return o

    def save_config(self, _checked: bool = False):
        o = self.config_from_ui()
        o.save()


class ConnectivityPluginFactory(pya.PluginFactory):
    def __init__(self):
        super().__init__()        
        
        self.has_tool_entry = False
        self.register(-1000, "connectivity_visible", "Connectivity Inspection", self.icon_path)
  
        self.setupDock      = None
        self.connectivity_browser_dialog = None
        self.manual_dialog = None
        self.conn_info = None
        self.markers_flywires = []
        self.markers_terminals = []
        self.markers_instance_names = []
        self.markers_findings = []
        self.sdl_flight_lines = ()
        self.sdl_pin_access_points = ()
        self.sdl_snapshot_state = ("missing", "No layout is available for SDL analysis.")
        self.sdl_live_dirty = False
        self.sdl_analysis_process = None
        self.sdl_analysis_timer = None
        self.sdl_analysis_log = None
        self.sdl_analysis_log_path = None
        self.sdl_analysis_target_path = None
        self.sdl_source_process = None
        self.sdl_source_timer = None
        self.sdl_source_log = None
        self.sdl_source_log_path = None
        self.sdl_source_target_path = None
        self.active_finding_selection = None
        self.rendered_flight_lines = ()
        self.last_focused_instance_id = None
        self.last_focused_instance_bbox = None
        self.flight_lines_mode = VisibilityMode.ALL_OPENS
        self.flight_lines_selected = ()
        self.flight_line_marker_seam = FlightLineMarkerSeam(
            self._create_flight_line_marker,
            self._destroy_flight_line_marker,
        )
        self.findings_selection_adapter = FindingsSelectionAdapter(
            self._zoom_to_finding_bbox,
            self._highlight_finding_targets,
            self._cross_probe_finding_targets,
        )
        
        self._waiting_for_file_open = False
        
        try:
            options = ConnectivityOptions.load()
            self.init_menu(options)
            self.setup(options)
        except Exception as e:
            print("ConnectivityPluginFactory.ctor caught an exception", e)
            traceback.print_exc()

    @property
    def icon_path(self) -> str:
        p = os.path.join(path_containing_this_script, 'icons', 'flywire_32px.png')
        return p

    @classmethod
    def instance(cls) -> cls:
        if 'ConnectivityPluginFactory_Singleton_Instance' in globals():
            global ConnectivityPluginFactory_Singleton_Instance
            return ConnectivityPluginFactory_Singleton_Instance
    
    @property
    def view(self) -> pya.LayoutView:
        return pya.LayoutView.current()
            
    @property
    def cell_view(self) -> pya.CellView:
        return pya.CellView.active()

    @property
    def layout(self) -> Optional[pya.Layout]:
        cell_view = self.cell_view
        return cell_view.layout() if cell_view else None
            
    @property
    def tech(self) -> Optional[pya.Technology]:
        layout = self.layout
        return layout.technology() if layout else None
    
    @property
    def options(self) -> ConnectivityOptions:
        o = ConnectivityOptions.load()
        return o

    def init_menu(self, options: ConnectivityOptions):
        if Debugging.DEBUG:
            debug("ConnectivityPluginFactory.init_menu")
        
        mw = pya.MainWindow.instance()
        menu = mw.menu()
        
        self._append_separator_if_needed(menu, "tools_menu.end", "connectivity_separator")
        menu.insert_menu("tools_menu.end", "connectivity_menu",  "Connectivity Inspection")
        
        action = pya.Action()
        action.title = "Show Connectivity Panel"
        action.checkable = True
        action.checked = options.show_connectivity_panel
        action.on_triggered += lambda a=action: self.toggle_connectivity_panel(a)
        menu.insert_item(f"tools_menu.connectivity_menu.#0", f"show_connectivity_panel", action)
        self._menu_action_show_connectivity_panel = action

        action = pya.Action()
        action.title = "Show Connectivity Information"
        action.checkable = True
        action.checked = options.show_connectivity_info
        action.on_triggered += lambda a=action: self.toggle_connectivity_info(a)
        menu.insert_item(f"tools_menu.connectivity_menu.#1", f"show_connectivity_info", action)
        self._menu_action_show_connectivity_info = action
    
        action = pya.Action()
        action.title = "Open Connectivity Browser"
        action.on_triggered += lambda: self.open_connectivity_browser()
        menu.insert_item(f"tools_menu.connectivity_menu.#2", f"open_connectivity_browser", action)
        self._menu_action_open_connectivity_browser = action

        action = pya.Action()
        action.title = "Attach SDL Source..."
        action.on_triggered += lambda: self.attach_sdl_source()
        menu.insert_item(
            "tools_menu.connectivity_menu.#3", "attach_sdl_source", action
        )
        self._menu_action_attach_sdl_source = action

        action = pya.Action()
        action.title = "Run SDL Analysis..."
        action.on_triggered += lambda: self.run_sdl_analysis()
        menu.insert_item(
            "tools_menu.connectivity_menu.#4", "run_sg13g2_sdl_analysis", action
        )
        self._menu_action_run_sdl_analysis = action

        action = pya.Action()
        action.title = "SDL / CAS User Manual..."
        action.on_triggered += lambda: self.show_user_manual()
        menu.insert_item(
            "tools_menu.connectivity_menu.end", "sdl_user_manual", action
        )
        self._menu_action_user_manual = action

        # add additional toolbar menu item to toggle flywire functionality
        
        action = pya.Action()
        action.title = "Flywire"
        action.tool_tip = "Show the Connectivity Inspection panel and Connectivity Overlay"
        action.icon = self.icon_path
        action.checkable = True
        action.checked = options.show_connectivity_info
        action.on_triggered += lambda a=action: self.toggle_connectivity_overlay(a)
        
        self._append_separator_if_needed(menu, "@toolbar.end", "connectivity_overlay_separator")
        menu.insert_item("@toolbar.end", "toggle_connectivity_overlay", action)
        self._toolbar_action_toggle_connectivity_overlay = action
        
    def _append_separator_if_needed(self,
                                    menu: pya.AbstractMenu,
                                    parent_path: str,
                                    separator_name: str):
        items = menu.items(parent_path)
        if items:
            last_item_path = f"{parent_path}.{items[-1]}"
            if menu.is_separator(last_item_path):
                return
    
        menu.insert_separator(f"{parent_path}.end", separator_name)        
        
    def update_menu(self, options: ConnectivityOptions):
        self._menu_action_show_connectivity_panel.checked = options.show_connectivity_panel
        self._menu_action_show_connectivity_info.checked = options.show_connectivity_info
        self._toolbar_action_toggle_connectivity_overlay.checked = options.show_connectivity_info
        
    def configure(self, name: str, value: str) -> bool:
        if name != CONFIG_KEY__CONNECTIVITY_OPTIONS:
            return False
            
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.configure: {name}")
            
        options = ConnectivityOptions.load()
        
        # Synchronize all visual representations of persisted state.
        self.update_menu(options)
        self.update_connectivity_panel(options)
    
        if self.layout is not None:
            self.refresh_connectivity_info()
            
        return True
    
    def setup(self, options: ConnectivityOptions):
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.setup")

        self.update_menu(options)

        if self.layout is None:
            return
        
        self.update_connectivity_panel(options)
        
        self.refresh_connectivity_info()   # TODO: figure when this must be updated and when not
        
    def stop(self):
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.stop")

        # TODO: hide all inspector dialogs
        if self.connectivity_browser_dialog:
            self.connectivity_browser_dialog.close()
            self.connectivity_browser_dialog = None

        if self.manual_dialog:
            self.manual_dialog.close()
            self.manual_dialog = None
        
        if self.setupDock:
            self.setupDock.hide()

    def show_user_manual(self):
        if self.manual_dialog is None:
            self.manual_dialog = SDLUserManualDialog(pya.MainWindow.instance())
        self.manual_dialog.show_section("cas")
        
    def toggle_connectivity_overlay(self, action: pya.Action):
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.toggle_connectivity_overlay: {action.checked}")
    
        options = ConnectivityOptions.load()
    
        if action.checked:
            # Activating the toolbar button presents both the panel and overlay.
            options.show_connectivity_panel = True
            options.show_connectivity_info = True
        else:
            # Deactivating it leaves the panel open, but hides the overlay.
            options.show_connectivity_info = False
    
        options.save()    
        
    def toggle_connectivity_panel(self, action: pya.Action):
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.toggle_connectivity_panel: {action.checked}")
        
        o = ConnectivityOptions.load()
        o.show_connectivity_panel = action.checked
        o.save()

    def hide_connectivity_panel(self):
        """Called e.g. if (x) is clicked on the panel"""
        
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.hide_connectivity_panel")
        
        o = ConnectivityOptions.load()
        o.show_connectivity_panel = False
        o.save()

    def update_connectivity_panel(self, options: ConnectivityOptions):
        if options.show_connectivity_panel:
            if not(self.setupDock):
                mw   = pya.Application.instance().main_window()
                self.setupDock = ConnectivitySetupDock(
                    self.refresh_connectivity_info,
                    self.open_connectivity_browser,
                    self.attach_sdl_source,
                    self.run_sdl_analysis,
                    self.hide_connectivity_panel,
                )
                mw.addDockWidget(pya.Qt_DockWidgetArea.RightDockWidgetArea, self.setupDock)
            self.setupDock.show()
            
            self.setupDock.update_ui_from_config(options)
        else:       
            if self.setupDock:
                self.setupDock.hide()
        
    def toggle_connectivity_info(self, action: pya.Action):
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.toggle_connectivity_info: {action.checked}")
        
        o = ConnectivityOptions.load()
        o.show_connectivity_info = action.checked
        o.save()
        
    def open_connectivity_browser(self):
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.open_connectivity_browser")
        
        try:
            cv = pya.CellView.active()
            if cv is None or cv.cell is None:
                qmessagebox_critical('Error', 'Connectivity Inspection failed', 'No layout open to inspect')
                return
                
            if self.conn_info is None:
                self.refresh_connectivity_info()  # updates self.conn_info
                
            if self.connectivity_browser_dialog is None:
                mw = pya.Application.instance().main_window()
                self.connectivity_browser_dialog = ConnectivityBrowserDialog(
                    mw,
                    refresh_callback=self.refresh_connectivity_info,
                    findings_selection_callback=self._apply_findings_selection,
                    analysis_callback=self.run_sdl_analysis,
                    source_callback=self.attach_sdl_source,
                    instance_selection_callback=self._focus_instance_info,
                )
            
            self.connectivity_browser_dialog.update_from_conn_info(self.conn_info)
            self._load_layout_sidecar_findings()
            self.update_markers_flywires()
            self.connectivity_browser_dialog.show()
            self.connectivity_browser_dialog.raise_()
            self.connectivity_browser_dialog.activateWindow()        
        except Exception as e:
            print("ConnectivityPluginFactory.open_connectivity_browser caught an exception", e)
            traceback.print_exc()        

    @staticmethod
    def _bool_api_value(owner, name: str) -> bool:
        value = getattr(owner, name, False)
        return bool(value() if callable(value) else value)

    def _technology_name(self) -> str:
        tech = self.tech
        if tech is None:
            return ""
        name = getattr(tech, "name", "")
        return str(name() if callable(name) else name)

    def _analysis_adapter(self) -> Optional[str]:
        return adapter_for_technology(
            self._technology_name(), os.environ.get("KLAYOUT_HOME", "")
        )

    def _saved_analysis_target(self, action: str):
        """Validate a stable on-disk target without ever saving it for the user."""
        cv = self.cell_view
        if cv is None or cv.cell is None:
            qmessagebox_critical(
                "Error", action + " failed", "No layout is open to analyze."
            )
            return None
        layout_filename = self._layout_filename()
        if not layout_filename or not os.path.isfile(layout_filename):
            qmessagebox_critical(
                "Save required",
                action + " was not started",
                "Save the layout as an OASIS file first. SDL reads that file in "
                "a separate read-only process and never writes its geometry.",
            )
            return None
        if self._bool_api_value(cv, "is_dirty"):
            qmessagebox_critical(
                "Save required",
                action + " was not started",
                "This layout has unsaved changes. Save it first so expected and "
                "observed connectivity refer to the same geometry. SDL itself "
                "will still run read-only and will not modify the OAS file.",
            )
            return None
        return cv, layout_filename

    def attach_sdl_source(self):
        """Attach .sch/SPICE expected connectivity without importing instances."""
        target = self._saved_analysis_target("Attach SDL Source")
        if target is None:
            return
        cv, layout_filename = target
        if self.sdl_analysis_process is not None and self.sdl_analysis_process.poll() is None:
            return
        if self.sdl_source_process is not None and self.sdl_source_process.poll() is None:
            return
        adapter = self._analysis_adapter()
        if adapter != "xh018":
            qmessagebox_critical(
                "Source attachment unavailable",
                "Attach SDL Source was not started",
                "Read-only source attachment for an existing layout is currently "
                "available for XH018 terminal-map projects. For SG13G2, use the "
                "SDL sidecar created by Netlist Import.",
            )
            return
        source = pya.QFileDialog.getOpenFileName(
            pya.MainWindow.instance(),
            "Attach SDL Source (layout remains read-only)",
            os.path.dirname(layout_filename),
            "Xschem / SPICE (*.sch *.spice *.spi *.cir *.cdl);;All Files (*)",
        )
        if isinstance(source, (tuple, list)):
            source = source[0] if source else ""
        if not source:
            return
        source = str(source)
        if not os.path.isfile(source):
            qmessagebox_critical(
                "Invalid source", "Attach SDL Source failed",
                "The selected schematic or netlist does not exist: " + source,
            )
            return
        script = find_source_attach_script()
        if script is None:
            qmessagebox_critical(
                "Missing source adapter", "Attach SDL Source failed",
                "The Netlist Import SDL source-attachment batch script was not "
                "found in this KLayout profile.",
            )
            return
        try:
            command = build_attach_source_command(
                script, layout_filename, str(cv.cell.name), source
            )
            self.sdl_source_log_path = layout_filename + ".sdl-attach.log"
            self.sdl_source_log = open(
                self.sdl_source_log_path, "w", encoding="utf-8"
            )
            self.sdl_source_process = subprocess.Popen(
                command, stdout=self.sdl_source_log, stderr=subprocess.STDOUT,
                close_fds=True,
            )
            self.sdl_source_target_path = layout_filename
        except Exception as error:
            if self.sdl_source_log is not None:
                self.sdl_source_log.close()
                self.sdl_source_log = None
            self.sdl_source_target_path = None
            qmessagebox_critical("Error", "Attach SDL Source failed", str(error))
            return
        if self.connectivity_browser_dialog is None:
            self.open_connectivity_browser()
        if self.connectivity_browser_dialog is not None:
            self.connectivity_browser_dialog.set_source_attaching(True)
            self.connectivity_browser_dialog.update_snapshot_status(
                "analyzing",
                "Attaching expected connectivity in a separate read-only batch "
                "process. No layout cells, instances or geometry will be changed.",
            )
        if self.setupDock is not None:
            self.setupDock.set_source_attaching(True)
        self.sdl_source_timer = pya.QTimer(
            pya.Application.instance().main_window()
        )
        self.sdl_source_timer.timeout.connect(self._poll_sdl_source_attach)
        self.sdl_source_timer.start(250)

    def _poll_sdl_source_attach(self):
        process = self.sdl_source_process
        if process is None or process.poll() is None:
            return
        exit_code = process.returncode
        if self.sdl_source_timer is not None:
            self.sdl_source_timer.stop()
            self.sdl_source_timer = None
        if self.sdl_source_log is not None:
            self.sdl_source_log.close()
            self.sdl_source_log = None
        self.sdl_source_process = None
        completed_target = self.sdl_source_target_path
        self.sdl_source_target_path = None
        if self.connectivity_browser_dialog is not None:
            self.connectivity_browser_dialog.set_source_attaching(False)
        if self.setupDock is not None:
            self.setupDock.set_source_attaching(False)
        if exit_code == 0:
            if completed_target == self._layout_filename():
                self.refresh_connectivity_info()
                print("SDL source attached read-only; browser refreshed")
            else:
                print(
                    "SDL source attached read-only for {}; active layout changed, "
                    "so its browser was not refreshed".format(completed_target)
                )
            return
        message = "Source attachment for {} exited with code {}. See {}".format(
            completed_target, exit_code, self.sdl_source_log_path
        )
        if completed_target == self._layout_filename():
            self.sdl_snapshot_state = ("error", message)
            if self.connectivity_browser_dialog is not None:
                self.connectivity_browser_dialog.update_snapshot_status(*self.sdl_snapshot_state)
        qmessagebox_critical("Error", "Attach SDL Source failed", message)

    def run_sdl_analysis(self):
        """Start technology-specific extraction/comparison in read-only batch."""
        target = self._saved_analysis_target("SDL Analysis")
        if target is None:
            return
        cv, layout_filename = target
        if self.sdl_source_process is not None and self.sdl_source_process.poll() is None:
            return
        if self.sdl_analysis_process is not None and self.sdl_analysis_process.poll() is None:
            if self.connectivity_browser_dialog is not None:
                self.connectivity_browser_dialog.raise_()
            return

        adapter = self._analysis_adapter()
        if adapter is None:
            qmessagebox_critical(
                "Unsupported technology", "SDL Analysis failed",
                "No SDL adapter matches technology '{}' in profile '{}'.".format(
                    self._technology_name() or "<unknown>",
                    os.environ.get("KLAYOUT_HOME", "<unknown>"),
                ),
            )
            return
        if adapter == "xh018" and not os.path.isfile(layout_filename + ".sdl.json"):
            qmessagebox_critical(
                "Expected connectivity required",
                "SDL Analysis was not started",
                "No SDL sidecar is attached to this XH018 layout. Click Attach "
                "SDL Source first and select the existing .sch or SPICE/CDL "
                "netlist. Attachment and analysis are read-only for the OAS file.",
            )
            return
        script = find_batch_script(adapter=adapter)
        if script is None:
            qmessagebox_critical(
                "Missing adapter",
                "SDL Analysis failed",
                "The Netlist Import {} batch adapter was not found in this "
                "KLayout profile.".format(adapter.upper()),
            )
            return
        try:
            command = build_sdl_command(
                script, layout_filename, str(cv.cell.name), adapter
            )
            self.sdl_analysis_log_path = layout_filename + ".sdl.log"
            self.sdl_analysis_log = open(self.sdl_analysis_log_path, "w", encoding="utf-8")
            self.sdl_analysis_process = subprocess.Popen(
                command,
                stdout=self.sdl_analysis_log,
                stderr=subprocess.STDOUT,
                close_fds=True,
            )
            self.sdl_analysis_target_path = layout_filename
        except Exception as error:
            if self.sdl_analysis_log is not None:
                self.sdl_analysis_log.close()
                self.sdl_analysis_log = None
            self.sdl_analysis_target_path = None
            qmessagebox_critical(
                "Error", "SDL Analysis failed", str(error)
            )
            return

        if self.connectivity_browser_dialog is None:
            self.open_connectivity_browser()
        if self.connectivity_browser_dialog is not None:
            self.connectivity_browser_dialog.set_analysis_running(True)
            self.connectivity_browser_dialog.update_snapshot_status(
                "analyzing",
                "{} extraction and comparison are running in a separate "
                "read-only process. The OAS layout will not be written; the "
                "browser will refresh automatically.".format(adapter.upper()),
            )
        if self.setupDock is not None:
            self.setupDock.set_analysis_running(True)
        self.sdl_analysis_timer = pya.QTimer(
            pya.Application.instance().main_window()
        )
        self.sdl_analysis_timer.timeout.connect(self._poll_sdl_analysis)
        self.sdl_analysis_timer.start(250)

    def run_sg13g2_sdl_analysis(self):
        """Compatibility alias retained for old menu scripts and runsets."""
        return self.run_sdl_analysis()

    def _poll_sdl_analysis(self):
        process = self.sdl_analysis_process
        if process is None or process.poll() is None:
            return
        exit_code = process.returncode
        if self.sdl_analysis_timer is not None:
            self.sdl_analysis_timer.stop()
            self.sdl_analysis_timer = None
        if self.sdl_analysis_log is not None:
            self.sdl_analysis_log.close()
            self.sdl_analysis_log = None
        self.sdl_analysis_process = None
        completed_target = self.sdl_analysis_target_path
        self.sdl_analysis_target_path = None
        if self.connectivity_browser_dialog is not None:
            self.connectivity_browser_dialog.set_analysis_running(False)
        if self.setupDock is not None:
            self.setupDock.set_analysis_running(False)
        if exit_code == 0:
            if completed_target == self._layout_filename():
                self.refresh_connectivity_info()
                print("SDL analysis completed; browser refreshed")
            else:
                print(
                    "SDL analysis completed for {}; active layout changed, so "
                    "its browser was not refreshed".format(completed_target)
                )
            return
        message = "Analysis for {} exited with code {}. See {}".format(
            completed_target, exit_code, self.sdl_analysis_log_path
        )
        if completed_target == self._layout_filename():
            self.sdl_snapshot_state = ("error", message)
            if self.connectivity_browser_dialog is not None:
                self.connectivity_browser_dialog.update_snapshot_status(*self.sdl_snapshot_state)
        qmessagebox_critical("Error", "SDL Analysis failed", message)

    def _poll_sg13g2_sdl_analysis(self):
        """Compatibility alias for an already scheduled legacy timer."""
        return self._poll_sdl_analysis()

    def _apply_findings_selection(self, selection: FindingSelection):
        """Cross-probe a browser multi-selection and update selected overlays."""
        self.active_finding_selection = selection
        self.findings_selection_adapter.apply(selection)
        self._apply_marker_emphasis(selection)
        try:
            mode = VisibilityMode(self.options.flight_lines_mode)
        except ValueError:
            mode = VisibilityMode.ALL_OPENS
        if mode in (
            VisibilityMode.SELECTED_NETS,
            VisibilityMode.SELECTED_PINS,
            VisibilityMode.SELECTED_INSTANCES,
        ):
            self.set_flight_lines_visibility(
                mode, selected_identifiers_for_mode(selection, mode)
            )

    def _focus_instance_info(self, instance_info):
        """Center, zoom and cross-probe an instance selected in either browser tab."""
        instance_id = self._normalized_target_identifier(
            instance_info.hierarchy_path or instance_info.inst_name
        )
        self.last_focused_instance_id = instance_id
        self._cross_probe_finding_targets((FindingTarget("instance", instance_id),))

        bbox = None
        for pin in instance_info.pin_infos:
            if pin.bbox.empty():
                continue
            bbox = pin.bbox if bbox is None else bbox + pin.bbox
        if bbox is None:
            bbox = getattr(instance_info, "sdl_placement_bbox", None)
        if bbox is None and self.layout is not None:
            try:
                if instance_info.inst is not None:
                    bbox = instance_info.inst.bbox().to_dtype(self.layout.dbu)
            except Exception:
                bbox = None
        if bbox is None or self.view is None:
            return
        self.last_focused_instance_bbox = (
            bbox.left, bbox.bottom, bbox.right, bbox.top
        )
        width = max(0.0, bbox.right - bbox.left)
        height = max(0.0, bbox.top - bbox.bottom)
        pad = max(width, height) * 0.5
        if pad <= 0.0:
            pad = 1.0
        self.view.zoom_box(pya.DBox(
            bbox.left - pad, bbox.bottom - pad, bbox.right + pad, bbox.top + pad
        ))
        try:
            self.view.update_content()
        except Exception:
            pass

    def _apply_marker_emphasis(self, selection: Optional[FindingSelection] = None):
        """Dim unrelated overlay markers while selected targets remain prominent."""
        selection = selection if selection is not None else self.active_finding_selection
        has_selection = bool(selection is not None and selection.findings)
        targets = () if selection is None else (
            tuple(selection.highlight_targets) + tuple(selection.cross_probe_targets)
        )
        emphasized_lines = set(
            emphasized_flight_line_ids(self.rendered_flight_lines, targets)
        ) if has_selection else set()

        stale_factor = 0.55 if self.sdl_live_dirty else 1.0
        bright_flight = dim_color(0xffff00, stale_factor)
        dim_flight = dim_color(bright_flight)
        for marker, line in zip(self.markers_flywires, self.rendered_flight_lines):
            marker.color = (
                bright_flight
                if not has_selection or line.line_id in emphasized_lines
                else dim_flight
            )

        base_terminal = dim_color(0xff0000, stale_factor)
        terminal_color = dim_color(base_terminal) if has_selection else base_terminal
        for marker in self.markers_terminals:
            marker.color = terminal_color
            marker.frame_color = terminal_color

        base_instance = dim_color(0xffffff, stale_factor)
        instance_color = dim_color(base_instance) if has_selection else base_instance
        for marker in self.markers_instance_names:
            marker.color = instance_color
            marker.frame_color = instance_color
        try:
            if self.view is not None:
                self.view.update_content()
        except Exception:
            pass
        
    def on_current_view_changed(self):
        if Debugging.DEBUG:
             debug(f"ConnectivityPluginFactory.on_current_view_changed, self.view={self.view}")
             debug(f"ConnectivityPluginFactory.on_current_view_changed, self.view={self.view}, "
                   f"active cell name={'none' if self.cell_view is None else self.cell_view.cell_name}")

        if self.view is None:
            return

        try:
            if self.layout is None:
                if not self._waiting_for_file_open:
                    if Debugging.DEBUG:
                        debug(
                            "ConnectivityPluginFactory.on_current_view_changed: "
                            "waiting for a layout file"
                        )
            
                    self.view.on_file_open.connect(self._on_file_open)
                    self._waiting_for_file_open = True
                return
            else:
                self.layout_changed()
        except Exception as e:
            print("ConnectivityPluginFactory.on_current_view_changed caught an exception", e)
            traceback.print_exc()
        
    def _on_file_open(self):
        if self.view is not None and self._waiting_for_file_open:
            self.view.on_file_open.disconnect(self._on_file_open)
    
        self._waiting_for_file_open = False
        self.layout_changed()
        
    def on_view_created(self):
        if Debugging.DEBUG:
             debug(f"ConnectivityPluginFactory.on_view_created, self.view={self.view}, "
                   f"active cell name={'none' if self.cell_view is None else self.cell_view.cell_name}")

        # NOTE: sometimes when starting klayout -e directly with a layout file
        #       on_current_view_changed won't get emitted
        try:
            options = ConnectivityOptions.load()
            
            mw = pya.MainWindow.instance()
            menu = mw.menu()
            if not menu.is_menu("tools_menu.connectivity_menu"):
                if Debugging.DEBUG:
                    debug(f"ConnectivityPluginFactory.on_view_created, no menu found yet, "
                          f"seems we are in a startup situation, "
                          f"so we'll create the menu now")
                self.init_menu(options)

            self.setup(options)
        except Exception as e:
            print("ConnectivityPluginFactory.on_view_created caught an exception", e)
            traceback.print_exc()        

    def on_view_closed(self):
        if Debugging.DEBUG:
             debug("ConnectivityPluginFactory.on_view_closed")
      
    def layout_changed(self):
        if Debugging.DEBUG:
            cell_view = self.cell_view
            debug(f"ConnectivityPluginFactory.layout_changed, "
                  f"for cell view {cell_view.cell_name if cell_view else 'none'}")
        
        if self.view is None or self.layout is None:
            return
        
        try:
            options = ConnectivityOptions.load()
            self.setup(options)
        except Exception as e:
            print("ConnectivityPluginFactory.layout_changed caught an exception", e)
            traceback.print_exc()        

    def update(self):
        """
        Gets called when the visible rectangle has changed, 
        i.e. after zooming in or out or panning.
        """
        cv = self.cell_view
        live_dirty = bool(cv is not None and self._bool_api_value(cv, "is_dirty"))
        if live_dirty and not self.sdl_live_dirty:
            self.sdl_live_dirty = True
            self.sdl_snapshot_state = (
                "stale",
                "The layout has unsaved changes. The dimmed overlay is the last "
                "saved SDL result; save the OAS and run SDL Analysis to update it.",
            )
            if self.connectivity_browser_dialog is not None:
                self.connectivity_browser_dialog.update_snapshot_status(
                    *self.sdl_snapshot_state
                )
        elif not live_dirty and self.sdl_live_dirty:
            self.sdl_live_dirty = False
            self.refresh_connectivity_info()
            return
        self.update_markers()
            
    def _clear_all_markers(self):
        self._clear_markers_flywires()
        self._clear_markers_terminals()
        self._clear_markers_instance_names()
        self._clear_markers_findings()
        
    def _clear_markers_field(self, attr: str):
        markers = getattr(self, attr)
        for marker in markers:
            marker._destroy()
        setattr(self, attr, [])

    def _clear_markers_flywires(self):
        # Keep marker ownership in the testable seam so refreshes cannot leave
        # stale lines behind (including when a fixed OPEN disappears).
        self.flight_line_marker_seam.render(())
        self.markers_flywires = []

    def _clear_markers_terminals(self):
        self._clear_markers_field('markers_terminals')

    def _clear_markers_instance_names(self):
        self._clear_markers_field('markers_instance_names')

    def _clear_markers_findings(self):
        self._clear_markers_field('markers_findings')

    def refresh_connectivity_info(self):
        cv = pya.CellView.active()
        if cv is None or cv.cell is None:
            qmessagebox_critical('Error', 'Connectivity Inspection failed', 'No layout open to analyze')
            return
        
        has_pcell, has_static_info = self._layout_instance_kinds()
        if has_pcell:
            self.conn_info = LayoutConnectivityInfo.for_layout_view(self.view)
        else:
            # KLayoutPluginUtils expands every occurrence while looking for
            # PCells.  Streamed project layouts can contain hundreds of
            # thousands of repeated static occurrences, so prove there are no
            # PCell definitions first and avoid freezing the editor.
            top_cell = self.cell_view.cell
            self.conn_info = LayoutConnectivityInfo(cell_infos=[
                CellConnectivityInfo(cell=top_cell, cell_name=top_cell.name)
            ])
        if has_static_info:
            self._include_static_cell_connectivity_info(self.conn_info)

        # Load the public snapshot before painting.  This also resets the
        # cached lines when a previously reported OPEN was fixed.
        self._load_layout_sidecar_findings()
        self._include_snapshot_pin_infos(self.conn_info)
        self._include_sidecar_connectivity_info(self.conn_info)
        
        self.update_markers()
        
        if self.connectivity_browser_dialog is not None and self.connectivity_browser_dialog.isVisible():
            self.connectivity_browser_dialog.update_from_conn_info(self.conn_info)

    def _layout_instance_kinds(self) -> Tuple[bool, bool]:
        """Inspect hierarchy definitions once, without expanding occurrences."""
        has_pcell = False
        has_static_info = False
        if self.layout is None:
            return has_pcell, has_static_info
        for cell in self.layout.each_cell():
            for inst in cell.each_inst():
                if inst.is_pcell():
                    has_pcell = True
                elif any(inst.property(key) is not None for key in _INSTANCE_INFO_KEYS):
                    has_static_info = True
                if has_pcell and has_static_info:
                    return has_pcell, has_static_info
        return has_pcell, has_static_info

    def _include_static_cell_connectivity_info(self, conn_info: LayoutConnectivityInfo):
        """Add imported/static instances carrying INSTANCE_INFO__* metadata.

        KLayoutPluginUtils currently collects only ``inst.is_pcell()``.  Its
        ``CellInstanceConnectivityInfo.for_instance`` parser itself works for
        both PCells and ordinary cells, so append only the latter here and
        preserve the existing PCell records unchanged.
        """
        if not conn_info.cell_infos or self.view is None or self.cell_view is None:
            return
        top_cell = self.cell_view.cell
        if top_cell is None:
            return
        target = conn_info.cell_infos[0].pcell_infos
        ctx = Context(layout_view=self.view)
        iterator = top_cell.begin_instances_rec()
        while not iterator.at_end():
            inst = iterator.current_inst_element().inst()
            hidden = self.view.is_cell_hidden(inst.cell.cell_index(), self.view.active_cellview_index)
            static_has_instance_info = any(
                inst.property(key) is not None for key in _INSTANCE_INFO_KEYS
            )
            if not hidden and not inst.is_pcell() and static_has_instance_info:
                info = CellInstanceConnectivityInfo.for_instance(inst, iterator.inst_trans(), ctx)
                if info is not None:
                    self._include_static_label_pin_infos(
                        info, inst, iterator.inst_trans()
                    )
                    target.append(info)
            iterator.next()

    def _include_static_label_pin_infos(self, info, inst, outer_trans):
        """Expose preserved static-cell terminal labels as inspector pins.

        Static XH018 cells have no PCell ``PIN_INFO`` polygons, but their GDS
        contains terminal text.  Match only labels named in the importer's
        local pin map and transform them to top coordinates.  This keeps the
        inspector technology-neutral and avoids inventing unnamed pins.
        """
        if info.pin_infos or not info.local_net_map or self.layout is None:
            return
        wanted = {str(name).casefold(): str(name) for name in info.local_net_map}
        iterator = pya.RecursiveShapeIterator(
            self.layout, inst.cell, self.layout.layer_indexes()
        )
        while not iterator.at_end():
            shape = iterator.shape()
            if shape.is_text():
                label = shape.text.string.strip()
                pin_name = wanted.get(label.casefold())
                if pin_name is not None:
                    full_trans = outer_trans * iterator.itrans()
                    bbox = shape.bbox().transformed(full_trans).to_dtype(
                        self.layout.dbu
                    )
                    if bbox.empty():
                        position = (full_trans * shape.text.trans).disp.to_dtype(
                            self.layout.dbu
                        )
                        bbox = pya.DBox(
                            position.x - 0.05, position.y - 0.05,
                            position.x + 0.05, position.y + 0.05,
                        )
                    info.pin_infos.append(PinInfo(
                        name=pin_name,
                        term_name=pin_name,
                        bbox=bbox,
                        layers=[self.layout.get_info(iterator.layer())],
                    ))
            iterator.next()

    def _layout_filename(self) -> Optional[str]:
        """Read a CellView filename across KLayout binding versions."""
        cv = self.cell_view
        if cv is None:
            return None
        for owner in (cv, cv.layout()):
            value = getattr(owner, "filename", None)
            if callable(value):
                value = value()
            if value:
                return str(value)
        return None

    def _load_layout_sidecar_findings(self):
        """Refresh findings and open-only flight-lines from ``<layout>.sdl.json``."""
        layout_filename = self._layout_filename()
        if not layout_filename:
            self.sdl_flight_lines = ()
            self.sdl_pin_access_points = ()
            self.sdl_snapshot_state = (
                "missing", "Save the layout as OAS before running SDL analysis."
            )
            if self.connectivity_browser_dialog is not None:
                self.connectivity_browser_dialog.update_findings(())
                self.connectivity_browser_dialog.update_snapshot_status(*self.sdl_snapshot_state)
            return
        try:
            state = snapshot_state_for_layout(layout_filename)
            findings = load_findings_for_layout(layout_filename)
            flight_lines = load_flight_lines_for_layout(layout_filename)
            pin_access_points = load_pin_access_for_layout(layout_filename)
            disk_result_ready = state.kind == "ready"
            self.sdl_live_dirty = bool(
                disk_result_ready
                and self.cell_view is not None
                and self._bool_api_value(self.cell_view, "is_dirty")
            )
            if self.sdl_live_dirty:
                state = SnapshotState(
                    "stale",
                    "The layout has unsaved changes. The dimmed overlay is the "
                    "last saved SDL result; save the OAS and run SDL Analysis "
                    "to update it.",
                )
            elif not disk_result_ready:
                # Findings remain reviewable, but stale geometry must not
                # guide routing or terminal cross-probing.
                flight_lines = ()
                pin_access_points = ()
        except FileNotFoundError:
            findings = ()
            flight_lines = ()
            pin_access_points = ()
            state = SnapshotState("missing", "No SDL sidecar was found for this layout.")
        except SnapshotFormatError as error:
            print("Connectivity SDL sidecar ignored: {}".format(error))
            findings = ()
            flight_lines = ()
            pin_access_points = ()
            state = SnapshotState(
                "error", "The SDL sidecar is invalid: {}".format(error)
            )
        self.sdl_flight_lines = flight_lines
        self.sdl_pin_access_points = pin_access_points
        self.sdl_snapshot_state = (state.kind, state.message)
        if self.connectivity_browser_dialog is not None:
            self.connectivity_browser_dialog.update_findings(findings)
            self.connectivity_browser_dialog.update_snapshot_status(*self.sdl_snapshot_state)

    def _include_snapshot_pin_infos(self, conn_info: LayoutConnectivityInfo) -> None:
        """Feed adapter access points into By Net/By Instance pages."""
        if not self.sdl_pin_access_points:
            return
        points_by_instance: Dict[str, List[Any]] = {}
        for access in self.sdl_pin_access_points:
            instance_id, separator, _pin = access.pin_id.rpartition("/")
            if separator:
                points_by_instance.setdefault(
                    self._normalized_target_identifier(instance_id), []
                ).append(access)
        for cell in conn_info.cell_infos:
            for info in cell.pcell_infos:
                instance_id = self._normalized_target_identifier(
                    info.hierarchy_path or info.inst_name
                )
                if instance_id not in points_by_instance and self.layout is not None:
                    # Some OAS readers preserve PCell geometry but not custom
                    # properties on the instance object.  Recover the stable
                    # path by the import-time/adapter bbox; require uniqueness
                    # so repeated or transformed hierarchy is never guessed.
                    box = info.inst.bbox()
                    scale = float(self.layout.dbu)
                    info_bbox = (
                        float(box.left) * scale, float(box.bottom) * scale,
                        float(box.right) * scale, float(box.top) * scale,
                    )
                    candidates = []
                    for candidate_id, accesses in points_by_instance.items():
                        access_bbox = accesses[0].bbox
                        if all(abs(left - right) <= 1e-6
                               for left, right in zip(info_bbox, access_bbox)):
                            candidates.append(candidate_id)
                    if len(candidates) == 1:
                        instance_id = candidates[0]
                        info.hierarchy_path = instance_id.replace("/", ".")
                known = {str(pin.name) for pin in info.pin_infos}
                for access in points_by_instance.get(instance_id, ()):
                    pin_name = access.pin_id.rsplit("/", 1)[-1]
                    if pin_name in known:
                        continue
                    x, y = access.point
                    radius = 0.02
                    info.pin_infos.append(PinInfo(
                        name=pin_name,
                        term_name=pin_name,
                        bbox=pya.DBox(x - radius, y - radius, x + radius, y + radius),
                        layers=[],
                    ))
                    known.add(pin_name)

    def _include_sidecar_connectivity_info(
        self, conn_info: LayoutConnectivityInfo
    ) -> None:
        """Merge source graph rows into the Browser without touching layout.

        Frozen XH018 streams commonly have neither PCells nor importer-owned
        ``INSTANCE_INFO__*`` properties.  The SDL sidecar is the source of
        truth for their logical instance/pin/net graph.  Physical access
        points and placement boxes are presentation hints only.
        """
        if not conn_info.cell_infos:
            return
        layout_filename = self._layout_filename()
        if not layout_filename:
            return
        try:
            records = load_browser_instances_for_layout(layout_filename)
        except FileNotFoundError:
            return
        except SnapshotFormatError as error:
            print("Connectivity SDL browser graph ignored: {}".format(error))
            return

        target = conn_info.cell_infos[0].pcell_infos
        existing: Dict[str, CellInstanceConnectivityInfo] = {}
        for info in target:
            identifier = self._normalized_target_identifier(
                info.hierarchy_path or info.inst_name
            )
            if identifier:
                existing.setdefault(identifier, info)

        for record in records:
            identifier = self._normalized_target_identifier(record.instance_id)
            info = existing.get(identifier)
            if info is None:
                info = CellInstanceConnectivityInfo(
                    inst=None,
                    inst_name=record.instance_name,
                    cell_name=record.layout_master or record.source_master,
                    lib_name=record.layout_library or None,
                    hierarchy_path=record.instance_id.replace("/", "."),
                    netlist_cell_name=record.source_master or None,
                    netlist_lib_name=None,
                    local_net_map={pin.name: pin.net for pin in record.pins},
                    global_net_map={pin.name: pin.net for pin in record.pins},
                )
                target.append(info)
                existing[identifier] = info
            else:
                # Sidecar net names are authoritative expected connectivity;
                # preserve any richer layout/PCell identity and geometry.
                info.local_net_map.update(
                    {pin.name: pin.net for pin in record.pins}
                )
                info.global_net_map.update(
                    {pin.name: pin.net for pin in record.pins}
                )

            if record.placement_bbox is not None:
                info.sdl_placement_bbox = pya.DBox(*record.placement_bbox)

            known = {str(pin.name) for pin in info.pin_infos}
            for record_pin in record.pins:
                if record_pin.name in known:
                    continue
                has_geometry = record_pin.bbox is not None
                bbox = (
                    pya.DBox(*record_pin.bbox)
                    if has_geometry else pya.DBox()
                )
                if has_geometry and bbox.empty() and record_pin.point is not None:
                    x, y = record_pin.point
                    radius = 0.02
                    bbox = pya.DBox(
                        x - radius, y - radius, x + radius, y + radius
                    )
                pin = PinInfo(
                    name=record_pin.name,
                    term_name=record_pin.name,
                    bbox=bbox,
                    layers=[],
                )
                info.pin_infos.append(pin)
                known.add(record_pin.name)

    def _zoom_to_finding_bbox(self, bbox: BoundingBox):
        """Zoom the current view to the union box supplied by FindingsModel."""
        if self.view is None:
            return
        width = max(0.0, bbox.right - bbox.left)
        height = max(0.0, bbox.top - bbox.bottom)
        pad = max(width, height) * 0.15
        if pad <= 0.0:
            pad = 1.0
        self.view.zoom_box(pya.DBox(
            bbox.left - pad, bbox.bottom - pad, bbox.right + pad, bbox.top + pad
        ))

    @staticmethod
    def _normalized_target_identifier(identifier: str) -> str:
        return str(identifier).strip().strip("/").replace(".", "/")

    def _highlight_finding_targets(self, targets: Tuple[FindingTarget, ...]):
        """Draw highlight boxes for pin/instance targets resolvable in layout."""
        self._clear_markers_findings()
        if self.conn_info is None:
            return
        wanted = {(target.target_type, self._normalized_target_identifier(target.identifier))
                  for target in targets}
        seen = set()
        for cell in self.conn_info.cell_infos:
            for instance_info in cell.pcell_infos:
                instance_id = self._normalized_target_identifier(
                    instance_info.hierarchy_path or instance_info.inst_name
                )
                instance_wanted = ("instance", instance_id) in wanted
                drew_instance = False
                for pin in instance_info.pin_infos:
                    pin_id = "{}/{}".format(instance_id, self._normalized_target_identifier(pin.name))
                    if not instance_wanted and ("pin", pin_id) not in wanted:
                        continue
                    if pin.bbox.empty():
                        continue
                    key = (pin.bbox.left, pin.bbox.bottom, pin.bbox.right, pin.bbox.top)
                    if key in seen:
                        continue
                    seen.add(key)
                    marker = self._box_marker(pin.bbox)
                    marker.line_width = 4
                    marker.color = 0xffff00
                    self.markers_findings.append(marker)
                    drew_instance = True
                placement_bbox = getattr(instance_info, "sdl_placement_bbox", None)
                if instance_wanted and not drew_instance and placement_bbox is not None:
                    key = (
                        placement_bbox.left, placement_bbox.bottom,
                        placement_bbox.right, placement_bbox.top,
                    )
                    if key not in seen:
                        seen.add(key)
                        marker = self._box_marker(placement_bbox)
                        marker.line_width = 4
                        marker.color = 0xffff00
                        self.markers_findings.append(marker)

    def _cross_probe_finding_targets(self, targets: Tuple[FindingTarget, ...]):
        """Select layout instances for SDL instance/pin targets in KLayout."""
        if self.view is None or self.cell_view is None or self.cell_view.cell is None:
            return
        instance_ids = set()
        for target in targets:
            if target.target_type == "instance":
                instance_ids.add(self._normalized_target_identifier(target.identifier))
            elif target.target_type == "pin":
                parts = self._normalized_target_identifier(target.identifier).rsplit("/", 1)
                if len(parts) == 2:
                    instance_ids.add(parts[0])
        paths = []
        iterator = self.cell_view.cell.begin_instances_rec()
        while not iterator.at_end():
            inst = iterator.current_inst_element().inst()
            hierarchy_path = inst.property(PROPERTY_KEY__INSTANCE_INFO__HIERARCHY_PATH)
            if hierarchy_path in (None, "") and self.conn_info is not None:
                # OAS can drop custom instance properties while retaining the
                # PCell instance itself.  _include_snapshot_pin_infos already
                # restores the stable hierarchy path on the corresponding
                # connectivity record; reuse that association for selection.
                for cell_info in self.conn_info.cell_infos:
                    matching = []
                    for info in cell_info.pcell_infos:
                        # Sidecar-only records intentionally have no live
                        # pya.Instance handle.  KLayout raises instead of
                        # returning False when a real Instance is compared
                        # with that null direct-reference value.
                        info_inst = getattr(info, "inst", None)
                        if info_inst is None or not info.hierarchy_path:
                            continue
                        try:
                            same_instance = info_inst == inst
                        except RuntimeError:
                            same_instance = False
                        if same_instance:
                            matching.append(info)
                    if len(matching) == 1:
                        hierarchy_path = matching[0].hierarchy_path
                        break
            instance_id = self._normalized_target_identifier(hierarchy_path or inst.cell.name)
            if instance_id in instance_ids:
                # Build the instance path with append_path.  Assigning the
                # raw ``path`` list creates an invalid primary selection in
                # KLayout 0.30 and opens a modal "does not contain polygons"
                # error instead of cross-probing the instance.
                object_path = pya.ObjectInstPath()
                object_path.cv_index = self.view.active_cellview_index
                for element in list(iterator.path()) + [iterator.current_inst_element()]:
                    object_path.append_path(element)
                paths.append(object_path)
            iterator.next()
        self.view.object_selection = paths
        try:
            self.view.update_content()
        except Exception:
            pass
        
    def update_markers(self):
        self.update_markers_flywires()
        self.update_markers_terminals()
        self.update_markers_instance_names()
        self._apply_marker_emphasis()

    def _text_marker(self, 
                     text: str, 
                     position: pya.DPoint, 
                     size: float = 12.0, 
                     text_color: int = 0xffffff,
                     frame_color: int = 0xff0000,
                     halign: pya.HAlign = pya.HAlign.HAlignCenter,
                     valign: pya.VAlign = pya.VAlign.VAlignCenter) -> pya.Marker:
        m = pya.Marker(self.view)
        dtext = pya.DText(text, position.x, position.y)
        dtext.halign = halign
        dtext.valign = valign
        
        # NOTE: size only works for font numbers >= 1
        ### dtext.size = self.viewport_adjust(size / 10-6)
        
        # 0 … default font (non scaled)
        # 1 … gothic
        # 2 … sans-serif #1
        # 3 … sans-serif #2
        # 4 … italic
        # 5 … times
        dtext.font = 0
        
        m.set(dtext)
        
        m.color = text_color  # text color (white)
        
        # m.text_frame_enabled = False  # frame around text
        m.text_frame_enabled = True # frame around text
        m.halo = 1  # -1 (default) / 0 (disable) / 1 (enable)
        
        m.frame_color = frame_color  # frame
        
        m.dither_pattern = 0  # default: 0==solid
        
        m.line_width = 14  # draw point at text anchor / max 14
        m.line_style = 1  # has no effect here | 0 = solid / 1 == dashed / …
        # if line_width == 1, the line style can be configured
        
        m.vertex_size = 0 # 8  # NOTE: not relevant for text
        
        return m
        
    def _line_marker(self, edge: pya.DEdge) -> pya.Marker:
        m = pya.Marker(self.view)
        m.line_style     = 1   # dashed, to distinguish from selection markers
        m.line_width     = 1
        m.vertex_size    = 0
        m.dither_pattern = 1
        m.set(edge)
        return m
    
    def _box_marker(self, box: pya.DBox):
        m = pya.Marker(self.view)
        m.line_style = 2
        m.line_width = 1
        m.vertex_size = 0
        m.dither_pattern = -1
        m.set(box)

        return m
        
    def update_markers_flywires(self):
        self._clear_markers_flywires()
        self.rendered_flight_lines = ()
        opts = self.options
        if not opts.show_connectivity_info:
            return
        if not opts.show_flywires:
            return
        try:
            self.flight_lines_mode = VisibilityMode(opts.flight_lines_mode)
        except ValueError:
            self.flight_lines_mode = VisibilityMode.ALL_OPENS
        lines = visible_flight_lines(
            self.sdl_flight_lines,
            self.flight_lines_mode,
            self.flight_lines_selected,
        )
        self.rendered_flight_lines = tuple(lines)
        self.markers_flywires = list(self.flight_line_marker_seam.render(lines))
        self._apply_marker_emphasis()

    def _create_flight_line_marker(self, start, end):
        return self._line_marker(pya.DEdge(pya.DPoint(*start), pya.DPoint(*end)))

    @staticmethod
    def _destroy_flight_line_marker(marker):
        marker._destroy()

    def set_flight_lines_visibility(self, mode: VisibilityMode, selected=()):
        """Set a snapshot overlay mode and immediately refresh its markers.

        This small method is the UI seam: browser controls can pass selected
        net, pin, or instance IDs without coupling the pure filter to Qt.
        """
        self.flight_lines_mode = VisibilityMode(mode)
        self.flight_lines_selected = tuple(selected)
        # Keep the mode consistent with update_markers_flywires(), which reads
        # persisted panel options on every refresh.  Without this write an API
        # request for Selected Nets/Pins/Instances was immediately overwritten
        # by the previous combo-box value.
        options = self.options
        options.flight_lines_mode = self.flight_lines_mode.value
        options.save()
        self.update_markers_flywires()

    def update_markers_terminals(self):
        self._clear_markers_terminals()

        opts = self.options
        if not opts.show_connectivity_info:
            return
        if not opts.show_terminals:
            return
        
        for cell in self.conn_info.cell_infos:
            # TODO: paint marker box around cell
            for pcell in cell.pcell_infos:
                for pin in pcell.pin_infos:
                    if pin.bbox.empty():
                        continue
                    m = self._box_marker(pin.bbox)
                    m.line_width = 3
                    m.color = 0xff0000

                    label_pos = pin.bbox.center()
                    tm = self._text_marker(pin.term_name, label_pos)
                    tm.line_width = 3
                    tm.color = 0xff0000

                    self.markers_terminals += [m, tm]
        self._apply_marker_emphasis()

    def update_markers_instance_names(self):
        self._clear_markers_instance_names()

        opts = self.options
        if not opts.show_connectivity_info:
            return
        if not opts.show_instance_names:
            return
        
        for cell in self.conn_info.cell_infos:
            for pcell in cell.pcell_infos:
                # Place the instance name label above the union bbox of
                # all this instance's pins (a reasonable proxy for "top
                # of the device", since we don't have the full device
                # bbox tracked separately in PCellInstanceConnectivityInfo).
                union_box = None
                for pin in pcell.pin_infos:
                    if pin.bbox.empty():
                        continue
                    union_box = pin.bbox if union_box is None else union_box + pin.bbox

                if union_box is None:
                    union_box = getattr(pcell, "sdl_placement_bbox", None)
                if union_box is None:
                    continue

                INSTANCE_NAME_Y_GAP_UM = 0.1
                label_pos = pya.DPoint(union_box.center().x, union_box.top + INSTANCE_NAME_Y_GAP_UM)

                # FQ instance name: the netlist importer's hierarchy path
                # (e.g. "top.X3.X1"); fall back to the local instance name
                # for layouts imported before this property existed.
                fq_inst_name = pcell.hierarchy_path or pcell.inst_name

                # FQ cell name: prefer the schematic/netlist device name
                # (INSTANCE_INFO__CELL_NAME / __LIB_NAME, e.g. "sg13_lv.nmos"
                # as it appears in xschem), since that's what a designer
                # recognizes -- not the PCell's PDK-internal name. Fall back
                # to the PCell name for layouts imported before these
                # properties existed.
                if pcell.netlist_cell_name:
                    fq_cell_name = (f"{pcell.netlist_lib_name}.{pcell.netlist_cell_name}"
                                     if pcell.netlist_lib_name else pcell.netlist_cell_name)
                else:
                    fq_cell_name = f"{pcell.lib_name}.{pcell.cell_name}" if pcell.lib_name else pcell.cell_name
                
                label = f"{fq_inst_name} ({fq_cell_name})"
                tm = self._text_marker(label, label_pos, 
                                       text_color=0xffffff, frame_color=0xffffff,
                                       halign=pya.HAlign.HAlignCenter, valign=pya.VAlign.VAlignBottom)
                self.markers_instance_names.append(tm)        
        self._apply_marker_emphasis()

    def viewport_adjust(self, v: int) -> int:
        trans = pya.CplxTrans(self.view.viewport_trans(), self.dbu)
        return v / trans.mag

#--------------------------------------------------------------------------------

def on_current_view_changed():
    try:
        if Debugging.DEBUG:
            debug(f"ConnectivityInspectionPlugin (GLOBAL) on_current_view_changed")
        inst = ConnectivityPluginFactory.instance
        EventLoop.defer(inst.on_current_view_changed)
    except Exception as e:
        print("ConnectivityInspectionPlugin (GLOBAL) on_current_view_changed caught an exception", e)
        traceback.print_exc()
    
def on_view_created():
    try:
        if Debugging.DEBUG:
            debug("ConnectivityInspectionPlugin (GLOBAL) on_view_created")
        inst = ConnectivityPluginFactory.instance
        EventLoop.defer(inst.on_view_created)
    except Exception as e:
        print("ConnectivityInspectionPlugin (GLOBAL) on_view_created caught an exception", e)
        traceback.print_exc()


def on_view_closed():
    try:
      if Debugging.DEBUG:
          debug("ConnectivityInspectionPlugin (GLOBAL) on_view_closed")
      inst = ConnectivityPluginFactory.instance
      EventLoop.defer(inst.on_view_closed)
    except Exception as e:
        print("ConnectivityInspectionPlugin (GLOBAL) on_view_closed caught an exception", e)
        traceback.print_exc()


#--------------------------------------------------------------------------------

# NOTE: need to keep an instance currently.
# (will be fixed in 0.30.4, so we can pull a temporary instance)
mw = pya.MainWindow.instance()

mw.on_current_view_changed += on_current_view_changed
mw.on_view_created += on_view_created
mw.on_view_closed += on_view_closed
