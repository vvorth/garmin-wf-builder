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
from wfb.emit.resources import bake_fonts, build_bundle


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
    baked = bake_fonts(face, device, device.minor_radius)
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
