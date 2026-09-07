"""Stage 2: data sources, null handling, refresh tiers, fonts and icons."""

import pytest

from tests.test_diagnostics import load

BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
"""


def design(*elements: str) -> str:
    return BASE + "".join(elements)


STEPS_TEXT = """
  - id: steps
    type: text
    value: activity.steps
    format: "{:d}"
    color: palette.fg
    at: {anchor: center}
"""


def test_a_nullable_source_requires_when_absent(write_design, bag):
    """Absence is the normal case here, so the format refuses to guess."""
    load(write_design(design(STEPS_TEXT)), bag)
    assert any(d.code == "when-absent" for d in bag.errors)
    note = " ".join(bag.errors[0].notes)
    assert "hide" in note and "placeholder" in note and "fallback" in note


def test_when_absent_hide_satisfies_it(write_design, bag):
    face = load(write_design(design(STEPS_TEXT + "    when_absent: hide\n")), bag)
    assert bag.ok(), bag.render()
    assert face is not None


def test_placeholder_policy_needs_a_placeholder(write_design, bag):
    load(write_design(design(STEPS_TEXT + "    when_absent: placeholder\n")), bag)
    assert not bag.ok()
    assert "placeholder" in bag.errors[0].message


def test_a_fallback_may_not_itself_be_absent(write_design, bag):
    load(write_design(design(
        STEPS_TEXT
        + "    when_absent: fallback\n"
        + "    fallback: activity.calories\n"
    )), bag)
    assert any("fallback" in d.message for d in bag.errors)


def test_when_absent_on_a_non_null_source_is_a_note_not_an_error(write_design, bag):
    load(write_design(design("""
  - id: battery
    type: text
    value: system.battery
    format: "{:.0f}"
    color: palette.fg
    at: {anchor: center}
    when_absent: hide
""")), bag)
    assert bag.ok(), bag.render()
    assert any(d.code == "when-absent" for d in bag.items)


def test_low_power_may_not_read_a_slow_tier_source(write_design, bag, monkeypatch):
    """onPartialUpdate overrun disables partial updates permanently, so this is an error."""
    from wfb import catalog

    slow = catalog.Source(
        path="weather.temperature", type=catalog.Type.NUMBER, reader="settings",
        field_name="temperature", nullable=True, tier=catalog.Tier.SLOW,
    )
    monkeypatch.setitem(catalog.CATALOG, "weather.temperature", slow)
    load(write_design(design("""
  - id: temp
    type: text
    value: weather.temperature
    format: "{:d}"
    color: palette.fg
    at: {anchor: center}
    modes: [active, low_power]
    when_absent: hide
""")), bag)
    assert any(d.code == "refresh-tier" for d in bag.errors), bag.render()


def test_low_power_may_not_read_the_real_weather_condition_source(write_design, bag):
    """Same check, against a real slow-tier source rather than a fabricated
    one -- weather.* is the first real one this project has."""
    load(write_design(design("""
  - id: temp
    type: text
    value: weather.condition
    format: "{:d}"
    color: palette.fg
    at: {anchor: center}
    modes: [active, low_power]
    when_absent: hide
""")), bag)
    assert any(d.code == "refresh-tier" for d in bag.errors), bag.render()


def test_low_power_may_not_read_a_real_complication_source(write_design, bag):
    """Same check again, against `event`-tier this time -- a complication is
    just as unreadable under onPartialUpdate's budget as a `slow` read is: the
    check in wfb/ir.py's `_check_tiers` is `tier is not Tier.FRAME`, not
    `is Tier.SLOW`, so this must reject EVENT too, not just SLOW."""
    load(write_design(design("""
  - id: bb
    type: text
    value: body_battery.current
    format: "{}"
    color: palette.fg
    at: {anchor: center}
    modes: [active, low_power]
    when_absent: hide
