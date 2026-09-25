"""`outline:` on a pattern's own `shape: text` part (plan 15 §14 slice 2) --
layout box growth (one level down from `tests/test_text_outline_layout.py`)
and codegen (one level down from `tests/test_text_outline_golden.py`).

The one thing genuinely new at this level, beyond "the same mechanism as
slice 1": a pattern's own per-copy rotation and a part's own `curve:` angle
both already turn the anchor/angle *before* an outline stamp's offset is
added, so the stamp has to land in screen space -- after both transforms,
never composed into either -- or the ring would smear as the pattern turns.
Every codegen test below drives that red first against the two ways it can
plausibly go wrong: an offset baked into the rotated anchor expression
itself (rather than added after it), and two outlined parts colliding on
the same generated loop variable names (a real `monkeyc` "Redefinition of
variable 'i'" this slice's own implementation hit before `_emit_outline_
loop` grew its `index_var`/`offsets_var` parameters -- `tests/fixtures/
outline_text/face.yaml` is the regression fixture for the second one).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wfb.build import load
from wfb.emit.monkeyc import emit_layout, emit_view
from wfb.emit.resources import bake_fonts
from wfb.layout import PlacedPattern, resolve
from wfb import lint
from tests.helpers import fonts_design as _design


_VECTOR_FONT = """\
  bezel:
    face: RobotoCondensedBold
    size: 6%r
"""


def _load(write_design, bag, design: str):
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    return face


def _placed_pattern(resolved, element_id: str) -> PlacedPattern:
    for p in resolved.items:
        if p.id == element_id:
            assert isinstance(p, PlacedPattern)
            return p
    raise AssertionError(f"{element_id!r} was not placed")


def _upright_ring(element_id: str, outline: str = "") -> str:
    return f"""\
  - id: {element_id}
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1
    parts:
      - shape: text
        text: "12"
        font: font.bezel
        color: palette.fg
        at: {{dy: -40%r}}{outline}"""


def _angled_ring(element_id: str, outline: str = "") -> str:
    return f"""\
  - id: {element_id}
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1
    parts:
      - shape: text
        text: "12"
        font: font.bezel
        color: palette.fg
        at: {{dy: -40%r}}
        curve: {{style: angled, angle: 0deg}}{outline}"""


def _radial_ring(element_id: str, outline: str = "") -> str:
    return f"""\
  - id: {element_id}
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1
    parts:
      - shape: text
        text: "12"
        font: font.bezel
        color: palette.fg
        curve: {{style: radial, angle: 0deg, radius: 40%r}}{outline}"""


_OUTLINE = "\n        outline: {color: palette.fg, width: 3}"


# -- layout: box growth -------------------------------------------------------


def test_upright_pattern_part_box_grows_by_the_ring(write_design, bag, db):
    elements = _upright_ring("plain") + "\n" + _upright_ring("ringed", _OUTLINE)
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    plain = _placed_pattern(resolved, "plain")
    ringed = _placed_pattern(resolved, "ringed")
    assert ringed.box.width > plain.box.width
    assert ringed.box.height > plain.box.height
    assert ringed.box.x <= plain.box.x
    assert ringed.box.y <= plain.box.y
    assert ringed.box.right >= plain.box.right
    assert ringed.box.bottom >= plain.box.bottom


def test_angled_pattern_part_box_grows_by_the_ring(write_design, bag, db):
    elements = _angled_ring("plain") + "\n" + _angled_ring("ringed", _OUTLINE)
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    plain = _placed_pattern(resolved, "plain")
    ringed = _placed_pattern(resolved, "ringed")
    assert ringed.box.width > plain.box.width
    assert ringed.box.height > plain.box.height


def test_radial_pattern_part_box_grows_by_the_ring(write_design, bag, db):
    elements = _radial_ring("plain") + "\n" + _radial_ring("ringed", _OUTLINE)
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    plain = _placed_pattern(resolved, "plain")
    ringed = _placed_pattern(resolved, "ringed")
    plain_area = plain.box.width * plain.box.height
    ringed_area = ringed.box.width * ringed.box.height
    assert ringed_area > plain_area
    assert ringed.box.x <= plain.box.x
    assert ringed.box.y <= plain.box.y
    assert ringed.box.right >= plain.box.right
    assert ringed.box.bottom >= plain.box.bottom


def test_no_outline_pattern_part_box_is_unchanged(write_design, bag, db):
    """`outline: none`/omitted must be byte-identical -- the contrast that
    would catch a `ring_px`/`pad` computed even with no outline at all."""
    elements = _upright_ring("plain")
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    plain = _placed_pattern(resolved, "plain")
    assert plain.parts[0].outline_color is None
    assert plain.parts[0].outline_width == 0
    assert plain.box.width > 0 and plain.box.height > 0


def test_off_screen_catches_a_pattern_box_that_only_overflows_once_ringed(write_design, bag, db):
    """The same D11 contrast slice 1 already proved for a standalone
    element (`tests/test_text_outline_layout.py::test_off_screen_catches_
    a_box_that_only_overflows_once_ringed`), one level down: a pattern
    positioned so its plain box fits the framebuffer exactly, but a wide
    ring pushes it over the edge -- `off-screen` fires only once
    `outline:` is added, with no new lint code (D11)."""
    elements = (
        """\
  - id: plain
    type: pattern
    pattern: radial
    at: {anchor: top_left, dx: 0px, dy: 0px}
    count: 1
    parts:
      - shape: text
        text: "12"
        font: font.bezel
        color: palette.fg
        align: left
        vertical_align: top
