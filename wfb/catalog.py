"""The typed data-source catalogue (ADR 0005).

Sources are addressed by dotted path, not by a flat ``#TAG#`` namespace, and each
one carries the four things the compiler must know about it:

* its **type**, so expressions can be type-checked at build time;
* its **nullability** -- every ``ActivityMonitor.Info`` field is ``... or Null``,
  so absence is the normal case and each binding must say what it renders as;
* the **permission** it implies, from which ``manifest.xml`` is derived (a missing
  permission fails *silently* on device, which is the failure this eliminates);
* its **refresh tier**, which decides where the read is placed and whether a
  ``low_power`` element may use it at all.

Every source also names the Monkey C symbol it reads, so availability can be
resolved against the device's own ``api.debug.xml`` rather than an API level.

The long-term plan (ADR 0005) is to generate this table from the SDK.  This
Phase 2 table is hand-written but deliberately shaped like the generated one,
and each entry cites the SDK page it came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Type(str, Enum):
    NUMBER = "number"
    FLOAT = "float"
    BOOLEAN = "boolean"
    STRING = "string"
    #: A clock reading; only ``format`` specs with ``%`` codes apply to it.
    TIME = "time"
    #: A calendar reading.  Separate from TIME because the codes differ -- ``%M``
    #: means minute and has no meaning on a date, and ``%b`` the reverse.
    DATE = "date"
    #: A palette or config colour.  Numeric on device, but not interchangeable
    #: with Number: arithmetic on a colour is almost always a mistake.
    COLOR = "color"

    def is_numeric(self) -> bool:
        return self in (Type.NUMBER, Type.FLOAT)

    def is_formatted(self) -> bool:
        """Types whose ``format`` uses strftime-style codes rather than {:d}."""
        return self in (Type.TIME, Type.DATE)


class Tier(str, Enum):
    #: Cheap enough to read on every frame, including ``onPartialUpdate``.
    FRAME = "frame"
    #: Expensive: SensorHistory walks, Weather, sunrise/sunset.  TTL-cached.
    SLOW = "slow"
    #: Delivered by a subscription callback.
    EVENT = "event"


@dataclass(frozen=True)
class Reader:
    """A single API call whose result several sources read fields from.

    Fetching ``ActivityMonitor.getInfo()`` once per frame and reading three
    fields off it is both cheaper and clearer than three separate calls, so the
    generator groups sources by reader.
    """

    name: str  # the local variable the generator declares
    call: str  # the Monkey C expression that produces it
    monkeyc_type: str  # its declared type, for -l 3 strict typechecking
    module: str  # the module to import
    nullable: bool = False  # whether the call itself can return null
    #: Every source reading this reader must agree with this tier -- checked in
    #: tests/test_catalog.py, since the cache (or lack of one) is generated
    #: once per *reader*, not per source.
    tier: Tier = Tier.FRAME
    #: Only meaningful when ``tier`` is ``SLOW``: how long a cached read stays
    #: fresh before the generated code calls this reader again. Chosen once,
    #: globally, rather than per-source -- there is no basis yet for a finer
    #: default, and an author can always override it (`wfb/emit/monkeyc.py`'s
    #: `ReadPlan` is where this would be threaded through if that need arises).
    ttl_seconds: int = 900


READERS: dict[str, Reader] = {
    "clock": Reader("clock", "System.getClockTime()", "System.ClockTime", "Toybox.System"),
    "settings": Reader(
        "settings", "System.getDeviceSettings()", "System.DeviceSettings", "Toybox.System"
    ),
    "stats": Reader("stats", "System.getSystemStats()", "System.Stats", "Toybox.System"),
    "date": Reader(
        "date",
        "Gregorian.info(Time.now(), Time.FORMAT_MEDIUM)",
        "Gregorian.Info",
        "Toybox.Time.Gregorian",
    ),
    "activity": Reader(
        "activity",
        "ActivityMonitor.getInfo()",
        "ActivityMonitor.Info",
        "Toybox.ActivityMonitor",
    ),
    "activity_info": Reader(
        "activityInfo",
        "Activity.getActivityInfo()",
        "Activity.Info?",
        "Toybox.Activity",
        nullable=True,
    ),
    # Toybox/Weather.html: "get the most recently cached weather conditions" --
    # cheap on Garmin's side, but still a call plus (for the daily forecast) an
    # array walk, and the tier design's whole point is not to pay that on every
    # single redraw. No permission needed: Toybox.Weather does not appear in
    # the manifest permission table at all (Core_Topics/Manifest_and_Permissions
    # .html), the same situation as Toybox.Activity.
    "weather_current": Reader(
        "weatherCurrent",
        "Weather.getCurrentConditions()",
        "Weather.CurrentConditions?",
        "Toybox.Weather",
        nullable=True,
        tier=Tier.SLOW,
        # An hour, not the 900s default: weather -- current conditions and the
        # forecast alike -- simply does not change fast enough to justify
        # reading it every 15 minutes, and the upstream service it is fetched
        # from does not refresh that often either.
        ttl_seconds=3600,
    ),
    "weather_daily": Reader(
        "weatherDaily",
        "Weather.getDailyForecast()",
        "Lang.Array<Weather.DailyForecast>?",
        "Toybox.Weather",
        nullable=True,
        tier=Tier.SLOW,
        ttl_seconds=3600,
    ),
    # Toybox/UserProfile.html: getProfile() itself never returns null (unlike
    # the ActivityMonitor/Activity/Weather readers above); the historical
    # metrics on the Profile it returns can each individually be null instead.
    # UserProfile is a real permission (unlike Activity/ActivityMonitor/
    # Weather) but is already allowed for a watch face -- see
    # WATCHFACE_PERMISSIONS below.
    "user_profile": Reader(
        "userProfile",
        "UserProfile.getProfile()",
        "UserProfile.Profile",
        "Toybox.UserProfile",
    ),
}


@dataclass(frozen=True)
class Source:
    """One addressable value."""

    path: str
    type: Type
    reader: str
    #: The field read off the reader, or ``None`` when the reader *is* the value.
    field_name: str | None
    nullable: bool
    tier: Tier
    #: ``iq:uses-permission`` ids implied by binding this source.
    permissions: tuple[str, ...] = ()
    #: ``Parent.name`` symbols that must exist on the target device.
    requires: tuple[str, ...] = ()
    unit: str | None = None
    doc: str = ""
    #: The SDK page this entry was taken from.
    source_ref: str = ""
    #: Set when the reader's value is an Array and this source reads one
    #: element's field rather than the reader object's own field directly --
    #: `weather.condition_today`/`_tomorrow` read `DailyForecast[0]`/`[1]`.
    array_index: int | None = None

    @property
    def read_expr(self) -> str:
        """The Monkey C expression reading this value off its reader local."""
        reader = READERS[self.reader]
        base = reader.name if self.array_index is None else f"{reader.name}[{self.array_index}]"
        if self.field_name is None:
            return base
        return f"{base}.{self.field_name}"

    @property
    def array_guard(self) -> str | None:
        """The extra null/bounds check `array_index` needs, beyond the reader's
        own nullability -- an Array being non-null does not mean it has an
        element at this index (a forecast provider can return fewer days than
        asked for)."""
        if self.array_index is None:
            return None
        reader = READERS[self.reader]
        return f"{reader.name}.size() > {self.array_index}"

    @property
    def guard_needed(self) -> bool:
        """Whether the generated code must null-check before using the value."""
        return self.nullable or READERS[self.reader].nullable


def _s(*args, **kwargs) -> Source:
    return Source(*args, **kwargs)


CATALOG: dict[str, Source] = {
    s.path: s
    for s in [
        # -- time ---------------------------------------------------------
        # Toybox/System/ClockTime.html -- all fields are non-null Numbers.
        _s("time.clock", Type.TIME, "clock", None, False, Tier.FRAME,
           doc="the current local time", source_ref="Toybox/System/ClockTime.html"),
        _s("time.hour", Type.NUMBER, "clock", "hour", False, Tier.FRAME,
           doc="hour, 0-23", source_ref="Toybox/System/ClockTime.html"),
        _s("time.minute", Type.NUMBER, "clock", "min", False, Tier.FRAME,
           doc="minute, 0-59", source_ref="Toybox/System/ClockTime.html"),
        _s("time.second", Type.NUMBER, "clock", "sec", False, Tier.FRAME,
           doc="second, 0-59", source_ref="Toybox/System/ClockTime.html"),
        # -- date ---------------------------------------------------------
        # Toybox/Time/Gregorian/Info.html.  Under FORMAT_MEDIUM the weekday and
        # month come back as localised strings, which is what a date row wants;
        # the day and year are Numbers either way.
        _s("date.today", Type.DATE, "date", None, False, Tier.FRAME,
           doc="today's date", source_ref="Toybox/Time/Gregorian/Info.html"),
        _s("date.day", Type.NUMBER, "date", "day", False, Tier.FRAME,
           doc="day of the month, 1-31", source_ref="Toybox/Time/Gregorian/Info.html"),
        _s("date.year", Type.NUMBER, "date", "year", False, Tier.FRAME,
           doc="the year", source_ref="Toybox/Time/Gregorian/Info.html"),
        # month/day_of_week come back as localised strings under FORMAT_MEDIUM
        # (the `date` reader's own format) -- "Sep", "Wed" -- not numbers, so
        # these are Type.STRING even though the field is `Number or String`.
        _s("date.month", Type.STRING, "date", "month", False, Tier.FRAME,
           doc="month, localised (e.g. \"Sep\")",
           source_ref="Toybox/Time/Gregorian/Info.html"),
        _s("date.day_of_week", Type.STRING, "date", "day_of_week", False, Tier.FRAME,
           doc="day of the week, localised (e.g. \"Wed\")",
           source_ref="Toybox/Time/Gregorian/Info.html"),

        # -- device settings ----------------------------------------------
        # Toybox/System/DeviceSettings.html
        _s("device.is_24_hour", Type.BOOLEAN, "settings", "is24Hour", False, Tier.FRAME,
           doc="whether the user has selected 24-hour time",
           source_ref="Toybox/System/DeviceSettings.html"),
        _s("device.do_not_disturb", Type.BOOLEAN, "settings", "doNotDisturb", False, Tier.FRAME,
           requires=("DeviceSettings.doNotDisturb",),
           doc="do-not-disturb is on", source_ref="Toybox/System/DeviceSettings.html"),
        _s("device.notification_count", Type.NUMBER, "settings", "notificationCount", False,
           Tier.FRAME, doc="unread notifications",
           source_ref="Toybox/System/DeviceSettings.html"),
        _s("device.alarm_count", Type.NUMBER, "settings", "alarmCount", False, Tier.FRAME,
           doc="alarms set", source_ref="Toybox/System/DeviceSettings.html"),
        _s("device.phone_connected", Type.BOOLEAN, "settings", "phoneConnected", False, Tier.FRAME,
           doc="phone is connected", source_ref="Toybox/System/DeviceSettings.html"),
        # -- system -------------------------------------------------------
        # Toybox/System/Stats.html -- battery and charging are non-null.
        _s("system.battery", Type.FLOAT, "stats", "battery", False, Tier.FRAME, unit="percent",
           doc="battery charge, 0-100", source_ref="Toybox/System/Stats.html"),
        _s("system.battery_in_days", Type.FLOAT, "stats", "batteryInDays", False, Tier.FRAME,
           unit="days", doc="estimated battery life remaining",
           source_ref="Toybox/System/Stats.html"),
        _s("system.charging", Type.BOOLEAN, "stats", "charging", False, Tier.FRAME,
           doc="the device is charging", source_ref="Toybox/System/Stats.html"),
        # -- activity monitor ---------------------------------------------
        # Toybox/ActivityMonitor/Info.html -- every field is "... or Null".
        _s("activity.steps", Type.NUMBER, "activity", "steps", True, Tier.FRAME,
           doc="steps today", source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.step_goal", Type.NUMBER, "activity", "stepGoal", True, Tier.FRAME,
           doc="today's step goal", source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.calories", Type.NUMBER, "activity", "calories", True, Tier.FRAME,
           unit="kcal", doc="calories today", source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.distance", Type.NUMBER, "activity", "distance", True, Tier.FRAME,
           unit="cm", doc="distance today, in centimetres",
           source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.floors_climbed", Type.NUMBER, "activity", "floorsClimbed", True, Tier.FRAME,
           doc="floors climbed today", source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.floors_climbed_goal", Type.NUMBER, "activity", "floorsClimbedGoal", True,
           Tier.FRAME, doc="today's floors goal",
           source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.move_bar_level", Type.NUMBER, "activity", "moveBarLevel", True, Tier.FRAME,
           doc="move bar level, 0-5", source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.active_minutes_week", Type.NUMBER, "activity",
           "activeMinutesWeek.total", True, Tier.FRAME, unit="minutes",
           doc="intensity minutes this week",
           source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.active_minutes_week_goal", Type.NUMBER, "activity",
           "activeMinutesWeekGoal", True, Tier.FRAME, unit="minutes",
           doc="weekly intensity-minutes goal",
           source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.stress_score", Type.NUMBER, "activity", "stressScore", True, Tier.FRAME,
           doc="current stress score, from a rolling 30s average",
           source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.respiration_rate", Type.NUMBER, "activity", "respirationRate", True,
           Tier.FRAME, unit="breaths/min", doc="current respiration rate",
           source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.time_to_recovery", Type.NUMBER, "activity", "timeToRecovery", True,
           Tier.FRAME, unit="hours", doc="time to recovery from the last activity",
           source_ref="Toybox/ActivityMonitor/Info.html"),
        # -- heart rate ----------------------------------------------------
        # Toybox/Activity/Info.html.  getActivityInfo() itself may return null.
        # No permission: Toybox.Activity does not appear in the permission table
        # at all (Core_Topics/Manifest_and_Permissions.html).  Reading heart rate
        # through Toybox.Sensor *would* need one -- and that permission is not
        # available to watch faces, which is why this source reads it off
        # Activity.getActivityInfo() instead.
        _s("heart_rate.current", Type.NUMBER, "activity_info", "currentHeartRate", True,
           Tier.FRAME, unit="bpm",
           doc="current heart rate", source_ref="Toybox/Activity/Info.html"),
        # -- ambient conditions ---------------------------------------------
        # Toybox/Activity/Info.html, the same reader and the same no-permission
        # reasoning as heart_rate.current above: Toybox.Activity is not in the
        # permission table at all. "altitude" is unrestricted; "ambientPressure"
        # is device-gated in the SDK doc but confirmed present on all three
        # targets by reading their own Supported Devices lists.
        _s("ambient.altitude", Type.FLOAT, "activity_info", "altitude", True, Tier.FRAME,
           unit="m", doc="altitude above mean sea level, from barometer or GPS",
           source_ref="Toybox/Activity/Info.html"),
        _s("ambient.pressure", Type.FLOAT, "activity_info", "ambientPressure", True,
           Tier.FRAME, unit="Pa", doc="local barometric pressure",
           source_ref="Toybox/Activity/Info.html"),
        # -- weather ---------------------------------------------------------
        # Toybox/Weather/CurrentConditions.html, Toybox/Weather/DailyForecast.html.
        # `condition` is one of the 54 `Weather.CONDITION_*` values (0-53) --
        # see wfb/icons.py's GARMIN_WEATHER_CONDITION_ICON for the full table
        # and `icon_for:` (wfb/ir.py) for turning one of these into a drawn
        # icon. All three are Tier.SLOW: see the `weather_current`/
        # `weather_daily` readers above for why, and wfb/emit/monkeyc.py's
        # ReadPlan for how a SLOW reader's value gets cached rather than
        # re-read every frame.
        _s("weather.condition", Type.NUMBER, "weather_current", "condition", True,
           Tier.SLOW, doc="the current weather condition (Weather.CONDITION_*)",
           source_ref="Toybox/Weather/CurrentConditions.html"),
        _s("weather.condition_today", Type.NUMBER, "weather_daily", "condition", True,
           Tier.SLOW, array_index=0,
           doc="today's overall forecast condition (Weather.CONDITION_*)",
           source_ref="Toybox/Weather/DailyForecast.html"),
        _s("weather.condition_tomorrow", Type.NUMBER, "weather_daily", "condition", True,
           Tier.SLOW, array_index=1,
           doc="tomorrow's forecast condition (Weather.CONDITION_*)",
           source_ref="Toybox/Weather/DailyForecast.html"),
        # temperature, today's high/low and today's precipitation chance are
        # all fields of CurrentConditions itself (not DailyForecast[0]) --
        # simpler than an array read, and it is the object weather.condition
        # already fetches, so these add no extra reader or API call.
        _s("weather.temperature", Type.FLOAT, "weather_current", "temperature", True,
           Tier.SLOW, unit="celsius", doc="current temperature",
           source_ref="Toybox/Weather/CurrentConditions.html"),
        _s("weather.feels_like_temperature", Type.FLOAT, "weather_current",
           "feelsLikeTemperature", True, Tier.SLOW, unit="celsius",
           doc="wind chill or heat index -- how the temperature actually feels",
           source_ref="Toybox/Weather/CurrentConditions.html"),
        _s("weather.high_temperature_today", Type.FLOAT, "weather_current", "highTemperature",
           True, Tier.SLOW, unit="celsius", doc="today's forecast high temperature",
           source_ref="Toybox/Weather/CurrentConditions.html"),
        _s("weather.low_temperature_today", Type.FLOAT, "weather_current", "lowTemperature",
           True, Tier.SLOW, unit="celsius", doc="today's forecast low temperature",
           source_ref="Toybox/Weather/CurrentConditions.html"),
        _s("weather.precipitation_chance_today", Type.NUMBER, "weather_current",
           "precipitationChance", True, Tier.SLOW, unit="percent",
           doc="chance of precipitation today, 0-100",
           source_ref="Toybox/Weather/CurrentConditions.html"),
        _s("weather.humidity", Type.NUMBER, "weather_current", "relativeHumidity", True,
           Tier.SLOW, unit="percent", doc="relative humidity, 0-100",
           source_ref="Toybox/Weather/CurrentConditions.html"),
        _s("weather.wind_speed", Type.FLOAT, "weather_current", "windSpeed", True,
           Tier.SLOW, unit="m/s", doc="current wind speed",
           source_ref="Toybox/Weather/CurrentConditions.html"),

        # -- user profile -----------------------------------------------------
        # Toybox/UserProfile/Profile.html. getProfile() itself never returns
        # null (unlike every other reader above); the historical metrics on
        # the Profile it returns can each be null instead if there is not yet
        # enough data. Needs the UserProfile permission -- the one source
        # namespace here that does; see WATCHFACE_PERMISSIONS below.
        _s("user.vo2max_running", Type.NUMBER, "user_profile", "vo2maxRunning", True,
           Tier.FRAME, unit="mL/kg/min", permissions=("UserProfile",),
           doc="running VO2 max, calculated from historical data",
           source_ref="Toybox/UserProfile/Profile.html"),
        _s("user.vo2max_cycling", Type.NUMBER, "user_profile", "vo2maxCycling", True,
           Tier.FRAME, unit="mL/kg/min", permissions=("UserProfile",),
           doc="cycling VO2 max, calculated from historical data",
           source_ref="Toybox/UserProfile/Profile.html"),
        _s("user.resting_heart_rate", Type.NUMBER, "user_profile", "averageRestingHeartRate",
           True, Tier.FRAME, unit="bpm", permissions=("UserProfile",),
           doc="average resting heart rate, calculated from historical data",
           source_ref="Toybox/UserProfile/Profile.html"),
    ]
}

#: The only sources `icon_for:` may bind to (wfb/ir.py) -- a Weather.CONDITION_*
#: value is meaningless without the specific glyph-mapping WfbWeather.mc and
#: wfb.icons.weather_icon_for_condition() both provide, so this is deliberately
#: not a generic "bind any Number source" mechanism.
WEATHER_CONDITION_SOURCES: frozenset[str] = frozenset({
    "weather.condition", "weather.condition_today", "weather.condition_tomorrow",
})


#: Permissions a **watch face** may declare.
#:
#: From the SDK's own table in ``Core_Topics/Manifest_and_Permissions.html``:
#: the "Watch Face" column is blank for ``Sensor``, ``SensorHistory``, ``Ant``,
#: ``BluetoothLowEnergy``, ``Fit``, ``PersistedContent``, ``ComplicationProvider``
#: and ``Data Field Alert``.  Declaring one of those is not a subtle mistake --
#: ``monkeyc`` rejects the manifest outright -- but it is far better caught
#: against the source that implied it than as a manifest error with no
#: indication of which binding is responsible.
WATCHFACE_PERMISSIONS: frozenset[str] = frozenset({
    "Background",
    "Communications",
    "ComplicationSubscriber",
    "Positioning",
    "UserProfile",
})


def get(path: str) -> Source | None:
    return CATALOG.get(path)


def suggest(path: str, limit: int = 3) -> list[str]:
    """Nearest catalogue paths, for the "misspelled data source" diagnostic."""
    import difflib

    return difflib.get_close_matches(path, CATALOG.keys(), n=limit, cutoff=0.5)


def namespaces() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in sorted(CATALOG):
        out.setdefault(path.split(".", 1)[0], []).append(path)
    return out


@dataclass
class Requirements:
    """What a set of bound sources implies for the generated project."""

    permissions: set[str] = field(default_factory=set)
    readers: set[str] = field(default_factory=set)
    modules: set[str] = field(default_factory=set)

    def add(self, source: Source) -> None:
        self.permissions.update(source.permissions)
        self.readers.add(source.reader)
        self.modules.add(READERS[source.reader].module)
