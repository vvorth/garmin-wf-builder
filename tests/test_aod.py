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

import pytest

from wfb.build import load
from wfb import lint
from wfb.build import build as real_build
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
# face-level `aod: jitter:` -- removed outright, so the schema rejects it
# (dim: built, below)


def test_jitter_is_rejected_by_the_schema(write_design, bag):
    text = BASE.replace("palette:\n", "aod:\n  jitter: 4\npalette:\n") + "elements:\n" + """  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""
    face = load(write_design(text), bag)
    assert face is None
    assert any("jitter" in d.message for d in bag.errors), bag.render()


# --------------------------------------------------------------------------
# friendly build errors for what slice 2 does not restyle (house style:
# never silently no-op an unimplemented override -- CLAUDE.md §7)


def test_pattern_font_override_is_a_friendly_error(write_design, bag):
    text = BASE + """
elements:
  - id: p
    type: pattern
    pattern: linear
    count: 2
    step: {dx: 20px, dy: 0}
    color: palette.fg
    aod: {font: FONT_SMALL}
    parts:
      - {shape: text, text: "x", font: FONT_MEDIUM}
"""
    face = load(write_design(text), bag)
    assert face is None
    hits = [d for d in bag.errors if d.code == "aod"]
    assert hits, bag.render()
    assert "pattern" in hits[0].message and "not implemented" in hits[0].message


def test_complication_slot_font_override_is_a_friendly_error(write_design, bag):
    text = BASE + """
config:
  data:
    top:
      default: complication.heart_rate
      choices: [complication.heart_rate]
elements:
  - id: slot
    type: complication_slot
    slot: config.data.top
    color: palette.fg
    aod: {font: FONT_SMALL}
"""
    face = load(write_design(text), bag)
    assert face is None
    hits = [d for d in bag.errors if d.code == "aod"]
    assert hits, bag.render()
    assert "complication_slot" in hits[0].message and "not implemented" in hits[0].message


def test_vector_face_font_override_is_a_friendly_error(write_design, bag):
    """An `aod: {font: ...}` naming a `face:` (vector) font -- rejected
    regardless of which kind of font the element itself draws with while
    awake."""
    text = BASE + """
fonts:
  night_face:
    face: [RobotoCondensedRegular]
    size: 20%r
elements:
  - id: clock
    type: text
    text: "12:00"
    font: FONT_MEDIUM
    color: palette.fg
    aod: {font: font.night_face}
"""
    face = load(write_design(text), bag)
    assert face is None
    hits = [d for d in bag.errors if d.code == "aod"]
    assert hits, bag.render()
    assert "vector" in hits[0].message and "not implemented" in hits[0].message


def test_polygon_filled_override_is_a_friendly_error(write_design, bag):
    """A polygon has no outline primitive (Dc has fillPolygon, no
    drawPolygon) -- an `aod: {filled: ...}` override must be refused the
    same way the awake `filled: false` already is, not silently ignored."""
    text = BASE + """
elements:
  - id: tri
    type: shape
    shape: polygon
    points:
      - {dx: 0px, dy: -10px}
      - {dx: 10px, dy: 10px}
      - {dx: -10px, dy: 10px}
    color: palette.fg
    aod: {filled: false}
"""
    face = load(write_design(text), bag)
    assert face is None
    hits = [d for d in bag.errors if d.code == "aod"]
    assert hits, bag.render()
    assert "polygon" in hits[0].message and "drawPolygon" in hits[0].message


# -- the same refusals when the key is inherited from a group (plan 18 item 5)

_GROUP_AOD_CHILDREN = {
    "slot": """
      - id: slot
        type: complication_slot
        slot: config.data.top
        color: palette.fg
""",
    "tri": """
      - id: tri
        type: shape
        shape: polygon
        points:
          - {dx: 0px, dy: -10px}
          - {dx: 10px, dy: 10px}
          - {dx: -10px, dy: 10px}
        color: palette.fg
""",
    "label": """
      - id: label
        type: text
        text: "12:00"
        color: palette.fg
""",
    "p": """
      - id: p
        type: pattern
        pattern: linear
        count: 2
        step: {dx: 20px, dy: 0}
        color: palette.fg
        parts:
          - {shape: text, text: "x", font: FONT_MEDIUM}
""",
}

_GROUP_AOD_CONFIG = """
config:
  data:
    top:
      default: complication.heart_rate
      choices: [complication.heart_rate]
"""


def _group_aod_design(aod: str, children: list[str]) -> str:
    return BASE + _GROUP_AOD_CONFIG + f"""
elements:
  - id: g
    type: group
    aod: {aod}
    children:""" + "".join(_GROUP_AOD_CHILDREN[c] for c in children)


def test_group_inherited_unsupported_aod_keys_are_errors_on_each_element(write_design, bag):
    """The plan's scratch design: before plan 18 item 5 this validated "ok",
    every key silently dropped by codegen."""
    text = _group_aod_design('{font: FONT_TINY, filled: false, format: "{:%H}"}',
                             ["slot", "tri", "label", "p"])
    assert load(write_design(text), bag) is None
    hits = [d for d in bag.errors if d.code in ("aod", "format")]
    assert sorted(d.message.split(":")[0] for d in hits) == ["label", "p", "slot", "tri"], \
        bag.render()
    for d in hits:
        assert "inherited from group 'g'" in d.message
        assert any("line" in note and "'g'" in note for note in d.notes), d.notes


@pytest.mark.parametrize("aod,child,needle", [
    ("{font: FONT_TINY}", "slot", "complication_slot"),
    ("{font: FONT_TINY}", "p", "pattern"),
    ("{filled: false}", "tri", "drawPolygon"),
    ('{format: "{:%H}"}', "label", "fixed 'text:'"),
])
def test_each_group_inherited_refusal_on_its_own(write_design, bag, aod, child, needle):
    text = _group_aod_design(aod, [child])
    assert load(write_design(text), bag) is None
    hits = [d for d in bag.errors if d.code in ("aod", "format")]
    assert len(hits) == 1, bag.render()
    assert hits[0].message.startswith(f"{child}:")
    assert needle in hits[0].message


def test_a_group_key_that_a_kind_supports_is_not_an_error(write_design, bag):
    """The contrast: the same group `aod: {font: ...}` over a plain text
    element, and `filled:` over a circle, are real overrides."""
    text = BASE + """
