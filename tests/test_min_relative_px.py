"""`min_1px:` -- the sub-pixel clamp, opt-in (plan 08).

The user's original ask (`%`/`%r` scale per device, so a hairline authored as
e.g. `thickness: 0.5%r` or `radius: 0.3%r` can resolve to 0.6px on one screen
and 0.4px on another -- one draws and the other vanishes once `round()` sends
it to 0) is unchanged. What changed after the first cut of this feature
(`d55363c`, which made the clamp unconditional) is that the user asked for an
opt-in switch, "globally for the whole watchface like `antialias:`, or per
group, per item, etc.", with overrides both ways at every level. This file
now tests that switch, not just the arithmetic it gates:

- `wfb.units.at_least_one_px(length, value, enabled)` -- clamps a nonzero
  `%`/`%r` result up to 1px, sign preserved, only when `enabled`.
- `wfb.units.Box.rounded(min_1px=...)` -- the round-half-to-even degenerate
  case correction, also gated.
- `wfb.layout.Resolver._extent`/`._hand_extent` -- the two choke points that
  apply the clamp and, when it is off, record a `wfb.layout.SubPixelLength`
  for the (separately owned) `sub-pixel-length` lint to read.
- `wfb.ir`'s inheritance: `Face.min_1px` -> `group`/`shape`/`progress`/
  `graph`/`hands`/`pattern`'s `resolved_min_1px` -> a hand/pattern part's own
  `min_1px` (computed per element instance at layout time, never stamped
  into the IR -- see `wfb.ir.HandPart.min_1px`'s docstring for why).

Every guard below was watched fail before it was believed (this file's
predecessor already asserted the *unconditional* rule; reworking each of its
cases to run once with the switch on and once off, and watching the "off"
half fail against the old unconditional code, is what stands in for driving
each one red here).
"""

from __future__ import annotations

import pytest

from tests.helpers import find
from wfb.build import load
from wfb.emit.resources import bake_fonts
from wfb.layout import PlacedHands, PlacedPattern, resolve
from wfb.units import Box

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

#: 0.3%r of this device's 130px minor radius is 0.39px -- bare `round()`
#: gives 0, and it is nonzero, so `at_least_one_px` clamps it to 1 when
#: enabled. Used everywhere below a "sub-pixel relative length" is needed.
HAIRLINE = "0.3%r"


def design(elements_block: str, *, face_min_1px: bool | None = None,
           hands_block: str = "") -> str:
    head = BASE
    if face_min_1px is not None:
        head += f"min_1px: {'true' if face_min_1px else 'false'}\n"
    return head + hands_block + "\nelements:\n" + elements_block


@pytest.fixture
def resolved_for(write_design, bag, db):
    """Build and layout-resolve a one-off design for `fenix8solar47mm`
    (260x260, minor radius 130) through the real pipeline (loader, desugar,
    schema, IR, layout), the same stages `wfb.build.load` runs minus the
    toolchain."""

    def _resolve(elements_block: str, **kwargs):
        face = load(write_design(design(elements_block, **kwargs)), bag)
        assert face is not None, bag.render()
        device = db.get("fenix8solar47mm")
        return resolve(face, device, bake_fonts(face, device))

    return _resolve


def sub_pixel_keys(resolved, owner: str) -> set[str]:
    """The set of `SubPixelLength.key`s recorded against ``owner`` -- the
    observable that proves a `_extent`/`_hand_extent` call site fired at
    all, independent of whether the *final* pixel value the clamp would
    have produced happens to be visible downstream (it is not, for
    `thickness:`/`bar_width:`, which a separate, unconditional `max(1, ...)`
    pen-width floor already masks -- see the "already floored" tests
    below)."""
    return {sp.key for sp in resolved.sub_pixel if sp.owner == owner}


def circle(id_: str, indent: int = 2, *, min_1px: bool | None = None,
           radius: str = HAIRLINE) -> str:
    """A minimal `shape: circle`, indented to sit at a list-item level
    ``indent`` spaces deep (2 = top-level `elements:`, 6 = one `group`'s
    `children:` deep, 10 = two deep, ...) -- lets the same helper build both
    a flat design and one nested inside `group()` below."""
    pad = " " * indent
    lines = [
        f"{pad}- id: {id_}",
        f"{pad}  type: shape",
        f"{pad}  shape: circle",
        f"{pad}  at: {{anchor: center}}",
        f"{pad}  radius: {radius}",
        f"{pad}  color: palette.fg",
    ]
    if min_1px is not None:
        lines.append(f"{pad}  min_1px: {'true' if min_1px else 'false'}")
    return "\n".join(lines) + "\n"


