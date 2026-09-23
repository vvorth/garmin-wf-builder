"""Always-on display (`aod:`, plan 14 slice 1): resolution precedence, the
`always_on` removal, the two AOD lints, and the byte-identical guarantee for
an all-MIP build.

Each resolution test names, in its own docstring, the precedence rule it
drives -- the same discipline `tests/test_static.py` documents at its own
top (`docs/lore/working-agreement.md`: a guard nobody has watched fail is
not a guard).
"""

from __future__ import annotations

from pathlib import Path

from tests.test_diagnostics import load
from wfb import lint
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve

ROOT = Path(__file__).resolve().parent.parent

BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix847mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
  dim: "#555555"
"""


def _face(text, write_design, bag):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    return face


def _by_id(face, element_id):
    return next(e for e in face.walk() if e.id == element_id)


# --------------------------------------------------------------------------
# `always_on` removed (D3)


def test_always_on_in_modes_is_a_schema_error_pointing_at_aod(write_design, bag):
    text = BASE + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    modes: [active, always_on]
"""
    face = load(write_design(text), bag)
    assert face is None
    errors = [d for d in bag.errors if d.code == "schema"]
    assert errors, bag.render()
    assert "always_on" in errors[0].message
    assert "aod:" in " ".join(errors[0].notes)


def test_hands_modes_accepts_only_active(write_design, bag):
    """`always_on` is gone and `low_power` was already forbidden on hands --
    `active` is the only value left standing."""
    text = BASE + """
hands:
  set:
    hour:
      color: palette.fg
      parts:
        - {shape: line, at: {dy: 0}, to: {dy: -40px}, thickness: 3px}
elements:
  - id: h
    type: hands
    hands: set
    modes: [active, low_power]
"""
    face = load(write_design(text), bag)
    assert face is None
    assert any(d.code == "hands" and "low_power" in d.message for d in bag.errors), bag.render()


# --------------------------------------------------------------------------
# face-level `aod: dim:`/`jitter:` -- friendly "not implemented" errors


def test_dim_is_a_friendly_not_implemented_error(write_design, bag):
    text = BASE.replace("palette:\n", "aod:\n  dim: 0.4\npalette:\n") + "elements:\n" + """  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""
    face = load(write_design(text), bag)
    assert face is None
    hits = [d for d in bag.errors if d.code == "aod"]
    assert hits and "dim" in hits[0].message and "not implemented" in hits[0].message


def test_jitter_is_a_friendly_not_implemented_error(write_design, bag):
    text = BASE.replace("palette:\n", "aod:\n  jitter: 4\npalette:\n") + "elements:\n" + """  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""
    face = load(write_design(text), bag)
    assert face is None
    hits = [d for d in bag.errors if d.code == "aod"]
    assert hits and "jitter" in hits[0].message and "not implemented" in hits[0].message


# --------------------------------------------------------------------------
# resolution precedence (plan 14 §3)


def test_element_own_aod_wins_key_by_key_over_its_ancestor(write_design, bag):
    """Rule 1: the element's own `aod:` wins, key by key, over its nearest
    ancestor group's."""
    text = BASE + """
elements:
  - id: g
    type: group
    aod: {color: palette.dim}
    children:
      - id: clock
        type: text
        text: "12:00"
        color: palette.fg
        aod: {color: palette.fg}
"""
    face = _face(text, write_design, bag)
    clock = _by_id(face, "clock")
    assert clock.aod is not None
    assert clock.aod.color.constant == face.palette["fg"].value


def test_key_by_key_merge_fills_missing_keys_from_the_ancestor(write_design, bag):
    """The element's own block need not repeat every key: whatever it leaves
    unset still falls back to its ancestor's own value for that key."""
    text = BASE + """
elements:
  - id: g
    type: group
    aod: {color: palette.dim}
    children:
      - id: bar
        type: progress
        style: bar
        value: system.battery
        max: 100
        when_absent: hide
        size: {width: 50%, height: 10%}
        color: palette.fg
        aod: {thickness: 2px}
"""
    face = _face(text, write_design, bag)
    bar = _by_id(face, "bar")
    assert bar.aod is not None
    # thickness is the child's own; color falls back to the ancestor's.
    assert bar.aod.color.constant == face.palette["dim"].value


