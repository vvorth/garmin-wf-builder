"""`config: data:` and `type: complication_slot` -- the native editor's Data
axis (docs/research/09-data-library-and-config-axes.md §4).

Every check below is driven red against the exact violating input before it
is trusted, the same discipline `tests/test_color_scheme.py`'s own module
docstring states.
"""

from __future__ import annotations

import pytest

from tests.test_build import toolchain  # noqa: F401  -- a fixture, used by name
from tests.test_diagnostics import load
from wfb import complications, icons, lint
from wfb.diagnostics import Bag
from wfb.ir import ComplicationSlot, config_data_ids

HEAD = """format: 1
face:
  id: 6b2f9a3e-5c1d-4e8a-9f7b-3a1d6c8e2f40
  name: Test
targets: [fenix8solar47mm, fenix8solar51mm, fr955]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
"""

#: Two slots -- one an explicit list with an icon, one `any` with none --
#: exercising both shapes the feature has.
DATA_BLOCK = """config:
  data:
    top:
      default: complication.steps
      choices:
        - complication.steps
        - complication.heart_rate
        - complication.calories
    bottom:
      default: complication.body_battery
      choices: any
"""

BODY = """elements:
  - id: top_reading
    type: complication_slot
    slot: config.data.top
    at: {anchor: center, dy: -20%}
    icon_size: 8%r
    color: palette.fg
    label: short
    unit: true
    when_absent: placeholder
    placeholder: "--"
  - id: bottom_reading
    type: complication_slot
    slot: config.data.bottom
    at: {anchor: center, dy: 20%}
    color: palette.fg
    when_absent: placeholder
    placeholder: "--"
"""

DESIGN = HEAD + DATA_BLOCK + BODY


def _face(text, write_design, bag):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    return face


def _errors(text, write_design):
    bag = Bag()
    load(write_design(text), bag)
    return [d for d in bag.items if d.severity.value == "error"]


def _resolved(text, write_design, bag, db, device_id="fenix8solar47mm"):
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = _face(text, write_design, bag)
    device = db.get(device_id)
    return face, resolve(face, device, bake_fonts(face, device, device.minor_radius))


def _lint(text, write_design, db, device_id="fenix8solar47mm"):
    bag = Bag()
    _, resolved = _resolved(text, write_design, bag, db, device_id)
    lint.run(resolved, bag)
    return bag


# -- schema and IR ------------------------------------------------------------


def test_a_valid_design_builds_clean(write_design, bag):
    face = _face(DESIGN, write_design, bag)
    assert set(face.config_data) == {"top", "bottom"}
    top = face.config_data["top"]
    assert top.default == "steps"
    assert top.choices == ("steps", "heart_rate", "calories")
    assert not top.allow_any
    bottom = face.config_data["bottom"]
    assert bottom.default == "body_battery"
    assert bottom.allow_any


def test_has_config_is_true_for_data_alone(write_design, bag):
    """The case CLAUDE.md's task brief calls out by name: no accent_color/
    data_color/colors at all, only `config: data:`."""
    face = _face(DESIGN, write_design, bag)
    assert not face.config
    assert face.config_colors is None
    assert face.has_config


def test_config_data_ids_are_1_based_in_declaration_order(write_design, bag):
    face = _face(DESIGN, write_design, bag)
    assert config_data_ids(face) == {"top": 1, "bottom": 2}


def test_slot_field_is_a_stable_derived_name(write_design, bag):
    face = _face(DESIGN, write_design, bag)
    assert face.config_data["top"].field == "_configDataTop"
    assert face.config_data["bottom"].field == "_configDataBottom"


def test_element_slot_resolves_to_the_bare_name(write_design, bag):
    face = _face(DESIGN, write_design, bag)
    top = next(e for e in face.walk() if e.id == "top_reading")
    assert isinstance(top, ComplicationSlot)
    assert top.slot == "top"


# -- config: data: block errors -----------------------------------------------


def test_unknown_complication_type_in_default_is_an_error(write_design):
    text = HEAD + """config:
  data:
    top:
      default: complication.step
      choices: [complication.step]
""" + BODY
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "config"]
    assert hits, errors
    assert "unknown complication type" in hits[0].message
    assert "complication.step" in hits[0].message
    assert any("did you mean" in n and "steps" in n for n in hits[0].notes), hits[0].notes


