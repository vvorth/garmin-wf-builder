"""`at: {anchor: subscreen}` (plan 20 D2): an element laid out inside the
Instinct family's subscreen window, and `if_unavailable: error|hide` on a
target without one."""

from __future__ import annotations

import pytest

from tests.helpers import find, load_errors, load_face
from wfb import lint
from wfb.availability import compute_guards
from wfb.build import build as real_build
from wfb.build import resolve_all
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.resources import bake_fonts
from wfb.preview import PreviewOptions, render

INSTINCT = "instinct2"
ROUND = "fenix8solar47mm"

DESIGN = """
format: 1
face:
  id: 3d2c1b0a-9f8e-4d7c-8b6a-5f4e3d2c1b0a
  name: Sub
targets: [instinct2, fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%h:%M}"
    font: FONT_SMALL
    at: {anchor: center, dy: 10%}
    color: palette.fg
  - id: ring
    type: progress
    style: arc
    at: {anchor: subscreen}
    radius: 40%
    thickness: 2px
    start_angle: 0deg
    sweep: 360deg
    value: system.battery
    max: 100
    color: palette.fg
    IF_UNAVAILABLE
  - id: pack
    type: group
    at: {anchor: subscreen, dy: 10%}
    size: {width: 50%, height: 20%}
    IF_UNAVAILABLE
    children:
      - id: dot
        type: shape
        shape: circle
        at: {anchor: center}
        radius: 10%r
        color: palette.fg
"""


def _text(policy: str | None) -> str:
    line = f"if_unavailable: {policy}" if policy else ""
    return DESIGN.replace("IF_UNAVAILABLE", line)


def _need(db, *device_ids):
    for device_id in device_ids:
        if device_id not in db.ids():
            pytest.skip(f"{device_id} not installed")


def _resolve(write_design, db, policy: str | None, device_ids=(INSTINCT, ROUND)):
    _need(db, *device_ids)
    bag = Bag()
    face = load_face(_text(policy), write_design, bag)
    resolved, _ = resolve_all(face, [db.get(d) for d in device_ids], bag)
    return face, resolved, bag


# -- the device fact -----------------------------------------------------------


def test_a_subscreen_needs_both_the_box_and_the_symbol(db):
    """`instinct3amoled50mm` declares a box but has no `getSubscreen`:
    a virtual window, which Garmin documents `getSubscreen()` as null for."""
    _need(db, INSTINCT, ROUND, "instinct3amoled50mm")
    assert db.get(INSTINCT).subscreen == (113, 0, 62, 62)
    assert db.get(ROUND).subscreen is None
    assert db.get("instinct3amoled50mm").simulator["subscreen"]["location"]
    assert db.get("instinct3amoled50mm").subscreen is None


# -- layout --------------------------------------------------------------------


def test_the_window_is_the_parent_box(write_design, db):
    """The ring centres on the window (144, 31); `40%` is of the 62 px
    window, not the screen; the group's `dy: 10%` and `size:` are too, and
    its child's `%r` stays the screen's."""
    _, resolved, bag = _resolve(write_design, db, None, (INSTINCT,))
    assert bag.ok(), bag.render()
    rf = resolved[INSTINCT]
    ring = find(rf, "ring")
    assert ring.center == (144, 31)
    assert ring.radius == round(0.40 * 62)
    pack = find(rf, "pack")
    # 50% x 20% of the window is 31 x 12.4 (of the screen it would be
    # 88 x 35); edges round independently, so allow a pixel.
    assert abs(pack.box.width - 31) <= 1 and abs(pack.box.height - 12.4) <= 1
    assert pack.center == (144, round(31 + 6.2))
    assert find(rf, "dot").radius == round(0.10 * 88)


# -- if_unavailable -----------------------------------------------------------


def test_a_target_without_a_window_is_an_error_by_default(write_design, db):
    _, _, bag = _resolve(write_design, db, None)
    errors = [d for d in bag.items if d.code == "subscreen" and d.severity.value == "error"]
    assert sorted(d.message.split(":", 1)[0] for d in errors) == ["pack", "ring"]
    assert all(ROUND in d.message and INSTINCT not in d.message for d in errors)
    assert "if_unavailable: hide" in " ".join(errors[0].notes)


def test_hide_is_a_note_and_hides_the_subtree_there(write_design, db):
    _, resolved, bag = _resolve(write_design, db, "hide")
    assert bag.ok(), bag.render()
    notes = [d for d in bag.items if d.code == "subscreen"]
    assert notes and all(d.severity.value == "note" for d in notes)
    assert set(resolved[ROUND].hidden) == {"ring", "pack", "dot"}
    assert not resolved[INSTINCT].hidden


def test_a_hidden_element_is_not_linted_where_it_does_not_draw(write_design, db):
    """On the round device the hidden group is placed at the screen's
    centre, under the clock; were it linted there, its hold region would
    overlap the clock's. It never draws there, so nothing may be said."""
    _need(db, ROUND)
    text = (_text("hide")
            .replace("    children:", "    on_hold: battery\n    children:")
            .replace("    font: FONT_SMALL\n", "    font: FONT_SMALL\n    on_hold: steps\n"))
    face = load_face(text, write_design, Bag())
    bag = Bag()
    resolved, _ = resolve_all(face, [db.get(ROUND)], bag)
    rf = resolved[ROUND]
    assert lint._intersects(find(rf, "pack").box, find(rf, "clock").box)  # the premise
    assert not [d for d in bag.items if d.code == "hold-overlap"], bag.render()


