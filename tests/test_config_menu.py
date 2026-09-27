"""The `config:` settings menu: on a device with no native editor (fr955),
the `config:` axes are offered from the watch's Watch Face menu
(`AppBase.getSettingsView`) and stored as `Application.Properties`
(`wfb.emit.monkeyc.config_menu`)."""

from __future__ import annotations

import pytest

from wfb.availability import compute_guards
from wfb.build import build as real_build
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.monkeyc.config_menu import menu_axes, slot_types
from wfb.emit.resources import bake_fonts
from tests.helpers import load_errors, load_face

DESIGN = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Menu
targets: [fenix8solar47mm, fr955]
palette:
  black: { value: "#000000", label: "Black" }
  white: { value: "#FFFFFF", label: "White" }
  red: "#FF0000"
  orange: "#FF5500"
color_scheme:
  dark: { label: "Dark", colors: { fg: palette.white } }
  warm: { colors: { fg: palette.orange } }
config:
  style:
    default: dark
    choices:
      dark: { colors: dark }
      warm: { label: "Warm", colors: warm }
  accent_color:
    default: palette.red
    choices: [palette.red, palette.white]
  data_color:
    default: "#00AA00"
    choices: any
  data:
    top:
      default: complication.steps
      choices: [complication.steps, complication.heart_rate]
    bottom:
      label: "Lower dial"
      default: complication.battery
      choices: any
elements:
  - id: disc
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 20%r
    filled: true
    color: config.colors.fg
    static: true
  - id: accent
    type: shape
    shape: circle
    at: {anchor: center, dy: 50%r}
    radius: 5%r
    filled: true
    color: config.accent_color
  - id: top_reading
    type: complication_slot
    slot: config.data.top
    at: {anchor: center, dy: -50%r}
    color: config.data_color
    when_absent: placeholder
    placeholder: "--"
  - id: bottom_reading
    type: complication_slot
    slot: config.data.bottom
    at: {anchor: center, dy: 70%r}
    color: config.data_color
    when_absent: placeholder
    placeholder: "--"
