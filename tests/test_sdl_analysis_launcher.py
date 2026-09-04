from pathlib import Path

from klayout_connectivity.sdl_analysis_launcher import (
    batch_script_candidates,
    build_sg13g2_command,
    find_batch_script,
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
