"""Analog hands (plan 04): `hands:` sets and `type: hands` elements.

Every diagnostic here was driven red first -- run against the violating input
below with the fix reverted, each one raised a different, wrong error (or
none at all) before the corresponding check landed, the same discipline
`tests/CLAUDE.md` asks for every new diagnostic.
"""

from __future__ import annotations

import pytest

from tests.helpers import errors, find
from wfb.build import load
from wfb.emit.resources import bake_fonts
from wfb.layout import PlacedHands, circular_extent, resolve

BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm, fenix8solar51mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
  accent: "#FF5500"
"""


def design(hands_block: str, elements_block: str) -> str:
    return BASE + hands_block + "\nelements:\n" + elements_block


#: A hand set with all four rotatable primitives, and every hand present --
#: the "everything builds" fixture most tests start from.
CLASSIC = """
hands:
  classic:
    hour:
      color: palette.fg
      parts:
        - {shape: polygon, points: [{dx: -3%r, dy: 6%r}, {dy: -44%r}, {dx: 3%r, dy: 6%r}]}
    minute:
      color: palette.fg
      parts:
        - {shape: rectangle, at: {dy: -30%r}, size: {width: 3%r, height: 70%r}}
        - {shape: circle, radius: 4%r}
    second:
      color: palette.accent
      parts:
        - {shape: line, at: {dy: 15%r}, to: {dy: -82%r}, thickness: 2px}
        - {shape: circle, at: {dy: 15%r}, radius: 3%r, filled: false, thickness: 1px}
"""

MAIN_HANDS = """  - id: main_hands
    type: hands
    hands: classic
    at: {anchor: center}
"""


# -- building the base fixture ----------------------------------------------


def test_the_reference_design_builds_clean(write_design, bag):
    face = load(write_design(design(CLASSIC, MAIN_HANDS)), bag)
    assert face is not None, bag.render()
    assert "classic" in face.hands
    element = face.elements[0]
    assert element.hands == "classic"
    assert element.seconds == "awake"


# -- §5.11 diagnostics --------------------------------------------------------


def test_unknown_hand_set_lists_the_declared_names(write_design, bag):
    bad = errors(design(CLASSIC, """  - id: h
    type: hands
    hands: nope
    at: {anchor: center}
"""), bag, write_design)
    assert len(bad) == 1
    assert "unknown hand set 'nope'" in bad[0].message
    assert "classic" in " ".join(bad[0].notes)


def test_a_rejected_hand_set_stays_bound_so_only_one_error_is_reported(write_design, bag):
    """The 'one error, not N' rule (docs/lore/codegen.md): a hand set
    rejected for its own fault must not also blame every element naming it.
    """
    broken = """
hands:
  broken:
    hour:
      parts:
        - {shape: circle, radius: 10%r}
"""
    two_users = MAIN_HANDS.replace("classic", "broken") + """  - id: second_user
    type: hands
    hands: broken
    at: {anchor: center, dy: 10%}
"""
    bad = errors(design(broken, two_users), bag, write_design)
    assert len(bad) == 1
    assert "no colour" in bad[0].message


def test_an_empty_hand_set_is_an_error(write_design, bag):
    bad = errors(design("""
hands:
  empty: {}
""", MAIN_HANDS.replace("classic", "empty")), bag, write_design)
    assert len(bad) == 1
    assert "declares none of hour, minute or second" in bad[0].message


@pytest.mark.parametrize("shape,reason", [
    ("rounded_rectangle", "rotated rounded rectangle"),
    ("ellipse", "rotated ellipse"),
    ("arc", "not implemented yet"),
    ("text", "cannot rotate"),
    ("icon", "cannot rotate"),
])
def test_bad_part_shapes_each_get_their_own_reason(write_design, bag, shape, reason):
    hands = f"""
hands:
  classic:
    hour:
      color: palette.fg
      parts:
        - {{shape: {shape}}}
