// What a design's catalogue bindings and features need from a target
// device, checked against that device's own symbol table, never an API
// level. Port of wfb/availability.py.
//
// Codegen needs the aggregate over a build's targets (`computeGuards`: which
// guards the one shared view must carry); the lint needs the per-element,
// per-device detail (`sourceUnavailable`, `readerUnavailable`). A binding a
// target lacks reads as absent there, like every nullable source.
import { CATALOG, READERS, type Source } from "./catalog.ts";
import { Device, DeviceError } from "./devices/device.ts";
import { CONFIG_SYMBOL, type Element, type Face, type FontSpec, Graph } from "./ir/model.ts";
import * as kinds from "./kinds/index.ts";
import { ACQUISITION } from "./series.ts";

/** The override the settings menu hangs off; absent on fenix5/fenix5x. */
export const SETTINGS_MENU_SYMBOL = "Toybox.Application.AppBase.getSettingsView";

/** Why one thing a design uses is unavailable on one device: a `module`, a `function` or a `field`. */
export class Unavailable {
  readonly kind: string;
  readonly symbol: string;
  readonly reason: string;

  constructor(kind: string, symbol: string, reason: string) {
    this.kind = kind;
    this.symbol = symbol;
    this.reason = reason;
  }
}

export function moduleUnavailable(module: string, device: Device): Unavailable | null {
  return device.hasModule(module) ? null : new Unavailable("module", module, `Toybox.${module} is absent on ${device.id}`);
}

function symbolGap(symbol: string, device: Device): Unavailable | null {
  return device.hasSymbol(symbol) ? null : new Unavailable("function", symbol, `${symbol} is absent on ${device.id}`);
}

function fieldGap(field: string, device: Device): Unavailable | null {
  return device.hasField(field) ? null : new Unavailable("field", field, `field '${field}' is absent on ${device.id}`);
}

/** Is `READERS[readerName]`'s call unavailable on `device`: its module first, then its function symbols. */
export function readerUnavailable(readerName: string, device: Device): Unavailable | null {
  const reader = READERS.get(readerName)!;
  if (reader.requires_module !== null) {
    const gap = moduleUnavailable(reader.requires_module, device);
    if (gap !== null) return gap;
  }
  for (const symbol of reader.requires) {
    const gap = symbolGap(symbol, device);
    if (gap !== null) return gap;
  }
  return null;
}

/** The bare field name `hasField` checks for `source`: the first dotted segment, or `null` for no field. */
function fieldRoot(source: Source): string | null {
  return source.field_name === null ? null : source.field_name.split(".", 1)[0]!;
}

/** Is the catalogue path unavailable on `device`, and why: its reader, its own requirements, then its field. */
export function sourceUnavailable(path: string, device: Device): Unavailable | null {
  const source = CATALOG.get(path);
  if (source === undefined) return null;
  const gap = readerUnavailable(source.reader, device);
  if (gap !== null) return gap;
  for (const symbol of source.requires) {
    const found = symbolGap(symbol, device);
    if (found !== null) return found;
  }
  const root = fieldRoot(source);
  return root === null ? null : fieldGap(root, device);
}

/** Every catalogue path this design's bound expressions read. */
export function designPaths(face: Face): Set<string> {
  const paths = new Set<string>();
  for (const element of face.walk()) for (const expression of element.expressions()) for (const p of expression.sources) paths.add(p);
  return paths;
}

/** Bare field names this design's bound sources read off a reader (a complication contributes none). */
export function designFields(face: Face): Set<string> {
  const fields = new Set<string>();
  for (const path of designPaths(face)) {
    const source = CATALOG.get(path);
    if (source === undefined || READERS.get(source.reader)!.complication_type !== null) continue;
    const root = fieldRoot(source);
    if (root !== null) fields.add(root);
  }
  return fields;
}

/** The `:face` a `face:` font resolves to on `device`, or `""`: the font object's own construction viability. */
export function vectorFontFace(spec: FontSpec, device: Device): string {
  if (!device.hasSymbol(Device.VECTOR_FONT_SYMBOL)) return "";
  for (const name of spec.face ?? []) if (device.scalableFaces.includes(name)) return name;
  return "";
}

/** Every declared `face:` font a text element or a pattern text part uses, in declaration order. */
export function vectorFontsUsed(face: Face): Map<string, FontSpec> {
  const named = new Set(kinds.faceTextRuns(face).filter(([, run]) => run.icon === null && !run.aod_only).map(([, run]) => run.font));
  return new Map([...face.fonts].filter(([name, spec]) => named.has(name) && spec.isVector));
}

