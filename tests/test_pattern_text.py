"""Pattern text parts (plan 06 §3): a `type: pattern` template part with
`shape: text` -- upright glyphs whose anchor turns (radial) or steps
(linear) with the copy.  This is phase B1 (`docs/plans/06-pattern-text-and-
group-align.md` §5): schema, IR, layout, `glyph_set` and the glyph lint --
not the barrel or codegen (B2) and not the preview (B3).

Every diagnostic here was driven red first, `tests/CLAUDE.md`'s own
discipline: run against the violating input below with the corresponding
`wfb/ir/` check reverted, each one raised a different, wrong error (or
built clean) before the fix landed.
"""

from __future__ import annotations

import math

from tests.helpers import errors, find
from wfb.build import load
from wfb import lint
from wfb.emit.resources import bake_fonts, glyph_set
from wfb.layout import ResolvedHandPart, pattern_text_anchor, resolve

BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm, fenix8solar51mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
"""


def design(elements_block: str, extra: str = "") -> str:
    return BASE + extra + "\nelements:\n" + elements_block


def ring(part_yaml: str, count: int = 4, extra: str = "") -> str:
    """A four-copy radial ring (90deg apart, the default step), with one
    template part supplied verbatim -- the same `RADIAL_RING` precedent
    `tests/test_patterns.py` uses, parameterised over the part so every
    diagnostic test below only has to write the one line that differs.
    """
    return f"""  - id: ring
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: {count}
    color: palette.fg
{extra}    parts:
{part_yaml}
"""


#: The reference text part: twelve copies, `(copy + 11) % 12 + 1` -- copy 0
#: draws "12", copy 1 draws "1", ... copy 11 draws "11" -- the exact example
#: `docs/plans/06-pattern-text-and-group-align.md` §3.1 gives for a clock
#: face's hour numerals.
HOURS = """  - id: hours
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 12
    color: palette.fg
    parts:
      - shape: text
        value: "(copy + 11) % 12 + 1"
        at: {dy: -80%r}
