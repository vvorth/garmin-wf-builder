"""The host-side preview renderer, `type: pattern` (plan 05, phase 2b).

Each test exercises a contrast a broken `PlacedPattern.transform` (or a
broken draw-order/part-shape branch in `wfb.kinds.pattern.draw_preview`) could fail --
not just "the preview doesn't crash" (`docs/lore/working-agreement.md` on the
`00:00`/`11:11` trap). Every design here is a minimal, self-contained face
built with `write_design` -- a solid black background plus one or two
`static:` pattern elements -- so a pixel's colour is unambiguous: it is
either the background or one part's own colour, nothing else competes for
the same spot.

The device is `fenix8solar47mm` (260x260, so centre is (130, 130)), like
`tests/test_hands_preview.py`.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from wfb.build import load
from wfb.diagnostics import Bag
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

CX, CY = 130, 130
BACKGROUND = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)
BLUE = (0, 0, 255)
ORANGE = (255, 85, 0)
CYAN = (0, 255, 255)

_HEADER = """\
format: 1
face:
  id: 8f14e45f-ceea-467e-9c0c-89f7c6a9309b
  name: PatternsPreviewTest
targets: [fenix8solar47mm]
palette:
  black: "#000000"
  white: "#FFFFFF"
  red: "#FF0000"
  blue: "#0000FF"
  orange: "#FF5500"
  cyan: "#00FFFF"
static:
  background:
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.black
{body}
"""


def _render(write_design, db, bag, body: str, **options):
    """Write a one-pattern face, build it through the real pipeline (loader,
    desugar, schema, IR, layout -- the same stages `wfb.build.load` runs,
    minus the toolchain), and render it with no scaling, quantising or bezel
    mask, so every pixel maps 1:1 onto the device's own coordinates and no
    colour is snapped to the 64-colour panel."""
    path = write_design(_HEADER.format(body=body))
    face = load(path, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    opts = {"scale": 1, "mask_shape": False, "quantise": False, **options}
    return render(resolved, PreviewOptions(**opts))


def _polar(cx: int, cy: int, r: float, degrees: float) -> tuple[int, int]:
    """A pixel at `r` px from `(cx, cy)`, `degrees` clockwise from 12
    o'clock -- the author convention `docs/plans/05-patterns.md` §5.3 uses
    for `start_angle`/`start`/`step`, and the same one `arc_span` maps onto
    Pillow's own (3-o'clock, clockwise) coordinate system."""
    theta = math.radians(degrees)
    return (round(cx + r * math.sin(theta)), round(cy - r * math.cos(theta)))


def _near(image, point: tuple[int, int], color, tolerance: int = 2) -> bool:
    """Whether `color` appears within `tolerance` px of `point` -- Pillow's
    arc rasterises its own stroke pixels, which do not necessarily include
    the single nearest-integer point a continuous radius/angle formula
    predicts, so an arc-ink assertion needs a small neighbourhood rather
    than one exact pixel. `tolerance` stays well under the angular/radial
    gap to any *other* segment, so this cannot accidentally match the wrong
    one."""
    x0, y0 = point
    for dx in range(-tolerance, tolerance + 1):
        for dy in range(-tolerance, tolerance + 1):
            if image.getpixel((x0 + dx, y0 + dy)) == color:
                return True
    return False


# A radial line template shared by the "12/3/6/9" family of tests below:
# copy 0, drawn at 12 o'clock, is a short radial line 20-40px out from the
# origin -- far enough from the centre pixel that a bug rotating the wrong
# way, or not rotating at all, lands on background instead.
_CROSS_PARTS = """    parts:
      - {shape: line, at: {dy: -40px}, to: {dy: -20px}, thickness: 3px}
