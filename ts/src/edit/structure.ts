// Structural patches: elements moved between blocks, grouped and
// ungrouped, and new elements of every type.
//
// An element block is an id-keyed mapping: the top level's and a layout's
// `static:` and `elements:`, and a group's `children:`. Moving an element
// between two of them cuts its lines (its leading comments with it, the
// rule `SpanIndex.entryRange` follows) and pastes them into the other,
// re-indented by the difference between the two blocks' indents. Nothing
// inside the element is re-serialised. A block that does not exist yet is
// created; one emptied by a move goes, with its key, as `remove` does.
//
// Grouping wraps sibling elements in a new `group` with only `type:` and
// `children:`, whose box is its parent's, so nothing moves on the screen.
// Ungrouping is the reverse, and is refused for a group with any other key
// (`at:`, `visible:`, ...), since its children would lose what it gives
// them.
//
// Pasting puts elements copied as text (one face's, or another's) into a
// block the same way, as written: an id the face already has is renamed,
// and anything else the copy needs (a colour, a font, a slot) is the
// gate's to refuse.
import { deepCopy, quoted, splitlines } from "../py.ts";
import * as seriesCatalog from "../series.ts";
import {
  blockText, child, dataAt, DEFAULTS, endedPatch, faceColor, keyText, patch, type Patch, rebuild, removeOn, ShapeError, withData,
} from "./patch.ts";
import { dotted, ELEMENT_BLOCKS, type Entry, indexFor, isElement, lineEnd, type Path, pathKey, Refused, SpanIndex } from "./spans.ts";
import type { Data, DataKey } from "./yaml.ts";

/** The types `add` needs a choice for, and what the choice names. */
export const CHOICES: ReadonlyMap<string, string> = new Map([["graph", "series"], ["data", "slot"], ["hands", "set"]]);

const m = (...pairs: [string, Data][]): Map<DataKey, Data> => new Map(pairs);

/** New elements of the types `DEFAULTS` leaves out. */
export const MORE_DEFAULTS: ReadonlyMap<string, Map<DataKey, Data>> = new Map([
  ["icon", m(["icon", "heart"], ["at", m(["anchor", "center"])], ["size", "12%r"])],
  ["gauge", m(["style", "bar"], ["value", "system.battery"], ["max", 100],
    ["at", m(["anchor", "center"])], ["size", m(["width", "40%"], ["height", "3%"])])],
  ["graph", m(["at", m(["anchor", "center"])], ["size", m(["width", "50%"], ["height", "20%"])])],
  ["pattern", m(["pattern", "radial"], ["at", m(["anchor", "center"])], ["count", 12],
    ["parts", [m(["type", "line"], ["at", m(["dy", "-96%r"])], ["to", m(["dy", "-88%r"])], ["thickness", "2px"])]])],
  ["data", m(["at", m(["anchor", "center"])])],
  ["hands", m(["at", m(["anchor", "center"])])],
  ["group", m(["children", new Map()])],
]);

/** Types drawn without a `color:` of their own. */
const NO_COLOR: ReadonlySet<string> = new Set(["group", "hands"]);

export function elementTypes(): string[] {
  return [...new Set([...DEFAULTS.keys(), ...MORE_DEFAULTS.keys()])].sort();
}

/** A range the series can show: a week of days, half a day of hours, four hours of heart rate. */
function graphRange(series: string): string | number {
  const interval = seriesCatalog.get(series)?.interval_seconds ?? null;
  if (interval === null) return "4h";
  return interval >= 86400 ? "7d" : interval >= 3600 ? "12h" : 12;
}

/** What a new element of `type` starts with: its defaults, the face's most used colour, and the series, slot or set `choice` names. */
export function newFields(index: SpanIndex, type: string, choice?: string | null): Map<DataKey, Data> {
  const defaults = DEFAULTS.get(type) ?? MORE_DEFAULTS.get(type);
  if (defaults === undefined) throw new Refused(`there is no element type ${quoted(type)}`);
  const fields: Map<DataKey, Data> = new Map([["type", type], ...deepCopy(defaults)]);
  const chosen = CHOICES.get(type);
  if (chosen !== undefined) {
    if (!choice) throw new Refused(`a ${type} needs its ${chosen}`);
    fields.set(chosen, choice);
    if (type === "graph") fields.set("range", graphRange(choice));
  }
  if (!NO_COLOR.has(type)) fields.set("color", faceColor(index));
  return fields;
}