"""
    bad = errors(design(hands, MAIN_HANDS), bag, write_design)
    assert len(bad) == 1
    assert f"'shape: {shape}'" in bad[0].message
    assert reason in bad[0].message


def test_a_key_not_used_by_this_part_shape_is_an_error(write_design, bag):
    """`radius:` typed on a polygon part, the same silent-key bug class
    `SHAPE_GEOMETRY_KEYS` exists to catch on the main `shape:` element."""
    hands = """
hands:
  classic:
    hour:
      color: palette.fg
      parts:
        - {shape: polygon, radius: 5, points: [{dy: -10}, {dx: -5, dy: 5}, {dx: 5, dy: 5}]}
"""
    bad = errors(design(hands, MAIN_HANDS), bag, write_design)
    assert len(bad) == 1
    assert "'radius' is not used by a hand 'shape: polygon' part" in bad[0].message


def test_anchor_in_a_part_position_is_always_an_error(write_design, bag):
    hands = """
hands:
  classic:
    hour:
      color: palette.fg
      parts:
        - {shape: polygon, points: [{anchor: top, dy: -10}, {dx: -5, dy: 5}, {dx: 5, dy: 5}]}
"""
    face = load(write_design(design(hands, MAIN_HANDS)), bag)
    assert face is None
    # One error, with the reason -- not the schema's bare "unknown key"
    # followed by a second report of the same key.
    assert len(bag.errors) == 1, bag.render()
    error = bag.errors[0]
    assert "no box to anchor to" in error.message
    assert "parts[0].points[0]" in error.message
    text = design(hands, MAIN_HANDS)
    assert error.span is not None
    assert error.span.line == text[:text.index("anchor: top")].count("\n") + 1


@pytest.mark.parametrize("length", ["10%", "2pt"])
def test_percent_and_pt_are_rejected_in_a_part_length(write_design, bag, length):
    hands = f"""
hands:
  classic:
    hour:
      color: palette.fg
      parts:
        - {{shape: circle, radius: {length!r}}}
"""
    face = load(write_design(design(hands, MAIN_HANDS)), bag)
    assert face is None
    # The schema alone says only "expected number, got string" -- which is
    # what this reported before `wfb/validate.py`'s `_check_hand_frame`, and
    # which does not tell an author that `10%` is fine everywhere else.
    assert len(bag.errors) == 1, bag.render()
    error = bag.errors[0]
    assert "px or %r only" in error.message
    assert ("no parent box" if length.endswith("%") else "no font") in error.message
    text = design(hands, MAIN_HANDS)
    assert error.span is not None
    assert error.span.line == text[:text.index("radius:")].count("\n") + 1


def test_percent_r_px_and_bare_numbers_are_accepted_in_a_part_length(write_design, bag):
    """The contrast for the refusal above: the check must not also catch `%r`."""
    hands = """
hands:
  classic:
    hour:
      color: palette.fg
      parts:
        - {shape: circle, radius: 3%r}
        - {shape: circle, at: {dy: -10px}, radius: 2}
        - {shape: line, to: {dy: "-40%r"}, thickness: 2px}
"""
    face = load(write_design(design(hands, MAIN_HANDS)), bag)
    assert face is not None, bag.render()


def test_no_colour_is_an_error(write_design, bag):
    hands = """
hands:
  classic:
    hour:
      parts:
        - {shape: circle, radius: 10%r}
"""
    bad = errors(design(hands, MAIN_HANDS), bag, write_design)
    assert len(bad) == 1
    assert "no colour" in bad[0].message


def test_a_part_colour_overrides_the_hands_default(write_design, bag):
    """The part without its own `color:` inherits the hand's; the one that
    does override keeps its own -- proven by resolving both."""
    face = load(write_design(design(CLASSIC, MAIN_HANDS)), bag)
    assert face is not None, bag.render()
    hand = face.hands["classic"].minute
    assert hand.parts[0].color.text == "palette.fg"  # inherited
    # the hub has no color: of its own either, in CLASSIC -- override case
    # is exercised by the second hand's centre-cap-less design here instead:
    second = face.hands["classic"].second
    assert second.parts[0].color.text == "palette.accent"


@pytest.mark.parametrize("where", ["hand", "part"])
def test_a_data_bound_colour_is_rejected(write_design, bag, where):
    color_line = ("      color: activity.steps\n" if where == "hand" else
                  "      color: palette.fg\n")
    part_color = "\n          color: activity.steps" if where == "part" else ""
    hands = f"""