"""


# -- IR: per-copy strings ----------------------------------------------------


def test_value_expression_renders_every_copy(write_design, bag):
    """The example from the plan: `(copy + 11) % 12 + 1` over twelve copies
    is the "1..12 with 12 first" hour-numeral sequence, not "0..11"."""
    face = load(write_design(design(HOURS)), bag)
    assert face is not None, bag.render()
    part = face.elements[0].parts[0]
    assert part.texts == ("12", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11")


def test_format_spec_applies_per_copy(write_design, bag):
    part_yaml = ("      - shape: text\n"
                 "        value: copy\n"
                 '        format: "{:02d}"\n'
                 "        at: {dy: -50px}\n")
    face = load(write_design(design(ring(part_yaml))), bag)
    assert face is not None, bag.render()
    part = face.elements[0].parts[0]
    assert part.texts == ("00", "01", "02", "03")


def test_fixed_text_repeats_for_every_copy(write_design, bag):
    part_yaml = '      - shape: text\n        text: "x"\n        at: {dy: -50px}\n'
    face = load(write_design(design(ring(part_yaml, count=3))), bag)
    assert face is not None, bag.render()
    part = face.elements[0].parts[0]
    assert part.texts == ("x", "x", "x")


# -- IR: §3.3 build-time checks, each driven red -----------------------------


def test_both_value_and_text_is_one_error(write_design, bag):
    part_yaml = ('      - shape: text\n'
                 '        value: copy\n'
                 '        text: "x"\n'
                 '        at: {dy: -50px}\n')
    bad = errors(design(ring(part_yaml)), bag, write_design)
    assert len(bad) == 1
    assert bad[0].code == "pattern"
    assert "exactly one of" in bad[0].message


def test_neither_value_nor_text_is_one_error(write_design, bag):
    part_yaml = "      - shape: text\n        at: {dy: -50px}\n"
    bad = errors(design(ring(part_yaml)), bag, write_design)
    assert len(bad) == 1
    assert bad[0].code == "pattern"
    assert "exactly one of" in bad[0].message


def test_value_reading_a_palette_reference_is_one_error(write_design, bag):
    part_yaml = "      - shape: text\n        value: palette.fg\n        at: {dy: -50px}\n"
    bad = errors(design(ring(part_yaml)), bag, write_design)
    assert len(bad) == 1
    assert "may read only 'copy'" in bad[0].message
    assert "palette.fg" in bad[0].message


def test_value_reading_a_data_source_is_one_error(write_design, bag):
    """A data source, not just palette: the same rule, a different kind of
    non-`copy` reference (§3.3 check 2)."""
    part_yaml = "      - shape: text\n        value: activity.steps\n        at: {dy: -50px}\n"
    bad = errors(design(ring(part_yaml)), bag, write_design)
    assert len(bad) == 1
    assert "may read only 'copy'" in bad[0].message
    assert "activity.steps" in bad[0].message


def test_a_boolean_value_is_one_error(write_design, bag):
    part_yaml = '      - shape: text\n        value: "copy > 3"\n        at: {dy: -50px}\n'
    bad = errors(design(ring(part_yaml)), bag, write_design)
    assert len(bad) == 1
    assert "must be a number or a string" in bad[0].message


def test_format_with_a_fixed_text_is_one_error(write_design, bag):
    part_yaml = ('      - shape: text\n'
                 '        text: "x"\n'
                 '        format: "{:02d}"\n'
                 '        at: {dy: -50px}\n')
    bad = errors(design(ring(part_yaml)), bag, write_design)
    assert len(bad) == 1
    assert "applies only to 'value:'" in bad[0].message


def test_radius_on_a_text_part_is_one_error(write_design, bag):
    part_yaml = ('      - shape: text\n'
                 '        value: copy\n'
                 '        radius: 5px\n'
                 '        at: {dy: -50px}\n')
    bad = errors(design(ring(part_yaml)), bag, write_design)
    assert len(bad) == 1
    assert "'radius' is not used by a pattern 'shape: text' part" in bad[0].message


def test_font_on_a_line_part_is_one_error(write_design, bag):
    """The reverse direction: a text-only key on a different shape is caught
    by the same "key not used by this shape" sweep (`_check_hand_part_keys`),
    with no special-casing for `font:` needed."""
    part_yaml = ('      - shape: line\n'
                 '        at: {dy: -40px}\n'
                 '        to: {dy: -50px}\n'
                 '        font: FONT_MEDIUM\n')
    bad = errors(design(ring(part_yaml)), bag, write_design)
    assert len(bad) == 1
    assert "'font' is not used by a pattern 'shape: line' part" in bad[0].message


def test_undeclared_font_is_one_error(write_design, bag):
    part_yaml = ('      - shape: text\n'
                 '        value: copy\n'
                 '        font: font.nope\n'
                 '        at: {dy: -50px}\n')
    bad = errors(design(ring(part_yaml)), bag, write_design)
    assert len(bad) == 1
    assert "unknown font 'font.nope'" in bad[0].message


def test_a_hand_still_rejects_shape_text(write_design, bag):
    """Regression: `HAND_PART_REJECTED_SHAPES` keeps its own `text` entry --
    only `PATTERN_PART_REJECTED_SHAPES` lost it. Same wording as before plan
    06 (`tests/test_patterns.py`'s own hand-vs-pattern regression test)."""
    hands = """
hands:
  classic:
    hour:
      color: palette.fg
      parts:
        - {shape: text, at: {dy: -30%r}}
"""
    elements = """  - id: h
    type: hands
    hands: classic
    at: {anchor: center}
"""
    bad = errors(BASE + hands + "\nelements:\n" + elements, bag, write_design)
    assert len(bad) == 1
    assert "'shape: text' is not accepted on a hand part" in bad[0].message
    assert "a bitmap font cannot rotate" in bad[0].message


# -- layout: radial -----------------------------------------------------------


#: Four copies, 90deg apart (the default step), one text part 50px above the
#: pattern's own centre, system font (`FONT_MEDIUM`, the default) -- no
#: `fonts:` block needed.
LAYOUT_RING = """  - id: ring
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 4
    color: palette.fg
    parts:
      - shape: text
        value: copy
        at: {dy: -50px}
"""


def test_radial_text_anchor_turns_with_the_copy(resolved_for):
    resolved = resolved_for(design(LAYOUT_RING))
    placed = find(resolved, "ring")
    part = placed.parts[0]
    assert part.shape == "text"
    cx, cy = placed.center

    # copy 0: dead above the centre.
    ax0, ay0 = pattern_text_anchor(part, *placed.transform(0))
    assert ax0 == cx
    assert ay0 == cy - 50

    # copy 1, 90deg clockwise from 12 o'clock: dead to the right.
    ax1, ay1 = pattern_text_anchor(part, *placed.transform(1))
    assert (ax1, ay1) == (cx + 50, cy)


def test_radial_text_box_is_the_union_of_every_drawn_copy(resolved_for):
    """`placed.box` contains every drawn copy's own text box -- computed
    here from `pattern_text_anchor` and `part.widths` independently of
    `wfb.layout._pattern_part_ink`, so a broken box union (or a broken
    per-copy width lookup) fails this even if the private helper itself is
    never touched."""
    resolved = resolved_for(design(LAYOUT_RING))
    placed = find(resolved, "ring")
    part = placed.parts[0]

    min_x = min_y = math.inf
    max_x = max_y = -math.inf
    for index in placed.copies:
        ax, ay = pattern_text_anchor(part, *placed.transform(index))
        width = part.widths[index]
        left, top = ax - width / 2.0, ay - part.line_height / 2.0
        min_x, min_y = min(min_x, left), min(min_y, top)
        max_x, max_y = max(max_x, left + width), max(max_y, top + part.line_height)

    # `IntBox.rounded()` snaps independently at each edge, so allow the
    # ordinary +/-1px a `round()` can move any one edge by.
    assert placed.box.x <= min_x + 1
    assert placed.box.y <= min_y + 1
    assert placed.box.x + placed.box.width >= max_x - 1
    assert placed.box.y + placed.box.height >= max_y - 1


def test_radial_reach_accounts_for_the_upright_text_box(resolved_for):
    """Upright text is not rotation-invariant (plan 06 §3.4): `reach` has to
    be at least the `at:` radius plus half the text's own height, not just
    the bare 50px a rotation-invariant shape would report."""
    resolved = resolved_for(design(LAYOUT_RING))
    placed = find(resolved, "ring")
    part = placed.parts[0]
    assert placed.reach >= 50 + part.line_height / 2.0


# -- layout: linear -------------------------------------------------------


LAYOUT_ROW = """  - id: row
    type: pattern
    pattern: linear
    at: {anchor: center}
    count: 3
    step: {dx: 30px}
    color: palette.fg
    parts:
      - shape: text
        value: copy
"""


def test_linear_text_anchor_steps_by_dx(resolved_for):
    resolved = resolved_for(design(LAYOUT_ROW))
    placed = find(resolved, "row")
    part = placed.parts[0]
    cx, cy = placed.center
    anchors = [pattern_text_anchor(part, *placed.transform(i)) for i in placed.copies]
    assert anchors == [(cx, cy), (cx + 30, cy), (cx + 60, cy)]


# -- half-up rounding (D5) ----------------------------------------------------


def test_pattern_text_anchor_rounds_half_up_not_to_even_or_away_from_zero():
    """Plan §3.2 D5: `floor(v + 0.5)`, not Python's banker's `round()` and
    not `_round_away`'s half-away-from-zero -- picked so the device's own
    `(v + 0.5).toNumber()` (`runtime-lib/WfbGeom.mc`, phase B2) matches this
    exactly. `x = 2.5` rounds up to 3 (`round(2.5)` would give 2, banker's
    rounding to even); `y = -0.5` rounds up to 0 (`_round_away(-0.5)` would
    give -1, rounding away from zero)."""
    part = ResolvedHandPart("text", None, x=2.5, y=-0.5)
    ax, ay = pattern_text_anchor(part, 0.0, 0.0, 0.0, 1.0)
    assert ax == 3
    assert ay == 0


def test_pattern_text_anchor_negative_offset_needs_floor_not_truncation():
    """The test above (`x = 2.5`, `y = -0.5`) happens to dodge the one case
    where 'the device's own `(v + 0.5).toNumber()` matches this exactly'
    was not actually true before the 2026-09-23 fix to `runtime-lib/
    WfbGeom.mc`: `y = -0.5` lands `v + 0.5` exactly on `0.0`, where
    Monkey C's truncate-toward-zero (`.toNumber()`, `WfbArc.roundAway`'s
    own docstring) and `floor` agree by coincidence. `x = -1.6` does not --
    a rotated/translated pattern text anchor can legitimately land off the
    screen's top-left edge (`docs/limitations.md`'s 'off-screen' lint is
    suppressible, not a build error), and this is exactly the input shape
    where the pre-fix barrel (`(v + 0.5).toNumber()` alone, no `Math.
    floor`) rounded one pixel away from what this function -- and `wfb
    preview` -- compute. See `test_wfb_geom_rotated_helpers_round_with_
    math_floor` below for the barrel-side half of this fix."""
    part = ResolvedHandPart("text", None, x=-1.6, y=0.0)
    ax, _ = pattern_text_anchor(part, 0.0, 0.0, 0.0, 1.0)
    assert ax == -2  # floor(-1.6 + 0.5) == floor(-1.1) == -2
    # Monkey C's own (v + 0.5).toNumber() truncates toward zero instead:
    # the exact disagreement runtime-lib/WfbGeom.mc is asserted to have
    # fixed below.
    assert int(-1.6 + 0.5) == -1
    assert ax != int(-1.6 + 0.5)


def test_wfb_geom_rotated_helpers_round_with_math_floor():
    """No simulator runs in this container (CLAUDE.md), so the barrel's own
    source is inspected directly for the fix -- the same 'read the actual
    .mc text' approach `tests/test_parameter_limits.py` already uses for
    this exact file. `rotatedX`/`rotatedY` must round through `Math.
    floor(...)`, or a negative anchor rounds one pixel off from this
    module's own `pattern_text_anchor` (proven by the test above)."""
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "runtime-lib" / "WfbGeom.mc").read_text()
    for name in ("rotatedX", "rotatedY"):
        start = text.index(f"function {name}(")
        end = text.index("\n    }", start)
        body = text[start:end]
        assert "Math.floor(" in body, (
            f"WfbGeom.{name} must round with Math.floor(...), not plain "
            "(v + 0.5).toNumber() truncation -- see "
            "test_pattern_text_anchor_negative_offset_needs_floor_not_truncation"
        )