elements:
  - id: g
    type: group
    aod: {font: FONT_TINY, filled: false}
    children:
      - id: label
        type: text
        text: "12:00"
        color: palette.fg
      - id: dot
        type: shape
        shape: circle
        radius: 10%r
        filled: true
        color: palette.fg
"""
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    assert _by_id(face, "label").aod.font == "FONT_TINY"
    assert _by_id(face, "dot").aod.filled is False


def test_an_elements_own_key_shadows_the_groups_unsupported_one(write_design, bag):
    """Only an *inherited* key is checked here: an element whose own block
    sets the key has already been judged on its own line, once."""
    text = BASE + _GROUP_AOD_CONFIG + """
elements:
  - id: g
    type: group
    aod: {format: "{:%H}"}
    children:
      - id: clock
        type: text
        value: time.clock
        format: "{:%H:%M}"
        color: palette.fg
        aod: {format: "{:%H.%M}"}
"""
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    assert _by_id(face, "clock").aod.format == "{:%H.%M}"


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


def test_an_all_mip_build_has_no_display_mode_code_either(write_design, bag, db):
    """The same byte-identical guarantee, restated for slice 6's own new
    lines specifically: an all-MIP build must carry none of the
    `getDisplayMode`/`DISPLAY_MODE_OFF` ladder, not just none of `_aod`
    itself -- would fail against an implementation that forgot to gate the
    new check behind `aod` (build-time `amoled_target`) the same way every
    other `_aod_*` helper already is."""
    without = MIP_BASE + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""
    view = _view_text(without, write_design, bag, db)
    assert "DISPLAY_MODE_OFF" not in view
    assert "getDisplayMode" not in view


# --------------------------------------------------------------------------
# the getDisplayMode ladder (plan 14 slice 6, research 11 §6 F): skip
# drawing entirely on DISPLAY_MODE_OFF, guarded per device.


def _view_text_multi(text, write_design, bag, db, device_ids):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    devices = [db.get(device_id) for device_id in device_ids]
    baked = {device.id: bake_fonts(face, device) for device in devices}
    project = generate(face, devices, write_design("").parent / "build", baked)
    return next(v for k, v in project.files().items() if k.endswith("View.mc"))


_ONE_CLOCK = """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: show
"""


def test_aod_frame_returns_early_on_display_mode_off_before_any_drawing(write_design, bag, db):
    """`fenix847mm` has `getDisplayMode` (research 11 §2): the AOD frame
    must check `DISPLAY_MODE_OFF` and return *before* the black clear and
    every element draw, not merely skip individual draw calls -- would pass
    against a broken implementation that checked the mode only around the
    per-element calls (still clearing to black on an unlit panel) if the
    ordering were not asserted directly."""
    view = _view_text(BASE + _ONE_CLOCK, write_design, bag, db, device_id="fenix847mm")
    body = view.split("function onUpdate(dc as Dc) as Void {")[1]
    off_check = body.find("DISPLAY_MODE_OFF")
    clear = body.find("dc.clear();")
    assert off_check != -1, view
    assert clear != -1, view
    assert off_check < clear, (
        "the DISPLAY_MODE_OFF check must run before the AOD frame clears to black"
    )
    guard_and_return = body[off_check - 200:clear]
    assert "return;" in guard_and_return, guard_and_return


def test_display_mode_check_is_has_guarded_when_a_target_lacks_the_symbol(write_design, bag, db):
    """`fenix8solar47mm` has no `getDisplayMode` at all (research 11 §2) --
    mixed into the same build as `fenix847mm` (constraint 6d: the shared
    view is one file `monkeyc` compiles once per device), the call must be
    wrapped in `System has :getDisplayMode`, mirroring
    `Guards.burn_in_field_guarded`'s own shape. Would fail against an
    implementation that always emits the bare call."""
    text = BASE.replace("targets: [fenix847mm]", "targets: [fenix847mm, fenix8solar47mm]")
    view = _view_text_multi(
        text + _ONE_CLOCK, write_design, bag, db, ["fenix847mm", "fenix8solar47mm"]
    )
    assert (
        "if ((System has :getDisplayMode) && "
        "(System.getDisplayMode() == System.DISPLAY_MODE_OFF)) {"
    ) in view


def test_display_mode_check_is_unguarded_when_every_target_has_the_symbol(write_design, bag, db):
    """`fenix847mm` and `fenix947mm` both have `getDisplayMode` -- an
    AMOLED-only build of the two must skip the has-check, the same "no
    guard for a thing every target has" rule `fields`/`vector_fonts`/
    `burn_in_field_guarded` already follow. Would fail against an
    implementation that always wraps the call in a has-check."""
    text = BASE.replace("targets: [fenix847mm]", "targets: [fenix847mm, fenix947mm]")
    view = _view_text_multi(
        text + _ONE_CLOCK, write_design, bag, db, ["fenix847mm", "fenix947mm"]
    )
    assert "if (System.getDisplayMode() == System.DISPLAY_MODE_OFF) {" in view
    assert "System has :getDisplayMode" not in view


@pytest.mark.slow
def test_display_mode_ladder_compiles_warning_free_on_a_mixed_build(
        write_design, db, tmp_path, toolchain):
    """The real `monkeyc` build, not just Python-level codegen: a mixed
    AMOLED + MIP build must compile warning-free on every target with the
    new `getDisplayMode` ladder in place -- the has-guarded form on the MIP
    devices, the plain form is never reached on them since `_aod` stays
    false there (D5)."""
    text = BASE.replace(
        "targets: [fenix847mm]", "targets: [fenix847mm, fenix8solar47mm, fr955]"
    ) + _ONE_CLOCK
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, "\n".join(d.message for d in warnings)


# --------------------------------------------------------------------------
# restyling (plan 14 slice 2): one ternary/branch per override key


def _layout_text(text, write_design, bag, db, device_id="fenix847mm"):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get(device_id)
    baked = {device.id: bake_fonts(face, device)}
    project = generate(face, [device], write_design("").parent / "build", baked)
    return next(v for k, v in project.files().items() if k.endswith("Layout.mc"))


def test_color_ternary_emitted_only_for_the_overridden_element(write_design, bag, db):
    """One override key (`color`), on one element only -- a sibling with no
    `aod:` at all must keep its plain, unrestyled `dc.setColor` line."""
    text = BASE + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: {color: palette.dim}
  - id: plain
    type: text
    text: "plain"
    color: palette.fg
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    assert "dc.setColor((_aod ? Palette.DIM : Palette.FG), Graphics.COLOR_TRANSPARENT);" in view
    plain = view.split("function drawPlain")[1].split("\n    }")[0]
    assert "_aod" not in plain
    assert "dc.setColor(Palette.FG, Graphics.COLOR_TRANSPARENT);" in plain


def test_track_color_ternary_on_progress(write_design, bag, db):
    text = BASE + """
