"""A `complication_slot`'s reading, formatted per complication type
(`wfb.complications.READING`): the Python twin the preview draws with, the
generated `SlotText.mc` the watch runs, and the icon, glyph and width
consequences of both.

The raw values are the ones a fenix 8 solar reported for each type in the
simulator (2026-09-28), drawn raw before this rule existed: sunrise 22512,
a 5k prediction 1480, a 5k pace 3.38, pressure 101675.
"""

from __future__ import annotations

import pytest

from wfb import complications, icons
from wfb.complications import ReadingSettings, format_reading
from wfb.diagnostics import Bag
from tests.helpers import load_face as _face, resolve_text as _resolved

TWELVE_HOUR_STATUTE = ReadingSettings(
    is_24_hour=False, statute_distance=True, statute_elevation=True,
    statute_temperature=True, statute_pace=True)


# -- the Python twin ------------------------------------------------------------


@pytest.mark.parametrize("name, value, shown", [
    ("steps", 8809, "8809"),
    ("steps", 12879, "12.9K"),             # scaled here
    ("calories", 339, "339"),
    ("intensity_minutes", 17, "17"),       # minutes stay a plain number
    ("sunrise", 22512, "06:15"),
    ("sunset", 65558, "18:12"),
    ("altitude", 511.0, "511"),
    ("sea_level_pressure", 101675.0, "1017"),
    ("recovery_time", 0, "0h"),
    ("recovery_time", 1, "1h"),            # time still left never reads as none
    ("recovery_time", 2161, "37h"),
    ("race_predictor_5k", 1480, "24:40"),
    ("race_predictor_5k", 590, "9:50"),
    ("race_predictor_marathon", 12345, "3:25:45"),
    ("race_pace_predictor_5k", 3.38, "4:56"),
    ("pulse_ox", 100, "100"),
    ("battery", 100, "100"),
    ("current_temperature", 23.9, "24°"),
    ("current_temperature", -2.5, "-3°"),  # halves away from zero
    ("high_low_temperature", "H 26 / L 17", "H 26 / L 17"),
    ("training_status", "MAINTAINING", "MAINTAINING"),
    ("current_weather", 0, "Clear"),
    ("forecast_weather_1day", 23, "Mostly clear"),
    ("current_weather", 99, "Unknown"),    # outside the documented 0-53
    ("weekly_run_distance", 23400.0, "23.4"),
    ("date", "28 Sep", "28 Sep"),
])
def test_each_type_reads_by_its_own_rule(name, value, shown):
    assert format_reading(name, value) == shown


def test_a_count_the_device_already_scaled_keeps_its_k():
    """Seen in the simulator: steps past 10,000 arrive as the Float 12.879
    with the unit "K".  The K is part of the number, so it is drawn even
    without `unit:`."""
    assert format_reading("steps", 12.879, "K") == "12.9K"
    assert format_reading("steps", 12.879, "K", unit=True) == "12.9K"


@pytest.mark.parametrize("name, value", [
    ("vo2max_bike", 0),                    # nothing recorded
    ("race_pace_predictor_5k", 0.0),       # no speed, no pace
    ("steps", None),
])
def test_a_reading_with_nothing_to_show_is_absent(name, value):
    assert format_reading(name, value) is None


@pytest.mark.parametrize("name, value, shown", [
    ("battery", 100, "100%"),
    ("body_battery", 43, "43%"),
    ("pulse_ox", 97, "97%"),
    ("heart_rate", 77, "77bpm"),
    ("sea_level_pressure", 101675.0, "1017hPa"),
    ("altitude", 511.0, "511m"),
    ("weekly_run_distance", 23400.0, "23.4km"),
    ("race_pace_predictor_5k", 3.38, "4:56/km"),
    ("current_temperature", 23.9, "24°C"),
])
def test_unit_adds_the_readings_own_unit(name, value, shown):
    assert format_reading(name, value) != shown
    assert format_reading(name, value, unit=True) == shown