export function freshId(index: SpanIndex, base: string): string {
  const taken = index.elementIds();
  for (let n = 1; ; n++) {
    const candidate = n === 1 ? base : `${base}${n}`;
    if (!taken.has(candidate)) return candidate;
  }
}

// -- text helpers -------------------------------------------------------------

function reindent(segment: string, old: number, next: number): string {
  const out: string[] = [];
  for (const line of splitlines(segment)) {
    if (line.trim() === "") out.push(line.endsWith("\n") ? "\n" : "");
    else if (next >= old) out.push(" ".repeat(next - old) + line);
    else {
      const cut = Math.min(old - next, line.length - line.replace(/^ +/, "").length);
      out.push(line.slice(cut));
    }
  }
  return out.join("");
}

/** An element's lines, leading comments included, and its key's column. */
function segmentOf(index: SpanIndex, entry: Entry): [string, number] {
  const [start, end] = index.entryRange(entry);
  return [index.text.slice(start, end), entry.key.start.column];
}

function checkBlock(index: SpanIndex, block: Path): void {
  if (block.length === 0 || !ELEMENT_BLOCKS.has(String(block[block.length - 1]))) {
    throw new Refused(`${dotted(block)} is not an element block (static:, elements: or a group's children:)`);
  }
  if (block[block.length - 1] === "children") {
    const parent = block.slice(0, -1);
    const group = index.get(parent);
    const data = group === undefined ? undefined : dataAt(index.data, parent);
    if (group === undefined || !isElement(index, group) || !(data instanceof Map) || data.get("type") !== "group") {
      throw new Refused(`${dotted(parent)} is not a group`);
    }
  }
}

/**
 * The text with an element's `lines` (written at `column`) pasted into
 * `block`: before the element `before`, or at its end. The block is created
 * when it does not exist; an empty one (`{}`, nothing) is filled.
 */
function pasteLines(index: SpanIndex, block: Path, lines: string, column: number, before: string | null): string {
  const text = index.text;
  const holder = index.get(block);
  if (holder !== undefined && holder.value.kind === "mapping" && !holder.value.flow && holder.value.pairs.length > 0) {
    const mapping = holder.value;
    const indent = mapping.pairs[0]![0].start.column;
    const siblings = index.entries().filter((e) => e.parent === mapping);
    let at: number;
    if (before !== null) {
      const anchor = siblings.find((e) => e.name === before);
      if (anchor === undefined) throw new Refused(`${before} is not in ${dotted(block)}`);
      at = index.entryRange(anchor)[0];
    } else {
      at = index.valueEnd(siblings[siblings.length - 1]!);
    }
    return text.slice(0, at) + reindent(lines, column, indent) + text.slice(at);
  }
  if (holder !== undefined) {
    const value = holder.value;
    const empty = (value.kind === "mapping" && value.pairs.length === 0)
      || (value.kind === "scalar" && ["", "~", "null"].includes(value.value));
    if (!empty) throw new Refused(`${dotted(block)} is not a block of elements`);
    // an empty value sits on its key's line: the rest of it goes
    const indent = holder.key.start.column + 2;
    const colon = text.indexOf(":", holder.key.end.index);
    if (colon < 0) throw new ShapeError("substring not found");
    const eol = lineEnd(text, holder.key.start.index);
    return text.slice(0, colon + 1) + "\n" + reindent(lines, column, indent) + text.slice(eol);
  }
  // the block itself is new: its key in its parent mapping
  const parentPath = block.slice(0, -1);
  let indent: number, at: number;
  if (parentPath.length > 0) {
    const parent = index.get(parentPath);
    if (parent === undefined || parent.value.kind !== "mapping" || parent.value.flow) {
      throw new Refused(`${dotted(parentPath)} is not a block mapping`);
    }
    const mapping = parent.value;
    indent = mapping.pairs.length > 0 ? mapping.pairs[0]![0].start.column : parent.key.start.column + 2;
    const siblings = index.entries().filter((e) => e.parent === mapping);
    at = siblings.length > 0 ? index.valueEnd(siblings[siblings.length - 1]!) : lineEnd(text, parent.key.start.index);
  } else {
    indent = 0;
    at = text.length;
  }
  const head = " ".repeat(indent) + keyText(String(block[block.length - 1])) + ":\n";
  const sep = parentPath.length === 0 && text && !text.endsWith("\n\n") ? "\n" : "";
  return text.slice(0, at) + sep + head + reindent(lines, column, indent + 2) + text.slice(at);
}

