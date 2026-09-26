"""`settings:` -- wearer settings stored as `Application.Properties`: the
block, `settings.<name>` in expressions, the generated properties/view/app
code, the on-watch settings menu (`edit: [watch]`), and the preview's
`--set`."""

from __future__ import annotations

import pytest

from wfb import expr
from wfb.build import build as real_build
from wfb.catalog import Type
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, SettingOverrideError, parse_settings, render
from tests.helpers import lint_text, load_errors, load_face, run_cli

HEAD = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Settings
targets: [fenix8solar47mm, fr955]
palette:
  fg: "#FFFFFF"
"""

SETTINGS = """
settings:
  show_dot:
    label: "Show dot"
    type: boolean
    default: true
  side:
    label: "Dot side"
    type: choice
    choices: { left: "Left", right: "Right", top: "Top" }
    default: left
"""

#: Three discs, each shown by a different setting read: the contrast the
#: preview and codegen tests below rely on.
ELEMENTS = """
elements:
  - id: centre
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 10%r
    filled: true
    color: palette.fg
    visible: settings.show_dot
  - id: left_dot
    type: shape
    shape: circle
    at: {anchor: center, dx: -50%r}
    radius: 10%r
    filled: true
    color: palette.fg
    visible: settings.side == "left"
  - id: right_dot
    type: shape
    shape: circle
    at: {anchor: center, dx: 50%r}
    radius: 10%r
    filled: true
    color: palette.fg
    visible: '"right" == settings.side'
"""

DESIGN = HEAD + SETTINGS + ELEMENTS


def _visible_code(face, element_id: str) -> str:
    element = next(e for e in face.walk() if e.id == element_id)
    assert element.visible is not None
    return element.visible.code


# --------------------------------------------------------------------------
# the IR and expressions


def test_settings_build_into_the_face(write_design, bag):
    face = load_face(DESIGN, write_design, bag)
    show, side = face.settings["show_dot"], face.settings["side"]
    assert (show.type, show.default, show.stored_default) == ("boolean", True, True)
    assert side.keys == ("left", "right", "top")
    assert (side.default, side.stored_default) == ("left", 0)
    assert show.field == "_settingShowDot"


def test_a_boolean_setting_reads_its_field(write_design, bag):
    face = load_face(DESIGN, write_design, bag)
    assert _visible_code(face, "centre") == "_settingShowDot"


def test_a_choice_compares_its_index_either_way_round(write_design, bag):
    face = load_face(DESIGN, write_design, bag)
    assert _visible_code(face, "left_dot") == "(_settingSide == 0)"
    assert _visible_code(face, "right_dot") == "(_settingSide == 1)"


def test_a_setting_is_not_a_data_source_and_never_folds(write_design, bag):
    face = load_face(DESIGN, write_design, bag)
    element = next(e for e in face.walk() if e.id == "centre")
    assert element.visible is not None
    assert element.visible.sources == ()
    assert element.visible.constant is None


def test_a_choice_compare_keeps_its_key_for_the_host():
    """The tree keeps the key, so `evaluate` compares keys on the host while
    `emit` compares the index on the device -- the two must agree."""
    scope = expr.Scope()
    scope.define("settings.side", expr.Binding(
        expr.Value(Type.STRING), code="_settingSide", choices=("left", "right")))
    code, value, node = expr.compile_expression('settings.side != "right"', scope)
    assert (code, value.type) == ("(_settingSide != 1)", Type.BOOLEAN)
    assert expr.evaluate(node, {"settings.side": "right"}) is False
    assert expr.evaluate(node, {"settings.side": "left"}) is True


@pytest.mark.parametrize("visible, message", [
    ("settings.side", "is a choice, so it can only be compared with one of its keys"),
    ('settings.side == "middle"', "settings.side has no choice 'middle'"),
    ("settings.side == 1", "compare it with one of its keys as a quoted string"),
    ('settings.side < "left"', "can only be compared with == or !="),
    ("settings.show_dott", "unknown data source 'settings.show_dott'"),
])
def test_a_misused_setting_is_one_error_on_its_line(write_design, visible, message):
    text = DESIGN.replace('visible: settings.side == "left"', f"visible: '{visible}'")
    errors = load_errors(text, write_design)
    assert len(errors) == 1, [e.message for e in errors]
    assert message in errors[0].message


def test_a_misspelled_key_is_suggested(write_design):
    text = DESIGN.replace('settings.side == "left"', 'settings.side == "lft"')
    (error,) = load_errors(text, write_design)
    assert any('"left"' in note for note in error.notes), error.notes


def test_a_setting_read_without_a_settings_block_says_so(write_design):
    """Each read is its own mistake here: there is no block to blame."""
    errors = load_errors(HEAD + ELEMENTS, write_design)
    assert [e.message.split(": ", 1)[1] for e in errors] == [
        "unknown setting 'settings.show_dot'",
        "unknown setting 'settings.side'",
        "unknown setting 'settings.side'",
    ]
    assert all(any("'settings:'" in note for note in e.notes) for e in errors)


def test_a_default_that_is_not_a_choice_is_one_error_not_n(write_design):
    """The rejected setting stays bound, so the two elements reading it get
    no second error each (`docs/lore/codegen.md`)."""
    text = DESIGN.replace("    default: left\n", "    default: middle\n")
    (error,) = load_errors(text, write_design)
    assert error.code == "settings"
    assert "settings.side: default 'middle' is not one of 'choices:'" in error.message


def test_two_names_for_one_field_are_rejected(write_design):
    text = DESIGN.replace("settings:\n", """settings:
  showDot:
    label: "Other"
    type: boolean
    default: false
