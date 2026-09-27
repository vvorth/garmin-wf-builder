"""The `config:` settings menu -- the native editor's axes, offered from the
watch's Watch Face menu (`AppBase.getSettingsView`) on a device that has no
native editor (ADR 0006's tenth amendment, as amended on 2026-09-27).

Which editor a device uses is decided at runtime, by the check the view
already makes before its first native read: `Application has
:WatchFaceConfig`. With the native editor, `getSettingsView` returns null
and nothing here runs. Without it (fr955), the view reads every axis from
`Application.Properties` (`applyStoredConfig`), and the menu writes them. A
device with neither (fenix5, no `getSettingsView`) keeps every default.

Every axis is one menu item whose sub-label is the current choice;
selecting it opens a list of the axis's options, focused on the current
one. The stored value is the option's index in that list, and each
property's default is -1, "never chosen", so `properties.xml` is the same
for every device while a data slot's list (and its default's position in
it) can differ per device.
"""

from __future__ import annotations

from dataclasses import dataclass

from ... import complications
from ...devices import Device, version_key
from ...ir import ConfigDataSlot, Face, config_field
from ...ir.naming import _pascal
from ...palette import Color
from ..writer import Writer
from .common import SourceFile, _mc_string, header

#: The view's public entry points; public because the app and the menu
#: delegates call them, and a private method is invisible to another class
#: (`docs/lore/monkeyc.md`).
APPLY_STORED_METHOD = "applyStoredConfig"
MENU_METHOD = "configMenu"
SELECT_METHOD = "selectConfig"
CHOOSE_METHOD = "chooseConfig"


@dataclass(frozen=True)
class MenuAxis:
    """One `config:` axis as a settings menu item."""

    #: The menu item's identifier: the axis's position in the menu.
    id: int
    #: `"style"`, `"color"` or `"data"`.
    kind: str
    #: `style`, `accent_color`, `data_color`, or the `config: data:` slot name.
    name: str
    #: The menu item's label; a data slot's is its `label:`, else its name.
    title: str
    #: The options' labels, in order; `None` for a data slot, whose list is
    #: per device (`Layout.CONFIG_DATA_<NAME>_LABELS`).
    labels: tuple[str, ...] | None
    #: A colour axis's options, parallel to `labels`.
    colors: tuple[Color, ...] = ()
    #: The default's index in `labels`; a data slot's is per device.
    default_index: int = 0

    @property
    def key(self) -> str:
        """The `Application.Properties` key the choice is stored under."""
        return f"config_{self.name}" if self.kind != "data" else f"config_data_{self.name}"

    @property
    def index_field(self) -> str:
        """The view field holding the current option's index."""
        return config_field(f"menu_{self.key[len('config_'):]}")

    @property
    def layout_prefix(self) -> str:
        return f"CONFIG_DATA_{self.name.upper()}"


def humanise(name: str) -> str:
    """`left_register` -> `Left register`: a label for a name with none."""
    text = name.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def menu_axes(face: Face) -> list[MenuAxis]:
    """Every `config:` axis the menu offers, in menu order: Styles, the two
    colours, then each data slot."""
    axes: list[MenuAxis] = []
    style = face.config_style
    if style is not None:
        labels = tuple(face.style_label(e) or humanise(e.name) for e in style.entries)
        axes.append(MenuAxis(len(axes), "style", "style", "Style", labels,
                             default_index=style.index(style.default)))
    for name, entry in face.config.items():
        if isinstance(entry.choices, str):  # `choices: any` offers the palette
            options = [(face.palette_labels.get(p) or humanise(p), c)
                       for p, c in face.palette.items()]
            if all(c != entry.default for _, c in options):
                options.insert(0, ("Default", entry.default))
        else:
            options = [(c.label or str(c.color), c.color) for c in entry.choices]
        default_index = next(i for i, (_, c) in enumerate(options) if c == entry.default)
        axes.append(MenuAxis(len(axes), "color", name, humanise(name.replace("color", "colour")),
                             tuple(label for label, _ in options),
                             tuple(c for _, c in options), default_index))
    for name, slot in face.config_data.items():
        axes.append(MenuAxis(len(axes), "data", name, slot.label or humanise(name), None))
    return axes


def slot_types(slot: ConfigDataSlot, device: Device) -> list[complications.ComplicationType]:
    """A data slot's options on `device`: its own `choices:`, or, for
    `choices: any`, every type the device's API level has (with the
    default first if it is not one of them). Empty on a device without
    `Toybox.Complications`, where a slot reads as absent anyway."""
    if not device.has_module("Complications"):
        return []
    if not slot.allow_any:
        return [complications.TYPES[c] for c in slot.choices]
    level = version_key(device.api_level)
    types = [t for t in complications.TYPES.values() if version_key(t.since) <= level]
    default = complications.TYPES[slot.default]
    if default not in types:
        types.insert(0, default)
    return types


# --------------------------------------------------------------------------
# resources and Layout constants


