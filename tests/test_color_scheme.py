"""`color_scheme:` and `config: colors:` -- the third `config:` axis, riding
Styles (docs/research/09-data-library-and-config-axes.md §3).

Every check below is driven red against the exact violating input before it
is trusted, the same discipline `tests/test_config.py`'s own module docstring
states.
"""

from __future__ import annotations

import pytest

from tests.test_build import toolchain  # noqa: F401  -- a fixture, used by name
from tests.test_diagnostics import load
from wfb import lint
from wfb.diagnostics import Bag
from wfb.palette import Color

HEAD = """format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm, fenix8solar51mm, fr955]
palette:
  black: "#000000"
  white: "#FFFFFF"
  dark_gray: "#555555"
  light_gray: "#AAAAAA"
"""

#: Two schemes, three roles each, all four colours legal on a 64-colour panel
#: -- the palette-dither tests below build their own off-grid variant.
SCHEME_BLOCK = """color_scheme:
  dark:
    label: "Dark"
    colors: { bg: palette.black, fg: palette.white, dim: palette.dark_gray }
  light:
    label: "Light"
    colors: { bg: palette.white, fg: palette.black, dim: palette.light_gray }

config:
  colors:
    default: color_scheme.dark
    choices:
      - color_scheme.dark
      - color_scheme.light
"""

#: Every declared role is bound somewhere, so a real `monkeyc` build never
#: warns about an unused view field -- the same reason `test_config.py`'s own
#: `CONFIG_BLOCK`/`BODY` pair binds both axes.
BODY = """elements:
  - id: bg
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: config.colors.bg
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    at: {anchor: center, dy: -20%}
    color: config.colors.fg
  - id: caption
    type: text
    text: "STEPS"
    font: FONT_XTINY
    at: {anchor: center, dy: 20%}
    color: config.colors.dim
"""

DESIGN = HEAD + SCHEME_BLOCK + BODY


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


# -- schema and IR -------------------------------------------------------------


def test_a_valid_design_builds_clean(write_design, bag):
    face = _face(DESIGN, write_design, bag)
    assert set(face.color_scheme) == {"dark", "light"}
    assert face.config_colors is not None
    assert face.config_colors.default == "dark"
    assert face.config_colors.choices == ("dark", "light")


def test_has_config_is_true_for_color_scheme_alone(write_design, bag):
    """The case CLAUDE.md's task brief calls out by name: no accent_color/
    data_color at all, only `color_scheme:`/`config: colors:`."""
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
    assert bg.color.text == "config.colors.bg"
    assert bg.color.code == "_configColorsBg"
    assert bg.color.constant is None


def test_schemes_disagreeing_on_role_set_is_an_error(write_design):
    text = HEAD + """color_scheme:
  dark:
    colors: { bg: palette.black, fg: palette.white, dim: palette.dark_gray }
  light:
    colors: { bg: palette.white, fg: palette.black }

config:
  colors:
    default: color_scheme.dark
    choices: [color_scheme.dark, color_scheme.light]
""" + BODY
    errors = _errors(text, write_design)
    assert any(d.code == "color-scheme" for d in errors), errors
    message = next(d for d in errors if d.code == "color-scheme").message
    assert "color_scheme.light" in message and "dim" in message


def test_the_scheme_with_every_role_is_not_blamed(write_design):
    """Only `light` (missing `dim`) is named -- `dark`, which has every role
    the union declares, gets no error of its own."""
    text = HEAD + """color_scheme:
  dark:
    colors: { bg: palette.black, fg: palette.white, dim: palette.dark_gray }
  light:
    colors: { bg: palette.white, fg: palette.black }

config:
  colors:
    default: color_scheme.dark
    choices: [color_scheme.dark, color_scheme.light]
""" + BODY
    errors = _errors(text, write_design)
    messages = [d.message for d in errors if d.code == "color-scheme"]
    assert len(messages) == 1
    assert "color_scheme.dark" not in messages[0]


