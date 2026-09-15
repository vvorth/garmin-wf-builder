"""Plan 07 phase B: `align:`/`vertical_align:` on `shape` (rectangle,
rounded_rectangle, ellipse, circle, arc -- not polygon or line), `progress`
(both styles) and `graph` (`docs/plans/07-align-everywhere.md` §4, Phase B
row).

Mechanism (a) only: every one of these resolves alignment entirely at build
time by moving the placement box's centre (`wfb.layout.alignment_shift`,
already the one implementation since phase A). Every test here picks pixel
(`px`) units so the expected geometry is hand-computable exactly, no float
rounding to reason about. The device is `fenix8solar47mm`: a 260x260 screen,
minor radius 130, screen centre (130, 130) (`tests/test_layout.py`), so
`at: {anchor: center}` always resolves to the point (130, 130).

Covers: the declared placement box's named edge (or centre) landing exactly
on `at:` for every accepted kind and value, at both `align: left` +
`vertical_align: top` and `align: right` + `vertical_align: bottom`; that an
outlined shape's *declared* geometry is what aligns, not its pen-padded
`box`; that `shape: arc`/`progress` `style: arc` align by the full circle
regardless of `sweep:`; the generated `Layout` constants for one shape,
proving the device reads the moved geometry; and the polygon/line rejection
messages (R3), one error per key, not per element.
"""

from __future__ import annotations

from tests.test_diagnostics import load
from wfb.emit.monkeyc import emit_layout
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve

BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
"""

AT_CENTER = 130, 130  # fenix8solar47mm's screen centre


def find(resolved, element_id):
    return next(p for p in resolved.items if p.id == element_id)


def _resolve(write_design, bag, db, elements_yaml: str):
    face = load(write_design(BASE + "elements:\n" + elements_yaml), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    fonts = bake_fonts(face, device)
    return resolve(face, device, fonts)


# -- rectangle / rounded_rectangle -------------------------------------------


def _rect_yaml(shape: str, element_id: str, align: str, vertical_align: str,
                extra: str = "") -> str:
    return f"""  - id: {element_id}
    type: shape
    shape: {shape}
    at: {{anchor: center}}
    size: {{width: 40px, height: 30px}}
    align: {align}
    vertical_align: {vertical_align}
    color: palette.fg
{extra}"""


def test_rectangle_left_top_declared_rect_top_left_corner_on_at(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, _rect_yaml("rectangle", "r", "left", "top"))
    box = find(resolved, "r").box
    assert (box.x, box.y, box.width, box.height) == (130, 130, 40, 30)


def test_rectangle_right_bottom_declared_rect_bottom_right_corner_on_at(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, _rect_yaml("rectangle", "r", "right", "bottom"))
    box = find(resolved, "r").box
    assert (box.x, box.y, box.width, box.height) == (90, 100, 40, 30)
    assert (box.x + box.width, box.y + box.height) == AT_CENTER


def test_rounded_rectangle_left_top(write_design, bag, db):
    resolved = _resolve(
        write_design, bag, db,
        _rect_yaml("rounded_rectangle", "rr", "left", "top", "    corner_radius: 5px\n"))
    box = find(resolved, "rr").box
    assert (box.x, box.y, box.width, box.height) == (130, 130, 40, 30)


def test_rounded_rectangle_right_bottom(write_design, bag, db):
    resolved = _resolve(
        write_design, bag, db,
        _rect_yaml("rounded_rectangle", "rr", "right", "bottom", "    corner_radius: 5px\n"))
    box = find(resolved, "rr").box
    assert (box.x + box.width, box.y + box.height) == AT_CENTER


# -- ellipse ------------------------------------------------------------------


def _ellipse_yaml(align: str, vertical_align: str) -> str:
    return f"""  - id: e
    type: shape
    shape: ellipse
    at: {{anchor: center}}
    size: {{width: 50px, height: 20px}}
    align: {align}
    vertical_align: {vertical_align}
    color: palette.fg
