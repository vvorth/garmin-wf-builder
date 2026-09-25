"""Vector fonts and `curve:` (plan 11 slice 1) -- the device layer
(`Device.scalable_faces`, gate 1's symbol constants), the IR
(`FontSpec.is_vector`/`is_baked`, `Curve`, `Text.curve`/`if_unavailable`),
and every builder diagnostic plan 11 §2 asks for.  Layout, lint, codegen and
preview are later slices (plan 11 §5; deleted once built, `docs/CLAUDE.md` --
`git show e744913:docs/plans/11-vector-text.md`) and are not exercised here.
"""

import pytest

from wfb.build import load

# -- Device.scalable_faces / gate 1 symbols -----------------------------------


def test_scalable_faces_on_devices_that_have_them(db):
    """`fenix8solar47mm` and `fr955` both publish a Latin scalable catalogue,
    `RobotoCondensedBold` included -- the one face 41 of 44 devices share
    (docs/research/12-vector-fonts.md §3.3)."""
    for device_id in ("fenix8solar47mm", "fr955"):
        if device_id not in db.ids():
            pytest.skip(f"{device_id} not installed")
        device = db.get(device_id)
        faces = device.scalable_faces
        assert "RobotoCondensedBold" in faces
        assert len(faces) == len(set(faces)), "must be de-duplicated"


def test_scalable_faces_is_stable_and_ordered(db):
    """Two reads agree, and the result is a tuple -- resolving `face: [A, B]`
    to "the first one this device actually publishes" needs a fixed order."""
    if "fenix8solar47mm" not in db.ids():
        pytest.skip("fenix8solar47mm not installed")
    device = db.get("fenix8solar47mm")
    assert isinstance(device.scalable_faces, tuple)
    assert device.scalable_faces == device.scalable_faces


def test_scalable_faces_empty_on_devices_that_lack_them(db):
    """`fenix6`/`fr245` predate scalable fonts entirely -- an ordinary,
    expected empty result, not a degraded one."""
    for device_id in ("fenix6", "fr245"):
        if device_id not in db.ids():
            pytest.skip(f"{device_id} not installed")
        assert db.get(device_id).scalable_faces == ()


def test_gate_1_symbols_move_together_on_devices_that_have_them(db):
    for device_id in ("fenix8solar47mm", "fr955"):
        if device_id not in db.ids():
            pytest.skip(f"{device_id} not installed")
        device = db.get(device_id)
        assert device.has_symbol(device.VECTOR_FONT_SYMBOL) is True
        assert device.has_symbol(device.DRAW_ANGLED_TEXT_SYMBOL) is True
        assert device.has_symbol(device.DRAW_RADIAL_TEXT_SYMBOL) is True


def test_gate_1_symbols_are_absent_on_devices_that_lack_vector_fonts(db):
    for device_id in ("fenix6", "fr245"):
        if device_id not in db.ids():
            pytest.skip(f"{device_id} not installed")
        device = db.get(device_id)
        assert device.has_symbol(device.VECTOR_FONT_SYMBOL) is False
        assert device.has_symbol(device.DRAW_ANGLED_TEXT_SYMBOL) is False
        assert device.has_symbol(device.DRAW_RADIAL_TEXT_SYMBOL) is False


# -- design templates ----------------------------------------------------------

_BAKED_SOURCE = "tests/fixtures/slice/assets/OpenSans-Regular.ttf"


def _design(fonts: str | None, elements: str, *, repo_root) -> str:
    """A minimal face with an author-supplied `fonts:` block (omitted
    entirely when `fonts` is `None` -- an empty `fonts:` value would fail
    the schema's own `type: object`, so "no custom fonts at all" has to
    mean "no key", the same shape `tests/test_semantics.py`'s own
    `_font_design` follows for a single font) and `elements:` block -- the
    baked font's `source:` is rewritten to an absolute path against
    `repo_root`, since `Builder._build_baked_font` resolves it against the
    design file's own directory (a tmp dir here), not the repo.
    """
    fonts_block = f"fonts:\n{fonts}\n" if fonts else ""
    text = f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: [fenix8solar47mm]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
{fonts_block}elements:
{elements}
"""
    return text.replace(_BAKED_SOURCE, f"{repo_root}/{_BAKED_SOURCE}")


_VECTOR_FONT = """\
  bezel:
    face: RobotoCondensedBold
    size: 6%r
