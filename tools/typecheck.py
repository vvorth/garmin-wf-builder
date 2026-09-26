#!/usr/bin/env python3
"""Run `mypy --strict` over the compiler and compare it with the baseline.

ADR 0001 names `mypy --strict` as the safeguard for Python's lack of
exhaustiveness checking over IR node types. The codebase predates the
check, so `tests/mypy-baseline.txt` records every error it reported when
the check was introduced. This script and `tests/test_typecheck.py` (the
`typecheck` test set) fail on any error the baseline does not hold, and on
any baseline entry that no longer occurs, so the baseline can only shrink:

    ./.venv/bin/python tools/typecheck.py            # report; exit 1 on a difference
    ./.venv/bin/python tools/typecheck.py --update   # rewrite the baseline

A baseline entry is `path: [code] message`, without the line number, so
editing a file does not churn it. The same entry may appear more than once:
the count is what is compared.

The configuration (`mypy.ini`), mypy itself and the type information of
the libraries `wfb/` imports decide the result. mypy and the jsonschema
stubs are pinned in `requirements-dev.txt`; Pillow and ruamel.yaml ship
their own types and are only lower-bounded, so a newer release can move
the result. The baseline records every one of those versions, and a
failing check names any that differ from the ones installed.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "mypy-baseline.txt"
CONFIG = ROOT / "mypy.ini"

_ERROR = re.compile(
    r"^(?P<path>[^:\s][^:]*):(?P<line>\d+)(?::\d+)?: error: (?P<message>.*?)"
    r"(?:  \[(?P<code>[a-z0-9-]+)\])?$")


@dataclass(frozen=True)
class Error:
    path: str
    line: int
    code: str
    message: str

    @property
    def key(self) -> str:
        """The baseline's line-number-free form of this error."""
        return f"{self.path}: [{self.code}] {self.message}"

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.code}] {self.message}"


class TypecheckError(RuntimeError):
    """mypy is missing, or stopped before checking anything."""


def parse(output: str) -> list[Error]:
    """Every `error:` line of mypy's plain output; notes are dropped."""
    errors = []
    for line in output.splitlines():
        match = _ERROR.match(line.strip())
        if match is not None:
            errors.append(Error(match["path"].replace("\\", "/"), int(match["line"]),
                                match["code"] or "misc", match["message"]))
    return errors


#: The distributions whose version decides what mypy reports.
TYPED_DISTRIBUTIONS = ("mypy", "types-jsonschema", "pillow", "ruamel.yaml", "jsonschema")


def versions() -> dict[str, str]:
    """The installed version of each of `TYPED_DISTRIBUTIONS`."""
    from importlib.metadata import PackageNotFoundError, version
    out = {}
    for name in TYPED_DISTRIBUTIONS:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = "not installed"
    return out


def run() -> list[Error]:
    """Run mypy as `mypy.ini` configures it and return its errors."""
    if importlib.util.find_spec("mypy") is None:
        raise TypecheckError("mypy is not installed in this interpreter -- "
                             "install requirements-dev.txt")
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--config-file", str(CONFIG),
         "--no-pretty", "--no-color-output", "--no-error-summary", "--show-error-codes"],
        cwd=ROOT, capture_output=True, text=True, check=False)
    # 0: clean, 1: type errors. Anything else is mypy itself failing (a bad
    # config, a module it could not even parse), which no baseline covers.
    if result.returncode not in (0, 1):
        raise TypecheckError(f"mypy exited {result.returncode}:\n{result.stdout}{result.stderr}")
    errors = parse(result.stdout)
    if result.returncode == 1 and not errors:
        raise TypecheckError(f"mypy failed but reported no parseable error:\n{result.stdout}")
    return errors


def load_baseline(path: Path = BASELINE) -> Counter[str]:
    """The baseline's entries, counted; `#` lines are comments."""
    if not path.exists():
        return Counter()
    return Counter(line for line in path.read_text(encoding="utf-8").splitlines()
                   if line.strip() and not line.startswith("#"))


def baseline_versions(path: Path = BASELINE) -> dict[str, str]:
    """The versions the baseline was written with, from its `# using` header."""
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# using "):
                name, _, version = line.removeprefix("# using ").partition(" ")
                out[name] = version.strip()
    return out


def version_note(path: Path = BASELINE) -> str:
    """A line naming every version that differs from the baseline's, or ''."""
    recorded, installed = baseline_versions(path), versions()
    differ = [f"{name} {recorded.get(name, '?')} -> {installed[name]}"
              for name in TYPED_DISTRIBUTIONS if recorded.get(name) != installed[name]]
    if not differ:
        return ""
    return "note: installed versions differ from the baseline's: " + ", ".join(differ)


def compare(errors: list[Error], baseline: Counter[str]) -> tuple[list[Error], Counter[str]]:
    """`(new, fixed)`: every occurrence of an entry reported more often than
    the baseline allows, and the baseline entries no longer reported (with
    how many fewer times)."""
    current = Counter(error.key for error in errors)
    over = {key for key, count in current.items() if count > baseline[key]}
    new = [error for error in errors if error.key in over]
    fixed = baseline - current
    return new, fixed


def format_baseline(errors: list[Error], using: dict[str, str]) -> str:
    lines = [
        "# Known `mypy --strict` errors, one per occurrence, without line numbers.",
        "# Written by `tools/typecheck.py --update`; only ever shrink it by hand.",
        *(f"# using {name} {version}" for name, version in using.items()),
    ]
    lines.extend(sorted(error.key for error in errors))
    return "\n".join(lines) + "\n"


def report(new: list[Error], fixed: Counter[str], baseline: Counter[str]) -> str:
    """What differs from the baseline, worded for a failing test or the CLI."""
    out = []
    if new:
        keys = Counter(error.key for error in new)
        out.append(f"{len(keys)} error kind(s) not in the baseline "
                   "(each occurrence listed; the baseline allows the count shown):")
        for error in new:
            out.append(f"  {error}  (baseline allows {baseline[error.key]})")
    if fixed:
        out.append(f"{sum(fixed.values())} baseline entr(ies) no longer reported -- "
                   "run `tools/typecheck.py --update` to shrink the baseline:")
        out.extend(f"  {key}" + (f"  (x{count})" if count > 1 else "")
                   for key, count in sorted(fixed.items()))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--update", action="store_true",
                        help="rewrite tests/mypy-baseline.txt from this run")
    args = parser.parse_args(argv)
    try:
        errors = run()
    except TypecheckError as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.update:
        before = sum(load_baseline().values())
        BASELINE.write_text(format_baseline(errors, versions()), encoding="utf-8")
        print(f"baseline: {before} -> {len(errors)} error(s)")
        return 0
    baseline = load_baseline()
    new, fixed = compare(errors, baseline)
    if not new and not fixed:
        print(f"ok -- {len(errors)} error(s), all in the baseline")
        return 0
    print(report(new, fixed, baseline))
    note = version_note()
    if note:
        print(note)
    return 1


if __name__ == "__main__":
    sys.exit(main())
