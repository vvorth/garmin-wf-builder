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


def test_resolve_codepoint_no_longer_accepts_a_pasted_character():
    """The pasted-character escape hatch is gone; `glyph: "U+XXXX"` replaced it.

    A character in the font that the catalogue does not name used to resolve
    to itself.  It now does not: the codepoint spelling is greppable, visible
    in a diff, and survives a copy-paste -- and a paste that silently fails
    still parses as valid YAML, which is exactly the hazard
    `wfb.icon_catalog`'s docstring bans for this project's own source.
    """
    # fa-question (U+F128) is in the vendored font and is not in CATALOG.
    raw = "\uf128"
    assert raw not in {i.codepoint for i in icons.CATALOG.values()}
    assert icons.font_has(raw), "still reachable, but only through glyph:"
    assert icons.resolve_codepoint(raw) is None


def test_resolve_codepoint_rejects_a_character_the_font_does_not_have():
    assert icons.resolve_codepoint("\uffff") is None


def test_resolve_codepoint_rejects_plain_ascii():
    """A single ASCII letter is almost certainly a typo of a catalogue name."""
    assert icons.resolve_codepoint("h") is None
    assert icons.resolve_codepoint("") is None


def test_resolve_codepoint_rejects_a_multi_character_name():
    assert icons.resolve_codepoint("notacatalogname") is None


# -- ink-height compensation across icon sets --------------------------------


def test_bake_size_normalizes_ink_height_across_icon_sets():
    """The whole point of `bake_size`: two icons from differently-padded icon
    sets (Material Design Icons vs. Font Awesome) declared at the same `size:`
    must end up visually the same height, even though they need different
    nominal font sizes to get there."""
    target = 12
    heart = icons.CATALOG["heart"].codepoint  # Material Design Icons
    steps = icons.CATALOG["steps"].codepoint  # Font Awesome
    heart_size = icons.bake_size(heart, target)
    steps_size = icons.bake_size(steps, target)
    assert icons._ink_height(heart, heart_size) == pytest.approx(target, abs=1)
    assert icons._ink_height(steps, steps_size) == pytest.approx(target, abs=1)


def test_bake_size_is_not_always_the_declared_size():
    """Material Design Icons pads more inside its em-square than Font Awesome
    did, so hitting the same visual height needs a *larger* nominal font size
    -- this is the direction of the original "icons are too small" report."""
    heart = icons.CATALOG["heart"].codepoint
    assert icons.bake_size(heart, 12) > 12


def test_bake_size_handles_a_non_positive_target():
    assert icons.bake_size(icons.CATALOG["heart"].codepoint, 0) == 1


def test_font_key_is_stable_across_devices():
    """The generated view class is shared across every target device, so an
    icon's font *identifier* must not depend on the device -- only the pixel
    content baked under that identifier does.  Keying by the resolved pixel
    value instead reproduces exactly this bug: two screen sizes resolve `8%r`
    to two different pixel counts, so the shared view would reference a font
    symbol that exists on only one device's resource bundle."""
    heart = icons.CATALOG["heart"].codepoint
    a = icons.font_key(Length.parse("8%r"), heart)
    b = icons.font_key(Length.parse("8%r"), heart)
    assert a == b
    assert a != icons.font_key(Length.parse("9%r"), heart)
    assert a != icons.font_key(Length.parse("8px"), heart)  # same number, different unit


def test_font_key_also_depends_on_the_glyph():
    """Two icons declared at the same `size:` do not necessarily bake at the
    same nominal font size any more (`bake_size` compensates per glyph), so
    they cannot always share one font resource the way they could when
    `size:` and nominal size were the same number."""
    length = Length.parse("9%r")
    assert (
        icons.font_key(length, icons.CATALOG["heart"].codepoint)
        != icons.font_key(length, icons.CATALOG["flame"].codepoint)
    )


def test_font_key_is_a_valid_monkey_c_identifier_fragment():
    for spec in ("8%r", "24px", "0.5%r", "-3px"):
        key = icons.font_key(Length.parse(spec), icons.CATALOG["heart"].codepoint)
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
    # pure function of both, so this is the same lookup the resolver does.
    probe = next(e for e in face.walk() if e.id == "probe")
    font = baked[icons.font_key(probe.size, probe.codepoint)]
    assert probe.codepoint in font.glyphs, f"{name!r}'s glyph is missing from its own baked font"

    resolved = resolve(face, device, baked)
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False))
    colors = set(image.get_flattened_data())
    assert (255, 255, 255) in colors, f"icon {name!r} drew nothing in the preview"