""")
    (error,) = load_errors(text, write_design)
    assert "the same generated name as settings.showDot" in error.message


@pytest.mark.parametrize("entry, where", [
    ('    type: boolean\n    default: true\n', "label"),
    ('    label: "X"\n    type: choice\n    choices: {a: "A"}\n    default: a\n', "choices"),
    ('    label: "X"\n    type: boolean\n    default: "yes"\n', "default"),
])
def test_the_schema_checks_a_setting_s_shape(write_design, entry, where):
    errors = load_errors(HEAD + "settings:\n  bad:\n" + entry, write_design)
    assert errors and all(e.code == "schema" for e in errors), [e.message for e in errors]
    assert any(where in e.message for e in errors), [e.message for e in errors]


# --------------------------------------------------------------------------
# generated code


def _project(write_design, db, text: str = DESIGN):
    bag = Bag()
    face = load_face(text, write_design, bag)
    devices = [db.get(d) for d in face.targets]
    out = write_design(text).parent / "out"
    return generate(face, devices, out, {d.id: bake_fonts(face, d) for d in devices})


def test_properties_xml_stores_each_default(write_design, db):
    files = _project(write_design, db).files()
    xml = files["resources/settings/properties.xml"]
    assert '<property id="show_dot" type="boolean">true</property>' in xml
    assert '<property id="side" type="number">0</property>' in xml
    assert "<!-- settings.side: 0 = left, 1 = right, 2 = top -->" in xml


def test_the_view_reads_every_setting_with_a_type_check(write_design, db):
    files = _project(write_design, db).files()
    view = files["source/SettingsView.mc"]
    assert "private var _settingShowDot as Boolean = true;" in view
    assert "private var _settingSide as Number = 0;  // left" in view
    assert "function applySettings() as Void" in view
    assert 'Application.Properties.getValue("show_dot")' in view
    assert "(settingsShowDot instanceof Boolean) ? settingsShowDot : true" in view
    assert "settingsSide instanceof Number && settingsSide >= 0 && settingsSide < 3" in view
    assert "import Toybox.Application;" in view
    # The constructor reads them before the first frame.
    init = view[view.index("function initialize()"):]
    assert init.index("applySettings();") < init.index("}")


def test_the_app_forwards_on_settings_changed_to_the_view(write_design, db):
    app = _project(write_design, db).files()["source/SettingsApp.mc"]
    assert "private var _view as SettingsView?;" in app
    assert "_view = view;" in app
    assert "function onSettingsChanged() as Void" in app
    assert "view.applySettings();" in app


def test_a_face_without_settings_generates_none_of_it(write_design, db, minimal):
    files = _project(write_design, db, minimal).files()
    assert "resources/settings/properties.xml" not in files
    assert "applySettings" not in files["source/TestView.mc"]
    app = files["source/TestApp.mc"]
    assert "onSettingsChanged" not in app and "_view" not in app


def test_a_setting_in_static_content_repaints_the_buffer(write_design, db):
    text = DESIGN.replace("    visible: settings.show_dot\n",
                          "    visible: settings.show_dot\n    static: true\n")
    view = _project(write_design, db, text).files()["source/SettingsView.mc"]
    apply = view[view.index("function applySettings()"):]
    apply = apply[:apply.index("\n    }\n")]
    assert "repaintStatic();" in apply
    assert "private function repaintStatic() as Void" in view


# --------------------------------------------------------------------------
# the on-watch settings menu


def _menu_part(view: str) -> str:
    start = view.index("function settingsMenu()")
    return view[start:view.index("function onLayout(")]


def test_the_menu_is_built_by_default(write_design, db, bag):
    assert load_face(DESIGN, write_design, bag).settings_menu
    files = _project(write_design, db).files()
    menu = _menu_part(files["source/SettingsView.mc"])
    assert 'new WatchUi.Menu2({ :title => "Settings" })' in menu
    # A boolean is a toggle showing its field; a choice a MenuItem whose
    # sub-label is the current choice.  Identifiers are declaration positions.
    assert ('menu.addItem(new WatchUi.ToggleMenuItem("Show dot", null, 0, '
            "_settingShowDot, null));") in menu
    assert ('menu.addItem(new WatchUi.MenuItem("Dot side", '
            "settingLabelSide(_settingSide), 1, null));") in menu


def test_selecting_stores_the_value_and_applies_it(write_design, db):
    menu = _menu_part(_project(write_design, db).files()["source/SettingsView.mc"])
    select = menu[menu.index("function selectSetting("):menu.index("private function settingLabelSide")]
    assert "if (id == 0 && item instanceof WatchUi.ToggleMenuItem)" in select
    assert 'Application.Properties.setValue("show_dot", item.isEnabled());' in select
    # A choice cycles through all three choices, wrapping.
    assert "var next = (_settingSide + 1) % 3;" in select
    assert 'Application.Properties.setValue("side", next);' in select
    assert "item.setSubLabel(settingLabelSide(next));" in select
    # Then the same path a Garmin Connect push takes.
    assert select.index("applySettings();") > select.index("setSubLabel")


def test_a_choice_label_method_maps_every_index(write_design, db):
    menu = _menu_part(_project(write_design, db).files()["source/SettingsView.mc"])
    labels = menu[menu.index("private function settingLabelSide"):]
    assert 'if (index == 1) {\n            return "Right";' in labels
    assert 'if (index == 2) {\n            return "Top";' in labels
    assert labels.index('return "Left";') > labels.index('return "Top";')


def test_the_app_opens_the_menu_through_the_delegate(write_design, db):
    files = _project(write_design, db).files()
    app = files["source/SettingsApp.mc"]
    assert "function getSettingsView() as [Views] or [Views, InputDelegates] or Null" in app
    assert "view = new SettingsView();" in app
    assert "return [ view.settingsMenu(), new SettingsSettingsDelegate(view) ];" in app
    delegate = files["source/SettingsSettingsDelegate.mc"]
    assert "class SettingsSettingsDelegate extends WatchUi.Menu2InputDelegate" in delegate
    assert "_view.selectSetting(item);" in delegate


PHONE = DESIGN.replace("settings:\n", "settings:\n  edit: [watch, phone]\n")


def test_edit_phone_describes_every_setting_for_garmin_connect(write_design, db):
    files = _project(write_design, db, PHONE).files()
    xml = files["resources/settings/settings.xml"]
    assert ('<setting propertyKey="@Properties.show_dot" '
            'title="@Strings.SettingShowDotTitle">\n'
            '        <settingConfig type="boolean" />') in xml
    # A choice is a list whose values are the indices properties.xml stores.
    assert ('        <settingConfig type="list">\n'
            '            <listEntry value="0">@Strings.SettingSide0</listEntry>\n'
            '            <listEntry value="1">@Strings.SettingSide1</listEntry>\n'
            '            <listEntry value="2">@Strings.SettingSide2</listEntry>\n') in xml
    strings = files["resources/strings/strings.xml"]
    for string_id, text in [("SettingShowDotTitle", "Show dot"), ("SettingSideTitle", "Dot side"),
                            ("SettingSide0", "Left"), ("SettingSide2", "Top")]:
        assert f'<string id="{string_id}">{text}</string>' in strings


def test_no_settings_xml_without_edit_phone(write_design, db):
    files = _project(write_design, db).files()
    assert "resources/settings/settings.xml" not in files
    assert "SettingShowDotTitle" not in files["resources/strings/strings.xml"]


def test_edit_phone_alone_has_no_menu_and_says_so(write_design, db, bag):
    text = DESIGN.replace("settings:\n", "settings:\n  edit: [phone]\n")
    face = load_face(text, write_design, bag)
    assert face.settings_phone and not face.settings_menu
    (note,) = [d for d in bag.items if d.code == "settings"]
    assert note.severity.value == "note"
    assert "nothing can change these settings" in note.message
    files = _project(write_design, db, text).files()
    assert "resources/settings/settings.xml" in files
    assert "getSettingsView" not in files["source/SettingsApp.mc"]


def test_edit_watch_and_phone_gives_no_note(write_design, bag):
    load_face(PHONE, write_design, bag)
    assert not [d for d in bag.items if d.code == "settings"]


def test_edit_alone_is_an_error(write_design):
    elements = "elements:\n  - {id: dot, type: shape, shape: circle, radius: 10%r, color: palette.fg}\n"
    (error,) = load_errors(HEAD + "settings:\n  edit: [watch]\n" + elements, write_design)
    assert "declares 'edit:' but no setting" in error.message


def test_edit_watch_is_the_default_spelled_out(write_design, db):
    explicit = DESIGN.replace("settings:\n", "settings:\n  edit: [watch]\n")
    assert _project(write_design, db, explicit).files() == _project(write_design, db).files()


def test_no_menu_without_settings(write_design, db, minimal):
    files = _project(write_design, db, minimal).files()
    assert not any("SettingsDelegate" in path for path in files)
    assert "getSettingsView" not in files["source/TestApp.mc"]


def test_a_face_with_complication_slots_builds_its_view_with_edit_mode(write_design, db):
    text = DESIGN + SLOT_ELEMENT
    text = text.replace("settings:\n", SLOT_CONFIG + "settings:\n")
    app = _project(write_design, db, text).files()["source/SettingsApp.mc"]
    assert "view = new SettingsView(_editMode);" in app


SLOT_CONFIG = """config:
  data:
    top: { default: complication.steps, choices: any }