"""


def test_ellipse_left_top_declared_box_top_left_corner_on_at(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, _ellipse_yaml("left", "top"))
    box = find(resolved, "e").box
    assert (box.x, box.y, box.width, box.height) == (130, 130, 50, 20)


def test_ellipse_right_bottom_declared_box_bottom_right_corner_on_at(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, _ellipse_yaml("right", "bottom"))
    box = find(resolved, "e").box
    assert (box.x + box.width, box.y + box.height) == AT_CENTER


# -- circle ---------------------------------------------------------------


def _circle_yaml(align: str, vertical_align: str, element_id: str = "c",
                  extra: str = "") -> str:
    return f"""  - id: {element_id}
    type: shape
    shape: circle
    at: {{anchor: center}}
    radius: 20px
    align: {align}
    vertical_align: {vertical_align}
    color: palette.fg
{extra}"""


def test_circle_left_top_leftmost_and_topmost_points_on_at(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, _circle_yaml("left", "top"))
    placed = find(resolved, "c")
    cx, cy = placed.center
    assert (cx - placed.radius, cy - placed.radius) == AT_CENTER


def test_circle_right_bottom_rightmost_and_bottommost_points_on_at(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, _circle_yaml("right", "bottom"))
    placed = find(resolved, "c")
    cx, cy = placed.center
    assert (cx + placed.radius, cy + placed.radius) == AT_CENTER


def test_outlined_circle_aligns_by_the_declared_radius_not_the_padded_box(write_design, bag, db):
    """R4: an outline's pen pad must not move the shift -- `box` is padded
    by the pen straddle, but `center`/`radius` (the declared geometry) still
    land exactly on `at:`, the same as a filled circle."""
    resolved = _resolve(
        write_design, bag, db,
        _circle_yaml("left", "top", extra="    filled: false\n    thickness: 4px\n"))
    placed = find(resolved, "c")
    cx, cy = placed.center
    assert (cx - placed.radius, cy - placed.radius) == AT_CENTER
    # The padded box reaches further out than the declared circle.
    assert placed.box.x < cx - placed.radius


# -- arc: full circle regardless of sweep ------------------------------------


def _arc_yaml(align: str, vertical_align: str, element_id: str, sweep: str) -> str:
    return f"""  - id: {element_id}
    type: shape
    shape: arc
    at: {{anchor: center}}
    radius: 20px
    start_angle: 0deg
    sweep: {sweep}
    align: {align}
    vertical_align: {vertical_align}
    color: palette.fg
"""


def test_arc_aligns_like_a_full_circle_regardless_of_sweep(write_design, bag, db):
    """Plan 07 choice 3 (§6): the placement box is the full circle
    (`2*radius`), whatever `sweep:` is -- an arc with `sweep: 90deg` moves
    exactly as a full-circle (`sweep: 360deg`) arc does."""
    elements = _arc_yaml("left", "top", "quarter", "90deg") + \
        _arc_yaml("left", "top", "full", "360deg")
    resolved = _resolve(write_design, bag, db, elements)
    quarter = find(resolved, "quarter")
    full = find(resolved, "full")
    assert quarter.center == full.center
    assert (quarter.center[0] - quarter.radius, quarter.center[1] - quarter.radius) == AT_CENTER


def test_arc_right_bottom(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, _arc_yaml("right", "bottom", "a", "300deg"))
    placed = find(resolved, "a")
    cx, cy = placed.center
    assert (cx + placed.radius, cy + placed.radius) == AT_CENTER


# -- outlined rectangle: declared rect, not the padded box -------------------


def test_outlined_rectangle_left_top_uses_the_declared_rect(write_design, bag, db):
    resolved = _resolve(
        write_design, bag, db,
        _rect_yaml("rectangle", "or", "left", "top", "    filled: false\n    thickness: 4px\n"))
    placed = find(resolved, "or")
    rect = placed.rect
    assert (rect.x, rect.y, rect.width, rect.height) == (130, 130, 40, 30)
    # The pen straddles the declared edge, so the hit/safe-area box is larger.
    assert placed.box.x < rect.x
    assert placed.box.y < rect.y


def test_outlined_rectangle_right_bottom_uses_the_declared_rect(write_design, bag, db):
    resolved = _resolve(
        write_design, bag, db,
        _rect_yaml("rectangle", "or", "right", "bottom", "    filled: false\n    thickness: 4px\n"))
    placed = find(resolved, "or")
    rect = placed.rect
    assert (rect.x + rect.width, rect.y + rect.height) == AT_CENTER


# -- progress: bar and arc ----------------------------------------------------


def _progress_bar_yaml(align: str, vertical_align: str) -> str:
    return f"""  - id: p
    type: progress
    style: bar
    value: activity.steps
    max: activity.step_goal
    at: {{anchor: center}}
    size: {{width: 40px, height: 30px}}
    align: {align}
    vertical_align: {vertical_align}
    color: palette.fg
    when_absent: hide
"""


def test_progress_bar_left_top(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, _progress_bar_yaml("left", "top"))
    box = find(resolved, "p").box
    assert (box.x, box.y, box.width, box.height) == (130, 130, 40, 30)


def test_progress_bar_right_bottom(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, _progress_bar_yaml("right", "bottom"))
    box = find(resolved, "p").box
    assert (box.x + box.width, box.y + box.height) == AT_CENTER


def _progress_arc_yaml(align: str, vertical_align: str) -> str:
    return f"""  - id: p
    type: progress
    style: arc
    value: activity.steps
    max: activity.step_goal
    at: {{anchor: center}}
    radius: 20px
    thickness: 10px
    start_angle: 0deg
    sweep: 340deg
    align: {align}
    vertical_align: {vertical_align}
    color: palette.fg
    when_absent: hide
