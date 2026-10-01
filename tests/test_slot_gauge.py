"""A gauge on a `config: slots:` slot: `slot:` in place of `value:`/`max:`.

The reading is the wearer's pick and the scale is that type's own
(`wfb.complications.SCALE`, through the generated `SlotScale`).  A pick with
no scale hides the whole gauge, track included; a scaled pick with no
reading yet follows `absent:` like any gauge.
"""

from __future__ import annotations

import pytest

from tests.helpers import load_errors, load_face as _face
from wfb import complications
from wfb.build import build as real_build
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.manifest import permissions
from wfb.emit.resources import bake_fonts
from wfb.kinds import progress
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

DEVICE = "fenix8solar47mm"
TRACK = (85, 85, 85)
FILL = (255, 170, 0)

HEAD = """format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f59
  name: Test
build:
  targets: [fenix8solar47mm, fenix8solar51mm, fr955]
resources:
  palette:
    bg: "#000000"
    fill: "#FFAA00"
    track: "#555555"
config:
  slots:
    top:
      default: {default}
      choices: [date, current_weather, steps, heart_rate, battery, body_battery]
elements:
"""

ARC = """  gauge:
    type: gauge
    slot: top
    style: arc
    at: {anchor: center}
    radius: 80%r
    thickness: 8%r
    start_angle: 0deg
    sweep: 360deg
    color: color.fill
    track_color: color.track
    absent: hide
"""

NEEDLE = """  gauge:
    type: gauge
    slot: top
    style: needle
    at: {anchor: center}
    start_angle: 240deg
    sweep: 240deg
    color: color.fill
    needle:
      - {type: line, at: {dy: 5%r}, to: {dy: -70%r}, thickness: 4px}
    absent: hide
"""

SEGMENTS_FALLBACK = """  gauge:
    type: gauge
    slot: top
    style: segments
    at: {anchor: center}
    size: {width: 60%, height: 10%}
    count: 5
    color: color.fill
    track_color: color.track
    absent: {value: 0.5}
"""


def _design(element: str, default: str = "steps") -> str:
    return HEAD.replace("{default}", default) + element


def _colors(text, write_design, db):
    face = _face(text, write_design, Bag())
    device = db.get(DEVICE)
    resolved = resolve(face, device, bake_fonts(face, device))
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    return {color for _, color in image.convert("RGB").getcolors(1 << 20)}


def _files(text, write_design, db):
    face = _face(text, write_design, Bag())
    devices = [db.get(DEVICE)]
    return generate(face, devices, write_design(text).parent / "out",
                    {d.id: bake_fonts(face, d) for d in devices}).files()


def _method(text, write_design, db):
    view = next(body for name, body in _files(text, write_design, db).items()
                if name.endswith("View.mc"))
    return view.split("private function drawGauge")[1].split("\n    }\n")[0]


def _messages(text, write_design):
    return [d.message for d in load_errors(text, write_design)]


# -- the format ----------------------------------------------------------------


def test_a_slot_gauge_builds(write_design):
    assert load_errors(_design(ARC), write_design) == []


def test_value_and_slot_cannot_both_be_set(write_design):
    text = _design(ARC.replace("    slot: top\n", "    slot: top\n    value: 5\n"))
    assert any("'value' and 'slot' cannot both be set" in m for m in _messages(text, write_design))


@pytest.mark.parametrize("key, line", [
    ("max", "    max: 100\n"),
    ("bands", "    bands: [{to: 0.5, color: color.fill}]\n"),
])
def test_a_key_the_slot_gauge_does_not_read_is_refused(key, line, write_design):
    text = _design(ARC.replace("    slot: top\n", f"    slot: top\n{line}"))
    if key == "bands":
        text = text.replace("style: arc", "style: scale")
    messages = _messages(text, write_design)
    assert any(f"'{key}:' is not read beside 'slot:'" in m for m in messages), messages


def test_a_gauge_with_value_still_needs_max(write_design):
    text = _design(ARC.replace("    slot: top\n", "    value: 5\n"))
    messages = _messages(text, write_design)
    assert any("missing required key 'max' -- 'value' needs it" in m for m in messages), messages


def test_a_gauge_needs_value_or_slot(write_design):
    assert _messages(_design(ARC.replace("    slot: top\n", "")), write_design)


def test_an_unknown_slot_is_refused(write_design):
    text = _design(ARC.replace("slot: top", "slot: nowhere"))
    assert any("unknown slot 'nowhere'" in m for m in _messages(text, write_design))


