"""Plan 07 phase D: `align:`/`vertical_align:` on hand and pattern parts
`rectangle` and `circle` (`docs/plans/07-align-everywhere.md` §4, Phase D
row).

Mechanism (a), in the part's own frame: `Resolver._resolve_hand_part` shifts
the part's frame centre (`_hand_point(part.at)`, or the resolved radius for a
circle) by `wfb.layout.alignment_shift` *before* computing corners/reach and
before `_round_away` -- everything downstream (a hand's rotation, a
pattern's per-copy transform, `PlacedPattern.box`/`.reach`) then follows the
already-moved geometry for free, the same bargain §3.2(a) strikes for every
other box-drawn kind.

`polygon`, `line` (hand and pattern) and pattern `arc` reject both keys
through the existing `_check_hand_part_keys` "key not used by this shape"
sweep (`HAND_PART_GEOMETRY_KEYS`/`PATTERN_PART_GEOMETRY_KEYS`), with an
extra reason note (`_HAND_PART_NO_ALIGNMENT_REASON`) -- the same precedent
phase B set for `shape: polygon`/`line`. `type: hands` and `type: pattern`
refuse the two keys at the element level, with a friendly pre-schema error
(`wfb.validate._check_hands_pattern_alignment`) explaining that their `at:`
is a pivot, not a box -- the schema stays closed to both keys on
`handsElement`/`patternElement`.

Every geometry test picks `px` units so the expected geometry is
hand-computable exactly, no float rounding to reason about.
"""

from __future__ import annotations

import math

import pytest

from tests.helpers import errors, find

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


def design(elements_block: str, extra: str = "") -> str:
    return BASE + extra + "\nelements:\n" + elements_block


# -- hand rectangle part: aligned in the hand's own frame ---------------------


def test_hand_rectangle_bottom_aligned_bottom_edge_on_the_axis(resolved_for):
    """The example the plan calls out: `at: {dy: 0}` +
    `vertical_align: bottom` puts the rectangle's bottom edge on the axis,
    extending from the axis towards the tip (negative dy) -- saves writing
    `dy: -length/2`.
    """
    resolved = resolved_for(design(
        """  - id: e
    type: hands
    hands: h
    at: {anchor: center}
""",
        """
hands:
  h:
    hour:
      color: palette.fg
      parts:
        - shape: rectangle
          at: {dy: 0px}
          size: {width: 4px, height: 40px}
          vertical_align: bottom
""",
    ))
    part = find(resolved, "e").hour.parts[0]
    assert part.shape == "polygon"
    xs = sorted({p[0] for p in part.points})
    ys = sorted({p[1] for p in part.points})
    assert xs == [-2, 2]
    assert ys == [-40, 0]


def test_hand_rectangle_left_top_top_left_corner_on_the_axis(resolved_for):
    resolved = resolved_for(design(
        """  - id: e
    type: hands
    hands: h
    at: {anchor: center}
""",
        """
hands:
  h:
    hour:
      color: palette.fg
      parts:
        - shape: rectangle
          at: {dx: 0px, dy: 0px}
          size: {width: 10px, height: 6px}
          align: left
          vertical_align: top
""",
    ))
    part = find(resolved, "e").hour.parts[0]
    xs = sorted({p[0] for p in part.points})
    ys = sorted({p[1] for p in part.points})
    assert xs == [0, 10]
    assert ys == [0, 6]


def test_hand_circle_aligned_centre_and_reach(resolved_for):
    resolved = resolved_for(design(
        """  - id: e
    type: hands
    hands: h
    at: {anchor: center}
""",
        """
hands:
  h:
    hour:
      color: palette.fg
      parts:
        - shape: circle
          at: {dy: 0px}
          radius: 5px
          align: right
          vertical_align: bottom
""",
    ))
    placed = find(resolved, "e")
    part = placed.hour.parts[0]
    assert part.shape == "circle"
    assert (part.x, part.y, part.radius) == (-5, -5, 5)
    assert placed.reach == pytest.approx(5 * math.sqrt(2) + 5)


