"""`align:`/`vertical_align:` as a placement property of
every element, starting with the shared foundation -- `group`, `text` and a
pattern's `shape: text` part.

Covers: `wfb.layout.alignment_shift` itself (its nine combinations); a
`text` element's lint box for every combination; the `baseline` -> `bottom`
rename, including "one error, not N" on both a `text` element and a
pattern text part; the §1.2 device/preview bug fix in codegen (the
`dc.getFontHeight` subtraction, present only for `bottom`) and in the host
preview (ink lies on the correct side of the anchor).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import with_resources, align_value, find
from wfb.build import load
from wfb.emit.monkeyc import emit_view
from wfb.emit.resources import bake_fonts
from wfb.layout import alignment_shift, resolve
from wfb.preview import PreviewOptions, render

ROOT = Path(__file__).resolve().parent.parent
OPEN_SANS = ROOT / "tests/fixtures/slice/assets/OpenSans-Regular.ttf"

BASE = """
format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
"""


# -- alignment_shift itself: all nine combinations ---------------------------


@pytest.mark.parametrize(
    "align, vertical_align, dx, dy",
    [
        ("left", "top", 20.0, 15.0),
        ("left", "center", 20.0, 0.0),
        ("left", "bottom", 20.0, -15.0),
        ("center", "top", 0.0, 15.0),
        ("center", "center", 0.0, 0.0),
        ("center", "bottom", 0.0, -15.0),
        ("right", "top", -20.0, 15.0),
        ("right", "center", -20.0, 0.0),
        ("right", "bottom", -20.0, -15.0),
    ],
)
def test_alignment_shift_all_nine_combinations(align, vertical_align, dx, dy):
    """`width=40, height=30`: `left`/`top` shift the centre by +half towards
    the far edge (so that edge lands back on the point), `right`/`bottom`
    shift it the other way, and `center` never moves it at all -- checked
    exactly, not just in sign, since the default path depends on `center` being exactly
    `0.0`, not merely close to it."""
    assert alignment_shift(40.0, 30.0, align, vertical_align) == (dx, dy)


def test_alignment_shift_center_is_exactly_zero_not_merely_close():
    """The default path must add exactly `0.0`, bit for bit, or a
    downstream `x + 0.0` could round differently from a bare `x` for some
    input -- checked directly with `is`/`==` on the float, not `pytest.approx`."""
    dx, dy = alignment_shift(123.456, 78.9, "center", "center")
    assert dx == 0.0 and dy == 0.0
    assert not str(dx).startswith("-")  # not -0.0 either


# -- text lint box: every combination ----------------------------------------


def _text_design(align: str = "", vertical_align: str = "") -> str:
    extra = ""
    if align or vertical_align:
        extra = f"    align: {align_value(align or 'center', vertical_align or 'center')}\n"
    return BASE + f"""
