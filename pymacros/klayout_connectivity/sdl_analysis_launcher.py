"""Qt-free helpers for launching the IHP SG13G2 SDL batch adapter.

The GUI never opens a writable layout in the child process. Analysis receives
the saved layout as input and may write only SDL diagnostic sidecars.
"""

from __future__ import annotations

import os
import shutil
from typing import Iterable, Optional


_PACKAGE_DIRS = ("IICSDLNetlistImportPlugin", "NetlistImportPlugin")
_BATCH_SCRIPT = "sg13g2_sdl_batch.py"


def adapter_for_technology(
    technology_name: str = "", klayout_home: str = ""
) -> Optional[str]:
    """Return the SG13G2 adapter key inferred from technology/profile names."""
    hints = (
        technology_name or "",
        klayout_home or "",
        os.environ.get("KLAYOUT_HOME", ""),
        os.environ.get("IHP_KLAYOUT_HOME", ""),
    )
    for raw_hint in hints:
        hint = raw_hint.lower()
        if "sg13" in hint or "ihp" in hint:
            return "sg13g2"
    return None


def batch_script_candidates(
    klayout_home: str, adapter: str = "sg13g2"
) -> Iterable[str]:
    """Yield supported Salt package locations, preferring the SDL fork."""
    override = os.environ.get("IIC_SDL_BATCH_SCRIPT")
    if override:
        yield override
    if adapter != "sg13g2":
        return
    for package in _PACKAGE_DIRS:
        yield os.path.join(
            klayout_home,
            "salt",
            package,
            "pymacros",
            "klayout_netlist_importer",
            _BATCH_SCRIPT,
        )


def find_batch_script(
    klayout_home: Optional[str] = None, adapter: str = "sg13g2"
) -> Optional[str]:
    home = klayout_home or os.environ.get("KLAYOUT_HOME", "")
    return next(
        (path for path in batch_script_candidates(home, adapter) if os.path.isfile(path)),
        None,
    )


def _klayout_executable(executable: Optional[str]) -> str:
    klayout = executable or shutil.which("klayout")
    if not klayout:
        raise FileNotFoundError("The klayout executable is not available on PATH")
    return klayout


def build_sdl_command(
    script: str,
    layout_path: str,
    top_cell: str,
    adapter: str,
    executable: Optional[str] = None,
) -> list[str]:
    """Build a shell-free, read-only SG13G2 SDL analysis command."""
    if adapter != "sg13g2":
        raise ValueError("Unsupported SDL adapter: {}".format(adapter))
    return build_sg13g2_command(script, layout_path, top_cell, executable)


def build_sg13g2_command(
    script: str,
    layout_path: str,
    top_cell: str,
    executable: Optional[str] = None,
) -> list[str]:
    """Build an argv-only command without shell expansion or quoting hazards."""
    return [
        _klayout_executable(executable),
        "-b",
        "-r",
        script,
        "-rd",
        "layout=" + layout_path,
        "-rd",
        "top=" + top_cell,
    ]
