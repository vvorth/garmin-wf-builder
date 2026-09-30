"""`color_scheme:` and `config: style:` -- the third `config:` axis, riding
Styles (docs/research/09-data-library-and-config-axes.md §3).

`config: style:` replaces the earlier `config: colors:` outright (no shim):
`choices:` is now an author-named, ordered mapping of entry name -> entry,
and `default:`/an entry's own `colors:` are both bare names (`default: dark`,
`colors: dark`), not `color_scheme.<name>` references.

Every check below is driven red against the exact violating input before it
is trusted, the same discipline `tests/test_config.py`'s own module docstring
states.
"""

from __future__ import annotations

import pytest

from wfb import lint
from wfb.diagnostics import Bag
from wfb.palette import Color
from tests.helpers import lint_text as _lint, load_errors as _errors, load_face as _face

HEAD = """format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm, fenix8solar51mm, fr955]
resources:
  palette:
    black: "#000000"
    white: "#FFFFFF"
    dark_gray: "#555555"
    light_gray: "#AAAAAA"
"""

#: Two schemes, three roles each, all four colours legal on a 64-colour panel
#: -- the palette-dither tests below build their own off-grid variant.  Two
#: entries, neither with its own `label:`, so both exercise the label
#: fallback at the same time -- the generated `<style label=...>`
#: text comes from `color_scheme.dark`/`color_scheme.light`'s own `label:`.
SCHEME_BLOCK = """theme:
  schemes:
    dark:
      label: "Dark"
      colors: { bg: color.black, fg: color.white, dim: color.dark_gray }
    light:
      label: "Light"
      colors: { bg: color.white, fg: color.black, dim: color.light_gray }

config:
  style:
    default: dark
    choices:
      dark: { scheme: dark }
      light: { scheme: light }
"""

#: Every declared role is bound somewhere, so a real `monkeyc` build never
#: warns about an unused view field -- the same reason `test_config.py`'s own
#: `CONFIG_BLOCK`/`BODY` pair binds both axes.
BODY = """elements:
  bg:
    type: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: color.bg
  clock:
    type: text
    text: "{time.clock:%H:%M}"
    at: {anchor: center, dy: -20%}
    color: color.fg
  caption:
    type: text
    text: "STEPS"
    font: FONT_XTINY
    at: {anchor: center, dy: 20%}
    color: color.dim
"""

DESIGN = HEAD + SCHEME_BLOCK + BODY

#: A minimal `elements:` block for tests that only care about the `config:`
#: block itself, binding `config.colors.bg` once so the axis is exercised.
ELEMENT = """elements:
  c:
    type: circle
    at: {anchor: center}
    radius: 20%
    color: color.bg
"""


# -- schema and IR -------------------------------------------------------------


def test_a_valid_design_builds_clean(write_design, bag):
    face = _face(DESIGN, write_design, bag)
    assert set(face.color_scheme) == {"dark", "light"}
    assert face.config_style is not None
    assert face.config_style.default == "dark"
    assert [e.name for e in face.config_style.entries] == ["dark", "light"]
    assert [e.colors for e in face.config_style.entries] == ["dark", "light"]


def test_has_config_is_true_for_color_scheme_alone(write_design, bag):
    """The case CLAUDE.md's task brief calls out by name: no accent_color/
    data_color at all, only `color_scheme:`/`config: style:`."""
    face = _face(DESIGN, write_design, bag)
    assert not face.config
    assert face.has_config


def test_a_role_reference_is_an_unfoldable_colour_binding(write_design, bag):
    """Same shape as `config.accent_color`'s own binding
    (`test_config.py::test_config_colour_is_an_ordinary_unfoldable_colour_binding`):
    `kind == "config"`, `constant=None` -- the view field is user-editable at
    runtime, so `fold` must never inline it."""
    face = _face(DESIGN, write_design, bag)
    bg = next(e for e in face.walk() if e.id == "bg")
    assert bg.color.shown == "color.bg"
    assert bg.color.code == "_configColorsBg"
    assert bg.color.constant is None