"""


def _face(write_design, text: str = DESIGN):
    return load_face(text, write_design, Bag())


def _files(write_design, db, device_ids, text: str = DESIGN) -> dict[str, str]:
    face = _face(write_design, text)
    devices = [db.get(d) for d in device_ids]
    out = write_design(text).parent / "out"
    return generate(face, devices, out, {d.id: bake_fonts(face, d) for d in devices}).files()


def _require(db, *ids: str) -> None:
    for device_id in ids:
        if device_id not in db.ids():
            pytest.skip(f"{device_id} is not installed")


# --------------------------------------------------------------------------
# when the menu is built


@pytest.mark.parametrize("device_ids, expected", [
    (["fenix8solar47mm", "fr955"], True),   # fr955: no editor, has the menu
    (["fenix8solar47mm"], False),           # native editor only
    (["fenix5"], False),                    # neither: nothing to offer it from
])
def test_the_menu_is_built_only_when_a_target_needs_it(write_design, db, device_ids, expected):
    _require(db, *device_ids)
    guards = compute_guards(_face(write_design), [db.get(d) for d in device_ids])
    assert guards.config_menu is expected


def test_no_config_no_menu(write_design, db, minimal):
    face = load_face(minimal.replace("[fenix8solar47mm]", "[fr955]"), write_design, Bag())
    assert not compute_guards(face, [db.get("fr955")]).config_menu


def test_a_native_only_build_carries_none_of_it(write_design, db):
    files = _files(write_design, db, ["fenix8solar47mm"])
    assert "resources/settings/properties.xml" not in files
    assert not any("ConfigMenuDelegate" in path for path in files)
    assert "getSettingsView" not in files["source/MenuApp.mc"]
    assert "applyStoredConfig" not in files["source/MenuView.mc"]


# --------------------------------------------------------------------------
# the axes


def test_every_axis_is_a_menu_item_in_order(write_design):
    axes = menu_axes(_face(write_design))
    assert [(a.kind, a.name, a.title) for a in axes] == [
        ("style", "style", "Style"),
        ("color", "accent_color", "Accent colour"),
        ("color", "data_color", "Data colour"),
        ("data", "top", "Top"),              # no label: titled from its name
        ("data", "bottom", "Lower dial"),    # its own label:
    ]
    style, accent, data = axes[0], axes[1], axes[2]
    # A style entry's own label, else its scheme's, else its name.
    assert style.labels == ("Dark", "Warm") and style.default_index == 0
    # An explicit colour list: a palette label, else the hex.
    assert accent.labels == ("#FF0000", "White") and accent.default_index == 0


def test_choices_any_offers_the_palette_plus_an_off_palette_default(write_design):
    data = menu_axes(_face(write_design))[2]
    assert data.labels == ("Default", "Black", "White", "Red", "Orange")
    assert str(data.colors[0]) == "#00AA00" and data.default_index == 0


def test_a_data_slot_s_options_are_per_device(write_design, db):
    _require(db, "fenix6")
    face = _face(write_design)
    top, bottom = face.config_data["top"], face.config_data["bottom"]
    fr955 = db.get("fr955")
    assert [t.name for t in slot_types(top, fr955)] == ["steps", "heart_rate"]
    # `any`: every type fr955's API level has -- none newer.
    names = [t.name for t in slot_types(bottom, fr955)]
    assert "battery" in names and len(names) > 20
    assert all(t.since <= fr955.api_level for t in slot_types(bottom, fr955))
    # No Toybox.Complications: no options at all.
    assert slot_types(bottom, db.get("fenix6")) == []


# --------------------------------------------------------------------------
# generated code


def test_properties_store_an_index_per_axis_defaulting_to_never_chosen(write_design, db):
    xml = _files(write_design, db, ["fenix8solar47mm", "fr955"])[
        "resources/settings/properties.xml"]
    for key in ("config_style", "config_accent_color", "config_data_color",
                "config_data_top", "config_data_bottom"):
        assert f'<property id="{key}" type="number">-1</property>' in xml


def test_the_view_reads_stored_config_only_without_the_native_editor(write_design, db):
    view = _files(write_design, db, ["fenix8solar47mm", "fr955"])["source/MenuView.mc"]
    init = view[view.index("function initialize("):view.index("function applyConfig(")]
    assert "if (!(Application has :WatchFaceConfig)) {\n            applyStoredConfig();" in init


def test_applying_stored_config_decodes_every_axis(write_design, db):
    view = _files(write_design, db, ["fenix8solar47mm", "fr955"])["source/MenuView.mc"]
    apply = view[view.index("function applyStoredConfig()"):view.index("function configMenu()")]
    # Wrong type or out of range keeps the default index.
    assert ('if (storedStyle instanceof Number && storedStyle >= 0 && storedStyle < 2) {\n'
            '            _configMenuStyle = storedStyle;') in apply
    assert "resolveStyle(_configMenuStyle);" in apply
    assert "if (_configMenuAccentColor == 1) {\n            _configAccentColor = 0xFFFFFF;" in apply
    assert "storedDataBottom < Layout.CONFIG_DATA_BOTTOM_TYPES.size()" in apply
    assert "_configDataBottom = new Complications.Id(typesBottom[_configMenuDataBottom]);" in apply
    assert "        repaintStatic();\n    }\n" in apply  # the method's last statement


def test_a_picked_option_is_stored_then_applied(write_design, db):
    view = _files(write_design, db, ["fenix8solar47mm", "fr955"])["source/MenuView.mc"]
    choose = view[view.index("function chooseConfig("):view.index("function configTitle(")]
    assert 'if (axis == 4) {\n            Application.Properties.setValue("config_data_bottom", index);' \
        in choose
    assert choose.index("applyStoredConfig();") > choose.index("config_data_bottom")


def test_selecting_an_axis_opens_its_options_focused_on_the_current_one(write_design, db):
    files = _files(write_design, db, ["fenix8solar47mm", "fr955"])
    view = files["source/MenuView.mc"]
    select = view[view.index("function selectConfig("):view.index("function chooseConfig(")]
    assert "options.addItem(new WatchUi.MenuItem(labels[i], null, i, null));" in select
    assert "options.setFocus(index);" in select
    assert "new MenuConfigChoiceDelegate(self, axis, item)" in select
    labels = view[view.index("function configLabels("):view.index("function configIndex(")]
    assert 'return ["Default", "Black", "White", "Red", "Orange"] as Array<String>;' in labels
    assert "return Layout.CONFIG_DATA_TOP_LABELS;" in labels
    delegate = files["source/MenuConfigMenuDelegate.mc"]
    assert "_view.chooseConfig(_axis, index);" in delegate
    assert "_parent.setSubLabel(item.getLabel());" in delegate


def test_a_data_slot_s_menu_title_is_its_label_else_its_name(write_design, db):
    view = _files(write_design, db, ["fenix8solar47mm", "fr955"])["source/MenuView.mc"]
    title = view[view.index("function configTitle("):view.index("function configLabels(")]
    assert 'if (axis == 3) {\n            return "Top";' in title
    assert 'if (axis == 4) {\n            return "Lower dial";' in title


def test_a_data_slot_label_never_reaches_the_native_editor(write_design, db):
    files = _files(write_design, db, ["fenix8solar47mm", "fr955"])
    # `<complication>` takes no label (resources.xsd), so only the menu has it.
    assert '<complication id="2" allowAny="true"/>' in files[
        "resources-fenix8solar47mm/configs/watchface.xml"]
    assert [path for path, text in files.items() if "Lower dial" in text] == [
        "source/MenuView.mc"]


def test_an_empty_data_slot_label_is_a_schema_error(write_design):
    errors = load_errors(DESIGN.replace('label: "Lower dial"', 'label: ""'), write_design)
    assert [e.message for e in errors] == ["config.data.bottom.label: '' should be non-empty"]


def test_the_app_offers_the_menu_only_without_the_native_editor(write_design, db):
    app = _files(write_design, db, ["fenix8solar47mm", "fr955"])["source/MenuApp.mc"]
    menu = app[app.index("function getSettingsView()"):]
    assert "if (Application has :WatchFaceConfig) {\n            return null;" in menu
    assert "view = new MenuView(_editMode);" in menu
    assert "return [ view.configMenu(), new MenuConfigMenuDelegate(view) ];" in menu


def test_layout_holds_each_device_s_slot_options(write_design, db):
    _require(db, "fenix6")
    files = _files(write_design, db, ["fenix8solar47mm", "fr955", "fenix6"])
    fr955 = files["source-fr955/Layout.mc"]
    assert ("const CONFIG_DATA_TOP_TYPES as Array<Complications.Type> = "
            "[Complications.COMPLICATION_TYPE_STEPS, "
            "Complications.COMPLICATION_TYPE_HEART_RATE];") in fr955
    assert 'const CONFIG_DATA_TOP_LABELS as Array<String> = ["Steps", "Heart rate"];' in fr955
    assert "const CONFIG_DATA_TOP_DEFAULT as Number = 0;" in fr955
    fenix6 = files["source-fenix6/Layout.mc"]
    assert "const CONFIG_DATA_BOTTOM_TYPES as Array<Complications.Type> = [];" in fenix6
    assert "const CONFIG_DATA_BOTTOM_DEFAULT as Number = -1;" in fenix6


# --------------------------------------------------------------------------
# the real compiler


@pytest.mark.slow
@pytest.mark.parametrize("targets", [
    "[fenix8solar47mm, fr955]",
    "[fenix8solar47mm, fr955, fenix6, fenix5]",
])
def test_the_config_menu_compiles_warning_free(write_design, db, tmp_path, toolchain, targets):
    """A native device, a menu device, a menu device without Complications
    (so the slot code is `has`-guarded) and a device with neither. Only
    `monkeyc`'s own diagnostics count here: the non-verification devices
    draw ordinary lint warnings (api-gated slots, config-unsupported)."""
    _require(db, "fenix6", "fenix5")
    text = DESIGN.replace("targets: [fenix8solar47mm, fr955]", f"targets: {targets}")
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    compiler = [d for d in bag.items if d.code == "monkeyc"]
    assert result is not None and not compiler, bag.render()