@pytest.mark.parametrize("name, value, shown", [
    ("sunrise", 22512, "6:15"),
    ("sunset", 65558, "6:12"),
    ("altitude", 511.0, "1677ft"),
    ("weekly_run_distance", 23400.0, "14.5mi"),
    ("race_pace_predictor_5k", 3.38, "7:56/mi"),
    ("current_temperature", 23.9, "75°F"),
])
def test_a_reading_follows_the_watchs_clock_and_units(name, value, shown):
    assert format_reading(name, value, unit=True, settings=TWELVE_HOUR_STATUTE) == shown


@pytest.mark.parametrize("name, value, long, short", [
    ("training_status", "MAINTAINING", "MAINTAINING", "MAINT"),
    ("training_status", "Productive", "Productive", "Prodctv"),  # keeps the reported case
    ("training_status", "SOMETHING NEW", "SOMETHING NEW", "SOMETHING NEW"),  # never cut
    ("high_low_temperature", "H 26 / L 17", "H 26 / L 17", "26/17"),
    ("high_low_temperature", "H -5 / L -12", "H -5 / L -12", "-5/-12"),
    ("current_weather", 23, "Mostly clear", "Mo clr"),
    ("current_weather", 47, "Cloudy chance of rain snow", "Ch r/s"),
    ("date", "28 sept.", "28 sept.", "28 sept."),  # the device's text is never cut
])
def test_short_uses_the_seven_character_forms(name, value, long, short):
    assert format_reading(name, value) == long
    assert format_reading(name, value, short=True) == short


def test_short_drops_a_unit_that_would_pass_seven_characters():
    slow = 1609.344 / 750  # 12:30 a mile
    assert format_reading("race_pace_predictor_5k", slow, unit=True,
                          settings=TWELVE_HOUR_STATUTE) == "12:30/mi"
    assert format_reading("race_pace_predictor_5k", slow, unit=True, short=True,
                          settings=TWELVE_HOUR_STATUTE) == "12:30"
    # one that fits keeps its unit
    assert format_reading("race_pace_predictor_5k", 3.38, unit=True, short=True) == "4:56/km"


def test_every_type_has_a_rule_and_every_short_name_fits():
    assert set(complications.READING) == set(complications.TYPES)
    assert sorted(complications.WEATHER_CONDITION_TEXT) == list(range(54))
    for long, short in complications.WEATHER_CONDITION_TEXT.values():
        assert len(short) <= complications.SHORT_LENGTH, short
    for short in complications.TRAINING_STATUS_SHORT.values():
        assert len(short) <= complications.SHORT_LENGTH, short


# -- the generated SlotText.mc ---------------------------------------------------

HEAD = """format: 2
face:
  id: 6b2f9a3e-5c1d-4e8a-9f7b-3a1d6c8e2f40
  name: Test
build:
  targets: [fenix8solar47mm, fenix8solar51mm, fr955]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
"""


def _design(choices: str, element: str = "", second: str = "") -> str:
    return HEAD + f"""config:
  slots:
    top:
      default: steps
      choices: {choices}
elements:
  top_reading:
    type: data
    slot: top
    at: {{anchor: center, dy: -20%}}
    icon: {{size: 8%r}}
    color: color.fg
{element}{second}"""


def _slot_text(text: str, write_design) -> str:
    from wfb.emit import monkeyc

    face = _face(text, write_design, Bag())
    return monkeyc.emit_slot_text(face).text


def test_slot_text_carries_a_case_only_for_the_slots_choices(write_design):
    """Steps, heart rate and calories: no weather table, no training-status
    table, and no settings read, which none of the three follows."""
    text = _slot_text(_design("[steps, heart_rate, "
                              "calories]"), write_design)
    assert "case Complications.COMPLICATION_TYPE_STEPS:" in text
    assert "COMPLICATION_TYPE_HEART_RATE: return WfbReading.suffixed(" in text
    assert "COMPLICATION_TYPE_SUNRISE" not in text
    assert "conditionName" not in text and "conditionShort" not in text
    assert "trainingShort" not in text
    assert "getDeviceSettings" not in text


