"""Plain helpers shared by several test modules; fixtures live in
`conftest.py`."""

from __future__ import annotations

from pathlib import Path

import pytest

from wfb.build import load

GOLDEN = Path(__file__).parent / "golden"


def find(resolved, element_id):
    """The placed item for ``element_id`` in a `ResolvedFace`."""
    return next(p for p in resolved.items if p.id == element_id)


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
