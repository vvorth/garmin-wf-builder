"""`wfb.availability` -- device-vs-design gap detection, and the runtime
guards it drives in `wfb/emit/monkeyc.py`.

fenix6 (ConnectIQ 3.4.5) and fr245 (3.3.6) are this project's lowest-level
*installed* devices and both lack `Toybox.Complications` outright (below its
4.2.0 floor); fenix6 additionally lacks `ActivityMonitor.Info.stressScore`
and fr245 lacks `floorsClimbed`. These are real gaps, confirmed directly
against the vendored `<id>.api.debug.xml` files (not assumed) -- see
`tests/test_devices.py` for the `Device.has_module`/`has_field` unit tests
this module's own logic is built on.

Every check below is driven red against a knowingly broken implementation
before being trusted, the same discipline this project's other test modules
follow (see e.g. `tests/test_color_scheme.py`'s own module docstring).
"""

from __future__ import annotations

import pytest

from tests.test_diagnostics import load
from wfb import availability
from wfb.availability import Guards, compute_guards, uses_complications
from wfb.catalog import CATALOG


def _skip_unless_installed(db, *device_ids: str) -> None:
    for device_id in device_ids:
        if device_id not in db.ids():
            pytest.skip(f"{device_id} not installed")


# --------------------------------------------------------------------------
# reader_unavailable / source_unavailable


def test_a_complication_reader_is_unavailable_on_fenix6(db):
    _skip_unless_installed(db, "fenix6")
    gap = availability.reader_unavailable("complication_body_battery", db.get("fenix6"))
    assert gap is not None
    assert gap.kind == "module"
    assert gap.symbol == "Complications"


def test_a_complication_reader_is_available_on_fenix8(db):
    gap = availability.reader_unavailable("complication_body_battery", db.get("fenix8solar47mm"))
    assert gap is None


def test_an_ordinary_reader_is_available_everywhere_installed(db):
    """`clock`/`activity`/`weather_current`/etc. are all core, pre-4.2.0
    APIs -- confirmed present in every installed device's own symbol table,
    fenix6/fr245 included (docs/research/probes/device-symbol-gate and this
    task's own device sweep)."""
    for device_id in db.ids():
        device = db.get(device_id)
        for reader_name in ("clock", "settings", "stats", "date", "activity",
                            "activity_info", "weather_current", "weather_daily",
                            "user_profile"):
            assert availability.reader_unavailable(reader_name, device) is None, (
                reader_name, device_id)


def test_stress_score_is_unavailable_on_fenix6_but_not_fenix8(db):
    _skip_unless_installed(db, "fenix6")
    fenix6_gap = availability.source_unavailable("activity.stress_score", db.get("fenix6"))
    assert fenix6_gap is not None
    assert fenix6_gap.kind == "field"
    assert fenix6_gap.symbol == "stressScore"
    assert availability.source_unavailable("activity.stress_score", db.get("fenix8solar47mm")) is None


def test_floors_climbed_is_unavailable_on_fr245(db):
    _skip_unless_installed(db, "fr245")
    gap = availability.source_unavailable("activity.floors_climbed", db.get("fr245"))
    assert gap is not None
    assert gap.kind == "field"
    assert gap.symbol == "floorsClimbed"


def test_a_complication_source_is_unavailable_on_fenix6_via_its_module(db):
    """`complication.body_battery` is gated by the reader's module, not a
    field -- the source itself has no `field_name` root that would ever be
    checked against `has_field`."""
    _skip_unless_installed(db, "fenix6")
    gap = availability.source_unavailable("complication.body_battery", db.get("fenix6"))
    assert gap is not None
    assert gap.kind == "module"


def test_a_never_absent_field_is_available_everywhere(db):
    for device_id in db.ids():
        assert availability.source_unavailable("time.hour", db.get(device_id)) is None


def test_unknown_path_and_unknown_reader_say_nothing(db):
    device = db.get("fenix8solar47mm")
    assert availability.source_unavailable("no.such.path", device) is None


# --------------------------------------------------------------------------
# invariant: no catalogue source is unavailable on the richest target, and
# the exact gap sets on fenix6/fr245 are pinned so a regression in either
# direction (a real gap silently swallowed, or a new false positive like the
# `device.do_not_disturb` bug -- see `wfb/catalog.py`'s `Source.requires`
# docstring) shows up here rather than in a lint nobody is watching.


def test_no_catalog_source_is_unavailable_on_fenix8solar47mm(db):
    """fenix8solar47mm (API 6.0.2) is this project's richest installed
    target and has every module/field/function every catalogue entry needs.
    A path reported unavailable here is always a false positive in this
    module's own logic, never a real device gap -- the bug `device.
    do_not_disturb` had (`requires=("DeviceSettings.doNotDisturb",)` naming
    a *field* in `has_symbol`'s function-only namespace, so it read as
    absent everywhere, fenix8solar47mm included) is exactly the shape this
    guards against.
    """
    device = db.get("fenix8solar47mm")
    false_positives = {
        path: gap for path, gap in (
            (path, availability.source_unavailable(path, device)) for path in CATALOG
        ) if gap is not None
    }
    assert false_positives == {}


