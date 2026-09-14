"""Patterns (plan 05): `type: pattern` templates, drawn repeatedly -- turned
about a centre (`pattern: radial`) or stepped along a line (`pattern:
linear`).

Every diagnostic here was driven red first -- run against the violating
input below with the fix reverted, each one raised a different, wrong error
(or none at all) before the corresponding check landed, the same discipline
`tests/CLAUDE.md` asks for every new diagnostic.
"""

from __future__ import annotations

import math

import pytest

from tests.test_diagnostics import load
from wfb import lint
from wfb.diagnostics import Bag
from wfb.emit.resources import bake_fonts
from wfb.ir import HandsElement, PatternElement
from wfb.layout import ANTIALIASED_PRIMITIVES, PlacedPattern, circular_extent, resolve

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


def design(elements_block: str) -> str:
    return BASE + "\nelements:\n" + elements_block


#: A four-copy radial ring -- 90deg apart, the default step -- used as the
#: "everything builds" fixture and as the geometry fixture below (§4).
RADIAL_RING = """  - id: ring
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 4
    color: palette.fg
    parts:
      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px}
"""

#: A three-copy linear row, 20px apart.
LINEAR_ROW = """  - id: row
    type: pattern
    pattern: linear
    at: {anchor: center}
    count: 3
    step: {dx: 20px}
    color: palette.fg
    parts:
      - {shape: circle, radius: 5px}
"""


@pytest.fixture
def resolved_for(write_design, bag, db):
    def _resolve(text: str, device_id: str = "fenix8solar47mm"):
        face = load(write_design(text), bag)
        assert face is not None, bag.render()
        device = db.get(device_id)
        return resolve(face, device, bake_fonts(face, device))

    return _resolve


def find(resolved, element_id):
    return next(p for p in resolved.items if p.id == element_id)


def errors(text: str, bag: Bag, write_design) -> list:
    face = load(write_design(text), bag)
    assert face is None
    return bag.errors


# -- building the base fixtures ----------------------------------------------


def test_the_reference_radial_design_builds_clean(write_design, bag):
    face = load(write_design(design(RADIAL_RING)), bag)
    assert face is not None, bag.render()
    element = face.elements[0]
    assert isinstance(element, PatternElement)
    assert element.pattern == "radial"
    assert element.count == 4


def test_the_reference_linear_design_builds_clean(write_design, bag):
    face = load(write_design(design(LINEAR_ROW)), bag)
    assert face is not None, bag.render()
    element = face.elements[0]
    assert isinstance(element, PatternElement)
    assert element.pattern == "linear"
    assert element.count == 3


def test_a_hand_still_builds_clean_after_the_part_builder_was_parameterised(write_design, bag):
    """Regression: `_build_hand_part`/`_check_hand_part_keys` now take a
    `context` argument (hand vs pattern) -- every existing call from
    `_build_hand` must still take the hand path unchanged."""
    hands = """
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
"""
    elements = """  - id: h
    type: hands
    hands: classic
    at: {anchor: center}
"""
    face = load(write_design(BASE + hands + "\nelements:\n" + elements), bag)
    assert face is not None, bag.render()
    assert isinstance(face.elements[0], HandsElement)
    # an arc part is still rejected on a hand, unchanged wording:
    bad_hands = hands.replace(
        "        - {shape: polygon,",
        "        - {shape: arc}\n        - {shape: polygon,",
    )
    bad = errors(BASE + bad_hands + "\nelements:\n" + elements, bag, write_design)
    assert len(bad) == 1
    assert "not implemented yet" in bad[0].message


# -- §5.4 diagnostics ---------------------------------------------------------


def test_radial_with_a_mapping_step_is_an_error(write_design, bag):
    text = RADIAL_RING.replace("count: 4", "count: 4\n    step: {dx: 5px}")
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "not {dx, dy}" in bad[0].message


def test_linear_with_an_angle_step_is_an_error(write_design, bag):
    text = LINEAR_ROW.replace("step: {dx: 20px}", "step: 5deg")
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "not an angle" in bad[0].message


def test_linear_with_no_step_is_an_error(write_design, bag):
    text = LINEAR_ROW.replace("    step: {dx: 20px}\n", "")
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "needs a 'step:" in bad[0].message


