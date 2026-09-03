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
from pathlib import Path
from typing import *
import traceback

import pya

from klayout_plugin_utils.debugging import debug, Debugging
from klayout_plugin_utils.event_loop import EventLoop
from klayout_plugin_utils.qt_helpers import (
    compat_QShortCut,
    compat_QTreeWidgetItem_setBackground,
)
from klayout_plugin_utils.ui_loader import load_ui
from klayout_connectivity.findings import Finding, FindingSelection, FindingsModel


#--------------------------------------------------------------------------------

#--------------------------------------------------------------------------------
# data-role key used to stash a python-side index on tree items, so we can
# look up the underlying object on selection without relying on QTreeWidgetItem
# identity surviving across the pya binding (which it does not reliably do)
_ITEM_INDEX_ROLE = int(pya.Qt.UserRole)


@dataclass
class _NetEntry:
    net_name: str
    pcell: CellInstanceConnectivityInfo
    cell: "CellConnectivityInfo"  # noqa: F821 (forward ref, avoids importing just for typing)
    pin: PinInfo


class _InstanceTreeNode:
    """One path segment of an instance hierarchy (e.g. 'X3' in 'top.X3.X1')."""

    def __init__(self, name: str):
        self.name = name
        self.children: Dict[str, "_InstanceTreeNode"] = {}
        self.pcell: Optional[CellInstanceConnectivityInfo] = None  # set only on leaf/instance nodes

    def child(self, name: str) -> "_InstanceTreeNode":
        node = self.children.get(name)
        if node is None:
            node = _InstanceTreeNode(name)
            self.children[name] = node
        return node


#--------------------------------------------------------------------------------