/** Into the data: `name: value` in `block`, created when missing. */
function put(expected: Data, block: Path, name: string, value: Data, before: string | null): void {
  let holder: Data = expected;
  for (const step of block.slice(0, -1)) holder = child(holder, step);
  if (!(holder instanceof Map)) throw new ShapeError("not a mapping");
  const last = block[block.length - 1]!;
  if (!(holder.get(last) instanceof Map)) holder.set(last, new Map());
  const target = holder.get(last) as Map<DataKey, Data>;
  if (before === null) {
    target.set(name, value);
    return;
  }
  const items = [...target];
  const at = items.findIndex(([k]) => k === before);
  if (at < 0) throw new ShapeError("no such key in the mapping");
  items.splice(at, 0, [name, value]);
  rebuild(target, items);
}

// -- the patches ----------------------------------------------------------------

function moveTo(index: SpanIndex, path: Path, block: Path, before: string | null): Patch {
  const entry = index.at(path);
  if (!isElement(index, entry)) throw new Refused(`${dotted(path)} is not an element`);
  if (entry.isFlow) throw new Refused(`${entry.name} is in a flow mapping; edit it in the text`);
  checkBlock(index, block);
  if (pathKey(block) === pathKey(path.slice(0, -1))) throw new Refused(`${entry.name} is already in ${dotted(block)}`);
  if (pathKey(block.slice(0, path.length)) === pathKey(path)) throw new Refused(`${entry.name} cannot move into itself`);
  if (before === entry.name) throw new Refused(`${entry.name} cannot go before itself`);
  const [lines, column] = segmentOf(index, entry);
  const value = deepCopy(dataAt(index.data, path));
  const removed = removeOn(index, path);
  const after = indexFor(removed.text);
  if (after.get(block) === undefined && block.length > 1 && after.get(block.slice(0, -1)) === undefined) {
    throw new Refused(`${dotted(block.slice(0, -1))} would not exist after the move`);
  }
  const text = pasteLines(after, block, lines, column, before);
  const expected = deepCopy(removed.expected);
  put(expected, block, entry.name, value, before);
  return patch(text, expected, `move ${entry.name} to ${dotted(block)}`);
}

function addOn(index: SpanIndex, type: string, block: Path, before: string | null,
  elementId: string | null, choice: string | null): Patch {
  checkBlock(index, block);
  const fields = newFields(index, type, choice);
  const newId = elementId || freshId(index, `new_${type}`);
  if (index.elementIds().has(newId)) throw new Refused(`there is already an element called ${newId}`);
  const lines = `${keyText(newId)}:\n` + blockText(fields, 2);
  const text = pasteLines(index, block, lines, 0, before);
  const expected = withData(index);
  put(expected, block, newId, fields, before);
  return patch(text, expected, `add ${newId}`);
}

const NOT_ELEMENTS = "what is pasted is not elements: copy them in the editor, or paste YAML of the form `id: {type: ...}`";