def test_unknown_complication_type_in_choices_is_an_error(write_design):
    text = HEAD + """config:
  data:
    top:
      default: complication.steps
      choices: [complication.steps, complication.bogus]
""" + BODY
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "config"]
    assert any("complication.bogus" in d.message for d in hits), errors


def test_default_not_among_explicit_choices_is_an_error(write_design):
    text = HEAD + """config:
  data:
    top:
      default: complication.heart_rate
      choices: [complication.steps, complication.calories]
""" + BODY
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "config"]
    assert hits, errors
    assert "is not one of 'choices:'" in hits[0].message
    assert "complication.heart_rate" in hits[0].message


def test_a_rejected_slot_does_not_cascade(write_design):
    """One error, at the real mistake -- two elements reference the same
    rejected slot, so binding it into scope anyway is what keeps this to one
    error rather than one more per referencing element (the same cascade fix
    `fonts:`/`config:`/`palette:`/`color_scheme:` all needed)."""
    text = HEAD + """config:
  data:
    top:
      default: complication.bogus_type
      choices: [complication.bogus_type]
elements:
  - id: a
    type: complication_slot
    slot: config.data.top
    at: {anchor: center, dy: -20%}
    color: palette.fg
    when_absent: placeholder
    placeholder: "--"
  - id: b
    type: complication_slot
    slot: config.data.top
    at: {anchor: center, dy: 20%}
    color: palette.fg
    when_absent: placeholder
    placeholder: "--"
"""
    errors = _errors(text, write_design)
    assert len(errors) == 1, errors
    assert errors[0].code == "config"
    assert "unknown complication type" in errors[0].message


# -- complication_slot element errors -----------------------------------------


def test_unknown_slot_reference_is_an_error(write_design):
    text = HEAD + DATA_BLOCK + """elements:
  - id: a
    type: complication_slot
    slot: config.data.bogus
    at: {anchor: center}
    color: palette.fg
"""
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "complication-slot"]
    assert hits, errors
    assert "unknown slot 'config.data.bogus'" in hits[0].message
    assert any("config.data.top" in n and "config.data.bottom" in n for n in hits[0].notes), \
        hits[0].notes


def test_icon_size_with_choices_any_is_an_error(write_design):
    text = HEAD + DATA_BLOCK + """elements:
  - id: a
    type: complication_slot
    slot: config.data.bottom
    at: {anchor: center}
    icon_size: 8%r
    color: palette.fg
"""
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "complication-slot"]
    assert hits, errors
    assert "icon_size" in hits[0].message and "'any'" in hits[0].message


def test_format_is_rejected_with_a_reason(write_design):
    text = HEAD + DATA_BLOCK + """elements:
  - id: a
    type: complication_slot
    slot: config.data.top
    at: {anchor: center}
    color: palette.fg
    format: "{:d}"
"""
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "complication-slot"]
    assert hits, errors
    assert "'format:' is not accepted" in hits[0].message
    assert any("value.toString" in n or "union" in n for n in hits[0].notes), hits[0].notes


def test_on_hold_explicit_target_is_rejected(write_design):
    """A fixed hold target on a slot would silently disagree with whatever
    the wearer actually has it pointed at -- only 'auto' is accepted."""
    text = HEAD + DATA_BLOCK + """elements:
  - id: a
    type: complication_slot
    slot: config.data.top
    at: {anchor: center}
    color: palette.fg
    on_hold: steps
"""
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "complication-slot"]
    assert hits, errors
    assert "only accepts 'auto'" in hits[0].message
    assert "'steps'" in hits[0].message
    assert any("bind a plain" in n for n in hits[0].notes), hits[0].notes


def test_on_hold_auto_is_accepted(write_design, bag):
    """`on_hold: auto` is the one spelling this element accepts, and it is
    never resolved to a fixed `wfb.complications.TYPES` name -- unlike every
    other element's `auto`, it stays the literal sentinel so the emitter can
    special-case it into a dynamic `Complications.exitTo` read."""
    from wfb.ir import HOLD_AUTO

    text = HEAD + DATA_BLOCK + """elements:
  - id: a
    type: complication_slot
    slot: config.data.top
    at: {anchor: center}
    color: palette.fg
    on_hold: auto
"""
    face = _face(text, write_design, bag)
    element = next(e for e in face.walk() if e.id == "a")
    assert element.on_hold == HOLD_AUTO


