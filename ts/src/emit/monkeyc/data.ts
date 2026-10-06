// A data element's on-device config-editor plumbing, its reading module and
// its hold and icon helpers; its drawing is the data kind's `lower`..
import { type Guards, NO_GUARDS } from "../../availability.ts";
import * as complications from "../../complications.ts";
import type { Face } from "../../ir/model.ts";
import { configField, dataHoldMethod, dataIconMethod, elementMethodName } from "../../ir/naming.ts";
import type { PlacedData, ResolvedFace } from "../../layout.ts";
import type { Writer as WriterType } from "../writer.ts";
import { Writer } from "../writer.ts";
import { dataElements, type EditorSlot, header, type SourceFile } from "./common.ts";
import type { ReadPlan } from "./readplan.ts";

export const LOAD_RESOURCES_METHOD = "loadResources";
export const RESOURCES_LOADED_FIELD = "_resourcesLoaded";

/** Python's `sorted()` of strings. */
function sortedNames(items: Iterable<string>): string[] {
  return [...items].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
}

export function emitResourcesLoadedField(w: WriterType): void {
  w.doc("Whether loadResources has run.  The native editor can ask for a slot's\ndrawable, and draw it, before onLayout -- drawableFor loads first then.");
  w.line(`private var ${RESOURCES_LOADED_FIELD} as Boolean = false;`);
  w.blank();
}

export function emitPulsingField(w: WriterType): void {
  w.doc("Which slot the native editor is animating right now (a\n"
    + "config_data_ids unique id), or 0 for none.  Read by every element\n"
    + "drawing a slot so the system does not see it drawn twice while it\n"
    + "pulses, and cleared after every onUpdate: the skip covers the one\n"
    + "redraw that follows the editor's request for the drawable.");
  w.line("private var _pulsing as Number = 0;");
  w.blank();
}

/** `setPulsing`/`drawSlot`/`drawableFor`, and one `drawSlot<Name>` per slot. */
export function emitDataEditorMethods(w: WriterType, resolved: ResolvedFace, plan: ReadPlan, slots: readonly EditorSlot[]): void {
  const face = resolved.face;
  const placedById = new Map(resolved.items.map((p) => [p.id, p]));
  w.doc("The native editor is telling this view which slot it is about to animate,\nor, with 0, that none is being animated any more.\n\n"
    + "Only ever called from getComplicationDrawable and onWatchFaceConfigEdited,\nwhich fire solely inside the on-device config editor (research 07 1a).");
  w.block("function setPulsing(unique as Number) as Void", () => w.line("_pulsing = unique;"));
  w.blank();
  for (const slot of slots) {
    const members = slot.elements.filter((e) => placedById.has(e.id)).map((e) => placedById.get(e.id)!);
    w.doc(`Every element drawing slot \`${slot.name}\`, as the editor's drawable shows it.`);
    w.block(`private function ${slot.drawMethod}(dc as Dc) as Void`, () => {
      const readers: string[] = [];
      for (const placed of members) for (const name of plan.readersOf(placed)) if (!readers.includes(name)) readers.push(name);
      plan.emitPulls(w, readers);
      for (const placed of members) w.line(`${elementMethodName(placed.id)}(dc${plan.arguments(placed)});`);
    });
    w.blank();
  }
  w.doc("Draw one slot by its config_data_ids unique id -- the one public entry\n"
    + "point the generated SlotDrawable needs, so every element's own draw\n"
    + "method can stay private.\n\n"
    + "The editor is drawing the slot it animates, so each element's own\n"
    + "_pulsing skip is lifted for this call: the face skips that slot so it is\n"
    + "not drawn under the animation, and this is what draws it instead.");
  w.block("function drawSlot(dc as Dc, unique as Number) as Void", () => {
    w.line("var pulsing = _pulsing;");
    w.line("_pulsing = 0;");
    w.block("switch (unique)", () => {
      for (const slot of slots) w.line(`case ${slot.unique}: ${slot.drawMethod}(dc); break;`);
    });
    w.line("_pulsing = pulsing;");
  });
  w.blank();
  w.doc("Build the Drawable the editor animates for one slot, on that slot's own\n"
    + "highlight box: every element drawing it, and for a reading, every screen\n"
    + "column it could reach -- the editor clips the drawable to this box, and\n"
    + "what the pick draws (label, value, unit, icon) is not known until the\n"
    + "device pulls it.");
  w.block("function drawableFor(unique as Number) as WatchUi.ComplicationDrawableRef or Null", () => {
    w.comment("the editor can get here before onLayout: fonts and the wearer's");
    w.comment("config first, or the slot draws without its icon");
    w.block(`if (!${RESOURCES_LOADED_FIELD})`, () => w.line(`${LOAD_RESOURCES_METHOD}();`));
    w.line("var drawable = null;");
    w.block("switch (unique)", () => {
      for (const slot of slots) {
        const box = `Layout.${slot.constPrefix}_HIGHLIGHT`;
        w.line(`case ${slot.unique}: drawable = new ${face.entry}SlotDrawable(self, ${slot.unique},`);
        w.line(`    ${box}_X, ${box}_Y,`);
        w.line(`    ${box}_WIDTH, ${box}_HEIGHT); break;`);
      }
    });
    w.block("if (drawable == null)", () => w.line("return null;"));
    w.line("return new WatchUi.ComplicationDrawableRef(");
    w.line("    { :drawable => drawable, :boundingBox => drawable.boundingBox() });");
  });
  w.blank();
}

