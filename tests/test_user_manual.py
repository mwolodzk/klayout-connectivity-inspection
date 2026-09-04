from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "pymacros/klayout_connectivity/SDLUserManual.html"
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
        "Run SG13G2 SDL Analysis",
        "okno CAS",
        "XH018",
        "klayout_sdl_gui_smoke.py",
    ):
        assert phrase in text


def test_connectivity_menu_exposes_manual():
    source = PLUGIN.read_text(encoding="utf-8")
    assert "tools_menu.connectivity_menu.end" in source
    assert "sdl_user_manual" in source
    assert "SDL / CAS User Manual..." in source
    assert "run_sg13g2_sdl_analysis" in source
