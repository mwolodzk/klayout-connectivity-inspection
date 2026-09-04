"""Qt-free helpers for launching technology-specific SDL batch adapters.

The GUI never opens a writable layout in the child process. Both analysis and
source attachment receive the saved layout as an input and may write only SDL
diagnostic sidecars.
"""

from __future__ import annotations

import os
import shutil
from typing import Iterable, Optional


_PACKAGE_DIRS = ("IICSDLNetlistImportPlugin", "NetlistImportPlugin")
_BATCH_SCRIPTS = {
    "sg13g2": "sg13g2_sdl_batch.py",
    "xh018": "xh018_sdl_batch.py",
}


def adapter_for_technology(technology_name: str = "",
                           klayout_home: str = "") -> Optional[str]:
    """Return the SDL adapter key inferred from technology/profile names."""
    hints = (
        technology_name or "",
        klayout_home or "",
        os.environ.get("KLAYOUT_HOME", ""),
        os.environ.get("XH018_KLAYOUT_HOME", ""),
        os.environ.get("IHP_KLAYOUT_HOME", ""),
    )
    for raw_hint in hints:
        hint = raw_hint.lower()
        if "xh018" in hint or "xh_018" in hint:
            return "xh018"
        if "sg13" in hint or "ihp" in hint:
            return "sg13g2"
    return None


def batch_script_candidates(klayout_home: str,
                            adapter: str = "sg13g2") -> Iterable[str]:
    """Yield supported Salt package locations, preferring the SDL fork."""
    override = os.environ.get("IIC_SDL_BATCH_SCRIPT")
    if override:
        yield override
    script_name = _BATCH_SCRIPTS.get(adapter)
    if script_name is None:
        return
    for package in _PACKAGE_DIRS:
        yield os.path.join(
            klayout_home,
            "salt",
            package,
            "pymacros",
            "klayout_netlist_importer",
            script_name,
        )


def find_batch_script(klayout_home: Optional[str] = None,
                      adapter: str = "sg13g2") -> Optional[str]:
    home = klayout_home or os.environ.get("KLAYOUT_HOME", "")
    return next(
        (path for path in batch_script_candidates(home, adapter) if os.path.isfile(path)),
        None,
    )


def source_attach_script_candidates(klayout_home: str) -> Iterable[str]:
    """Yield importer-owned, layout-preserving source-attachment scripts."""
    override = os.environ.get("IIC_SDL_ATTACH_SCRIPT")
    if override:
        yield override
    for package in _PACKAGE_DIRS:
        yield os.path.join(
            klayout_home,
            "salt",
            package,
            "pymacros",
            "klayout_netlist_importer",
            "sdl_attach_source.py",
        )


def find_source_attach_script(klayout_home: Optional[str] = None) -> Optional[str]:
    home = klayout_home or os.environ.get("KLAYOUT_HOME", "")
    return next(
        (path for path in source_attach_script_candidates(home) if os.path.isfile(path)),
        None,
    )


def _klayout_executable(executable: Optional[str]) -> str:
    klayout = executable or shutil.which("klayout")
    if not klayout:
        raise FileNotFoundError("The klayout executable is not available on PATH")
    return klayout


def build_sdl_command(script: str, layout_path: str, top_cell: str,
                      adapter: str,
                      executable: Optional[str] = None) -> list[str]:
    """Build a shell-free, read-only SDL analysis command.

    ``layout`` is the common v1 argument. ``input`` and ``output`` retain
    compatibility with the initial XH018 extractor. XH018 additionally gets
    explicit sidecar/RDB destinations so it cannot silently stop after
    extraction and leave the Browser with an empty snapshot.
    """
    command = [
        _klayout_executable(executable),
        "-b", "-r", script,
        "-rd", "layout=" + layout_path,
        "-rd", "input=" + layout_path,
        "-rd", "top=" + top_cell,
    ]
    if adapter == "xh018":
        command.extend((
            "-rd", "output=" + layout_path + ".observed.json",
            "-rd", "sidecar=" + layout_path + ".sdl.json",
            "-rd", "rdb=" + layout_path + ".sdl.lyrdb",
        ))
    return command


def build_attach_source_command(script: str, layout_path: str, top_cell: str,
                                source_path: str,
                                executable: Optional[str] = None) -> list[str]:
    """Build an analysis-only source attachment command (never imports cells)."""
    return [
        _klayout_executable(executable),
        "-b", "-r", script,
        "-rd", "layout=" + layout_path,
        "-rd", "input=" + layout_path,
        "-rd", "top=" + top_cell,
        "-rd", "source=" + source_path,
    ]


def build_sg13g2_command(
    script: str, layout_path: str, top_cell: str, executable: Optional[str] = None
) -> list[str]:
    """Build an argv-only command: no shell expansion or path quoting hazards."""
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
