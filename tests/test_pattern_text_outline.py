"""`outline:` on a pattern's own `shape: text` part (plan 15 slice 2) --
the schema/IR/builder layer, mirroring `tests/test_text_outline.py`'s own
structure one level down: both spellings (D7), the width cap (D6),
`outline.color`'s full parity with `color:` including `copy` (D8, plan 15
§3 -- the one thing a pattern part's `outline.color` can do that a
standalone element's cannot), and the absence rule -- deferred here to
`Builder._check_pattern_absence` rather than an immediate per-key check,
since a pattern polices absence once for the whole element (`tests/
test_pattern_text.py`'s own `when_absent` tests are the precedent).

Layout box growth, codegen and the golden fixture are covered separately
(`tests/test_pattern_text_outline_codegen.py`); preview in
`tests/test_pattern_text_outline_preview.py`; the lint check in
`tests/test_lint.py`.
"""

from __future__ import annotations

from tests.test_diagnostics import load


def _design(minimal: str, extra: str) -> str:
    return minimal + extra


def _pattern_outline(outline: str, *, when_absent: str = "", second_part: str = "") -> str:
    absent = f"\n    when_absent: {when_absent}" if when_absent else ""
    return f"""
  - id: ring
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1{absent}
    parts:
      - shape: text
        text: "12"
        font: FONT_MEDIUM
        color: palette.fg
        outline: {outline}{second_part}
"""


# -- both spellings accepted (D7), same as a standalone element -------------


def test_pattern_outline_none_is_the_default_shape(write_design, bag, minimal):
    face = load(write_design(_design(minimal, _pattern_outline("none"))), bag)
    assert face is not None, bag.render()
    ring = next(e for e in face.elements if e.id == "ring")
    assert ring.parts[0].outline is None


def test_pattern_outline_omitted_key_is_also_none(write_design, bag, minimal):
    design = _design(minimal, """
  - id: ring
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 1
    parts:
      - shape: text
        text: "12"
        font: FONT_MEDIUM
        color: palette.fg
""")
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    ring = next(e for e in face.elements if e.id == "ring")
    assert ring.parts[0].outline is None


def test_pattern_outline_shorthand_colour_defaults_width_2(write_design, bag, minimal):
    face = load(write_design(_design(minimal, _pattern_outline("palette.fg"))), bag)
    assert face is not None, bag.render()
    ring = next(e for e in face.elements if e.id == "ring")
    outline = ring.parts[0].outline
    assert outline is not None
    assert outline.width == 2
    assert outline.color.text == "palette.fg"


def test_pattern_outline_object_form_with_explicit_width(write_design, bag, minimal):
    face = load(write_design(_design(
        minimal, _pattern_outline("{color: palette.fg, width: 1}"))), bag)
    assert face is not None, bag.render()
    ring = next(e for e in face.elements if e.id == "ring")
    assert ring.parts[0].outline.width == 1


def test_pattern_outline_object_form_defaults_width_2(write_design, bag, minimal):
    face = load(write_design(_design(
        minimal, _pattern_outline("{color: palette.fg}"))), bag)
    assert face is not None, bag.render()
    ring = next(e for e in face.elements if e.id == "ring")
    assert ring.parts[0].outline.width == 2


def test_pattern_outline_hex_literal_shorthand(write_design, bag, minimal):
    face = load(write_design(_design(minimal, _pattern_outline('"#FF0000"'))), bag)
    assert face is not None, bag.render()
    ring = next(e for e in face.elements if e.id == "ring")
    assert ring.parts[0].outline is not None


# -- missing 'color:' in object form is a schema error -----------------------


def test_pattern_outline_object_form_without_color_is_a_schema_error(write_design, bag, minimal):
    face = load(write_design(_design(minimal, _pattern_outline("{width: 2}"))), bag)
    assert face is None
    assert not bag.ok()


# -- width cap (D6): red-then-green, part_where names the part ---------------


def test_pattern_outline_width_over_cap_is_a_build_error(write_design, bag, minimal):
    face = load(write_design(_design(
        minimal, _pattern_outline("{color: palette.fg, width: 4}"))), bag)
    assert face is None
    assert not bag.ok()
    diag = next(d for d in bag.errors if d.code == "text-outline")
    assert "ring.parts[0]" in diag.message
    assert "3" in diag.message or "3px" in " ".join(diag.notes)


