"""`visible:` -- conditional visibility, and the group conjunction behind it.

Three things are being pinned down here, and they are worth naming because
each was a real decision rather than an obvious consequence:

1. **Absent means hidden.**  A nullable source read by `visible:` contributes a
   `== null` to the *same* guard as the condition, and takes no `when_absent:`
   policy -- there is no substitute for existence.
2. **A group's condition is pushed into its subtree by the IR**, not by the
   emitter.  A `group` emits no draw method and `wfb.layout` flattens the tree,
   so the conjunction has to happen while the tree still exists.  What that
   buys is everything downstream working unchanged: the read plan hoists the
   group's readers, the preview evaluates one merged AST, and the linter folds
   the whole conjunction.  These tests assert that from the outside.
3. **`dead-element` reports the outermost dead element only**, because a dead
   group would otherwise repeat one mistake once per descendant.

Needs the device files (font baking and per-device layout), not the Garmin
toolchain -- the real `monkeyc` build lives in `tests/test_build.py`.
"""

from __future__ import annotations

import pytest

from tests.test_diagnostics import load
from wfb import lint
from wfb.emit.project import generate
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

DESIGN = """
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: [fenix8solar47mm]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
{elements}
"""

#: A condition over a source that is never null (`System.ClockTime.sec`).
NON_NULLABLE = """
  - id: label
    type: text
    text: "X"
    font: FONT_TINY
    at: {anchor: center}
    color: palette.fg
    visible: "time.second < 30"
"""

#: A condition over a nullable source -- absence must hide the element.
NULLABLE = """
  - id: label
    type: text
    text: "X"
    font: FONT_TINY
    at: {anchor: center}
    color: palette.fg
    visible: "activity.steps > 500"
"""

#: A group condition, a nested group condition, and a leaf condition, so the
#: three-way conjunction is visible in one generated method.
NESTED = """
  - id: outer
    type: group
    at: {anchor: center}
    size: {width: 80%, height: 40%}
    visible: "time.hour >= 18"
    children:
      - id: mid
        type: group
        at: {anchor: center}
        size: {width: 100%, height: 50%}
        visible: "not device.do_not_disturb"
        children:
          - id: leaf
            type: text
            text: "X"
            font: FONT_TINY
            at: {anchor: center}
            color: palette.fg
            visible: "activity.steps > 500"
"""


def _face(write_design, bag, elements: str):
    face = load(write_design(DESIGN.format(elements=elements)), bag)
    return face


def _resolved(write_design, bag, db, elements: str):
    face = _face(write_design, bag, elements)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device, device.minor_radius))


def _view(write_design, bag, db, tmp_path, elements: str) -> str:
    face = _face(write_design, bag, elements)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = bake_fonts(face, device, device.minor_radius)
    project = generate(face, [device], tmp_path, {device.id: baked})
    return project.files()["source/TestView.mc"]


def _element(face, element_id):
    return next(e for e in face.walk() if e.id == element_id)


# -- typing -----------------------------------------------------------------


def test_a_non_boolean_condition_is_an_error_naming_the_type(write_design, bag):
    """Guessing a truthiness rule is how a face shows something nobody asked
    for -- and Monkey C has no truthy Number either, so the generated code
    would not even compile."""
    assert _face(write_design, bag, NULLABLE.replace(
        'visible: "activity.steps > 500"', "visible: activity.steps")) is None
    assert not bag.ok()
    diag = next(d for d in bag.errors if d.code == "type")
    assert "visible must be a boolean" in diag.message
    assert "number?" in diag.message


def test_a_string_condition_is_also_refused(write_design, bag):
    _face(write_design, bag, NULLABLE.replace(
        'visible: "activity.steps > 500"', "visible: date.month"))
    diag = next(d for d in bag.errors if d.code == "type")
    assert "got string" in diag.message


