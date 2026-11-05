// The `config:` settings menu: the native editor's axes, offered from the
// watch's Watch Face menu (`AppBase.getSettingsView`) on a device with no
// native editor.
//
// Which editor a device uses is decided at runtime (`Application has
// :WatchFaceConfig`). Every axis is one menu item whose sub-label is the
// current choice; the stored value is the option's index, one
// `Application.Properties` number per axis, which defaults to the declared
// default's index on that device. Garmin Connect edits the same properties
// for a Store install, through the device's `settings.xml` (one list per
// axis, in the menu's order), so the menu and the phone share one storage.
import * as complications from "../../complications.ts";
import { usesSettingsMenu } from "../../availability.ts";
import { compareVersions, type Device } from "../../devices/device.ts";
import type { ConfigDataSlot, Face } from "../../ir/model.ts";
import { configField, configLabelId, configStyleLabelId, pascal } from "../../ir/naming.ts";
import { commentText, stringLiteral } from "../../mcsource.ts";
import type { Color } from "../../palette.ts";
import { humanise } from "../../vocab.ts";
import { Writer } from "../writer.ts";
import { XMLNS, XSD } from "../xml.ts";
import { header, type SourceFile } from "./common.ts";

export const APPLY_STORED_METHOD = "applyStoredConfig";
export const MENU_METHOD = "configMenu";
export const SELECT_METHOD = "selectConfig";
export const CHOOSE_METHOD = "chooseConfig";

/** One `config:` axis as a settings menu item. */
export class MenuAxis {
  readonly id: number;
  readonly kind: "style" | "color" | "data";
  readonly name: string;
  readonly title: string;
  /** The options' labels; `null` for a data slot, whose list is per device. */
  readonly labels: string[] | null;
  readonly colors: Color[];
  readonly default_index: number;

  constructor(id: number, kind: "style" | "color" | "data", name: string, title: string, labels: string[] | null, colors: Color[] = [], defaultIndex = 0) {
    this.id = id;
    this.kind = kind;
    this.name = name;
    this.title = title;
    this.labels = labels;
    this.colors = colors;
    this.default_index = defaultIndex;
  }

  get key(): string {
    return this.kind !== "data" ? `config_${this.name}` : `config_data_${this.name}`;
  }

  get indexField(): string {
    return configField(`menu_${this.key.slice("config_".length)}`);
  }

  get layoutPrefix(): string {
    return `CONFIG_DATA_${this.name.toUpperCase()}`;
  }
}


/** Every axis the menu offers: Styles, the two colours, then each data slot. */
export function menuAxes(face: Face): MenuAxis[] {
  const axes: MenuAxis[] = [];
  const style = face.config_style;
  if (style !== null) {
    const labels = style.entries.map((e) => face.styleLabel(e) || humanise(e.name));
    axes.push(new MenuAxis(axes.length, "style", "style", "Style", labels, [], style.index(style.default)));
  }
  for (const [name, entry] of face.config) {
    const options = entry.options.map((c): [string, Color] => [c.label || String(c.color), c.color]);
    const defaultIndex = options.findIndex(([, c]) => c.equals(entry.default));
    axes.push(new MenuAxis(axes.length, "color", name, humanise(name.replaceAll("color", "colour")),
      options.map(([label]) => label), options.map(([, c]) => c), defaultIndex));
  }
  for (const [name, slot] of face.config_data) axes.push(new MenuAxis(axes.length, "data", name, slot.label || humanise(name), null));
  return axes;
}

/** A data slot's options on `device`: its `choices:`, or every type its API level has; empty without Complications. */
export function slotTypes(slot: ConfigDataSlot, device: Device): complications.ComplicationType[] {
  if (!device.hasModule("Complications")) return [];
  if (slot.choices !== "any") return slot.choices.map((c) => complications.TYPES.get(c)!);
  const types = [...complications.TYPES.values()].filter((t) => compareVersions(t.since, device.apiLevel) <= 0);
  const fallback = complications.TYPES.get(slot.default)!;
  if (!types.includes(fallback)) types.unshift(fallback);
  return types;
}

/** The default's index into `axis`'s options on `device`: -1 for a data slot with no options there. */
function defaultIndex(face: Face, axis: MenuAxis, device: Device): number {
  if (axis.kind !== "data") return axis.default_index;
  const slot = face.config_data.get(axis.name)!;
  return slotTypes(slot, device).indexOf(complications.TYPES.get(slot.default)!);
}

