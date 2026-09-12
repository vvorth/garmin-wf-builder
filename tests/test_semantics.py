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


def test_low_power_may_bind_a_slow_reader_source(write_design, bag, monkeypatch):
    """The refresh-tier concept is gone (SPEC.md D2): every read is a plain
    per-frame read, and the SDK itself caches whatever backs it -- e.g.
    `Weather.getCurrentConditions()` is documented as "the most recently
    cached weather conditions". So a `low_power` element may bind a source
    that used to be tier-gated, and this must produce no error at all."""
    from wfb import catalog

    fabricated = catalog.Source(
        path="weather.temperature", type=catalog.Type.NUMBER, reader="settings",
        field_name="temperature", nullable=True,
    )
    monkeypatch.setitem(catalog.CATALOG, "weather.temperature", fabricated)
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
    assert not any(d.code == "refresh-tier" for d in bag.errors), bag.render()
    assert bag.ok(), bag.render()


def test_low_power_may_bind_the_real_weather_condition_source(write_design, bag):
    """Same check, against a real (formerly slow-tier) source rather than a
    fabricated one -- weather.* is the first real one this project has."""
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
    assert not any(d.code == "refresh-tier" for d in bag.errors), bag.render()
    assert bag.ok(), bag.render()


def test_low_power_may_bind_a_real_complication_source(write_design, bag):
    """Same check again, against a `complication.*` source -- SPEC.md D1
    renamed `body_battery.current` to `complication.body_battery`, and D2
    means a complication read is no more restricted in low_power than any
    other read now."""
    load(write_design(design("""
  - id: bb
    type: text
    value: complication.body_battery
    format: "{}"
    color: palette.fg
    at: {anchor: center}
    modes: [active, low_power]
    when_absent: hide
""")), bag)
    assert not any(d.code == "refresh-tier" for d in bag.errors), bag.render()
    assert bag.ok(), bag.render()


def test_low_power_may_bind_a_dynamic_weather_icon(write_design, bag):
    load(write_design(design("""
  - id: wicon
    type: icon
    icon_for: weather.condition
    size: 20%r
    color: palette.fg
    at: {anchor: center}
    modes: [active, low_power]
""")), bag)
    assert not any(d.code == "refresh-tier" for d in bag.errors), bag.render()
    assert bag.ok(), bag.render()


# --------------------------------------------------------------------------
# renamed sources (SPEC.md D1) -- nine paths moved to `complication.*`


def test_body_battery_current_names_its_replacement(write_design, bag):
    """`body_battery.current` moved to `complication.body_battery`: complications
    now have their own namespace, always read through Toybox.Complications,
    rather than piggybacking on ActivityMonitor's tier."""
    load(write_design(design("""
  - id: bb
    type: text
    value: body_battery.current
    format: "{}"
    color: palette.fg
    at: {anchor: center}
    when_absent: hide
""")), bag)
    hits = [d for d in bag.errors if d.code == "source-renamed"]
    assert hits, bag.render()
    assert "body_battery.current" in hits[0].message
    assert "complication.body_battery" in hits[0].message


def test_device_next_calendar_event_names_its_replacement(write_design, bag):
    """A second renamed path, to confirm the diagnostic is not hard-coded to
    just the one -- it is driven by `catalog.RENAMED_SOURCES`."""
    load(write_design(design("""
  - id: cal
    type: text
    value: device.next_calendar_event
    format: "{:%H:%M}"
    color: palette.fg
    at: {anchor: center}
    when_absent: hide
""")), bag)
    hits = [d for d in bag.errors if d.code == "source-renamed"]
    assert hits, bag.render()
    assert "device.next_calendar_event" in hits[0].message
    assert "complication.calendar_events" in hits[0].message


def test_a_source_renamed_error_is_a_registered_lint_code(write_design, bag):
    """`source-renamed` must actually be in `lint.ALL_CODES`, or
    `check_lint_allow` would treat a `lint: {allow: [source-renamed]}` as
    naming an unknown code rather than one that is simply not suppressible."""
    from wfb import lint

    assert "source-renamed" in lint.ALL_CODES


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
            field_name="temperature", nullable=True,
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
# `on_hold:` -- the one exit a watch face has (ADR 0006 6)


