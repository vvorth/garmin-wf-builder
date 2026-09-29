"""`config: data:` and `type: data` -- the native editor's Data
axis (docs/research/09-data-library-and-config-axes.md §4).

Every check below is driven red against the exact violating input before it
is trusted, the same discipline `tests/test_color_scheme.py`'s own module
docstring states.
"""

from __future__ import annotations

import pytest

from wfb import complications, icons
from wfb.diagnostics import Bag
from wfb.ir import ComplicationSlot, config_data_ids
from tests.helpers import (
    lint_text as _lint, load_errors as _errors, load_face as _face, resolve_text as _resolved,
)

HEAD = """format: 2
face:
  id: 6b2f9a3e-5c1d-4e8a-9f7b-3a1d6c8e2f40
  name: Test
build:
  targets: [fenix8solar47mm, fenix8solar51mm, fr955]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
"""

#: Two slots -- one an explicit list with an icon, one `any` with none --
#: exercising both shapes the feature has.
DATA_BLOCK = """config:
  slots:
    top:
      default: steps
      choices:
        - steps
        - heart_rate
        - calories
    bottom:
      default: body_battery
      choices: any
"""

BODY = """elements:
  top_reading:
    type: data
    slot: top
    at: {anchor: center, dy: -20%}
    icon: {size: 8%r}
    color: color.fg
    label: short
    unit: true
    absent: "--"
  bottom_reading:
    type: data
    slot: bottom
    at: {anchor: center, dy: 20%}
    color: color.fg
    short: true
    absent: "--"
"""

DESIGN = HEAD + DATA_BLOCK + BODY


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
    assert face.config_style is None
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
  slots:
    top:
      default: step
      choices: [step]
""" + BODY
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "config"]
    assert hits, errors
    assert "unknown complication type 'step'" in hits[0].message
    assert any("did you mean" in n and "steps" in n for n in hits[0].notes), hits[0].notes


def test_unknown_complication_type_in_choices_is_an_error(write_design):
    text = HEAD + """config:
  slots:
    top:
      default: steps
      choices: [steps, bogus]
""" + BODY
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "config"]
    assert any("'bogus'" in d.message for d in hits), errors


def test_default_not_among_explicit_choices_is_an_error(write_design):
    text = HEAD + """config:
  slots:
    top:
      default: heart_rate
      choices: [steps, calories]
""" + BODY
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "config"]
    assert hits, errors
    assert "is not one of 'choices:'" in hits[0].message
    assert "'heart_rate'" in hits[0].message


def test_a_rejected_slot_does_not_cascade(write_design):
    """One error, at the real mistake -- two elements reference the same
    rejected slot, so binding it into scope anyway is what keeps this to one
    error rather than one more per referencing element (the same cascade fix
    `fonts:`/`config:`/`palette:`/`color_scheme:` all needed)."""
    text = HEAD + """config:
  slots:
    top:
      default: bogus_type
      choices: [bogus_type]
elements:
  a:
    type: data
    slot: top
    at: {anchor: center, dy: -20%}
    color: color.fg
    absent: "--"
  b:
    type: data
    slot: top
    at: {anchor: center, dy: 20%}
    color: color.fg
    absent: "--"
"""
    errors = _errors(text, write_design)
    assert len(errors) == 1, errors
    assert errors[0].code == "config"
    assert "unknown complication type" in errors[0].message


# -- per-choice icon overrides (plan 03 §6.1/§6.2) ----------------------------


PER_CHOICE_DATA_BLOCK = """config:
  slots:
    top:
      default: steps
      choices:
        - steps
        - {type: heart_rate, icon: flame}
        - {type: calories, icon: none}
        - {type: body_battery, icon: "U+F0004"}
    bottom:
      default: body_battery
      choices: any
"""


def test_per_choice_icon_override_wins_over_the_catalogue_default(write_design, bag):
    text = HEAD + PER_CHOICE_DATA_BLOCK + BODY
    face = _face(text, write_design, bag)
    slot = face.config_data["top"]
    resolved = slot.icons
    assert resolved["steps"].key == "steps"  # catalogue default, unaffected
    assert resolved["heart_rate"].key == "flame"  # overridden
    assert resolved["heart_rate"].codepoint == icons.CATALOG["flame"].codepoint


def test_per_choice_icon_none_removes_the_catalogue_default(write_design, bag):
    text = HEAD + PER_CHOICE_DATA_BLOCK + BODY
    face = _face(text, write_design, bag)
    slot = face.config_data["top"]
    assert "calories" not in slot.icons  # icon: none -- explicitly no icon
    assert "calories" in icons.COMPLICATION_ICON  # the catalogue does map it


def test_per_choice_glyph_override_uses_the_canonical_codepoint_spelling(write_design, bag):
    text = HEAD + PER_CHOICE_DATA_BLOCK + BODY
    face = _face(text, write_design, bag)
    slot = face.config_data["top"]
    resolved = slot.icons["body_battery"]
    assert resolved.key == "U+F0004"
    assert resolved.codepoint == "\U000f0004"


def test_per_choice_unknown_icon_name_is_an_error_with_suggestions(write_design):
    text = HEAD + """config:
  slots:
    top:
      default: steps
      choices:
        - steps
        - {type: heart_rate, icon: hart}
