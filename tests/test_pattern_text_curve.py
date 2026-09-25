"""`curve:` on a pattern's own `shape: text` part (plan 11 slice 2):
`docs/limitations.md`'s "a bitmap font cannot turn, so only the anchor
turns" finally gets its answer -- rotated hour numerals around a dial, each
tangent to its own radius, through a device-resident `face:` font.

Slice 1 (`tests/test_vector_fonts.py`, `tests/test_vector_text_*.py`)
covers a standalone `text` element's own `curve:`; this file covers what is
*different* about a pattern's own text part: the authored angle is in the
template's own local (copy-0) frame, and a radial pattern composes it with
each copy's own rotation at codegen/preview time (`wfb.kinds.
pattern._emit_pattern_text_angle_expr`, `wfb.kinds.pattern._pattern_part_ink`,
`wfb.kinds.pattern._pattern_text`) -- never in `wfb.layout.Resolver.
_resolve_hand_part`, which stores the part's own *local* angle only (see
its own docstring). Every check here was driven red first (`tests/
CLAUDE.md`): run against a design that should fail with the corresponding
`wfb/ir/`/`wfb/lint.py` check reverted, it either raised a different, wrong
error or built clean before the real check landed.

Real installed devices throughout: `fenix8solar47mm`/`fr955` have vector
fonts, `fenix6` does not (`tests/test_vector_text_layout.py`'s own module
docstring).
"""

from __future__ import annotations

import math

import pytest

from wfb.build import load
from wfb import build, lint
from wfb.diagnostics import Bag
from wfb.emit.monkeyc import emit_layout, emit_view
from wfb.emit.resources import bake_fonts
from wfb.kinds.pattern import _emit_pattern_text_angle_expr, _pattern_part_ink
from wfb.layout import PlacedPattern, inside_screen, resolve
from wfb.preview import PreviewOptions, render
from tests.helpers import fonts_design as _design


_VECTOR_FONT = """\
  bezel:
    face: RobotoCondensedBold
    size: 8%r
"""

_HIDE_FONT = """\
  bezel:
    face: RobotoCondensedBold
    size: 8%r
    if_unavailable: hide
"""

#: `line_height` 36px on `fenix8solar51mm` (minor radius 140) -- the same
#: showcase-motivated case `tests/test_vector_text_layout.py`'s own
#: `_TALL_FONT` uses: `size: 26%r` -> `round(0.26 * 140) == 36`.
_TALL_FONT = """\
  bezel:
    face: RobotoCondensedBold
    size: 26%r
"""


def _radial_badge(vertical_align: str = "center", direction: str = "clockwise") -> str:
    """A single-copy (`count: 1`, so `copy_angle_degrees == 0.0` and the
    part's own local curve angle is never composed with anything) radial
    pattern whose one `shape: text` part is otherwise exactly the
    standalone-element case `tests/test_vector_text_layout.py`'s own
    radial-band tests use -- `radius: 75%r` = 105px on `fenix8solar51mm`
    -- so the two files' worth of tests below can reuse the same
    reasoning and expected numbers.
    """
    return f"""\
  - id: badge
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1
    color: palette.fg
    parts:
      - shape: text
        text: "GARMIN"
        font: font.bezel
        vertical_align: {vertical_align}
        curve: {{style: radial, angle: 0deg, radius: 75%r, direction: {direction}}}"""


def _radial_hours(curve: str = "curve: {style: angled, angle: 0deg}\n        ",
                  font: str = "font.bezel", count: int = 12) -> str:
    return f"""\
  - id: hours
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: {count}
    color: palette.fg
    parts:
      - shape: text
        value: "(copy + 11) % 12 + 1"
        font: {font}
        at: {{dy: -74%r}}
        {curve}"""


def _linear_row(curve: str = "curve: {style: angled, angle: 20deg}\n        ") -> str:
    return f"""\
  - id: row
    type: pattern
    pattern: linear
    at: {{anchor: center}}
    count: 3
    step: {{dx: 14%r}}
    color: palette.fg
    parts:
      - shape: text
        text: "V"
        font: font.bezel
        {curve}"""


def _load(write_design, bag, design: str):
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    return face


