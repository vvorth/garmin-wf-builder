"""Coloured CLI output (R2): `--color`, the shared `--color` plumbing, and
the styling rules in `wfb/cli.py`.

Subprocess tests exercise the real entry point the way `tests/test_cli.py`
does -- a non-TTY pipe, so `auto` (the default) is plain regardless of the
running terminal, and `always`/`never` are what actually flip the ANSI
codes on or off.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "wfb.py"

ESC = "\033["
_ANSI = re.compile(r"\033\[[0-9;]*m")


def plain(text: str) -> str:
    """Strip ANSI codes, so a content assertion is not tripped up by a reset
    code landing between two words that are styled separately (`ok` then a
    plain ` -- `)."""
    return _ANSI.sub("", text)


def run(*args: str, env: dict | None = None):
    """Invoke the entry point the way an outside caller would: by path."""
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(ENTRY), *args],
        capture_output=True, text=True, cwd=str(ROOT), env=full_env, check=False,
    )


def test_doctor_always_has_escapes(db):
    result = run("doctor", "--color", "always")
    assert result.returncode == 0, result.stdout + result.stderr
    assert ESC in result.stdout


def test_doctor_never_has_no_escapes(db):
    result = run("doctor", "--color", "never")
    assert result.returncode == 0, result.stdout + result.stderr
    assert ESC not in result.stdout


def test_no_color_env_wins_with_no_flag(db):
    """NO_COLOR is respected even though stdout here is a pipe, not a TTY --
    `should_color` would already say no for a pipe, so this also exercises
    that a set-but-empty precedence chain does not somehow re-enable colour."""
    result = run("doctor", env={"NO_COLOR": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert ESC not in result.stdout


def test_color_before_the_subcommand_also_works(db):
    """`wfb --color always doctor` -- the flag before the command name, not
    just after it."""
    result = run("--color", "always", "doctor")
    assert result.returncode == 0, result.stdout + result.stderr
    assert ESC in result.stdout


def test_color_after_the_subcommand_overrides_before_it(db):
    result = run("--color", "always", "doctor", "--color", "never")
    assert result.returncode == 0, result.stdout + result.stderr
    assert ESC not in result.stdout


def test_validate_ok_summary_is_coloured(tmp_path, db, minimal):
    design = tmp_path / "face.yaml"
    design.write_text(minimal, encoding="utf-8")
    result = run("validate", str(design), "--color", "always")
    assert result.returncode == 0, result.stdout + result.stderr
    assert ESC in result.stdout
    assert "ok --" in plain(result.stdout)


def test_validate_ok_summary_is_plain_by_default(tmp_path, db, minimal):
    design = tmp_path / "face.yaml"
    design.write_text(minimal, encoding="utf-8")
    result = run("validate", str(design), "--color", "never")
    assert result.returncode == 0, result.stdout + result.stderr
    assert ESC not in result.stdout
    assert f"{design}: ok -- no diagnostics" in result.stdout


def test_validate_invalid_summary_is_coloured(tmp_path):
    design = tmp_path / "face.yaml"
    design.write_text("not: valid: yaml: at: all: [", encoding="utf-8")
    result = run("validate", str(design), "--color", "always")
    assert result.returncode == 1
    assert ESC in result.stderr
    assert "invalid --" in plain(result.stderr)


def test_build_no_compile_summary_is_coloured(tmp_path, db, minimal):
    design = tmp_path / "face.yaml"
    design.write_text(minimal, encoding="utf-8")
    result = run("build", str(design), "--no-compile", "-o", str(tmp_path / "out"),
                 "--color", "always")
    assert result.returncode == 0, result.stdout + result.stderr
    assert ESC in result.stdout
    assert "build succeeded --" in plain(result.stdout)


def test_build_summary_is_plain_by_default(tmp_path, db, minimal):
    design = tmp_path / "face.yaml"
    design.write_text(minimal, encoding="utf-8")
    result = run("build", str(design), "--no-compile", "-o", str(tmp_path / "out"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert ESC not in result.stdout
    assert "build succeeded --" in result.stdout


# -- `built` line alignment: a unit test against a helper, not a real build,
# so it needs no `monkeyc` and stays out of the `slow` suite. --------------


def test_built_lines_align_regardless_of_prg_name_length():
    from wfb.cli import _format_built

    products = {
        "short": Path("a.prg"),
        "long": Path("a-much-longer-device-name.prg"),
    }
    memory = {
        "short": {"total": 1_000, "limit": 100_000},
        "long": {"total": 1_000, "limit": 100_000},
    }
    lines = _format_built(products, memory, color=False)
    assert len(lines) == 2
    first_paren = lines[0].index("(")
    second_paren = lines[1].index("(")
    assert first_paren == second_paren, lines


def test_memory_share_thresholds_colour_correctly():
    from wfb.cli import _memory_share

    low = _memory_share(50.0, color=True)
    mid = _memory_share(80.0, color=True)
    high = _memory_share(95.0, color=True)
    assert f"{ESC}32m" in low and "33" not in low and "31" not in low
    assert f"{ESC}33m" in mid
    assert f"{ESC}31m" in high


def test_memory_share_plain_has_no_escapes():
    from wfb.cli import _memory_share

    assert _memory_share(95.0, color=False) == "95.0%"


@pytest.mark.parametrize("value", ["auto", "always", "never"])
def test_every_subcommand_accepts_color(value, db):
    """Spot-check a representative handful, not all -- `--color` is added
    once in `_command`, so one broken subcommand would mean all of them are."""
    for args in (("devices", "--color", value), ("sources", "--color", value),
                 ("series", "--color", value)):
        result = run(*args)
        assert result.returncode == 0, (args, result.stdout + result.stderr)
