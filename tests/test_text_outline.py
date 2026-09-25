"""`outline:` on a standalone `text` element (plan 15 slice 1) -- the schema/
IR/builder layer: both spellings (D7), the width cap (D6), `outline.color`'s
full parity with `color:` (D8), and the absence rule `check_other_absence`
already gives every other non-value binding.  Layout, codegen, lint and
preview are covered separately (`tests/test_text_outline_layout.py`,
`tests/test_text_outline_golden.py`, `tests/test_lint.py`,
`tests/test_text_outline_preview.py`).
"""

from __future__ import annotations

from wfb.build import load


def _design(minimal: str, extra: str) -> str:
    return minimal + extra


def _outline_text(outline: str, *, when_absent: str = "") -> str:
    absent = f"\n    when_absent: {when_absent}" if when_absent else ""
    return f"""
  - id: clock
    type: text
    text: "12:34"
    color: palette.fg
    at: {{anchor: center}}
    outline: {outline}{absent}
"""


# -- both spellings accepted (D7) --------------------------------------------


def test_outline_none_is_the_default_shape(write_design, bag, minimal):
    """Omitting `outline:` entirely, and writing `outline: none` explicitly,
    both resolve to no outline at all -- `outline: none` is not merely
    schema-legal, it must actually build a `Text` with `.outline is None`,
    which is the contrast this test claims (an implementation that treated
    `none` as *any* truthy string would fail it)."""
    face = load(write_design(_design(minimal, _outline_text("none"))), bag)
    assert face is not None, bag.render()
    clock = next(e for e in face.elements if e.id == "clock")
    assert clock.outline is None


def test_outline_omitted_key_is_also_none(write_design, bag, minimal):
    design = _design(minimal, """
  - id: clock
    type: text
    text: "12:34"
    color: palette.fg
    at: {anchor: center}
""")
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    clock = next(e for e in face.elements if e.id == "clock")
    assert clock.outline is None


def test_outline_shorthand_colour_defaults_width_2(write_design, bag, minimal):
    """The bare-colour shorthand (D7) is 'width: 2' with that colour --
    checked against the actual resolved width, not just "it parsed", since
    an implementation that accepted the shorthand but defaulted to some
    other width would still pass a weaker "no error" test."""
    face = load(write_design(_design(minimal, _outline_text("palette.fg"))), bag)
    assert face is not None, bag.render()
    clock = next(e for e in face.elements if e.id == "clock")
    assert clock.outline is not None
    assert clock.outline.width == 2
    assert clock.outline.color.text == "palette.fg"


def test_outline_object_form_with_explicit_width(write_design, bag, minimal):
    face = load(write_design(_design(
        minimal, _outline_text("{color: palette.fg, width: 3}"))), bag)
    assert face is not None, bag.render()
    clock = next(e for e in face.elements if e.id == "clock")
    assert clock.outline is not None
    assert clock.outline.width == 3


def test_outline_object_form_defaults_width_2(write_design, bag, minimal):
    face = load(write_design(_design(
        minimal, _outline_text("{color: palette.fg}"))), bag)
    assert face is not None, bag.render()
    clock = next(e for e in face.elements if e.id == "clock")
    assert clock.outline is not None
    assert clock.outline.width == 2


def test_outline_hex_literal_shorthand(write_design, bag, minimal):
    """A bare hex literal is also legal shorthand -- `colorExpression`
    covers both a palette reference and a literal colour."""
    face = load(write_design(_design(minimal, _outline_text('"#FF0000"'))), bag)
    assert face is not None, bag.render()
    clock = next(e for e in face.elements if e.id == "clock")
    assert clock.outline is not None


# -- missing 'color:' in object form is a schema error -----------------------


def test_outline_object_form_without_color_is_a_schema_error(write_design, bag, minimal):
    face = load(write_design(_design(minimal, _outline_text("{width: 2}"))), bag)
    assert face is None
    assert not bag.ok()