HELD = """
  - id: hr
    type: icon
    icon: heart
    size: 14%r
    at: {anchor: center, dy: -20%}
    color: palette.fg
    on_hold: heart_rate
"""


def test_on_hold_must_name_a_real_complication_type(write_design, bag):
    """An invented name would compile to an undefined Monkey C symbol, so it
    is caught here, against the author's line, rather than deep in monkeyc."""
    load(write_design(design(HELD.replace("heart_rate", "hart_rate"))), bag)
    hits = [d for d in bag.errors if d.code == "on-hold"]
    assert hits, bag.render()
    assert any("heart_rate" in n for n in hits[0].notes), hits[0].notes


def test_the_old_on_tap_spelling_is_now_an_ordinary_unknown_key(write_design, bag):
    """The rename shim is gone; `on_tap:` is just not a key any more.

    It was carried in all seven element branches of the schema for one
    purpose -- reporting its own rename -- long after anything could still be
    written against it.  What is left is the ordinary unknown-key error, which
    already lists the keys that *are* allowed, `on_hold` among them.
    """
    load(write_design(design(HELD.replace("on_hold:", "on_tap:"))), bag)
    assert not [d for d in bag.errors if d.code == "on-tap-renamed"], bag.render()
    schema = [d for d in bag.errors if d.code == "schema"]
    assert schema, bag.render()
    assert "on_tap" in bag.render()


