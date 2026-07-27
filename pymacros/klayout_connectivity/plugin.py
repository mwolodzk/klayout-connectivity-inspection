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

from dataclasses import dataclass
import os 
import math
import sys
import traceback
from typing import *

import pya

from klayout_plugin_utils.debugging import debug, Debugging
from klayout_plugin_utils.editor_options import EditGridKind
from klayout_plugin_utils.event_loop import EventLoop
from klayout_plugin_utils.layout_connectivity_info import LayoutConnectivityInfo
from klayout_plugin_utils.str_enum_compat import StrEnum
from klayout_plugin_utils.tech_helpers import drc_tech_grid_um

from klayout_connectivity.options import ConnectivityOptions, CONFIG_KEY__CONNECTIVITY_OPTIONS

#--------------------------------------------------------------------------------

path_containing_this_script = os.path.realpath(os.path.dirname(__file__))

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

        self.page.show_connectivity_cbx.clicked(self.save_config)
        self.page.open_connectivity_browser_pb.clicked(open_connectivity_browser_callback)
         
        self.page.show_flywires_cbx.stateChanged(self.save_config)
        self.page.show_instance_names_cbx.stateChanged(self.save_config)
        self.page.show_terminals_cbx.stateChanged(self.save_config)
        self.page.refresh_pb.clicked(refresh_callback)
         
    def hideEvent(self, event):
        self.hide_callback()
        event.accept()
        
    def update_ui_from_config(self, config: ConnectivityOptions):
        self.page.show_connectivity_cbx.setChecked(config.show_connectivity_info)
        self.page.show_flywires_cbx.setChecked(config.show_flywires)
        self.page.show_instance_names_cbx.setChecked(config.show_instance_names)
        self.page.show_terminals_cbx.setChecked(config.show_terminals)
        
    def config_from_ui(self) -> ConnectivityOptions:
        o = ConnectivityOptions(
            show_connectivity_panel=True,
            show_connectivity_info=self.page.show_connectivity_cbx.checked,
            show_flywires=self.page.show_flywires_cbx.checked,
            show_instance_names=self.page.show_instance_names_cbx.checked,
            show_terminals=self.page.show_terminals_cbx.checked,
        )
        return o

    def save_config(self):
        o = self.config_from_ui()
        o.save()


