"""The `wfb new` templates.

A template is a promise: whatever it produces compiles cleanly on every target it
declares.  Both of the bugs these tests guard were found *by* writing the
templates, because the slice example happened not to exercise them.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

from tests.test_diagnostics import load
from wfb import lint
from wfb.cli import TEMPLATE_DIR
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve

TEMPLATES = sorted(p.stem for p in TEMPLATE_DIR.glob("*.yaml"))


def materialise(tmp_path: Path, name: str) -> Path:
    """Do what `wfb new` does: substitute the placeholders."""
    text = (TEMPLATE_DIR / f"{name}.yaml").read_text(encoding="utf-8")
    text = text.replace("__UUID__", str(uuid.uuid4())).replace("__NAME__", "Test Face")
    path = tmp_path / f"{name}.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_there_is_at_least_one_template():
    assert TEMPLATES


@pytest.mark.parametrize("name", TEMPLATES)
def test_template_has_placeholders(name):
    """`wfb new` must give every face its own id -- a shared one makes the watch
    treat two faces as the same app, so installing the second replaces the first."""
    text = (TEMPLATE_DIR / f"{name}.yaml").read_text(encoding="utf-8")
    assert "__UUID__" in text and "__NAME__" in text


@pytest.mark.parametrize("name", TEMPLATES)
def test_template_is_clean_on_every_target(tmp_path, bag, db, name):
    """No errors *and no warnings*: a template with a warning teaches the warning."""
    design = materialise(tmp_path, name)
    face = load(design, bag)
    assert face is not None, bag.render()
    lint.check_permissions(face, bag)
    for device_id in face.targets:
        if device_id not in db.ids():
            continue
        device = db.get(device_id)
        resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
        lint.run(resolved, bag)
    noisy = [d for d in bag.items if d.severity.value in ("error", "warning")]
    assert not noisy, bag.render()


@pytest.mark.parametrize("name", TEMPLATES)
def test_template_uses_proportional_units(tmp_path, name):
    """Offsets should be proportional, or the template teaches the wrong habit.

    A bare pixel offset is identical on the 47 mm and wrong on the 51 mm, which is
    the single easiest way to write a design that silently does not travel.
    """
    text = (TEMPLATE_DIR / f"{name}.yaml").read_text(encoding="utf-8")
    # The lookahead has to reject a partial match too: without `[\d.]` in it the
    # pattern happily matches the "3" inside "30%r" by backtracking.
    offsets = re.findall(r"\b(?:dx|dy|radius):\s*(-?[\d.]+)(?![\d.]|\s*%)", text)
    assert not offsets, f"{name} uses bare pixel offsets: {offsets}"


@pytest.mark.slow
@pytest.mark.parametrize("name", TEMPLATES)
def test_template_compiles(tmp_path, bag, db, name):
    from wfb.build import Toolchain, build

    toolchain = Toolchain.discover()
    if toolchain is None or not toolchain.key.exists():
        pytest.skip("no Connect IQ SDK or developer key")
    design = materialise(tmp_path, name)
    result = build(design, output=tmp_path / "build", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    assert result.products, "nothing was compiled"


# -- the worked examples ----------------------------------------------------

EXAMPLES = sorted((Path(__file__).resolve().parent.parent / "examples").glob("*/face.yaml"))


@pytest.mark.parametrize("design", EXAMPLES, ids=lambda p: p.parent.name)
def test_example_is_clean_on_every_target(design, bag, db):
    """An example is copied verbatim, so a warning in one teaches the warning."""
    from wfb import lint

    face = load(design, bag)
    assert face is not None, bag.render()
    lint.check_permissions(face, bag)
    for device_id in face.targets:
        if device_id not in db.ids():
            continue
        device = db.get(device_id)
        resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
        lint.run(resolved, bag)
    noisy = [d for d in bag.items if d.severity.value in ("error", "warning")]
    assert not noisy, bag.render()


@pytest.mark.slow
@pytest.mark.parametrize("design", EXAMPLES, ids=lambda p: p.parent.name)
def test_example_compiles(design, tmp_path, bag, db):
    from wfb.build import Toolchain, build

    toolchain = Toolchain.discover()
    if toolchain is None or not toolchain.key.exists():
        pytest.skip("no Connect IQ SDK or developer key")
    result = build(design, output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    assert len(result.products) == len(result.devices)