""")), bag)
    assert any(d.code == "refresh-tier" for d in bag.errors), bag.render()


def test_low_power_may_not_bind_a_dynamic_weather_icon(write_design, bag):
    load(write_design(design("""
  - id: wicon
    type: icon
    icon_for: weather.condition
    size: 20%r
    color: palette.fg
    at: {anchor: center}
    modes: [active, low_power]
""")), bag)
    assert any(d.code == "refresh-tier" for d in bag.errors), bag.render()


def test_a_time_value_needs_a_time_format(write_design, bag):
    load(write_design(design("""
  - id: clock
    type: text
    value: time.clock
    format: "{:d}"
    color: palette.fg
    at: {anchor: center}
""")), bag)
    assert any(d.code == "format" for d in bag.errors)


def test_unknown_icon_lists_the_catalogue(write_design, bag):
    load(write_design(design("""
  - id: badge
    type: icon
    icon: rocket
    size: 20px
    color: palette.fg
    at: {anchor: center}
""")), bag)
    assert any(d.code == "icon" for d in bag.errors)
    assert "steps" in " ".join(bag.errors[0].notes)


def test_icon_for_resolves_a_dynamic_glyph(write_design, bag):
    face = load(write_design(design("""
  - id: wicon
    type: icon
    icon_for: weather.condition
    size: 20%r
    color: palette.fg
    at: {anchor: center}
""")), bag)
    assert face is not None, bag.render()
    element = face.elements[0]
    assert element.is_dynamic
    assert element.icon is None
    assert element.value_for.text == "weather.condition"


@pytest.mark.parametrize("body", [
    "icon: heart\n    icon_for: weather.condition",  # both
    "",  # neither
])
def test_icon_needs_exactly_one_of_icon_or_icon_for(write_design, bag, body):
    face = load(write_design(design(f"""
  - id: wicon
    type: icon
    {body}
    size: 20%r
    color: palette.fg
    at: {{anchor: center}}
""")), bag)
    assert face is None
    assert any(d.code in ("icon", "schema") for d in bag.errors), bag.render()


@pytest.mark.parametrize("source", ["weather.condition_today", "weather.condition_tomorrow"])
def test_icon_for_accepts_every_weather_condition_source(write_design, bag, source):
    face = load(write_design(design(f"""
  - id: wicon
    type: icon
    icon_for: {source}
    size: 20%r
    color: palette.fg
    at: {{anchor: center}}
""")), bag)
    assert face is not None, bag.render()


@pytest.mark.parametrize("source", ["weather.condition + 1", "activity.steps"])
def test_icon_for_rejects_arithmetic_and_non_weather_sources(write_design, bag, source):
    """A raw Weather.CONDITION_* value is what `WfbWeather.iconGlyph` expects --
    arithmetic on it, or a source that is not a condition at all, would break
    that lookup silently rather than draw the wrong thing loudly."""
    face = load(write_design(design(f"""
  - id: wicon
    type: icon
    icon_for: "{source}"
    size: 20%r
    color: palette.fg
    at: {{anchor: center}}
""")), bag)
    assert face is None
    assert any(d.code == "icon" for d in bag.errors)


def test_unknown_font_lists_the_declared_ones(write_design, bag):
    load(write_design(design("""
  - id: label
    type: text
    text: "hi"
    font: font.nope
    color: palette.fg
    at: {anchor: center}
""")), bag)
    assert any(d.code == "font" for d in bag.errors)


def test_a_colour_property_must_be_a_colour(write_design, bag):
    load(write_design(design("""
  - id: label
    type: text
    text: "hi"
    color: activity.steps
    at: {anchor: center}
""")), bag)
    assert any(d.code == "type" for d in bag.errors)


def test_a_literal_colour_is_allowed_but_noted(write_design, bag):
    face = load(write_design(design("""
  - id: label
    type: text
    text: "hi"
    color: "#FF5500"
    at: {anchor: center}
