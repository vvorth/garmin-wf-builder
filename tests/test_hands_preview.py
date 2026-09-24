"""The host-side preview renderer, analog hands (plan 04 §7), and how it
renders `--asleep`/`--aod` (plan 14).

Each test exercises a contrast a broken renderer could fail: a pixel that
must differ between two known clock times or between the awake and asleep/
AOD frames, not just "the preview doesn't crash"
(`docs/lore/working-agreement.md` on the `00:00`/`11:11` trap).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wfb.build import load
from wfb.diagnostics import Bag
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / "examples" / "features" / "analog" / "face.yaml"

#: The design's own axis, on `fenix8solar47mm` (260x260, so centre is 130,130).
AXIS = (130, 130)


@pytest.fixture(scope="module")
def resolved(db):
    if not DESIGN.exists():
        pytest.skip("examples/features/analog/face.yaml is missing")
    bag = Bag()
    face = load(DESIGN, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


def render_at(resolved, time, *, asleep: bool = False, aod: bool = False):
    return render(resolved, PreviewOptions(
        scale=1, mask_shape=False, quantise=False, time=time, asleep=asleep, aod=aod,
    ))


def test_at_3_00_the_minute_tip_is_up_and_the_hour_tip_is_to_the_right(resolved):
    """`--asleep` isolates the minute/hour hands from the second hand, which
    also points straight up at :00 and would otherwise sit on top of the
    same pixels -- and needs no `aod:` at all, unlike `--aod` below."""
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
    exactly where an `awake` render draws and an `--asleep` one does not."""
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


#: `examples/features/analog/face.yaml` declares no `aod:` at all (it is not
#: the plan 14 example), so the face default (`hide`, D2) would render an
#: empty `--aod` frame for it -- exactly right per plan 14, but useless for
#: exercising hands-in-AOD. A small, self-contained hands fixture with its
#: own `aod: show` is what `test_hands_codegen.py`'s own `NO_HANDS`/
#: `SECONDS_NEVER` constants already do for the same reason.
#:
#: `mask: false` (plan 16): these tests check single exact pixels along a
#: thin hand line, which the pixel mask (on by default) would black out on
#: three renders in four -- an orthogonal concern with its own coverage in
#: `tests/test_aod_mask_preview.py`, not something this file's hand-geometry
#: tests should have to account for.
HANDS_AOD = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
aod:
  mask: false
hands:
  clock:
    hour:
      color: palette.fg
      parts:
        - {shape: line, at: {dy: 0}, to: {dy: -40px}, thickness: 3px}
    minute:
      color: palette.fg
      parts:
        - {shape: line, at: {dy: 0}, to: {dy: -70px}, thickness: 2px}
    second:
      color: palette.fg
      parts:
        - {shape: line, at: {dy: 0}, to: {dy: -110px}, thickness: 1px}
elements:
  - id: main_hands
    type: hands
    hands: clock
    at: {anchor: center}
    aod: show
"""


@pytest.fixture
def aod_resolved(write_design, db):
    bag = Bag()
    face = load(write_design(HANDS_AOD), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


def test_aod_at_3_00_the_minute_tip_is_up_and_the_hour_tip_is_to_the_right(aod_resolved):
    """`--aod` isolates the minute/hour hands from the second hand, which
    also points straight up at :00 and would otherwise sit on top of the
    same pixels."""
    cx, cy = AXIS
    image = render_at(aod_resolved, (3, 0, 0), aod=True)
    background = image.getpixel((cx - 60, cy + 60))  # a corner with nothing drawn
    assert image.getpixel((cx, cy - 40)) != background   # minute tip: straight up
    assert image.getpixel((cx + 25, cy)) != background   # hour tip: to the right
    assert image.getpixel((cx - 25, cy)) == background   # nothing to the left


def test_aod_at_9_00_the_hour_tip_is_to_the_left(aod_resolved):
    cx, cy = AXIS
    image = render_at(aod_resolved, (9, 0, 0), aod=True)
    background = image.getpixel((cx - 60, cy + 60))
    assert image.getpixel((cx - 25, cy)) != background
    assert image.getpixel((cx + 25, cy)) == background


def test_an_aod_render_has_no_second_hand_pixel_where_awake_does(aod_resolved):
    """The second hand's far reach (beyond the minute hand's own tip) is
    exactly where an `awake` render draws and an `--aod` one does not --
    the awake-only second hand hides while asleep, same as before plan 14."""
    cx, cy = AXIS
    awake = render_at(aod_resolved, (3, 0, 0), aod=False)
    aod = render_at(aod_resolved, (3, 0, 0), aod=True)
    far_tip = (cx, cy - 100)  # past the minute hand's own 70px reach
    assert awake.getpixel(far_tip) != aod.getpixel(far_tip)


def test_a_hands_element_with_no_aod_of_its_own_is_hidden_in_aod(write_design, db):
    """The face default is `hide` (D2): a hands element that never mentions
    `aod:` simply does not draw in the `--aod` frame at all."""
    no_aod = HANDS_AOD.replace("    aod: show\n", "")
    bag = Bag()
    face = load(write_design(no_aod, "no_aod.yaml"), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    image = render_at(resolved, (3, 0, 0), aod=True)
    colors = {pixel for pixel in image.get_flattened_data()}
    assert colors == {(0, 0, 0)}, "nothing should draw: no element opted into aod:"
