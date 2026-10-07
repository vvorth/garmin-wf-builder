// What the editor's inspector and Face panel show: an element's keys as
// widgets, and the face's colours, styles, fonts and targets.
//
// The inspector is generated from the published schema, so it offers
// exactly the keys the format has for the element's `type:`. A key's widget
// follows from the `$defs` entry its schema names (`length`, `angle`,
// `align`, a colour, `position`, `size`) or else its JSON type; a key no
// widget covers is shown as its text, edited in the YAML. A shape's keys
// are narrowed to its own, since the schema lists every shape key on every
// shape.
//
// Values are the author's, read from the text: what the author wrote, in
// their units, or nothing when the key is absent.
import { BASE_API_LEVEL } from "../build.ts";
import * as catalog from "../catalog.ts";
import * as complications from "../complications.ts";
import { compareVersions, type Device, type DeviceDatabase, DeviceError } from "../devices/device.ts";
import * as colors from "../edit/colors.ts";
import { selectorPaths } from "../edit/geometry.ts";
import * as hands from "../edit/hands.ts";
import { slotDrawers } from "../edit/patch.ts";
import { indexFor, type Path, Refused, type SpanIndex } from "../edit/spans.ts";
import { elementTypes } from "../edit/structure.ts";
import { WholeFloat } from "../edit/yaml.ts";
import * as icons from "../icons.ts";
import { SHAPE_GEOMETRY_KEYS } from "../kinds/shape.ts";
import { Color, ColorError, MIP64_NAMED } from "../palette.ts";
import { hasSkin } from "../preview.ts";
import { DATA_SAMPLE } from "../sample.ts";
import * as series from "../series.ts";
import { schema } from "../validate.ts";
import { jsonDumps } from "./json.ts";

type Json = Record<string, unknown>;

/** The keys an override may patch: edited with the "all targets / this device / this shape" chooser. */
export const GEOMETRY: ReadonlySet<string> = new Set(["at", "size", "radius", "align"]);

/** `$defs` entries that pick a widget, by the name the schema refers to. */
const WIDGET_BY_REF: Record<string, string> = {
  length: "length", handLength: "length", patternLength: "length",
  angle: "angle",
  align: "align",
  colorExpression: "color", colorRef: "color", color: "color", hexColor: "color", swatchColor: "color",
  visible: "expression", expression: "expression",
};
/** Objects shown as their own keys, one level down. */
const NESTED = new Set(["position", "size"]);
/** Keys the inspector leaves out: structure, and the overrides the chooser writes. */
const SKIPPED = new Set(["children", "overrides"]);

const isMap = (v: unknown): v is Map<unknown, unknown> => v instanceof Map;
const g = (m: unknown, k: unknown): unknown => (m instanceof Map ? m.get(k) : undefined);
const keysOf = (m: unknown): unknown[] => (m instanceof Map ? [...m.keys()] : []);
const isScalar = (v: unknown): boolean => typeof v === "string" || typeof v === "number" || typeof v === "boolean" || v instanceof WholeFloat;

function refName(node: Json): string | null {
  const ref = node["$ref"];
  return typeof ref === "string" ? ref.slice(ref.lastIndexOf("/") + 1) : null;
}

/** The first `$defs` name `node` refers to, and the schema it ends at. */
function deref(node: Json): [string | null, Json] {
  const first = refName(node);
  const defs = schema()["$defs"] as Record<string, Json>;
  for (let seen = 0; refName(node) !== null && seen < 10; seen++) node = defs[refName(node)!]!;
  return [first, node];
}

/** The schema branch for elements of `type`. */
export function elementSchema(type: string): Json | null {
  const defs = schema()["$defs"] as Record<string, Json>;
  for (const option of defs["element"]!["oneOf"] as Json[]) {
    const [, branch] = deref(option);
    if (((branch["properties"] as Json | undefined)?.["type"] as Json | undefined)?.["const"] === type) return branch;
  }
  return null;
}