class ConnectivityPluginFactory(pya.PluginFactory):
    def __init__(self):
        super().__init__()        
        
        icon_path = os.path.join(path_containing_this_script, 'icons', 'flywire_32px.png')
        
        self.has_tool_entry = False
        self.register(-1000, "connectivity_visible", "Connectivity Inspection", icon_path)
  
        self.setupDock      = None
        self.markers_flywires = []
        self.markers_terminals = []
        self.markers_instance_names = []
        
        try:
            options = ConnectivityOptions.load()
            self.setup(options)
        except Exception as e:
            print("ConnectivityPluginFactory.ctor caught an exception", e)
            traceback.print_exc()

    @property
    def view(self) -> pya.LayoutView:
        return pya.LayoutView.current()
            
    @property
    def cell_view(self) -> pya.CellView:
        return pya.CellView.active()

    @property
    def layout(self) -> pya.Layout:
        return self.cell_view.layout()

    @property
    def tech(self) -> pya.Technology:
        return self.layout.technology()

    @property
    def options(self) -> ConnectivityOptions:
        o = ConnectivityOptions.load()
        return o

    def reset_menu(self, options: ConnectivityOptions):
        if Debugging.DEBUG:
            debug("ConnectivityPluginFactory.reset_menu")
        
        mw = pya.MainWindow.instance()
        menu = mw.menu()
        
        menu.insert_separator("tools_menu.end", "connectivity_separator")
        menu.insert_menu("tools_menu.end", "connectivity_menu",  "Connectivity Inspection")

        action = pya.Action()
        action.title = "Show Connectivity Panel"
        action.checkable = True
        action.checked = options.show_connectivity_panel
        action.on_triggered += lambda a=action: self.toggle_connectivity_panel(a)
        menu.insert_item(f"tools_menu.connectivity_menu.#0", f"show_connectivity_panel", action)

        action = pya.Action()
        action.title = "Show Connectivity Information"
        action.checkable = True
        action.checked = options.show_connectivity_info
        action.on_triggered += lambda a=action: self.toggle_connectivity_info(a)
        menu.insert_item(f"tools_menu.connectivity_menu.#1", f"show_connectivity_info", action)
    
        action = pya.Action()
        action.title = "Open Connectivity Browser"
        action.on_triggered += lambda: self.open_connectivity_browser()
        menu.insert_item(f"tools_menu.connectivity_menu.#2", f"open_connectivity_browser", action)
    
    def configure(self, name: str, value: str) -> bool:
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.configure: {name}")
            
        # NOTE:
        #   main menu actions update directly
        #   this gets triggered when the config is saved
        
        if name == CONFIG_KEY__CONNECTIVITY_OPTIONS:
            options = ConnectivityOptions.load()
            self.reset_menu(options)
            self.refresh_connectivity_info()
    
    def setup(self, options: ConnectivityOptions):
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.setup")

        self.reset_menu(options)

        if self.layout is None:
            return
        
        self.update_connectivity_panel(options)
        
        self.refresh_connectivity_info()   # TODO: figure when this must be updated and when not
        
    def stop(self):
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.stop")

        # TODO: hide all inspector dialogs
        
    def toggle_connectivity_panel(self, action: pya.Action):
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.toggle_connectivity_panel: {action.checked}")
        
        o = ConnectivityOptions.load()
        o.show_connectivity_panel = action.checked
        o.save()
        
        if self.layout is None:
            return

        self.update_connectivity_panel(o)

    def hide_connectivity_panel(self):
        """Called e.g. if (x) is clicked on the panel"""
        
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.hide_connectivity_panel")
        
        o = ConnectivityOptions.load()
        o.show_connectivity_panel = False
        o.save()

        if self.setupDock:
            self.setupDock.hide()
            
        self.reset_menu(o)

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
        
        self.refresh_connectivity_info()
        self.update_connectivity_panel(o)
        
    def open_connectivity_browser(self):
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.open_connectivity_browser")
        
    def on_current_view_changed(self):
        if Debugging.DEBUG:
             debug(f"ConnectivityPluginFactory.on_current_view_changed, self.view={self.view}")
             debug(f"ConnectivityPluginFactory.on_current_view_changed, self.view={self.view}, "
                   f"active cell name={'none' if self.cell_view is None else self.cell_view.cell_name}")

        if self.view is None:
            return

        try:
            if self.layout is None:
                if Debugging.DEBUG:
                    debug("ConnectivityPluginFactory.on_current_view_changed: no layout yet, register callback")
                self.view.on_file_open.connect(self.layout_changed)
            else:
                self.layout_changed()
        except Exception as e:
            print("ConnectivityPluginFactory.on_current_view_changed caught an exception", e)
            traceback.print_exc()
        
    def on_view_created(self):
        if Debugging.DEBUG:
             debug(f"ConnectivityPluginFactory.on_view_created, self.view={self.view}, "
                   f"active cell name={'none' if self.cell_view is None else self.cell_view.cell_name}")

        # NOTE: sometimes when starting klayout -e directly with a layout file
        #       on_current_view_changed won't get emitted
        mw = pya.MainWindow.instance()
        menu = mw.menu()
        if not menu.is_menu("tools_menu.connectivity_menu"):
            if Debugging.DEBUG:
                debug(f"ConnectivityPluginFactory.on_view_created, no menu found yet, "
                      f"seems we are in a startup situation, "
                      f"so we'll create the menu now")
            self.setup()

    def on_view_closed(self):
        if Debugging.DEBUG:
             debug("ConnectivityPluginFactory.on_view_closed")
      
    def on_active_cellview_changed(self) -> bool:
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.on_active_cellview_changed: {self.cell_view.cell_name}")
        
    def layout_changed(self):
        if Debugging.DEBUG:
            debug(f"ConnectivityPluginFactory.layout_changed, "
                  f"for cell view {self.cell_view.cell_name}")
        
        try:
            self.setup()
            
            self.view.on_active_cellview_changed += self.on_active_cellview_changed
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
        
    def _clear_markers_field(self, attr: str):
        markers = getattr(self, attr)
        for marker in markers:
            marker._destroy()
        setattr(self, attr, [])

    def _clear_markers_flywires(self):
        self._clear_markers_field('markers_flywires')

    def _clear_markers_terminals(self):
        self._clear_markers_field('markers_terminals')

    def _clear_markers_instance_names(self):
        self._clear_markers_field('markers_instance_names')

    def refresh_connectivity_info(self):
        self.conn_info = LayoutConnectivityInfo.for_layout_view(self.view)
        
        self.update_markers()
        
    def update_markers(self):
        self.update_markers_flywires()
        self.update_markers_terminals()
        self.update_markers_instance_names()

    def _text_marker(self, 
                     text: str, 
                     position: pya.DPoint, 
                     size: float = 12.0, 
                     text_color: int = 0xffffff,
                     frame_color: int = 0xff0000) -> pya.Marker:
        m = pya.Marker(self.view)
        dtext = pya.DText(text, position.x, position.y)
        dtext.halign = pya.HAlign.HAlignCenter
        dtext.valign = pya.VAlign.VAlignCenter
        
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
            
        # Group all pins across the whole layout by net (term_name).
        # NOTE: this assumes term_name is the net-level identifier that is
        # consistent across instances (i.e. globally-relevant net names,
        # not just PCell-local terminal names). If your design instead
        # needs hierarchical net tracing (net names differing per instance,
        # connected via parent-cell routing), this simple grouping is not
        # enough -- flag this if that's the case.
        pins_by_net: Dict[str, List[pya.DPoint]] = {}

        for cell in self.conn_info.cell_infos:
            for pcell in cell.pcell_infos:
                for pin in pcell.pin_infos:
                    pins_by_net.setdefault(pin.term_name, []).append(pin.bbox.center())

        for net_name, points in pins_by_net.items():
            if len(points) < 2:
                continue

            # Connect each pin to the first pin on the same net (star
            # topology) -- simplest approach, avoids O(n^2) full mesh.
            anchor = points[0]
            for pt in points[1:]:
                edge = pya.DEdge(anchor, pt)
                m = self._line_marker(edge)
                self.markers_flywires.append(m)
            

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

                label_pos = pya.DPoint(union_box.center().x, union_box.top)
                label = pcell.inst_name or pcell.cell_name
                tm = self._text_marker(label, label_pos)
                self.markers_instance_names.append(tm)        

    def viewport_adjust(self, v: int) -> int:
        trans = pya.CplxTrans(self.view.viewport_trans(), self.dbu)
        return v / trans.mag