def test_role_mismatch_does_not_cascade(write_design):
    """One error, at the real mistake -- `BODY` binds `config.colors.bg` on
    three elements, so throwing the whole axis out of scope would add an
    "unknown data source" per element, the same cascade
    `test_config.py::test_a_rejected_config_axis_does_not_cascade` exists to
    prevent."""
    text = HEAD + """color_scheme:
  dark:
    colors: { bg: palette.black, fg: palette.white, dim: palette.dark_gray }
  light:
    colors: { bg: palette.white, fg: palette.black }

config:
  colors:
    default: color_scheme.dark
    choices: [color_scheme.dark, color_scheme.light]
""" + BODY
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["color-scheme"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))


def test_config_colors_naming_an_undeclared_role_is_an_error(write_design):
    text = HEAD + SCHEME_BLOCK + """elements:
  - id: c
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%
    color: config.colors.nope
"""
    errors = _errors(text, write_design)
    assert any(d.code == "config" and "no role 'nope'" in d.message for d in errors), errors
    note = " ".join(n for d in errors for n in d.notes)
    assert "config.colors.bg" in note and "config.colors.fg" in note and "config.colors.dim" in note


def test_a_bare_config_colors_used_as_a_color_is_an_error(write_design):
    text = HEAD + SCHEME_BLOCK + """elements:
  - id: c
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%
    color: config.colors
"""
    errors = _errors(text, write_design)
    assert any(
        d.code == "config" and "is a colour scheme, not a colour" in d.message
        for d in errors
    ), errors
    note = " ".join(n for d in errors for n in d.notes)
    assert "config.colors.bg" in note


def test_default_not_among_choices_is_an_error(write_design):
    text = HEAD + """color_scheme:
  dark:
    colors: { bg: palette.black }
  light:
    colors: { bg: palette.white }

config:
  colors:
    default: color_scheme.light
    choices: [color_scheme.dark]
""" + """elements:
  - id: c
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%
    color: config.colors.bg
"""
    errors = _errors(text, write_design)
    assert any(d.code == "config" and "not one of 'choices:'" in d.message for d in errors), errors


def test_default_check_is_by_scheme_identity_not_colour_value(write_design, bag):
    """Two schemes may legitimately share a colour for one role; the
    default/choices comparison is on the scheme *name*, unlike the accent/data
    axes' colour-value comparison."""
    text = HEAD + """color_scheme:
  dark:
    colors: { bg: palette.black }
  also_dark:
    colors: { bg: palette.black }

config:
  colors:
    default: color_scheme.also_dark
    choices: [color_scheme.dark, color_scheme.also_dark]
""" + """elements:
  - id: c
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%
    color: config.colors.bg
"""
    face = _face(text, write_design, bag)
    assert face.config_colors.default == "also_dark"


def test_a_rejected_axis_default_does_not_cascade(write_design):
    text = HEAD + """color_scheme:
  dark:
    colors: { bg: palette.black }
  light:
    colors: { bg: palette.white }

config:
  colors:
    default: color_scheme.light
    choices: [color_scheme.dark]
""" + """elements:
  - id: c
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%
    color: config.colors.bg
"""
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["config"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))


def test_choices_naming_an_undeclared_scheme_is_an_error(write_design):
    text = HEAD + """color_scheme:
  dark:
    colors: { bg: palette.black }

config:
  colors:
    default: color_scheme.dark
    choices: [color_scheme.dark, color_scheme.nope]
""" + """elements:
  - id: c
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%
    color: config.colors.bg
"""
    errors = _errors(text, write_design)
    assert any(d.code == "config" and "unknown color scheme 'color_scheme.nope'" in d.message
               for d in errors), errors
    note = " ".join(n for d in errors for n in d.notes)
    assert "color_scheme.dark" in note


def test_default_naming_an_undeclared_scheme_is_an_error(write_design):
    text = HEAD + """color_scheme:
  dark:
    colors: { bg: palette.black }

config:
  colors:
    default: color_scheme.nope
    choices: [color_scheme.dark]
""" + """elements:
  - id: c
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%
    color: config.colors.bg
"""
    errors = _errors(text, write_design)
    assert any(d.code == "config" and "unknown color scheme 'color_scheme.nope'" in d.message
               for d in errors), errors


def test_a_role_colour_may_be_a_palette_reference_or_a_literal(write_design, bag):
    text = HEAD + """color_scheme:
  dark:
    colors: { bg: palette.black, accent: "#FFAA00" }

config:
  colors:
    default: color_scheme.dark
    choices: [color_scheme.dark]
""" + """elements:
  - id: c
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%
    color: config.colors.accent
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
    text = HEAD + """color_scheme:
  dark:
    colors: { bg: config.accent_color }