""")), bag)
    assert bag.ok(), bag.render()
    assert any(d.code == "raw-color" for d in bag.items)


def test_permissions_are_derived_from_bindings(write_design, bag, monkeypatch):
    """The strongest single justification for the project: a missing permission
    fails silently on device, so it must not be hand-maintained."""
    from wfb import catalog

    # Positioning is one a watch face may actually hold; weather will be the
    # first real source to need it.
    monkeypatch.setitem(
        catalog.CATALOG,
        "weather.temperature",
        catalog.Source(
            path="weather.temperature", type=catalog.Type.NUMBER, reader="settings",
            field_name="temperature", nullable=True, tier=catalog.Tier.FRAME,
            permissions=("Positioning",),
        ),
    )
    face = load(write_design(design("""
  - id: temp
    type: text
    value: weather.temperature
    format: "{:d}"
    color: palette.fg
    at: {anchor: center}
    when_absent: hide
""")), bag)
    assert bag.ok(), bag.render()
    assert face.requirements().permissions == {"Positioning"}


def test_reading_heart_rate_implies_no_permission(write_design, bag):
    """It is read off Activity.getActivityInfo(), which needs none.

    The obvious-looking alternative -- Toybox.Sensor -- needs a permission that a
    watch face may not declare at all, so the manifest would be rejected.
    """
    face = load(write_design(design("""
  - id: hr
    type: text
    value: heart_rate.current
    format: "{:d}"
    color: palette.fg
    at: {anchor: center}
    when_absent: hide
""")), bag)
    assert bag.ok(), bag.render()
    assert face.requirements().permissions == set()


def test_no_binding_means_no_permissions(write_design, bag, minimal):
    face = load(write_design(minimal), bag)
    assert face.requirements().permissions == set()


def test_a_nullable_reader_is_narrowed_before_its_field_is_read(write_design, bag, db):
    """`Activity.getActivityInfo()` returns null when there is no activity.

    Guarding only the *field* would dereference the null reader one line earlier,
    which fails the strict typecheck rather than failing on the wrist.
    """
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    face = load(write_design(design("""
  - id: hr
    type: text
    value: heart_rate.current
    format: "{:d}"
    color: palette.fg
    at: {anchor: center}
    when_absent: hide
""")), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    project = generate(face, [device], write_design("").parent / "build", baked)
    view = next(v for k, v in project.files().items() if k.endswith("View.mc"))
    assert "(activityInfo != null) ? activityInfo.currentHeartRate : null" in view


def test_a_constant_divisor_is_recovered_from_the_expression(write_design, bag):
    """The overflow lint sizes the rendered result, so it needs the scale."""
    face = load(write_design(design("""
  - id: steps
    type: text
    value: "activity.steps / 1000.0"
    format: "{:.1f}k"
    color: palette.fg
    at: {anchor: center}
    when_absent: hide
""")), bag)
    assert face is not None, bag.render()
    steps = next(e for e in face.walk() if e.id == "steps")
    assert steps.value.scale == pytest.approx(0.001)


def test_an_unscaled_expression_reports_a_scale_of_one(write_design, bag):
    face = load(write_design(design("""
  - id: steps
    type: text
    value: activity.steps
    format: "{:d}"
    color: palette.fg
    at: {anchor: center}
    when_absent: hide
""")), bag)
    steps = next(e for e in face.walk() if e.id == "steps")
    assert steps.value.scale == 1.0


def test_a_date_value_rejects_a_time_format(write_design, bag):
    load(write_design(design("""
  - id: date
    type: text
    value: date.today
    format: "{:%H:%M}"
    color: palette.fg
    at: {anchor: center}
""")), bag)
    assert any(d.code == "format" for d in bag.errors)
    assert "%a" in bag.errors[0].message


def test_a_date_value_needs_a_format(write_design, bag):
    load(write_design(design("""
  - id: date
    type: text
    value: date.today
    color: palette.fg
    at: {anchor: center}
