"""Driving the Connect IQ simulator.

The simulator is a GUI application: it needs a display, a GTK stack and, on
Linux, a WebKit build that is now several distribution releases old.  Where that
is available this module launches it and pushes a built ``.prg`` with
``monkeydo``; where it is not, it says so precisely rather than failing
obscurely, and points at :mod:`wfb.preview`, which renders the same resolved
geometry with no toolchain at all.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path


class SimulatorError(RuntimeError):
    def __init__(self, message: str, hints: list[str] | None = None) -> None:
        super().__init__(message)
        self.hints = hints or []


def is_running() -> bool:
    return subprocess.run(["pgrep", "-x", "simulator"], capture_output=True).returncode == 0


def launch(toolchain, *, wait: float = 8.0) -> None:
    """Start the simulator if it is not already up."""
    if is_running():
        return
    binary = toolchain.sdk / "bin" / "connectiq"
    if not binary.exists():
        raise SimulatorError(f"{binary} not found")
    if not os.environ.get("DISPLAY"):
        raise SimulatorError(
            "no DISPLAY is set, and the Connect IQ simulator is a GUI application",
            hints=["run it on a desktop session, or under Xvfb:",
                   "  Xvfb :99 -screen 0 1400x1000x24 &  DISPLAY=:99 wfb simulate ..."],
        )
    subprocess.Popen([str(binary)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if is_running():
            return
        time.sleep(0.3)
    raise SimulatorError("the simulator did not start", hints=_missing_library_hints(toolchain))


def push(toolchain, prg: Path, device_id: str, *, timeout: float = 120.0) -> None:
    """Send a built ``.prg`` to a running simulator."""
    if toolchain is None:
        raise SimulatorError("no Connect IQ SDK found; set CIQ_SDK")
    launch(toolchain)
    process = subprocess.run(
        [str(toolchain.sdk / "bin" / "monkeydo"), str(prg), device_id],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    if not is_running():
        raise SimulatorError(
            "the simulator exited while loading the app",
            hints=[
                "this is an environment problem, not a problem with the built face:",
                "it reproduces with an unmodified SDK sample .prg",
                "software OpenGL under Xvfb is the usual cause",
            ] + _missing_library_hints(toolchain),
        )
    if process.returncode != 0:
        raise SimulatorError(process.stderr.strip() or "monkeydo failed")


def screenshot(path: Path) -> Path:
    """Capture the simulator window from the current display."""
    tool = shutil.which("import") or shutil.which("xwd")
    if tool is None:
        raise SimulatorError(
            "no X capture tool found",
            hints=["install imagemagick (`import`) or x11-apps (`xwd`)"],
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    if tool.endswith("import"):
        subprocess.run([tool, "-window", "root", str(path)], check=True)
    else:
        raw = path.with_suffix(".xwd")
        subprocess.run([tool, "-root", "-out", str(raw)], check=True)
        subprocess.run(["convert", str(raw), str(path)], check=True)
        raw.unlink(missing_ok=True)
    return path


def _missing_library_hints(toolchain) -> list[str]:
    """Report shared libraries the simulator binary cannot resolve."""
    binary = toolchain.sdk / "bin" / "simulator"
    if not binary.exists() or not shutil.which("ldd"):
        return []
    result = subprocess.run(["ldd", str(binary)], capture_output=True, text=True, check=False)
    missing = sorted({
        line.split("=>")[0].strip()
        for line in result.stdout.splitlines()
        if "not found" in line
    })
    if not missing:
        return []
    return [f"unresolved shared libraries: {', '.join(missing)}"]
