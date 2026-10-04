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
    """Whether ``pid`` runs: neither gone nor a zombie. One read of its
    state, so a process reaped between two looks is never taken for alive."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0]
    except OSError:                     # gone, or going while read
        return False
    return state != "Z"                 # a zombie waits only to be reaped


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
    # long enough for a loaded machine to start the child and write its pid
    with pytest.raises(subprocess.TimeoutExpired):
        run(["sh", "-c", script], cwd=tmp_path, timeout=3)
    assert time.monotonic() - started < 15
    written = pid_file.read_text().strip() if pid_file.exists() else ""
    assert written, "the script was stopped before it started its child"
    child = int(written)
    deadline = time.monotonic() + 5
    while (alive := _alive(child)) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not alive, "the command's own child outlived the timeout"