def test_schemes_disagreeing_on_role_set_is_an_error(write_design):
    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black, fg: color.white, dim: color.dark_gray }
    light:
      colors: { bg: color.white, fg: color.black }

config:
  style:
    default: dark
    choices:
      dark: { scheme: dark }
      light: { scheme: light }
""" + BODY
    errors = _errors(text, write_design)
    assert any(d.code == "color-scheme" for d in errors), errors
    message = next(d for d in errors if d.code == "color-scheme").message
    assert "theme.schemes.light" in message and "dim" in message


def test_the_scheme_with_every_role_is_not_blamed(write_design):
    """Only `light` (missing `dim`) is named -- `dark`, which has every role
    the union declares, gets no error of its own."""
    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black, fg: color.white, dim: color.dark_gray }
    light:
      colors: { bg: color.white, fg: color.black }

config:
  style:
    default: dark
    choices:
      dark: { scheme: dark }
      light: { scheme: light }
""" + BODY
    errors = _errors(text, write_design)
    messages = [d.message for d in errors if d.code == "color-scheme"]
    assert len(messages) == 1
    assert "color_scheme.dark" not in messages[0]


def test_role_mismatch_does_not_cascade(write_design):
    """One error, at the real mistake -- `BODY` binds `color.bg` on
    three elements, so throwing the whole axis out of scope would add an
    "unknown data source" per element, the same cascade
    `test_config.py::test_a_rejected_config_axis_does_not_cascade` exists to
    prevent.  This is also the "a rejected `config: style:` plus a
    `color.bg` reader gives one error, not two" case the task brief
    calls out by name."""
    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black, fg: color.white, dim: color.dark_gray }
    light:
      colors: { bg: color.white, fg: color.black }

config:
  style:
    default: dark
    choices:
      dark: { scheme: dark }
      light: { scheme: light }
""" + BODY
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["color-scheme"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))


def test_config_colors_naming_an_undeclared_role_is_an_error(write_design):
    text = HEAD + SCHEME_BLOCK + """elements:
  c:
    type: circle
    at: {anchor: center}
    radius: 20%
    color: color.nope
"""
    errors = _errors(text, write_design)
    assert [d.message for d in errors] == ["unknown colour 'color.nope'"]
    note = " ".join(errors[0].notes)
    assert "color.bg" in note and "color.fg" in note and "color.dim" in note


def test_default_not_among_choices_is_an_error(write_design):
    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black }
    light:
      colors: { bg: color.white }

config:
  style:
    default: light
    choices:
      dark: { scheme: dark }
""" + ELEMENT
    errors = _errors(text, write_design)
    assert any(d.code == "config" and "not one of 'choices:'" in d.message for d in errors), errors


def test_default_naming_an_undeclared_entry_is_an_error(write_design):
    """`default:` names a `choices:` *entry*, not a scheme -- naming
    something that is not a declared entry at all is the same "not one of
    choices:" error, listing the entries that are declared."""
    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black }

config:
  style:
    default: nope
    choices:
      dark: { scheme: dark }
""" + ELEMENT
    errors = _errors(text, write_design)
    error = next(d for d in errors if d.code == "config" and "not one of 'choices:'" in d.message)
    assert "nope" in error.message
    assert "dark" in " ".join(error.notes)


def test_default_check_is_by_entry_name_not_scheme_reference(write_design, bag):
    """Two `choices:` entries may legitimately reference the same
    `color_scheme:` entry -- nothing but the suppressible `duplicate-style`
    warning forbids it (accepted explicitly here) -- and `default:` still
    matches by `choices:` entry *name*, not by which scheme (or, transitively,
    colour) the entry resolves to, unlike the accent/data axes' colour-value
    comparison."""
    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black }

config:
  style:
    default: also_dark
    choices:
      dark: { scheme: dark }
      also_dark:
        scheme: dark
        lint: { allow: [duplicate-style], reason: "test fixture" }
""" + ELEMENT
    face = _face(text, write_design, bag)
    assert face.config_style.default == "also_dark"