function hidden(type: string): Set<string> {
  if (!SHAPE_GEOMETRY_KEYS.has(type)) return new Set();
  const every = new Set([...SHAPE_GEOMETRY_KEYS.values()].flatMap((s) => [...s]));
  const own = SHAPE_GEOMETRY_KEYS.get(type)!;
  const out = new Set([...every].filter((k) => !own.has(k)));
  if (type !== "arc") {
    out.add("start_angle");
    out.add("sweep");
  }
  return out;
}

function widget(key: string, type: string, node: Json): [string, Json] {
  const [ref, resolved] = deref(node);
  if (key === "type") return ["readonly", resolved];
  if ((ref !== null && NESTED.has(ref)) || (key === "icon" && type === "data")) return ["object", resolved];
  if (ref !== null && ref in WIDGET_BY_REF) return [WIDGET_BY_REF[ref]!, resolved];
  if (key === "text" && type === "text") return ["template", resolved];
  if (key === "slot") return ["slot", resolved];
  if (key === "set" && type === "hands") return ["handset", resolved];
  if (key === "font") return ["font", resolved];
  if (key === "icon") return ["icon", resolved];
  if (key === "on_hold") return ["complication", resolved];
  if ("enum" in resolved) return ["enum", resolved];
  const kind = resolved["type"];
  if (kind === "boolean") return ["bool", resolved];
  if (kind === "integer" || kind === "number") return ["number", resolved];
  if (kind === "string") return ["text", resolved];
  return ["yaml", resolved];
}

function field(key: string, path: Path, type: string, node: Json, value: unknown, required: boolean): Json {
  const [kind, resolved] = widget(key, type, node);
  const out: Json = {
    key, path: [...path], widget: kind, description: node["description"] || resolved["description"] || "",
    value, present: value !== null && value !== undefined, required,
    default: "default" in resolved ? resolved["default"] : node["default"] ?? null,
    geometry: path.length > 0 ? GEOMETRY.has(String(path[0])) : false,
  };
  if (value === undefined) out["value"] = null;
  if ("enum" in resolved) out["enum"] = resolved["enum"];
  if (kind === "object") {
    const props = (resolved["properties"] ?? {}) as Record<string, Json>;
    out["children"] = Object.entries(props).map(([k, sub]) => field(k, [...path, k], type, sub, isMap(value) ? value.get(k) ?? null : null, false));
  }
  if (["icon", "complication", "color", "yaml"].includes(out["widget"] as string) && value !== null && value !== undefined && !isScalar(value)) {
    out["widget"] = "yaml";
  }
  if (out["widget"] === "yaml" && value !== null && value !== undefined) out["text"] = typeof value === "string" ? value : jsonDumps(value);
  return out;
}

function dataAt(data: unknown, path: Path): unknown {
  for (const step of path) {
    if (isMap(data) && data.has(step)) data = data.get(step);
    else if (Array.isArray(data) && typeof step === "number" && step >= -data.length && step < data.length) data = data.at(step);
    else return null;
  }
  return data;
}

/** The inspector for the element at `element`: its fields in schema order, and each geometry key's overrides on `device`. */
export function inspect(text: string, element: Path, device: Device | null): Json {
  const index = indexFor(text);
  const data = dataAt(index.data, element);
  if (!isMap(data) || !data.has("type")) return { element: [...element], fields: [], error: "not an element" };
  const type = String(data.get("type"));
  const branch = elementSchema(type) ?? { properties: {} };
  const hide = hidden(type);
  const required = new Set((branch["required"] ?? []) as string[]);
  const props = (branch["properties"] ?? {}) as Record<string, Json>;
  const order = [...[...data.keys()].filter((k) => typeof k === "string" && k in props) as string[], ...Object.keys(props).filter((k) => !data.has(k))];
  const fields = order
    .filter((k) => !SKIPPED.has(k) && (!hide.has(k) || data.has(k))
      && (data.has(k) || !String(props[k]!["description"] ?? "").startsWith("Not accepted")))
    .map((k) => field(k, [k], type, props[k]!, data.has(k) ? data.get(k) : null, required.has(k)));
  const unknown = [...data.keys()].filter((k) => !(String(k) in props));
  const overrides: Json = {};
  if (device !== null) {
    const [deviceSel, shapeSel] = selectorPaths(device);
    for (const [scope, selector] of [["device", deviceSel], ["shape", shapeSel]] as const) {
      const patch = dataAt(data, selector);
      if (isMap(patch)) overrides[scope] = { selector: selector[1], keys: patch };
    }
  }
  return {
    element: [...element], id: element[element.length - 1], type, fields, unknown, overrides,
    device: device?.id ?? null, shape: device?.shape ?? null,
  };
}