""" + BODY
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "icon"]
    assert hits, errors
    assert "unknown icon" in hits[0].message
    assert any("heart" in n for n in hits[0].notes), hits[0].notes


def test_per_choice_glyph_not_in_the_font_is_an_error(write_design):
    text = HEAD + """config:
  slots:
    top:
      default: steps
      choices:
        - steps
        - {type: heart_rate, icon: "U+FFFF"}
""" + BODY
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "icon"]
    assert hits, errors
    assert "no glyph at" in hits[0].message


def test_a_type_listed_twice_across_shapes_is_an_error(write_design):
    """The schema's own 'uniqueItems' cannot see through a bare reference and
    a mapping-form entry naming the same type -- this is an IR check."""
    text = HEAD + """config:
  slots:
    top:
      default: steps
      choices:
        - steps
        - {type: steps, icon: flame}
""" + BODY
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "config"]
    assert hits, errors
    assert "listed more than once" in hits[0].message
    assert "steps" in hits[0].message


def test_a_rejected_choice_icon_does_not_cascade(write_design):
    """The same 'one error, not N' discipline as
    `test_a_rejected_slot_does_not_cascade`, for a bad per-choice icon."""
    text = HEAD + """config:
  slots:
    top:
      default: steps
      choices:
        - steps
        - {type: heart_rate, icon: not-a-real-icon}
elements:
  a:
    type: data
    slot: top
    at: {anchor: center, dy: -20%}
    color: color.fg
  b:
    type: data
    slot: top
    at: {anchor: center, dy: 20%}
    color: color.fg
"""
    errors = _errors(text, write_design)
    assert len(errors) == 1, errors
    assert errors[0].code == "icon"


# -- complication_slot element errors -----------------------------------------


def test_unknown_slot_reference_is_an_error(write_design):
    text = HEAD + DATA_BLOCK + """elements:
  a:
    type: data
    slot: bogus
    at: {anchor: center}
    color: color.fg
"""
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "complication-slot"]
    assert hits, errors
    assert "unknown slot 'bogus'" in hits[0].message
    assert any("bottom, top" in n for n in hits[0].notes), \
        hits[0].notes


def test_icon_size_is_now_allowed_with_choices_any(write_design, bag):
    """Superseded 2026-09-13 (plan 03 §6.6): 'icon_size:' + 'choices: any'
    used to be an error (see the account this test replaced, in git
    history) because the set of icons an unbounded picker could need was
    unbounded. Lifted once every native type had a catalogue icon -- 'any'
    now resolves against the whole of 'wfb.icons.COMPLICATION_ICON'."""
    text = HEAD + DATA_BLOCK + """elements:
  a:
    type: data
    slot: bottom
    at: {anchor: center}
    icon: {size: 8%r}
    color: color.fg
"""
    face = _face(text, write_design, bag)
    element = next(e for e in face.walk() if e.id == "a")
    assert element.icon_size is not None
    slot = face.config_data["bottom"]
    assert slot.allow_any
    assert set(slot.icons) == set(icons.COMPLICATION_ICON)


def test_format_is_rejected_with_a_reason(write_design):
    text = HEAD + DATA_BLOCK + """elements:
  a:
    type: data
    slot: top
    at: {anchor: center}
    color: color.fg
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
  a:
    type: data
    slot: top
    at: {anchor: center}
    color: color.fg
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
  a:
    type: data
    slot: top
    at: {anchor: center}
    color: color.fg
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
  a:
    type: data
    slot: top
    at: {anchor: center}
    color: color.fg
"""
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "static"]
    assert hits, errors
    assert "cannot be static" in hits[0].message


def test_missing_color_is_an_error(write_design):
    text = HEAD + DATA_BLOCK + """elements:
  a:
    type: data
    slot: top
    at: {anchor: center}