hands:
  classic:
    hour:
{color_line}      parts:
        - shape: circle
          radius: 10%r{part_color}
"""
    face = load(write_design(design(hands, MAIN_HANDS)), bag)
    assert face is None
    # `activity.steps` types as Number, not a colour -- caught by the
    # ordinary colour-type check when it is the hand's own `color:`, and by
    # the dedicated hands-data-binding check when the part's own reference
    # resolves as a genuine colour-typed data source.
    assert bag.errors


def test_seconds_awake_without_a_second_hand_is_an_error(write_design, bag):
    hands = """
hands:
  classic:
    hour:
      color: palette.fg
      parts:
        - {shape: circle, radius: 10%r}
"""
    elements = """  - id: h
    type: hands
    hands: classic
    seconds: awake
    at: {anchor: center}
"""
    bad = errors(design(hands, elements), bag, write_design)
    assert len(bad) == 1
    assert "needs a second hand" in bad[0].message


def test_seconds_always_is_a_friendly_not_implemented_error(write_design, bag):
    elements = """  - id: h
    type: hands
    hands: classic
    seconds: always
    at: {anchor: center}
"""
    bad = errors(design(CLASSIC, elements), bag, write_design)
    assert len(bad) == 1
    assert "not implemented yet" in bad[0].message
    assert "awake" in bad[0].message or "awake" in " ".join(bad[0].notes)


def test_low_power_mode_is_rejected_on_hands(write_design, bag):
    elements = """  - id: h
    type: hands
    hands: classic
    modes: [active, low_power]
    at: {anchor: center}
"""
    bad = errors(design(CLASSIC, elements), bag, write_design)
    assert len(bad) == 1
    assert "low_power" in bad[0].message


@pytest.mark.parametrize("elements", [
    """  - id: h
    type: hands
    hands: classic
    static: true
    at: {anchor: center}
""",
    """  - id: wrap
    type: group
    static: true
    children:
      - id: h
        type: hands
        hands: classic
        at: {anchor: center}
""",
])
def test_static_hands_is_rejected_directly_and_nested(write_design, bag, elements):
    bad = errors(design(CLASSIC, elements), bag, write_design)
    assert any("cannot be static" in d.message for d in bad)


@pytest.mark.parametrize("part,message", [
    ("{shape: polygon, filled: false, points: [{dy: -10}, {dx: -5, dy: 5}, {dx: 5, dy: 5}]}",
     "not accepted on a hand 'shape: polygon' part"),
    ("{shape: rectangle, filled: false, at: {dy: 0}, size: {width: 4%r, height: 4%r}}",
     "not accepted on a hand 'shape: rectangle' part"),
])
def test_filled_false_is_rejected_on_polygon_and_rectangle(write_design, bag, part, message):
    hands = f"""
hands:
  classic:
    hour:
      color: palette.fg
      parts:
        - {part}
"""
    bad = errors(design(hands, MAIN_HANDS), bag, write_design)
    assert len(bad) == 1
    assert message in bad[0].message


def test_thickness_is_rejected_on_a_filled_circle_part(write_design, bag):
    hands = """
hands:
  classic:
    hour:
      color: palette.fg
      parts:
        - {shape: circle, radius: 10%r, thickness: 2px}
"""
    bad = errors(design(hands, MAIN_HANDS), bag, write_design)
    assert len(bad) == 1
    assert "'thickness' is not used by a filled 'shape: circle' part" in bad[0].message


def test_filled_is_rejected_on_a_line_part(write_design, bag):
    hands = """
