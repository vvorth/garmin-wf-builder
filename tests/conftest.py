"""Shared fixtures.

Tests are split by what they need:

* everything in ``test_units``, ``test_expr``, ``test_formatting``, ``test_fonts``
  and ``test_schema`` needs nothing but Python;
* ``test_layout``, ``test_lint`` and ``test_golden`` need the **device files**,
  which cannot be downloaded, so they skip cleanly when absent rather than
  failing in an environment that never had them.

Nothing here needs the Garmin toolchain: the compiler is testable in CI, which
is the point of stages 1-3 not touching ``monkeyc`` (ADR 0003).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wfb.devices import DeviceDatabase, DeviceError  # noqa: E402

#: The device the golden files are generated for.
GOLDEN_DEVICE = "fenix8solar47mm"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def db() -> DeviceDatabase:
    try:
        database = DeviceDatabase.discover()
    except DeviceError as exc:
        pytest.skip(f"device definitions unavailable: {exc}")
    if GOLDEN_DEVICE not in database.ids():
        pytest.skip(f"{GOLDEN_DEVICE} is not installed")
    return database


@pytest.fixture(scope="session")
def device(db):
    return db.get(GOLDEN_DEVICE)


@pytest.fixture
def bag():
    from wfb.diagnostics import Bag

    return Bag()


@pytest.fixture
def write_design(tmp_path):
    """Write a YAML design to a temp file and return its path."""

    def _write(text: str, name: str = "face.yaml") -> Path:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    return _write


MINIMAL = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
"""


@pytest.fixture
def minimal() -> str:
    return MINIMAL


def pytest_addoption(parser):
    parser.addoption(
        "--update-golden", action="store_true", default=False,
        help="rewrite the golden files from the current generator output",
    )


@pytest.fixture(autouse=True)
def _run_from_repo_root(monkeypatch):
    """Generated headers name the design relative to the working directory, so
    tests must run from a fixed one or the golden files would not be stable."""
    monkeypatch.chdir(ROOT)


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: needs the Garmin toolchain and runs monkeyc")
