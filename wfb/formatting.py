"""Format specs: what they compile to, and how wide they can get.

ADR 0005 4.  ``format:`` uses Python-style specs because they are familiar and
unambiguous.  Two jobs come out of one declaration:

* the **Monkey C** that renders the value;
* the **widest plausible rendering**, which is what makes "does this label
  overflow its slot on this device?" a static check, and what decides which
  glyphs a subsetted font must contain.

Time specs use strftime codes, plus one addition: ``%h`` is *the hour the user
has asked to see* -- 24-hour zero-padded or 12-hour unpadded, following
``DeviceSettings.is24Hour``.  Hand-written faces get this wrong constantly; a
builder should get it right once.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable, NamedTuple

from .catalog import Source, Type

_FIELD_RE = re.compile(r"\{(?::(?P<spec>[^}]*))?\}")
_NUMERIC_SPEC_RE = re.compile(r"^(?P<zero>0)?(?P<width>\d+)?(?:\.(?P<precision>\d+))?(?P<kind>[dfs])$")


class FormatError(ValueError):
    pass


@dataclass(frozen=True)
class Literal:
    text: str


@dataclass(frozen=True)
class Field:
    spec: str


@dataclass(frozen=True)
class TimePart:
    """One strftime code, or literal text between codes."""

    code: str | None
    text: str = ""


class Readers(NamedTuple):
    """The generated reader locals a strftime code's Monkey C reads off."""

    clock: str = "clock"
    settings: str = "settings"
    date: str = "date"
    date_short: str = "dateShort"


@dataclass(frozen=True)
class Code:
    """One strftime code, with both of its implementations in one row.

    `emit` (the Monkey C String expression, given the reader locals) and
    `render` (the host rendering `wfb preview` draws, given values keyed like
    `wfb.preview.SAMPLE`) must agree for every input; keeping them side by
    side is what lets the two be checked against each other one code at a
    time.  ``%%`` has neither: :func:`parse_time` turns it into literal text.
    """

    description: str
    #: The widest string the code can produce -- for the overflow lint and a
    #: subsetted font's glyph set.
    widest: str
    emit: Callable[[Readers], str] | None = None
    render: Callable[[dict], str] | None = None
    #: A `wfb.catalog.CATALOG` path the code reads beyond the value's own
    #: reader -- see :func:`extra_paths`.
    extra_path: str | None = None


_PERCENT = Code("a literal percent sign", "%")


def _hour(values: dict) -> int:
    return int(values.get("time.hour", 10))


def _hour12(values: dict) -> int:
    return (_hour(values) % 12) or 12


def _day(values: dict) -> int:
    return int(values.get("date.day", 3))


def _year(values: dict) -> int:
    return int(values.get("date.year", 2026))


#: strftime codes for a **clock** reading.
TIME_CODES: dict[str, Code] = {
    "H": Code("hour, 24-hour, zero-padded", "23",
              lambda r: f'{r.clock}.hour.format("%02d")',
              lambda v: f"{_hour(v):02d}"),
    "I": Code("hour, 12-hour, zero-padded", "12",
              lambda r: f'WfbTime.hour12({r.clock}.hour).format("%02d")',
              lambda v: f"{_hour12(v):02d}"),
    "l": Code("hour, 12-hour, unpadded", "12",
              lambda r: f'WfbTime.hour12({r.clock}.hour).format("%d")',
              lambda v: f"{_hour12(v):d}"),
    # `WfbTime.displayHour` (runtime-lib/WfbTime.mc): zero-padded 24-hour, or
    # unpadded 12-hour, following `DeviceSettings.is24Hour`.
    "h": Code("hour, following the device's 12/24-hour setting", "23",
              lambda r: f"WfbTime.displayHour({r.clock}.hour, {r.settings}.is24Hour)",
              lambda v: (f"{_hour(v):02d}" if bool(v.get("device.is_24_hour", True))
                         else f"{_hour12(v):d}"),
              extra_path="device.is_24_hour"),
    "M": Code("minute, zero-padded", "59",
              lambda r: f'{r.clock}.min.format("%02d")',
              lambda v: f"{int(v.get('time.minute', 9)):02d}"),
    "S": Code("second, zero-padded", "59",
              lambda r: f'{r.clock}.sec.format("%02d")',
              lambda v: f"{int(v.get('time.second', 0)):02d}"),
    "p": Code("AM or PM", "AM",
              lambda r: f"WfbTime.meridiem({r.clock}.hour)",
              lambda v: "AM" if _hour(v) < 12 else "PM"),
    "%": _PERCENT,
}