def _placed_pattern(resolved, element_id: str) -> PlacedPattern:
    for p in resolved.items:
        if p.id == element_id:
            assert isinstance(p, PlacedPattern)
            return p
    raise AssertionError(f"{element_id!r} was not placed")


def _stub_baking(monkeypatch) -> None:
    monkeypatch.setattr("wfb.emit.resources.bake_fonts", lambda face, device: {})


# --------------------------------------------------------------------------
# IR: curve/if_unavailable accepted only with a face: font


def test_curve_on_a_pattern_text_part_is_accepted_with_a_vector_font(write_design, bag):
    face = _load(write_design, bag, _design(_VECTOR_FONT, _radial_hours()))
    part = face.elements[0].parts[0]
    assert part.curve is not None
    assert part.curve.style == "angled"
    assert part.curve.angle.degrees == 0.0


def test_curve_is_rejected_without_a_face_font(write_design, bag, repo_root):
    source = repo_root / "tests" / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"
    baked = f"  bezel:\n    source: {source}\n    size: 20px\n"
    face = load(write_design(_design(baked, _radial_hours())), bag)
    assert face is None
    errors = [d for d in bag.errors if d.code == "text-curve"]
    assert errors, bag.render()
    assert "needs a 'face:' (vector) font" in errors[0].message
    assert "hours.parts[0]" in errors[0].message


def test_vertical_align_bottom_rejected_under_curve(write_design, bag):
    elements = _radial_hours().rstrip("\n") + "\n        vertical_align: bottom\n"
    face = load(write_design(_design(_VECTOR_FONT, elements)), bag)
    assert face is None
    errors = [d for d in bag.errors if d.code == "text-curve"]
    assert any("vertical_align: bottom" in e.message for e in errors), bag.render()


def test_vertical_align_bottom_accepted_under_radial_curve(write_design, bag):
    """`radial`'s native no-`VCENTER` mode is baseline-on-the-circle, so
    `bottom` is legal there; only `angled` still rejects it."""
    elements = _radial_hours(
        curve="curve: {style: radial, angle: 0deg, radius: 10%r}\n        ",
    ).rstrip("\n") + "\n        vertical_align: bottom\n"
    face = load(write_design(_design(_VECTOR_FONT, elements)), bag)
    assert face is not None, bag.render()


def test_radius_and_direction_rejected_under_angled(write_design, bag):
    elements = _radial_hours(
        curve="curve: {style: angled, angle: 0deg, radius: 10%r}\n        ",
    )
    face = load(write_design(_design(_VECTOR_FONT, elements)), bag)
    assert face is None
    assert any("radius" in d.message for d in bag.errors), bag.render()


def test_if_unavailable_requires_a_face_font_on_a_pattern_part(write_design, bag, repo_root):
    source = repo_root / "tests" / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"
    baked = f"  bezel:\n    source: {source}\n    size: 20px\n"
    elements = _radial_hours(curve="").rstrip("\n") + "\n        if_unavailable: hide\n"
    face = load(write_design(_design(baked, elements)), bag)
    assert face is None
    errors = [d for d in bag.errors if d.code == "text-curve"]
    assert any("'if_unavailable:' is not accepted" in e.message for e in errors), bag.render()


def test_if_unavailable_is_accepted_on_a_pattern_part_with_a_face_font(write_design, bag):
    elements = _radial_hours(curve="").rstrip("\n") + "\n        if_unavailable: hide\n"
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    part = face.elements[0].parts[0]
    assert part.if_unavailable == "hide"


# --------------------------------------------------------------------------
# layout: the part's own curve angle is LOCAL, not composed with the copy


def test_curve_angle_garmin_on_the_resolved_part_is_the_local_angle_only(write_design, bag, db):
    """`ResolvedTextPart.curve.angle_garmin` must be `wfb.layout.
    garmin_curve_angle` of the *authored* angle alone -- composition with a
    radial pattern's own `start`/`step` happens downstream (codegen,
    preview, the lint ink box), never here. Proven by giving the pattern a
    non-zero `start:`/`step:` and checking the resolved part is
    unaffected."""
    elements = _radial_hours(count=4).rstrip("\n")
    # non-default start/step: if composition leaked into layout, this would
    # change `curve.angle_garmin` away from `garmin_curve_angle("angled",
    # 0deg) == 0.0` (a rotation, not a position: `0deg` is unrotated, so it
    # converts to Garmin `0.0` with no offset, unlike `radial`'s `to_garmin`).
    elements = elements.replace("pattern: radial\n", "pattern: radial\n    start: 45deg\n"
                                "    step: 90deg\n")
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    placed = _placed_pattern(resolved, "hours")
    part = placed.parts[0]
    assert part.curve.style == "angled"
    assert part.curve.angle_garmin == pytest.approx(0.0)  # garmin_curve_angle("angled", 0deg)
    assert part.curve.angle_degrees == 0.0