def group(id_: str, children_block: str, indent: int = 2, *,
          min_1px: bool | None = None) -> str:
    """A `type: group` wrapping ``children_block`` (already indented to
    ``indent + 4``, e.g. via `circle(..., indent=indent + 4)` or a nested
    `group(..., indent=indent + 4)`)."""
    pad = " " * indent
    lines = [
        f"{pad}- id: {id_}",
        f"{pad}  type: group",
        f"{pad}  at: {{anchor: center}}",
        f"{pad}  size: {{width: 200px, height: 200px}}",
    ]
    if min_1px is not None:
        lines.append(f"{pad}  min_1px: {'true' if min_1px else 'false'}")
    lines.append(f"{pad}  children:")
    return "\n".join(lines) + "\n" + children_block


# ============================================================================
# The switch's own mechanics (§5 tests 1-5) -- a single hairline circle
# radius stands in for all of them; §2.1 scope coverage (every in-scope key,
# every out-of-scope key) is proven separately further down.
# ============================================================================


def test_default_is_off_when_min_1px_is_never_mentioned(resolved_for):
    """§5 test 1: a face that writes `min_1px:` nowhere at all -- not even
    `false` -- resolves a sub-pixel relative extent to the pre-feature
    value.  This is also what every design written before this feature
    existed keeps doing."""
    resolved = resolved_for(circle("dot"))
    assert find(resolved, "dot").radius == 0
    assert sub_pixel_keys(resolved, "dot") == {"radius"}


def test_face_level_turns_it_on(resolved_for):
    """§5 test 2 (face)."""
    resolved = resolved_for(circle("dot"), face_min_1px=True)
    assert find(resolved, "dot").radius == 1
    assert sub_pixel_keys(resolved, "dot") == set()


def test_group_level_turns_it_on(resolved_for):
    """§5 test 2 (group): the face default stays off, the group's own
    `min_1px: true` is what reaches the leaf."""
    block = group("g", circle("dot", indent=6), min_1px=True)
    resolved = resolved_for(block)
    assert find(resolved, "dot").radius == 1


def test_element_level_turns_it_on(resolved_for):
    """§5 test 2 (element)."""
    resolved = resolved_for(circle("dot", min_1px=True))
    assert find(resolved, "dot").radius == 1


def test_part_level_turns_it_on(resolved_for):
    """§5 test 2 (part): the pattern element itself declares nothing, only
    this one part does."""
    resolved = resolved_for(f"""  - id: pat
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1
    color: palette.fg
    parts:
      - {{shape: circle, radius: {HAIRLINE}, min_1px: true}}
""")
    placed = find(resolved, "pat")
    assert isinstance(placed, PlacedPattern)
    assert placed.parts[0].radius == 1


def test_group_level_turns_it_back_off_under_a_true_face(resolved_for):
    """§5 test 3 (group under a true face) -- "the easy one to leave
    untested": `false` under a `true` ancestor is just as real as the other
    way around."""
    block = group("g", circle("dot", indent=6, min_1px=False), min_1px=None)
    resolved = resolved_for(block, face_min_1px=True)
    assert find(resolved, "dot").radius == 0


def test_element_level_turns_it_back_off_under_a_true_face(resolved_for):
    """§5 test 3 (element under a true face)."""
    resolved = resolved_for(circle("dot", min_1px=False), face_min_1px=True)
    assert find(resolved, "dot").radius == 0


def test_element_level_turns_it_back_off_under_a_true_group(resolved_for):
    """§5 test 3 (element under a true group)."""
    block = group("g", circle("dot", indent=6, min_1px=False), min_1px=True)
    resolved = resolved_for(block)
    assert find(resolved, "dot").radius == 0


def test_part_level_turns_it_back_off_under_a_true_pattern(resolved_for):
    """§5 test 3 (part under a true element)."""
    resolved = resolved_for(f"""  - id: pat
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1
    color: palette.fg
    min_1px: true
    parts:
      - {{shape: circle, radius: {HAIRLINE}, min_1px: false}}
""")
    placed = find(resolved, "pat")
    assert placed.parts[0].radius == 0