def test_start_on_a_linear_pattern_is_an_error(write_design, bag):
    text = LINEAR_ROW.replace("count: 3", "count: 3\n    start: 10deg")
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "not accepted on 'pattern: linear'" in bad[0].message


def test_radial_step_zero_is_an_error(write_design, bag):
    text = RADIAL_RING.replace("count: 4", "count: 4\n    step: 0deg")
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "step: 0deg" in bad[0].message


def test_radial_copies_that_wrap_past_a_full_turn_name_the_two_indices(write_design, bag):
    """5 copies at 90deg apart: copy 4 lands back on copy 0's angle."""
    text = RADIAL_RING.replace("count: 4", "count: 5\n    step: 90deg")
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "copies 0 and 4 land on the same angle" in bad[0].message


def test_a_skip_index_out_of_range_is_an_error(write_design, bag):
    text = RADIAL_RING.replace("count: 4", "count: 4\n    skip: [4]")
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "out of range" in bad[0].message


def test_a_repeated_skip_index_is_an_error(write_design, bag):
    """§5.4 check 4's other half: a repeated index, not just one out of
    range.  Enforced by the schema's own `uniqueItems: true` on `skip:`
    (`schema/wfb-face-1.schema.json`), one stage before the IR checks
    above -- still one error, not a silent dedupe."""
    text = RADIAL_RING.replace("count: 4", "count: 4\n    skip: [1, 1]")
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "non-unique" in bad[0].message


def test_skip_every_greater_than_count_is_an_error(write_design, bag):
    text = RADIAL_RING.replace("count: 4", "count: 4\n    skip_every: 5")
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "skips nothing" in bad[0].message


def test_every_copy_skipped_is_an_error(write_design, bag):
    text = RADIAL_RING.replace("count: 4", "count: 4\n    skip_every: 2\n    skip: [1, 3]")
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "leave every copy undrawn" in bad[0].message


def test_low_power_mode_is_rejected_on_a_pattern(write_design, bag):
    text = RADIAL_RING.replace("    at: {anchor: center}", "    at: {anchor: center}\n    modes: [active, low_power]")
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "low_power" in bad[0].message


# -- §5.2 part diagnostics -----------------------------------------------------


@pytest.mark.parametrize("shape,reason", [
    ("rounded_rectangle", "rotated or translated rounded rectangle"),
    ("ellipse", "rotated or translated ellipse"),
    ("text", "cannot rotate or translate"),
    ("icon", "cannot rotate or translate"),
])
def test_bad_part_shapes_each_get_their_own_reason(write_design, bag, shape, reason):
    text = RADIAL_RING.replace(
        "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px}",
        f"      - {{shape: {shape}}}",
    )
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert f"'shape: {shape}'" in bad[0].message
    assert reason in bad[0].message


def test_arc_is_a_real_shape_on_a_pattern_unlike_a_hand(write_design, bag):
    text = RADIAL_RING.replace(
        "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px}",
        "      - {shape: arc, radius: 40px, thickness: 4px, start_angle: 3deg, sweep: 24deg}",
    )
    face = load(write_design(design(text)), bag)
    assert face is not None, bag.render()


def test_at_on_an_arc_part_is_rejected_with_the_centring_reason(write_design, bag):
    text = RADIAL_RING.replace(
        "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px}",
        "      - {shape: arc, at: {dy: -10px}, radius: 40px, sweep: 24deg}",
    )
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "'at' is not used by a pattern 'shape: arc' part" in bad[0].message
    assert "always centred on the copy's own origin" in " ".join(bad[0].notes)


def test_a_key_not_used_by_this_part_shape_is_an_error(write_design, bag):
    text = RADIAL_RING.replace(
        "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px}",
        "      - {shape: polygon, radius: 5, points: [{dy: -10}, {dx: -5, dy: 5}, {dx: 5, dy: 5}]}",
    )
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "'radius' is not used by a pattern 'shape: polygon' part" in bad[0].message


def test_no_colour_is_an_error(write_design, bag):
    text = RADIAL_RING.replace("    color: palette.fg\n", "")
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "no colour" in bad[0].message
    assert "this pattern" in bad[0].message


def test_a_part_colour_overrides_the_pattern_default(write_design, bag):
    text = RADIAL_RING.replace(
        "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px}",
        "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px, color: palette.accent}",
    )
    face = load(write_design(design(text)), bag)
    assert face is not None, bag.render()
    part = face.elements[0].parts[0]
    assert part.color.text == "palette.accent"