"""
    errors = _errors(text, write_design)
    assert any("needs a color" in d.message for d in errors), errors


def test_nullable_color_is_an_error(write_design):
    """There is no `when_absent:` for the element's own appearance -- only
    for the pulled reading."""
    text = HEAD + DATA_BLOCK + """elements:
  a:
    type: data
    slot: top
    at: {anchor: center}
    color: "heart_rate.current > 100 ? color.fg : color.fg"
"""
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "complication-slot"]
    assert hits and "can be absent" in hits[0].message, errors
    assert any("guard it in the expression" in n for n in hits[0].notes), hits[0].notes


# -- icon_position:/icon_gap:/icon_color: (plan 03 §6.1/§6.3) -----------------


def test_icon_position_and_gap_and_color_resolve(write_design, bag):
    text = HEAD + DATA_BLOCK + """elements:
  a:
    type: data
    slot: top
    at: {anchor: center}
    icon: {size: 8%r, position: right, gap: 2px, color: color.bg}
    color: color.fg
"""
    face = _face(text, write_design, bag)
    element = next(e for e in face.walk() if e.id == "a")
    assert element.icon_position == "right"
    assert element.icon_gap is not None and element.icon_gap.value == 2
    assert element.icon_color is not None and element.icon_color.shown == "color.bg"


@pytest.mark.parametrize("key,value", [
    ("position", "top"),
    ("gap", "2px"),
    ("color", "color.bg"),
])
def test_icon_position_gap_color_need_icon_size(write_design, key, value):
    text = HEAD + DATA_BLOCK + f"""elements:
  a:
    type: data
    slot: top
    at: {{anchor: center}}
    color: color.fg
    icon: {{{key}: {value}}}
"""
    errors = _errors(text, write_design)
    assert [d.message for d in errors] == ["elements.a.icon: missing required key 'size'"]


def test_icon_gap_percent_unit_is_rejected(write_design):
    text = HEAD + DATA_BLOCK + """elements:
  a:
    type: data
    slot: top
    at: {anchor: center}
    icon: {size: 8%r, gap: 5%}
    color: color.fg
"""
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "complication-slot"]
    assert hits, errors
    assert "icon: {gap:} must be px or %r" in hits[0].message


def test_icon_gap_negative_is_rejected(write_design):
    text = HEAD + DATA_BLOCK + """elements:
  a:
    type: data
    slot: top
    at: {anchor: center}
    icon: {size: 8%r, gap: -2px}
    color: color.fg
"""
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "complication-slot"]
    assert hits, errors
    assert "must not be negative" in hits[0].message


def test_icon_color_nullable_is_an_error(write_design):
    text = HEAD + DATA_BLOCK + """elements:
  a:
    type: data
    slot: top
    at: {anchor: center}
    icon: {size: 8%r, color: "heart_rate.current > 100 ? color.fg : color.fg"}
    color: color.fg
"""
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "complication-slot"]
    assert hits and "'icon: {color:}'" in hits[0].message \
        and "can be absent" in hits[0].message, errors


def test_icon_color_defaults_to_color_when_unauthored(write_design, bag):
    text = HEAD + DATA_BLOCK + """elements:
  a:
    type: data
    slot: top
    at: {anchor: center}
    icon: {size: 8%r}
    color: color.fg
"""
    face = _face(text, write_design, bag)
    element = next(e for e in face.walk() if e.id == "a")
    assert element.icon_color is None


def test_a_dithered_icon_color_is_caught_by_the_palette_lint(write_design, db):
    """`icon_color:` must be one of the fields `check_palette`'s `_users_of`
    walks -- proven by actually dithering it, not just reading the code."""
    text = HEAD.replace('fg: "#FFFFFF"', 'fg: "#123456"') + DATA_BLOCK + """elements:
  a:
    type: data
    slot: top
    at: {anchor: center}
    icon: {size: 8%r, color: color.fg}
    color: color.bg
"""
    bag = _lint(text, write_design, db)
    hits = [d for d in bag.items if d.code == "palette-dither"]
    assert hits, bag.render()


def test_a_dithered_icon_color_can_be_suppressed_on_its_own_element(write_design, db):
    text = HEAD.replace('fg: "#FFFFFF"', 'fg: "#123456"') + DATA_BLOCK + """elements:
  a:
    type: data
    slot: top
    at: {anchor: center}
    icon: {size: 8%r, color: color.fg}
    color: color.bg
    lint:
      allow: [palette-dither]
      reason: "probing"
