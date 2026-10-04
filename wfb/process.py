"""Running a tool that may hang, so that stopping it stops all of it.

`monkeyc` is a shell script that runs `java` as its child, and `wfb
studio` builds by running `wfb build`, which runs `monkeyc` in turn.
`subprocess.run(timeout=...)` kills only the process it started, which
leaves the JVM running, with its 1 GB heap, after the build reported it
stopped. `run` starts the command in its own process group and kills the
whole group instead.
"""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path


def run(command: list[str], *, cwd: Path | str | None = None,
        timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    """``command``'s output and exit code, as `subprocess.run` with
    `capture_output` and `text` gives them. On a timeout, or when the
    caller is interrupted (its own process group no longer passes Ctrl+C
    on), the command and everything it started are killed and the
    exception is raised."""
    with subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, start_new_session=True) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            _kill_group(process)
            process.communicate()
            raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _kill_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:          # the group has already gone
        pass
