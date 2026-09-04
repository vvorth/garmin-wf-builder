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


def test_permissions_are_derived_from_bindings(write_design, bag):
    """The strongest single justification for the project: a missing permission
    fails silently on device, so it must not be hand-maintained."""
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
    assert face.requirements().permissions == {"Sensor"}


def test_no_binding_means_no_permissions(write_design, bag, minimal):
    face = load(write_design(minimal), bag)
    assert face.requirements().permissions == set()
