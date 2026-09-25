"""`layouts:` -- named widget sets, form A only (plan 02
§12.1, §12.2). An author never writes membership on an element; a
`layouts: <name>:` body's `static:`/`elements:` are folded by
`wfb/desugar.py`'s `_layouts_block` into two synthetic groups appended to the
top-level `elements:`, and `wfb/ir/builder.py`'s `Builder._assign_layouts` stamps
`Element.layout` on them (and their descendants) afterwards.

Every check below is driven red against the exact violating input before it
is trusted, the same discipline `tests/test_color_scheme.py`'s own module
docstring states.  This file is the front end only (schema, desugar, IR,
front-end lint); codegen for `layouts:` is covered in
`tests/test_layouts_codegen.py`.
"""

from __future__ import annotations

from wfb import desugar, yamlsrc
from wfb.diagnostics import Bag
from tests.helpers import (
    lint_text as _lint, load_errors as _errors, load_face as _face, resolve_text as _resolved,
)

HEAD = """format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm, fenix8solar51mm, fr955]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
"""

#: Two layouts, one shared element.  `digital` has both static and dynamic
#: content of its own; `analog` has only dynamic content -- exercising both
#: halves of the fold and the "no static half at all" case together.
TWO_LAYOUTS = HEAD + """layouts:
  digital:
    static:
      digital_bg:
        type: shape
        shape: rectangle
        at: {anchor: center}
        size: {width: 40%, height: 40%}
        color: palette.bg
    elements:
      digital_clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg
  analog:
    elements:
      analog_label:
        type: text
        text: "A"
        at: {anchor: center}
        color: palette.fg

config:
  style:
    default: digital
    choices:
      digital: { layout: digital }
      analog: { layout: analog }

elements:
  shared_caption:
    type: text
    text: "STEPS"
    at: {anchor: center, dy: 40%}
    color: palette.fg
"""

#: The same design, with each layout's `static:`/`elements:` written as a
#: list instead of a mapping.
TWO_LAYOUTS_LIST_FORM = HEAD + """layouts:
  digital:
    static:
      - id: digital_bg
        type: shape
        shape: rectangle
        at: {anchor: center}
        size: {width: 40%, height: 40%}
        color: palette.bg
    elements:
      - id: digital_clock
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg
  analog:
    elements:
      - id: analog_label
        type: text
        text: "A"
        at: {anchor: center}
        color: palette.fg

config:
  style:
    default: digital
    choices:
      digital: { layout: digital }
      analog: { layout: analog }

elements:
  - id: shared_caption
    type: text
    text: "STEPS"
    at: {anchor: center, dy: 40%}
    color: palette.fg
"""


def _document(write_design, text: str, bag: Bag):
    """Load and desugar without validating, so a rewrite can be inspected raw."""
    doc = yamlsrc.load(write_design(text), bag)
    assert doc is not None, bag.render()
    ok = desugar.desugar(doc, bag)
    return doc, ok


# -- desugar --------------------------------------------------------------------


def test_mapping_and_list_forms_produce_the_same_document(write_design, bag):
    map_face = _face(TWO_LAYOUTS, write_design, bag)
    list_face = _face(TWO_LAYOUTS_LIST_FORM, write_design, Bag())
    map_walk = [(e.id, e.kind, e.layout) for e in map_face.walk()]
    list_walk = [(e.id, e.kind, e.layout) for e in list_face.walk()]
    assert map_walk == list_walk
    assert [e.id for e in map_face.draw_order()] == [e.id for e in list_face.draw_order()]


def test_layout_content_spans_point_at_the_authors_line(write_design, bag):
    """An error inside `layouts.digital.elements.digital_clock` reports that
    element's own line -- the fold must not cost the author the span the
    top-level `static:` rewrite already keeps."""
    text = TWO_LAYOUTS.replace("color: palette.fg\n  analog:",
                               "color: palette.missing\n  analog:")
    errors = _errors(text, write_design)
    diag = next(d for d in errors if d.code == "expression")
    assert diag.span is not None
    assert "palette.missing" in text.splitlines()[diag.span.line - 1]