def test_a_comparison_is_accepted_and_typed_boolean(write_design, bag):
    face = _face(write_design, bag, NON_NULLABLE)
    assert face is not None, bag.render()
    from wfb.catalog import Type

    assert _element(face, "label").visible.value.type is Type.BOOLEAN


# -- absence ----------------------------------------------------------------


def test_a_nullable_condition_needs_no_when_absent(write_design, bag):
    """`when_absent:` chooses a substitute *value*; existence has none, so a
    nullable `visible:` must not trip the "policy required" error the same
    source would trip in `value:`."""
    face = _face(write_design, bag, NULLABLE)
    assert face is not None, bag.render()
    assert bag.ok(), bag.render()
    assert _element(face, "label").visible.nullable


def test_a_nullable_condition_folds_its_null_check_into_one_guard(
        write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, NULLABLE)
    assert "if (activitySteps == null || !(activitySteps > 500))" in view
    assert "// visible: activity.steps > 500 -- absent means hidden" in view


def test_a_non_nullable_condition_gets_no_null_check(write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, NON_NULLABLE)
    assert "if (!(timeSecond < 30))" in view
    assert "timeSecond == null" not in view


def test_a_visible_source_is_not_null_checked_twice(write_design, bag, db, tmp_path):
    """The same reading in `visible:` and `color:`: the visibility guard has
    already returned on null, so a second `== null` on that local would be dead
    code a reviewer would (rightly) ask about."""
    view = _view(write_design, bag, db, tmp_path, """
  - id: label
    type: text
    text: "X"
    font: FONT_TINY
    at: {anchor: center}
    color: "activity.steps > 9000 ? palette.fg : palette.bg"
    when_absent: hide
    visible: "activity.steps > 500"
""")
    assert view.count("activitySteps == null") == 1


def test_a_placeholder_policy_does_not_re_guard_a_visible_source(
        write_design, bag, db, tmp_path):
    """The `when_absent: placeholder` path guards colour bindings separately
    from the value's (a colour has no placeholder).  A source read by
    `visible:` must not pick up a guard there either: the visibility guard has
    already returned on null."""
    view = _view(write_design, bag, db, tmp_path, """
  - id: label
    type: text
    value: activity.steps
    format: "{:d}"
    when_absent: placeholder
    placeholder: "--"
    font: FONT_TINY
    at: {anchor: center}
    color: "activity.calories > 100 ? palette.fg : palette.bg"
    visible: "activity.calories > 50"
""")
    assert bag.ok(), bag.render()
    assert view.count("activityCalories == null") == 1
    # The placeholder itself is still reachable: `activity.steps` is absent
    # independently of `activity.calories`.
    assert 'var text = "--";' in view


def test_a_placeholder_behind_its_own_visible_condition_is_reported(write_design, bag):
    """`visible:` reading the same nullable source as `value:` makes the
    placeholder unreachable -- the element is already gone.  Same reasoning
    (and same check) as a nullable colour reading it."""
    _face(write_design, bag, """
  - id: label
    type: text
    value: activity.steps
    format: "{:d}"
    when_absent: placeholder
    placeholder: "--"
    font: FONT_TINY
    at: {anchor: center}
    color: palette.fg
    visible: "activity.steps > 500"
""")
    diag = next(d for d in bag.items if d.code == "when-absent")
    assert "can never be drawn" in diag.message
    assert "'visible'" in diag.message


def test_a_visible_binding_still_derives_its_permission(write_design, bag):
    """`visible:` goes through `Element.expressions()` like any other binding,
    so permission derivation, barrel collection and reader hoisting all see
    it."""
    face = _face(write_design, bag, """
  - id: label
    type: text
    text: "X"
    font: FONT_TINY
    at: {anchor: center}
    color: palette.fg
    visible: "user.vo2max_running > 40"
""")
    assert face is not None, bag.render()
    assert "UserProfile" in face.requirements().permissions


# -- groups -----------------------------------------------------------------


