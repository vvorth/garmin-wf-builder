#!/usr/bin/env python3
"""Entry point: ``python3 /path/to/wfb.py build design.yaml``.

Re-executes itself under the project's own virtualenv when the interpreter it
was started with cannot import the dependencies.  That makes the command work
whichever ``python`` happens to be on a caller's PATH -- which matters because
the commonest way to reach this tool is an absolute path from a working
directory that has nothing to do with the repository.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

#: Set on the child so a broken virtualenv cannot cause an exec loop.
_GUARD = "WFB_REEXEC"


def _venv_python() -> Path | None:
    for candidate in (
        ROOT / ".venv" / "bin" / "python",
        ROOT / ".venv" / "Scripts" / "python.exe",  # Windows
    ):
        if candidate.exists():
            return candidate
    return None


def _dependencies_present() -> bool:
    from importlib.util import find_spec

    try:
        return all(find_spec(m) is not None for m in ("ruamel.yaml", "jsonschema", "PIL"))
    except (ImportError, ValueError):
        return False


def _bootstrap() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if _dependencies_present() or os.environ.get(_GUARD):
        return

    interpreter = _venv_python()
    if interpreter is None:
        print(
            "wfb: the host dependencies are not installed for "
            f"{sys.executable}.\n"
            f"     run {ROOT / 'tools' / 'setup-env.sh'} to create .venv, or\n"
            f"     pip install -r {ROOT / 'requirements.txt'}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    os.environ[_GUARD] = "1"
    os.execv(str(interpreter), [str(interpreter), str(Path(__file__).resolve()), *sys.argv[1:]])


_bootstrap()

from wfb.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
