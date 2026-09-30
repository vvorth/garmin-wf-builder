"""`outline:` on shapes and icons (research 19, plan 23): which shapes grow one
copy of themselves and which are stamped, the ring growing the element's
box, the width cap, and the preview ringing what it draws, openings
included.  The fixture `tests/fixtures/outline_shapes/face.yaml` is also
built for real by `tests/test_outline_build.py` (`slow`).
"""

from __future__ import annotations

import re

import pytest

from wfb.preview import PreviewOptions, render

from tests.helpers import find, generate_for_targets, load_errors, load_face, resolve_text

_PALETTE = """
format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm]
resources:
  palette:
    bg: "#000000"
    fg: "#0055AA"
    ring: "#FFFF00"
elements:
  background:
    type: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: color.bg
"""

RING = (255, 255, 0)
FG = (0, 85, 170)
BG = (0, 0, 0)


def _view(text: str, write_design, tmp_path) -> str:
    """The generated view source for a design."""
    files = generate_for_targets(write_design(_PALETTE + text), tmp_path / "out").files()
    return next(body for name, body in files.items() if name.endswith("View.mc"))


def _method(view: str, name: str) -> str:
    """One generated method's body, `private function <name>` to its close."""
    match = re.search(rf"private function {name}\(.*?\n    }}\n", view, re.S)
    assert match is not None, f"no {name} in the view"
    return match.group(0)


# -- which shapes grow, which are stamped (plan 23 D2) -------------------------


def test_a_filled_circle_grows_one_copy(write_design, tmp_path):
    body = _method(_view("""
  disc:
    type: circle
    at: {anchor: center}
    radius: 20px
    color: color.fg
    outline: color.ring
""", write_design, tmp_path), "drawDisc")
    assert "dc.fillCircle(Layout.DISC_CX, Layout.DISC_CY, Layout.DISC_RADIUS + 1);" in body
    assert "OUTLINE_OFFSETS" not in body
    # the ring comes first, the interior over it
    assert body.index("RADIUS + 1") < body.index("dc.fillCircle(Layout.DISC_CX, Layout.DISC_CY, Layout.DISC_RADIUS);")


def test_a_filled_rectangle_grows_into_a_rounded_one(write_design, tmp_path):
    """A rectangle's dilation has round corners of the ring's own radius."""
    body = _method(_view("""
  card:
    type: rectangle
    at: {anchor: center}
    size: {width: 40px, height: 20px}
    color: color.fg
    outline: color.ring
""", write_design, tmp_path), "drawCard")
    assert re.search(r"dc\.fillRoundedRectangle\(Layout\.CARD_X - 1, Layout\.CARD_Y - 1,\s+"
                     r"Layout\.CARD_WIDTH \+ 2, Layout\.CARD_HEIGHT \+ 2,\s+1\);", body), body
    assert "dc.fillRectangle(Layout.CARD_X, Layout.CARD_Y," in body


def test_a_rounded_rectangle_grows_its_corner_radius_too(write_design, tmp_path):
    body = _method(_view("""
  pill:
    type: rectangle
    at: {anchor: center}
    size: {width: 40px, height: 20px}
    corner_radius: 5px
    color: color.fg
    outline: color.ring
""", write_design, tmp_path), "drawPill")
    assert re.search(r"Layout\.PILL_WIDTH \+ 2, Layout\.PILL_HEIGHT \+ 2,\s+Layout\.PILL_CORNER \+ 1\);",
                     body), body


@pytest.mark.parametrize("shape, call", [
    ("type: ellipse\n    at: {anchor: center}\n    size: {width: 40px, height: 20px}",
     "dc.fillEllipse(Layout.EL_CX - 1, Layout.EL_CY,"),
    ("type: circle\n    at: {anchor: center}\n    radius: 20px\n    thickness: 3px\n    filled: false",
     "dc.drawCircle(Layout.EL_CX - 1, Layout.EL_CY,"),
    ("type: rectangle\n    at: {anchor: center}\n    size: {width: 40px, height: 20px}\n"
     "    thickness: 2px\n    filled: false",
     "dc.drawRectangle(Layout.EL_X - 1, Layout.EL_Y,"),
    ("type: line\n    at: {anchor: center}\n    to: {anchor: center, dx: 30px}\n    thickness: 2px",
     "dc.drawLine(Layout.EL_CX - 1, Layout.EL_CY, Layout.EL_END_X - 1, Layout.EL_END_Y);"),
    ("type: arc\n    at: {anchor: center}\n    radius: 40px\n    thickness: 3px\n"
     "    start_angle: 0deg\n    sweep: 90deg",
     "WfbArc.drawSpan(dc, Layout.EL_CX - 1, Layout.EL_CY,"),
])
def test_every_other_shape_is_stamped(write_design, tmp_path, shape, call):
    """No one-draw dilation for these: each is stamped at the ring's
    offsets, every coordinate shifted, and never grown."""
    body = _method(_view(f"""
  el:
    {shape}
    color: color.fg
    outline: color.ring
""", write_design, tmp_path), "drawEl")
    assert call in body, body
    assert "offsets" not in body and "while" not in body  # unrolled
    assert "RADIUS + 1" not in body and "_X + 2" not in body  # never grown


