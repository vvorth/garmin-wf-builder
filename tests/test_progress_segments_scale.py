"""`progress` with `style: segments` and `style: scale`, each on an arc or a
bar track.

`segments` lights `round(fraction x count)` cells; `scale` draws the track,
its coloured bands, and a dot at the value. The preview tests sample the
rendered pixels where one cell or the pointer must (and must not) be, so
they fail against an off-by-one lit count or a pointer that ignores the
reading; the codegen tests pin the generated loop and constants.
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
  track: "#555555"
  ok: "#00AA00"
  bad: "#FF0000"
elements:
"""

ARC_SEGMENTS = """
  - id: gauge
    type: progress
    style: segments
    value: system.battery
    max: 100
    at: {anchor: center}
    radius: 80%r
    thickness: 8%r
    start_angle: 0deg
    sweep: 360deg
    count: 10
    gap: 4px
    color: palette.fg
    track_color: palette.track
"""

BAR_SEGMENTS = """
  - id: gauge
    type: progress
    style: segments
    value: system.battery
    max: 100
    at: {anchor: center}
    size: {width: 60%, height: 10%}
    count: 5
    gap: 4px
    color: palette.fg
"""

ARC_SCALE = """
  - id: gauge
    type: progress
    style: scale
    value: system.battery
    max: 100
    at: {anchor: center}
    radius: 70%r
    thickness: 3px
    start_angle: 240deg
    sweep: 240deg
    color: palette.fg
    track_color: palette.track
    bands: [{to: 0.25, color: palette.bad}, {to: 0.5, color: palette.ok}]
"""

BAR_SCALE = """
  - id: gauge
    type: progress
    style: scale
    value: system.battery
    max: 100
    at: {anchor: center}
    size: {width: 60%, height: 4%}
    color: palette.fg
    track_color: palette.track
"""


def _face(text, write_design, bag):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    return face


def _resolved(text, write_design, bag, db):
    face = _face(text, write_design, bag)
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


def _method(text, write_design, bag, db):
    face = _face(text, write_design, bag)
    device = db.get("fenix8solar47mm")
    files = generate(face, [device], write_design("").parent / "build",
                     {device.id: bake_fonts(face, device)}).files()
    view = next(v for k, v in files.items() if k.endswith("View.mc"))
    return view.split("function drawGauge")[1].split("\n    }")[0]


def _render(resolved, battery):
    return render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False,
                                           sample={"system.battery": battery}))


def _gauge(resolved):
    return next(p for p in resolved.items if p.id == "gauge")


# -- segments --------------------------------------------------------------------


def test_arc_segments_loop_over_every_cell_lit_or_track(write_design, bag, db):
    method = _method(BASE + ARC_SEGMENTS, write_design, bag, db)
    assert "var lit = ((WfbMath.percent(systemBattery, 100) / 100.0) * 10 + 0.5).toNumber();" \
        in method
    assert "for (var i = 0; i < 10; i++)" in method
    assert "dc.setColor((i < lit) ? Palette.FG : Palette.TRACK" in method
    assert "Layout.GAUGE_START - i * Layout.GAUGE_STEP, Layout.GAUGE_CELL" in method


def test_segments_with_no_track_draw_only_the_lit_cells(write_design, bag, db):
    method = _method(BASE + BAR_SEGMENTS, write_design, bag, db)
    assert "for (var i = 0; i < lit; i++)" in method
    assert "(i * Layout.GAUGE_STEP + Layout.GAUGE_CELL).toNumber()" in method


@pytest.mark.parametrize("battery, lit", [(34.0, 3), (36.0, 4), (95.0, 10)])
def test_preview_lights_the_rounded_number_of_arc_cells(write_design, bag, db, battery, lit):
    """34% of 10 rounds to 3 cells and 36% to 4 -- the cell just past the
    last lit one must be track-coloured, the last lit one white."""
    resolved = _resolved(BASE + ARC_SEGMENTS, write_design, bag, db)
    placed = _gauge(resolved)
    image = _render(resolved, battery)

    def cell_pixel(index):
        angle = math.radians(index * placed.step + placed.cell / 2)
        return (round(placed.center[0] + placed.radius * math.sin(angle)),
                round(placed.center[1] - placed.radius * math.cos(angle)))

    assert image.getpixel(cell_pixel(lit - 1)) == (255, 255, 255)
    if lit < 10:
        assert image.getpixel(cell_pixel(lit)) == (0x55, 0x55, 0x55)


def test_bar_cells_leave_their_gaps_empty(write_design, bag, db):
    resolved = _resolved(BASE + BAR_SEGMENTS, write_design, bag, db)
    placed = _gauge(resolved)
    image = _render(resolved, 100.0)
    y = placed.box.y + placed.box.height // 2
    first_cell_end = placed.box.x + int(placed.cell)
    assert image.getpixel((placed.box.x + 1, y)) == (255, 255, 255)
    assert image.getpixel((first_cell_end + 1, y)) == (0, 0, 0)