"""
    bag = _lint(text, write_design, db)
    hits = [d for d in bag.items if d.code == "palette-dither"]
    assert not hits, bag.render()


# -- lint: config-unsupported, extended to name slots -------------------------


def test_config_unsupported_names_the_data_axis_on_fenix5(write_design, db):
    if "fenix5" not in db.ids():
        pytest.skip("fenix5 is not installed")
    fr955 = _lint(DESIGN, write_design, db, device_id="fr955")
    assert not [d for d in fr955.items if d.code == "config-unsupported"], fr955.render()
    bag = _lint(DESIGN, write_design, db, device_id="fenix5")
    hits = [d for d in bag.items if d.code == "config-unsupported"]
    assert hits, bag.render()
    assert "slot 'top'" in hits[0].message and "slot 'bottom'" in hits[0].message


def test_config_unsupported_is_silenced_by_lint_allow_on_any_relevant_element(write_design, db):
    """`check_config_support` emits one combined warning per device, naming
    every axis/slot the design has -- so `lint: {allow: [config-unsupported]}`
    on any *one* relevant element silences the whole message for that
    device, the same pre-existing shape `test_config.py`'s own colour-axis
    version of this check already has. Not a per-slot suppression."""
    text = DESIGN.replace(
        """    color: color.fg
    label: short""",
        """    color: color.fg
    lint:
      allow: [config-unsupported]
      reason: test
    label: short""",
    )
    bag = _lint(text, write_design, db, device_id="fr955")
    hits = [d for d in bag.items if d.code == "config-unsupported"]
    assert not hits, bag.render()


# -- lint: api-gated, extended to slot default/choices ------------------------


def test_complication_gated_fires_for_a_slots_default_on_fr955(write_design, db):
    """`sleep_score` needs ConnectIQ 6.0.2; fr955 tops out at 5.2.0 -- the
    same fact `docs/guide/data.md`'s own `complication.*` and `docs/guide/modes-and-interaction.md`'s `on_hold:` examples
    already rely on, reused here for a slot's own `default:`."""
    assert complications.TYPES["sleep_score"].since == "6.0.2"
    text = HEAD + """config:
  slots:
    top:
      default: sleep_score
      choices: [sleep_score, steps]
elements:
  top_reading:
    type: data
    slot: top
    at: {anchor: center}
    color: color.fg
    absent: "--"
"""
    bag = _lint(text, write_design, db, device_id="fr955")
    hits = [d for d in bag.items if d.code == "api-gated"]
    assert hits, bag.render()
    assert any("sleep_score" in d.message and "slot 'top'" in d.message for d in hits), \
        [d.message for d in hits]


def test_complication_gated_does_not_check_choices_any(write_design, db):
    """`choices: any` has no list to check -- only `default:` is (the same
    `choices: any` carve-out `check_config_palette` already makes)."""
    text = HEAD + """config:
  slots:
    bottom:
      default: body_battery
      choices: any
""" + """elements:
  bottom_reading:
    type: data
    slot: bottom
    at: {anchor: center}
    color: color.fg
    absent: "--"
"""
    bag = _lint(text, write_design, db, device_id="fr955")
    hits = [d for d in bag.items if d.code == "api-gated"]
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
    resolved = resolve(face, device, bake_fonts(face, device))
    view = monkeyc.emit_view(resolved).text
    method = complication_slot_icon_method("top_reading")
    assert f"private function {method}(t as Complications.Type,\n" in view
    assert "pulled as Complications.Complication?) as String? {" in view
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
    resolved = resolve(face, device, bake_fonts(face, device))
    view = monkeyc.emit_view(resolved).text
    method = complication_slot_hold_method("top_reading")
    assert f"function {method}() as Complications.Id" in view
    assert f"private function {method}" not in view
    assert f"return {face.config_data['top'].field};" in view
    # `bottom_reading` declares no `on_hold:` -- no getter for it.
    assert complication_slot_hold_method("bottom_reading") not in view


def _method_body(source: str, signature: str) -> list[str]:
    """The stripped lines of one generated method's body, from its
    signature line to the closing brace at the signature's own indent."""
    lines = source.splitlines()
    start = next(i for i, line in enumerate(lines) if signature in line)
    indent = len(lines[start]) - len(lines[start].lstrip())
    body = []
    for line in lines[start + 1:]:
        if line.strip() == "}" and len(line) - len(line.lstrip()) == indent:
            return body
        body.append(line.strip())
    raise AssertionError(f"no closing brace for {signature!r}")