def test_outline_object_form_with_width_zero_is_a_schema_error(write_design, bag, minimal):
    """`width:` has a schema `minimum: 1` -- 0 is rejected before the
    builder's own cap ever runs."""
    face = load(write_design(_design(
        minimal, _outline_text("{color: palette.fg, width: 0}"))), bag)
    assert face is None
    assert not bag.ok()


# -- width cap (D6): red-then-green -------------------------------------------


def test_outline_width_over_cap_is_a_build_error(write_design, bag, minimal):
    """`width: 4` is schema-legal (no `maximum:` in the schema, D6) but a
    build error, citing the measured evidence, not jsonschema's generic
    message -- the red half of red-then-green."""
    face = load(write_design(_design(
        minimal, _outline_text("{color: palette.fg, width: 4}"))), bag)
    assert face is None
    assert not bag.ok()
    diag = next(d for d in bag.errors if d.code == "text-outline")
    assert "3" in diag.message or "3px" in " ".join(diag.notes)


def test_outline_width_at_cap_builds_clean(write_design, bag, minimal):
    """`width: 3` -- the cap itself -- is accepted: the green half of the
    same contrast the previous test drives red.  Without this test, a
    builder that rejected everything above `width: 1` would still pass the
    red half alone."""
    face = load(write_design(_design(
        minimal, _outline_text("{color: palette.fg, width: 3}"))), bag)
    assert face is not None, bag.render()
    clock = next(e for e in face.elements if e.id == "clock")
    assert clock.outline is not None
    assert clock.outline.width == 3


# -- outline.color has full parity with color: (D8) --------------------------


def test_outline_color_reads_a_config_expression(write_design, bag, minimal):
    design = minimal.replace(
        "elements:",
        "config:\n  accent_color: {default: palette.fg, choices: any}\nelements:",
    )
    face = load(write_design(_design(design, _outline_text("config.accent_color"))), bag)
    assert face is not None, bag.render()
    clock = next(e for e in face.elements if e.id == "clock")
    assert clock.outline is not None
    assert clock.outline.color.text == "config.accent_color"


def test_outline_color_reads_a_conditional_expression(write_design, bag, minimal):
    """`outline.color` accepts a full expression, not just a bare
    reference -- the same grammar `color:` itself has (D8)."""
    face = load(write_design(_design(
        minimal, _outline_text('"copy == 0 ? palette.fg : palette.bg"'))), bag)
    # `copy` is only bound inside a pattern part -- this design is a
    # standalone `text` element, so the expression is rejected, but the
    # important thing this proves is that outline.color is compiled through
    # the general expression path (it produces a real diagnostic about
    # 'copy', not a "not a valid colour" or "unknown key" error).
    assert face is None
    assert not bag.ok()
    assert not any(d.code in ("schema", "element-mapping") for d in bag.errors)


def test_outline_color_type_error_matches_color(write_design, bag, minimal):
    """A non-colour expression is rejected the same way `color:` rejects
    one -- `color_expression` is shared, not a parallel, looser check."""
    design = _design(minimal, _outline_text('"1 + 1"'))
    face = load(write_design(design), bag)
    assert face is None
    assert any(d.code == "type" for d in bag.errors)


# -- absence rule (mirrors color:'s own check_other_absence) ----------------


def test_outline_color_nullable_without_when_absent_is_an_error(write_design, bag, minimal):
    design = minimal.replace(
        "elements:",
        "config:\n  data_color: {default: palette.fg, choices: any}\nelements:",
    )
    # `complication.battery` is a real nullable catalogue source used
    # elsewhere in this project's own tests as the canonical nullable case.
    face = load(write_design(_design(
        design, _outline_text('"complication.battery > 50 ? palette.fg : palette.bg"'))), bag)
    assert face is None
    assert any(d.code == "when-absent" for d in bag.errors)


def test_outline_color_nullable_with_when_absent_hide_builds_clean(write_design, bag, minimal):
    face = load(write_design(_design(
        minimal,
        _outline_text(
            '"complication.battery > 50 ? palette.fg : palette.bg"', when_absent="hide"),
    )), bag)
    assert face is not None, bag.render()
    clock = next(e for e in face.elements if e.id == "clock")
    assert clock.outline is not None
    assert clock.outline.color.nullable is True
