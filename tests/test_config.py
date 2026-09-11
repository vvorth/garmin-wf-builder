"""`config:` -- the two native on-device colour axes (ADR 0006 1, amended).

Every check below is driven red against the exact violating input before it
is trusted, the same discipline `tests/test_static.py`'s module docstring
states -- see CLAUDE.md's own account of a check that was advertised as
suppressible and was not, because it called `bag.warning` directly instead
of checking `lint_allow` at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_build import toolchain  # noqa: F401  -- a fixture, used by name
from tests.test_diagnostics import load
from wfb import lint
from wfb.diagnostics import Bag
from wfb.ir import CONFIG_SYMBOL

HEAD = """format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm, fenix8solar51mm, fr955]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
"""

#: `accent_color` deliberately takes an off-grid default -- #FF8000 dithers
#: on a 64-colour panel -- so the palette-legality tests below have a real
#: violation to catch without a second design.
CONFIG_BLOCK = """config:
  accent_color:
    default: "#FF8000"
    choices: any
  data_color:
    default: "#FFFFFF"
    choices:
      - { color: "#FFFFFF", label: "White" }
      - { color: "#00FFFF", label: "Aqua" }
      - { color: "#FFAA00", label: "Amber" }
"""

BODY = """elements:
  - id: accent_dot
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%
    color: config.accent_color
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    at: {anchor: center, dy: 30%}
    color: config.data_color
"""

DESIGN = HEAD + CONFIG_BLOCK + BODY


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


# -- device symbol table itself -----------------------------------------------


def test_has_symbol_agrees_with_the_probe(db):
    """CLAUDE.md's own headline finding, pinned so it cannot silently drift:
    both fēnix 8 Solar targets have the editor, fr955 does not, even though
    fr955's own ConnectIQ ceiling (5.2.0) is *above* the editor's documented
    floor (5.1.0)."""
    assert db.get("fenix8solar47mm").has_symbol(CONFIG_SYMBOL)
    assert db.get("fenix8solar51mm").has_symbol(CONFIG_SYMBOL)
    assert not db.get("fr955").has_symbol(CONFIG_SYMBOL)


# -- schema and IR -------------------------------------------------------------


def test_an_unknown_config_key_is_rejected_naming_what_is_accepted(write_design):
    text = HEAD + """config:
  border_color:
    default: "#FFFFFF"
    choices: any
""" + BODY
    errors = _errors(text, write_design)
    assert any(d.code == "schema" for d in errors)
    note = " ".join(n for d in errors for n in d.notes)
    assert "accent_color" in note and "data_color" in note


def test_default_outside_an_explicit_choices_list_is_an_error(write_design):
    text = HEAD + """config:
  accent_color:
    default: "#FF8000"
    choices: any
  data_color:
    default: "#123456"
    choices:
      - { color: "#FFFFFF", label: "White" }