function pasteText(index: SpanIndex, clip: string, block: Path, before: string | null): Patch {
  checkBlock(index, block);
  if (!clip.endsWith("\n")) clip += "\n";
  const root = new SpanIndex(clip).root;
  if (root === null || root.kind !== "mapping" || root.flow || root.pairs.length === 0) throw new Refused(NOT_ELEMENTS);
  // read as an element block, so every element in it is one
  const head = "elements:\n";
  let wrapped = head + reindent(clip, root.pairs[0]![0].start.column, 2);
  const source = new SpanIndex(wrapped);
  const tops = source.entries().filter((e) => e.path.length === 2);
  if (!tops.every((e) => isElement(source, e))) throw new Refused(NOT_ELEMENTS);
  // every id the copy brings that the face has already is renamed; last
  // first, so each rewrite leaves the positions before it, and a name the
  // copy keeps is taken before an earlier one could be renamed to it
  const taken = new Set(index.elementIds());
  for (const e of [...source.elements()].sort((a, b) => b.key.start.index - a.key.start.index)) {
    let name = e.name;
    for (let n = 2; taken.has(name); n++) name = `${e.name}${n}`;
    taken.add(name);
    if (name !== e.name) wrapped = wrapped.slice(0, e.key.start.index) + keyText(name) + wrapped.slice(e.key.end.index);
  }
  const pasted = new SpanIndex(wrapped);
  const text = pasteLines(index, block, wrapped.slice(head.length), 2, before);
  const expected = withData(index);
  const fresh = pasted.entries().filter((e) => e.path.length === 2);
  for (const e of fresh) put(expected, block, e.name, deepCopy(dataAt(pasted.data, e.path)), before);
  return patch(text, expected, "paste " + fresh.map((e) => e.name).join(", "));
}

function groupOn(index: SpanIndex, paths: Path[], groupId: string | null): Patch {
  if (paths.length === 0) throw new Refused("nothing to group");
  const entries = paths.map((p) => index.at(p));
  for (const e of entries) {
    if (!isElement(index, e)) throw new Refused(`${dotted(e.path)} is not an element`);
    if (e.isFlow) throw new Refused(`${e.name} is in a flow mapping; edit it in the text`);
  }
  const block = paths[0]!.slice(0, -1);
  if (paths.some((p) => pathKey(p.slice(0, -1)) !== pathKey(block))) {
    throw new Refused("only elements side by side in one block can be grouped");
  }
  entries.sort((a, b) => a.key.start.index - b.key.start.index);
  const newId = groupId || freshId(index, "group");
  if (index.elementIds().has(newId)) throw new Refused(`there is already an element called ${newId}`);
  const column = entries[0]!.key.start.column;
  let text = index.text;
  const siblings = index.entries().filter((e) => e.parent === entries[0]!.parent);
  const at = siblings.indexOf(entries[0]!);
  const firstStart = index.entryRange(entries[0]!)[0];
  let children: string;
  if (siblings.slice(at, at + entries.length).map((e) => e.name).join("\0") === entries.map((e) => e.name).join("\0")) {
    // side by side: their whole span, the blank lines between them kept
    // inside the group, so ungrouping gives the text back as it was
    const lastEnd = index.valueEnd(entries[entries.length - 1]!);
    children = reindent(text.slice(firstStart, lastEnd), column, column + 4);
    text = text.slice(0, firstStart) + text.slice(lastEnd);
  } else {
    children = entries.map((e) => reindent(segmentOf(index, e)[0], column, column + 4)).join("");
    for (const e of [...entries].reverse()) {
      const [start, end] = index.entryRange(e);
      text = text.slice(0, start) + text.slice(end);
    }
  }
  const groupLines = " ".repeat(column) + `${keyText(newId)}:\n` + " ".repeat(column + 2)
    + "type: group\n" + " ".repeat(column + 2) + "children:\n" + children;
  text = text.slice(0, firstStart) + groupLines + text.slice(firstStart);
  const expected = withData(index);
  const holder = dataAt(expected, block);
  if (!(holder instanceof Map)) throw new ShapeError("not a mapping");
  const members = new Map<DataKey, Data>(entries.map((e) => [e.name, child(holder, e.name)]));
  const items: [DataKey, Data][] = [];
  for (const [k, v] of holder) {
    if (k === entries[0]!.name) items.push([newId, new Map<DataKey, Data>([["type", "group"], ["children", members]])]);
    else if (!members.has(k)) items.push([k, v]);
  }
  rebuild(holder, items);
  return patch(text, expected, `group ${entries.map((e) => e.name).join(", ")} as ${newId}`);
}

