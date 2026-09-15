"""The host-side preview renderer, a pattern `shape: text` part (plan 06
§3.4, phase B3).

Same discipline as `tests/test_patterns_preview.py`, whose fixtures and
small pixel-probing helpers (`_near`, `_polar`, the fixed device/colours)
this file reuses directly rather than re-deriving them: a minimal,
self-contained `static:` face -- a solid black background plus one
`type: pattern` element with a single `shape: text` part -- so a pixel's
colour is unambiguous.

Every design here uses a real baked font (`tests/fixtures/slice/assets/
OpenSans-Regular.ttf`, the same fixture `tests/test_pattern_text.py` bakes
from), with `antialias:` left at its default (off), so a drawn glyph pixel
is *exactly* the part's own colour or exactly the background -- no blended
edge pixel to complicate an exact-colour pixel probe.

Each test is built to fail against the pre-B3 preview, which fell into
`_hand_part`'s `circle` branch for a text part (drawing nothing useful:
`part.radius`/`part.filled` are at their unused defaults) and so left
every one of these designs blank but for the background rectangle.

The device is `fenix8solar47mm` (260x260, centre (130, 130)), like every
other pattern preview test.
"""

from __future__ import annotations

import pytest

from tests.test_diagnostics import load
from tests.test_patterns_preview import BACKGROUND, CX, CY, RED, WHITE, _near, _polar
from wfb.emit.resources import bake_fonts
from wfb.layout import pattern_text_anchor, resolve
from wfb.preview import PreviewOptions, render

#: A generous-but-safe tolerance for "is there ink near this anchor":
#: `numfont` is baked at 20px, so a glyph's own half-extent is comfortably
#: under this, and every design below keeps anchors at least ~40px apart --
#: far more than 2x this tolerance -- so it can never accidentally pick up
#: a neighbouring copy's ink.
TOLERANCE = 14

_HEADER = """\
format: 1
face:
  id: 6a9c0e2b-2222-4abc-9def-0123456789ab
  name: PatternTextPreviewTest
targets: [fenix8solar47mm]
palette:
  black: "#000000"
  white: "#FFFFFF"
  red: "#FF0000"
fonts:
  numfont:
    source: {ttf}
    size: 20px
static:
  background:
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.black
{body}
"""


@pytest.fixture
def ttf(repo_root):
    return repo_root / "tests/fixtures/slice/assets/OpenSans-Regular.ttf"


