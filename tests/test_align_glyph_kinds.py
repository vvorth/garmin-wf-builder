"""Plan 07 phase C: `align:`/`vertical_align:` on `icon` (mechanism (b), a
glyph kind -- the same device-side justify a `text` element already uses)
and `complication_slot` (mechanism (c), ADR 0004's runtime-measured
exception -- the arithmetic lives on the device) (`docs/plans/
07-align-everywhere.md` §4, Phase C row).

Covers: an icon's lint box (static and dynamic `icon_for:`) moved by
`wfb.layout.alignment_shift` exactly like `text`'s, while its runtime anchor
(`Layout.<P>_CX/_CY`) stays put; the generated `TEXT_JUSTIFY_*` flags and the
`dc.getFontHeight` subtraction for `bottom`; that the exact default draw call
is unchanged (R5); icon preview ink on the correct side of the anchor; a
`complication_slot`'s per-`icon_position:` runtime arithmetic for a
non-default `align:`/`vertical_align:` (the pieces §3.2(c) specifies,
asserted literally); that its default codegen (every `icon_position:`,
fast path included) is still byte-identical to a design that never writes
either key; its estimated box moved the same way a glyph kind's lint box is;
and its preview pair origin moved.
"""

from __future__ import annotations

import re

import pytest

from tests.helpers import find
from wfb.build import load
from wfb.emit.monkeyc import emit_view
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

WHITE = (255, 255, 255)


def _white_pixels(image, x_range, y_range) -> set[tuple[int, int]]:
    pts = set()
    for y in y_range:
        for x in x_range:
            if image.getpixel((x, y)) == WHITE:
                pts.add((x, y))
    return pts


# =============================================================================
# icon
# =============================================================================

ICON_BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
"""


def _icon_yaml(element_id: str, align: str, vertical_align: str, dynamic: bool = False) -> str:
    body = "    icon_for: weather.condition\n" if dynamic else "    icon: heart\n"
    return f"""  - id: {element_id}
    type: icon
{body}    size: 20px
    at: {{anchor: center}}
    align: {align}
    vertical_align: {vertical_align}
    color: palette.fg
"""


def _resolve_icon(write_design, bag, db, elements_yaml: str):
    face = load(write_design(ICON_BASE + "elements:\n" + elements_yaml), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


# -- lint box: moved by alignment_shift, static and dynamic -------------------


@pytest.mark.parametrize("dynamic", [False, True])
def test_icon_lint_box_left_top_puts_top_left_corner_on_anchor(write_design, bag, db, dynamic):
    resolved = _resolve_icon(write_design, bag, db, _icon_yaml("i", "left", "top", dynamic))
    placed = find(resolved, "i")
    assert (placed.box.x, placed.box.y) == placed.anchor_point


@pytest.mark.parametrize("dynamic", [False, True])
def test_icon_lint_box_right_bottom_puts_bottom_right_corner_on_anchor(write_design, bag, db, dynamic):
    resolved = _resolve_icon(write_design, bag, db, _icon_yaml("i", "right", "bottom", dynamic))
    placed = find(resolved, "i")
    box = placed.box
    assert (box.x + box.width, box.y + box.height) == placed.anchor_point


def test_icon_box_default_matches_no_keys_at_all(write_design, bag, db):
    """R5: writing `align: center`/`vertical_align: center` explicitly must
    resolve to the exact same box (and the same `justify`) as writing
    neither key at all."""
    with_keys = find(_resolve_icon(write_design, bag, db, _icon_yaml("i", "center", "center")), "i")
    without_keys = find(_resolve_icon(write_design, bag, db, """  - id: i
    type: icon
    icon: heart
    size: 20px
    at: {anchor: center}
    color: palette.fg
