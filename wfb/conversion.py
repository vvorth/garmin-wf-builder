"""Unit conversion for a `text` element's `units:` (ADR 0005 §4).

A source's value arrives in the SDK's own unit -- centimetres, metres, °C,
m/s -- whatever the wearer chose in the watch's settings.  `units:` converts
it to the unit the wearer asked for: `auto` follows `DeviceSettings` at
runtime, `metric`/`statute` fix one system at build time.

The conversion is not a second code path.  The builder rewrites the bound
value into an ordinary expression over the source and one
`device.<quantity>_units` setting (:func:`converted_text`), then compiles
it like any other `value:`, so null guards, the read plan, permissions and
the preview all treat it the way they treat an expression the author wrote.

A *quantity* is decided per source (`Source.quantity`), not from the unit
string: `complication.altitude` and `complication.weekly_run_distance` are
both in metres, but one is an elevation (m/ft) and the other a distance
(km/mi).

Pace (min/km, min/mi) converts m/s to *seconds* per km or mile -- the
reciprocal of a speed, guarded so a speed of 0 reads 0 rather than dividing
by it -- for a duration `format:` (``{:%-M:%S}``) to show as ``4:30``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .catalog import Source

#: `units:`'s values.
SYSTEMS = ("auto", "metric", "statute")


@dataclass(frozen=True)
class Display:
    """One displayed unit: ``value * factor + offset``, labelled ``label``
    -- or ``factor / value`` when `reciprocal` (a pace from a speed)."""

    label: str
    factor: float
    offset: float = 0.0
    reciprocal: bool = False


@dataclass(frozen=True)
class Conversion:
    #: The `wfb.catalog` path of the `DeviceSettings` field that picks the
    #: system at runtime (`System.UNIT_METRIC` 0, `UNIT_STATUTE` 1).
    setting: str
    metric: Display
    statute: Display
    #: Digits before the decimal point either display can reach, for the
    #: overflow lint and a baked font's glyph subset.
    digits: int


_KM_FROM_CM = Display("km", 1 / 100000)
_MI_FROM_CM = Display("mi", 1 / 160934.4)
_KM_FROM_M = Display("km", 1 / 1000)
_MI_FROM_M = Display("mi", 1 / 1609.344)
_METRES = Display("m", 1.0)
_FEET = Display("ft", 1 / 0.3048)
_CELSIUS = Display("°C", 1.0)
_FAHRENHEIT = Display("°F", 1.8, 32.0)
_KMH = Display("km/h", 3.6)
_MPH = Display("mph", 3600 / 1609.344)
_PER_KM = Display("/km", 1000.0, reciprocal=True)
_PER_MI = Display("/mi", 1609.344, reciprocal=True)

#: ``(quantity, the source's own unit)`` -> how to display it.
CONVERSIONS: dict[tuple[str, str], Conversion] = {
    ("distance", "cm"): Conversion("device.distance_units", _KM_FROM_CM, _MI_FROM_CM, 3),
    ("distance", "meters"): Conversion("device.distance_units", _KM_FROM_M, _MI_FROM_M, 4),
    ("elevation", "m"): Conversion("device.elevation_units", _METRES, _FEET, 5),
    ("elevation", "meters"): Conversion("device.elevation_units", _METRES, _FEET, 5),
    ("temperature", "celsius"): Conversion("device.temperature_units", _CELSIUS, _FAHRENHEIT, 3),
    ("temperature", "degrees Celsius"): Conversion(
        "device.temperature_units", _CELSIUS, _FAHRENHEIT, 3),
    ("speed", "m/s"): Conversion("device.distance_units", _KMH, _MPH, 3),
    # Seconds per km or mile: its digits are a duration format's to count.
    ("pace", "meters/second"): Conversion("device.pace_units", _PER_KM, _PER_MI, 5),
}

#: Seconds in one of a catalogue unit, for a duration `format:` over a bare
#: source stated in something else (`wfb.kinds.text._in_seconds`).
SECONDS_PER_UNIT: dict[str, int] = {
    "seconds": 1,
    "seconds since local midnight": 1,
    "minutes": 60,
    "hours": 3600,
    "days": 86400,
}


def conversion_for(source: "Source | None") -> Conversion | None:
    """The conversion a `wfb.catalog.Source` takes, or `None` when it has no
    quantity `units:` knows."""
    if source is None or source.quantity is None or source.unit is None:
        return None
    return CONVERSIONS.get((source.quantity, source.unit))


def _literal(number: float) -> str:
    """A float literal the expression language parses back exactly: the
    shortest round-tripping digits, never in exponent form (`1e-05`),
    which the expression grammar has no spelling for."""
    text = format(Decimal(repr(float(number))), "f")
    return text if "." in text else text + ".0"


def _scaled(path: str, display: Display) -> str:
    if display.reciprocal:
        return f"({path} > 0 ? {_literal(display.factor)} / {path} : 0.0)"
    text = path if display.factor == 1.0 else f"{path} * {_literal(display.factor)}"
    if display.offset:
        text = f"{text} + {_literal(display.offset)}"
    return text


def converted_text(path: str, conversion: Conversion, system: str) -> str:
    """The expression text `value: <path>` becomes under `units: <system>`.

    `auto` chooses per frame on the setting (1 is `System.UNIT_STATUTE`);
    `metric`/`statute` fix the display at build time, with no settings read.
    """
    if system == "metric":
        return _scaled(path, conversion.metric)
    if system == "statute":
        return _scaled(path, conversion.statute)
    return (f"{conversion.setting} == 1 ? {_scaled(path, conversion.statute)} "
            f": {_scaled(path, conversion.metric)}")


def label_text(conversion: Conversion, system: str) -> str:
    """The expression text `format:`'s `{unit}` field renders."""
    if system == "metric":
        return f'"{conversion.metric.label}"'
    if system == "statute":
        return f'"{conversion.statute.label}"'
    return (f'{conversion.setting} == 1 ? "{conversion.statute.label}" '
            f': "{conversion.metric.label}"')


def labels(conversion: Conversion, system: str) -> tuple[str, ...]:
    """Every label `{unit}` can render under ``system``."""
    if system == "metric":
        return (conversion.metric.label,)
    if system == "statute":
        return (conversion.statute.label,)
    return (conversion.metric.label, conversion.statute.label)
