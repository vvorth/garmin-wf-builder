// Hand-set edits: `resources: hand_sets:` entries added from a preset,
// duplicated, renamed with every element's `set:` following, and deleted
// while nothing places them. Port of wfb/edit/hands.py.
//
// The presets are `wfb/templates/hands/sets.yaml`, handed in as text
// (`loadPresets`) so this module runs in the browser too. Their `color.fg`
// and `color.accent` stand for the face's main colour and its accent, and
// are rewritten to colours the face has, so an added set loads.
import { deepCopy, get, item, or, repr } from "../py.ts";
import { roles, swatches } from "./colors.ts";
import { chain, endedPatch, patch, type Patch, pyKey, remove, renameKey, repointOn, setValue } from "./patch.ts";
import { type Path, parse, Refused, type SpanIndex } from "./spans.ts";
import { add } from "./structure.ts";
import type { Data, DataKey } from "./yaml.ts";

/** A hand set's hands, in the order they are drawn. */
export const HANDS = ["hour", "minute", "second"] as const;

let presetData: Map<DataKey, Data> | undefined;

/** Read the presets file's text (`wfb/templates/hands/sets.yaml`). */
export function loadPresets(text: string): void {
  const data = parse(text);
  presetData = data instanceof Map ? data : new Map();
}

/** Every preset by name, as written in the presets file. */
export function presets(): Map<DataKey, Data> {
  if (presetData === undefined) throw new Error("hand-set presets not loaded: call loadPresets first");
  return presetData;
}

function sets(index: SpanIndex): Map<DataKey, Data> {
  const data = index.data instanceof Map ? index.data : new Map<DataKey, Data>();
  const found = or(get(or(data.get("resources"), new Map()), "hand_sets"), new Map());
  return found instanceof Map ? found : new Map();
}

/** The ids of the `hands` elements placing the set `name`. */
export function placedBy(index: SpanIndex, name: string): string[] {
  const out: string[] = [];
  for (const entry of index.elements()) {
    let data: Data = index.data;
    for (const step of entry.path) data = item(data, step);
    if (data instanceof Map && data.get("type") === "hands" && data.get("set") === name) out.push(entry.name);
  }
  return out;
}

/**
 * What a preset's `color.fg` and `color.accent` become on this face: a
 * colour of that name if it has one, else its likeliest main colour
 * (`text`, then `white`, then its first colour that is not `bg`).
 */
function faceColors(index: SpanIndex): Map<string, string> {
  const names = [...swatches(index).keys(), ...roles(index)];
  const main = ["fg", "text", "white"].find((n) => names.includes(n)) ?? names.find((n) => n !== "bg");
  const mainRef = main ? `color.${main}` : "#FFFFFF";
  const accentRef = names.includes("accent") ? "color.accent" : mainRef;
  return new Map([["color.fg", mainRef], ["color.accent", accentRef]]);
}

function recolored(value: Data, colors: Map<string, string>): Data {
  if (value instanceof Map) return new Map([...value].map(([k, v]) => [k, recolored(v, colors)]));
  if (Array.isArray(value)) return value.map((v) => recolored(v, colors));
  return typeof value === "string" ? colors.get(value) ?? value : value;
}

function checkName(name: string): string {
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name || "")) {
    throw new Refused(`${repr(name)} is not a hand set name: letters, digits and _, not starting with a digit`);
  }
  return name;
}

/** Add the preset `preset` as the hand set `name`, in the face's colours; when no element places a hand set yet, a `hands` element at the centre places this one. */
export function addHandSet(index: SpanIndex, name: string, preset: string): Patch {
  checkName(name);
  const all = presets();
  if (!all.has(preset)) throw new Refused(`there is no preset called ${preset}: ${[...all.keys()].map(pyKey).join(", ")}`);
  if (sets(index).has(name)) throw new Refused(`there is a hand set called ${name} already`);
  const value = recolored(deepCopy(all.get(preset)!), faceColors(index));
  let result = setValue(index, ["resources", "hand_sets", name], value, { block: true });
  const placed = [...sets(index).keys()].some((n) => placedBy(index, n as string).length > 0);
  if (!placed) result = chain(result, (i) => add(i, "hands", ["elements"], null, null, name));
  return patch(result.text, result.expected, `add the hand set ${name} (${preset})` + (placed ? "" : ", placed at the centre"));
}

/** A copy of the hand set `name` as `<name>_copy` (or `_copy2`, ...). */
export function duplicateHandSet(index: SpanIndex, name: string): Patch {
  const all = sets(index);
  if (!all.has(name)) throw new Refused(`there is no hand set called ${name}`);
  let copyName = "";
  for (let n = 1; n < 1000; n++) {
    const candidate = `${name}_copy${n === 1 ? "" : n}`;
    if (!all.has(candidate)) { copyName = candidate; break; }
  }
  const result = setValue(index, ["resources", "hand_sets", copyName], deepCopy(all.get(name)!), { block: true });
  return patch(result.text, result.expected, `duplicate the hand set ${name} as ${copyName}`);
}

/** Rename a hand set and every element's `set: <old>`. */
export function renameHandSet(index: SpanIndex, old: string, renamed: string): Patch {
  if (!sets(index).has(old)) throw new Refused(`there is no hand set called ${old}`);
  checkName(renamed);
  if (sets(index).has(renamed)) throw new Refused(`there is a hand set called ${renamed} already`);
  const result = chain(renameKey(index, ["resources", "hand_sets", old], renamed),
    (i) => endedPatch(i, (j) => repointOn(j, "set", old, renamed)));
  return patch(result.text, result.expected, `rename the hand set ${old} to ${renamed}`);
}

/** Delete a hand set. Refused while an element places it. */
export function deleteHandSet(index: SpanIndex, name: string): Patch {
  if (!sets(index).has(name)) throw new Refused(`there is no hand set called ${name}`);
  const placing = placedBy(index, name);
  if (placing.length > 0) {
    const one = placing.length === 1;
    throw new Refused(`${placing.join(", ")} ${one ? "places" : "place"} the hand set ${name}: delete ${one ? "it" : "them"} ` +
      "or point them at another set first");
  }
  const path: Path = ["resources", "hand_sets", name];
  const result = remove(index, path);
  return patch(result.text, result.expected, `delete the hand set ${name}`);
}

/** The declared hand sets' names. */
export function summaryNames(index: SpanIndex): string[] {
  return [...sets(index).keys()].map(pyKey);
}

/** Each hand set: its hands (parts and colour) and the elements placing it, for the Face panel. */
export function summary(index: SpanIndex): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = [];
  for (const [name, original] of sets(index)) {
    const entry = original instanceof Map ? original : new Map<DataKey, Data>();
    const hands: Record<string, unknown> = {};
    for (const h of HANDS) {
      const hand = entry.get(h);
      if (hand instanceof Map) {
        const parts = or(get(or(hand, new Map()), "parts"), []);
        hands[h] = { parts: Array.isArray(parts) ? parts.length : parts instanceof Map ? parts.size : 0, color: get(hand, "color") ?? null };
      }
    }
    const held = index.at(["resources", "hand_sets", pyKey(name)]);
    const until = Math.max(index.valueEnd(held) - 1, 0);
    const last = (index.text.slice(0, until).match(/\n/g)?.length ?? 0) + 1;
    out.push({ name: pyKey(name), hands, placed_by: placedBy(index, pyKey(name)), line: held.key.start.line + 1, end: last });
  }
  return out;
}
