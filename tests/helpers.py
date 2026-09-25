"""Plain helpers shared by several test modules; fixtures live in
`conftest.py`."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from wfb.build import load

GOLDEN = Path(__file__).parent / "golden"
ROOT = Path(__file__).resolve().parent.parent


def find(resolved, element_id):
    """The placed item for ``element_id`` in a `ResolvedFace`."""
    return next(p for p in resolved.items if p.id == element_id)


def load_face(text: str, write_design, bag):
    """Load a design that must be accepted, and return its `Face`."""
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    return face


def load_errors(text: str, write_design) -> list:
    """Load a design into a fresh `Bag`, and return its errors, if any."""
    from wfb.diagnostics import Bag

    bag = Bag()
    load(write_design(text), bag)
    return [d for d in bag.items if d.severity.value == "error"]


def resolve_text(text: str, write_design, bag, db, device_id: str = "fenix8solar47mm"):
    """Load a design and resolve it for ``device_id``: ``(face, resolved)``."""
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = load_face(text, write_design, bag)
    device = db.get(device_id)
    return face, resolve(face, device, bake_fonts(face, device))


def lint_text(text: str, write_design, db, device_id: str = "fenix8solar47mm"):
    """Resolve a design for ``device_id``, run the per-device lint, and
    return the `Bag`."""
    from wfb import lint
    from wfb.diagnostics import Bag

    bag = Bag()
    _, resolved = resolve_text(text, write_design, bag, db, device_id)
    lint.run(resolved, bag)
    return bag


def fonts_design(fonts: str, elements: str, *, targets: str = "[fenix8solar47mm]") -> str:
    """A minimal design with a `fonts:` block -- the header the vector-text,
    outline and pattern-text test families share."""
    return f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: {targets}
palette: {{bg: "#000000", fg: "#FFFFFF"}}
fonts:
{fonts}
elements:
{elements}"""


def errors(text: str, bag, write_design) -> list:
    """Load a design that must be rejected, and return its errors."""
    face = load(write_design(text), bag)
    assert face is None
    return bag.errors


def resolve_design(path: Path, bag, db, device_id: str):
    """Load the design at ``path`` and resolve it for ``device_id``."""
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = load(path, bag)
    assert face is not None, bag.render()
    device = db.get(device_id)
    return resolve(face, device, bake_fonts(face, device))


def generate_for_targets(path: Path, out_dir: Path):
    """Generate the project for every installed target of the design at
    ``path`` -- what the golden-file tests compare against."""
    from wfb.devices import DeviceDatabase, DeviceError
    from wfb.diagnostics import Bag
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    bag = Bag()
    face = load(path, bag)
    assert face is not None, bag.render()
    try:
        db = DeviceDatabase.discover()
    except DeviceError as exc:
        pytest.skip(str(exc))
    ids = [d for d in face.targets if d in db.ids()]
    if not ids:
        pytest.skip("none of the design's targets are installed")
    devices = [db.get(d) for d in ids]
    baked = {d.id: bake_fonts(face, d) for d in devices}
    return generate(face, devices, out_dir, baked)


def compare_golden(pytestconfig, name: str, actual: str) -> None:
    """Assert ``actual`` equals `tests/golden/<name>`, or rewrite it under
    ``--update-golden``."""
    path = GOLDEN / name
    if pytestconfig.getoption("--update-golden"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
        return
    if not path.exists():
        pytest.fail(f"no golden file for {name}; run pytest --update-golden")
    expected = path.read_text(encoding="utf-8")
    assert actual == expected, f"{name} differs from its golden file"


def run_cli(*args: str, cwd: Path | None = None, env: dict | None = None,
            binary: bool = False) -> subprocess.CompletedProcess:
    """`wfb <args>` in this process -- `wfb.cli.main` with stdout and stderr
    captured, from `cwd` (the repository root by default), with `env` laid
    over `os.environ` -- returning what `subprocess.run` would. A pipe is
    not a TTY either way, so colour behaves the same as for a subprocess.
    `binary` leaves stdout and stderr as bytes, as `subprocess.run` without
    `text=True` does (`-o -` writes a PNG to stdout). A test of
    the entry point itself (`wfb.py`: re-exec, run from elsewhere) still
    needs a real subprocess."""
    from wfb import cli

    out, err = io.BytesIO(), io.BytesIO()
    streams = (io.TextIOWrapper(out, encoding="utf-8", write_through=True),
               io.TextIOWrapper(err, encoding="utf-8", write_through=True))
    saved_streams, saved_cwd, saved_env = (sys.stdout, sys.stderr), os.getcwd(), dict(os.environ)
    try:
        sys.stdout, sys.stderr = streams
        os.environ.update(env or {})
        os.chdir(cwd or ROOT)
        try:
            code = cli.main(list(args))
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    finally:
        for stream in streams:
            stream.flush()
        sys.stdout, sys.stderr = saved_streams
        os.chdir(saved_cwd)
        os.environ.clear()
        os.environ.update(saved_env)
    if binary:
        return subprocess.CompletedProcess(list(args), code, out.getvalue(), err.getvalue())
    return subprocess.CompletedProcess(list(args), code, out.getvalue().decode("utf-8"),
                                       err.getvalue().decode("utf-8"))


#: `example` and `resolved_example`'s session-wide caches.
_EXAMPLES: dict = {}
_RESOLVED_EXAMPLES: dict = {}


def example(path: Path):
    """``(face, load_diagnostics)`` for the design at ``path``, loaded once
    per test session. The face is shared: read it, never change it."""
    from wfb.diagnostics import Bag

    key = Path(path).resolve()
    if key not in _EXAMPLES:
        bag = Bag()
        _EXAMPLES[key] = (load(key, bag), tuple(bag.items))
    return _EXAMPLES[key]


def resolved_example(path: Path, db, device_id: str):
    """The design at ``path`` resolved for ``device_id``, once per test
    session -- the big examples take seconds each, and several modules ask
    for the same ones. Shared: read it, never change it."""
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    key = (Path(path).resolve(), device_id)
    if key not in _RESOLVED_EXAMPLES:
        face, _ = example(path)
        device = db.get(device_id)
        _RESOLVED_EXAMPLES[key] = resolve(face, device, bake_fonts(face, device))
    return _RESOLVED_EXAMPLES[key]
