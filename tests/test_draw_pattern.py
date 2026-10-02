"""`type: pattern` as a draw program (`wfb.kinds.pattern.PatternKind.lower`):
the copy loop the watch runs, its skips, a colour reading `copy` evaluated
per copy, a grid's rows by whole division, the radial angle exactly as
printed, and a ringed text part ringed by its own glyphs."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

from tests.helpers import find, resolve_text, resolved_example
from tests.test_patterns import LINEAR_ROW, RADIAL_RING, design
from wfb import kinds, preview
from wfb.draw.jsonform import to_json
from wfb.draw.printer import print_ops
from wfb.draw.program import DrawContext
from wfb.emit.monkeyc.common import NO_AOD
from wfb.emit.writer import Writer

OUTLINED = Path("tests/fixtures/outline_pattern_gauge/face.yaml")
DEVICE = "fenix8solar47mm"


def _renderer(resolved, scale: int = 2) -> preview.Renderer:
    options = preview.PreviewOptions(scale=scale)
    sample = preview.sample_values(resolved, options, None)
    image = Image.new("RGB", (resolved.device.width * scale, resolved.device.height * scale))
    return preview.Renderer(resolved, ImageDraw.Draw(image), image, scale, sample, options)


def _json(resolved, placed) -> list[dict]:
    ops, _ = to_json(_renderer(resolved), placed)
    return ops


def _printed(resolved, placed) -> str:
    w = Writer()
    print_ops(w, kinds.for_placed(placed).lower(DrawContext(resolved, NO_AOD), placed))
    return w.render()


def _value(n) -> float:
    return float(n["value"] + n["add"]) if isinstance(n, dict) else float(n)


def test_a_skipped_copy_draws_nothing(write_design, bag, db):
    text = design(RADIAL_RING.replace("count: 4", "count: 4\n    skip: [1]"))
    _, resolved = resolve_text(text, write_design, bag, db)
    ring = find(resolved, "ring")
    assert "if (i == 1)" in _printed(resolved, ring)
    assert "continue;" in _printed(resolved, ring)
    assert [op["op"] for op in _json(resolved, ring)].count("drawLine") == 3


def test_a_colour_reading_copy_is_evaluated_for_each_copy(write_design, bag, db):
    text = design(RADIAL_RING.replace(
        "color: color.fg", 'color: "copy % 2 == 0 ? color.accent : color.fg"'))
    _, resolved = resolve_text(text, write_design, bag, db)
    colors = [tuple(op["rgb"]) for op in _json(resolved, find(resolved, "ring"))
              if op["op"] == "color"]
    accent, fg = (255, 85, 0), (255, 255, 255)
    assert colors == [accent, fg, accent, fg]


def test_a_grid_steps_its_rows_by_whole_division(write_design, bag, db):
    """`oy = Y + (i / columns) * DY`: copies 0 and 1 share a row, 2 and 3
    the next."""
    text = design(LINEAR_ROW.replace("pattern: linear", "pattern: grid\n    columns: 2")
                  .replace("count: 3", "count: 4").replace("step: {dx: 20px}",
                                                            "step: {dx: 20px, dy: 10px}"))
    _, resolved = resolve_text(text, write_design, bag, db)
    row = find(resolved, "row")
    centres = [(_value(op["args"][0]), _value(op["args"][1]))
               for op in _json(resolved, row) if op["op"] == "fillCircle"]
    x, y = row.center
    assert centres == [(x, y), (x + 20, y), (x, y + 10), (x + 20, y + 10)]


def test_the_radial_angle_is_the_one_printed(write_design, bag, db):
    """Copy ``i`` turns by ``i * radians(step)``, the literal the watch is
    given, and its line's ends are rotated about the centre by it."""
    _, resolved = resolve_text(design(RADIAL_RING), write_design, bag, db)
    ring = find(resolved, "ring")
    step = math.radians(90.0)
    assert f"var angle = i * {step!r};" in _printed(resolved, ring)
    lines = [op for op in _json(resolved, ring) if op["op"] == "drawLine"]
    part = ring.parts[0]
    cx, cy = ring.center
    for index, op in enumerate(lines):
        sin, cos = math.sin(index * step), math.cos(index * step)
        assert [_value(n) for n in op["args"][:2]] == [
            cx + (part.x1 * cos - part.y1 * sin), cy + (part.x1 * sin + part.y1 * cos)]


def test_a_ringed_text_part_rings_with_its_own_glyphs(db):
    """The pattern's `outline:` stamps each copy's text at the ring's four
    offsets, in the ring colour, before the copy's own text: five text
    draws a copy, as the watch makes them."""
    resolved = resolved_example(OUTLINED, db, DEVICE)
    numerals = find(resolved, "numerals")
    ops = _json(resolved, numerals)
    assert [op["op"] for op in ops].count("text") == 4 * 5
    first = [op for op in ops if op["op"] == "text"][:5]
    assert len({(op["x"], op["y"]) for op in first}) == 5
