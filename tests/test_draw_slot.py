"""A data element (`type: data`, `complication_slot`) as a draw program
(`wfb.kinds.complication_slot.ComplicationSlotKind.lower`): the pair placed
by the watch's own whole-pixel arithmetic over the host's measurements of
the slot's default pick, the editor's pulsing guard, and the icon's colour
in each frame."""

from __future__ import annotations

from PIL import Image, ImageDraw

from tests.helpers import align_value, find, resolve_text
from wfb import kinds, preview
from wfb.draw.jsonform import to_json
from wfb.draw.printer import print_ops
from wfb.draw.program import DrawContext
from wfb.emit.monkeyc.common import NO_AOD
from wfb.emit.writer import Writer
from wfb.fonts import fallback
from wfb.layout import COMPLICATION_SLOT_ICON_GAP

BASE = """
format: 2
face:
  id: 6b2f9a3e-5c1d-4e8a-9f7b-3a1d6c8e2f40
  name: Test
build:
  targets: [fenix8solar47mm, fenix847mm]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
    acc: "#FF5500"
config:
  slots:
    top:
      default: steps
      choices:
        - steps
        - heart_rate
elements:
  slot:
    type: data
    slot: top
    at: {anchor: center}
    color: color.fg
"""


def _json(resolved, placed, **options: object) -> list[dict]:
    opts = preview.PreviewOptions(**options)
    sample = preview.sample_values(resolved, opts, None)
    image = Image.new("RGB", (resolved.device.width * 2, resolved.device.height * 2))
    renderer = preview.Renderer(resolved, ImageDraw.Draw(image), image, 2, sample, opts)
    ops, _ = to_json(renderer, placed)
    return ops


def _value(n) -> float:
    return float(n["value"] + n["add"]) if isinstance(n, dict) else float(n)


def test_the_pair_starts_at_the_watchs_whole_pixel(write_design, bag, db):
    """`startX = CX - totalWidth / 2` on two `Number`s: the icon at `startX`,
    the reading after it and the gap.  The total is odd here, so an exact
    half would land between two pixels."""
    _, resolved = resolve_text(BASE + "    icon: {size: 16%r}\n", write_design, bag, db)
    slot = find(resolved, "slot")
    icon_font = resolved.fonts[slot.icon_font_key]
    texts = [op for op in _json(resolved, slot) if op["op"] == "text"]
    icon, reading = texts
    icon_width = icon_font.measure(icon["text"])[0] + COMPLICATION_SLOT_ICON_GAP
    text_width = fallback.measure(reading["text"], slot.font.metric)[0]
    assert (icon_width + text_width) % 2 == 1  # the contrast this test needs
    start = slot.anchor_point[0] - (icon_width + text_width) // 2
    assert _value(icon["x"]) == start
    assert _value(reading["x"]) == start + icon_width
    assert reading["text"] == "8432"  # the default pick's sample reading


def test_a_row_aligned_to_the_top_hangs_from_a_whole_pixel_axis(write_design, bag, db):
    """`rowY = CY + rowHeight / 2`, truncated, on a font with an odd line
    height (53 px on fenix847mm), where a fractional half would not be."""
    text = BASE + f"    align: {align_value('center', 'top')}\n"
    _, resolved = resolve_text(text, write_design, bag, db, "fenix847mm")
    slot = find(resolved, "slot")
    height = int(fallback.line_height(slot.font.metric))
    assert height % 2 == 1
    reading, = [op for op in _json(resolved, slot) if op["op"] == "text"]
    assert _value(reading["y"]) == slot.anchor_point[1] + height // 2


def test_every_slot_waits_while_the_editor_animates_it(write_design, bag, db):
    _, resolved = resolve_text(BASE, write_design, bag, db)
    slot = find(resolved, "slot")
    w = Writer()
    print_ops(w, kinds.for_placed(slot).lower(DrawContext(resolved, NO_AOD), slot))
    code = w.render()
    assert code.index("if (_pulsing == ") < code.index("var chosenId")
    assert [op["op"] for op in _json(resolved, slot)].count("text") == 1


def test_an_aod_icon_colour_replaces_only_the_always_on_icon(write_design, bag, db):
    """No `icon: {color:}`: the icon draws in the text's colour awake, and in
    its `aod:` colour in the always-on frame."""
    text = BASE + "    icon: {size: 12%r, position: right}\n    aod: {icon: {color: color.acc}}\n"
    _, resolved = resolve_text(text, write_design, bag, db, "fenix847mm")
    slot = find(resolved, "slot")
    awake = [tuple(op["rgb"]) for op in _json(resolved, slot) if op["op"] == "color"]
    asleep = [tuple(op["rgb"]) for op in _json(resolved, slot, aod=True) if op["op"] == "color"]
    assert set(awake) == {(255, 255, 255)}
    assert asleep[-1] == (255, 85, 0) and asleep[0] == (255, 255, 255)
