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

from tests.helpers import errors, find
from wfb.build import load
from wfb import lint
from wfb.emit.resources import bake_fonts
from wfb.ir import HandsElement, PatternElement
from wfb.layout import PlacedPattern, circular_extent, is_antialiased_primitive, resolve

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
    # "text" left this table 2026-09-15 (plan 06 §3): a pattern text part's
    # glyphs are upright, only the anchor rotates/steps, so it is a real,
    # drawable shape now -- see tests/test_pattern_text.py. A hand part still
    # rejects it outright (a bitmap font really cannot rotate) -- covered by
    # test_a_hand_still_builds_clean_after_the_part_builder_was_parameterised's
    # sibling regression in tests/test_pattern_text.py.
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


def _with_color(template: str, color: str, where: str) -> str:
    """RADIAL_RING with `color` on the element, or on its one part (and
    none on the element)."""
    if where == "element":
        return template.replace("color: palette.fg", f'color: "{color}"')
    return template.replace(
        "thickness: 2px}", f'thickness: 2px, color: "{color}"}}').replace(
        "    color: palette.fg\n", "")


def _with_when_absent(template: str, value: str = "hide") -> str:
    """`template` with `when_absent: <value>` added at the element level,
    just above `parts:` -- every RADIAL_RING-derived fixture has exactly one
    `parts:` line."""
    assert template.count("    parts:\n") == 1
    return template.replace("    parts:\n", f"    when_absent: {value}\n    parts:\n", 1)


@pytest.mark.parametrize("where", ["element", "part"])
def test_a_colour_reading_an_absent_able_source_needs_when_absent(write_design, bag, where):
    """2026-09-15: a pattern colour may now read a source that can be
    absent, but only with 'when_absent: hide' declared -- the old outright
    refusal (`cannot read a source that may be absent`) is gone; this is
    the new one-error-not-N replacement, `_check_pattern_absence`."""
    color = "activity.steps > 5000 ? palette.accent : palette.fg"
    bad = errors(design(_with_color(RADIAL_RING, color, where)), bag, write_design)
    assert len(bad) == 1, [d.message for d in bad]
    assert bad[0].code == "when-absent"
    assert "reads 'activity.steps', which can be absent" in bad[0].message
    assert "'when_absent: hide' is required" in bad[0].message


def test_two_nullable_bindings_on_one_pattern_still_get_one_error(write_design, bag):
    """The element colour *and* the one part's colour both read a nullable
    source: `_check_pattern_absence` reports once for the whole element, not
    once per expression."""
    color = "activity.steps > 5000 ? palette.accent : palette.fg"
    text = _with_color(RADIAL_RING, color, "element").replace(
        "thickness: 2px}", f'thickness: 2px, color: "{color}"}}')
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1, [d.message for d in bad]
    assert bad[0].code == "when-absent"


@pytest.mark.parametrize("where", ["element", "part"])
def test_a_colour_reading_an_absent_able_source_builds_with_when_absent_hide(write_design, bag, where):
    color = "activity.steps > 5000 ? palette.accent : palette.fg"
    text = _with_when_absent(_with_color(RADIAL_RING, color, where))
    face = load(write_design(design(text)), bag)
    assert face is not None, bag.render()
    assert face.elements[0].when_absent == "hide"


