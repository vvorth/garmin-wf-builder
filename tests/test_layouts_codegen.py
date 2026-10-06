"""Codegen for `layouts:`, through
`examples/features/styles/face.yaml` -- the one example that actually ships both a
layout-only and a colour-only-adjacent entry, a hold target with a layout,
and a `low_power` element inside a layout.

A full golden file is not needed here (`ts/test/goldens/monkeyc/` already pins the
byte-identical, no-`layouts:` case): this asserts on the specific shapes
`layouts:` promises -- `resolveStyle`'s combined colour/layout blocks, the
guarded `onUpdate`/`onPartialUpdate`/`renderStatic` call sequences, and the
delegate's guarded hold hit test through the view's `configLayout()`
accessor.  Each assertion is driven from the design's own known shape
(three entries over two layouts, `big_clock`'s `on_hold:`, `compact_clock`'s
`sleep_update: true`), not a guess at what the emitter *should* do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wfb.build import load
from wfb.diagnostics import Bag
from wfb.emit.monkeyc import emit_delegate, emit_view
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / "examples" / "features" / "styles" / "face.yaml"


@pytest.fixture(scope="module")
def resolved(db):
    if not DESIGN.exists():
        pytest.skip("examples/features/styles/face.yaml is missing")
    bag = Bag()
    face = load(DESIGN, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


@pytest.fixture(scope="module")
def view_text(resolved):
    return emit_view(resolved).text


@pytest.fixture(scope="module")
def delegate_text(resolved):
    return emit_delegate(resolved).text


def test_the_design_has_the_shape_these_assertions_assume(resolved):
    """A guard nobody has watched fail is not a guard: pin the fixture's own
    shape first, so a future edit to the example that breaks these
    assumptions fails here with a clear message, not inside a regex."""
    face = resolved.face
    assert face.layouts == ("big", "compact")
    assert face.config_style is not None
    assert [e.name for e in face.config_style.entries] == [
        "big_dark", "big_light", "compact_dark"]
    assert [e.layout for e in face.config_style.entries] == ["big", "big", "compact"]


def test_resolve_style_sets_both_colours_and_layout_per_entry(view_text):
    assert "private function resolveStyle(style as Number) as Void" in view_text
    body = view_text.split("private function resolveStyle")[1].split("\n\n")[0]
    blocks = body.split("if (style ==")
    assert len(blocks) == 4  # the split boundary itself, then one per entry
    big_dark, big_light, compact_dark = blocks[1], blocks[2], blocks[3]
    for block, layout_index in ((big_dark, "0"), (big_light, "0"), (compact_dark, "1")):
        assert "_configColorsBg" in block
        assert "_configColorsFg" in block
        assert "_configColorsTrack" in block
        assert f"_configLayout = {layout_index};" in block
    assert "big_dark -- scheme: dark, layout: big" in big_dark
    assert "big_light -- scheme: light, layout: big" in big_light
    assert "compact_dark -- scheme: dark, layout: compact" in compact_dark


def test_the_config_layout_field_starts_at_the_default_entrys_layout(view_text):
    """`big_dark` is the default entry, and its layout ('big') is index 0."""
    assert "private var _configLayout as Number = 0;" in view_text


def test_on_update_guards_each_layouts_calls_as_one_block(view_text):
    on_update = view_text.split("function onUpdate(dc as Dc) as Void")[1].split(
        "\n    function ")[0]
    # Shared content (date_text, reading_slot) is unguarded and comes first.
    assert "drawDateText(dc, date);" in on_update
    assert "drawReadingSlot(dc);" in on_update
    shared_index = on_update.index("drawReadingSlot(dc);")
    big_guard_index = on_update.index("if (_configLayout == 0)")
    compact_guard_index = on_update.index("if (_configLayout == 1)")
    assert shared_index < big_guard_index < compact_guard_index

    big_block = on_update[big_guard_index:compact_guard_index]
    assert "drawBigClock(dc, clock);" in big_block
    # Exactly one guard for 'big' -- its one call is not split into two blocks.
    assert big_block.count("if (_configLayout == 0)") == 1

    compact_block = on_update[compact_guard_index:]
    assert "drawCompactClock(dc, clock);" in compact_block
    assert "drawStepsArc(dc, activity);" in compact_block
    # Consecutive calls sharing one layout share one guard block: both compact calls fall inside the single 'if' opened above, so
    # there is no second 'if (_configLayout == 1)' between them.
    assert compact_block.count("if (_configLayout == 1)") == 1


def test_render_static_guards_each_roots_call_by_its_own_layout(view_text):
    render_static = view_text.split("private function renderStatic")[1].split(
        "\n\n")[0]
    assert "drawStatic(dc);" in render_static  # shared root, unguarded
    shared_index = render_static.index("drawStatic(dc);")
    big_index = render_static.index("if (_configLayout == 0)")
    compact_index = render_static.index("if (_configLayout == 1)")
    assert shared_index < big_index < compact_index
    assert "drawStaticLayoutBigStatic(dc);" in render_static[big_index:compact_index]
    assert "drawStaticLayoutCompactStatic(dc);" in render_static[compact_index:]
    # drawStatic<Id> itself stays unguarded -- the guard is only on the call.
    big_method = view_text.split("private function drawStaticLayoutBigStatic")[1].split(
        "\n\n")[0]
    assert "_configLayout" not in big_method


def test_on_partial_update_guards_the_compact_layouts_low_power_call(view_text):
    assert "function onPartialUpdate(dc as Dc) as Void" in view_text
    partial = view_text.split("function onPartialUpdate(dc as Dc) as Void")[1].split(
        "\n    function ")[0]
    assert "if (_configLayout == 1)" in partial
    assert "drawCompactClock(dc, clock);" in partial
    # big_clock never draws in low_power at all, guarded or not.
    assert "drawBigClock" not in partial


def test_config_layout_accessor_is_public_and_used_by_the_delegate(view_text, delegate_text):
    assert "function configLayout() as Number" in view_text
    assert "private function configLayout" not in view_text
    assert "return _configLayout;" in view_text

    on_press = delegate_text.split("function onPress(clickEvent as ClickEvent) as Boolean")[1]
    # big_clock -> heart_rate is the only on_hold: target, and it belongs to
    # 'big' (index 0) -- the guard is folded into the same hit-test 'if'.
    condition = on_press.split("if (")[1].split("{")[0]
    assert "_view.configLayout() == 0" in condition
    assert "Complications.COMPLICATION_TYPE_HEART_RATE" in on_press


READS_DESIGN = """\
format: 2
face: { id: 6f1c2b7e-3d4a-4e5f-9a1b-2c3d4e5f6a7b, name: Reads, version: 1.0.0 }
build:
  targets: [fenix8solar47mm]