@pytest.mark.parametrize("where", ["element", "part"])
def test_a_data_bound_colour_is_rejected(write_design, bag, where):
    if where == "element":
        text = RADIAL_RING.replace("color: palette.fg", "color: activity.steps")
    else:
        text = RADIAL_RING.replace(
            "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px}",
            "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px, "
            "color: activity.steps}",
        )
    face = load(write_design(design(text)), bag)
    assert face is None
    assert bag.errors


def test_filled_false_is_rejected_on_polygon(write_design, bag):
    text = RADIAL_RING.replace(
        "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px}",
        "      - {shape: polygon, filled: false, points: "
        "[{dy: -10}, {dx: -5, dy: 5}, {dx: 5, dy: 5}]}",
    )
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "not accepted on a pattern 'shape: polygon' part" in bad[0].message


def test_thickness_is_rejected_on_a_filled_circle_part(write_design, bag):
    text = RADIAL_RING.replace(
        "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px}",
        "      - {shape: circle, radius: 10px, thickness: 2px}",
    )
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "'thickness' is not used by a filled 'shape: circle' part" in bad[0].message


def test_thickness_is_accepted_on_an_arc_part(write_design, bag):
    text = RADIAL_RING.replace(
        "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px}",
        "      - {shape: arc, radius: 30px, thickness: 4px, sweep: 20deg}",
    )
    face = load(write_design(design(text)), bag)
    assert face is not None, bag.render()


def test_filled_is_rejected_on_an_arc_part(write_design, bag):
    text = RADIAL_RING.replace(
        "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px}",
        "      - {shape: arc, radius: 30px, sweep: 20deg, filled: false}",
    )
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "'filled' is not used by a pattern 'shape: arc' part" in bad[0].message


def test_an_arc_part_needs_a_radius(write_design, bag):
    text = RADIAL_RING.replace(
        "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px}",
        "      - {shape: arc, sweep: 20deg}",
    )
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "an arc part needs a radius" in bad[0].message


def test_anchor_in_a_part_position_is_rejected(write_design, bag):
    text = RADIAL_RING.replace(
        "at: {dy: -40px}, to: {dy: -50px}",
        "at: {anchor: top, dy: -40px}, to: {dy: -50px}",
    )
    face = load(write_design(design(text)), bag)
    assert face is None
    assert len(bag.errors) == 1, bag.render()
    assert "no box to anchor to" in bag.errors[0].message


@pytest.mark.parametrize("length", ["10%", "2pt"])
def test_percent_and_pt_are_rejected_in_a_part_length(write_design, bag, length):
    text = RADIAL_RING.replace(
        "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px}",
        f"      - {{shape: circle, radius: {length!r}}}",
    )
    face = load(write_design(design(text)), bag)
    assert face is None
    assert len(bag.errors) == 1, bag.render()
    assert "px or %r only" in bag.errors[0].message


def test_pt_is_rejected_in_a_linear_step(write_design, bag):
    text = LINEAR_ROW.replace("step: {dx: 20px}", "step: {dx: 2pt}")
    face = load(write_design(design(text)), bag)
    assert face is None
    assert len(bag.errors) == 1, bag.render()
    assert "px, % or %r" in bag.errors[0].message


def test_percent_is_accepted_in_a_linear_step_but_not_a_part_length(write_design, bag):
    """The contrast for the refusal above: `%` is fine on `step:` (resolved
    against the parent box), but still refused inside the template frame."""
    text = LINEAR_ROW.replace("step: {dx: 20px}", "step: {dx: 5%}")
    face = load(write_design(design(text)), bag)
    assert face is not None, bag.render()


# -- IR: drawn_indices / default step -----------------------------------------


def test_drawn_indices_applies_skip_and_skip_every(write_design, bag):
    text = RADIAL_RING.replace("count: 4", "count: 10\n    skip: [1]\n    skip_every: 5")
    face = load(write_design(design(text)), bag)
    assert face is not None, bag.render()
    element = face.elements[0]
    # 0 and 5 are multiples of 5 (skipped); 1 is explicitly skipped.
    assert element.drawn_indices() == (2, 3, 4, 6, 7, 8, 9)