def test_a_colour_reading_a_complication_builds_clean_with_the_subscription(
        write_design, bag, db, tmp_path):
    """`complication.battery` (every `complication.*` source is nullable, so
    it needed the same treatment as `activity.steps` above) -- builds with
    `when_absent: hide`, and the generated project actually subscribes:
    `ComplicationSubscriber` in the manifest, the right `minApiLevel`, and a
    `WfbComplications.subscribe` call in the view (1c in the brief -- costlier
    than a direct source, but it must still work end to end)."""
    from wfb.emit.project import generate

    color = "complication.battery > 50 ? palette.accent : palette.fg"
    text = _with_when_absent(_with_color(RADIAL_RING, color, "part"))
    face = load(write_design(design(text)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    project = generate(resolved.face, [device], tmp_path, {device.id: resolved.fonts})
    assert 'id="ComplicationSubscriber"' in project.manifest_text
    assert 'minApiLevel="3.1.0"' in project.manifest_text
    files = project.files()
    (view_path,) = [p for p in files if p.endswith("View.mc")]
    assert "WfbComplications.subscribe(new Complications.Id(Complications.COMPLICATION_TYPE_BATTERY))" \
        in files[view_path]


@pytest.mark.parametrize("where", ["element", "part"])
def test_a_colour_reading_a_never_absent_source_builds(write_design, bag, where):
    """The contrast: `date.weekday` is never absent, so a pattern may read it
    with no 'when_absent:' at all -- until 2026-09-15 this was the same
    "cannot read data" error as a hand's colour still gets."""
    color = "date.weekday == 1 ? palette.accent : palette.fg"
    face = load(write_design(design(_with_color(RADIAL_RING, color, where))), bag)
    assert face is not None, bag.render()
    assert face.elements[0].parts[0].color.sources == ("date.weekday",)


def test_when_absent_hide_on_a_pattern_that_reads_nothing_nullable_is_a_note(write_design, bag):
    """The mirror of the error above: `when_absent: hide` declared but
    nothing on the pattern can ever be absent -- a note, not an error, the
    same "has no effect" wording `_check_absence` gives every other element
    kind."""
    text = _with_when_absent(RADIAL_RING)
    face = load(write_design(design(text)), bag)
    assert face is not None, bag.render()
    notes = [d for d in bag.items if d.code == "when-absent"]
    assert len(notes) == 1, [d.message for d in bag.items]
    assert "has no effect" in notes[0].message


def test_when_absent_placeholder_is_a_schema_error_on_a_pattern(write_design, bag):
    """The schema restricts a pattern's 'when_absent:' to 'hide' only (no
    placeholder/fallback: a pattern has no single value to substitute one
    for) -- `progressElement`'s own restricted enum is the precedent."""
    text = _with_when_absent(RADIAL_RING, "placeholder")
    face = load(write_design(design(text)), bag)
    assert face is None
    assert any(d.code == "schema" for d in bag.errors), bag.render()


def test_a_hand_colour_still_may_not_read_a_never_absent_source(write_design, bag):
    """Relaxing the pattern rule must not relax the hand one: a hand's colour
    reads no data at all, absent-able or not."""
    hands = """
hands:
  classic:
    hour:
      color: "date.weekday == 1 ? palette.accent : palette.fg"
      parts:
        - {shape: rectangle, at: {dy: -30%r}, size: {width: 3%r, height: 50%r}}
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
    bad = errors(BASE + hands + "\nelements:\n" + elements, bag, write_design)
    assert len(bad) == 1
    assert "a hand colour cannot read data ('date.weekday')" in bad[0].message


# -- `copy`: the copy index in a colour ----------------------------------------


@pytest.mark.parametrize("where", ["element", "part"])
def test_copy_is_bound_in_a_pattern_colour(write_design, bag, where):
    color = "copy % 2 == 0 ? palette.accent : palette.fg"
    face = load(write_design(design(_with_color(RADIAL_RING, color, where))), bag)
    assert face is not None, bag.render()
    part_color = face.elements[0].parts[0].color
    assert part_color.code == "(((i % 2) == 0) ? Palette.ACCENT : Palette.FG)"
    assert part_color.sources == ()  # the copy index is not a data source
    assert part_color.constant is None  # ... and not a build-time constant


def test_copy_outside_a_pattern_has_its_own_error(write_design, bag):
    shape = """  - id: dot
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 5px
    color: "copy == 0 ? palette.accent : palette.fg"
"""
    bad = errors(design(shape), bag, write_design)
    assert len(bad) == 1
    assert "'copy' is only defined in a 'type: pattern' element's colours, " \
           "its parts' 'visible:' and a text part's 'value:'" in bad[0].message


def test_copy_does_not_leak_past_the_pattern_that_bound_it(write_design, bag):
    """`copy` is bound while one pattern's colours compile and unbound
    straight after -- an element built next must not see it."""
    shape = """  - id: dot
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 5px
    color: "copy == 0 ? palette.accent : palette.fg"
"""
    bad = errors(design(RADIAL_RING + shape), bag, write_design)
    assert len(bad) == 1
    assert "'copy' is only defined" in bad[0].message


def test_copy_does_not_leak_past_a_rejected_pattern(write_design, bag):
    """The same, when the pattern itself fails part-way through its
    colours: the `finally` unbinding must still run."""
    broken = _with_color(RADIAL_RING, "activity.steps > 1 ? palette.fg : palette.bg", "element")
    shape = """  - id: dot
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 5px
    color: "copy == 0 ? palette.accent : palette.fg"
"""
    bad = errors(design(broken + shape), bag, write_design)
    assert [d.message for d in bad if "'copy' is only defined" in d.message]


def test_copy_in_the_element_level_visible_is_its_own_error(write_design, bag):
    """B4: `copy` is bound only while a pattern's colours/parts' `visible:`
    compile -- the element's own `visible:` is compiled earlier, in
    `_build_element`, before `wfb.kinds.pattern.build` (and its `copy`
    binding) ever runs, so it gets the same "only defined in ..." error as
    anywhere else outside a pattern."""
    text = RADIAL_RING.replace(
        "    at: {anchor: center}",
        '    at: {anchor: center}\n    visible: "copy == 0"',
    )
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "'copy' is only defined in a 'type: pattern' element's colours, " \
           "its parts' 'visible:' and a text part's 'value:'" in bad[0].message


# -- part `visible:` (B) -------------------------------------------------------


def _with_part_visible(template: str, condition: str) -> str:
    """RADIAL_RING's one part with `visible: <condition>` added."""
    return template.replace("thickness: 2px}", f'thickness: 2px, visible: "{condition}"}}')


def test_part_visible_reading_only_copy_builds(write_design, bag):
    text = _with_part_visible(RADIAL_RING, "copy < 2")
    face = load(write_design(design(text)), bag)
    assert face is not None, bag.render()
    part = face.elements[0].parts[0]
    assert part.visible is not None
    assert part.visible.sources == ()
    assert part.visible.code == "(i < 2)"


def test_part_visible_reading_only_copy_may_be_static(write_design, bag):
    """A copy's index never changes once the buffer is filled -- the same
    reasoning that already lets a colour reading only `copy` be static."""
    text = _static(_with_part_visible(RADIAL_RING, "copy < 2"))
    face = load(write_design(design(text)), bag)
    assert face is not None, bag.render()


def test_part_visible_reading_a_nullable_source_needs_when_absent(write_design, bag):
    text = _with_part_visible(RADIAL_RING, "copy <= activity.move_bar_level - 1")
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1, [d.message for d in bad]
    assert bad[0].code == "when-absent"
    assert "activity.move_bar_level" in bad[0].message
    assert "'when_absent: hide' is required" in bad[0].message


def test_part_visible_reading_a_nullable_source_builds_with_when_absent_hide(write_design, bag):
    text = _with_when_absent(_with_part_visible(RADIAL_RING, "copy <= activity.move_bar_level - 1"))
    face = load(write_design(design(text)), bag)
    assert face is not None, bag.render()
    part = face.elements[0].parts[0]
    assert part.visible.sources == ("activity.move_bar_level",)


def test_part_visible_reading_a_data_source_inside_static_is_a_static_error(write_design, bag):
    """Even a never-absent source: static freezes the reading, the same
    ordinary static-binding error a colour reading `date.weekday` gets --
    and the message says 'visible', not 'a value' (A3)."""
    text = _static(_with_part_visible(RADIAL_RING, "date.weekday == 1"))
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert bad[0].code == "static"
    assert "visible" in bad[0].message
    assert "date.weekday" in bad[0].message


def test_part_visible_non_boolean_is_the_boolean_type_error(write_design, bag):
    text = _with_part_visible(RADIAL_RING, "copy")
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert "visible must be a boolean" in bad[0].message


def test_visible_on_a_hand_part_is_rejected_by_the_schema(write_design, bag):
    """`handPart` never gained `visible:` -- schema keeps `additionalProperties:
    false`, unlike `patternPart` (B1)."""
    hands = """
hands:
  classic:
    hour:
      color: palette.fg
      parts:
        - {shape: rectangle, at: {dy: -30%r}, size: {width: 3%r, height: 50%r}, visible: "true"}
"""
    elements = """  - id: h
    type: hands
    hands: classic
    at: {anchor: center}
"""
    face = load(write_design(BASE + hands + "\nelements:\n" + elements), bag)
    assert face is None
    assert any(d.code == "schema" for d in bag.errors), bag.render()


def test_copy_does_not_leak_past_a_pattern_whose_part_visible_bound_it(write_design, bag):
    text = _with_part_visible(RADIAL_RING, "copy < 2")
    shape = """  - id: dot
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 5px
    color: "copy == 0 ? palette.accent : palette.fg"
"""
    bad = errors(design(text + shape), bag, write_design)
    assert len(bad) == 1
    assert "'copy' is only defined" in bad[0].message



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
    # Worded for a pattern, not borrowed from hands (plan 18 item 9).
    assert "hand" not in bag.errors[0].message
    assert "pattern part" in bag.errors[0].message.split(";")[1]


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


def test_placed_pattern_is_in_antialiased_primitives(resolved_for):
    placed = find(resolved_for(design(RADIAL_RING)), "ring")
    assert is_antialiased_primitive(placed)


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


def _static(text: str) -> str:
    return text.replace("    at: {anchor: center}", "    at: {anchor: center}\n    static: true")


def test_a_static_pattern_may_colour_by_copy(write_design, bag):
    """`copy` is fixed per copy, not a reading: a static buffer filled once
    still shows it correctly."""
    text = _static(_with_color(RADIAL_RING, "copy == 0 ? palette.accent : palette.fg", "part"))
    face = load(write_design(design(text)), bag)
    assert face is not None, bag.render()


def test_a_static_pattern_may_not_read_the_date(write_design, bag):
    """The contrast: `date.weekday` changes, and a static buffer would freeze
    it -- the ordinary static-binding error, reached through the pattern's
    `colors`."""
    text = _static(_with_color(RADIAL_RING, "date.weekday == 1 ? palette.accent : palette.fg",
                               "part"))
    bad = errors(design(text), bag, write_design)
    assert len(bad) == 1
    assert bad[0].code == "static"
    assert "date.weekday" in bad[0].message


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
    `wfb/emit/monkeyc/rotated.py`).  `BARREL_FILES`' own promise
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


# -- codegen: where the colour is set -------------------------------------------


def _view_for(text: str, write_design, bag, db, tmp_path) -> str:
    from wfb.emit.project import generate

    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    files = generate(resolved.face, [device], tmp_path, {device.id: resolved.fonts}).files()
    (view_path,) = [p for p in files if p.endswith("View.mc")]
    return files[view_path]


def _loop_body(view: str) -> str:
    return view.split("for (var i = 0; i <", 1)[1].split("\n        }\n", 1)[0]


def test_one_plain_colour_is_still_hoisted_out_of_the_loop(write_design, bag, db, tmp_path):
    view = _view_for(design(LINEAR_ROW), write_design, bag, db, tmp_path)
    assert "dc.setColor(Palette.FG, Graphics.COLOR_TRANSPARENT);  // hoisted: one colour" in view
    assert "setColor" not in _loop_body(view)


def test_a_colour_reading_copy_is_set_inside_the_loop(write_design, bag, db, tmp_path):
    """One distinct colour *text* is not one colour when it reads `copy`:
    hoisted above the loop it would reference `i` before it exists (a
    monkeyc error), so it is set per copy instead."""
    text = LINEAR_ROW.replace("color: palette.fg",
                              'color: "copy == 1 ? palette.accent : palette.fg"')
    view = _view_for(design(text), write_design, bag, db, tmp_path)
    assert "hoisted: one colour" not in view
    assert ("dc.setColor(((i == 1) ? Palette.ACCENT : Palette.FG), "
            "Graphics.COLOR_TRANSPARENT);") in _loop_body(view)


def test_a_date_reading_is_declared_once_before_the_loop(write_design, bag, db, tmp_path):
    """`date.weekday` reads through its own FORMAT_SHORT reader, cast to
    Number for -l 3, into a local declared at the top of the method -- not
    re-read per copy."""
    text = LINEAR_ROW.replace(
        "color: palette.fg",
        'color: "copy == (date.weekday + 5) % 7 ? palette.accent : palette.fg"')
    view = _view_for(design(text), write_design, bag, db, tmp_path)
    before_loop = view.split("for (var i = 0; i <", 1)[0]
    assert "var dateWeekday = dateShort.day_of_week as Number;" in before_loop
    assert "day_of_week" not in _loop_body(view)
    assert "dateShort as Gregorian.Info" in view  # the method's reader parameter
    assert "Gregorian.info(Time.now(), Time.FORMAT_SHORT)" in view


# -- codegen: gated part `visible:` (B6) ----------------------------------------


#: Three parts, same colour on the first (gated) and third (ungated) -- the
#: precedent B6 names: "[A gated, color X] [B ungated, color X] -- B must
#: not depend on A's branch."  A different colour on the middle part
#: (`palette.bg`) keeps colour hoisting off, so each part's `dc.setColor`
#: call is emitted (or, for the third part, *not* re-emitted, because the
#: colour did not change) exactly the way a real multi-colour pattern would.
GATED_ORDER = """  - id: bars
    type: pattern
    pattern: linear
    at: {anchor: center}
    count: 3
    step: {dx: 10px}
    when_absent: hide
    parts:
      - {shape: circle, radius: 6px, color: palette.bg}
      - shape: rectangle
        size: {width: 4px, height: 4px}
        color: palette.fg
        visible: "copy <= activity.move_bar_level - 1"
      - {shape: rectangle, size: {width: 2px, height: 2px}, color: palette.fg}
"""


def test_a_gated_parts_draw_call_sits_inside_its_if(write_design, bag, db, tmp_path):
    view = _view_for(design(GATED_ORDER), write_design, bag, db, tmp_path)
    body = _loop_body(view)
    assert "// visible: copy <= activity.move_bar_level - 1" in body
    gate_index = body.index("if (")
    draw_index = body.index("Layout.BARS_1_")  # the gated rectangle's own constants
    assert gate_index < draw_index, "the gated part's own draw call must sit after its 'if'"


def test_a_gated_parts_setcolor_sits_before_the_gate_not_inside_it(write_design, bag, db, tmp_path):
    """B6's own worked example: a broken implementation that moved the
    gated part's `dc.setColor` *inside* its `if` would leave the third
    (ungated, same-colour) part's pen colour unset whenever the gate is
    false at runtime -- this fails against exactly that mistake, because
    `setColor(Palette.FG...)` would then appear *after* `if (`, not before
    it, and it is emitted only once (not re-emitted for the third part)."""
    view = _view_for(design(GATED_ORDER), write_design, bag, db, tmp_path)
    body = _loop_body(view)
    lines = body.splitlines()
    set_fg = [i for i, line in enumerate(lines) if "setColor(Palette.FG" in line]
    gates = [i for i, line in enumerate(lines) if line.strip().startswith("if (")]
    assert len(set_fg) == 1, lines  # not re-set for the third, ungated part
    assert len(gates) == 1, lines
    assert set_fg[0] < gates[0], "Palette.FG must be set before the gate, not inside it"


def test_a_nullable_source_read_by_part_visible_is_guarded_before_the_loop(
        write_design, bag, db, tmp_path):
    """The element-level null guard `_emit_element_method` already emits
    generically for every element (from `element.expressions()`) covers a
    part `visible:`'s own nullable sources too, the same as a colour's --
    verified here, not reimplemented."""
    text = _with_when_absent(_with_part_visible(RADIAL_RING, "copy <= activity.move_bar_level - 1"))
    view = _view_for(design(text), write_design, bag, db, tmp_path)
    before_loop = view.split("for (var i = 0; i <", 1)[0]
    assert "var activityMoveBarLevel = " in before_loop
    assert "if (activityMoveBarLevel == null)" in before_loop
    assert "return;" in before_loop


CONST_FALSE_PART = """  - id: bars2
    type: pattern
    pattern: linear
    at: {anchor: center}
    count: 2
    step: {dx: 10px}
    parts:
      - {shape: circle, radius: 4px, color: palette.fg, visible: "false"}
      - {shape: circle, radius: 2px, color: palette.bg}
"""


def test_a_constant_false_visible_part_emits_no_draw_code(write_design, bag, db, tmp_path):
    view = _view_for(design(CONST_FALSE_PART), write_design, bag, db, tmp_path)
    body = _loop_body(view)
    assert "Palette.FG" not in body  # the dead part's own colour never appears
    assert "fillCircle" in body  # the live (background) part still draws


def test_a_constant_false_visible_part_warns_dead_element(lint_run):
    bag = lint_run(design(CONST_FALSE_PART))
    findings = [d for d in bag.items if d.code == "dead-element"]
    assert len(findings) == 1, [d.message for d in bag.items]
    assert "bars2.parts[0]" in findings[0].message
    assert "never drawn" in findings[0].message


CONST_TRUE_PART = """  - id: bars3
    type: pattern
    pattern: linear
    at: {anchor: center}
    count: 2
    step: {dx: 10px}
    parts:
      - {shape: circle, radius: 4px, color: palette.fg, visible: "true"}
"""


def test_a_constant_true_visible_part_emits_no_gate(write_design, bag, db, tmp_path):
    view = _view_for(design(CONST_TRUE_PART), write_design, bag, db, tmp_path)
    body = _loop_body(view)
    assert "if (" not in body
    assert "fillCircle" in body


# -- lint: safe-area on a radial ring of non-text parts (fix B contrast) ------
#
# Unlike a `shape: text` part (`tests/test_pattern_text_curve.py`'s own
# "safe-area" section), a polygon/line/circle/arc pattern part's own reach
# was already exact before that fix (`Resolver._resolve_hand_part` derives
# it straight from the part's own rotation-invariant geometry, never from
# an AABB's corners) -- these two tests are a regression guard confirming
# the `_pattern_part_ink` refactor (fix B) left that already-correct path
# alone, not a "driven red" case for this fix itself.


def _tick_ring(inner_px: int, outer_px: int, count: int = 12) -> str:
    return f"""  - id: ticks
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: {count}
    color: palette.fg
    parts:
      - {{shape: line, at: {{dy: -{inner_px}px}}, to: {{dy: -{outer_px}px}}, thickness: 2px}}
"""


def test_radial_tick_ring_inside_the_disc_does_not_warn_safe_area(lint_run):
    """A full 12-tick ring reaching to 125px on `fenix8solar47mm` (130px
    minor radius, 127.4px visible limit) -- comfortably inside."""
    bag = lint_run(design(_tick_ring(117, 125)))
    assert not any(d.code == "safe-area" for d in bag.items), bag.render()


def test_radial_tick_ring_pushed_out_warns_safe_area(lint_run):
    """The same ring, reaching to 127px -- just past the 127.4px visible
    limit, so `safe-area` must still fire for a ring of plain shapes
    exactly the way it always did."""
    bag = lint_run(design(_tick_ring(119, 127)))
    assert any(d.code == "safe-area" for d in bag.items), bag.render()
