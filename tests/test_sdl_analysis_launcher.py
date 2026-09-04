from pathlib import Path

from klayout_connectivity.sdl_analysis_launcher import (
    adapter_for_technology,
    batch_script_candidates,
    build_attach_source_command,
    build_sdl_command,
    build_sg13g2_command,
    find_batch_script,
    find_source_attach_script,
    source_attach_script_candidates,
)


def test_finds_sdl_fork_before_upstream_package(tmp_path: Path):
    candidates = list(batch_script_candidates(str(tmp_path)))
    for candidate in reversed(candidates):
        path = Path(candidate)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# batch\n", encoding="utf-8")
    assert find_batch_script(str(tmp_path)) == candidates[0]


def test_builds_argv_without_shell_quoting():
    command = build_sg13g2_command(
        "/profile with space/batch.py",
        "/designs/active quenching.oas",
        "active-quenching",
        executable="/opt/klayout",
    )
    assert command == [
        "/opt/klayout", "-b", "-r", "/profile with space/batch.py",
        "-rd", "layout=/designs/active quenching.oas",
        "-rd", "top=active-quenching",
    ]


def test_detects_xh018_and_ihp_profiles(monkeypatch):
    for name in ("KLAYOUT_HOME", "XH018_KLAYOUT_HOME", "IHP_KLAYOUT_HOME"):
        monkeypatch.delenv(name, raising=False)
    assert adapter_for_technology("TECH_XH018_1131") == "xh018"
    assert adapter_for_technology("sg13g2") == "sg13g2"
    assert adapter_for_technology("", "/designs/.klayout-xh018") == "xh018"
    assert adapter_for_technology("unknown", "/tmp/plain") is None


def test_finds_technology_specific_batch(tmp_path: Path):
    xh = list(batch_script_candidates(str(tmp_path), "xh018"))[0]
    path = Path(xh)
    path.parent.mkdir(parents=True)
    path.write_text("# xh batch\n", encoding="utf-8")
    assert find_batch_script(str(tmp_path), "xh018") == xh
    assert xh.endswith("/xh018_sdl_batch.py")


def test_generic_xh_command_passes_complete_snapshot_output_contract():
    command = build_sdl_command(
        "/profile/xh018_sdl_batch.py", "/design/frozen.oas", "TOP",
        "xh018", executable="/opt/klayout",
    )
    assert command == [
        "/opt/klayout", "-b", "-r", "/profile/xh018_sdl_batch.py",
        "-rd", "layout=/design/frozen.oas",
        "-rd", "input=/design/frozen.oas",
        "-rd", "top=TOP",
        "-rd", "output=/design/frozen.oas.observed.json",
        "-rd", "sidecar=/design/frozen.oas.sdl.json",
        "-rd", "rdb=/design/frozen.oas.sdl.lyrdb",
    ]


def test_attach_source_command_is_sidecar_only(tmp_path: Path):
    candidate = list(source_attach_script_candidates(str(tmp_path)))[0]
    path = Path(candidate)
    path.parent.mkdir(parents=True)
    path.write_text("# attach\n", encoding="utf-8")
    assert find_source_attach_script(str(tmp_path)) == candidate
    assert build_attach_source_command(
        candidate, "/design/frozen.oas", "TOP", "/design/TOP.sch",
        executable="/opt/klayout",
    ) == [
        "/opt/klayout", "-b", "-r", candidate,
        "-rd", "layout=/design/frozen.oas",
        "-rd", "input=/design/frozen.oas",
        "-rd", "top=TOP",
        "-rd", "source=/design/TOP.sch",
    ]