def test_font_face_and_availability_resolve_per_device_for_a_pattern_part(write_design, bag, db):
    face = _load(write_design, bag, _design(_VECTOR_FONT, _radial_hours()))
    good = db.get("fenix8solar47mm")
    bad = db.get("fenix6")
    good_part = _placed_pattern(resolve(face, good, {}), "hours").parts[0]
    bad_part = _placed_pattern(resolve(face, bad, {}), "hours").parts[0]
    assert good_part.font.is_vector is True
    assert good_part.font.available is True
    assert good_part.font.face == "RobotoCondensedBold"
    assert bad_part.font.available is False
    assert bad_part.font.face == ""


def test_radial_style_curve_gets_a_radius_on_the_resolved_part(write_design, bag, db):
    elements = _radial_hours(
        curve="curve: {style: radial, angle: 90deg, radius: 20%r}\n        ",
    )
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    placed = _placed_pattern(resolve(face, device, {}), "hours")
    part = placed.parts[0]
    assert part.curve.style == "radial"
    assert part.curve.radius_px > 0


def test_pattern_radial_band_is_line_height_over_two_not_line_height(write_design, bag, db):
    """The same 2026-09-21 radial-band tightening as a standalone `text`
    element's own lint box (`tests/test_vector_text_layout.py::test_
    radial_band_is_line_height_over_two_not_line_height`), for a
    pattern's `shape: text` part instead: `_pattern_part_ink`'s radial
    branch shares `wfb.layout.radial_text_band` with `Resolver._resolve_
    text`, so the two can never drift into two different bands. Same
    showcase-motivated geometry -- a 280px round device
    (`fenix8solar51mm`), `radius: 75%r` = 105px, `line_height` 36px --
    reused here with `count: 1` (a single, unrotated copy) so the
    pattern's own ink box is exactly the annulus sector the standalone
    test already proved fits, not something the extra rotation/copy
    machinery could accidentally get right for a different reason."""
    face = _load(
        write_design, bag, _design(_TALL_FONT, _radial_badge(), targets="[fenix8solar51mm]"))
    device = db.get("fenix8solar51mm")
    resolved = resolve(face, device, {})
    placed = _placed_pattern(resolved, "badge")
    part = placed.parts[0]
    assert part.font.px == 36  # pins "line_height 36" from the standalone case
    assert part.curve.radius_px == 105  # pins "radius 75%r == 105px"

    fresh = Bag()
    lint.check_geometry(resolved, fresh)
    assert not any(d.code == "off-screen" for d in fresh.items), (
        "the tightened +/-line_height/2 band must fit on this device, "
        "just like the standalone element's own box"
    )


def test_pattern_radial_band_flips_inward_outward_with_facing(write_design, bag, db):
    """`vertical_align: top`'s band flips with `direction:` for a pattern
    text part exactly the way it does for a standalone element
    (`tests/test_vector_text_layout.py::test_radial_band_flips_inward_
    outward_with_facing`), reusing the same showcase-motivated geometry:
    `clockwise` (outward-facing) keeps the inward band, which still fits;
    `counter_clockwise` (inward-facing) keeps the outward band, which
    still reaches the same edge the direction-blind old band did --
    proving `_pattern_part_ink` reads `part.curve.direction`, not just
    `part.vertical_align` alone (CLAUDE.md §7)."""
    def _resolved(direction: str):
        face = _load(write_design, bag, _design(
            _TALL_FONT, _radial_badge(vertical_align="top", direction=direction),
            targets="[fenix8solar51mm]"))
        device = db.get("fenix8solar51mm")
        return resolve(face, device, {}), device

    inward_resolved, device = _resolved("clockwise")
    outward_resolved, _ = _resolved("counter_clockwise")
    inward_box = _placed_pattern(inward_resolved, "badge").box
    outward_box = _placed_pattern(outward_resolved, "badge").box
    assert inside_screen(inward_box, device), (
        "clockwise (outward-facing) 'top' is the inward band and must fit"
    )
    assert not inside_screen(outward_box, device), (
        "counter_clockwise (inward-facing) 'top' is the outward band, "
        "reaching the same edge the direction-blind old band did"
    )


