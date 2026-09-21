"""Codegen for vector fonts and `curve:` (plan 11 slice 1, step 3).

`tests/test_vector_fonts.py` covers the IR (step 1), `tests/
test_vector_text_layout.py` covers per-device face resolution and lint
(step 2); this covers `wfb/emit/**`: `Graphics.getVectorFont` construction
(plain and guarded), the null check (gate 4, never omitted), the
`dc.drawAngledText`/`dc.drawRadialText` calls with the converted angle and
justification, direction constants, and the fact that a vector font
contributes no `<font>` resource or glyph set. `tests/
test_vector_text_golden.py` pins a full generated file for one design; this
asserts on the specific shapes plan 11 §3 promises, driven from small
designs built directly rather than a golden diff, the same
`tests/test_hands_codegen.py` precedent.

Real installed devices throughout: `fenix8solar47mm`/`fr955` have vector
fonts, `fenix6` does not (`tests/test_vector_text_layout.py`'s own module
docstring).
"""

from __future__ import annotations

import pytest

from tests.test_diagnostics import load
from wfb.availability import compute_guards
from wfb.emit.monkeyc import _mc_number, _mc_type, emit_layout, emit_view
from wfb.emit.resources import bake_fonts, glyph_set
from wfb.layout import resolve


def _design(fonts: str, elements: str, *, targets: str = "[fenix8solar47mm]") -> str:
    return f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: {targets}
palette: {{bg: "#000000", fg: "#FFFFFF"}}
fonts:
{fonts}
elements:
{elements}"""


_SINGLE_FONT = """\
  bezel:
    face: RobotoCondensedBold
    size: 6%r
"""

_HIDE_FONT = """\
  bezel:
    face: RobotoCondensedBold
    size: 6%r
    if_unavailable: hide
"""


def _background() -> str:
    return """\
  - id: background
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
"""


def _upright() -> str:
    return """\
  - id: brand
    type: text
    text: "GARMIN"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
"""


def _angled(vertical_align: str | None = None) -> str:
    extra = f"    vertical_align: {vertical_align}\n" if vertical_align else ""
    return f"""\
  - id: brand
    type: text
    text: "GARMIN"
    font: font.bezel
    color: palette.fg
    at: {{anchor: center}}
    curve: {{style: angled, angle: 45deg}}
{extra}"""


def _radial(direction: str = "clockwise", vertical_align: str = "center") -> str:
    return f"""\
  - id: brand
    type: text
    text: "GARMIN"
    font: font.bezel
    color: palette.fg
    at: {{anchor: center}}
    vertical_align: {vertical_align}
    curve: {{style: radial, angle: 90deg, radius: 40%r, direction: {direction}}}