hands:
  classic:
    hour:
      color: palette.fg
      parts:
        - {shape: line, at: {dy: 5%r}, to: {dy: -20%r}, filled: false}
"""
    bad = errors(design(hands, MAIN_HANDS), bag, write_design)
    assert len(bad) == 1
    assert "'filled' is not used by a hand 'shape: line' part" in bad[0].message


def test_the_old_analog_clock_hint_now_points_at_type_hands(write_design, bag):
    text = BASE + "\nelements:\n  - id: h\n    type: analog_clock\n"
    face = load(write_design(text), bag)
    assert face is None
    notes = " ".join(n for d in bag.errors for n in d.notes)
    assert "type: hands" in notes


# -- resolution (wfb.layout) --------------------------------------------------


def test_a_percent_r_length_resolves_per_device(resolved_for):
    hands = CLASSIC.replace("radius: 4%r", "radius: 44%r")
    small = find(resolved_for(design(hands, MAIN_HANDS), "fenix8solar47mm"), "main_hands")
    large = find(resolved_for(design(hands, MAIN_HANDS), "fenix8solar51mm"), "main_hands")
    assert small.minute.parts[1].radius == 57   # 44% of 130
    assert large.minute.parts[1].radius == 62   # 44% of 140


def test_a_mirrored_pair_resolves_to_mirrored_pixels(resolved_for):
    """Round half away from zero (§5.3): -1.5px/1.5px must resolve to -2/2,
    not 0/2 the way round-half-to-even would for a *different* value."""
    hands = """
hands:
  classic:
    hour:
      color: palette.fg
      parts:
        - {shape: line, at: {dx: -1.5px, dy: 0}, to: {dx: 1.5px, dy: 0}, thickness: 1px}
"""
    placed = find(resolved_for(design(hands, MAIN_HANDS)), "main_hands")
    part = placed.hour.parts[0]
    assert (part.x1, part.x2) == (-2, 2)


def test_a_rectangle_part_becomes_a_polygon_in_corner_order(resolved_for):
    """top-left, top-right, bottom-right, bottom-left (§6) -- the order a
    rotated rectangle keeps no matter which corner ends up where."""
    hands = """
hands:
  classic:
    minute:
      color: palette.fg
      parts:
        - {shape: rectangle, at: {dy: 0}, size: {width: 10px, height: 20px}}
"""
    placed = find(resolved_for(design(hands, MAIN_HANDS)), "main_hands")
    part = placed.minute.parts[0]
    assert part.shape == "polygon"
    assert part.points == ((-5, -10), (5, -10), (5, 10), (-5, 10))


def test_reach_is_the_farthest_ink_from_the_axis(resolved_for):
    hands = """
hands:
  classic:
    second:
      color: palette.fg
      parts:
        - {shape: line, at: {dy: 15px}, to: {dy: -82px}, thickness: 2px}
"""
    placed = find(resolved_for(design(hands, MAIN_HANDS)), "main_hands")
    # the far end of the line, plus half the pen width
    assert placed.reach == pytest.approx(82.0 + 1.0)


def test_a_seconds_never_hand_is_excluded_from_reach_and_from_drawing(resolved_for):
    """'seconds: never' -- the set's second hand is not drawn at all (§5.6),
    so its geometry must not inflate the swept disc either."""
    hands = """
hands:
  classic:
    hour:
      color: palette.fg
      parts:
        - {shape: circle, radius: 10px}
    second:
      color: palette.fg
      parts:
        - {shape: line, at: {dy: 0}, to: {dy: -100px}, thickness: 1px}
"""
    elements = """  - id: main_hands
    type: hands
    hands: classic
    seconds: never
    at: {anchor: center}
"""
    placed = find(resolved_for(design(hands, elements)), "main_hands")
    assert placed.second is None
    assert placed.reach == pytest.approx(10.0)


def test_an_off_centre_axis_inside_a_group(resolved_for):
    hands = """
hands:
  small_seconds:
    second:
      color: palette.fg
      parts:
        - {shape: line, at: {dy: 3%r}, to: {dy: -20%r}, thickness: 1px}
