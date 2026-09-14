"""Codegen for analog hands (plan 04), mostly through `examples/analog/
face.yaml` -- the one example that ships two hand sets in two layouts, an
off-centre subdial, a `config.*` hand colour, `seconds: awake` and a set with
no second hand at all.

A full golden file is not pinned here (the byte-identity gate is
`tests/fixtures/slice/` and the other `layouts:`/no-hands examples staying
untouched, checked separately); this asserts on the specific shapes plan 04
promises instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_diagnostics import load
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.monkeyc import ReadPlan, emit_layout, emit_view
from wfb.emit.resources import bake_fonts
from wfb.layout import PlacedHands, resolve

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / "examples" / "analog" / "face.yaml"


@pytest.fixture(scope="module")
def resolved(db):
    # Fails rather than skips: a skip once silently turned the goldens off
    # (tests/CLAUDE.md), and this module is the goldens' stand-in for hands.
    assert DESIGN.exists(), "examples/analog/face.yaml is missing"
    bag = Bag()
    face = load(DESIGN, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


@pytest.fixture(scope="module")
def layout_text(resolved):
    return emit_layout(resolved).text


@pytest.fixture(scope="module")
def view_text(resolved):
    return emit_view(resolved).text


def test_the_design_has_the_shape_these_assertions_assume(resolved):
    face = resolved.face
    assert set(face.hands) == {"classic", "sport", "small_seconds"}
    assert face.hands["sport"].second is None
    hands_placed = [p for p in resolved.items if isinstance(p, PlacedHands)]
    assert {p.id for p in hands_placed} >= {"main_hands", "small_secs", "sport_hands"}


def test_layout_constants_name_the_axis_then_each_part(layout_text):
    assert "`main_hands` -- analog hands (hands.classic)" in layout_text
    assert "const MAIN_HANDS_CX as Number" in layout_text
    assert "const MAIN_HANDS_CY as Number" in layout_text
    # hour: a polygon
    assert "const MAIN_HANDS_HOUR_0_POINTS as Array<Graphics.Point2D>" in layout_text
    # minute: a rectangle folded into a polygon, plus a circle hub
    assert "const MAIN_HANDS_MINUTE_0_POINTS as Array<Graphics.Point2D>" in layout_text
    assert "const MAIN_HANDS_MINUTE_1_RADIUS as Number" in layout_text
    # second: a line plus a circle counterweight and a circle centre cap
    assert "const MAIN_HANDS_SECOND_0_X1 as Number" in layout_text
    assert "const MAIN_HANDS_SECOND_0_THICKNESS as Number" in layout_text
    assert "const MAIN_HANDS_SECOND_1_RADIUS as Number" in layout_text
    assert "const MAIN_HANDS_SECOND_2_RADIUS as Number" in layout_text


def test_sport_has_no_second_hand_constants(layout_text):
    assert "SPORT_HANDS_SECOND" not in layout_text


def test_the_view_draws_hour_then_minute_then_second_in_one_method(view_text):
    method = view_text.split("private function drawMainHands")[1]
    method = method.split("\n\n    //!")[0]  # up to the next doc comment / method
    hour_at = method.index("WfbHands.hourAngle")
    minute_at = method.index("WfbHands.minuteAngle")
    second_at = method.index("WfbHands.secondAngle")
    assert hour_at < minute_at < second_at


def test_the_draw_method_takes_a_clock_parameter(view_text):
    assert "private function drawMainHands(dc as Dc, clock as System.ClockTime) as Void" \
        in view_text


def test_an_awake_second_hand_is_wrapped_in_a_sleeping_guard(view_text):
    method = view_text.split("private function drawMainHands")[1]
    assert "if (!_sleeping) {" in method
    guarded = method.split("if (!_sleeping) {")[1]
    assert "WfbHands.secondAngle" in guarded


def test_sleeping_field_is_declared_once_for_the_whole_view(view_text):
    assert view_text.count("private var _sleeping as Boolean = false;") == 1
    assert "onEnterSleep" in view_text and "_sleeping = true;" in view_text
    assert "onExitSleep" in view_text and "_sleeping = false;" in view_text


def test_toybox_math_is_imported(view_text):
    assert "import Toybox.Math;" in view_text


def test_onupdate_reads_the_clock_once_for_every_hands_element(view_text):
    """One `System.getClockTime()` covers every hands element in the mode,
    however many layouts they belong to -- plan 02 §6.4's "reads happen
    unconditionally, only the calls are layout-guarded" applies to `clock`
    exactly like any other reader."""
    on_update = view_text.split("function onUpdate(dc as Dc) as Void {")[1]
    on_update = on_update.split("\n    }\n")[0]
    assert on_update.count("System.getClockTime()") == 1
    assert "drawMainHands(dc, clock);" in on_update
    assert "drawSmallSecs(dc, clock);" in on_update
    assert "drawSportHands(dc, clock);" in on_update
    # `sport`'s call sits behind its own layout guard, one line above it.
    before, _, after = on_update.partition("drawSportHands(dc, clock);")
    guard_line = before.strip().splitlines()[-1]
    assert "if (_configLayout ==" in guard_line
    assert after.strip().startswith("}")  # the guard closes right after


def test_barrel_includes_wfbhands(resolved, tmp_path, db):
    baked = {resolved.device.id: resolved.fonts}
    project = generate(resolved.face, [resolved.device], tmp_path, baked)
    assert "WfbHands.mc" in project.barrel


# -- designs with no hands stay exactly as before -----------------------------


NO_HANDS = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
"""


def test_a_design_with_no_hands_imports_no_math_and_declares_no_sleeping_field(
        write_design, bag, db):
    face = load(write_design(NO_HANDS), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    text = emit_view(resolved).text
    assert "Toybox.Math" not in text
    assert "_sleeping" not in text


SECONDS_NEVER = NO_HANDS.replace(
    'elements:\n', '''hands:
  set:
    hour:
      color: palette.fg
      parts:
        - {shape: circle, radius: 10%r}
    second:
      color: palette.fg
      parts:
        - {shape: line, at: {dy: 0}, to: {dy: -20%r}, thickness: 1px}
elements:
''') + """  - id: h
    type: hands
    hands: set
    seconds: never
    at: {anchor: center}
"""


def test_seconds_never_with_no_always_on_declares_no_sleeping_field(write_design, bag, db):
    """The second hand simply is not drawn: no `if (!_sleeping)`, no field."""
    face = load(write_design(SECONDS_NEVER), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    text = emit_view(resolved).text
    assert "_sleeping" not in text
    assert "secondAngle" not in text  # the second hand is never drawn at all


def test_read_plan_gives_a_hands_element_a_clock_parameter(write_design, bag, db):
    face = load(write_design(SECONDS_NEVER), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    plan = ReadPlan(resolved)
    placed = next(p for p in resolved.items if p.kind == "hands")
    assert plan.parameters(placed) == ", clock as System.ClockTime"
    assert plan.arguments(placed) == ", clock"


def test_consecutive_parts_sharing_a_colour_set_it_once(view_text):
    """`classic`'s second hand is a line and a counterweight in the accent
    colour, then a black hub: two setColor calls, not three."""
    body = view_text.split("function drawMainHands", 1)[1].split("\n    }\n", 1)[0]
    second = body.split("// second", 1)[1]
    assert second.count("dc.setColor(_configAccentColor") == 1
    assert second.count("dc.setColor(") == 2
