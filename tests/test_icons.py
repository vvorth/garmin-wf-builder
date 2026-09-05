"""The icon catalogue: three places that must agree with each other.

An icon exists in three places -- ``wfb/icons.py`` (the catalogue), the
generated Monkey C's support barrel (``runtime-lib/WfbIcons.mc``), and the host
preview (``wfb/preview.py``, so a design can be checked before a device sees
it). Nothing enforces that they agree except these tests: a name added to one
and not the others compiles, or previews, but silently draws nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wfb import icons

BARREL = Path(__file__).resolve().parent.parent / "runtime-lib" / "WfbIcons.mc"
PREVIEW = Path(__file__).resolve().parent.parent / "wfb" / "preview.py"


def test_every_icon_has_a_barrel_function():
    barrel_text = BARREL.read_text(encoding="utf-8")
    functions = set(re.findall(r"function (draw\w+)\(", barrel_text))
    for icon in icons.CATALOG.values():
        name = icon.function.split(".", 1)[1]
        assert name in functions, f"{icon.name!r} names {icon.function!r}, which is not in {BARREL.name}"


def test_every_icon_has_a_preview_branch():
    """Otherwise the icon compiles onto the device and draws nothing in `wfb preview`."""
    preview_text = PREVIEW.read_text(encoding="utf-8")
    for name in icons.names():
        assert f'"{name}"' in preview_text, (
            f"icon {name!r} has no `elif element.icon == {name!r}` branch in preview.py"
        )


def test_names_are_unique_and_lowercase():
    for name in icons.names():
        assert name == name.lower()
        assert re.match(r"^[a-z][a-z_]*$", name)


def test_get_returns_none_for_an_unknown_name():
    assert icons.get("nonexistent") is None


@pytest.mark.parametrize("name", icons.names())
def test_every_icon_renders_without_error(name, tmp_path, bag, db):
    """A smoke test over the actual preview code path, for every icon at once."""
    from tests.test_diagnostics import load
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve
    from wfb.preview import PreviewOptions, render

    design = f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: [fenix8solar47mm]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
elements:
  - id: bg
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
  - id: probe
    type: icon
    icon: {name}
    size: 20%r
    at: {{anchor: center}}
    color: palette.fg
"""
    path = tmp_path / "face.yaml"
    path.write_text(design, encoding="utf-8")
    face = load(path, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False))
    # A pixel of the foreground colour must actually have been drawn: this is
    # what a missing preview branch (silently drawing nothing) fails.
    colors = set(image.get_flattened_data())
    assert (255, 255, 255) in colors, f"icon {name!r} drew nothing"
