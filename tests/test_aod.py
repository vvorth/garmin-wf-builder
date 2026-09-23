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
    asleep = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False, aod=True))
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
