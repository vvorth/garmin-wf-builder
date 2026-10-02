"""`wfb.draw.barrel`: the barrel's arithmetic, transcribed, and checked two ways.

1. The `.mc` source still says what is transcribed (`WfbArc`, `WfbGeom`,
   `WfbMath`, `WfbScale`, `WfbSeries`, `WfbRing`): each rule-carrying
   statement is looked up in the real file.
2. Swept against an independent model of what the watch draws, fed the
   argument the watch is given -- for an arc, the Garmin start angle in its
   `Layout` constant, not the author's angle.  The evaluator draws from these
   functions, so a sweep that passes means the preview covers the degrees
   and pixels the watch does.

A sweep is only worth having if it catches a broken twin, so each one is
also run against the twin it replaces and seen to fail (the half-degree arc
start: research 27 §2.5).
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from wfb.draw import barrel
from wfb.layout import garmin_arc
from tests.helpers import author_arc_span as arc_span

RUNTIME = Path(__file__).resolve().parent.parent / "runtime-lib"


def _source(name: str) -> str:
    return re.sub(r"\s+", " ", (RUNTIME / name).read_text(encoding="utf-8"))


# -- 1. the transcription is of the real files --------------------------------


@pytest.mark.parametrize("name,statements", [
    ("WfbArc.mc", (
        "if (fraction <= 0.0 || radius <= 0) { return; }",
        "var swept = sweepDegrees * ((fraction > 1.0) ? 1.0 : fraction);",
        "drawSpan(dc, cx, cy, radius, penWidth, startDegrees, swept);",
        "if (radius <= 0) { return; }",
        "var sweep = roundAway(sweepDegrees);",
        "if (sweep == 0) { return; }",
        "if (sweep > 360) { sweep = 360; }",
        "if (sweep < -360) { sweep = -360; }",
        "var start = roundAway(startDegrees) % 360;",
        "if (start < 0) { start += 360; }",
        "var end = (start - sweep) % 360;",
        "if (end < 0) { end += 360; }",
        "? Graphics.ARC_CLOCKWISE : Graphics.ARC_COUNTER_CLOCKWISE;",
        "dc.drawArc(cx, cy, radius, direction, start, end);",
        "? (degrees - 0.5).toNumber() : (degrees + 0.5).toNumber();",
    )),
    ("WfbGeom.mc", (
        "return Math.floor(cx + x * cos - y * sin + 0.5).toNumber();",
        "return Math.floor(cy + x * sin + y * cos + 0.5).toNumber();",
        "out[i] = [cx + x * cos - y * sin, cy + x * sin + y * cos];",
        "dc.fillCircle(cx + x * cos - y * sin, cy + x * sin + y * cos, r);",
    )),
    ("WfbMath.mc", (
        "if (goal <= 0) { return 0.0; }",
        "var pct = 100.0 * value.toFloat() / goal.toFloat();",
        "return clamp(pct, 0.0, 100.0) as Float;",
    )),
    ("WfbScale.mc", (
        "var low = scale[0].toFloat();",
        "var full = (reading.toFloat() - low) / (scale[1].toFloat() - low);",
        "if (full < 0.0) { return 0.0; }",
        "return (full > 1.0) ? 1.0 : full;",
    )),
    ("WfbSeries.mc", (
        "if (span <= 0.0) { span = 1.0; }",
        "if (v == null) { havePrevious = false; continue; }",
        "var cx = x + (i * w / (n - 1));",
        "var cy = y + h - ((v - lo) * h / span).toNumber();",
        "run[count] = [x + ((end - 1) * w / (n - 1)), y + h];",
        "run[count + 1] = [x + (start * w / (n - 1)), y + h];",
        "var pitch = w / n;",
        "var barHeight = ((v - lo) * h / span).toNumber();",
        "if (barHeight < 1) { barHeight = 1; }",
        "x + (i * pitch) + ((pitch - barWidth) / 2), y + h - barHeight,",
    )),
    ("WfbRing.mc", (
        "dc.drawLine(ax - 1, ay, bx - 1, by);",
        "dc.drawCircle(px - 1, py, r);",
    )),
])
def test_the_transcription_matches_the_barrel_source(name, statements):
    body = _source(name)
    for statement in statements:
        assert statement in body, f"{name} no longer contains {statement!r}"


# -- 2. the sweeps ------------------------------------------------------------


def _device_cells(call: tuple[int, int, bool] | None) -> frozenset[int]:
    """The whole-degree cells a `dc.drawArc(start, end, direction)` call
    covers, numbered clockwise from 3 o'clock (Pillow's frame), modelled
    straight from the SDK's definition: clockwise runs from `start` down to
    `end` in Garmin's counter-clockwise degrees, and `start == end` is the
    whole circle."""
    if call is None:
        return frozenset()
    start, end, clockwise = call
    length = ((start - end) if clockwise else (end - start)) % 360 or 360
    first = -start if clockwise else -end
    return frozenset((first + i) % 360 for i in range(length))


def _pillow_cells(span: tuple[int, int] | None) -> frozenset[int]:
    if span is None:
        return frozenset()
    a, b = span
    return frozenset((a + i) % 360 for i in range(b - a))


START_ANGLES = [tenths / 10 for tenths in range(0, 3600, 5)]  # every half degree
SWEEPS = [0.3, -0.3, 0.5, -0.5, 1.0, -28.0, 32.0, 45.5, -90.0, 180.5, 359.6, -360.0, 400.0]


def _evaluator_cells(author_start: float, sweep: float) -> frozenset[int]:
    """What the evaluator draws for a `shape: arc` / gauge track: the
    `Layout` start constant (`garmin_arc`), through `draw_span`, as Pillow
    angles (`pillow_arc`)."""
    call = barrel.draw_span(garmin_arc(author_start, sweep)[0], sweep)
    return _pillow_cells(barrel.pillow_arc(call) if call is not None else None)


def test_the_evaluator_covers_the_degrees_the_watch_covers():
    for author_start in START_ANGLES:
        for sweep in SWEEPS:
            device = _device_cells(barrel.draw_span(garmin_arc(author_start, sweep)[0], sweep))
            assert _evaluator_cells(author_start, sweep) == device, (author_start, sweep)


def test_the_sweep_catches_the_old_preview_twin():
    """The old preview twin rounded the author's start, the watch the Garmin
    start, so the two part at every half degree: the sweep above must see
    that, or it could not catch a broken evaluator either."""
    disagree = [
        (author_start, sweep)
        for author_start in START_ANGLES for sweep in SWEEPS
        if _pillow_cells(arc_span(author_start, sweep))
        != _device_cells(barrel.draw_span(garmin_arc(author_start, sweep)[0], sweep))
    ]
    assert disagree, "the sweep no longer separates the old twin from the watch"
    assert all(start % 1 == 0.5 for start, _ in disagree)


@pytest.mark.parametrize("start", [0.0, 77.5, 302.0, 359.5])
@pytest.mark.parametrize("sweep", [32.0, -32.0, 359.6, 0.4])
@pytest.mark.parametrize("fraction", [-0.1, 0.0, 0.001, 0.02, 0.5, 1.0, 1.7])
def test_draw_progress_is_draw_span_of_the_clamped_fraction(start, sweep, fraction):
    expected = (None if fraction <= 0.0
                else barrel.draw_span(start, sweep * min(fraction, 1.0)))
    assert barrel.draw_progress(start, sweep, fraction) == expected


@pytest.mark.parametrize("value,expected", [
    (0.0, 0), (0.49, 0), (0.5, 1), (1.5, 2), (2.4999, 2),
    (-0.49, 0), (-0.5, -1), (-1.5, -2), (-2.4999, -2),
])
def test_round_away_rounds_half_away_from_zero(value, expected):
    assert barrel.round_away(value) == expected


def test_rotated_anchor_matches_the_pattern_text_twin():
    """`WfbGeom.rotatedX`/`Y` against `wfb.kinds.pattern.pattern_text_anchor`'s
    own arithmetic, over angles and offsets that land on negative,
    non-half-integer coordinates -- where truncation and floor differ."""
    for degrees in range(0, 360, 7):
        theta = math.radians(degrees)
        sin, cos = math.sin(theta), math.cos(theta)
        for x in (-37, -1, 0, 3, 41):
            for y in (-52, -2, 0, 5, 60):
                for cx in (-3, 0, 130):
                    tx = cx + x * cos - y * sin
                    ty = cx + x * sin + y * cos
                    assert barrel.rotated_x(x, y, cx, sin, cos) == math.floor(tx + 0.5)
                    assert barrel.rotated_y(x, y, cx, sin, cos) == math.floor(ty + 0.5)


def test_truncation_would_differ_from_the_barrel():
    """The control: `toNumber` alone (the bug `WfbGeom.mc`'s note describes)
    rounds a negative anchor differently, and the test above would see it."""
    assert barrel.rotated_x(-1.6, 0, 0, 0.0, 1.0) == -2
    assert barrel.to_number(-1.6 + 0.5) == -1
