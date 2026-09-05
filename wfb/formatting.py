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

import re
from dataclasses import dataclass

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


#: strftime codes for a **date**, with the widest string each can produce.
#:
#: The widths assume English: the weekday and month arrive from the firmware as
#: localised strings, so a longer language makes these under-estimates and the
#: overflow lint correspondingly optimistic.  Three characters is what
#: ``FORMAT_MEDIUM`` yields in English, which is the common case.
DATE_CODES: dict[str, tuple[str, str]] = {
    "a": ("abbreviated weekday, e.g. Thu", "Wed"),
    "d": ("day of the month, zero-padded", "30"),
    "e": ("day of the month, unpadded", "30"),
    "b": ("abbreviated month, e.g. Sep", "Sep"),
    "m": ("month number, zero-padded", "12"),
    "Y": ("four-digit year", "2026"),
    "y": ("two-digit year", "26"),
    "%": ("a literal percent sign", "%"),
}

#: strftime codes we implement, with the widest string each can produce.
TIME_CODES: dict[str, tuple[str, str]] = {
    "H": ("hour, 24-hour, zero-padded", "23"),
    "I": ("hour, 12-hour, zero-padded", "12"),
    "l": ("hour, 12-hour, unpadded", "12"),
    "h": ("hour, following the device's 12/24-hour setting", "23"),
    "M": ("minute, zero-padded", "59"),
    "S": ("second, zero-padded", "59"),
    "p": ("AM or PM", "AM"),
    "%": ("a literal percent sign", "%"),
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


def parse_time(spec: str, codes: dict[str, tuple[str, str]] | None = None) -> list[TimePart]:
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


# --------------------------------------------------------------------------
# Monkey C emission


def emit(spec: str, value_code: str, value_type: Type, *, clock: str = "clock",
         settings: str = "settings", date: str = "date") -> str:
    """Compile a format spec to a Monkey C String expression."""
    if value_type is Type.DATE:
        return _emit_date(spec, date=date)
    if is_time_spec(spec):
        return _emit_time(spec, clock=clock, settings=settings)

    pieces: list[str] = []
    for part in parse(spec):
        if isinstance(part, Literal):
            pieces.append(_quote(part.text))
        else:
            pieces.append(_emit_numeric(part.spec, value_code, value_type))
    return " + ".join(pieces)


def _emit_numeric(spec: str, value_code: str, value_type: Type) -> str:
    if spec == "":
        return f"{value_code}.toString()"
    m = _NUMERIC_SPEC_RE.match(spec)
    if not m:
        raise FormatError(
            f"{'{'}:{spec}{'}'} is not a supported format -- use {{:d}}, {{:02d}}, {{:.1f}} or {{}}"
        )
    kind = m.group("kind")
    if kind == "s":
        return f"{value_code}.toString()"
    zero, width, precision = m.group("zero"), m.group("width"), m.group("precision")
    if kind == "d":
        if value_type is Type.FLOAT:
            value_code = f"{value_code}.toNumber()"
        flags = f"{'0' if zero else ''}{width or ''}"
        return f'{value_code}.format("%{flags}d")'
    # float
    flags = f"{'0' if zero else ''}{width or ''}"
    return f'{value_code}.format("%{flags}.{precision or 1}f")'


def _emit_time(spec: str, *, clock: str, settings: str) -> str:
    pieces: list[str] = []
    for part in parse_time(_strip_braces(spec)):
        if part.code is None:
            pieces.append(_quote(part.text))
        elif part.code == "H":
            pieces.append(f'{clock}.hour.format("%02d")')
        elif part.code == "I":
            pieces.append(f"WfbTime.hour12({clock}.hour).format(\"%02d\")")
        elif part.code == "l":
            pieces.append(f"WfbTime.hour12({clock}.hour).format(\"%d\")")
        elif part.code == "h":
            pieces.append(f"WfbTime.displayHour({clock}.hour, {settings}.is24Hour)")
        elif part.code == "M":
            pieces.append(f'{clock}.min.format("%02d")')
        elif part.code == "S":
            pieces.append(f'{clock}.sec.format("%02d")')
        elif part.code == "p":
            pieces.append(f"WfbTime.meridiem({clock}.hour)")
    return " + ".join(pieces) if pieces else '""'


def _emit_date(spec: str, *, date: str) -> str:
    """Compile a date spec.

    ``day_of_week`` and ``month`` are already Strings under ``FORMAT_MEDIUM``, so
    they need no conversion; the numeric fields do.
    """
    pieces: list[str] = []
    for part in parse_time(_strip_braces(spec), DATE_CODES):
        if part.code is None:
            pieces.append(_quote(part.text))
        elif part.code == "a":
            pieces.append(f"{date}.day_of_week")
        elif part.code == "d":
            pieces.append(f'{date}.day.format("%02d")')
        elif part.code == "e":
            pieces.append(f'{date}.day.format("%d")')
        elif part.code == "b":
            pieces.append(f"{date}.month")
        elif part.code == "m":
            pieces.append(f'{date}.month.format("%02d")')
        elif part.code == "Y":
            pieces.append(f'{date}.year.format("%04d")')
        elif part.code == "y":
            pieces.append(f"({date}.year % 100).format(\"%02d\")")
    return " + ".join(pieces) if pieces else '""'


def _strip_braces(spec: str) -> str:
    parts = parse(spec)
    for part in parts:
        if isinstance(part, Field):
            return part.spec
    return spec


def _quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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
    if value_type is Type.DATE:
        out = ""
        for part in parse_time(_strip_braces(spec), DATE_CODES):
            out += part.text if part.code is None else DATE_CODES[part.code][1]
        return out

    if is_time_spec(spec):
        out = ""
        for part in parse_time(_strip_braces(spec)):
            out += part.text if part.code is None else TIME_CODES[part.code][1]
        return out

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
        import math

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

    if is_time_spec(spec):
        out |= set("0123456789")
        if "%p" in spec:
            out |= set("AMP")
    else:
        out |= set("0123456789")
        for part in parse(spec):
            if isinstance(part, Field) and part.spec.endswith("f"):
                out.add(".")
            if isinstance(part, Field):
                out.add("-")  # a negative value is always possible
    return out