"""), "i")
    a, b = with_keys.box, without_keys.box
    assert (a.x, a.y, a.width, a.height) == (b.x, b.y, b.width, b.height)
    assert with_keys.justify == without_keys.justify == ("TEXT_JUSTIFY_CENTER", "TEXT_JUSTIFY_VCENTER")
    assert with_keys.anchor_point == without_keys.anchor_point


# -- codegen: justify flags, the getFontHeight subtraction, default unchanged -


def _view_icon(write_design, bag, db, align: str, vertical_align: str, dynamic: bool = False) -> str:
    face = load(write_design(ICON_BASE + "elements:\n" +
                             _icon_yaml("wicon", align, vertical_align, dynamic)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    return emit_view(resolved).text


def test_icon_default_draw_call_is_byte_identical(write_design, bag, db):
    """The exact literal this call has always emitted (R5) -- center/center,
    the anchor untouched, the flags a fixed literal, no getFontHeight."""
    view = _view_icon(write_design, bag, db, "center", "center")
    assert 'dc.drawText(Layout.WICON_CX, Layout.WICON_CY, font,\n                    "' in view
    assert "Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);" in view
    assert "getFontHeight" not in view


def test_icon_left_top_uses_left_justify_with_no_vcenter(write_design, bag, db):
    """`vertical_align: top` is what drops VCENTER (it is added for
    `center` regardless of `align`, exactly as `Resolver._justify` already
    does for `text`) -- `align: left` alone still centres vertically."""
    view = _view_icon(write_design, bag, db, "left", "top")
    assert "Graphics.TEXT_JUSTIFY_LEFT);" in view
    assert "TEXT_JUSTIFY_VCENTER" not in view
    # the anchor itself never moves for a glyph kind (§3.2(b)).
    assert "Layout.WICON_CX, Layout.WICON_CY, font," in view


def test_icon_bottom_subtracts_the_icon_fonts_own_height(write_design, bag, db):
    view = _view_icon(write_design, bag, db, "center", "bottom")
    assert "Layout.WICON_CX, Layout.WICON_CY - dc.getFontHeight(font), font," in view
    # center/bottom: horizontal flag is CENTER, no VCENTER (bottom is not center).
    assert "Graphics.TEXT_JUSTIFY_CENTER);" in view


def test_icon_dynamic_bottom_also_subtracts_font_height(write_design, bag, db):
    """The dynamic (`icon_for:`) path shares `wfb.kinds.icon.emit_draw`'s one
    draw call -- this is not a second, weather-only copy of the alignment
    arithmetic."""
    view = _view_icon(write_design, bag, db, "left", "bottom", dynamic=True)
    assert "IconGlyphs.glyph(WfbWeather.chooseIcon(" in view
    assert "Layout.WICON_CX, Layout.WICON_CY - dc.getFontHeight(font), font," in view
    assert "Graphics.TEXT_JUSTIFY_LEFT);" in view


def test_icon_layout_constant_comment_only_on_non_default(write_design, bag, db):
    """The `_CX`/`_CY` constant names and values stay byte-identical either
    way (R5); only the trailing comment changes, and only when aligned."""
    from wfb.emit.monkeyc import emit_layout

    def _layout(align, vertical_align):
        face = load(write_design(
            ICON_BASE + "elements:\n" + _icon_yaml("wicon", align, vertical_align)), bag)
        assert face is not None, bag.render()
        device = db.get("fenix8solar47mm")
        resolved = resolve(face, device, bake_fonts(face, device))
        return emit_layout(resolved).text

    default = _layout("center", "center")
    aligned = _layout("left", "bottom")
    default_line = next(line for line in default.splitlines() if "WICON_CX" in line)
    aligned_line = next(line for line in aligned.splitlines() if "WICON_CX" in line)
    assert "//" not in default_line
    assert "//" in aligned_line
    assert "not the glyph" in aligned_line or "not its centre" in aligned_line


# -- preview: ink on the correct side of the anchor ---------------------------


def _icon_preview_design(align: str, vertical_align: str) -> str:
    return ICON_BASE + f"""
static:
  background:
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
elements:
  - id: label
    type: icon
    icon: heart
    size: 40px
    at: {{anchor: center}}
    color: palette.fg
    align: {align}
    vertical_align: {vertical_align}