def test_on_hold_absent_is_fine(write_design, bag):
    """No `on_hold:` at all is a legitimate choice -- holding does nothing."""
    face = _face(DESIGN, write_design, bag)
    for element in face.walk():
        if isinstance(element, ComplicationSlot):
            assert element.on_hold is None


def test_static_is_rejected(write_design):
    text = HEAD + DATA_BLOCK + """static:
  - id: a
    type: complication_slot
    slot: config.data.top
    at: {anchor: center}
    color: palette.fg
"""
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "static"]
    assert hits, errors
    assert "cannot be static" in hits[0].message


def test_missing_color_is_an_error(write_design):
    text = HEAD + DATA_BLOCK + """elements:
  - id: a
    type: complication_slot
    slot: config.data.top
    at: {anchor: center}
"""
    errors = _errors(text, write_design)
    assert any("needs a color" in d.message for d in errors), errors


def test_nullable_color_is_an_error(write_design):
    """There is no `when_absent:` for the element's own appearance -- only
    for the pulled reading."""
    text = HEAD + DATA_BLOCK + """elements:
  - id: a
    type: complication_slot
    slot: config.data.top
    at: {anchor: center}
    color: "heart_rate.current > 100 ? palette.fg : palette.fg"
"""
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "complication-slot"]
    assert hits and "can be absent" in hits[0].message, errors
    assert any("guard it in the expression" in n for n in hits[0].notes), hits[0].notes


def test_when_absent_placeholder_needs_a_placeholder(write_design):
    text = HEAD + DATA_BLOCK + """elements:
  - id: a
    type: complication_slot
    slot: config.data.top
    at: {anchor: center}
    color: palette.fg
    when_absent: placeholder
"""
    errors = _errors(text, write_design)
    assert any("needs a 'placeholder:'" in d.message for d in errors), errors


# -- lint: config-unsupported, extended to name slots -------------------------


def test_config_unsupported_names_the_data_axis_on_fr955(write_design, db):
    bag = _lint(DESIGN, write_design, db, device_id="fr955")
    hits = [d for d in bag.items if d.code == "config-unsupported"]
    assert hits, bag.render()
    assert "config.data.top" in hits[0].message and "config.data.bottom" in hits[0].message


def test_config_unsupported_is_silenced_by_lint_allow_on_any_relevant_element(write_design, db):
    """`check_config_support` emits one combined warning per device, naming
    every axis/slot the design has -- so `lint: {allow: [config-unsupported]}`
    on any *one* relevant element silences the whole message for that
    device, the same pre-existing shape `test_config.py`'s own colour-axis
    version of this check already has. Not a per-slot suppression."""
    text = DESIGN.replace(
        "    color: palette.fg\n    label: short",
        "    color: palette.fg\n    lint:\n      allow: [config-unsupported]\n"
        "      reason: test\n    label: short",
    )
    bag = _lint(text, write_design, db, device_id="fr955")
    hits = [d for d in bag.items if d.code == "config-unsupported"]
    assert not hits, bag.render()


# -- lint: complication-gated, extended to slot default/choices --------------


def test_complication_gated_fires_for_a_slots_default_on_fr955(write_design, db):
    """`sleep_score` needs ConnectIQ 6.0.2; fr955 tops out at 5.2.0 -- the
    same fact `docs/format.md`'s own `on_hold:`/`complication.*` examples
    already rely on, reused here for a slot's own `default:`."""
    assert complications.TYPES["sleep_score"].since == "6.0.2"
    text = HEAD + """config:
  data:
    top:
      default: complication.sleep_score
      choices: [complication.sleep_score, complication.steps]
elements:
  - id: top_reading
    type: complication_slot
    slot: config.data.top
    at: {anchor: center}
    color: palette.fg
    when_absent: placeholder
    placeholder: "--"
"""
    bag = _lint(text, write_design, db, device_id="fr955")
    hits = [d for d in bag.items if d.code == "complication-gated"]
    assert hits, bag.render()
    assert any("sleep_score" in d.message and "config.data.top" in d.message for d in hits), \
        [d.message for d in hits]


def test_complication_gated_does_not_check_choices_any(write_design, db):
    """`choices: any` has no list to check -- only `default:` is (the same
    `choices: any` carve-out `check_config_palette` already makes)."""
    text = HEAD + """config:
  data:
    bottom:
      default: complication.body_battery
      choices: any
""" + """elements:
  - id: bottom_reading
    type: complication_slot
    slot: config.data.bottom
    at: {anchor: center}
    color: palette.fg
    when_absent: placeholder
    placeholder: "--"
"""
    bag = _lint(text, write_design, db, device_id="fr955")
    hits = [d for d in bag.items if d.code == "complication-gated"]
    assert not hits, bag.render()


