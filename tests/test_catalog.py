"""wfb/catalog.py: readers, sources, and the permission machinery built
around them (ADR 0005), plus the generated `complication.*` half of the
catalogue (`wfb.complications.TYPES`).

Nothing here needs the Garmin toolchain or device files, except the one
``@pytest.mark.slow`` test at the bottom that builds every catalogue entry
through the real compiler -- the catalogue can only *advertise* a source
correctly (`wfb sources`); whether binding it actually compiles is a claim
only `monkeyc` can settle.
"""

from __future__ import annotations

import uuid

import pytest

from wfb import catalog, complications
from wfb.catalog import CATALOG, READERS, Type


def test_every_reader_is_used_by_at_least_one_source():
    used = {source.reader for source in CATALOG.values()}
    for name in READERS:
        assert name in used, f"reader {name!r} is declared but no source reads it"


def test_array_index_sources_have_a_bounds_guard():
    for path, source in CATALOG.items():
        if source.array_index is not None:
            assert source.array_guard is not None, path
            assert f"{READERS[source.reader].name}." in source.array_guard

    # and the converse: no array_index means no extra guard.
    plain = CATALOG["time.hour"]
    assert plain.array_index is None
    assert plain.array_guard is None


def test_weather_condition_sources_are_numeric_and_nullable():
    for path in catalog.WEATHER_CONDITION_SOURCES:
        source = CATALOG[path]
        assert source.type is Type.NUMBER
        assert source.nullable


def test_weather_condition_sources_need_no_permission():
    """Toybox.Weather does not appear in the manifest permission table at all
    (Core_Topics/Manifest_and_Permissions.html) -- confirmed directly against
    the SDK doc, not assumed by analogy with heart_rate.current."""
    for path in catalog.WEATHER_CONDITION_SOURCES:
        assert CATALOG[path].permissions == ()


def test_weather_condition_today_and_tomorrow_read_different_array_slots():
    today = CATALOG["weather.condition_today"]
    tomorrow = CATALOG["weather.condition_tomorrow"]
    assert today.reader == tomorrow.reader  # one API call, shared
    assert today.array_index == 0
    assert tomorrow.array_index == 1
    assert today.read_expr != tomorrow.read_expr


def test_read_expr_for_a_plain_field_has_no_array_indexing():
    source = CATALOG["activity.steps"]
    reader = READERS[source.reader]
    assert source.array_index is None
    assert source.read_expr == f"{reader.name}.{source.field_name}"
    assert "[" not in source.read_expr


def test_dotted_field_name_has_an_intermediate_guard():
    """`activity.active_minutes_week` reads `activeMinutesWeek.total`, and
    `activeMinutesWeek` is itself `ActiveMinutes or Null` (Toybox/
    ActivityMonitor/Info.html) -- dereferencing `.total` unconditionally
    crashes with "Cannot find symbol ':total' on type 'Null'" the moment the
    field is genuinely absent, which is the common case on this platform, not
    an edge case."""
    source = CATALOG["activity.active_minutes_week"]
    reader = READERS[source.reader]
    assert "." in source.field_name
    assert source.intermediate == "activeMinutesWeek"
    assert source.intermediate_guard == f"{reader.name}.activeMinutesWeek != null"


def test_plain_field_name_has_no_intermediate_guard():
    """The converse: a source whose `field_name` is not itself a dotted path
    needs no extra guard beyond its own/reader nullability."""
    source = CATALOG["activity.steps"]
    assert "." not in source.field_name
    assert source.intermediate is None
    assert source.intermediate_guard is None


def test_no_other_dotted_field_names_are_missing_an_intermediate_guard():
    """A future entry copy-pasting a dotted `field_name` (the same mistake
    `activity.active_minutes_week` made) must not silently ship without a
    guard -- this is the audit `activity.active_minutes_week`'s fix was
    supposed to generalise, pinned down so it can't regress."""
    for path, source in CATALOG.items():
        if source.field_name is not None and "." in source.field_name:
            assert source.intermediate is not None, (
                f"{path!r} has a dotted field_name {source.field_name!r} but no "
                "'intermediate' guard -- its intermediate object may itself be "
                "nullable, the exact bug activity.active_minutes_week had"
            )
            assert source.intermediate_guard is not None, path