def test_default_radial_step_is_360_over_count(write_design, bag):
    text = RADIAL_RING.replace("count: 4", "count: 8")
    face = load(write_design(design(text)), bag)
    assert face is not None, bag.render()
    assert face.elements[0].step_angle == pytest.approx(45.0)
    assert face.elements[0].start_angle == 0.0


# -- layout: transform, arc resolution ----------------------------------------


def test_radial_transform_turns_a_12_oclock_point_to_3_oclock(resolved_for):
    """Copy 1 is 90deg clockwise (the default step for 4 copies): a point
    straight up from the axis lands to its right (§5.3)."""
    placed = find(resolved_for(design(RADIAL_RING)), "ring")
    assert isinstance(placed, PlacedPattern)
    ox, oy, sin_t, cos_t = placed.transform(1)
    assert (ox, oy) == (float(placed.center[0]), float(placed.center[1]))
    x, y = 0.0, -50.0  # a 12-o'clock point, 50px from the axis
    wx = ox + x * cos_t - y * sin_t
    wy = oy + x * sin_t + y * cos_t
    assert wx == pytest.approx(ox + 50.0)
    assert wy == pytest.approx(oy)


def test_linear_transform_steps_by_dx_dy(resolved_for):
    placed = find(resolved_for(design(LINEAR_ROW)), "row")
    assert isinstance(placed, PlacedPattern)
    ox0, oy0, sin0, cos0 = placed.transform(0)
    ox2, oy2, sin2, cos2 = placed.transform(2)
    assert (sin0, cos0) == (0.0, 1.0)
    assert (sin2, cos2) == (0.0, 1.0)
    assert ox2 - ox0 == pytest.approx(2 * placed.dx)
    assert oy2 - oy0 == pytest.approx(2 * placed.dy)


def test_arc_part_resolves_centred_on_the_origin(resolved_for):
    text = RADIAL_RING.replace("count: 4", "count: 1").replace(
        "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px}",
        "      - {shape: arc, radius: 30px, thickness: 4px, start_angle: 10deg, sweep: 50deg}",
    )
    placed = find(resolved_for(design(text)), "ring")
    part = placed.parts[0]
    assert part.shape == "arc"
    assert (part.x, part.y) == (0, 0)
    assert part.radius == 30
    assert part.thickness == 4
    assert part.start_angle == pytest.approx(10.0)
    assert part.sweep == pytest.approx(50.0)


# -- layout: box / reach -------------------------------------------------------


def test_radial_ring_box_and_reach(resolved_for):
    """4 copies, 90deg apart, a line 40-50px from the axis, 2px thick: the
    ring's reach is rotation-invariant (50 + half the pen), and with copies
    at 12/3/6/9 o'clock the box is the square that reach implies."""
    placed = find(resolved_for(design(RADIAL_RING)), "ring")
    cx, cy = placed.center
    assert placed.reach == pytest.approx(51.0)
    assert placed.box.x == cx - 51
    assert placed.box.y == cy - 51
    assert placed.box.width == 102
    assert placed.box.height == 102


def test_circular_extent_matches_reach_for_a_radial_pattern(resolved_for):
    placed = find(resolved_for(design(RADIAL_RING)), "ring")
    extent = circular_extent(placed)
    assert extent is not None
    assert extent == (placed.center[0], placed.center[1], placed.reach)


def test_circular_extent_is_none_for_a_linear_pattern(resolved_for):
    placed = find(resolved_for(design(LINEAR_ROW)), "row")
    assert circular_extent(placed) is None
    assert placed.reach == 0.0


def test_linear_row_box(resolved_for):
    """3 copies, 20px apart, a 5px-radius circle: the box spans from the
    first copy's left edge to the last copy's right edge."""
    placed = find(resolved_for(design(LINEAR_ROW)), "row")
    cx, cy = placed.center
    assert placed.box.x == cx - 5
    assert placed.box.y == cy - 5
    assert placed.box.width == 40 + 10  # (0..40 span between copy centres) + 2*radius
    assert placed.box.height == 10


def test_placed_pattern_is_in_antialiased_primitives():
    assert PlacedPattern in ANTIALIASED_PRIMITIVES


# -- antialias inheritance -----------------------------------------------------


def test_a_pattern_inherits_the_face_antialias_default(write_design, bag):
    text = "antialias: true\n" + design(RADIAL_RING)
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    assert face.elements[0].resolved_antialias is True


