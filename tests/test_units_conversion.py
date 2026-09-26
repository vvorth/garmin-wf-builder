"""`units:` on a `text` element (ADR 0005 §4): a bound value shown in the
wearer's units, with `format:`'s `{unit}` field for the label.

The conversion is an ordinary expression the builder writes
(`wfb.conversion.converted_text`), so these tests pin its three parts: the
generated Monkey C switches on the watch's own setting (and reads no
setting at all for a fixed system), the preview draws the same numbers the
device would, and every way of asking for a conversion that cannot happen
is one error on the author's line.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wfb import conversion, formatting
from wfb.build import build as real_build
from wfb.build import load
from wfb.catalog import CATALOG, Type
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

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


def _text(value: str, units: str | None = "auto", fmt: str = "{:.1f} {unit}",
           extra: str = "") -> str:
    units_line = f"\n    units: {units}" if units else ""
    return BASE + f"""
  - id: reading
    type: text
    value: {value}{units_line}
    format: "{fmt}"
    font: FONT_SMALL
    at: {{anchor: center}}
    color: palette.fg
    when_absent: hide{extra}
"""


def _face(text, write_design, bag):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    return face


def _view(text, write_design, bag, db):
    face = _face(text, write_design, bag)
    device = db.get("fenix8solar47mm")
    files = generate(face, [device], write_design("").parent / "build",
                     {device.id: bake_fonts(face, device)}).files()
    return next(v for k, v in files.items() if k.endswith("View.mc"))


def _rendered(text, write_design, bag, db, sample: dict) -> str:
    """The string the preview draws for `reading`, through the same path
    (`wfb.kinds.text._text_value`) the rendered PNG uses."""
    from wfb.kinds.text import _text_value

    face = _face(text, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    placed = next(p for p in resolved.items if p.id == "reading")

    class Renderer:
        options = PreviewOptions()
        values = sample

        def aod_field(self, element, key, base):
            return base

    return _text_value(Renderer(), placed)


# -- the conversion table ------------------------------------------------------


def test_every_convertible_source_has_one_conversion():
    """Each quantity-tagged source maps to exactly one table row; a unit the
    table lacks would silently leave that source unconvertible."""
    tagged = [s for s in CATALOG.values() if s.quantity is not None]
    assert tagged
    for source in tagged:
        assert conversion.conversion_for(source) is not None, source.path


def test_the_same_unit_converts_by_quantity_not_by_unit_string():
    """Altitude and a weekly run distance are both metres; only one becomes
    miles."""
    altitude = conversion.conversion_for(CATALOG.get("complication.altitude"))
    distance = conversion.conversion_for(CATALOG.get("complication.weekly_run_distance"))
    assert altitude.statute.label == "ft" and distance.statute.label == "mi"


def test_a_fixed_system_reads_no_setting():
    found = conversion.conversion_for(CATALOG.get("activity.distance"))
    assert conversion.converted_text("activity.distance", found, "statute") == \
        "activity.distance * 0.00000621371192237334"
    assert "device." not in conversion.converted_text("activity.distance", found, "metric")


# -- codegen -------------------------------------------------------------------


def test_auto_switches_on_the_watchs_own_setting(write_design, bag, db):
    view = _view(_text("activity.distance"), write_design, bag, db)
    method = view.split("function drawReading")[1].split("\n    }")[0]
    assert "var deviceDistanceUnits = settings.distanceUnits;" in method
    assert "(deviceDistanceUnits == 1) ? (activityDistance * 6.21371192237334e-06f)" in method
    assert '((deviceDistanceUnits == 1) ? "mi" : "km")' in method


def test_a_fixed_system_generates_no_settings_read(write_design, bag, db):
    view = _view(_text("weather.temperature", "statute", "{:d}{unit}"), write_design, bag, db)
    method = view.split("function drawReading")[1].split("\n    }")[0]
    assert "temperatureUnits" not in method
    assert "(weatherTemperature * 1.8f) + 32.0f" in method
    assert '"°F"' in method


def test_a_face_without_units_is_unchanged_by_the_setting_sources(write_design, bag, db):
    """A plain `value:` reads no unit setting: the new `device.*_units`
    sources are read only when something binds them."""
    view = _view(_text("activity.distance / 100000.0", None, "{:.1f} km"),
                 write_design, bag, db)
    assert "Units" not in view.split("function drawReading")[1].split("\n    }")[0]


# -- preview -------------------------------------------------------------------


@pytest.mark.parametrize("value, fmt, sample, expected", [
    ("activity.distance", "{:.1f} {unit}", {"activity.distance": 631000}, "6.3 km"),
    ("activity.distance", "{:.1f} {unit}",
     {"activity.distance": 631000, "device.distance_units": 1}, "3.9 mi"),
    ("weather.temperature", "{:d}{unit}", {"weather.temperature": 21.5}, "21°C"),
    ("weather.temperature", "{:d}{unit}",
     {"weather.temperature": 21.5, "device.temperature_units": 1}, "70°F"),
    ("ambient.altitude", "{:d} {unit}",
     {"ambient.altitude": 1234.0, "device.elevation_units": 1}, "4048 ft"),
    ("weather.wind_speed", "{:d} {unit}",
     {"weather.wind_speed": 5.0, "device.distance_units": 1}, "11 mph"),
])
def test_preview_renders_the_converted_value_and_label(write_design, bag, db,
                                                       value, fmt, sample, expected):
    values = {"device.distance_units": 0, "device.elevation_units": 0,
              "device.temperature_units": 0, **sample}
    assert _rendered(_text(value, fmt=fmt), write_design, bag, db, values) == expected


def test_overflow_estimate_uses_the_displayed_range_and_label(write_design, bag):
    """`activity.distance` is seven digits of centimetres; in km or mi it is
    three, plus the label -- must fail against the raw source's digits."""
    from wfb.kinds.text import _glyphs, _widest_text

    element = _face(_text("activity.distance"), write_design, bag).elements[0]
    assert _widest_text(element) == "888.8 km"
    glyphs, _ = _glyphs(element)
    assert set("kmi") <= glyphs