def test_the_slots_reading_needs_an_absent_policy(write_design):
    text = _design(ARC.replace("    absent: hide\n", ""))
    messages = _messages(text, write_design)
    assert any("slot top" in m and "'absent:' is required" in m for m in messages), messages


def test_on_hold_auto_is_not_implemented_on_a_slot_gauge(write_design):
    text = _design(ARC + "    on_hold: auto\n")
    messages = _messages(text, write_design)
    assert any("'on_hold: auto' on a gauge with 'slot:' is not implemented yet" in m
               for m in messages), messages


def test_a_slot_gauge_may_not_be_inside_a_layout(write_design):
    text = _design("""  clock:
    type: text
    text: "{time.clock:%H:%M}"
    font: FONT_SMALL
    at: {anchor: center}
    color: color.fill
""").replace("config:\n", "layouts:\n  big:\n    elements:\n" + "\n".join(
        "    " + line if line else line for line in ARC.splitlines()) + "\nconfig:\n"
    ).replace("config:\n  slots:",
              "config:\n  style:\n    default: big\n    choices:\n      big: {layout: big}\n  slots:")
    messages = _messages(text, write_design)
    assert any("a gauge with 'slot:' may not be inside layout 'big'" in m for m in messages), messages


# -- the preview ---------------------------------------------------------------


def test_a_scaled_pick_draws_its_fill_and_track(write_design, db):
    colors = _colors(_design(ARC, "steps"), write_design, db)
    assert FILL in colors and TRACK in colors


def test_a_pick_with_no_scale_hides_the_whole_gauge(write_design, db):
    """The date has no scale: no fill, and no track either -- the contrast
    with `absent: hide`, which keeps the track."""
    colors = _colors(_design(ARC, "date"), write_design, db)
    assert FILL not in colors and TRACK not in colors


def test_a_scaled_pick_without_a_reading_keeps_its_track(write_design, db, monkeypatch):
    sample = dict(progress.COMPLICATION_SLOT_SAMPLE)
    del sample["battery"]
    monkeypatch.setattr(progress, "COMPLICATION_SLOT_SAMPLE", sample)
    colors = _colors(_design(ARC, "battery"), write_design, db)
    assert TRACK in colors and FILL not in colors


# -- the generated code ------------------------------------------------------------


def test_everything_is_wrapped_in_the_scale_and_nothing_returns(write_design, db):
    method = _method(_design(ARC), write_design, db)
    assert "var scale = (chosenType != null && pulled != null) " \
           "? SlotScale.scale(chosenType, pulled) : null;" in method
    assert "return;" not in method
    wrap = method.index("if (scale != null && pulled != null)")
    track = method.index("Palette.TRACK")
    guard = method.index("if (reading != null)")
    assert wrap < track < guard < method.index("WfbArc.drawProgress")


def test_a_needle_hides_whole_while_the_reading_is_absent(write_design, db):
    method = _method(_design(NEEDLE), write_design, db)
    assert method.index("if (reading != null)") < method.index("Math.sin")


def test_a_fallback_substitutes_the_fill(write_design, db):
    method = _method(_design(SEGMENTS_FALLBACK), write_design, db)
    assert "var fraction = (reading != null) ? reading : 0.5f;" in method
    assert "(fraction) * 5 + 0.5" in method


def test_slot_scale_has_a_case_for_each_choice_with_a_scale(write_design, db):
    text = _files(_design(ARC), write_design, db)["source/SlotScale.mc"]
    for name in ("STEPS", "HEART_RATE", "BATTERY", "BODY_BATTERY"):
        assert f"COMPLICATION_TYPE_{name}:" in text
    for name in ("DATE", "CURRENT_WEATHER", "STRESS", "INVALID"):
        assert f"COMPLICATION_TYPE_{name}" not in text


def test_no_slot_gauge_no_slot_scale(write_design, db):
    text = _design("""  reading:
    type: data
    slot: top
    at: {anchor: center}
    color: color.fill
""")
    assert "source/SlotScale.mc" not in _files(text, write_design, db)