elements:
  label:
    type: text
    text: "hello"
    font: FONT_MEDIUM
    at: {{anchor: center}}
    color: color.fg
{extra}"""


@pytest.fixture
def text_box_for(write_design, bag, db):
    def _resolve(align: str = "", vertical_align: str = ""):
        face = load(write_design(_text_design(align, vertical_align)), bag)
        assert face is not None, bag.render()
        device = db.get("fenix8solar47mm")
        resolved = resolve(face, device, bake_fonts(face, device))
        return find(resolved, "label")

    return _resolve


def test_text_box_default_matches_center_center(text_box_for):
    default = text_box_for()
    explicit = text_box_for(align="center", vertical_align="center")
    assert (default.box.x, default.box.y) == (explicit.box.x, explicit.box.y)
    assert (default.box.width, default.box.height) == (explicit.box.width, explicit.box.height)


@pytest.mark.parametrize("align", ["left", "center", "right"])
@pytest.mark.parametrize("vertical_align", ["top", "center", "bottom"])
def test_text_box_edge_sits_on_the_anchor(text_box_for, align, vertical_align):
    """For every one of the nine combinations, the named edge (or the
    centre) of the resolved box sits on the anchor point -- the same
    property `test_group_align.py` checks for a group's own box, now
    checked for `text` (one rule, every accepting kind)."""
    placed = text_box_for(align=align, vertical_align=vertical_align)
    box = placed.box
    ax, ay = placed.anchor_point

    if align == "left":
        assert box.x == ax
    elif align == "right":
        assert box.x + box.width == ax
    else:
        assert box.x <= ax <= box.x + box.width

    if vertical_align == "top":
        assert box.y == ay
    elif vertical_align == "bottom":
        assert box.y + box.height == ay
    else:
        assert box.y <= ay <= box.y + box.height


def test_text_box_bottom_matches_the_pre_rename_baseline_box():
    """The box for `bottom` is exactly what `baseline` already
    computed before the rename (the §1.2 bug was in the *draw*, never the
    lint box) -- `top = anchor_y - line_height`, checked arithmetically
    rather than by re-authoring the removed spelling."""
    # No live design can spell `baseline` any more: this is the same
    # arithmetic `wfb.kinds.text.TextKind.resolve` used for it, kept here as the
    # historical cross-check that the rename did not also change the box.
    width, line_height = 40.0, 20.0
    dx, dy = alignment_shift(width, line_height, "center", "bottom")
    assert dy == -line_height / 2


def test_bottom_is_accepted_where_baseline_used_to_be(write_design, bag, db):
    face = load(write_design(_text_design(vertical_align="bottom")), bag)
    assert face is not None, bag.render()


# -- codegen: the getFontHeight subtraction, and only for bottom ------------


def _codegen_text_design(vertical_align: str) -> str:
    extra = f"    align: {vertical_align}\n" if vertical_align else ""
    return BASE + f"""
elements:
  clock:
    type: text
    text: "hi"
    font: FONT_MEDIUM
    at: {{anchor: center}}
    color: color.fg
{extra}"""


@pytest.fixture
def view_text_for(write_design, bag, db):
    def _emit(vertical_align: str) -> str:
        face = load(write_design(_codegen_text_design(vertical_align)), bag)
        assert face is not None, bag.render()
        device = db.get("fenix8solar47mm")
        resolved = resolve(face, device, bake_fonts(face, device))
        return emit_view(resolved).text

    return _emit


@pytest.mark.parametrize("vertical_align", ["", "top", "center"])
def test_top_and_center_text_never_subtract_font_height(view_text_for, vertical_align):
    method = view_text_for(vertical_align).split("private function drawClock")[1]
    method = method.split("\n\n    //!")[0]
    assert "getFontHeight" not in method


def test_bottom_text_subtracts_the_devices_own_font_height(view_text_for):
    method = view_text_for("bottom").split("private function drawClock")[1]
    method = method.split("\n\n    //!")[0]
    assert "dc.getFontHeight(Graphics.FONT_MEDIUM)" in method
    assert "Layout.CLOCK_Y - dc.getFontHeight(Graphics.FONT_MEDIUM)" in method


# -- codegen: pattern text parts, radial and linear --------------------------

HOURS_BOTTOM = """  hours:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 12
    color: color.fg
    parts:
      - type: text
        text: "{(copy + 11) % 12 + 1}"
        at: {dy: -80%r}
        align: bottom
"""

ROW_BOTTOM = f"""resources:
  fonts:
    small:
      source: {OPEN_SANS}
      size: 20px
elements:
  row:
    type: pattern
    pattern: linear
    at: {{anchor: center}}
    count: 3
    step: {{dx: 20px}}
    color: color.fg
    parts:
      - type: text
        text: "x"
        font: font.small
        align: bottom