# -- the broader catalogue expansion (weather fields, ambient, user profile) -


def test_user_profile_sources_declare_the_user_profile_permission():
    """UserProfile is a real permission, unlike Activity/ActivityMonitor/
    Weather -- confirmed against Core_Topics/Manifest_and_Permissions.html's
    own table, which lists a Watch Face as allowed to declare it."""
    for path, source in CATALOG.items():
        if path.startswith("user."):
            assert source.permissions == ("UserProfile",), path


def test_ambient_sources_need_no_permission():
    """Same reasoning as heart_rate.current: both read through
    Activity.getActivityInfo(), and Toybox.Activity is not in the permission
    table at all."""
    for path, source in CATALOG.items():
        if path.startswith("ambient."):
            assert source.permissions == (), path
            assert source.reader == "activity_info"


def test_date_month_and_day_of_week_are_strings():
    """Gregorian.info() under FORMAT_MEDIUM (the `date` reader's own format)
    returns month/day_of_week as localised strings, not numbers."""
    assert CATALOG["date.month"].type is Type.STRING
    assert CATALOG["date.day_of_week"].type is Type.STRING


def test_new_weather_fields_share_the_current_conditions_reader():
    """temperature, feels-like, today's high/low, precipitation chance,
    humidity and wind speed are all fields of CurrentConditions itself, not
    DailyForecast[0] -- one shared reader, no extra API call or array index,
    for every one of them plus weather.condition."""
    names = [
        "weather.temperature", "weather.feels_like_temperature",
        "weather.high_temperature_today", "weather.low_temperature_today",
        "weather.precipitation_chance_today", "weather.humidity", "weather.wind_speed",
    ]
    for name in names:
        source = CATALOG[name]
        assert source.reader == "weather_current", name
        assert source.array_index is None, name


def test_no_refresh_tier_concept_survives():
    """D2: the tier concept is deleted outright, not merely hidden -- neither
    `Reader` nor `Source` may carry a field for it any more."""
    for reader in READERS.values():
        assert not hasattr(reader, "tier")
        assert not hasattr(reader, "ttl_seconds")
    for source in CATALOG.values():
        assert not hasattr(source, "tier")
    assert not hasattr(catalog, "Tier")


# -- complications: the generated `complication.*` half of the catalogue ----


def test_all_42_complication_types_are_exposed():
    """COMPLICATION_TYPE_INVALID is not a real value and must not appear;
    every other COMPLICATION_TYPE_* from Toybox/Complications.html must."""
    assert len(complications.TYPES) == 42
    assert "invalid" not in complications.TYPES
    for entry in complications.TYPES.values():
        assert entry.constant != "COMPLICATION_TYPE_INVALID"
        assert entry.constant.startswith("COMPLICATION_TYPE_")


def test_every_complication_type_has_a_matching_catalog_source():
    """D1's one rule: `complication.<type>` is *always* read through
    Toybox.Complications, generated by looping over the type table -- not a
    hand-picked subset the way the nine old complication-backed sources
    were."""
    for name in complications.TYPES:
        path = f"complication.{name}"
        assert path in CATALOG, path
        source = CATALOG[path]
        assert source.field_name == "value"
        assert source.nullable is True
        assert source.permissions == ("ComplicationSubscriber",)
        assert source.source_ref == "Toybox/Complications.html"


def test_no_complication_source_is_a_leftover_hand_written_one():
    """Exactly 42 `complication.*` paths -- no more (a stale hand-written
    entry left behind), no fewer (the loop silently skipped one)."""
    comp_paths = [p for p in CATALOG if p.startswith("complication.")]
    assert len(comp_paths) == 42
    assert sorted(p.split(".", 1)[1] for p in comp_paths) == sorted(complications.TYPES)


def test_complication_source_type_matches_its_type_table_value_type():
    _MAP = {"number": Type.NUMBER, "float": Type.FLOAT, "string": Type.STRING}
    for name, entry in complications.TYPES.items():
        source = CATALOG[f"complication.{name}"]
        assert source.type is _MAP[entry.value_type], name