config:
  accent_color:
    default: "#FF8000"
    choices: any
  colors:
    default: color_scheme.dark
    choices: [color_scheme.dark]
""" + """elements:
  - id: c
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%
    color: config.colors.bg
"""
    errors = _errors(text, write_design)
    assert any(d.code == "schema" for d in errors), errors


def test_schema_widened_for_config_colors_lets_the_ir_give_the_friendly_error(write_design):
    """The schema's own `$defs/color` pattern is widened to accept
    `config.colors.<role>` (three segments), so a palette entry that
    mistakenly names one reaches `Builder._build_palette`'s domain-specific
    error rather than failing raw schema validation with no context -- the
    same treatment a two-segment `config.<axis>` reference already got.
    """
    text = HEAD.replace(
        'palette:\n  black: "#000000"',
        'palette:\n  black: config.colors.bg',
    ) + SCHEME_BLOCK + BODY
    errors = _errors(text, write_design)
    assert not any(d.code == "schema" for d in errors), errors
    assert any(d.code == "palette" for d in errors), errors
    note = " ".join(n for d in errors for n in d.notes)
    assert "color: config.accent_color" in note or "must be literal colours" in " ".join(
        d.message for d in errors if d.code == "palette")


# -- lint: config-unsupported --------------------------------------------------


def test_config_unsupported_names_every_role_on_fr955(write_design, db):
    fenix = _lint(DESIGN, write_design, db, "fenix8solar47mm")
    assert not any(d.code == "config-unsupported" for d in fenix.items), fenix.render()

    fr955 = _lint(DESIGN, write_design, db, "fr955")
    warnings = [d for d in fr955.items if d.code == "config-unsupported"]
    assert len(warnings) == 1, fr955.render()
    assert "config.colors.bg" in warnings[0].message
    assert "config.colors.fg" in warnings[0].message
    assert "config.colors.dim" in warnings[0].message


def test_config_unsupported_is_suppressible_from_any_one_referencing_element(write_design, db):
    text = DESIGN.replace(
        "    color: config.colors.dim\n",
        "    color: config.colors.dim\n"
        "    lint:\n"
        "      allow: [config-unsupported]\n"
        "      reason: \"test\"\n",
    )
    fr955 = _lint(text, write_design, db, "fr955")
    assert not any(d.code == "config-unsupported" for d in fr955.items), fr955.render()


# -- lint: palette-dither, reached through config.colors -----------------------


OFF_GRID_SCHEME = HEAD + """color_scheme:
  dark:
    colors: { bg: "#FF8000" }

config:
  colors:
    default: color_scheme.dark
    choices: [color_scheme.dark]
""" + """elements:
  - id: c
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%
    color: config.colors.bg
"""


def test_an_off_grid_role_colour_dithers(write_design, db):
    bag = _lint(OFF_GRID_SCHEME, write_design, db, "fenix8solar47mm")
    warnings = [d for d in bag.items if d.code == "palette-dither"]
    assert any("config.colors.bg" in d.message for d in warnings), bag.render()


def test_role_palette_dither_is_suppressible_on_the_referencing_element(write_design, db):
    text = OFF_GRID_SCHEME.replace(
        "    color: config.colors.bg\n",
        "    color: config.colors.bg\n"
        "    lint:\n"
        "      allow: [palette-dither]\n"
        "      reason: \"test\"\n",
    )
    bag = _lint(text, write_design, db, "fenix8solar47mm")
    warnings = [d for d in bag.items
                if d.code == "palette-dither" and "config.colors.bg" in d.message]
    assert not warnings, bag.render()


def test_a_scheme_never_listed_in_choices_is_not_checked(write_design, db, bag):
    """`unused` is a real color_scheme entry with an off-grid colour, but it
    is never in `config: colors: choices:`, so `resolveColorScheme` never
    assigns it and there is nothing on the wrist to warn about."""
    text = HEAD + """color_scheme:
  dark:
    colors: { bg: palette.black }
  unused:
    colors: { bg: "#FF8000" }

config:
  colors:
    default: color_scheme.dark
    choices: [color_scheme.dark]
""" + """elements:
  - id: c
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%
    color: config.colors.bg
