"""Colour parsing and the 64-colour MIP palette rule."""

import pytest

from wfb.palette import MIP64_LEVELS, Color, ColorError


@pytest.mark.parametrize("raw,value", [
    ("#FF5500", 0xFF5500), ("FF5500", 0xFF5500), ("#f50", 0xFF5500),
    (0x00AA55, 0x00AA55),
])
def test_parsing(raw, value):
    assert Color.parse(raw).value == value


@pytest.mark.parametrize("raw", ["#GGGGGG", "orange", "#FF55", None, True])
def test_rejects_nonsense(raw):
    with pytest.raises(ColorError):
        Color.parse(raw)


@pytest.mark.parametrize("hexcode,legal", [
    ("#000000", True), ("#FFFFFF", True), ("#FF5500", True), ("#55AAFF", True),
    ("#FF5501", False), ("#123456", False), ("#808080", False),
])
def test_mip64_legality(hexcode, legal):
    """Each channel must be 0x00/0x55/0xAA/0xFF or the firmware dithers it."""
    assert Color.parse(hexcode).is_palette_legal(64) is legal


def test_nearest_legal_snaps_every_channel():
    nearest = Color.parse("#808080").nearest_legal(64)
    assert all(channel in MIP64_LEVELS for channel in (nearest.r, nearest.g, nearest.b))


def test_unknown_palette_size_is_not_checked():
    """A confident wrong answer is worse than no answer (ADR 0008)."""
    assert Color.parse("#123456").is_palette_legal(None) is True


def test_contrast_ratio_matches_wcag_endpoints():
    black, white = Color.parse("#000000"), Color.parse("#FFFFFF")
    assert white.contrast_ratio(black) == pytest.approx(21.0)
    assert white.contrast_ratio(white) == pytest.approx(1.0)