/** `source/<Face>SlotDrawable.mc`: the stand-in the native editor animates, drawing through the view. */
export function emitSlotDrawable(face: Face): SourceFile {
  const w = new Writer();
  w.doc(header(face)).blank();
  w.lines("import Toybox.Graphics;", "import Toybox.Lang;", "import Toybox.WatchUi;").blank();
  w.doc("A generated stand-in for one `data` element's slot, handed to the editor so\n"
    + "it can animate (\"pulse\") the slot the wearer is about to change.  It\n"
    + "delegates straight back to the view's own drawSlot, so there is exactly\n"
    + "one implementation of what a slot looks like.\n"
    + "\n"
    + "Seen on a fenix8solar47mm: the editor animates it over the slot.  A watch\nwith no editor never constructs one.");
  w.block(`class ${face.entry}SlotDrawable extends WatchUi.Drawable`, () => {
    w.line(`private var _view as ${face.entry}View;`);
    w.line("private var _unique as Number;");
    w.blank();
    w.block(`function initialize(view as ${face.entry}View, unique as Number,\n                    x as Number, y as Number, w as Number, h as Number)`, () => {
      w.line("Drawable.initialize({ :locX => x, :locY => y, :width => w, :height => h });");
      w.line("_view = view;");
      w.line("_unique = unique;");
    });
    w.blank();
    w.block("function boundingBox() as Graphics.BoundingBox", () => {
      w.line("var box = new Graphics.BoundingBox();");
      w.line("box.addRectangle(locX.toNumber(), locY.toNumber(), width.toNumber(), height.toNumber());");
      w.line("return box;");
    });
    w.blank();
    w.block("function draw(dc as Dc) as Void", () => {
      w.block("if (!isVisible)", () => w.line("return;"));
      w.line("_view.drawSlot(dc, _unique);");
    });
  });
  return { path: `source/${face.entry}SlotDrawable.mc`, text: w.render() };
}

export const SLOT_TEXT_MODULE = "SlotText";

/** Every complication type a drawn `data` element can show, across every slot. */
export function slotReadingTypes(face: Face): string[] {
  const names = new Set<string>();
  for (const element of dataElements(face)) {
    const slot = face.config_data.get(element.slot);
    if (slot === undefined) continue;
    for (const name of slot.choices === "any" ? complications.TYPES.keys() : slot.choices) names.add(name);
  }
  return sortedNames(names);
}

/** The `short:` values of the drawn slots that can show a `kind` reading. */
function wordedVariants(face: Face, kind: string): Set<boolean> {
  const variants = new Set<boolean>();
  for (const element of dataElements(face)) {
    const slot = face.config_data.get(element.slot);
    if (slot === undefined) continue;
    const shown = slot.choices === "any" ? [...complications.TYPES.keys()] : slot.choices;
    if (shown.some((name) => complications.READING.get(name) === kind)) variants.add(element.short);
  }
  return variants;
}