/** The `<string>` id of an axis's title in Garmin Connect: `ConfigTitleStyle`, `ConfigTitleAccentColor`, `ConfigTitleDataTop`. */
export function titleStringId(axis: MenuAxis): string {
  return `ConfigTitle${pascal(axis.key.slice("config_".length))}`;
}

/** The `<string>` id of a complication type's label: `ConfigTypeHeartRate`. */
export function typeStringId(type: complications.ComplicationType): string {
  return `ConfigType${pascal(type.name)}`;
}

/** `[string id, label]` for each of `axis`'s options on `device`, in the menu's order. */
function optionStrings(face: Face, axis: MenuAxis, device: Device): [string, string][] {
  if (axis.kind === "data") return slotTypes(face.config_data.get(axis.name)!, device).map((t) => [typeStringId(t), humanise(t.name)]);
  const id = axis.kind === "style" ? configStyleLabelId : (index: number) => configLabelId(axis.name, index);
  return axis.labels!.map((label, index) => [id(index), label]);
}

/**
 * `[string id, text]` for every string some menu device's `settings.xml`
 * names: each axis's title, the Style and colour options' labels, and every
 * complication type any of those devices' slots offers. One shared list, so
 * an id means the same text on every device.
 */
export function settingsStrings(face: Face, devices: readonly Device[]): [string, string][] {
  const menuDevices = face.hasConfig ? devices.filter(usesSettingsMenu) : [];
  if (menuDevices.length === 0) return [];
  const out: [string, string][] = [];
  const axes = menuAxes(face);
  for (const axis of axes) out.push([titleStringId(axis), axis.title]);
  for (const axis of axes) if (axis.kind !== "data") out.push(...optionStrings(face, axis, menuDevices[0]!));
  const offered = new Set<complications.ComplicationType>();
  for (const [, slot] of face.config_data) for (const device of menuDevices) for (const type of slotTypes(slot, device)) offered.add(type);
  for (const type of complications.TYPES.values()) if (offered.has(type)) out.push([typeStringId(type), humanise(type.name)]);
  return out;
}

/** `resources-<device>/settings/properties.xml`: one `number` property per axis, defaulting to the declared default's index there. */
export function propertiesResource(face: Face, device: Device): string {
  const lines = [`<properties ${XMLNS} xsi:noNamespaceSchemaLocation="${XSD}">`];
  for (const axis of menuAxes(face)) lines.push(`    <property id="${axis.key}" type="number">${defaultIndex(face, axis, device)}</property>`);
  lines.push("</properties>");
  return lines.join("\n") + "\n";
}

/**
 * `resources-<device>/settings/settings.xml`: what Garmin Connect offers for
 * a Store install, one list per axis in the menu's order, storing the same
 * index the menu stores. A data slot with no options on `device` (no
 * Toybox.Complications) is left out, as the menu leaves it out; `null` when
 * that leaves nothing to offer.
 */
export function settingsResource(face: Face, device: Device): string | null {
  const lines = [`<settings ${XMLNS} xsi:noNamespaceSchemaLocation="${XSD}">`];
  for (const axis of menuAxes(face)) {
    const options = optionStrings(face, axis, device);
    if (options.length === 0) continue;
    lines.push(`    <setting propertyKey="@Properties.${axis.key}" title="@Strings.${titleStringId(axis)}">`);
    lines.push('        <settingConfig type="list">');
    options.forEach(([id], index) => lines.push(`            <listEntry value="${index}">@Strings.${id}</listEntry>`));
    lines.push("        </settingConfig>");
    lines.push("    </setting>");
  }
  if (lines.length === 1) return null;
  lines.push("</settings>");
  return lines.join("\n") + "\n";
}

/** Each data slot's options on this device: the types, their labels and the default's index. */
export function emitLayoutConstants(w: Writer, face: Face, device: Device): void {
  for (const axis of menuAxes(face)) {
    if (axis.kind !== "data") continue;
    const slot = face.config_data.get(axis.name)!;
    const types = slotTypes(slot, device);
    const fallback = complications.TYPES.get(slot.default)!;
    w.blank();
    w.doc(`Slot \`${axis.name}\` in the settings menu: its options on ${device.id}.`);
    const values = types.map((t) => `Complications.${t.constant}`).join(", ");
    const labels = types.map((t) => stringLiteral(humanise(t.name))).join(", ");
    w.line(`const ${axis.layoutPrefix}_TYPES as Array<Complications.Type> = [${values}];`);
    w.line(`const ${axis.layoutPrefix}_LABELS as Array<String> = [${labels}];`);
    w.line(`const ${axis.layoutPrefix}_DEFAULT as Number = ${types.indexOf(fallback)};`);
  }
}