elements:
  - id: bar
    type: progress
    style: arc
    value: system.battery
    max: 100
    radius: 40%r
    thickness: 4px
    start_angle: 0deg
    sweep: 300deg
    color: palette.fg
    track_color: palette.dim
    aod: {track_color: palette.bg}
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    assert "dc.setColor((_aod ? Palette.BG : Palette.DIM), Graphics.COLOR_TRANSPARENT);" in view


def test_icon_color_ternary_on_complication_slot(write_design, bag, db):
    text = BASE + """
config:
  data:
    top:
      default: complication.heart_rate
      choices: [complication.heart_rate]
elements:
  - id: slot
    type: complication_slot
    slot: config.data.top
    color: palette.fg
    icon_size: 20px
    icon_color: palette.dim
    aod: {icon_color: palette.bg}
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    assert "_aod ? Palette.BG : Palette.DIM" in view


def test_thickness_ternary_on_shape_and_layout_constant(write_design, bag, db):
    """A `line` shape's thickness is a `Layout` constant (unlike a circle's,
    which is inlined as a plain per-device literal) -- the ternary lives at
    that call site."""
    text = BASE + """
elements:
  - id: ring
    type: shape
    shape: line
    at: {dx: -20%, dy: 0}
    to: {dx: 20%, dy: 0}
    thickness: 4px
    color: palette.fg
    aod: {thickness: 1px}
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    assert "dc.setPenWidth((_aod ? Layout.RING_AOD_THICKNESS : Layout.RING_THICKNESS));" in view
    layout = _layout_text(text, write_design, Bag(), db)
    assert "RING_AOD_THICKNESS" in layout


def test_bar_width_ternary_on_graph(write_design, bag, db):
    text = BASE + """
elements:
  - id: g
    type: graph
    style: bars
    series: steps
    range: 7d
    size: {width: 50%, height: 10%}
    color: palette.fg
    bar_width: 6px
    min: 0
    max: auto
    aod: {bar_width: 2px}
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    assert ("_aod ? Layout.G_AOD_BAR_WIDTH : Layout.G_BAR_WIDTH" in view)


def test_filled_override_wraps_both_draw_calls(write_design, bag, db):
    """`filled: true -> false` changes the draw call itself, not an
    argument -- must fail against an implementation that only ternaries
    `color`/`thickness` and ignores `filled`."""
    text = BASE + """
elements:
  - id: dot
    type: shape
    shape: circle
    radius: 10%r
    filled: true
    color: palette.fg
    aod: {filled: false, thickness: 1px}
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    body = view.split("function drawDot")[1].split("\n    }")[0]
    assert "if (_aod)" in body
    assert "dc.fillCircle(" in body
    assert "dc.drawCircle(" in body


def test_format_ternary_on_text(write_design, bag, db):
    text = BASE + """
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    color: palette.fg
    aod: {format: "{:%H.%M}"}
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    body = view.split("function drawClock")[1].split("\n    }")[0]
    assert '"."' in body or "'.'" in body
    assert "_aod ?" in body
    assert ':"' in body or "':'" in body


def test_aod_format_with_its_own_extra_reader_declares_it(write_design, bag, db):
    """Plan 18 item 1: `%h` needs `device.is_24_hour`'s reader.  When only
    the `aod: {format: ...}` override uses it, the awake format alone must
    not decide which readers the draw method gets, or `monkeyc` fails with
    `Undefined symbol ':settings'`."""
    text = BASE + """
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    color: palette.fg
    aod: {format: "{:%h:%M}"}
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    signature = view.split("function drawClock(")[1].split(")")[0]
    assert "settings" in signature
    body = view.split("function drawClock")[1].split("\n    }")[0]
    assert "settings.is24Hour" in body


def _barrel(text, write_design, bag, db, device_id="fenix847mm"):
    from wfb.emit.project import _barrel_for

    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get(device_id)
    return _barrel_for(face, resolve(face, device, bake_fonts(face, device)))


_CLOCK_WITH_AOD = BASE + """
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    color: palette.fg
    aod: {format: "{:%I:%M}"}
"""


def test_wftime_is_copied_only_for_a_code_that_calls_it(write_design, bag, db):
    """Plan 18 item 9: `%H:%M` never calls `WfbTime`, so the barrel file is
    not copied for it (before, any time format pulled it in)."""
    text = _CLOCK_WITH_AOD.replace('    aod: {format: "{:%I:%M}"}\n', "")
    assert "WfbTime.mc" not in _barrel(text, write_design, bag, db)