def test_an_empty_layout_is_legal(write_design, bag):
    text = HEAD + """layouts:
  digital:
    elements:
      digital_clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg
  analog: {}

config:
  style:
    default: digital
    choices:
      digital: { layout: digital }
      analog: { layout: analog }

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""
    face = _face(text, write_design, bag)
    assert face.layouts == ("digital", "analog")
    assert not any(e.layout == "analog" for e in face.walk())


def test_an_empty_static_or_elements_list_is_popped_not_left_behind(write_design, bag):
    """`static: []`/`elements: []` inside a layout must be treated as
    absent, the same as an omitted key -- left behind, the schema's own
    `minItems: 1` on `$defs/elementListOrMapping` would reject it, which is
    not what "treated as absent" means (a coordinator hand-probe caught this:
    the key was skipped but never popped)."""
    text = HEAD + """layouts:
  digital:
    static: []
    elements:
      digital_clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg

config:
  style:
    default: digital
    choices:
      digital: { layout: digital }

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""
    face = _face(text, write_design, bag)
    assert face.layouts == ("digital",)
    assert not any(e.id == "layout_digital_static" for e in face.walk())


def test_a_nested_author_id_colliding_with_a_generated_one_is_an_error(write_design):
    """A collision buried inside a shared group's `children:` -- not just a
    top-level element -- must still surface as the dedicated `layouts`
    error, naming the reserved id, not a generic `duplicate-id` pointing at
    the layout's own `elements:` key (a coordinator hand-probe caught this:
    the initial scan was top-level only)."""
    text = HEAD + """layouts:
  digital:
    elements:
      clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg

elements:
  - id: wrapper
    type: group
    children:
      - id: layout_digital
        type: shape
        shape: circle
        at: {anchor: center}
        radius: 10%
        color: palette.fg
"""
    bag = Bag()
    doc, ok = _document(write_design, text, bag)
    assert not ok
    assert any(d.code == "layouts" for d in bag.items), bag.render()
    assert not any(d.code == "duplicate-id" for d in bag.items), bag.render()
    diag = next(d for d in bag.items if d.code == "layouts")
    assert "layout_digital" in diag.message
    assert "an element" in diag.message


def test_a_layouts_lint_key_survives_desugar(write_design, bag):
    text = HEAD + """layouts:
  digital:
    elements:
      digital_clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg
    lint:
      allow: [unreachable-layout]
      reason: "test fixture"

config:
  style:
    default: digital
    choices:
      digital: { layout: digital }

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""
    face = _face(text, write_design, bag)
    decl = face.layout_decls["digital"]
    assert decl.lint_allow == frozenset({"unreachable-layout"})
    assert decl.lint_reason == "test fixture"


def test_an_unknown_key_in_a_layout_body_is_a_schema_error(write_design):
    text = HEAD + """layouts:
  digital:
    elements:
      digital_clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg
    bogus: 1

config:
  style:
    default: digital
    choices:
      digital: { layout: digital }

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""
    errors = _errors(text, write_design)
    diag = next(d for d in errors if d.code == "schema" and "unknown key" in d.message)
    assert "layouts.digital" in diag.message
    assert diag.span is not None
    # additionalProperties reports at the containing object's own span (the
    # same convention `test_an_unknown_config_key_is_rejected_naming_what_
    # is_accepted` in tests/test_config.py already exercises) -- a line
    # inside the offending 'digital:' body, not the extra key itself.
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "digital:")
    end = next(i for i, line in enumerate(lines) if line.strip() == "config:")
    assert start < diag.span.line - 1 < end
    note = " ".join(diag.notes)
    assert "static" in note and "elements" in note and "lint" in note


def test_an_author_element_id_colliding_with_a_generated_one_is_an_error(write_design):
    text = HEAD + """layouts:
  digital:
    elements:
      clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg

elements:
  - id: layout_digital
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 10%
    color: palette.fg
"""
    bag = Bag()
    doc, ok = _document(write_design, text, bag)
    assert not ok
    assert any(d.code == "layouts" for d in bag.items), bag.render()
    diag = next(d for d in bag.items if d.code == "layouts")
    assert "layout_digital" in diag.message
    assert "an element" in diag.message