# -- weather-condition and data-source-alias tables -------------------------


def test_every_condition_value_zero_to_fifty_three_is_covered():
    """`Toybox.Weather.CONDITION_*` is 0-53 -- a gap here would be a silent
    "unknown" for a real, documented condition."""
    assert set(icons.GARMIN_WEATHER_CONDITION_ICON) == set(range(54))


def test_every_condition_maps_to_a_real_catalogue_name():
    """`GARMIN_WEATHER_CONDITION_ICON` names a `CATALOG` entry directly --
    there is no separate weather-only table any more (one catalogue, ADR-style
    "icons are icons")."""
    for condition, name in icons.GARMIN_WEATHER_CONDITION_ICON.items():
        assert name in icons.CATALOG, f"condition {condition} -> unknown icon {name!r}"
        assert name.startswith("weather_")


def test_every_night_variant_has_a_matching_day_entry():
    for name in icons.names():
        if name.endswith("_night"):
            day_name = name[: -len("_night")]
            assert day_name in icons.CATALOG, f"{name!r} has no day counterpart {day_name!r}"


def test_weather_icon_for_condition_resolves_day_and_night():
    day = icons.weather_icon_for_condition(3)  # CONDITION_RAIN
    night = icons.weather_icon_for_condition(3, night=True)
    assert day == icons.CATALOG["weather_rain"].codepoint
    assert night == icons.CATALOG["weather_rain_night"].codepoint
    assert day != night


def test_weather_icon_for_condition_falls_back_for_no_night_variant():
    """`strong_wind` has no night glyph -- night=True should still resolve,
    to the day glyph, not raise."""
    assert "weather_strong_wind_night" not in icons.CATALOG
    assert (icons.weather_icon_for_condition(36, night=True)
            == icons.CATALOG["weather_strong_wind"].codepoint)


def test_weather_icon_for_condition_handles_unknown_and_none():
    unknown = icons.CATALOG["weather_unknown"].codepoint
    assert icons.weather_icon_for_condition(53) == unknown  # CONDITION_UNKNOWN
    assert icons.weather_icon_for_condition(None) == unknown


def test_metric_icon_values_all_resolve_in_the_catalogue():
    for source, name in icons.METRIC_ICON.items():
        assert icons.get(name) is not None, f"METRIC_ICON[{source!r}] names {name!r}, not in CATALOG"


def test_icon_for_source_returns_the_aliased_icon():
    assert icons.icon_for_source("activity.steps") is icons.CATALOG["steps"]
    assert icons.icon_for_source("heart_rate.current") is icons.CATALOG["heart"]


def test_icon_for_source_returns_none_for_an_unaliased_source():
    assert icons.icon_for_source("activity.step_goal") is None


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
    assert "glyph:" in notes  # and the escape hatch for a name it does not have


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


# -- `glyph:`, the explicit codepoint escape hatch --------------------------


def test_a_codepoint_parses_in_unicode_notation():
    from wfb import icons

    assert icons.parse_codepoint("U+F0BC") == ""
    assert icons.parse_codepoint("u+f0bc") == ""          # case-insensitive
    assert icons.parse_codepoint("  U+F0BC  ") == ""      # surrounding space
    assert icons.parse_codepoint("U+F02D1") == "\U000f02d1"     # above the BMP


def test_anything_that_is_not_that_notation_is_not_a_codepoint():
    """`None` means "not this spelling", which the caller reports differently
    from "this codepoint is not in the font" -- they are different mistakes."""
    from wfb import icons

    for text in ("F0BC", "0xF0BC", "U+ZZZZ", "U+", "steps", ""):
        assert icons.parse_codepoint(text) is None, text


def test_an_out_of_range_codepoint_is_rejected_rather_than_raising():
    from wfb import icons

    assert icons.parse_codepoint("U+110000") is None  # past the last code point


def test_name_for_codepoint_finds_a_catalogue_duplicate():
    from wfb import icons

    assert icons.name_for_codepoint(icons.CATALOG["steps"].codepoint) == "steps"
    assert icons.name_for_codepoint("A") is None