def test_cast_is_set_iff_the_source_reads_a_complication():
    """`Source.cast` exists only because `Complications.Complication.value`
    is a Monkey C union type -- no other reader returns a union, so no other
    source should ever set it."""
    for path, source in CATALOG.items():
        if path.startswith("complication."):
            assert source.cast is not None, path
            assert source.cast in ("Number?", "Float?", "String?"), (path, source.cast)
        else:
            assert source.cast is None, path


def test_read_expr_does_not_bake_in_the_cast():
    """SPEC contract: `read_expr` names what to read; `cast` is a separate
    instruction the emitter applies where it can parenthesise correctly --
    the two must never be conflated into one string here."""
    source = CATALOG["complication.body_battery"]
    assert " as " not in source.read_expr
    assert source.cast == "Number?"


def test_every_complication_reader_is_a_plain_pull_not_a_cached_field():
    """D2: no tier, no cache -- `call` is a real `WfbComplications.valueOf`
    expression, not a bare local field name a subscription callback used to
    write into."""
    for name in complications.TYPES:
        reader = READERS[f"complication_{name}"]
        assert reader.call.startswith("WfbComplications.valueOf(")
        assert reader.complication_type == complications.TYPES[name].constant
        assert reader.nullable is True


def test_launch_complication_always_names_a_real_type():
    for path, source in CATALOG.items():
        if source.launch_complication is not None:
            assert source.launch_complication in complications.TYPES, (
                path, source.launch_complication
            )


def test_every_complication_source_launches_itself():
    for name in complications.TYPES:
        source = CATALOG[f"complication.{name}"]
        assert source.launch_complication == name


def test_direct_read_sources_with_a_conventional_launch_target():
    """The hand-set half of `launch_complication`, per SPEC.md's table --
    pinned down so a future edit can't silently drop or scramble one."""
    expected = {
        "activity.steps": "steps",
        "activity.calories": "calories",
        "activity.floors_climbed": "floors_climbed",
        "activity.active_minutes_week": "intensity_minutes",
        "activity.time_to_recovery": "recovery_time",
        "activity.stress_score": "stress",
        "activity.respiration_rate": "respiration_rate",
        "heart_rate.current": "heart_rate",
        "pulse_ox.current": "pulse_ox",
        "system.battery": "battery",
        "ambient.altitude": "altitude",
        "ambient.pressure": "sea_level_pressure",
        "weather.condition": "current_weather",
        "weather.condition_tomorrow": "forecast_weather_1day",
        "weather.temperature": "current_temperature",
        "weather.high_temperature_today": "high_low_temperature",
        "weather.low_temperature_today": "high_low_temperature",
        "date.today": "date",
        "date.day": "date",
        "device.notification_count": "notification_count",
        "user.vo2max_running": "vo2max_run",
        "user.vo2max_cycling": "vo2max_bike",
    }
    for path, target in expected.items():
        assert CATALOG[path].launch_complication == target, path


def test_weather_condition_today_has_no_launch_target():
    """FORECAST_WEATHER_1DAY means tomorrow, not today -- mapping
    condition_today to it would open the wrong day's glance."""
    assert CATALOG["weather.condition_today"].launch_complication is None


# -- renamed sources (D1) -----------------------------------------------------


def test_renamed_source_keys_are_gone_from_the_catalog():
    for old_path in catalog.RENAMED_SOURCES:
        assert old_path not in CATALOG, old_path


def test_renamed_source_targets_all_exist():
    for old_path, new_path in catalog.RENAMED_SOURCES.items():
        assert new_path in CATALOG, (old_path, new_path)


def test_renamed_sources_match_spec_table():
    expected = {
        "body_battery.current": "complication.body_battery",
        "system.solar_input": "complication.solar_input",
        "weather.sunrise": "complication.sunrise",
        "weather.sunset": "complication.sunset",
        "activity.training_status": "complication.training_status",
        "activity.weekly_run_distance": "complication.weekly_run_distance",
        "activity.weekly_bike_distance": "complication.weekly_bike_distance",
        "activity.sleep_score": "complication.sleep_score",
        "device.next_calendar_event": "complication.calendar_events",
    }
    assert catalog.RENAMED_SOURCES == expected


def test_renamed_to_helper():
    assert catalog.renamed_to("body_battery.current") == "complication.body_battery"
    assert catalog.renamed_to("not.a.real.path") is None
    assert catalog.renamed_to("complication.body_battery") is None