def test_wftime_is_copied_when_only_the_aod_format_calls_it(write_design, bag, db):
    """The contrast, and the trap in tightening the rule: `%I` in the AOD
    override alone emits `WfbTime.hour12`, so the file must still come."""
    assert "WfbTime.mc" in _barrel(_CLOCK_WITH_AOD, write_design, bag, db)


@pytest.mark.parametrize("style,wants_arc", [("bar", False), ("arc", True)])
def test_wfbarc_is_copied_only_for_an_arc_progress(write_design, bag, db, style, wants_arc):
    """Plan 18 item 9: a bar progress draws with fillRectangle and never
    calls `WfbArc`; only the arc style does."""
    geometry = ("at: {anchor: center}\n    size: {width: 50%, height: 5%}" if style == "bar"
                else "at: {anchor: center}\n    radius: 40%r\n    thickness: 4px\n"
                     "    start_angle: 0deg\n    sweep: 360deg")
    text = BASE + f"""
elements:
  - id: bar
    type: progress
    style: {style}
    value: 5
    max: 10
    {geometry}
    color: palette.fg
"""
    assert ("WfbArc.mc" in _barrel(text, write_design, bag, db)) is wants_arc


@pytest.mark.slow
def test_a_wftime_code_in_the_aod_format_alone_compiles(write_design, db, tmp_path, toolchain):
    bag = Bag()
    result = real_build(write_design(_CLOCK_WITH_AOD), output=tmp_path, bag=bag, db=db,
                        toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()


@pytest.mark.slow
def test_aod_format_with_its_own_extra_reader_compiles(write_design, db, tmp_path, toolchain):
    """The real `monkeyc` half of the test above: before plan 18 item 1 this
    exact design failed with `Undefined symbol ':settings'`."""
    text = BASE + """
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    color: palette.fg
    aod: {format: "{:%h:%M}"}
"""
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, "\n".join(d.message for d in warnings)


def test_own_aod_format_with_an_unknown_strftime_code_is_a_friendly_error(write_design, bag):
    """An `aod: {format: ...}` override is a strftime-style spec exactly
    like the awake `format:` it restyles -- it must go through the same
    `Builder._check_format` checks, not reach `formatting.emit`/`render`
    unvalidated and crash with a raw `FormatError` (must fail against an
    implementation that stores `aod.format` verbatim with no check at
    all)."""
    text = BASE + """
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    color: palette.fg
    aod: {format: "{:%Q}"}
"""
    face = load(write_design(text), bag)
    assert face is None
    hits = [d for d in bag.errors if d.code == "format"]
    assert hits, bag.render()
    assert "%Q" in hits[0].message


def test_own_aod_format_with_the_wrong_code_table_is_a_friendly_error(write_design, bag):
    """The same date-code-on-a-clock-value (and reverse) mismatch
    `_check_format` already catches for the awake `format:` -- `%M` is a
    time code (minute), not a date one, and a `date.today` value's `aod:`
    override must be checked against `DATE_CODES`, not silently accepted."""
    text = BASE + """
elements:
  - id: today
    type: text
    value: date.today
    format: "{:%a %e %b}"
    color: palette.fg
    aod: {format: "{:%M}"}
"""
    face = load(write_design(text), bag)
    assert face is None
    hits = [d for d in bag.errors if d.code == "format"]
    assert hits, bag.render()
    assert "date code %M" in hits[0].message


def test_ancestor_group_aod_format_is_checked_against_the_descendant_value(write_design, bag):
    """A group's own `aod: {format: ...}` (D2.3: the union of what its
    descendants allow) reaches a text descendant by the ordinary key-by-key
    resolution rule -- it must be checked against *that* descendant's bound
    value type too, not just an element's own override (`_resolve_aod`)."""
    text = BASE + """
elements:
  - id: g
    type: group
    aod: {format: "{:%Q}"}
    children:
      - id: clock
        type: text
        value: time.clock
        format: "{:%H:%M}"
        color: palette.fg
"""
    face = load(write_design(text), bag)
    assert face is None
    hits = [d for d in bag.errors if d.code == "format"]
    assert hits, bag.render()
    assert "%Q" in hits[0].message


def test_system_font_override_on_text(write_design, bag, db):
    text = BASE + """
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    font: FONT_NUMBER_MEDIUM
    color: palette.fg
    aod: {font: FONT_NUMBER_MILD}
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    assert "_aod ? Graphics.FONT_NUMBER_MILD : Graphics.FONT_NUMBER_MEDIUM" in view


def test_elements_without_overrides_are_untouched(write_design, bag, db):
    """An element with no `aod:` at all generates exactly what it always
    did -- no `_aod` anywhere in its own method."""
    text = BASE + """
elements:
  - id: plain_shape
    type: shape
    shape: rectangle
    size: {width: 10%, height: 10%}
    color: palette.fg
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    body = view.split("function drawPlainShape")[1].split("\n    }")[0]
    assert "_aod" not in body


def test_static_element_bypasses_its_buffer_in_aod(write_design, bag, db):
    """plan 14 §4.4: a static element with its own `aod:` override draws
    directly in the AOD branch -- must fail against an implementation that
    still excludes every static id from the AOD call list."""
    text = BASE + """
elements:
  - id: label
    type: text
    text: "hi"
    static: true
    color: palette.fg
    aod: {color: palette.dim}
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    on_update = view.split("function onUpdate")[1].split("\n    function ")[0]
    aod_branch = on_update.split("if (_aod) {", 1)[1].split("\n        else {", 1)[0]
    assert "drawLabel(dc" in aod_branch


def test_aod_only_baked_font_is_loaded_only_in_on_enter_sleep(write_design, bag, db):
    """plan 14 §4.3: a baked font named only by an `aod: {font: ...}`
    override is a second resource -- never loaded in onLayout, only inside
    onEnterSleep's own `if (_aod)`, and released again in onExitSleep."""
    text = BASE + f"""
fonts:
  clock_font:
    source: {ROOT / "tests" / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"}
    size: 30%r
  night_font:
    source: {ROOT / "tests" / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"}
    size: 24%r
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{{:%H:%M}}"
    font: font.clock_font
    color: palette.fg
    aod: {{color: palette.dim, font: font.night_font}}
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    assert "_fontNightFont" in view
    on_layout = view.split("function onLayout")[1].split("\n    function ")[0]
    assert "NightFont" not in on_layout  # not loaded up front
    enter_sleep = view.split("function onEnterSleep")[1].split("\n    function ")[0]
    assert "if (_aod)" in enter_sleep
    assert "_fontNightFontAod = WatchUi.loadResource" in enter_sleep
    exit_sleep = view.split("function onExitSleep")[1].split("\n    function ")[0]
    assert "_fontNightFontAod = null;" in exit_sleep


def test_hands_color_and_thickness_apply_uniformly_to_every_part(write_design, bag, db):
    text = BASE + """
hands:
  set:
    hour:
      color: palette.fg
      parts:
        - {shape: line, at: {dy: 0}, to: {dy: -40px}, thickness: 3px}
    minute:
      color: palette.dim
      parts:
        - {shape: line, at: {dy: 0}, to: {dy: -60px}, thickness: 2px}
elements:
  - id: h
    type: hands
    hands: set
    aod: {color: palette.bg, thickness: 1px}
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    body = view.split("function drawH(")[1].split("\n    }")[0]
    # every dc.setColor line in this method must be the same uniform ternary
    for line in body.splitlines():
        if "dc.setColor(" in line:
            assert "_aod ? Palette.BG : " in line
    assert "_aod ? Layout.H_AOD_THICKNESS : " in body


def test_pattern_color_and_thickness_apply_uniformly_to_every_part(write_design, bag, db):
    text = BASE + """
elements:
  - id: p
    type: pattern
    pattern: radial
    count: 4
    color: palette.fg
    aod: {color: palette.dim, thickness: 1px}
    parts:
      - {shape: line, at: {dy: 0}, to: {dy: -20px}, thickness: 3px}
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    body = view.split("function drawP(")[1].split("\n    }")[0]
    assert "_aod ? Palette.DIM : Palette.FG" in body
    assert "_aod ? Layout.P_AOD_THICKNESS : " in body


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


# --------------------------------------------------------------------------
# preview (plan 14 slice 2): overridden colour and thickness actually render


def _resolved(text, write_design, bag, db, device_id="fenix847mm"):
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get(device_id)
    return resolve(face, device, bake_fonts(face, device))


def test_preview_aod_renders_the_overridden_colour(write_design, bag, db):
    """A filled rectangle's `aod: {color: ...}` must actually change the
    rendered pixel colour under `--aod` -- must fail against a preview that
    still reads the element's plain, awake `color:` there."""
    from wfb.preview import PreviewOptions, render

    text = BASE + """
elements:
  - id: block
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 40%, height: 40%}
    color: palette.fg
    aod: {color: palette.dim}
"""
    resolved = _resolved(text, write_design, bag, db)
    cx, cy = resolved.device.width // 2, resolved.device.height // 2
    awake = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    # `aod_mask=False`: this test is about the colour override, not plan
    # 16's pixel mask (on by default), which would black out this exact
    # pixel on some clock minutes regardless of which colour got drawn --
    # an orthogonal concern with its own coverage in
    # `tests/test_aod_mask_preview.py`.
    asleep = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False, aod=True,
                                             aod_mask=False))
    assert awake.getpixel((cx, cy)) == (255, 255, 255)  # palette.fg
    assert asleep.getpixel((cx, cy)) == (0x55, 0x55, 0x55)  # palette.dim


