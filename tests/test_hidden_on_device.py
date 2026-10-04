"""An element a device does not draw is one `ResolvedFace.hidden` entry,
whatever hides it: `anchor: subscreen` on a device without the window, or a
`face:` font that resolves no face there under `unsupported: hide`.
Every consumer -- the per-device lints, the preview, the hold regions --
reads that one map, so a font-hidden text is no longer linted, or held,
where nothing draws it."""

from __future__ import annotations

import pytest

from tests.helpers import find, load_face
from wfb.build import resolve_all
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.resources import bake_fonts

#: Publishes `BionicSemiBold`; has `onPress`.
DRAWN = "fenix8solar47mm"
#: Has `getVectorFont` and `onPress`, but not `BionicSemiBold`.
LACKS_FACE = "fr955"
#: Has the subscreen, but no `getVectorFont` at all.
INSTINCT = "instinct2"

DESIGN = """
format: 2
face:
  id: 5a4b3c2d-1e0f-4a9b-8c7d-6e5f4a3b2c1d
  name: Hidden
build:
  targets: [TARGETS]
resources:
  fonts:
    bezel:
      face: BionicSemiBold
      size: 6%r
      unsupported: hide
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
elements:
  badge:
    type: text
    text: "SOLAR"
    font: font.bezel
    at: {anchor: top}
    color: color.fg
    on_hold: battery
"""


def _need(db, *device_ids):
    for device_id in device_ids:
        if device_id not in db.ids():
            pytest.skip(f"{device_id} not installed")


def _resolve(write_design, db, text: str, device_ids):
    _need(db, *device_ids)
    bag = Bag()
    face = load_face(text.replace("TARGETS", ", ".join(device_ids)), write_design, bag)
    devices = [db.get(d) for d in device_ids]
    resolved, _ = resolve_all(face, devices, bag)
    return face, devices, resolved, bag


def _codes_on(bag: Bag, element_id: str) -> set[str]:
    return {d.code for d in bag.items if d.message.startswith(f"{element_id}:")
            or d.message.startswith(f"{element_id} ")}


def test_a_font_hidden_text_is_one_hidden_entry(write_design, db):
    _, _, resolved, _ = _resolve(write_design, db, DESIGN, (DRAWN, LACKS_FACE))
    assert dict(resolved[LACKS_FACE].hidden) == {"badge": "font-unavailable"}
    assert dict(resolved[DRAWN].hidden) == {}


def test_a_font_hidden_text_is_not_linted_where_it_does_not_draw(write_design, db):
    """`at: {anchor: top}` centres the badge on the top edge, so half of it
    is off the framebuffer: `off-screen` where it draws (the premise), and
    nothing at all where the font hides it."""
    _, _, _, drawn_bag = _resolve(write_design, db, DESIGN, (DRAWN,))
    assert "off-screen" in _codes_on(drawn_bag, "badge"), drawn_bag.render()
    _, _, _, hidden_bag = _resolve(write_design, db, DESIGN, (LACKS_FACE,))
    assert not _codes_on(hidden_bag, "badge") & {"off-screen", "text-overflow", "safe-area"}, \
        hidden_bag.render()


def test_a_font_hidden_hold_region_is_empty(write_design, db):
    """The generated `onPress` tests only these constants: a region left in
    place would launch the battery app from a strip where nothing draws."""
    face, devices, resolved, _ = _resolve(write_design, db, DESIGN, (DRAWN, LACKS_FACE))
    out = write_design(DESIGN).parent / "out"
    files = generate(face, devices, out, {d.id: bake_fonts(face, d) for d in devices},
                     resolved=resolved).files()
    assert "const BADGE_HOLD_WIDTH as Number = 0;" in files[f"source-{LACKS_FACE}/Layout.mc"]
    drawn_width = find(resolved[DRAWN], "badge").box.width
    assert drawn_width > 0
    assert (f"const BADGE_HOLD_WIDTH as Number = {drawn_width};"
            in files[f"source-{DRAWN}/Layout.mc"])


def test_the_font_lint_leaves_out_a_device_the_subscreen_hides(write_design, db):
    """On fr955 the badge is hidden by the missing subscreen, which
    `check_subscreen_availability` reports; its font failing there too is
    not a second finding. On instinct2 the window exists and only the font
    hides it."""
    text = (DESIGN.replace("at: {anchor: top}", "at: {anchor: subscreen}")
            .replace("    on_hold: battery\n", """    unsupported: hide
"""))
    _, _, resolved, bag = _resolve(write_design, db, text, (INSTINCT, LACKS_FACE))
    assert dict(resolved[LACKS_FACE].hidden) == {"badge": "subscreen"}
    assert dict(resolved[INSTINCT].hidden) == {"badge": "font-unavailable"}
    font = [d for d in bag.items if d.code == "font-unavailable"]
    assert len(font) == 1, bag.render()
    assert INSTINCT in font[0].message and LACKS_FACE not in font[0].message


# -- what the resolve records against a hidden element ------------------------

#: AMOLED, no subscreen, and no pixel metrics for `FONT_SYSTEM_LARGE`.
NO_METRICS = "fenix847mm"

SUBSCREEN_TEXT = """
format: 2
face:
  id: 5a4b3c2d-1e0f-4a9b-8c7d-6e5f4a3b2c1d
  name: Hidden
build:
  targets: [TARGETS]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
elements:
  level:
    type: text
    text: "42"
    font: FONT_SYSTEM_LARGE
    at: {anchor: subscreen}
    color: color.fg
    unsupported: hide
  tick:
    type: rectangle
    at: {anchor: subscreen}
    size: {width: 0.1%r, height: 10px}
    min_1px: false
    color: color.fg
    unsupported: hide
"""


def _drawn(text: str) -> str:
    """The same design with nothing anchored to the subscreen."""
    return (text.replace("at: {anchor: subscreen}", "at: {anchor: center}")
            .replace("""    unsupported: hide
""", ""))


def _metrics_notes(bag: Bag) -> list:
    return [d for d in bag.items if d.code == "metrics" and d.message.startswith("level:")]


def test_no_metrics_note_where_the_element_is_hidden(write_design, db):
    """The premise: where `level` draws, the missing metrics are a note."""
    drawn = _drawn(SUBSCREEN_TEXT)
    _, _, _, bag = _resolve(write_design, db, drawn, (NO_METRICS,))
    assert _metrics_notes(bag), bag.render()
    _, _, _, bag = _resolve(write_design, db, SUBSCREEN_TEXT, (NO_METRICS,))
    assert not _metrics_notes(bag), bag.render()


def test_a_metrics_note_is_on_its_element_s_line(write_design, db):
    drawn = _drawn(SUBSCREEN_TEXT)
    face, _, _, bag = _resolve(write_design, db, drawn, (NO_METRICS,))
    [note] = _metrics_notes(bag)
    level = next(e for e in face.elements if e.id == "level")
    assert note.span is not None and note.span == level.span


def test_no_sub_pixel_finding_where_the_element_is_hidden(write_design, db):
    """0.1%r is under a pixel on both devices; only the one that draws
    `tick` may say so."""
    _, _, _, bag = _resolve(write_design, db, SUBSCREEN_TEXT, (INSTINCT, NO_METRICS))
    findings = [d for d in bag.items if d.code == "sub-pixel-length"]
    assert findings, bag.render()
    assert all(INSTINCT in d.message and NO_METRICS not in d.message for d in findings), \
        bag.render()