""")), bag)
    assert any("%a %e %b" in d.message for d in bag.errors)


# --------------------------------------------------------------------------
# Bug 1: when_absent: fallback actually renders, for text and progress alike


def test_text_fallback_is_emitted_not_dropped(write_design, bag, db):
    """Before this fix, codegen routed every non-'placeholder' when_absent
    policy through the same 'return;' guard as 'hide', so 'fallback:' parsed
    and validated cleanly but never actually appeared in the generated code --
    preview (which does evaluate it) and the device silently disagreed."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    face = load(write_design(design("""
  - id: steps
    type: text
    value: activity.steps
    format: "{:d}"
    color: palette.fg
    at: {anchor: center}
    when_absent: fallback
    fallback: 0
""")), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    project = generate(face, [device], write_design("").parent / "build", baked)
    view = next(v for k, v in project.files().items() if k.endswith("View.mc"))
    assert "when_absent: fallback" in view
    assert 'var text = 0.format("%d");' in view
    assert "if (activitySteps != null) {\n            text = activitySteps.format(\"%d\");" in view
    # The old, wrong behaviour: an unconditional early return with no fallback
    # value ever computed.
    assert "// when_absent: hide" not in view


def test_progress_fallback_replaces_the_fraction(write_design, bag, db):
    """Same bug, for `progress`: the fraction falls back rather than the
    element returning early, so a ring with a fallback still draws (at the
    fallback fraction) instead of vanishing."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    face = load(write_design(design("""
  - id: ring
    type: progress
    style: arc
    value: activity.steps
    max: activity.step_goal
    at: {anchor: center}
    radius: 90%r
    thickness: 10px
    start_angle: 180deg
    sweep: 340deg
    color: palette.fg
    when_absent: fallback
    fallback: 0.0
""")), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    project = generate(face, [device], write_design("").parent / "build", baked)
    view = next(v for k, v in project.files().items() if k.endswith("View.mc"))
    assert "when_absent: fallback" in view
    assert "var fraction = 0.0f;" in view
    assert "fraction = WfbMath.percent(activitySteps, activityStepGoal) / 100.0;" in view
    assert "// when_absent: hide" not in view


# --------------------------------------------------------------------------
# Bug 2: two ids that fold to the same Monkey C symbol


def test_ids_differing_only_by_case_convention_are_rejected(write_design, bag):
    """`temp_low` and `tempLow` both derive the Monkey C symbol `TEMP_LOW` /
    `drawTempLow` (`wfb.ir.element_const_prefix`/`element_method_name`).
    Before this fix, the IR only rejected a literal duplicate string, so this
    validated cleanly and `monkeyc` was the one to discover the collision --
    four 'Redefinition of ...' errors deep, pointing at generated line
    numbers rather than the author's YAML."""
    load(write_design(design(
        """
  - id: temp_low
    type: text
    text: "A"
    color: palette.fg
    at: {anchor: center}
""",
        """
  - id: tempLow
    type: text
    text: "B"
    color: palette.fg
    at: {anchor: center}
""",
    )), bag)
    assert any(d.code == "duplicate-id" for d in bag.errors)
    message = bag.errors[0].message
    assert "temp_low" in message and "tempLow" in message


def test_distinct_ids_that_do_not_collide_are_unaffected(write_design, bag):
    """The collision check must not become a blanket ban on similar-looking
    ids -- only ones that actually fold to the same symbol."""
    face = load(write_design(design(
        """
  - id: temp_low
    type: text
    text: "A"
    color: palette.fg
    at: {anchor: center}
""",
        """
  - id: temp_high
    type: text
    text: "B"
    color: palette.fg
    at: {anchor: center}
""",
    )), bag)
    assert face is not None, bag.render()


# --------------------------------------------------------------------------
# Bug 3: a dotted field_name whose intermediate object is itself nullable


def test_active_minutes_week_guards_its_nullable_intermediate(write_design, bag, db):
    """`activity.active_minutes_week` reads `activeMinutesWeek.total`, and
    `activeMinutesWeek` is itself `ActiveMinutes or Null`.  monkeyc's flow
    typing narrows a *local variable*, not a field-access expression, inside
    a ternary, so `(activity.activeMinutesWeek != null) ?
    activity.activeMinutesWeek.total : null` still fails strict typecheck --
    confirmed against a real build.  The intermediate needs its own local
    first."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    face = load(write_design(design("""
  - id: minutes
    type: text
    value: activity.active_minutes_week
    format: "{:d}"
    color: palette.fg
    at: {anchor: center}
    when_absent: placeholder
    placeholder: "--"
