"""The typed data-source catalogue (ADR 0005).

Sources are addressed by dotted path, not by a flat ``#TAG#`` namespace, and each
one carries the things the compiler must know about it:

* its **type**, so expressions can be type-checked at build time;
* its **nullability** -- every ``ActivityMonitor.Info`` field is ``... or Null``,
  so absence is the normal case and each binding must say what it renders as;
* the **permission** it implies, from which ``manifest.xml`` is derived (a missing
  permission fails *silently* on device, which is the failure this eliminates).

Every source also names the Monkey C symbol it reads, so availability can be
resolved against the device's own ``api.debug.xml`` rather than an API level.

**There is no refresh-tier concept here: every `Reader` is read fresh, every
frame, unconditionally.** Garmin's own SDK documents its calls as already
cached on its side -- ``Toybox/Weather.html`` describes
``getCurrentConditions()`` as "get the **most recently cached** weather
conditions", not "fetch weather conditions" -- so a second cache inside the
128 KB watch face budget would be pure overhead for no freshness gained.
``weather.*`` and ``complication.*`` are bindable from ``low_power``
elements the same as anything else; overrunning the
``onPartialUpdate`` budget still calls ``onPowerBudgetExceeded`` and disables
partial updates for the rest of the app's lifecycle (CLAUDE.md constraint 4),
so watching for that is the author's own responsibility, backed by the
suppressible ``partial-update-budget`` lint rather than a hard compile-time
rule.

**One rule, no exceptions, for where a value comes from:** ``complication.*``
is *always* read through ``Toybox.Complications``; every other path here is
*always* a direct API read. See :mod:`wfb.complications` for the single
``COMPLICATION_TYPE_*`` table both the ``complication.*`` sources below and
an element's ``on_hold:``/``launch:`` target are generated from -- looping
over that table, not hand-copied, because a 42-entry hand copy is exactly
the drift this project keeps warning about.

The long-term plan (ADR 0005) is to generate the rest of this table from the
SDK too. This table is otherwise hand-written but deliberately shaped like
the generated one, and each entry cites the SDK page it came from.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from enum import Enum

from . import complications


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


#: Maps a `complications.ComplicationType.value_type` string onto this
#: module's own `Type` enum -- `wfb.complications` cannot import this module
#: (circular), so it expresses value types as plain strings and this is
#: where they become real `Type` members.
_COMPLICATION_VALUE_TYPE: dict[str, Type] = {
    "number": Type.NUMBER,
    "float": Type.FLOAT,
    "string": Type.STRING,
}

#: The Monkey C cast each value type needs -- see `Source.cast`'s docstring.
_COMPLICATION_CAST: dict[str, str] = {
    "number": "Number?",
    "float": "Float?",
    "string": "String?",
}


@dataclass(frozen=True)
class Reader:
    """One generated local a `Source` reads its value off.

    Covers two shapes, told apart by `complication_type` (below): set means
    the complication shape, ``None`` means the shared-accessor shape.

    **Shared accessor** (e.g. ``activity``, ``weather_current``, ``date``):
    several sources read fields off one call. Fetching
    ``ActivityMonitor.getInfo()`` once per frame and reading three fields
    off it is both cheaper and clearer than three separate calls, so the
    generator groups sources by reader and hoists one ``var`` that every
    source sharing it reads through.

    **Complication** (one per `complications.TYPES` entry -- see the
    ``READERS.update(...)`` loop below): a single-use wrapper, generated
    rather than hand-copied per the module docstring's "one rule, no
    exceptions" paragraph, so it can share `ReadPlan`'s declare/guard/
    parameter pipeline (`wfb.emit.monkeyc.readplan`, keyed by reader) even
    though each one serves exactly one `Source` and `call` -- e.g.
    ``WfbComplications.valueOf(new Complications.Id(Complications.<CONSTANT>))``
    -- is already the whole read, with no fields to share afterwards.
    """

    name: str  # the local variable the generator declares
    call: str  # the Monkey C expression that produces it
    monkeyc_type: str  # its declared type, for -l 3 strict typechecking
    module: str  # the module to import
    nullable: bool = False  # whether the call itself can return null
    #: ``Parent.name`` symbols (`Device.has_symbol`'s own namespace) this
    #: reader's `call` actually invokes at runtime, checked against the
    #: device's own `api.debug.xml` by `wfb.availability` rather than an API
    #: level (CLAUDE.md constraint 6d). Every reader below sets exactly the
    #: one function `call` is built from, confirmed present in every
    #: currently-installed device's symbol table, `fenix6`/`fr245` (the
    #: lowest API level installed) included -- so today this field never
    #: actually gates anything; it exists so a future device genuinely
    #: lacking one of these core calls is caught the same structural way
    #: `requires_module` below already catches `Complications`, rather than
    #: by an API-level compare (constraint 6).
    requires: tuple[str, ...] = ()
    #: The bare `Toybox` module name (`Device.has_module`'s own namespace,
    #: e.g. ``"Complications"``) this reader's `call` needs to exist at all,
    #: or ``None`` when `requires` above is enough on its own. Set only for
    #: the 42 complication readers below: `fenix6` and `fr245` do not merely
    #: lack the individual functions `WfbComplications.valueOf` calls, they
    #: lack the `Toybox.Complications` module *itself* -- so every reference
    #: to it, not only a call, fails at runtime (`wfb.devices.Device.
    #: has_module`'s own docstring). `wfb.availability.reader_unavailable`
    #: checks this before `requires`, since a missing module makes checking
    #: an individual function moot.
    requires_module: str | None = None
    #: Only set for a `complication.*` reader: the `Complications.Type`
    #: constant this reader pulls (`WfbComplications.valueOf`, a plain read --
    #: see module docstring, there is no cache here). Used for two things:
    #: `wfb.availability.uses_complications` reads it (via `requires_module`
    #: above, set on exactly the same readers) to decide whether a design
    #: needs `Toybox.Complications` at all -- availability is gated per
    #: device at runtime, never by raising the manifest's one shared
    #: `minApiLevel` (`wfb/emit/manifest.py`'s module docstring) -- and
    #: `wfb/emit/monkeyc/view.py` reads it to build the `onLayout`
    #: subscription list: subscribing is kept even though the read itself is
    #: a pull, so a value that arrives after the first draw is not stuck
    #: stale forever (`docs/adr/0005`,
    #: `docs/research/probes/complication-pull`).
    complication_type: str | None = None


READERS: dict[str, Reader] = {
    "clock": Reader("clock", "System.getClockTime()", "System.ClockTime", "Toybox.System",
                     requires=("System.getClockTime",)),
    "settings": Reader(
        "settings", "System.getDeviceSettings()", "System.DeviceSettings", "Toybox.System",
        requires=("System.getDeviceSettings",),
    ),
    "stats": Reader("stats", "System.getSystemStats()", "System.Stats", "Toybox.System",
                     requires=("System.getSystemStats",)),
    "date": Reader(
        "date",
        "Gregorian.info(Time.now(), Time.FORMAT_MEDIUM)",
        "Gregorian.Info",
        "Toybox.Time.Gregorian",
        requires=("Gregorian.info",),
    ),
    # The same call under FORMAT_SHORT, where `day_of_week` is a Number
    # (Gregorian.DAY_SUNDAY = 1 .. DAY_SATURDAY = 7, Toybox/Time/Gregorian.html)
    # rather than a localised String -- the one form an expression can do
    # arithmetic on or compare.  A second reader, not a second field on
    # `date`: one `Gregorian.Info` cannot be both formats at once.
    "date_short": Reader(
        "dateShort",
        "Gregorian.info(Time.now(), Time.FORMAT_SHORT)",
        "Gregorian.Info",
        "Toybox.Time.Gregorian",
        requires=("Gregorian.info",),
    ),
    "activity": Reader(
        "activity",
        "ActivityMonitor.getInfo()",
        "ActivityMonitor.Info",
        "Toybox.ActivityMonitor",
        requires=("ActivityMonitor.getInfo",),
    ),
    "activity_info": Reader(
        "activityInfo",
        "Activity.getActivityInfo()",
        "Activity.Info?",
        "Toybox.Activity",
        nullable=True,
        requires=("Activity.getActivityInfo",),
    ),
    # Toybox/Weather.html: "get the most recently cached weather conditions" --
    # already cached on Garmin's side, which is exactly why this project does
    # not also cache it (see module docstring). No permission needed:
    # Toybox.Weather does not appear in the manifest permission table at all
    # (Core_Topics/Manifest_and_Permissions.html), the same situation as
    # Toybox.Activity.
    "weather_current": Reader(
        "weatherCurrent",
        "Weather.getCurrentConditions()",
        "Weather.CurrentConditions?",
        "Toybox.Weather",
        nullable=True,
        requires=("Weather.getCurrentConditions",),
    ),
    "weather_daily": Reader(
        "weatherDaily",
        "Weather.getDailyForecast()",
        "Lang.Array<Weather.DailyForecast>?",
        "Toybox.Weather",
        nullable=True,
        requires=("Weather.getDailyForecast",),
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
        requires=("UserProfile.getProfile",),
    ),
}


def _complication_reader_key(name: str) -> str:
    return f"complication_{name}"


def _complication_local_name(name: str) -> str:
    """``body_battery`` -> ``bodyBatteryComplication``.

    The suffix, not a ``complication`` prefix, is deliberate: a reader's
    local and a *source's* local live in the same scope in the generated
    element method (the reader arrives as the method's parameter, and
    ``ReadPlan.declarations`` then declares the value read off it).
    ``wfb.ir.local_name`` derives the value local straight from the source
    path, so ``complication.body_battery`` already owns
    ``complicationBodyBattery``; naming the reader the same way would
    collide. Suffixing keeps the two distinct while both still read as what
    they are: ``bodyBatteryComplication`` is the ``Complication`` object,
    ``complicationBodyBattery`` is the value pulled off it.

    ``tests/test_catalog.py::test_reader_and_value_locals_never_collide``
    checks this catalogue-wide: every `Reader.name`, every
    `wfb.ir.local_name(path)`, the ``...Obj`` intermediate form, and the
    emitter's own fixed scope-local names, not just this one suffix.
    """
    return "".join(
        part if index == 0 else part.capitalize()
        for index, part in enumerate(name.split("_"))
    ) + "Complication"


# Generated, not hand-written -- one Reader per `complications.TYPES` entry,
# doing a plain pull read (see module docstring: no cache, no tier). A device
# that doesn't support a type just gets `null` back from `valueOf`, the
# ordinary "absence is normal" contract every other nullable source has.
READERS.update({
    _complication_reader_key(t.name): Reader(
        _complication_local_name(t.name),
        f"WfbComplications.valueOf(new Complications.Id(Complications.{t.constant}))",
        "Complications.Complication?",
        "Toybox.Complications",
        nullable=True,
        complication_type=t.constant,
        # `has_module`, not `has_symbol`: fenix6/fr245 do not merely lack
        # `Complications.getComplication`, they lack the `Toybox.
        # Complications` module itself -- confirmed absent from both
        # devices' own `<dataEntry type="module">` rows. Any reference to
        # the module at runtime fails on a device like that, not only a
        # call, which is why `wfb.availability` checks `requires_module`
        # before ever looking at `requires` (see Reader.requires_module's
        # own docstring).
        requires_module="Complications",
    )
    for t in complications.TYPES.values()
})


@dataclass(frozen=True)
class Source:
    """One addressable value."""

    path: str
    type: Type
    reader: str
    #: The field read off the reader, or ``None`` when the reader *is* the value.
    field_name: str | None
    nullable: bool
    #: ``iq:uses-permission`` ids implied by binding this source.
    permissions: tuple[str, ...] = ()
    #: ``Parent.name`` *function* symbols (`Device.has_symbol`'s own
    #: namespace -- checked with `_symbol_gap`, never `has_field`) that this
    #: source's own read needs *beyond* its reader's call -- e.g. a helper
    #: method the value expression invokes that the reader itself does not.
    #: No entry currently needs this (every source's availability is already
    #: covered by its reader's own `Reader.requires`/`requires_module` plus
    #: `field_name` -> `Device.has_field`, checked automatically by
    #: `wfb.availability.source_unavailable`). **Do not put a field name
    #: here**: `has_symbol` only ever matches `<functionEntry>` rows in
    #: `api.debug.xml`, never a ``<entry field="true" .../>`` row, so a
    #: field named here reports absent on every device, including ones that
    #: have it. The `field_name` -> `Device.has_field` check above already
    #: covers a bare field's own presence/absence correctly; this tuple is
    #: for a genuine extra *function* dependency only.
    requires: tuple[str, ...] = ()
    unit: str | None = None
    doc: str = ""
    #: The SDK page this entry was taken from.
    source_ref: str = ""
    #: Set when the reader's value is an Array and this source reads one
    #: element's field rather than the reader object's own field directly --
    #: `weather.condition_today`/`_tomorrow` read `DailyForecast[0]`/`[1]`.
    array_index: int | None = None
    #: Set when `field_name` is a dotted path whose intermediate object is itself
    #: nullable -- `activity.active_minutes_week` reads `activeMinutesWeek.total`,
    #: and `activeMinutesWeek` is `ActiveMinutes or Null`.
    intermediate: str | None = None
    #: A Monkey C type the read expression must be cast to (e.g. ``"Number?"``,
    #: ``"String?"``, ``"Float?"``), or ``None`` when no cast is needed.
    #: Set for `complication.*` sources: `Complications.Complication.value`
    #: is declared `Complications.Value or Null` -- a union of
    #: `String or Number or Float or Long or Double or Null` -- so the
    #: compiler cannot narrow it to this source's own `type` without an
    #: explicit cast.  Also set for `date.weekday`, whose field is declared
    #: `Number or String` though FORMAT_SHORT always yields the Number.
    #: **Contract:** `Source.read_expr` deliberately does NOT
    #: bake this cast into the expression it returns -- the emitter
    #: (`wfb/emit/monkeyc/`) is the one that knows the surrounding
    #: expression shape (a bare read vs. inside a ternary guard vs. inside a
    #: larger expression) and can append `` as {cast}`` with the parentheses
    #: the context actually needs. Treat `read_expr` as "what to read" and
    #: `cast` as a separate instruction to the emitter, not something already
    #: folded into the string.
    cast: str | None = None
    #: The `complications` type *name* (`wfb.complications.TYPES` key) whose
    #: glance this value conventionally belongs to, or ``None``. Set
    #: automatically to a `complication.*` source's own name; set by hand on
    #: a handful of direct-read sources that have an established
    #: counterpart (see each entry's own comment below). `on_hold: auto`
    #: (`wfb/ir/builder.py`) resolves to this field.
    launch_complication: str | None = None

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
    def intermediate_guard(self) -> str | None:
        """The null check a dotted `field_name` needs for its intermediate object."""
        if self.intermediate is None:
            return None
        return f"{READERS[self.reader].name}.{self.intermediate} != null"

    @property
    def guard_needed(self) -> bool:
        """Whether the generated code must null-check before using the value."""
        return self.nullable or READERS[self.reader].nullable


_s = Source


CATALOG: dict[str, Source] = {
    s.path: s
    for s in [
        # -- time ---------------------------------------------------------
        # Toybox/System/ClockTime.html -- all fields are non-null Numbers.
        _s("time.clock", Type.TIME, "clock", None, False,
           doc="the current local time", source_ref="Toybox/System/ClockTime.html"),
        _s("time.hour", Type.NUMBER, "clock", "hour", False,
           doc="hour, 0-23", source_ref="Toybox/System/ClockTime.html"),
        _s("time.minute", Type.NUMBER, "clock", "min", False,
           doc="minute, 0-59", source_ref="Toybox/System/ClockTime.html"),
        _s("time.second", Type.NUMBER, "clock", "sec", False,
           doc="second, 0-59", source_ref="Toybox/System/ClockTime.html"),
        # -- date ---------------------------------------------------------
        # Toybox/Time/Gregorian/Info.html.  Under FORMAT_MEDIUM the weekday and
        # month come back as localised strings, which is what a date row wants;
        # the day and year are Numbers either way.
        _s("date.today", Type.DATE, "date", None, False,
           doc="today's date", source_ref="Toybox/Time/Gregorian/Info.html",
           launch_complication="date"),
        _s("date.day", Type.NUMBER, "date", "day", False,
           doc="day of the month, 1-31", source_ref="Toybox/Time/Gregorian/Info.html",
           launch_complication="date"),
        _s("date.year", Type.NUMBER, "date", "year", False,
           doc="the year", source_ref="Toybox/Time/Gregorian/Info.html"),
        # month/day_of_week come back as localised strings under FORMAT_MEDIUM
        # (the `date` reader's own format) -- "Sep", "Wed" -- not numbers, so
        # these are Type.STRING even though the field is `Number or String`.
        _s("date.month", Type.STRING, "date", "month", False,
           doc="month, localised (e.g. \"Sep\")",
           source_ref="Toybox/Time/Gregorian/Info.html"),
        _s("date.day_of_week", Type.STRING, "date", "day_of_week", False,
           doc="day of the week, localised (e.g. \"Wed\")",
           source_ref="Toybox/Time/Gregorian/Info.html"),
        # The numeric twin, read under FORMAT_SHORT (the `date_short`
        # reader).  The field is declared `Number or String`, so -l 3 needs
        # the cast to let it reach a Number local -- the same reason
        # complication values carry one.
        _s("date.weekday", Type.NUMBER, "date_short", "day_of_week", False,
           cast="Number",
           doc="day of the week as a number, 1 = Sunday .. 7 = Saturday",
           source_ref="Toybox/Time/Gregorian.html"),

        # -- device settings ----------------------------------------------
        # Toybox/System/DeviceSettings.html
        _s("device.is_24_hour", Type.BOOLEAN, "settings", "is24Hour", False,
           doc="whether the user has selected 24-hour time",
           source_ref="Toybox/System/DeviceSettings.html"),
        # No `requires=` here: `doNotDisturb` is a *field*
        # (`<entry field="true" symbol="doNotDisturb"/>`), already covered by
        # `field_name` -> `Device.has_field` in `source_unavailable` -- see
        # `Source.requires`'s own docstring above for why this field must
        # not be named there instead.
        _s("device.do_not_disturb", Type.BOOLEAN, "settings", "doNotDisturb", False,
           doc="do-not-disturb is on", source_ref="Toybox/System/DeviceSettings.html"),
        _s("device.notification_count", Type.NUMBER, "settings", "notificationCount", False,
           doc="unread notifications",
           source_ref="Toybox/System/DeviceSettings.html",
           launch_complication="notification_count"),
        _s("device.alarm_count", Type.NUMBER, "settings", "alarmCount", False,
           doc="alarms set", source_ref="Toybox/System/DeviceSettings.html"),
        _s("device.phone_connected", Type.BOOLEAN, "settings", "phoneConnected", False,
           doc="phone is connected", source_ref="Toybox/System/DeviceSettings.html"),
        # -- system -------------------------------------------------------
        # Toybox/System/Stats.html -- battery and charging are non-null.
        _s("system.battery", Type.FLOAT, "stats", "battery", False, unit="percent",
           doc="battery charge, 0-100", source_ref="Toybox/System/Stats.html",
           launch_complication="battery"),
        _s("system.battery_in_days", Type.FLOAT, "stats", "batteryInDays", False,
           unit="days", doc="estimated battery life remaining",
           source_ref="Toybox/System/Stats.html"),
        _s("system.charging", Type.BOOLEAN, "stats", "charging", False,
           doc="the device is charging", source_ref="Toybox/System/Stats.html"),
        # -- activity monitor ---------------------------------------------
        # Toybox/ActivityMonitor/Info.html -- every field is "... or Null".
        _s("activity.steps", Type.NUMBER, "activity", "steps", True,
           doc="steps today", source_ref="Toybox/ActivityMonitor/Info.html",
           launch_complication="steps"),
        _s("activity.step_goal", Type.NUMBER, "activity", "stepGoal", True,
           doc="today's step goal", source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.calories", Type.NUMBER, "activity", "calories", True,
           unit="kcal", doc="calories today", source_ref="Toybox/ActivityMonitor/Info.html",
           launch_complication="calories"),
        _s("activity.distance", Type.NUMBER, "activity", "distance", True,
           unit="cm", doc="distance today, in centimetres",
           source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.floors_climbed", Type.NUMBER, "activity", "floorsClimbed", True,
           doc="floors climbed today", source_ref="Toybox/ActivityMonitor/Info.html",
           launch_complication="floors_climbed"),
        _s("activity.floors_climbed_goal", Type.NUMBER, "activity", "floorsClimbedGoal", True,
           doc="today's floors goal",
           source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.move_bar_level", Type.NUMBER, "activity", "moveBarLevel", True,
           doc="move bar level, 0-5", source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.active_minutes_week", Type.NUMBER, "activity",
           "activeMinutesWeek.total", True, unit="minutes",
           doc="intensity minutes this week",
           source_ref="Toybox/ActivityMonitor/Info.html",
           # activeMinutesWeek is itself "ActiveMinutes or Null" -- the
           # generated code cannot dereference `.total` on it unconditionally.
           # See Source.intermediate_guard.
           intermediate="activeMinutesWeek",
           launch_complication="intensity_minutes"),
        _s("activity.active_minutes_week_goal", Type.NUMBER, "activity",
           "activeMinutesWeekGoal", True, unit="minutes",
           doc="weekly intensity-minutes goal",
           source_ref="Toybox/ActivityMonitor/Info.html"),
        _s("activity.stress_score", Type.NUMBER, "activity", "stressScore", True,
           doc="current stress score, from a rolling 30s average",
           source_ref="Toybox/ActivityMonitor/Info.html",
           launch_complication="stress"),
        _s("activity.respiration_rate", Type.NUMBER, "activity", "respirationRate", True,
           unit="breaths/min", doc="current respiration rate",
           source_ref="Toybox/ActivityMonitor/Info.html",
           launch_complication="respiration_rate"),
        _s("activity.time_to_recovery", Type.NUMBER, "activity", "timeToRecovery", True,
           unit="hours", doc="time to recovery from the last activity",
           source_ref="Toybox/ActivityMonitor/Info.html",
           launch_complication="recovery_time"),
        # -- heart rate ----------------------------------------------------
        # Toybox/Activity/Info.html.  getActivityInfo() itself may return null.
        # No permission: Toybox.Activity does not appear in the permission table
        # at all (Core_Topics/Manifest_and_Permissions.html).  Reading heart rate
        # through Toybox.Sensor *would* need one -- and that permission is not
        # available to watch faces, which is why this source reads it off
        # Activity.getActivityInfo() instead.
        _s("heart_rate.current", Type.NUMBER, "activity_info", "currentHeartRate", True,
           unit="bpm",
           doc="current heart rate", source_ref="Toybox/Activity/Info.html",
           launch_complication="heart_rate"),
        # -- blood oxygen ----------------------------------------------------
        # Toybox/Activity/Info.html, same reader and no-permission reasoning as
        # heart_rate.current above. Confirmed present on all three targets by
        # reading currentOxygenSaturation's own Supported Devices list (it is
        # device-gated in the SDK doc, unlike currentHeartRate).
        _s("pulse_ox.current", Type.NUMBER, "activity_info", "currentOxygenSaturation", True,
           unit="percent",
           doc="current blood oxygen saturation", source_ref="Toybox/Activity/Info.html",
           launch_complication="pulse_ox"),
        # -- ambient conditions ---------------------------------------------
        # Toybox/Activity/Info.html, the same reader and the same no-permission
        # reasoning as heart_rate.current above: Toybox.Activity is not in the
        # permission table at all. "altitude" is unrestricted; "ambientPressure"
        # is device-gated in the SDK doc but confirmed present on all three
        # targets by reading their own Supported Devices lists.
        _s("ambient.altitude", Type.FLOAT, "activity_info", "altitude", True,
           unit="m", doc="altitude above mean sea level, from barometer or GPS",
           source_ref="Toybox/Activity/Info.html",
           launch_complication="altitude"),
        _s("ambient.pressure", Type.FLOAT, "activity_info", "ambientPressure", True,
           unit="Pa", doc="local barometric pressure",
           source_ref="Toybox/Activity/Info.html",
           launch_complication="sea_level_pressure"),
        # -- weather ---------------------------------------------------------
        # Toybox/Weather/CurrentConditions.html, Toybox/Weather/DailyForecast.html.
        # `condition` is one of the 54 `Weather.CONDITION_*` values (0-53) --
        # see wfb/icons.py's GARMIN_WEATHER_CONDITION_ICON for the full table
        # and `icon_for:` (`wfb.ir`) for turning one of these into a drawn
        # icon.
        _s("weather.condition", Type.NUMBER, "weather_current", "condition", True,
           doc="the current weather condition (Weather.CONDITION_*)",
           source_ref="Toybox/Weather/CurrentConditions.html",
           launch_complication="current_weather"),
        _s("weather.condition_today", Type.NUMBER, "weather_daily", "condition", True,
           array_index=0,
           doc="today's overall forecast condition (Weather.CONDITION_*)",
           source_ref="Toybox/Weather/DailyForecast.html"),
        # Deliberately no launch_complication: COMPLICATION_TYPE_FORECAST_
        # WEATHER_1DAY means *tomorrow*, not today (see the SDK's own Type
        # table) -- mapping condition_today to it would open the wrong day's
        # glance.
        _s("weather.condition_tomorrow", Type.NUMBER, "weather_daily", "condition", True,
           array_index=1,
           doc="tomorrow's forecast condition (Weather.CONDITION_*)",
           source_ref="Toybox/Weather/DailyForecast.html",
           launch_complication="forecast_weather_1day"),
        # temperature, today's high/low and today's precipitation chance are
        # all fields of CurrentConditions itself (not DailyForecast[0]) --
        # simpler than an array read, and it is the object weather.condition
        # already fetches, so these add no extra reader or API call.
        _s("weather.temperature", Type.FLOAT, "weather_current", "temperature", True,
           unit="celsius", doc="current temperature",
           source_ref="Toybox/Weather/CurrentConditions.html",
           launch_complication="current_temperature"),
        _s("weather.feels_like_temperature", Type.FLOAT, "weather_current",
           "feelsLikeTemperature", True, unit="celsius",
           doc="wind chill or heat index -- how the temperature actually feels",
           source_ref="Toybox/Weather/CurrentConditions.html"),
        _s("weather.high_temperature_today", Type.FLOAT, "weather_current", "highTemperature",
           True, unit="celsius", doc="today's forecast high temperature",
           source_ref="Toybox/Weather/CurrentConditions.html",
           launch_complication="high_low_temperature"),
        _s("weather.low_temperature_today", Type.FLOAT, "weather_current", "lowTemperature",
           True, unit="celsius", doc="today's forecast low temperature",
           source_ref="Toybox/Weather/CurrentConditions.html",
           launch_complication="high_low_temperature"),
        _s("weather.precipitation_chance_today", Type.NUMBER, "weather_current",
           "precipitationChance", True, unit="percent",
           doc="chance of precipitation today, 0-100",
           source_ref="Toybox/Weather/CurrentConditions.html"),
        _s("weather.humidity", Type.NUMBER, "weather_current", "relativeHumidity", True,
           unit="percent", doc="relative humidity, 0-100",
           source_ref="Toybox/Weather/CurrentConditions.html"),
        _s("weather.wind_speed", Type.FLOAT, "weather_current", "windSpeed", True,
           unit="m/s", doc="current wind speed",
           source_ref="Toybox/Weather/CurrentConditions.html"),

        # -- user profile -----------------------------------------------------
        # Toybox/UserProfile/Profile.html. getProfile() itself never returns
        # null (unlike every other reader above); the historical metrics on
        # the Profile it returns can each be null instead if there is not yet
        # enough data. Needs the UserProfile permission -- the one source
        # namespace here that does; see WATCHFACE_PERMISSIONS below.
        _s("user.vo2max_running", Type.NUMBER, "user_profile", "vo2maxRunning", True,
           unit="mL/kg/min", permissions=("UserProfile",),
           doc="running VO2 max, calculated from historical data",
           source_ref="Toybox/UserProfile/Profile.html",
           launch_complication="vo2max_run"),
        _s("user.vo2max_cycling", Type.NUMBER, "user_profile", "vo2maxCycling", True,
           unit="mL/kg/min", permissions=("UserProfile",),
           doc="cycling VO2 max, calculated from historical data",
           source_ref="Toybox/UserProfile/Profile.html",
           launch_complication="vo2max_bike"),
        _s("user.resting_heart_rate", Type.NUMBER, "user_profile", "averageRestingHeartRate",
           True, unit="bpm", permissions=("UserProfile",),
           doc="average resting heart rate, calculated from historical data",
           source_ref="Toybox/UserProfile/Profile.html"),

        # -- complications (Toybox/Complications.html, API 4.2.0) -----------
        # Generated below by looping over `complications.TYPES` -- all 42
        # real COMPLICATION_TYPE_* values, not a hand-picked subset. See the
        # module docstring's "one rule, no exceptions" paragraph: this is the
        # *only* place a `complication.*` path is read from, and reading one
        # is always a pull through `Toybox.Complications`, never a shortcut
        # through ActivityMonitor/Activity/Weather/UserProfile even when one
        # of those would also work.
        *[
            _s(
                f"complication.{t.name}",
                _COMPLICATION_VALUE_TYPE[t.value_type],
                _complication_reader_key(t.name),
                "value",
                True,
                permissions=("ComplicationSubscriber",),
                unit=t.unit,
                doc=t.doc,
                source_ref="Toybox/Complications.html",
                cast=_COMPLICATION_CAST[t.value_type],
                launch_complication=t.name,
            )
            for t in complications.TYPES.values()
        ],
    ]
}


#: The nine paths superseded by `complication.*`, now the one and only way
#: to read a complication (module docstring's "one rule, no exceptions").
#: Kept so an author's old design gets a diagnostic naming the replacement
#: rather than a bare "unknown data source". No example YAML in this repo
#: binds any of these.
RENAMED_SOURCES: dict[str, str] = {
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


def renamed_to(path: str) -> str | None:
    """The new path for a renamed source, or ``None`` if ``path`` was never
    one of the nine complication-backed paths this catalogue moved under
    `complication.*`. Callers (`wfb.ir`, `wfb.expr`) should check this
    *before* falling back to `suggest`'s fuzzy match -- a renamed path is an
    exact former name, not a typo, and deserves the more specific
    diagnostic."""
    return RENAMED_SOURCES.get(path)


#: The only sources `icon_for:` may bind to (`wfb.ir`) -- a Weather.CONDITION_*
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
    """Nearest catalogue paths, for the "misspelled data source" diagnostic.

    Does not consider `RENAMED_SOURCES` keys -- those are exact former names
    with their own, more specific diagnostic (`renamed_to`), not something a
    fuzzy match should surface as a "did you mean" guess.
    """
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