"""
SLOT_ELEMENT = """  - id: top_reading
    type: complication_slot
    slot: config.data.top
    at: {anchor: center, dy: -30%}
    color: palette.fg
    when_absent: placeholder
    placeholder: "--"
    lint: {allow: [config-unsupported], reason: "fr955 has no native editor"}
"""


def test_a_device_without_get_settings_view_gets_a_note(write_design, db):
    if "fenix5" not in db.ids():
        pytest.skip("fenix5 is not installed")
    bag = lint_text(DESIGN, write_design, db, "fenix5")
    (note,) = [d for d in bag.items if d.code == "settings-menu-unsupported"]
    assert note.severity.value == "note"
    assert "fenix5 has no AppBase.getSettingsView" in note.message
    assert "settings.show_dot, settings.side keep their defaults" in note.message
    fr955 = lint_text(DESIGN, write_design, db, "fr955")
    assert not [d for d in fr955.items if d.code == "settings-menu-unsupported"]


# --------------------------------------------------------------------------
# preview


def _lit(image, x: int, y: int) -> bool:
    return sum(image.getpixel((x, y))[:3]) > 300


def _dots(write_design, db, settings=None) -> tuple[bool, bool, bool]:
    bag = Bag()
    face = load_face(DESIGN, write_design, bag)
    device = db.get("fr955")
    resolved = resolve(face, device, bake_fonts(face, device))
    image = render(resolved, PreviewOptions(scale=1, settings=settings))
    cx, cy, r = device.width // 2, device.height // 2, min(device.width, device.height) // 2
    return (_lit(image, cx - r // 2, cy), _lit(image, cx, cy), _lit(image, cx + r // 2, cy))


def test_the_preview_renders_the_defaults(write_design, db):
    assert _dots(write_design, db) == (True, True, False)


def test_set_overrides_a_boolean_and_a_choice(write_design, db):
    assert _dots(write_design, db, {"show_dot": False, "side": "right"}) == (False, False, True)
    assert _dots(write_design, db, {"side": "top"}) == (False, True, False)


def test_parse_settings_checks_names_and_values(write_design, bag):
    face = load_face(DESIGN, write_design, bag)
    assert parse_settings(face, ["show_dot=FALSE", "side=top"]) == {
        "show_dot": False, "side": "top"}
    for bad, message in [("show_dot", "expected NAME=VALUE"),
                         ("nope=1", "no such setting"),
                         ("show_dot=maybe", "expected true or false"),
                         ("side=middle", "expected one of left, right, top")]:
        with pytest.raises(SettingOverrideError, match=message):
            parse_settings(face, [bad])


def test_wfb_preview_set_flag(write_design, tmp_path):
    path = write_design(DESIGN)
    result = run_cli("preview", str(path), "-d", "fr955", "-o", str(tmp_path / "p"),
                     "-q", "--set", "side=up")
    assert result.returncode == 1
    assert "--set side: expected one of left, right, top, got 'up'" in result.stderr
    result = run_cli("preview", str(path), "-d", "fr955", "-o", str(tmp_path / "p"),
                     "-q", "--set", "side=top")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "p" / "fr955.png").exists()


# --------------------------------------------------------------------------
# the real compiler


@pytest.mark.slow
@pytest.mark.parametrize("targets, slots, phone", [
    ("[fenix8solar47mm, fr955]", False, False),
    ("[fenix5]", False, True),
    ("[fenix8solar47mm, fr955]", True, True),
])
def test_settings_compile_warning_free(write_design, db, tmp_path, toolchain, targets, slots,
                                       phone):
    """The type-checked reads (`instanceof` narrowing inside `&&` and a
    ternary) and the menu's `MenuItem` handling are only proven by `monkeyc`
    itself; `fenix5` is the 3.1.0 floor and has no `getSettingsView`, and a
    design with complication slots constructs its view with `_editMode`."""
    if "fenix5" in targets and "fenix5" not in db.ids():
        pytest.skip("fenix5 is not installed")
    text = DESIGN.replace("targets: [fenix8solar47mm, fr955]", f"targets: {targets}")
    if slots:
        text = text.replace("settings:\n", SLOT_CONFIG + "settings:\n") + SLOT_ELEMENT
    if phone:
        text = text.replace("settings:\n", "settings:\n  edit: [watch, phone]\n")
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, "\n".join(d.message for d in warnings)


@pytest.mark.slow
def test_settings_xml_matches_monkeyc_s_own_settings_json(write_design, db, tmp_path, toolchain):
    """`monkeyc` writes `<prg>-settings.json`, what the Store and Garmin
    Connect read: the settings must come out as declared."""
    import json

    bag = Bag()
    text = PHONE.replace("targets: [fenix8solar47mm, fr955]", "targets: [fr955]")
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None and bag.ok(), bag.render()
    prg = result.products["fr955"]
    data = json.loads(prg.with_name(prg.stem + "-settings.json").read_text())
    by_key = {entry["key"]: entry for entry in data["settings"]}
    assert (by_key["show_dot"]["valueType"], by_key["show_dot"]["configType"],
            by_key["show_dot"]["defaultValue"]) == ("boolean", "boolean", True)
    side = by_key["side"]
    assert (side["valueType"], side["configType"], side["defaultValue"]) == ("number", "list", 0)
    assert [o["value"] for o in side["configOptions"]] == [0, 1, 2]
    (strings,) = data["languages"].values()
    assert [strings[o["display"]] for o in side["configOptions"]] == ["Left", "Right", "Top"]
    assert strings[side["configTitle"]] == "Dot side"


# --------------------------------------------------------------------------
# color_scheme settings

SCHEMES = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Schemes
targets: [fenix8solar47mm, fr955]
palette:
  white: "#FFFFFF"
  orange: "#FF5500"
  red: "#FF0000"
color_scheme:
  day: { label: "Day", colors: { fg: palette.white, accent: palette.orange } }
  night: { colors: { fg: palette.red, accent: palette.red } }
settings:
  theme:
    label: "Colours"
    type: color_scheme
    choices: [day, night]
    default: day
elements:
  - id: disc
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 30%r
    filled: true
    color: settings.theme.fg
  - id: dot
    type: shape
    shape: circle
    at: {anchor: center, dy: 60%r}
    radius: 8%r
    filled: true
    color: settings.theme.accent
    static: true
"""