#: strftime codes for a **date** reading.
#:
#: The widths assume English: the weekday and month arrive from the firmware as
#: localised strings (``FORMAT_MEDIUM``, the ``date`` reader, needs no
#: conversion for them), so a longer language makes these under-estimates and
#: the overflow lint correspondingly optimistic.
DATE_CODES: dict[str, Code] = {
    "a": Code("abbreviated weekday, e.g. Thu", "Wed",
              lambda r: f"{r.date}.day_of_week",
              lambda v: str(v.get("date.day_of_week", "Wed"))),
    "d": Code("day of the month, zero-padded", "30",
              lambda r: f'{r.date}.day.format("%02d")',
              lambda v: f"{_day(v):02d}"),
    "e": Code("day of the month, unpadded", "30",
              lambda r: f'{r.date}.day.format("%d")',
              lambda v: f"{_day(v)}"),
    "b": Code("abbreviated month, e.g. Sep", "Sep",
              lambda r: f"{r.date}.month",
              lambda v: str(v.get("date.month", "Sep"))),
    # FORMAT_MEDIUM's `month` is a localised String with no numeric form, so
    # the Number month only exists under FORMAT_SHORT (the `date_short`
    # reader), cast from its declared `Number or String` the same way
    # `date.weekday` is.
    "m": Code("month number, zero-padded", "12",
              lambda r: f'({r.date_short}.month as Number).format("%02d")',
              lambda v: f"{int(v.get('date.month_number', 9)):02d}",
              extra_path="date.weekday"),
    "Y": Code("four-digit year", "2026",
              lambda r: f'{r.date}.year.format("%04d")',
              lambda v: f"{_year(v):04d}"),
    "y": Code("two-digit year", "26",
              lambda r: f'({r.date}.year % 100).format("%02d")',
              lambda v: f"{_year(v) % 100:02d}"),
    "%": _PERCENT,
}


def parse(spec: str) -> list:
    """Split a format string into literals and fields."""
    parts: list = []
    pos = 0
    for match in _FIELD_RE.finditer(spec):
        if match.start() > pos:
            parts.append(Literal(spec[pos:match.start()]))
        parts.append(Field(match.group("spec") or ""))
        pos = match.end()
    if pos < len(spec):
        parts.append(Literal(spec[pos:]))
    if not any(isinstance(p, Field) for p in parts):
        raise FormatError(f"{spec!r} has no {{}} field -- use 'text:' for a fixed string")
    return parts


def parse_time(spec: str, codes: dict[str, Code] | None = None) -> list[TimePart]:
    """Split a strftime-style field spec into codes and literal text."""
    codes = TIME_CODES if codes is None else codes
    what = "date" if codes is DATE_CODES else "time"
    parts: list[TimePart] = []
    buffer = ""
    index = 0
    while index < len(spec):
        char = spec[index]
        if char == "%" and index + 1 < len(spec):
            code = spec[index + 1]
            if code not in codes:
                known = ", ".join(f"%{c}" for c in codes)
                raise FormatError(f"unknown {what} code %{code} -- supported: {known}")
            if buffer:
                parts.append(TimePart(None, buffer))
                buffer = ""
            if code == "%":
                buffer = "%"
            else:
                parts.append(TimePart(code))
            index += 2
            continue
        buffer += char
        index += 1
    if buffer:
        parts.append(TimePart(None, buffer))
    return parts


def is_time_spec(spec: str) -> bool:
    """Does this format use strftime codes?

    Only the *field* is inspected.  A percent sign in the surrounding literal
    text is ordinary punctuation -- ``{:.0f}%`` renders a battery percentage and
    has nothing to do with strftime.
    """
    try:
        parts = parse(spec)
    except FormatError:
        return False
    return any(isinstance(part, Field) and "%" in part.spec for part in parts)


def _strftime_parts(spec: str, value_type: Type) -> tuple[list[TimePart], dict[str, Code]]:
    """A TIME/DATE spec's field, parsed against the code table for its type."""
    codes = DATE_CODES if value_type is Type.DATE else TIME_CODES
    return parse_time(strip_braces(spec), codes), codes


def strip_braces(spec: str) -> str:
    parts = parse(spec)
    for part in parts:
        if isinstance(part, Field):
            return part.spec
    return spec


