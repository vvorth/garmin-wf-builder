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