// -- the Face panel --

/** The devices whose panel would dither `value`. */
function legalOn(value: unknown, devices: readonly Device[]): string[] {
  let color: Color;
  try {
    color = Color.parse(value);
  } catch (error) {
    if (error instanceof ColorError) return [];
    throw error;
  }
  return devices.filter((d) => !color.isPaletteLegal(d.displayColors)).map((d) => d.id);
}

function slots(index: SpanIndex): Json[] {
  const out: Json[] = [];
  const entries = g(g(index.data, "config"), "slots");
  for (const name of keysOf(entries)) {
    const entry = isMap(g(entries, name)) ? g(entries, name) : new Map();
    const raw = g(entry, "choices");
    const choices = Array.isArray(raw)
      ? raw.map((c) => (isMap(c) ? { type: c.get("type") ?? null, icon: c.get("icon") ?? null } : { type: c, icon: null }))
      : raw ?? null;
    out.push({ name, label: g(entry, "label") ?? null, default: g(entry, "default") ?? null, choices, drawn_by: slotDrawers(index, String(name)) });
  }
  return out;
}

function automatic(name: string, value: unknown): boolean {
  try {
    return colors.isAutomatic(name, value as string);
  } catch (error) {
    if (error instanceof Refused) return false;
    throw error;
  }
}

function problem(value: unknown): string | null {
  try {
    colors.hexOf(value);
  } catch (error) {
    if (error instanceof Refused) return error.message;
    throw error;
  }
  return null;
}

function axes(data: unknown): Json {
  const config = g(data, "config");
  const out: Json = {};
  for (const [axis, role] of [["accent_color", "accent"], ["data_color", "data"]] as const) {
    const entry = g(config, axis);
    if (!isMap(entry)) {
      out[axis] = null;
      continue;
    }
    const raw = entry.get("choices");
    const choices = typeof raw === "string" ? raw : (Array.isArray(raw) ? raw : []).map((c) => (isMap(c) ? c.get("color") : c));
    out[axis] = { default: entry.get("default") ?? null, choices, raw: raw ?? null, role: entry.get("role") || role, own_role: entry.has("role") };
  }
  return out;
}