def _numeric_spec(spec: str) -> tuple[str, str, str | None]:
    """A non-empty numeric field spec as ``(kind, flags, precision)``.

    Shared by `_emit_numeric` and `_render_numeric_field`, so the device and
    the preview accept exactly the same specs and read them the same way.
    """
    m = _NUMERIC_SPEC_RE.match(spec)
    if not m:
        raise FormatError(
            f"{'{'}:{spec}{'}'} is not a supported format -- use {{:d}}, {{:02d}}, {{:.1f}} or {{}}"
        )
    flags = f"{'0' if m.group('zero') else ''}{m.group('width') or ''}"
    return m.group("kind"), flags, m.group("precision")


# --------------------------------------------------------------------------
# Monkey C emission


def emit(spec: str, value_code: str, value_type: Type, *, clock: str = "clock",
         settings: str = "settings", date: str = "date",
         date_short: str = "dateShort") -> str:
    """Compile a format spec to a Monkey C String expression."""
    if value_type is Type.DATE or is_time_spec(spec):
        readers = Readers(clock, settings, date, date_short)
        parts, codes = _strftime_parts(spec, value_type)
        pieces = [_quote(part.text) if part.code is None else codes[part.code].emit(readers)
                  for part in parts]
        return " + ".join(pieces) if pieces else '""'

    pieces = []
    for part in parse(spec):
        if isinstance(part, Literal):
            pieces.append(_quote(part.text))
        else:
            pieces.append(_emit_numeric(part.spec, value_code, value_type))
    return " + ".join(pieces)


def _emit_numeric(spec: str, value_code: str, value_type: Type) -> str:
    if spec == "":
        return f"{value_code}.toString()"
    kind, flags, precision = _numeric_spec(spec)
    if kind == "s":
        return f"{value_code}.toString()"
    if kind == "d":
        if value_type is Type.FLOAT:
            value_code = f"{value_code}.toNumber()"
        return f'{value_code}.format("%{flags}d")'
    return f'{value_code}.format("%{flags}.{precision or 1}f")'


def extra_paths(spec: str, value_type: Type) -> tuple[str, ...]:
    """Extra `wfb.catalog.CATALOG` paths a strftime spec's own codes need
    read, beyond the value's own reader -- ``("date.weekday",)`` for a DATE
    spec using ``%m`` (whose Number month only exists under the
    `date_short` reader), ``("device.is_24_hour",)`` for a TIME spec using
    ``%h``, ``()`` otherwise.  Read off the same `Code` rows `emit`
    compiles, so an element's generated method and the parameter list
    `wfb.emit.monkeyc.readplan.ReadPlan` supplies it cannot drift apart.
    """
    parts, codes = _strftime_parts(spec, value_type)
    paths = (codes[part.code].extra_path for part in parts if part.code is not None)
    return tuple(dict.fromkeys(path for path in paths if path is not None))


def _quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# --------------------------------------------------------------------------
# host-side rendering: what `wfb preview` shows


def render(spec: str, value, value_type: Type, values: dict | None = None) -> str:
    """The host-side rendering of ``spec`` for ``value`` -- what `wfb preview`
    draws in place of the Monkey C `emit` produces for the same declaration.

    Walks the same code tables and spec parsing as `emit`, which is what
    keeps this answer and the device's from disagreeing: `{:d}` on a Float
    must render the same truncated digits here as on the wrist (Python's
    `format(8.5, 'd')` raises where Monkey C's `.toNumber()` truncates).

    ``values`` supplies the clock/date fields, by the same keys
    `wfb.preview.SAMPLE` uses: ``time.hour``, ``time.minute``, ``time.second``,
    ``device.is_24_hour``, ``date.day_of_week``, ``date.day``, ``date.month``,
    ``date.month_number``, ``date.year`` -- read only when ``value_type`` is
    TIME or DATE, so a numeric caller may omit it.

    An unparseable numeric spec raises `FormatError`, the same as `emit`,
    rather than falling back to `str(value)`: every spec reaching here has
    already passed `Builder._check_format`, and a fallback would let a
    preview show something the device never would.
    """
    values = values or {}
    if value_type in (Type.DATE, Type.TIME):
        parts, codes = _strftime_parts(spec, value_type)
        return "".join(part.text if part.code is None else codes[part.code].render(values)
                       for part in parts)
    return "".join(part.text if isinstance(part, Literal)
                   else _render_numeric_field(part.spec, value)
                   for part in parse(spec))