def test_a_scheme_setting_picks_among_declared_schemes(write_design, bag):
    face = load_face(SCHEMES, write_design, bag)
    theme = face.settings["theme"]
    assert theme.type == "color_scheme"
    # A scheme's own label, or its name when it has none.
    assert [(c.key, c.label) for c in theme.choices] == [("day", "Day"), ("night", "night")]
    assert theme.stored_default == 0


def test_a_scheme_setting_is_read_one_role_at_a_time(write_design, bag):
    face = load_face(SCHEMES, write_design, bag)
    disc = next(e for e in face.walk() if e.id == "disc")
    assert disc.color is not None
    assert (disc.color.code, disc.color.value.type, disc.color.constant) == (
        "_settingThemeFg", Type.COLOR, None)


@pytest.mark.parametrize("color, message", [
    ("settings.theme", "settings.theme is a colour scheme, not a colour"),
    ("settings.theme.bg", "settings.theme has no role 'bg'"),
])
def test_a_scheme_setting_misread_is_one_error(write_design, color, message):
    (error,) = load_errors(SCHEMES.replace("color: settings.theme.fg", f"color: {color}"),
                           write_design)
    assert error.code == "settings"
    assert message in error.message
    assert "settings.theme.accent, settings.theme.fg" in error.notes[0]


