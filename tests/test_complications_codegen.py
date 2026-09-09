"""Generated Monkey C for `complication.*` sources.

Every complication is read by *pull*, exactly like every other reader in the
catalogue (`Weather.getCurrentConditions()`, `ActivityMonitor.getInfo()`, ...):
`WfbComplications.valueOf(...)` is called fresh from `onUpdate` every frame.
There is no cache field, no staleness check, and `onComplicationChanged`'s
only job is to ask for an earlier redraw -- see
`docs/research/probes/complication-pull/README.md` and
`runtime-lib/WfbComplications.mc`'s own header for why a subscription is kept
anyway.  These need only the device files (for font baking), not the Garmin
toolchain -- see tests/test_weather_codegen.py for the equivalent split on
`weather.*`.
"""

from __future__ import annotations

from tests.test_diagnostics import load
from wfb.emit.manifest import api_level
from wfb.emit.project import _barrel_for, _features, generate
from wfb.emit.resources import bake_fonts

DESIGN = """
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f58, name: Test}}
targets: [fenix8solar47mm]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
elements:
  - id: bg
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
{elements}
"""

BODY_BATTERY = """
  - id: bb
    type: text
    value: complication.body_battery
    format: "{}"
    when_absent: hide
    font: FONT_TINY
    at: {anchor: center}
    color: palette.fg
"""

TWO_COMPLICATIONS = """
  - id: bb
    type: text
    value: complication.body_battery
    format: "{}"
    when_absent: hide
    font: FONT_TINY
    at: {anchor: center, dy: -20%}
    color: palette.fg
  - id: training
    type: text
    value: complication.training_status
    format: "{}"
    when_absent: hide
    font: FONT_TINY
    at: {anchor: center, dy: 20%}
    color: palette.fg
"""

NO_COMPLICATION = """
  - id: steps
    type: text
    value: activity.steps
    format: "{:d}"
    when_absent: hide
    font: FONT_TINY
    at: {anchor: center}
    color: palette.fg
"""


