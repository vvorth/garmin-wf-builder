"""Baked ring fonts: a ringed text in a baked font, or a ringed
icon, draws its 1px ring as one `drawText` in a companion font holding just
the glyphs it rings, each dilated by 1px -- instead of four stamps."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops

from wfb import kinds
from wfb.fonts import bake
from wfb.fonts.bmfont import dilate
from wfb.ir import RING_OFFSETS

from tests.helpers import generate_for_targets, lint_text, load_face

ROOT = Path(__file__).resolve().parent
TTF = ROOT / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"


def _tile(font, char: str) -> tuple[Image.Image, int, int]:
    box = font.glyphs[char]
    return (font.sheet.crop((box.x, box.y, box.x + box.width, box.y + box.height)),
            box.xoffset, box.yoffset)


def test_a_ring_glyph_is_the_exact_1px_dilation_of_its_glyph():
    """Placed on one canvas at their own offsets, the ring glyph is the
    union of the glyph and its four 1px shifts -- what the stamp draws."""
    base, _ = bake(TTF, name="clock", size=30, glyphs="0123456789:")
    ring, _ = dilate(base, name="clock_ring_glyphs", glyphs="8:")
    assert set(ring.glyphs) == {"8", ":"}
    for char in "8:":
        tile, left, top = _tile(base, char)
        expected = Image.new("L", (80, 80), 0)
        for dx, dy in ((0, 0), *RING_OFFSETS):
            shifted = Image.new("L", expected.size, 0)
            shifted.paste(tile, (20 + left + dx, 20 + top + dy))
            expected = ImageChops.lighter(expected, shifted)
        ring_tile, ring_left, ring_top = _tile(ring, char)
        actual = Image.new("L", expected.size, 0)
        actual.paste(ring_tile, (20 + ring_left, 20 + ring_top))
        assert ImageChops.difference(actual, expected).getbbox() is None, char
        assert ring.glyphs[char].xadvance == base.glyphs[char].xadvance
    assert (ring.line_height, ring.base) == (base.line_height, base.base)


_HEAD = f"""
format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm]
resources:
  fonts:
    clock: {{source: {TTF}, size: 20%r}}
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
    ring: "#FFFF00"
elements:
"""


def _view(text: str, write_design, tmp_path):
    project = generate_for_targets(write_design(_HEAD + text), tmp_path / "out")
    files = project.files()
    return files, next(body for name, body in files.items() if name.endswith("View.mc"))


def test_ringed_baked_text_draws_its_ring_from_the_ring_font(write_design, tmp_path):
    files, view = _view("""
  time:
    type: text
    text: "12:34"
    font: font.clock
    at: {anchor: center}
    color: color.fg
    outline: color.ring
""", write_design, tmp_path)
    method = view.split("private function drawTime")[1].split("\n    }")[0]
    assert "var ringFont = _fontClockRingGlyphs;" in method
    assert "offsets" not in method  # no stamp
    assert method.index("ringFont") < method.rindex("Palette.FG")
    fonts = files["resources-fenix8solar47mm/fonts/fonts.xml"]
    # the ring font holds only what the ringed text draws
    assert 'id="FontClockRingGlyphs"' in fonts and 'filter="1234:"' in fonts
    assert "_fontClockRingGlyphs = WatchUi.loadResource(Rez.Fonts.FontClockRingGlyphs)" in view


def test_system_font_text_still_stamps(write_design, tmp_path):
    """No sheet to dilate: a device's own `FONT_*` keeps the stamp."""
    _, view = _view("""
  time:
    type: text
    text: "12:34"
    font: FONT_SMALL
    at: {anchor: center}
    color: color.fg
    outline: color.ring
""", write_design, tmp_path)
    method = view.split("private function drawTime")[1].split("\n    }")[0]
    assert "Layout.TIME_X - 1" in method and "ringFont" not in method


def test_unringed_text_bakes_no_ring_font(write_design, tmp_path):
    files, view = _view("""
  time:
    type: text
    text: "12:34"
    font: font.clock
    at: {anchor: center}
    color: color.fg
""", write_design, tmp_path)
    assert "RingGlyphs" not in files["resources-fenix8solar47mm/fonts/fonts.xml"]
    assert "RingGlyphs" not in view


def test_a_group_members_text_uses_the_ring_font_in_its_ring_pass(write_design, tmp_path):
    _, view = _view("""
  g:
    type: group
    outline: color.ring
    children:
      time:
        type: text
        text: "12:34"
        font: font.clock
        at: {anchor: center}
        color: color.fg
""", write_design, tmp_path)
    ring = view.split("private function ringTime")[1].split("\n    }")[0]
    assert "var ringFont = _fontClockRingGlyphs;" in ring
    assert "dc.setColor(ringColor, Graphics.COLOR_TRANSPARENT);" in ring


def test_the_ring_fonts_glyphs_are_the_union_over_ringed_runs(write_design, bag):
    face = load_face(_HEAD + """
  a: {type: text, text: "12", font: font.clock, at: {anchor: center}, color: color.fg,
      outline: color.ring}
  b: {type: text, text: "39", font: font.clock, at: {anchor: center, dy: 20%}, color: color.fg,
      outline: color.ring}
  c: {type: text, text: "7", font: font.clock, at: {anchor: center, dy: -20%}, color: color.fg}
""", write_design, bag)
    assert kinds.ring_fonts(face) == {"clock_ring_glyphs": ("clock", frozenset("1239"))}


def test_a_baked_ring_in_a_partial_update_is_not_reported(write_design, db):
    """One extra draw, not four: the lint's stamp warning does not apply."""
    text = _HEAD.replace("[fenix8solar47mm]", "[fr955]") + """
  secs:
    type: text
    text: "{time.second:02d}"
    font: FONT
    at: {anchor: center}
    color: color.fg
    outline: color.ring
    sleep_update: true
"""
    baked = lint_text(text.replace("FONT", "font.clock"), write_design, db, "fr955")
    stamped = lint_text(text.replace("FONT", "FONT_SMALL"), write_design, db, "fr955")
    assert not [d for d in baked.items if d.code == "partial-update-budget"], baked.render()
    assert [d for d in stamped.items if d.code == "partial-update-budget"]
