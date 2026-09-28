"""Driving the Connect IQ simulator.

The simulator is a GUI application.  On macOS it is the SDK's
``ConnectIQ.app`` bundle, started with ``open``; on Linux it is the bare
``simulator`` binary, which needs a display, a GTK stack and a WebKit build
that is now several distribution releases old.  This module starts it when it
is not already up, pushes a built ``.prg`` with ``monkeydo``, and, where the
simulator cannot run, says so precisely rather than failing obscurely, pointing
at :mod:`wfb.preview`, which renders the same resolved geometry with no
toolchain at all.

The simulator is found by its TCP port, not by process name: ``monkeydo``
reaches it on the first of 127.0.0.1:1234-1238 that answers
(``ShellUtils.findSimulatorPort`` in ``bin/monkeybrains.jar``), so a port that
answers is exactly the condition a push needs, on every OS.

``monkeydo`` does not return once the app is loaded.  It stays connected,
printing the app's ``System.println`` output, until the app or the simulator
exits, and it prints nothing when the load succeeds.  :func:`push` therefore
runs it in the background, logging to a file, and calls the push good once
it has survived a short settle window with the simulator still up.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from .build import Toolchain

SIMULATOR_PORTS = range(1234, 1239)
"""The ports ``monkeydo`` tries, in order (``ShellUtils.findSimulatorPort``)."""

IS_MAC = sys.platform == "darwin"


class SimulatorError(RuntimeError):
    def __init__(self, message: str, hints: list[str] | None = None) -> None:
        super().__init__(message)
        self.hints = hints or []


def simulator_port() -> int | None:
    """The port a running simulator answers on, or ``None``."""
    for port in SIMULATOR_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return port
        except OSError:
            continue
    return None


def is_running() -> bool:
    return simulator_port() is not None


def launch(toolchain: Toolchain, *, wait: float = 45.0) -> None:
    """Start the simulator if it is not already up, and wait until it
    accepts a push."""
    if is_running():
        return
    if IS_MAC:
        _launch_mac(toolchain)
    else:
        _launch_linux(toolchain)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if is_running():
            return
        time.sleep(0.3)
    if IS_MAC:
        raise SimulatorError(
            f"the simulator did not start within {wait:.0f} s",
            hints=["open it once by hand to see why -- the first launch after an SDK",
                   "update can stop on a macOS security prompt:",
                   f"  open -a \"{_mac_bundle(toolchain)}\""],
        )
    raise SimulatorError("the simulator did not start", hints=_missing_library_hints(toolchain))


def _mac_bundle(toolchain: Toolchain) -> Path:
    return toolchain.sdk / "bin" / "ConnectIQ.app"


def _launch_mac(toolchain: Toolchain) -> None:
    bundle = _mac_bundle(toolchain)
    if not bundle.exists():
        raise SimulatorError(
            f"{bundle} not found",
            hints=["CIQ_SDK should name the SDK Manager's own install:",
                   "  ~/Library/Application Support/Garmin/ConnectIQ/Sdks/connectiq-sdk-mac-*",
                   "./tools/setup-env.sh prints the export for it"],
        )
    process = subprocess.run(["open", "-a", str(bundle)], capture_output=True, text=True,
                             check=False)
    if process.returncode != 0:
        raise SimulatorError(process.stderr.strip() or f"`open` could not start {bundle.name}")


def _launch_linux(toolchain: Toolchain) -> None:
    binary = toolchain.sdk / "bin" / "simulator"
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


@dataclass
class Session:
    """A ``monkeydo`` left running against the simulator, and its log."""

    process: subprocess.Popen[bytes]
    log: Path

    def follow(self) -> Iterator[str]:
        """Yield the app's console output as it arrives, until ``monkeydo``
        exits -- when the app does, or the simulator closes."""
        with self.log.open(encoding="utf-8", errors="replace") as stream:
            while True:
                chunk = stream.read()
                if chunk:
                    yield chunk
                elif self.process.poll() is not None:
                    return
                else:
                    time.sleep(0.2)

    def stop(self) -> None:
        """Disconnect ``monkeydo`` and the ``shell`` it drives."""
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def push(toolchain: Toolchain, prg: Path, device_id: str, *, settle: float = 6.0) -> Session:
    """Send a built ``.prg`` to the simulator, starting it first if need be.

    ``monkeydo``'s output goes to ``simulator.log`` beside the ``.prg``.  The
    returned :class:`Session` is still attached; leaving it running keeps the
    app's console going to that log until the app is replaced or the
    simulator closes."""
    if toolchain is None:
        raise SimulatorError("no Connect IQ SDK found; set CIQ_SDK")
    launch(toolchain)
    log = prg.parent / "simulator.log"
    with log.open("wb") as sink:
        process = subprocess.Popen(
            [str(toolchain.sdk / "bin" / "monkeydo"), str(prg), device_id],
            stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    session = Session(process, log)
    deadline = time.monotonic() + settle
    while time.monotonic() < deadline:
        code = process.poll()
        if not is_running():
            session.stop()
            raise SimulatorError("the simulator exited while loading the app",
                                 hints=_crash_hints(toolchain))
        if code is not None:
            if code != 0:
                output = log.read_text(encoding="utf-8", errors="replace").strip()
                raise SimulatorError(output.splitlines()[-1] if output else
                                     f"monkeydo failed (exit {code})",
                                     hints=_monkeydo_hints(output))
            return session
        time.sleep(0.25)
    return session


def _monkeydo_hints(output: str) -> list[str]:
    if "Java Runtime" in output or "java: command not found" in output:
        return ["monkeydo needs a Java runtime on PATH (`wfb doctor` checks for one)"]
    if "not properly signed" in output:
        return ["the simulator rejected the signature: build again with the same "
                "developer key (`--key`)"]
    return []


def _crash_hints(toolchain: Toolchain) -> list[str]:
    if IS_MAC:
        return ["the simulator's own crash report is in Console.app, under Crash Reports"]
    return [
        "this is an environment problem, not a problem with the built face:",
        "it reproduces with an unmodified SDK sample .prg on Linux",
        "(docs/limitations.md, \"The simulator crashes when an app is pushed\")",
    ] + _missing_library_hints(toolchain)


def screenshot(path: Path) -> tuple[Path, str | None]:
    """Capture the simulator window, returning the file and, when only a
    fallback capture was possible, a note saying what was captured instead."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if IS_MAC:
        return _screenshot_mac(path)
    return _screenshot_x11(path), None