# -- codegen -------------------------------------------------------------------


def test_icon_lookup_is_a_generated_method_not_an_inline_local(write_design, bag, db):
    """Monkey C locals cannot be given an explicit `as String?` type ("Invalid
    explicit typing of a local variable", a real build error found while
    writing this) -- the icon-name lookup has to be a separate method whose
    own declared return type the call site's local infers from."""
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve
    from wfb.ir import complication_slot_icon_method

    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    view = monkeyc.emit_view(resolved).text
    method = complication_slot_icon_method("top_reading")
    assert f"private function {method}(t as Complications.Type) as String?" in view
    assert "as String? = null" not in view
    assert "IconGlyphs.glyph(" in view
    # `bottom_reading` has no icon (`choices: any`) -- no lookup method for it.
    assert complication_slot_icon_method("bottom_reading") not in view


def test_hold_target_lookup_is_a_generated_public_method(write_design, bag, db):
    """`on_hold: auto` on a slot compiles to a public getter returning this
    slot's own current `Complications.Id` field -- public, unlike every draw
    method, because the delegate is a different class and Monkey C's
    `private` genuinely blocks a cross-class call (verified by building both
    ways)."""
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve
    from wfb.ir import complication_slot_hold_method

    text = DESIGN.replace(
        "    label: short",
        "    on_hold: auto\n    label: short",
    )
    face = _face(text, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    view = monkeyc.emit_view(resolved).text
    method = complication_slot_hold_method("top_reading")
    assert f"function {method}() as Complications.Id" in view
    assert f"private function {method}" not in view
    assert f"return {face.config_data['top'].field};" in view
    # `bottom_reading` declares no `on_hold:` -- no getter for it.
    assert complication_slot_hold_method("bottom_reading") not in view


def test_complication_slot_hold_method_symbol_is_reserved_against_collision(write_design):
    """`complication_slot_hold_method` must be checked the same way
    `complication_slot_icon_method` already is -- a later id that folds to
    the same Monkey C symbol should be caught here, not four `Redefinition
    of ...` errors deep pointing at a generated line number."""
    from wfb.ir import complication_slot_hold_method

    # `top_reading` and `topReading` fold to the same element_method_name
    # ("drawTopReading") regardless of this feature -- reuse that existing,
    # already-covered collision as the vehicle, and additionally confirm the
    # hold-method name itself is what a real `on_hold: auto` slot would use,
    # so this test would catch a second id colliding on *only* the hold
    # method if the two id spellings ever stopped folding together first.
    assert complication_slot_hold_method("top_reading") == complication_slot_hold_method("topReading")
    text = HEAD + DATA_BLOCK + """elements:
  - id: top_reading
    type: complication_slot
    slot: config.data.top
    at: {anchor: center, dy: -20%}
    color: palette.fg
    on_hold: auto
  - id: topReading
    type: complication_slot
    slot: config.data.bottom
    at: {anchor: center, dy: 20%}
    color: palette.fg
    on_hold: auto
"""
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "duplicate-id"]
    assert hits, errors
    assert "holdTargetForTopReading" in hits[0].message


def test_only_a_mapped_choice_appears_in_the_icon_switch(write_design, bag, db):
    """Not every complication type has a catalogue icon (docs/format.md) --
    `calories` maps to `flame`; an unmapped type simply is not one of the
    switch's cases."""
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    view = monkeyc.emit_view(resolved).text
    assert "COMPLICATION_TYPE_STEPS: return \"steps\"" in view
    assert "COMPLICATION_TYPE_HEART_RATE: return \"heart\"" in view
    assert "COMPLICATION_TYPE_CALORIES: return \"flame\"" in view


def test_apply_config_matches_settings_by_unique_identifier(write_design, bag, db):
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    view = monkeyc.emit_view(resolved).text
    assert "settings.complicationSettings" in view
    assert "ref.uniqueIdentifier" in view
    assert "ref.complicationId" in view
    assert "if (unique == 1)" in view and "_configDataTop = picked;" in view
    assert "if (unique == 2)" in view and "_configDataBottom = picked;" in view


