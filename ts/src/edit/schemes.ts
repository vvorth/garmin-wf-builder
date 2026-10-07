// Colour-scheme edits: each changes every place a scheme or a role is
// written, as one patch.
//
// A scheme edit one key at a time is refused by the gate, rightly: every
// scheme must declare the same roles, a style entry names its scheme, and a
// role is referenced as `color.<role>` anywhere in the face. So each edit
// here is a `chain` of the keys it must change together:
//
// - `makeSwitchable`: chosen palette colours become the roles of a first
//   scheme, under the same names, so no reference changes; a style entry
//   picks the scheme;
// - `addScheme`: a copy of another scheme, and the style entries that reach it;
// - `renameScheme`, `deleteScheme`: the key and every style entry naming it;
// - `addRole`, `renameRole`, `deleteRole`: the role in every scheme, and for
//   a rename every `color.<role>`;
// - `removeTheme`: the kept scheme's roles become palette colours of the
//   same names, `theme:` goes, and every style entry loses its `scheme:`. An
//   entry left with nothing (it named only a scheme) goes; one naming a
//   layout stays, even when that leaves two alike (the author's to resolve).
import { get, or, quoted, truthy } from "../py.ts";
import { hexOf, roles, swatches, users } from "./colors.ts";
import {
  chain, patch, type Patch, referencePattern, remove, renameKey, rewriteScalars, setValue,
} from "./patch.ts";
import { type Path, Refused, type SpanIndex } from "./spans.ts";
import type { Data, DataKey } from "./yaml.ts";

type Step = (index: SpanIndex) => Patch;

function data(index: SpanIndex): Map<DataKey, Data> {
  return index.data instanceof Map ? index.data : new Map();
}

function schemesOf(index: SpanIndex): Map<DataKey, Data> {
  const schemes = or(get(or(data(index).get("theme"), new Map()), "schemes"), new Map());
  return schemes instanceof Map ? schemes : new Map();
}

function styleOf(index: SpanIndex): Map<DataKey, Data> | undefined {
  const style = get(or(data(index).get("config"), new Map()), "style");
  return style instanceof Map ? style : undefined;
}

function entriesOf(index: SpanIndex): Map<DataKey, Data> {
  const choices = or(get(or(styleOf(index), new Map()), "choices"), new Map());
  return choices instanceof Map ? choices : new Map();
}

/** `steps` as one patch, each on the text the one before left. */
function run(index: SpanIndex, steps: Step[], what: string): Patch {
  if (steps.length === 0) throw new Refused(`${what}: nothing to change`);
  let result = steps[0]!(index);
  for (const step of steps.slice(1)) result = chain(result, step);
  return patch(result.text, result.expected, what);
}

const set = (path: Path, value: Data, block = false): Step => (i) => setValue(i, path, value, { block });
const drop = (path: Path): Step => (i) => remove(i, path);
const rename = (path: Path, renamed: string): Step => (i) => renameKey(i, path, renamed);

function checkName(name: string, what: string): string {
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name || "")) {
    throw new Refused(`${quoted(name)} is not a ${what} name: letters, digits and _, not starting with a digit`);
  }
  return name;
}

function scheme(index: SpanIndex, name: string): Map<DataKey, Data> {
  const found = schemesOf(index).get(name);
  if (!(found instanceof Map)) throw new Refused(`there is no scheme called ${name}`);
  return found;
}

/** A role's colour as written for a scheme: a swatch reference stays, anything else is a hex value. */
function roleValue(index: SpanIndex, value: Data): string {
  if (typeof value === "string" && value.startsWith("color.")) {
    if (!swatches(index).has(value.slice(6))) {
      throw new Refused(`${value} is not a palette colour: a scheme's colour must be known when the face is built`);
    }
    return value;
  }
  return hexOf(value);
}

function colorsOf(value: Data | undefined): Map<DataKey, Data> {
  const colors = or(get(or(value, new Map()), "colors"), new Map());
  return colors instanceof Map ? colors : new Map();
}

// -- schemes --------------------------------------------------------------------