# -- symbol-collision guard (F2): fast, catalogue-wide, no toolchain --------
#
# docs/review/2026-09-architecture-review.md's F2: `wfb/ir.py`'s
# `Builder._check_symbol_collision` only ever compares two derived forms of
# one *element id* against each other -- it says nothing about the families
# below, which are the ones that actually collided in the session that
# produced `Redefinition of variable 'complicationBodyBattery'` on all three
# targets: a `complication.*` reader's own local name (its element method's
# parameter) and `wfb.ir.local_name` of that same source's path (its value
# local) both landed on the same generated identifier. The shipped fix
# (`_complication_local_name`, wfb/catalog.py) is a naming *convention* for
# that one family; nothing before this test asserted the families stay
# distinct in general.

#: Fixed identifiers `wfb/emit/monkeyc.py` writes directly into the same
#: generated scope a reader parameter (`ReadPlan.parameters`) and a value /
#: intermediate local (`ReadPlan.declarations`) share -- the private
#: per-element method `_emit_element_method` builds
#: (``private function draw<Id>(dc as Dc, <reader params>) as Void { <value
#: locals>; ... }``). Read directly out of that file, line by line, not
#: guessed -- each name's origin:
#:   - "dc": `_emit_element_method`'s own signature, every element method.
#:   - "font": `_emit_text_draw` (a custom text font) and `_emit_icon` (the
#:     icon's baked font) -- never both in one element, but both are this
#:     same kind of scope.
#:   - "text": `_emit_text`'s `when_absent: placeholder`/`fallback`
#:     branches.
#:   - "fraction": `_emit_progress`'s `when_absent: fallback` branch.
#:   - "filled": `_emit_progress`'s rectangle-style fill width.
#: A future catalogue entry landing on one of these would be exactly the
#: same class of `Redefinition of variable` this test exists to catch,
#: just against a name the emitter chose rather than one another catalogue
#: entry chose. If a name here stops being cleanly enumerable this way (a
#: literal `var` scattered across a helper this list doesn't cover), that is
#: a real gap in this guard -- see this test's own docstring.
FIXED_ELEMENT_METHOD_LOCALS = {
    "dc", "font", "text", "fraction", "filled",
}


def test_reader_and_value_locals_never_collide():
    """F2: a fast, catalogue-wide guard for the whole class of bug that
    produced ``Redefinition of variable 'complicationBodyBattery'`` -- not
    just the one family (a `complication.*` reader's local vs. its own
    source's value local) the shipped fix happens to cover.

    Three families of generated identifier can land in one per-element
    method's scope (`wfb/emit/monkeyc.py`'s `_emit_element_method`):

    1. Every `Reader.name` in `READERS` -- becomes a parameter of whichever
       element method uses that reader (`ReadPlan.parameters`).
    2. Every `wfb.ir.local_name(path)` for `path` in `CATALOG` -- becomes a
       `var` inside that element method (`ReadPlan.declarations`), plus the
       ``...Obj`` form for any source with an `intermediate` (the
       dotted-field-name intermediate local `declarations` also declares).
    3. `FIXED_ELEMENT_METHOD_LOCALS` above -- names the emitter itself
       writes into that same scope, independent of the catalogue.

    Only the readers and sources one *particular* element actually binds
    ever share one real scope -- but which readers and sources that will be
    depends on a future design this test cannot see, so it deliberately
    checks the whole catalogue as one flat namespace rather than trying to
    track real co-occurrence. That is strictly more conservative than the
    bug it is guarding against needs, and is the same shape of check the
    architecture review itself proposed for this finding.

    No SDK, no `monkeyc`, no device files -- runs in the default
    ``pytest -m "not slow"`` loop, unlike `test_every_catalog_source_compiles`
    below, which is the only thing that caught this collision before this
    test existed (and only because it happens to bind every source in one
    build).
    """
    from wfb.ir import local_name

    # generated identifier -> [ human-readable origins that produced it ]
    origins: dict[str, list[str]] = {}

    def register(name: str, origin: str) -> None:
        origins.setdefault(name, []).append(origin)

    for reader_key, reader in READERS.items():
        register(reader.name, f"Reader {reader_key!r}.name")

    for path, source in CATALOG.items():
        register(local_name(path), f"local_name({path!r})")
        if source.intermediate is not None:
            register(f"{local_name(path)}Obj", f"intermediate local for {path!r}")

    for fixed in FIXED_ELEMENT_METHOD_LOCALS:
        register(fixed, f"fixed emitter local {fixed!r} (wfb/emit/monkeyc.py)")

    collisions = {name: where for name, where in origins.items() if len(where) > 1}
    assert not collisions, "symbol collision(s) in the generated element-method scope:\n" + "\n".join(
        f"  {name!r} <- {', '.join(where)}"
        for name, where in sorted(collisions.items())
    )