def test_nearest_declaration_wins_three_deep_middle_flips(resolved_for):
    """§5 test 4: outer group `true`, middle group `false`, the leaf
    declares nothing -- must land on the *middle* group's `false` (the
    nearest declaration), not the outer `true` two levels up, and the two
    must not combine into anything else (it is an override, not a
    conjunction -- `wfb.ir._resolve_inherited_flag`'s docstring)."""
    leaf = circle("leaf", indent=10)
    middle = group("middle", leaf, indent=6, min_1px=False)
    outer = group("outer", middle, indent=2, min_1px=True)
    resolved = resolved_for(outer)
    assert find(resolved, "leaf").radius == 0


def test_two_hands_elements_sharing_one_set_resolve_min_1px_independently(resolved_for):
    """§5 test 5: the case that makes a `resolved_` field on `HandPart`
    wrong (`wfb.ir.HandPart.min_1px`'s own docstring). One `hands:` set,
    placed by two `type: hands` elements with opposite `min_1px`, must
    resolve the shared part's radius differently for each placement --
    proving the effective value is computed per element instance at layout
    time, not stamped once onto the part in the IR."""
    hands_block = f"""
hands:
  shared:
    hour:
      color: palette.fg
      parts:
        - {{shape: circle, radius: {HAIRLINE}}}
"""
    resolved = resolved_for(f"""  - id: h1
    type: hands
    hands: shared
    at: {{anchor: center}}
    min_1px: true
  - id: h2
    type: hands
    hands: shared
    at: {{anchor: center}}
    min_1px: false
""", hands_block=hands_block)
    h1 = find(resolved, "h1")
    h2 = find(resolved, "h2")
    assert isinstance(h1, PlacedHands) and isinstance(h2, PlacedHands)
    assert h1.hour.parts[0].radius == 1
    assert h2.hour.parts[0].radius == 0


# ============================================================================
# §5 test 6: every in-scope key of §2.1 is clamped when on, and recorded as
# a `SubPixelLength` when off -- named individually, per kind, so a missed
# `_extent`/`_hand_extent` call site fails loudly rather than silently
# reporting the wrong key (or none at all).
#
# `thickness:`/`bar_width:` are checked only through `sub_pixel_keys`, not
# through the final resolved pixel value: every kind that accepts them
# already runs the result through a separate, unconditional `max(1, ...)`
# pen-width floor (a 0px pen cannot draw at all, regardless of relative
# units), so the *final* value is 1 whether `min_1px` is on or off -- the
# switch only changes whether the raw, pre-floor extent gets recorded.
# `size:`/`radius:` have no such downstream floor, so those are checked both
# ways.
# ============================================================================


def test_group_size_is_covered(resolved_for):
    block = group("g", circle("leaf", indent=6, radius="1px"),
                  min_1px=None)
    block = block.replace("size: {width: 200px, height: 200px}",
                          f"size: {{width: {HAIRLINE}, height: {HAIRLINE}}}")
    off = resolved_for(block)
    on = resolved_for(block.replace("    type: group\n", "    type: group\n    min_1px: true\n"))
    assert sub_pixel_keys(off, "g") == {"size.width", "size.height"}
    assert sub_pixel_keys(on, "g") == set()
    assert (find(off, "g").box.width, find(off, "g").box.height) == (0, 0)
    assert (find(on, "g").box.width, find(on, "g").box.height) == (1, 1)


def test_shape_rectangle_size_is_covered(resolved_for):
    def make(min_1px: bool) -> str:
        return f"""  - id: r
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: {HAIRLINE}, height: 10px}}
    color: palette.fg
    min_1px: {'true' if min_1px else 'false'}
"""
    off = resolved_for(make(False))
    on = resolved_for(make(True))
    assert sub_pixel_keys(off, "r") == {"size.width"}
    assert find(off, "r").box.width == 0
    assert sub_pixel_keys(on, "r") == set()
    assert find(on, "r").box.width == 1


def test_shape_circle_radius_is_covered(resolved_for):
    off = resolved_for(circle("dot"))
    on = resolved_for(circle("dot", min_1px=True))
    assert sub_pixel_keys(off, "dot") == {"radius"}
    assert find(off, "dot").radius == 0
    assert sub_pixel_keys(on, "dot") == set()
    assert find(on, "dot").radius == 1