const NUMERIC_READING: Readonly<Record<string, string>> = {
  percent: "WfbReading.percent(value, unit)",
  vo2max: "(value.toNumber() == 0) ? null : WfbReading.count(value, c.unit)",
  clock: "WfbReading.clock(value, settings.is24Hour)",
  duration: "WfbReading.duration(value)",
  hours: "WfbReading.hours(value)",
  temperature: "WfbReading.temperature(value, settings.temperatureUnits == System.UNIT_STATUTE, unit)",
  elevation: "WfbReading.elevation(value, settings.elevationUnits == System.UNIT_STATUTE, unit, short)",
  distance: "WfbReading.distance(value, settings.distanceUnits == System.UNIT_STATUTE, unit, short)",
  pressure: "WfbReading.pressure(value, unit, short)",
  pace: "WfbReading.pace(value, settings.paceUnits == System.UNIT_STATUTE, unit, short)",
};

const READS_SETTINGS = new Set(["clock", "temperature", "elevation", "distance", "pace"]);

function variantExpression(variants: Set<boolean>, short: string, full: string): string {
  if (variants.size === 1 && variants.has(true)) return short;
  if (variants.size === 1 && variants.has(false)) return full;
  return `short ? ${short} : ${full}`;
}

const PACK_FILL = "|";

/** Every weather condition's name, in value order, padded to one width and joined. */
function packedNames(short: boolean): [string, number] {
  const values = [...complications.WEATHER_CONDITION_TEXT.keys()].sort((a, b) => a - b);
  const names = values.map((v) => complications.WEATHER_CONDITION_TEXT.get(v)![short ? 1 : 0]);
  const width = Math.max(...names.map((n) => n.length));
  return [names.map((n) => n.padEnd(width, PACK_FILL)).join(""), width];
}

function emitConditionTable(w: WriterType, method: string, short: boolean): void {
  const [packed, width] = packedNames(short);
  w.block(`function ${method}(condition as Number) as String`, () => {
    w.line(`return WfbReading.packed("${packed}",`);
    w.line(`        ${width}, condition);`);
  });
  w.blank();
}

/** `source/SlotText.mc`: a data element's reading as the text it draws, one rule per type. */
export function emitSlotText(face: Face): SourceFile {
  const names = slotReadingTypes(face);
  const kinds = new Map(names.map((name) => [name, complications.READING.get(name)!]));
  const constant = new Map(names.map((name) => [name, `Complications.${complications.TYPES.get(name)!.constant}`]));
  const training = wordedVariants(face, "training_status");
  const conditions = wordedVariants(face, "condition");
  const w = new Writer();
  w.doc(header(face)).blank();
  w.lines("import Toybox.Complications;", "import Toybox.Lang;", "import Toybox.System;").blank();
  w.doc("A `data` element's reading as the text it draws: one rule per\ncomplication type, generated from the complication table's readings (ts/src/complications.ts).");
  w.block(`module ${SLOT_TEXT_MODULE}`, () => {
    w.doc("The pulled complication `c`, of type `t`, as display text, or null when\nit has no reading.  `unit` and `short` are the element's own keys.");
    w.block("function reading(t as Complications.Type, c as Complications.Complication,\n                     unit as Boolean, short as Boolean) as String?", () => {
      w.line("var value = c.value;");
      w.block("if (value == null)", () => w.line("return null;"));
      w.block("if (value instanceof Lang.String)", () => {
        const stringCases = new Map<string, string>();
        for (const name of names) {
          const shortened = ({ training_status: "trainingShort(value)", high_low: "WfbReading.highLowShort(value)" } as Record<string, string>)[kinds.get(name)!];
          const variants = wordedVariants(face, kinds.get(name)!);
          if (shortened !== undefined && variants.has(true)) stringCases.set(name, variantExpression(variants, shortened, "value"));
        }
        if (stringCases.size > 0) {
          w.block("switch (t)", () => {
            for (const [name, expression] of stringCases) w.line(`case ${constant.get(name)}: return ${expression};`);
          });
        }
        w.line("return value;");
      });
      if (names.some((n) => READS_SETTINGS.has(kinds.get(n)!))) w.line("var settings = System.getDeviceSettings();");
      const numeric = names.filter((n) => !(complications.WORDED.has(kinds.get(n)!) && kinds.get(n) !== "condition"));
      if (numeric.length > 0) {
        const groups = new Map<string, string[]>();
        for (const name of numeric) {
          const kind = kinds.get(name)!;
          let expression: string;
          if (kind === "count") {
            const suffix = complications.COUNT_UNIT.get(name) ?? "";
            expression = !suffix ? "WfbReading.count(value, c.unit)"
              : `WfbReading.suffixed(WfbReading.count(value, c.unit), unit ? "${suffix}" : "", short)`;
          } else if (kind === "condition") {
            expression = variantExpression(conditions, "conditionShort(value.toNumber())", "conditionName(value.toNumber())");
          } else {
            expression = NUMERIC_READING[kind]!;
          }
          if (!groups.has(expression)) groups.set(expression, []);
          groups.get(expression)!.push(name);
        }
        w.block("switch (t)", () => {
          for (const [expression, members] of groups) {
            for (const name of members.slice(0, -1)) w.line(`case ${constant.get(name)}:`);
            w.line(`case ${constant.get(members[members.length - 1]!)}: return ${expression};`);
          }
        });
      }
      w.comment("no rule of its own: an app's complication, under choices: any");
      w.line("return WfbReading.suffixed(WfbReading.formatValue(value),");
      w.line('        unit ? WfbReading.unitSuffix(c.unit) : "", short);');
    });
    w.blank();
    if (conditions.has(true)) emitConditionTable(w, "conditionShort", true);
    if (conditions.has(false)) emitConditionTable(w, "conditionName", false);
    if (training.has(true)) {
      w.doc("A training status's short form, in the case the device reported it.");
      w.block("function trainingShort(status as String) as String", () => {
        w.block("switch (status.toUpper())", () => {
          for (const [status, short] of complications.TRAINING_STATUS_SHORT) w.line(`case "${status}": return WfbReading.inCaseOf("${short}", status);`);
          w.line("default: return status;");
        });
      });
    }
  });
  return { path: `source/${SLOT_TEXT_MODULE}.mc`, text: w.render() };
}