def test_manifest_gets_complications_feature_from_data_alone(write_design, bag, db):
    """A `config: data:` slot is not a catalogue reader `face.requirements()`
    would see -- `_features()`/`permissions()` must add it separately."""
    from wfb.emit import manifest

    face = _face(DESIGN, write_design, bag)
    assert not any(r for r in face.requirements().readers)
    devices = [db.get(d) for d in face.targets]
    text = manifest.render(face, devices, features={"complications"})
    assert 'minApiLevel="4.2.0"' in text
    assert '<iq:uses-permission id="ComplicationSubscriber"/>' in text
    assert "ComplicationSubscriber" in manifest.permissions(face)


def test_no_config_data_means_no_complications_permission(write_design, bag, db):
    """The absence half of the same check: a design with no complication
    binding of any kind gets neither the permission nor the API floor."""
    from wfb.emit import manifest

    text = HEAD + """elements:
  - id: a
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""
    face = _face(text, write_design, bag)
    devices = [db.get(d) for d in face.targets]
    assert manifest.permissions(face) == []
    rendered = manifest.render(face, devices, features=set())
    assert 'minApiLevel="4.2.0"' not in rendered
    assert "ComplicationSubscriber" not in rendered


def test_config_resource_emits_the_data_block(write_design, bag, db):
    from wfb.emit.resources import config_resource

    face = _face(DESIGN, write_design, bag)
    text = config_resource(face)
    assert '<complication id="1">' in text
    assert '<type default="true">Complications.COMPLICATION_TYPE_STEPS</type>' in text
    assert "Complications.COMPLICATION_TYPE_HEART_RATE" in text
    assert "Complications.COMPLICATION_TYPE_CALORIES" in text
    assert '<complication id="2" allowAny="true"/>' in text


def test_unit_suffix_barrel_matches_the_python_table(write_design, bag):
    """`WfbComplications.mc`'s `unitSuffix` is the on-device twin of
    `wfb.complications.UNIT_SUFFIX` -- parsed and checked directly, the same
    discipline `tests/test_weather_barrel.py` already applies to
    `WfbWeather.mc`."""
    from pathlib import Path
    import re

    source = (Path(__file__).resolve().parent.parent / "runtime-lib"
              / "WfbComplications.mc").read_text(encoding="utf-8")
    cases = dict(re.findall(
        r'case Complications\.(UNIT_\w+):\s*return\s*"([^"]*)";', source))
    assert cases, "no unitSuffix cases found -- did the barrel change shape?"
    assert cases == complications.UNIT_SUFFIX


def test_preview_renders_without_crashing(write_design, bag, db):
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve
    from wfb.preview import render

    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    image = render(resolved)
    assert image.size == (device.width * 2, device.height * 2)


# -- golden files must not move -----------------------------------------------


def test_a_design_with_no_slots_is_untouched_by_this_feature(write_design, bag, db):
    """The negative control every additive feature in this repo needs: a
    design with no `config: data:` and no `complication_slot` element must
    come out byte-identical to before -- `has_config` stays false, no
    Complications import, no barrel, and none of this session's editor-only
    machinery (onTap/getComplicationDrawable/onStart/_pulsing/SlotDrawable)
    leaks in either."""
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    text = HEAD + """elements:
  - id: a
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
    on_hold: steps