def test_linear_pattern_curve_has_no_copy_angle_to_compose_with(write_design, bag, db):
    """`element.start_angle`/`.step_angle` are always `0.0` on a linear
    pattern (`wfb.kinds.pattern.PatternKind.resolve`), so the composition
    formula reduces to the part's own local angle unchanged -- checked at
    the `PatternElement` level, since that is what codegen/preview actually
    read for the per-copy composition."""
    face = _load(write_design, bag, _design(_VECTOR_FONT, _linear_row()))
    element = face.elements[0]
    assert element.pattern == "linear"
    assert element.start_angle == 0.0
    assert element.step_angle == 0.0


# --------------------------------------------------------------------------
# codegen: the composed angle expression


def test_angle_expr_composes_local_angle_with_element_start_for_radial(write_design, bag, db):
    """`g0 = part.curve.angle_garmin - element.start_angle`, then `- i *
    step` per copy -- the exact arithmetic `_emit_pattern_text_angle_expr`
    performs, checked against hand-derived numbers rather than a substring
    of generated code, so a sign error cannot hide behind a passing
    'contains "i *"' assertion."""
    elements = _radial_hours(count=4).rstrip("\n")
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    placed = _placed_pattern(resolve(face, device, {}), "hours")
    part = placed.parts[0]
    element = face.elements[0]
    assert element.start_angle == 0.0
    assert element.step_angle == pytest.approx(90.0)  # 360 / 4
    expr = _emit_pattern_text_angle_expr(element, part)
    # g0 = garmin_curve_angle("angled", 0deg) - 0.0 = 0.0; step = 90.0
    assert expr == "0.0 - i * 90.0"


def test_angle_expr_folds_element_start_angle_into_g0(write_design, bag, db):
    elements = _radial_hours(count=4).rstrip("\n").replace(
        "pattern: radial\n", "pattern: radial\n    start: 10deg\n")
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    placed = _placed_pattern(resolve(face, device, {}), "hours")
    part = placed.parts[0]
    element = face.elements[0]
    expr = _emit_pattern_text_angle_expr(element, part)
    # g0 = 0.0 (garmin_curve_angle("angled", 0deg)) - 10.0 (element.start_angle) = -10.0
    assert expr == "-10.0 - i * 90.0"


def test_angle_expr_has_no_per_copy_term_for_a_linear_pattern(write_design, bag, db):
    face = _load(write_design, bag, _design(_VECTOR_FONT, _linear_row()))
    device = db.get("fenix8solar47mm")
    placed = _placed_pattern(resolve(face, device, {}), "row")
    part = placed.parts[0]
    element = face.elements[0]
    expr = _emit_pattern_text_angle_expr(element, part)
    assert "i *" not in expr
    # garmin_curve_angle("angled", 20deg) = (-20) % 360 = 340.0
    assert expr == "340.0"


# --------------------------------------------------------------------------
# codegen: the actual draw call and gate 4


def test_angled_pattern_part_emits_draw_angled_text(write_design, bag, db):
    elements = _radial_hours(count=4).rstrip("\n")
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    view = emit_view(resolve(face, device, {})).text
    method = view.split("private function drawHours")[1]
    loop_body = method.split("for (var i")[1]
    assert "dc.drawAngledText(" in loop_body
    assert "dc.drawText(" not in loop_body  # never the plain, uncurved call
    call = loop_body.split("dc.drawAngledText(")[1].split(";")[0]
    # x, y (rotated anchor), font, text, justification, angle -- in order.
    assert call.index("WfbGeom.rotatedX") < call.index("WfbGeom.rotatedY") < call.index("font0")
    assert call.index("font0") < call.index("TEXT_JUSTIFY")
    assert call.index("TEXT_JUSTIFY") < call.index("0.0 - i * 90.0")