def _build(write_design, db, bag, body: str, ttf):
    """Write a one-pattern face with a `shape: text` part, and build it
    through the real pipeline (loader, desugar, schema, IR, layout, font
    baking) -- the same stages `tests/test_patterns_preview.py::_render`
    runs, plus `bake_fonts`, which that helper never needed."""
    path = write_design(_HEADER.format(ttf=ttf, body=body))
    face = load(path, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


def _draw(resolved, **options):
    opts = {"scale": 1, "mask_shape": False, "quantise": False, **options}
    return render(resolved, PreviewOptions(**opts))


def _find(resolved, element_id):
    return next(p for p in resolved.items if p.id == element_id)


def _ink_bbox(image, point, color, half=30):
    """The tight bounding box of `color` pixels within `half` px of
    `point` -- used to compare a glyph's drawn *shape*, not just whether
    it drew at all."""
    cx, cy = round(point[0]), round(point[1])
    xs, ys = [], []
    for dx in range(-half, half + 1):
        for dy in range(-half, half + 1):
            x, y = cx + dx, cy + dy
            if image.getpixel((x, y)) == color:
                xs.append(x)
                ys.append(y)
    assert xs, f"no {color} ink found near {point}"
    return min(xs), min(ys), max(xs), max(ys)


# -- four anchors, and nowhere else -------------------------------------------


def test_four_copies_draw_upright_glyphs_at_the_four_cardinal_anchors(write_design, db, bag, ttf):
    """A 4-copy radial ring: ink at each of `pattern_text_anchor`'s own
    four anchors (top/right/bottom/left of centre), and nowhere near the
    centre or a diagonal between two copies -- the pre-B3 preview drew
    nothing at all here."""
    body = """  hours:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 4
    color: palette.white
    parts:
      - shape: text
        value: copy
        font: font.numfont
        at: {dy: -60px}
"""
    resolved = _build(write_design, db, bag, body, ttf)
    image = _draw(resolved)
    placed = _find(resolved, "hours")
    part = placed.parts[0]

    for index in placed.copies:
        anchor = pattern_text_anchor(part, *placed.transform(index))
        assert _near(image, anchor, WHITE, tolerance=TOLERANCE), \
            f"copy {index} missing ink near {anchor}"

    # A diagonal (45deg from 12 o'clock, the same 60px reach) sits between
    # two copies -- nothing was asked to draw there.
    for degrees in (45, 135, 225, 315):
        point = _polar(CX, CY, 60, degrees)
        assert not _near(image, point, WHITE, tolerance=TOLERANCE)

    # The centre itself is well clear of every 60px-out anchor.
    assert not _near(image, (CX, CY), WHITE, tolerance=TOLERANCE)


# -- upright: the glyph itself never rotates ----------------------------------


def test_glyphs_stay_upright_when_the_copy_turns_90_degrees(write_design, db, bag, ttf):
    """The same fixed glyph ("1", tall and narrow) at copy 0 (12 o'clock)
    and copy 1 (90deg further, 3 o'clock): the *anchor* turns with the
    copy, but the glyph's own drawn shape must not -- a bug that rotated
    the glyph the way `_hand_part` rotates a hand's vertices would swap
    copy 1's width and height."""
    body = """  digits:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 4
    color: palette.white
    parts:
      - shape: text
        text: "1"
        font: font.numfont
        at: {dy: -60px}
"""
    resolved = _build(write_design, db, bag, body, ttf)
    image = _draw(resolved)
    placed = _find(resolved, "digits")
    part = placed.parts[0]

    anchor0 = pattern_text_anchor(part, *placed.transform(0))
    anchor1 = pattern_text_anchor(part, *placed.transform(1))
    x0min, y0min, x0max, y0max = _ink_bbox(image, anchor0, WHITE)
    x1min, y1min, x1max, y1max = _ink_bbox(image, anchor1, WHITE)
    w0, h0 = x0max - x0min, y0max - y0min
    w1, h1 = x1max - x1min, y1max - y1min

    assert h0 > w0, "a '1' glyph should be taller than it is wide"
    assert abs(w0 - w1) <= 1 and abs(h0 - h1) <= 1, \
        f"copy 1's glyph shape ({w1}x{h1}) differs from copy 0's ({w0}x{h0}) -- rotated?"


# -- per-copy strings: different copies, different widths ---------------------


def test_per_copy_value_draws_a_different_width_string_per_copy(write_design, db, bag, ttf):
    """`value:` reads `copy`, so copy 0 draws a 4-digit string and copy 1
    a 1-digit one -- the drawn ink must be visibly wider for copy 0. Single
    quotes inside the expression (the expr grammar accepts either quote
    character, `wfb/expr.py`) sidestep any YAML string-escaping question."""
    body = """  numerals:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 2
    color: palette.white
    parts:
      - shape: text
        value: "copy == 0 ? '8888' : '1'"
        font: font.numfont
        at: {dy: -60px}
"""
    resolved = _build(write_design, db, bag, body, ttf)
    image = _draw(resolved)
    placed = _find(resolved, "numerals")
    part = placed.parts[0]
    assert part.texts == ("8888", "1")

    anchor0 = pattern_text_anchor(part, *placed.transform(0))
    anchor1 = pattern_text_anchor(part, *placed.transform(1))
    x0min, _, x0max, _ = _ink_bbox(image, anchor0, WHITE, half=45)
    x1min, _, x1max, _ = _ink_bbox(image, anchor1, WHITE, half=45)
    assert (x0max - x0min) > (x1max - x1min)


# -- skip / visible: hides exactly the right copy -----------------------------


def test_skip_removes_the_skipped_copys_ink(write_design, db, bag, ttf):
    body = """  hours:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 4
    skip: [1]
    color: palette.white
    parts:
      - shape: text
        text: "8"
        font: font.numfont
        at: {dy: -60px}
"""
    resolved = _build(write_design, db, bag, body, ttf)
    image = _draw(resolved)
    placed = _find(resolved, "hours")
    part = placed.parts[0]

    skipped = pattern_text_anchor(part, *placed.transform(1))
    assert not _near(image, skipped, WHITE, tolerance=TOLERANCE)
    for index in placed.copies:
        anchor = pattern_text_anchor(part, *placed.transform(index))
        assert _near(image, anchor, WHITE, tolerance=TOLERANCE)


def test_part_visible_hides_exactly_that_copy(write_design, db, bag, ttf):
    body = """  hours:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 4
    color: palette.white
    parts:
      - shape: text
        text: "8"
        font: font.numfont
        at: {dy: -60px}
        visible: "copy != 2"
"""
    resolved = _build(write_design, db, bag, body, ttf)
    image = _draw(resolved)
    placed = _find(resolved, "hours")
    part = placed.parts[0]

    hidden = pattern_text_anchor(part, *placed.transform(2))
    assert not _near(image, hidden, WHITE, tolerance=TOLERANCE)
    for index in placed.copies:
        if index == 2:
            continue
        anchor = pattern_text_anchor(part, *placed.transform(index))
        assert _near(image, anchor, WHITE, tolerance=TOLERANCE)


# -- linear: the anchor steps by dx -------------------------------------------


def test_linear_pattern_draws_ink_at_each_stepped_anchor(write_design, db, bag, ttf):
    body = """  row:
    type: pattern
    pattern: linear
    at: {anchor: center, dx: -40px}
    count: 3
    step: {dx: 40px}
    color: palette.white
    parts:
      - shape: text
        text: "8"
        font: font.numfont
"""
    resolved = _build(write_design, db, bag, body, ttf)
    image = _draw(resolved)
    placed = _find(resolved, "row")
    part = placed.parts[0]

    assert len(placed.copies) == 3
    for index in placed.copies:
        anchor = pattern_text_anchor(part, *placed.transform(index))
        assert _near(image, anchor, WHITE, tolerance=TOLERANCE), \
            f"copy {index} missing ink near {anchor}"


# -- colour: a per-copy `color:` on the text part -----------------------------


def test_per_copy_colour_paints_only_that_copys_glyph_red(write_design, db, bag, ttf):
    body = """  hours:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 3
    parts:
      - shape: text
        text: "8"
        font: font.numfont
        at: {dy: -60px}
        color: "copy == 1 ? palette.red : palette.white"
"""
    resolved = _build(write_design, db, bag, body, ttf)
    image = _draw(resolved)
    placed = _find(resolved, "hours")
    part = placed.parts[0]

    for index in placed.copies:
        anchor = pattern_text_anchor(part, *placed.transform(index))
        expected, other = (RED, WHITE) if index == 1 else (WHITE, RED)
        assert _near(image, anchor, expected, tolerance=TOLERANCE), \
            f"copy {index} missing {expected} ink near {anchor}"
        assert not _near(image, anchor, other, tolerance=TOLERANCE), \
            f"copy {index} unexpectedly has {other} ink near {anchor}"
