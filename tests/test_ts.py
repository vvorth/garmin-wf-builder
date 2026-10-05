"""The TypeScript package in ts/: its own tests and its type check, run from
the fast suite so one command keeps both halves green.

Both need a Node that runs `.ts` sources directly (type stripping: an
official Node 22.18+ or 24, which ./tools/setup-env.sh installs). Without
one these tests fail rather than skip, as the rasteriser's do.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

TS = Path(__file__).resolve().parent.parent / "ts"


def node() -> str:
    found = shutil.which("node")
    if found is None:
        pytest.fail("Node is needed for ts/: run ./tools/setup-env.sh -- this test fails rather than skips")
    probe = subprocess.run([found, "--input-type=module-typescript", "-e", "const n: number = 0"],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.fail(f"{found} cannot run TypeScript (it does not strip types): run "
                    f"./tools/setup-env.sh, which installs an official Node 24\n{probe.stderr}")
    return found


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    if not (TS / "node_modules").is_dir():
        pytest.fail("ts/node_modules is missing: run ./tools/setup-env.sh (or npm ci in ts/)")
    return subprocess.run(args, cwd=TS, capture_output=True, text=True)


def test_the_typescript_tests_pass() -> None:
    result = run([node(), "--test", "test/**/*.test.ts"])
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]


def test_the_typescript_package_typechecks() -> None:
    node()
    result = run([str(TS / "node_modules" / ".bin" / "tsc"), "-p", "."])
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
