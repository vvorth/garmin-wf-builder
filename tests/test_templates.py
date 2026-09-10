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


# -- the schema's own hygiene -------------------------------------------------


def test_every_schema_def_is_referenced():
    """A `$defs` entry nothing points at is dead weight that drifts silently.

    `commonElement` sat here for several phases: defined, never `$ref`'d, and
    every element branch repeated its properties by hand -- so a change to one
    copy (the `on_hold:` description, most recently) reached six other places
    only if someone remembered.  Extracting the shared properties fixed the
    duplication; this keeps a replacement from accumulating unnoticed.
    """
    import json

    from wfb.validate import SCHEMA_PATH

    text = SCHEMA_PATH.read_text(encoding="utf-8")
    schema = json.loads(text)
    unreferenced = [name for name in schema["$defs"]
                    if f'#/$defs/{name}"' not in text]
    assert not unreferenced, (
        "these $defs are defined but never referenced: " + ", ".join(unreferenced)
        + " -- either point something at them or delete them"
    )


def test_the_element_branches_share_one_definition_of_each_common_property():
    """`on_hold:` and friends are defined once, not once per element type.

    The 2026-09 review found `on_hold:`'s description hand-copied across seven
    branches.  `visible:` (added later) got a shared `$defs` entry from the
    start; this asserts the rest followed, so a seventh element type cannot
    reintroduce the drift by copy-pasting a sixth.
    """
    import json

    from wfb.validate import SCHEMA_PATH

    defs = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["$defs"]
    branches = [name for name in defs if name.endswith("Element")]
    assert branches, "no element branches found -- has the schema been restructured?"
    shared = ("z", "on_tap", "on_hold", "static", "visible", "overrides", "antialias")
    for branch in branches:
        for prop in shared:
            body = defs[branch].get("properties", {}).get(prop)
            if body is None:
                continue
            assert list(body) == ["$ref"], (
                f"{branch}.{prop} is defined inline; it must be a $ref so every "
                f"element type shares one description"
            )