"""


def test_progress_arc_left_top(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, _progress_arc_yaml("left", "top"))
    placed = find(resolved, "p")
    cx, cy = placed.center
    assert (cx - placed.radius, cy - placed.radius) == AT_CENTER


def test_progress_arc_right_bottom(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, _progress_arc_yaml("right", "bottom"))
    placed = find(resolved, "p")
    cx, cy = placed.center
    assert (cx + placed.radius, cy + placed.radius) == AT_CENTER


# -- graph ---------------------------------------------------------------


def _graph_yaml(align: str, vertical_align: str) -> str:
    return f"""  - id: g
    type: graph
    series: heart_rate
    range: 4h
    at: {{anchor: center}}
    size: {{width: 40px, height: 30px}}
    align: {align}
    vertical_align: {vertical_align}
    color: palette.fg
"""


def test_graph_left_top(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, _graph_yaml("left", "top"))
    box = find(resolved, "g").box
    assert (box.x, box.y, box.width, box.height) == (130, 130, 40, 30)


def test_graph_right_bottom(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, _graph_yaml("right", "bottom"))
    box = find(resolved, "g").box
    assert (box.x + box.width, box.y + box.height) == AT_CENTER


# -- default byte-identity (R5) -----------------------------------------------


def test_default_center_center_is_byte_identical_to_no_keys_at_all(write_design, bag, db):
    with_keys = _resolve(write_design, bag, db, _rect_yaml("rectangle", "r", "center", "center"))
    without_keys = _resolve(write_design, bag, db, """  - id: r
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 40px, height: 30px}
    color: palette.fg
""")
    a, b = find(with_keys, "r").box, find(without_keys, "r").box
    assert (a.x, a.y, a.width, a.height) == (b.x, b.y, b.width, b.height)


# -- generated Layout constants: the device reads the moved geometry ---------


def test_layout_constants_use_the_moved_rectangle(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, _rect_yaml("rectangle", "moved_r", "left", "top"))
    layout = emit_layout(resolved).text
    assert "const MOVED_R_X as Number = 130;" in layout
    assert "const MOVED_R_Y as Number = 130;" in layout
    assert "const MOVED_R_WIDTH as Number = 40;" in layout
    assert "const MOVED_R_HEIGHT as Number = 30;" in layout


def test_layout_constants_use_the_moved_circle(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, _circle_yaml("right", "bottom", element_id="moved_c"))
    layout = emit_layout(resolved).text
    placed = find(resolved, "moved_c")
    cx, cy = placed.center
    assert f"const MOVED_C_CX as Number = {cx};" in layout
    assert f"const MOVED_C_CY as Number = {cy};" in layout
    assert (cx + placed.radius, cy + placed.radius) == AT_CENTER


# -- polygon / line: rejected, one error per key, not N ----------------------


def _polygon_yaml(extra: str) -> str:
    return f"""  - id: poly
    type: shape
    shape: polygon
    color: palette.fg
{extra}    points:
      - {{anchor: center, dy: 10px}}
      - {{anchor: center, dx: -10px, dy: 20px}}
      - {{anchor: center, dx: 10px, dy: 20px}}
"""


def test_polygon_rejects_align_with_the_no_single_at_reason(write_design, bag):
    load(write_design(BASE + "elements:\n" + _polygon_yaml("    align: left\n")), bag)
    assert not bag.ok()
    assert len(bag.errors) == 1
    message = bag.errors[0]
    assert "'align' is not used by 'shape: polygon'" in message.message
    notes = " ".join(message.notes)
    assert "every vertex is its own position" in notes
    assert "no 'at:' of its own" in notes


def test_polygon_rejects_both_keys_as_two_separate_errors(write_design, bag):
    """One error per key, not one per element (or per mistake bundled)."""
    load(
        write_design(BASE + "elements:\n" +
                     _polygon_yaml("    align: left\n    vertical_align: top\n")),
        bag,
    )
    assert not bag.ok()
    assert len(bag.errors) == 2
    messages = [d.message for d in bag.errors]
    assert any("'align' is not used by 'shape: polygon'" in m for m in messages)
    assert any("'vertical_align' is not used by 'shape: polygon'" in m for m in messages)


def _line_yaml(extra: str) -> str:
    return f"""  - id: ln
    type: shape
    shape: line
    at: {{anchor: center}}
    to: {{anchor: center, dx: 20px}}
    color: palette.fg
{extra}"""


def test_line_rejects_align_with_the_two_ends_reason(write_design, bag):
    load(write_design(BASE + "elements:\n" + _line_yaml("    align: left\n")), bag)
    assert not bag.ok()
    assert len(bag.errors) == 1
    message = bag.errors[0]
    assert "'align' is not used by 'shape: line'" in message.message
    assert any("two ends" in note for note in message.notes)


def test_line_rejects_vertical_align_too(write_design, bag):
    load(write_design(BASE + "elements:\n" + _line_yaml("    vertical_align: bottom\n")), bag)
    assert not bag.ok()
    assert len(bag.errors) == 1
    assert "'vertical_align' is not used by 'shape: line'" in bag.errors[0].message