def test_shape_arc_radius_and_thickness_are_covered(resolved_for):
    def make(min_1px: bool) -> str:
        return f"""  - id: ring
    type: shape
    shape: arc
    at: {{anchor: center}}
    radius: {HAIRLINE}
    thickness: {HAIRLINE}
    color: palette.fg
    min_1px: {'true' if min_1px else 'false'}
"""
    off = resolved_for(make(False))
    on = resolved_for(make(True))
    assert sub_pixel_keys(off, "ring") == {"radius", "thickness"}
    assert find(off, "ring").radius == 0
    assert find(off, "ring").thickness == 1  # already floored, see module docstring
    assert sub_pixel_keys(on, "ring") == set()
    assert find(on, "ring").radius == 1
    assert find(on, "ring").thickness == 1


def test_shape_line_thickness_is_already_floored_by_a_separate_rule(resolved_for):
    def make(min_1px: bool) -> str:
        return f"""  - id: hair
    type: shape
    shape: line
    at: {{anchor: center}}
    to: {{anchor: center, dx: 50px}}
    thickness: {HAIRLINE}
    color: palette.fg
    min_1px: {'true' if min_1px else 'false'}
"""
    off = resolved_for(make(False))
    on = resolved_for(make(True))
    assert sub_pixel_keys(off, "hair") == {"thickness"}
    assert find(off, "hair").thickness == 1
    assert sub_pixel_keys(on, "hair") == set()
    assert find(on, "hair").thickness == 1


def test_progress_arc_radius_and_thickness_are_covered(resolved_for):
    def make(min_1px: bool) -> str:
        return f"""  - id: ring
    type: progress
    style: arc
    value: 3
    max: 10
    radius: {HAIRLINE}
    thickness: {HAIRLINE}
    start_angle: 0
    sweep: 300
    color: palette.fg
    min_1px: {'true' if min_1px else 'false'}
"""
    off = resolved_for(make(False))
    on = resolved_for(make(True))
    assert sub_pixel_keys(off, "ring") == {"radius", "thickness"}
    assert find(off, "ring").radius == 0
    assert find(off, "ring").thickness == 1
    assert sub_pixel_keys(on, "ring") == set()
    assert find(on, "ring").radius == 1


def test_progress_bar_size_is_covered(resolved_for):
    def make(min_1px: bool) -> str:
        return f"""  - id: bar
    type: progress
    style: bar
    value: 3
    max: 10
    size: {{width: {HAIRLINE}, height: 10px}}
    color: palette.fg
    min_1px: {'true' if min_1px else 'false'}
"""
    off = resolved_for(make(False))
    on = resolved_for(make(True))
    assert sub_pixel_keys(off, "bar") == {"size.width"}
    assert find(off, "bar").box.width == 0
    assert sub_pixel_keys(on, "bar") == set()
    assert find(on, "bar").box.width == 1


def test_graph_size_and_thickness_are_covered(resolved_for):
    """`style: line` reads `thickness:`, not `bar_width:`."""
    def make(min_1px: bool) -> str:
        return f"""  - id: g
    type: graph
    series: heart_rate
    range: 30m
    style: line
    size: {{width: {HAIRLINE}, height: 40px}}
    thickness: {HAIRLINE}
    color: palette.fg
    min_1px: {'true' if min_1px else 'false'}
"""
    off = resolved_for(make(False))
    on = resolved_for(make(True))
    assert sub_pixel_keys(off, "g") == {"size.width", "thickness"}
    assert find(off, "g").size[0] == 0
    assert find(off, "g").thickness == 1  # already floored
    assert sub_pixel_keys(on, "g") == set()
    assert find(on, "g").size[0] == 1


def test_graph_bar_width_is_covered(resolved_for):
    """`style: bars` reads `bar_width:`, not `thickness:`."""
    def make(min_1px: bool) -> str:
        return f"""  - id: g
    type: graph
    series: heart_rate
    range: 30m
    style: bars
    size: {{width: 100px, height: 40px}}
    bar_width: {HAIRLINE}
    color: palette.fg
    min_1px: {'true' if min_1px else 'false'}
"""
    off = resolved_for(make(False))
    on = resolved_for(make(True))
    assert sub_pixel_keys(off, "g") == {"bar_width"}
    assert find(off, "g").bar_width == 1  # already floored
    assert sub_pixel_keys(on, "g") == set()


