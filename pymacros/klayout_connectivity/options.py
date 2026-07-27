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
from typing import *

import pya
    
from klayout_plugin_utils.debugging import debug, Debugging
from klayout_plugin_utils.str_enum_compat import DualStrEnum

# ---------------------------------------------------------------------------

CONFIG_KEY__CONNECTIVITY_OPTIONS = 'ConnectivityInspectionPlugin__Options'


@dataclass
class ConnectivityOptions:
    show_connectivity_panel: bool = False
    show_connectivity_info: bool = False
    
    show_flywires: bool = True
    show_instance_names: bool = True
    show_terminals: bool = True

    @classmethod
    def load(cls) -> ConnectivityOptions:
        if Debugging.DEBUG:
            debug("ConnectivityOptions.load")
            
        mw = pya.MainWindow.instance()
        config_str = mw.get_config(CONFIG_KEY__CONNECTIVITY_OPTIONS)
        
        options = ConnectivityOptions()
        
        try:
            if config_str:
                d = pya.AbstractMenu.unpack_key_binding(config_str)
                
                options.show_connectivity_panel = cls.str2bool(d['show_connectivity_panel'])
                options.show_connectivity_info = cls.str2bool(d['show_connectivity_info'])
                options.show_flywires = cls.str2bool(d['show_flywires'])
                options.show_instance_names = cls.str2bool(d['show_instance_names'])
                options.show_terminals = cls.str2bool(d['show_terminals'])
        except Exception as e:
            if Debugging.DEBUG:
                debug(f"ConnectivityOptions.load: failed to load options, "
                      f"reverting to default. Exception: {e}")
            
        return options
    
    def save(self):
        if Debugging.DEBUG:
            debug("ConnectivityOptions.save")
            
        mw = pya.MainWindow.instance()
        
        config_str = pya.AbstractMenu.pack_key_binding(self.dict())
        mw.set_config(CONFIG_KEY__CONNECTIVITY_OPTIONS, config_str)
    
    def dict(self) -> Dict[str, str]:
        return {
            'show_connectivity_panel': self.bool2str(self.show_connectivity_panel),
            'show_connectivity_info': self.bool2str(self.show_connectivity_info),
            'show_flywires': self.bool2str(self.show_flywires),
            'show_instance_names': self.bool2str(self.show_instance_names),
            'show_terminals': self.bool2str(self.show_terminals),
        }
    
    @staticmethod    
    def bool2str(v: bool) -> str:
        return 'true' if v else 'false'
    
    @staticmethod
    def str2bool(s: str) -> bool:
        return s == 'true'