"""


def _render_icon(write_design, bag, db, align: str, vertical_align: str):
    face = load(write_design(_icon_preview_design(align, vertical_align)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    return image, find(resolved, "label")


def test_icon_preview_left_ink_lies_at_or_right_of_the_anchor_column(write_design, bag, db):
    image, placed = _render_icon(write_design, bag, db, "left", "center")
    ax, ay = placed.anchor_point
    pts = _white_pixels(image, range(ax - 30, ax + 50), range(ay - 30, ay + 30))
    assert pts, "no ink drawn at all"
    assert min(x for x, _ in pts) >= ax - 1


def test_icon_preview_bottom_ink_lies_above_the_anchor_row(write_design, bag, db):
    image, placed = _render_icon(write_design, bag, db, "center", "bottom")
    ax, ay = placed.anchor_point
    pts = _white_pixels(image, range(ax - 30, ax + 30), range(ay - 50, ay + 30))
    assert pts, "no ink drawn at all"
    assert max(y for _, y in pts) <= ay + 1


# =============================================================================
# complication_slot
# =============================================================================

CS_BASE = """
format: 1
face:
  id: 6b2f9a3e-5c1d-4e8a-9f7b-3a1d6c8e2f40
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
config:
  data:
    top:
      default: complication.steps
      choices:
        - complication.steps
        - complication.heart_rate
"""


def _cs_yaml(element_id: str, icon_position: str, align: str, vertical_align: str) -> str:
    return f"""  - id: {element_id}
    type: complication_slot
    slot: config.data.top
    at: {{anchor: center}}
    icon_size: 8%r
    icon_position: {icon_position}
    color: palette.fg
    align: {align}
    vertical_align: {vertical_align}
"""


def _resolve_cs(write_design, bag, db, elements_yaml: str):
    face = load(write_design(CS_BASE + "elements:\n" + elements_yaml), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


def _view_cs(write_design, bag, db, icon_position: str, align: str, vertical_align: str) -> str:
    face = load(write_design(
        CS_BASE + "elements:\n" + _cs_yaml("slot", icon_position, align, vertical_align)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    return emit_view(resolved).text


# -- estimated box: moved the same way a glyph kind's lint box is ------------


@pytest.mark.parametrize("icon_position", ["left", "right", "top", "bottom"])
def test_estimated_box_left_top_puts_top_left_corner_on_anchor(write_design, bag, db, icon_position):
    resolved = _resolve_cs(write_design, bag, db, _cs_yaml("slot", icon_position, "left", "top"))
    placed = find(resolved, "slot")
    assert (placed.box.x, placed.box.y) == placed.anchor_point


@pytest.mark.parametrize("icon_position", ["left", "right", "top", "bottom"])
def test_estimated_box_right_bottom_puts_bottom_right_corner_on_anchor(write_design, bag, db, icon_position):
    resolved = _resolve_cs(write_design, bag, db, _cs_yaml("slot", icon_position, "right", "bottom"))
    placed = find(resolved, "slot")
    box = placed.box
    assert (box.x + box.width, box.y + box.height) == placed.anchor_point


# -- codegen: default unchanged (fast path included) --------------------------


def test_default_codegen_matches_no_keys_at_all(write_design, bag, db):
    with_keys = _view_cs(write_design, bag, db, "left", "center", "center")
    face = load(write_design(CS_BASE + """elements:
  - id: slot
    type: complication_slot
    slot: config.data.top
    at: {anchor: center}
    icon_size: 8%r
    color: palette.fg
"""), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    without_keys = emit_view(resolved).text
    assert with_keys == without_keys
    # confirms the fast path itself is still taken, not merely equal output.
    assert "var iconWidth = 0;" in with_keys
    assert "iconGlyphWidth" not in with_keys


@pytest.mark.parametrize("icon_position", ["right", "top", "bottom"])
def test_default_codegen_matches_no_keys_at_all_off_the_fast_path(write_design, bag, db, icon_position):
    """The general path (any position but 'left', here) is unaffected by
    plan 07 phase C when neither key is authored either."""
    with_keys = _view_cs(write_design, bag, db, icon_position, "center", "center")
    face = load(write_design(CS_BASE + f"""elements:
  - id: slot
    type: complication_slot
    slot: config.data.top
    at: {{anchor: center}}
    icon_size: 8%r
    icon_position: {icon_position}
    color: palette.fg
