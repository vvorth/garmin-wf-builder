"""Duration formats: strftime codes on a Number or Float of seconds.

One spec language serves a time of day read as seconds since midnight
(sunrise), a duration (a race predictor, recovery time) and a pace (seconds
per km, from `units:`).  These tests pin the three rules that make it one
language rather than three: the largest unit carries the total, smaller
units wrap, and a time-of-day code wraps at 24 hours and carries no sign.
"""

from __future__ import annotations

import pytest

from wfb import formatting
from wfb.build import build as real_build
from wfb.build import load
from wfb.catalog import Type
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions

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


def _text(value: str, fmt: str, extra: str = "") -> str:
    return BASE + f"""
  - id: reading
    type: text
    value: {value}
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


def _method(text, write_design, bag, db) -> str:
    face = _face(text, write_design, bag)
    device = db.get("fenix8solar47mm")
    files = generate(face, [device], write_design("").parent / "build",
                     {device.id: bake_fonts(face, device)}).files()
    view = next(v for k, v in files.items() if k.endswith("View.mc"))
    return view.split("function drawReading")[1].split("\n    }")[0]


def _rendered(text, write_design, bag, db, sample: dict) -> str:
    """What the preview draws for `reading` (`wfb.kinds.text._text_value`)."""
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


# -- the rules -------------------------------------------------------------------


@pytest.mark.parametrize("spec, seconds, expected", [
    # The largest unit carries the total: 3900 s is 65 minutes, not 5.
    ("{:%M:%S}", 3900, "65:00"),
    ("{:%H:%M:%S}", 3900, "01:05:00"),
    # Unpadded leading fields: a pace, a marathon, a recovery time.
    ("{:%-M:%S}", 270, "4:30"),
    ("{:%-H:%M:%S}", 13512, "3:45:12"),
    ("{:%-H:%M}", 2235 * 60, "37:15"),
    # Hours lead a time of day too, and minutes wrap under them.
    ("{:%H:%M}", 24120, "06:42"),
    # A negative duration keeps its magnitude and gains a sign.
    ("{:%-M:%S}", -75, "-1:15"),
    # Text around the field, and a literal percent, survive.
    ("T-{:%-M:%S} left", 75, "T-1:15 left"),
    ("{:%-S%%}", 7, "7%"),
])
def test_duration_rendering(spec, seconds, expected):
    assert formatting.render(spec, seconds, Type.NUMBER) == expected


def test_a_float_truncates_toward_zero_like_toNumber():
    """272.7 s is 4:32, and -0.5 s is no sign at all: `Float.toNumber()`
    truncates, so a rounding or flooring preview would disagree."""
    assert formatting.render("{:%-M:%S}", 272.7, Type.FLOAT) == "4:32"
    assert formatting.render("{:%-M:%S}", -0.5, Type.FLOAT) == "0:00"


@pytest.mark.parametrize("is_24_hour, expected", [
    (True, "18:05 PM"),
    (False, "6:05 PM"),
])
def test_time_of_day_follows_the_12_24_hour_setting(is_24_hour, expected):
    seconds = 18 * 3600 + 5 * 60
    assert formatting.render("{:%h:%M %p}", seconds, Type.NUMBER,
                             {"device.is_24_hour": is_24_hour}) == expected


def test_a_time_of_day_wraps_at_24_hours_and_carries_no_sign():
    """90000 s is 25 h: a duration says 25, a time of day says 1 AM."""
    assert formatting.render("{:%H:%M}", 90000, Type.NUMBER) == "25:00"
    assert formatting.render("{:%l:%M %p}", 90000, Type.NUMBER) == "1:00 AM"
    assert formatting.render("{:%I:%M}", -3600, Type.NUMBER) == "01:00"


# -- emission ------------------------------------------------------------------------


def test_emission_passes_the_leading_unit_unwrapped():
    code = formatting.emit("{:%-M:%S}", "pace", Type.FLOAT)
    assert code == ('WfbTime.durationSign(pace) + WfbTime.durationPart(pace, 60, 0).format("%d")'
                    ' + ":" + WfbTime.durationPart(pace, 1, 60).format("%02d")')


def test_a_time_of_day_emits_no_sign_and_reads_the_setting_only_for_h():
    code = formatting.emit("{:%h:%M}", "sunrise", Type.NUMBER)
    assert "durationSign" not in code
    assert "WfbTime.displayHour(WfbTime.durationPart(sunrise, 3600, 24), settings.is24Hour)" in code
    assert formatting.extra_paths("{:%h:%M}", Type.NUMBER) == ("device.is_24_hour",)
    assert formatting.extra_paths("{:%l:%M %p}", Type.NUMBER) == ()


def test_widest_and_glyphs():
    assert formatting.widest("{:%-M:%S} {unit}", None, Type.FLOAT, unit_widest="/km") == "88:59 /km"
    assert formatting.widest("{:%h:%M %p}", None, Type.NUMBER) == "23:59 AM"
    assert "-" in formatting.glyphs("{:%-M:%S}", None, Type.NUMBER)
    time_of_day = formatting.glyphs("{:%l:%M %p}", None, Type.NUMBER)
    assert "-" not in time_of_day and set("AMP") <= time_of_day


def test_the_flag_is_only_valid_where_the_table_has_it():
    with pytest.raises(formatting.FormatError, match="unknown duration code %-Q"):
        formatting.emit("{:%-Q}", "x", Type.NUMBER)
    with pytest.raises(formatting.FormatError, match="unknown time code %-H"):
        formatting.emit("{:%-H}", "", Type.TIME)


# -- a face: codegen, preview, the checks ------------------------------------------------


def test_sunrise_reads_no_clock(write_design, bag, db):
    """A duration's hour comes from the value, not from `clock.hour`."""
    method = _method(_text("complication.sunrise", "{:%h:%M}"), write_design, bag, db)
    assert "WfbTime.durationPart(complicationSunrise, 3600, 24)" in method
    assert "clock" not in method
    assert "settings.is24Hour" in method