def test_preview_aod_renders_the_overridden_thickness(write_design, bag, db):
    """An unfilled shape's `aod: {thickness: ...}` must actually change how
    many pixels the rendered stroke covers under `--aod`."""
    from wfb.preview import PreviewOptions, render

    text = BASE + """
elements:
  - id: ring
    type: shape
    shape: line
    at: {dx: -40%, dy: 0}
    to: {dx: 40%, dy: 0}
    thickness: 10px
    color: palette.fg
    aod: {thickness: 2px}
"""
    resolved = _resolved(text, write_design, bag, db)
    cy = resolved.device.height // 2
    cx = resolved.device.width // 2

    def stroke_height(image) -> int:
        count = 0
        for dy in range(-10, 11):
            pixel = image.getpixel((cx, cy + dy))
            if pixel != (0, 0, 0):
                count += 1
        return count

    awake = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    asleep = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False, aod=True))
    assert stroke_height(awake) > stroke_height(asleep)


def test_preview_aod_renders_the_filled_override(write_design, bag, db):
    """`aod: {filled: false}` must actually stop the preview from filling
    the shape's interior."""
    from wfb.preview import PreviewOptions, render

    text = BASE + """
elements:
  - id: dot
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 30%r
    filled: true
    color: palette.fg
    aod: {filled: false, thickness: 2px}
"""
    resolved = _resolved(text, write_design, bag, db)
    cx, cy = resolved.device.width // 2, resolved.device.height // 2
    awake = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    asleep = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False, aod=True))
    # the centre of the disc is lit while awake (filled)...
    assert awake.getpixel((cx, cy)) == (255, 255, 255)
    # ...and unlit in AOD, where only a thin ring near the edge is drawn.
    assert asleep.getpixel((cx, cy)) == (0, 0, 0)