# -- glyph_set (resources.py) -------------------------------------------------


def _custom_font_design(part_yaml: str, count: int, ttf, extra: str = "") -> str:
    return f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: [fenix8solar47mm]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
fonts:
  small:
    source: {ttf}
    size: 20px
elements:
{ring(part_yaml, count=count, extra=extra)}"""


def test_glyph_set_is_exactly_the_drawn_copies_characters(write_design, bag, repo_root):
    ttf = repo_root / "tests/fixtures/slice/assets/OpenSans-Regular.ttf"
    part_yaml = ("      - shape: text\n"
                 "        value: copy + 1\n"
                 "        font: font.small\n"
                 "        at: {dy: -50px}\n")
    text = _custom_font_design(part_yaml, count=3, ttf=ttf)
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    chars = set(glyph_set(face)["small"])
    assert chars == set("123")


def test_glyph_set_respects_skip(write_design, bag, repo_root):
    ttf = repo_root / "tests/fixtures/slice/assets/OpenSans-Regular.ttf"
    part_yaml = ("      - shape: text\n"
                 "        value: copy + 1\n"
                 "        font: font.small\n"
                 "        at: {dy: -50px}\n")
    text = _custom_font_design(part_yaml, count=3, ttf=ttf, extra="    skip: [1]\n")
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    chars = set(glyph_set(face)["small"])
    assert chars == set("13")


# -- check_glyphs (lint.py) ---------------------------------------------------


def test_check_glyphs_flags_a_pattern_text_part(write_design, bag, db, repo_root):
    ttf = repo_root / "tests/fixtures/slice/assets/OpenSans-Regular.ttf"
    text = f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: [fenix8solar47mm]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
fonts:
  small:
    source: {ttf}
    size: 20px
    glyphs: "12"
elements:
  - id: ring
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1
    color: palette.fg
    parts:
      - shape: text
        value: "3"
        font: font.small
        at: {{dy: -50px}}
"""
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    lint.run(resolved, bag)
    findings = [d for d in bag.items if d.code == "missing-glyph"]
    assert len(findings) == 1
    assert "no glyph for" in findings[0].message
    assert "'3'" in findings[0].message