def _render_numeric_field(spec: str, value) -> str:
    """Mirror `_emit_numeric` field-for-field: `{:d}` on a Float truncates
    toward zero like Monkey C's `.toNumber()` (`math.trunc`, not `round`),
    and a written-out `.0` precision stays zero decimals (the group is the
    truthy *string* `"0"`)."""
    if spec == "":
        return str(value)
    kind, flags, precision = _numeric_spec(spec)
    if kind == "s":
        return str(value)
    if kind == "d":
        return format(math.trunc(value), f"{flags}d")
    return format(float(value), f"{flags}.{precision or 1}f")


# --------------------------------------------------------------------------
# static analysis: widest rendering, and the glyph set


def widest(spec: str, source: Source | None, value_type: Type,
           scale: float = 1.0) -> str:
    """The widest string this binding can plausibly render.

    Used by the text-overflow lint and to derive a font's glyph set.  Digit
    counts come from the source's real range where one is known, and fall back
    to a stated assumption otherwise -- an over-estimate here costs a spurious
    warning, an under-estimate costs a clipped face on the wrist.
    """
    if value_type is Type.DATE or is_time_spec(spec):
        parts, codes = _strftime_parts(spec, value_type)
        return "".join(part.text if part.code is None else codes[part.code].widest
                       for part in parts)

    out = ""
    for part in parse(spec):
        if isinstance(part, Literal):
            out += part.text
            continue
        m = _NUMERIC_SPEC_RE.match(part.spec) if part.spec else None
        digits = _max_digits(source, scale)
        if m and m.group("kind") == "f":
            precision = int(m.group("precision") or 1)
            # A zero precision prints no decimal point at all, so counting one
            # here over-estimates the width by a character.
            out += "8" * digits + ("." + "8" * precision if precision else "")
        else:
            width = int(m.group("width")) if m and m.group("width") else 0
            out += "8" * max(digits, width)
    return out


#: Known upper bounds, so the overflow lint is exact rather than guessed.
_SOURCE_DIGITS: dict[str, int] = {
    "activity.steps": 5,
    "activity.step_goal": 5,
    "activity.calories": 5,
    "activity.distance": 7,
    "activity.floors_climbed": 3,
    "activity.floors_climbed_goal": 3,
    "activity.move_bar_level": 1,
    "activity.active_minutes_week": 4,
    "activity.active_minutes_week_goal": 4,
    "heart_rate.current": 3,
    "system.battery": 3,
    "system.battery_in_days": 3,
    "device.notification_count": 2,
    "device.alarm_count": 2,
    "time.hour": 2,
    "time.minute": 2,
    "time.second": 2,
}

#: Used when the bound source has no documented range.
DEFAULT_DIGITS = 5


def _max_digits(source: Source | None, scale: float = 1.0) -> int:
    """Digits before the decimal point, after any constant scaling.

    ``activity.steps / 1000.0`` cannot reach five digits, and treating it as if
    it could makes the overflow lint warn about text that will never appear.
    """
    digits = DEFAULT_DIGITS if source is None else _SOURCE_DIGITS.get(source.path, DEFAULT_DIGITS)
    if scale and scale != 1.0:
        digits = max(1, digits - max(0, round(math.log10(1.0 / scale))))
    return digits


def digits_are_known(source: Source | None) -> bool:
    return source is not None and source.path in _SOURCE_DIGITS


def glyphs(spec: str, source: Source | None, value_type: Type,
           scale: float = 1.0) -> set[str]:
    """Every character this binding can render -- the font's required subset."""
    out = set(widest(spec, source, value_type, scale))
    if value_type is Type.DATE:
        # The weekday and month are localised strings chosen by the firmware, so
        # the full alphabet has to be present -- a custom font subset that
        # carried only "Wed" and "Sep" would drop glyphs on most days of the year.
        out |= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        out |= set("abcdefghijklmnopqrstuvwxyz")
        out |= set("0123456789 ")
        return out

    out |= set("0123456789")
    if is_time_spec(spec):
        if "%p" in spec:
            out |= set("AMP")
    else:
        for part in parse(spec):
            if isinstance(part, Field):
                out.add("-")  # a negative value is always possible
                if part.spec.endswith("f"):
                    out.add(".")
    return out