#: Bare field names `activity.*`/`ambient.*`/`system.*` sources reduce to on
#: fenix6/fr245 (confirmed directly against the vendored `api.debug.xml`
#: files, not merely asserted -- see `docs/research/probes/api-gating/`).
_FENIX6_FIELD_GAPS = {"activity.stress_score": "stressScore"}
_FR245_FIELD_GAPS = {
    "activity.floors_climbed": "floorsClimbed",
    "activity.floors_climbed_goal": "floorsClimbedGoal",
    "activity.stress_score": "stressScore",
    "ambient.pressure": "ambientPressure",
    "system.battery_in_days": "batteryInDays",
}


def _complication_gaps() -> set[str]:
    return {path for path in CATALOG if path.startswith("complication.")}


def test_fenix6_gap_set_is_pinned(db):
    _skip_unless_installed(db, "fenix6")
    device = db.get("fenix6")
    gaps = {path: gap for path in CATALOG
            if (gap := availability.source_unavailable(path, device)) is not None}
    assert {path for path, gap in gaps.items() if gap.kind == "field"} == set(_FENIX6_FIELD_GAPS)
    for path, symbol in _FENIX6_FIELD_GAPS.items():
        assert gaps[path].symbol == symbol
    assert {path for path, gap in gaps.items() if gap.kind == "module"} == _complication_gaps()
    assert all(gap.symbol == "Complications" for path, gap in gaps.items()
               if gap.kind == "module")
    assert set(gaps) == set(_FENIX6_FIELD_GAPS) | _complication_gaps()


def test_fr245_gap_set_is_pinned(db):
    _skip_unless_installed(db, "fr245")
    device = db.get("fr245")
    gaps = {path: gap for path in CATALOG
            if (gap := availability.source_unavailable(path, device)) is not None}
    assert {path for path, gap in gaps.items() if gap.kind == "field"} == set(_FR245_FIELD_GAPS)
    for path, symbol in _FR245_FIELD_GAPS.items():
        assert gaps[path].symbol == symbol
    assert {path for path, gap in gaps.items() if gap.kind == "module"} == _complication_gaps()
    assert all(gap.symbol == "Complications" for path, gap in gaps.items()
               if gap.kind == "module")
    assert set(gaps) == set(_FR245_FIELD_GAPS) | _complication_gaps()


# --------------------------------------------------------------------------
# design-wide queries


TEMPLATE = """
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f59, name: Test}}
targets: [{targets}]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
elements:
  - id: bg
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
  - id: bb
    type: text
    value: complication.body_battery
    format: "{{}}"
    when_absent: hide
    font: FONT_TINY
    at: {{anchor: center, dy: -30%}}
    color: palette.fg
  - id: stress
    type: text
    value: activity.stress_score
    format: "{{:d}}"
    when_absent: hide
    font: FONT_TINY
    at: {{anchor: center, dy: 0%}}
    color: palette.fg
  - id: hr
    type: icon
    icon: heart
    size: 10%r
    at: {{anchor: center, dy: 30%}}
    color: palette.fg
    on_hold: heart_rate
"""


def _face(write_design, bag, targets: str = "fenix6, fenix8solar47mm"):
    face = load(write_design(TEMPLATE.format(targets=targets)), bag)
    assert face is not None, bag.render()
    return face


def test_design_fields_finds_stress_score_but_not_the_complication(write_design, bag):
    """`complication.body_battery` contributes nothing to `design_fields` --
    it is gated by module, not field (see the module docstring)."""
    face = _face(write_design, bag)
    assert availability.design_fields(face) == frozenset({"stressScore"})


def test_uses_complications_true_for_a_bound_reader(write_design, bag):
    face = _face(write_design, bag)
    assert uses_complications(face) is True


def test_uses_complications_true_for_on_hold_alone(write_design, bag):
    """Even a design that reads no `complication.*` value needs the module,
    purely because of `on_hold:` (`Complications.exitTo`)."""
    text = TEMPLATE.format(targets="fenix8solar47mm").replace(
        "    value: complication.body_battery\n", "    value: activity.steps\n"
    )
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    assert uses_complications(face) is True


def test_uses_complications_false_for_a_plain_design(write_design, bag):
    text = """
format: 1
face: {id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f5a, name: Test}
targets: [fenix8solar47mm]
palette: {bg: "#000000", fg: "#FFFFFF"}
elements:
  - id: steps
    type: text
    value: activity.steps
    format: "{:d}"
    when_absent: hide
    color: palette.fg
    at: {anchor: center}
"""
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    assert uses_complications(face) is False


# --------------------------------------------------------------------------
# compute_guards -- the aggregate over every target device