/** `holdTargetFor<Id>()`: the public getter `on_hold: auto` on a data element compiles to. */
export function emitDataHoldMethod(w: WriterType, placed: PlacedData, guards: Guards = NO_GUARDS): void {
  const element = placed.element;
  const field = configField(`data_${element.slot}`);
  const returnType = guards.complications ? "Complications.Id?" : "Complications.Id";
  w.blank();
  w.doc(`\`${element.id}\`'s current pick, for the delegate's 'on_hold: auto' ->\n`
    + "Complications.exitTo.  Whatever the wearer has this slot pointed at right\n"
    + "now, read fresh -- never a fixed type baked in at build time.");
  w.block(`function ${dataHoldMethod(element.id)}() as ${returnType}`, () => w.line(`return ${field};`));
}

/** `iconFor<Id>(t)`: one slot's picked type to its icon's catalogue name. */
export function emitDataIconMethod(w: WriterType, resolved: ResolvedFace, placed: PlacedData): void {
  const element = placed.element;
  const slot = resolved.face.config_data.get(element.slot)!;
  const mapped = slot.icons;
  const names = slot.choices !== "any" ? slot.choices : sortedNames(mapped.keys());
  const follows = slot.conditionIcons;
  w.blank();
  w.doc(`\`${element.id}\`'s icon, chosen from the wearer's picked type -- not from\n`
    + "the reading, so it still shows on a frame the reading could not be pulled.\n"
    + "A weather type's icon follows the pulled condition when there is one.");
  w.block(`private function ${dataIconMethod(element.id)}(t as Complications.Type,\n            pulled as Complications.Complication?) as String?`, () => {
    if (follows.size > 0) w.line("var value = (pulled != null) ? pulled.value : null;");
    w.block("switch (t)", () => {
      for (const name of names) {
        const icon = mapped.get(name);
        if (icon === undefined) continue;
        const ctype = complications.TYPES.get(name)!;
        if (follows.has(name)) {
          w.line(`case Complications.${ctype.constant}: return (value instanceof Lang.Number) ? WfbWeather.chooseIcon(value) : "${icon.key}";`);
        } else {
          w.line(`case Complications.${ctype.constant}: return "${icon.key}";`);
        }
      }
      w.line("default: return null;");
    });
  });
  w.blank();
}