def test_preview_aod_renders_the_overridden_system_font(write_design, bag, db):
    """`aod: {font: ...}` naming a *system* font (not a baked one) must
    actually swap the drawn typeface's size under `--aod` too -- the same
    override `test_system_font_override_on_text` proves codegen honours
    (`_aod ? Graphics.FONT_NUMBER_MILD : Graphics.FONT_NUMBER_MEDIUM`).
    Must fail against a preview whose `_text` only ever swapped a
    baked/custom font override (gated on `element.aod.font_is_custom`),
    silently ignoring a system-font one."""
    from wfb.preview import PreviewOptions, render

    text = BASE + """
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    font: FONT_NUMBER_MEDIUM
    color: palette.fg
    aod: {font: FONT_NUMBER_MILD}
"""
    resolved = _resolved(text, write_design, bag, db)

    def ink_rows(image) -> int:
        """How many rows have any non-black pixel -- a cheap proxy for the
        drawn glyphs' vertical extent, which shrinks with a smaller font."""
        return sum(
            1 for y in range(image.height)
            if any(image.getpixel((x, y)) != (0, 0, 0) for x in range(image.width))
        )

    awake = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    asleep = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False, aod=True))
    assert ink_rows(asleep) < ink_rows(awake)


# --------------------------------------------------------------------------
# `aod: dim:` (plan 14 slice 3, docs/guide/always-on-display.md): scales the
# luminance of every AOD colour, override colours excepted.


def test_dim_0_is_a_schema_error(write_design, bag):
    """0 would dim every undimmed colour to black -- indistinguishable from
    `aod: hide` -- so the schema refuses it outright (`exclusiveMinimum: 0`),
    the same house style a bad `modes: [always_on]` already gets (D3)."""
    text = BASE.replace("palette:\n", "aod:\n  dim: 0\npalette:\n") + "elements:\n" + """  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""
    face = load(write_design(text), bag)
    assert face is None
    hits = [d for d in bag.errors if d.code == "schema"]
    assert hits and "dim" in hits[0].message, bag.render()


def test_a_show_only_element_is_dimmed_to_its_exact_value(write_design, bag, db):
    """`dim` reaches every colour the AOD frame draws, not only overridden
    ones -- a plain `aod: show`, with no override block at all, still gets a
    dimming ternary, against the exact per-channel value `wfb.palette.
    dim_channel` computes: 0x55 * 0.4, rounded, is 0x22 on every channel."""
    text = BASE.replace("palette:\n", "aod:\n  dim: 0.4\npalette:\n") + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.dim
    aod: show
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    assert "dc.setColor((_aod ? 0x222222 : Palette.DIM), Graphics.COLOR_TRANSPARENT);" in view


def test_an_explicit_override_colour_is_never_dimmed(write_design, bag, db):
    """The author's own `aod: {color: ...}` is the final word -- must fail
    against an implementation that dims an override the same as anything
    else. A sibling with no override of its own is dimmed in the same
    build, so this cannot pass by `dim` silently doing nothing at all."""
    text = BASE.replace("palette:\n", "aod:\n  dim: 0.4\npalette:\n") + """
elements:
  - id: overridden
    type: text
    text: "12:00"
    color: palette.dim
    aod: {color: palette.bg}
  - id: plain
    type: text
    text: "plain"
    color: palette.dim
    aod: show
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    # the override colour, Palette.BG, appears bare -- never as a dimmed literal
    assert "dc.setColor((_aod ? Palette.BG : Palette.DIM), Graphics.COLOR_TRANSPARENT);" in view
    plain = view.split("function drawPlain")[1].split("\n    }")[0]
    assert "dc.setColor((_aod ? 0x222222 : Palette.DIM), Graphics.COLOR_TRANSPARENT);" in plain


def test_a_runtime_role_colour_is_dimmed_with_the_generated_helper(write_design, bag, db):
    """`config.colors.<role>` is a view field the wearer's on-device pick can
    repoint, so it cannot be pre-dimmed into a build-time literal the way a
    `palette.<name>` reference can -- it must go through the generated
    `WfbColor.dim` at runtime instead. Must fail against an implementation
    that only handles the compile-time-constant case."""
    text = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix847mm]
aod:
  dim: 0.4
palette:
  black: "#000000"
  white: "#FFFFFF"
color_scheme:
  dark:
    colors: {fg: palette.white}
config:
  style:
    default: dark
    choices:
      dark: {colors: dark}
elements:
  - id: clock
    type: text
    text: "12:00"
    color: config.colors.fg
    aod: show
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    assert ("dc.setColor((_aod ? WfbColor.dim(_configColorsFg, 400, 1000) : "
            "_configColorsFg), Graphics.COLOR_TRANSPARENT);") in view


def test_dim_absent_or_dim_1_is_byte_identical(write_design, bag, db):
    """`dim: 1` and no `dim:` at all must mean exactly the same thing --
    identity -- and neither may emit a single dimming ternary."""
    without = BASE + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: show
"""
    dim_one = BASE.replace("palette:\n", "aod:\n  dim: 1\npalette:\n") + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: show
"""
    bag_a, bag_b = Bag(), Bag()
    text_a = _view_text(without, write_design, bag_a, db, device_id="fenix847mm")
    text_b = _view_text(dim_one, write_design, bag_b, db, device_id="fenix847mm")
    assert text_a == text_b
    assert "WfbColor.dim" not in text_a


def test_an_all_mip_build_stays_byte_identical_with_dim_set(write_design, bag, db):
    """`dim` is AMOLED-only like the rest of `aod:` (constraint 5): an
    all-MIP build's generated source must not change at all, even with
    `dim:` set and an element drawn in AOD -- the same guarantee slice 1
    established for `aod:` itself, now re-checked with `dim:` in the mix."""
    without = MIP_BASE + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""
    with_dim = MIP_BASE.replace(
        "palette:\n", "aod:\n  default: hide\n  dim: 0.4\npalette:\n"
    ) + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: {color: palette.fg}