def _build(write_design, bag, db, tmp_path, elements: str):
    face = load(write_design(DESIGN.format(elements=elements)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = bake_fonts(face, device, device.minor_radius)
    project = generate(face, [device], tmp_path, {device.id: baked})
    return face, project


def _view(write_design, bag, db, tmp_path, elements: str) -> str:
    _, project = _build(write_design, bag, db, tmp_path, elements)
    return project.files()["source/TestView.mc"]


def test_no_private_complication_cache_field_is_declared(write_design, bag, db, tmp_path):
    """There used to be one `private var ..Cache` per bound complication --
    the whole point of this change is that nothing is cached between frames,
    so no such field should exist at all."""
    view = _view(write_design, bag, db, tmp_path, BODY_BATTERY)
    private_var_lines = [line for line in view.splitlines() if "private var" in line]
    assert not any("Complication" in line for line in private_var_lines)
    assert "Cache" not in view


def test_onupdate_pulls_the_complication_every_frame(write_design, bag, db, tmp_path):
    """`onUpdate` calls `WfbComplications.valueOf` directly -- the ordinary
    per-frame read every other reader gets, not a copy out of a cached
    field."""
    view = _view(write_design, bag, db, tmp_path, BODY_BATTERY)
    assert ("var bodyBatteryComplication = WfbComplications.valueOf("
            "new Complications.Id(Complications.COMPLICATION_TYPE_BODY_BATTERY));") in view
    # exactly one such read -- in onUpdate's per-frame block, not per element.
    assert view.count("WfbComplications.valueOf(new Complications.Id("
                       "Complications.COMPLICATION_TYPE_BODY_BATTERY))") == 1


def test_read_carries_the_right_cast_per_value_type(write_design, bag, db, tmp_path):
    """`Complications.Complication.value` is a union type -- the declared
    local for each source must carry that source's own cast."""
    view = _view(write_design, bag, db, tmp_path, TWO_COMPLICATIONS)
    assert ("var complicationBodyBattery = (bodyBatteryComplication != null) "
            "? bodyBatteryComplication.value as Number? : null;") in view
    assert ("var complicationTrainingStatus = (trainingStatusComplication != null) "
            "? trainingStatusComplication.value as String? : null;") in view


def test_weekly_run_distance_casts_to_float(write_design, bag, db, tmp_path):
    design = """
  - id: run
    type: text
    value: complication.weekly_run_distance
    format: "{:.1f}"
    when_absent: hide
    font: FONT_TINY
    at: {anchor: center}
    color: palette.fg
"""
    view = _view(write_design, bag, db, tmp_path, design)
    assert ("var complicationWeeklyRunDistance = "
            "(weeklyRunDistanceComplication != null) "
            "? weeklyRunDistanceComplication.value as Float? : null;") in view


def test_onlayout_registers_one_callback_and_subscribes_per_type(write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, TWO_COMPLICATIONS)
    assert view.count(
        "Complications.registerComplicationChangeCallback(method(:onComplicationChanged));"
    ) == 1
    assert ("WfbComplications.subscribe(new Complications.Id("
            "Complications.COMPLICATION_TYPE_BODY_BATTERY));") in view
    assert ("WfbComplications.subscribe(new Complications.Id("
            "Complications.COMPLICATION_TYPE_TRAINING_STATUS));") in view


def test_two_complications_still_share_one_callback(write_design, bag, db, tmp_path):
    """Two bound complications produce two subscriptions but exactly one
    onComplicationChanged -- there is nothing per-type left inside it to
    duplicate."""
    view = _view(write_design, bag, db, tmp_path, TWO_COMPLICATIONS)
    assert view.count("function onComplicationChanged(id as Complications.Id) as Void") == 1


def test_complication_callback_has_exactly_one_statement(write_design, bag, db, tmp_path):
    """No switch, no cache write -- just an earlier redraw request."""
    view = _view(write_design, bag, db, tmp_path, BODY_BATTERY)
    lines = view.splitlines()
    start = next(i for i, l in enumerate(lines) if "function onComplicationChanged" in l)
    end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "}")
    body = [l.strip() for l in lines[start + 1:end] if l.strip()]
    assert body == ["WatchUi.requestUpdate();"]


def test_absent_complication_hides_the_element(write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, BODY_BATTERY)
    assert "if (complicationBodyBattery == null) {\n            return;\n        }" in view


def test_barrel_includes_wfb_complications(write_design, bag, db, tmp_path):
    face, project = _build(write_design, bag, db, tmp_path, BODY_BATTERY)
    resolved = project.resolved["fenix8solar47mm"]
    assert "WfbComplications.mc" in _barrel_for(face, resolved)


def test_barrel_omits_wfb_complications_without_one(write_design, bag, db, tmp_path):
    face, project = _build(write_design, bag, db, tmp_path, NO_COMPLICATION)
    resolved = project.resolved["fenix8solar47mm"]
    assert "WfbComplications.mc" not in _barrel_for(face, resolved)
    files = project.files()
    assert "WfbComplications.mc" not in files
    assert "WfbComplications" not in files["source/TestView.mc"]


def test_minapilevel_bumps_to_4_2_0_for_a_complication(write_design, bag, db, tmp_path):
    face, _ = _build(write_design, bag, db, tmp_path, BODY_BATTERY)
    assert _features(face) == {"complications"}
    assert api_level(face, _features(face)) == "4.2.0"


def test_minapilevel_stays_at_the_base_without_one(write_design, bag, db, tmp_path):
    face, _ = _build(write_design, bag, db, tmp_path, NO_COMPLICATION)
    assert _features(face) == set()
    assert api_level(face, _features(face)) == "3.2.0"


def test_manifest_declares_complicationsubscriber(write_design, bag, db, tmp_path):
    _, project = _build(write_design, bag, db, tmp_path, BODY_BATTERY)
    assert '<iq:uses-permission id="ComplicationSubscriber"/>' in project.manifest_text
    assert 'minApiLevel="4.2.0"' in project.manifest_text


def test_manifest_omits_complicationsubscriber_without_one(write_design, bag, db, tmp_path):
    _, project = _build(write_design, bag, db, tmp_path, NO_COMPLICATION)
    assert 'ComplicationSubscriber' not in project.manifest_text
    assert 'minApiLevel="3.2.0"' in project.manifest_text


def test_view_imports_complications(write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, BODY_BATTERY)
    assert "import Toybox.Complications;" in view


def test_low_power_element_may_bind_a_complication(write_design, bag, db, tmp_path):
    """The refresh-tier restriction that used to reject a slow/event-tier
    source on a low_power element is gone (D2): a complication is an
    ordinary per-frame read now, so it is fine anywhere a plain value is."""
    design = """
  - id: bb
    type: text
    value: complication.body_battery
    format: "{}"
    when_absent: hide
    font: FONT_TINY
    at: {anchor: center}
    color: palette.fg
    modes: [active, low_power]
"""
    face, project = _build(write_design, bag, db, tmp_path, design)
    assert face is not None