def test_a_rejected_axis_default_does_not_cascade(write_design):
    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black }
    light:
      colors: { bg: color.white }

config:
  style:
    default: nope
    choices:
      dark: { scheme: dark }
""" + ELEMENT
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["config"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))


def test_choices_naming_an_undeclared_scheme_is_an_error(write_design):
    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black }

config:
  style:
    default: dark
    choices:
      dark: { scheme: dark }
      bogus: { scheme: nope }
""" + ELEMENT
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["config"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))
    assert "unknown color scheme 'nope'" in errors[0].message
    assert "dark" in " ".join(errors[0].notes)


def test_a_declared_but_rejected_scheme_in_colors_does_not_cascade(write_design):
    """A `colors:` naming a scheme that was declared and then rejected (a
    role-set mismatch here) gets no second error -- the real mistake already
    has its own error pointing at `color_scheme:` (CLAUDE.md, "one error, not
    N").  Same scenario `test_role_mismatch_does_not_cascade` covers via
    `BODY`'s three readers; this one uses a single reader for contrast."""
    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black, fg: color.white }
    light:
      colors: { bg: color.white }

config:
  style:
    default: dark
    choices:
      dark: { scheme: dark }
      light: { scheme: light }
""" + ELEMENT
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["color-scheme"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))


def test_an_entry_with_no_colors_is_an_error(write_design):
    """This design declares no `layouts:`, so an entry needs at least
    `colors:` to mean anything at all -- `light: {}` has neither `layout:`
    nor `colors:`, which is a build error regardless of `layouts:`
    (`tests/test_layouts.py` covers the `layouts:`-declared case)."""
    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black }
    light:
      colors: { bg: color.white }

config:
  style:
    default: dark
    choices:
      dark: { scheme: dark }
      light: {}
""" + ELEMENT
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["config"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))
    assert "config.style.choices.light" in errors[0].message
    assert "needs at least one of 'layout:'/'scheme:'" in errors[0].message


def test_colors_all_or_none_reports_the_first_entry_that_lacks_it(write_design):
    """Three entries, only the second missing `colors:` -- exactly one
    error, at `middle`, not at `last` (which does have `colors:`)."""
    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black }

config:
  style:
    default: dark
    choices:
      dark: { scheme: dark }
      middle: {}
      last: { scheme: dark }
""" + ELEMENT
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["config"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))
    assert "config.style.choices.middle" in errors[0].message


def test_a_role_colour_may_be_a_palette_reference_or_a_literal(write_design, bag):
    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black, accent: "#FFAA00" }

config:
  style:
    default: dark
    choices:
      dark: { scheme: dark }
""" + """elements:
  c:
    type: circle
    at: {anchor: center}
    radius: 20%
    color: color.accent
"""
    face = _face(text, write_design, bag)
    assert face.color_scheme["dark"].colors["accent"] == Color.parse("#FFAA00")


def test_a_scheme_role_may_not_reference_config(write_design):
    """A role's colour is typed exactly like a `config:` axis's own
    `default:` -- a literal or a `palette.<name>` reference, never `config.*`
    -- the same `$defs/hexColor | $defs/paletteRef` restriction
    `configColor.default` already has, so this is rejected at the schema
    itself (there is no build-time value for a runtime-editable field for
    either one)."""
    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.accent }

config:
  accent_color:
    default: "#FF8000"
    choices: any
  style:
    default: dark
    choices:
      dark: { scheme: dark }
""" + ELEMENT
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["color"], errors
    assert "'color.accent' is a colour role" in errors[0].message


def test_the_old_config_colors_spelling_is_now_a_schema_error(write_design):
    """`config: colors:` was removed outright, no shim -- the old spelling is now an unknown-key schema error, reported on
    the author's own `config:` line, the same as `on_tap:`/`carousel`/bare
    font `scale:` (CLAUDE.md §6)."""
    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black }
    light:
      colors: { bg: color.white }

config:
  colors:
    default: color_scheme.dark
    choices:
      - color_scheme.dark
      - color_scheme.light
""" + ELEMENT
    errors = _errors(text, write_design)
    schema_errors = [d for d in errors if d.code == "schema"]
    assert schema_errors, errors
    assert schema_errors[0].span is not None
    note = " ".join(n for d in schema_errors for n in d.notes)
    assert "style" in note