def _screenshot_mac(path: Path) -> tuple[Path, str | None]:
    window = _mac_simulator_window()
    if window is not None:
        subprocess.run(["screencapture", "-x", "-o", f"-l{window}", str(path)], check=True)
        return path, None
    subprocess.run(["screencapture", "-x", str(path)], check=True)
    return path, "the simulator window was not found, so this is the whole screen"


# Picks the simulator's largest on-screen, normal-layer window by owning pid.
# kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements == 17;
# kCGNullWindowID is a C macro JXA cannot see, so it is spelled 0.
_WINDOW_JXA = """
ObjC.import('CoreGraphics');
function run(argv) {
  var pid = parseInt(argv[0], 10);
  var windows = ObjC.deepUnwrap(ObjC.castRefToObject(
      $.CGWindowListCopyWindowInfo(17, 0)));
  var best = '', area = 0;
  windows.forEach(function (w) {
    if (w.kCGWindowOwnerPID !== pid || w.kCGWindowLayer !== 0) return;
    var size = w.kCGWindowBounds.Width * w.kCGWindowBounds.Height;
    if (size > area) { area = size; best = String(w.kCGWindowNumber); }
  });
  return best;
}
"""


def _mac_simulator_window() -> int | None:
    """The CoreGraphics window number of the simulator, found through the pid
    listening on its port, or ``None``."""
    port = simulator_port()
    if port is None or not shutil.which("lsof") or not shutil.which("osascript"):
        return None
    owner = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                           capture_output=True, text=True, check=False)
    pids = owner.stdout.split()
    if not pids:
        return None
    found = subprocess.run(["osascript", "-l", "JavaScript", "-e", _WINDOW_JXA, pids[0]],
                           capture_output=True, text=True, check=False)
    number = found.stdout.strip()
    return int(number) if number.isdigit() else None


def _screenshot_x11(path: Path) -> Path:
    tool = shutil.which("import") or shutil.which("xwd")
    if tool is None:
        raise SimulatorError(
            "no X capture tool found",
            hints=["install imagemagick (`import`) or x11-apps (`xwd`)"],
        )
    if tool.endswith("import"):
        subprocess.run([tool, "-window", "root", str(path)], check=True)
    else:
        raw = path.with_suffix(".xwd")
        subprocess.run([tool, "-root", "-out", str(raw)], check=True)
        subprocess.run(["convert", str(raw), str(path)], check=True)
        raw.unlink(missing_ok=True)
    return path


def _missing_library_hints(toolchain: Toolchain) -> list[str]:
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
