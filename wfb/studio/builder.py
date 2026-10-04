"""Building a face from the editor: `wfb build` for one watch, as a
subprocess, so a hung `monkeyc` cannot take the editor down with it.

The face's directory is copied first, so an edit made while it builds
does not reach a half-read project; the `.prg` is kept until the editor
stops, for the browser to download. One build runs at a time: `monkeyc`
uses every core.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .bundle import FACE

#: `wfb.py`, run by the same Python the editor runs under.
WFB = Path(__file__).resolve().parents[2] / "wfb.py"
#: Long enough for the largest face on a slow machine; a hung `monkeyc` is
#: stopped after it.
TIMEOUT = 600

#: The build command for a face, a watch and an output directory.
Command = Callable[[Path, str, Path], list[str]]


def wfb_build(face: Path, device: str, output: Path) -> list[str]:
    return [sys.executable, str(WFB), "build", str(face), "-d", device, "-o", str(output),
            "--color", "never"]


class BuildBusy(RuntimeError):
    """Another build is running."""


@dataclass
class Build:
    """One finished build: whether it succeeded, its log, its `.prg`, and
    the line `wfb build` reports its memory on."""

    id: str
    device: str
    version: int
    ok: bool
    log: str
    prg: Path | None = None
    name: str | None = None
    memory: str | None = None
    seconds: float = 0.0


class Builder:
    def __init__(self, command: Command = wfb_build, timeout: float = TIMEOUT) -> None:
        self.command = command
        self.timeout = timeout
        self.root = Path(tempfile.mkdtemp(prefix="wfb-studio-builds-"))
        self._running = threading.Lock()
        self._done: dict[str, Build] = {}

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def get(self, build_id: str) -> Build | None:
        return self._done.get(build_id)

    def stage(self, source: Path) -> Path:
        """A copy of the face's directory (`face.yaml` and its files) to
        build from: quick, so the caller can take it while holding the
        editor's lock and build after releasing it."""
        work = self.root / uuid.uuid4().hex
        shutil.copytree(source, work / "face")
        return work

    def run(self, work: Path, device: str, version: int, stem: str) -> Build:
        """Build the staged face in ``work`` for ``device``; raises
        `BuildBusy` while another build runs."""
        import time

        if not self._running.acquire(blocking=False):
            shutil.rmtree(work, ignore_errors=True)
            raise BuildBusy("a build is already running; wait for it to finish")
        try:
            build_id = work.name
            started = time.monotonic()
            try:
                done = subprocess.run(self.command(work / "face" / FACE, device, work / "out"),
                                      capture_output=True, text=True, timeout=self.timeout, check=False,
                                      cwd=work)
                log = (done.stdout + ("\n" + done.stderr if done.stderr else "")).strip()
                ok = done.returncode == 0
            except subprocess.TimeoutExpired:
                log, ok = f"the build took longer than {self.timeout:g} s and was stopped", False
            seconds = time.monotonic() - started
            prgs = sorted((work / "out").glob(f"*/*-{device}.prg")) if ok else []
            prg = prgs[0] if prgs else None
            memory = next((m.group(1) for m in re.finditer(
                r"^built\s+\S+\s+(.+)$", log, re.M)), None)
            build = Build(build_id, device, version, ok and prg is not None, log, prg,
                          f"{stem}-{device}.prg", memory, seconds)
            if ok and prg is None:
                build.log += "\n\nthe build reported success but left no .prg"
            self._done[build_id] = build
            shutil.rmtree(work / "face", ignore_errors=True)
            return build
        finally:
            self._running.release()