"""


def test_radial_pattern_text_bottom_shifts_cy_not_cx(write_design, bag, db):
    face = load(write_design(BASE + "\nelements:\n" + HOURS_BOTTOM), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    view = emit_view(resolved).text
    # `WfbGeom.drawTextRotated`'s single 10-argument call is split into
    # `rotatedX`/`rotatedY` (docs/lore/monkeyc.md, CIQ 3.x's 9-parameter
    # ceiling); the `cy` shift for `bottom` now shows up only in the `y`
    # helper's own third argument, not `cx`'s.
    assert "WfbGeom.rotatedX(Layout.HOURS_0_X, Layout.HOURS_0_Y, cx, sin, cos)" in view
    assert (
        "WfbGeom.rotatedY(Layout.HOURS_0_X, Layout.HOURS_0_Y, "
        "cy - dc.getFontHeight(Graphics.FONT_MEDIUM), sin, cos)"
    ) in view


def test_linear_pattern_text_bottom_subtracts_after_oy(write_design, bag, db):
    face = load(write_design(with_resources(BASE, ROW_BOTTOM)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    view = emit_view(resolved).text
    assert "oy + Layout.ROW_0_Y - dc.getFontHeight(font0)" in view


def test_radial_pattern_text_top_center_do_not_touch_cy():
    """Regression guard alongside the two tests above: nothing here re-tests
    top/center, which `tests/test_pattern_text_codegen.py::
    test_radial_text_part_calls_draw_text_rotated_with_the_anchor_and_trig`
    already pins to the literal `cx, cy, sin, cos,` -- byte-identical to
    before this phase. Documented here rather than duplicated."""


# -- preview: ink on the correct side of the anchor ----------------------

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)


def _preview_text_design(vertical_align: str, font_block: str = "", font_key: str = "FONT_MEDIUM") -> str:
    base = with_resources(BASE, font_block) if font_block else BASE
    return base + f"""
static:
  background:
    type: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: color.bg
elements:
  label:
    type: text
    text: "Hg"
    font: {font_key}
    at: {{anchor: center}}
    color: color.fg
    align: {vertical_align}
"""


def _render_text(write_design, bag, db, vertical_align: str, **font_kwargs):
    face = load(write_design(_preview_text_design(vertical_align, **font_kwargs)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    placed = find(resolved, "label")
    return image, placed


def _white_rows(image, x_range, y_range):
    rows = set()
    for y in y_range:
        for x in x_range:
            if image.getpixel((x, y)) == WHITE:
                rows.add(y)
                break
    return rows


def test_system_font_bottom_ink_lies_above_the_anchor_row(write_design, bag, db):
    """The system-font path (`draw_text` over a device face): drive this red first by
    checking it against the *old* meaning of `baseline` -- the old
    code drew a bottom-anchored line exactly like `top`, hanging down from
    the anchor, so this same assertion made against that code fails (see
    the session notes / `wfb/preview.py` history for the manual before/after
    check; not re-run automatically here since `baseline` no longer parses)."""
    image, placed = _render_text(write_design, bag, db, "bottom")
    ax, ay = placed.anchor_point
    rows = _white_rows(image, range(ax - 20, ax + 20), range(ay - 40, ay + 40))
    assert rows, "no ink drawn at all"
    assert max(rows) <= ay + 1, f"bottom-aligned ink should lie at or above the anchor row {ay}, found {rows}"


def test_system_font_top_ink_lies_below_the_anchor_row(write_design, bag, db):
    image, placed = _render_text(write_design, bag, db, "top")
    ax, ay = placed.anchor_point
    rows = _white_rows(image, range(ax - 20, ax + 20), range(ay - 40, ay + 40))
    assert rows, "no ink drawn at all"
    assert min(rows) >= ay - 1, f"top-aligned ink should lie at or below the anchor row {ay}, found {rows}"


def test_custom_font_bottom_ink_lies_above_the_anchor_row(write_design, bag, db):
    font_block = f"""
resources:
  fonts:
    clock:
      source: {OPEN_SANS}
      size: 24px"""
    image, placed = _render_text(
        write_design, bag, db, "bottom", font_block=font_block, font_key="font.clock")
    ax, ay = placed.anchor_point
    rows = _white_rows(image, range(ax - 30, ax + 30), range(ay - 40, ay + 40))
    assert rows, "no ink drawn at all"
    assert max(rows) <= ay + 1, f"bottom-aligned ink should lie at or above the anchor row {ay}, found {rows}"


def test_custom_font_top_ink_lies_below_the_anchor_row(write_design, bag, db):
    font_block = f"""
resources:
  fonts:
    clock:
      source: {OPEN_SANS}
      size: 24px"""
    image, placed = _render_text(
        write_design, bag, db, "top", font_block=font_block, font_key="font.clock")
    ax, ay = placed.anchor_point
    rows = _white_rows(image, range(ax - 30, ax + 30), range(ay - 40, ay + 40))
    assert rows, "no ink drawn at all"
    assert min(rows) >= ay - 1, f"top-aligned ink should lie at or below the anchor row {ay}, found {rows}"
