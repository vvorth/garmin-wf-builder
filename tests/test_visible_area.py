"""The simulator skin as a visible-area mask (`wfb.visible_area`, research 16
§3): the `safe-area` lint, the preview crop and the `aod-burn-in`
denominator on every screen that is not round."""

import math

import pytest

from tests.helpers import find
from wfb import lint
from wfb.build import load
from wfb.diagnostics import Bag
from wfb.emit.resources import bake_fonts
from wfb.layout import InkDisc, InkQuad, InkRect, InkSector, inside_visible_area_for, resolve
from wfb.preview import PreviewOptions, render
from wfb.visible_area import visible_mask

INSTINCT = "instinct2"
ROUND = "fenix8solar47mm"

#: Pixel positions on the 176x176 Instinct 2, read off its skin: (117, 57)
#: is on the opaque ring round the subscreen window, (144, 31) the window's
#: centre, (88, 88) the screen's. `under_ring` is well inside the visible
#: disc on the 260x260 round device, so only the skin can flag it.
DESIGN = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [instinct2, fenix8solar47mm]
palette:
  fg: "#FFFFFF"
elements:
  - id: under_ring
    type: shape
    shape: circle
    at: {anchor: top_left, dx: 117px, dy: 57px}
    radius: 2px
    color: palette.fg
  - id: in_window
    type: shape
    shape: circle
    at: {anchor: top_left, dx: 144px, dy: 31px}
    radius: 4px
    color: palette.fg
  - id: middle
    type: shape
    shape: rectangle
    at: {anchor: top_left, dx: 88px, dy: 88px}
    size: {width: 20px, height: 10px}
    color: palette.fg
  - id: corner
    type: shape
    shape: rectangle
    at: {anchor: top_left}
    size: {width: 8px, height: 8px}
    align: left
    vertical_align: top
    color: palette.fg
"""


def _need(db, *device_ids):
    for device_id in device_ids:
        if device_id not in db.ids():
            pytest.skip(f"{device_id} not installed")


@pytest.fixture
def resolved_for(write_design, bag, db):
    def _resolve(device_id: str, design: str = DESIGN):
        _need(db, device_id)
        face = load(write_design(design), bag)
        assert face is not None, bag.render()
        device = db.get(device_id)
        return resolve(face, device, bake_fonts(face, device))

    return _resolve


# -- the mask itself ---------------------------------------------------------


def test_device_names_its_skin_and_panel_location(db):
    _need(db, INSTINCT)
    device = db.get(INSTINCT)
    assert device.skin_path is not None and device.skin_path.name == "instinct2.png"
    assert device.display_location == (99, 164, 176, 176)


@pytest.mark.parametrize("device_id", ["fr955", "fenix8solar51mm", "venu"])
def test_a_round_skin_is_the_inscribed_circle_up_to_its_rim(db, device_id):
    """Round screens keep their analytic circle; this pins that the skin
    agrees with it, so the two mechanisms cannot mean different screens.
    Every pixel on which they disagree lies on the circle's edge."""
    _need(db, device_id)
    device = db.get(device_id)
    mask = visible_mask(device)
    assert mask is not None
    r = device.width / 2
    for y in range(mask.height):
        for x in range(mask.width):
            in_circle = math.hypot(x + 0.5 - r, y + 0.5 - r) <= r
            if bool(mask.visible[y * mask.width + x]) != in_circle:
                assert abs(math.hypot(x + 0.5 - r, y + 0.5 - r) - r) <= 1.5, (x, y)


def test_the_instinct_mask_has_the_subscreen_window_and_its_ring(db):
    _need(db, INSTINCT)
    mask = visible_mask(db.get(INSTINCT))
    assert mask is not None
    at = lambda x, y: bool(mask.visible[y * mask.width + x])  # noqa: E731
    assert at(88, 88) and at(144, 31)        # the face, and the window
    assert not at(117, 57) and not at(0, 0)  # the ring, and a chamfered corner
    assert 117 in mask.hidden[57]


def test_the_one_pixel_rim_is_tolerated(db):
    """The Instinct 3 skin paints row 0 opaque, although its declared
    subscreen box starts there (research 16 §3). Row 0 is covered, but
    not firmly: the visible row below it keeps it out of `hidden`."""
    _need(db, "instinct3solar45mm")
    mask = visible_mask(db.get("instinct3solar45mm"))
    assert mask is not None
    assert not any(mask.visible[x] for x in range(mask.width))
    assert 88 not in mask.hidden.get(0, ())


@pytest.mark.parametrize("ink, inside, outside", [
    (InkRect(10, 10, 4, 4), (12, 12), (15, 12)),
    (InkDisc(10, 10, 3), (12, 10), (13.5, 10)),
    (InkQuad(((10, 0), (20, 10), (10, 20), (0, 10))), (10, 10), (2, 2)),
    # A quarter annulus from 3 to 12 o'clock (Garmin degrees, y down).
    (InkSector(0, 0, 5, 10, 0, 90), (5, -5), (5, 5)),
])
def test_ink_contains(ink, inside, outside):
    assert ink.contains(*inside)
    assert not ink.contains(*outside)


# -- safe-area -----------------------------------------------------------------


def test_the_subscreen_ring_is_a_finding_on_the_instinct_only(resolved_for):
    instinct = resolved_for(INSTINCT)
    assert inside_visible_area_for(find(instinct, "under_ring"), instinct.device) is False
    assert inside_visible_area_for(find(instinct, "in_window"), instinct.device) is True
    assert inside_visible_area_for(find(instinct, "middle"), instinct.device) is True
    round_ = resolved_for(ROUND)
    assert inside_visible_area_for(find(round_, "under_ring"), round_.device) is True


def test_safe_area_warns_on_the_instinct_with_a_skin_note(resolved_for):
    bag = Bag()
    lint.run(resolved_for(INSTINCT), bag)
    hits = {d.message.split(" ", 1)[0]: d for d in bag.items if d.code == "safe-area"}
    assert set(hits) == {"under_ring", "corner"}
    assert "simulator skin" in " ".join(hits["under_ring"].notes)
    assert not any("not checked" in d.message for d in bag.items if d.code == "safe-area")


def test_a_rounded_rectangle_corner_is_a_finding(resolved_for):
    """`venux1`'s skin rounds its corners; the framebuffer alone would
    call an 8x8 mark in the top-left corner visible."""
    bag = Bag()
    lint.run(resolved_for("venux1", DESIGN.replace("instinct2, fenix8solar47mm", "venux1")), bag)
    assert "corner" in {d.message.split(" ", 1)[0] for d in bag.items if d.code == "safe-area"}


# -- preview and aod-burn-in ---------------------------------------------------


def test_the_preview_greys_out_what_the_instinct_bezel_hides(resolved_for):
    image = render(resolved_for(INSTINCT), PreviewOptions(scale=2, quantise=False)).convert("RGB")
    assert image.getpixel((1, 1)) == (24, 24, 24)             # chamfered corner
    assert image.getpixel((117 * 2, 57 * 2)) == (24, 24, 24)  # the ring
    assert image.getpixel((144 * 2, 31 * 2)) == (255, 255, 255)  # in_window's own dot
    assert image.getpixel((88 * 2, 88 * 2)) == (255, 255, 255)   # middle


def test_burn_in_counts_only_the_skins_visible_pixels(db):
    _need(db, "venux1")
    device = db.get("venux1")
    mask = lint._aod_burn_in_mask(device)
    assert mask.histogram()[255] == visible_mask(device).visible_count
    assert mask.histogram()[255] < device.width * device.height