def properties_resource(face: Face) -> str:
    """`resources/settings/properties.xml`: one `number` property per axis,
    each defaulting to -1 ("never chosen", so the view falls back to the
    declared default)."""
    from ..resources import _XMLNS, _XSD

    lines = [f"<properties {_XMLNS} xsi:noNamespaceSchemaLocation=\"{_XSD}\">"]
    for axis in menu_axes(face):
        lines.append(f'    <property id="{axis.key}" type="number">-1</property>')
    lines.append("</properties>")
    return "\n".join(lines) + "\n"


def emit_layout_constants(w: Writer, face: Face, device: Device) -> None:
    """Each data slot's options on this device: the types, their labels
    and the default's index (-1 on a device without `Toybox.Complications`,
    whose lists are empty)."""
    for axis in menu_axes(face):
        if axis.kind != "data":
            continue
        slot = face.config_data[axis.name]
        types = slot_types(slot, device)
        default = complications.TYPES[slot.default]
        w.blank()
        w.doc(f"`config.data.{axis.name}` in the settings menu: its options on {device.id}.")
        values = ", ".join(f"Complications.{t.constant}" for t in types)
        labels = ", ".join(_mc_string(humanise(t.name)) for t in types)
        w.line(f"const {axis.layout_prefix}_TYPES as Array<Complications.Type> = [{values}];")
        w.line(f"const {axis.layout_prefix}_LABELS as Array<String> = [{labels}];")
        index = types.index(default) if default in types else -1
        w.line(f"const {axis.layout_prefix}_DEFAULT as Number = {index};")


# --------------------------------------------------------------------------
# the view


def emit_fields(w: Writer, face: Face) -> None:
    """One index field per axis, starting at its default."""
    w.doc("The settings menu's current choice per config axis, as an index into\n"
          "that axis's list of options (applyStoredConfig).")
    for axis in menu_axes(face):
        default = f"Layout.{axis.layout_prefix}_DEFAULT" if axis.kind == "data" \
            else str(axis.default_index)
        w.line(f"private var {axis.index_field} as Number = {default};")
    w.blank()


def emit_view_methods(w: Writer, face: Face, entry: str, *, repaint: str | None,
                      resolve_style: str, complications_guarded: bool) -> None:
    """`applyStoredConfig`, `configMenu`, `selectConfig`, `chooseConfig` and
    the private `configLabels`/`configIndex`."""
    axes = menu_axes(face)
    w.doc(
        "Read every config axis the settings menu stores into view state -- on a\n"
        "device with no native editor, where it replaces WatchFaceConfig.\n"
        "\n"
        "A value of the wrong type, or out of range (-1, never chosen), keeps\n"
        "the declared default."
    )
    with w.block(f"function {APPLY_STORED_METHOD}() as Void"):
        for axis in axes:
            local = f"stored{axis.index_field[len('_configMenu'):]}"
            size = f"Layout.{axis.layout_prefix}_TYPES.size()" if axis.kind == "data" \
                else str(len(axis.labels or ()))
            w.line(f'var {local} = Application.Properties.getValue("{axis.key}");')
            with w.block(f"if ({local} instanceof Number && {local} >= 0 && {local} < {size})"):
                w.line(f"{axis.index_field} = {local};")
            if axis.kind == "style":
                w.line(f"{resolve_style}({axis.index_field});")
            elif axis.kind == "color":
                field = config_field(axis.name)
                assert axis.labels is not None
                for index, color in enumerate(axis.colors):
                    with w.block(f"if ({axis.index_field} == {index})"):
                        w.line(f"{field} = {color.as_monkeyc()};  // {axis.labels[index]}")
            else:
                slot = face.config_data[axis.name]
                # One local per slot: without the `has` block around it, a
                # second `var types` in this method is a Redefinition error.
                types = f"types{_pascal(axis.name)}"
                with w.block_if("if (Toybox has :Complications)" if complications_guarded else None):
                    w.line(f"var {types} = Layout.{axis.layout_prefix}_TYPES;")
                    with w.block(f"if ({axis.index_field} >= 0 && {axis.index_field} < {types}.size())"):
                        w.line(f"{slot.field} = new Complications.Id({types}[{axis.index_field}]);")
        if repaint is not None:
            w.comment("a config colour may be drawn into the static buffer -- repaint it")
            w.line(f"{repaint}();")
    w.blank()
    w.doc("The settings menu: one item per config axis, showing its current choice.")
    with w.block(f"function {MENU_METHOD}() as WatchUi.Menu2"):
        w.line(f"var menu = new WatchUi.Menu2({{ :title => {_mc_string(face.name)} }});")
        with w.block(f"for (var axis = 0; axis < {len(axes)}; axis += 1)"):
            w.line("var labels = configLabels(axis);")
            w.line("var index = configIndex(axis);")
            w.comment("a data slot has no options on a device without Toybox.Complications")
            with w.block("if (index >= 0 && index < labels.size())"):
                w.line("menu.addItem(new WatchUi.MenuItem(configTitle(axis), labels[index], "
                       "axis, null));")
        w.line("return menu;")
    w.blank()
    w.doc("A config axis was selected: open the list of its options, focused on the\n"
          "current one.")
    with w.block(f"function {SELECT_METHOD}(item as WatchUi.MenuItem) as Void"):
        w.line("var axis = item.getId();")
        with w.block("if (axis instanceof Number)"):
            w.line("var labels = configLabels(axis);")
            w.line("var options = new WatchUi.Menu2({ :title => configTitle(axis) });")
            with w.block("for (var i = 0; i < labels.size(); i += 1)"):
                w.line("options.addItem(new WatchUi.MenuItem(labels[i], null, i, null));")
            w.line("var index = configIndex(axis);")
            with w.block("if (index >= 0)"):
                w.line("options.setFocus(index);")
            w.line(f"WatchUi.pushView(options, new {entry}ConfigChoiceDelegate(self, axis, item), "
                   "WatchUi.SLIDE_LEFT);")
    w.blank()
    w.doc("An option was picked from an axis's list: store it and apply it.")
    with w.block(f"function {CHOOSE_METHOD}(axis as Number, index as Number) as Void"):
        for axis in axes:
            with w.block(f"if (axis == {axis.id})"):
                w.line(f'Application.Properties.setValue("{axis.key}", index);')
        w.line(f"{APPLY_STORED_METHOD}();")
        w.line("WatchUi.requestUpdate();")
    w.blank()
    w.doc("A config axis's menu title.")
    with w.block("private function configTitle(axis as Number) as String"):
        for axis in axes[1:]:
            with w.block(f"if (axis == {axis.id})"):
                w.line(f"return {_mc_string(axis.title)};")
        w.line(f"return {_mc_string(axes[0].title)};")
    w.blank()
    w.doc("A config axis's options, in order -- a data slot's come from Layout, since\n"
          "the complication types on offer can differ per device.")
    with w.block("private function configLabels(axis as Number) as Array<String>"):
        for axis in axes:
            with w.block(f"if (axis == {axis.id})"):
                if axis.labels is None:
                    w.line(f"return Layout.{axis.layout_prefix}_LABELS;")
                else:
                    labels = ", ".join(_mc_string(label) for label in axis.labels)
                    w.line(f"return [{labels}] as Array<String>;")
        w.line("return [] as Array<String>;")
    w.blank()
    w.doc("A config axis's current option, as an index into configLabels.")
    with w.block("private function configIndex(axis as Number) as Number"):
        for axis in axes[1:]:
            with w.block(f"if (axis == {axis.id})"):
                w.line(f"return {axis.index_field};")
        w.line(f"return {axes[0].index_field};")
    w.blank()