def test_a_polygon_fills_its_four_shifted_copies_baked_at_build_time(write_design, tmp_path):
    """No per-vertex work on the watch: the four shifted copies are
    `Layout` constants (research 19 §4.6)."""
    body = _method(_view("""
  tri:
    type: polygon
    points: [{anchor: center}, {anchor: center, dx: 20px}, {anchor: center, dy: 20px}]
    color: color.fg
    outline: color.ring
""", write_design, tmp_path), "drawTri")
    assert [f"dc.fillPolygon(Layout.TRI_RING_{i});" in body for i in range(4)] == [True] * 4
    assert "WfbRing" not in body


def test_an_aod_filled_flip_stamps_instead_of_growing(write_design, tmp_path):
    """A shape filled in only one frame has no single grown copy: it stamps
    whichever primitive the frame draws.  Needs an AMOLED target, or no
    AOD code is emitted at all."""
    text = """
  disc:
    type: circle
    at: {anchor: center}
    radius: 20px
    color: color.fg
    outline: color.ring
    aod: {filled: false}
"""
    path = write_design(_PALETTE.replace("[fenix8solar47mm]", "[fenix847mm]") + text)
    files = generate_for_targets(path, tmp_path / "out").files()
    view = next(body for name, body in files.items() if name.endswith("View.mc"))
    body = _method(view, "drawDisc")
    assert "dc.fillCircle(Layout.DISC_CX - 1, Layout.DISC_CY," in body
    assert "RADIUS + 1" not in body


def test_no_outline_emits_exactly_the_plain_draw(write_design, tmp_path):
    body = _method(_view("""
  disc:
    type: circle
    at: {anchor: center}
    radius: 20px
    color: color.fg
""", write_design, tmp_path), "drawDisc")
    assert body.count("dc.") == 2  # one setColor, one fillCircle


# -- icons ---------------------------------------------------------------------


def test_an_icon_draws_its_ring_from_its_ring_font(write_design, tmp_path):
    body = _method(_view("""
  alarm:
    type: icon
    icon: alarm
    size: 20%r
    at: {anchor: center}
    color: color.fg
    outline: color.ring
""", write_design, tmp_path), "drawAlarm")
    assert "offsets" not in body
    assert "dc.drawText(Layout.ALARM_CX, Layout.ALARM_CY, ringFont," in body
    assert body.index("Palette.RING") < body.index("Palette.FG")


# -- the IR and layout -----------------------------------------------------------


def test_the_removed_object_form_is_refused_on_every_kind(write_design):
    errors = load_errors(_PALETTE + """
  disc:
    type: circle
    at: {anchor: center}
    radius: 20px
    color: color.fg
    outline: {color: color.ring, width: 2}
""", write_design)
    assert [e.code for e in errors] == ["outline"], errors
    assert errors[0].message.startswith("elements.disc.outline: ")


def test_the_ring_grows_the_box_but_not_what_is_drawn(write_design, bag, db):
    """The lints and the low-power clip read `box`; a rectangle draws from
    its own rectangle, which must not move."""
    plain = """
  card:
    type: rectangle
    at: {anchor: center}
    size: {width: 40px, height: 20px}
    color: color.fg
"""
    _, before = resolve_text(_PALETTE + plain, write_design, bag, db)
    _, after = resolve_text(_PALETTE + plain + "    outline: color.ring\n",
                            write_design, bag, db)
    old, new = find(before, "card"), find(after, "card")
    assert new.box == old.box.inflate(1)
    assert new.inner_box == old.box
    assert new.ring_grow == 1