def test_on_hold_compiles_to_exit_to(write_design, bag, db):
    """`Complications.exitTo` is the entire mechanism: a watch face cannot
    launch an arbitrary app, only the one owning a complication type."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    path = write_design(design(HELD))
    face = load(path, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    files = generate(face, [device], path.parent / "b", baked).files()
    delegate = next(v for k, v in files.items() if k.endswith("Delegate.mc"))
    assert "Complications.exitTo(new Complications.Id(" \
           "Complications.COMPLICATION_TYPE_HEART_RATE))" in delegate
    # onPress only: onTap fires solely in the on-device config editor, so
    # emitting it would be dead code that also tells the reader a lie
    assert "function onPress(" in delegate
    assert "function onTap(" not in delegate
    app = next(v for k, v in files.items() if k.endswith("App.mc"))
    assert "WatchUi has :WatchFaceDelegate" in app


def test_a_passive_face_gets_no_delegate_and_no_permission(write_design, bag, db):
    """Nothing is emitted for a design that asks for nothing -- the delegate,
    the permission and the raised minApiLevel all follow from the declaration."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    path = write_design(design(HELD.replace("    on_hold: heart_rate\n", "")))
    face = load(path, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    files = generate(face, [device], path.parent / "b", baked).files()
    assert not [k for k in files if k.endswith("Delegate.mc")]
    assert "ComplicationSubscriber" not in files["manifest.xml"]


def test_on_hold_derives_the_permission_and_api_level(write_design, bag, db):
    """`exitTo` lives in Toybox.Complications, which is gated by
    ComplicationSubscriber -- so a design that reads no complication value at
    all still needs it as soon as it launches one."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    path = write_design(design(HELD))
    face = load(path, bag)
    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    manifest = generate(face, [device], path.parent / "b", baked).files()["manifest.xml"]
    assert 'uses-permission id="ComplicationSubscriber"' in manifest
    assert 'minApiLevel="4.2.0"' in manifest


def test_on_hold_on_a_group_covers_the_whole_box_not_one_child(write_design, bag, db):
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
    on_hold: heart_rate
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
    assert "HR_GROUP_HOLD_X" in delegate
    assert "HR_ICON_HOLD_X" not in delegate and "HR_VALUE_HOLD_X" not in delegate
    layout = next(v for k, v in files.items() if k.endswith("Layout.mc"))
    assert "HR_GROUP_HOLD_WIDTH" in layout


# --------------------------------------------------------------------------
# `on_hold: auto` -- resolved from the element's own value binding (D3)


def _generated(write_design, bag, db, source: str) -> dict:
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    path = write_design(design(source))
    face = load(path, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    return generate(face, [device], path.parent / "b", baked).files()


def test_on_hold_auto_resolves_a_direct_read_source(write_design, bag, db):
    """`activity.steps` has no complication of its own -- it is a direct
    Activity.Info read -- but `Source.launch_complication` names the
    conventional counterpart (`steps`), so `auto` still resolves."""
    files = _generated(write_design, bag, db, """
  - id: steps
    type: text
    value: activity.steps
    format: "{:d}"
    color: palette.fg
    at: {anchor: center}
    when_absent: hide
    on_hold: auto
""")
    delegate = next(v for k, v in files.items() if k.endswith("Delegate.mc"))
    assert "Complications.exitTo(new Complications.Id(" \
           "Complications.COMPLICATION_TYPE_STEPS))" in delegate


def test_on_hold_auto_resolves_a_complication_source(write_design, bag, db):
    """A `complication.*` source's own name is always its
    `launch_complication` -- `auto` on an element reading one is never
    ambiguous."""
    files = _generated(write_design, bag, db, """
  - id: bb
    type: text
    value: complication.body_battery
    format: "{}"
    color: palette.fg
    at: {anchor: center}
    when_absent: hide
    on_hold: auto
""")
    delegate = next(v for k, v in files.items() if k.endswith("Delegate.mc"))
    assert "Complications.exitTo(new Complications.Id(" \
           "Complications.COMPLICATION_TYPE_BODY_BATTERY))" in delegate


def test_on_hold_auto_with_no_value_binding_is_unresolved(write_design, bag):
    """A shape has nothing to resolve `auto` from at all -- the zero case,
    same diagnostic as a value with no conventional target."""
    load(write_design(design("""
  - id: box
    type: shape
    shape: rectangle
    size: {width: 20%, height: 20%}
    color: palette.fg
    at: {anchor: center}
    on_hold: auto
""")), bag)
    hits = [d for d in bag.errors if d.code == "hold-auto-unresolved"]
    assert hits, bag.render()
    assert "box" in hits[0].message


def test_on_hold_auto_with_no_conventional_target_is_unresolved(write_design, bag):
    """`weather.condition_today` deliberately has no `launch_complication`:
    `COMPLICATION_TYPE_FORECAST_WEATHER_1DAY` means tomorrow, not today, so
    mapping it would open the wrong glance (SPEC.md)."""
    load(write_design(design("""
  - id: cond
    type: text
    value: weather.condition_today
    format: "{:d}"
    color: palette.fg
    at: {anchor: center}
    when_absent: hide
    on_hold: auto
""")), bag)
    hits = [d for d in bag.errors if d.code == "hold-auto-unresolved"]
    assert hits, bag.render()
    assert "weather.condition_today" in hits[0].message
    assert any("wfb complications" in n for n in hits[0].notes), hits[0].notes


def test_on_hold_auto_is_ambiguous_between_two_targets(write_design, bag):
    """Two direct-read sources with different conventional targets in one
    value expression -- `auto` must refuse to guess which glance to open."""
    load(write_design(design("""
  - id: total
    type: text
    value: activity.steps + activity.calories
    format: "{:d}"
    color: palette.fg
    at: {anchor: center}
    when_absent: hide
    on_hold: auto
""")), bag)
    hits = [d for d in bag.errors if d.code == "hold-auto-ambiguous"]
    assert hits, bag.render()
    assert "'steps'" in hits[0].message and "'calories'" in hits[0].message


def test_on_hold_auto_ignores_color_and_max(write_design, bag):
    """D3: only the value binding is consulted -- a conditional colour's
    heart-rate reference is not what the element is *about*, so it must not
    make `auto` ambiguous or change what it resolves to."""
    load(write_design(design("""
  - id: steps
    type: progress
    style: arc
    value: activity.steps
    max: activity.step_goal
    radius: 40%r
    thickness: 4%r
    color: "heart_rate.current != null and heart_rate.current > 100 ? palette.fg : palette.fg"
    when_absent: hide
    at: {anchor: center}
    on_hold: auto
""")), bag)
    assert not any(d.code in ("hold-auto-ambiguous", "hold-auto-unresolved")
                   for d in bag.errors), bag.render()


# -- a font's `size:` as a length ---------------------------------------------


def _font_design(size: str, extra: str = "") -> str:
    """A design whose one custom font declares this `size:`."""
    return f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: [fenix8solar47mm]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
fonts:
  clock:
    source: examples/slice/assets/OpenSans-Regular.ttf
    size: {size}
{extra}
elements:
  - id: clock
    type: text
    text: "12:00"
    font: font.clock
    color: palette.fg
    at: {{anchor: center}}
"""


@pytest.mark.parametrize("size,unit", [('"18%"', "%"), ('"1.5pt"', "pt")])
def test_a_font_size_may_not_use_percent_or_pt(write_design, bag, repo_root, size, unit):
    """A font's sheet is rasterised before any element is placed, so neither
    context a `%` or a `pt` would need exists yet -- and `pt` is measured
    against a font, which for a font's own size is circular.  The note has to
    point at `%r`, which is the unit an author reaching for `%` actually wants.
    """
    design_text = _font_design(size).replace(
        "examples/", f"{repo_root}/examples/")
    load(write_design(design_text), bag)
    errors = [d for d in bag.errors if d.code == "font"]
    assert errors, bag.render()
    assert f"not {unit}" in errors[0].message
    assert any("%r" in note for note in errors[0].notes)


@pytest.mark.parametrize("size", ['"18%r"', '"12px"'])
@pytest.mark.parametrize("scale", ["true", "false"])
def test_scale_with_a_length_font_size_is_an_error(write_design, bag, repo_root,
                                                   size, scale):
    """The unit already decides.  `scale` is only meaningful for the bare
    number, whose 'pixels on the smallest target' meaning needs a reference
    device to scale away from; a length has no such reference to scale from.
    """
    design_text = _font_design(size, extra=f"    scale: {scale}").replace(
        "examples/", f"{repo_root}/examples/")
    load(write_design(design_text), bag)
    errors = [d for d in bag.errors if d.code == "font"]
    assert errors, bag.render()
    assert "scale" in errors[0].message


@pytest.mark.parametrize("size", ["0", "-5", '"0%r"', '"-3px"'])
def test_a_font_size_must_be_positive(write_design, bag, repo_root, size):
    """One rule for both spellings: the schema only says 'a number or a
    length', so this is the compiler's job in either case."""
    design_text = _font_design(size).replace("examples/", f"{repo_root}/examples/")
    load(write_design(design_text), bag)
    errors = [d for d in bag.errors if d.code == "font"]
    assert errors, bag.render()
    assert "greater than zero" in errors[0].message


@pytest.mark.parametrize("size,expected", [
    ('"18%r"', ("%r", 18.0)), ('"12px"', ("px", 12.0)), ("68", None),
])
def test_a_font_size_keeps_the_spelling_it_was_written_in(write_design, bag,
                                                          repo_root, size, expected):
    """A bare number is deliberately *not* normalised into a `Length`: the two
    mean different things (reference-device pixels that scale, versus this
    device's pixels), so collapsing them would silently move one of them.
    """
    from wfb.units import Length

    design_text = _font_design(size).replace("examples/", f"{repo_root}/examples/")
    face = load(write_design(design_text), bag)
    assert face is not None, bag.render()
    spec = face.fonts["clock"]
    if expected is None:
        assert not spec.size_is_length and spec.size == 68.0
        assert spec.scale is True
    else:
        assert spec.size_is_length and isinstance(spec.size, Length)
        assert (spec.size.unit, spec.size.value) == expected
        # Left false so nothing downstream can consult it and get a "scaled"
        # answer for a size that is already per-device by construction.
        assert spec.scale is False


# -- a monospaced font --------------------------------------------------------


def test_align_without_monospace_is_an_error(write_design, bag, repo_root):
    """A proportional font has no cell for the ink to sit in, so `align:` would
    be silently doing nothing -- which is exactly the class of bug this
    compiler exists to turn into a line number."""
    design_text = _font_design("33", extra="    align: right").replace(
        "examples/", f"{repo_root}/examples/")
    load(write_design(design_text), bag)
    errors = [d for d in bag.errors if d.code == "font"]
    assert errors, bag.render()
    assert "align" in errors[0].message and "monospace" in errors[0].message


@pytest.mark.parametrize("align,expected", [("", "center"), ("    align: left", "left")])
def test_monospace_carries_its_alignment_onto_the_spec(write_design, bag, repo_root,
                                                       align, expected):
    extra = "    monospace: true" + (f"\n{align}" if align else "")
    design_text = _font_design("33", extra=extra).replace(
        "examples/", f"{repo_root}/examples/")
    face = load(write_design(design_text), bag)
    assert face is not None, bag.render()
    spec = face.fonts["clock"]
    assert spec.monospace is True and spec.align == expected


def test_a_font_is_proportional_unless_it_asks_not_to_be(write_design, bag, repo_root):
    design_text = _font_design("33").replace("examples/", f"{repo_root}/examples/")
    face = load(write_design(design_text), bag)
    assert face is not None, bag.render()
    assert face.fonts["clock"].monospace is False
    assert face.fonts["clock"].align == "center"


# -- graph --------------------------------------------------------------------

HR_GRAPH = """
  - id: hr_graph
    type: graph
    series: heart_rate
    range: 4h
    style: line
    thickness: 2px
    color: palette.fg
    at: {anchor: center}
    size: {width: 60%, height: 18%}
"""


def _graph(**overrides: str) -> str:
    """`HR_GRAPH`, with one or more `key: value` lines replaced or appended."""
    lines = HR_GRAPH.strip("\n").splitlines()
    for key, value in overrides.items():
        prefix = f"    {key}:"
        replaced = False
        for i, line in enumerate(lines):
            if line.strip().startswith(prefix.strip()):
                lines[i] = f"{prefix} {value}" if value is not None else None
                replaced = True
                break
        if value is None:
            if replaced:
                lines = [l for l in lines if l is not None]
            continue
        if not replaced:
            lines.append(f"{prefix} {value}")
    return "\n" + "\n".join(l for l in lines if l is not None) + "\n"


def test_a_valid_graph_builds_cleanly(write_design, bag):
    face = load(write_design(design(_graph())), bag)
    assert face is not None, bag.render()
    assert bag.ok(), bag.render()
    from wfb.ir import Graph

    element = face.elements[0]
    assert isinstance(element, Graph)
    assert element.series == "heart_rate"
    assert element.range_kind == "duration" and element.range_value == 14400
    assert element.min_auto and element.max_auto
    assert element.sample_count == 40  # the default bucket count


def test_an_unknown_series_is_reported_with_a_suggestion(write_design, bag):
    load(write_design(design(_graph(series="hart_rate"))), bag)
    errors = [d for d in bag.errors if d.code == "graph"]
    assert errors, bag.render()
    assert "unknown series" in errors[0].message
    assert "heart_rate" in " ".join(errors[0].notes)


@pytest.mark.parametrize("name,cite", [
    ("pressure", "SensorHistory"),
    ("body_battery", "SensorHistory"),
    ("stress", "SensorHistory"),
    ("ambient.pressure", "SensorHistory"),   # matched on the trailing segment
    ("solar", "no solar history API"),
    ("solar_intensity", "no solar history API"),
])
def test_a_series_the_platform_forbids_says_why_rather_than_unknown(
        write_design, bag, name, cite):
    """A real quantity the watch shows natively, that a face still cannot plot.

    "unknown series 'pressure'" would send an author hunting for a spelling
    mistake that does not exist -- the failure mode `source-renamed`
    already exists to avoid.  Drives both branches: the
    message must NOT be the "unknown series" one, and must carry the reason.
    """
    load(write_design(design(_graph(series=name))), bag)
    errors = [d for d in bag.errors if d.code == "graph"]
    assert errors, bag.render()
    assert "unknown series" not in errors[0].message
    assert "cannot be plotted on a watch face" in errors[0].message
    assert cite in " ".join(errors[0].notes)


def test_buckets_on_a_non_heart_rate_series_is_an_error(write_design, bag):
    load(write_design(design(_graph(series="steps", range="4d", buckets="10"))), bag)
    errors = [d for d in bag.errors if d.code == "graph"]
    assert errors, bag.render()
    assert "buckets" in errors[0].message


def test_buckets_on_a_heart_rate_count_range_is_also_an_error(write_design, bag):
    """`buckets:` only binning-by-time; a bare sample count does not bin."""
    load(write_design(design(_graph(range="30", buckets="10"))), bag)
    errors = [d for d in bag.errors if d.code == "graph"]
    assert errors, bag.render()
    assert "buckets" in errors[0].message


def test_a_duration_range_on_heart_rate_needs_no_buckets_error(write_design, bag):
    face = load(write_design(design(_graph())), bag)
    assert bag.ok(), bag.render()
    assert face is not None


def test_thickness_on_a_bars_graph_is_not_used(write_design, bag):
    load(write_design(design(_graph(style="bars"))), bag)
    errors = [d for d in bag.errors if d.code == "graph"]
    assert errors, bag.render()
    assert "thickness" in errors[0].message
    assert "style: line" in " ".join(errors[0].notes)


def test_bar_width_on_a_line_graph_is_not_used(write_design, bag):
    load(write_design(design(_graph(bar_width="4px"))), bag)
    errors = [d for d in bag.errors if d.code == "graph"]
    assert errors, bag.render()
    assert "bar_width" in errors[0].message


def test_area_needs_neither_thickness_nor_bar_width(write_design, bag):
    face = load(write_design(design(_graph(
        style="area", thickness=None, bar_width=None))), bag)
    assert bag.ok(), bag.render()
    assert face is not None


def test_two_fixed_bounds_with_min_at_least_max_is_an_error(write_design, bag):
    load(write_design(design(_graph(min="100", max="50"))), bag)
    errors = [d for d in bag.errors if d.code == "graph"]
    assert errors, bag.render()
    assert "min" in errors[0].message and "max" in errors[0].message


def test_min_less_than_max_is_fine(write_design, bag):
    face = load(write_design(design(_graph(min="40", max="180"))), bag)
    assert bag.ok(), bag.render()
    element = face.elements[0]
    assert element.min_auto is False and element.max_auto is False
    assert element.min.constant == 40 and element.max.constant == 180


def test_a_mixed_fixed_and_auto_bound_is_not_checked_at_build_time(write_design, bag):
    """One fixed, one auto -- there is nothing to compare until the auto side
    is known on-device, so this must not be flagged."""
    face = load(write_design(design(_graph(min="40"))), bag)
    assert bag.ok(), bag.render()
    element = face.elements[0]
    assert element.min_auto is False and element.max_auto is True


def test_a_duration_range_over_the_documented_maximum_is_an_error_not_a_clamp(write_design, bag):
    """`range: 14d` on `steps` -- `getHistory()` returns at most 7 days, and
    silently drawing 7 when 14 was asked for is exactly the class of quiet
    wrongness this compiler exists to remove."""
    load(write_design(design(_graph(series="steps", range="14d"))), bag)
    errors = [d for d in bag.errors if d.code == "graph"]
    assert errors, bag.render()
    assert "steps" in errors[0].message and "7" in errors[0].message


def test_a_count_range_over_the_documented_maximum_is_also_an_error(write_design, bag):
    load(write_design(design(_graph(series="steps", range="10"))), bag)
    errors = [d for d in bag.errors if d.code == "graph"]
    assert errors, bag.render()
    assert "10" in errors[0].message and "7" in errors[0].message


def test_a_duration_range_within_the_documented_maximum_is_fine(write_design, bag):
    face = load(write_design(design(_graph(series="steps", range="4d"))), bag)
    assert bag.ok(), bag.render()
    element = face.elements[0]
    assert element.sample_count == 4


def test_forecast_series_have_no_documented_maximum_to_exceed(write_design, bag):
    face = load(write_design(design(_graph(series="forecast_temperature", range="240h"))), bag)
    assert bag.ok(), bag.render()
    element = face.elements[0]
    assert element.sample_count == 240


def test_an_area_graph_over_the_62_sample_cap_is_an_error(write_design, bag):
    """`fillPolygon`'s own 64-point limit, minus the two corners that close
    the outline -- `docs/research/probes/graph-series/`."""
    load(write_design(design(_graph(
        style="area", buckets="70", thickness=None))), bag)
    errors = [d for d in bag.errors if d.code == "graph"]
    assert errors, bag.render()
    assert "62" in errors[0].message


def test_an_area_graph_over_the_cap_via_a_count_range_is_also_an_error(write_design, bag):
    load(write_design(design(_graph(
        style="area", range="70", thickness=None))), bag)
    errors = [d for d in bag.errors if d.code == "graph"]
    assert errors, bag.render()
    assert "62" in errors[0].message


def test_an_area_graph_at_exactly_the_cap_is_fine(write_design, bag):
    face = load(write_design(design(_graph(
        style="area", buckets="62", thickness=None))), bag)
    assert bag.ok(), bag.render()
    assert face.elements[0].sample_count == 62


def test_a_graph_cannot_be_static(write_design, bag):
    load(write_design(design(_graph(static="true"))), bag)
    errors = [d for d in bag.errors if d.code == "static"]
    assert errors, bag.render()
    assert "graph" in errors[0].message


def test_a_nullable_color_still_hides_the_element_with_no_when_absent_required(
        write_design, bag):
    """A graph has no `when_absent:` field at all -- unlike `text`/`progress`,
    a nullable `color:` here needs no explicit policy, the same as `shape`
    and `icon` (`_check_other_absence` is deliberately not called for it)."""
    face = load(write_design(design(_graph(
        color='"activity.step_goal > 0 ? palette.fg : palette.fg"'))), bag)
    assert bag.ok(), bag.render()
    assert face is not None


from tests.test_build import toolchain  # noqa: E402,F401 -- a fixture, used by name


@pytest.mark.slow
def test_a_graph_design_compiles_warning_free_on_every_target(
        repo_root, tmp_path, bag, db, toolchain):
    """Real `monkeyc`, all three targets, **warning-free** -- not merely
    successful. Every other test in this file inspects generated text or the
    IR directly; this is the one that puts a `graph` design through the real
    toolchain, which is exactly the gap that let a real, unrelated `monkeyc`
    warning ship once before (CLAUDE.md's account of the delegate's unused
    `_view` field). `wfb.build` turns each `WARNING:` line `monkeyc` prints
    into a bag diagnostic, so asserting no warnings here is on the
    compiler's own output, not a proxy for it.
    """
    from wfb.build import build as run_build

    design_path = repo_root / "examples" / "graph" / "face.yaml"
    result = run_build(design_path, output=tmp_path / "out", bag=bag, db=db,
                       toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, "\n".join(d.message for d in warnings)
    assert set(result.products) == {"fenix8solar47mm", "fenix8solar51mm", "fr955"}



# -- literal text vs an expression ------------------------------------------
#
# A real report: `value: 'XX%'` failed with "expected a value but found 'end of
# expression'", and the author could not find the literal-text spelling.  YAML
# strips the quotes before this compiler sees them, so the expression parser
# receives a bare `XX%` -- the name `XX`, the `%` operator, then nothing.  Both
# diagnostics below exist to say that out loud rather than leave it to be
# puzzled out.

_PROSE_VALUE = """
  - id: unit
    type: text
    value: 'XX%'
    color: palette.fg
    at: {anchor: center}
"""

_BOTH_SPELLINGS = """
  - id: unit
    type: text
    text: "XX%"
    value: activity.steps
    color: palette.fg
    at: {anchor: center}
"""

_LITERAL = """
  - id: unit
    type: text
    text: "XX%"
    color: palette.fg
    at: {anchor: center}
"""


def test_a_literal_string_in_value_points_at_text(write_design, bag):
    load(write_design(design(_PROSE_VALUE)), bag)
    errors = [d for d in bag.errors if d.code == "expression"]
    assert errors, bag.render()
    notes = " ".join(errors[0].notes)
    assert "'text:' instead" in notes, notes
    assert "YAML strips the quotes" in notes, notes


def test_a_genuine_expression_typo_is_not_told_to_use_text(write_design, bag):
    """The note above must be narrow.  An unknown *source* is a real mistake in
    a real expression, and telling that author to write `text:` instead would
    send them the wrong way entirely -- so it keys off a syntax failure, not
    any expression error."""
    load(write_design(design("""
  - id: steps
    type: text
    value: activity.stepss
    when_absent: hide
    color: palette.fg
    at: {anchor: center}
""")), bag)
    errors = [d for d in bag.errors if d.code == "expression"]
    assert errors, bag.render()
    notes = " ".join(errors[0].notes)
    assert "text:" not in notes, notes
    assert "did you mean" in notes, notes


def test_text_and_value_together_name_both_keys(write_design, bag):
    """jsonschema calls this "is valid under each of {...}, {...}" and renders
    the whole element dict, which tells an author nothing at all."""
    load(write_design(design(_BOTH_SPELLINGS)), bag)
    errors = [d for d in bag.errors if d.code == "schema"]
    assert errors, bag.render()
    assert "cannot both be set" in errors[0].message, errors[0].message
    assert "'text'" in errors[0].message and "'value'" in errors[0].message
    notes = " ".join(errors[0].notes)
    assert "literal string" in notes, notes


def test_a_literal_text_element_is_accepted(write_design, bag):
    face = load(write_design(design(_LITERAL)), bag)
    assert bag.ok(), bag.render()
    assert face is not None


# -- `overrides:` is not implemented, and now says so -------------------------


def test_overrides_is_rejected_rather_than_silently_ignored(write_design, bag):
    """ADR 0004 4 is unbuilt, so accepting the key is worse than refusing it.

    Before this error existed, the design below validated with *no diagnostics
    at all*: a device id that does not exist and a key that is not a property
    of any element both sailed through, because `$defs/overrides` is
    `{additionalProperties: {type: object}}` and nothing downstream ever reads
    `Element.overrides`.
    """
    load(write_design(design("""
  - id: ring
    type: shape
    shape: circle
    radius: 40%r
    color: palette.fg
    at: {anchor: center}
    overrides:
      notADeviceAtAll:
        radius: 999%r
        totally_bogus_key: [1, 2, 3]
""")), bag)
    errors = [d for d in bag.errors if d.code == "overrides"]
    assert len(errors) == 1, bag.render()
    assert "not implemented" in errors[0].message


def test_an_empty_overrides_block_is_not_an_error(write_design, bag):
    """`overrides: {}` asks for nothing, so there is nothing to warn about."""
    face = load(write_design(design("""
  - id: ring
    type: shape
    shape: circle
    radius: 40%r
    color: palette.fg
    at: {anchor: center}
    overrides: {}
""")), bag)
    assert face is not None, bag.render()
    assert not [d for d in bag.errors if d.code == "overrides"]


def test_progress_cannot_ask_for_a_placeholder_it_has_no_key_for(write_design, bag):
    """The enum used to offer a policy the schema made unsatisfiable.

    `when_absent: placeholder` needed a `placeholder:` string, and
    `progressElement` has no such property with `additionalProperties: false`
    -- so the author was given an error with no legal way out.  There is no
    substitute *text* for a fill fraction; `fallback:` is the real answer.
    """
    load(write_design(design("""
  - id: ring
    type: progress
    style: arc
    radius: 40%r
    thickness: 4px
    start_angle: 0
    sweep: 180
    value: activity.steps
    max: 10000
    color: palette.fg
    at: {anchor: center}
    when_absent: placeholder
""")), bag)
    schema = [d for d in bag.errors if d.code == "schema"]
    assert schema, bag.render()
    assert "placeholder" in bag.render()
