"""`runtime-lib/WfbArc.mc`'s whole-degree rule, and its host twin `wfb.preview.arc_span`.

The bug this pins, seen on a real fenix 8 Solar 47mm: `examples/dashboard`'s
`arc_steps` (start 148deg, sweep -32deg) painted the **whole bezel ring** in the
data colour for the first ~3% of the step goal each day. `Dc.drawArc` takes
whole degrees and draws a complete circle when start == end; the barrel used to
truncate start and end *separately*, so a sub-degree anticlockwise fill
(`302.0 -> 302.4`) became `drawArc(..., 302, 302)`. A clockwise fill of the same
size truncated to a 1-degree stub instead, which is why only the two
negative-sweep arcs on that face could do it.

Monkey C cannot run in this environment (no simulator -- CLAUDE.md, Phase 2
finding 11), so the barrel is checked the way `tests/test_weather_barrel.py`
checks its own: parse the real file for the statements that carry the rule,
and exercise a line-for-line Python transcription of them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.test_diagnostics import load
from wfb.emit.resources import bake_fonts
from wfb.layout import garmin_arc, resolve
from wfb.preview import PreviewOptions, arc_span, render

BARREL = Path(__file__).resolve().parent.parent / "runtime-lib" / "WfbArc.mc"


def _to_number(x: float) -> int:
    """Monkey C `Float.toNumber`: truncates towards zero."""
    return int(x)


def _mc_mod(a: int, b: int) -> int:
    """Monkey C `%`: the result takes the sign of the dividend, as in C."""
    return int(__import__("math").fmod(a, b))


def _round_away(x: float) -> int:
    return _to_number(x - 0.5) if x < 0.0 else _to_number(x + 0.5)


def device_draw_arc(start_degrees: float, sweep_degrees: float) -> tuple[int, int, str] | None:
    """`WfbArc.drawSpan`, transcribed: the `drawArc` arguments, or None for no call."""
    sweep = _round_away(sweep_degrees)
    if sweep == 0:
        return None
    sweep = max(-360, min(360, sweep))
    start = _mc_mod(_round_away(start_degrees), 360)
    if start < 0:
        start += 360
    end = _mc_mod(start - sweep, 360)
    if end < 0:
        end += 360
    return start, end, "ARC_CLOCKWISE" if sweep > 0 else "ARC_COUNTER_CLOCKWISE"


def old_device_draw_arc(start_degrees: float, sweep_degrees: float) -> tuple[int, int, str] | None:
    """The pre-fix barrel, kept only so the tests below are seen to catch it."""
    sweep = sweep_degrees
    if sweep >= 360.0:
        sweep = 359.9
    if sweep <= -360.0:
        sweep = -359.9
    if sweep == 0.0:
        return None
    end = start_degrees - sweep
    while end < 0.0:
        end += 360.0
    while end >= 360.0:
        end -= 360.0
    return (_to_number(start_degrees), _to_number(end),
            "ARC_CLOCKWISE" if sweep > 0 else "ARC_COUNTER_CLOCKWISE")


def _draws_full_circle(call: tuple[int, int, str] | None) -> bool:
    return call is not None and call[0] == call[1]


# -- the transcription is of the real file ------------------------------------


def test_the_transcription_matches_the_barrel_source():
    text = BARREL.read_text(encoding="utf-8")
    body = re.sub(r"\s+", " ", text)
    for statement in (
        "var sweep = roundAway(sweepDegrees);",
        "if (sweep == 0) { return; }",
        "if (sweep > 360) { sweep = 360; }",
        "if (sweep < -360) { sweep = -360; }",
        "var start = roundAway(startDegrees) % 360;",
        "var end = (start - sweep) % 360;",
        "dc.drawArc(cx, cy, radius, direction, start, end);",
        "(degrees - 0.5).toNumber()",
        "(degrees + 0.5).toNumber()",
    ):
        assert statement in body, f"WfbArc.mc no longer contains {statement!r}"
    # The shape of the bug: angles converted to whole degrees independently,
    # at the call site, after the decision about whether to draw was made.
    assert "startDegrees.toNumber()" not in body
    assert "endDegrees.toNumber()" not in body


# -- the rule -----------------------------------------------------------------

# Every arc on examples/dashboard, as the author wrote it.
DASHBOARD_ARCS = [(212.0, 32.0), (180.0, -28.0), (180.0, 28.0), (148.0, -32.0)]
SMALL_FRACTIONS = [0.001, 0.005, 0.01, 0.02, 0.03]


@pytest.mark.parametrize("author_start,sweep", DASHBOARD_ARCS)
@pytest.mark.parametrize("fraction", SMALL_FRACTIONS)
def test_a_small_fill_never_draws_the_full_circle(author_start, sweep, fraction):
    start, _ = garmin_arc(author_start, sweep)
    assert not _draws_full_circle(device_draw_arc(start, sweep * fraction))


def test_the_old_barrel_did_draw_the_full_circle():
    """The control: the case above is one the pre-fix code actually fails."""
    start, _ = garmin_arc(148.0, -32.0)  # arc_steps
    assert _draws_full_circle(old_device_draw_arc(start, -32.0 * 0.02))
    assert not _draws_full_circle(device_draw_arc(start, -32.0 * 0.02))


@pytest.mark.parametrize("sweep", [360.0, -360.0, 400.0, -720.0])
def test_a_full_sweep_is_the_one_intended_full_circle(sweep):
    assert _draws_full_circle(device_draw_arc(302.0, sweep))


@pytest.mark.parametrize("sweep", [0.0, 0.49, -0.49])
def test_under_half_a_degree_draws_nothing(sweep):
    assert device_draw_arc(302.0, sweep) is None


@pytest.mark.parametrize("sweep", [0.5, -0.5, 0.9, -0.9])
def test_half_a_degree_or_more_draws_one_degree_either_way(sweep):
    start, end, _ = device_draw_arc(302.0, sweep)
    assert (start - end) % 360 == (1 if sweep > 0 else 359)


def test_no_non_full_sweep_ever_collapses_to_a_circle():
    """Anything that does not round to +-360 -- i.e. |sweep| < 359.5."""
    for start_tenths in range(0, 3600, 7):
        for sweep_tenths in range(-3594, 3595, 13):
            call = device_draw_arc(start_tenths / 10, sweep_tenths / 10)
            assert not _draws_full_circle(call), (start_tenths, sweep_tenths)


# -- the preview agrees with the device ---------------------------------------


def _pillow_degrees(call: tuple[int, int, str] | None) -> set[int] | None:
    """The whole degrees a `drawArc` call covers, in Pillow's clockwise-from-3 frame."""
    if call is None:
        return None
    start, end, direction = call
    length = (start - end) % 360 if direction == "ARC_CLOCKWISE" else (end - start) % 360
    length = length or 360
    first = -start if direction == "ARC_CLOCKWISE" else -end
    return {(first + i) % 360 for i in range(length)}