/** One index field per axis, starting at its default. */
export function emitFields(w: Writer, face: Face): void {
  w.doc("The settings menu's current choice per config axis, as an index into\nthat axis's list of options (applyStoredConfig).");
  for (const axis of menuAxes(face)) {
    const fallback = axis.kind === "data" ? `Layout.${axis.layoutPrefix}_DEFAULT` : String(axis.default_index);
    w.line(`private var ${axis.indexField} as Number = ${fallback};`);
  }
  w.blank();
}

/** `applyStoredConfig`, `configMenu`, `selectConfig`, `chooseConfig` and the private helpers. */
export function emitViewMethods(w: Writer, face: Face, entry: string,
  { repaint, resolveStyle, complicationsGuarded }: { repaint: string | null; resolveStyle: string; complicationsGuarded: boolean }): void {
  const axes = menuAxes(face);
  w.doc("Read every config axis the settings menu stores into view state -- on a\n"
    + "device with no native editor, where it replaces WatchFaceConfig.\n"
    + "\n"
    + "A value of the wrong type, or out of range, keeps the declared default.");
  w.block(`function ${APPLY_STORED_METHOD}() as Void`, () => {
    for (const axis of axes) {
      const local = `stored${axis.indexField.slice("_configMenu".length)}`;
      const size = axis.kind === "data" ? `Layout.${axis.layoutPrefix}_TYPES.size()` : String((axis.labels ?? []).length);
      w.line(`var ${local} = Application.Properties.getValue("${axis.key}");`);
      w.block(`if (${local} instanceof Number && ${local} >= 0 && ${local} < ${size})`, () => w.line(`${axis.indexField} = ${local};`));
      if (axis.kind === "style") {
        w.line(`${resolveStyle}(${axis.indexField});`);
      } else if (axis.kind === "color") {
        const field = configField(axis.name);
        axis.colors.forEach((color, index) => {
          w.block(`if (${axis.indexField} == ${index})`, () => w.line(`${field} = ${color.asMonkeyc()};  // ${commentText(axis.labels![index]!)}`));
        });
      } else {
        const slot = face.config_data.get(axis.name)!;
        const types = `types${pascal(axis.name)}`;
        w.blockIf(complicationsGuarded ? "if (Toybox has :Complications)" : null, () => {
          w.line(`var ${types} = Layout.${axis.layoutPrefix}_TYPES;`);
          w.block(`if (${axis.indexField} >= 0 && ${axis.indexField} < ${types}.size())`, () => {
            w.line(`${slot.field} = new Complications.Id(${types}[${axis.indexField}]);`);
          });
        });
      }
    }
    if (repaint !== null) {
      w.comment("a config colour may be drawn into the static buffer -- repaint it");
      w.line(`${repaint}();`);
    }
  });
  w.blank();
  w.doc("The settings menu: one item per config axis, showing its current choice.");
  w.block(`function ${MENU_METHOD}() as WatchUi.Menu2`, () => {
    w.line(`var menu = new WatchUi.Menu2({ :title => ${stringLiteral(face.name)} });`);
    w.block(`for (var axis = 0; axis < ${axes.length}; axis += 1)`, () => {
      w.line("var labels = configLabels(axis);");
      w.line("var index = configIndex(axis);");
      w.comment("a data slot has no options on a device without Toybox.Complications");
      w.block("if (index >= 0 && index < labels.size())", () => {
        w.line("menu.addItem(new WatchUi.MenuItem(configTitle(axis), labels[index], axis, null));");
      });
    });
    w.line("return menu;");
  });
  w.blank();
  w.doc("A config axis was selected: open the list of its options, focused on the\ncurrent one.");
  w.block(`function ${SELECT_METHOD}(item as WatchUi.MenuItem) as Void`, () => {
    w.line("var axis = item.getId();");
    w.block("if (axis instanceof Number)", () => {
      w.line("var labels = configLabels(axis);");
      w.line("var options = new WatchUi.Menu2({ :title => configTitle(axis) });");
      w.block("for (var i = 0; i < labels.size(); i += 1)", () => w.line("options.addItem(new WatchUi.MenuItem(labels[i], null, i, null));"));
      w.line("var index = configIndex(axis);");
      w.block("if (index >= 0)", () => w.line("options.setFocus(index);"));
      w.line(`WatchUi.pushView(options, new ${entry}ConfigChoiceDelegate(self, axis, item), WatchUi.SLIDE_LEFT);`);
    });
  });
  w.blank();
  w.doc("An option was picked from an axis's list: store it and apply it.");
  w.block(`function ${CHOOSE_METHOD}(axis as Number, index as Number) as Void`, () => {
    for (const axis of axes) w.block(`if (axis == ${axis.id})`, () => w.line(`Application.Properties.setValue("${axis.key}", index);`));
    w.line(`${APPLY_STORED_METHOD}();`);
    w.line("WatchUi.requestUpdate();");
  });
  w.blank();
  w.doc("A config axis's menu title.");
  w.block("private function configTitle(axis as Number) as String", () => {
    for (const axis of axes.slice(1)) w.block(`if (axis == ${axis.id})`, () => w.line(`return ${stringLiteral(axis.title)};`));
    w.line(`return ${stringLiteral(axes[0]!.title)};`);
  });
  w.blank();
  w.doc("A config axis's options, in order -- a data slot's come from Layout, since\nthe complication types on offer can differ per device.");
  w.block("private function configLabels(axis as Number) as Array<String>", () => {
    for (const axis of axes) {
      w.block(`if (axis == ${axis.id})`, () => {
        if (axis.labels === null) w.line(`return Layout.${axis.layoutPrefix}_LABELS;`);
        else w.line(`return [${axis.labels.map((l) => stringLiteral(l)).join(", ")}] as Array<String>;`);
      });
    }
    w.line("return [] as Array<String>;");
  });
  w.blank();
  w.doc("A config axis's current option, as an index into configLabels.");
  w.block("private function configIndex(axis as Number) as Number", () => {
    for (const axis of axes.slice(1)) w.block(`if (axis == ${axis.id})`, () => w.line(`return ${axis.indexField};`));
    w.line(`return ${axes[0]!.indexField};`);
  });
  w.blank();
}