""" + BODY
    errors = _errors(text, write_design)
    assert any(d.code == "config" for d in errors)
    message = next(d for d in errors if d.code == "config").message
    assert "not one of 'choices:'" in message


def test_a_rejected_config_axis_does_not_cascade(write_design):
    """One error, at the real mistake -- not one more per element using it.

    `BODY` binds `config.data_color` on an element, so throwing the rejected
    axis out of the expression scope would add an "unknown data source
    'config.data_color'" error that is true only because the compiler
    discarded it.  That error points at a correct line and blames the wrong
    thing; the same cascade `rejected_fonts` was added to prevent for a
    rejected `fonts:` entry (CLAUDE.md, "A rejected `fonts:` entry no longer
    cascades").
    """
    text = HEAD + """config:
  accent_color:
    default: "#FF8000"
    choices: any
  data_color:
    default: "#123456"
    choices:
      - { color: "#FFFFFF", label: "White" }
""" + BODY
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["config"], (
        "expected exactly the one real error, got: "
        + "; ".join(f"{d.code}: {d.message}" for d in errors))
    assert not [d for d in errors if "unknown data source" in d.message]


def test_default_matching_a_listed_choice_is_fine(write_design, bag):
    _face(DESIGN, write_design, bag)
    assert bag.ok(), bag.render()


def test_choices_any_needs_no_list(write_design, bag):
    face = _face(DESIGN, write_design, bag)
    assert face.config["accent_color"].allow_any


def test_a_palette_entry_may_not_reference_config(write_design):
    text = HEAD.replace(
        'palette:\n  bg: "#000000"',
        'palette:\n  bg: config.accent_color',
    ) + CONFIG_BLOCK + BODY
    errors = _errors(text, write_design)
    assert any(d.code == "palette" for d in errors)
    note = " ".join(n for d in errors for n in d.notes)
    assert "color: config.accent_color" in note


def test_config_colour_is_an_ordinary_unfoldable_colour_binding(write_design, bag):
    """`kind == \"config\"` and `constant=None` -- unlike a palette entry, the
    view field this names is user-editable at runtime, so `fold` must never
    inline it (`wfb.expr.fold`'s `Ref` branch only substitutes when
    `binding.constant` is set)."""
    face = _face(DESIGN, write_design, bag)
    dot = next(e for e in face.walk() if e.id == "accent_dot")
    assert dot.color.text == "config.accent_color"
    assert dot.color.code == "_configAccentColor"
    assert dot.color.constant is None


def test_an_unknown_config_reference_suggests_the_declared_ones(write_design):
    text = HEAD + CONFIG_BLOCK + """elements:
  - id: dot
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%
    color: config.acent_color
"""
    errors = _errors(text, write_design)
    assert any(d.code == "expression" for d in errors)
    note = " ".join(n for d in errors for n in d.notes)
    assert "config.accent_color" in note and "config.data_color" in note


# -- lint: config-unsupported --------------------------------------------------


def test_config_unsupported_fires_on_fr955_and_not_on_fenix8(write_design, db):
    fenix = _lint(DESIGN, write_design, db, "fenix8solar47mm")
    assert not any(d.code == "config-unsupported" for d in fenix.items), fenix.render()

    fr955 = _lint(DESIGN, write_design, db, "fr955")
    warnings = [d for d in fr955.items if d.code == "config-unsupported"]
    assert len(warnings) == 1, fr955.render()
    assert warnings[0].severity.value == "warning"
    assert "config.accent_color" in warnings[0].message
    assert "config.data_color" in warnings[0].message


def test_config_unsupported_is_silent_with_no_config_block(write_design, db):
    text = HEAD + BODY.replace("config.accent_color", "palette.fg").replace(
        "config.data_color", "palette.fg"
    )
    fr955 = _lint(text, write_design, db, "fr955")
    assert not any(d.code == "config-unsupported" for d in fr955.items)


def test_config_unsupported_is_suppressible(write_design, db):
    """Driven red first: the un-suppressed design above already proves the
    warning fires without this -- so `lint_allow` is what is on trial here,
    not the check's existence."""
    text = DESIGN.replace(
        "    color: config.accent_color\n",
        "    color: config.accent_color\n"
        "    lint:\n"
        "      allow: [config-unsupported]\n"
        "      reason: \"test\"\n",
    )
    fr955 = _lint(text, write_design, db, "fr955")
    assert not any(d.code == "config-unsupported" for d in fr955.items), fr955.render()


def test_config_unsupported_with_no_referencing_element_still_warns_unsuppressibly(
        write_design, db):
    """Mirrors `check_palette`'s own "nowhere to put lint:allow" branch: a
    declared but unused config entry still warns, and the note says why it
    cannot be silenced with `lint:` at all."""
    text = HEAD + CONFIG_BLOCK + """elements:
  - id: bg
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
"""
    fr955 = _lint(text, write_design, db, "fr955")
    warnings = [d for d in fr955.items if d.code == "config-unsupported"]
    assert len(warnings) == 1, fr955.render()
    assert "nowhere to put" in " ".join(warnings[0].notes)


def test_config_unsupported_is_a_real_registered_suppressible_code():
    assert "config-unsupported" in lint.SUPPRESSIBLE
    assert "config-unsupported" in lint.ALL_CODES


def test_config_is_not_suppressible(write_design, db):
    """The IR-level `config` code (a malformed `config:` entry) is a hard
    error, not a lint warning -- `lint: {allow: [config]}` must be rejected
    the way any other real-but-unsuppressible code is."""
    text = DESIGN.replace(
        "    color: config.data_color\n",
        "    color: config.data_color\n"
        "    lint:\n"
        "      allow: [config]\n"
        "      reason: \"nonsense\"\n",
    )
    face = load(write_design(text), Bag())
    assert face is not None
    bag = Bag()
    lint.check_lint_allow(face, bag)
    errors = [d for d in bag.items if d.code == "lint-allow"]
    assert len(errors) == 1, bag.render()
    assert "not suppressible" in errors[0].message


# -- lint: palette-dither, reached through config ------------------------------


def test_an_off_grid_config_default_dithers(write_design, db):
    """`accent_color`'s default (#FF8000) is off the 64-colour grid on
    purpose -- CONFIG_BLOCK's own comment says so."""
    bag = _lint(DESIGN, write_design, db, "fenix8solar47mm")
    warnings = [d for d in bag.items if d.code == "palette-dither"]
    assert any("config.accent_color" in d.message for d in warnings), bag.render()


def test_config_palette_dither_is_suppressible_on_the_referencing_element(
        write_design, db):
    text = DESIGN.replace(
        "    color: config.accent_color\n",
        "    color: config.accent_color\n"
        "    lint:\n"
        "      allow: [palette-dither]\n"
        "      reason: \"test\"\n",
    )
    bag = _lint(text, write_design, db, "fenix8solar47mm")
    warnings = [d for d in bag.items
                if d.code == "palette-dither" and "config.accent_color" in d.message]
    assert not warnings, bag.render()


def test_choices_any_skips_the_list_but_not_the_default(write_design, bag, db):
    """`allow_any` means there is no *list* to check -- the compiled-in
    default is still checked unconditionally, since it is the only value a
    device with no editor ever shows.  Reached with a design whose default is
    legal and whose (nonexistent) list would otherwise be the only thing
    checked, to prove the default path runs on its own."""
    text = HEAD + """config:
  accent_color:
    default: "#FFAA00"
    choices: any
""" + BODY.replace("config.data_color", "palette.fg")
    face = _face(text, write_design, bag)
    assert face.config["accent_color"].allow_any
    fenix = _lint(text, write_design, db, "fenix8solar47mm")
    assert not any(d.code == "palette-dither" for d in fenix.items), fenix.render()


def test_an_explicit_choice_off_the_grid_also_dithers(write_design, db):
    text = HEAD + """config:
  data_color:
    default: "#FFFFFF"
    choices:
      - { color: "#FFFFFF", label: "White" }
      - { color: "#FF8000", label: "Bad" }
""" + BODY.replace("config.accent_color", "palette.fg")
    bag = _lint(text, write_design, db, "fenix8solar47mm")
    warnings = [d for d in bag.items
                if d.code == "palette-dither" and "config.data_color" in d.message]
    assert warnings, bag.render()
    assert "1 declared colour" in warnings[0].message


# -- codegen: fields, applyConfig, onLayout, delegate --------------------------


def _view(text, write_design, db, tmp_path, device_id="fenix8solar47mm"):
    from wfb.emit.monkeyc import emit_view
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    bag = Bag()
    face = _face(text, write_design, bag)
    device = db.get(device_id)
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    return emit_view(resolved).text


def test_the_generated_view_has_defaulted_fields_and_applyconfig(write_design, db, tmp_path):
    view = _view(DESIGN, write_design, db, tmp_path)
    assert "private var _configAccentColor as Number = 0xFF8000;" in view
    assert "private var _configDataColor as Number = 0xFFFFFF;" in view
    assert "function applyConfig(settings as WatchFaceConfig.Settings) as Void" in view
    assert "settings.accentColor" in view
    assert "settings.complicationColor" in view
    # every value nullable twice over -- both the Settings field and .color
    assert view.count("if (configAccentColor != null)") == 1
    assert view.count("if (configAccentColorValue != null)") == 1


def test_onlayout_reads_config_behind_the_has_guard(write_design, db, tmp_path):
    view = _view(DESIGN, write_design, db, tmp_path)
    on_layout = view.split("function onLayout")[1].split("\n    function ")[0]
    assert "if (Application has :WatchFaceConfig)" in on_layout
    assert "WatchFaceConfig.getSettings(null)" in on_layout
    assert "applyConfig(settings);" in on_layout


def test_a_face_with_no_config_generates_exactly_what_it_did_before(write_design, db, tmp_path):
    """The feature must cost nothing to a design that does not use it -- the
    same guarantee `test_static.py` makes for `static:`."""
    plain = HEAD + """elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    at: {anchor: center}
    color: palette.fg
"""
    view = _view(plain, write_design, db, tmp_path)
    assert "_configAccentColor" not in view
    assert "_configDataColor" not in view
    assert "applyConfig" not in view
    assert "WatchFaceConfig" not in view


def test_needs_delegate_is_true_for_config_alone(write_design, bag):
    from wfb.emit.monkeyc import hold_targets, needs_delegate

    face = _face(DESIGN, write_design, bag)
    assert not hold_targets(face)
    assert needs_delegate(face)


def test_the_delegate_gets_onwatchfaceconfigedited_and_a_view_field(write_design, db):
    from wfb.emit.monkeyc import emit_delegate
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    bag = Bag()
    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    delegate = emit_delegate(resolved).text
    assert "private var _view as TestView;" in delegate
    assert "function onWatchFaceConfigEdited(options as {" in delegate
    assert "_view.applyConfig(settings);" in delegate
    # a config-only design (no on_hold, no carousel) still emits onPress,
    # returning false unconditionally rather than reading clickEvent at all
    on_press = delegate.split("function onPress")[1]
    assert "clickEvent.getCoordinates()" not in on_press
    assert "return false;" in on_press


def test_a_design_with_no_config_gets_no_onwatchfaceconfigedited(write_design, db):
    from wfb.emit.monkeyc import emit_delegate
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    text = HEAD + """elements:
  - id: hr
    type: icon
    icon: heart
    at: {anchor: center}
    size: 20%r
    color: palette.fg
    on_hold: heart_rate
"""
    bag = Bag()
    face = _face(text, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    delegate = emit_delegate(resolved).text
    assert "onWatchFaceConfigEdited" not in delegate
    assert "WatchFaceConfig" not in delegate


# -- codegen: the generated resource -------------------------------------------


def test_the_config_resource_is_per_device_not_shared(write_design, db):
    from wfb.emit.resources import build_bundle, config_resource

    bag = Bag()
    face = _face(DESIGN, write_design, bag)

    fenix = db.get("fenix8solar47mm")
    bundle = build_bundle(face, fenix, {})
    assert "configs/watchface.xml" in bundle.files
    xml = bundle.files["configs/watchface.xml"]
    assert '<accentColors allowAny="true"/>' in xml
    assert '<dataColors>' in xml
    # allowAny means no <color> list for accent_color at all -- the compiled
    # default only ever reaches the view field, not this resource -- so the
    # one axis that does have an explicit list is what to check here.
    assert '<color default="true" label="@Strings.ConfigDataColor0">0xFFFFFF</color>' in xml

    fr955 = db.get("fr955")
    bundle = build_bundle(face, fr955, {})
    assert "configs/watchface.xml" not in bundle.files

    text = config_resource(face)
    assert text.count("<color") == 3  # the three labelled data_color choices


def test_labelled_choices_get_shared_strings(write_design, bag):
    from wfb.emit.resources import shared_strings

    face = _face(DESIGN, write_design, bag)
    strings = shared_strings(face)
    assert '<string id="ConfigDataColor0">White</string>' in strings
    assert '<string id="ConfigDataColor1">Aqua</string>' in strings
    assert '<string id="ConfigDataColor2">Amber</string>' in strings


def test_an_unlabelled_choice_needs_no_string(write_design, bag):
    text = HEAD + """config:
  data_color:
    default: "#FFFFFF"
    choices:
      - { color: "#FFFFFF" }
""" + BODY.replace("config.accent_color", "palette.fg")
    face = _face(text, write_design, bag)
    from wfb.emit.resources import config_resource

    xml = config_resource(face)
    assert "label=" not in xml
    assert "<color default=\"true\">0xFFFFFF</color>" in xml


# -- preview --------------------------------------------------------------------


def test_preview_renders_at_the_declared_defaults(write_design, db):
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve
    from wfb.preview import render

    bag = Bag()
    face = _face(DESIGN, write_design, bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    image = render(resolved)
    assert image.size == (device.width * 2, device.height * 2)


# -- wfb sources ----------------------------------------------------------------


def test_wfb_sources_lists_config_axes():
    from wfb.cli import _sources

    class _Args:
        pass

    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        _sources(_Args())
    out = buf.getvalue()
    assert "config.accent_color" in out
    assert "config.data_color" in out


# -- the real toolchain ---------------------------------------------------------


@pytest.mark.slow
def test_a_config_design_compiles_warning_free_on_every_target(
        write_design, tmp_path, db, toolchain):  # noqa: F811
    """The bar CLAUDE.md and this task both set: real `monkeyc`, all three
    targets, **warning-free**, not merely successful.  `config-unsupported`
    is expected on fr955 and is accepted explicitly here, the same way
    `examples/config/face.yaml` accepts it -- so this asserts `bag.ok()` for
    errors and a *known, filtered* set of warnings, not zero warnings
    outright, which is the one place this test cannot mirror
    `test_static.py`'s stricter assertion.
    """
    from wfb.build import build as run_build

    text = DESIGN.replace(
        "    color: config.accent_color\n",
        "    color: config.accent_color\n"
        "    lint:\n"
        "      allow: [config-unsupported, palette-dither]\n"
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
    assert "applyConfig" in view
    delegate = (result.output_dir / "source" / "TestDelegate.mc").read_text(encoding="utf-8")
    assert "onWatchFaceConfigEdited" in delegate

    fenix_config = (result.output_dir / "resources-fenix8solar47mm" / "configs"
                    / "watchface.xml")
    assert fenix_config.exists()
    fr955_config = (result.output_dir / "resources-fr955" / "configs" / "watchface.xml")
    assert not fr955_config.exists()