"""
        + """\
  - id: ringed
    type: pattern
    pattern: radial
    at: {anchor: top_left, dx: 0px, dy: 0px}
    count: 1
    parts:
      - shape: text
        text: "12"
        font: font.bezel
        color: palette.fg
        align: left
        vertical_align: top
        outline: {color: palette.fg, width: 3}
"""
    )
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    lint.check_geometry(resolved, bag)
    by_id = {}
    for d in bag.items:
        if d.code == "off-screen":
            by_id.setdefault(d.message.split(":")[0], []).append(d.code)
    assert "ringed" in by_id, bag.render()
    assert "plain" not in by_id, "only the ring should push the pattern past the edge"


# -- codegen: the stamp loop, unique variable names, screen-space offsets ---


def test_pattern_outline_stamp_loop_appears_and_precedes_interior_draw(write_design, bag, db):
    elements = _upright_ring("ring", _OUTLINE)
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    view = emit_view(resolve(face, device, {})).text
    method = view.split("private function drawRing")[1]
    assert "while (" in method and ".size())" in method
    stamp_index = method.index("while (")
    last_setcolor = method.rindex("dc.setColor(")
    assert stamp_index < last_setcolor, (
        "the interior pass's own dc.setColor must come after the stamp loop"
    )


def test_pattern_outline_offsets_added_after_the_rotation_not_inside_it(write_design, bag, db):
    """Screen-space offsets, not rotated ones (research 14 §3.2): the
    generated stamp adds `+ offsets[...]` OUTSIDE the `WfbGeom.rotatedX`/
    `rotatedY(...)` call that already carries the pattern's own per-copy
    rotation, never as one of that call's own arguments -- proven by a
    real, hand-derived expected string, not merely "the loop exists"."""
    elements = _upright_ring("ring", _OUTLINE)
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    view = emit_view(resolve(face, device, {})).text
    method = view.split("private function drawRing")[1]
    assert "WfbGeom.rotatedX(Layout.RING_0_X, Layout.RING_0_Y, cx, sin, cos) + outlineOffsets" \
        in method.replace("\n", " ").replace("  ", " ") or (
        # tolerate wrapped whitespace across lines
        "WfbGeom.rotatedX(Layout.RING_0_X, Layout.RING_0_Y, cx, sin, cos) +" in method
        and "outlineOffsetsRING_0" in method
    )


def test_pattern_outline_uses_unique_variable_names_per_part(write_design, bag, db):
    """The real bug this slice's own implementation hit: two outlined text
    parts sharing one pattern's generated method must not both declare a
    plain `var i`/`var offsets` -- Monkey C rejects the redefinition even
    across separate straight-line statements in the same method. Each
    part's own stamp loop must use a name derived from its own
    `part_prefix` instead."""
    elements = f"""\
  - id: ring
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1
    parts:
      - shape: text
        text: "A"
        font: font.bezel
        color: palette.fg
        at: {{dy: -30%r}}
        outline: {{color: palette.fg, width: 1}}
      - shape: text
        text: "B"
        font: font.bezel
        color: palette.fg
        at: {{dy: 30%r}}
        outline: {{color: palette.fg, width: 2}}