class ConnectivityByNetPage(pya.QWidget):
    """
    Master/detail: master lists all nets in the layout, detail lists every
    instance+terminal that belongs to the selected net.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._net_entries_by_index: List[List[_NetEntry]] = []

        layout = pya.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = pya.QSplitter(pya.Qt.Horizontal, self)
        layout.addWidget(splitter)

        self.net_tw = pya.QTreeWidget(splitter)
        self.net_tw.setHeaderLabels(["Net", "Terminals"])
        self.net_tw.setRootIsDecorated(False)
        self.net_tw.setSelectionMode(pya.QAbstractItemView.SingleSelection)
        self.net_tw.header.setSectionResizeMode(0, pya.QHeaderView.Stretch)
        self.net_tw.header.setSectionResizeMode(1, pya.QHeaderView.ResizeToContents)

        self.detail_tw = pya.QTreeWidget(splitter)
        self.detail_tw.setHeaderLabels(["Instance", "Cell", "Pin", "Terminal"])
        self.detail_tw.setRootIsDecorated(False)
        for col in range(4):
            self.detail_tw.header.setSectionResizeMode(col, pya.QHeaderView.ResizeToContents)
        self.detail_tw.header.setSectionResizeMode(1, pya.QHeaderView.Stretch)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self.net_tw.itemSelectionChanged.connect(self.on_net_selection_changed)

    def update_from_conn_info(self, conn_info: LayoutConnectivityInfo):
        self.net_tw.clear()
        self.detail_tw.clear()
        self._net_entries_by_index = []

        entries_by_net: Dict[str, List[_NetEntry]] = {}
        for cell in conn_info.cell_infos:
            for pcell in cell.pcell_infos:
                for pin in pcell.pin_infos:
                    net_name = pcell.net_for_pin(pin)
                    entries_by_net.setdefault(net_name, []).append(
                        _NetEntry(net_name=net_name, pcell=pcell, cell=cell, pin=pin)
                    )

        for net_name in sorted(entries_by_net.keys()):
            entries = entries_by_net[net_name]
            item = pya.QTreeWidgetItem()
            item.setText(0, net_name)
            item.setText(1, str(len(entries)))
            item.setData(0, _ITEM_INDEX_ROLE, len(self._net_entries_by_index))
            self._net_entries_by_index.append(entries)
            self.net_tw.addTopLevelItem(item)

    def on_net_selection_changed(self):
        self.detail_tw.clear()

        selected = self.net_tw.selectedItems()
        if not selected:
            return

        idx = selected[0].data(0, _ITEM_INDEX_ROLE)
        if idx is None:
            return

        entries = self._net_entries_by_index[idx]
        entries = sorted(entries, key=lambda e: (e.pcell.hierarchy_path or e.pcell.inst_name))

        for entry in entries:
            item = pya.QTreeWidgetItem()
            item.setText(0, entry.pcell.hierarchy_path or entry.pcell.inst_name)
            item.setText(1, _fq_cell_name(entry.pcell))
            item.setText(2, entry.pin.name)
            item.setText(3, entry.pin.term_name)
            self.detail_tw.addTopLevelItem(item)


class ConnectivityByInstancePage(pya.QWidget):
    """
    Master/detail: master shows the instance hierarchy (from
    INSTANCE_INFO__HIERARCHY_PATH), detail lists the selected instance's
    pins, their terminal names, and the net each pin is on.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._pcells_by_index: List[CellInstanceConnectivityInfo] = []

        layout = pya.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = pya.QSplitter(pya.Qt.Horizontal, self)
        layout.addWidget(splitter)

        self.instance_tw = pya.QTreeWidget(splitter)
        self.instance_tw.setHeaderLabels(["Instance", "Cell"])
        self.instance_tw.setSelectionMode(pya.QAbstractItemView.SingleSelection)
        self.instance_tw.header.setSectionResizeMode(0, pya.QHeaderView.Stretch)
        self.instance_tw.header.setSectionResizeMode(1, pya.QHeaderView.ResizeToContents)

        self.detail_tw = pya.QTreeWidget(splitter)
        self.detail_tw.setHeaderLabels(["Pin", "Terminal", "Net"])
        self.detail_tw.setRootIsDecorated(False)
        for col in range(3):
            self.detail_tw.header.setSectionResizeMode(col, pya.QHeaderView.ResizeToContents)
        self.detail_tw.header.setSectionResizeMode(2, pya.QHeaderView.Stretch)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self.instance_tw.itemSelectionChanged.connect(self.on_instance_selection_changed)

    def update_from_conn_info(self, conn_info: LayoutConnectivityInfo):
        self.instance_tw.clear()
        self.detail_tw.clear()
        self._pcells_by_index = []

        root = _InstanceTreeNode('')
        no_path_counter = 0

        for cell in conn_info.cell_infos:
            for pcell in cell.pcell_infos:
                path = pcell.hierarchy_path
                if not path:
                    # instances without a hierarchy path (e.g. layouts
                    # imported before the netlist importer set it) get
                    # listed flat, under a synthetic name so they're not
                    # silently dropped
                    no_path_counter += 1
                    segments = [f"<no hierarchy path #{no_path_counter}: {pcell.inst_name}>"]
                else:
                    segments = path.split('.')

                node = root
                for seg in segments:
                    node = node.child(seg)
                node.pcell = pcell

        self._populate_instance_tree(None, root)
        self.instance_tw.expandAll()

    def _populate_instance_tree(self, parent_item: Optional[pya.QTreeWidgetItem], node: _InstanceTreeNode):
        for name in sorted(node.children.keys()):
            child_node = node.children[name]

            item = pya.QTreeWidgetItem()
            item.setText(0, name)

            if child_node.pcell is not None:
                item.setText(1, _fq_cell_name(child_node.pcell))
                item.setData(0, _ITEM_INDEX_ROLE, len(self._pcells_by_index))
                self._pcells_by_index.append(child_node.pcell)

            if parent_item is None:
                self.instance_tw.addTopLevelItem(item)
            else:
                parent_item.addChild(item)

            self._populate_instance_tree(item, child_node)

    def on_instance_selection_changed(self):
        self.detail_tw.clear()

        selected = self.instance_tw.selectedItems()
        if not selected:
            return

        idx = selected[0].data(0, _ITEM_INDEX_ROLE)
        if idx is None:
            return   # a purely structural (non-instance) hierarchy node

        pcell = self._pcells_by_index[idx]

        for pin in sorted(pcell.pin_infos, key=lambda p: p.name):
            item = pya.QTreeWidgetItem()
            item.setText(0, pin.name)
            item.setText(1, pin.term_name)
            item.setText(2, pcell.net_for_pin(pin))
            self.detail_tw.addTopLevelItem(item)