def test_the_editor_drawable_draws_the_slot_the_face_skips(write_design, bag, db):
    """The pulsing slot is skipped by its own draw method, and the editor's
    SlotDrawable reaches that same method through `drawSlot` -- so `drawSlot`
    must lift the skip for its own call, or the slot is drawn by nobody (on
    a fenix8solar47mm the selected slot vanished and never previewed a
    choice).  Checked as an order: `_pulsing` cleared before the dispatch,
    restored after it, while each per-slot method keeps its own skip."""
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    view = monkeyc.emit_view(resolved).text
    ids = config_data_ids(face)

    body = _method_body(view, "function drawSlot(dc as Dc, unique as Number) as Void")
    cleared = body.index("_pulsing = 0;")
    restored = body.index("_pulsing = pulsing;")
    for method in ("drawTopReading", "drawBottomReading"):
        dispatch = next(i for i, line in enumerate(body) if f"{method}(dc);" in line)
        assert cleared < dispatch < restored, body

    for method, slot in (("drawTopReading", "top"), ("drawBottomReading", "bottom")):
        own = [line for line in _method_body(view, f"private function {method}(dc as Dc) as Void")
               if line and not line.startswith("//")]
        assert own[0] == f"if (_pulsing == {ids[slot]}) {{", own[:3]


@pytest.mark.parametrize("anchor_x, align, expected", [
    # centred at the screen centre: the whole row, like the SDK sample's drawable
    (130, "center", (0, 260)),
    # centred off-centre: as far as the nearer edge, so the pulse stays on the anchor
    (60, "center", (0, 120)),
    (200, "center", (140, 260)),
    # the pair grows away from the anchor on one side only
    (60, "left", (60, 260)),
    (200, "right", (0, 200)),
])
def test_the_highlight_box_spans_every_column_the_pair_can_reach(anchor_x, align, expected):
    """The editor clips the slot's drawable to its box, and the estimated box
    leaves out the label and unit ("STEPS 5068" drew as "TEPS 506" on a
    fenix8solar47mm), so the drawable's box spans the screen columns the pair
    can reach from its anchor, keeping the estimated rows."""
    from wfb.kinds.complication_slot import highlight_box
    from wfb.units import IntBox

    # the estimate sits where `align:` puts the pair: on the anchor's own side
    left = {"left": anchor_x, "center": anchor_x - 20, "right": anchor_x - 40}[align]
    box = IntBox(left, 41, 40, 32)
    got = highlight_box(box, anchor_x, align, 260)
    assert (got.x, got.right) == expected
    assert (got.y, got.height) == (41, 32)


def test_the_highlight_box_keeps_an_estimate_that_overhangs_the_edge():
    """An anchor at the very edge leaves a centred span of nothing; the
    estimated box is kept inside it rather than handing the editor a
    zero-width drawable."""
    from wfb.kinds.complication_slot import highlight_box
    from wfb.units import IntBox

    box = IntBox(-10, 41, 40, 32)
    assert highlight_box(box, 0, "center", 260) == box


def test_the_editor_drawable_gets_the_highlight_box_and_taps_the_estimate(
        write_design, bag, db):
    """`drawableFor` builds each slot's drawable on its `_HIGHLIGHT` box --
    the full row for these centred slots, wider than the estimate -- while
    `onTap` keeps hit-testing the estimated `_BOX`, so two slots side by side
    stay separate tap targets."""
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    view = monkeyc.emit_view(resolved).text
    body = "\n".join(_method_body(
        view, "function drawableFor(unique as Number) as WatchUi.ComplicationDrawableRef or Null"))
    for prefix in ("TOP_READING", "BOTTOM_READING"):
        assert f"Layout.{prefix}_HIGHLIGHT_X, Layout.{prefix}_HIGHLIGHT_Y," in body
        assert f"Layout.{prefix}_HIGHLIGHT_WIDTH, Layout.{prefix}_HIGHLIGHT_HEIGHT)" in body
    assert "_BOX_" not in body

    delegate = monkeyc.emit_delegate(resolved).text
    tap = "\n".join(_method_body(delegate, "function onTap(clickEvent as ClickEvent) as Boolean"))
    assert "Layout.TOP_READING_BOX_X" in tap
    assert "HIGHLIGHT" not in tap

    slots = [p for p in resolved.items if p.id in ("top_reading", "bottom_reading")]
    assert len(slots) == 2
    for placed in slots:
        assert placed.highlight is not None
        assert (placed.highlight.x, placed.highlight.width) == (0, device.width)
        assert placed.highlight.width > placed.box.width


