"""A rectangular screen, resolved, linted and previewed against real device
files (research 16 §2: a rectangle is designed to work, and these pin it).

`venusq2` is 320x360, deliberately *not* square: every round device is
square, so a width/height mix-up in placement, the off-screen test or the
preview could hide on all of them and only shows here.
"""

import pytest

from tests.helpers import find
from wfb import lint
from wfb.build import load
from wfb.diagnostics import Bag
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

RECT = "venusq2"
ROUND = "fenix8solar47mm"

DESIGN = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [venusq2, fenix8solar47mm]
palette:
  bg: "#FFFFFF"
  fg: "#000000"
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
  - id: right_mark
    type: shape
    shape: rectangle
    at: {anchor: right}
    size: {width: 10px, height: 10px}
    align: right
    color: palette.fg
  - id: bottom_mark
    type: shape
    shape: rectangle
    at: {anchor: bottom}
    size: {width: 10px, height: 10px}
    vertical_align: bottom
    color: palette.fg
  - id: offset_mark
    type: shape
    shape: circle
    at: {anchor: center, dx: 25%, dy: 25%}
    radius: 2px
    color: palette.fg
  - id: polar_mark
    type: shape
    shape: circle
    at: {anchor: center, angle: 180deg, radius: 50%r}
    radius: 2px
    color: palette.fg
"""

#: Two marks either side of the screen's aspect ratio: `tall_mark` sits in
#: rows 340-350, inside 360 but outside 320; `wide_mark` in columns 315-325,
#: past 320 but inside 360. A width/height swap flips both verdicts.
EDGES = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [venusq2]
palette:
  fg: "#FFFFFF"
elements:
  - id: tall_mark
    type: shape
    shape: rectangle
    at: {anchor: top_left, dx: 150px, dy: 340px}
    size: {width: 10px, height: 10px}
    align: left
    vertical_align: top
    color: palette.fg
  - id: wide_mark
    type: shape
    shape: rectangle
    at: {anchor: top_left, dx: 315px, dy: 150px}
    size: {width: 10px, height: 10px}
    align: left
    vertical_align: top
    color: palette.fg
"""


@pytest.fixture
def resolved_for(write_design, bag, db):
    def _resolve(device_id: str, design: str = DESIGN):
        if device_id not in db.ids():
            pytest.skip(f"{device_id} not installed")
        face = load(write_design(design), bag)
        assert face is not None, bag.render()
        device = db.get(device_id)
        return resolve(face, device, bake_fonts(face, device))

    return _resolve


def _lint_codes(resolved) -> dict[str, set[str]]:
    bag = Bag()
    lint.run(resolved, bag)
    out: dict[str, set[str]] = {}
    for d in bag.items:
        out.setdefault(d.code, set()).add(d.message.split(" ", 1)[0].rstrip(":"))
    return out


def test_venusq2_reads_as_a_320x360_rectangle(db):
    if RECT not in db.ids():
        pytest.skip(f"{RECT} not installed")
    device = db.get(RECT)
    assert (device.shape, device.width, device.height) == ("rectangle", 320, 360)
    assert device.minor_radius == 160          # half the *shorter* side
    assert device.device_family == "rectangle-320x360"
    assert device.display_type == "amoled"


def test_full_bleed_percent_fills_the_non_square_framebuffer(resolved_for):
    placed = find(resolved_for(RECT), "background")
    assert (placed.box.x, placed.box.y, placed.box.width, placed.box.height) == (0, 0, 320, 360)


def test_edge_anchors_land_on_their_own_axis(resolved_for):
    resolved = resolved_for(RECT)
    assert find(resolved, "right_mark").box.right == 320
    assert find(resolved, "right_mark").center[1] == 180
    assert find(resolved, "bottom_mark").box.bottom == 360
    assert find(resolved, "bottom_mark").center[0] == 160


def test_percent_offsets_resolve_per_axis(resolved_for):
    """`dx: 25%` is a quarter of the width, `dy: 25%` a quarter of the height:
    80 and 90 px here, where a square screen would make them equal."""
    assert find(resolved_for(RECT), "offset_mark").center == (160 + 80, 180 + 90)


def test_percent_r_is_half_the_shorter_side(resolved_for):
    """`50%r` straight down is 80 px (half of 160), not 90 (half of 180)."""
    assert find(resolved_for(RECT), "polar_mark").center == (160, 180 + 80)


def test_edge_marks_are_visible_on_a_rectangle_but_not_on_a_round_screen(resolved_for):
    """A rectangle's visible area is its framebuffer; the same edge-hugging
    marks fall under a round device's bezel."""
    rect = _lint_codes(resolved_for(RECT))
    assert "safe-area" not in rect and "off-screen" not in rect
    assert _lint_codes(resolved_for(ROUND)).get("safe-area") == {"right_mark", "bottom_mark"}


def test_off_screen_uses_width_for_x_and_height_for_y(resolved_for):
    codes = _lint_codes(resolved_for(RECT, EDGES))
    assert codes.get("off-screen") == {"wide_mark"}
    assert "safe-area" not in codes


def test_preview_is_the_non_square_size(resolved_for):
    image = render(resolved_for(RECT), PreviewOptions(scale=1))
    assert image.size == (320, 360)


def test_preview_keeps_the_top_edge_a_round_crop_would_hide(resolved_for):
    """(60, 1) is inside a rectangle's panel but far outside the inscribed
    circle, so the white background shows there only on the rectangle."""
    rect = render(resolved_for(RECT), PreviewOptions(scale=1)).convert("RGB")
    round_ = render(resolved_for(ROUND), PreviewOptions(scale=1)).convert("RGB")
    assert rect.getpixel((60, 1)) == (255, 255, 255)
    assert round_.getpixel((60, 1)) != (255, 255, 255)
