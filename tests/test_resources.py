"""`wfb/emit/resources.py`: font resource generation.

Regression coverage for the bug this session fixed: the resource compiler's
`<font filter="...">` attribute is parsed as Java UTF-16 code units, so a
codepoint above the Basic Multilingual Plane (used by several catalogue icons
now -- `heart`, `flame`, `alarm`, `dnd`, `notification`, and more, all
Material Design Icons glyphs) splits into a surrogate pair that matches no
real glyph and fails the build with "does not have characters in the given
filter". `build_bundle` works around it by omitting `filter` for any font that
needs such a glyph. Reproduced directly against a real `monkeyc` build before
this fix existed; these tests check the generated resource XML rather than
re-running the compiler, so they need no Garmin toolchain.
"""

from __future__ import annotations

from tests.test_diagnostics import load
from wfb.emit.resources import bake_fonts, build_bundle, glyph_set


def _fonts_xml(write_design, bag, db, icon_name: str) -> str:
    face = load(write_design(f"""
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
    icon: {icon_name}
    size: 20%r
    at: {{anchor: center}}
    color: palette.fg
"""), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = bake_fonts(face, device)
    bundle = build_bundle(face, device, baked)
    return bundle.files["fonts/fonts.xml"]


def test_a_supplementary_plane_icon_omits_the_filter_attribute(write_design, bag, db):
    """`heart` is md-heart, U+F02D1 -- above the Basic Multilingual Plane."""
    xml = _fonts_xml(write_design, bag, db, "heart")
    assert 'filter="' not in xml
    assert "filter omitted" in xml


def test_a_bmp_only_icon_keeps_the_filter_attribute(write_design, bag, db):
    """`steps` is fa-shoe_prints, U+EE14 -- within the Basic Multilingual
    Plane, so the filter attribute is safe and should still be emitted (it is
    the compiler's own belt-and-suspenders glyph-coverage check)."""
    xml = _fonts_xml(write_design, bag, db, "steps")
    assert 'filter="' in xml
    assert "filter omitted" not in xml


def test_a_literal_string_fallback_extends_the_glyph_set(write_design, bag, db, repo_root):
    """Bug 1: `fallback:` is drawn through the same custom font as the real
    value (see `_emit_text` in `wfb.emit.monkeyc`), so a literal string
    fallback's own characters must be in the subsetted glyph set too.

    `complication.training_status` is a nullable `STRING` source with no known
    digit range, so `formatting.widest`'s worst-case estimate for the *value*
    alone already happens to be several characters wide -- not wide enough,
    though, to coincidentally cover a longer literal fallback like this one,
    and (being digits) it never covers letters at all.  Before this fix,
    `glyph_set` never looked at `element.fallback`, so a font baked for this
    design would be missing the very letters the fallback needs.
    """
    ttf = repo_root / "examples/slice/assets/OpenSans-Regular.ttf"
    face = load(write_design(f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: [fenix8solar47mm]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
fonts:
  small:
    source: {ttf}
    size: 20px
elements:
  - id: bg
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
  - id: status
    type: text
    value: complication.training_status
    font: font.small
    at: {{anchor: center}}
    color: palette.fg
    when_absent: fallback
    fallback: "'Not Available'"
"""), bag)
    assert face is not None, bag.render()
    chars = glyph_set(face)["small"]
    for letter in "Not Available":
        assert letter in chars, f"{letter!r} missing from the subsetted glyph set {chars!r}"


# -- a font's `size:` as a length ---------------------------------------------
#
# `fonts.<name>.size` accepts a `Length` (`12px`, `18%r`) as well as the bare
# number it always took.  These assert the *baked pixel size*, per device --
# the only number that decides what the wearer sees -- rather than checking
# that the YAML parsed.


def _baked_size(write_design, bag, db, repo_root, size: str, device_id: str,
                extra: str = "") -> int:
    """The nominal pixel size `clock` is rasterised at on one device."""
    ttf = repo_root / "examples/slice/assets/OpenSans-Regular.ttf"
    face = load(write_design(f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: [fenix8solar47mm, fenix8solar51mm, fr955]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
fonts:
  clock:
    source: {ttf}
    size: {size}
{extra}
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{{:%H:%M}}"
    font: font.clock
    at: {{anchor: center}}
    color: palette.fg
""", name=f"{device_id}-{size}.yaml".replace("%", "pct")), bag)
    assert face is not None, bag.render()
    device = db.get(device_id)
    return bake_fonts(face, device)["clock"].size


def test_a_percent_r_font_size_bakes_per_device(write_design, bag, db, repo_root):
    """The gate for this feature, asserted rather than eyeballed.

    `fenix8solar47mm` is 260x260, so its minor radius is 130 and 18%r is 23.4
    pixels; `fenix8solar51mm` is 280x280, minor radius 140, and the same
    declaration is 25.2.  `fr955` is 260x260 too, so it must agree with the
    47 mm exactly -- these are two screen sizes, not three.
    """
    def size(device_id):
        return _baked_size(write_design, bag, db, repo_root, "18%r", device_id)

    assert size("fenix8solar47mm") == 23
    assert size("fenix8solar51mm") == 25
    assert size("fr955") == 23


def test_a_px_font_size_is_the_same_on_every_device(write_design, bag, db, repo_root):
    """`px` is verbatim on every device -- the exact effect the removed
    `scale: false` used to give a bare number."""
    for device_id in ("fenix8solar47mm", "fenix8solar51mm", "fr955"):
        assert _baked_size(write_design, bag, db, repo_root, "12px", device_id) == 12


# -- a monospaced font --------------------------------------------------------


def _baked_clock(write_design, bag, db, repo_root, device_id: str, extra: str = ""):
    """The whole `BakedFont` for `clock`, not just its nominal size."""
    ttf = repo_root / "examples/slice/assets/OpenSans-Regular.ttf"
    face = load(write_design(f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: [fenix8solar47mm, fenix8solar51mm, fr955]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
fonts:
  clock:
    source: {ttf}
    size: 30%r
{extra}
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{{:%H:%M}}"
    font: font.clock
    at: {{anchor: center}}
    color: palette.fg
""", name=f"mono-{device_id}-{abs(hash(extra))}.yaml"), bag)
    assert face is not None, bag.render()
    device = db.get(device_id)
    return bake_fonts(face, device)["clock"]


def test_monospace_reaches_the_bake(write_design, bag, db, repo_root):
    """The declaration has to survive the whole way to the rasteriser -- this
    is the seam a `FontSpec` field is easiest to add and forget to pass on."""
    font = _baked_clock(write_design, bag, db, repo_root, "fenix8solar47mm",
                        extra="    monospace: true\n    align: right")
    assert font.monospace and font.cell_width > 0
    assert {g.xadvance for g in font.glyphs.values()} == {font.cell_width}
    for glyph in font.glyphs.values():
        if glyph.width:
            assert glyph.xoffset == font.cell_width - glyph.width


def test_a_font_that_does_not_ask_for_it_is_still_proportional(
        write_design, bag, db, repo_root):
    font = _baked_clock(write_design, bag, db, repo_root, "fenix8solar47mm")
    assert not font.monospace and font.cell_width == 0
    assert font.glyphs[":"].xadvance < font.glyphs["0"].xadvance


def test_icon_fonts_are_never_monospaced(write_design, bag, db, repo_root):
    """An icon font is synthesised, one glyph per resource: a shared cell would
    only pad a single independently-placed glyph."""
    from wfb.emit.resources import icon_font_specs

    face = load(write_design(f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: [fenix8solar47mm]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
elements:
  - id: hr
    type: icon
    icon: heart
    size: 9%r
    at: {{anchor: center}}
    color: palette.fg
"""), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    specs = icon_font_specs(face, device)
    assert specs and all(not spec.monospace for spec in specs.values())
    baked = bake_fonts(face, device)
    assert all(not font.monospace for name, font in baked.items())
