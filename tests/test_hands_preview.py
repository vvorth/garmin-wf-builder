"""The host-side preview renderer, analog hands (plan 04 §7).

Each test exercises a contrast a broken renderer could fail: a pixel that
must differ between two known clock times or between the awake and asleep
frames, not just "the preview doesn't crash" (`docs/lore/working-agreement.md`
on the `00:00`/`11:11` trap).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_diagnostics import load
from wfb.diagnostics import Bag
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / "examples" / "analog" / "face.yaml"

#: The design's own axis, on `fenix8solar47mm` (260x260, so centre is 130,130).
AXIS = (130, 130)


@pytest.fixture(scope="module")
def resolved(db):
    if not DESIGN.exists():
        pytest.skip("examples/analog/face.yaml is missing")
    bag = Bag()
    face = load(DESIGN, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


def render_at(resolved, time, *, asleep: bool = False):
    return render(resolved, PreviewOptions(
        scale=1, mask_shape=False, quantise=False, time=time, asleep=asleep,
    ))


def test_at_3_00_the_minute_tip_is_up_and_the_hour_tip_is_to_the_right(resolved):
    """--asleep isolates the minute/hour hands from the second hand, which
    also points straight up at :00 and would otherwise sit on top of the
    same pixels."""
    cx, cy = AXIS
    image = render_at(resolved, (3, 0, 0), asleep=True)
    background = image.getpixel((cx - 60, cy + 60))  # a corner with nothing drawn
    assert image.getpixel((cx, cy - 40)) != background   # minute tip: straight up
    assert image.getpixel((cx + 25, cy)) != background   # hour tip: to the right
    assert image.getpixel((cx - 25, cy)) == background   # nothing to the left


def test_at_9_00_the_hour_tip_is_to_the_left(resolved):
    cx, cy = AXIS
    image = render_at(resolved, (9, 0, 0), asleep=True)
    background = image.getpixel((cx - 60, cy + 60))
    assert image.getpixel((cx - 25, cy)) != background
    assert image.getpixel((cx + 25, cy)) == background


def test_an_asleep_render_has_no_second_hand_pixel_where_awake_does(resolved):
    """The second hand's far reach (beyond the minute hand's own tip) is
    exactly where an `awake` render draws and an `asleep` one does not."""
    cx, cy = AXIS
    awake = render_at(resolved, (3, 0, 0), asleep=False)
    asleep = render_at(resolved, (3, 0, 0), asleep=True)
    far_tip = (cx, cy - 95)  # past the minute hand's own ~85px reach
    assert awake.getpixel(far_tip) != asleep.getpixel(far_tip)


def test_time_moves_the_hands_and_leaves_the_dial_alone(resolved):
    """A sample-time-only change must move the hands but not the shared
    static dial -- proof that `--time` reaches the hands and nothing else
    gets accidentally re-seeded."""
    a = render_at(resolved, (0, 0, 0))
    b = render_at(resolved, (6, 30, 0))
    assert list(a.get_flattened_data()) != list(b.get_flattened_data())
    cx, cy = AXIS
    edge = (cx, cy - 118)  # inside dial_ring's 92%r radius -- unaffected by hands
    assert a.getpixel(edge) == b.getpixel(edge)


def test_the_default_sample_time_still_renders(resolved):
    """No `--time` at all keeps working -- the sample clock (10:09:42)."""
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False))
    colors = {pixel for pixel in image.get_flattened_data()}
    assert len(colors) > 2, "the preview is blank"
