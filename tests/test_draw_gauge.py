"""`type: gauge` as a draw program (`wfb.kinds.progress.ProgressKind.lower`):
the fill fraction computed as the watch computes it, a bar filled exactly as
far as `dc.fillRectangle` fills it, segments lit by the fraction, a slot's
pick and `max: auto` scaled by their twins, and a needle's ring through the
barrel."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from tests.helpers import find, resolved_example
from wfb import kinds, preview
from wfb.draw import evaluator
from wfb.draw.jsonform import to_json
from wfb.draw.printer import print_ops
from wfb.draw.program import (
    Bin, Call, Conv, Disagreement, DrawContext, FloatLit, Lit, Paren, Part,
)
from wfb.emit.monkeyc.common import NO_AOD
from wfb.emit.writer import Writer

ALIGN = Path("examples/features/align/face.yaml")
PROGRESS = Path("examples/features/progress/face.yaml")
SLOTS = Path("examples/features/slot-gauge/face.yaml")
OUTLINED = Path("tests/fixtures/outline_pattern_gauge/face.yaml")
DEVICE = "fenix8solar47mm"


def _renderer(resolved, scale: int = 2, **values: object) -> preview.Renderer:
    options = preview.PreviewOptions(scale=scale)
    sample = preview.sample_values(resolved, options, None)
    sample.update(values)
    image = Image.new("RGB", (resolved.device.width * scale, resolved.device.height * scale))
    return preview.Renderer(resolved, ImageDraw.Draw(image), image, scale, sample, options)


def _printed(resolved, placed, guards: tuple[str, ...] = ()) -> str:
    w = Writer()
    print_ops(w, kinds.for_placed(placed).lower(DrawContext(resolved, NO_AOD, guards), placed))
    return w.render()


def _painted(resolved, placed, **values: object) -> preview.Renderer:
    renderer = _renderer(resolved, **values)
    renderer.render_element(placed)
    return renderer


# -- the arithmetic ---------------------------------------------------------------


def test_a_chain_is_read_the_way_monkey_c_parses_the_printed_text():
    """`Layout.W * WfbMath.percent(v, m) / 100.0` is ``(W * pct) / 100.0`` on
    the watch, whatever tree printed it: 100 * 29 / 100.0 truncates to 29,
    where 100 * (29 / 100.0) is 28.999... and truncates to 28."""
    tree = Conv(Paren(Bin("*", Lit(100), Bin("/", Lit(29), FloatLit(100.0)))), "toNumber")
    assert evaluator.num_value(tree) == 29
    assert evaluator.num_value(Bin("+", Lit(1), Bin("*", Lit(2), Lit(3)))) == 7


def test_two_numbers_divide_as_monkey_c_numbers_do():
    """`/` of two `Number`s truncates toward zero, and a `Float` makes it a
    float division."""
    assert evaluator.num_value(Bin("/", Lit(7), Lit(2))) == 3
    assert evaluator.num_value(Bin("/", Lit(-7), Lit(2))) == -3
    assert evaluator.num_value(Bin("/", Lit(7), FloatLit(2.0))) == 3.5


def test_the_fill_fraction_is_the_barrels_percent():
    """`WfbMath.percent`'s twin clamps to 0..100 and takes a goal at or
    below zero as 0."""
    call = Call("WfbMath.percent", (Lit(150), Lit(100)))
    assert evaluator.num_value(call) == 100.0
    assert evaluator.num_value(Call("WfbMath.percent", (Lit(5), Lit(0)))) == 0.0


# -- what it paints ---------------------------------------------------------------


def test_a_bar_fills_exactly_the_pixels_the_watch_fills(db):
    """`dc.fillRectangle(X, Y, filled, H)` covers columns X .. X+filled-1:
    the fill's last preview column is fill, the next is track."""
    resolved = resolved_example(ALIGN, db, DEVICE)
    bar = find(resolved, "steps_bar")
    painted = _painted(resolved, bar)
    box, s = bar.inner_box, painted.scale
    filled = int(box.width * 8432 / 10000)  # the sample steps against the sample goal
    y = (box.y + box.height // 2) * s
    fill = painted.color(bar.element.color)
    track = painted.color(bar.element.track_color)
    assert painted.image.getpixel(((box.x + filled) * s - 1, y)) == fill
    assert painted.image.getpixel(((box.x + filled) * s, y)) == track


@pytest.mark.parametrize("battery, lit", [(68.0, 7), (64.0, 6)])
def test_segments_light_as_many_cells_as_the_fraction_rounds_to(db, battery, lit):
    """Ten cells on an arc, `(fraction * count + 0.5).toNumber()` of them in
    `color:` and the rest in `track_color:`, one colour per cell."""
    resolved = resolved_example(PROGRESS, db, DEVICE)
    cells = find(resolved, "battery_segments")
    renderer = _renderer(resolved, **{"system.battery": battery})
    ops, _ = to_json(renderer, cells)
    colors = [tuple(op["rgb"]) for op in ops if op["op"] == "color"]
    assert [op["op"] for op in ops].count("arc") == 10
    accent = renderer.color(cells.element.color)
    track = renderer.color(cells.element.track_color)
    assert colors == [accent] * lit + [track] * (10 - lit)


def test_max_auto_with_no_reading_keeps_its_track(db):
    """The preview has no sample reading for a fixed complication: the
    complication is there, so its scale is, and `absent: hide` keeps the
    track with nothing on it (`docs/guide/progress-and-graphs.md`)."""
    resolved = resolved_example(SLOTS, db, DEVICE)
    bar = find(resolved, "battery_bar")
    assert "complication.battery" not in preview.SAMPLE
    painted = _painted(resolved, bar)
    colors = {c for _, c in painted.image.getcolors(1 << 20)}
    assert painted.color(bar.element.track_color) in colors
    assert painted.color(bar.element.color) not in colors


def test_max_auto_with_a_reading_fills_against_its_own_scale(db):
    """The contrast: a battery of 50 against its own 0-100 scale fills half."""
    resolved = resolved_example(SLOTS, db, DEVICE)
    bar = find(resolved, "battery_bar")
    painted = _painted(resolved, bar, **{"complication.battery": 50})
    box, s = bar.inner_box, painted.scale
    y = (box.y + box.height // 2) * s
    half = box.width // 2
    assert painted.image.getpixel(((box.x + half) * s - 1, y)) == painted.color(bar.element.color)
    assert painted.image.getpixel(((box.x + half) * s, y)) == painted.color(
        bar.element.track_color)


def test_a_slot_gauge_waits_for_the_editor_and_draws_its_default_pick(db):
    resolved = resolved_example(SLOTS, db, DEVICE)
    ring = find(resolved, "top_ring")
    code = _printed(resolved, ring)
    assert "if (_pulsing != " in code
    assert "WfbScale.fraction(pulled, scale)" in code
    painted = _painted(resolved, ring)
    assert painted.image.getbbox() is not None


def test_a_slot_gauge_whose_pick_has_no_scale_draws_nothing(db):
    """`right` defaults to the date, which has no scale: the needle hides."""
    resolved = resolved_example(SLOTS, db, DEVICE)
    needle = find(resolved, "right_needle")
    assert _painted(resolved, needle).image.getbbox() is None


def test_a_needles_ring_goes_through_the_barrel(db):
    """Each part rings through `WfbRing`/`WfbRingWide`; a filled circle part
    rings as itself grown, which the preview still stamps (a
    `Disagreement`, until the ring question is measured)."""
    resolved = resolved_example(OUTLINED, db, DEVICE)
    needle = find(resolved, "needle")
    code = _printed(resolved, needle)
    assert "WfbRingWide.rotated(" in code
    assert "_RADIUS + 2" in code
    ops = kinds.for_placed(needle).lower(DrawContext(resolved, NO_AOD), needle)
    disagreements = [op for op in ops if isinstance(op, Disagreement)]
    assert len(disagreements) == 1
    watch, = disagreements[0].watch
    assert isinstance(watch, Part) and watch.part.shape == "circle" and not watch.stamp
