"""`wfb.layout.PatternTextAngle` (plan 19 A1): the one definition of a
`shape: text` pattern part's per-copy curved-text angle, shared by the lint
ink (`wfb.layout._pattern_text_ink`), the preview
(`wfb.preview._pattern_text`) and codegen
(`wfb.emit.monkeyc.rotated._emit_pattern_text_angle_expr`) instead of each
recomputing `(local - (start + index * step)) % 360.0` on its own.
"""

from __future__ import annotations

import pytest

from wfb.layout import PatternTextAngle


def test_linear_pattern_keeps_the_local_angle_on_every_copy():
    """A linear pattern's `start`/`step` are always `0.0`, so every copy
    must draw at exactly the part's own local angle. Must fail against an
    implementation that still multiplies `index` into the result even when
    `step` is `0.0`."""
    angle = PatternTextAngle(local=30.0, start=0.0, step=0.0)
    assert angle.copy_curve_angle(0) == 30.0
    assert angle.copy_curve_angle(1) == 30.0
    assert angle.copy_curve_angle(5) == 30.0


def test_radial_pattern_turns_back_by_the_copy_rotation():
    """A radial pattern's copy `i` sits `start + i * step` design-degrees
    around from copy 0, so its text must be turned back by exactly that
    much: `local - (start + i * step)`. Must fail against a sign error, or
    against `step` not being scaled by `index`."""
    angle = PatternTextAngle(local=90.0, start=10.0, step=15.0)
    assert angle.copy_curve_angle(0) == pytest.approx(80.0)
    assert angle.copy_curve_angle(1) == pytest.approx(65.0)
    assert angle.copy_curve_angle(2) == pytest.approx(50.0)


def test_result_wraps_into_0_360():
    """The result is always taken modulo 360 -- a copy rotation past the
    local angle must wrap back into range rather than go negative. Must
    fail against an implementation that skips the `% 360.0`."""
    angle = PatternTextAngle(local=10.0, start=0.0, step=100.0)
    assert angle.copy_curve_angle(1) == pytest.approx((10.0 - 100.0) % 360.0)
    assert 0.0 <= angle.copy_curve_angle(1) < 360.0