def test_a_face_that_never_scales_by_the_profile_ships_none_of_it(write_design, db):
    """`monkeyc` refuses any `Toybox.UserProfile` reference without the
    permission, so the profile reads live in their own module, and a slot
    that cannot show heart rate or VO2 max must not ship it."""
    text = _design(ARC).replace(
        "choices: [date, current_weather, steps, heart_rate, battery, body_battery]",
        "choices: [date, steps, battery]")
    face = _face(text, write_design, Bag())
    devices = [db.get(DEVICE)]
    project = generate(face, devices, write_design(text).parent / "out",
                       {d.id: bake_fonts(face, d) for d in devices})
    assert "WfbScale.mc" in project.barrel
    assert "WfbProfileScale.mc" not in project.barrel
    assert "UserProfile" not in project.files()["manifest.xml"]


@pytest.mark.parametrize("choices, profile", [
    ("[date, steps, heart_rate]", True),
    ("[steps, vo2max_run]", True),
    ("any", True),
    ("[date, steps, battery, body_battery]", False),
])
def test_user_profile_is_derived_from_what_the_scale_reads(choices, profile, write_design):
    text = _design(ARC).replace(
        "choices: [date, current_weather, steps, heart_rate, battery, body_battery]",
        f"choices: {choices}")
    face = _face(text, write_design, Bag())
    assert ("UserProfile" in permissions(face)) is profile
    assert "ComplicationSubscriber" in permissions(face)


# -- the fill fraction ---------------------------------------------------------


@pytest.mark.parametrize("value, unit, scale, expected", [
    (133, None, (95.0, 190.0), 0.4),        # heart rate from zone 1's minimum
    (95, None, (95.0, 190.0), 0.0),
    (80, None, (95.0, 190.0), 0.0),         # below the scale: clamped
    (12.0, "K", (0.0, 8000.0), 1.0),        # 12,000 steps in thousands, past the goal
    (4.0, "K", (0.0, 8000.0), 0.5),
    (62, None, (0.0, 100.0), 0.62),
    ("H 19 / L 13", None, (0.0, 100.0), None),
    (None, None, (0.0, 100.0), None),
])
def test_the_fill_runs_from_the_scales_minimum(value, unit, scale, expected):
    got = complications.scale_fraction(value, unit, scale)
    assert got == expected if expected is None else got == pytest.approx(expected)


def test_a_vo2max_of_zero_has_no_scale():
    """0 is how a watch reports no VO2 max recorded (seen on an fr955)."""
    args = {"goals": {}, "heart_rate_zones": None, "sex": "male", "age": 35}
    assert complications.scale_for("vo2max_run", value=0, **args) is None
    assert complications.scale_for("vo2max_run", value=49, **args) == (36.0, 58.5)


def test_the_watch_fraction_matches_the_twin():
    """`scale_fraction` models `WfbScale.fraction`; keep the two in step by
    reading the helper's own source."""
    from pathlib import Path
    lib = Path(__file__).parent.parent / "runtime-lib"
    source = (lib / "WfbScale.mc").read_text()
    assert "var full = (reading.toFloat() - low) / (scale[1].toFloat() - low);" in source
    assert 'unit.equals("K")' in source and "reading = reading * 1000;" in source
    assert "if (value instanceof Lang.Number && value == 0)" in (
        lib / "WfbProfileScale.mc").read_text()


# -- a real build --------------------------------------------------------------