"""
    face = _face(text, write_design, bag)
    assert "unused" in face.color_scheme
    lint_bag = _lint(text, write_design, db, "fenix8solar47mm")
    assert not any(d.code == "palette-dither" for d in lint_bag.items), lint_bag.render()


# -- codegen: fields, resolveColorScheme, applyConfig --------------------------


def _view(text, write_design, db, device_id="fenix8solar47mm"):
    from wfb.emit.monkeyc import emit_view
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    bag = Bag()
    face = _face(text, write_design, bag)
    device = db.get(device_id)
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    return emit_view(resolved).text


def test_the_generated_view_has_role_fields_and_resolve_color_scheme(write_design, db):
    view = _view(DESIGN, write_design, db)
    assert "private var _configColorsBg as Number = 0x000000;" in view
    assert "private var _configColorsFg as Number = 0xFFFFFF;" in view
    assert "private var _configColorsDim as Number = 0x555555;" in view
    assert "private function resolveColorScheme(style as Number) as Void" in view
    resolve_body = view.split("private function resolveColorScheme")[1].split("\n\n")[0]
    assert "if (style == 0)" in resolve_body
    assert "if (style == 1)" in resolve_body
    assert "_configColorsBg = 0xFFFFFF;" in resolve_body  # style 1 == light


def test_applyconfig_reads_styleid_and_dispatches(write_design, db):
    view = _view(DESIGN, write_design, db)
    apply_config = view.split("function applyConfig")[1].split("\n    function ")[0]
    assert "settings.styleId" in apply_config
    assert "resolveColorScheme(" in apply_config
    # range-checked, not trusted -- a rebuild with fewer schemes can leave a
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
    assert "resolveColorScheme" in view
    assert "function onLayout" in view
    on_layout = view.split("function onLayout")[1].split("\n    function ")[0]
    assert "Application has :WatchFaceConfig" in on_layout
    assert "applyConfig(settings);" in on_layout

    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    delegate = emit_delegate(resolved).text
    assert "function onWatchFaceConfigEdited" in delegate
    assert "_view.applyConfig(settings);" in delegate


def test_a_face_with_no_config_at_all_generates_no_color_scheme_code(write_design, db):
    plain = HEAD + """elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    at: {anchor: center}
    color: palette.black
"""
    view = _view(plain, write_design, db)
    assert "_configColors" not in view
    assert "resolveColorScheme" not in view
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

    text = HEAD + """color_scheme:
  dark:
    colors: { bg: palette.black }
  light:
    colors: { bg: palette.white }

config:
  colors:
    default: color_scheme.dark
    choices: [color_scheme.dark, color_scheme.light]
""" + """elements:
  - id: c
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%
    color: config.colors.bg
"""
    face = _face(text, write_design, bag)
    xml = config_resource(face)
    assert '<style id="0" default="true"/>' in xml
    assert '<style id="1"/>' in xml


def test_labelled_schemes_get_shared_strings(write_design, bag):
    from wfb.emit.resources import shared_strings

    face = _face(DESIGN, write_design, bag)
    strings = shared_strings(face)
    assert '<string id="ConfigStyle0">Dark</string>' in strings
    assert '<string id="ConfigStyle1">Light</string>' in strings


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
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    image = render(resolved)
    assert image.size == (device.width * 2, device.height * 2)


# -- the real toolchain ---------------------------------------------------------


@pytest.mark.slow
def test_a_color_scheme_design_compiles_warning_free_on_every_target(
        write_design, tmp_path, db, toolchain):  # noqa: F811
    """The bar this task and CLAUDE.md both set: real `monkeyc`, all three
    targets, warning-free (`config-unsupported` on fr955 accepted explicitly,
    the same as `examples/config/face.yaml` does for the two colour axes)."""
    from wfb.build import build as run_build

    text = DESIGN.replace(
        "    color: config.colors.dim\n",
        "    color: config.colors.dim\n"
        "    lint:\n"
        "      allow: [config-unsupported]\n"
        "      reason: \"test fixture\"\n",
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
    assert "resolveColorScheme" in view
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
        "    color: config.colors.dim\n",
        "    color: config.colors.dim\n"
        "    lint:\n"
        "      allow: [config-unsupported]\n"
        "      reason: \"test fixture\"\n",
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