"""), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    without_keys = emit_view(resolved).text
    assert with_keys == without_keys


# -- codegen: the arithmetic for a non-default align/vertical_align ----------


def test_left_position_align_shifts_startX_and_stays_off_the_fast_path(write_design, bag, db):
    view = _view_cs(write_design, bag, db, "left", "left", "center")
    assert "var startX = Layout.SLOT_CX;" in view
    assert "rowY" not in view  # vertical_align: center -> CY used directly
    assert "dc.drawText(startX + iconGlyphWidth + gap, Layout.SLOT_CY, " in view


def test_left_position_align_right_shifts_startX_to_total(write_design, bag, db):
    view = _view_cs(write_design, bag, db, "left", "right", "center")
    assert "var startX = Layout.SLOT_CX - totalWidth;" in view


def test_left_position_vertical_align_shifts_the_row_axis(write_design, bag, db):
    view = _view_cs(write_design, bag, db, "left", "center", "bottom")
    assert "var startX = Layout.SLOT_CX - totalWidth / 2;" in view  # align: center unchanged
    assert "var rowHeight = dc.getFontHeight(" in view
    assert "var iconRowHeight = dc.getFontHeight(" in view
    assert "if (iconRowHeight > rowHeight)" in view
    assert "var rowY = Layout.SLOT_CY - rowHeight / 2;" in view
    assert "dc.drawText(startX, rowY, " in view
    assert "dc.drawText(startX + iconGlyphWidth + gap, rowY, " in view


def test_left_position_vertical_align_top_shifts_the_other_way(write_design, bag, db):
    view = _view_cs(write_design, bag, db, "left", "center", "top")
    assert "var rowY = Layout.SLOT_CY + rowHeight / 2;" in view


def test_right_position_align_shifts_startX_to_zero(write_design, bag, db):
    view = _view_cs(write_design, bag, db, "right", "left", "center")
    assert "var startX = Layout.SLOT_CX;" in view
    assert "dc.drawText(startX, Layout.SLOT_CY, " in view


def test_top_position_vertical_align_shifts_startY_to_zero(write_design, bag, db):
    view = _view_cs(write_design, bag, db, "top", "center", "top")
    assert "var startY = Layout.SLOT_CY;" in view


def test_bottom_position_vertical_align_shifts_startY_to_total(write_design, bag, db):
    view = _view_cs(write_design, bag, db, "bottom", "center", "bottom")
    assert "var startY = Layout.SLOT_CY - totalHeight;" in view


def test_top_position_align_left_shifts_the_pair_axis(write_design, bag, db):
    view = _view_cs(write_design, bag, db, "top", "left", "center")
    assert "var textWidth = dc.getTextWidthInPixels(text, " in view
    assert "var pairWidth = (iconGlyphWidth > textWidth) ? iconGlyphWidth : textWidth;" in view
    assert "var pairX = Layout.SLOT_CX + pairWidth / 2;" in view
    assert "dc.drawText(pairX, startY, " in view
    assert "dc.drawText(pairX, startY + iconHeight + gap, " in view


def test_bottom_position_align_right_shifts_the_pair_axis_the_other_way(write_design, bag, db):
    view = _view_cs(write_design, bag, db, "bottom", "right", "center")
    assert "var pairX = Layout.SLOT_CX - pairWidth / 2;" in view
    assert "dc.drawText(pairX, startY, " in view


# -- preview: pair origin moved -----------------------------------------------


def _cs_preview_design(icon_position: str, align: str, vertical_align: str) -> str:
    return CS_BASE + f"""
static:
  background:
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
elements:
  - id: slot
    type: complication_slot
    slot: config.data.top
    at: {{anchor: center}}
    icon_size: 10%r
    icon_position: {icon_position}
    color: palette.fg
    align: {align}
    vertical_align: {vertical_align}