def _span_degrees(span: tuple[int, int] | None) -> set[int] | None:
    if span is None:
        return None
    a, b = span
    return {(a + i) % 360 for i in range(b - a)}


@pytest.mark.parametrize("author_start", [0.0, 45.0, 148.0, 180.0, 212.0, 359.0])
@pytest.mark.parametrize("sweep", [0.3, -0.3, 0.64, -0.64, 1.0, -28.0, 32.0, 359.6, -360.0])
def test_the_preview_draws_what_the_device_draws(author_start, sweep):
    start, _ = garmin_arc(author_start, sweep)
    assert _span_degrees(arc_span(author_start, sweep)) == _pillow_degrees(
        device_draw_arc(start, sweep)
    )


STEPS_ARC = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  fill: "#00FF00"
elements:
  - id: arc_steps
    type: progress
    style: arc
    value: activity.steps
    max: activity.step_goal
    at: { anchor: center }
    radius: 97%r
    thickness: 4%r
    start_angle: 148deg
    sweep: -32deg
    color: palette.fill
    when_absent: hide
"""


@pytest.mark.parametrize("steps,expect_fill", [(50, False), (2000, True)])
def test_the_preview_of_a_barely_started_step_arc_has_no_fill(
    write_design, bag, db, steps, expect_fill
):
    face = load(write_design(STEPS_ARC), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    image = render(resolved, PreviewOptions(
        sample={"activity.steps": steps, "activity.step_goal": 10000},
        mask_shape=False,
    ))
    colors = {rgb for _, rgb in image.getcolors(maxcolors=1 << 16)}
    assert ((0, 255, 0) in colors) is expect_fill