# -- lint: config-unsupported --------------------------------------------------


def test_config_unsupported_names_every_role_on_fenix5(write_design, db):
    """The native editor (fēnix 8) and the settings menu (fr955) both edit
    config:; fenix5 has neither."""
    if "fenix5" not in db.ids():
        pytest.skip("fenix5 is not installed")
    for device_id in ("fenix8solar47mm", "fr955"):
        bag = _lint(DESIGN, write_design, db, device_id)
        assert not any(d.code == "config-unsupported" for d in bag.items), bag.render()

    fr955 = _lint(DESIGN, write_design, db, "fenix5")
    warnings = [d for d in fr955.items if d.code == "config-unsupported"]
    assert len(warnings) == 1, fr955.render()
    assert "color.bg" in warnings[0].message
    assert "color.fg" in warnings[0].message
    assert "color.dim" in warnings[0].message
    # DESIGN has two entries (dark, light) -- the non-default one is named as
    # unreachable on a device with no editor to switch away from the default.
    note = " ".join(warnings[0].notes)
    assert "light" in note and "unreachable" in note


def test_config_unsupported_is_suppressible_from_any_one_referencing_element(write_design, db):
    text = DESIGN.replace(
        """    color: color.dim
""",
        """    color: color.dim
    lint:
      allow: [config-unsupported]
      reason: "test"
""",
    )
    fr955 = _lint(text, write_design, db, "fr955")
    assert not any(d.code == "config-unsupported" for d in fr955.items), fr955.render()


def test_config_unsupported_is_suppressible_from_an_outline_only_user(write_design, db):
    """An element that reaches `color.dim` only
    through `outline: ...` is a user of it, so its `lint: allow`
    counts -- before, `_users_of` never looked at an outline."""
    text = DESIGN.replace(
        """    color: color.dim
""",
        """    color: "#FFFFFF"
    outline: color.dim
    lint:
      allow: [config-unsupported]
      reason: "test"
""",
    )
    fr955 = _lint(text, write_design, db, "fr955")
    assert not any(d.code == "config-unsupported" for d in fr955.items), fr955.render()


# -- lint: palette-dither, reached through config.colors -----------------------


OFF_GRID_SCHEME = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: "#FF8000" }

config:
  style:
    default: dark
    choices:
      dark: { scheme: dark }
""" + ELEMENT


def test_an_off_grid_role_colour_dithers(write_design, db):
    bag = _lint(OFF_GRID_SCHEME, write_design, db, "fenix8solar47mm")
    warnings = [d for d in bag.items if d.code == "palette-dither"]
    assert any("color.bg" in d.message for d in warnings), bag.render()


def test_role_palette_dither_is_suppressible_on_the_referencing_element(write_design, db):
    text = OFF_GRID_SCHEME.replace(
        """    color: color.bg
""",
        """    color: color.bg
    lint:
      allow: [palette-dither]
      reason: "test"
""",
    )
    bag = _lint(text, write_design, db, "fenix8solar47mm")
    warnings = [d for d in bag.items
                if d.code == "palette-dither" and "color.bg" in d.message]
    assert not warnings, bag.render()


def test_a_scheme_no_entry_references_is_not_checked(write_design, db, bag):
    """`unused` is a real color_scheme entry with an off-grid colour, but no
    `config: style:` entry references it, so `resolveStyle` never assigns it
    and there is nothing on the wrist to warn about."""
    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black }
    unused:
      colors: { bg: "#FF8000" }

config:
  style:
    default: dark
    choices:
      dark: { scheme: dark }
""" + ELEMENT
    face = _face(text, write_design, bag)
    assert "unused" in face.color_scheme
    lint_bag = _lint(text, write_design, db, "fenix8solar47mm")
    assert not any(d.code == "palette-dither" for d in lint_bag.items), lint_bag.render()