def test_pattern_rectangle_part_size_is_covered(resolved_for):
    """A rectangle part's corners round with `_round_away`, so the clamped
    1.0px width folds into a 2px-wide polygon (`-1..1`) rather than exactly
    1 -- this only proves it is no longer 0, the same distinction the
    original (unconditional) version of this test made."""
    def make(min_1px: bool) -> str:
        return f"""  - id: pat
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1
    color: palette.fg
    parts:
      - {{shape: rectangle, size: {{width: {HAIRLINE}, height: 4px}}, min_1px: {'true' if min_1px else 'false'}}}
"""
    off_resolved = resolved_for(make(False))
    on_resolved = resolved_for(make(True))
    off_xs = [x for x, _ in find(off_resolved, "pat").parts[0].points]
    on_xs = [x for x, _ in find(on_resolved, "pat").parts[0].points]
    assert max(off_xs) - min(off_xs) == 0
    assert max(on_xs) - min(on_xs) > 0
    assert sub_pixel_keys(off_resolved, "pat.parts[0]") == {"size.width"}
    assert sub_pixel_keys(on_resolved, "pat.parts[0]") == set()


def test_pattern_line_part_thickness_is_already_floored(resolved_for):
    def make(min_1px: bool) -> str:
        return f"""  - id: pat
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1
    color: palette.fg
    parts:
      - {{shape: line, to: {{dx: 10px}}, thickness: {HAIRLINE}, min_1px: {'true' if min_1px else 'false'}}}
"""
    off_resolved = resolved_for(make(False))
    on_resolved = resolved_for(make(True))
    assert find(off_resolved, "pat").parts[0].thickness == 1
    assert find(on_resolved, "pat").parts[0].thickness == 1
    assert sub_pixel_keys(off_resolved, "pat.parts[0]") == {"thickness"}
    assert sub_pixel_keys(on_resolved, "pat.parts[0]") == set()


def test_pattern_circle_part_radius_and_thickness_are_covered(resolved_for):
    def make(min_1px: bool) -> str:
        return f"""  - id: pat
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1
    color: palette.fg
    parts:
      - {{shape: circle, radius: {HAIRLINE}, filled: false, thickness: {HAIRLINE}, min_1px: {'true' if min_1px else 'false'}}}
"""
    off_resolved = resolved_for(make(False))
    on_resolved = resolved_for(make(True))
    assert find(off_resolved, "pat").parts[0].radius == 0
    assert find(off_resolved, "pat").parts[0].thickness == 1  # already floored
    assert find(on_resolved, "pat").parts[0].radius == 1
    assert sub_pixel_keys(off_resolved, "pat.parts[0]") == {"radius", "thickness"}
    assert sub_pixel_keys(on_resolved, "pat.parts[0]") == set()


def test_pattern_arc_part_radius_and_thickness_are_covered(resolved_for):
    def make(min_1px: bool) -> str:
        return f"""  - id: pat
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1
    color: palette.fg
    parts:
      - {{shape: arc, radius: {HAIRLINE}, thickness: {HAIRLINE}, min_1px: {'true' if min_1px else 'false'}}}
"""
    off_resolved = resolved_for(make(False))
    on_resolved = resolved_for(make(True))
    assert find(off_resolved, "pat").parts[0].radius == 0
    assert find(on_resolved, "pat").parts[0].radius == 1
    assert sub_pixel_keys(off_resolved, "pat.parts[0]") == {"radius", "thickness"}
    assert sub_pixel_keys(on_resolved, "pat.parts[0]") == set()


def test_hand_rectangle_part_size_is_covered(resolved_for):
    hands_block = f"""
hands:
  h:
    hour:
      color: palette.fg
      parts:
        - {{shape: rectangle, size: {{width: {HAIRLINE}, height: 4px}}}}
"""

    def elements(min_1px: bool) -> str:
        return f"""  - id: hd
    type: hands
    hands: h
    at: {{anchor: center}}
    min_1px: {'true' if min_1px else 'false'}
"""
    off = find(resolved_for(elements(False), hands_block=hands_block), "hd")
    on = find(resolved_for(elements(True), hands_block=hands_block), "hd")
    off_xs = [x for x, _ in off.hour.parts[0].points]
    on_xs = [x for x, _ in on.hour.parts[0].points]
    assert max(off_xs) - min(off_xs) == 0
    assert max(on_xs) - min(on_xs) > 0