def test_the_editor_drawable_loads_fonts_and_config_before_onlayout(write_design, bag, db):
    """Entering the editor's Data list starts the face afresh, and the editor
    draws the preselected slot's drawable before `onLayout` has run -- on a
    fenix8solar47mm the slot pulsed with no icon, its font field still null.
    `drawableFor` runs `loadResources` (the icon fonts and the first config
    read, which `onLayout` calls too) when it has not run yet."""
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    view = monkeyc.emit_view(resolved).text

    def code(signature: str) -> list[str]:
        return [line for line in _method_body(view, signature)
                if line and not line.startswith("//")]

    drawable = code(
        "function drawableFor(unique as Number) as WatchUi.ComplicationDrawableRef or Null")
    assert drawable[:3] == ["if (!_resourcesLoaded) {", "loadResources();", "}"], drawable[:4]

    load = code("private function loadResources() as Void")
    assert "_resourcesLoaded = true;" in load
    # `top_reading` draws an icon; `bottom_reading` (`choices: any`) does not
    assert any("loadResource(Rez.Fonts.FontIcon" in line and "SlotTop" in line
               for line in load), load
    assert "applyConfig(settings);" in load

    layout = code("function onLayout(dc as Dc) as Void")
    assert layout[0] == "loadResources();"
    assert not any("loadResource(" in line or "applyConfig" in line for line in layout)


def test_leaving_a_slot_in_the_editor_stops_skipping_it(write_design, bag, db):
    """Nothing but the editor's own edits can tell the view no slot is being
    animated any more: a `:type` other than COMPLICATION (null is "the end of
    previous editing") clears `_pulsing`, or the last slot animated stays
    hidden until another one is picked -- seen on a fenix8solar47mm."""
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    delegate = monkeyc.emit_delegate(resolved).text
    body = _method_body(delegate, "function onWatchFaceConfigEdited(options as {")
    guard = body.index(
        "if (options[:type] != WatchUi.WATCH_FACE_CONFIG_TYPE_COMPLICATION) {")
    assert body[guard + 1] == "_view.setPulsing(0);"


def test_the_slot_skip_covers_one_redraw(write_design, bag, db):
    """Moving past the last slot to "Done" fires no editor callback, only
    one more onUpdate (traced on a fenix8solar47mm,
    `examples/probes/slot-editor/`), so onUpdate itself must end by clearing
    `_pulsing`, after every slot has been drawn -- or the last slot stays
    blank at "Done"."""
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    view = monkeyc.emit_view(resolved).text
    body = [line for line in _method_body(view, "function onUpdate(dc as Dc) as Void")
            if line and not line.startswith("//")]
    assert body[-1] == "_pulsing = 0;", body[-4:]
    for method in ("drawTopReading", "drawBottomReading"):
        assert any(f"{method}(dc" in line for line in body[:-1]), method


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
  top_reading:
    type: data
    slot: top
    at: {anchor: center, dy: -20%}
    color: color.fg
    on_hold: auto
  topReading:
    type: data
    slot: bottom
    at: {anchor: center, dy: 20%}
    color: color.fg
    on_hold: auto
"""
    errors = _errors(text, write_design)
    hits = [d for d in errors if d.code == "duplicate-id"]
    assert hits, errors
    assert "holdTargetForTopReading" in hits[0].message


def test_only_a_mapped_choice_appears_in_the_icon_switch(write_design, bag, db):
    """Not every complication type has a catalogue icon (docs/guide/configuration.md) --
    `calories` maps to `flame`; an unmapped type simply is not one of the
    switch's cases."""
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    view = monkeyc.emit_view(resolved).text
    assert "COMPLICATION_TYPE_STEPS: return \"steps\"" in view
    assert "COMPLICATION_TYPE_HEART_RATE: return \"heart\"" in view
    assert "COMPLICATION_TYPE_CALORIES: return \"flame\"" in view