def test_two_layouts_generating_the_same_id_is_an_error(write_design):
    """`digital`'s static half and `digital_static`'s elements half both
    generate the id `layout_digital_static` -- the exact collision plan 02
    §12.2 names by example."""
    text = HEAD + """layouts:
  digital:
    static:
      digital_bg:
        type: shape
        shape: circle
        at: {anchor: center}
        radius: 10%
        color: palette.bg
  digital_static:
    elements:
      whatever:
        type: text
        text: "x"
        at: {anchor: center}
        color: palette.fg
"""
    bag = Bag()
    doc, ok = _document(write_design, text, bag)
    assert not ok
    assert any(d.code == "layouts" for d in bag.items), bag.render()
    diag = next(d for d in bag.items if d.code == "layouts")
    assert "layout_digital_static" in diag.message
    assert "layout 'digital'" in diag.message


# -- IR: membership ---------------------------------------------------------------


def test_membership_is_assigned_to_synthetic_groups_and_descendants(write_design, bag):
    face = _face(TWO_LAYOUTS, write_design, bag)
    by_id = {e.id: e for e in face.walk()}
    assert by_id["digital_bg"].layout == "digital"
    assert by_id["digital_clock"].layout == "digital"
    assert by_id["analog_label"].layout == "analog"
    assert by_id["shared_caption"].layout is None
    # The synthetic groups themselves carry the assignment too.
    assert by_id["layout_digital_static"].layout == "digital"
    assert by_id["layout_digital"].layout == "digital"
    assert by_id["layout_analog"].layout == "analog"


def test_an_author_written_layouts_key_on_an_element_is_rejected(write_design):
    """Form A only -- there is no element-level membership key."""
    text = HEAD + """elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    at: {anchor: center}
    color: palette.fg
    layouts: [digital]
"""
    errors = _errors(text, write_design)
    assert any(d.code == "schema" and "unknown key" in d.message for d in errors), errors


# -- IR: the slot rule (§12.5), over all three paths -----------------------------


SLOT_CONFIG = """config:
  data:
    reading:
      default: complication.steps
      choices: any
  style:
    default: digital
    choices:
      digital: { layout: digital }

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""


def test_slot_directly_in_layout_elements_is_an_error(write_design):
    text = HEAD + """layouts:
  digital:
    elements:
      digital_slot:
        type: complication_slot
        slot: config.data.reading
        at: {anchor: center}
        icon_size: 10%r
        color: palette.fg
""" + SLOT_CONFIG
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["layouts"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))
    assert "digital_slot" in errors[0].message


def test_slot_nested_in_a_group_inside_a_layout_is_an_error(write_design):
    text = HEAD + """layouts:
  digital:
    elements:
      wrapper:
        type: group
        children:
          - id: digital_slot
            type: complication_slot
            slot: config.data.reading
            at: {anchor: center}
            icon_size: 10%r
            color: palette.fg
""" + SLOT_CONFIG
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["layouts"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))
    assert "digital_slot" in errors[0].message


def test_slot_in_layout_static_gives_exactly_one_error(write_design):
    """The static-subtree check (`_apply_static`) never runs once
    `_assign_layouts` has already put an error in the bag -- so this must
    give exactly the layout error, not also `static`'s own "a
    complication_slot cannot be static"."""
    text = HEAD + """layouts:
  digital:
    static:
      digital_slot:
        type: complication_slot
        slot: config.data.reading
        at: {anchor: center}
        icon_size: 10%r
        color: palette.fg
""" + SLOT_CONFIG
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["layouts"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))
    assert "digital_slot" in errors[0].message


# -- IR: config: style: entries ---------------------------------------------------


def test_an_undeclared_layout_is_an_error(write_design):
    text = HEAD + """layouts:
  digital:
    elements:
      digital_clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg

config:
  style:
    default: digital
    choices:
      digital: { layout: nope }

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""
    errors = _errors(text, write_design)
    assert any(d.code == "config" and "unknown layout 'nope'" in d.message
               for d in errors), errors
    note = " ".join(n for d in errors for n in d.notes)
    assert "digital" in note


def test_layout_is_required_on_every_entry_once_layouts_is_declared(write_design):
    text = HEAD + """layouts:
  digital:
    elements:
      digital_clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg

color_scheme:
  dark:
    colors: { fg: palette.fg }