def test_the_preview_leaves_a_hidden_element_out(write_design, db):
    """The hidden ring is placed at the screen's centre on the round device
    (so its constants exist) but must not draw there."""
    _, resolved, _ = _resolve(write_design, db, "hide")
    rf = resolved[ROUND]
    ring = find(rf, "ring")
    image = render(rf, PreviewOptions(scale=1, mask_shape=False)).convert("RGB")
    x, y = ring.center[0] + ring.radius, ring.center[1]
    assert image.getpixel((x, y)) == (0, 0, 0)
    shown = render(resolved[INSTINCT], PreviewOptions(scale=1, mask_shape=False)).convert("RGB")
    ring = find(resolved[INSTINCT], "ring")
    assert shown.getpixel((ring.center[0] + ring.radius, ring.center[1])) != (0, 0, 0)


# -- codegen -------------------------------------------------------------------


def _files(write_design, db, policy, device_ids):
    face, _, _ = _resolve(write_design, db, policy, device_ids)
    devices = [db.get(d) for d in device_ids]
    out = write_design(_text(policy)).parent / "out"
    return generate(face, devices, out, {d.id: bake_fonts(face, d) for d in devices}).files()


def test_each_device_says_whether_it_draws_and_the_view_checks(write_design, db):
    files = _files(write_design, db, "hide", (INSTINCT, ROUND))
    instinct = files[f"source-{INSTINCT}/Layout.mc"]
    round_ = files[f"source-{ROUND}/Layout.mc"]
    for const in ("RING_SHOWN", "DOT_SHOWN"):
        assert f"const {const} as Boolean = true;" in instinct
        assert f"const {const} as Boolean = false;" in round_
    assert "PACK_SHOWN" not in instinct  # a group draws nothing itself
    view = next(text for name, text in files.items() if name.endswith("View.mc"))
    assert "if (!Layout.RING_SHOWN)" in view and "if (!Layout.DOT_SHOWN)" in view
    assert "if (!Layout.CLOCK_SHOWN)" not in view


def test_an_all_subscreen_build_carries_no_guard(write_design, db):
    """No target lacks the window: no constant, no check -- the same "no
    guard for a thing every target has" rule every other guard follows."""
    _need(db, "instinct3solar45mm")
    files = _files(write_design, db, None, (INSTINCT, "instinct3solar45mm"))
    assert not any("_SHOWN" in text for text in files.values())
    face, _, _ = _resolve(write_design, db, None, (INSTINCT, "instinct3solar45mm"))
    assert compute_guards(face, [db.get(INSTINCT)]).subscreen_hidden == frozenset()


def test_a_hidden_hold_region_is_empty(write_design, db):
    text = _text("hide").replace("    children:", "    on_hold: battery\n    children:")
    _need(db, INSTINCT, ROUND)
    face = load_face(text, write_design, Bag())
    devices = [db.get(INSTINCT), db.get(ROUND)]
    files = generate(face, devices, write_design(text).parent / "out",
                     {d.id: bake_fonts(face, d) for d in devices}).files()
    assert "const PACK_HOLD_WIDTH as Number = 0;" in files[f"source-{ROUND}/Layout.mc"]
    assert "const PACK_HOLD_WIDTH as Number = 32;" in files[f"source-{INSTINCT}/Layout.mc"]


# -- the format ------------------------------------------------------------------


def _errors(write_design, text: str) -> list[str]:
    return [d.message for d in load_errors(text, write_design)]


def test_subscreen_is_a_top_level_at_only(write_design):
    child = _text(None).replace("        at: {anchor: center}\n        radius: 10%r",
                                "        at: {anchor: subscreen}\n        radius: 10%r")
    assert any("not accepted on a group's child" in m for m in _errors(write_design, child))
    line = _text(None).replace("""  - id: clock""", """  - id: rule
    type: shape
    shape: line
    at: {anchor: left}
    to: {anchor: subscreen}
    thickness: 1px
    color: palette.fg
  - id: clock""")
    assert any("not accepted in 'to:'" in m for m in _errors(write_design, line))


def test_if_unavailable_needs_something_that_can_be_unavailable(write_design):
    shape = _text(None).replace("      - id: dot", "      - id: dot\n        if_unavailable: hide")
    assert any("dot: 'if_unavailable:' is not accepted here" in m
               for m in _errors(write_design, shape))
    # A system-font text anchored to the window may say it; unanchored, not.
    anchored = _text(None).replace("    at: {anchor: center, dy: 10%}",
                                   "    at: {anchor: subscreen}\n    if_unavailable: hide")
    assert _errors(write_design, anchored) == []
    loose = _text(None).replace("    at: {anchor: center, dy: 10%}",
                                "    at: {anchor: center}\n    if_unavailable: hide")
    assert any("'if_unavailable:' is not accepted here" in m for m in _errors(write_design, loose))


# -- the real compiler -------------------------------------------------------------


@pytest.mark.slow
def test_a_hidden_subscreen_element_compiles_warning_free(write_design, db, tmp_path, toolchain):
    _need(db, INSTINCT, ROUND)
    bag = Bag()
    result = real_build(write_design(_text("hide")), output=tmp_path, bag=bag, db=db,
                        toolchain=toolchain)
    compiler = [d for d in bag.items if d.code == "monkeyc"]
    assert result is not None and not compiler, bag.render()
