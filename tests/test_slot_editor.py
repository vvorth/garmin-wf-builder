"""The native editor sees every element of a slot.

A slot can be drawn by several elements -- a gauge's ring and a `data`
element's reading -- and the editor must select, highlight and redraw them
as one: `onTap` hit-tests the slot's union box, `drawableFor` builds on the
union highlight, `drawSlot` draws every element, and each element skips
itself while its slot pulses.
"""

from __future__ import annotations

import pytest

from tests.helpers import load_face as _face
from wfb.build import build as real_build
from wfb.diagnostics import Bag
from wfb.emit import generate, monkeyc
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve

DEVICE = "fenix8solar47mm"

HEAD = """format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f60
  name: Test
build:
  targets: [fenix8solar47mm, fenix8solar51mm, fr955]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
    warn: "#FF5500"
config:
  slots:
    top: {default: steps, choices: [date, steps, battery]}
    inner: {default: battery, choices: [battery, body_battery]}
elements:
"""

RING = """  top_ring:
    type: gauge
    slot: top
    style: arc
    at: {anchor: center}
    radius: 46%r
    thickness: 5px
    start_angle: 210deg
    sweep: 300deg
    color: color.fg
    track_color: color.warn
    absent: hide
"""

TEXT = """  top_text:
    type: data
    slot: top
    at: {anchor: center, dy: -20%}
    font: FONT_TINY
    color: color.fg
    absent: "--"
"""

INNER = """  inner_bar:
    type: gauge
    slot: inner
    style: bar
    at: {anchor: center, dy: 15%}
    size: {width: 30%, height: 6px}
    color: color.fg
    absent: hide
"""

#: a reading whose colour reads data, so its draw method takes a reader
COLOURED_TEXT = TEXT.replace("color: color.fg", 'color: "system.battery > 20 ? color.fg : color.warn"')


def _resolved(text, write_design, db):
    face = _face(text, write_design, Bag())
    device = db.get(DEVICE)
    return resolve(face, device, bake_fonts(face, device))


def _body(source: str, signature: str) -> str:
    return source.split(signature)[1].split("\n    }\n")[0]


def test_every_element_of_a_slot_is_drawn_for_the_editor(write_design, db):
    """The old dispatch drew only a slot's first element; the ring drawn
    first would have left the reading undrawn under the highlight."""
    view = monkeyc.emit_view(_resolved(HEAD + RING + TEXT, write_design, db)).text
    body = _body(view, "private function drawSlotTop(dc as Dc) as Void")
    assert body.index("drawTopRing(dc);") < body.index("drawTopText(dc);")
    assert "case 1: drawSlotTop(dc); break;" in _body(
        view, "function drawSlot(dc as Dc, unique as Number) as Void")


def test_a_slot_drawn_only_by_a_gauge_reaches_the_editor(write_design, db):
    text = HEAD + RING
    files = generate(_face(text, write_design, Bag()), [db.get(DEVICE)],
                     write_design(text).parent / "out",
                     {DEVICE: bake_fonts(_face(text, write_design, Bag()), db.get(DEVICE))}).files()
    assert "source/TestSlotDrawable.mc" in files
    assert "source/SlotText.mc" not in files  # no reading to format
    assert "function onTap(" in files["source/TestDelegate.mc"]
    assert "private var _pulsing as Number = 0;" in files["source/TestView.mc"]


def test_a_slot_gauge_skips_itself_while_its_slot_pulses(write_design, db):
    view = monkeyc.emit_view(_resolved(HEAD + RING, write_design, db)).text
    body = _body(view, "private function drawTopRing(dc as Dc) as Void")
    assert body.index("if (_pulsing != 1) {") < body.index("SlotScale.scale")
    assert "return;" not in body  # wrapped: an antialias: restore must still run


def test_the_tap_box_is_every_element_of_the_slot_together(write_design, db):
    resolved = _resolved(HEAD + RING + TEXT, write_design, db)
    ring = next(p for p in resolved.items if p.id == "top_ring")
    text = next(p for p in resolved.items if p.id == "top_text")
    union = ring.box.union(text.box)
    assert union != ring.box and union != text.box, "the premise: neither box alone"
    layout = monkeyc.emit_layout(resolved).text
    for name, value in (("X", union.x), ("Y", union.y),
                        ("WIDTH", union.width), ("HEIGHT", union.height)):
        assert f"const CONFIG_DATA_TOP_BOX_{name} as Number = {value};" in layout


def test_a_slot_inside_a_ring_stays_selectable(write_design, db):
    """The ring's box encloses the inner slot's, so a document-order test
    would always answer `top`; the smallest box holding the touch wins."""
    resolved = _resolved(HEAD + RING + INNER, write_design, db)
    ring = next(p for p in resolved.items if p.id == "top_ring").box
    inner = next(p for p in resolved.items if p.id == "inner_bar").box
    assert ring.union(inner) == ring, "the premise: the ring encloses the bar"
    tap = _body(monkeyc.emit_delegate(resolved).text,
                "function onTap(clickEvent as ClickEvent) as Boolean")
    assert "if (chosen == 0 || area < chosenArea) {" in tap
    assert "var area = Layout.CONFIG_DATA_INNER_BOX_WIDTH * Layout.CONFIG_DATA_INNER_BOX_HEIGHT;" in tap
    assert tap.rstrip().endswith("setSelectedComplication(chosen);\n        return true;") \
        or "setSelectedComplication(chosen);" in tap


def test_the_editor_pulls_what_a_slot_elements_colour_reads(write_design, db):
    """A `data` element whose colour reads data has a draw method taking that
    reader; the editor's dispatch used to call it with `dc` alone, which
    monkeyc refuses ("wrong number of arguments")."""
    view = monkeyc.emit_view(_resolved(HEAD + COLOURED_TEXT, write_design, db)).text
    assert "private function drawTopText(dc as Dc, stats as System.Stats) as Void" in view
    body = _body(view, "private function drawSlotTop(dc as Dc) as Void")
    assert body.index("var stats = System.getSystemStats();") < body.index("drawTopText(dc, stats);")


@pytest.mark.slow
def test_the_editor_wiring_compiles_warning_free(tmp_path, bag, db, toolchain):
    """A ring and a reading on one slot, a slot inside the ring, and a
    reading whose colour reads data, through `-l 3` on all three targets."""
    design = tmp_path / "editor.yaml"
    design.write_text(HEAD + RING + COLOURED_TEXT + INNER, encoding="utf-8")
    result = real_build(design, output=tmp_path / "build", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert len(result.products) == 3
    complaints = [d for d in bag.items if d.severity.value == "error"
                  or (d.severity.value == "warning" and d.code == "monkeyc")]
    assert not complaints, bag.render()