def test_an_unknown_scheme_is_one_error_not_n(write_design):
    """Both elements read the rejected setting's roles: no second error."""
    (error,) = load_errors(SCHEMES.replace("choices: [day, night]", "choices: [day, dusk]"),
                           write_design)
    assert "unknown color scheme 'dusk'" in error.message


def test_a_setting_whose_schemes_all_fail_still_binds_their_roles(write_design):
    """No choice resolves, so the roles come from every declared scheme:
    one error per unknown scheme, none per reference."""
    errors = load_errors(SCHEMES.replace("choices: [day, night]", "choices: [dawn, dusk]")
                         .replace("default: day", "default: dawn"), write_design)
    assert sorted(e.message for e in errors) == [
        "unknown color scheme 'dawn'", "unknown color scheme 'dusk'"]


def test_a_scheme_default_must_be_a_choice(write_design):
    (error,) = load_errors(SCHEMES.replace("    default: day\n", "    default: dusk\n"),
                           write_design)
    assert "settings.theme: default 'dusk' is not one of 'choices:'" in error.message


def test_a_role_field_cannot_collide_with_another_setting(write_design):
    text = SCHEMES.replace("settings:\n", """settings:
  theme_fg:
    label: "Other"
    type: boolean
    default: true
""")
    (error,) = load_errors(text, write_design)
    assert "settings.theme: the same generated name as settings.theme_fg" in error.message