config:
  style:
    default: digital
    choices:
      digital: { layout: digital }
      dark_only: { colors: dark }

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""
    errors = _errors(text, write_design)
    assert any(
        d.code == "config" and "config.style.choices.dark_only" in d.message
        and "needs 'layout:'" in d.message
        for d in errors
    ), errors


def test_layout_is_rejected_when_no_layouts_are_declared(write_design):
    text = HEAD + """color_scheme:
  dark:
    colors: { fg: palette.fg }

config:
  style:
    default: dark
    choices:
      dark: { layout: digital, colors: dark }

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""
    errors = _errors(text, write_design)
    assert any(
        d.code == "config" and "config.style.choices.dark" in d.message
        and "declares no 'layouts:'" in d.message
        for d in errors
    ), errors


def test_an_entry_with_neither_layout_nor_colors_is_an_error(write_design):
    text = HEAD + """layouts:
  digital:
    elements:
      digital_clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg
  analog:
    elements:
      analog_label:
        type: text
        text: "A"
        at: {anchor: center}
        color: palette.fg

config:
  style:
    default: digital
    choices:
      digital: { layout: digital }
      bare: {}

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["config"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))
    assert "config.style.choices.bare" in errors[0].message
    assert "needs at least one of 'layout:'/'colors:'" in errors[0].message


def test_colors_all_or_none_still_holds_with_layouts(write_design):
    """`colors:` is all-or-none across entries, independent of `layout:`
    (plan 02 §12.4) -- one entry naming both, another naming only `layout:`,
    disagree on `colors:`."""
    text = HEAD + """layouts:
  digital:
    elements:
      digital_clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg
  analog:
    elements:
      analog_label:
        type: text
        text: "A"
        at: {anchor: center}
        color: palette.fg

color_scheme:
  dark:
    colors: { fg: palette.fg }

config:
  style:
    default: digital
    choices:
      digital: { layout: digital, colors: dark }
      analog: { layout: analog }

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["config"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))
    assert "config.style.choices.analog" in errors[0].message
    assert "'colors:' must be declared on every entry, or none" in " ".join(errors[0].notes)


def test_layouts_with_no_config_style_is_an_error(write_design):
    text = HEAD + """layouts:
  digital:
    elements:
      digital_clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["layouts"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))
    assert "nothing lets the wearer pick it" in errors[0].message


def test_a_rejected_config_style_plus_layouts_gives_one_error(write_design):
    """`config: style:` itself fails (`default:` not among `choices:`) --
    `layouts:` gets no second, derived error about being unreachable, the
    usual cascade discipline."""
    text = HEAD + """layouts:
  digital:
    elements:
      digital_clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg

config:
  style:
    default: nope
    choices:
      digital: { layout: digital }

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["config"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))


# -- has_config / wfb check ---------------------------------------------------------


def test_a_layout_only_design_passes_check_and_has_config(write_design, bag):
    """No `color_scheme:` anywhere -- `layouts:` alone must still turn on
    the whole on-device-config feature (the truthiness trap, CLAUDE.md §7)."""
    text = HEAD + """layouts:
  digital:
    elements:
      digital_clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg
  analog:
    elements:
      analog_label:
        type: text
        text: "A"
        at: {anchor: center}
        color: palette.fg

config:
  style:
    default: digital
    choices:
      digital: { layout: digital }
      analog: { layout: analog }

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""
    face = _face(text, write_design, bag)
    assert face.has_config
    assert not face.color_scheme
    assert face.config_style.default_entry.colors is None


# -- draw order (§12.3) -----------------------------------------------------------


def test_a_high_z_shared_element_still_draws_before_a_layout_element(write_design, bag):
    """Dynamic content: a shared element with `z: 50` still draws before a
    layout element with no `z:` at all -- the layer rank outranks `z`."""
    text = HEAD + """layouts:
  digital:
    elements:
      digital_clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg

config:
  style:
    default: digital
    choices:
      digital: { layout: digital }

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
    z: 50
"""
    face = _face(text, write_design, bag)
    order = [e.id for e in face.draw_order()]
    assert order.index("shared") < order.index("digital_clock")


