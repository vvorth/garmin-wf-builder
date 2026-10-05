#!/usr/bin/env python3
"""Capture every design the fast test suite loads, as a corpus for the
TypeScript port's parity (`tools/oracle.py` dumps its load stages).

    ./.venv/bin/python tools/capture_designs.py

The test suite writes thousands of small designs, most of them written to
hit one diagnostic, which the example faces never do. This runs the fast
suite with `WFB_CAPTURE_DESIGNS` set; `tests/conftest.py` then calls
`install`, which wraps `wfb.build.load` so each text it loads is written to
`.cache/test-designs/<id>/<its file name>` (gitignored; `<id>/.design`
holds that name), next to an empty
stand-in for every file beside the original, so a `fonts:` entry's
`source:` exists exactly when it existed in the test. Loading never reads
a font, so an empty file is enough.

The suite's own result does not matter here, only what it loaded: the
capture runs whether tests pass or fail.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".cache" / "test-designs"
#: The file in a capture's directory naming its design, the rest being stand-ins.
DESIGN = ".design"
#: A directory with more files than this beside the design (the repository
#: root, say) gets no stand-ins: no test's fonts live there.
MAX_SIBLINGS = 200


def _siblings(directory: Path, design: Path) -> list[str]:
    found: list[str] = []
    for path in directory.rglob("*"):
        if len(found) > MAX_SIBLINGS:
            return []
        if path.is_file() and path != design and "__pycache__" not in path.parts:
            found.append(path.relative_to(directory).as_posix())
    return sorted(found)


def capture(root: Path, path: Path, text: str | None) -> None:
    """Write one loaded design, and stand-ins for the files beside it."""
    if text is None:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
    siblings = _siblings(path.parent, path) if path.parent.is_dir() else []
    key = hashlib.sha256("\0".join([path.name, text, *siblings]).encode("utf-8")).hexdigest()[:16]
    where = root / key
    if where.exists():
        return
    where.mkdir(parents=True)
    for name in siblings:
        stand_in = where / name
        stand_in.parent.mkdir(parents=True, exist_ok=True)
        stand_in.touch()
    (where / path.name).write_text(text, encoding="utf-8")
    (where / DESIGN).write_text(path.name, encoding="utf-8")


def install(root: Path) -> None:
    """Wrap `wfb.build.load` so every design it loads is captured under `root`."""
    import wfb.build as build

    original = build.load

    def load(path: Path, bag: Any, text: str | None = None, node: Any = None) -> Any:
        try:
            capture(root, Path(path), text)
        except OSError:
            pass
        return original(path, bag, text, node)

    build.load = load  # type: ignore[assignment]


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    env = dict(os.environ, WFB_CAPTURE_DESIGNS=str(OUT))
    subprocess.run([sys.executable, "-m", "pytest", "-m", "not slow", "-q", "-p", "no:cacheprovider"],
                   cwd=ROOT, env=env, check=False)
    count = sum(1 for _ in OUT.iterdir()) if OUT.exists() else 0
    print(f"capture_designs: {count} designs in {OUT.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
