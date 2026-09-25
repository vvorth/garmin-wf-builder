"""`Element.bound_expressions()`/`.color_roles()` (plan 19 A2): one place
that tags "which expression is this" and "which colours does this element
draw", read by `ReadPlan`/`Builder._hold_auto_sources`/the absence checks
and by `wfb.lint`'s palette-declaration and contrast checks respectively,
instead of each re-deriving it its own way.

Every `bound_expressions()` test below reconstructs the *old*
`_own_expressions()`/`expressions()` formula for that kind by hand (the
exact tuple/filter shape the pre-refactor code used) and checks the new
method against it, so a reordering would fail here even though nothing
downstream happens to notice.
"""

from __future__ import annotations

from wfb.build import load
from wfb.ir import (
    ComplicationSlot, Graph, HandsElement, IconElement, PatternElement, Progress, Shape, Text,
    ROLE_COLOR, ROLE_FALLBACK, ROLE_ICON_COLOR, ROLE_MAX, ROLE_MIN, ROLE_OUTLINE_COLOR,
    ROLE_PART_TEXT, ROLE_PART_VISIBLE, ROLE_TRACK_COLOR, ROLE_VALUE, ROLE_VISIBLE,
)

HEAD = """format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
  accent: "#FF5500"
"""


def _face(body: str, write_design, bag):
    face = load(write_design(HEAD + body), bag)
    assert face is not None, bag.render()
    return face


def _by_id(face, element_id: str):
    return next(e for e in face.walk() if e.id == element_id)


# -- bound_expressions(): same expressions, same order as the old
# `_own_expressions()`/`expressions()` -------------------------------------


TEXT_DESIGN = """
elements:
  - id: label
    type: text
    value: system.battery
    format: "{:.0f}"
    when_absent: fallback
    fallback: 0
    color: palette.fg
    outline: {color: palette.bg, width: 2}
    visible: "system.battery > 50"
    at: {anchor: center}
    aod:
      color: palette.bg
"""


def test_text_bound_expressions_order(write_design, bag):
    face = _face(TEXT_DESIGN, write_design, bag)
    label = _by_id(face, "label")
    assert isinstance(label, Text)

    # the pre-A2 formula, by hand
    expected = [e for e in (label.value, label.color, label.fallback) if e]
    expected.append(label.outline.color)
    expected.append(label.visible)
    assert label.expressions() == expected

    roles = label.bound_expressions()
    assert [e for _, e in roles] == expected
    assert [r for r, _ in roles] == [
        ROLE_VALUE, ROLE_COLOR, ROLE_FALLBACK, ROLE_OUTLINE_COLOR, ROLE_VISIBLE,
    ]
    assert Text.VALUE_ROLES == frozenset({ROLE_VALUE})


PROGRESS_DESIGN = """
elements:
  - id: bar
    type: progress
    style: bar
    value: system.battery
    max: 100
    when_absent: fallback
    fallback: 0.5
    color: palette.fg
    track_color: palette.bg
    size: {width: 40px, height: 10px}
    at: {anchor: center}
"""


def test_progress_bound_expressions_order(write_design, bag):
    face = _face(PROGRESS_DESIGN, write_design, bag)
    bar = _by_id(face, "bar")
    assert isinstance(bar, Progress)

    expected = [e for e in (bar.value, bar.maximum, bar.color, bar.track_color, bar.fallback) if e]
    assert bar.expressions() == expected

    roles = bar.bound_expressions()
    assert [e for _, e in roles] == expected
    assert [r for r, _ in roles] == [
        ROLE_VALUE, ROLE_MAX, ROLE_COLOR, ROLE_TRACK_COLOR, ROLE_FALLBACK,
    ]
    assert Progress.VALUE_ROLES == frozenset({ROLE_VALUE, ROLE_MAX})


ICON_DESIGN = """
elements:
  - id: gauge
    type: icon
    icon_for: weather.condition
    color: palette.fg
    size: 20px
    at: {anchor: center}
"""


