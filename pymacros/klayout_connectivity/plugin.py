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
    load_findings_for_layout,
    load_flight_lines_for_layout,
    load_pin_access_for_layout,
    snapshot_state_for_layout,
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
                 hide_callback: Callable):
        super().__init__()
        self.setupWidget = ConnectivitySetupWidget(refresh_callback, 
                                                   open_connectivity_browser_callback,
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
        
        
class ConnectivitySetupWidget(pya.QWidget):
    def __init__(self, 
                 refresh_callback: Callable,
                 open_connectivity_browser_callback: Callable, 
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

        for cbx in (
            self.page.show_connectivity_cbx,
            self.page.show_flywires_cbx,
            self.page.show_instance_names_cbx,
            self.page.show_terminals_cbx,
        ):
            cbx.toggled(self.save_config)        
        self.page.flight_lines_mode_cb.currentIndexChanged(self.save_config)
         
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
                self.setupDock = ConnectivitySetupDock(self.refresh_connectivity_info, self.open_connectivity_browser, self.hide_connectivity_panel)
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

    def _apply_findings_selection(self, selection: FindingSelection):
        """Cross-probe a browser multi-selection and update selected overlays."""
        self.findings_selection_adapter.apply(selection)
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
        self.update_markers_terminals()
        self.update_markers_instance_names()
            
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
            if state.kind != "ready":
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
        """Feed SG13G2 adapter access points into By Net/By Instance pages."""
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
                for pin in instance_info.pin_infos:
                    pin_id = "{}/{}".format(instance_id, self._normalized_target_identifier(pin.name))
                    if not instance_wanted and ("pin", pin_id) not in wanted:
                        continue
                    key = (pin.bbox.left, pin.bbox.bottom, pin.bbox.right, pin.bbox.top)
                    if key in seen:
                        continue
                    seen.add(key)
                    marker = self._box_marker(pin.bbox)
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
                    matching = [
                        info for info in cell_info.pcell_infos
                        if info.inst == inst and info.hierarchy_path
                    ]
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
        self.markers_flywires = list(self.flight_line_marker_seam.render(lines))

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
                    m = self._box_marker(pin.bbox)
                    m.line_width = 3
                    m.color = 0xff0000

                    label_pos = pin.bbox.center()
                    tm = self._text_marker(pin.term_name, label_pos)
                    tm.line_width = 3
                    tm.color = 0xff0000

                    self.markers_terminals += [m, tm]

    def update_markers_instance_names(self):
        self._clear_markers_instance_names()

        opts = self.options
        if not opts.show_connectivity_info:
            return
        if not opts.show_instance_names:
            return
        
        for cell in self.conn_info.cell_infos:
            for pcell in cell.pcell_infos:
                if not pcell.pin_infos:
                    continue

                # Place the instance name label above the union bbox of
                # all this instance's pins (a reasonable proxy for "top
                # of the device", since we don't have the full device
                # bbox tracked separately in PCellInstanceConnectivityInfo).
                union_box = None
                for pin in pcell.pin_infos:
                    union_box = pin.bbox if union_box is None else union_box + pin.bbox

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