def test_nearest_ancestor_group_applies_when_the_element_says_nothing(write_design, bag):
    """Rule 2: with no `aod:` of its own, the element takes its nearest
    ancestor group's `aod:` wholesale."""
    text = BASE + """
elements:
  - id: g
    type: group
    aod: show
    children:
      - id: clock
        type: text
        text: "12:00"
        color: palette.fg
"""
    face = _face(text, write_design, bag)
    clock = _by_id(face, "clock")
    assert clock.aod is not None


def test_face_default_fills_only_where_nothing_in_the_ancestry_spoke(write_design, bag):
    """Rule 3: the face default only ever fills silence -- an element or any
    ancestor speaking at all pre-empts it, in either direction."""
    text = BASE.replace("palette:\n", "aod:\n  default: show\npalette:\n") + """
elements:
  - id: quiet
    type: text
    text: "quiet"
    color: palette.fg
  - id: g
    type: group
    aod: hide
    children:
      - id: loud
        type: text
        text: "loud"
        color: palette.fg
"""
    face = _face(text, write_design, bag)
    # nothing in `quiet`'s ancestry (itself included) ever mentions `aod:` --
    # the face default (`show`) fills it.
    assert _by_id(face, "quiet").aod is not None
    # `g` explicitly hides -- the default does not apply, because something
    # in the ancestry *did* speak.
    assert _by_id(face, "loud").aod is None


def test_group_hide_is_unconditional_and_cannot_be_undone_below(write_design, bag):
    """The one asymmetry (§3): an explicit `aod: hide` on a group hides the
    whole subtree even against a descendant's own explicit `aod: show`."""
    text = BASE + """
elements:
  - id: g
    type: group
    aod: hide
    children:
      - id: clock
        type: text
        text: "12:00"
        color: palette.fg
        aod: show
"""
    face = _face(text, write_design, bag)
    assert _by_id(face, "clock").aod is None


def test_visible_conjoins_with_the_elements_own_visible(write_design, bag):
    """`aod: {visible: ...}` conjoins with the element's own `visible:`,
    rather than replacing it."""
    text = BASE + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    visible: "system.battery > 0"
    aod: {visible: "system.battery < 20"}
"""
    face = _face(text, write_design, bag)
    clock = _by_id(face, "clock")
    assert clock.aod is not None
    assert "system.battery > 0" in clock.aod.visible.text
    assert "system.battery < 20" in clock.aod.visible.text
    # the codegen-only "extra" half is exactly the aod-only clause, not the
    # conjunction -- the element's own method already checks the other half.
    assert clock.aod.visible_override.text == "system.battery < 20"


def test_visible_with_no_own_visible_is_just_the_aod_clause(write_design, bag):
    text = BASE + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: {visible: "system.battery < 20"}
"""
    face = _face(text, write_design, bag)
    clock = _by_id(face, "clock")
    assert clock.visible is None
    assert clock.aod.visible.text == "system.battery < 20"


def test_empty_override_block_means_show(write_design, bag):
    text = BASE + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: {}
"""
    face = _face(text, write_design, bag)
    clock = _by_id(face, "clock")
    assert clock.aod is not None
    assert clock.aod.color is None  # nothing overridden, still "drawn"


# --------------------------------------------------------------------------
# the two lints


def test_aod_unreachable_fires_when_an_ancestor_hides_explicitly(write_design, bag, db):
    text = BASE + """
elements:
  - id: g
    type: group
    aod: hide
    children:
      - id: clock
        type: text
        text: "12:00"
        color: palette.fg
        aod: show
