"""The icon catalogue.

An icon is a single glyph from the vendored icon font
(``wfb/assets/icons/SymbolsNerdFont-Regular.ttf``), baked into a BMFont sheet at
build time by the same pipeline that bakes an author's own custom text font.
Drawing an icon is therefore drawing text -- one ``drawText`` call against a
baked bitmap font -- so there is no per-icon Monkey C to keep in sync with the
catalogue the way an earlier, hand-drawn-primitives version of this module had.

What *does* still need to agree with itself: every catalogue codepoint must be
a real glyph in the vendored font, :mod:`wfb.layout` and :mod:`wfb.preview` must
resolve the same font for the same element (the anti-drift property the rest of
the pipeline has), and an icon actually has to draw a visible pixel somewhere,
both on device and in preview.
"""

from __future__ import annotations

import re

import pytest

from wfb import icons
from wfb.units import Length


def test_every_catalogue_codepoint_is_a_real_glyph():
    """A name whose codepoint the vendored font does not contain would bake an
    empty tile and draw nothing, silently."""
    for icon in icons.CATALOG.values():
        assert icon.codepoint in icons._available_glyphs(), (
            f"{icon.name!r} names U+{ord(icon.codepoint):04X}, which "
            f"{icons.FONT_PATH.name} does not contain"
        )


def test_names_are_unique_and_lowercase():
    for name in icons.names():
        assert name == name.lower()
        assert re.match(r"^[a-z][a-z_]*$", name)


def test_get_returns_none_for_an_unknown_name():
    assert icons.get("nonexistent") is None


def test_resolve_codepoint_finds_catalogue_entries():
    assert icons.resolve_codepoint("heart") == icons.CATALOG["heart"].codepoint


def test_resolve_codepoint_accepts_a_raw_glyph_from_the_font():
    """The escape hatch: any of the font's ~10,000 glyphs, not just the six
    maintained names, by pasting the character directly."""
    # fa-question (U+F128) is in the vendored font and is not in CATALOG.
    raw = ""
    assert raw not in {i.codepoint for i in icons.CATALOG.values()}
    assert icons.resolve_codepoint(raw) == raw


def test_resolve_codepoint_rejects_a_character_the_font_does_not_have():
    assert icons.resolve_codepoint("￿") is None


def test_resolve_codepoint_rejects_plain_ascii():
    """A single ASCII letter is not a raw-glyph request -- it is almost
    certainly a typo of a catalogue name, and the font has no ASCII glyphs at
    all (it is an icon-only "Symbols" build) to fall back to."""
    assert icons.resolve_codepoint("h") is None
    assert icons.resolve_codepoint("") is None


def test_resolve_codepoint_rejects_a_multi_character_name():
    assert icons.resolve_codepoint("notacatalogname") is None


@pytest.mark.parametrize(
    "spec,minor_radius,expected",
    [("8%r", 130.0, 10), ("24px", 130.0, 24), ("50%r", 200.0, 100)],
)
def test_pixel_size_resolves_px_and_percent_r(spec, minor_radius, expected):
    assert icons.pixel_size(Length.parse(spec), minor_radius) == expected


def test_pixel_size_has_a_default_for_an_unset_size():
    assert icons.pixel_size(None, 130.0) == 24


def test_font_key_is_stable_across_devices():
    """The generated view class is shared across every target device, so an
    icon's font *identifier* must not depend on the device -- only the pixel
    content baked under that identifier does.  Keying by the resolved pixel
    value instead reproduces exactly this bug: two screen sizes resolve `8%r`
    to two different pixel counts, so the shared view would reference a font
    symbol that exists on only one device's resource bundle."""
    a = icons.font_key(Length.parse("8%r"))
    b = icons.font_key(Length.parse("8%r"))
    assert a == b
    assert a != icons.font_key(Length.parse("9%r"))
    assert a != icons.font_key(Length.parse("8px"))  # same number, different unit


def test_font_key_is_a_valid_monkey_c_identifier_fragment():
    for spec in ("8%r", "24px", "0.5%r", "-3px"):
        key = icons.font_key(Length.parse(spec))
        assert re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", key), key


# -- integration: baking, layout and preview all agree -----------------------


@pytest.mark.parametrize("name", icons.names())
def test_every_icon_bakes_resolves_and_renders(name, tmp_path, bag, db):
    """One design per catalogue icon: it must validate, resolve to a font
    that actually contains the glyph, and draw a visible pixel in preview."""
    from tests.test_diagnostics import load
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve
    from wfb.preview import PreviewOptions, render

    design = f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: [fenix8solar47mm]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
elements:
  - id: bg
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
  - id: probe
    type: icon
    icon: {name}
    size: 20%r
    at: {{anchor: center}}
    color: palette.fg
"""
    path = tmp_path / "face.yaml"
    path.write_text(design, encoding="utf-8")
    face = load(path, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = bake_fonts(face, device, device.minor_radius)

    # The IR element carries `size` (a Length) and `codepoint`; `font_key` is a
    # pure function of the former, so this is the same lookup the resolver does.
    probe = next(e for e in face.walk() if e.id == "probe")
    font = baked[icons.font_key(probe.size)]
    assert probe.codepoint in font.glyphs, f"{name!r}'s glyph is missing from its own baked font"

    resolved = resolve(face, device, baked)
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False))
    colors = set(image.get_flattened_data())
    assert (255, 255, 255) in colors, f"icon {name!r} drew nothing in the preview"


def test_an_unknown_icon_name_is_a_build_error_not_a_silent_blank(write_design, bag, db):
    from tests.test_diagnostics import load

    face = load(write_design("""
format: 1
face: {id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}
targets: [fenix8solar47mm]
palette: {bg: "#000000", fg: "#FFFFFF"}
elements:
  - id: bg
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
  - id: probe
    type: icon
    icon: not-a-real-icon
    size: 20%r
    at: {anchor: center}
    color: palette.fg
"""), bag)
    assert face is None
    assert any(d.code == "icon" for d in bag.errors)
    notes = " ".join(n for d in bag.errors for n in d.notes)
    assert "heart" in notes  # the catalogue is listed
    assert "vendored icon font" in notes  # and the raw-glyph escape hatch


def test_percent_size_is_rejected_with_an_explanation(write_design, bag):
    """`%` depends on the parent box, which is not known until layout runs --
    after the icon font would already need to have been baked."""
    from tests.test_diagnostics import load

    face = load(write_design("""
format: 1
face: {id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}
targets: [fenix8solar47mm]
palette: {bg: "#000000", fg: "#FFFFFF"}
elements:
  - id: bg
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
  - id: probe
    type: icon
    icon: heart
    size: 20%
    at: {anchor: center}
    color: palette.fg
"""), bag)
    assert face is None
    assert any(d.code == "icon" and "%r" in d.message for d in bag.errors)
