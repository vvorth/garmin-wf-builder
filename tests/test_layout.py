"""Per-device resolution: relative units in, absolute pixels out."""

import pytest

from tests.test_diagnostics import load
from wfb.emit.resources import bake_fonts
from wfb.layout import (
    PlacedIcon, PlacedProgress, PlacedShape, PlacedText, inside_screen,
    inside_visible_area_for, is_full_bleed, resolve,
)

DESIGN = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm, fenix8solar51mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
  - id: ring
    type: progress
    style: arc
    value: activity.steps
    max: activity.step_goal
    at: {anchor: center}
    radius: 50%r
    thickness: 10px
    start_angle: 180deg
    sweep: 340deg
    color: palette.fg
    when_absent: hide
  - id: dot
    type: shape
    shape: circle
    at: {anchor: center, angle: 90deg, radius: 40%r}
    radius: 6px
    color: palette.fg
  - id: badge
    type: icon
    icon: steps
    size: 20px
    at: {anchor: center, dy: 25%}
    color: palette.fg
"""


@pytest.fixture
def resolved_for(write_design, bag, db):
    def _resolve(device_id: str, design: str = DESIGN):
        face = load(write_design(design), bag)
        assert face is not None, bag.render()
        device = db.get(device_id)
        fonts = bake_fonts(face, device, device.minor_radius)
        return resolve(face, device, fonts)

    return _resolve


def find(resolved, element_id):
    return next(p for p in resolved.items if p.id == element_id)


def test_percent_of_screen_fills_the_framebuffer(resolved_for):
    placed = find(resolved_for("fenix8solar47mm"), "background")
    assert (placed.box.x, placed.box.y, placed.box.width, placed.box.height) == (0, 0, 260, 260)


def test_the_same_design_resolves_differently_per_device(resolved_for):
    """260x260 and 280x280 are both round-260x260's family peers by shape only."""
    small = find(resolved_for("fenix8solar47mm"), "ring")
    large = find(resolved_for("fenix8solar51mm"), "ring")
    assert small.radius == 65   # 50% of a 130px minor radius
    assert large.radius == 70   # 50% of a 140px minor radius
    assert small.center == (130, 130)
    assert large.center == (140, 140)


def test_author_angles_are_converted_for_drawarc(resolved_for):
    ring = find(resolved_for("fenix8solar47mm"), "ring")
    assert ring.start_angle == 180.0          # author: 6 o'clock
    assert ring.garmin_start == 270.0         # Garmin: 6 o'clock
    assert ring.garmin_direction == "ARC_CLOCKWISE"


def test_polar_placement_puts_90_degrees_at_3_oclock(resolved_for):
    """Author angles are clockwise from 12, so 90 degrees is the right-hand side."""
    dot = find(resolved_for("fenix8solar47mm"), "dot")
    assert dot.center == (182, 130)           # 130 + 40% of 130


def test_an_arcs_box_covers_its_pen_width(resolved_for):
    ring = find(resolved_for("fenix8solar47mm"), "ring")
    assert ring.box.width >= 2 * (ring.radius + ring.thickness // 2)


def test_icon_is_sized_to_its_own_glyph_and_centred(resolved_for):
    """An icon's box comes from measuring its actual baked glyph, not from
    forcing a `size x size` square -- a footprints glyph is wider than tall,
    and pretending otherwise would make the safe-area/overflow lints check
    the wrong box."""
    badge = find(resolved_for("fenix8solar47mm"), "badge")
    assert badge.size == 20
    assert badge.box.width > 0 and badge.box.height > 0
    assert badge.center == (130, 195)
    assert badge.font_key and badge.codepoint


def test_full_bleed_is_recognised(resolved_for, db):
    device = db.get("fenix8solar47mm")
    resolved = resolved_for("fenix8solar47mm")
    assert is_full_bleed(find(resolved, "background").box, device)
    assert not is_full_bleed(find(resolved, "badge").box, device)


def test_a_ring_is_measured_as_a_circle_not_as_its_bounding_box(resolved_for, db):
    """The corners of a ring's box lie outside the disc; the ring itself does not."""
    device = db.get("fenix8solar47mm")
    ring = find(resolved_for("fenix8solar47mm"), "ring")
    assert inside_screen(ring.box, device)
    assert inside_visible_area_for(ring, device) is True


def test_draw_order_follows_the_document(resolved_for):
    ids = [p.id for p in resolved_for("fenix8solar47mm").items]
    assert ids == ["background", "ring", "dot", "badge"]


def test_explicit_z_overrides_document_order(write_design, bag, db):
    design = DESIGN.replace("  - id: background\n", "  - id: background\n    z: 5\n")
    face = load(write_design(design), bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    assert resolved.items[-1].id == "background"


def test_text_extent_comes_from_real_font_metrics(write_design, bag, db, repo_root):
    design = DESIGN + """
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    font: font.clock
    at: {anchor: center}
    color: palette.fg
"""
    ttf = repo_root / "examples/slice/assets/OpenSans-Regular.ttf"
    design = design.replace("targets:", f"fonts:\n  clock:\n    source: {ttf}\n    size: 60\ntargets:")
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    clock = find(resolved, "clock")
    assert clock.widest == "23:59"
    assert clock.width_is_estimated is False
    assert clock.measured_width > 0


def test_low_power_clip_is_none_when_nothing_is_low_power(resolved_for):
    assert resolved_for("fenix8solar47mm").clip_for("low_power") is None


def test_low_power_clip_is_the_tight_union(write_design, bag, db):
    design = DESIGN.replace(
        "    at: {anchor: center, dy: 25%}\n    color: palette.fg",
        "    at: {anchor: center, dy: 25%}\n    color: palette.fg\n    modes: [active, low_power]",
    )
    face = load(write_design(design), bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    clip = resolved.clip_for("low_power")
    assert clip is not None
    # Only the badge is low-power, so the clip must be tiny, not the screen.
    assert clip.area < 0.05 * device.width * device.height
