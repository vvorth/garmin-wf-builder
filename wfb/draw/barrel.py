"""The barrel's arithmetic, transcribed from `runtime-lib/*.mc`.

The evaluator computes what a barrel call draws with these functions, so the
preview draws what the watch draws by construction.  Each is a
line-for-line transcription of the Monkey C it names, including Monkey C's
own number semantics (`toNumber` truncates toward zero, `%` takes the
dividend's sign); `tests/test_draw_barrel.py` checks the source still says
what is transcribed, and sweeps each against an independent model of the
pixels it should cover.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any


def to_number(x: float) -> int:
    """Monkey C `Float.toNumber`: truncates toward zero."""
    return int(x)


def mc_mod(a: int, b: int) -> int:
    """Monkey C `%` on `Number`s: the result takes the dividend's sign."""
    return int(math.fmod(a, b))


def round_away(degrees: float) -> int:
    """`WfbArc.roundAway`: half away from zero."""
    return to_number(degrees - 0.5) if degrees < 0.0 else to_number(degrees + 0.5)


def draw_span(start_degrees: float, sweep_degrees: float) -> tuple[int, int, bool] | None:
    """`WfbArc.drawSpan`: the `dc.drawArc` call it makes, as ``(start, end,
    clockwise)`` in Garmin's degrees (counter-clockwise from 3 o'clock), or
    `None` when it makes none.  The radius check (`radius <= 0`) is the
    caller's."""
    sweep = round_away(sweep_degrees)
    if sweep == 0:
        return None
    if sweep > 360:
        sweep = 360
    if sweep < -360:
        sweep = -360
    start = mc_mod(round_away(start_degrees), 360)
    if start < 0:
        start += 360
    end = mc_mod(start - sweep, 360)
    if end < 0:
        end += 360
    return start, end, sweep > 0


def draw_progress(start_degrees: float, sweep_degrees: float,
                  fraction: float) -> tuple[int, int, bool] | None:
    """`WfbArc.drawProgress`: ``fraction`` of the sweep through
    `draw_span`, nothing at or below zero, the whole sweep above one."""
    if fraction <= 0.0:
        return None
    swept = sweep_degrees * (1.0 if fraction > 1.0 else fraction)
    return draw_span(start_degrees, swept)


def pillow_arc(call: tuple[int, int, bool]) -> tuple[int, int]:
    """A `dc.drawArc(start, end, direction)` call as Pillow's
    ``(start, end)``: Pillow measures clockwise from 3 o'clock and always
    draws clockwise from its start to its end.  Garmin's start equal to
    its end is the full circle."""
    start, end, clockwise = call
    if start == end:
        return -start, -start + 360
    a, b = (-start, -end) if clockwise else (-end, -start)
    while b <= a:
        b += 360
    return a, b


def rotated_x(x: float, y: float, cx: float, sin: float, cos: float) -> int:
    """`WfbGeom.rotatedX`: the anchor turned clockwise about ``cx``, rounded
    half up."""
    return to_number(math.floor(cx + x * cos - y * sin + 0.5))


def rotated_y(x: float, y: float, cy: float, sin: float, cos: float) -> int:
    """`WfbGeom.rotatedY`, the same for ``y``."""
    return to_number(math.floor(cy + x * sin + y * cos + 0.5))


def mc_round(x: float) -> float:
    """`Math.round`: half up, a whole `Float` the caller then `toNumber`s."""
    return float(math.floor(x + 0.5))


def clamp(value: float, lo: float, hi: float) -> float:
    """`WfbMath.clamp`."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def percent(value: float, goal: float) -> float:
    """`WfbMath.percent`: ``value`` as a percentage of ``goal``, 0 to 100;
    0 for a goal at or below zero."""
    if goal <= 0:
        return 0.0
    pct = 100.0 * float(value) / float(goal)
    return clamp(pct, 0.0, 100.0)


def share(reading: float, scale: tuple[float, float]) -> float:
    """`WfbScale.share`: how full a gauge on ``scale`` is for ``reading``,
    0.0 to 1.0."""
    low = float(scale[0])
    full = (float(reading) - low) / (float(scale[1]) - low)
    if full < 0.0:
        return 0.0
    return 1.0 if full > 1.0 else full


def scale_fraction(c: Any, scale: tuple[float, float]) -> float | None:
    """`WfbScale.fraction`: `share` of the pulled complication ``c``'s
    numeric `value` (a count the device scaled to thousands, unit "K",
    multiplied back), null for any other."""
    value = c.value
    if value is None or isinstance(value, (str, bool)) or not isinstance(value, (int, float)):
        return None
    reading = float(value)
    if not isinstance(value, int) and getattr(c, "unit", None) == "K":
        reading = reading * 1000
    return share(reading, scale)


#: The functions a program's `Call` may name, by their Monkey C name.
CALLS: dict[str, Callable[..., Any]] = {
    "Math.sin": math.sin,
    "Math.cos": math.cos,
    "Math.round": mc_round,
    "WfbMath.clamp": clamp,
    "WfbMath.percent": percent,
    "WfbScale.share": share,
    "WfbScale.fraction": scale_fraction,
    "WfbGeom.rotatedX": rotated_x,
    "WfbGeom.rotatedY": rotated_y,
}
