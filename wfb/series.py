"""The time-series catalogue a `type: graph` element may plot (research 08 §1).

Shaped like :mod:`wfb.complications`: one table, transcribed from the SDK
rather than hand-copied, because a hand-copied table is exactly the kind of
drift this project keeps finding and fixing (see that module's own docstring,
and CLAUDE.md's account of the catalogue-table bugs found so far).

**A series is not a `catalog.Source`.** A scalar source is one reader shared
by every element that binds it, hoisted once per frame and read through the
expression compiler. A series is a *history* -- an iterator or a short array,
acquired, binned or looped over, and cached across frames because its sample
interval is minutes, not seconds (see `runtime-lib/WfbSeries.mc`'s module
docstring for why that caching is not the TTL cache this project deleted).
Nothing about that shape fits `Source`, so this is a second, smaller table
with its own dataclass, not a reuse of the first.

**Four families, and none of them is solar** -- `docs/research/probes/
graph-series/` is the reference build every acquisition strategy below is
taken from, and `docs/research/08-graphs-and-configuration.md` §1 is the
research. `Toybox.SensorHistory` -- the obvious route to pressure, stress,
elevation and Body Battery *as a series* -- has an empty "Watch Face" cell in
`Core_Topics/Manifest_and_Permissions.html`'s permission table (checked
directly: neither `Toybox.ActivityMonitor` nor `Toybox.Weather`, the two
modules every entry below reads through, appear in that table at all -- the
same no-permission situation `wfb.catalog`'s `activity`/`weather_current`
readers already document). It still compiles -- a watch face may not *declare*
the permission, but nothing stops `monkeyc` accepting the call -- and then
fails silently on the wrist (CLAUDE.md constraint 7), which is why this is
written down rather than left to be rediscovered. Solar is a stronger
negative still: there is no solar *history* API anywhere in Connect IQ, only
two current-value reads (`System.Stats.solarIntensity`,
`Complications.COMPLICATION_TYPE_SOLAR_INPUT`) -- the chart on a stock fēnix
is native firmware, and there is nothing here for this compiler to reach.

Every entry below needs no permission -- `Toybox.ActivityMonitor` and
`Toybox.Weather` are both absent from the permission table, exactly like
`Toybox.Activity` already is for `heart_rate.current`/`pulse_ox.current` in
`wfb/catalog.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .catalog import Type


class Acquisition(str, Enum):
    """How a series' samples are actually obtained on-device.

    Only `HEART_RATE` is hand-written in `runtime-lib/WfbSeries.mc` -- it is
    one shape (an iterator, optionally binned by time) shared by every
    design that plots it. The other three are *generated*, one per bound
    series, because the field each reads (`day.steps` vs. `day.calories`)
    varies with the design and Monkey C has no way to pass a field name.
    """

    #: `ActivityMonitor.getHeartRateHistory(period, false)` -- an iterator,
    #: either binned by time (a `Duration` range) or read raw (a count range).
    HEART_RATE = "heart_rate"
    #: `ActivityMonitor.getHistory()` -- an `Array<History>`, newest first,
    #: at most 7 entries (checked against `Toybox/ActivityMonitor.html`
    #: directly, not assumed).
    ACTIVITY_HISTORY = "activity_history"
    #: `Weather.getHourlyForecast()` -- `Array<HourlyForecast> or Null`,
    #: oldest (nearest) first, no documented maximum length.
    HOURLY_FORECAST = "hourly_forecast"
    #: `Weather.getDailyForecast()` -- `Array<DailyForecast> or Null`,
    #: oldest (nearest) first, no documented maximum length.
    DAILY_FORECAST = "daily_forecast"


@dataclass(frozen=True)
class AcquisitionInfo:
    """How to get the raw array/iterator for one :class:`Acquisition` family.

    `heart_rate` never reads this for `call`/`newest_first`/`array_nullable`
    -- it is the one hand-written shape in `runtime-lib/WfbSeries.mc`
    (`binHeartRate`/`collectHeartRate`), called directly from the generated
    `_emit_hr_rebuild`. The other three are generated per project
    (`wfb.emit.monkeyc._emit_array_rebuild`), because the field each reads
    off one entry varies with the design -- this is what that generated loop
    needs to know about the call that produces the array it loops over.
    """

    #: The Toybox module the call needs (also what a bound `heart_rate`
    #: series needs imported, even though nothing else here applies to it).
    module: str
    #: The Monkey C expression that acquires the array. Unused for
    #: `heart_rate`.
    call: str
    #: Whether the acquired array's own order is newest-first, so the
    #: generated loop has to read it back to front to get oldest-first (left
    #: to right on screen) -- true for `ActivityMonitor.getHistory()`
    #: (documented "inserted most recent first"), false for both forecast
    #: calls (index 0 is the earliest/nearest, ascending from there, the same
    #: order `weather.condition_today`/`_tomorrow` already assume).
    newest_first: bool
    #: Whether the call itself can return `null` (not just entries within
    #: it) -- true for both `Weather` forecast calls, false for
    #: `ActivityMonitor.getHistory()`, whose own signature carries no "or
    #: Null" (checked directly against `Toybox/ActivityMonitor.html`, not
    #: assumed from the class-level "fields may return null" note, which is
    #: about the fields of one `History` entry, not the array itself).
    array_nullable: bool


#: One entry per :class:`Acquisition` value -- `wfb.emit.monkeyc` indexes this
#: by `SeriesDef.acquisition` both to decide which Toybox module a graph
#: needs imported and, for the three generated (non-heart-rate) families, to
#: generate the acquisition call itself.
ACQUISITION: dict[Acquisition, AcquisitionInfo] = {
    Acquisition.HEART_RATE: AcquisitionInfo(
        "Toybox.ActivityMonitor", "", False, False),
    Acquisition.ACTIVITY_HISTORY: AcquisitionInfo(
        "Toybox.ActivityMonitor", "ActivityMonitor.getHistory()", True, False),
    Acquisition.HOURLY_FORECAST: AcquisitionInfo(
        "Toybox.Weather", "Weather.getHourlyForecast()", False, True),
    Acquisition.DAILY_FORECAST: AcquisitionInfo(
        "Toybox.Weather", "Weather.getDailyForecast()", False, True),
}


@dataclass(frozen=True)
class SeriesDef:
    """One `series:` a `graph` element may name."""

    name: str
    acquisition: Acquisition
    #: The field read off one entry (a `HeartRateSample`, `History`,
    #: `HourlyForecast` or `DailyForecast`) -- `None` for `heart_rate`, whose
    #: value *is* the reader (`HeartRateSample.heartRate`), the same
    #: `field_name is None` convention `catalog.Source` already uses for a
    #: reader-is-the-value source.
    field_name: str | None
    value_type: Type  # NUMBER or FLOAT
    #: Set when `field_name` is a dotted path whose intermediate object is
    #: itself nullable -- `active_minutes` reads `activeMinutes.total`, and
    #: `activeMinutes` is `ActivityMonitor.ActiveMinutes or Null`. The same
    #: shape `catalog.Source.intermediate` exists for, and needs the same fix:
    #: monkeyc's flow typing narrows a *local*, not a repeated field-access
    #: expression, so the intermediate has to be hoisted into its own local
    #: before `.total` is read off it (confirmed against a real build, see
    #: `catalog.py`'s own note on `activity.active_minutes_week`).
    intermediate: str | None
    #: The natural calendar interval between entries, in seconds -- what a
    #: duration `range:` is divided by to get a sample count at build time.
    #: `None` for `heart_rate`, which passes a duration straight through to
    #: `getHeartRateHistory` instead (its own sample interval is device
    #: dependent and unknowable at build time -- Toybox/ActivityMonitor.html
    #: says so directly).
    interval_seconds: int | None
    #: The hard cap the SDK documents for this series' backing array, or
    #: `None` when no such cap is documented. Only `ACTIVITY_HISTORY` has
    #: one (`getHistory()`'s own "maximum of 7"): the forecast arrays'
    #: length is never stated, so this compiler does not invent a number for
    #: them -- it takes as many entries as the array actually has, at
    #: runtime, the same bounds-checked shape `catalog.Source.array_guard`
    #: already uses for `weather.condition_today`/`_tomorrow`.
    max_count: int | None
    unit: str | None
    doc: str
    source_ref: str


def _s(*args, **kwargs) -> SeriesDef:
    return SeriesDef(*args, **kwargs)


#: Transcribed from `Toybox/ActivityMonitor.html`, `Toybox/ActivityMonitor/
#: History.html`, `Toybox/ActivityMonitor/ActiveMinutes.html`,
#: `Toybox/Weather/HourlyForecast.html` and `Toybox/Weather/
#: DailyForecast.html` -- every field name and "or Null" checked directly
#: against the real SDK doc (`$CIQ_SDK/doc/Toybox/...`), not typed from
#: memory, for the same reason `wfb.complications`' own table gives.
SERIES: dict[str, SeriesDef] = {
    s.name: s
    for s in [
        _s("heart_rate", Acquisition.HEART_RATE, None, Type.NUMBER, None,
           None, None, "bpm",
           "heart rate history -- a Duration range bins by time; a count "
           "range reads the last N samples raw",
           "Toybox/ActivityMonitor.html#getHeartRateHistory-instance_method"),

        _s("steps", Acquisition.ACTIVITY_HISTORY, "steps", Type.NUMBER, None,
           86400, 7, None, "steps per day, up to 7 days, newest first",
           "Toybox/ActivityMonitor/History.html"),
        _s("calories", Acquisition.ACTIVITY_HISTORY, "calories", Type.NUMBER, None,
           86400, 7, "kcal", "calories burned per day, up to 7 days",
           "Toybox/ActivityMonitor/History.html"),
        _s("distance", Acquisition.ACTIVITY_HISTORY, "distance", Type.NUMBER, None,
           86400, 7, "cm", "distance per day, up to 7 days",
           "Toybox/ActivityMonitor/History.html"),
        _s("floors_climbed", Acquisition.ACTIVITY_HISTORY, "floorsClimbed", Type.NUMBER,
           None, 86400, 7, None, "floors climbed per day, up to 7 days",
           "Toybox/ActivityMonitor/History.html"),
        _s("active_minutes", Acquisition.ACTIVITY_HISTORY, "activeMinutes.total",
           Type.NUMBER, "activeMinutes", 86400, 7, "minutes",
           "active minutes per day, up to 7 days -- activeMinutes itself is "
           "nullable, .total on it is not",
           "Toybox/ActivityMonitor/History.html, "
           "Toybox/ActivityMonitor/ActiveMinutes.html"),

        _s("forecast_temperature", Acquisition.HOURLY_FORECAST, "temperature",
           Type.FLOAT, None, 3600, None, "celsius", "hourly forecast temperature",
           "Toybox/Weather/HourlyForecast.html"),
        _s("forecast_precipitation_chance", Acquisition.HOURLY_FORECAST,
           "precipitationChance", Type.NUMBER, None, 3600, None, "percent",
           "hourly forecast chance of precipitation, 0-100",
           "Toybox/Weather/HourlyForecast.html"),
        _s("forecast_cloud_cover", Acquisition.HOURLY_FORECAST, "cloudCover",
           Type.NUMBER, None, 3600, None, "percent", "hourly forecast cloud cover, 0-100",
           "Toybox/Weather/HourlyForecast.html"),
        _s("forecast_uv_index", Acquisition.HOURLY_FORECAST, "uvIndex", Type.FLOAT,
           None, 3600, None, None, "hourly forecast UV index, 0-10",
           "Toybox/Weather/HourlyForecast.html"),
        _s("forecast_wind_speed", Acquisition.HOURLY_FORECAST, "windSpeed", Type.FLOAT,
           None, 3600, None, "m/s", "hourly forecast wind speed",
           "Toybox/Weather/HourlyForecast.html"),
        _s("forecast_humidity", Acquisition.HOURLY_FORECAST, "relativeHumidity",
           Type.NUMBER, None, 3600, None, "percent", "hourly forecast relative humidity, 0-100",
           "Toybox/Weather/HourlyForecast.html"),

        _s("daily_high_temperature", Acquisition.DAILY_FORECAST, "highTemperature",
           Type.FLOAT, None, 86400, None, "celsius", "daily forecast high temperature",
           "Toybox/Weather/DailyForecast.html"),
        _s("daily_low_temperature", Acquisition.DAILY_FORECAST, "lowTemperature",
           Type.FLOAT, None, 86400, None, "celsius", "daily forecast low temperature",
           "Toybox/Weather/DailyForecast.html"),
        _s("daily_precipitation_chance", Acquisition.DAILY_FORECAST, "precipitationChance",
           Type.NUMBER, None, 86400, None, "percent",
           "daily forecast chance of precipitation, 0-100",
           "Toybox/Weather/DailyForecast.html"),
    ]
}


def get(name: str) -> SeriesDef | None:
    return SERIES.get(name)


def names() -> list[str]:
    return sorted(SERIES)


def suggest(name: str, limit: int = 3) -> list[str]:
    """Nearest series names, for the "unknown series" diagnostic."""
    import difflib

    return difflib.get_close_matches(name, SERIES, n=limit, cutoff=0.5)


#: Series an author will reasonably reach for and **cannot have**, mapped to
#: the reason, so the diagnostic can say why rather than only "unknown".
#:
#: Every one of these is a real quantity the watch measures and displays in
#: its own native widgets, which is exactly why the name gets typed. Answering
#: "unknown series 'pressure'" would send the author looking for a spelling
#: mistake that does not exist -- the same failure mode `source-renamed` and
#: `on-tap-renamed` were added to avoid. See research 08 §1 and CLAUDE.md
#: constraint 14b.
UNAVAILABLE: dict[str, str] = {
    name: ("Toybox.SensorHistory is the only API that serves it as a history, "
           "and a watch face may not declare that permission -- "
           "Core_Topics/Manifest_and_Permissions.html gives SensorHistory an "
           "empty 'Watch Face' column")
    for name in (
        "pressure", "barometric_pressure", "stress", "elevation", "altitude",
        "body_battery", "oxygen_saturation", "pulse_ox", "temperature",
    )
} | {
    name: ("there is no solar history API anywhere in Connect IQ -- solar is "
           "only ever a current reading (System.Stats.solarIntensity, "
           "Complications.COMPLICATION_TYPE_SOLAR_INPUT), so the chart on a "
           "stock Garmin face is native firmware this API does not expose")
    for name in ("solar", "solar_input", "solar_intensity", "solar_charge")
}


def unavailable_reason(name: str) -> str | None:
    """Why a plausible-but-impossible series name cannot be plotted, or None.

    Matched on the bare name and on its last dotted/underscored segment, so
    `ambient.pressure` and `sensor_pressure` land here too -- an author
    reaching for a forbidden quantity rarely guesses this module's exact
    spelling for it.
    """
    if name in UNAVAILABLE:
        return UNAVAILABLE[name]
    tail = name.rsplit(".", 1)[-1]
    return UNAVAILABLE.get(tail)