def test_a_pattern_inherits_its_groups_antialias(write_design, bag):
    indented_ring = "\n".join(
        "    " + line if line.strip() else line for line in RADIAL_RING.splitlines()
    )
    grouped = f"""  - id: wrap
    type: group
    antialias: true
    children:
{indented_ring}
"""
    face = load(write_design(design(grouped)), bag)
    assert face is not None, bag.render()
    ring = next(e for e in face.walk() if e.id == "ring")
    assert ring.resolved_antialias is True


# -- static: -------------------------------------------------------------------


def test_a_pattern_may_be_static(write_design, bag):
    text = RADIAL_RING.replace("    at: {anchor: center}", "    at: {anchor: center}\n    static: true")
    face = load(write_design(design(text)), bag)
    assert face is not None, bag.render()
    element = face.elements[0]
    assert element.static is True
    assert element.static_root == element.id


# -- lint: pattern-step --------------------------------------------------------


@pytest.fixture
def lint_run(write_design, bag, db):
    def _run(text: str, device_id: str = "fenix8solar47mm"):
        face = load(write_design(text), bag)
        assert face is not None, bag.render()
        device = db.get(device_id)
        lint.run(resolve(face, device, bake_fonts(face, device)), bag)
        return bag

    return _run


def test_pattern_step_fires_when_the_step_rounds_to_zero(lint_run):
    text = LINEAR_ROW.replace("step: {dx: 20px}", 'step: {dx: "0.001%"}')
    bag = lint_run(design(text))
    findings = [d for d in bag.items if d.code == "pattern-step"]
    assert len(findings) == 1
    assert "rounds to {0, 0}px" in findings[0].message


def test_pattern_step_does_not_fire_for_a_real_step(lint_run):
    bag = lint_run(design(LINEAR_ROW))
    findings = [d for d in bag.items if d.code == "pattern-step"]
    assert findings == []


def test_pattern_step_does_not_fire_for_a_radial_pattern(lint_run):
    bag = lint_run(design(RADIAL_RING))
    findings = [d for d in bag.items if d.code == "pattern-step"]
    assert findings == []


# -- barrel selection (§6.5 dispatch) -------------------------------------------


ALL_ARC_RING = """  - id: segs
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 12
    color: palette.fg
    parts:
      - {shape: arc, radius: 40px, thickness: 4px, start_angle: 3deg, sweep: 24deg}
"""


def _barrel_for(text: str, write_design, bag, db, tmp_path):
    from wfb.emit.project import generate

    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    baked = {device.id: resolved.fonts}
    project = generate(resolved.face, [device], tmp_path, baked)
    return project.barrel


def test_an_all_arc_pattern_does_not_pull_in_wfbgeom(write_design, bag, db, tmp_path):
    """An all-arc pattern (radial or linear) draws only through
    `WfbArc.drawSpan` -- it never rotates a vertex or translates a polygon,
    so it has no call into `WfbGeom` at all (`_emit_pattern_part` in
    `wfb/emit/monkeyc.py`).  `BARREL_FILES`' own promise
    ("only what a face uses is copied") means `WfbGeom.mc` must be left
    out here, unlike a pattern with a line/rectangle/circle part."""
    barrel = _barrel_for(design(ALL_ARC_RING), write_design, bag, db, tmp_path)
    assert "WfbArc.mc" in barrel
    assert "WfbGeom.mc" not in barrel


def test_a_mixed_pattern_pulls_in_both_barrels(write_design, bag, db, tmp_path):
    """The contrast for the test above: a line part alongside the arc part
    does call into `WfbGeom` (`WfbGeom.drawLineRotated`), so both barrels
    are needed together."""
    text = ALL_ARC_RING.replace(
        "      - {shape: arc, radius: 40px, thickness: 4px, start_angle: 3deg, sweep: 24deg}\n",
        "      - {shape: arc, radius: 40px, thickness: 4px, start_angle: 3deg, sweep: 24deg}\n"
        "      - {shape: line, at: {dy: -40px}, to: {dy: -50px}, thickness: 2px}\n",
    )
    barrel = _barrel_for(design(text), write_design, bag, db, tmp_path)
    assert "WfbArc.mc" in barrel
    assert "WfbGeom.mc" in barrel