"""

_BAKED_FONT = f"""\
  clock:
    source: {_BAKED_SOURCE}
    size: 18%r
"""


def _text_element(extra: str = "", *, font: str | None = "font.bezel") -> str:
    font_line = f"    font: {font}\n" if font else ""
    return f"""\
  - id: brand
    type: text
    text: "GARMIN"
    color: palette.fg
    at: {{anchor: center}}
{font_line}{extra}"""


# -- fonts: face: ---------------------------------------------------------------


def test_vector_font_reaches_the_ir(write_design, bag, repo_root):
    design = _design(_VECTOR_FONT, _text_element(font=None), repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    spec = face.fonts["bezel"]
    assert spec.is_vector is True
    assert spec.is_baked is False
    assert spec.source is None
    assert spec.face == ("RobotoCondensedBold",)
    assert spec.if_unavailable == "error"


def test_vector_font_face_list_and_if_unavailable(write_design, bag, repo_root):
    fonts = """\
  bezel:
    face: [RobotoCondensedBold, RobotoCondensedRegular]
    size: 6%r
    if_unavailable: hide
"""
    design = _design(fonts, _text_element(font=None), repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    spec = face.fonts["bezel"]
    assert spec.face == ("RobotoCondensedBold", "RobotoCondensedRegular")
    assert spec.if_unavailable == "hide"


def test_baked_font_is_unaffected(write_design, bag, repo_root):
    """The existing baked shape still builds byte-for-byte the same way."""
    design = _design(_BAKED_FONT, _text_element(font="font.clock"), repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    spec = face.fonts["clock"]
    assert spec.is_baked is True
    assert spec.is_vector is False
    assert spec.face is None
    assert spec.if_unavailable is None


@pytest.mark.parametrize("both_source_and_face", [True, False])
def test_source_and_face_are_mutually_exclusive_and_jointly_required(
    write_design, bag, repo_root, both_source_and_face,
):
    """A `oneOf` in the schema, so the error names the missing half rather
    than reading as an unknown key (plan 11 §2.1)."""
    if both_source_and_face:
        fonts = f"""\
  bezel:
    source: {_BAKED_SOURCE}
    face: RobotoCondensedBold
    size: 6%r
"""
    else:
        fonts = """\
  bezel:
    size: 6%r
"""
    design = _design(fonts, _text_element(font=None), repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is None
    assert any(d.code == "schema" for d in bag.errors), bag.render()


@pytest.mark.parametrize("key,value", [
    ("glyphs", '"AB"'), ("monospace", "true"), ("align", '"left"'), ("antialias", "true"),
])
def test_baking_keys_are_rejected_on_a_vector_font(write_design, bag, repo_root, key, value):
    """`glyphs:`/`monospace:`/`align:`/`antialias:` are properties of baking a
    sheet, and a vector font has no sheet -- each must name why, not just
    reject (plan 11 §2.1)."""
    fonts = f"""\
  bezel:
    face: RobotoCondensedBold
    size: 6%r
    {key}: {value}
"""
    design = _design(fonts, _text_element(font=None), repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is None
    errors = [d for d in bag.errors if d.code == "font"]
    assert errors, bag.render()
    assert any(key in d.message and "face" in d.message for d in errors)


def test_if_unavailable_is_rejected_on_a_baked_font_entry(write_design, bag, repo_root):
    fonts = f"""\
  clock:
    source: {_BAKED_SOURCE}
    size: 18%r
    if_unavailable: hide