"""
    face = _face(text, write_design, bag)
    assert not face.config_data
    assert not face.has_config
    assert monkeyc.complication_slots(face) == []
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    view = monkeyc.emit_view(resolved).text
    assert "Complications" not in view
    assert "complicationSettings" not in view
    assert "_pulsing" not in view
    assert "drawSlot" not in view
    assert "drawableFor" not in view

    app = monkeyc.emit_app(face).text
    assert "onStart" not in app
    assert "_editMode" not in app
    assert f"new {face.entry}View()" in app

    delegate = monkeyc.emit_delegate(resolved).text
    assert "function onTap(" not in delegate
    assert "getComplicationDrawable" not in delegate
    # this design's own on_hold: steps still works -- a fixed complications.TYPES
    # target, unrelated to the complication_slot machinery this test guards
    assert "Complications.exitTo(new Complications.Id(Complications." in delegate


# -- the real toolchain --------------------------------------------------------


@pytest.mark.slow
def test_a_data_axis_design_compiles_warning_free_on_every_target(
        write_design, tmp_path, db, toolchain):  # noqa: F811
    """The bar CLAUDE.md and this task both set: real `monkeyc`, all three
    targets, warning-free (`config-unsupported` on fr955 accepted explicitly
    per element, the same as `examples/slots/face.yaml` does)."""
    from wfb.build import build as run_build

    text = DESIGN.replace(
        "    label: short",
        "    lint:\n      allow: [config-unsupported]\n      reason: test\n"
        "    label: short",
    ).replace(
        "  - id: bottom_reading\n    type: complication_slot\n"
        "    slot: config.data.bottom\n    at: {anchor: center, dy: 20%}\n"
        "    color: palette.fg\n",
        "  - id: bottom_reading\n    type: complication_slot\n"
        "    slot: config.data.bottom\n    at: {anchor: center, dy: 20%}\n"
        "    color: palette.fg\n"
        "    lint:\n      allow: [config-unsupported]\n      reason: test\n",
    )
    design = write_design(text)
    bag = Bag()
    result = run_build(design, output=tmp_path / "out", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    monkeyc_warnings = [d for d in bag.items
                        if d.severity.value == "warning" and d.code == "monkeyc"]
    assert not monkeyc_warnings, "\n".join(d.message for d in monkeyc_warnings)
    assert set(result.products) == {"fenix8solar47mm", "fenix8solar51mm", "fr955"}

    manifest_text = (result.output_dir / "manifest.xml").read_text(encoding="utf-8")
    assert 'minApiLevel="4.2.0"' in manifest_text
    assert '<iq:uses-permission id="ComplicationSubscriber"/>' in manifest_text

    fenix_config = (result.output_dir / "resources-fenix8solar47mm" / "configs"
                    / "watchface.xml")
    assert fenix_config.exists()
    assert "<data>" in fenix_config.read_text(encoding="utf-8")
    fr955_config = (result.output_dir / "resources-fr955" / "configs" / "watchface.xml")
    assert not fr955_config.exists()


@pytest.mark.slow
def test_only_config_data_no_colour_axes_compiles_warning_free_with_manifest(
        write_design, tmp_path, db, toolchain):  # noqa: F811
    """The task brief's own headline risk, put through the real compiler and
    the generated manifest -- not just inspected as generated text (CLAUDE.md
    records a feature that shipped with a real, undetected `monkeyc` warning
    for exactly this shape of gap: every test inspected generated text and
    none ran the compiler)."""
    from wfb.build import build as run_build

    text = HEAD + """config:
  data:
    reading:
      default: complication.steps
      choices: [complication.steps, complication.heart_rate]
elements:
  - id: reading
    type: complication_slot
    slot: config.data.reading
    at: {anchor: center}
    icon_size: 10%r
    color: palette.fg
    when_absent: placeholder
    placeholder: "--"
    lint:
      allow: [config-unsupported]
      reason: test