def _fq_cell_name(pcell: CellInstanceConnectivityInfo) -> str:
    if pcell.netlist_cell_name:
        return (f"{pcell.netlist_lib_name}.{pcell.netlist_cell_name}"
                if pcell.netlist_lib_name else pcell.netlist_cell_name)
    return f"{pcell.lib_name}.{pcell.cell_name}" if pcell.lib_name else pcell.cell_name


#--------------------------------------------------------------------------------

class ConnectivityBrowserDialog(pya.QDialog):
    """
    Non-modal inspector showing all connectivity info for the current
    layout: one tab browsing by net, one tab browsing by instance.
    """

    def __init__(self, parent=None, refresh_callback: Optional[Callable] = None,
                 findings_selection_callback: Optional[Callable[[FindingSelection], None]] = None):
        super().__init__(parent)
        self.refresh_callback = refresh_callback
        # The current browser has no findings producer yet.  Keeping its state
        # here gives that producer a small, explicit integration seam without
        # making the reusable model depend on pya/Qt.
        self.findings_model = FindingsModel()
        self.findings_selection_callback = findings_selection_callback
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("Connectivity Browser")
        self.setModal(False)
        self.resize(900, 500)

        layout = pya.QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        self.tabs = pya.QTabWidget(self)
        layout.addWidget(self.tabs)

        self.by_net_page = ConnectivityByNetPage(self)
        self.by_instance_page = ConnectivityByInstancePage(self)

        self.tabs.addTab(self.by_net_page, "By Net")
        self.tabs.addTab(self.by_instance_page, "By Instance")

        bottom = pya.QHBoxLayout()
        self.refresh_pb = pya.QPushButton("Refresh")
        bottom.addWidget(self.refresh_pb)
        bottom.addStretch()
        self.close_pb = pya.QPushButton("Close")
        bottom.addWidget(self.close_pb)
        layout.addLayout(bottom)

        self.refresh_pb.clicked.connect(self.on_refresh)
        self.close_pb.clicked.connect(self.on_close)

    def update_from_conn_info(self, conn_info: LayoutConnectivityInfo):
        self.by_net_page.update_from_conn_info(conn_info)
        self.by_instance_page.update_from_conn_info(conn_info)

    def update_findings(self, findings: Iterable[Finding]) -> None:
        """Replace findings supplied by a checker and retain surviving selection."""
        self.findings_model.replace_findings(findings)
        self._notify_findings_selection()

    def select_findings(self, identifiers: Iterable[str]) -> FindingSelection:
        """UI selection hook; callback receives union bbox and probe targets."""
        selection = self.findings_model.set_selection(identifiers)
        self._notify_findings_selection(selection)
        return selection

    def _notify_findings_selection(self, selection: Optional[FindingSelection] = None) -> None:
        if self.findings_selection_callback is not None:
            self.findings_selection_callback(selection or self.findings_model.selection())

    def on_close(self):
        if Debugging.DEBUG:
            debug("ConnectivityBrowserDialog.on_close")
        try:
            self.close()
        except Exception as e:
            traceback.print_exc()
    
    def on_refresh(self):
        if Debugging.DEBUG:
            debug("ConnectivityBrowserDialog.on_refresh")
        if self.refresh_callback is not None:
            self.refresh_callback()
