"""`outline:` on `pattern` and `gauge` (research 19, plan 23 slice 4): each
pattern copy ringed whole by moving its own origin, an arc gauge stamped
round its track, a bar grown round its track or its lit length, a needle
ringed like a hand -- and the contrast rule for a ring that parts things
rather than outlines them.  `tests/fixtures/outline_pattern_gauge/` is
built for real by `tests/test_outline_build.py` (`slow`)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wfb.preview import PreviewOptions, render

from tests.helpers import find, generate_for_targets, lint_text, load_errors, resolve_design

FIXTURE = Path(__file__).parent / "fixtures" / "outline_pattern_gauge" / "face.yaml"


@pytest.fixture(scope="module")
def view(tmp_path_factory) -> str:
    files = generate_for_targets(FIXTURE, tmp_path_factory.mktemp("build")).files()
    return next(body for name, body in files.items() if name.endswith("View.mc"))


def _method(view: str, name: str) -> str:
    match = re.search(rf"private function {name}\(.*?\n    }}\n", view, re.S)
    assert match is not None, name
    return match.group(0)


# -- pattern -----------------------------------------------------------------------


def test_a_radial_copy_is_ringed_by_moving_its_centre(view):
    body = _method(view, "drawTicks")
    loop = body[body.index("while (ringI"):body.index("ringI += 2;")]
    assert "cx = Layout.TICKS_X + ringStamp[ringI];" in loop
    assert "TICKS_0_POINTS" in loop and "TICKS_1_X1" in loop  # every part, one loop
    after = body[body.index("ringI += 2;"):]
    assert after.index("cx = Layout.TICKS_X;") < after.index("dc.setColor(Palette.ACCENT")


def test_the_stamp_names_never_collide_with_the_copy_loop(view):
    """The copy loop owns `i`; Monkey C rejects a second `var i`."""
    body = _method(view, "drawTicks")
    assert body.count("var i ") == 1 and "var ringI = 0;" in body


def test_a_ringed_pattern_sets_its_colour_every_copy(view):
    """The ring colour is set inside the loop, so the part colour cannot be
    hoisted above it."""
    body = _method(view, "drawTicks")
    assert "hoisted: one colour" not in body
    loop = body[body.index("for (var i"):]
    assert loop.index("Palette.RING") < loop.index("Palette.ACCENT")


def test_a_linear_copy_is_ringed_by_moving_its_origin(view):
    body = _method(view, "drawDots")
    assert "ox = Layout.DOTS_X + i * Layout.DOTS_DX + ringStamp[ringI];" in body
    assert "\n            ox = Layout.DOTS_X + i * Layout.DOTS_DX;" in body


def test_a_ringed_text_part_inside_a_ringed_pattern_is_refused(write_design, minimal):
    errors = load_errors(minimal + """
  numerals:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 4
    step: 90deg
    color: color.fg
    outline: color.fg
    parts:
      - type: text
        text: "{copy}"
        font: FONT_XTINY
        at: {dy: -60%r}
        outline: color.bg
""", write_design)
    assert [e.code for e in errors] == ["outline"], errors
    assert errors[0].message.startswith("numerals: 'outline:' round a pattern with a ringed text part")


# -- gauge ------------------------------------------------------------------------


def test_an_arc_gauge_is_stamped_round_its_track(view):
    body = _method(view, "drawBatteryArc")
    ring = body[:body.index("// the unfilled track")]
    assert "WfbArc.drawSpan(dc, Layout.BATTERY_ARC_CX + offsets[i]," in ring
    assert "drawProgress" not in ring  # the lit arc lies inside the track


def test_a_trackless_arc_gauge_is_stamped_round_its_lit_arc_only_while_present(view):
    body = _method(view, "drawHrArc")
    ring = body[:body.index("// the filled portion")]
    assert "if (heartRateCurrent != null) {" in ring
    assert "WfbArc.drawProgress(dc, Layout.HR_ARC_CX + offsets[i]," in ring


def test_a_trackless_bar_is_grown_round_its_lit_length(view):
    body = _method(view, "drawStepsBar")
    assert "if (filled > 0) {" in body
    assert "filled + 4, Layout.STEPS_BAR_HEIGHT + 4," in body
    assert body.index("fillRoundedRectangle") < body.index("fillRectangle(Layout.STEPS_BAR_X")


def test_a_bar_with_a_track_is_grown_round_the_whole_track(write_design, tmp_path, minimal):
    files = generate_for_targets(write_design(minimal + """
  bar:
    type: gauge
    style: bar
    value: system.battery
    max: 100
    at: {anchor: center}
    size: {width: 40%, height: 4%}
    color: color.fg
    track_color: color.bg
    outline: {color: color.fg, width: 1}