# --------------------------------------------------------------------------
# the delegates


def emit_delegates(face: Face) -> SourceFile:
    """`source/<Face>ConfigMenuDelegate.mc`: the settings menu's input and
    the input of the list an axis opens. Both hand the selection to the
    view."""
    entry = face.entry
    w = Writer()
    w.doc(header(face)).blank()
    w.lines("import Toybox.Lang;", "import Toybox.WatchUi;").blank()
    w.doc("Input for the settings menu: a selected axis opens its list of options.")
    with w.block(f"class {entry}ConfigMenuDelegate extends WatchUi.Menu2InputDelegate"):
        w.line(f"private var _view as {entry}View;")
        w.blank()
        with w.block(f"function initialize(view as {entry}View)"):
            w.line("Menu2InputDelegate.initialize();")
            w.line("_view = view;")
        w.blank()
        with w.block("function onSelect(item as WatchUi.MenuItem) as Void"):
            w.line(f"_view.{SELECT_METHOD}(item);")
    w.blank()
    w.doc("Input for one axis's list of options: the picked option is stored, the\n"
          "settings menu's item shows it, and the list closes.")
    with w.block(f"class {entry}ConfigChoiceDelegate extends WatchUi.Menu2InputDelegate"):
        w.line(f"private var _view as {entry}View;")
        w.line("private var _axis as Number;")
        w.line("private var _parent as WatchUi.MenuItem;")
        w.blank()
        with w.block(f"function initialize(view as {entry}View, axis as Number, "
                     "parent as WatchUi.MenuItem)"):
            w.line("Menu2InputDelegate.initialize();")
            w.line("_view = view;")
            w.line("_axis = axis;")
            w.line("_parent = parent;")
        w.blank()
        with w.block("function onSelect(item as WatchUi.MenuItem) as Void"):
            w.line("var index = item.getId();")
            with w.block("if (index instanceof Number)"):
                w.line(f"_view.{CHOOSE_METHOD}(_axis, index);")
                w.line("_parent.setSubLabel(item.getLabel());")
            w.line("WatchUi.popView(WatchUi.SLIDE_RIGHT);")
    return SourceFile(f"source/{entry}ConfigMenuDelegate.mc", w.render())
