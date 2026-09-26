"""`progress` with `style: needle`: a gauge needle, the analog hands'
rotation machinery driven by a bound fraction instead of the clock.

The angle is `start_angle + fraction x sweep`, clockwise from 12 -- the
same mapping `style: arc` already draws its fill with -- and the needle is
authored like a hand: pointing at 12, the axis (`at:`) at the origin.
Each test pins one half of that: the generated angle line and rotated
parts, the preview's pixels at the needle's tip for two different
readings, and every key the style does not read being one error.
"""

from __future__ import annotations

import math

import pytest

from wfb import lint
from wfb.build import build as real_build
from wfb.build import load
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
  accent: "#FFAA00"
  red: "#FF0000"
elements:
"""

NEEDLE = """
  - id: gauge
    type: progress
    style: needle
    value: system.battery
    max: 100
    at: {anchor: center}
    start_angle: 240deg
    sweep: 240deg
    color: palette.accent
    needle:
      - shape: polygon
        points: [{dx: -2%r, dy: 8%r}, {dy: -80%r}, {dx: 2%r, dy: 8%r}]
      - {shape: circle, radius: 4%r, color: palette.fg}
"""


def _face(text, write_design, bag):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    return face


def _resolved(text, write_design, bag, db):
    face = _face(text, write_design, bag)
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


def _view(text, write_design, bag, db):
    face = _face(text, write_design, bag)
    device = db.get("fenix8solar47mm")
    files = generate(face, [device], write_design("").parent / "build",
                     {device.id: bake_fonts(face, device)}).files()
    return next(v for k, v in files.items() if k.endswith("View.mc"))


# -- codegen ---------------------------------------------------------------------


def test_the_angle_is_start_plus_fraction_times_sweep(write_design, bag, db):
    method = _view(BASE + NEEDLE, write_design, bag, db).split("function drawGauge")[1]
    method = method.split("\n    }")[0]
    start = sweep = repr(math.radians(240))
    assert (f"var angle = {start} + (WfbMath.percent(systemBattery, 100) / 100.0) * {sweep};"
            in method)
    assert "WfbGeom.fillRotated(dc, Layout.GAUGE_NEEDLE_0_POINTS, cx, cy, sin, cos);" in method
    assert "WfbGeom.fillCircleRotated(dc, Layout.GAUGE_NEEDLE_1_X" in method
    # a part's own colour, then back to none: one setColor per change
    assert method.index("Palette.ACCENT") < method.index("Palette.FG")


def test_a_fallback_substitutes_the_fraction(write_design, bag, db):
    text = BASE + NEEDLE.replace("value: system.battery", "value: heart_rate.current") \
        .replace("    max: 100\n", "    max: 200\n    when_absent: fallback\n    fallback: 0.5\n")
    method = _view(text, write_design, bag, db).split("function drawGauge")[1]
    assert "var fraction = 0.5f;" in method
    assert "+ (fraction) *" in method


# -- preview ---------------------------------------------------------------------


def _tip(resolved, fraction):
    """A pixel halfway along the needle (40%r from the axis, where the
    polygon is still ~2 px wide) for `fraction`."""
    placed = next(p for p in resolved.items if p.id == "gauge")
    angle = math.radians(240 + fraction * 240)
    length = 0.40 * resolved.device.width / 2
    return (round(placed.center[0] + length * math.sin(angle)),
            round(placed.center[1] - length * math.cos(angle)))


@pytest.mark.parametrize("battery", [10.0, 68.0])
def test_preview_points_the_needle_at_the_reading(write_design, bag, db, battery):
    """The tip lands where `start + fraction x sweep` says, and not where the
    other reading would put it -- must fail against a needle that ignores
    the value, or turns counter-clockwise."""
    resolved = _resolved(BASE + NEEDLE, write_design, bag, db)
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False,
                                            sample={"system.battery": battery}))
    here, other = _tip(resolved, battery / 100), _tip(resolved, (78 - battery) / 100)
    assert image.getpixel(here) == (0xFF, 0xAA, 0x00)
    assert image.getpixel(other) == (0, 0, 0)


# -- layout and lint ---------------------------------------------------------------


def test_the_extent_is_the_disc_the_needle_sweeps(write_design, bag, db):
    resolved = _resolved(BASE + NEEDLE, write_design, bag, db)
    placed = next(p for p in resolved.items if p.id == "gauge")
    assert placed.reach == pytest.approx(0.80 * resolved.device.width / 2, abs=2)
    assert placed.box.width == placed.box.height == round(2 * placed.reach)


def test_a_needle_parts_own_colour_reaches_the_palette_lint(write_design, bag):
    face = _face(BASE + NEEDLE, write_design, bag)
    labels = {role.label: role.expression.text for role in face.elements[0].color_roles()}
    assert labels["gauge.needle[1]"] == "palette.fg"


def test_off_screen_sees_a_needle_that_reaches_past_the_edge(write_design, bag, db):
    text = BASE + NEEDLE.replace("{dy: -80%r}", "{dy: -120%r}")
    resolved = _resolved(text, write_design, bag, db)
    lint.check_geometry(resolved, bag)
    assert any(d.code in ("off-screen", "safe-area") for d in bag.items), bag.render()


# -- refusals ----------------------------------------------------------------------


def _errors(text, write_design, bag):
    assert load(write_design(text), bag) is None
    return bag.errors


@pytest.mark.parametrize("key, line", [
    ("radius", "    radius: 40%r\n"),
    ("track_color", "    track_color: palette.fg\n"),
    ("align", "    align: left\n"),
])
def test_a_key_the_needle_does_not_read_is_an_error(write_design, bag, key, line):
    text = BASE + NEEDLE.replace("    color: palette.accent\n", f"    color: palette.accent\n{line}")
    errors = _errors(text, write_design, bag)
    assert any(f"'{key}:' is not read by 'style: needle'" in e.message for e in errors), \
        [e.message for e in errors]


def test_needle_on_an_arc_is_an_error(write_design, bag):
    text = BASE + """
  - id: ring
    type: progress
    style: arc
    value: system.battery
    max: 100
    radius: 40%r
    thickness: 3px
    start_angle: 0deg
    sweep: 360deg
    color: palette.fg
    needle: [{shape: circle, radius: 2%r}]