"""), tmp_path / "out").files()
    body = _method(next(b for n, b in files.items() if n.endswith("View.mc")), "drawBar")
    assert re.search(r"dc\.fillRoundedRectangle\(Layout\.BAR_X - 1, Layout\.BAR_Y - 1,\s+"
                     r"Layout\.BAR_WIDTH \+ 2, Layout\.BAR_HEIGHT \+ 2,\s+1\);", body), body


def test_a_needle_is_ringed_whole(view):
    body = _method(view, "drawNeedle")
    loop = body[body.index("while"):body.index("i += 2;")]
    assert "cx = Layout.NEEDLE_CX + offsets[i];" in loop
    assert "NEEDLE_NEEDLE_0_POINTS" in loop and "NEEDLE_NEEDLE_1_RADIUS" in loop


@pytest.mark.parametrize("style", ["segments", "scale"])
def test_a_ticked_gauge_ring_is_refused(write_design, minimal, style):
    extra = "    count: 5\n" if style == "segments" else ""
    errors = load_errors(minimal + f"""
  g:
    type: gauge
    style: {style}
    value: system.battery
    max: 100
    at: {{anchor: center}}
    size: {{width: 40%, height: 4%}}
{extra}    color: color.fg
    outline: color.fg
""", write_design)
    assert [e.code for e in errors] == ["outline"], errors
    assert f"'style: {style}' gauge is not implemented yet" in errors[0].message


def test_a_ticked_gauge_in_an_outlined_group_is_refused(write_design, minimal):
    errors = load_errors(minimal + """
  g:
    type: group
    outline: color.fg
    children:
      scale:
        type: gauge
        style: scale
        value: system.battery
        max: 100
        at: {anchor: center}
        size: {width: 40%, height: 4%}
        color: color.fg
""", write_design)
    assert [e.code for e in errors] == ["outline"], errors
    assert "'scale' cannot: 'outline:' on a 'style: scale' gauge" in errors[0].message


# -- contrast ---------------------------------------------------------------------


def test_a_backdrop_coloured_ring_round_a_readable_interior_does_not_warn(write_design, db, minimal):
    """The idiom that parts overlapping hands: the ring matches the backdrop
    on purpose, and the interior is what reads."""
    bag = lint_text(minimal + """
  disc:
    type: circle
    at: {anchor: center}
    radius: 20px
    color: color.fg
    outline: color.bg
""", write_design, db)
    assert not [d for d in bag.items if d.code == "contrast"], bag.render()


def test_a_hollow_interior_still_needs_a_ring_that_reads(write_design, db, minimal):
    """The contrast the rule above must not lose: interior and ring both
    matching the backdrop leaves nothing visible."""
    bag = lint_text(minimal + """
  disc:
    type: circle
    at: {anchor: center}
    radius: 20px
    color: color.bg
    outline: color.bg
""", write_design, db)
    assert any(d.code == "contrast" and "disc: outline ring #000000 on #000000" in d.message
               for d in bag.items), bag.render()


# -- preview ----------------------------------------------------------------------


def test_the_preview_rings_each_copy(bag, db):
    resolved = resolve_design(FIXTURE, bag, db, "fenix8solar47mm")
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    dots = find(resolved, "dots")
    ring = (255, 255, 0)
    y = dots.center[1]
    # one pixel either side: the box rounds a circle's edge, not the ring's
    row = [image.getpixel((x, y)) for x in range(dots.box.x - 1, dots.box.right + 1)]
    # five dots, each with a ring on both sides: ten ring runs
    runs = sum(1 for a, b in zip([None] + row, row) if b == ring and a != ring)
    assert runs == 10, row