def test_compute_guards_flags_both_gaps_when_fenix6_is_a_target(db, write_design, bag):
    _skip_unless_installed(db, "fenix6")
    face = _face(write_design, bag, targets="fenix6, fenix8solar47mm")
    devices = [db.get("fenix6"), db.get("fenix8solar47mm")]
    guards = compute_guards(face, devices)
    assert guards.complications is True
    assert guards.fields == frozenset({"stressScore"})
    assert guards.any is True


def test_compute_guards_is_empty_when_every_target_has_everything(db, write_design, bag):
    face = _face(write_design, bag, targets="fenix8solar47mm")
    guards = compute_guards(face, [db.get("fenix8solar47mm")])
    assert guards == Guards(complications=False, fields=frozenset())
    assert guards.any is False


def test_compute_guards_field_gap_is_independent_of_the_complications_gap(db, write_design, bag):
    """fr245 has Complications *and* stressScore both absent, but the two are
    unrelated gaps -- swap the design to read a field fr245 alone lacks and
    check both are reported for what they actually are."""
    _skip_unless_installed(db, "fr245")
    text = TEMPLATE.format(targets="fr245, fenix8solar47mm").replace(
        "activity.stress_score", "activity.floors_climbed"
    ).replace('value: activity.floors_climbed\n    format: "{:d}"',
              'value: activity.floors_climbed\n    format: "{:d}"')
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    devices = [db.get("fr245"), db.get("fenix8solar47mm")]
    guards = compute_guards(face, devices)
    assert guards.complications is True
    assert "floorsClimbed" in guards.fields


# --------------------------------------------------------------------------
# codegen: the guards `wfb/emit/monkeyc.py` actually emits


def _generate(write_design, bag, db, tmp_path, targets: str):
    from wfb.emit.project import generate
    from wfb.emit.resources import bake_fonts

    face = _face(write_design, bag, targets=targets)
    devices = [db.get(t.strip()) for t in targets.split(",")]
    baked = {d.id: bake_fonts(face, d) for d in devices}
    return generate(face, devices, tmp_path, baked)


def test_fenix6_target_gets_the_complications_and_field_guards(write_design, bag, db, tmp_path):
    _skip_unless_installed(db, "fenix6")
    project = _generate(write_design, bag, db, tmp_path, "fenix6, fenix8solar47mm")
    files = project.files()
    (view_path,) = [p for p in files if p.endswith("View.mc")]
    (delegate_path,) = [p for p in files if p.endswith("Delegate.mc")]
    view = files[view_path]
    delegate = files[delegate_path]

    # the reader pull is guarded, not the barrel call
    assert "var hasComplications = Toybox has :Complications;" in view
    assert ("hasComplications ? WfbComplications.valueOf(new Complications.Id("
            "Complications.COMPLICATION_TYPE_BODY_BATTERY)) : null") in view

    # onLayout's subscribe/register loop sits behind its own has-guard
    assert "if (Toybox has :Complications)" in view
    assert view.count("Complications.registerComplicationChangeCallback") == 1

    # a field some target (fenix6) lacks gets an `x has :field` guard
    assert "activity has :stressScore" in view

    # the fixed on_hold:heart_rate exitTo call is guarded in the delegate
    assert "if (Toybox has :Complications)" in delegate
    assert "Complications.exitTo(new Complications.Id(Complications.COMPLICATION_TYPE_HEART_RATE));" \
        in delegate


def test_fenix8_only_target_gets_no_guards_at_all(write_design, bag, db, tmp_path):
    """Every target supports everything this design uses, so the generated
    code is exactly what it was before this feature existed -- no `has`
    guard anywhere."""
    project = _generate(write_design, bag, db, tmp_path, "fenix8solar47mm")
    files = project.files()
    (view_path,) = [p for p in files if p.endswith("View.mc")]
    (delegate_path,) = [p for p in files if p.endswith("Delegate.mc")]
    view = files[view_path]
    delegate = files[delegate_path]

    assert "has :Complications" not in view
    assert "hasComplications" not in view
    assert "has :stressScore" not in view
    assert "has :Complications" not in delegate
    assert ("var bodyBatteryComplication = WfbComplications.valueOf(new Complications.Id("
            "Complications.COMPLICATION_TYPE_BODY_BATTERY));") in view
    assert "Complications.exitTo(new Complications.Id(Complications.COMPLICATION_TYPE_HEART_RATE));" \
        in delegate


def test_manifest_floor_stays_at_base_even_with_fenix6_and_a_complication(write_design, bag, db, tmp_path):
    """The historical bug this whole task exists to fix: `minApiLevel` used
    to bump to 4.2.0 for any bound complication, which broke a build that
    also targeted a sub-4.2.0 device like fenix6
    (`error[monkeyc]: Device 'fenix6' does not support API Level '4.2.0'`)."""
    _skip_unless_installed(db, "fenix6")
    project = _generate(write_design, bag, db, tmp_path, "fenix6, fenix8solar47mm")
    assert 'minApiLevel="3.2.0"' in project.manifest_text
    assert 'minApiLevel="4.2.0"' not in project.manifest_text
