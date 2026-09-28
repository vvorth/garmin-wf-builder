"""`wfb.simulate` against a stand-in simulator: a TCP listener on one of the
ports `monkeydo` probes, and a fake SDK whose `monkeydo` (and, for the macOS
path, `open` on PATH) are small shell scripts.  No Garmin binary runs."""

from __future__ import annotations

import socket
import stat
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from wfb import simulate
from wfb.build import Toolchain
from wfb.simulate import SimulatorError


class FakeSimulator:
    """Accepts and drops connections on the first free simulator port."""

    def __init__(self) -> None:
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        for port in simulate.SIMULATOR_PORTS:
            try:
                self.server.bind(("127.0.0.1", port))
                break
            except OSError:
                continue
        else:
            pytest.skip("every simulator port is taken")
        self.port = self.server.getsockname()[1]
        self.server.listen()
        self.server.settimeout(0.1)
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._closed.is_set():
            try:
                connection, _ = self.server.accept()
                connection.close()
            except OSError:
                continue

    def close(self, after: float = 0.0) -> None:
        """Stop listening, now or ``after`` seconds from now."""
        def stop() -> None:
            time.sleep(after)
            self._closed.set()
            self._thread.join()
            self.server.close()
        if after:
            threading.Thread(target=stop, daemon=True).start()
        else:
            stop()


def _script(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def sdk(tmp_path: Path) -> Toolchain:
    root = tmp_path / "sdk"
    _script(root / "bin" / "monkeyc", "exit 0\n")
    return Toolchain(root, tmp_path / "key.der")


@pytest.fixture
def prg(tmp_path: Path) -> Path:
    path = tmp_path / "build" / "fr955" / "face.prg"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")
    return path


@pytest.fixture
def no_simulator() -> Iterator[None]:
    if simulate.is_running():
        pytest.skip("something is already listening on a simulator port")
    yield


def test_the_simulator_is_found_by_its_port(no_simulator: None) -> None:
    assert simulate.simulator_port() is None
    fake = FakeSimulator()
    try:
        assert simulate.simulator_port() == fake.port
    finally:
        fake.close()


def test_a_push_returns_while_monkeydo_stays_attached(
        no_simulator: None, sdk: Toolchain, prg: Path) -> None:
    """`monkeydo` never exits while the app runs; the push must not wait
    for it, and the app's console output must reach the log."""
    _script(sdk.sdk / "bin" / "monkeydo", 'echo "hello from $2"\nexec sleep 60\n')
    fake = FakeSimulator()
    try:
        started = time.monotonic()
        session = simulate.push(sdk, prg, "fr955", settle=1.0)
        assert time.monotonic() - started < 10
        assert session.process.poll() is None
        assert session.log == prg.parent / "simulator.log"
        assert "hello from fr955" in session.log.read_text(encoding="utf-8")
        session.stop()
        assert session.process.wait(timeout=5) != 0
        assert "".join(session.follow()) == "hello from fr955\n"
    finally:
        fake.close()


def test_a_monkeydo_failure_is_reported_with_its_own_message(
        no_simulator: None, sdk: Toolchain, prg: Path) -> None:
    _script(sdk.sdk / "bin" / "monkeydo",
            'echo "Unable to connect to simulator."\nexit 1\n')
    fake = FakeSimulator()
    try:
        with pytest.raises(SimulatorError, match="Unable to connect to simulator"):
            simulate.push(sdk, prg, "fr955", settle=3.0)
    finally:
        fake.close()


def test_a_simulator_that_dies_during_the_push_is_reported(
        no_simulator: None, sdk: Toolchain, prg: Path) -> None:
    _script(sdk.sdk / "bin" / "monkeydo", "exec sleep 60\n")
    fake = FakeSimulator()
    fake.close(after=0.5)
    with pytest.raises(SimulatorError, match="exited while loading"):
        simulate.push(sdk, prg, "fr955", settle=5.0)


def test_macos_opens_the_app_bundle_and_needs_no_display(
        no_simulator: None, sdk: Toolchain, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    (sdk.sdk / "bin" / "ConnectIQ.app").mkdir(parents=True)
    calls = tmp_path / "open.calls"
    fakebin = tmp_path / "fakebin"
    _script(fakebin / "open", f'echo "$@" > "{calls}"\n')
    monkeypatch.setenv("PATH", f"{fakebin}:/usr/bin:/bin")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(simulate, "IS_MAC", True)
    fake: list[FakeSimulator] = []
    original = simulate.subprocess.run

    def run_then_listen(*args: object, **kwargs: object) -> object:
        result = original(*args, **kwargs)  # type: ignore[call-overload]
        fake.append(FakeSimulator())
        return result

    monkeypatch.setattr(simulate.subprocess, "run", run_then_listen)
    try:
        simulate.launch(sdk, wait=5.0)
        assert calls.read_text(encoding="utf-8").split() == [
            "-a", str(sdk.sdk / "bin" / "ConnectIQ.app")]
    finally:
        for server in fake:
            server.close()


def test_macos_without_the_app_bundle_says_where_the_sdk_should_be(
        no_simulator: None, sdk: Toolchain, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(simulate, "IS_MAC", True)
    with pytest.raises(SimulatorError, match="ConnectIQ.app not found") as raised:
        simulate.launch(sdk, wait=1.0)
    assert any("connectiq-sdk-mac" in hint for hint in raised.value.hints)


def test_linux_without_a_display_says_so(
        no_simulator: None, sdk: Toolchain, monkeypatch: pytest.MonkeyPatch) -> None:
    _script(sdk.sdk / "bin" / "simulator", "exit 0\n")
    monkeypatch.setattr(simulate, "IS_MAC", False)
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(SimulatorError, match="no DISPLAY"):
        simulate.launch(sdk, wait=1.0)