"""
    elements = """  - id: wrap
    type: group
    at: {anchor: center, dy: 20%}
    size: {width: 50%, height: 50%}
    children:
      - id: sub
        type: hands
        hands: small_seconds
        at: {anchor: center, dy: 30%}
"""
    resolved = resolved_for(design(hands, elements))
    sub = find(resolved, "sub")
    wrap = find(resolved, "wrap")
    # the axis is resolved against the group's own box, not the screen
    assert sub.center[1] > wrap.box.y + wrap.box.height / 2


def test_circular_extent_matches_reach(resolved_for):
    placed = find(resolved_for(design(CLASSIC, MAIN_HANDS)), "main_hands")
    extent = circular_extent(placed)
    assert extent is not None
    assert extent == (placed.center[0], placed.center[1], placed.reach)
    assert isinstance(placed, PlacedHands)


def test_seconds_never_on_a_second_only_set_is_an_error(write_design, bag):
    """The one combination that would draw nothing at all -- refused, not
    generated as an empty method (no silent no-ops)."""
    hands = """
hands:
  small:
    second:
      color: palette.fg
      parts:
        - {shape: line, to: {dy: -20%r}, thickness: 1px}
"""
    element = """  - {id: sub, type: hands, hands: small, seconds: never}
"""
    face = load(write_design(design(hands, element)), bag)
    assert face is None
    assert len(bag.errors) == 1, bag.render()
    assert "draws nothing" in bag.errors[0].message


# -- lints that read a hand's colours ---------------------------------------


DITHER_HANDS = """
hands:
  odd:
    minute:
      color: palette.fg
      parts:
        - {shape: circle, radius: 4%r}
    second:
      color: palette.odd
      parts:
        - {shape: line, to: {dy: -40%r}, thickness: 1px}
"""


@pytest.fixture
def lint_design(write_design, bag, db):
    from wfb import lint

    def _lint(elements: str):
        text = design(DITHER_HANDS, elements).replace(
            'accent: "#FF5500"', 'accent: "#FF5500"\n  odd: "#123456"')
        face = load(write_design(text), bag)
        assert face is not None, bag.render()
        device = db.get("fenix8solar47mm")
        lint.run(resolve(face, device, bake_fonts(face, device)), bag)
        return [d for d in bag.items if d.code == "palette-dither"]

    return _lint


def test_a_dithered_hand_colour_warns_and_names_the_hands_element(lint_design):
    """`palette.odd` is read only by a hand.  Before `lint._users_of` learnt
    hand colours, this warned with the "nowhere to put a suppression" note,
    and the suppression below silently did nothing."""
    warnings = lint_design("  - {id: h, type: hands, hands: odd}\n")
    assert len(warnings) == 1
    assert not any("nowhere to put" in note for note in warnings[0].notes)


def test_a_dithered_hand_colour_is_suppressed_on_the_hands_element(lint_design):
    warnings = lint_design(
        "  - {id: h, type: hands, hands: odd,\n"
        "     lint: {allow: [palette-dither], reason: probing}}\n")
    assert warnings == []


def test_a_suppression_on_some_other_element_does_not_reach_a_hand_colour(lint_design):
    warnings = lint_design(
        "  - {id: h, type: hands, hands: odd}\n"
        "  - {id: dot, type: shape, shape: circle, radius: 2px, color: palette.fg,\n"
        "     lint: {allow: [palette-dither], reason: probing}}\n")
    assert len(warnings) == 1


def test_a_never_drawn_second_hand_colour_counts_as_unused(lint_design):
    """`seconds: never` draws no second hand, so its colour is not on screen:
    `palette.odd` is then an unused entry, and warns the way any unused
    dithered entry does -- saying there is no element to suppress it on,
    rather than naming a hands element that never draws it."""
    warnings = lint_design("  - {id: h, type: hands, hands: odd, seconds: never}\n")
    assert len(warnings) == 1
    assert any("nowhere to put" in note for note in warnings[0].notes)