"""


# -- radial: the transform rotates copy 0 by `start + i * step` --------------


def test_radial_line_pattern_count_4_draws_at_12_3_6_9_not_the_diagonals(write_design, db, bag):
    body = f"""  cross:
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 4
    color: palette.white
{_CROSS_PARTS}"""
    image = _render(write_design, db, bag, body)
    assert image.getpixel((CX, CY - 30)) != BACKGROUND  # 12 o'clock
    assert image.getpixel((CX + 30, CY)) != BACKGROUND  # 3 o'clock
    assert image.getpixel((CX, CY + 30)) != BACKGROUND  # 6 o'clock
    assert image.getpixel((CX - 30, CY)) != BACKGROUND  # 9 o'clock
    # A diagonal (45deg from 12 o'clock, same 30px reach) is between copies
    # -- nothing was asked to draw there.
    assert image.getpixel(_polar(CX, CY, 30, 45)) == BACKGROUND


def test_skip_removes_exactly_that_copys_ink(write_design, db, bag):
    """`skip: [1]` leaves out the 3 o'clock copy (index 1: 0=12, 1=3, 2=6,
    3=9 o'clock at the default 90deg step) and nothing else."""
    body = f"""  cross:
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 4
    skip: [1]
    color: palette.white
{_CROSS_PARTS}"""
    image = _render(write_design, db, bag, body)
    assert image.getpixel((CX, CY - 30)) != BACKGROUND  # 12 -- still drawn
    assert image.getpixel((CX + 30, CY)) == BACKGROUND  # 3 -- skipped
    assert image.getpixel((CX, CY + 30)) != BACKGROUND  # 6 -- still drawn
    assert image.getpixel((CX - 30, CY)) != BACKGROUND  # 9 -- still drawn


def test_skip_every_removes_exactly_those_copies_ink(write_design, db, bag):
    """`skip_every: 2` leaves out copies 0 and 2 (multiples of 2: 12 and 6
    o'clock), keeping 1 and 3 (3 and 9 o'clock)."""
    body = f"""  cross:
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 4
    skip_every: 2
    color: palette.white
{_CROSS_PARTS}"""
    image = _render(write_design, db, bag, body)
    assert image.getpixel((CX, CY - 30)) == BACKGROUND  # 12 -- skipped (i=0)
    assert image.getpixel((CX + 30, CY)) != BACKGROUND  # 3 -- kept (i=1)
    assert image.getpixel((CX, CY + 30)) == BACKGROUND  # 6 -- skipped (i=2)
    assert image.getpixel((CX - 30, CY)) != BACKGROUND  # 9 -- kept (i=3)


def test_start_45deg_moves_the_ink_to_the_diagonals(write_design, db, bag):
    body = f"""  cross:
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 4
    start: 45deg
    color: palette.white
{_CROSS_PARTS}"""
    image = _render(write_design, db, bag, body)
    assert image.getpixel(_polar(CX, CY, 30, 45)) != BACKGROUND  # copy 0
    assert image.getpixel(_polar(CX, CY, 30, 135)) != BACKGROUND  # copy 1
    assert image.getpixel((CX, CY - 30)) == BACKGROUND  # 12 o'clock is now empty


# -- linear: copy i's origin is `at + i * step` -------------------------------


def test_linear_patterns_copies_land_at_origin_plus_i_times_step(write_design, db, bag):
    body = """  dots:
    type: pattern
    pattern: linear
    at: {anchor: center, dx: -30px, dy: 0px}
    count: 4
    step: {dx: 20px}
    color: palette.orange
    parts:
      - {shape: circle, radius: 4px}
"""
    image = _render(write_design, db, bag, body)
    for i in range(4):
        x = CX - 30 + 20 * i
        assert image.getpixel((x, CY)) == ORANGE, f"copy {i} missing at x={x}"


def test_a_skipped_linear_index_leaves_a_gap(write_design, db, bag):
    body = """  dots:
    type: pattern
    pattern: linear
    at: {anchor: center, dx: -30px, dy: 0px}
    count: 4
    step: {dx: 20px}
    skip: [2]
    color: palette.orange
    parts:
      - {shape: circle, radius: 4px}
"""
    image = _render(write_design, db, bag, body)
    for i in (0, 1, 3):
        x = CX - 30 + 20 * i
        assert image.getpixel((x, CY)) == ORANGE, f"copy {i} missing at x={x}"
    assert image.getpixel((CX - 30 + 20 * 2, CY)) == BACKGROUND  # copy 2: skipped


# -- arc parts: the start angle turns with the copy ---------------------------


