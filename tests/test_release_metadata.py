import base64
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def test_xh018_release_grain_and_runtime_payload_are_complete() -> None:
    grain = ET.parse(ROOT / "grain.xml").getroot()
    assert grain.findtext("name") == "IICSDLConnectivityInspectionPlugin"
    assert grain.findtext("version") == "0.4"
    assert "SG13G2 and XH018" in (grain.findtext("doc") or "")
    assert [
        (item.findtext("name"), item.findtext("version"))
        for item in grain.findall("depends")
    ] == [
        ("KLayoutPluginUtils", "0.28"),
        ("IICSDLNetlistImportPlugin", "0.14"),
    ]
    screenshot = base64.b64decode(grain.findtext("screenshot") or "", validate=True)
    assert screenshot.startswith(b"\xff\xd8\xff"), "Salt.Mine screenshot must be JPEG"
    package = ROOT / "pymacros/klayout_connectivity"
    for filename in ("marker_emphasis.py", "sdl_analysis_launcher.py"):
        assert (package / filename).is_file(), filename


def test_autorun_hot_reloads_new_gui_runtime() -> None:
    source = (ROOT / "pymacros/autorun.lym").read_text(encoding="utf-8")
    for module in ("marker_emphasis", "sdl_analysis_launcher"):
        assert "import klayout_connectivity.%s" % module in source
        assert "reload(klayout_connectivity.%s)" % module in source
