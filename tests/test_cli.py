"""The command line, and the environment check an unfamiliar caller starts with."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "wfb.py"


def run(*args: str, cwd: Path | None = None, python: str | None = None):
    """Invoke the entry point the way an outside caller would: by path."""
    return subprocess.run(
        [python or sys.executable, str(ENTRY), *args],
        capture_output=True, text=True, cwd=str(cwd or ROOT), check=False,
    )


def test_doctor_reports_a_working_environment(db):
    result = run("doctor")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ready" in result.stdout


def test_doctor_names_what_is_missing_rather_than_failing_obscurely(tmp_path):
    """An unfamiliar caller's first command has to explain itself."""
    import os

    env = dict(os.environ, WFB_DEVICES=str(tmp_path / "nothing-here"), HOME=str(tmp_path))
    env.pop("CIQ_SDK", None)
    result = subprocess.run(
        [sys.executable, str(ENTRY), "doctor"],
        capture_output=True, text=True, env=env, cwd=str(ROOT), check=False,
    )
    assert result.returncode == 1
    assert "not ready" in result.stdout
    # It must say *why* the devices cannot simply be downloaded, or the caller
    # will burn a round trying.
    assert "401" in result.stdout
    assert "Connect IQ SDK" in result.stdout


def test_the_entry_point_works_from_an_unrelated_directory(tmp_path, db):
    """The commonest way to reach this tool is an absolute path from elsewhere."""
    result = run("devices", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "fenix8solar47mm" in result.stdout


def test_the_entry_point_finds_its_own_interpreter(tmp_path, db):
    """`python3 wfb.py` must work even when that python lacks the dependencies.

    An arbitrary agent reaches for whatever python is on PATH; making that work
    is cheaper than explaining virtualenvs in every set of instructions.
    """
    bare = "/usr/bin/python3"
    if not Path(bare).exists():
        pytest.skip("no system python to test against")
    probe = subprocess.run(
        [bare, "-c", "import ruamel.yaml"], capture_output=True, check=False
    )
    if probe.returncode == 0:
        pytest.skip("the system python already has the dependencies")
    result = run("devices", cwd=tmp_path, python=bare)
    assert result.returncode == 0, result.stderr
    assert "fenix8solar47mm" in result.stdout


def test_new_lists_its_templates():
    result = run("new", "--list")
    assert result.returncode == 0
    assert "dashboard" in result.stdout and "minimal" in result.stdout


def test_new_refuses_to_overwrite(tmp_path):
    (tmp_path / "taken.yaml").write_text("existing", encoding="utf-8")
    result = run("new", "Taken", "-o", str(tmp_path / "taken.yaml"))
    assert result.returncode == 1
    assert "already exists" in result.stderr
    assert (tmp_path / "taken.yaml").read_text(encoding="utf-8") == "existing"


def test_new_gives_every_face_its_own_id(tmp_path):
    """Two faces sharing an id are one app to the watch: installing the second
    replaces the first."""
    import re

    ids = []
    for name in ("One", "Two"):
        path = tmp_path / f"{name}.yaml"
        assert run("new", name, "-o", str(path)).returncode == 0
        ids.append(re.search(r"id: (\S+)", path.read_text(encoding="utf-8")).group(1))
    assert ids[0] != ids[1]
    assert "__UUID__" not in ids


def test_schema_path_points_at_a_real_file():
    result = run("schema", "--path")
    assert result.returncode == 0
    assert Path(result.stdout.strip()).exists()


# -- `wfb help` -------------------------------------------------------------


def test_bare_help_matches_the_help_flag():
    """`wfb help` with no topic is another spelling of `wfb --help` -- same
    text, but exit 0 rather than --help's own exit 0 too (unlike bare `wfb`
    with no command at all, which is a usage error and exits 2)."""
    via_help = run("help")
    via_flag = run("--help")
    assert via_help.returncode == 0
    assert via_flag.returncode == 0
    assert via_help.stdout == via_flag.stdout


def test_bare_command_is_still_a_usage_error():
    result = run()
    assert result.returncode == 2


def test_leading_help_topic_matches_the_commands_own_help_flag():
    """`wfb help build` == `wfb build --help`."""
    via_topic = run("help", "build")
    via_flag = run("build", "--help")
    assert via_topic.returncode == 0
    assert via_flag.returncode == 0
    assert via_topic.stdout == via_flag.stdout


def test_trailing_help_word_matches_the_commands_own_help_flag():
    """`wfb build help` -- help as the trailing word after the command,
    rewritten to `--help` before argparse ever sees it -- also matches."""
    via_trailing = run("build", "help")
    via_flag = run("build", "--help")
    assert via_trailing.returncode == 0
    assert via_trailing.stdout == via_flag.stdout


def test_help_rejects_an_unknown_topic_and_lists_real_commands():
    result = run("help", "nope")
    assert result.returncode == 1
    assert "no such command 'nope'" in result.stderr
    assert "build" in result.stderr and "validate" in result.stderr


def test_every_command_help_is_sourced_from_its_own_docstring():
    """The single-source-of-truth guarantee: nothing hand-duplicates a
    command's help text as a separate string anywhere -- `_command()` reads
    it straight from the handler's docstring, and this pins that down so a
    future edit cannot quietly reintroduce a diverging help= string."""
    import inspect

    from wfb.cli import _parser, _subparsers

    parser = _parser()
    for name, subparser in _subparsers(parser).items():
        handler = subparser.get_default("handler")
        assert handler is not None, name
        doc = inspect.getdoc(handler)
        assert doc, f"{name} has no docstring to source help from"
        assert subparser.description == doc, name