def test_hand_part_default_is_byte_identical_to_no_keys_at_all(resolved_for):
    with_keys = resolved_for(design(
        """  - id: e
    type: hands
    hands: h
    at: {anchor: center}
""",
        """
hands:
  h:
    hour:
      color: palette.fg
      parts:
        - shape: rectangle
          at: {dy: -10px}
          size: {width: 4px, height: 40px}
          align: center
          vertical_align: center
""",
    ))
    without_keys = resolved_for(design(
        """  - id: e
    type: hands
    hands: h
    at: {anchor: center}
""",
        """
hands:
  h:
    hour:
      color: palette.fg
      parts:
        - shape: rectangle
          at: {dy: -10px}
          size: {width: 4px, height: 40px}
""",
    ))
    a = find(with_keys, "e").hour.parts[0]
    b = find(without_keys, "e").hour.parts[0]
    assert a.points == b.points


# -- pattern rectangle / circle part: aligned in the template frame ----------


def test_pattern_rectangle_radial_template_frame_and_box_follow(resolved_for):
    resolved = resolved_for(design(
        """  - id: p
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 1
    color: palette.fg
    parts:
      - shape: rectangle
        at: {dy: 0px}
        size: {width: 10px, height: 6px}
        vertical_align: bottom
"""
    ))
    placed = find(resolved, "p")
    part = placed.parts[0]
    xs = sorted({p[0] for p in part.points})
    ys = sorted({p[1] for p in part.points})
    assert xs == [-5, 5]
    assert ys == [-6, 0]
    # count=1, start=0deg -> the transform is the identity (sin=0, cos=1),
    # so the world box is exactly the template box offset by the centre.
    cx, cy = placed.center
    assert (placed.box.x, placed.box.y) == (cx - 5, cy - 6)
    assert (placed.box.x + placed.box.width, placed.box.y + placed.box.height) == (cx + 5, cy)


def test_pattern_circle_radial_template_frame_and_reach_follow(resolved_for):
    resolved = resolved_for(design(
        """  - id: p
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 1
    color: palette.fg
    parts:
      - shape: circle
        at: {dy: 0px}
        radius: 5px
        align: right
        vertical_align: bottom
"""
    ))
    placed = find(resolved, "p")
    part = placed.parts[0]
    assert (part.x, part.y, part.radius) == (-5, -5, 5)
    assert placed.reach == pytest.approx(5 * math.sqrt(2) + 5)


def test_pattern_rectangle_linear_template_frame_and_box_follow(resolved_for):
    resolved = resolved_for(design(
        """  - id: p
    type: pattern
    pattern: linear
    at: {anchor: center}
    count: 2
    step: {dx: 20px}
    color: palette.fg
    parts:
      - shape: rectangle
        size: {width: 10px, height: 6px}
        align: left
        vertical_align: top
"""
    ))
    placed = find(resolved, "p")
    part = placed.parts[0]
    xs = sorted({p[0] for p in part.points})
    ys = sorted({p[1] for p in part.points})
    assert xs == [0, 10]
    assert ys == [0, 6]
    cx, cy = placed.center
    # Copy 0's box starts at (cx, cy); copy 1 steps +20px in x (no rotation
    # on a linear pattern), so the drawn-ink box spans both.
    assert (placed.box.x, placed.box.y) == (cx, cy)
    assert placed.box.x + placed.box.width == cx + 10 + 20