def test_a_scheme_setting_decodes_its_index_into_role_fields(write_design, db):
    files = _project(write_design, db, SCHEMES).files()
    view = files["source/SchemesView.mc"]
    assert "private var _settingTheme as Number = 0;  // day" in view
    assert "private var _settingThemeFg as Number = 0xFFFFFF;" in view
    apply = view[view.index("function applySettings()"):view.index("function settingsMenu()")]
    assert ("if (_settingTheme == 1) {\n"
            "            _settingThemeFg = 0xFF0000;  // color_scheme.night") in apply
    # Static content follows a changed scheme too.
    assert apply.index("repaintStatic();") > apply.index("_settingTheme == 1")
    assert 'return "night";' in view and 'return "Day";' in view
    assert '<property id="theme" type="number">0</property>' in \
        files["resources/settings/properties.xml"]


def _disc(write_design, db, settings=None):
    bag = Bag()
    face = load_face(SCHEMES, write_design, bag)
    device = db.get("fr955")
    resolved = resolve(face, device, bake_fonts(face, device))
    image = render(resolved, PreviewOptions(scale=1, settings=settings))
    return image.getpixel((device.width // 2, device.height // 2))[:3]


def test_the_preview_draws_the_chosen_scheme(write_design, db):
    assert _disc(write_design, db) == (255, 255, 255)
    assert _disc(write_design, db, {"theme": "night"}) == (255, 0, 0)


def test_a_scheme_the_styles_axis_also_offers_warns(write_design):
    text = SCHEMES.replace("settings:\n", """config:
  style:
    default: day
    choices:
      day: {colors: day}
      night: {colors: night}
settings:
""")
    bag = Bag()
    face = load_face(text, write_design, bag)
    from wfb import lint
    lint.run_design(face, bag)
    (warning,) = [d for d in bag.items if d.code == "settings-scheme-overlap"]
    assert "settings.theme and 'config: style:' both pick from color_scheme day, night" \
        in warning.message
    allowed = text.replace("    default: day\nelements:", "    default: day\n"
                           "    lint: {allow: [settings-scheme-overlap], reason: \"on purpose\"}\n"
                           "elements:")
    bag = Bag()
    lint.run_design(load_face(allowed, write_design, bag), bag)
    assert not [d for d in bag.items if d.code in ("settings-scheme-overlap", "lint-allow")]


def test_a_scheme_setting_s_off_grid_colour_dithers(write_design, db):
    text = SCHEMES.replace('red: "#FF0000"', 'red: "#F01010"')
    bag = lint_text(text, write_design, db, "fr955")
    dithers = sorted(d.message.split(":")[0] for d in bag.items
                     if d.code == "palette-dither" and d.message.startswith("settings."))
    assert dithers == ["settings.theme.accent", "settings.theme.fg"]


@pytest.mark.slow
@pytest.mark.parametrize("targets", ["[fenix8solar47mm, fr955]", "[fenix5]"])
def test_scheme_settings_compile_warning_free(write_design, db, tmp_path, toolchain, targets):
    if "fenix5" in targets and "fenix5" not in db.ids():
        pytest.skip("fenix5 is not installed")
    text = SCHEMES.replace("targets: [fenix8solar47mm, fr955]", f"targets: {targets}") \
        .replace("settings:\n", "settings:\n  edit: [watch, phone]\n")
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None and bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, "\n".join(d.message for d in warnings)
