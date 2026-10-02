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
from collections.abc import Callable, Sequence
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


def hour_angle(hour: int, minute: int, second: int) -> float:
    """`WfbHands.hourAngle`, in radians clockwise from 12: half a degree a
    minute.  Python's degrees-to-radians conversion rather than Monkey C's
    `Math.PI / 360.0` constant, kept at the expression the preview has
    always used so its pixels never move (`tests/test_hand_angles.py` checks
    the `.mc` return)."""
    return math.radians(((hour % 12) * 60 + minute) * 0.5)


def minute_angle(hour: int, minute: int, second: int) -> float:
    """`WfbHands.minuteAngle`: 6 degrees a minute."""
    return math.radians(minute * 6.0)


def second_angle(hour: int, minute: int, second: int) -> float:
    """`WfbHands.secondAngle`: 6 degrees a second."""
    return math.radians(second * 6.0)


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


#: Each hand's angle twin, by hand name.
HAND_ANGLES: dict[str, Callable[[int, int, int], float]] = {
    "hour": hour_angle, "minute": minute_angle, "second": second_angle,
}


def _whole_div(a: int, b: int) -> int:
    """Monkey C `/` on two `Number`s: truncates toward zero."""
    quotient = abs(a) // abs(b)
    return quotient if (a < 0) == (b < 0) else -quotient


def _span(lo: float, hi: float) -> float:
    span = hi - lo
    return 1.0 if span <= 0.0 else span


def series_line(x: int, y: int, w: int, h: int, values: Sequence[float | None], lo: float,
                hi: float) -> list[tuple[int, int, int, int]]:
    """`WfbSeries.drawLine`'s `dc.drawLine` calls, as ``(x1, y1, x2, y2)``:
    a segment between each two present neighbours, none across a gap."""
    n = len(values)
    if n < 2:
        return []
    span = _span(lo, hi)
    out: list[tuple[int, int, int, int]] = []
    have = False
    px = py = 0
    for i, v in enumerate(values):
        if v is None:
            have = False
            continue
        cx = x + _whole_div(i * w, n - 1)
        cy = y + h - to_number((v - lo) * h / span)
        if have:
            out.append((px, py, cx, cy))
        px, py, have = cx, cy, True
    return out


def series_area(x: int, y: int, w: int, h: int, values: Sequence[float | None], lo: float,
                hi: float) -> list[list[tuple[int, int]]]:
    """`WfbSeries.drawArea`'s `dc.fillPolygon` calls: one per run of two or
    more present samples, closed by its own two bottom corners."""
    n = len(values)
    if n < 2:
        return []
    span = _span(lo, hi)
    out: list[list[tuple[int, int]]] = []
    i = 0
    while i < n:
        if values[i] is None:
            i += 1
            continue
        start = end = i
        while end < n and values[end] is not None:
            end += 1
        if end - start >= 2:
            run: list[tuple[int, int]] = []
            for j in range(start, end):
                v = values[j]
                cx = x + _whole_div(j * w, n - 1)
                cy = y + h - to_number((v - lo) * h / span) if v is not None else y + h
                run.append((cx, cy))
            run.append((x + _whole_div((end - 1) * w, n - 1), y + h))
            run.append((x + _whole_div(start * w, n - 1), y + h))
            out.append(run)
        i = end
    return out


def series_bars(x: int, y: int, w: int, h: int, bar_width: int, values: Sequence[float | None],
                lo: float, hi: float) -> list[tuple[int, int, int, int]]:
    """`WfbSeries.drawBars`'s `dc.fillRectangle` calls, as ``(x, y, w, h)``:
    one per present sample, `barWidth` centred in its whole-pixel slot, at
    least 1 px tall."""
    n = len(values)
    if n < 1:
        return []
    span = _span(lo, hi)
    pitch = _whole_div(w, n)
    out: list[tuple[int, int, int, int]] = []
    for i, v in enumerate(values):
        if v is None:
            continue
        bar_height = to_number((v - lo) * h / span)
        if bar_height < 1:
            bar_height = 1
        out.append((x + i * pitch + _whole_div(pitch - bar_width, 2), y + h - bar_height,
                    bar_width, bar_height))
    return out


def auto_min(values: Sequence[float | None]) -> float:
    """`WfbSeries.autoMin`: the least present sample, 0.0 with none."""
    present = [v for v in values if v is not None]
    return min(present) if present else 0.0


def auto_max(values: Sequence[float | None]) -> float:
    """`WfbSeries.autoMax`: the greatest present sample, 0.0 with none."""
    present = [v for v in values if v is not None]
    return max(present) if present else 0.0
