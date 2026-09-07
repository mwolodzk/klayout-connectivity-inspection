from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "pymacros/klayout_connectivity/SDLUserManual.html"
README = ROOT / "README.md"
PLUGIN = ROOT / "pymacros/klayout_connectivity/plugin.py"


def test_manual_covers_complete_ihp_user_flow():
    text = HTML.read_text(encoding="utf-8")
    for phrase in (
        "IHP SG13G2",
        "File → Import → Netlist",
        "Source File",
        "Tech Cell Mapping",
        "Netlist Node Order",
        "Packed Mode with Padding",
        "&lt;layout&gt;.sdl.json",
        "All Opens",
        "Open Connectivity Browser",
        "Run SDL Analysis",
        "read-only",
        "Connectivity Browser i CAS",
    ):
        assert phrase in text


def test_documents_are_explicitly_ihp_only():
    for document in (HTML, README):
        assert "IHP SG13G2" in document.read_text(encoding="utf-8")


def test_connectivity_menu_exposes_manual_and_analysis():
    source = PLUGIN.read_text(encoding="utf-8")
    assert "tools_menu.connectivity_menu.end" in source
    assert "sdl_user_manual" in source
    assert "SDL / CAS User Manual..." in source
    assert "run_sg13g2_sdl_analysis" in source