def test_a_gap_that_leaves_no_cell_is_an_error(write_design, bag, db):
    resolved = _resolved(BASE + BAR_SEGMENTS.replace("gap: 4px", "gap: 60px"), write_design,
                         bag, db)
    lint.run(resolved, bag)
    assert any(d.code == "progress-segments" for d in bag.errors), bag.render()


# -- scale -----------------------------------------------------------------------


def test_scale_bands_are_layout_spans_and_the_pointer_follows_the_value(write_design, bag, db):
    method = _method(BASE + ARC_SCALE, write_design, bag, db)
    assert "Layout.GAUGE_BAND_0_START, Layout.GAUGE_BAND_0_SWEEP" in method
    assert "Layout.GAUGE_BAND_1_START, Layout.GAUGE_BAND_1_SWEEP" in method
    assert "Math.round(Layout.GAUGE_RADIUS * Math.sin(angle)).toNumber()" in method
    placed = _gauge(_resolved(BASE + ARC_SCALE, write_design, bag, db))
    assert placed.band_spans == ((240.0, 60.0), (300.0, 60.0))


@pytest.mark.parametrize("battery", [20.0, 80.0])
def test_preview_puts_the_pointer_at_the_reading(write_design, bag, db, battery):
    resolved = _resolved(BASE + ARC_SCALE, write_design, bag, db)
    placed = _gauge(resolved)
    image = _render(resolved, battery)

    def at(fraction):
        angle = math.radians(240 + fraction * 240)
        return (placed.center[0] + round(placed.radius * math.sin(angle)),
                placed.center[1] - round(placed.radius * math.cos(angle)))

    assert image.getpixel(at(battery / 100)) == (255, 255, 255)
    assert image.getpixel(at(1 - battery / 100)) != (255, 255, 255)


def test_a_bar_scale_grows_its_box_to_hold_the_pointer(write_design, bag, db):
    placed = _gauge(_resolved(BASE + BAR_SCALE, write_design, bag, db))
    assert placed.rect is not None
    assert placed.box.x == placed.rect.x - placed.pointer
    assert placed.box.width == placed.rect.width + 2 * placed.pointer


# -- refusals ----------------------------------------------------------------------


def _errors(text, write_design, bag):
    assert load(write_design(text), bag) is None
    return bag.errors


def test_count_on_an_arc_style_is_an_error(write_design, bag):
    text = BASE + ARC_SCALE.replace("style: scale", "style: arc").replace(
        "    bands: [{to: 0.25, color: palette.bad}, {to: 0.5, color: palette.ok}]\n",
        "    count: 5\n")
    [error] = _errors(text, write_design, bag)
    assert "'count:' is read only by 'style: segments'" in error.message


def test_bands_must_increase(write_design, bag):
    text = BASE + ARC_SCALE.replace("{to: 0.5, color: palette.ok}", "{to: 0.2, color: palette.ok}")
    [error] = _errors(text, write_design, bag)
    assert "bands[1]" in error.message and "greater than" in error.message


def test_an_arc_and_a_bar_at_once_is_an_error(write_design, bag):
    text = BASE + ARC_SEGMENTS.replace("    count: 10\n", "    count: 10\n    size: {width: 10%}\n")
    [error] = _errors(text, write_design, bag)
    assert "not both" in error.message


def test_a_partial_arc_names_the_missing_keys(write_design, bag):
    text = BASE + ARC_SEGMENTS.replace("    sweep: 360deg\n", "")
    [error] = _errors(text, write_design, bag)
    assert "'sweep'" in error.message


# -- a real build ------------------------------------------------------------------


@pytest.mark.slow
def test_every_style_and_track_compiles_warning_free(write_design, db, tmp_path, toolchain):
    text = BASE.replace("targets: [fenix8solar47mm]", "targets: [fenix8solar47mm, fr955]")
    for index, design in enumerate((ARC_SEGMENTS, BAR_SEGMENTS, ARC_SCALE,
                                    BAR_SCALE.replace("    track_color: palette.track\n",
                                                      "    bands: [{to: 0.2, color: palette.bad}]\n"))):
        text += design.replace("id: gauge", f"id: gauge{index}").replace(
            "at: {anchor: center}", f"at: {{anchor: center, dy: {index * 10 - 15}%r}}") \
            + "    lint: {allow: [contrast, static-overlap, safe-area, off-screen], reason: \"a test design\"}\n"
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert not [d for d in bag.items if d.severity.value in ("warning", "error")], bag.render()