def test_pattern_outline_width_at_cap_builds_clean(write_design, bag, minimal):
    face = load(write_design(_design(
        minimal, _pattern_outline("{color: palette.fg, width: 3}"))), bag)
    assert face is not None, bag.render()
    ring = next(e for e in face.elements if e.id == "ring")
    assert ring.parts[0].outline.width == 3


# -- outline.color has full parity with color:, INCLUDING 'copy' (D8) -------


def test_pattern_outline_color_reads_copy(write_design, bag, minimal):
    """The one thing a pattern part's `outline.color` can do that a
    standalone `text` element's cannot (plan 15 §3): `copy` is bound in a
    pattern's own scope, so the ring can alternate by copy exactly the way
    the interior fill already can."""
    face = load(write_design(_design(
        minimal, _pattern_outline('"copy == 0 ? palette.fg : palette.bg"'))), bag)
    assert face is not None, bag.render()
    ring = next(e for e in face.elements if e.id == "ring")
    outline = ring.parts[0].outline
    assert outline is not None
    assert "copy" in outline.color.text


def test_pattern_outline_color_reads_a_config_expression(write_design, bag, minimal):
    design = minimal.replace(
        "elements:",
        "config:\n  accent_color: {default: palette.fg, choices: any}\nelements:",
    )
    face = load(write_design(_design(design, _pattern_outline("config.accent_color"))), bag)
    assert face is not None, bag.render()
    ring = next(e for e in face.elements if e.id == "ring")
    assert ring.parts[0].outline.color.text == "config.accent_color"


def test_pattern_outline_color_type_error_matches_color(write_design, bag, minimal):
    """A non-colour expression is rejected the same way `color:` rejects
    one -- `_color_expression` is shared, not a parallel, looser check."""
    face = load(write_design(_design(minimal, _pattern_outline('"1 + 1"'))), bag)
    assert face is None
    assert any(d.code == "type" for d in bag.errors)


# -- absence: deferred to the pattern-level check, not an immediate one -----


def test_pattern_outline_color_nullable_without_when_absent_is_an_error(write_design, bag, minimal):
    face = load(write_design(_design(
        minimal,
        _pattern_outline('"complication.battery > 50 ? palette.fg : palette.bg"'))), bag)
    assert face is None
    errors = [d for d in bag.errors if d.code == "when-absent"]
    assert errors, bag.render()
    # the pattern's own message, naming the element, not a per-key one
    assert "ring" in errors[0].message
    assert "when_absent: hide" in errors[0].message


def test_pattern_outline_color_nullable_with_when_absent_hide_builds_clean(write_design, bag, minimal):
    face = load(write_design(_design(
        minimal,
        _pattern_outline(
            '"complication.battery > 50 ? palette.fg : palette.bg"', when_absent="hide"))), bag)
    assert face is not None, bag.render()
    ring = next(e for e in face.elements if e.id == "ring")
    assert ring.parts[0].outline.color.nullable is True


def test_pattern_outline_color_folds_into_element_colors(write_design, bag, minimal):
    """`PatternElement._own_expressions` grows to include a part's own
    `outline.color` by way of `PatternElement.colors` (`_build_pattern_
    element`'s own `_dedup_append` calls) -- checked directly here rather
    than only indirectly through the absence tests above, since a bug that
    ran the absence check some other way could still pass those."""
    face = load(write_design(_design(
        minimal, _pattern_outline("palette.fg"))), bag)
    assert face is not None, bag.render()
    ring = next(e for e in face.elements if e.id == "ring")
    outline_color = ring.parts[0].outline.color
    assert outline_color in ring.colors
    assert outline_color in ring.expressions()


# -- 'outline' is a text-only key, same "key belongs to another shape" sweep


def test_pattern_outline_rejected_on_a_non_text_shape(write_design, bag, minimal):
    design = _design(minimal, """
  - id: dot
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 1
    color: palette.fg
    parts:
      - shape: circle
        radius: 10px
        outline: {color: palette.fg, width: 2}
""")
    face = load(write_design(design), bag)
    assert face is None
    assert not bag.ok()