def test_hand_circle_part_radius_is_covered(resolved_for):
    hands_block = f"""
hands:
  h:
    hour:
      color: palette.fg
      parts:
        - {{shape: circle, radius: {HAIRLINE}}}
"""

    def elements(min_1px: bool) -> str:
        return f"""  - id: hd
    type: hands
    hands: h
    at: {{anchor: center}}
    min_1px: {'true' if min_1px else 'false'}
"""
    off = find(resolved_for(elements(False), hands_block=hands_block), "hd")
    on = find(resolved_for(elements(True), hands_block=hands_block), "hd")
    assert off.hour.parts[0].radius == 0
    assert on.hour.parts[0].radius == 1


# ============================================================================
# §5 test 7: every out-of-scope key of §2.1 is *not* clamped even when
# `min_1px` is on -- a position is not an extent, `corner_radius:` is not a
# size, `px`/`pt` lengths and an exact `0` are already exactly what the
# author wrote, and a font size (icon/complication_slot) floors on its own
# separate path with no switch and no lint.
# ============================================================================


def test_at_offset_is_never_clamped(resolved_for):
    def make(min_1px: bool) -> str:
        return f"""  - id: dot
    type: shape
    shape: circle
    at: {{anchor: center, dx: {HAIRLINE}}}
    radius: 5px
    color: palette.fg
    min_1px: {'true' if min_1px else 'false'}
"""
    off_resolved = resolved_for(make(False))
    on_resolved = resolved_for(make(True))
    # 130 (screen centre) + 0.39 (0.3%r) rounds to 130 either way -- `at:`
    # never reaches `_extent`, so the switch cannot touch it.
    assert find(off_resolved, "dot").center == find(on_resolved, "dot").center == (130, 130)
    # `radius: 5px` is not relative at all, so nothing here is "sub-pixel" --
    # this also proves `at:`'s own relative offset was never recorded either
    # (an `at`/`dx` key never appears in `sub_pixel_keys` at all, since
    # `_point` stays on `_len`, never `_extent`).
    assert sub_pixel_keys(off_resolved, "dot") == set()


def test_to_offset_is_never_clamped(resolved_for):
    def make(min_1px: bool) -> str:
        return f"""  - id: hair
    type: shape
    shape: line
    at: {{anchor: center}}
    to: {{anchor: center, dx: {HAIRLINE}}}
    thickness: 2px
    color: palette.fg
    min_1px: {'true' if min_1px else 'false'}
"""
    off = find(resolved_for(make(False)), "hair")
    on = find(resolved_for(make(True)), "hair")
    assert off.end == on.end == (130, 130)


def test_polygon_points_are_never_clamped(resolved_for):
    """A polygon's own bounding box comes straight from its resolved
    vertices (`wfb.kinds.shape.ShapeKind.resolve`'s polygon branch never calls
    `_extent`), so a hairline triangle's width must be identical whether
    `min_1px` is on or off -- unlike every in-scope shape's own `size:` or
    `radius:` above."""
    def make(min_1px: bool) -> str:
        return f"""  - id: poly
    type: shape
    shape: polygon
    min_1px: {'true' if min_1px else 'false'}
    points:
      - {{anchor: center}}
      - {{anchor: center, dx: {HAIRLINE}}}
      - {{anchor: center, dy: 3%r}}
    color: palette.fg
"""
    off = find(resolved_for(make(False)), "poly")
    on = find(resolved_for(make(True)), "poly")
    assert off.box.width == on.box.width


def test_linear_pattern_step_is_never_clamped(resolved_for):
    def make(min_1px: bool) -> str:
        return f"""  - id: pat
    type: pattern
    pattern: linear
    at: {{anchor: center}}
    count: 2
    step: {{dx: {HAIRLINE}}}
    color: palette.fg
    min_1px: {'true' if min_1px else 'false'}
    parts:
      - {{shape: circle, radius: 3px}}
"""
    off = find(resolved_for(make(False)), "pat")
    on = find(resolved_for(make(True)), "pat")
    # A 0.39px step rounds to 0 -- both copies land on the same spot --
    # regardless of `min_1px`, because a linear pattern's `step:` stays on
    # `_len`, never `_extent`.
    assert off.dx == on.dx == 0