# -- lint: duplicate-style ------------------------------------------------------


DUPLICATE_STYLE = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black }

config:
  style:
    default: dark
    choices:
      dark: { scheme: dark }
      dark2: { scheme: dark }
""" + ELEMENT


def test_duplicate_style_fires_for_two_entries_resolving_the_same_way(write_design, bag):
    """`check_duplicate_style` is design-level, not part of
    `lint.run`'s per-device checks -- called directly here, the same way
    `resolve_all` calls it, rather than through the `_lint` helper."""
    face = _face(DUPLICATE_STYLE, write_design, bag)
    lint.check_duplicate_style(face, bag)
    warnings = [d for d in bag.items if d.code == "duplicate-style"]
    assert len(warnings) == 1, bag.render()
    assert "dark2" in warnings[0].message
    assert "dark" in " ".join(warnings[0].notes)


def test_duplicate_style_is_suppressible_on_the_second_entry(write_design, bag):
    text = DUPLICATE_STYLE.replace(
        "      dark2: { scheme: dark }\n",
        "      dark2:\n"
        "        scheme: dark\n"
        "        lint: { allow: [duplicate-style], reason: \"test fixture\" }\n",
    )
    face = _face(text, write_design, bag)
    lint.check_duplicate_style(face, bag)
    assert not any(d.code == "duplicate-style" for d in bag.items), bag.render()


def test_duplicate_style_is_suppressible_only_on_the_second_entry(write_design, bag):
    """Suppression lives on the entry that *makes* the pair a duplicate
    -- putting it on the first entry instead leaves the warning
    live."""
    text = DUPLICATE_STYLE.replace(
        "      dark: { scheme: dark }\n",
        "      dark:\n"
        "        scheme: dark\n"
        "        lint: { allow: [duplicate-style], reason: \"test fixture\" }\n",
    )
    face = _face(text, write_design, bag)
    lint.check_duplicate_style(face, bag)
    assert any(d.code == "duplicate-style" for d in bag.items), bag.render()


def test_duplicate_style_is_reported_once_across_every_target(write_design, bag):
    """Design-level, not per-target: `check_duplicate_style` runs
    once in `resolve_all`, before the per-device loop -- unlike an ordinary
    `lint.run` check, which runs once per resolved device.  `DUPLICATE_STYLE`
    targets all three of this project's devices."""
    from wfb.build import resolve_all, select_devices
    from wfb.build import load

    design = write_design(DUPLICATE_STYLE)
    face = load(design, bag)
    assert face is not None, bag.render()
    assert len(face.targets) == 3, face.targets

    from wfb.devices import DeviceDatabase

    db = DeviceDatabase.discover()
    devices = select_devices(face, db, bag)
    resolve_all(face, devices, bag)
    warnings = [d for d in bag.items if d.code == "duplicate-style"]
    assert len(warnings) == 1, bag.render()


def test_an_unknown_style_entry_lint_code_is_a_lint_allow_error(write_design, bag):
    """`check_lint_allow` validates a `config: style:` entry's own `lint:`
    the same way it validates an element's -- a typo there must not
    fail silently either.  Called directly, the same way `resolve_all` does
    -- `check_lint_allow` is device-independent, not part of `lint.run`."""
    text = DUPLICATE_STYLE.replace(
        "      dark2: { scheme: dark }\n",
        "      dark2:\n"
        "        scheme: dark\n"
        "        lint: { allow: [duplicat-style], reason: \"typo\" }\n",
    )
    face = _face(text, write_design, bag)
    lint.check_lint_allow(face, bag)
    assert any(
        d.code == "lint-allow" and "config.style.choices.dark2" in d.message
        for d in bag.items
    ), bag.render()


# -- codegen: fields, resolveStyle, applyConfig --------------------------------


def _view(text, write_design, db, device_id="fenix8solar47mm"):
    from wfb.emit.monkeyc import emit_view
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    bag = Bag()
    face = _face(text, write_design, bag)
    device = db.get(device_id)
    resolved = resolve(face, device, bake_fonts(face, device))
    return emit_view(resolved).text