""")), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    project = generate(face, [device], write_design("").parent / "build", baked)
    view = next(v for k, v in project.files().items() if k.endswith("View.mc"))
    assert "var activityActiveMinutesWeekObj = activity.activeMinutesWeek;" in view
    assert ("var activityActiveMinutesWeek = (activityActiveMinutesWeekObj != null) "
            "? activityActiveMinutesWeekObj.total : null;") in view


# --------------------------------------------------------------------------
# Bug 5 / 5b: a nullable binding outside 'value' (colour, track colour, max)


def test_placeholder_does_not_leave_a_shared_nullable_colour_unguarded(write_design, bag, db):
    """`value` and `color` can read the very same nullable source.  A
    placeholder gives the *text* a safe substitute, but the colour expression
    dereferences the same local at its own call site regardless -- before
    this fix that call site had no guard at all and failed strict typecheck
    ('gt' on Null and Number)."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    face = load(write_design(design("""
  - id: hr
    type: text
    value: heart_rate.current
    format: "{:d}"
    color: "heart_rate.current > 100 ? palette.fg : palette.fg"
    at: {anchor: center}
    when_absent: placeholder
    placeholder: "--"
""")), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    project = generate(face, [device], write_design("").parent / "build", baked)
    view = next(v for k, v in project.files().items() if k.endswith("View.mc"))
    assert "if (heartRateCurrent == null) {\n            return;" in view
    # The placeholder logic is still there underneath the guard.
    assert 'var text = "--";' in view


def test_a_nullable_colour_alone_still_needs_when_absent(write_design, bag):
    """Before this fix, `_check_absence` only ever ran for `value` -- a
    `color:` expression reading a nullable source, on an element whose
    `value:` is never null, sailed through validation with no policy at all,
    and codegen then emitted an *undeclared* hide guard: a clock that
    silently vanishes whenever heart rate has no reading, with nothing in the
    design saying that was ever a possibility."""
    load(write_design(design("""
  - id: hr
    type: text
    value: time.hour
    format: "{:d}"
    color: "heart_rate.current > 100 ? palette.fg : palette.fg"
    at: {anchor: center}
""")), bag)
    assert any(d.code == "when-absent" for d in bag.errors)
    message = bag.errors[0].message
    assert "hr" in message and "color" in message and "heart_rate.current" in message


def test_a_nullable_track_color_alone_needs_when_absent_on_progress(write_design, bag):
    """Same gap as the colour case above, for `track_color` on `progress`."""
    load(write_design(design("""
  - id: ring
    type: progress
    style: arc
    value: 50
    max: 100
    at: {anchor: center}
    radius: 90%r
    thickness: 10px
    start_angle: 180deg
    sweep: 340deg
    color: palette.fg
    track_color: "heart_rate.current > 100 ? palette.fg : palette.fg"
""")), bag)
    assert any(d.code == "when-absent" for d in bag.errors)
    message = " ".join(d.message for d in bag.errors)
    assert "track_color" in message


def test_a_non_nullable_colour_needs_no_when_absent(write_design, bag):
    """The new check must not make ordinary, always-safe designs fail --
    `time.hour` and a literal palette colour are never absent."""
    face = load(write_design(design("""
  - id: hr
    type: text
    value: time.hour
    format: "{:d}"
    color: palette.fg
    at: {anchor: center}