def test_corner_radius_is_never_clamped(resolved_for):
    def make(min_1px: bool) -> str:
        return f"""  - id: r
    type: shape
    shape: rounded_rectangle
    at: {{anchor: center}}
    size: {{width: 50px, height: 50px}}
    corner_radius: {HAIRLINE}
    color: palette.fg
    min_1px: {'true' if min_1px else 'false'}
"""
    off = find(resolved_for(make(False)), "r")
    on = find(resolved_for(make(True)), "r")
    assert off.corner_radius == on.corner_radius == 0


def test_px_lengths_are_never_clamped(resolved_for):
    """Documents the scope: `radius: 0.3px` still resolves to 0 even with
    `min_1px: true` -- `px` is already exactly what the author wrote."""
    def make(min_1px: bool) -> str:
        return f"""  - id: dot
    type: shape
    shape: circle
    at: {{anchor: center}}
    radius: 0.3px
    color: palette.fg
    min_1px: {'true' if min_1px else 'false'}
"""
    off_resolved = resolved_for(make(False))
    on_resolved = resolved_for(make(True))
    assert find(off_resolved, "dot").radius == find(on_resolved, "dot").radius == 0
    assert sub_pixel_keys(off_resolved, "dot") == set()  # px is never "sub-pixel"


def test_pt_lengths_are_never_clamped():
    """`pt` is not `%`/`%r`, so `is_sub_pixel_length`/`at_least_one_px` must
    leave it alone regardless of `min_1px` -- checked directly against
    `wfb.units` rather than through a real design: every in-scope kind's own
    `_extent`/`._hand_extent` call site leaves `font_px` at its default
    `None` (no group/shape/progress/graph/hand/pattern geometry key ever has
    a font in scope to resolve a `pt` length against), so a `thickness:
    0.3pt` on one of them would raise `Length.resolve`'s own "pt units need
    a reference font" error before ever reaching the clamp -- a real, but
    separate and pre-existing, gap this plan does not touch. Testing the
    scope boundary directly, at `is_sub_pixel_length`, is what proves the
    actual claim without depending on that unrelated crash.
    """
    from wfb.units import Length, at_least_one_px, is_sub_pixel_length

    length = Length.parse("0.3pt", what="thickness")
    value = 0.39  # a plausible resolved value, well under 1px
    assert is_sub_pixel_length(length, value) is False
    assert at_least_one_px(length, value, True) == value


def test_exactly_zero_percent_stays_zero(resolved_for):
    """The author asked for nothing; `0%`/`0%r` is not "nonzero", so the
    clamp must not turn it into 1 even with `min_1px: true`."""
    def make(min_1px: bool) -> str:
        return f"""  - id: gone
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 0%, height: 10px}}
    color: palette.fg
    min_1px: {'true' if min_1px else 'false'}
"""
    off_resolved = resolved_for(make(False))
    on_resolved = resolved_for(make(True))
    assert find(off_resolved, "gone").box.width == find(on_resolved, "gone").box.width == 0
    assert sub_pixel_keys(off_resolved, "gone") == set()  # exactly 0 is never "sub-pixel"


def test_a_relative_value_already_1px_or_more_is_unchanged(resolved_for):
    """`radius: 2%r` of a 130px minor radius is 2.6px -- `round(2.6) == 3`,
    the ordinary rounding rule, untouched by the clamp either way."""
    off_resolved = resolved_for(circle("dot", radius="2%r"))
    on_resolved = resolved_for(circle("dot", radius="2%r", min_1px=True))
    assert find(off_resolved, "dot").radius == find(on_resolved, "dot").radius == 3
    assert sub_pixel_keys(off_resolved, "dot") == set()  # >= 1px is never "sub-pixel"


def test_a_pattern_rectangle_part_at_or_above_1px_is_unchanged(resolved_for):
    """`width: 4%r` (5.2px, half-width 2.6px) never enters the clamp
    (`abs(value) >= 1`), so its resolved extent must match the pre-existing
    `_round_away` math exactly, `min_1px` on or off: half-width 2.6 ->
    corners at -3 and 3."""
    def make(min_1px: bool) -> str:
        return f"""  - id: pat
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1
    color: palette.fg
    parts:
      - {{shape: rectangle, size: {{width: 4%r, height: 4px}}, min_1px: {'true' if min_1px else 'false'}}}
"""
    for min_1px in (False, True):
        resolved = resolved_for(make(min_1px))
        placed = find(resolved, "pat")
        xs = [x for x, _ in placed.parts[0].points]
        assert min(xs) == -3
        assert max(xs) == 3