def test_slot_text_carries_only_the_name_table_a_slot_draws(write_design):
    weather = "[steps, current_weather]"
    long = _slot_text(_design(weather), write_design)
    assert "function conditionName(" in long and "conditionShort" not in long
    assert "Mostly clear|" in long

    short = _slot_text(_design(weather, "    short: true\n"), write_design)
    assert "function conditionShort(" in short and "conditionName" not in short
    assert "Mo clr|" in short

    both = _slot_text(_design(weather, "", """  again:
    type: data
    slot: top
    at: {anchor: center, dy: 20%}
    color: color.fg
    short: true
"""), write_design)
    assert "function conditionName(" in both and "function conditionShort(" in both
    assert "short ? conditionShort(value.toNumber()) : conditionName(value.toNumber())" in both
    assert "short ? trainingShort(value) : value" not in both  # no training status here


def test_slot_text_tables_match_the_python_ones(write_design):
    """The generated weather and training-status tables are read out of the
    Python ones; parse them back and compare, so neither can drift."""
    import re

    text = _slot_text(_design("any", "    short: true\n", """  again:
    type: data
    slot: top
    at: {anchor: center, dy: 20%}
    color: color.fg
"""), write_design)

    def table(method: str) -> dict[int, str]:
        """`WfbReading.packed`'s reading of the generated literal."""
        body = text[text.index(f"function {method}("):]
        names, width = re.search(r'WfbReading\.packed\("([^"]*)",\s*(\d+), condition\)',
                                 body).groups()
        width = int(width)
        return {i: names[i * width:(i + 1) * width].split("|")[0]
                for i in range(len(names) // width)}

    expected = complications.WEATHER_CONDITION_TEXT
    assert table("conditionName") == {k: v[0] for k, v in expected.items()}
    assert table("conditionShort") == {k: v[1] for k, v in expected.items()}
    training = dict(re.findall(r'case "([^"]+)": return WfbReading.inCaseOf\("([^"]+)"', text))
    assert training == complications.TRAINING_STATUS_SHORT
    # under `choices: any`, every native type with a rule of its own has a
    # case; the device's own text (a date) is drawn as reported, with none
    for ctype in complications.TYPES.values():
        has_case = f"Complications.{ctype.constant}" in text
        assert has_case == (complications.READING[ctype.name] != "text"), ctype.name


def test_the_device_text_is_shortened_only_where_a_slot_is_short(write_design):
    """With no `short:` slot, the training status and high/low text are the
    device's own, and `trainingShort` is neither emitted nor called (a real
    build failed on the call once: "Undefined symbol ':trainingShort'")."""
    long = _slot_text(_design("any"), write_design)
    assert "trainingShort" not in long and "highLowShort" not in long
    assert "COMPLICATION_TYPE_TRAINING_STATUS" not in long

    short = _slot_text(_design("any", "    short: true\n"), write_design)
    assert "COMPLICATION_TYPE_TRAINING_STATUS: return trainingShort(value);" in short
    assert "COMPLICATION_TYPE_HIGH_LOW_TEMPERATURE: return WfbReading.highLowShort(value);" in short
    assert "function trainingShort(" in short


def test_the_view_passes_each_elements_own_unit_and_short(write_design, db):
    from wfb.emit import monkeyc

    _, resolved = _resolved(_design("any", "    unit: true\n    short: true\n"),
                            write_design, Bag(), db)
    view = monkeyc.emit_view(resolved).text
    assert "SlotText.reading(chosenId.getType(), pulled, true, true);" in view


def test_a_design_with_no_slots_has_no_slot_text(write_design, db, tmp_path):
    from wfb.emit import generate

    text = HEAD + """elements:
  clock:
    type: text
    text: "{time.clock:%H:%M}"
    at: {anchor: center}
    color: color.fg
"""
    face = _face(text, write_design, Bag())
    project = generate(face, [db.get("fenix8solar47mm")], tmp_path)
    assert not any(s.path.endswith("SlotText.mc") for s in project.sources)
    assert "WfbReading.mc" not in project.barrel


# -- the weather icon follows the condition --------------------------------------


def test_a_weather_choice_icon_follows_the_pulled_condition(write_design, db):
    from wfb.emit import monkeyc
    from wfb.ir import complication_slot_icon_method

    _, resolved = _resolved(_design("[steps, current_weather]"),
                            write_design, Bag(), db)
    view = monkeyc.emit_view(resolved).text
    method = complication_slot_icon_method("top_reading")
    assert f"var iconName = {method}(chosenId.getType(), pulled);" in view
    assert ("COMPLICATION_TYPE_CURRENT_WEATHER: return (value instanceof Lang.Number)"
            ' ? WfbWeather.chooseIcon(value) : "weather";') in view
    assert 'COMPLICATION_TYPE_STEPS: return "steps";' in view

    placed = next(p for p in resolved.items if p.id == "top_reading")
    from wfb import kinds
    run = next(r for _, r in kinds.placed_text_runs([placed], resolved.face)
               if r.icon is not None)
    assert set(icons.WEATHER_GLYPH_SET) <= set(run.icon.glyphs)
    for name in icons.GARMIN_WEATHER_CONDITION_ICON.values():
        assert name in run.glyph_table


def test_an_authored_weather_icon_stays_as_written(write_design, db):
    from wfb.emit import monkeyc

    _, resolved = _resolved(_design(
        "[steps, {type: current_weather, icon: weather_rain}]"),
        write_design, Bag(), db)
    view = monkeyc.emit_view(resolved).text
    assert 'COMPLICATION_TYPE_CURRENT_WEATHER: return "weather_rain";' in view
    assert "WfbWeather.chooseIcon" not in view


# -- glyphs and widths -------------------------------------------------------------


def test_a_baked_font_gets_every_character_the_readings_draw(write_design):
    from wfb.kinds.complication_slot import _text_glyphs

    face = _face(_design("[steps, sunrise, "
                         "recovery_time, current_temperature]"),
                 write_design, Bag())
    element = next(e for e in face.walk() if e.id == "top_reading")
    glyphs = _text_glyphs(element, face)
    assert {":", "h", "°"} <= glyphs
    assert "a" not in glyphs  # nothing here draws words

    face = _face(_design("[steps, current_weather]",
                         "    short: true\n"), write_design, Bag())
    element = next(e for e in face.walk() if e.id == "top_reading")
    glyphs = _text_glyphs(element, face)
    assert set("Mo clr") <= glyphs and "K" in glyphs


def test_the_lint_width_counts_long_weather_names(write_design, db):
    """`choices: any` in full names can draw "Cloudy chance of rain snow";
    `short: true` keeps it to seven characters, and the estimate says so."""
    long_face, long = _resolved(_design("any"), write_design, Bag(), db)
    short_face, short = _resolved(_design("any", "    short: true\n"), write_design, Bag(), db)
    long_box = next(p for p in long.items if p.id == "top_reading").box
    short_box = next(p for p in short.items if p.id == "top_reading").box
    assert long_box.width > db.get("fenix8solar47mm").width
    assert short_box.width < long_box.width / 2


# -- the real toolchain ------------------------------------------------------------


@pytest.mark.slow
def test_every_reading_rule_compiles_warning_free_on_every_target(
        write_design, tmp_path, db, toolchain):
    """`choices: any` twice, one slot full-length and one `short: true` with
    `unit: true`, so every case, both name tables, the training-status
    table and every `WfbReading` helper are in one program."""
    from wfb.build import build as run_build

    lint = "    lint:\n      allow: [config-unsupported, off-screen]\n      reason: test\n"
    text = _design("any", lint, """  again:
    type: data
    slot: top
    at: {anchor: center, dy: 20%}
    color: color.fg
    unit: true
    short: true
""" + lint)
    design = write_design(text)
    bag = Bag()
    result = run_build(design, output=tmp_path / "out", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning" and d.code == "monkeyc"]
    assert not warnings, "\n".join(d.message for d in warnings)
    slot_text = (result.output_dir / "source" / "SlotText.mc").read_text(encoding="utf-8")
    assert "function conditionName(" in slot_text and "function trainingShort(" in slot_text
    assert (result.output_dir / "runtime-lib" / "WfbReading.mc").exists()
