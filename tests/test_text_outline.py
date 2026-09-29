"""`outline:` on a standalone `text` element (plan 15 slice 1) -- the schema/
IR/builder layer: both spellings (D7), the width cap (D6), `outline.color`'s
full parity with `color:` (D8), and the absence rule `check_other_absence`
already gives every other non-value binding.  Layout, codegen, lint and
preview are covered separately (`tests/test_text_outline_layout.py`,
`tests/test_text_outline_golden.py`, `tests/test_lint.py`,
`tests/test_text_outline_preview.py`).
"""

from __future__ import annotations

import pytest

from wfb.build import load


def _design(minimal: str, extra: str) -> str:
    return minimal + extra


def _outline_text(outline: str, *, absent: str = "") -> str:
    absent = f"\n    absent: {absent}" if absent else ""
    return f"""
  clock:
    type: text
    text: "12:34"
    color: color.fg
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
  clock:
    type: text
    text: "12:34"
    color: color.fg
    at: {anchor: center}
""")
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    clock = next(e for e in face.elements if e.id == "clock")
    assert clock.outline is None


def test_outline_is_a_colour_and_nothing_else(write_design, bag, minimal):
    """Every ring is 1px (research 19 §4.5): the colour is all an
    `Outline` carries."""
    face = load(write_design(_design(minimal, _outline_text("color.fg"))), bag)
    assert face is not None, bag.render()
    clock = next(e for e in face.elements if e.id == "clock")
    assert clock.outline is not None
    assert clock.outline.color.shown == "color.fg"
    assert not hasattr(clock.outline, "width")


def test_outline_hex_literal_shorthand(write_design, bag, minimal):
    """A bare hex literal is legal too -- `colorExpression` covers both a
    palette reference and a literal colour."""
    face = load(write_design(_design(minimal, _outline_text('"#FF0000"'))), bag)
    assert face is not None, bag.render()
    clock = next(e for e in face.elements if e.id == "clock")
    assert clock.outline is not None


# -- the removed {color, width} form -------------------------------------------


@pytest.mark.parametrize("spelling", ["{color: color.fg, width: 2}", "{color: color.fg}",
                                      "{width: 1, color: color.fg}"])
def test_the_removed_object_form_names_its_replacement(write_design, bag, minimal, spelling):
    """One friendly error naming the colour spelling -- never the schema's
    generic oneOf failure."""
    face = load(write_design(_design(minimal, _outline_text(spelling))), bag)
    assert face is None
    assert [d.code for d in bag.errors] == ["outline"], bag.render()
    assert "a ring is always 1px" in bag.errors[0].message
    assert "outline: color.fg" in " ".join(bag.errors[0].notes)


# -- outline.color has full parity with color: (D8) --------------------------


def test_outline_color_reads_a_config_expression(write_design, bag, minimal):
    design = minimal.replace(
        "elements:",
        """config:
  accent_color: {default: color.fg, choices: any}
elements:""",
    )
    face = load(write_design(_design(design, _outline_text("color.accent"))), bag)
    assert face is not None, bag.render()
    clock = next(e for e in face.elements if e.id == "clock")
    assert clock.outline is not None
    assert clock.outline.color.shown == "color.accent"


def test_outline_color_reads_a_conditional_expression(write_design, bag, minimal):
    """`outline.color` accepts a full expression, not just a bare
    reference -- the same grammar `color:` itself has (D8)."""
    face = load(write_design(_design(
        minimal, _outline_text('"copy == 0 ? color.fg : color.bg"'))), bag)
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
        """config:
  data_color: {default: color.fg, choices: any}
elements:""",
    )
    # `complication.battery` is a real nullable catalogue source used
    # elsewhere in this project's own tests as the canonical nullable case.
    face = load(write_design(_design(
        design, _outline_text('"complication.battery > 50 ? color.fg : color.bg"'))), bag)
    assert face is None
    assert any(d.code == "when-absent" for d in bag.errors)


def test_outline_color_nullable_with_when_absent_hide_builds_clean(write_design, bag, minimal):
    face = load(write_design(_design(
        minimal,
        _outline_text(
            '"complication.battery > 50 ? color.fg : color.bg"', absent="hide"),
    )), bag)
    assert face is not None, bag.render()
    clock = next(e for e in face.elements if e.id == "clock")
    assert clock.outline is not None
    assert clock.outline.color.nullable is True
