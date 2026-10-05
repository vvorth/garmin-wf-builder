// Colour edits: a picked colour becomes a named palette swatch. Port of
// wfb/edit/colors.py.
//
// The editor's picker offers the face's own swatches and roles, the 64
// named MIP colours and any custom colour. Whatever is picked, the element
// names a swatch (`color.<name>`), never a bare literal:
//
// - a colour the palette already holds reuses that swatch, whatever its name;
// - one of the 64 is added under its MIP name, with its label;
// - any other colour is added as `c` plus its hex: `#FF8000` is `cFF8000`.
//
// A name taken by another colour, or by a role, gets `_2`, `_3`, ...
//
// A swatch named after its own value (`cFF8000`, or the MIP name of its
// colour, with or without that suffix) is the editor's *automatic* swatch.
// Picking another colour for the last element that used one removes it in
// the same patch, and changing its value in the Colours section renames it
// to match. A swatch with a name of the author's own is never renamed or
// removed by either.
import { Color, ColorError, MIP64_NAMED, mip64Name } from "../palette.ts";
import { get, or } from "../py.ts";
import { chain, patch, type Patch, pyKey, remove, renameReference, setValue } from "./patch.ts";
import { dotted, type Path, pathKey, Refused, SpanIndex, type Step } from "./spans.ts";
import type { Data, DataKey } from "./yaml.ts";

/** A whole `color.<name>` reference, inside an expression too. */
export const REFERENCE = /(?<![A-Za-z0-9_.])color\.([A-Za-z_][A-Za-z0-9_]*)(?![A-Za-z0-9_])/g;

/** Swatches the launcher icon reads by name, so a face uses them even where no `color.<name>` does. */
export const LAUNCHER: ReadonlySet<string> = new Set(["bg", "accent", "text", "fg"]);

const LABELS = new Map(MIP64_NAMED.map(([name, , label]) => [name, label]));
const SUFFIX = /_\d+$/;

/** `value` as `#RRGGBB`, upper case; `Refused` when it is no colour. */
export function hexOf(value: unknown): string {
  try {
    return Color.parse(value).toString();
  } catch (error) {
    if (error instanceof ColorError) throw new Refused(error.message);
    throw error;
  }
}

function palette(index: SpanIndex): Map<DataKey, Data> {
  const found = or(get(or(get(index.data, "resources"), new Map()), "palette"), new Map());
  return found instanceof Map ? found : new Map();
}

/** Every swatch whose value is a colour: name to `#RRGGBB`. */
export function swatches(index: SpanIndex): Map<string, string> {
  const out = new Map<string, string>();
  for (const [name, entry] of palette(index)) {
    const raw = entry instanceof Map ? entry.get("value") : entry;
    try {
      out.set(pyKey(name), Color.parse(raw).toString());
    } catch (error) {
      if (!(error instanceof ColorError)) throw error;
    }
  }
  return out;
}

/** Every role: each scheme's, then the colour axes' (`accent`, `data`, or the axis's own `role:`). */
export function roles(index: SpanIndex): string[] {
  const data = index.data instanceof Map ? index.data : new Map<DataKey, Data>();
  const out: string[] = [];
  const schemes = or(get(or(data.get("theme"), new Map()), "schemes"), new Map());
  for (const scheme of schemes instanceof Map ? schemes.values() : []) {
    const colors = or(get(or(scheme, new Map()), "colors"), new Map());
    for (const role of colors instanceof Map ? colors.keys() : []) {
      if (!out.includes(role as string)) out.push(pyKey(role));
    }
  }
  const config = or(data.get("config"), new Map());
  for (const [axis, fallback] of [["accent_color", "accent"], ["data_color", "data"]] as const) {
    const value = get(config, axis);
    if (value instanceof Map) {
      const role = String(or(value.get("role"), fallback));
      if (!out.includes(role)) out.push(role);
    }
  }
  return out;
}

/** The name the editor gives a colour: its MIP name, else `c` + hex. */
export function automaticName(value: string): string {
  const v = hexOf(value);
  return mip64Name(v) ?? "c" + v.slice(1);
}

/** Whether `name` is the editor's own name for `value`. */
export function isAutomatic(name: string, value: string): boolean {
  return name.replace(SUFFIX, "") === automaticName(value);
}

function fresh(index: SpanIndex, base: string): string {
  const taken = new Set([...[...palette(index).keys()].map((k) => k as string), ...roles(index)]);
  if (!taken.has(base)) return base;
  for (let n = 2; n < 10_000; n++) if (!taken.has(`${base}_${n}`)) return `${base}_${n}`;
  throw new Refused("no free name");
}

function walk(data: Data, path: Step[]): [Step[], string][] {
  if (data instanceof Map) return [...data].flatMap(([k, v]) => walk(v, [...path, k as Step]));
  if (Array.isArray(data)) return data.flatMap((v, i) => walk(v, [...path, i]));
  return typeof data === "string" ? [[path, data]] : [];
}

function refersTo(text: string, name: string): boolean {
  for (const m of text.matchAll(REFERENCE)) if (m[1] === name) return true;
  return false;
}

/** The path of every string value that names `color.<name>`. */
export function users(index: SpanIndex, name: string): Path[] {
  return walk(index.data, []).filter(([, text]) => refersTo(text, name)).map(([path]) => path);
}