/** Move the palette colours `names` into a first scheme, `name`, as roles of the same names; a style entry (or every existing one) picks it. */
export function makeSwitchable(index: SpanIndex, names: string[], name: string): Patch {
  checkName(name, "scheme");
  if (schemesOf(index).size > 0) throw new Refused("the face has schemes already: add a scheme instead");
  const held = swatches(index);
  if (names.length === 0) throw new Refused("pick the colours that should change with the style");
  const missing = names.filter((n) => !held.has(n));
  if (missing.length > 0) {
    throw new Refused(`${missing.join(", ")} ${missing.length === 1 ? "is" : "are"} not a palette colour`);
  }
  const steps: Step[] = names.map((n) => drop(["resources", "palette", n]));
  const colors = new Map<DataKey, Data>(names.map((n) => [n, held.get(n)!]));
  steps.push(set(["theme"], new Map([["schemes", new Map([[name, new Map([["colors", colors]])]])]]), true));
  const entries = entriesOf(index);
  if (entries.size === 0) {
    steps.push(set(["config", "style"], new Map<DataKey, Data>([
      ["default", name], ["choices", new Map([[name, new Map([["scheme", name]])]])]]), true));
  } else {
    for (const e of entries.keys()) steps.push(set(["config", "style", "choices", e as string, "scheme"], name));
  }
  return run(index, steps, `make ${names.join(", ")} switchable, in the scheme ${name}`);
}

/**
 * A new scheme, a copy of `like` (the first scheme by default), and the
 * style entries that reach it: one, when every entry names only a scheme;
 * else one per layout, `<layout>_<name>`.
 */
export function addScheme(index: SpanIndex, name: string, like: string | null = null): Patch {
  checkName(name, "scheme");
  const schemes = schemesOf(index);
  if (schemes.size === 0) throw new Refused("the face has no schemes yet: make colours switchable first");
  if (schemes.has(name)) throw new Refused(`there is a scheme called ${name} already`);
  const source = scheme(index, like || String(schemes.keys().next().value));
  const steps: Step[] = [set(["theme", "schemes", name], new Map([["colors", new Map(colorsOf(source))]]))];
  const entries = entriesOf(index);
  const layouts: Data[] = [];
  for (const e of entries.values()) {
    const layout = get(e, "layout");
    if (e instanceof Map && truthy(layout) && !layouts.includes(layout!)) layouts.push(layout!);
  }
  if (layouts.length > 0) {
    for (const layout of layouts) {
      const entry = `${String(layout as DataKey)}_${name}`;
      if (entries.has(entry)) throw new Refused(`there is a style called ${entry} already`);
      steps.push(set(["config", "style", "choices", entry], new Map<DataKey, Data>([["layout", layout], ["scheme", name]])));
    }
  } else {
    if (entries.has(name)) throw new Refused(`there is a style called ${name} already`);
    steps.push(set(["config", "style", "choices", name], new Map([["scheme", name]])));
  }
  return run(index, steps, `add the scheme ${name}`);
}

/** Rename a scheme and every style entry's `scheme:` naming it. */
export function renameScheme(index: SpanIndex, old: string, renamed: string): Patch {
  scheme(index, old);
  checkName(renamed, "scheme");
  if (schemesOf(index).has(renamed)) throw new Refused(`there is a scheme called ${renamed} already`);
  const steps: Step[] = [rename(["theme", "schemes", old], renamed)];
  for (const [e, entry] of entriesOf(index)) {
    if (entry instanceof Map && entry.get("scheme") === old) steps.push(set(["config", "style", "choices", e as string, "scheme"], renamed));
  }
  return run(index, steps, `rename the scheme ${old} to ${renamed}`);
}

/** Delete a scheme and the style entries naming it. Refused for the last scheme and when no style entry would be left. */
export function deleteScheme(index: SpanIndex, name: string): Patch {
  scheme(index, name);
  if (schemesOf(index).size === 1) throw new Refused(`${name} is the only scheme: remove the schemes instead`);
  const entries = entriesOf(index);
  const gone = [...entries].filter(([, entry]) => entry instanceof Map && entry.get("scheme") === name).map(([e]) => e as string);
  if (gone.length > 0 && gone.length === entries.size) {
    throw new Refused(`every style picks ${name}: point one at another scheme first`);
  }
  const steps: Step[] = gone.map((e) => drop(["config", "style", "choices", e]));
  const style = or(styleOf(index), new Map());
  if (gone.includes(get(style, "default") as string)) {
    steps.push(set(["config", "style", "default"], [...entries.keys()].find((e) => !gone.includes(e as string))!));
  }
  steps.push(drop(["theme", "schemes", name]));
  return run(index, steps, `delete the scheme ${name}` + (gone.length > 0 ? ` and the styles ${gone.join(", ")}` : ""));
}