def test_pulse_ox_is_a_direct_source_not_a_complication():
    """currentOxygenSaturation is a field of Activity.Info (like
    heart_rate.current), so it does not need a complication subscription at
    all -- confirmed present on all three targets directly against the SDK's
    own Supported Devices list, unlike the complication-backed sources."""
    source = CATALOG["pulse_ox.current"]
    assert source.reader == "activity_info"
    assert source.permissions == ()


# -- every catalogue entry actually compiles ---------------------------------
#
# This is the test the activity.active_minutes_week bug (the dotted
# field_name / intermediate_guard fix above) should have made unnecessary to
# discover by hand: `wfb sources` advertises a binding as soon as it is in
# CATALOG, but nothing short of a real `monkeyc` build proves the generated
# Monkey C for that binding actually typechecks. One catalogue entry failing
# this way is exactly the shape of bug that a schema/validate-only test
# cannot catch -- `wfb validate` never lowers as far as Monkey C at all.


def _text_element_for(path: str, source) -> str:
    """One `text` element YAML block binding `path`, valid for its type."""
    element_id = path.replace(".", "_")
    lines = [
        f"  - id: {element_id}",
        "    type: text",
        f"    value: {path}",
    ]
    if source.type is Type.TIME:
        lines.append('    format: "{:%H:%M}"')
    elif source.type is Type.DATE:
        lines.append('    format: "{:%a %e %b}"')
    if source.guard_needed:
        lines.append("    when_absent: hide")
    lines += [
        "    at: { anchor: center }",
        "    color: palette.text",
        "    lint:",
        "      allow: [text-overflow, safe-area]",
        "      reason: \"one text element per catalogue source, stacked on top of",
        "        itself on purpose -- this design exists to compile, not to be read\"",
    ]
    return "\n".join(lines)


def _full_catalog_design(tmp_path) -> "pathlib.Path":
    import pathlib

    elements = ["""  - id: background
    type: shape
    shape: rectangle
    at: { anchor: center }
    size: { width: 100%, height: 100% }
    color: palette.bg"""]
    elements += [_text_element_for(path, source) for path, source in sorted(CATALOG.items())]

    text = f"""format: 1

face:
  id: {uuid.uuid4()}
  name: FullCatalog
  version: 1.0.0

targets:
  - fenix8solar47mm
  - fenix8solar51mm
  - fr955

palette:
  bg: "#000000"
  text: "#FFFFFF"

elements:
{chr(10).join(elements)}
"""
    path = pathlib.Path(tmp_path) / "full_catalog.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.slow
def test_every_catalog_source_compiles(tmp_path, bag, db):
    """The catalogue-wide guard against `activity.active_minutes_week`'s bug:
    build a design binding *every* CATALOG entry, one text element each, and
    require a real BUILD SUCCESSFUL. `wfb sources`/`wfb validate` can only
    check that a binding is well-typed against the catalogue's own claims --
    they cannot catch a claim that is simply wrong, the way
    `activeMinutesWeek.total` was wrong until this session's fix. This test
    would have failed before that fix, and is the reason the fix is worth
    more than its one line."""
    from wfb.build import Toolchain, build

    toolchain = Toolchain.discover()
    if toolchain is None or not toolchain.key.exists():
        pytest.skip("no Connect IQ SDK or developer key")
    design = _full_catalog_design(tmp_path)
    result = build(design, output=tmp_path / "build", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    errors = [d for d in bag.items if d.severity.value == "error"]
    assert not errors, bag.render()
    assert result.products, "nothing was compiled"
