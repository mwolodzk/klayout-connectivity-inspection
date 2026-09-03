from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MACRO = ROOT / "deployment/xh018-production/sdl_manual_only.lym"


def test_xh018_manual_macro_is_standalone_from_sdl_runtime():
    source = MACRO.read_text(encoding="utf-8")
    assert "klayout_connectivity.user_manual" in source
    assert "klayout_connectivity.findings" not in source
    assert "tools_menu.end" in source
    assert "sdl_cas_user_manual" in source