"""
    bag_a, bag_b = Bag(), Bag()
    text_a = _view_text(without, write_design, bag_a, db)
    text_b = _view_text(with_dim, write_design, bag_b, db)
    assert text_a == text_b
    assert "_aod" not in text_a and "WfbColor" not in text_a


def test_preview_and_codegen_dim_the_same_colour_identically(write_design, bag, db):
    """One colour, dimmed by both paths -- the codegen ternary's own literal
    and the preview's rendered pixel -- must land on the exact same value.
    `dim: 0.5` on `#555555` (85) is a genuine tie (42.5): a preview that used
    Python's own banker's-rounding `round()` instead of `wfb.palette.
    dim_channel`'s integer formula would compute 42 here, not 43, so this
    fails against that mismatch specifically."""
    from wfb.preview import PreviewOptions, render

    text = BASE.replace("palette:\n", "aod:\n  dim: 0.5\npalette:\n") + """
elements:
  - id: block
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 40%, height: 40%}
    color: palette.dim
    aod: show
"""
    view = _view_text(text, write_design, Bag(), db, device_id="fenix847mm")
    assert "dc.setColor((_aod ? 0x2B2B2B : Palette.DIM), Graphics.COLOR_TRANSPARENT);" in view

    resolved = _resolved(text, write_design, bag, db)
    cx, cy = resolved.device.width // 2, resolved.device.height // 2
    # `aod_mask=False`: this test is about the dimmed colour value, not
    # plan 16's pixel mask (on by default) -- see the sibling test above.
    asleep = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False, aod=True,
                                             aod_mask=False))
    assert asleep.getpixel((cx, cy)) == (0x2B, 0x2B, 0x2B) == (43, 43, 43)


def test_no_palette_lint_fires_on_a_dimmed_constant(write_design, bag, db):
    """plan 14 §4.6: the 64-colour palette lint checks `palette:`/`config:`/
    `color_scheme:`'s own *declared* entries, never a dimmed colour -- a
    dimmed value is a synthetic literal that never becomes one of those.
    `#FFFFFF` dimmed by 0.4 is `0x666666`, off the 64-colour grid, which
    would fail `Color.is_palette_legal` outright if this check ever looked
    at it -- must fail against an implementation that registers the dimmed
    constant as a new palette entry (or otherwise feeds it to the check)."""
    text = BASE.replace("palette:\n", "aod:\n  dim: 0.4\npalette:\n") + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: show
"""
    resolved = _resolved(text, write_design, bag, db)
    lint.run(resolved, bag)
    assert not any(d.code in ("palette", "palette-dither") for d in bag.items), bag.render()


def test_hands_colour_is_dimmed_per_part_with_no_override(write_design, bag, db):
    """`dim` reaches hands too (plan §3 item 3), independently per part --
    each part keeps its *own* colour, dimmed on its own value, when the
    hand set has no `aod: {color: ...}` override to apply uniformly
    instead. Must fail against an implementation that only wires `dim`
    through the plain shape/text/progress/icon/graph call sites."""
    text = BASE.replace("palette:\n", "aod:\n  dim: 0.4\npalette:\n") + """
hands:
  set:
    hour:
      color: palette.fg
      parts:
        - {shape: line, at: {dy: 0}, to: {dy: -40px}, thickness: 3px}
    minute:
      color: palette.dim
      parts:
        - {shape: line, at: {dy: 0}, to: {dy: -60px}, thickness: 2px}
elements:
  - id: h
    type: hands
    hands: set
    aod: show
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    body = view.split("function drawH(")[1].split("\n    }")[0]
    assert "(_aod ? 0x666666 : Palette.FG)" in body  # hour: palette.fg dimmed
    assert "(_aod ? 0x222222 : Palette.DIM)" in body  # minute: palette.dim dimmed


@pytest.mark.slow
def test_a_runtime_dimmed_colour_compiles_warning_free(write_design, db, tmp_path, toolchain):
    """The real `monkeyc` build, not just Python-level codegen, for a colour
    that goes through `WfbColor.dim` at runtime -- a face-level Python
    codegen test cannot catch a barrel file the real compiler needs but
    `wfb.emit.project._barrel_for` forgot to copy in (`Undefined symbol
    ':WfbColor'`, found by building this exact design for real while
    developing this slice: `_barrel_for` only listed the pre-existing
    helpers, so a design whose only dimmed colour was a `config.colors.*`
    field failed to compile even though the Python-level codegen tests above
    were all green)."""
    text = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: RuntimeDim
targets: [fenix847mm]
aod:
  dim: 0.5
palette:
  black: "#000000"
  white: "#FFFFFF"
color_scheme:
  dark:
    colors: {fg: palette.white}
config:
  style:
    default: dark
    choices:
      dark: {colors: dark}
elements:
  - id: clock
    type: text
    text: "12:00"
    color: config.colors.fg
    aod: show
"""
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, "\n".join(d.message for d in warnings)


# --------------------------------------------------------------------------
# burn-in (plan 14 slice 4, research 11 §6 D, ADR 0008 check 8): lit-pixel
# and luminance fractions from the same `--aod` render, per element.

#: A near-full-screen filled disc, shown unrestyled in AOD -- Garmin's FAQ
#: says any non-black pixel is "on" (research 11 §1.1), so this lights well
#: over both the pixel-count and the luminance halves of the 10% rule at
#: once, on purpose: the test must fail against a burn-in check that only
#: wires up one of the two bases.
_BIG_DISC = BASE + """
elements:
  - id: disc
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 90%r
    filled: true
    color: palette.fg
    aod: show
"""


def test_aod_burn_in_fires_when_a_design_lights_over_ten_percent(write_design, bag, db):
    resolved = _resolved(_BIG_DISC, write_design, bag, db)
    lint.check_aod_burn_in(resolved, bag)
    hits = [d for d in bag.items if d.code == "aod-burn-in"]
    assert hits, bag.render()
    assert hits[0].severity.value == "error"
    assert "disc" in hits[0].message