""")), bag)
    assert face is not None, bag.render()


# --------------------------------------------------------------------------
# Bug 6: `modes: [always_on]` elements were generated but never drawn


def test_always_on_elements_are_drawn_while_asleep(write_design, bag, db):
    """Before this fix, `_emit_on_update` only ever looked at 'active' and
    `_emit_on_partial_update` only at 'low_power' -- an 'always_on' element's
    private draw method was emitted and never called from anywhere, and the
    build reported no diagnostics."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    face = load(write_design(design("""
  - id: clock_dim
    type: text
    text: "12:00"
    color: palette.fg
    at: {anchor: center}
    modes: [always_on]
""")), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    project = generate(face, [device], write_design("").parent / "build", baked)
    view = next(v for k, v in project.files().items() if k.endswith("View.mc"))
    assert "private var _sleeping as Boolean = false;" in view
    assert "_sleeping = true;" in view  # onEnterSleep
    assert "_sleeping = false;" in view  # onExitSleep
    on_update = view.split("function onUpdate")[1].split("function ")[0]
    assert "if (_sleeping) {" in on_update
    assert "drawClockDim(dc);" in on_update


def test_a_design_with_no_always_on_elements_is_unchanged(write_design, bag, db, minimal):
    """The always_on plumbing must be entirely invisible to a design that
    does not use the mode, so ordinary designs (and their golden files)
    do not churn."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    face = load(write_design(minimal), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    project = generate(face, [device], write_design("").parent / "build", baked)
    view = next(v for k, v in project.files().items() if k.endswith("View.mc"))
    assert "_sleeping" not in view


# --------------------------------------------------------------------------
# the fallback fraction's type and range, and substitutes that can never render


def _view(face, db, tmp, extra_device=None):
    """Generate and return the shared view module, for asserting on codegen."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    project = generate(face, [device], tmp / "build", baked)
    return next(v for k, v in project.files().items() if k.endswith("View.mc"))


RING = """
  - id: ring
    type: progress
    style: arc
    value: activity.steps
    max: activity.step_goal
    at: {anchor: center}
    radius: 90%r
    thickness: 10px
    start_angle: 180deg
    sweep: 340deg
    color: palette.fg
    when_absent: fallback
    fallback: __FALLBACK__
"""


def test_an_integer_progress_fallback_is_still_emitted_as_a_float(write_design, bag, db):
    """`fallback: 0` must not make the fill fraction a Number.

    `fraction` is reassigned from `_fraction()` (a Float) in the branch below
    it, so a `var` first bound to a Number becomes a
    `PolyType<Float or Number>` and `WfbArc.drawProgress`'s `Float` parameter
    rejects it under `-l 3`.  The original test for this used `fallback: 0.0`,
    which is already a Float and so could never have caught it.
    """
    path = write_design(design(RING.replace("__FALLBACK__", "0")))
    face = load(path, bag)
    assert face is not None, bag.render()
    view = _view(face, db, path.parent)
    assert "var fraction = 0.0f;" in view
    assert "var fraction = 0;" not in view


def test_a_progress_fallback_outside_zero_to_one_is_rejected(write_design, bag):
    """A progress fallback is a fill *fraction*, unlike a text one, which
    supplies the value.  Writing the reading you wanted to show is the
    plausible mistake, and it is the one path `WfbMath.percent` does not
    already clamp -- so an out-of-range constant could draw a bar wider than
    its own box."""
    load(write_design(design(RING.replace("__FALLBACK__", "5000"))), bag)
    assert any(d.code == "when-absent" and "fill fraction" in d.message
               for d in bag.errors), bag.render()


def test_a_computed_progress_fallback_is_clamped_on_device(write_design, bag, db):
    """Only a *constant* fallback can be range-checked at build time, so
    anything computed is clamped where it is drawn instead."""
    path = write_design(design(RING.replace("__FALLBACK__", '"time.hour / 24.0"')))
    face = load(path, bag)
    assert face is not None, bag.render()
    view = _view(face, db, path.parent)
    assert "WfbMath.clamp(" in view and ".toFloat()" in view


def test_a_substitute_that_can_never_be_drawn_is_reported(write_design, bag):
    """A nullable colour hides the element before the value's own placeholder
    is ever chosen, so a placeholder whose sources are all also read by the
    colour is dead text -- declared, accepted, and impossible to see."""
    load(write_design(design("""
  - id: hr
    type: text
    value: heart_rate.current
    format: "{:d}"
    at: {anchor: center}
    when_absent: placeholder
    placeholder: "--"
    color: "heart_rate.current > 100 ? palette.fg : palette.bg"