def test_radial_style_pattern_part_emits_draw_radial_text_and_radius_constant(
    write_design, bag, db,
):
    elements = _radial_hours(
        curve="curve: {style: radial, angle: 90deg, radius: 20%r}\n        ",
    )
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    layout = emit_layout(resolved).text
    view = emit_view(resolved).text
    assert "const HOURS_0_RADIUS as Number" in layout
    method = view.split("private function drawHours")[1]
    assert "dc.drawRadialText(" in method
    assert "Layout.HOURS_0_RADIUS" in method
    assert "Graphics.RADIAL_TEXT_DIRECTION_CLOCKWISE" in method


def test_vector_font_local_is_never_early_return_guarded_in_a_pattern(write_design, bag, db):
    """The critical difference from a baked custom font (plan 11 slice 2's
    own design note): an early `return;` before the loop would cancel
    every OTHER part of this same pattern too, so a vector font's local is
    loaded once but the null check happens per copy, wrapping only its own
    draw call."""
    elements = _radial_hours().rstrip("\n")
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    view = emit_view(resolve(face, device, {})).text
    method = view.split("private function drawHours")[1]
    assert "var font0 = _fontBezel;" in method
    assert "if (font0 == null)" not in method
    assert "return;  // the font resource failed to load" not in method
    assert "if (font0 != null) {" in method


def test_upright_vector_font_pattern_part_is_also_null_guarded(write_design, bag, db):
    """Gate 4 applies even with no `curve:` at all -- an upright `face:`
    font pattern part must be guarded exactly the same way a curved one
    is, not treated like a baked resource."""
    elements = _radial_hours(curve="").rstrip("\n")
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    view = emit_view(resolve(face, device, {})).text
    method = view.split("private function drawHours")[1]
    assert "if (font0 != null) {" in method
    assert "dc.drawText(" in method


def test_baked_font_pattern_part_keeps_the_early_return_guard(write_design, bag, db, repo_root):
    """Contrast: an ordinary baked custom font on a pattern text part must
    keep the pre-existing early-return behaviour, unaffected by this
    slice."""
    source = repo_root / "tests" / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"
    baked = f"  small:\n    source: {source}\n    size: 20px\n"
    elements = _radial_hours(curve="", font="font.small").rstrip("\n")
    face = _load(write_design, bag, _design(baked, elements))
    device = db.get("fenix8solar47mm")
    resolved_fonts = bake_fonts(face, device)
    view = emit_view(resolve(face, device, resolved_fonts)).text
    method = view.split("private function drawHours")[1]
    assert "if (font0 == null)" in method
    assert "return;  // the font resource failed to load" in method


# --------------------------------------------------------------------------
# lint: font-unavailable on a pattern part


def test_font_unavailable_error_on_a_pattern_part(write_design, bag, db, monkeypatch):
    elements = _radial_hours()
    face = _load(
        write_design, bag,
        _design(_VECTOR_FONT, elements, targets="[fenix8solar47mm, fenix6]"),
    )
    devices = build.select_devices(face, db, bag)
    _stub_baking(monkeypatch)
    build.resolve_all(face, devices, bag)
    assert not bag.ok()
    errors = [d for d in bag.errors if d.code == "font-unavailable"]
    assert errors, bag.render()
    assert "hours.parts[0]" in errors[0].message
    assert "fenix6" in errors[0].message


def test_font_unavailable_hide_on_a_pattern_part_does_not_fail_the_build(
    write_design, bag, db, monkeypatch,
):
    elements = _radial_hours(curve="").rstrip("\n") + "\n        if_unavailable: hide\n"
    face = _load(
        write_design, bag,
        _design(_VECTOR_FONT, elements, targets="[fenix8solar47mm, fenix6]"),
    )
    devices = build.select_devices(face, db, bag)
    _stub_baking(monkeypatch)
    build.resolve_all(face, devices, bag)
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.code == "font-unavailable"]
    assert warnings, bag.render()
    assert "hours.parts[0]" in warnings[0].message


# --------------------------------------------------------------------------
# preview: renders without crashing, ink rotates with position


def _render(write_design, db, bag, elements: str, *, target: str = "fenix8solar47mm"):
    design = _design(_VECTOR_FONT, elements, targets=f"[{target}]")
    path = write_design(design)
    face = build.load(path, bag)
    assert face is not None, bag.render()
    device = db.get(target)
    resolved = resolve(face, device, bake_fonts(face, device))
    return render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))