def test_a_radial_arc_patterns_segments_turn_with_the_copy(write_design, db, bag):
    """Four 20deg segments, 90deg apart, each `start_angle: 10deg` into its
    copy's slice -- so copy 0 spans author angles [10, 30] and copy 2 (two
    steps further, 180deg round) spans [190, 210]: ink at the *rotated*
    midpoints of both, and nothing in the 70deg gap between copy 0 and
    copy 1."""
    body = """  segs:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 4
    color: palette.cyan
    parts:
      - {shape: arc, radius: 40px, thickness: 6px, start_angle: 10deg, sweep: 20deg}
"""
    image = _render(write_design, db, bag, body)
    assert _near(image, _polar(CX, CY, 40, 20), CYAN)  # copy 0 midpoint (10+30)/2
    assert _near(image, _polar(CX, CY, 40, 200), CYAN)  # copy 2 midpoint (190+210)/2
    assert not _near(image, _polar(CX, CY, 40, 60), CYAN)  # gap between copy 0 and 1


# -- draw order: copies ascending, parts in list order within a copy --------


def test_a_two_part_templates_second_part_draws_over_the_first(write_design, db, bag):
    """Two full-size, fully overlapping circles at the same origin: the
    part listed second (blue) must be the one visible on top."""
    body = """  order:
    type: pattern
    pattern: linear
    at: {anchor: center, dx: -80px, dy: -80px}
    count: 1
    step: {dx: 0px}
    parts:
      - {shape: circle, radius: 10px, color: palette.red}
      - {shape: circle, radius: 10px, color: palette.blue}
"""
    image = _render(write_design, db, bag, body)
    assert image.getpixel((CX - 80, CY - 80)) == BLUE


def test_copy_i_plus_1_draws_over_copy_i(write_design, db, bag):
    """Two copies 5px apart; each copy is a big red disc (radius 6) with a
    small blue dot (radius 3) on top of its own centre. copy 0's centre is
    only 5px from copy 1's centre, so copy 1's big red disc (radius 6)
    reaches back over copy 0's own blue dot. If copies draw ascending (copy
    1 painted after copy 0, as the spec requires), copy 0's centre pixel
    ends up red again; if the draw order were reversed, it would stay blue.
    """
    body = """  order2:
    type: pattern
    pattern: linear
    at: {anchor: center, dx: 40px, dy: -80px}
    count: 2
    step: {dx: 5px}
    parts:
      - {shape: circle, radius: 6px, color: palette.red}
      - {shape: circle, radius: 3px, color: palette.blue}
"""
    image = _render(write_design, db, bag, body)
    origin0 = (CX + 40, CY - 80)
    origin1 = (CX + 45, CY - 80)
    assert image.getpixel(origin0) == RED, "copy 1's red did not draw over copy 0's blue"
    assert image.getpixel(origin1) == BLUE  # copy 1's own top part, drawn last


# -- rectangle parts fold into a polygon, which rotates like any other -------


def test_a_rectangle_part_turned_90deg_becomes_horizontal(write_design, db, bag):
    """copy 0 (0deg) is a tall, narrow bar sticking up from the origin;
    copy 1 (90deg further) must be the same bar turned on its side: wide in
    x, narrow in y, offset to the *side* of its origin rather than above
    it."""
    body = """  bar:
    type: pattern
    pattern: radial
    at: {anchor: center, dx: -80px, dy: 80px}
    count: 4
    color: palette.white
    parts:
      - {shape: rectangle, at: {dy: -20px}, size: {width: 4px, height: 20px}}
"""
    image = _render(write_design, db, bag, body)
    ox, oy = CX - 80, CY + 80

    # copy 0: vertical -- tall (y 180..200) and narrow (x 48..52).
    assert image.getpixel((ox, oy - 20)) == WHITE  # inside the vertical bar
    assert image.getpixel((ox + 10, oy - 20)) == BACKGROUND  # well outside its 4px width

    # copy 1 (90deg): horizontal -- wide (x 60..80) and narrow (y 208..212).
    assert image.getpixel((ox + 20, oy)) == WHITE  # inside the horizontal bar
    assert image.getpixel((ox + 20, oy + 15)) == BACKGROUND  # well outside its 4px height
    assert image.getpixel((ox + 12, oy)) == WHITE  # the bar's left end (wide extent)
    assert image.getpixel((ox + 28, oy)) == WHITE  # the bar's right end (wide extent)


