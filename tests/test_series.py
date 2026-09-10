"""The `wfb/series.py` catalogue -- what a `graph` element's `series:` may name.

Shaped like `tests/test_catalog.py` (its data-source sibling): checks the
table's own shape and cross-references against the SDK facts it was
transcribed from, not against `wfb.ir`/`wfb.emit`, which have their own tests.
"""

from __future__ import annotations

from wfb import series
from wfb.catalog import Type
from wfb.series import Acquisition, SERIES


def test_fifteen_series_and_none_of_them_solar():
    assert len(SERIES) == 15
    assert "solar" not in " ".join(SERIES).lower()
    assert not any("pressure" in name or "stress" in name or "elevation" in name
                   or "body_battery" in name for name in SERIES)


def test_get_and_names_and_suggest():
    assert series.get("heart_rate") is not None
    assert series.get("nope") is None
    assert series.names() == sorted(SERIES)
    assert "steps" in series.suggest("stps")


def test_heart_rate_has_no_natural_interval_or_documented_max():
    """It bins by real time on-device instead of a build-time count --
    Toybox/ActivityMonitor.html documents the sample interval as device
    dependent, so this compiler cannot turn a duration into a count for it
    the way it does for every array-backed series."""
    hr = series.get("heart_rate")
    assert hr.acquisition is Acquisition.HEART_RATE
    assert hr.field_name is None
    assert hr.interval_seconds is None
    assert hr.max_count is None


def test_activity_history_series_share_a_seven_day_documented_cap():
    for name in ("steps", "calories", "distance", "floors_climbed", "active_minutes"):
        entry = series.get(name)
        assert entry.acquisition is Acquisition.ACTIVITY_HISTORY, name
        assert entry.interval_seconds == 86400, name
        assert entry.max_count == 7, name


def test_active_minutes_has_the_same_intermediate_shape_as_the_catalog_source():
    """`day.activeMinutes.total` -- `activeMinutes` is itself nullable
    (`ActivityMonitor.ActiveMinutes or Null`), `.total` on it is not, the
    same shape `catalog.Source.intermediate` exists for."""
    entry = series.get("active_minutes")
    assert entry.field_name == "activeMinutes.total"
    assert entry.intermediate == "activeMinutes"


def test_no_other_series_has_an_intermediate_it_does_not_need():
    for name, entry in SERIES.items():
        if name == "active_minutes":
            continue
        assert entry.intermediate is None, name


def test_forecast_series_document_no_maximum_and_the_right_interval():
    hourly = ("forecast_temperature", "forecast_precipitation_chance",
              "forecast_cloud_cover", "forecast_uv_index", "forecast_wind_speed",
              "forecast_humidity")
    for name in hourly:
        entry = series.get(name)
        assert entry.acquisition is Acquisition.HOURLY_FORECAST, name
        assert entry.interval_seconds == 3600, name
        assert entry.max_count is None, name
    daily = ("daily_high_temperature", "daily_low_temperature",
             "daily_precipitation_chance")
    for name in daily:
        entry = series.get(name)
        assert entry.acquisition is Acquisition.DAILY_FORECAST, name
        assert entry.interval_seconds == 86400, name
        assert entry.max_count is None, name


def test_temperature_and_float_only_fields_are_typed_float():
    """`highTemperature`/`lowTemperature`/`temperature` are `Lang.Numeric`,
    `uvIndex`/`windSpeed` are `Lang.Float` -- both distinct from the plain
    `Lang.Number` percentages/counts, checked directly against the SDK doc
    rather than assumed uniform."""
    for name in ("forecast_temperature", "forecast_uv_index", "forecast_wind_speed",
                 "daily_high_temperature", "daily_low_temperature"):
        assert series.get(name).value_type is Type.FLOAT, name
    for name in ("forecast_precipitation_chance", "forecast_cloud_cover",
                 "forecast_humidity", "daily_precipitation_chance", "steps",
                 "calories", "distance", "floors_climbed", "active_minutes",
                 "heart_rate"):
        assert series.get(name).value_type is Type.NUMBER, name


def test_every_series_cites_the_sdk_page_it_came_from():
    for name, entry in SERIES.items():
        assert entry.source_ref, name
        assert "Toybox" in entry.source_ref, name


def test_acquisition_info_covers_every_acquisition_value():
    """`wfb.emit.monkeyc` indexes `series.ACQUISITION` by every `Acquisition`
    a `SeriesDef` can carry -- a missing entry would be a `KeyError` at
    codegen time, not a diagnostic, so this pins the two enums together."""
    assert set(series.ACQUISITION) == set(Acquisition)


def test_activity_history_is_not_documented_nullable_but_forecasts_are():
    """`ActivityMonitor.getHistory()` returns `Lang.Array<History>`, never
    `... or Null`; both `Weather` forecast calls document `... or Null` --
    checked directly against the SDK doc, not assumed uniform across the
    three array-backed families."""
    assert series.ACQUISITION[Acquisition.ACTIVITY_HISTORY].array_nullable is False
    assert series.ACQUISITION[Acquisition.HOURLY_FORECAST].array_nullable is True
    assert series.ACQUISITION[Acquisition.DAILY_FORECAST].array_nullable is True


def test_only_activity_history_is_newest_first():
    """`getHistory()`'s own doc: "The objects will be inserted most recent
    first" -- the one family whose on-screen order (oldest first, left to
    right) is the reverse of the array it reads."""
    assert series.ACQUISITION[Acquisition.ACTIVITY_HISTORY].newest_first is True
    assert series.ACQUISITION[Acquisition.HOURLY_FORECAST].newest_first is False
    assert series.ACQUISITION[Acquisition.DAILY_FORECAST].newest_first is False