"""
    design = _design(fonts, _text_element(font="font.clock"), repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is None
    errors = [d for d in bag.errors if d.code == "font"]
    assert errors, bag.render()
    assert "if_unavailable" in errors[0].message
    assert "baked" in errors[0].message


# -- text: curve: ---------------------------------------------------------------


def test_angled_curve_reaches_the_ir_in_the_design_convention(write_design, bag, repo_root):
    """The angle stays 12-o'clock-zero/clockwise at this stage -- conversion
    to Garmin's own convention is codegen's job, a later slice."""
    element = _text_element("    curve: {style: angled, angle: 45deg}\n")
    design = _design(_VECTOR_FONT, element, repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    text = face.elements[0]
    assert text.curve is not None
    assert text.curve.style == "angled"
    assert text.curve.angle.degrees == pytest.approx(45.0)
    assert text.curve.radius is None
    assert text.curve.direction is None


def test_radial_curve_reaches_the_ir_with_radius_and_direction(write_design, bag, repo_root):
    element = _text_element(
        "    curve: {style: radial, angle: 90deg, radius: 44%r, "
        "direction: counter_clockwise}\n"
    )
    design = _design(_VECTOR_FONT, element, repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    curve = face.elements[0].curve
    assert curve.style == "radial"
    assert curve.angle.degrees == pytest.approx(90.0)
    assert curve.radius is not None and curve.radius.unit == "%r" and curve.radius.value == 44.0
    assert curve.direction == "counter_clockwise"


def test_radial_curve_defaults_to_clockwise(write_design, bag, repo_root):
    element = _text_element("    curve: {style: radial, angle: 0deg, radius: 40%r}\n")
    design = _design(_VECTOR_FONT, element, repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    assert face.elements[0].curve.direction == "clockwise"


def test_curve_on_a_baked_font_is_rejected(write_design, bag, repo_root):
    """Quotes the SDK directly: 'These APIs only support scalable fonts and
    do not support custom fonts loaded as resources.'"""
    element = _text_element("    curve: {style: angled, angle: 45deg}\n", font="font.clock")
    design = _design(_BAKED_FONT, element, repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is None
    errors = [d for d in bag.errors if d.code == "text-curve"]
    assert errors, bag.render()
    assert "face" in errors[0].message and "curve" in errors[0].message
    assert any("scalable fonts" in note for note in errors[0].notes)


def test_curve_on_a_system_font_is_rejected(write_design, bag, repo_root):
    """No `font:` at all -- the element draws with the system default,
    which is exactly as rejectable as a named system font."""
    element = _text_element("    curve: {style: angled, angle: 45deg}\n", font=None)
    design = _design(None, element, repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is None
    errors = [d for d in bag.errors if d.code == "text-curve"]
    assert errors, bag.render()
    assert any("system font" in note for note in errors[0].notes)


def test_radius_and_direction_are_rejected_under_angled(write_design, bag, repo_root):
    element = _text_element(
        "    curve: {style: angled, angle: 45deg, radius: 10%r, direction: clockwise}\n",
    )
    design = _design(_VECTOR_FONT, element, repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is None
    errors = [d for d in bag.errors if d.code == "text-curve"]
    assert errors, bag.render()
    messages = " ".join(d.message for d in errors)
    assert "radius" in messages and "angled" in messages
    assert "direction" in messages


def test_radial_requires_a_radius(write_design, bag, repo_root):
    """Schema-enforced (the required-key half of `progress`'s own
    `style:`-discriminator precedent)."""
    element = _text_element("    curve: {style: radial, angle: 45deg}\n")
    design = _design(_VECTOR_FONT, element, repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is None
    assert any(d.code == "schema" for d in bag.errors), bag.render()


def test_vertical_align_bottom_is_rejected_under_curve(write_design, bag, repo_root):
    element = _text_element(
        "    curve: {style: angled, angle: 45deg}\n    vertical_align: bottom\n",
    )
    design = _design(_VECTOR_FONT, element, repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is None
    errors = [d for d in bag.errors if d.code == "text-curve"]
    assert errors, bag.render()
    assert any("vertical_align" in d.message and "bottom" in d.message for d in errors)


@pytest.mark.parametrize("vertical_align", ["top", "center"])
def test_vertical_align_top_and_center_are_accepted_under_curve(
    write_design, bag, repo_root, vertical_align,
):
    """§2.3's VCENTER finding: the SDK's own `TrueTypeFonts` sample ORs
    `Graphics.TEXT_JUSTIFY_VCENTER` into `drawAngledText`/`drawRadialText`'s
    `justification`, so `top`/`center` both stay legal under `angled` and
    only `bottom` (a screen-space subtraction that cannot follow a rotated
    baseline) is rejected there."""
    element = _text_element(
        f"    curve: {{style: angled, angle: 45deg}}\n    vertical_align: {vertical_align}\n",
    )
    design = _design(_VECTOR_FONT, element, repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    assert face.elements[0].vertical_align == vertical_align


@pytest.mark.parametrize("vertical_align", ["top", "center", "bottom"])
def test_every_vertical_align_is_accepted_under_radial_curve(
    write_design, bag, repo_root, vertical_align,
):
    """`radial` accepts all three: `bottom` is the device's own
    baseline-on-the-circle mode (measured 2026-09-21), `top` the same call
    at a radius moved by the font's ascent, `center` is `VCENTER`."""
    element = _text_element(
        "    curve: {style: radial, angle: 45deg, radius: 50%r}\n"
        f"    vertical_align: {vertical_align}\n",
    )
    design = _design(_VECTOR_FONT, element, repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    assert face.elements[0].vertical_align == vertical_align


# -- text: if_unavailable: -------------------------------------------------------


def test_if_unavailable_on_a_vector_font_element_reaches_the_ir(write_design, bag, repo_root):
    element = _text_element("    if_unavailable: hide\n")
    design = _design(_VECTOR_FONT, element, repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    assert face.elements[0].if_unavailable == "hide"


def test_if_unavailable_is_rejected_on_an_element_with_a_baked_font(write_design, bag, repo_root):
    element = _text_element("    if_unavailable: hide\n", font="font.clock")
    design = _design(_BAKED_FONT, element, repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is None
    errors = [d for d in bag.errors if d.code == "text-curve"]
    assert errors, bag.render()
    assert "if_unavailable" in errors[0].message
    assert any("baked" in note for note in errors[0].notes)


def test_if_unavailable_is_rejected_on_an_element_with_a_system_font(write_design, bag, repo_root):
    element = _text_element("    if_unavailable: hide\n", font=None)
    design = _design(None, element, repo_root=repo_root)
    face = load(write_design(design), bag)
    assert face is None
    errors = [d for d in bag.errors if d.code == "text-curve"]
    assert errors, bag.render()
    assert any("system font" in note for note in errors[0].notes)


# -- a `face:` font used anywhere other than `text:` -----------------------
#
# `Builder.resolve_font` is shared by a `text` element, a
# `complication_slot` and a pattern's `shape: text` part -- only `text`
# actually knows how to draw a vector face (`Dc.drawText`/`drawAngledText`/
# `drawRadialText` all take one; nothing else in the generated code does).
# Before these checks existed, either of the two designs below validated
# clean and then crashed `monkeyc` on a generated `Undefined symbol` for the
# `:face` resource constant -- a raw compiler crash leaking to the author,
# which this project does not accept (root `CLAUDE.md` §6's `image`/`raw`
# precedent). Regression tests for that hole.


def test_vector_font_is_rejected_on_a_complication_slot(write_design, bag, repo_root):
    design = f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f58, name: Test}}
targets: [fenix8solar47mm]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
fonts:
{_VECTOR_FONT}config:
  data:
    slot1:
      default: complication.steps
      choices: [complication.steps]
elements:
  - id: slot0
    type: complication_slot
    slot: config.data.slot1
    font: font.bezel
    color: palette.fg
    at: {{anchor: center}}
"""
    face = load(write_design(design), bag)
    assert face is None
    errors = [d for d in bag.errors if d.code == "complication-slot"]
    assert errors, bag.render()
    assert "font.bezel" in errors[0].message
    assert "vector" in errors[0].message
    assert any("'text' element" in note for note in errors[0].notes)


def test_vector_font_is_accepted_on_a_pattern_text_part(write_design, bag, repo_root):
    """Slice 2 of plan 11 (`git show 35217d1:docs/plans/11-vector-text.md`
    §5): a pattern's own `shape: text` part may name a `face:` (vector)
    font, with or without
    `curve:` -- this used to be a build error naming "the next slice", and
    now that slice has landed. See `tests/test_pattern_text_curve.py` for
    the curve-specific behaviour (angle composition, if_unavailable, lint,
    codegen, preview)."""
    design = f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f59, name: Test}}
targets: [fenix8solar47mm]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
fonts:
{_VECTOR_FONT}elements:
  - id: hour_numerals
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 12
    color: palette.fg
    parts:
      - shape: text
        value: "(copy + 11) % 12 + 1"
        font: font.bezel
        at: {{dy: -64%r}}
"""
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    assert bag.ok(), bag.render()
    part = face.elements[0].parts[0]
    assert part.font_is_custom is True
    assert part.curve is None