def test_the_generated_view_has_role_fields_and_resolve_style(write_design, db):
    view = _view(DESIGN, write_design, db)
    assert "private var _configColorsBg as Number = 0x000000;" in view
    assert "private var _configColorsFg as Number = 0xFFFFFF;" in view
    assert "private var _configColorsDim as Number = 0x555555;" in view
    assert "private function resolveStyle(style as Number) as Void" in view
    resolve_body = view.split("private function resolveStyle")[1].split("\n\n")[0]
    assert "if (style == 0)" in resolve_body
    assert "if (style == 1)" in resolve_body
    assert "_configColorsBg = 0xFFFFFF;" in resolve_body  # style 1 == light
    assert "dark -- color_scheme.dark" in resolve_body
    assert "light -- color_scheme.light" in resolve_body


def test_applyconfig_reads_styleid_and_dispatches(write_design, db):
    view = _view(DESIGN, write_design, db)
    apply_config = view.split("function applyConfig")[1].split("\n    function ")[0]
    assert "settings.styleId" in apply_config
    assert "resolveStyle(" in apply_config
    # range-checked, not trusted -- a rebuild with fewer entries can leave a
    # saved id past the end.
    assert ">= 0" in apply_config and "< 2" in apply_config


def test_only_color_scheme_no_colour_axes_still_gets_the_full_feature(write_design, db):
    """The exact case the task brief calls the most likely to be broken and
    least likely to be noticed: no `accent_color`/`data_color` at all."""
    from wfb.emit.monkeyc import emit_delegate, needs_delegate

    bag = Bag()
    face = _face(DESIGN, write_design, bag)
    assert not face.config
    assert needs_delegate(face)

    view = _view(DESIGN, write_design, db)
    assert "import Toybox.Application.WatchFaceConfig;" in view
    assert "resolveStyle" in view
    assert "function onLayout" in view
    on_layout = view.split("function onLayout")[1].split("\n    function ")[0]
    assert "Application has :WatchFaceConfig" in on_layout
    assert "applyConfig(settings);" in on_layout

    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    delegate = emit_delegate(resolved).text
    assert "function onWatchFaceConfigEdited" in delegate
    assert "_view.applyConfig(settings);" in delegate


def test_a_face_with_no_config_at_all_generates_no_style_code(write_design, db):
    plain = HEAD + """elements:
  clock:
    type: text
    text: "{time.clock:%H:%M}"
    at: {anchor: center}
    color: color.black
"""
    view = _view(plain, write_design, db)
    assert "_configColors" not in view
    assert "resolveStyle" not in view
    assert "applyConfig" not in view
    assert "WatchFaceConfig" not in view


# -- codegen: the generated resource -------------------------------------------


def test_the_config_resource_has_a_styles_block(write_design, bag):
    from wfb.emit.resources import config_resource

    face = _face(DESIGN, write_design, bag)
    xml = config_resource(face)
    assert '<style id="0" default="true" label="@Strings.ConfigStyle0"/>' in xml
    assert '<style id="1" label="@Strings.ConfigStyle1"/>' in xml


def test_an_unlabelled_scheme_gets_no_label_attribute(write_design, bag):
    from wfb.emit.resources import config_resource

    text = HEAD + """theme:
  schemes:
    dark:
      colors: { bg: color.black }
    light:
      colors: { bg: color.white }

config:
  style:
    default: dark
    choices:
      dark: { scheme: dark }
      light: { scheme: light }
""" + ELEMENT
    face = _face(text, write_design, bag)
    xml = config_resource(face)
    assert '<style id="0" default="true"/>' in xml
    assert '<style id="1"/>' in xml


def test_labelled_schemes_get_shared_strings(write_design, bag):
    """Both `DESIGN` entries have no `label:` of their own, so both exercise
    the label fallback: the generated `<string>` text is the
    `color_scheme:` entry's own `label:`."""
    from wfb.emit.resources import shared_strings

    face = _face(DESIGN, write_design, bag)
    strings = shared_strings(face)
    assert '<string id="ConfigStyle0">Dark</string>' in strings
    assert '<string id="ConfigStyle1">Light</string>' in strings


