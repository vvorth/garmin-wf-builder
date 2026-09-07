"""wfb/catalog.py: readers, sources, and the tier/permission machinery
built around them (ADR 0005).

Nothing here needs the Garmin toolchain or device files, except the one
``@pytest.mark.slow`` test at the bottom that builds every catalogue entry
through the real compiler -- the catalogue can only *advertise* a source
correctly (`wfb sources`); whether binding it actually compiles is a claim
only `monkeyc` can settle.
"""

from __future__ import annotations

import uuid

import pytest

from wfb import catalog
from wfb.catalog import CATALOG, READERS, Tier, Type


def test_every_source_agrees_with_its_readers_tier():
    """The cache (or lack of one) is generated once per *reader*
    (wfb/emit/monkeyc.py's ReadPlan), not per source, so every source sharing
    a reader had better agree with it -- a source claiming `slow` off a
    `frame`-tier reader (or vice versa) would silently get the wrong
    treatment."""
    for path, source in CATALOG.items():
        reader = READERS[source.reader]
        assert source.tier == reader.tier, (
            f"{path!r} is {source.tier.value}-tier but its reader {source.reader!r} "
            f"is {reader.tier.value}-tier"
        )


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


def test_weather_condition_sources_are_slow_tier_and_numeric():
    from wfb.catalog import Type

    for path in catalog.WEATHER_CONDITION_SOURCES:
        source = CATALOG[path]
        assert source.tier is Tier.SLOW
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


def test_weather_readers_have_an_hourly_ttl():
    """Weather -- current conditions and the forecast -- does not change fast
    enough to justify the 900s default; both weather readers use an hour."""
    assert READERS["weather_current"].ttl_seconds == 3600
    assert READERS["weather_daily"].ttl_seconds == 3600


# -- complications (ADR 0005's `event` tier) --------------------------------


def test_every_event_tier_reader_names_a_complication_type():
    """The one thing that distinguishes an EVENT reader from a FRAME/SLOW one
    is `complication_type` -- catch a reader marked EVENT that forgot to set
    it (nothing would subscribe to it) or a non-EVENT reader that set it by
    copy-paste accident (nothing would ever fill its cache)."""
    for name, reader in READERS.items():
        if reader.tier is Tier.EVENT:
            assert reader.complication_type is not None, name
        else:
            assert reader.complication_type is None, name


def test_complication_backed_sources_have_no_field_name():
    """Like `time.clock`, the reader *is* the value for a complication -- there
    is no sub-field to read off it, unlike `activity.steps` off `activity`."""
    for name, reader in READERS.items():
        if reader.complication_type is None:
            continue
        for source in CATALOG.values():
            if source.reader == name:
                assert source.field_name is None, source.path


def test_complication_backed_sources_declare_complicationsubscriber():
    for name, reader in READERS.items():
        if reader.complication_type is None:
            continue
        for source in CATALOG.values():
            if source.reader == name:
                assert source.permissions == ("ComplicationSubscriber",), source.path


def test_complication_readers_are_not_grouped():
    """Unlike ActivityMonitor.getInfo(), no single Complications call returns
    several types at once, so each complication is its own reader -- one
    source per reader, not several sources sharing one."""
    counts: dict[str, int] = {}
    for source in CATALOG.values():
        if READERS[source.reader].complication_type is not None:
            counts[source.reader] = counts.get(source.reader, 0) + 1
    assert counts, "expected at least one complication-backed source"
    assert all(count == 1 for count in counts.values()), counts


def test_body_battery_is_bindable():
    """The concrete ask this feature exists for."""
    source = CATALOG["body_battery.current"]
    assert source.tier is Tier.EVENT
    assert READERS[source.reader].complication_type == "COMPLICATION_TYPE_BODY_BATTERY"


def test_pulse_ox_is_a_direct_source_not_a_complication():
    """currentOxygenSaturation is a field of Activity.Info (like
    heart_rate.current), so it does not need a complication subscription at
    all -- confirmed present on all three targets directly against the SDK's
    own Supported Devices list, unlike the complication-backed sources above."""
    source = CATALOG["pulse_ox.current"]
    assert source.tier is Tier.FRAME
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
