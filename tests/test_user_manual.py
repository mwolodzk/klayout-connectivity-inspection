from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "pymacros/klayout_connectivity/SDLUserManual.html"
README = ROOT / "README.md"
PLUGIN = ROOT / "pymacros/klayout_connectivity/plugin.py"


def test_manual_covers_complete_user_flow():
    text = HTML.read_text(encoding="utf-8")
    for phrase in (
        "File → Import → Netlist",
        "Source File",
        "Tech Cell Mapping",
        "Netlist Node Order",
        "Packed Mode with Padding",
        "&lt;layout&gt;.sdl.json",
        "stale=false",
        "All Opens",
        "Open Connectivity Browser",
        "Run SDL Analysis",
        "Attach SDL Source",
        "xh018-gds1131",
        "read-only",
        "SDL analysis warning",
        "-rd sidecar=",
        "-rd rdb=",
        "okno CAS",
        "XH018",
        "klayout_sdl_gui_smoke.py",
    ):
        assert phrase in text


def test_documented_batch_paths_use_actual_salt_install_directory():
    manual = HTML.read_text(encoding="utf-8")
    assert "/salt/NetlistImportPlugin/" in manual
    for document in (HTML, README):
        assert "/salt/IICSDLNetlistImportPlugin/" not in document.read_text(
            encoding="utf-8"
        )


def test_connectivity_menu_exposes_manual():
    source = PLUGIN.read_text(encoding="utf-8")
    assert "tools_menu.connectivity_menu.end" in source
    assert "sdl_user_manual" in source
    assert "SDL / CAS User Manual..." in source
    assert "run_sg13g2_sdl_analysis" in source
    assert "attach_sdl_source" in source
