"""Per-device `overrides:`: an element's geometry patched for one device
id or one screen shape, deep-merged over the element's own keys and
resolved per device; the shared view never changes."""

from __future__ import annotations

import textwrap

import pytest

from wfb.build import build as real_build, load, resolve_all, select_devices
from wfb.diagnostics import Bag
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve

from tests.helpers import find, generate_for_targets

ROUND, OTHER_ROUND, RECT = "fenix8solar47mm", "fr955", "venusq2"


def design(elements: str, targets: str = f"[{ROUND}, {OTHER_ROUND}, {RECT}]") -> str:
    return f"""\
format: 2
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
build: {{targets: {targets}}}
resources:
  palette: {{bg: "#000000", fg: "#FFFFFF"}}
elements:
""" + textwrap.indent(textwrap.dedent(elements), "  ")


DOT = """\
dot:
  type: circle
  radius: 10px
  at: {anchor: center, dy: -40px}
  color: color.fg
  overrides:
    "shape:rectangle": {at: {dx: 30px}}
    fr955: {at: {anchor: top, dy: 50px}, radius: 20px}
"""


def _resolved(text: str, write_design, db, device_id: str):
    bag = Bag()
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get(device_id)
    return resolve(face, device, bake_fonts(face, device))


def _errors(text: str, write_design) -> list:
    bag = Bag()
    assert load(write_design(text), bag) is None, bag.render()
    return bag.errors


def test_each_device_resolves_its_own_override_or_the_base(write_design, db):
    base = find(_resolved(design(DOT), write_design, db, ROUND), "dot")
    by_id = find(_resolved(design(DOT), write_design, db, OTHER_ROUND), "dot")
    by_shape = find(_resolved(design(DOT), write_design, db, RECT), "dot")
    assert base.center == (130, 90) and base.radius == 10
    # fr955 (260x260): anchored to the top now, and a larger dot
    assert by_id.center == (130, 50) and by_id.radius == 20
    # venusq2 (320x360): the shape patch adds dx and keeps the base's anchor and dy
    assert by_shape.center == (160 + 30, 180 - 40) and by_shape.radius == 10


def test_a_device_id_wins_over_its_shape_and_both_merge_over_the_base(write_design, db):
    text = design("""\
        dot:
          type: circle
          radius: 10px
          at: {anchor: center, dy: -40px}
          color: color.fg
          overrides:
            "shape:rectangle": {at: {dx: 30px, dy: 0px}, radius: 15px}
            venusq2: {at: {dy: 12px}}
        """)
    dot = find(_resolved(text, write_design, db, RECT), "dot")
    assert dot.center == (160 + 30, 180 + 12)
    assert dot.radius == 15


def test_align_moves_a_shape_box(write_design, db):
    text = design("""\
        box:
          type: rectangle
          size: {width: 20px, height: 20px}
          at: {anchor: center}
          color: color.fg
          overrides:
            fr955: {align: top_left}
        """)
    assert find(_resolved(text, write_design, db, ROUND), "box").box.x == 120
    moved = find(_resolved(text, write_design, db, OTHER_ROUND), "box")
    assert (moved.box.x, moved.box.y) == (130, 130)


def test_the_shared_view_is_unchanged_and_only_layout_moves(write_design, tmp_path):
    project = generate_for_targets(write_design(design(DOT)), tmp_path / "out")
    assert project.divergences == []
    files = project.files()
    assert "const DOT_CY as Number = 90;" in files[f"source-{ROUND}/Layout.mc"]
    assert "const DOT_CY as Number = 50;" in files[f"source-{OTHER_ROUND}/Layout.mc"]
    assert "const DOT_RADIUS as Number = 20;" in files[f"source-{OTHER_ROUND}/Layout.mc"]


def test_a_text_moves_but_keeps_its_alignment(write_design, db):
    text = design("""\
        t:
          type: text
          text: "12:00"
          at: {anchor: center}
          color: color.fg
          overrides:
            fr955: {at: {dy: 25px}}
        """)
    base = find(_resolved(text, write_design, db, ROUND), "t")
    moved = find(_resolved(text, write_design, db, OTHER_ROUND), "t")
    assert moved.anchor_point[1] == base.anchor_point[1] + 25


@pytest.mark.parametrize("elements, message", [
    ("""\
     t:
       type: text
       text: "x"
       color: color.fg
       overrides:
         fr955: {align: left}
     """, "'align:' on a text is the draw call's justification"),
    ("""\
     box:
       type: rectangle
       size: {width: 20px, height: 20px}
       color: color.fg
       overrides:
         fr955: {radius: 4px}
     """, "'radius:' is not a key this element writes"),
    ("""\
     dot:
       type: circle
       radius: 4px
       at: {anchor: subscreen}
       unsupported: hide
       color: color.fg
       overrides:
         fr955: {at: {anchor: center}}
     """, "an override cannot move an element into or out of the subscreen window"),
    ("""\
     dot:
       type: circle
       radius: 4px
       color: color.fg
       overrides:
         fr955: {radius: 4furlongs}
     """, "4furlongs"),
])
def test_override_errors(elements, message, write_design):
    found = _errors(design(elements), write_design)
    assert [d.message for d in found if message in d.message], [d.message for d in found]


def test_a_key_that_is_not_geometry_is_a_schema_error(write_design):
    found = _errors(design("""\
        dot:
          type: circle
          radius: 4px
          color: color.fg
          overrides:
            fr955: {color: color.bg}
        """), write_design)
    assert found and all(d.code == "schema" for d in found)


def _select(text: str, write_design, db, only=None) -> Bag:
    bag = Bag()
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    devices = select_devices(face, db, bag, only)
    if devices and bag.ok():
        resolve_all(face, devices, bag)
    return bag


def test_an_unknown_device_id_is_an_error(write_design, db):
    bag = _select(design("""\
        dot:
          type: circle
          radius: 4px
          color: color.fg
          overrides:
            fr9555: {radius: 8px}
        """), write_design, db)
    assert [d.code for d in bag.errors] == ["overrides"]
    assert "fr9555" in bag.errors[0].message


def test_a_selector_no_device_in_the_build_matches_warns(write_design, db):
    text = design(DOT, targets=f"[{ROUND}]")
    bag = _select(text, write_design, db)
    unreachable = [d for d in bag.items if d.code == "override-unreachable"]
    assert len(unreachable) == 2, bag.render()
    # -d brings fr955 in: its own selector is then reachable
    bag = _select(text, write_design, db, [ROUND, OTHER_ROUND])
    messages = [d.message for d in bag.items if d.code == "override-unreachable"]
    assert len(messages) == 1 and "shape:rectangle" in messages[0], bag.render()


@pytest.mark.slow
def test_overrides_compile_warning_free(write_design, db, tmp_path, toolchain):
    text = design("""\
        t:
          type: text
          text: "{time.clock:%H:%M}"
          at: {anchor: center, dy: -10%}
          color: color.fg
          overrides:
            fr955: {at: {dy: -20%}}
        box:
          type: rectangle
          size: {width: 30px, height: 10px}
          at: {anchor: center, dy: 20%}
          color: color.fg
          overrides:
            "shape:round": {size: {width: 40px}}
            fenix8solar51mm: {align: top_left}
        """, targets="[fenix8solar47mm, fenix8solar51mm, fr955]")
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db,
                        toolchain=toolchain)
    assert result is not None, bag.render()
    assert not [d for d in bag.items if d.severity.value in ("warning", "error")], bag.render()