resources:
  palette: { fg: "#FFFFFF" }
config:
  style:
    default: a
    choices:
      a: { layout: a }
      b: { layout: b }
elements:
  battery:
    type: text
    text: "{system.battery:d}"
    font: FONT_XTINY
    at: { anchor: center, dy: -30% }
    color: color.fg
layouts:
  a:
    elements:
      steps_a:
        type: text
        text: "{activity.steps}"
        absent: hide
        font: FONT_XTINY
        at: { anchor: center }
        color: color.fg
      battery_a:
        type: text
        text: "{system.battery:d}%"
        font: FONT_XTINY
        at: { anchor: center, dy: 30% }
        color: color.fg
  b:
    elements:
      clock_b:
        type: text
        text: "{time.clock:%H:%M}"
        font: FONT_XTINY
        at: { anchor: center }
        color: color.fg
"""


def test_a_reader_is_read_where_its_elements_draw(write_design, bag, db):
    """Shared content's readers are read at the top of the frame, once,
    and each layout reads only what its own elements draw with, inside its
    guard: `stats` (shared and layout `a`) at the top only, `activity`
    (layout `a` alone) in `a`'s block, the clock (layout `b` alone) in
    `b`'s -- so showing `a` never reads the clock, nor `b` the activity."""
    from tests.helpers import resolve_text

    _, resolved = resolve_text(READS_DESIGN, write_design, bag, db)
    view = emit_view(resolved).text
    on_update = view.split("function onUpdate(dc as Dc) as Void {")[1].split("\n    }\n")[0]
    shared, block_a, block_b = on_update.split("if (_configLayout ==")
    assert shared.count("System.getSystemStats()") == 1
    assert "System.getSystemStats()" not in block_a + block_b
    assert "ActivityMonitor.getInfo()" in block_a and "ActivityMonitor.getInfo()" not in shared + block_b
    assert "System.getClockTime()" in block_b and "System.getClockTime()" not in shared + block_a