function ungroupOn(index: SpanIndex, path: Path): Patch {
  const entry = index.at(path);
  const data = dataAt(index.data, path);
  if (!isElement(index, entry) || !(data instanceof Map) || data.get("type") !== "group") {
    throw new Refused(`${dotted(path)} is not a group`);
  }
  if (entry.isFlow) throw new Refused(`${entry.name} is in a flow mapping; edit it in the text`);
  const extra = [...data.keys()].filter((k) => k !== "type" && k !== "children");
  if (extra.length > 0) {
    throw new Refused(`${entry.name} has ${extra.map(String).join(", ")}, which its children take from it; ` +
      "remove those first, or edit it in the text");
  }
  const children = index.get([...path, "children"]);
  const column = entry.key.start.column;
  let lifted = "";
  if (children !== undefined && children.value.kind === "mapping" && children.value.pairs.length > 0) {
    if (children.value.flow) throw new Refused(`${entry.name}'s children are in a flow mapping; edit them in the text`);
    const inner = children.value.pairs[0]![0].start.column;
    const first = index.entries().find((e) => e.parent === children.value)!;
    const start = index.entryRange(first)[0];
    const end = index.valueEnd(children);
    lifted = reindent(index.text.slice(start, end), inner, column);
  }
  const [g0, g1] = index.entryRange(entry);
  const text = index.text.slice(0, g0) + lifted + index.text.slice(g1);
  const expected = withData(index);
  const holder = dataAt(expected, path.slice(0, -1));
  if (!(holder instanceof Map)) throw new ShapeError("not a mapping");
  const kids = data.get("children");
  const kidMap = kids instanceof Map ? kids : new Map<DataKey, Data>();
  const clash = [...kidMap.keys()].filter((k) => holder.has(k) && k !== entry.name);
  if (clash.length > 0) throw new Refused(`${clash.map(String).join(", ")} already exist beside ${entry.name}`);
  const items: [DataKey, Data][] = [];
  for (const [k, v] of holder) {
    if (k === entry.name) for (const [ck, cv] of kidMap) items.push([ck, deepCopy(cv)]);
    else items.push([k, v]);
  }
  rebuild(holder, items);
  return patch(text, expected, `ungroup ${entry.name}`);
}

// -- the public operations --------------------------------------------------------

/** Move the element at `path` into `block` (another block's path), before its element `before` or at its end. */
export function moveToBlock(index: SpanIndex, path: Path, block: Path, before: string | null = null): Patch {
  return endedPatch(index, (i) => moveTo(i, path, block, before));
}

/** Add a new element of any type to `block`, before `before` or at its end (`newFields`). */
export function add(index: SpanIndex, type: string, block: Path = ["elements"], before: string | null = null,
  elementId: string | null = null, choice: string | null = null): Patch {
  return endedPatch(index, (i) => addOn(i, type, block, before, elementId, choice));
}

/** Wrap sibling elements in a new group, where the first of them was. */
export function group(index: SpanIndex, paths: Path[], groupId: string | null = null): Patch {
  return endedPatch(index, (i) => groupOn(i, paths, groupId));
}

/** Put the elements `clip` writes into `block`, before `before` or at its end, each id the face already has renamed with a number. */
export function paste(index: SpanIndex, clip: string, block: Path = ["elements"], before: string | null = null): Patch {
  return endedPatch(index, (i) => pasteText(i, clip, block, before));
}

/** Put a group's children where it was, and remove it. */
export function ungroup(index: SpanIndex, path: Path): Patch {
  return endedPatch(index, (i) => ungroupOn(i, path));
}