# -- refusals --------------------------------------------------------------------


def _errors(text, write_design, bag):
    assert load(write_design(text), bag) is None
    return bag.errors


def test_units_on_an_expression_is_one_error_naming_the_bare_source(write_design, bag):
    [error] = _errors(_text("activity.distance / 1000.0"), write_design, bag)
    assert error.code == "units" and "not a single source" in error.message
    assert any("activity.distance" in note for note in error.notes)


def test_units_on_a_source_with_no_quantity_says_its_unit(write_design, bag):
    [error] = _errors(_text("heart_rate.current", fmt="{:d} {unit}"), write_design, bag)
    assert "is in bpm" in error.message


def test_units_on_fixed_text_is_an_error(write_design, bag):
    text = BASE + """
  - id: reading
    type: text
    text: "5 km"
    units: auto
"""
    [error] = _errors(text, write_design, bag)
    assert error.code == "units" and "fixed 'text:'" in error.message


def test_unit_field_without_units_is_an_error(write_design, bag):
    [error] = _errors(_text("activity.distance / 100000.0", None), write_design, bag)
    assert error.code == "format" and "{unit}" in error.message


def test_unit_field_only_parses_as_a_label():
    parts = formatting.parse("{:.1f}{unit}")
    assert isinstance(parts[1], formatting.UnitField)
    with pytest.raises(formatting.FormatError):
        formatting.emit("{:.1f}{unit}", "x", Type.FLOAT)


# -- a real build ------------------------------------------------------------------


@pytest.mark.slow
def test_every_quantity_compiles_warning_free(write_design, db, tmp_path, toolchain):
    """The generated `settings.<x>Units` read (an enum compared with 1) and the Float
    arithmetic, through the real `monkeyc`, on a MIP and an older target."""
    text = BASE.replace("targets: [fenix8solar47mm]", "targets: [fenix8solar47mm, fr955]")
    for index, (value, units, fmt) in enumerate([
        ("activity.distance", "auto", "{:.1f} {unit}"),
        ("weather.temperature", "auto", "{:d}{unit}"),
        ("ambient.altitude", "statute", "{:d} {unit}"),
        ("weather.wind_speed", "metric", "{:d} {unit}"),
        ("complication.weekly_run_distance", "auto", "{:.0f} {unit}"),
    ]):
        text += f"""
  - id: reading{index}
    type: text
    value: {value}
    units: {units}
    format: "{fmt}"
    font: FONT_XTINY
    at: {{anchor: center, dy: {index * 10 - 20}%r}}
    color: palette.fg
    when_absent: hide
"""
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    warnings = [d for d in bag.items if d.severity.value in ("warning", "error")]
    assert not warnings, bag.render()