/** `source/<Face>ConfigMenuDelegate.mc`: the settings menu's input and the input of an axis's list. */
export function emitDelegates(face: Face): SourceFile {
  const entry = face.entry;
  const w = new Writer();
  w.doc(header(face)).blank();
  w.lines("import Toybox.Lang;", "import Toybox.WatchUi;").blank();
  w.doc("Input for the settings menu: a selected axis opens its list of options.");
  w.block(`class ${entry}ConfigMenuDelegate extends WatchUi.Menu2InputDelegate`, () => {
    w.line(`private var _view as ${entry}View;`);
    w.blank();
    w.block(`function initialize(view as ${entry}View)`, () => {
      w.line("Menu2InputDelegate.initialize();");
      w.line("_view = view;");
    });
    w.blank();
    w.block("function onSelect(item as WatchUi.MenuItem) as Void", () => w.line(`_view.${SELECT_METHOD}(item);`));
  });
  w.blank();
  w.doc("Input for one axis's list of options: the picked option is stored, the\nsettings menu's item shows it, and the list closes.");
  w.block(`class ${entry}ConfigChoiceDelegate extends WatchUi.Menu2InputDelegate`, () => {
    w.line(`private var _view as ${entry}View;`);
    w.line("private var _axis as Number;");
    w.line("private var _parent as WatchUi.MenuItem;");
    w.blank();
    w.block(`function initialize(view as ${entry}View, axis as Number, parent as WatchUi.MenuItem)`, () => {
      w.line("Menu2InputDelegate.initialize();");
      w.line("_view = view;");
      w.line("_axis = axis;");
      w.line("_parent = parent;");
    });
    w.blank();
    w.block("function onSelect(item as WatchUi.MenuItem) as Void", () => {
      w.line("var index = item.getId();");
      w.block("if (index instanceof Number)", () => {
        w.line(`_view.${CHOOSE_METHOD}(_axis, index);`);
        w.line("_parent.setSubLabel(item.getLabel());");
      });
      w.line("WatchUi.popView(WatchUi.SLIDE_RIGHT);");
    });
  });
  return { path: `source/${entry}ConfigMenuDelegate.mc`, text: w.render() };
}