"""
    assert "config:\n  accent_color" not in text
    assert "colors:" not in text
    design = write_design(text)
    bag = Bag()
    result = run_build(design, output=tmp_path / "out", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    monkeyc_warnings = [d for d in bag.items
                        if d.severity.value == "warning" and d.code == "monkeyc"]
    assert not monkeyc_warnings, "\n".join(d.message for d in monkeyc_warnings)

    manifest_text = (result.output_dir / "manifest.xml").read_text(encoding="utf-8")
    assert 'minApiLevel="4.2.0"' in manifest_text
    assert '<iq:uses-permission id="ComplicationSubscriber"/>' in manifest_text


# -- on_hold: auto + the editor-only machinery (piece 1 + piece 2) -----------


@pytest.mark.slow
def test_slot_with_on_hold_auto_compiles_warning_free_on_every_target(
        write_design, tmp_path, db, toolchain):  # noqa: F811
    """A `complication_slot` with `on_hold: auto` -- Complications.exitTo on
    whatever the wearer currently has the slot pointed at -- plus the
    editor-only machinery (`AppBase.onStart`, `WatchFaceDelegate.onTap`/
    `getComplicationDrawable`, the generated SlotDrawable) every
    complication_slot design now carries, real `monkeyc`, all three targets,
    warning-free."""
    from wfb.build import build as run_build

    text = DESIGN.replace(
        "    label: short",
        "    lint:\n      allow: [config-unsupported]\n      reason: test\n"
        "    on_hold: auto\n"
        "    label: short",
    ).replace(
        "  - id: bottom_reading\n    type: complication_slot\n"
        "    slot: config.data.bottom\n    at: {anchor: center, dy: 20%}\n"
        "    color: palette.fg\n",
        "  - id: bottom_reading\n    type: complication_slot\n"
        "    slot: config.data.bottom\n    at: {anchor: center, dy: 20%}\n"
        "    color: palette.fg\n"
        "    lint:\n      allow: [config-unsupported]\n      reason: test\n",
    )
    design = write_design(text)
    bag = Bag()
    result = run_build(design, output=tmp_path / "out", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    monkeyc_warnings = [d for d in bag.items
                        if d.severity.value == "warning" and d.code == "monkeyc"]
    assert not monkeyc_warnings, "\n".join(d.message for d in monkeyc_warnings)
    assert set(result.products) == {"fenix8solar47mm", "fenix8solar51mm", "fr955"}

    view_text = (result.output_dir / "source" / "TestView.mc").read_text(encoding="utf-8")
    assert "holdTargetForTopReading" in view_text
    assert "_pulsing" in view_text
    assert "function drawSlot(dc as Dc, unique as Number) as Void" in view_text

    delegate_text = (result.output_dir / "source" / "TestDelegate.mc").read_text(encoding="utf-8")
    assert "Complications.exitTo(_view.holdTargetForTopReading())" in delegate_text
    assert "function onTap(clickEvent as ClickEvent) as Boolean" in delegate_text
    assert "function getComplicationDrawable" in delegate_text

    app_text = (result.output_dir / "source" / "TestApp.mc").read_text(encoding="utf-8")
    assert "function onStart(state as Dictionary?) as Void" in app_text
    assert "launchedFromWatchFaceSettingsEditor" in app_text

    drawable_path = result.output_dir / "source" / "TestSlotDrawable.mc"
    assert drawable_path.exists()


@pytest.mark.slow
def test_slot_without_on_hold_still_gets_editor_machinery_warning_free(
        write_design, tmp_path, db, toolchain):  # noqa: F811
    """The other half of the same coin: a `complication_slot` design with no
    `on_hold:` anywhere still gets the editor's onTap/getComplicationDrawable
    machinery (the editor can animate any slot, not only ones that also
    launch something on a live face) -- and still builds warning-free."""
    from wfb.build import build as run_build

    design = write_design(DESIGN)
    bag = Bag()
    result = run_build(design, output=tmp_path / "out", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    monkeyc_warnings = [d for d in bag.items
                        if d.severity.value == "warning" and d.code == "monkeyc"]
    assert not monkeyc_warnings, "\n".join(d.message for d in monkeyc_warnings)

    delegate_text = (result.output_dir / "source" / "TestDelegate.mc").read_text(encoding="utf-8")
    assert "function onTap(clickEvent as ClickEvent) as Boolean" in delegate_text
    assert "function getComplicationDrawable" in delegate_text
    assert "holdTargetForTopReading" not in delegate_text
    assert "Complications.exitTo" not in delegate_text


@pytest.mark.slow
def test_a_design_with_no_slots_at_all_still_builds_warning_free(
        write_design, tmp_path, db, toolchain):  # noqa: F811
    """The real-toolchain twin of
    `test_a_design_with_no_slots_is_untouched_by_this_feature`: a design with
    no `complication_slot` anywhere must still build, warning-free, on every
    target -- proof that none of this session's editor-only machinery leaks
    into, or breaks, an unrelated face."""
    from wfb.build import build as run_build

    text = HEAD + """elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    at: {anchor: center}
    color: palette.fg
    on_hold: current_weather
"""
    design = write_design(text)
    bag = Bag()
    result = run_build(design, output=tmp_path / "out", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    monkeyc_warnings = [d for d in bag.items
                        if d.severity.value == "warning" and d.code == "monkeyc"]
    assert not monkeyc_warnings, "\n".join(d.message for d in monkeyc_warnings)
    assert set(result.products) == {"fenix8solar47mm", "fenix8solar51mm", "fr955"}

    delegate_text = (result.output_dir / "source" / "TestDelegate.mc").read_text(encoding="utf-8")
    assert "function onTap(" not in delegate_text
    assert "getComplicationDrawable" not in delegate_text
    assert not (result.output_dir / "source" / "TestSlotDrawable.mc").exists()

    app_text = (result.output_dir / "source" / "TestApp.mc").read_text(encoding="utf-8")
    assert "onStart" not in app_text
    assert "_editMode" not in app_text