def test_choices_any_icon_switch_covers_every_native_type(write_design, bag, db):
    """Since 2026-09-13, 'icon_size:' + 'choices: any' resolves against the
    whole of `wfb.icons.COMPLICATION_ICON` (plan 03 §6.6) -- the generated
    switch gets one case per native type this compiler knows an icon for."""
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    text = HEAD + DATA_BLOCK + """elements:
  bottom_reading:
    type: data
    slot: bottom
    at: {anchor: center}
    icon: {size: 8%r}
    color: color.fg
"""
    face = _face(text, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    view = monkeyc.emit_view(resolved).text
    for name, icon_name in icons.COMPLICATION_ICON.items():
        ctype = complications.TYPES[name]
        if complications.READING[name] == "condition":
            # A weather type's icon follows the pulled condition, falling
            # back to its own icon without one.
            assert (f"Complications.{ctype.constant}: return (value instanceof Lang.Number)"
                    f' ? WfbWeather.chooseIcon(value) : "{icon_name}";') in view
        else:
            assert f'Complications.{ctype.constant}: return "{icon_name}";' in view


# -- codegen: byte-identical output, and each `icon_position:` branch --------


def test_unauthored_left_position_generates_byte_identical_code(write_design, bag, db):
    """The bar plan 03 §6.3/§6.7 sets: a design that authors none of
    'icon_position:'/'icon_gap:'/'icon_color:' must keep generating today's
    exact code -- the literal fixed gap, the combined 'iconWidth' variable,
    one 'dc.setColor' call shared by icon and text."""
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    view = monkeyc.emit_view(resolved).text
    assert "var iconWidth = 0;" in view
    assert "iconWidth = dc.getTextWidthInPixels(iconGlyph, iconFont) + 4;" in view
    assert "var totalWidth = iconWidth + textWidth;" in view
    assert "dc.drawText(startX + iconWidth, Layout." in view
    # no general-path artifacts anywhere
    assert "iconGlyphWidth" not in view
    assert "_ICON_GAP" not in view


@pytest.mark.parametrize("position,marker", [
    ("right", "dc.drawText(startX + textWidth + gap, Layout."),
    ("top", "Graphics.TEXT_JUSTIFY_CENTER"),
    ("bottom", "Graphics.TEXT_JUSTIFY_CENTER"),
])
def test_each_new_icon_position_gets_its_own_generated_branch(
        write_design, bag, db, position, marker):
    """A test pinning each position's generated branch (plan 03 §6.3)."""
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    text = DESIGN.replace("    icon: {size: 8%r}\n",
                          f"    icon: {{size: 8%r, position: {position}}}\n")
    assert text != DESIGN
    face = _face(text, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    view = monkeyc.emit_view(resolved).text
    assert marker in view


def test_authored_gap_becomes_a_per_device_layout_constant(write_design, bag, db):
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    text = DESIGN.replace("    icon: {size: 8%r}\n", "    icon: {size: 8%r, gap: 2%r}\n")
    assert text != DESIGN
    face = _face(text, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    view = monkeyc.emit_view(resolved).text
    assert "_ICON_GAP" in view


def test_icon_color_draws_the_icon_in_its_own_colour(write_design, bag, db):
    """A test that fails if the icon is drawn in the text colour when
    `icon_color:` differs (plan 03's added scope)."""
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    text = DESIGN.replace("    icon: {size: 8%r}\n", "    icon: {size: 8%r, color: color.bg}\n")
    assert text != DESIGN
    face = _face(text, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    view = monkeyc.emit_view(resolved).text
    # two distinct setColor calls: one for the icon (palette.bg -> BG), one
    # reset back to the text colour (palette.fg -> FG) before drawing text.
    assert "dc.setColor(Palette.BG, Graphics.COLOR_TRANSPARENT);" in view
    assert "dc.setColor(Palette.FG, Graphics.COLOR_TRANSPARENT);" in view
    set_color_calls = [line for line in view.splitlines() if "dc.setColor(" in line]
    assert len(set_color_calls) >= 2


def test_apply_config_matches_settings_by_unique_identifier(write_design, bag, db):
    from wfb.emit import monkeyc
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    view = monkeyc.emit_view(resolved).text
    assert "settings.complicationSettings" in view
    assert "ref.uniqueIdentifier" in view
    assert "ref.complicationId" in view
    assert "if (unique == 1)" in view and "_configDataTop = picked;" in view
    assert "if (unique == 2)" in view and "_configDataBottom = picked;" in view


def test_manifest_gets_complications_permission_from_data_alone(write_design, bag, db):
    """A `config: data:` slot is not a catalogue reader `face.requirements()`
    would see -- `manifest.permissions()` must add it separately. The API
    floor no longer moves for this at all (2026-09-15): the manifest is one
    file shared by every target device, so `minApiLevel` stays the base
    level regardless -- availability is gated at runtime instead
    (`wfb.availability`, `wfb/emit/monkeyc/`)."""
    from wfb.emit import manifest

    face = _face(DESIGN, write_design, bag)
    assert not any(r for r in face.requirements().readers)
    devices = [db.get(d) for d in face.targets]
    text = manifest.render(face, devices)
    assert f'minApiLevel="{manifest.BASE_API_LEVEL}"' in text
    assert '<iq:uses-permission id="ComplicationSubscriber"/>' in text
    assert "ComplicationSubscriber" in manifest.permissions(face)


def test_no_config_data_means_no_complications_permission(write_design, bag, db):
    """The absence half of the same check: a design with no complication
    binding of any kind gets neither the permission nor (either way) a
    raised API floor."""
    from wfb.emit import manifest

    text = HEAD + """elements:
  a:
    type: text
    text: "hi"
    at: {anchor: center}
    color: color.fg
"""
    face = _face(text, write_design, bag)
    devices = [db.get(d) for d in face.targets]
    assert manifest.permissions(face) == []
    rendered = manifest.render(face, devices)
    assert f'minApiLevel="{manifest.BASE_API_LEVEL}"' in rendered
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
    """`WfbReading.mc`'s `unitSuffix` is the on-device twin of
    `wfb.complications.UNIT_SUFFIX` -- parsed and checked directly, the same
    discipline `tests/test_weather_barrel.py` already applies to
    `WfbWeather.mc`."""
    from pathlib import Path
    import re

    source = (Path(__file__).resolve().parent.parent / "runtime-lib"
              / "WfbReading.mc").read_text(encoding="utf-8")
    cases = dict(re.findall(
        r'case Complications\.(UNIT_\w+):\s*return\s*"([^"]*)";', source))
    assert cases, "no unitSuffix cases found -- did the barrel change shape?"
    assert cases == complications.UNIT_SUFFIX


@pytest.mark.parametrize("value, shown", [
    (12.879, "12.9"),      # steps >= 10,000, as the simulator reports them (unit "K")
    (9.876, "9.88"),
    (21.5, "21.5"),
    (101325.0, "101325"),
    (10.0, "10"),
    (9.999, "10"),         # rounds up past a threshold, then trims
    (0.5, "0.5"),
    (-3.25, "-3.25"),
    (9876, "9876"),        # a Number is untouched
    ("Mon 28", "Mon 28"),  # so is a String
])
def test_format_value_rounds_floats_and_trims_zeros(value, shown):
    assert complications.format_value(value) == shown


def test_slot_reading_goes_through_slot_text(write_design, bag, db):
    """The reading is formatted by its type's own rule (`SlotText.reading`),
    never drawn through `toString()` directly: `Float.toString()` prints six
    decimals ("12.879000K" in the simulator), and a raw sunrise is 22512."""
    from wfb.emit import monkeyc

    _, resolved = _resolved(DESIGN, write_design, bag, db)
    view = monkeyc.emit_view(resolved).text
    assert "var reading = SlotText.reading(chosenId.getType(), pulled, true, false);" in view
    assert "var reading = SlotText.reading(chosenId.getType(), pulled, false, true);" in view
    assert "value.toString()" not in view
    assert "WfbComplications.formatValue" not in view


def test_format_value_barrel_matches_the_python_twin():
    """The preview's `format_value` and the barrel's `decimalText` must use
    the same thresholds and default, or the preview lies about the watch."""
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "runtime-lib"
              / "WfbReading.mc").read_text(encoding="utf-8")
    body = source[source.index("function decimalText"):source.index("function unitSuffix")]
    assert "var decimals = 2;" in body
    assert "if (magnitude >= 100) {\n            decimals = 0;" in body
    assert "} else if (magnitude >= 10) {\n            decimals = 1;" in body
    assert complications.format_value(99.99) == "100"   # one decimal, rounds to 100.0, trimmed
    assert complications.format_value(5.0) == "5"


def test_preview_renders_without_crashing(write_design, bag, db):
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve
    from wfb.preview import render

    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
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
  a:
    type: text
    text: "hi"
    at: {anchor: center}
    color: color.fg
    on_hold: steps
"""
    face = _face(text, write_design, bag)
    assert not face.config_data
    assert not face.has_config
    assert monkeyc.complication_slots(face) == []
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
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
    per element, the same as `examples/features/slots/face.yaml` does)."""
    from wfb.build import build as run_build

    text = DESIGN.replace(
        "    label: short",
        "    lint:\n      allow: [config-unsupported]\n      reason: test\n"
        "    label: short",
    ).replace(
        """  bottom_reading:
    type: data
    slot: bottom
    at: {anchor: center, dy: 20%}
    color: color.fg
""",
        """  bottom_reading:
    type: data
    slot: bottom
    at: {anchor: center, dy: 20%}
    color: color.fg
    lint:
      allow: [config-unsupported]
      reason: test
""",
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
    assert 'minApiLevel="3.1.0"' in manifest_text
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
  slots:
    reading:
      default: steps
      choices: [steps, heart_rate]
elements:
  reading:
    type: data
    slot: reading
    at: {anchor: center}
    icon: {size: 10%r}
    color: color.fg
    absent: "--"
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
    assert 'minApiLevel="3.1.0"' in manifest_text
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
        """  bottom_reading:
    type: data
    slot: bottom
    at: {anchor: center, dy: 20%}
    color: color.fg
""",
        """  bottom_reading:
    type: data
    slot: bottom
    at: {anchor: center, dy: 20%}
    color: color.fg
    lint:
      allow: [config-unsupported]
      reason: test
""",
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
  clock:
    type: text
    text: "{time.clock:%H:%M}"
    at: {anchor: center}
    color: color.fg
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