"""
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get("fenix847mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    lint.check_aod_unreachable(resolved, bag)
    hits = [d for d in bag.items if d.code == "aod-unreachable"]
    assert hits, bag.render()
    assert "clock" in hits[0].message


def test_aod_unreachable_is_silent_when_nothing_is_unreachable(write_design, bag, db):
    """Green half of the contrast above: the same shape, minus the
    ancestor's hide, must not warn."""
    text = BASE + """
elements:
  - id: g
    type: group
    children:
      - id: clock
        type: text
        text: "12:00"
        color: palette.fg
        aod: show
"""
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get("fenix847mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    lint.check_aod_unreachable(resolved, bag)
    assert "aod-unreachable" not in {d.code for d in bag.items}


def test_aod_empty_fires_on_an_amoled_target_with_nothing_shown(write_design, bag, db):
    text = BASE + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get("fenix847mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    lint.check_aod_empty(resolved, bag)
    hits = [d for d in bag.items if d.code == "aod-empty"]
    assert hits, bag.render()
    assert "fenix847mm" in hits[0].message


def test_aod_empty_is_silent_once_something_is_shown(write_design, bag, db):
    text = BASE + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: show
"""
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get("fenix847mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    lint.check_aod_empty(resolved, bag)
    assert "aod-empty" not in {d.code for d in bag.items}


def test_aod_empty_is_silent_on_a_mip_target(write_design, bag, db):
    """D5/D1: nothing about `aod:` applies to a MIP device at all."""
    text = BASE.replace("targets: [fenix847mm]", "targets: [fenix8solar47mm]") + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    lint.check_aod_empty(resolved, bag)
    assert "aod-empty" not in {d.code for d in bag.items}


def test_aod_empty_is_suppressible_on_the_face(write_design, bag, db):
    text = BASE.replace(
        "palette:\n",
        'aod:\n  lint: {allow: [aod-empty], reason: "deliberately no AOD yet"}\npalette:\n',
    ) + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get("fenix847mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    lint.check_aod_empty(resolved, bag)
    assert "aod-empty" not in {d.code for d in bag.items}


# --------------------------------------------------------------------------
# byte-identical guarantee for an all-MIP build (plan 14 §4.1, §6 slice 1)


MIP_BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
"""


def _view_text(text, write_design, bag, db, device_id="fenix8solar47mm"):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get(device_id)
    baked = {device.id: bake_fonts(face, device)}
    project = generate(face, [device], write_design("").parent / "build", baked)
    return next(v for k, v in project.files().items() if k.endswith("View.mc"))


def test_an_all_mip_build_is_byte_identical_with_and_without_aod_keys(write_design, bag, db):
    without = MIP_BASE + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""
    with_aod = MIP_BASE.replace(
        "palette:\n", "aod:\n  default: hide\npalette:\n"
    ) + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: {color: palette.fg, visible: "system.battery < 20"}
"""
    bag_a, bag_b = Bag(), Bag()
    text_a = _view_text(without, write_design, bag_a, db)
    text_b = _view_text(with_aod, write_design, bag_b, db)
    assert text_a == text_b
    assert "_aod" not in text_a
    assert "_aod" not in text_b


def test_an_amoled_target_does_add_aod_plumbing(write_design, bag, db):
    """The other half of the same contrast: swap in an AMOLED device and the
    plumbing must actually appear, or the test above would be vacuous."""
    text = MIP_BASE.replace(
        "targets: [fenix8solar47mm]", "targets: [fenix847mm]"
    ).replace("palette:\n", "aod:\n  default: hide\npalette:\n") + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: show
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    assert "private var _aod as Boolean = false;" in view


def test_aod_branch_clears_to_black_before_any_draw_call(write_design, bag, db):
    """Review finding: `Dc` keeps its contents between `onUpdate` calls --
    there is no implicit clear -- and the awake frame's own background
    element is what clears it there. The AOD branch never draws that
    element (it is hidden by the face default), so without an explicit
    clear the first AOD frame would draw its few elements over whatever
    the *last awake frame* left lit -- every pixel that frame lit stays
    lit, exactly the burn-in AOD exists to prevent."""
    text = MIP_BASE.replace(
        "targets: [fenix8solar47mm]", "targets: [fenix847mm]"
    ).replace("palette:\n", "aod:\n  default: hide\npalette:\n") + """
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.fg
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: show
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    on_update = view.split("function onUpdate")[1].split("\n    function ")[0]
    aod_branch = on_update.split("if (_aod) {", 1)[1].split("\n        else {", 1)[0]
    # the awake-only background never draws in the aod branch...
    assert "drawBackground" not in aod_branch
    # ...so the explicit clear is what has to stand in for it, and it must
    # come before the first draw call, not after.
    assert "dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);" in aod_branch
    assert "dc.clear();" in aod_branch
    clear_pos = aod_branch.index("dc.clear();")
    call_pos = aod_branch.index("drawClock(dc")
    assert clear_pos < call_pos