def test_icon_bound_expressions_order(write_design, bag):
    face = _face(ICON_DESIGN, write_design, bag)
    gauge = _by_id(face, "gauge")
    assert isinstance(gauge, IconElement)

    expected = [e for e in (gauge.color, gauge.value_for) if e]
    assert gauge.expressions() == expected

    roles = gauge.bound_expressions()
    assert [e for _, e in roles] == expected
    assert [r for r, _ in roles] == [ROLE_COLOR, ROLE_VALUE]
    # an icon has no `when_absent:` at all -- nothing is a governed "value".
    assert IconElement.VALUE_ROLES == frozenset()


GRAPH_DESIGN = """
elements:
  - id: hr
    type: graph
    series: heart_rate
    range: 4h
    min: 40
    max: 180
    color: palette.fg
    size: {width: 40px, height: 30px}
    at: {anchor: center}
"""


def test_graph_bound_expressions_order(write_design, bag):
    face = _face(GRAPH_DESIGN, write_design, bag)
    hr = _by_id(face, "hr")
    assert isinstance(hr, Graph)

    expected = [e for e in (hr.color, hr.min, hr.max) if e]
    assert hr.expressions() == expected

    roles = hr.bound_expressions()
    assert [e for _, e in roles] == expected
    assert [r for r, _ in roles] == [ROLE_COLOR, ROLE_MIN, ROLE_MAX]
    assert Graph.VALUE_ROLES == frozenset()


COMPLICATION_SLOT_DESIGN = """
config:
  data:
    top:
      default: complication.steps
      choices: [complication.steps, complication.heart_rate]
elements:
  - id: reading
    type: complication_slot
    slot: config.data.top
    at: {anchor: center}
    icon_size: 8%r
    color: palette.fg
    icon_color: palette.bg
    label: short
"""


def test_complication_slot_bound_expressions_order(write_design, bag):
    face = _face(COMPLICATION_SLOT_DESIGN, write_design, bag)
    reading = _by_id(face, "reading")
    assert isinstance(reading, ComplicationSlot)

    expected = [e for e in (reading.color, reading.icon_color) if e]
    assert reading.expressions() == expected
    assert [r for r, _ in reading.bound_expressions()] == [ROLE_COLOR, ROLE_ICON_COLOR]
    assert ComplicationSlot.VALUE_ROLES == frozenset()


PATTERN_DESIGN = """
elements:
  - id: dial
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 2
    color: palette.fg
    aod:
      color: palette.bg
    parts:
      - shape: text
        value: copy
        format: "{:.0f}"
        font: FONT_MEDIUM
        color: palette.bg
        outline: {color: palette.fg, width: 2}
        visible: "copy == 0"
      - shape: circle
        radius: 5px
        color: palette.fg
"""


def test_pattern_bound_expressions_order(write_design, bag):
    face = _face(PATTERN_DESIGN, write_design, bag)
    dial = _by_id(face, "dial")
    assert isinstance(dial, PatternElement)

    expected = list(dial.colors)
    for part in dial.parts:
        if part.visible is not None:
            expected.append(part.visible)
        if part.shape == "text" and part.text_value is not None:
            expected.append(part.text_value)
    assert dial.expressions() == expected

    roles = dial.bound_expressions()
    assert [e for _, e in roles] == expected
    assert [r for r, _ in roles] == (
        [ROLE_COLOR] * len(dial.colors) + [ROLE_PART_VISIBLE, ROLE_PART_TEXT]
    )
    assert PatternElement.VALUE_ROLES == frozenset()
    # exactly one part carries a visible/text_value pair (the text part);
    # the circle part contributes neither.
    assert len(dial.colors) == 4


# -- color_roles(): "which colours does this element draw", one place ------


