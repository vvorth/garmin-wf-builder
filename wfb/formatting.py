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

The same codes on a **Number or Float** read the value as a number of
*seconds*: a duration (a race predictor, recovery time, a pace in seconds per
km) or a time of day (sunrise's "seconds since local midnight").  The largest
unit a spec uses carries the whole total, so ``%M:%S`` on 3900 s is ``65:00``,
and every smaller unit wraps at the next one up.  A ``-`` flag drops the
zero-padding (``%-M:%S`` is ``4:30``).  ``%h``/``%I``/``%l``/``%p`` read a
time of day, wrapping at 24 hours; a spec without them is a duration, and a
negative one gets a leading ``-`` (`DURATION_CODES`).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable, NamedTuple

from .catalog import Source, Type

_FIELD_RE = re.compile(r"\{(?:(?P<unit>unit)|:(?P<spec>[^}]*))?\}")
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
class UnitField:
    """`{unit}`: the label of the unit a `units:` conversion displays in
    ("km" or "mi"), rendered from a compiled expression the caller passes."""


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
    time.  ``%%`` never reaches either (:func:`parse_time` turns it into
    literal text); its row implements both anyway, so every row does.
    """

    description: str
    #: The widest string the code can produce -- for the overflow lint and a
    #: subsetted font's glyph set.
    widest: str
    emit: Callable[[Readers], str]
    render: Callable[[dict[str, Any]], str]
    #: A `wfb.catalog.CATALOG` path the code reads beyond the value's own
    #: reader -- see :func:`extra_paths`.
    extra_path: str | None = None


_PERCENT = Code("a literal percent sign", "%", lambda r: '"%"', lambda v: "%")


def _hour(values: dict[str, Any]) -> int:
    return int(values.get("time.hour", 10))


def _hour12(values: dict[str, Any]) -> int:
    return (_hour(values) % 12) or 12


def _day(values: dict[str, Any]) -> int:
    return int(values.get("date.day", 3))


def _year(values: dict[str, Any]) -> int:
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


@dataclass(frozen=True)
class DurationCode:
    """One strftime code read off a number of seconds (`DURATION_CODES`).

    `emit` and `render` get the value's code (or its truncated absolute
    value, for `render`) and whether this code *leads* -- is the spec's
    largest unit, carrying the whole total rather than wrapping.  They mirror
    `WfbTime.durationPart` (runtime-lib/WfbTime.mc) and must agree for every
    input, the same contract `Code` keeps.
    """

    description: str
    #: Seconds per unit, which ranks the codes: the largest `unit` in a spec
    #: leads (`leading_units`).
    unit: int
    #: The widest rendering when the code leads (no wrap to bound it) and
    #: when it wraps.
    widest_leading: str
    widest_wrapped: str
    emit: Callable[[str, Readers, bool], str]
    render: Callable[[int, dict[str, Any], bool], str]
    #: A time-of-day code: always wraps at 24 hours, and a spec using one
    #: carries no sign.
    clock: bool = False
    extra_path: str | None = None


def _part_code(value_code: str, unit: int, wrap: int) -> str:
    """`WfbTime.durationPart`: ``|value|`` in whole ``unit``s, wrapped at
    ``wrap`` of them (0: not wrapped)."""
    return f"WfbTime.durationPart({value_code}, {unit}, {wrap})"


def _part(seconds: int, unit: int, wrap: int) -> int:
    """`_part_code`'s host twin, over an already truncated, non-negative
    ``seconds``."""
    whole = seconds // unit
    return whole % wrap if wrap else whole


def _field(unit: int, wrap: int, pad: bool, what: str, widest_leading: str) -> DurationCode:
    """A plain count of ``unit``s: the total when it leads, wrapped at
    ``wrap`` otherwise."""
    fmt = "%02d" if pad else "%d"
    return DurationCode(
        f"{what}{'' if pad else ', unpadded'} -- the whole total when it is the largest unit",
        unit, widest_leading, "59" if wrap == 60 else "23",
        lambda v, r, lead: f'{_part_code(v, unit, 0 if lead else wrap)}.format("{fmt}")',
        lambda n, values, lead: format(_part(n, unit, 0 if lead else wrap), fmt[1:]),
    )


def _clock_hour_code(value_code: str) -> str:
    return _part_code(value_code, 3600, 24)


def _clock_hour(seconds: int) -> int:
    return _part(seconds, 3600, 24)


#: strftime codes for a **Number or Float of seconds**: a duration, or a time
#: of day.  ``-H``/``-M``/``-S`` are the unpadded forms (the glibc ``-``
#: flag).  A leading H or M is assumed to stay within two digits and a
#: leading S within `DEFAULT_DIGITS` -- nothing bounds a total, so these are
#: stated assumptions, the same kind `_max_digits` makes.
DURATION_CODES: dict[str, DurationCode] = {
    "H": _field(3600, 24, True, "hours", "88"),
    "-H": _field(3600, 24, False, "hours", "88"),
    "M": _field(60, 60, True, "minutes", "88"),
    "-M": _field(60, 60, False, "minutes", "88"),
    "S": _field(1, 60, True, "seconds", "88888"),
    "-S": _field(1, 60, False, "seconds", "88888"),
    "h": DurationCode(
        "hour of the day, following the device's 12/24-hour setting", 3600, "23", "23",
        lambda v, r, lead: f"WfbTime.displayHour({_clock_hour_code(v)}, {r.settings}.is24Hour)",
        lambda n, values, lead: (f"{_clock_hour(n):02d}" if bool(values.get("device.is_24_hour", True))
                                 else f"{(_clock_hour(n) % 12) or 12:d}"),
        clock=True, extra_path="device.is_24_hour"),
    "I": DurationCode(
        "hour of the day, 12-hour, zero-padded", 3600, "12", "12",
        lambda v, r, lead: f'WfbTime.hour12({_clock_hour_code(v)}).format("%02d")',
        lambda n, values, lead: f"{(_clock_hour(n) % 12) or 12:02d}",
        clock=True),
    "l": DurationCode(
        "hour of the day, 12-hour, unpadded", 3600, "12", "12",
        lambda v, r, lead: f'WfbTime.hour12({_clock_hour_code(v)}).format("%d")',
        lambda n, values, lead: f"{(_clock_hour(n) % 12) or 12:d}",
        clock=True),
    "p": DurationCode(
        "AM or PM of the time of day", 3600, "AM", "AM",
        lambda v, r, lead: f"WfbTime.meridiem({_clock_hour_code(v)})",
        lambda n, values, lead: "AM" if _clock_hour(n) < 12 else "PM",
        clock=True),
    "%": DurationCode("a literal percent sign", 0, "%", "%",
                      lambda v, r, lead: '"%"', lambda n, values, lead: "%"),
}


def parse(spec: str) -> list[Literal | Field | UnitField]:
    """Split a format string into literals and fields."""
    parts: list[Literal | Field | UnitField] = []
    pos = 0
    for match in _FIELD_RE.finditer(spec):
        if match.start() > pos:
            parts.append(Literal(spec[pos:match.start()]))
        parts.append(UnitField() if match.group("unit") else Field(match.group("spec") or ""))
        pos = match.end()
    if pos < len(spec):
        parts.append(Literal(spec[pos:]))
    if not any(isinstance(p, Field) for p in parts):
        raise FormatError(f"{spec!r} has no {{}} field -- use 'text:' for a fixed string")
    return parts


def parse_time(spec: str, codes: dict[str, Code] | dict[str, DurationCode] | None = None,
               ) -> list[TimePart]:
    """Split a strftime-style field spec into codes and literal text.  A
    ``-`` flag (``%-M``) is part of the code it modifies, so it is only
    valid where the table has that flagged key."""
    codes = TIME_CODES if codes is None else codes
    what = {id(DATE_CODES): "date", id(DURATION_CODES): "duration"}.get(id(codes), "time")
    parts: list[TimePart] = []
    buffer = ""
    index = 0
    while index < len(spec):
        char = spec[index]
        if char == "%" and index + 1 < len(spec):
            code = spec[index + 1]
            if code == "-" and index + 2 < len(spec):
                code = spec[index + 1:index + 3]
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
            index += 1 + len(code)
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


def is_duration(spec: str, value_type: Type) -> bool:
    """Is this a duration format: strftime codes on a Number or Float of
    seconds (`DURATION_CODES`)?"""
    return value_type.is_numeric() and is_time_spec(spec)


def _duration_field(spec: str) -> tuple[list[TimePart], int, bool]:
    """A duration field spec's parts, the unit that leads (the largest one
    it uses), and whether it carries a sign (no time-of-day code)."""
    parts = parse_time(spec, DURATION_CODES)
    rows = [DURATION_CODES[part.code] for part in parts if part.code is not None]
    leading = max((row.unit for row in rows), default=0)
    signed = not any(row.clock for row in rows)
    return parts, leading, signed


def _leads(row: DurationCode, leading: int) -> bool:
    return not row.clock and row.unit == leading


def strftime_parts(spec: str, value_type: Type) -> tuple[list[TimePart], dict[str, Code]]:
    """A whole TIME/DATE spec as one run of codes and literal text: the text
    around each field kept (``at {:%H:%M} UTC``), every field parsed against
    the code table for its type."""
    codes = DATE_CODES if value_type is Type.DATE else TIME_CODES
    parts: list[TimePart] = []
    for part in parse(spec):
        if isinstance(part, Literal):
            parts.append(TimePart(None, part.text))
        elif isinstance(part, UnitField):
            raise FormatError("{unit} needs 'units:' on the element")
        else:
            parts.extend(parse_time(part.spec, codes))
    return parts, codes


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


def has_unit_field(spec: str) -> bool:
    """Does this format use `{unit}`?"""
    try:
        return any(isinstance(part, UnitField) for part in parse(spec))
    except FormatError:
        return False


def emit(spec: str, value_code: str, value_type: Type, *, clock: str = "clock",
         settings: str = "settings", date: str = "date",
         date_short: str = "dateShort", unit_code: str | None = None) -> str:
    """Compile a format spec to a Monkey C String expression.  ``unit_code``
    is the String expression a `{unit}` field compiles to."""
    if is_duration(spec, value_type):
        return _emit_duration(spec, value_code, Readers(clock, settings, date, date_short),
                              unit_code)
    if value_type is Type.DATE or is_time_spec(spec):
        readers = Readers(clock, settings, date, date_short)
        parts, codes = strftime_parts(spec, value_type)
        pieces = [_quote(part.text) if part.code is None else codes[part.code].emit(readers)
                  for part in parts]
        return " + ".join(pieces) if pieces else '""'

    pieces = []
    for part in parse(spec):
        if isinstance(part, Literal):
            pieces.append(_quote(part.text))
        elif isinstance(part, UnitField):
            if unit_code is None:
                raise FormatError("{unit} needs 'units:' on the element")
            pieces.append(f"({unit_code})")
        else:
            pieces.append(_emit_numeric(part.spec, value_code, value_type))
    return " + ".join(pieces)


def _emit_duration(spec: str, value_code: str, readers: Readers, unit_code: str | None) -> str:
    """A duration spec (`is_duration`): the literal text and `{unit}` around
    the field kept, the field one `DurationCode` per code, led by
    `WfbTime.durationSign` when it carries a sign."""
    pieces = []
    for part in parse(spec):
        if isinstance(part, Literal):
            pieces.append(_quote(part.text))
        elif isinstance(part, UnitField):
            if unit_code is None:
                raise FormatError("{unit} needs 'units:' on the element")
            pieces.append(f"({unit_code})")
        else:
            parts, leading, signed = _duration_field(part.spec)
            if signed:
                pieces.append(f"WfbTime.durationSign({value_code})")
            for time_part in parts:
                if time_part.code is None:
                    pieces.append(_quote(time_part.text))
                else:
                    row = DURATION_CODES[time_part.code]
                    pieces.append(row.emit(value_code, readers, _leads(row, leading)))
    return " + ".join(pieces) if pieces else '""'


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
    table: dict[str, Code] | dict[str, DurationCode]
    if is_duration(spec, value_type):
        table = DURATION_CODES
        parts = [p for field in parse(spec) if isinstance(field, Field)
                 for p in parse_time(field.spec, DURATION_CODES)]
    else:
        parts, table = strftime_parts(spec, value_type)
    paths = (table[part.code].extra_path for part in parts if part.code is not None)
    return tuple(dict.fromkeys(path for path in paths if path is not None))


def _quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# --------------------------------------------------------------------------
# host-side rendering: what `wfb preview` shows


def render(spec: str, value: object, value_type: Type, values: dict[str, Any] | None = None,
           unit_text: str | None = None) -> str:
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
    TIME or DATE, or a duration spec uses ``%h``, so a plain numeric caller
    may omit it.  ``unit_text`` is what a
    `{unit}` field renders.

    An unparseable numeric spec raises `FormatError`, the same as `emit`,
    rather than falling back to `str(value)`: every spec reaching here has
    already passed `Builder.check_format`, and a fallback would let a
    preview show something the device never would.
    """
    values = values or {}
    if is_duration(spec, value_type):
        return _render_duration(spec, value, values, unit_text)
    if value_type in (Type.DATE, Type.TIME):
        parts, codes = strftime_parts(spec, value_type)
        return "".join(part.text if part.code is None else codes[part.code].render(values)
                       for part in parts)
    out = ""
    for part in parse(spec):
        if isinstance(part, Literal):
            out += part.text
        elif isinstance(part, UnitField):
            if unit_text is None:
                raise FormatError("{unit} needs 'units:' on the element")
            out += unit_text
        else:
            out += _render_numeric_field(part.spec, value)
    return out