def test_a_minutes_source_is_read_as_seconds(write_design, bag, db):
    text = _text("complication.recovery_time", "{:%-H:%M}")
    method = _method(text, write_design, bag, db)
    assert "(complicationRecoveryTime * 60)" in method
    assert _rendered(text, write_design, Bag(), db,
                     {"complication.recovery_time": 2235}) == "37:15"


def test_an_expression_is_read_as_seconds_as_written(write_design, bag, db):
    """No scaling reaches past a bare source: the author's arithmetic
    already decided the unit."""
    method = _method(_text("complication.recovery_time * 60", "{:%-H:%M}"),
                     write_design, bag, db)
    assert "* 60 * 60" not in method and "60) * 60" not in method


def test_a_plain_number_format_on_a_minutes_source_is_not_scaled(write_design, bag, db):
    method = _method(_text("complication.recovery_time", "{:d} min"), write_design, bag, db)
    assert "* 60" not in method


@pytest.mark.parametrize("sample, expected", [
    ({"complication.race_pace_predictor_5k": 1000 / 270, "device.pace_units": 0}, "4:30/km"),
    ({"complication.race_pace_predictor_5k": 1609.344 / 434, "device.pace_units": 1}, "7:14/mi"),
    ({"complication.race_pace_predictor_5k": 0.0, "device.pace_units": 0}, "0:00/km"),
])
def test_pace_from_units(write_design, bag, db, sample, expected):
    text = _text("complication.race_pace_predictor_5k", "{:%-M:%S}{unit}",
                 extra="\n    units: auto")
    assert _rendered(text, write_design, bag, db, sample) == expected


def test_pace_guards_a_zero_speed_in_the_generated_code(write_design, bag, db):
    method = _method(_text("complication.race_pace_predictor_5k", "{:%-M:%S}{unit}",
                           extra="\n    units: auto"), write_design, bag, db)
    assert "settings.paceUnits" in method
    assert "complicationRacePacePredictor5k > 0" in method


def test_an_unknown_duration_code_is_one_error_on_the_format_line(write_design, bag):
    assert load(write_design(_text("complication.sunrise", "{:%a %M}")), bag) is None
    [error] = bag.errors
    assert error.code == "format" and "unknown duration code %a" in error.message


def test_a_strftime_spec_on_a_string_is_still_an_error(write_design, bag):
    assert load(write_design(_text("date.month", "{:%H}")), bag) is None
    assert any("needs a time, date or number value" in e.message for e in bag.errors)


def test_a_pattern_text_part_cannot_follow_the_12_24_hour_setting(write_design, bag):
    text = BASE + """
  - id: dial
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 4
    color: palette.fg
    parts:
      - shape: text
        value: copy * 21600
        format: "{:%h}"
        at: {dy: -80%r}
"""
    assert load(write_design(text), bag) is None
    [error] = bag.errors
    assert error.code == "format" and "12/24-hour" in error.message


def test_a_pattern_text_part_takes_a_fixed_duration(write_design, bag):
    text = BASE + """
  - id: dial
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 4
    color: palette.fg
    parts:
      - shape: text
        value: copy * 21600
        format: "{:%H}"
        at: {dy: -80%r}
"""
    face = _face(text, write_design, bag)
    assert face.elements[0].parts[0].texts == ("00", "06", "12", "18")


# -- a real build --------------------------------------------------------------------


@pytest.mark.slow
def test_every_duration_code_compiles_warning_free(write_design, db, tmp_path, toolchain):
    """Every `DURATION_CODES` row through the real `monkeyc`, on a Number
    and a Float, a time of day, a scaled source and a pace -- the
    `WfbTime.durationPart` `Numeric` parameter included."""
    text = BASE.replace("targets: [fenix8solar47mm]", "targets: [fenix8solar47mm, fr955]")
    rows = [
        ("complication.sunrise", "{:%h:%M %p}", ""),
        ("complication.sunset", "{:%I:%M %l}", ""),
        ("complication.race_predictor_marathon", "{:%-H:%M:%S %H %-M %-S %%}", ""),
        ("complication.recovery_time", "{:%-H:%M}", ""),
        ("complication.race_pace_predictor_5k", "{:%-M:%S}{unit}", "\n    units: auto"),
        ("system.battery_in_days", "{:%H}h", ""),
    ]
    for index, (value, fmt, extra) in enumerate(rows):
        text += f"""
  - id: reading{index}
    type: text
    value: {value}
    format: "{fmt}"
    font: FONT_XTINY
    at: {{anchor: center, dy: {index * 10 - 25}%r}}
    color: palette.fg
    when_absent: hide{extra}
"""
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    warnings = [d for d in bag.items if d.severity.value in ("warning", "error")]
    assert not warnings, bag.render()
