"""Generated Monkey C for `EVENT`-tier sources -- complications (ADR 0005).

Unlike `SLOW`, there is no staleness check: the cached field is filled by
onComplicationChanged, and onUpdate just reads it. These need only the device
files (for font baking), not the Garmin toolchain -- see
tests/test_weather_codegen.py for the same split on the `SLOW` tier.
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
    value: body_battery.current
    format: "{}"
    when_absent: hide
    font: FONT_TINY
    at: {anchor: center}
    color: palette.fg
"""

TWO_COMPLICATIONS = """
  - id: bb
    type: text
    value: body_battery.current
    format: "{}"
    when_absent: hide
    font: FONT_TINY
    at: {anchor: center, dy: -20%}
    color: palette.fg
  - id: training
    type: text
    value: activity.training_status
    format: "{}"
    when_absent: hide
    font: FONT_TINY
    at: {anchor: center, dy: 20%}
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


def test_event_tier_cache_field_has_no_time(write_design, bag, db, tmp_path):
    """Unlike a `slow`-tier field, there is exactly one cache field per
    complication and no companion `*CacheTime` -- there is nothing to
    time out; onComplicationChanged is what keeps it current."""
    view = _view(write_design, bag, db, tmp_path, BODY_BATTERY)
    assert "private var _bodyBatteryComplicationCache as Number?;" in view
    assert "CacheTime" not in view
    assert "WfbCache" not in view


def test_event_tier_read_has_no_staleness_check(write_design, bag, db, tmp_path):
    """onUpdate just copies the cache into a local -- no `if (stale(...))`
    re-fetch, because there is no on-demand call to make."""
    view = _view(write_design, bag, db, tmp_path, BODY_BATTERY)
    assert "var bodyBatteryComplication = _bodyBatteryComplicationCache;" in view
    assert "stale(" not in view


def test_onlayout_subscribes_and_registers_one_shared_callback(write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, BODY_BATTERY)
    assert "Complications.registerComplicationChangeCallback(method(:onComplicationChanged));" in view
    assert ("WfbComplications.subscribe(new Complications.Id("
            "Complications.COMPLICATION_TYPE_BODY_BATTERY));") in view
    # one registration call, no matter how many complications are subscribed to
    # (the doc comment on onComplicationChanged also names the method, hence
    # matching the call itself rather than the bare method name).
    assert view.count("Complications.registerComplicationChangeCallback(method(:onComplicationChanged));") == 1


def test_two_complications_share_one_callback_with_two_cases(write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, TWO_COMPLICATIONS)
    assert view.count("function onComplicationChanged(id as Complications.Id) as Void") == 1
    assert "case Complications.COMPLICATION_TYPE_BODY_BATTERY: _bodyBatteryComplicationCache = complication.value as Number?; break;" in view
    assert "case Complications.COMPLICATION_TYPE_TRAINING_STATUS: _trainingStatusComplicationCache = complication.value as String?; break;" in view
    assert "WfbComplications.subscribe(new Complications.Id(Complications.COMPLICATION_TYPE_BODY_BATTERY));" in view
    assert "WfbComplications.subscribe(new Complications.Id(Complications.COMPLICATION_TYPE_TRAINING_STATUS));" in view


def test_complication_callback_requests_an_update(write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, BODY_BATTERY)
    assert "WfbComplications.valueOf(id);" in view
    lines = view.splitlines()
    callback_start = next(i for i, l in enumerate(lines) if "function onComplicationChanged" in l)
    callback_body = "\n".join(lines[callback_start:callback_start + 14])
    assert "WatchUi.requestUpdate();" in callback_body


def test_complication_callback_guards_a_not_found_or_unavailable_complication(
    write_design, bag, db, tmp_path,
):
    """`getComplication` throws `ComplicationNotFoundException` (Bug 7) --
    the callback must not call it directly and must bail out if the looked-up
    value comes back null, rather than dereferencing `.value` on it."""
    view = _view(write_design, bag, db, tmp_path, BODY_BATTERY)
    assert "Complications.getComplication(id)" not in view
    assert "var complication = WfbComplications.valueOf(id);" in view
    assert "if (complication == null) {\n            return;" in view


def test_absent_complication_hides_the_element(write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, BODY_BATTERY)
    assert "if (bodyBatteryCurrent == null) {\n            return;\n        }" in view


def test_barrel_includes_wfb_complications(write_design, bag, db, tmp_path):
    face, project = _build(write_design, bag, db, tmp_path, BODY_BATTERY)
    resolved = project.resolved["fenix8solar47mm"]
    assert "WfbComplications.mc" in _barrel_for(face, resolved)


def test_barrel_omits_wfb_complications_without_one(write_design, bag, db, tmp_path):
    no_complication = """
  - id: steps
    type: text
    value: activity.steps
    format: "{:d}"
    when_absent: hide
    font: FONT_TINY
    at: {anchor: center}
    color: palette.fg
"""
    face, project = _build(write_design, bag, db, tmp_path, no_complication)
    resolved = project.resolved["fenix8solar47mm"]
    assert "WfbComplications.mc" not in _barrel_for(face, resolved)
    assert "WfbComplications.mc" not in project.files()
    files = project.files()
    assert "WfbComplications" not in files["source/TestView.mc"]


def test_minapilevel_bumps_to_4_2_0_for_a_complication(write_design, bag, db, tmp_path):
    face, _ = _build(write_design, bag, db, tmp_path, BODY_BATTERY)
    assert _features(face) == {"complications"}
    assert api_level(face, _features(face)) == "4.2.0"


def test_minapilevel_stays_at_the_base_without_one(write_design, bag, db, tmp_path):
    no_complication = """
  - id: steps
    type: text
    value: activity.steps
    format: "{:d}"
    when_absent: hide
    font: FONT_TINY
    at: {anchor: center}
    color: palette.fg
"""
    face, _ = _build(write_design, bag, db, tmp_path, no_complication)
    assert _features(face) == set()
    assert api_level(face, _features(face)) == "3.2.0"


def test_manifest_declares_complicationsubscriber(write_design, bag, db, tmp_path):
    _, project = _build(write_design, bag, db, tmp_path, BODY_BATTERY)
    assert '<iq:uses-permission id="ComplicationSubscriber"/>' in project.manifest_text
    assert 'minApiLevel="4.2.0"' in project.manifest_text


def test_view_imports_complications(write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, BODY_BATTERY)
    assert "import Toybox.Complications;" in view
