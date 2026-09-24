"""`wfb.layout.HAND_ANGLES` (plan 19 A1): one table holding both halves of
each analog hand's angle rule -- the Monkey C `runtime-lib/WfbHands.mc`
already ships, and the host radians computation `wfb.preview`/
`wfb.emit.monkeyc.rotated` now read instead of each keeping its own copy.

This is the same anti-drift move `tests/test_aod_mask_preview.py` makes
against `WfbAodMask.mc`: parse the real `.mc` source and compare it to the
table, so the two cannot silently disagree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wfb.layout import HAND_ANGLES

ROOT = Path(__file__).resolve().parent.parent


def test_hand_angle_table_matches_the_device_source():
    """Every `HAND_ANGLES` entry's `monkeyc_return` must equal the real
    `return ...;` expression inside its own named function in
    `runtime-lib/WfbHands.mc`. Must fail against a table entry that has
    drifted from the `.mc` source (a changed constant, a transposed
    `hour`/`min`, ...)."""
    text = (ROOT / "runtime-lib" / "WfbHands.mc").read_text()
    for name, angle in HAND_ANGLES.items():
        match = re.search(
            r"function " + re.escape(angle.monkeyc_function)
            + r"\(clock as System\.ClockTime\) as Float \{\s*return (?P<expr>.+?);\s*\}",
            text, re.DOTALL,
        )
        assert match, f"{angle.monkeyc_function!r} not found in WfbHands.mc"
        assert match.group("expr") == angle.monkeyc_return, (
            name, match.group("expr"), angle.monkeyc_return,
        )


@pytest.mark.parametrize("hour, minute, second, hand, degrees", [
    # 03:30:00 -- the hour hand sits between 3 and 4, half past.
    (3, 30, 0, "hour", 105.0),
    (0, 0, 0, "hour", 0.0),
    (0, 15, 0, "minute", 90.0),
    (0, 0, 45, "second", 270.0),
])
def test_host_angle_matches_the_known_clock_position(hour, minute, second, hand, degrees):
    """`HAND_ANGLES[hand].host` at a few known clock times, converted back
    to degrees. Must fail against a host function that mixes up which of
    `hour`/`minute`/`second` a hand reads, or gets the degrees-per-unit
    wrong."""
    import math

    radians = HAND_ANGLES[hand].host(hour, minute, second)
    assert math.degrees(radians) == pytest.approx(degrees)