def test_a_group_condition_reaches_every_descendant(write_design, bag):
    face = _face(write_design, bag, NESTED)
    assert face is not None, bag.render()
    leaf = _element(face, "leaf").visible
    assert set(leaf.sources) == {"activity.steps", "device.do_not_disturb", "time.hour"}
    # Right-associated: the inner group pushed into the leaf first, then the
    # outer group pushed into that -- which is what makes nesting compose.
    assert leaf.text == "(time.hour >= 18) and " \
                        "((not device.do_not_disturb) and (activity.steps > 500))"


def test_a_group_condition_reaches_a_child_with_none_of_its_own(write_design, bag):
    face = _face(write_design, bag, NESTED.replace(
        '            visible: "activity.steps > 500"\n', ""))
    assert face is not None, bag.render()
    leaf = _element(face, "leaf").visible
    assert leaf is not None
    assert set(leaf.sources) == {"device.do_not_disturb", "time.hour"}


def test_the_conjunction_is_a_real_expression_the_read_plan_can_hoist(
        write_design, bag, db, tmp_path):
    """The point of building an `Expression` rather than splicing code: the
    leaf's method takes the group's readers as parameters and null-checks the
    group's nullable local, with no group-aware code anywhere in the
    emitter."""
    view = _view(write_design, bag, db, tmp_path, NESTED)
    assert "private function drawLeaf(dc as Dc, activity as ActivityMonitor.Info, " \
           "settings as System.DeviceSettings, clock as System.ClockTime) as Void" in view
    assert ("if (activitySteps == null || !((timeHour >= 18) "
            "&& ((!deviceDoNotDisturb) && (activitySteps > 500))))") in view


def test_a_group_emits_no_method_of_its_own(write_design, bag, db, tmp_path):
    """Which is the whole reason the conjunction happens in the IR."""
    view = _view(write_design, bag, db, tmp_path, NESTED)
    assert "drawOuter" not in view
    assert "drawMid" not in view


# -- constant folding and the lint ------------------------------------------


def test_a_constant_true_condition_emits_no_guard(write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, NON_NULLABLE.replace(
        'visible: "time.second < 30"', 'visible: "1 < 2"'))
    assert "// visible: 1 < 2 -- always true, nothing to check" in view
    assert "return;" not in view.split("private function drawLabel")[1]


def test_dead_element_is_reported_for_a_constant_false(write_design, bag, db):
    resolved = _resolved(write_design, bag, db, NON_NULLABLE.replace(
        'visible: "time.second < 30"', 'visible: "false"'))
    lint.run(resolved, bag)
    diag = next(d for d in bag.items if d.code == "dead-element")
    assert "never drawn" in diag.message
    assert diag.severity.value == "warning"


def test_dead_element_is_not_reported_for_a_constant_true(write_design, bag, db):
    """Too noisy: a `true` is a normal thing to write while iterating, and is
    also what a folded condition legitimately reduces to."""
    resolved = _resolved(write_design, bag, db, NON_NULLABLE.replace(
        'visible: "time.second < 30"', 'visible: "true"'))
    lint.run(resolved, bag)
    assert not [d for d in bag.items if d.code == "dead-element"]


DEAD_SUBTREE = """
  - id: outer
    type: group
    at: {anchor: center}
    size: {width: 80%, height: 40%}
    visible: "false"
    children:
      - id: kid_a
        type: text
        text: "A"
        font: FONT_TINY
        at: {anchor: left}
        color: palette.fg
      - id: kid_group
        type: group
        at: {anchor: right}
        size: {width: 20%, height: 100%}
        children:
          - id: kid_b
            type: text
            text: "B"
            font: FONT_TINY
            at: {anchor: center}
            color: palette.fg
"""