def test_shape_color_roles(write_design, bag):
    design = """
elements:
  - id: box
    type: shape
    shape: rectangle
    size: {width: 10px, height: 10px}
    color: palette.fg
    at: {anchor: center}
"""
    face = _face(design, write_design, bag)
    box = _by_id(face, "box")
    assert isinstance(box, Shape)
    roles = box.color_roles()
    assert len(roles) == 1
    assert roles[0].label == "box"
    assert roles[0].expression is box.color
    assert roles[0].role == "ink"
    assert roles[0].is_glyph is False  # a shape's ink may match its backdrop
    assert roles[0].aod is False


def test_text_color_roles_ink_ring_and_aod_override(write_design, bag):
    face = _face(TEXT_DESIGN, write_design, bag)
    label = _by_id(face, "label")
    roles = label.color_roles()
    assert [(r.label, r.expression, r.role, r.is_glyph, r.aod) for r in roles] == [
        ("label", label.color, "ink", True, False),
        ("label", label.outline.color, "ring", True, False),
        ("label", label.aod.color, "ink", True, True),
    ]


def test_progress_color_roles(write_design, bag):
    face = _face(PROGRESS_DESIGN, write_design, bag)
    bar = _by_id(face, "bar")
    roles = bar.color_roles()
    assert [(r.label, r.expression, r.role) for r in roles] == [
        ("bar", bar.color, "ink"), ("bar", bar.track_color, "track"),
    ]
    assert all(r.is_glyph for r in roles)


def test_complication_slot_color_roles(write_design, bag):
    face = _face(COMPLICATION_SLOT_DESIGN, write_design, bag)
    reading = _by_id(face, "reading")
    roles = reading.color_roles()
    assert [(r.label, r.expression, r.role) for r in roles] == [
        ("reading", reading.color, "ink"), ("reading", reading.icon_color, "icon"),
    ]


def test_pattern_color_roles_parts_and_aod(write_design, bag):
    face = _face(PATTERN_DESIGN, write_design, bag)
    dial = _by_id(face, "dial")
    roles = dial.color_roles()
    assert [(r.label, r.role, r.is_glyph, r.aod) for r in roles] == [
        ("dial", "ink", True, False),
        ("dial.parts[0]", "ink", True, False),
        ("dial.parts[0]", "ring", True, False),
        ("dial.parts[1]", "ink", False, False),
        ("dial", "ink", True, True),
    ]
    # the *set* of colours drawn (ink + ring, awake only) is exactly
    # `PatternElement.colors` -- `wfb.kinds.pattern.PatternKind.build`'s own dedup.
    drawn = [r.expression for r in roles if not r.aod]
    assert len(drawn) == len(dial.colors)
    assert all(any(e is c for e in drawn) for c in dial.colors)
    assert all(any(c is e for c in dial.colors) for e in drawn)


HANDS_DESIGN = """
hands:
  classic:
    hour:
      color: palette.fg
      parts:
        - {shape: polygon, points: [{dx: -3%r, dy: 6%r}, {dy: -44%r}, {dx: 3%r, dy: 6%r}]}
    minute:
      color: palette.accent
      parts:
        - {shape: rectangle, at: {dy: -30%r}, size: {width: 3%r, height: 70%r}}
elements:
  - id: main_hands
    type: hands
    hands: classic
    at: {anchor: center}
    aod:
      color: palette.bg
"""


def test_hands_color_roles_and_aod_override(write_design, bag):
    face = _face(HANDS_DESIGN, write_design, bag)
    hands = _by_id(face, "main_hands")
    assert isinstance(hands, HandsElement)
    assert len(hands.colors) == 2  # hour, minute -- each part reuses its hand's colour

    roles = hands.color_roles()
    assert [(r.label, r.expression, r.role, r.is_glyph, r.aod) for r in roles] == [
        ("main_hands", hands.colors[0], "ink", False, False),
        ("main_hands", hands.colors[1], "ink", False, False),
        ("main_hands", hands.aod.color, "ink", False, True),
    ]