def test_pattern_part_default_is_byte_identical_to_no_keys_at_all(resolved_for):
    with_keys = resolved_for(design(
        """  - id: p
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 1
    color: palette.fg
    parts:
      - shape: rectangle
        at: {dy: -10px}
        size: {width: 4px, height: 40px}
        align: center
        vertical_align: center
"""
    ))
    without_keys = resolved_for(design(
        """  - id: p
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 1
    color: palette.fg
    parts:
      - shape: rectangle
        at: {dy: -10px}
        size: {width: 4px, height: 40px}
"""
    ))
    a = find(with_keys, "p").parts[0]
    b = find(without_keys, "p").parts[0]
    assert a.points == b.points


# -- rejection: hand/pattern parts polygon, line, (pattern) arc -------------


HAND_POLYGON = """  - id: e
    type: hands
    hands: h
    at: {anchor: center}
"""
HAND_POLYGON_SET = """
hands:
  h:
    hour:
      color: palette.fg
      parts:
        - shape: polygon
          {extra}
          points:
            - {{dy: 6px}}
            - {{dx: -3px, dy: -10px}}
            - {{dx: 3px, dy: -10px}}
"""


def test_hand_polygon_rejects_align_with_the_no_single_at_reason(bag, write_design):
    bad = errors(design(HAND_POLYGON, HAND_POLYGON_SET.format(extra="align: left")),
                 bag, write_design)
    assert len(bad) == 1
    assert "'align' is not used by a hand 'shape: polygon' part" in bad[0].message
    notes = " ".join(bad[0].notes)
    assert "every vertex is its own position" in notes


def test_hand_polygon_rejects_both_keys_as_two_separate_errors(bag, write_design):
    bad = errors(
        design(HAND_POLYGON,
               HAND_POLYGON_SET.format(extra="align: left\n          vertical_align: top")),
        bag, write_design,
    )
    assert len(bad) == 2
    messages = [d.message for d in bad]
    assert any("'align' is not used by a hand 'shape: polygon' part" in m for m in messages)
    assert any("'vertical_align' is not used by a hand 'shape: polygon' part" in m for m in messages)


HAND_LINE_SET = """
hands:
  h:
    hour:
      color: palette.fg
      parts:
        - shape: line
          at: {{dy: 0px}}
          to: {{dy: -20px}}
          {extra}
"""


def test_hand_line_rejects_align_with_the_two_ends_reason(bag, write_design):
    bad = errors(design(HAND_POLYGON, HAND_LINE_SET.format(extra="align: left")),
                 bag, write_design)
    assert len(bad) == 1
    assert "'align' is not used by a hand 'shape: line' part" in bad[0].message
    assert any("two ends" in note for note in bad[0].notes)


def test_hand_line_rejects_vertical_align_too(bag, write_design):
    bad = errors(design(HAND_POLYGON, HAND_LINE_SET.format(extra="vertical_align: bottom")),
                 bag, write_design)
    assert len(bad) == 1
    assert "'vertical_align' is not used by a hand 'shape: line' part" in bad[0].message


PATTERN_ELEMENT = """  - id: p
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 2
    color: palette.fg
    parts:
{parts}
"""


def test_pattern_polygon_rejects_align(bag, write_design):
    parts = """      - shape: polygon
        align: left
        points:
          - {dy: 6px}
          - {dx: -3px, dy: -10px}
          - {dx: 3px, dy: -10px}
"""
    bad = errors(design(PATTERN_ELEMENT.format(parts=parts)), bag, write_design)
    assert len(bad) == 1
    assert "'align' is not used by a pattern 'shape: polygon' part" in bad[0].message
    assert any("every vertex is its own position" in note for note in bad[0].notes)


def test_pattern_line_rejects_vertical_align(bag, write_design):
    parts = """      - shape: line
        at: {dy: 0px}
        to: {dy: -20px}
        vertical_align: bottom
"""
    bad = errors(design(PATTERN_ELEMENT.format(parts=parts)), bag, write_design)
    assert len(bad) == 1
    assert "'vertical_align' is not used by a pattern 'shape: line' part" in bad[0].message
    assert any("two ends" in note for note in bad[0].notes)


