"""`wfb.layout.radial_direction_sign`/`radial_align_offset` (plan 19 A1):
the two pieces `radial_text_angle_span` (the lint band) and
`wfb.preview._draw_radial_vector_text` (the pixels) both derive from
`curve.direction`/`align`, factored into one place so they cannot disagree
about which way a `curve: {style: radial}` run walks or where its anchor
sits along it. Each side still does its own degrees-vs-radians arithmetic
around these two pieces (root instructions: pixels must not move).
"""

from __future__ import annotations

import pytest

from wfb.layout import radial_align_offset, radial_direction_sign


@pytest.mark.parametrize("direction, expected", [
    ("clockwise", -1.0),
    ("counter_clockwise", 1.0),
    (None, -1.0),  # the schema default is clockwise
])
def test_direction_sign(direction, expected):
    """`clockwise` (and the unset default) is `-1.0`; `counter_clockwise`
    is `1.0`. Must fail against a sign flip, or against `None` not falling
    back to `clockwise`."""
    assert radial_direction_sign(direction) == expected


@pytest.mark.parametrize("align, expected", [
    ("left", 0.0),
    ("center", 50.0),
    ("right", 100.0),
])
def test_align_offset(align, expected):
    """`left` starts the run on the anchor, `right` ends it there, `center`
    splits the difference. Must fail against a swapped `left`/`right`, or
    against `center` not being exactly half."""
    assert radial_align_offset(align, 100.0) == expected