""")), bag)
    hits = [d for d in bag.items
            if d.code == "when-absent" and "can never be drawn" in d.message]
    assert hits, bag.render()
    assert "heart_rate.current" in hits[0].message


def test_a_substitute_still_reachable_through_another_source_is_not_reported(
        write_design, bag):
    """The converse: when the value reads a nullable source the colour does
    not, the element survives the colour's guard and the placeholder really
    can render.  Reporting that would be a false positive."""
    load(write_design(design("""
  - id: hr
    type: text
    value: activity.steps
    format: "{:d}"
    at: {anchor: center}
    when_absent: placeholder
    placeholder: "--"
    color: "heart_rate.current > 100 ? palette.fg : palette.bg"
""")), bag)
    assert not [d for d in bag.items if "can never be drawn" in d.message], bag.render()


def test_when_absent_is_not_called_pointless_when_a_colour_needs_it(write_design, bag):
    """`when_absent:` next to a non-nullable value is doing real work as soon
    as the colour is nullable -- it is what `_check_other_absence` demands.
    Telling the author it "has no effect" would contradict the error they
    just fixed."""
    load(write_design(design("""
  - id: hr
    type: text
    value: time.hour
    format: "{:d}"
    at: {anchor: center}
    when_absent: hide
    color: "heart_rate.current > 100 ? palette.fg : palette.bg"
""")), bag)
    assert not [d for d in bag.items if "has no effect" in d.message], bag.render()


# --------------------------------------------------------------------------
# `glyph:` -- a codepoint the icon catalogue does not name


def test_a_glyph_codepoint_resolves_to_the_character(write_design, bag):
    """The point of `glyph:` is that the YAML stays readable: `U+F09B` is
    greppable and survives a diff, where the character itself is invisible in
    most editors -- the same hazard wfb/icon_catalog.py warns about for this
    project's own source."""
    face = load(write_design(design("""
  - id: gh
    type: icon
    glyph: "U+F09B"
    size: 14%r
    at: {anchor: center}
    color: palette.fg
""")), bag)
    assert face is not None, bag.render()
    icon = face.walk()[0]
    assert icon.codepoint == ""


def test_a_glyph_outside_the_font_is_rejected(write_design, bag):
    """Checked against the font's own cmap, the same way a custom text font's
    coverage is -- otherwise it bakes to a blank tile and only shows up on the
    wrist."""
    load(write_design(design("""
  - id: gh
    type: icon
    glyph: "U+FFFFF"
    size: 14%r
    at: {anchor: center}
    color: palette.fg
""")), bag)
    assert any(d.code == "icon" and "no glyph at" in d.message for d in bag.errors), bag.render()


def test_a_glyph_that_duplicates_a_catalogue_name_says_so(write_design, bag):
    """A name keeps meaning if the catalogue moves that icon to a different
    codepoint, which it has done before (Font Awesome -> Material Design
    Icons); a raw codepoint does not."""
    from wfb import icons

    codepoint = "U+%04X" % ord(icons.CATALOG["heart"].codepoint)
    load(write_design(design(f"""
  - id: h
    type: icon
    glyph: "{codepoint}"
    size: 14%r
    at: {{anchor: center}}
    color: palette.fg
""")), bag)
    assert any("in the catalogue as 'heart'" in d.message for d in bag.items), bag.render()


def test_icon_and_glyph_are_mutually_exclusive(write_design, bag):
    load(write_design(design("""
  - id: h
    type: icon
    icon: heart
    glyph: "U+F09B"
    size: 14%r
    at: {anchor: center}
    color: palette.fg
""")), bag)
    assert not bag.ok(), "expected exactly-one-of to be enforced"