"""


def _load(write_design, bag, design: str):
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    return face


# --------------------------------------------------------------------------
# _mc_type / _mc_number, extended for a String/Boolean constant


def test_mc_type_and_number_render_a_string_constant():
    assert _mc_type("RobotoCondensedBold") == "String"
    assert _mc_number("RobotoCondensedBold") == '"RobotoCondensedBold"'
    assert _mc_number("") == '""'


def test_mc_type_and_number_render_a_boolean_constant():
    assert _mc_type(True) == "Boolean"
    assert _mc_number(True) == "true"
    assert _mc_type(False) == "Boolean"
    assert _mc_number(False) == "false"


def test_mc_number_escapes_a_quote_in_a_string_constant():
    assert _mc_number('a"b') == '"a\\"b"'


def test_numeric_constants_are_unaffected():
    """The pre-existing Number/Float/McLiteral behaviour must not move."""
    assert _mc_type(3.5) == "Float"
    assert _mc_number(3.5) == "3.5f"
    assert _mc_type(3) == "Number"
    assert _mc_number(3) == "3"


# --------------------------------------------------------------------------
# Layout.mc constants


def test_layout_constants_name_the_font_by_name_not_element_id(write_design, bag, db):
    face = _load(write_design, bag, _design(_SINGLE_FONT, _background() + _upright()))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    layout = emit_layout(resolved).text
    assert "const FONT_BEZEL_FACE as String = \"RobotoCondensedBold\";" in layout
    assert "const FONT_BEZEL_SIZE as Number" in layout
    # No per-element font constant -- a font is named once, by its own name,
    # regardless of how many elements draw with it.
    assert "BRAND_FACE" not in layout


def test_no_available_constant_when_every_target_resolves(write_design, bag, db):
    face = _load(write_design, bag, _design(_SINGLE_FONT, _background() + _upright()))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    guards = compute_guards(face, [device])
    assert guards.vector_fonts == frozenset()
    layout = emit_layout(resolved, guards).text
    assert "FONT_BEZEL_AVAILABLE" not in layout


def test_available_constant_emitted_and_correct_per_device_when_some_target_fails(
    write_design, bag, db,
):
    _skip_unless(db, "fenix6")
    face = _load(
        write_design, bag,
        _design(_HIDE_FONT, _background() + _upright(), targets="[fenix8solar47mm, fenix6]"),
    )
    good, bad = db.get("fenix8solar47mm"), db.get("fenix6")
    guards = compute_guards(face, [good, bad])
    assert guards.vector_fonts == frozenset({"bezel"})

    good_layout = emit_layout(resolve(face, good, {}), guards).text
    bad_layout = emit_layout(resolve(face, bad, {}), guards).text
    assert "const FONT_BEZEL_AVAILABLE as Boolean = true;" in good_layout
    assert 'const FONT_BEZEL_FACE as String = "RobotoCondensedBold";' in good_layout
    assert "const FONT_BEZEL_AVAILABLE as Boolean = false;" in bad_layout
    assert 'const FONT_BEZEL_FACE as String = "";' in bad_layout


def test_angle_constant_carries_both_conventions_in_the_comment(write_design, bag, db):
    face = _load(write_design, bag, _design(_SINGLE_FONT, _background() + _angled()))
    device = db.get("fenix8solar47mm")
    layout = emit_layout(resolve(face, device, {})).text
    assert "const BRAND_ANGLE as Float = " in layout
    assert "45deg clockwise rotation from upright, in Garmin's convention" in layout


def test_radial_gets_a_radius_constant_angled_does_not(write_design, bag, db):
    device = db.get("fenix8solar47mm")
    angled_face = _load(write_design, bag, _design(_SINGLE_FONT, _background() + _angled()))
    angled_layout = emit_layout(resolve(angled_face, device, {})).text
    assert "BRAND_RADIUS" not in angled_layout

    radial_face = _load(write_design, bag, _design(_SINGLE_FONT, _background() + _radial()))
    radial_layout = emit_layout(resolve(radial_face, device, {})).text
    assert "const BRAND_RADIUS as Number" in radial_layout


# --------------------------------------------------------------------------
# onLayout construction: plain vs. guarded


def test_plain_construction_when_every_target_resolves(write_design, bag, db):
    face = _load(write_design, bag, _design(_SINGLE_FONT, _background() + _upright()))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    guards = compute_guards(face, [device])
    view = emit_view(resolved, guards).text
    assert (
        "_fontBezel = Graphics.getVectorFont({:face => Layout.FONT_BEZEL_FACE, "
        ":size => Layout.FONT_BEZEL_SIZE});"
    ) in view
    assert "FONT_BEZEL_AVAILABLE" not in view
    assert "private var _fontBezel as Graphics.VectorFont?;" in view


def test_guarded_construction_when_some_target_fails(write_design, bag, db):
    _skip_unless(db, "fenix6")
    face = _load(
        write_design, bag,
        _design(_HIDE_FONT, _background() + _upright(), targets="[fenix8solar47mm, fenix6]"),
    )
    good, bad = db.get("fenix8solar47mm"), db.get("fenix6")
    guards = compute_guards(face, [good, bad])
    resolved = resolve(face, good, {})
    view = emit_view(resolved, guards).text
    assert "if (Layout.FONT_BEZEL_AVAILABLE && (Graphics has :getVectorFont)) {" in view
    on_layout = view.split("function onLayout")[1].split("\n    }")[0]
    assert (
        "_fontBezel = Graphics.getVectorFont({:face => Layout.FONT_BEZEL_FACE, "
        ":size => Layout.FONT_BEZEL_SIZE});"
    ) in on_layout


def test_vector_font_is_not_in_the_loaded_bitmap_font_list(write_design, bag, db):
    """`_loaded_fonts`/`WatchUi.loadResource` is baked-font-only -- a vector
    font must never appear as something the view loads as a resource."""
    face = _load(write_design, bag, _design(_SINGLE_FONT, _background() + _upright()))
    device = db.get("fenix8solar47mm")
    view = emit_view(resolve(face, device, {})).text
    assert "WatchUi.loadResource(Rez.Fonts.FontBezel)" not in view
    assert "Rez.Fonts.FontBezel" not in view


# --------------------------------------------------------------------------
# the draw call: null check, argument order, angle, justification, direction


def test_gate_4_null_check_present_for_upright_vector_text(write_design, bag, db):
    face = _load(write_design, bag, _design(_SINGLE_FONT, _background() + _upright()))
    device = db.get("fenix8solar47mm")
    view = emit_view(resolve(face, device, {})).text
    method = view.split("private function drawBrand")[1]
    assert "var font = _fontBezel;" in method
    assert "if (font != null) {" in method
    assert "dc.drawText(Layout.BRAND_X," in method


def test_angled_draw_call_argument_order_and_angle(write_design, bag, db):
    face = _load(write_design, bag, _design(_SINGLE_FONT, _background() + _angled()))
    device = db.get("fenix8solar47mm")
    view = emit_view(resolve(face, device, {})).text
    method = view.split("private function drawBrand")[1]
    assert "if (font != null) {" in method
    assert (
        'dc.drawAngledText(Layout.BRAND_X, Layout.BRAND_Y, font, "GARMIN",'
    ) in method
    assert "Layout.BRAND_ANGLE);" in method
    # x, y, font, text, justification, angle -- in that order, on the two lines.
    call = method.split("dc.drawAngledText(")[1].split(";")[0]
    assert call.index("Layout.BRAND_X") < call.index("Layout.BRAND_Y") < call.index("font")
    assert call.index("font") < call.index('"GARMIN"') < call.index("TEXT_JUSTIFY")
    assert call.index("TEXT_JUSTIFY") < call.index("Layout.BRAND_ANGLE")


def test_radial_draw_call_argument_order_angle_radius_and_direction(write_design, bag, db):
    face = _load(
        write_design, bag,
        _design(_SINGLE_FONT, _background() + _radial("counter_clockwise")),
    )
    device = db.get("fenix8solar47mm")
    view = emit_view(resolve(face, device, {})).text
    method = view.split("private function drawBrand")[1]
    assert (
        'dc.drawRadialText(Layout.BRAND_X, Layout.BRAND_Y, font, "GARMIN",'
    ) in method
    call = method.split("dc.drawRadialText(")[1].split(";")[0]
    assert call.index("Layout.BRAND_X") < call.index("Layout.BRAND_Y") < call.index("font")
    assert call.index("font") < call.index('"GARMIN"') < call.index("TEXT_JUSTIFY")
    assert call.index("TEXT_JUSTIFY") < call.index("Layout.BRAND_ANGLE")
    assert call.index("Layout.BRAND_ANGLE") < call.index("Layout.BRAND_RADIUS")
    assert call.index("Layout.BRAND_RADIUS") < call.index("RADIAL_TEXT_DIRECTION")
    assert "Graphics.RADIAL_TEXT_DIRECTION_COUNTER_CLOCKWISE" in method


def test_radial_direction_defaults_to_clockwise_constant(write_design, bag, db):
    face = _load(write_design, bag, _design(_SINGLE_FONT, _background() + _radial("clockwise")))
    device = db.get("fenix8solar47mm")
    view = emit_view(resolve(face, device, {})).text
    method = view.split("private function drawBrand")[1]
    assert "Graphics.RADIAL_TEXT_DIRECTION_CLOCKWISE" in method
    assert "COUNTER_CLOCKWISE" not in method


@pytest.mark.parametrize("vertical_align,expect_vcenter", [("center", True), ("top", False)])
def test_justification_composes_vcenter_under_curve(
    write_design, bag, db, vertical_align, expect_vcenter,
):
    """§2.3's own finding: TEXT_JUSTIFY_VCENTER may be OR'd into the
    justification argument of both curved draw calls; 'top' omits it."""
    face = _load(write_design, bag, _design(_SINGLE_FONT, _background() + _angled(vertical_align)))
    device = db.get("fenix8solar47mm")
    view = emit_view(resolve(face, device, {})).text
    method = view.split("private function drawBrand")[1]
    call = method.split("dc.drawAngledText(")[1]
    assert ("TEXT_JUSTIFY_VCENTER" in call) is expect_vcenter
    assert "Graphics.TEXT_JUSTIFY_CENTER" in call


@pytest.mark.parametrize("vertical_align,direction,vcenter,radius", [
    ("center", "clockwise", True, "Layout.BRAND_RADIUS,"),
    ("bottom", "clockwise", False, "Layout.BRAND_RADIUS,"),
    ("bottom", "counter_clockwise", False, "Layout.BRAND_RADIUS,"),
    ("top", "clockwise", False, "Layout.BRAND_RADIUS - Graphics.getFontAscent(font),"),
    ("top", "counter_clockwise", False, "Layout.BRAND_RADIUS + Graphics.getFontAscent(font),"),
])
def test_radial_vertical_align_maps_to_justify_and_radius(
    write_design, bag, db, vertical_align, direction, vcenter, radius,
):
    """Without VCENTER the device puts the BASELINE on the circle (measured
    2026-09-21): that is `bottom` as-is, and `top` moves the baseline one
    ascent toward the glyphs' "down" -- inward when they face out
    (`clockwise`), outward when they face in. The bug this guards: `top`
    emitted the bare radius, so it drew exactly like `bottom`."""
    face = _load(write_design, bag, _design(
        _SINGLE_FONT, _background() + _radial(direction, vertical_align)))
    device = db.get("fenix8solar47mm")
    view = emit_view(resolve(face, device, {})).text
    call = view.split("private function drawBrand")[1].split("dc.drawRadialText(")[1].split(";")[0]
    assert ("TEXT_JUSTIFY_VCENTER" in call) is vcenter
    assert f"Layout.BRAND_ANGLE, {radius}" in call


# --------------------------------------------------------------------------
# no <font> resource, no glyph set


def test_bake_fonts_skips_a_vector_font(write_design, bag, db):
    face = _load(write_design, bag, _design(_SINGLE_FONT, _background() + _upright()))
    device = db.get("fenix8solar47mm")
    baked = bake_fonts(face, device)
    assert "bezel" not in baked


def test_glyph_set_excludes_a_vector_font(write_design, bag, db):
    face = _load(write_design, bag, _design(_SINGLE_FONT, _background() + _upright()))
    sets = glyph_set(face)
    assert "bezel" not in sets


def _skip_unless(db, *device_ids: str) -> None:
    for device_id in device_ids:
        if device_id not in db.ids():
            pytest.skip(f"{device_id} not installed")