/** Who uses `color.<name>`, as the author knows them: the id of the element holding each reference, else the reference's dotted path. */
export function userNames(index: SpanIndex, name: string): string[] {
  const elements = new Map(index.elements().map((e) => [pathKey(e.path), e.name]));
  const out: string[] = [];
  for (const path of users(index, name)) {
    let holder: string | undefined;
    for (let n = path.length; n > 0; n--) {
      holder = elements.get(pathKey(path.slice(0, n)));
      if (holder !== undefined) break;
    }
    const shown = holder || dotted(path);
    if (!out.includes(shown)) out.push(shown);
  }
  return out;
}

function valuePath(index: SpanIndex, name: string): Path {
  const entry = palette(index).get(name);
  return ["resources", "palette", name, ...(entry instanceof Map ? ["value"] : [])];
}

/** The swatch holding `value`: an existing one, or a new one and the patch adding it. */
function swatchFor(index: SpanIndex, value: string): [string, Patch | undefined] {
  const v = hexOf(value);
  for (const [name, held] of swatches(index)) if (held === v) return [name, undefined];
  const name = fresh(index, automaticName(v));
  const mip = mip64Name(v);
  const entry: Data = mip ? new Map<DataKey, Data>([["value", v], ["label", LABELS.get(mip)!]]) : v;
  return [name, setValue(index, ["resources", "palette", name], entry)];
}

/** `result`, followed by removing the automatic swatch `name` when nothing uses it any more. */
function dropIfUnused(result: Patch, name: string | undefined, keep: string): Patch {
  if (name === undefined || name === keep || LAUNCHER.has(name)) return result;
  const after = new SpanIndex(result.text);
  const held = swatches(after).get(name);
  if (held === undefined || !isAutomatic(name, held) || users(after, name).length > 0) return result;
  return chain(result, (i) => remove(i, ["resources", "palette", name]));
}

function fullReference(value: unknown): RegExpExecArray | null {
  if (typeof value !== "string") return null;
  const m = new RegExp(`^(?:${REFERENCE.source})$`).exec(value);
  return m;
}

/**
 * Point the key at `path` at `value`: a `color.<name>` as it is, a hex
 * through the swatch holding it (added when there is none). The automatic
 * swatch the key named before goes when it has no other user.
 */
export function useColor(index: SpanIndex, path: Path, value: string): Patch {
  let before: Data | undefined = index.data;
  for (const step of path) before = before instanceof Map ? before.get(step) : undefined;
  const was = fullReference(before)?.[1];
  const ref = fullReference(value);
  let name: string, result: Patch, what: string;
  if (ref !== null) {
    name = ref[1]!;
    result = setValue(index, path, value);
    what = `set ${dotted(path)} to ${value}`;
  } else {
    let added: Patch | undefined;
    [name, added] = swatchFor(index, value);
    what = `set ${dotted(path)} to color.${name}` + (added ? ` (adds ${name})` : "");
    const swatch = name;
    result = added ? chain(added, (i) => setValue(i, path, `color.${swatch}`)) : setValue(index, path, `color.${name}`);
  }
  result = dropIfUnused(result, was, name);
  return patch(result.text, result.expected, what);
}

/** Add `value` to the palette under the editor's name for it. */
export function addSwatch(index: SpanIndex, value: string): [Patch, string] {
  const [name, added] = swatchFor(index, value);
  if (added === undefined) throw new Refused(`${hexOf(value)} is in the palette already, as ${name}`);
  return [patch(added.text, added.expected, `add the colour ${name}`), name];
}

/** Change a swatch's value; every `color.<name>` follows. An automatic swatch is renamed to match its new value. */
export function setSwatch(index: SpanIndex, name: string, value: string): Patch {
  const held = swatches(index).get(name);
  if (held === undefined) throw new Refused(`there is no colour called ${name}`);
  const v = hexOf(value);
  let result = setValue(index, valuePath(index, name), v);
  let what = `set the colour ${name} to ${v}`;
  if (!LAUNCHER.has(name) && isAutomatic(name, held) && !isAutomatic(name, v)) {
    const renamed = fresh(new SpanIndex(result.text), automaticName(v));
    result = chain(result, (i) => renameReference(i, ["resources", "palette", name], renamed, "color."));
    what += `, renamed ${renamed}`;
    // the MIP label came with the name, and goes with it
    const entry = palette(index).get(name);
    if (entry instanceof Map && entry.get("label") === LABELS.get(automaticName(held))) {
      const labelPath: Path = ["resources", "palette", renamed, "label"];
      const mip = mip64Name(v);
      result = chain(result, (i) => mip ? setValue(i, labelPath, LABELS.get(mip)!) : remove(i, labelPath));
    }
  }
  return patch(result.text, result.expected, what);
}

/** Remove every swatch no `color.<name>` names, except those the launcher icon reads. */
export function removeUnused(index: SpanIndex): Patch {
  const unused = [...palette(index).keys()].map(pyKey).filter((n) => !LAUNCHER.has(n) && users(index, n).length === 0);
  if (unused.length === 0) throw new Refused("every colour in the palette is in use");
  let result = remove(index, ["resources", "palette", unused[0]!]);
  for (const name of unused.slice(1)) result = chain(result, (i) => remove(i, ["resources", "palette", name]));
  return patch(result.text, result.expected, `remove the unused colours ${unused.join(", ")}`);
}
