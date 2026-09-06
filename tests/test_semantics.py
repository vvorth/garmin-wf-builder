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
