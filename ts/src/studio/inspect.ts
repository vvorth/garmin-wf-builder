// What the editor's inspector and Face panel show: an element's keys as a
// field tree, each with the value the editing context reads, and the face's
// colours, styles, layouts, fonts and targets.
//
// The inspector is generated from the published schema, so it offers
// exactly the keys the format has for the element's `type:`, each as its
// schema branch says: a scalar with the control its `$defs` entry picks
// (`length`, `angle`, `align`, a colour, an expression) or else its JSON
// type, an object with every property, a list with its items, or a choice
// between branches. Only a key the schema does not have is raw (`unknown`).
// A shape's keys are narrowed to its own, since the schema lists every
// shape key on every shape, and a part's to its type's the same way.
//
// The path inspected may name a hand of a hand set, or a part of a hand, a
// pattern or a needle (`subject`): the fields are then the hand's (`color`,
// `parts`) or the part's own schema branch (`handPart`, `patternPart`),
// read as written, since neither has overrides or an `aod:` block. It may
// also name a `resources: fonts:` entry (`subject` "font"): the fields of
// its branch, `bakedFont` with a `source:` and `vectorFont` with a `face:`,
// without the keys the schema marks a build error on that branch.
//
// Values are the author's, read from the text: what the author wrote, in
// their units, or nothing when the key is absent. Beside each, `effective`
// is what the editing context reads there: awake, the most specific
// override the viewed device has, else the element's own key; in the
// always-on frame, the `aod:` cascade the compiler resolves
// (`ir/builder/aod.ts`): the element's own block, else the nearest ancestor
// group's, else `defaults: {aod:}` for `visible` and `dim`, else the awake
// value.
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
import { SUPPRESSIBLE } from "../lint.ts";
import { HAND_PART_FILLED_SHAPES, HAND_PART_GEOMETRY_KEYS, PATTERN_PART_GEOMETRY_KEYS } from "../ir/builder/hands.ts";
import type { Face } from "../ir/model.ts";
import { SHAPE_GEOMETRY_KEYS } from "../kinds/shape.ts";
import { subjectOf } from "./parts.ts";
import { Color, ColorError, MIP64_NAMED } from "../palette.ts";
import { hasSkin } from "../preview.ts";
import { DATA_SAMPLE } from "../sample.ts";
import { DATE_CODES, DURATION_CODES, TIME_CODES } from "../formatting.ts";
import * as series from "../series.ts";
import { schema } from "../validate.ts";
import { jsonDumps, plain } from "./json.ts";
import type {
  Axes, AxisEntry, Capability, ComplicationType, DeviceInfo, EditContext, Effective, Field, FieldKind, FormatCode, Globals, HandSet, IconSpelling, Inspect, LayoutEntry,
  OverrideSummary, PartsSummary, RuleFamily, SlotEntry, StyleEntry, UnreadableDevice, Value, Widget, Words,
} from "./protocol.ts";

/** A schema node, as JSON. */
type Json = Record<string, unknown>;

/** Author data as the answer carries it: a mapping an object, a whole float a number. */
const value = (data: unknown): Value => plain(data ?? null) as Value;
/** A mapping as an object of values; anything else is empty. */
const mapping = (data: unknown): Record<string, Value> => (data instanceof Map ? plain(data) as Record<string, Value> : {});
/** A name as written, when it is text. */
const name = (data: unknown): string | null => (typeof data === "string" ? data : null);
/** An icon as written: a name, or `{codepoint}`. */
const iconSpelling = (data: unknown): IconSpelling | null =>
  typeof data === "string" ? data : isMap(data) && typeof data.get("codepoint") === "string" ? { codepoint: String(data.get("codepoint")) } : null;

/** The keys an override may patch: edited with the "all targets / this device / this shape / this display class" chooser. */
export const GEOMETRY: ReadonlySet<string> = new Set(["at", "size", "radius", "align"]);

/** The editing context when none is given: the awake frame, the face's default style. */
export const AWAKE: EditContext = { frame: "awake", style: null };

/** How deep the field tree follows the schema below an element's own keys. */
const MAX_DEPTH = 6;

/** `$defs` entries that pick a scalar's control, by the name the schema refers to. */
const WIDGET_BY_REF: Record<string, Widget> = {
  length: "length", handLength: "length", patternLength: "length",
  angle: "angle",
  // a segmented gauge's gap: a length, or an angle on an arc
  gaugeGap: "gap",
  align: "align",
  colorExpression: "color", colorRef: "color", color: "color", hexColor: "color", swatchColor: "color",
  visible: "expression", partVisible: "expression", expression: "expression",
  // a text's `font:`: a name, or the font written inline
  fontRef: "font",
};
/** `$defs` entries whose value may be a rule list, and of which family. */
const RULES_BY_REF: Record<string, RuleFamily> = { expression: "value", colorExpression: "color", visible: "boolean", partVisible: "boolean" };
/** Keys the inspector leaves out: the layer tree owns an element's `children:`. */
const SKIPPED = new Set(["children"]);

