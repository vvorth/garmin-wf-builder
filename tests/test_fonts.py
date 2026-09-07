"""Baking a TrueType source into a Connect IQ bitmap font."""

import pytest

from wfb.fonts import bake


@pytest.fixture(scope="module")
def source(pytestconfig):
    path = pytestconfig.rootpath / "examples/slice/assets/OpenSans-Regular.ttf"
    if not path.exists():
        pytest.skip("the example font is not vendored")
    return path


def test_only_the_requested_glyphs_are_baked(source):
    """Subsetting is the point: a large font carries eleven glyphs, not a charset."""
    font, _ = bake(source, name="clock", size=48, glyphs="0123456789:")
    assert set(font.glyphs) == set("0123456789:")


def test_duplicate_glyphs_are_collapsed(source):
    font, _ = bake(source, name="clock", size=24, glyphs="00112233")
    assert set(font.glyphs) == set("0123")


def test_metrics_are_measured_not_guessed(source):
    font, _ = bake(source, name="clock", size=48, glyphs="0123456789:")
    width, height = font.measure("23:59")
    assert width == sum(font.glyphs[c].xadvance for c in "23:59")
    assert height == font.line_height
    assert font.base < font.line_height


def test_missing_reports_exactly_what_is_absent(source):
    font, _ = bake(source, name="clock", size=24, glyphs="0123456789")
    assert font.missing("12:30") == {":"}
    assert font.missing("1230") == set()


def test_fnt_is_the_bmfont_text_format(source):
    font, _ = bake(source, name="clock", size=32, glyphs="012")
    text = font.to_fnt()
    assert text.startswith("info face=")
    assert "unicode=1" in text
    assert 'page id=0 file="clock.png"' in text
    assert "chars count=3" in text
    assert text.count("\nchar id=") == 3
    assert "kernings count=0" in text


def test_glyph_boxes_stay_inside_the_sheet(source):
    font, sheet = bake(source, name="clock", size=64, glyphs="0123456789:.-")
    assert sheet.size == (font.sheet_width, font.sheet_height)
    for glyph in font.glyphs.values():
        assert glyph.x + glyph.width <= font.sheet_width
        assert glyph.y + glyph.height <= font.sheet_height


def test_glyphs_do_not_overlap_on_the_sheet(source):
    font, _ = bake(source, name="clock", size=40, glyphs="0123456789:")
    boxes = [
        (g.x, g.y, g.x + g.width, g.y + g.height)
        for g in font.glyphs.values() if g.width and g.height
    ]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            overlaps = a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
            assert not overlaps, f"{a} overlaps {b}"


def test_one_bit_by_default_and_antialiased_on_request(source):
    """Bitmap fonts default to 1-bit because anti-aliasing costs runtime RAM."""
    plain, sheet_plain = bake(source, name="c", size=48, glyphs="8", antialias=False)
    smooth, sheet_smooth = bake(source, name="c", size=48, glyphs="8", antialias=True)
    assert set(sheet_plain.get_flattened_data()) <= {0, 255}
    assert len(set(sheet_smooth.get_flattened_data())) > 2
    assert "smooth=0" in plain.to_fnt() and "smooth=1" in smooth.to_fnt()


def test_an_empty_glyph_set_is_rejected(source):
    with pytest.raises(ValueError):
        bake(source, name="clock", size=24, glyphs="")


# -- rasterisation symmetry -------------------------------------------------


def _mirror_asymmetry(sheet, glyph) -> float:
    """Fraction of a glyph's ink pixels that break left/right mirror symmetry."""
    from PIL import Image

    tile = sheet.crop((glyph.x, glyph.y, glyph.x + glyph.width, glyph.y + glyph.height))
    flipped = tile.transpose(Image.FLIP_LEFT_RIGHT)
    a, b = list(tile.get_flattened_data()), list(flipped.get_flattened_data())
    ink = sum(1 for v in a if v) or 1
    return sum(1 for x, y in zip(a, b) if x != y) / ink


#: Glyph names in the vendored icon font that are mirror-symmetric by design --
#: verified by rendering each at 256px, where the pixel grid is far finer than
#: the shape and the rasteriser cannot be what breaks it.
SYMMETRIC_GLYPHS = ("md-square", "md-circle", "md-circle_outline", "md-record")


def _codepoint(name: str) -> str:
    from fontTools.ttLib import TTFont

    from wfb import icons

    for code, glyph_name in TTFont(icons.FONT_PATH).getBestCmap().items():
        if glyph_name == name:
            return chr(code)
    raise AssertionError(f"{name} is not in the vendored font")


@pytest.mark.parametrize("glyph_name", SYMMETRIC_GLYPHS)
@pytest.mark.parametrize("size", [8, 10, 12, 14, 16, 20, 24])
def test_a_symmetric_glyph_rasterises_symmetrically(glyph_name, size):
    """A round icon must come out round.

    Rendering straight to the target size asks FreeType to fit an outline to
    the pixel grid at single-digit sizes, and its hinting broke the shape's own
    symmetry badly: a plain square baked to 7x7 ink inside an 8x8 tile, and
    `md-circle_outline` at 16px was lopsided in every row -- 16.8% of ink
    pixels landed asymmetrically across 99 provably-symmetric glyphs. The
    supersampling in `wfb.fonts.bmfont` exists for this, and the threshold
    below is what stops it regressing.
    """
    from wfb import icons
    from wfb.fonts import bake

    char = _codepoint(glyph_name)
    baked, sheet = bake(icons.FONT_PATH, name="probe", size=size, glyphs=char)
    glyph = baked.glyphs[char]
    if not glyph.width:
        pytest.skip(f"{glyph_name} has no ink at {size}px")
    assert _mirror_asymmetry(sheet, glyph) <= 0.05


def test_lowering_the_supersample_factor_would_be_caught():
    """The factor was measured, not guessed.

    Guards the constant directly rather than restating the symmetry test:
    below 8x the measured asymmetry roughly doubles (1.8% at 8x, 4.5% at 4x),
    and at 1x -- rendering straight to the target size, which is what this
    replaced -- it is 16.8%.
    """
    from wfb.fonts import bmfont

    assert bmfont.SUPERSAMPLE >= 8