def test_an_entrys_own_label_overrides_the_schemes(write_design, bag):
    """An entry's own `label:` wins over its scheme's -- the fallback only
    applies when the entry has none of its own."""
    from wfb.emit.resources import config_resource, shared_strings

    text = HEAD + """theme:
  schemes:
    dark:
      label: "Dark"
      colors: { bg: color.black }
    light:
      colors: { bg: color.white }

config:
  style:
    default: dark
    choices:
      dark: { label: "Midnight", scheme: dark }
      light: { scheme: light }
""" + ELEMENT
    face = _face(text, write_design, bag)
    xml = config_resource(face)
    assert '<style id="0" default="true" label="@Strings.ConfigStyle0"/>' in xml
    # 'light' has no label of its own, and color_scheme.light has none either
    # -- no fallback value exists, so no label attribute at all.
    assert '<style id="1"/>' in xml
    strings = shared_strings(face)
    assert '<string id="ConfigStyle0">Midnight</string>' in strings  # entry wins over "Dark"
    assert "ConfigStyle1" not in strings


def test_fr955_gets_no_configs_resource(write_design, bag, db):
    from wfb.emit.resources import build_bundle

    face = _face(DESIGN, write_design, bag)
    fr955 = db.get("fr955")
    bundle = build_bundle(face, fr955, {})
    assert "configs/watchface.xml" not in bundle.files


# -- preview --------------------------------------------------------------------


def test_preview_renders_at_the_default_scheme(write_design, db):
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve
    from wfb.preview import render

    bag = Bag()
    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    image = render(resolved)
    assert image.size == (device.width * 2, device.height * 2)


# -- the real toolchain ---------------------------------------------------------


@pytest.mark.slow
def test_a_color_scheme_design_compiles_warning_free_on_every_target(
        write_design, tmp_path, db, toolchain):  # noqa: F811
    """The bar this task and CLAUDE.md both set: real `monkeyc`, all three
    targets, warning-free (`config-unsupported` on fr955 accepted explicitly,
    the same as `examples/features/config/face.yaml` does for the two colour axes)."""
    from wfb.build import build as run_build

    text = DESIGN.replace(
        """    color: color.dim
""",
        """    color: color.dim
    lint:
      allow: [config-unsupported]
      reason: "test fixture"
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

    view = (result.output_dir / "source" / "TestView.mc").read_text(encoding="utf-8")
    assert "resolveStyle" in view
    delegate = (result.output_dir / "source" / "TestDelegate.mc").read_text(encoding="utf-8")
    assert "onWatchFaceConfigEdited" in delegate

    fenix_config = (result.output_dir / "resources-fenix8solar47mm" / "configs"
                    / "watchface.xml")
    assert fenix_config.exists()
    assert "<styles>" in fenix_config.read_text(encoding="utf-8")
    fr955_config = (result.output_dir / "resources-fr955" / "configs" / "watchface.xml")
    assert not fr955_config.exists()


@pytest.mark.slow
def test_only_color_scheme_no_colour_axes_compiles_warning_free(
        write_design, tmp_path, db, toolchain):  # noqa: F811
    """The task brief's own headline risk, put through the real compiler --
    not just inspected as generated text (CLAUDE.md records a feature that
    shipped with a real, undetected `monkeyc` warning for exactly this gap:
    every test inspected generated text and none ran the compiler)."""
    from wfb.build import build as run_build

    text = DESIGN.replace(
        """    color: color.dim
""",
        """    color: color.dim
    lint:
      allow: [config-unsupported]
      reason: "test fixture"
""",
    )
    assert "config:\n  accent_color" not in text
    design = write_design(text)
    bag = Bag()
    result = run_build(design, output=tmp_path / "out", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    monkeyc_warnings = [d for d in bag.items
                        if d.severity.value == "warning" and d.code == "monkeyc"]
    assert not monkeyc_warnings, "\n".join(d.message for d in monkeyc_warnings)