const isMap = (v: unknown): v is Map<unknown, unknown> => v instanceof Map;
const g = (m: unknown, k: unknown): unknown => (m instanceof Map ? m.get(k) : undefined);
const keysOf = (m: unknown): unknown[] => (m instanceof Map ? [...m.keys()] : []);
const isScalar = (v: unknown): boolean => typeof v === "string" || typeof v === "number" || typeof v === "boolean" || v instanceof WholeFloat;

function refName(node: Json): string | null {
  const ref = node["$ref"];
  return typeof ref === "string" ? ref.slice(ref.lastIndexOf("/") + 1) : null;
}

/**
 * `node` with its `$ref`s followed through `$defs`, and an `allOf` whose
 * first branch is a `$ref` read as that branch (the shared shape, with the
 * kind's own restriction beside it): the first `$defs` name met, and the
 * schema it ends at.
 */
function deref(node: Json): [string | null, Json] {
  const defs = schema()["$defs"] as Record<string, Json>;
  let first: string | null = null;
  for (let seen = 0; seen < 10; seen++) {
    const ref = refName(node);
    if (ref !== null) {
      first ??= ref;
      node = defs[ref]!;
      continue;
    }
    const all = node["allOf"];
    if (Array.isArray(all) && all.length > 0 && refName(all[0] as Json) !== null) {
      node = all[0] as Json;
      continue;
    }
    break;
  }
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

/** The keys an element of `type` may restyle in its `aod:` block, from the schema's per-kind `aod*` def; `visible` and `dim` are every kind's. */
export function aodKeys(type: string): string[] {
  const branch = elementSchema(type);
  const node = branch !== null ? ((branch["properties"] ?? {}) as Record<string, Json>)["aod"] : undefined;
  if (node === undefined) return [];
  const [, resolved] = deref(node);
  return Object.keys((resolved["properties"] ?? {}) as Json).filter((k) => k !== "visible" && k !== "dim");
}

/** The keys a part of `type` does not read, by the compiler's own tables: a pattern's parts have two more types than a hand's. */
function hiddenPartKeys(type: string, pattern: boolean): Set<string> {
  const table = pattern ? PATTERN_PART_GEOMETRY_KEYS : HAND_PART_GEOMETRY_KEYS;
  const own = table.get(type) ?? new Set<string>();
  const out = new Set([...table.values()].flatMap((keys) => [...keys]).filter((k) => !own.has(k)));
  if (type !== "polygon") out.add("mirror");
  if (!HAND_PART_FILLED_SHAPES.has(type)) out.add("filled");
  if (!["line", "arc", "circle"].includes(type)) out.add("thickness");
  return out;
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

function dataAt(data: unknown, path: Path): unknown {
  for (const step of path) {
    if (isMap(data) && data.has(step)) data = data.get(step);
    else if (Array.isArray(data) && typeof step === "number" && step >= -data.length && step < data.length) data = data.at(step);
    else return null;
  }
  return data;
}

// -- the field tree --

/** Whether `raw`'s shape is what a choice's branch admits: its const or enum, its type, and an object's required keys. */
function matches(node: Json, raw: unknown): boolean {
  const [, resolved] = deref(node);
  const same = (a: unknown, b: unknown): boolean => JSON.stringify(plain(a)) === JSON.stringify(b);
  if ("const" in resolved) return same(raw, resolved["const"]);
  if (Array.isArray(resolved["enum"])) return resolved["enum"].some((e) => same(raw, e));
  const alternatives = resolved["oneOf"] ?? resolved["anyOf"];
  if (Array.isArray(alternatives)) return alternatives.some((b) => matches(b as Json, raw));
  const types = Array.isArray(resolved["type"]) ? resolved["type"] : [resolved["type"]];
  return types.some((t) => {
    if (t === "object") return isMap(raw) && ((resolved["required"] ?? []) as string[]).every((k) => raw.has(k));
    if (t === "array") return Array.isArray(raw);
    if (t === "string") return typeof raw === "string";
    if (t === "boolean") return typeof raw === "boolean";
    if (t === "integer") return typeof raw === "number" && Number.isInteger(raw);
    if (t === "number") return typeof raw === "number" || raw instanceof WholeFloat;
    return t === undefined;
  });
}

/** What a field is, from its schema branch: its kind, a scalar's control, and the schema the branch ends at. */
function classify(key: string, type: string, path: Path, node: Json): [FieldKind, Widget, Json] {
  const [ref, resolved] = deref(node);
  const scalar = (widget: Widget): [FieldKind, Widget, Json] => ["scalar", widget, resolved];
  const kind = resolved["type"];
  if (key === "type" && path.length === 1) return scalar("readonly");
  if (ref !== null && ref in WIDGET_BY_REF) return scalar(WIDGET_BY_REF[ref]!);
  // the templates: a text's own, a pattern text part's, and an aod: block's restyled one
  if (key === "text" && kind === "string" && (path.length === 1 || path[0] === "parts" || path[0] === "aod")) return scalar("template");
  if (key === "series" && type === "graph" && path.length === 1) return ["scalar", "enum", { ...resolved, enum: series.names() }];
  if (key === "slot" && path.length === 1) return scalar("slot");
  if (key === "set" && type === "hands" && path.length === 1) return scalar("handset");
  if (key === "font" && kind === "string") return scalar("font");
  // a vector font's face names, one or each of a list
  if (type === "font" && path[0] === "face" && kind === "string") return scalar("face");
  // an element's icon: a name or a {codepoint}, one picker (a data element's icon: is the block placing the pick's own)
  if (key === "icon" && type !== "data" && (kind === "string" || Array.isArray(resolved["oneOf"]))) return scalar("icon");
  // a data element's hold opens the wearer's own pick, so `auto` is its only target
  if (key === "on_hold" && path.length === 1) return ["scalar", "complication", { ...resolved, enum: type === "data" ? ["auto"] : ["auto", ...complications.names()] }];
  if ("enum" in resolved) return scalar("enum");
  if ("const" in resolved) return ["scalar", "enum", { ...resolved, enum: [resolved["const"]] }];
  if (Array.isArray(resolved["oneOf"]) || Array.isArray(resolved["anyOf"])) return ["choice", "text", resolved];
  if (kind === "object") return ["object", "object", resolved];
  if (kind === "array") return ["list", "yaml", resolved];
  if (kind === "boolean") return scalar("bool");
  if (kind === "integer" || kind === "number") return scalar("number");
  return scalar("text");
}

/** What `inspect` reads an element's keys against: the element, the device viewed, the context, and the `aod:` cascade round it. */
interface Reading {
  type: string;
  data: Map<unknown, unknown>;
  device: Device | null;
  context: EditContext;
  aodKeys: Set<string>;
  cascade: Cascade;
}

function field(r: Reading, key: string, path: Path, node: Json, raw: unknown, required: boolean, depth: number): Field {
  const [kind, widget, resolved] = classify(key, r.type, path, node);
  const present = raw !== null && raw !== undefined;
  const out: Field = {
    key, path: [...path], kind, widget, description: String(node["description"] || resolved["description"] || ""),
    value: value(raw), present, required,
    default: value("default" in resolved ? resolved["default"] : node["default"]),
    geometry: path.length > 0 && GEOMETRY.has(String(path[0])),
    effective: effectiveOf(r, path),
  };
  if (depth > MAX_DEPTH) return { ...out, kind: "scalar", widget: "text", truncated: true };
  const rules = RULES_BY_REF[deref(node)[0] ?? ""];
  if (kind === "scalar" && rules !== undefined) out.rules = rules;
  if (kind === "scalar") {
    if (Array.isArray(resolved["enum"])) out.enum = value(resolved["enum"]) as Value[];
    // a value whose shape is not the schema's is shown as its text; an icon's `{codepoint}` is one of its spellings,
    // a rule list a conditional value's, and a font written inline a font's
    const codepoint = widget === "icon" && isMap(raw) && raw.size === 1 && typeof raw.get("codepoint") === "string";
    const ruled = rules !== undefined && Array.isArray(raw);
    const inline = widget === "font" && isMap(raw);
    if (present && !isScalar(raw) && !codepoint && !ruled && !inline) out.widget = "yaml";
  } else if (kind === "object") {
    const props = (resolved["properties"] ?? {}) as Record<string, Json>;
    const extra = resolved["additionalProperties"];
    if (Object.keys(props).length > 0) {
      const needed = new Set((resolved["required"] ?? []) as string[]);
      out.children = Object.entries(props).map(([k, sub]) => field(r, k, [...path, k], sub, isMap(raw) ? raw.get(k) ?? null : null, needed.has(k), depth + 1));
    } else if (extra !== null && typeof extra === "object") {
      // the author names the keys (`overrides:` by selector): the keys present, and the template a new key takes
      const sub = extra as Json;
      out.children = keysOf(raw).map((k) => field(r, String(k), [...path, String(k)], sub, g(raw, k), false, depth + 1));
      out.item = field(r, "", [...path, ""], sub, null, false, depth + 1);
    } else {
      out.children = [];
    }
  } else if (kind === "list") {
    const sub = (resolved["items"] ?? {}) as Json;
    const items = Array.isArray(raw) ? raw : [];
    out.items = items.map((item, i) => field(r, String(i), [...path, i], sub, item, false, depth + 1));
    out.item = field(r, String(items.length), [...path, items.length], sub, null, false, depth + 1);
  } else {
    const branches = (resolved["oneOf"] ?? resolved["anyOf"]) as Json[];
    const chosen = present ? branches.findIndex((b) => matches(b, raw)) : -1;
    out.branches = branches.map((b, i) => field(r, key, path, b, i === chosen ? raw : null, required, depth + 1));
    out.chosen = chosen >= 0 ? chosen : null;
    out.widget = out.branches[Math.max(chosen, 0)]?.widget ?? "text";
  }
  if (out.widget === "yaml" && present) out.text = typeof raw === "string" ? raw : jsonDumps(raw);
  return out;
}

// -- effective values --

/** A value a context might read, and where it would come from. */
type Source = [raw: unknown, from: Omit<Effective, "value">];

/**
 * The most specific source that has a value, with a mapping merged key by
 * key over the mappings beneath it (an override's `at: {dy}` keeps the
 * element's `anchor:`), unless `whole` says the value replaces.
 */
function layered(sources: Source[], whole = false): Effective {
  const found = sources.filter(([raw]) => raw !== null && raw !== undefined);
  if (found.length === 0) return { value: null, from: "absent" };
  const [top, from] = found[0]!;
  if (isMap(top) && !whole) {
    const merged = new Map<unknown, unknown>();
    for (const [raw] of [...found].reverse()) if (isMap(raw)) for (const [k, v] of raw) merged.set(k, v);
    return { ...from, value: value(merged) };
  }
  return { ...from, value: value(top) };
}

/** The awake rule: the viewed device's overrides, most specific first, then the element's own key. */
function awakeSources(r: Reading, path: Path): Source[] {
  const own: Source = [dataAt(r.data, path), { from: "own" }];
  if (r.device === null) return [own];
  return [...selectorPaths(r.device).map((selector): Source => [dataAt(r.data, [...selector, ...path]), { from: "override", selector: String(selector[1]) }]), own];
}

/**
 * The `aod:` blocks round an element: its own, the nearest ancestor group's
 * that wrote one (the compiler takes that block whole, never a merge of
 * several ancestors'), the face's `defaults: {aod:}`, and the group whose
 * `visible: false` hides the element's whole subtree, if any.
 */
interface Cascade {
  own: Map<unknown, unknown> | null;
  group: { id: string; aod: Map<unknown, unknown> } | null;
  defaults: Map<unknown, unknown> | null;
  hiddenBy: string | null;
}

/**
 * The cascade round the element at `element`, from the text, with the
 * compiler's own decision on the sticky hide where the face is built
 * (`Element.aod_ancestor_hidden`); the text names the group.
 */
function cascadeOf(index: SpanIndex, element: Path, data: Map<unknown, unknown>, face: Face | null): Cascade {
  const block = (node: unknown): Map<unknown, unknown> | null => (isMap(g(node, "aod")) ? g(node, "aod") as Map<unknown, unknown> : null);
  const ancestors: { id: string; aod: Map<unknown, unknown> | null }[] = [];
  for (let p = element; p.length >= 4 && p[p.length - 2] === "children"; p = p.slice(0, -2)) {
    const parent = p.slice(0, -2);
    const node = dataAt(index.data, parent);
    if (isMap(node) && node.has("type")) ancestors.push({ id: String(parent[parent.length - 1]), aod: block(node) });
  }
  const built = face?.walk().find((e) => e.id === String(element[element.length - 1]));
  let hiddenBy = ancestors.find((a) => a.aod !== null && a.aod.get("visible") === false)?.id ?? null;
  if (built !== undefined && !built.aod_ancestor_hidden) hiddenBy = null;
  const nearest = ancestors.find((a) => a.aod !== null);
  const defaults = dataAt(index.data, ["defaults", "aod"]);
  return {
    own: block(data),
    group: nearest !== undefined ? { id: nearest.id, aod: nearest.aod! } : null,
    defaults: isMap(defaults) ? defaults : null,
    hiddenBy,
  };
}

/** Whether the always-on frame draws the element: a group's `visible: false` is sticky, a block written draws it, else the face default. */
function aodVisible(c: Cascade): Effective {
  if (c.hiddenBy !== null) return { value: false, from: "group", group: c.hiddenBy };
  if (c.own !== null) return { value: value(c.own.has("visible") ? c.own.get("visible") : true), from: "aod" };
  if (c.group !== null) return { value: value(c.group.aod.has("visible") ? c.group.aod.get("visible") : true), from: "group", group: c.group.id };
  return { value: value(c.defaults?.get("visible") ?? false), from: "defaults" };
}

/** What the always-on frame reads for the key `path` of an `aod:` block: the cascade, then the awake value for a restyling key. */
function aodEffective(r: Reading, path: Path): Effective {
  const c = r.cascade;
  const key = String(path[0]);
  if (path.length === 1 && key === "visible") return aodVisible(c);
  const sources: Source[] = [];
  if (c.own !== null) sources.push([dataAt(c.own, path), { from: "aod" }]);
  if (c.group !== null) sources.push([dataAt(c.group.aod, path), { from: "group", group: c.group.id }]);
  if (path.length === 1 && (key === "visible" || key === "dim")) sources.push([g(c.defaults, key), { from: "defaults" }]);
  if (key !== "dim") sources.push(...awakeSources(r, path));
  // an aod: outline replaces the awake ring whole
  return layered(sources, key === "outline");
}

/** What the editing context reads for the key at `path` of the element. */
function effectiveOf(r: Reading, path: Path): Effective {
  if (r.context.frame !== "aod" || path.length === 0) return layered(awakeSources(r, path));
  if (path[0] === "aod") return path.length > 1 ? aodEffective(r, path.slice(1)) : layered(awakeSources(r, path));
  const key = String(path[0]);
  if (key === "visible" || r.aodKeys.has(key)) return aodEffective(r, path);
  return layered(awakeSources(r, path));
}

// -- the rest of the answer --

/** Every selector's non-geometry overrides (`color`/`track_color`/`visible`), read-only, with its line span to jump to in the YAML tab. */
function nonGeometryOverrides(index: SpanIndex, element: Path, data: unknown): OverrideSummary[] {
  const raw = isMap(data) ? data.get("overrides") : undefined;
  if (!isMap(raw)) return [];
  const out: OverrideSummary[] = [];
  for (const selector of keysOf(raw)) {
    const entry = g(raw, selector);
    if (!isMap(entry)) continue;
    const keys: Record<string, Value> = {};
    for (const k of keysOf(entry)) if (!GEOMETRY.has(String(k))) keys[String(k)] = value(entry.get(k));
    if (Object.keys(keys).length === 0) continue;
    const held = index.at([...element, "overrides", selector as string]);
    const until = Math.max(index.valueEnd(held) - 1, 0);
    out.push({
      selector: String(selector), keys,
      line: held.key.start.line + 1,
      end: (index.text.slice(0, until).match(/\n/g)?.length ?? 0) + 1,
    });
  }
  return out;
}

/** A pattern's parts, read-only: how many and of what shape, with a line span to jump to in the YAML tab. */
function patternPartsSummary(index: SpanIndex, type: string, element: Path, data: unknown): PartsSummary | null {
  if (type !== "pattern" || !isMap(data) || !data.has("parts")) return null;
  const written = data.get("parts");
  // the id-keyed mapping, or the list form kept as shorthand
  const parts = Array.isArray(written) ? written : isMap(written) ? [...written.values()] : null;
  if (parts === null) return null;
  const held = index.at([...element, "parts"]);
  const until = Math.max(index.valueEnd(held) - 1, 0);
  return {
    count: parts.length, shapes: parts.map((p) => (isMap(p) ? String(p.get("type") ?? "") : "")),
    line: held.key.start.line + 1,
    end: (index.text.slice(0, until).match(/\n/g)?.length ?? 0) + 1,
  };
}

/**
 * The inspector for the element at `element`: its fields in schema order,
 * each with what `context` reads on `device`, and each geometry key's
 * overrides there. `face` is the text built, when it loads, for the
 * compiler's own resolution of the `aod:` cascade.
 */
export function inspect(text: string, element: Path, device: Device | null, context: EditContext = AWAKE, face: Face | null = null): Inspect {
  const index = indexFor(text);
  const data = dataAt(index.data, element);
  const out: Inspect = {
    element: [...element], id: String(element[element.length - 1]), type: "", subject: "element", context: { ...context }, fields: [], unknown: [],
    aod_keys: [], overrides: {}, overridden: [], parts: null,
    device: device?.id ?? null, shape: device?.shape ?? null, display: device?.displayClass ?? null, error: null,
  };
  const font = element.length === 3 && element[0] === "resources" && element[1] === "fonts" && isMap(data);
  const subject = font ? "font" : subjectOf(index, element);
  if (subject === null || !isMap(data)) return { ...out, error: "not an element" };
  const defs = schema()["$defs"] as Record<string, Json>;
  let type: string, branch: Json, hide: Set<string>, reading: Reading;
  if (subject === "font") {
    // the branch its shape picks; a key the schema keeps on it only to name the mistake is not offered
    type = "font";
    branch = (data.has("face") && !data.has("source") ? defs["vectorFont"] : defs["bakedFont"]) ?? { properties: {} };
    const props = (branch["properties"] ?? {}) as Record<string, Json>;
    hide = new Set(Object.keys(props).filter((k) => /^(Baked|Vector)-font key\. A build error here/.test(String(props[k]!["description"] ?? ""))));
    reading = { type, data, device: null, context: { ...context, frame: "awake" }, aodKeys: new Set(), cascade: { own: null, group: null, defaults: null, hiddenBy: null } };
  } else if (subject === "element") {
    type = String(data.get("type"));
    branch = elementSchema(type) ?? { properties: {} };
    hide = hidden(type);
    reading = { type, data, device, context, aodKeys: new Set(aodKeys(type)), cascade: cascadeOf(index, element, data, face) };
  } else {
    // a hand's or a part's keys are read as written: no overrides, no `aod:` block
    const inHand = element[1] === "hand_sets";
    const owner = subject === "part" ? dataAt(index.data, element.slice(0, -2)) : null;
    const pattern = subject === "part" && !inHand && isMap(owner) && owner.get("type") === "pattern";
    type = subject === "hand" ? "hand" : String(data.get("type"));
    branch = (subject === "hand" ? defs["hand"] : pattern ? defs["patternPart"] : defs["handPart"]) ?? { properties: {} };
    hide = subject === "part" ? hiddenPartKeys(type, pattern) : new Set();
    const written = { own: null, group: null, defaults: null, hiddenBy: null };
    reading = { type, data, device: null, context: { ...context, frame: "awake" }, aodKeys: new Set(), cascade: written };
  }
  const required = new Set((branch["required"] ?? []) as string[]);
  const props = (branch["properties"] ?? {}) as Record<string, Json>;
  const order = [...[...data.keys()].filter((k) => typeof k === "string" && k in props) as string[], ...Object.keys(props).filter((k) => !data.has(k))];
  const restyled = subject === "element" ? aodKeys(type) : [];
  const id = typeof element[element.length - 1] === "number" ? `part${Number(element[element.length - 1]) + 1}` : String(element[element.length - 1]);
  const fields = order
    .filter((k) => !SKIPPED.has(k) && (!hide.has(k) || data.has(k))
      && (data.has(k) || !String(props[k]!["description"] ?? "").startsWith("Not accepted")))
    .map((k) => field(reading, k, [k], props[k]!, data.has(k) ? data.get(k) : null, required.has(k), 1));
  const unknown = [...data.keys()].filter((k) => !(String(k) in props)).map(String);
  const overrides: Inspect["overrides"] = {};
  if (device !== null && subject === "element") {
    const [deviceSel, shapeSel, displaySel] = selectorPaths(device);
    for (const [scope, selector] of [["device", deviceSel], ["shape", shapeSel], ["display", displaySel]] as const) {
      const patch = dataAt(data, selector);
      if (isMap(patch)) overrides[scope] = { selector: String(selector[1]), keys: mapping(patch) };
    }
  }
  if (subject !== "element") return { ...out, id, type, subject, fields, unknown };
  return {
    ...out, type, fields, unknown, aod_keys: restyled, overrides,
    overridden: nonGeometryOverrides(index, element, data),
    parts: patternPartsSummary(index, type, element, data),
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

function slots(index: SpanIndex): SlotEntry[] {
  const out: SlotEntry[] = [];
  const entries = g(g(index.data, "config"), "slots");
  for (const slot of keysOf(entries)) {
    const entry = isMap(g(entries, slot)) ? g(entries, slot) : new Map();
    const raw = g(entry, "choices");
    const choices = Array.isArray(raw)
      ? raw.map((c) => (isMap(c) ? { type: name(c.get("type")), icon: iconSpelling(c.get("icon")) } : { type: name(c), icon: null }))
      : name(raw);
    out.push({ name: String(slot), label: name(g(entry, "label")), default: name(g(entry, "default")), choices, drawn_by: slotDrawers(index, String(slot)) });
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

function axes(data: unknown): Axes {
  const config = g(data, "config");
  const out: Axes = { accent_color: null, data_color: null };
  for (const [axis, role] of [["accent_color", "accent"], ["data_color", "data"]] as const) {
    const entry = g(config, axis);
    if (!isMap(entry)) continue;
    const raw = entry.get("choices");
    const choices = typeof raw === "string" ? raw : (Array.isArray(raw) ? raw : []).map((c) => value(isMap(c) ? c.get("color") : c));
    const own = entry.get("role");
    const axisEntry: AxisEntry = { default: name(entry.get("default")), choices, raw: value(raw), role: own ? String(own) : role, own_role: entry.has("role") };
    out[axis] = axisEntry;
  }
  return out;
}

/** `face:` as written. */
function faceInfo(data: unknown): Globals["face"] {
  const face = g(data, "face");
  return { name: name(g(face, "name")), version: name(g(face, "version")), id: name(g(face, "id")) };
}

/** `defaults:` as written. */
function defaultsInfo(data: unknown): Globals["defaults"] {
  const defaults = g(data, "defaults");
  const aod = g(defaults, "aod");
  return {
    antialias: value(g(defaults, "antialias")), min_1px: value(g(defaults, "min_1px")),
    aod: { visible: value(g(aod, "visible")), dim: value(g(aod, "dim")), mask: value(g(aod, "mask")) },
  };
}

/**
 * `theme: schemes:` with each scheme's `base:` folded in as the compiler
 * folds it: the base's roles in the base's order, a role the scheme lists
 * itself in its place, a role only it has after them. A base no scheme
 * declares, or a chain that comes back round, is not followed (the build
 * reports it).
 */
function schemesOf(schemes: unknown, roles: string[]): Globals["schemes"] {
  const names = keysOf(schemes).map(String);
  const own = (n: string): Record<string, Value> => mapping(g(g(schemes, n), "colors"));
  const baseOf = (n: string): string | null => name(g(g(schemes, n), "base"));
  const fold = (n: string, seen: Set<string>): Record<string, Value> => {
    const mine = own(n);
    const base = baseOf(n);
    if (base === null || !names.includes(base) || seen.has(base)) return mine;
    const inherited = fold(base, new Set([...seen, base]));
    const out: Record<string, Value> = Object.fromEntries(Object.keys(inherited).map((k) => [k, k in mine ? mine[k]! : inherited[k]!]));
    for (const [k, v] of Object.entries(mine)) if (!(k in out)) out[k] = v;
    return out;
  };
  const colors = Object.fromEntries(names.map((n) => [n, fold(n, new Set([n]))]));
  return {
    names, roles, colors,
    base: Object.fromEntries(names.map((n) => [n, baseOf(n)])),
    inherited: Object.fromEntries(names.map((n) => [n, Object.keys(colors[n]!).filter((k) => !(k in own(n)))])),
    labels: Object.fromEntries(names.map((n) => [n, name(g(g(schemes, n), "label"))])),
  };
}

/** `globalsOf` for a text that does not parse: nothing in it. */
const NO_GLOBALS: Globals = {
  face: { name: null, version: null, id: null },
  defaults: { antialias: null, min_1px: null, aod: { visible: null, dim: null, mask: null } },
  palette: [], schemes: { names: [], roles: [], colors: {}, base: {}, inherited: {}, labels: {} }, styles: { default: null, entries: [] }, layouts: [], layout_entries: [], fonts: [], slots: [],
  roles: [], axes: { accent_color: null, data_color: null }, displays: [], hand_sets: [], hands: [], targets: [], target_problems: {},
};

/** The face's identity, defaults, colours, schemes, styles, layouts, fonts, slots and targets. */
export function globalsOf(text: string, db: DeviceDatabase): Globals {
  let index: SpanIndex;
  try {
    index = indexFor(text);
  } catch (error) {
    if (error instanceof Refused) return NO_GLOBALS;
    throw error;
  }
  const data = index.data;
  if (!isMap(data)) return NO_GLOBALS;
  const written = g(g(data, "build"), "targets");
  const targets = Array.isArray(written) ? written.map(String) : [];
  const devices: Device[] = [];
  const targetProblems: Record<string, string> = {};
  for (const target of targets) {
    try {
      devices.push(db.get(target));
    } catch (error) {
      if (!(error instanceof DeviceError)) throw error;
      targetProblems[target] = error.message;
    }
  }
  const resources = g(data, "resources");
  const palette = keysOf(g(resources, "palette")).map((key) => {
    const entry = g(g(resources, "palette"), key);
    const color = isMap(entry) ? entry.get("value") : entry;
    return {
      name: String(key), value: value(color), label: isMap(entry) ? value(entry.get("label")) : null, long: isMap(entry),
      dithers_on: legalOn(color, devices), used_by: colors.userNames(index, String(key)),
      automatic: automatic(String(key), color), problem: problem(color), launcher: colors.LAUNCHER.has(String(key)),
    };
  });
  const schemes = g(g(data, "theme"), "schemes");
  const roles: string[] = [];
  for (const scheme of keysOf(schemes).map((k) => g(schemes, k))) {
    for (const role of keysOf(g(scheme, "colors")).map(String)) if (!roles.includes(role)) roles.push(role);
  }
  const style = g(g(data, "config"), "style");
  const fonts = keysOf(g(resources, "fonts")).map((key) => {
    const spec = g(g(resources, "fonts"), key);
    return { name: String(key), source: name(g(spec, "source")), face: value(g(spec, "face")), size: value(g(spec, "size")) };
  });
  const entries: StyleEntry[] = keysOf(g(style, "choices")).map((key, index) => {
    const e = g(g(style, "choices"), key);
    return { name: String(key), index, label: name(g(e, "label")), layout: name(g(e, "layout")), scheme: name(g(e, "scheme")) };
  });
  const layouts = g(data, "layouts");
  const layoutEntries: LayoutEntry[] = keysOf(layouts).map((key) => {
    const layout = g(layouts, key);
    return {
      name: String(key), label: name(g(layout, "label")), elements: keysOf(g(layout, "elements")).length, static: keysOf(g(layout, "static")).length,
      styles: entries.filter((e) => e.layout === String(key)).map((e) => e.name),
    };
  });
  return {
    face: faceInfo(data),
    defaults: defaultsInfo(data),
    palette,
    schemes: schemesOf(schemes, roles),
    styles: { default: name(g(style, "default")), entries },
    layouts: keysOf(layouts).map(String),
    layout_entries: layoutEntries,
    fonts,
    slots: slots(index),
    roles: colors.roles(index),
    axes: axes(data),
    displays: [...new Set(devices.map((d) => d.displayColors).filter((c): c is number => Boolean(c)))].sort((a, b) => a - b),
    hand_sets: keysOf(g(resources, "hand_sets")).map(String),
    hands: hands.summary(index).map((set): HandSet => ({
      ...set, hands: Object.fromEntries(Object.entries(set.hands).map(([hand, h]) => [hand, { parts: h.parts, color: value(h.color) }])),
    })),
    targets,
    target_problems: targetProblems,
  };
}

function complicationType(name: string): ComplicationType {
  const sample = DATA_SAMPLE.get(name);
  return {
    name, label: complications.label(name), category: complications.category(name),
    icon: icons.COMPLICATION_ICON.get(name) ?? null,
    sample: sample !== undefined && sample !== null ? complications.formatReading(name, sample) : null,
    capabilities: capabilities(name),
  };
}

/** The readings whose text the device supplies or names at length: they can outrun a slot. */
const LONG_READINGS: ReadonlySet<string> = new Set(["condition", "high_low", "training_status"]);

/** What a slot showing type `name` supports beyond its reading, each said as a hover says it. */
export function capabilities(name: string): Capability[] {
  const out: Capability[] = [];
  const graph = series.SLOT_SERIES.get(name);
  if (graph !== undefined) out.push({ kind: "graph", detail: `graph: a graph on this slot plots ${graph.span}` });
  if (complications.ICON_CONDITION.has(name)) {
    out.push({ kind: "dynamic_icon", detail: "dynamic icon: it follows the weather condition" });
  } else if (complications.ICON_WHEN_ZERO.has(name)) {
    out.push({ kind: "dynamic_icon", detail: "dynamic icon: it empties when there is nothing to count" });
  } else if (complications.ICON_LEVEL.has(name)) {
    out.push({ kind: "dynamic_icon", detail: "dynamic icon: it fills with the reading" });
  }
  const scale = complications.SCALE.get(name);
  if (scale !== undefined) {
    const across = scale.kind === "goal" ? "from 0 to the watch's own goal"
      : scale.kind === "heart_rate_zones" ? "across the wearer's heart-rate zones"
        : scale.kind === "vo2max" ? "across the wearer's VO2 max rating row, from Poor to Superior"
          : scale.maximum === 86400 ? "across one day" : `from ${scale.minimum} to ${scale.maximum}`;
    out.push({ kind: "gauge", detail: `progress: a gauge on this slot fills ${across}` });
  }
  const reading = complications.READING.get(name);
  if (reading !== undefined && LONG_READINGS.has(reading)) {
    const detail = reading === "training_status"
      ? "long text: the device's own words (\"Unproductive\"); 'short: true' shortens the ones it knows (\"Unprod\")"
      : `long text: up to ${complications.widestReading(name, false, false).length} characters `
        + `(\"${complications.widestReading(name, false, false)}\"); 'short: true' keeps it to `
        + `\"${complications.widestReading(name, false, true)}\"`;
    out.push({ kind: "long_text", detail });
  }
  return out;
}

/** strftime-style codes as written after a placeholder's colon (`%H`, `%-M`), each with what it draws. */
function codesOf(codes: ReadonlyMap<string, { description: string }>): FormatCode[] {
  return [...codes].map(([code, c]) => [`%${code}`, c.description]);
}

/** A number's specs, the commonest first: `[0][width][.precision]` and `d`, `f` or `s` (`docs/guide/data.md`, Formats). */
const NUMBER_SPECS: readonly FormatCode[] = [
  ["d", "a whole number (a Float truncates)"],
  ["02d", "a whole number, two digits, zero-padded"],
  [".1f", "one decimal, rounded"],
  [".2f", "two decimals, rounded"],
  [".0f", "no decimals, rounded"],
  ["3d", "a whole number, three wide, space-padded"],
  ["s", "the value's own text"],
];

let words: Words | null = null;

/** What the pickers offer: data sources by namespace, icon names and complication types. Device-independent. */
export function vocabulary(): Words {
  if (words === null) {
    const glyphs: Record<string, number> = {};
    for (const [name, icon] of icons.CATALOG) glyphs[name] = icon.codepoint.codePointAt(0) ?? 0;
    words = {
      sources: Object.fromEntries(catalog.namespaces()),
      icons: [...icons.CATALOG.keys()].sort(),
      complications: ["auto", ...complications.names()],
      series: series.names(),
      types: elementTypes(),
      mip: MIP64_NAMED.map(([name, value, label]) => ({ name, value, label })),
      hand_presets: [...hands.presets().keys()].map(String),
      categories: [...complications.CATEGORIES],
      complication_types: complications.names().map(complicationType),
      icon_glyphs: glyphs,
      source_info: Object.fromEntries([...catalog.CATALOG.keys()].sort().map((path) => {
        const source = catalog.get(path)!;
        return [path, { type: source.type, unit: source.unit, quantity: source.quantity, doc: source.doc, nullable: source.nullable }];
      })),
      format_codes: {
        time: codesOf(TIME_CODES), date: codesOf(DATE_CODES), duration: codesOf(DURATION_CODES), number: NUMBER_SPECS.map(([spec, label]) => [spec, label]),
      },
      lint_codes: [...SUPPRESSIBLE].sort(),
    };
  }
  return words;
}

/** Every installed device that can run a face, for the targets list, and every one whose files could not be read. */
export function devices(db: DeviceDatabase): [DeviceInfo[], UnreadableDevice[]] {
  const out: DeviceInfo[] = [];
  const unreadable: UnreadableDevice[] = [];
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
      fonts: [...device.systemFonts.keys()], faces: device.scalableFaces,
    });
  }
  const lower = (d: DeviceInfo): string => d.name.toLowerCase();
  return [out.sort((a, b) => (lower(a) < lower(b) ? -1 : lower(a) > lower(b) ? 1 : 0)), unreadable];
}