def test_aod_burn_in_passes_under_the_threshold(write_design, bag, db):
    """A single thin ring lights far under 10% -- must be a `note`, not a
    warning or an error, the same "the author sees the figure on every
    build" shape `graphics-pool` already uses. Must fail against an
    implementation that reports nothing at all once a design is clean, the
    same way `graphics-pool`'s own note-on-every-build guard would."""
    text = BASE + """
elements:
  - id: ring
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 90%r
    filled: false
    thickness: 1px
    color: palette.fg
    aod: show
"""
    resolved = _resolved(text, write_design, bag, db)
    lint.check_aod_burn_in(resolved, bag)
    hits = [d for d in bag.items if d.code == "aod-burn-in"]
    assert hits, bag.render()
    assert hits[0].severity.value == "note"
    assert bag.ok()


def test_aod_burn_in_names_the_right_top_contributor(write_design, bag, db):
    """Two AOD-shown discs of very different size: the diagnostic must name
    -- and anchor on -- the *actually* bigger contributor, not just the
    first or the last one declared. Must fail against an implementation
    that always blames the first/last AOD-shown element regardless of its
    real share.

    `mask: false`: this test is about attribution/ranking, not plan 16's
    pixel mask -- masking this design's lit fraction down to about a
    quarter would drop it under `AOD_BURN_IN_THRESHOLD` and turn the
    `error` this test checks for into a `note` (masking's own severity
    interaction has its own coverage in `tests/test_aod_mask_preview.py`).
    """
    text = BASE.replace("palette:\n", "aod:\n  mask: false\npalette:\n") + """
elements:
  - id: tiny
    type: shape
    shape: circle
    at: {anchor: center, dy: -40%}
    radius: 5%r
    filled: true
    color: palette.fg
    aod: show
  - id: huge
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 60%r
    filled: true
    color: palette.fg
    aod: show
"""
    resolved = _resolved(text, write_design, bag, db)
    lint.check_aod_burn_in(resolved, bag)
    hits = [d for d in bag.items if d.code == "aod-burn-in"]
    assert hits, bag.render()
    assert hits[0].severity.value == "error"
    assert "huge" in hits[0].message.split("top contributor:")[1].split(",")[0]
    huge = next(e for e in resolved.face.walk() if e.id == "huge")
    assert hits[0].span == huge.span


def test_aod_burn_in_is_suppressible_on_the_top_contributor(write_design, bag, db):
    text = _BIG_DISC.replace(
        "aod: show\n",
        'aod: show\n    lint: {allow: [aod-burn-in], reason: "deliberately bright, test"}\n',
    )
    resolved = _resolved(text, write_design, bag, db)
    lint.check_aod_burn_in(resolved, bag)
    assert "aod-burn-in" not in {d.code for d in bag.items}
    assert bag.ok()


def test_aod_burn_in_is_silent_on_a_mip_target(write_design, bag, db):
    """D5: `aod:` does not apply on MIP at all, so this must never even
    render -- checked with a design that would fail outright on an AMOLED
    target, so a check that forgot the device guard cannot pass by
    accident."""
    text = _BIG_DISC.replace("targets: [fenix847mm]", "targets: [fenix8solar47mm]")
    resolved = _resolved(text, write_design, bag, db, device_id="fenix8solar47mm")
    lint.check_aod_burn_in(resolved, bag)
    assert "aod-burn-in" not in {d.code for d in bag.items}


def test_aod_burn_in_is_silent_when_nothing_draws_in_aod(write_design, bag, db):
    """`aod-empty` already reports an empty AOD set; the burn-in check has
    nothing to measure or blame there and must stay silent rather than
    double up."""
    text = BASE + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""
    resolved = _resolved(text, write_design, bag, db)
    lint.check_aod_burn_in(resolved, bag)
    assert "aod-burn-in" not in {d.code for d in bag.items}


def test_the_aod_example_stays_clean_under_burn_in(write_design, bag, db):
    """The shipped example (`examples/features/aod/face.yaml`) must stay
    clean under this new check: a `note` is fine, a `warning` or `error` is
    not (plan 14 slice 4 §6)."""
    face = load(ROOT / "examples" / "features" / "aod" / "face.yaml", bag)
    assert face is not None, bag.render()
    device = db.get("fenix847mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    lint.check_aod_burn_in(resolved, bag)
    hits = [d for d in bag.items if d.code == "aod-burn-in"]
    assert hits, bag.render()
    assert hits[0].severity.value == "note", bag.render()


# --------------------------------------------------------------------------
# `wfb preview --heatmap`: the AOD frame summed over minutes


def test_heatmap_counts_each_minute_separately(write_design, bag, db):
    """A clock's digits change from minute to minute and a block does not, so
    a real sum has both full-white pixels and partial ones. Rendering one
    frame, or OR-ing frames together, would leave no partial pixel.

    `mask: false`: this test is about the heatmap's own summing logic, not
    plan 16's pixel mask (on by default), which would cap every pixel's
    share at 25% regardless of how the summing worked -- the mask's own
    heatmap ceiling has its own coverage in
    `tests/test_aod_mask_preview.py`."""
    from wfb.preview import PreviewOptions, render_aod_heatmap

    text = BASE.replace("palette:\n", "aod:\n  mask: false\npalette:\n") + """
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    at: {anchor: center}
    color: palette.fg
    aod: show
  - id: block
    type: shape
    shape: rectangle
    at: {anchor: center, dy: 30%}
    size: {width: 20, height: 20}
    color: palette.fg
    aod: show
"""
    resolved = _resolved(text, write_design, bag, db)
    heat, peak = render_aod_heatmap(resolved, PreviewOptions(scale=1),
                                    minutes=range(600, 604))
    values = set(heat.convert("L").getdata())
    assert peak == 1.0
    assert 255 in values
    assert values & {64, 127, 191}, sorted(values)
