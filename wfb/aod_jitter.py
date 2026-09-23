"""Deterministic per-minute AOD pixel jitter (plan 14 slice 5, `aod: {jitter: ...}`).

Garmin's own guidance (research 11 §1.3, the UX guidelines' "Best Practices"):
"consider moving elements up to four pixels in any direction every minute
while in always-on mode." This module is the *one* place that arithmetic is
written down -- `runtime-lib/WfbJitter.mc` is its Monkey C twin, kept
bit-for-bit identical on purpose (`tests/test_aod_jitter.py::
test_python_matches_the_spot_check_table_for_every_minute` spot-checks the
Python half; a slow test compiles the Monkey C module warning-free -- there
is no simulator here to run it and compare directly).

**The rule this has to satisfy** (plan 14 §5.2, research 11 §1.3): bounded to
``±n`` pixels, deterministic from the minute of day alone (so the host
preview and the device agree with no shared state), and never the same
offset for three or more *consecutive* minutes (Garmin's other AMOLED rule,
research 11 §1.2: "any pixel on longer than 3 minutes" fails the original
Venu's burn-in check) -- **on every axis at once**, not just the pair as a
whole. A straight 1px line (a ring's top/bottom edge, a progress bar, a
text baseline) is exactly the shape the 3-minute rule exists for, and a
line's own lit pixels only care about the shift *along* the line's own
axis: a horizontal line's interior pixels stay lit for as long as ``dy``
alone stays put, whatever ``dx`` does meanwhile (`tests/test_aod_jitter.py`
checks this directly, with plain set arithmetic on a line's own offset
pixel sets, not just that the ``(dx, dy)`` pair as a whole changes).

**A first version failed exactly this way.** A plain raster scan --
``w = 2n+1; dx = (minute % w) - n; dy = ((minute // w) % w) - n`` -- steps
``dx`` by 1 every minute but only advances ``dy`` once every ``w`` minutes,
so a horizontal line's own interior sat lit for up to ``w`` (9, at ``n =
4``) consecutive minutes: "the pair changes every minute" is the wrong
property; each *axis* has to change every minute on its own.

**The sequence, built.** For a cap of ``n`` pixels, the reachable grid is
``(2n + 1) x (2n + 1)`` offsets, ``-n..n`` on each axis, flattened into one
linear index ``cell`` (row-major, ``w`` cells per row) and walked with a
constant stride, using only integer ``%``/``//``:

    w = 2 * n + 1
    stride = 2 * w + 1
    cell = (minute * stride) % (w * w)
    dx = (cell % w) - n
    dy = (cell // w) - n

``stride`` is coprime with ``w * w`` (``w`` is odd, so ``stride = 2w + 1 ==
1 (mod w)``, hence ``gcd(stride, w) == 1`` and therefore ``gcd(stride, w *
w) == 1`` too), so the map ``minute -> cell`` is a bijection over any
``w * w``-minute window: every one of the ``w * w`` offsets is visited
exactly once per period, the same even coverage the raster scan gave the
heatmap, without its per-axis stall. Each step advances `cell` by exactly
``stride``, which in grid terms is +1 column and +2 rows (with the usual
carry when a column wraps past ``w``) -- never +1 and +0, so a horizontal,
vertical *or* 45-degree line all move along their own axis every single
minute, never leaving a line's own interior pixels lit for more than 2
consecutive minutes on any of the three (checked directly, see above).

Pure integer arithmetic throughout (`%`/`//` on two non-negative integers,
truncating exactly like Monkey C's own `%`/`/` do for non-negative
operands), so the host and the device compute bit-identical offsets with no
floating-point rounding to keep in sync.
"""

from __future__ import annotations

#: Garmin's own cap (research 11 §1.3: "up to four pixels").
MAX_JITTER_PX = 4

#: A day's worth of distinct "minute of day" values, `0..1439` -- the same
#: clock `System.getClockTime()` reports on the device (`hour * 60 + min`).
MINUTES_PER_DAY = 1440


def offset(minute_of_day: int, n: int) -> tuple[int, int]:
    """The deterministic ``(dx, dy)`` jitter offset for this minute of day,
    both in ``-n..n`` -- see the module docstring for the sequence and why
    it never sits still for 3+ consecutive minutes **on either axis**.

    ``runtime-lib/WfbJitter.mc``'s `offsetX`/`offsetY` compute the exact
    same two numbers, split into two functions there only because that is
    how every call site (one X coordinate, one Y coordinate) actually wants
    them -- this single Python function returning both is simply the more
    convenient shape for a host caller that always wants the pair together
    (`wfb.preview`, and this module's own tests).
    """
    if not (0 <= minute_of_day < MINUTES_PER_DAY):
        raise ValueError(f"minute_of_day must be 0..{MINUTES_PER_DAY - 1}, got {minute_of_day!r}")
    if not (1 <= n <= MAX_JITTER_PX):
        raise ValueError(f"n must be 1..{MAX_JITTER_PX}, got {n!r}")
    w = 2 * n + 1
    stride = 2 * w + 1
    cell = (minute_of_day * stride) % (w * w)
    dx = (cell % w) - n
    dy = (cell // w) - n
    return dx, dy