def _render_duration(spec: str, value: object, values: dict[str, Any],
                     unit_text: str | None) -> str:
    """`_emit_duration`'s host twin: the value truncated toward zero first,
    as `Number.toNumber()`/`Float.toNumber()` do, then split by its
    absolute value, so no `//` or `%` ever sees a negative operand."""
    assert isinstance(value, (int, float)), value
    whole = math.trunc(value)
    out = ""
    for part in parse(spec):
        if isinstance(part, Literal):
            out += part.text
        elif isinstance(part, UnitField):
            if unit_text is None:
                raise FormatError("{unit} needs 'units:' on the element")
            out += unit_text
        else:
            parts, leading, signed = _duration_field(part.spec)
            if signed and whole < 0:
                out += "-"
            for time_part in parts:
                if time_part.code is None:
                    out += time_part.text
                else:
                    row = DURATION_CODES[time_part.code]
                    out += row.render(abs(whole), values, _leads(row, leading))
    return out


def _render_numeric_field(spec: str, value: object) -> str:
    """Mirror `_emit_numeric` field-for-field: `{:d}` on a Float truncates
    toward zero like Monkey C's `.toNumber()` (`math.trunc`, not `round`),
    and a written-out `.0` precision stays zero decimals (the group is the
    truthy *string* `"0"`)."""
    if spec == "":
        return str(value)
    kind, flags, precision = _numeric_spec(spec)
    if kind == "s":
        return str(value)
    # `check_format` only lets a numeric spec reach a Number or Float.
    assert isinstance(value, (int, float)), value
    if kind == "d":
        return format(math.trunc(value), f"{flags}d")
    return format(float(value), f"{flags}.{precision or 1}f")