@pytest.mark.slow
def test_slot_gauges_compile_warning_free(tmp_path, bag, db, toolchain):
    """An arc, a needle and a segments gauge with a fallback, on a listed slot
    and a `choices: any` one, through `-l 3` on all three targets."""
    any_slot = HEAD.replace("{default}", "steps").replace(
        "elements:\n", "    bottom: {default: body_battery, choices: any}\nelements:\n")
    design = tmp_path / "slot-gauge.yaml"
    design.write_text(
        any_slot + ARC + NEEDLE.replace("  gauge:", "  needle:").replace("slot: top", "slot: bottom")
        + SEGMENTS_FALLBACK.replace("  gauge:", "  bar:"),
        encoding="utf-8")
    result = real_build(design, output=tmp_path / "build", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert len(result.products) == 3
    complaints = [d for d in bag.items if d.severity.value == "error"
                  or (d.severity.value == "warning" and d.code == "monkeyc")]
    assert not complaints, bag.render()


@pytest.mark.slow
def test_a_slot_gauge_without_profile_scales_compiles(tmp_path, bag, db, toolchain):
    """No heart rate or VO2 max among the choices: no UserProfile permission,
    and nothing that needs it shipped (monkeyc refused this once)."""
    design = tmp_path / "plain.yaml"
    design.write_text(_design(ARC).replace(
        "choices: [date, current_weather, steps, heart_rate, battery, body_battery]",
        "choices: [date, steps, battery]"), encoding="utf-8")
    result = real_build(design, output=tmp_path / "build", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert len(result.products) == 3
    complaints = [d for d in bag.items if d.severity.value == "error"
                  or (d.severity.value == "warning" and d.code == "monkeyc")]
    assert not complaints, bag.render()


# -- max: auto on a fixed complication -----------------------------------------

AUTO_HEAD = """format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f61
  name: Test
build:
  targets: [fenix8solar47mm, fenix8solar51mm, fr955]
resources:
  palette:
    bg: "#000000"
    fill: "#FFAA00"
    track: "#555555"
elements:
"""

AUTO = """  gauge:
    type: gauge
    style: arc
    value: {value}
    max: auto
    at: {anchor: center}
    radius: 80%r
    thickness: 8%r
    start_angle: 0deg
    sweep: 360deg
    color: color.fill
    track_color: color.track
    absent: hide
"""


def _auto(value: str) -> str:
    return AUTO_HEAD + AUTO.replace("{value}", value)


def test_max_auto_builds_on_a_scaled_complication(write_design):
    assert load_errors(_auto("complication.steps"), write_design) == []


@pytest.mark.parametrize("value, expected", [
    ("complication.steps / 2", "'max: auto' needs 'value:' to be a bare 'complication.<type>'"),
    ("activity.steps", "'max: auto' needs 'value:' to be a bare 'complication.<type>'"),
    ("complication.calories", "'max: auto' -- complication.calories has no scale of its own"),
])
def test_max_auto_is_refused_where_there_is_no_scale_to_take(value, expected, write_design):
    messages = _messages(_auto(value), write_design)
    assert any(expected in m for m in messages), messages


def test_max_auto_wraps_the_gauge_in_the_types_own_scale(write_design, db):
    method = _method(_auto("complication.steps"), write_design, db)
    assert ("var scale = (stepsComplication != null) "
            "? SlotScale.scale(Complications.COMPLICATION_TYPE_STEPS, stepsComplication) : null;"
            in method)
    assert method.index("if (scale != null)") < method.index("Palette.TRACK")
    assert "WfbScale.share(complicationSteps, scale)" in method
    assert "return;" not in method


@pytest.mark.parametrize("value, profile", [
    ("complication.heart_rate", True), ("complication.vo2max_run", True),
    ("complication.steps", False), ("complication.body_battery", False),
])
def test_max_auto_derives_user_profile_only_for_a_profile_scale(value, profile, write_design, db):
    text = _auto(value)
    face = _face(text, write_design, Bag())
    assert ("UserProfile" in permissions(face)) is profile
    devices = [db.get(DEVICE)]
    project = generate(face, devices, write_design(text).parent / "out",
                       {d.id: bake_fonts(face, d) for d in devices})
    assert ("WfbProfileScale.mc" in project.barrel) is profile


def test_max_auto_hides_whole_without_a_scale_in_the_preview(write_design, db):
    """A VO2 max of 0 (none recorded) has no scale: no track either -- the
    contrast with a recorded one, which draws both."""
    def colors(vo2max):
        face = _face(_auto("complication.vo2max_run"), write_design, Bag())
        device = db.get(DEVICE)
        image = render(resolve(face, device, bake_fonts(face, device)),
                       PreviewOptions(scale=1, mask_shape=False, quantise=False,
                                      sample={"complication.vo2max_run": vo2max}))
        return {color for _, color in image.convert("RGB").getcolors(1 << 20)}
    recorded = colors(49)
    assert FILL in recorded and TRACK in recorded
    none = colors(0)
    assert FILL not in none and TRACK not in none


@pytest.mark.slow
def test_max_auto_compiles_warning_free(tmp_path, bag, db, toolchain):
    """A goal scale, the heart-rate zones with a fallback fill, and a fixed
    0-100, through `-l 3` on all three targets."""
    design = tmp_path / "auto.yaml"
    design.write_text(
        _auto("complication.steps")
        + AUTO.replace("  gauge:", "  hr:").replace("{value}", "complication.heart_rate")
              .replace("absent: hide", "absent: {value: 0.0}")
        + AUTO.replace("  gauge:", "  bb:").replace("{value}", "complication.body_battery"),
        encoding="utf-8")
    result = real_build(design, output=tmp_path / "build", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert len(result.products) == 3
    complaints = [d for d in bag.items if d.severity.value == "error"
                  or (d.severity.value == "warning" and d.code == "monkeyc")]
    assert not complaints, bag.render()