def test_a_high_z_shared_static_element_still_draws_before_a_layout_static_element(
        write_design, bag):
    text = HEAD + """layouts:
  digital:
    static:
      digital_bg:
        type: shape
        shape: circle
        at: {anchor: center}
        radius: 10%
        color: palette.bg

config:
  style:
    default: digital
    choices:
      digital: { layout: digital }

static:
  shared_bg:
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
    z: 50

elements:
  clock:
    type: text
    value: time.clock
    format: "{:%H:%M}"
    at: {anchor: center}
    color: palette.fg
"""
    face = _face(text, write_design, bag)
    order = [e.id for e in face.draw_order()]
    assert order.index("shared_bg") < order.index("digital_bg")


def test_z_still_orders_within_one_layout(write_design, bag):
    text = HEAD + """layouts:
  digital:
    elements:
      first:
        type: text
        text: "1"
        at: {anchor: center}
        color: palette.fg
        z: 5
      second:
        type: text
        text: "2"
        at: {anchor: center}
        color: palette.fg
        z: 1

config:
  style:
    default: digital
    choices:
      digital: { layout: digital }

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""
    face = _face(text, write_design, bag)
    order = [e.id for e in face.draw_order()]
    assert order.index("second") < order.index("first")


# -- lint: a layout-only default entry (no color_scheme: at all) -----------------


LAYOUT_ONLY = HEAD + """layouts:
  digital:
    elements:
      digital_clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        at: {anchor: center}
        color: palette.fg
  analog:
    elements:
      analog_label:
        type: text
        text: "A"
        at: {anchor: center}
        color: palette.fg

config:
  style:
    default: digital
    choices:
      digital: { layout: digital }
      analog: { layout: analog }

elements:
  shared:
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""


def test_config_unsupported_on_a_layout_only_default_names_no_role(write_design, db):
    """The default entry (`digital`) is layout-only -- no `colors:` at all --
    so there is no role for `config-unsupported` to name; only the
    unreachable-entry note applies (the widened Phase 1 assert sites, per the
    coordinator's Phase 2 follow-up)."""
    bag = _lint(LAYOUT_ONLY, write_design, db, "fr955")
    warnings = [d for d in bag.items if d.code == "config-unsupported"]
    assert len(warnings) == 1, bag.render()
    assert "config.colors." not in warnings[0].message
    note = " ".join(warnings[0].notes)
    assert "analog" in note and "unreachable" in note


def test_color_scheme_palette_check_is_a_no_op_for_a_layout_only_default(write_design, db):
    """`check_color_scheme_palette` returns early when the default entry has
    no `colors:` -- there is no role to check the palette-legality of."""
    from wfb import lint

    bag = Bag()
    face, resolved = _resolved(LAYOUT_ONLY, write_design, bag, db, "fenix8solar47mm")
    lint.check_color_scheme_palette(resolved, bag)
    assert not any(d.code == "palette-dither" for d in bag.items), bag.render()


def test_preview_renders_a_layout_only_design(write_design, db, bag):
    """`wfb.preview.render` must not crash on a design whose default style
    entry has no `colors:` to seed `config.colors.*` from."""
    from wfb.preview import render

    face, resolved = _resolved(LAYOUT_ONLY, write_design, bag, db, "fenix8solar47mm")
    image = render(resolved)
    assert image.size == (resolved.device.width * 2, resolved.device.height * 2)


def test_emit_view_does_not_crash_on_a_layout_only_default_entry(write_design, db, bag):
    """`_emit_config_fields`/`_emit_resolve_style` must not crash on a
    layout-only default entry -- called directly on the resolved face, the
    same way `tests/test_color_scheme.py`'s own `_view` helper does.  Real
    codegen for `layouts:` (the `_configLayout` field, the guards) is
    covered in `tests/test_layouts_codegen.py`; this pins the narrower
    "no colour axis at all" edge case."""
    from wfb.emit.monkeyc import emit_view

    face, resolved = _resolved(LAYOUT_ONLY, write_design, bag, db, "fenix8solar47mm")
    view = emit_view(resolved).text
    assert "_configColorsBg" not in view  # no scheme -- no role fields at all
    assert "private var _configLayout as Number = 0;" in view
    assert "private function resolveStyle(style as Number) as Void" in view
    resolve_body = view.split("private function resolveStyle")[1].split("\n\n")[0]
    assert "if (style == 0)" in resolve_body and "if (style == 1)" in resolve_body
    assert "digital -- layouts.digital" in resolve_body