def test_preview_renders_a_curved_pattern_without_crashing(write_design, db, bag):
    background = (
        "  - id: background\n    type: shape\n    shape: rectangle\n"
        "    at: {anchor: center}\n    size: {width: 100%, height: 100%}\n"
        "    color: palette.bg\n"
    )
    image = _render(write_design, db, bag, background + _radial_hours(count=4))
    assert image.size[0] > 0 and image.size[1] > 0


def test_preview_draws_nothing_for_a_hidden_unavailable_pattern_part(write_design, db, bag):
    """`if_unavailable: hide` on fenix6 (no vector fonts at all): the
    honest preview is nothing drawn for that part, not a crash and not a
    fallback glyph."""
    background = (
        "  - id: background\n    type: shape\n    shape: rectangle\n"
        "    at: {anchor: center}\n    size: {width: 100%, height: 100%}\n"
        "    color: palette.bg\n"
    )
    elements = _radial_hours(curve="").rstrip("\n") + "\n        if_unavailable: hide\n"
    image = _render(write_design, db, bag, background + elements, target="fenix6")
    # Solid background everywhere -- nothing else this design draws.
    w, h = image.size
    for x in (0, w // 2, w - 1):
        for y in (0, h // 2, h - 1):
            assert image.getpixel((x, y)) in ((0, 0, 0),)


# --------------------------------------------------------------------------
# safe-area: a full radial ring's exact reach, not the union AABB's corners
# (fix B: `docs/lore/platform-constraints.md` §4 "safe-area is shape-aware").


def _radial_ring_text(curve: str, count: int = 12, font: str = "font.bezel") -> str:
    """A 12-numeral radial ring with no `at:` override on the part -- the
    exact shape `examples/showcase`'s own `numerals` element uses: the
    curve circle's own centre (for `radial`) or the text anchor (for
    `angled`) coincides with the pattern's own rotation axis, so every
    copy's ink sits at the same reach from that axis and only its angle
    changes -- the case the old, AABB-corner-based `text_reach` most
    badly overreported (`annulus_sector_reach`'s own docstring: even
    centred exactly on the reference point, an annulus sector's AABB
    corners sit past `r_outer`)."""
    return f"""\
  - id: hours
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: {count}
    color: palette.fg
    parts:
      - shape: text
        value: "(copy + 11) % 12 + 1"
        font: {font}
        {curve}"""


def _old_style_pattern_reach(placed: PlacedPattern) -> float:
    """Reconstructs the AABB-corner-based `text_reach` `Resolver.
    _resolve_pattern` used before this fix -- the max distance from the
    pattern's own axis to any DRAWN COPY's own `_pattern_part_ink` corners,
    rather than the exact geometry `annulus_sector_reach`/
    `rotated_rect_corners` now derive. `_pattern_part_ink` itself is
    unchanged by the fix (still the right AABB for `off-screen`), so this
    is a faithful reconstruction of the old numbers, not a guess -- the
    same "rebuild the old box by hand since the code that made it no
    longer exists to call" precedent `tests/test_vector_text_layout.py::
    test_radial_band_is_line_height_over_two_not_line_height` sets."""
    cx_f, cy_f = float(placed.center[0]), float(placed.center[1])
    old_reach = 0.0
    for index in placed.copies:
        ox, oy, sin_t, cos_t = placed.transform(index)
        for part in placed.parts:
            lo_x, lo_y, hi_x, hi_y = _pattern_part_ink(
                part, ox, oy, sin_t, cos_t, index, placed.start, placed.step)
            for corner_x, corner_y in ((lo_x, lo_y), (lo_x, hi_y), (hi_x, lo_y), (hi_x, hi_y)):
                old_reach = max(old_reach, math.hypot(corner_x - cx_f, corner_y - cy_f))
    return old_reach


def test_radial_curve_ring_inside_the_disc_does_not_warn_safe_area(write_design, bag, db):
    """A full 12-copy ring of `curve: {style: radial}` numerals,
    `radius: 92%r`: comfortably inside the visible disc by the real
    (exact) reach every glyph's ink actually occupies. The old,
    AABB-corner-based `text_reach` this replaces would have failed this
    exact case (reconstructed below, CLAUDE.md §7's "must be able to fail
    against a knowingly broken implementation") -- the false positive the
    user was papering over with `lint: {allow: [safe-area]}` on
    `examples/showcase`'s own `numerals` element."""
    elements = _radial_ring_text("curve: {style: radial, angle: 0deg, radius: 92%r}")
    face = load(write_design(_design(_VECTOR_FONT, elements)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    placed = next(p for p in resolved.items if p.id == "hours")
    assert isinstance(placed, PlacedPattern)

    limit = device.minor_radius * (1.0 - 0.02)
    assert placed.reach <= limit + 0.5, "the exact reach must fit"
    assert _old_style_pattern_reach(placed) > limit + 0.5, (
        "the old AABB-corner reconstruction must still overreport this "
        "exact ring -- the contrast this fix exists to correct"
    )

    lint.check_geometry(resolved, bag)
    assert not any(d.code == "safe-area" for d in bag.items), bag.render()


def test_radial_curve_ring_pushed_out_still_warns_safe_area(write_design, bag, db):
    """The non-regression half: pushed out far enough (`radius: 95%r`) the
    ring's real ink genuinely crosses the bezel margin too, so the fix
    must still catch it -- not silently disable `safe-area` for every
    radial-text ring."""
    elements = _radial_ring_text("curve: {style: radial, angle: 0deg, radius: 95%r}")
    face = load(write_design(_design(_VECTOR_FONT, elements)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    placed = next(p for p in resolved.items if p.id == "hours")

    lint.check_geometry(resolved, bag)
    warnings = [d for d in bag.items if d.code == "safe-area"]
    assert warnings, bag.render()
    assert any("reaches" in n and "limit" in n for n in warnings[0].notes), warnings[0].notes


def test_angled_curve_ring_inside_the_disc_does_not_warn_safe_area(write_design, bag, db):
    """The same ring, `curve: {style: angled}` instead of `radial`
    (`at: {dy: -92%r}` supplies the ring radius this style has no
    `curve.radius` of its own for): each copy's own rotated-rectangle box
    has AABB corners that are not points on the rectangle once turned away
    from a multiple of 90 degrees, the same trap `rotated_rect_corners`
    exists to avoid -- 12 copies around a full turn guarantee some of them
    land at exactly such an angle."""
    elements = _radial_ring_text(
        "at: {dy: -92%r}\n        curve: {style: angled, angle: 0deg}")
    face = load(write_design(_design(_VECTOR_FONT, elements)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    placed = next(p for p in resolved.items if p.id == "hours")
    assert isinstance(placed, PlacedPattern)

    limit = device.minor_radius * (1.0 - 0.02)
    assert placed.reach <= limit + 0.5
    assert _old_style_pattern_reach(placed) > limit + 0.5, (
        "the old AABB-corner reconstruction must still overreport this ring"
    )

    lint.check_geometry(resolved, bag)
    assert not any(d.code == "safe-area" for d in bag.items), bag.render()


def test_angled_curve_ring_pushed_out_still_warns_safe_area(write_design, bag, db):
    elements = _radial_ring_text(
        "at: {dy: -95%r}\n        curve: {style: angled, angle: 0deg}")
    face = load(write_design(_design(_VECTOR_FONT, elements)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})

    lint.check_geometry(resolved, bag)
    assert any(d.code == "safe-area" for d in bag.items), bag.render()


def test_off_screen_pattern_still_uses_the_aabb_not_the_exact_reach(write_design, bag, db):
    """`off-screen` (the rectangular *framebuffer* test) must stay on
    `placed.box`'s own AABB regardless of this fix -- only the round-disc
    `safe-area` check became shape-aware. A ring radius far past the
    framebuffer itself is cropped no matter how tightly its real ink is
    measured, and acknowledging `off-screen` must still silence the
    (otherwise redundant) `safe-area` warning underneath it, the same
    suppression `wfb.lint.check_geometry`'s own docstring already
    documents for any other kind."""
    elements = _radial_ring_text("curve: {style: radial, angle: 0deg, radius: 400%r}")
    face = load(write_design(_design(_VECTOR_FONT, elements)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})

    lint.check_geometry(resolved, bag)
    assert any(d.code == "off-screen" for d in bag.items), bag.render()
    assert not any(d.code == "safe-area" for d in bag.items), bag.render()