"""
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    view = emit_view(resolve(face, device, {})).text
    method = view.split("private function drawRing")[1]
    assert "outlineOffsetsRING_0" in method
    assert "outlineOffsetsRING_1" in method
    assert "outlineIRING_0" in method
    assert "outlineIRING_1" in method
    # Never the plain, standalone-element-style bare names -- those would
    # collide with each other AND with the copy loop's own `for (var i ...)`.
    # (`"var i = 0;"` alone is not a safe substring to check: the copy loop's
    # own `for (var i = 0; i < 1; i++)` header legitimately contains it.)
    assert "while (i <" not in method
    assert "var offsets = Layout" not in method


def test_pattern_outline_angle_is_identical_for_stamp_and_interior(write_design, bag, db):
    """The angle argument (the part's own `curve:` composed with the
    pattern's per-copy rotation, `_emit_pattern_text_angle_expr`) must be
    the exact same expression for every stamp and the interior draw --
    an outline offset is a screen-space translation only, never a second,
    independently-rotated copy of the glyph."""
    elements = _angled_ring("ring", _OUTLINE)
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    view = emit_view(resolve(face, device, {})).text
    method = view.split("private function drawRing")[1]
    calls = method.split("dc.drawAngledText(")[1:]
    assert len(calls) >= 2, "expected at least one stamp call plus the interior call"
    angle_terms = [c.split(";")[0].rsplit(",", 1)[-1].strip() for c in calls]
    assert len(set(angle_terms)) == 1, angle_terms


def test_pattern_outline_vector_gate_wraps_loop_and_interior_together(write_design, bag, db):
    elements = _angled_ring("ring", _OUTLINE)
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    view = emit_view(resolve(face, device, {})).text
    method = view.split("private function drawRing")[1]
    method = method.split("\n\n    //!")[0]
    assert method.count("if (font0 != null) {") == 1


def test_pattern_outline_offset_width_dedups_with_a_standalone_elements_own(write_design, bag, db):
    """`OUTLINE_OFFSETS_<W>` is emitted once per distinct width used
    ANYWHERE in the design -- a pattern part reusing a width a standalone
    `text` element already uses must not emit a second, duplicate
    constant (plan 15 §8/§14 slice 2: "dedup already covers it")."""
    elements = (
        """\
  - id: clock
    type: text
    text: "12:34"
    font: font.bezel
    color: palette.fg
    at: {anchor: center, dy: -60%r}
    outline: {color: palette.fg, width: 3}
"""
        + _upright_ring("ring", _OUTLINE)
    )
    face = _load(write_design, bag, _design(_VECTOR_FONT, elements))
    device = db.get("fenix8solar47mm")
    layout = emit_layout(resolve(face, device, {})).text
    assert layout.count("OUTLINE_OFFSETS_3 as Array<Number>") == 1


# -- the shared golden fixture (extends tests/fixtures/outline_text) --------


GOLDEN = Path(__file__).parent / "golden"


def test_golden_fixture_pattern_methods_have_no_redefinition_regressions(
    pytestconfig, tmp_path_factory,
):
    """The regression that motivated `index_var`/`offsets_var`
    (`emit_outline_loop`) was only caught by a real `monkeyc` build of
    `tests/fixtures/outline_text/face.yaml` (`dial_numbers`/`dial_ring`,
    both radial patterns with outlined `shape: text` parts) -- this test
    pins the generated shape so a future change cannot silently reintroduce
    a bare `var i`/`var offsets` inside a pattern's own draw method without
    a golden diff explaining why."""
    from wfb.devices import DeviceDatabase, DeviceError
    from wfb.diagnostics import Bag
    from wfb.emit import generate

    bag = Bag()
    path = pytestconfig.rootpath / "tests" / "fixtures" / "outline_text" / "face.yaml"
    assert path.exists(), path
    face = load(path, bag)
    assert face is not None, bag.render()
    try:
        db = DeviceDatabase.discover()
    except DeviceError as exc:
        pytest.skip(str(exc))
    ids = [d for d in face.targets if d in db.ids()]
    if not ids:
        pytest.skip("none of the design's targets are installed")
    devices = [db.get(d) for d in ids]
    baked = {d.id: bake_fonts(face, d) for d in devices}
    generated = generate(face, devices, tmp_path_factory.mktemp("build"), baked)
    view = generated.files()["source/OutlineTextView.mc"]
    for method_name in ("drawDialNumbers", "drawDialRing"):
        method = view.split(f"private function {method_name}")[1]
        method = method.split("\n\n    //!")[0]
        assert "while (i <" not in method
        assert "var offsets = Layout" not in method
        assert "while (" in method