"""
    [error] = _errors(text, write_design, bag)
    assert "'needle:' is read only by 'style: needle'" in error.message


def test_a_needle_without_its_parts_is_a_schema_error(write_design, bag):
    text = BASE + NEEDLE.split("    needle:")[0]
    errors = _errors(text, write_design, bag)
    assert any("needle" in e.message for e in errors), [e.message for e in errors]


def test_a_part_with_no_colour_anywhere_is_an_error(write_design, bag):
    text = BASE + NEEDLE.replace("    color: palette.accent\n", "")
    errors = _errors(text, write_design, bag)
    assert any("no colour" in e.message for e in errors), [e.message for e in errors]


# -- a real build ------------------------------------------------------------------


@pytest.mark.slow
def test_a_needle_compiles_warning_free(write_design, db, tmp_path, toolchain):
    """All four part shapes, a data-driven element colour and a fallback
    fraction, through the real `monkeyc`, on a MIP and an older target."""
    text = BASE.replace("targets: [fenix8solar47mm]", "targets: [fenix8solar47mm, fr955]") + \
        NEEDLE + """
  - id: hr
    type: progress
    style: needle
    value: heart_rate.current
    max: 200
    at: {anchor: center, dy: 40%r}
    start_angle: 270deg
    sweep: 180deg
    color: "system.battery < 20 ? palette.red : palette.fg"
    when_absent: fallback
    fallback: 0.0
    needle:
      - {shape: line, to: {dy: -15%r}, thickness: 2px}
      - {shape: rectangle, at: {dy: 2%r}, size: {width: 2%r, height: 4%r}}
      - {shape: circle, radius: 2%r, filled: false, thickness: 1px}
"""
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert not [d for d in bag.items if d.severity.value in ("warning", "error")], bag.render()
