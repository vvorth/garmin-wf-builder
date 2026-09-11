"""Colour parsing and the 64-colour MIP palette rule."""

import pytest

from tests.test_diagnostics import load
from wfb.palette import MIP64_LEVELS, Color, ColorError

HEAD = """format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
"""

BODY = """elements:
  - id: dot
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%
    color: palette.bg
"""


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


# -- the long form: `name: {value, label}` --------------------------------


def test_long_form_entry_is_accepted_and_records_its_label(write_design, bag):
    text = HEAD + 'palette:\n  bg: { value: "#00FFFF", label: "Aqua" }\n' + BODY
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    assert face.palette["bg"] == Color.parse("#00FFFF")
    assert face.palette_labels == {"bg": "Aqua"}


def test_long_form_with_no_label_gets_no_palette_label(write_design, bag):
    text = HEAD + 'palette:\n  bg: { value: "#00FFFF" }\n' + BODY
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    assert face.palette["bg"] == Color.parse("#00FFFF")
    assert face.palette_labels == {}


def test_short_and_long_form_agree_on_colour(write_design, bag):
    short = load(write_design(HEAD + 'palette:\n  bg: "#00FFFF"\n' + BODY), bag)
    assert short is not None, bag.render()

    bag2_text = HEAD + 'palette:\n  bg: { value: "#00FFFF" }\n' + BODY
    from wfb.diagnostics import Bag
    bag2 = Bag()
    long_ = load(write_design(bag2_text, "face2.yaml"), bag2)
    assert long_ is not None, bag2.render()
    assert short.palette["bg"] == long_.palette["bg"]


def test_long_form_missing_value_is_a_schema_error_on_the_entrys_own_line(write_design, bag):
    text = HEAD + 'palette:\n  bg: { label: "Aqua" }\n' + BODY
    face = load(write_design(text), bag)
    assert face is None
    errors = [d for d in bag.items if d.severity.value == "error"]
    assert any(d.code == "schema" for d in errors)
    schema_error = next(d for d in errors if d.code == "schema")
    assert schema_error.span is not None
    lines = text.splitlines()
    assert "bg:" in lines[schema_error.span.line - 1]


def test_long_form_entry_may_not_reference_config(write_design, bag):
    text = HEAD + 'palette:\n  bg: { value: config.accent_color }\n' + BODY
    face = load(write_design(text), bag)
    assert face is None
    errors = [d for d in bag.items if d.severity.value == "error"]
    assert any(d.code == "palette" for d in errors)
    note = " ".join(n for d in errors for n in d.notes)
    assert "color: config.accent_color" in note


def test_a_rejected_long_form_palette_entry_does_not_cascade(write_design, bag):
    """The same cascade fix `rejected_fonts`/`rejected_config` exist for:

    the design's own `color: palette.bg` should not add a second "unknown
    data source" error on top of the real one against the `palette:` block.
    """
    text = HEAD + 'palette:\n  bg: { value: config.accent_color }\n' + BODY
    face = load(write_design(text), bag)
    assert face is None
    errors = [d for d in bag.items if d.severity.value == "error"]
    assert [d.code for d in errors] == ["palette"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))