def test_a_circles_round_extent_grows_with_its_ring(write_design, bag, db):
    from wfb.layout import circular_extent

    text = """
  disc:
    type: circle
    at: {anchor: center}
    radius: 20px
    color: color.fg
"""
    _, before = resolve_text(_PALETTE + text, write_design, bag, db)
    _, after = resolve_text(_PALETTE + text + "    outline: color.ring\n", write_design, bag, db)
    (_, _, r0), (_, _, r1) = circular_extent(find(before, "disc")), circular_extent(find(after, "disc"))
    assert r1 == r0 + 1


def test_a_shape_ring_is_linted_for_contrast_against_its_fill(write_design, db):
    from tests.helpers import lint_text

    bag = lint_text(_PALETTE.replace('ring: "#FFFF00"', 'ring: "#0055AB"') + """
  disc:
    type: circle
    at: {anchor: center}
    radius: 20px
    color: color.fg
    outline: color.ring
""", write_design, db)
    assert any(d.code == "contrast" and "disc: outline ring" in d.message for d in bag.items), \
        bag.render()


# -- preview -------------------------------------------------------------------


def _render(text: str, write_design, bag, db):
    _, resolved = resolve_text(_PALETTE + text, write_design, bag, db)
    return resolved, render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))


def test_the_preview_rings_a_disc(write_design, bag, db):
    resolved, image = _render("""
  disc:
    type: circle
    at: {anchor: center}
    radius: 20px
    color: color.fg
    outline: color.ring
""", write_design, bag, db)
    cx, cy = find(resolved, "disc").center
    assert image.getpixel((cx, cy)) == FG
    assert image.getpixel((cx + 21, cy)) == RING
    assert image.getpixel((cx + 25, cy)) == BG


def test_the_preview_rings_the_inside_of_an_opening_too(write_design, bag, db):
    """A stroked circle's hole is an opening: its inner edge gets a ring
    and its centre stays open -- the contrast a ring drawn only round the
    outside would fail."""
    resolved, image = _render("""
  hoop:
    type: circle
    at: {anchor: center}
    radius: 30px
    thickness: 4px
    filled: false
    color: color.fg
    outline: color.ring
""", write_design, bag, db)
    cx, cy = find(resolved, "hoop").center
    column = [image.getpixel((cx, cy - dy)) for dy in range(0, 40)]
    assert column[0] == BG
    first_ring = column.index(RING)
    first_fg = column.index(FG)
    assert first_ring < first_fg, column
    assert column[first_fg:].count(RING) > 0, column  # the outer ring beyond the stroke


# -- the partial-update lint -----------------------------------------------------


def _low_power(body: str) -> str:
    return _PALETTE.replace("[fenix8solar47mm]", "[fr955]") + body


def test_a_stamped_ring_in_a_partial_update_warns(write_design, db):
    """Four more draws of the element every second: measured about 4x its
    own cost on a watch (research 19 §4.5)."""
    from tests.helpers import lint_text

    bag = lint_text(_low_power("""
  secs:
    type: text
    text: "{time.second:02d}"
    at: {anchor: center}
    color: color.fg
    outline: color.ring
    sleep_update: true
"""), write_design, db, "fr955")
    [warning] = [d for d in bag.items if d.code == "partial-update-budget"]
    assert warning.message.startswith("secs: its 'outline:' ring is stamped -- 4 more draws")


def test_a_grown_ring_in_a_partial_update_does_not_warn(write_design, db):
    from tests.helpers import lint_text

    bag = lint_text(_low_power("""
  dot:
    type: circle
    at: {anchor: center}
    radius: 5px
    color: color.fg
    outline: color.ring
    sleep_update: true
"""), write_design, db, "fr955")
    assert not [d for d in bag.items if d.code == "partial-update-budget"], bag.render()


def test_a_group_rings_share_in_a_partial_update_warns_and_can_be_allowed(write_design, db):
    from tests.helpers import lint_text

    body = """
  g:
    type: group
    outline: color.ring
    ALLOW
    children:
      secs:
        type: text
        text: "{time.second:02d}"
        at: {anchor: center}
        color: color.fg
        sleep_update: true
"""
    bag = lint_text(_low_power(body.replace("ALLOW", "")), write_design, db, "fr955")
    [warning] = [d for d in bag.items if d.code == "partial-update-budget"]
    assert "its share of a group's 'outline:' ring" in warning.message
    allowed = lint_text(_low_power(body.replace(
        "ALLOW", 'lint: {allow: [partial-update-budget], reason: "measured, fits"}')),
        write_design, db, "fr955")
    assert not [d for d in allowed.items if d.code == "partial-update-budget"], allowed.render()