def test_pattern_arc_rejects_align_with_the_own_origin_reason(bag, write_design):
    parts = """      - shape: arc
        radius: 10px
        align: left
"""
    bad = errors(design(PATTERN_ELEMENT.format(parts=parts)), bag, write_design)
    assert len(bad) == 1
    assert "'align' is not used by a pattern 'shape: arc' part" in bad[0].message
    assert any("centred on the copy's own origin" in note for note in bad[0].notes)


def test_pattern_arc_rejects_both_keys_as_two_separate_errors(bag, write_design):
    parts = """      - shape: arc
        radius: 10px
        align: left
        vertical_align: top
"""
    bad = errors(design(PATTERN_ELEMENT.format(parts=parts)), bag, write_design)
    assert len(bad) == 2


# -- rejection: type: hands / type: pattern refuse element-level alignment --


def test_hands_element_rejects_align_with_the_pivot_reason(bag, write_design):
    elements = """  - id: e
    type: hands
    hands: h
    at: {anchor: center}
    align: left
"""
    hands = """
hands:
  h:
    hour:
      color: palette.fg
      parts:
        - {shape: circle, radius: 10px}
"""
    bad = errors(design(elements, hands), bag, write_design)
    assert len(bad) == 1
    assert "'align' is not accepted on 'type: hands'" in bad[0].message
    assert "axis" in bad[0].message


def test_hands_element_rejects_both_keys_as_two_separate_errors(bag, write_design):
    elements = """  - id: e
    type: hands
    hands: h
    at: {anchor: center}
    align: left
    vertical_align: top
"""
    hands = """
hands:
  h:
    hour:
      color: palette.fg
      parts:
        - {shape: circle, radius: 10px}
"""
    bad = errors(design(elements, hands), bag, write_design)
    assert len(bad) == 2
    messages = [d.message for d in bad]
    assert any("'align' is not accepted on 'type: hands'" in m for m in messages)
    assert any("'vertical_align' is not accepted on 'type: hands'" in m for m in messages)


def test_hands_element_still_reports_an_unrelated_bad_key(bag, write_design):
    """R3: an unrelated mistake on the same element is still reported --
    the alignment refusal must not swallow the whole element's other errors.
    """
    elements = """  - id: e
    type: hands
    hands: h
    at: {anchor: center}
    align: left
    this_key_does_not_exist: true
"""
    hands = """
hands:
  h:
    hour:
      color: palette.fg
      parts:
        - {shape: circle, radius: 10px}
"""
    bad = errors(design(elements, hands), bag, write_design)
    assert len(bad) == 2
    messages = [d.message for d in bad]
    assert any("'align' is not accepted on 'type: hands'" in m for m in messages)
    assert any("this_key_does_not_exist" in m for m in messages)
    # The unrelated-key message must not also mention 'align' as unexpected
    # -- that key was already fully explained by its own error.
    unrelated = next(m for m in messages if "this_key_does_not_exist" in m)
    assert "align" not in unrelated


def test_pattern_element_rejects_vertical_align_with_the_pivot_reason(bag, write_design):
    elements = """  - id: p
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 2
    vertical_align: top
    color: palette.fg
    parts:
      - {shape: circle, radius: 10px}
"""
    bad = errors(design(elements), bag, write_design)
    assert len(bad) == 1
    assert "'vertical_align' is not accepted on 'type: pattern'" in bad[0].message
    assert "origin" in bad[0].message


def test_pattern_element_still_reports_an_unrelated_bad_key(bag, write_design):
    elements = """  - id: p
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 2
    vertical_align: top
    another_bad_key: 1
    color: palette.fg
    parts:
      - {shape: circle, radius: 10px}
"""
    bad = errors(design(elements), bag, write_design)
    assert len(bad) == 2
    messages = [d.message for d in bad]
    assert any("'vertical_align' is not accepted on 'type: pattern'" in m for m in messages)
    assert any("another_bad_key" in m for m in messages)