/** The face's colours, schemes, styles, layouts, fonts, slots and targets. */
export function globalsOf(text: string, db: DeviceDatabase): Json {
  let index: SpanIndex;
  try {
    index = indexFor(text);
  } catch (error) {
    if (error instanceof Refused) return {};
    throw error;
  }
  const data = index.data;
  if (!isMap(data)) return {};
  const targets = (g(g(data, "build"), "targets") ?? []) as unknown[];
  const devices: Device[] = [];
  const targetProblems: Record<string, string> = {};
  for (const target of Array.isArray(targets) ? targets : []) {
    try {
      devices.push(db.get(String(target)));
    } catch (error) {
      if (!(error instanceof DeviceError)) throw error;
      targetProblems[String(target)] = error.message;
    }
  }
  const resources = g(data, "resources");
  const palette = keysOf(g(resources, "palette")).map((name) => {
    const entry = g(g(resources, "palette"), name);
    const value = isMap(entry) ? entry.get("value") : entry;
    return {
      name, value, label: isMap(entry) ? entry.get("label") ?? null : null, long: isMap(entry),
      dithers_on: legalOn(value, devices), used_by: colors.userNames(index, String(name)),
      automatic: automatic(String(name), value), problem: problem(value), launcher: colors.LAUNCHER.has(String(name)),
    };
  });
  const schemes = g(g(data, "theme"), "schemes");
  const roles: unknown[] = [];
  for (const scheme of keysOf(schemes).map((k) => g(schemes, k))) {
    for (const role of keysOf(g(scheme, "colors"))) if (!roles.includes(role)) roles.push(role);
  }
  const style = g(g(data, "config"), "style");
  const fonts = keysOf(g(resources, "fonts")).map((name) => {
    const spec = g(g(resources, "fonts"), name);
    return { name, source: g(spec, "source") ?? null, face: g(spec, "face") ?? null, size: g(spec, "size") ?? null };
  });
  return {
    palette,
    schemes: {
      names: keysOf(schemes), roles,
      colors: Object.fromEntries(keysOf(schemes).map((n) => [String(n), g(g(schemes, n), "colors") ?? new Map()])),
    },
    styles: {
      default: g(style, "default") ?? null,
      entries: keysOf(g(style, "choices")).map((n) => {
        const e = g(g(style, "choices"), n);
        return { name: n, ...(isMap(e) ? Object.fromEntries([...e].map(([k, v]) => [String(k), v])) : {}) };
      }),
    },
    layouts: keysOf(g(data, "layouts")),
    fonts,
    slots: slots(index),
    roles: colors.roles(index),
    axes: axes(data),
    displays: [...new Set(devices.map((d) => d.displayColors).filter((c): c is number => Boolean(c)))].sort((a, b) => a - b),
    hand_sets: keysOf(g(resources, "hand_sets")),
    hands: hands.summary(index),
    targets,
    target_problems: targetProblems,
  };
}

function complicationType(name: string): Json {
  const sample = DATA_SAMPLE.get(name);
  return {
    name, label: complications.label(name), category: complications.category(name),
    icon: icons.COMPLICATION_ICON.get(name) ?? null,
    sample: sample !== undefined && sample !== null ? complications.formatReading(name, sample) : null,
  };
}

let words: Json | null = null;

/** What the pickers offer: data sources by namespace, icon names and complication types. Device-independent. */
export function vocabulary(): Json {
  if (words === null) {
    words = {
      sources: Object.fromEntries(catalog.namespaces()),
      icons: [...icons.CATALOG.keys()].sort(),
      complications: ["auto", ...complications.names()],
      series: series.names(),
      types: elementTypes(),
      mip: MIP64_NAMED.map(([name, value, label]) => ({ name, value, label })),
      hand_presets: [...hands.presets().keys()],
      categories: [...complications.CATEGORIES],
      complication_types: complications.names().map(complicationType),
      icon_glyphs: Object.fromEntries([...icons.CATALOG].map(([name, icon]) => [name, icon.codepoint.codePointAt(0)])),
    };
  }
  return words;
}

/** Every installed device that can run a face, for the targets list, and every one whose files could not be read. */
export function devices(db: DeviceDatabase): [Json[], { id: string; reason: string }[]] {
  const out: Json[] = [];
  const unreadable: { id: string; reason: string }[] = [];
  for (const id of db.ids()) {
    let device: Device;
    try {
      device = db.get(id);
      if (!device.supportsWatchface || compareVersions(device.apiLevel, BASE_API_LEVEL) < 0) continue;
    } catch (error) {
      unreadable.push({ id, reason: (error as Error).message });
      continue;
    }
    const ppi = device.simulator["ppi"];
    out.push({
      id: device.id, name: (device.compiler["displayName"] as string | undefined) || device.id, shape: device.shape,
      size: `${device.width}x${device.height}`, width: device.width, height: device.height,
      ppi: typeof ppi === "number" && ppi > 0 ? ppi : null, skin: hasSkin(device), display: device.displayType,
      fonts: [...device.systemFonts.keys()],
    });
  }
  const name = (d: Json): string => String(d["name"]).toLowerCase();
  return [out.sort((a, b) => (name(a) < name(b) ? -1 : name(a) > name(b) ? 1 : 0)), unreadable];
}