"""


def _render_cs(write_design, bag, db, icon_position: str, align: str, vertical_align: str):
    face = load(write_design(_cs_preview_design(icon_position, align, vertical_align)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    return image, find(resolved, "slot")


def test_preview_pair_origin_moves_left(write_design, bag, db):
    image, placed = _render_cs(write_design, bag, db, "left", "left", "center")
    ax, ay = placed.anchor_point
    pts = _white_pixels(image, range(ax - 10, min(ax + 120, image.width)), range(ay - 30, ay + 30))
    assert pts, "no ink drawn at all"
    assert min(x for x, _ in pts) >= ax - 1


def test_preview_pair_origin_moves_up(write_design, bag, db):
    image, placed = _render_cs(write_design, bag, db, "top", "center", "bottom")
    ax, ay = placed.anchor_point
    pts = _white_pixels(image, range(ax - 60, ax + 60), range(ay - 60, ay + 10))
    assert pts, "no ink drawn at all"
    assert max(y for _, y in pts) <= ay + 1


# -- regression: no local is declared and never referenced again -------------
#
# Coordinator review found a real warning regression: the "declare only when
# read" logic above ignored the icon-less case (`icon_size:` set, but every
# choice maps `icon: none`, so `icon_present_guard` is `None` at codegen
# time) -- a width/height/gap read only inside `if (icon_present_guard)` was
# still declared unconditionally, and that whole block is never *emitted*
# when the slot can draw no icon at all, not merely skipped at runtime. This
# generates every combination -- both an icon-having and an icon-less slot,
# every `icon_position:`, every `align:` x `vertical_align:` -- and checks
# each `var <name> = ...;` the method declares is referenced again somewhere
# later in that same method (monkeyc's own "not used" check, approximated).


def _method_body(view: str, method_name: str) -> str:
    """The full text of one generated method, braces balanced -- robust to
    being the last method in the class (no trailing doc-comment to split on,
    unlike the `.split("\\n\\n    //!")[0]` shortcut other tests use)."""
    start = view.index(f"private function {method_name}")
    brace = view.index("{", start)
    depth = 0
    i = brace
    while True:
        if view[i] == "{":
            depth += 1
        elif view[i] == "}":
            depth -= 1
            if depth == 0:
                return view[start:i + 1]
        i += 1


def _unused_locals(body: str) -> list[str]:
    declared = re.findall(r"\bvar (\w+) = ", body)
    return [name for name in declared if len(re.findall(rf"\b{re.escape(name)}\b", body)) < 2]


def _cs_codegen_design(icon_position: str, align: str, vertical_align: str, has_icon: bool) -> str:
    choices = (
        "        - complication.steps\n        - complication.heart_rate\n"
        if has_icon else
        "        - { type: complication.steps, icon: none }\n"
        "        - { type: complication.calories, icon: none }\n"
    )
    return f"""
format: 1
face:
  id: 5a1e7c2b-9d4f-4e8a-b3c6-2f7d9e1a4b58
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
config:
  data:
    top:
      default: complication.steps
      choices:
{choices}elements:
  - id: slot
    type: complication_slot
    slot: config.data.top
    at: {{anchor: center}}
    font: FONT_XTINY
    icon_size: 8%r
    icon_position: {icon_position}
    color: palette.fg
    align: {align}
    vertical_align: {vertical_align}
    when_absent: hide
"""


@pytest.mark.parametrize("has_icon", [True, False], ids=["icon", "icon_less"])
@pytest.mark.parametrize("vertical_align", ["top", "center", "bottom"])
@pytest.mark.parametrize("align", ["left", "center", "right"])
@pytest.mark.parametrize("icon_position", ["left", "right", "top", "bottom"])
def test_no_declared_local_goes_unreferenced(
        write_design, bag, db, icon_position, align, vertical_align, has_icon):
    from wfb.ir import element_method_name

    face = load(write_design(_cs_codegen_design(icon_position, align, vertical_align, has_icon)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    view = emit_view(resolved).text
    body = _method_body(view, element_method_name("slot"))
    unused = _unused_locals(body)
    assert not unused, f"declared but never referenced again: {unused}\n{body}"
