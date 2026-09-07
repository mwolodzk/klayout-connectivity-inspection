from pathlib import Path

import pytest

from klayout_connectivity.sdl_analysis_launcher import (
    adapter_for_technology,
    batch_script_candidates,
    build_sdl_command,
    build_sg13g2_command,
    find_batch_script,
)


def test_finds_sdl_fork_before_upstream_package(tmp_path: Path):
    candidates = list(batch_script_candidates(str(tmp_path), "sg13g2"))
    for candidate in reversed(candidates):
        path = Path(candidate)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# batch\n", encoding="utf-8")
    assert find_batch_script(str(tmp_path), "sg13g2") == candidates[0]


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


def test_detects_only_ihp_profile(monkeypatch):
    for name in ("KLAYOUT_HOME", "IHP_KLAYOUT_HOME"):
        monkeypatch.delenv(name, raising=False)
    assert adapter_for_technology("sg13g2") == "sg13g2"
    assert adapter_for_technology("IHP SG13G2") == "sg13g2"
    assert adapter_for_technology("unknown", "/tmp/plain") is None


def test_generic_command_is_sg13g2_only():
    command = build_sdl_command(
        "/profile/sg13g2_sdl_batch.py", "/design/chip.oas", "TOP",
        "sg13g2", executable="/opt/klayout",
    )
    assert command[-4:] == ["-rd", "layout=/design/chip.oas", "-rd", "top=TOP"]
    with pytest.raises(ValueError, match="Unsupported SDL adapter"):
        build_sdl_command(
            "/profile/other.py", "/design/chip.oas", "TOP", "other"
        )
