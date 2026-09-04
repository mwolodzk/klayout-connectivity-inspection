"""Small, Qt-free helpers for launching the SG13G2 SDL batch adapter."""

from __future__ import annotations

import os
import shutil
from typing import Iterable, Optional


_PACKAGE_DIRS = ("IICSDLNetlistImportPlugin", "NetlistImportPlugin")


def batch_script_candidates(klayout_home: str) -> Iterable[str]:
    """Yield supported Salt package locations, preferring the SDL fork."""
    override = os.environ.get("IIC_SDL_BATCH_SCRIPT")
    if override:
        yield override
    for package in _PACKAGE_DIRS:
        yield os.path.join(
            klayout_home,
            "salt",
            package,
            "pymacros",
            "klayout_netlist_importer",
            "sg13g2_sdl_batch.py",
        )


def find_batch_script(klayout_home: Optional[str] = None) -> Optional[str]:
    home = klayout_home or os.environ.get("KLAYOUT_HOME", "")
    return next((path for path in batch_script_candidates(home) if os.path.isfile(path)), None)


def build_sg13g2_command(
    script: str, layout_path: str, top_cell: str, executable: Optional[str] = None
) -> list[str]:
    """Build an argv-only command: no shell expansion or path quoting hazards."""
    klayout = executable or shutil.which("klayout")
    if not klayout:
        raise FileNotFoundError("The klayout executable is not available on PATH")
    return [
        klayout,
        "-b",
        "-r",
        script,
        "-rd",
        "layout=" + layout_path,
        "-rd",
        "top=" + top_cell,
    ]