# --------------------------------------------------------------------------
# static analysis: widest rendering, and the glyph set


def widest(spec: str, source: Source | None, value_type: Type,
           scale: float = 1.0, *, digits: int | None = None, unit_widest: str = "") -> str:
    """The widest string this binding can plausibly render.

    ``digits`` overrides the source-derived digit count (a `units:`
    conversion knows its own display range); ``unit_widest`` is the widest
    label a `{unit}` field can show.

    Used by the text-overflow lint and to derive a font's glyph set.  Digit
    counts come from the source's real range where one is known, and fall back
    to a stated assumption otherwise -- an over-estimate here costs a spurious
    warning, an under-estimate costs a clipped face on the wrist.
    """
    if is_duration(spec, value_type):
        return _widest_duration(spec, unit_widest)
    if value_type is Type.DATE or is_time_spec(spec):
        parts, codes = strftime_parts(spec, value_type)
        return "".join(part.text if part.code is None else codes[part.code].widest
                       for part in parts)

    out = ""
    for part in parse(spec):
        if isinstance(part, Literal):
            out += part.text
            continue
        if isinstance(part, UnitField):
            out += unit_widest
            continue
        m = _NUMERIC_SPEC_RE.match(part.spec) if part.spec else None
        if digits is None:
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


def _widest_duration(spec: str, unit_widest: str) -> str:
    out = ""
    for part in parse(spec):
        if isinstance(part, Literal):
            out += part.text
        elif isinstance(part, UnitField):
            out += unit_widest
        else:
            parts, leading, _ = _duration_field(part.spec)
            for time_part in parts:
                if time_part.code is None:
                    out += time_part.text
                else:
                    row = DURATION_CODES[time_part.code]
                    out += row.widest_leading if _leads(row, leading) else row.widest_wrapped
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
           scale: float = 1.0, *, digits: int | None = None,
           unit_labels: tuple[str, ...] = ()) -> set[str]:
    """Every character this binding can render -- the font's required subset,
    every label a `{unit}` field can show included."""
    out = set(widest(spec, source, value_type, scale, digits=digits))
    for label in unit_labels:
        out |= set(label)
    if value_type is Type.DATE:
        # The weekday and month are localised strings chosen by the firmware, so
        # the full alphabet has to be present -- a custom font subset that
        # carried only "Wed" and "Sep" would drop glyphs on most days of the year.
        out |= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        out |= set("abcdefghijklmnopqrstuvwxyz")
        out |= set("0123456789 ")
        return out

    out |= set("0123456789")
    if is_duration(spec, value_type):
        for part in parse(spec):
            if isinstance(part, Field):
                parts, _, signed = _duration_field(part.spec)
                if signed:
                    out.add("-")
                if any(p.code == "p" for p in parts):
                    out |= set("AMP")
    elif is_time_spec(spec):
        if "%p" in spec:
            out |= set("AMP")
    else:
        for part in parse(spec):
            if isinstance(part, Field):
                out.add("-")  # a negative value is always possible
                if part.spec.endswith("f"):
                    out.add(".")
    return out