def test_a_dead_group_is_reported_once_not_once_per_descendant(write_design, bag, db):
    """Every element beneath a dead group inherits the same constant `false`
    (a child with no `visible:` of its own gets the group's expression object
    verbatim), so without the subtree skip this design would report the one
    mistake four times."""
    resolved = _resolved(write_design, bag, db, DEAD_SUBTREE)
    assert [p.id for p in resolved.items if p.element.visible is not None] == \
        ["outer", "kid_a", "kid_group", "kid_b"]
    lint.run(resolved, bag)
    dead = [d for d in bag.items if d.code == "dead-element"]
    assert len(dead) == 1
    assert dead[0].message.startswith("outer:")


def test_dead_element_is_suppressible(write_design, bag, db):
    resolved = _resolved(write_design, bag, db, NON_NULLABLE.replace(
        'visible: "time.second < 30"',
        'visible: "false"\n    lint: {allow: [dead-element], reason: "wip"}'))
    lint.run(resolved, bag)
    assert not [d for d in bag.items if d.code == "dead-element"]
    assert bag.ok(), bag.render()


def test_dead_element_is_registered_in_both_lint_tables():
    assert "dead-element" in lint.ALL_CODES
    assert "dead-element" in lint.SUPPRESSIBLE


# -- preview ----------------------------------------------------------------


def _pixels(resolved, **sample):
    return list(render(resolved, PreviewOptions(
        scale=1, mask_shape=False, sample=sample)).get_flattened_data())


def test_preview_hides_an_element_whose_condition_is_false(write_design, bag, db):
    resolved = _resolved(write_design, bag, db, NULLABLE)
    assert _pixels(resolved, **{"activity.steps": 9000}) != \
        _pixels(resolved, **{"activity.steps": 100})


def test_preview_hides_an_element_whose_condition_is_absent(write_design, bag, db):
    """Absent means hidden on the host too -- `expr.evaluate` returns None when
    any input is missing, which is exactly the `== null` half of the device's
    guard."""
    resolved = _resolved(write_design, bag, db, NULLABLE)
    assert _pixels(resolved, **{"activity.steps": None}) == \
        _pixels(resolved, **{"activity.steps": 100})
    assert _pixels(resolved, **{"activity.steps": None}) != \
        _pixels(resolved, **{"activity.steps": 9000})


def test_preview_applies_a_group_condition_to_the_subtree(write_design, bag, db):
    """No tree walking in the preview: the conjunction is already in the leaf's
    own expression, which is what keeps the two renderers from disagreeing
    about a subtree."""
    resolved = _resolved(write_design, bag, db, NESTED)
    shown = {"time.hour": 20, "device.do_not_disturb": False, "activity.steps": 9000}
    assert _pixels(resolved, **shown) != _pixels(resolved, **dict(shown, **{"time.hour": 9}))
    assert _pixels(resolved, **dict(shown, **{"time.hour": 9})) == \
        _pixels(resolved, **dict(shown, **{"device.do_not_disturb": True}))


# -- other element kinds ----------------------------------------------------


def test_visible_works_on_a_shape_and_an_icon(write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, """
  - id: dot
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 10px
    color: palette.fg
    visible: "system.charging"
  - id: bolt
    type: icon
    icon: battery
    at: {anchor: center, dy: 20%}
    size: 8%r
    color: palette.fg
    visible: "not system.charging"
""")
    # `_negatable` adds brackets only where `expr.emit` did not, and a `not`
    # condition is un-negated outright rather than becoming `!(!x)`.
    assert "if (!(systemCharging))" in view
    assert "if (systemCharging)" in view


def test_the_generated_doc_comment_says_when_the_element_draws(
        write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, NULLABLE)
    assert ("//! Drawn only when `activity.steps > 500` "
            "(absent readings count as hidden).") in view


@pytest.mark.parametrize("kind", ["group", "shape", "text", "progress", "icon", "graph"])
def test_the_schema_offers_visible_on_every_element_type(repo_root, kind):
    import json

    schema = json.loads((repo_root / "schema" / "wfb-face-1.schema.json").read_text())
    branch = schema["$defs"][f"{kind}Element"]
    assert branch["properties"]["visible"] == {"$ref": "#/$defs/visible"}