/** Remove every scheme, keeping `keep`'s colours as palette colours named after their roles; every style entry loses its `scheme:`. */
export function removeTheme(index: SpanIndex, keep: string): Patch {
  const kept = scheme(index, keep);
  const held = swatches(index);
  const steps: Step[] = [];
  for (const [role, original] of colorsOf(kept)) {
    let value: Data = original;
    if (typeof value === "string" && value.startsWith("color.")) value = held.get(value.slice(6)) ?? value;
    steps.push(set(["resources", "palette", role as string], hexOf(value), true));
  }
  steps.push(drop(["theme"]));
  const entries = entriesOf(index);
  const left = [...entries].filter(([, entry]) => entry instanceof Map && Boolean(entry.get("layout"))).map(([e]) => e as string);
  if (entries.size > 0 && left.length === 0) {
    steps.push(drop(["config", "style"]));
  } else {
    for (const [e, entry] of entries) {
      if (!(entry instanceof Map) || !entry.has("scheme")) continue;
      steps.push(left.includes(e as string) ? drop(["config", "style", "choices", e as string, "scheme"])
        : drop(["config", "style", "choices", e as string]));
    }
    if (left.length > 0 && !left.includes(get(or(styleOf(index), new Map()), "default") as string)) {
      steps.push(set(["config", "style", "default"], left[0]!));
    }
  }
  return run(index, steps, `remove the schemes, keeping ${keep}'s colours`);
}

// -- roles ----------------------------------------------------------------------

/** A new role in every scheme: `values` maps each scheme to its colour, or is one colour for all. */
export function addRole(index: SpanIndex, name: string, values: Data): Patch {
  checkName(name, "role");
  const schemes = schemesOf(index);
  if (schemes.size === 0) throw new Refused("the face has no schemes yet: make colours switchable first");
  if (roles(index).includes(name)) throw new Refused(`there is a role called ${name} already`);
  if (swatches(index).has(name)) throw new Refused(`${name} is a palette colour: a role needs a name of its own`);
  const each = values instanceof Map ? values : new Map([...schemes.keys()].map((s) => [s, values]));
  const missing = [...schemes.keys()].filter((s) => !each.has(s));
  if (missing.length > 0) throw new Refused(`no colour for ${name} in ${missing.map(String).join(", ")}`);
  const steps = [...schemes.keys()].map((s) => set(["theme", "schemes", s as string, "colors", name], roleValue(index, each.get(s)!)));
  return run(index, steps, `add the role ${name}`);
}

/** Rename a role in every scheme and every `color.<old>` with it. */
export function renameRole(index: SpanIndex, old: string, renamed: string): Patch {
  checkName(renamed, "role");
  const schemes = schemesOf(index);
  if (![...schemes.values()].some((s) => colorsOf(s).has(old))) throw new Refused(`there is no role called ${old}`);
  if (roles(index).includes(renamed) || swatches(index).has(renamed)) throw new Refused(`${renamed} names a colour already`);
  const pattern = referencePattern("color.", old);
  const steps: Step[] = [...schemes.keys()].map((s) => rename(["theme", "schemes", s as string, "colors", old], renamed));
  steps.push((i) => rewriteScalars(i, (t) => t.replace(pattern, () => `color.${renamed}`), `refer to color.${renamed}`));
  return run(index, steps, `rename the role ${old} to ${renamed}`);
}

/** Delete a role from every scheme. Refused while something uses it, and for a scheme's last role. */
export function deleteRole(index: SpanIndex, name: string): Patch {
  const schemes = schemesOf(index);
  if (![...schemes.values()].some((s) => colorsOf(s).has(name))) throw new Refused(`there is no role called ${name}`);
  const used = users(index, name);
  if (used.length > 0) {
    throw new Refused(`color.${name} is used by ${used.length} key${used.length > 1 ? "s" : ""}: point them at another colour first`);
  }
  if ([...schemes.values()].some((s) => colorsOf(s).size === 1)) throw new Refused(`${name} is the only role: remove the schemes instead`);
  return run(index, [...schemes.keys()].map((s) => drop(["theme", "schemes", s as string, "colors", name])), `delete the role ${name}`);
}