/** Does this design need `Toybox.Complications`: a complication source, a `config: data:` slot, or any `on_hold:`. */
export function usesComplications(face: Face): boolean {
  return [...face.requirements().readers].some((name) => READERS.get(name)!.requires_module === "Complications")
    || face.config_data.size > 0
    || face.walk().some((element) => element.on_hold !== null);
}

/** Every bare `Toybox` module the shared code can guard with `Toybox has :<Module>`. */
export function modulesUsed(face: Face): Set<string> {
  const modules = new Set<string>();
  for (const name of face.requirements().readers) {
    const module = READERS.get(name)!.requires_module;
    if (module !== null) modules.add(module);
  }
  if (usesComplications(face)) modules.add("Complications");
  for (const element of face.walk()) {
    if (element instanceof Graph && element.series_def !== null
      && (element.series_def.acquisition === "hourly_forecast" || element.series_def.acquisition === "daily_forecast")) {
      modules.add(ACQUISITION[element.series_def.acquisition].module.replace(/^Toybox\./, ""));
    }
  }
  return modules;
}

/** What the one generated view/delegate, shared across every target, must guard against. */
export interface Guards {
  /** Some target lacks `Toybox.Complications`, which the design uses. */
  complications: boolean;
  /** Bare field names the design reads that some target lacks. */
  fields: ReadonlySet<string>;
  /** Used `face:` fonts some target fails to resolve. */
  vector_fonts: ReadonlySet<string>;
  /** Some target is AMOLED. */
  amoled_target: boolean;
  /** An AMOLED build where some target lacks `requiresBurnInProtection`. */
  burn_in_field_guarded: boolean;
  /** An AMOLED build where some target lacks `System.getDisplayMode`. */
  display_mode_guarded: boolean;
  /** Used modules some target lacks. */
  modules: ReadonlySet<string>;
  /** No target supports `onPartialUpdate`. */
  partial_update_unsupported: boolean;
  /** `config:` and some target has the settings menu but no native editor. */
  config_menu: boolean;
  /** Elements in the subscreen window, when some target has none. */
  subscreen_hidden: ReadonlySet<string>;
}

/** The "nothing is missing" `Guards`. */
export const NO_GUARDS: Guards = {
  complications: false, fields: new Set(), vector_fonts: new Set(), amoled_target: false, burn_in_field_guarded: false,
  display_mode_guarded: false, modules: new Set(), partial_update_unsupported: false, config_menu: false, subscreen_hidden: new Set(),
};

/** Every element laid out in the subscreen window: each top-level `anchor: subscreen` element and its subtree. */
export function subscreenElementIds(face: Face): Set<string> {
  const out = new Set<string>();
  const add = (element: Element): void => {
    out.add(element.id);
    for (const child of element.children()) add(child);
  };
  for (const element of face.elements) if (element.inSubscreen) add(element);
  return out;
}

/** `device.hasSymbol(symbol)`, false when its symbol table is missing or unreadable. */
function has(device: Device, symbol: string): boolean {
  try {
    return device.hasSymbol(symbol);
  } catch (error) {
    if (error instanceof DeviceError) return false;
    throw error;
  }
}

/** The `Guards` the shared generated code needs for `face`, across every device in a build. */
export function computeGuards(face: Face, devices: readonly Device[]): Guards {
  const missingModules = new Set([...modulesUsed(face)].filter((m) => devices.some((d) => !d.hasModule(m))));
  const missingFields = new Set([...designFields(face)].filter((f) => devices.some((d) => !d.hasField(f))));
  const unavailableVectorFonts = new Set([...vectorFontsUsed(face)]
    .filter(([, spec]) => devices.some((d) => vectorFontFace(spec, d) === "")).map(([name]) => name));
  const amoledTarget = devices.some((d) => d.isAmoled);
  return {
    complications: missingModules.has("Complications"),
    fields: missingFields,
    vector_fonts: unavailableVectorFonts,
    amoled_target: amoledTarget,
    burn_in_field_guarded: amoledTarget && devices.some((d) => !d.hasField(Device.BURN_IN_FIELD)),
    display_mode_guarded: amoledTarget && devices.some((d) => !d.hasSymbol(Device.DISPLAY_MODE_SYMBOL)),
    modules: missingModules,
    partial_update_unsupported: !devices.some((d) => d.supportsPartialUpdate),
    config_menu: face.hasConfig && devices.some((d) => !has(d, CONFIG_SYMBOL) && has(d, SETTINGS_MENU_SYMBOL)),
    subscreen_hidden: devices.some((d) => d.subscreen === null) ? subscreenElementIds(face) : new Set(),
  };
}