def test_icon_size_floors_on_its_own_path_with_no_switch_and_no_lint(resolved_for):
    """`icon`/`complication_slot`/`text` accept no `min_1px:` at all (schema:
    see `test_min_1px_is_rejected_on_icon_as_an_unknown_key` below) because a
    font size already floors at 1px on `wfb.units.pixel_size`'s own path --
    checked here with a hairline `size:` and no `min_1px:` anywhere."""
    resolved = resolved_for(f"""  - id: ic
    type: icon
    icon: heart
    size: {HAIRLINE}
    at: {{anchor: center}}
    color: palette.fg
""")
    icon = find(resolved, "ic")
    assert icon.size == 1
    assert resolved.sub_pixel == []


def test_min_1px_is_rejected_on_icon_as_an_unknown_key(write_design, bag):
    text = design("""  - id: ic
    type: icon
    icon: heart
    size: 20%r
    at: {anchor: center}
    color: palette.fg
    min_1px: true
""")
    face = load(write_design(text), bag)
    assert face is None
    assert bag.errors, "schema should reject min_1px as an unknown key on icon"


def test_min_1px_is_rejected_on_text_as_an_unknown_key(write_design, bag):
    text = design("""  - id: t
    type: text
    text: "12:00"
    font: FONT_MEDIUM
    color: palette.fg
    min_1px: true
""")
    face = load(write_design(text), bag)
    assert face is None
    assert bag.errors, "schema should reject min_1px as an unknown key on text"


# ============================================================================
# `Box.rounded()`'s degenerate round-half-to-even tie -- now gated (§3.3).
# ============================================================================


def test_box_rounded_default_leaves_the_tie_unfixed():
    """The default (`min_1px=False`) is today's pre-feature arithmetic,
    exactly: a box whose float width is exactly 1.0, centred on an even
    integer coordinate, rounds to width 0 -- the correction does not run
    unless asked."""
    box = Box(129.5, 0, 1.0, 1.0)
    assert box.rounded().width == 0


def test_box_rounded_fixes_the_1px_wide_even_centred_tie_when_asked():
    """Same box, with `min_1px=True`: this is the case `at_least_one_px`
    clamps a length *to* (1.0), so `Box.rounded()` must not immediately
    undo it when the switch that produced the 1.0 is on."""
    box = Box(129.5, 0, 1.0, 1.0)
    assert box.rounded(min_1px=True).width == 1


def test_box_rounded_other_ties_are_unchanged_either_way():
    """Narrow, deliberate fix: a *different* pre-existing round-half-to-even
    surprise (a 25px-wide box at a half-integer left edge coming out 24px)
    is left exactly as it was, `min_1px` on or off -- this pins today's
    actual value so the fix above cannot be read as touching this case too."""
    box = Box(117.5, 0, 25, 1)
    assert box.rounded().width == 24
    assert box.rounded(min_1px=True).width == 24


def test_the_element_owns_again_once_its_parts_are_resolved(write_design, bag, db):
    """A part narrows the `SubPixelLength` owner to `<id>.parts[<i>]` only
    while it resolves; a length resolved after the parts (as `_aod_extent`
    is in hands and patterns) belongs to the element again, not to
    whichever part came last."""
    from wfb.layout import Resolver, _Owner

    face = load(write_design(design(f"""  - id: pat
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1
    color: palette.fg
    parts:
      - {{shape: circle, radius: {HAIRLINE}}}
""")), bag)
    assert face is not None, bag.render()
    element = face.elements[0]
    resolver = Resolver(face, db.get("fenix8solar47mm"), {})
    with resolver._owned_by(_Owner(element.id, element.span, element)):
        resolver._resolve_parts(element.parts, element.id, min_1px=False)
        resolver._record_sub_pixel("radius", element.parts[0].radius, 0.39)
    assert [sp.owner for sp in resolver.sub_pixel] == ["pat.parts[0]", "pat"]
    assert resolver._owner is None