# --------------------------------------------------------------------------
# `on_tap:` -- the one exit a watch face has (ADR 0006 6)


TAPPED = """
  - id: hr
    type: icon
    icon: heart
    size: 14%r
    at: {anchor: center, dy: -20%}
    color: palette.fg
    on_tap: heart_rate
"""


def test_on_tap_must_name_a_real_complication_type(write_design, bag):
    """An invented name would compile to an undefined Monkey C symbol, so it
    is caught here, against the author's line, rather than deep in monkeyc."""
    load(write_design(design(TAPPED.replace("heart_rate", "hart_rate"))), bag)
    hits = [d for d in bag.errors if d.code == "on-tap"]
    assert hits, bag.render()
    assert any("heart_rate" in n for n in hits[0].notes), hits[0].notes


def test_on_tap_compiles_to_exit_to(write_design, bag, db):
    """`Complications.exitTo` is the entire mechanism: a watch face cannot
    launch an arbitrary app, only the one owning a complication type."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    path = write_design(design(TAPPED))
    face = load(path, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    files = generate(face, [device], path.parent / "b", baked).files()
    delegate = next(v for k, v in files.items() if k.endswith("Delegate.mc"))
    assert "Complications.exitTo(new Complications.Id(" \
           "Complications.COMPLICATION_TYPE_HEART_RATE))" in delegate
    # both entry points, because onTap is absent on some watches that have onPress
    assert "function onTap(" in delegate and "function onPress(" in delegate
    app = next(v for k, v in files.items() if k.endswith("App.mc"))
    assert "WatchUi has :WatchFaceDelegate" in app


def test_a_passive_face_gets_no_delegate_and_no_permission(write_design, bag, db):
    """Nothing is emitted for a design that asks for nothing -- the delegate,
    the permission and the raised minApiLevel all follow from the declaration."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    path = write_design(design(TAPPED.replace("    on_tap: heart_rate\n", "")))
    face = load(path, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    files = generate(face, [device], path.parent / "b", baked).files()
    assert not [k for k in files if k.endswith("Delegate.mc")]
    assert "ComplicationSubscriber" not in files["manifest.xml"]


def test_on_tap_derives_the_permission_and_api_level(write_design, bag, db):
    """`exitTo` lives in Toybox.Complications, which is gated by
    ComplicationSubscriber -- so a design that reads no complication value at
    all still needs it as soon as it launches one."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    path = write_design(design(TAPPED))
    face = load(path, bag)
    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    manifest = generate(face, [device], path.parent / "b", baked).files()["manifest.xml"]
    assert 'uses-permission id="ComplicationSubscriber"' in manifest
    assert 'minApiLevel="4.2.0"' in manifest


def test_on_tap_on_a_group_covers_the_whole_box_not_one_child(write_design, bag, db):
    """A group draws nothing of its own, but its box is still a real tap
    region -- the documented way to make a multi-element cluster (an icon
    next to its reading) act as one target instead of tagging every child."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    path = write_design(design("""
  - id: hr_group
    type: group
    size: {width: 60%, height: 20%}
    at: {anchor: center, dy: -20%}
    on_tap: heart_rate
    children:
      - id: hr_icon
        type: icon
        icon: heart
        size: 10%r
        at: {anchor: center, dx: -15%}
      - id: hr_value
        type: text
        value: heart_rate.current
        format: "{:d}"
        when_absent: hide
        at: {anchor: center, dx: 15%}
"""))
    face = load(path, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    files = generate(face, [device], path.parent / "b", baked).files()
    delegate = next(v for k, v in files.items() if k.endswith("Delegate.mc"))
    assert "HR_GROUP_TAP_X" in delegate
    assert "HR_ICON_TAP_X" not in delegate and "HR_VALUE_TAP_X" not in delegate
    layout = next(v for k, v in files.items() if k.endswith("Layout.mc"))
    assert "HR_GROUP_TAP_WIDTH" in layout