# -- smoke test: the shipped example ------------------------------------------


DESIGN = Path(__file__).resolve().parent.parent / "examples" / "features" / "patterns" / "face.yaml"
SAVE_TO = Path("/home/agent/.claude/jobs/32690555/tmp/patterns-preview.png")


def test_examples_patterns_face_renders_without_crashing(db, bag):
    """`examples/features/patterns/face.yaml` -- every kind this plan added (radial
    and linear, `skip`/`skip_every`, `start:`, `arc` parts, a multi-part
    linear pattern outside `static:`) in one real design. Not a pixel-level
    assertion -- that is what the tests above are for -- just proof the
    renderer gets through the whole thing and produces a real image."""
    if not DESIGN.exists():
        pytest.skip("examples/features/patterns/face.yaml is missing")
    face = load(DESIGN, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    image = render(resolved, PreviewOptions(scale=2))
    assert image.size == (device.width * 2, device.height * 2)
    colors = {pixel for pixel in image.get_flattened_data()}
    assert len(colors) > 2, "the preview is blank"

    SAVE_TO.parent.mkdir(parents=True, exist_ok=True)
    image.save(SAVE_TO, format="PNG")


# -- per-copy colour: `copy` and `date.weekday` ---------------------------------


_WEEK = """\
elements:
  week:
    type: pattern
    pattern: linear
    at: {{anchor: center, dx: -60px}}
    count: 7
    step: {{dx: 20px}}
    parts:
      - shape: circle
        radius: 4px
        color: "copy == (date.weekday + 5) % 7 ? palette.cyan : palette.red"
"""


@pytest.mark.parametrize("weekday,lit", [(2, 0), (4, 2), (1, 6)])
def test_the_week_row_lights_todays_copy(write_design, db, bag, weekday, lit):
    """`date.weekday` 2 (Monday) lights copy 0, 4 (Wednesday) copy 2, and 1
    (Sunday) copy 6 -- every other copy is red.  A colour evaluated once for
    the whole pattern (copy fixed at 0), or with the wrong weekday offset,
    lights the wrong dot in at least one row."""
    image = _render(write_design, db, bag, _WEEK.format(),
                    sample={"date.weekday": weekday})
    for index in range(7):
        pixel = image.getpixel((CX - 60 + 20 * index, CY))
        assert pixel == (CYAN if index == lit else RED), (index, pixel)


# -- `when_absent: hide` + per-copy part `visible:` (B7, 2026-09-15) -----------


#: A 5-copy move-bar row: a blue "track" circle always drawn, an orange
#: "lit" circle on top of it only for copies under the move-bar level.
#: Radii chosen (6px/3px) so the orange dot, when drawn, fully covers the
#: blue one at that copy's centre pixel -- a broken implementation that
#: ignored `visible:` (always drawing orange) or that hid only the gated
#: part instead of the whole pattern would both fail at least one pixel
#: below.
_BARS = """\
elements:
  bars:
    type: pattern
    pattern: linear
    at: {anchor: center, dx: -30px, dy: 0px}
    count: 5
    step: {dx: 15px}
    when_absent: hide
    parts:
      - {shape: circle, radius: 6px, color: palette.blue}
      - shape: circle
        radius: 3px
        color: palette.orange
        visible: "copy < activity.move_bar_level"
"""


def test_move_bar_level_2_lights_exactly_copies_0_and_1(write_design, db, bag):
    image = _render(write_design, db, bag, _BARS, sample={"activity.move_bar_level": 2})
    for index in range(5):
        x = CX - 30 + 15 * index
        expected = ORANGE if index < 2 else BLUE
        assert image.getpixel((x, CY)) == expected, (index, image.getpixel((x, CY)))


def test_move_bar_absent_hides_the_whole_pattern_track_included(write_design, db, bag):
    """`when_absent: hide` on the pattern: with the source missing, nothing
    draws at all -- not even the always-on blue track part, which has no
    `visible:` of its own and would otherwise still be there."""
    image = _render(write_design, db, bag, _BARS, sample={"activity.move_bar_level": None})
    for index in range(5):
        x = CX - 30 + 15 * index
        assert image.getpixel((x, CY)) == BACKGROUND, (index, image.getpixel((x, CY)))
