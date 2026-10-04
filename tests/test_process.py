"""`wfb.process.run`: a command stopped on a timeout is stopped with
everything it started, as `monkeyc` (a shell script running `java`) needs."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from wfb.process import run


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # a zombie still answers until its parent reaps it
    stat = Path(f"/proc/{pid}/stat")
    return not (stat.is_file() and stat.read_text().split(") ", 1)[1].startswith("Z"))


def test_output_and_exit_code_come_back(tmp_path):
    done = run(["sh", "-c", "echo out; echo err >&2; exit 3"], cwd=tmp_path)
    assert (done.returncode, done.stdout, done.stderr) == (3, "out\n", "err\n")


def test_a_timeout_kills_the_command_and_what_it_started(tmp_path):
    """The script starts a child the way `monkeyc` starts `java`: not by
    `exec`, so killing the script alone would leave the child running. The
    child's output goes elsewhere, so no wait on a shared pipe can hide an
    orphan by outliving it."""
    pid_file = tmp_path / "child.pid"
    script = f"sleep 30 >/dev/null 2>&1 & echo $! > {pid_file}; wait"
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run(["sh", "-c", script], cwd=tmp_path, timeout=0.5)
    assert time.monotonic() - started < 10
    child = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while _alive(child) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(child), "the command's own child outlived the timeout"
