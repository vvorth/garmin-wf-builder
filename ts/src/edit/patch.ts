// Text patches: every edit the editor makes, as characters rewritten in
// the design's own text.
//
// Each function takes a `SpanIndex` and returns a `Patch`: the new text and
// the plain data it must parse to. The data is computed from the original
// data with the one intended change, never from the new text, so the gate
// can check the text against it. A patch never re-serialises anything it
// does not change, so comments, quoting, flow or block style and blank
// lines outside the edit stay byte for byte.
//
// Four rules, each found on the example corpus:
//
// - a block value ends where the next token starts (`SpanIndex.valueEnd`);
// - removing the last entry of a block mapping removes the mapping's own
//   key too, since an emptied block mapping parses as null, and so does
//   removing the last item of a block sequence;
// - a list item is whole lines, from its own comment lines to its value's
//   last line, as a mapping entry is; moving items permutes those lines
//   and leaves the blank lines and shallower comments between them where
//   they are;
// - a duplicate renames every element id inside it, the element's own and
//   each descendant's, or a copied group's children clash with the
//   original's.
//
// Two patches can be one edit (`chain`): a colour's rename rewrites its key
// and every `color.<name>` that names it, and only the pair loads.
import { deepCopy, formatFixed, jsonString, reEscape, quoted, truthy } from "../py.ts";
import {
  dotted, type Entry, indentOf, isElement, lineEnd, lineStart, type Path, pathKey, parse, Refused,
  sameData, SpanIndex, type Step,
} from "./spans.ts";
import {
  type Data, type DataKey, type MappingNode, WholeFloat, type ScalarNode, type SequenceNode, Timestamp, type YamlNode,
} from "./yaml.ts";

/** A patched text and the data it must parse to. */
export interface Patch {
  text: string;
  expected: Data;
  /** What the patch does, in the author's terms: "set elements.clock.at.dy". */
  what: string;
}

export function patch(text: string, expected: Data, what: string): Patch {
  return { text, expected, what };
}

// -- rendering values -------------------------------------------------------

const PLAIN_SAFE = /^[A-Za-z0-9_.%#+\-/][A-Za-z0-9_.%#+\-/ ]*$/;

/** A number as the shortest plain text that reads back as it: no exponent, no trailing zeros. */
export function number(value: number): string {
  if (Number.isInteger(value)) return BigInt(value).toString();
  const text = formatFixed(value, 6).replace(/0+$/, "").replace(/\.$/, "");
  return text === "-0" || text === "" ? "0" : text;
}

function isNumber(value: unknown): value is number {
  return typeof value === "number";
}

/** `value` as a YAML scalar, in `style` (a node's own: `"`, `'` or null for plain) when that still reads back as `value`. */
export function scalar(value: Data, style: string | null = null): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (value instanceof WholeFloat) return number(value.value);
  if (isNumber(value)) return number(value);
  const text = value instanceof Timestamp ? value.iso : String(value);
  if (style === "'") return "'" + text.replaceAll("'", "''") + "'";
  if (style === "\"") return jsonString(text);
  if (PLAIN_SAFE.test(text) && !text.endsWith(" ") && readsBack(text)) return text;
  return jsonString(text);
}

function readsBack(text: string): boolean {
  try {
    return sameData(parse(`k: ${text}\n`), new Map([["k", text]]));
  } catch (error) {
    if (error instanceof Refused) return false;
    throw error;
  }
}

/** A mapping key: plain, unless it would not read back or holds a colon (`"shape:round"`, the guide's own spelling). */
export function keyText(key: string): string {
  if (key.includes(":") || !PLAIN_SAFE.test(key) || !readsBack(key)) return jsonString(key);
  return key;
}

/** `value` in flow style, the examples' spacing: `{ a: 1, b: 2 }`. */
export function flow(value: Data): string {
  if (value instanceof Map) {
    if (value.size === 0) return "{}";
    return "{ " + [...value].map(([k, v]) => `${yamlKey(k)}: ${flow(v)}`).join(", ") + " }";
  }
  if (Array.isArray(value)) return "[" + value.map(flow).join(", ") + "]";
  return scalar(value);
}

/** A mapping key as YAML writes it, so it reads back as the same key: a string through `keyText`, `null`, `true`, `false` and a number plain. */
export function yamlKey(key: DataKey): string {
  if (typeof key === "string") return keyText(key);
  if (key === null) return "null";
  return String(key);
}

// -- data helpers -----------------------------------------------------------

/**
 * The data is not the shape its caller already checked (through the span
 * index or the gate): a bug in the patch engine, never the author's mistake,
 * which is `Refused`.
 */
export class ShapeError extends Error {}

/** `container[step]`: a mapping's key, or a list's index (negative counts from the end). */
export function child(container: unknown, step: DataKey): Data {
  if (container instanceof Map && container.has(step)) return container.get(step)!;
  if (Array.isArray(container) && typeof step === "number" && Number.isInteger(step)) {
    const found = container.at(step) as Data | undefined;
    if (found !== undefined) return found;
  }
  throw new ShapeError(`no ${quoted(step)} in this data`);
}

/** `container[step] = value`: a mapping's key, or a list's existing index. */
export function setChild(container: unknown, step: DataKey, value: Data): void {
  if (container instanceof Map) {
    container.set(step, value);
    return;
  }
  if (Array.isArray(container) && typeof step === "number" && Number.isInteger(step)) {
    const i = step < 0 ? container.length + step : step;
    if (i >= 0 && i < container.length) {
      container[i] = value;
      return;
    }
  }
  throw new ShapeError(`cannot set ${quoted(step)} in this data`);
}

/** Remove `container[step]`: a mapping's key, or a list's index. */
export function deleteChild(container: unknown, step: DataKey): void {
  if (container instanceof Map && container.delete(step)) return;
  if (Array.isArray(container) && typeof step === "number" && Number.isInteger(step)) {
    const i = step < 0 ? container.length + step : step;
    if (i >= 0 && i < container.length) {
      container.splice(i, 1);
      return;
    }
  }
  throw new ShapeError(`no ${quoted(step)} to remove in this data`);
}

export function dataAt(data: Data, path: Path): Data {
  for (const step of path) data = child(data, step);
  return data;
}

export function withData(index: SpanIndex): Data {
  return deepCopy(index.data);
}

function nested(rest: Path, value: Data): Data {
  for (let i = rest.length - 1; i >= 0; i--) value = new Map([[rest[i]!, value]]);
  return value;
}

/** Python's `dict(items)` into `mapping`, in place: a repeated key keeps its first place and its last value. */
export function rebuild(mapping: Map<DataKey, Data>, items: [DataKey, Data][]): void {
  mapping.clear();
  for (const [k, v] of items) mapping.set(k, v);
}

export function insertAfter(mapping: Data, after: DataKey | undefined, key: DataKey, value: Data): void {
  if (!(mapping instanceof Map)) throw new ShapeError("not a mapping");
  const items = [...mapping];
  let at = items.length;
  if (after !== undefined) {
    const i = items.findIndex(([k]) => k === after);
    if (i < 0) throw new ShapeError("no such key in the mapping");
    at = i + 1;
  }
  items.splice(at, 0, [key, value]);
  rebuild(mapping, items);
}

// -- text helpers -----------------------------------------------------------

function ended(index: SpanIndex): [SpanIndex, boolean] {
  if (index.text && !index.text.endsWith("\n")) return [new SpanIndex(index.text + "\n"), true];
  return [index, false];
}

function restore(text: string, added: boolean): string {
  return added && text.endsWith("\n") ? text.slice(0, -1) : text;
}

export function blockIndent(mapping: MappingNode): number {
  return mapping.pairs.length > 0 ? mapping.pairs[0]![0].start.column : 0;
}

export function lastEntry(index: SpanIndex, mapping: MappingNode): Entry {
  const key = mapping.pairs[mapping.pairs.length - 1]![0];
  const entry = index.entries().find((e) => e.parent === mapping && e.key === key);
  if (entry === undefined) throw new Refused("the mapping's last entry is not in the index");
  return entry;
}

/**
 * The node at `path`: the root, an entry's value, or a list item reached
 * through its indices from the deepest entry on the way (the index holds
 * entries for keys only, inside list items too, never for items).
 */
export function nodeAt(index: SpanIndex, path: Path): YamlNode | undefined {
  let node: YamlNode | null = index.root;
  let from = 0;
  for (let depth = path.length; depth > 0; depth--) {
    const entry = index.get(path.slice(0, depth));
    if (entry !== undefined) {
      node = entry.value;
      from = depth;
      break;
    }
  }
  for (let i = from; i < path.length; i++) {
    const step = path[i];
    if (node === null || node.kind !== "sequence" || typeof step !== "number") return undefined;
    node = node.items[step] ?? null;
  }
  return node ?? undefined;
}

function mappingAt(index: SpanIndex, path: Path): MappingNode {
  const node = nodeAt(index, path);
  if (node === undefined) throw new Refused(path.length === 0 ? "the file is empty" : `${dotted(path)} is not in the file`);
  if (node.kind !== "mapping") throw new Refused(path.length === 0 ? "the file is not a mapping" : `${dotted(path)} is not a mapping`);
  return node;
}

/** The index of `needle` in `text` from `from`; absent, a `ShapeError`. */
export function indexOf(text: string, needle: string, from: number): number {
  const i = text.indexOf(needle, from);
  if (i < 0) throw new ShapeError("substring not found");
  return i;
}

/**
 * The text with `key: value` added to `mapping`: before a flow mapping's
 * closing brace, or on its own line at a block mapping's indent after its
 * last entry (or after `after`). With `block`, a mapping value in a block
 * mapping is written in block style, and a new top-level key gets a blank
 * line before it.
 */
function insertKey(index: SpanIndex, mapping: MappingNode, key: string, value: Data,
  after?: Entry, block = false): string {
  const text = index.text;
  if (mapping.flow) {
    const close = mapping.end.index - 1;
    if (text[close] !== "}") throw new Refused("cannot find the flow mapping's closing brace");
    const before = text.slice(0, close).trimEnd();
    const sep = before.endsWith("{") ? "" : ",";
    const pad = text[close - 1] === " " || before.endsWith("{") ? " " : "";
    return before + `${sep} ${keyText(key)}: ${flow(value)}` + pad + text.slice(close);
  }
  if (mapping.pairs.length === 0) throw new Refused("cannot add a key to an empty mapping");
  const indent = blockIndent(mapping);
  const end = index.valueEnd(after ?? lastEntry(index, mapping));
  let line: string;
  if (block && (value instanceof Map || Array.isArray(value)) && truthy(value)) {
    line = " ".repeat(indent) + `${keyText(key)}:\n` + blockText(value, indent + 2);
    if (mapping === index.root && !text.slice(0, end).endsWith("\n\n")) line = "\n" + line;
  } else {
    line = " ".repeat(indent) + `${keyText(key)}: ${flow(value)}\n`;
  }
  return text.slice(0, end) + line + text.slice(end);
}

// -- scalar and key patches -------------------------------------------------

function quoteStyle(node: ScalarNode): string | null {
  return node.style === "'" || node.style === "\"" ? node.style : null;
}

function setValueOn(index: SpanIndex, path: Path, value: Data, block = false): Patch {
  const expected = withData(index);
  const what = `set ${dotted(path)}`;
  const text = index.text;
  const entry = index.get(path);
  // an entry's value, or a whole list item (a path ending in an index)
  const node = entry?.value ?? (typeof path[path.length - 1] === "number" ? nodeAt(index, path) : undefined);
  if (node !== undefined) {
    const empty = node.kind === "scalar" && node.value === "" && node.style === null;
    if (entry === undefined && empty) throw new Refused(`${dotted(path)} is an empty item; edit it in the text`);
    setChild(dataAt(expected, path.slice(0, -1)), path[path.length - 1]!, value);
    let replacement: string;
    if (node.kind === "scalar" && !(value instanceof Map) && !Array.isArray(value)) {
      replacement = scalar(value, quoteStyle(node));
    } else if (node.kind === "scalar" || node.flow) {
      replacement = flow(value);
    } else if (entry !== undefined) {
      return patch(replaceBlock(index, entry, value), expected, what);
    } else {
      throw new Refused(`${dotted(path)} is a block item: remove it and insert the new one`);
    }
    let start = node.start.index, end = node.end.index;
    if (entry !== undefined && empty) {
      if (block && !entry.isFlow && (value instanceof Map || Array.isArray(value)) && truthy(value)) {
        // an empty value (`key:`) under a block mapping takes block lines after the key's own line
        const after = lineEnd(text, entry.key.start.index);
        return patch(text.slice(0, after) + blockText(value, entry.key.start.column + 2) + text.slice(after), expected, what);
      }
      // an empty value has a zero-width node: write after the colon
      start = end = indexOf(text, ":", entry.key.end.index) + 1;
      replacement = " " + replacement;
    }
    return patch(text.slice(0, start) + replacement + text.slice(end), expected, what);
  }
  // the deepest existing ancestor that is a mapping
  let depth = path.length - 1;
  for (; depth >= 0; depth--) {
    if (depth === 0 || nodeAt(index, path.slice(0, depth)) !== undefined) break;
  }
  const prefix = path.slice(0, depth);
  const rest = path.slice(depth);
  if (nodeAt(index, prefix)?.kind === "sequence" && typeof rest[0] === "number") throw new Refused(`${dotted(path.slice(0, depth + 1))} is not in the file`);
  const mapping = mappingAt(index, prefix);
  if (rest.some((step) => typeof step !== "string")) throw new Refused(`cannot create the list item ${dotted(path)}; insert it`);
  const holder = dataAt(expected, prefix);
  if (!(holder instanceof Map)) throw new Refused(`${dotted(prefix)} is not a mapping`);
  holder.set(rest[0]!, nested(rest.slice(1), value));
  const added = insertKey(index, mapping, String(rest[0]), nested(rest.slice(1), value), undefined, block);
  return patch(added, expected, what);
}

/**
 * `value` as block lines at `indent`: a mapping's keys one per line, a
 * list's items as `- item`, anything nested in a list in flow style,
 * except a mapping item holding a list of mappings (a polygon part's
 * `points:`), which is a block under its dash, one point a line.
 */
export function blockText(value: Data, indent: number): string {
  const pad = " ".repeat(indent);
  const lines: string[] = [];
  if (value instanceof Map) {
    for (const [k, v] of value) {
      if ((v instanceof Map || Array.isArray(v)) && truthy(v)) lines.push(`${pad}${yamlKey(k)}:\n` + blockText(v, indent + 2));
      else lines.push(`${pad}${yamlKey(k)}: ${flow(v)}\n`);
    }
  } else if (Array.isArray(value)) {
    for (const entry of value) {
      if (entry instanceof Map && [...entry.values()].some((v) => Array.isArray(v) && v.length > 0 && v[0] instanceof Map)) {
        lines.push(`${pad}- ` + blockText(entry, indent + 2).slice(indent + 2));
      } else {
        lines.push(`${pad}- ${flow(entry)}\n`);
      }
    }
  } else {
    throw new ShapeError("not iterable");
  }
  return lines.join("");
}

/**
 * The text with a block mapping's or sequence's value replaced by `value`,
 * in block style at the same indent. The key's own line, and any comment on
 * it, stays; comments inside the old value go with it.
 */
function replaceBlock(index: SpanIndex, entry: Entry, value: Data): string {
  const text = index.text;
  const node = entry.value;
  const end = index.valueEnd(entry);
  const sameShape = node.kind === "mapping" ? value instanceof Map : Array.isArray(value);
  if ((value instanceof Map || Array.isArray(value)) && truthy(value) && sameShape) {
    const first = node.kind === "mapping" ? node.pairs[0]![0] : (node as { items: YamlNode[] }).items[0]!;
    const indent = node.kind === "mapping" ? first.start.column : indentOf(text, first.start.index);
    const start = lineEnd(text, entry.key.start.index);
    return text.slice(0, start) + blockText(value, indent) + text.slice(end);
  }
  // an empty or differently shaped value: on the key's line, in flow style
  const colon = indexOf(text, ":", entry.key.end.index) + 1;
  return text.slice(0, colon) + " " + flow(value) + "\n" + text.slice(end);
}

function renameKeyOn(index: SpanIndex, path: Path, renamed: string): Patch {
  const entry = index.at(path);
  if (index.get([...path.slice(0, -1), renamed]) !== undefined) {
    throw new Refused(`${dotted([...path.slice(0, -1), renamed])} already exists`);
  }
  const expected = withData(index);
  const holder = dataAt(expected, entry.path.slice(0, -1));
  if (!(holder instanceof Map)) throw new ShapeError("not a mapping");
  const last = entry.path[entry.path.length - 1];
  rebuild(holder, [...holder].map(([k, v]) => [k === last ? renamed : k, v]));
  const { index: start } = entry.key.start, { index: end } = entry.key.end;
  return patch(index.text.slice(0, start) + keyText(renamed) + index.text.slice(end), expected,
    `rename ${dotted(entry.path)} to ${renamed}`);
}

/** Every string scalar that is a value (a mapping's value or a list's item, never a key), in document order. */
function stringValues(node: YamlNode): ScalarNode[] {
  if (node.kind === "mapping") return node.pairs.flatMap(([, v]) => stringValues(v));
  if (node.kind === "sequence") return node.items.flatMap(stringValues);
  return node.tag.endsWith(":str") && node.style !== "|" && node.style !== ">" ? [node] : [];
}

function rewriteData(data: Data, fn: (s: string) => string): Data {
  if (data instanceof Map) return new Map([...data].map(([k, v]) => [k, rewriteData(v, fn)]));
  if (Array.isArray(data)) return data.map((v) => rewriteData(v, fn));
  return typeof data === "string" ? fn(data) : data;
}

function rewriteScalarsOn(index: SpanIndex, fn: (s: string) => string, what: string): Patch {
  let text = index.text;
  const nodes = index.root === null ? [] : stringValues(index.root);
  for (const node of [...nodes].reverse()) {
    const replacement = fn(node.value);
    if (replacement !== node.value) {
      text = text.slice(0, node.start.index) + scalar(replacement, quoteStyle(node)) + text.slice(node.end.index);
    }
  }
  return patch(text, rewriteData(withData(index), fn), what);
}

/**
 * `first` followed by each of `then`, in turn, on the text the one before
 * left, as one patch. Every text along the way is checked against its data
 * before the next step builds on it, so the chain keeps each step's
 * guarantee.
 */
export function chain(first: Patch, ...then: ((index: SpanIndex) => Patch)[]): Patch {
  let result = first;
  for (const step of then) {
    const index = new SpanIndex(result.text);
    if (!sameData(index.data, result.expected)) throw new Refused(`${result.what}: the edit would change more than intended`);
    const next = step(index);
    result = patch(next.text, next.expected, `${result.what}; ${next.what}`);
  }
  return result;
}

/**
 * Remove the entry at `path`. A mapping the removal empties, flow or
 * block, goes with its own key, and so on upward: the last `dx:` of an
 * override leaves no `at: {}`, `fr955: {}` or `overrides: {}` behind.
 */
export function removeOn(index: SpanIndex, path: Path): Patch {
  const entry = index.at(path);
  const expected = withData(index);
  const holder = index.holder(entry.parent);
  if (entry.parent.pairs.length === 1 && holder !== undefined) {
    const removed = removeOn(index, holder.path);
    return patch(removed.text, removed.expected, `remove ${dotted(entry.path)}`);
  }
  deleteChild(dataAt(expected, entry.path.slice(0, -1)), entry.path[entry.path.length - 1]!);
  const text = index.text;
  if (entry.isFlow) {
    const pairs = entry.parent.pairs;
    const i = pairs.findIndex(([k]) => k === entry.key);
    if (pairs.length === 1) {
      const start = entry.parent.start.index, end = entry.parent.end.index;
      return patch(text.slice(0, start) + "{}" + text.slice(end), expected, `remove ${dotted(entry.path)}`);
    }
    let start = entry.key.start.index, end = entry.value.end.index;
    if (i + 1 < pairs.length) end = pairs[i + 1]![0].start.index; // eat the following ", "
    else start = pairs[i - 1]![1].end.index; // eat the preceding ", "
    return patch(text.slice(0, start) + text.slice(end), expected, `remove ${dotted(entry.path)}`);
  }
  const lead = text.slice(lineStart(text, entry.key.start.index), entry.key.start.index);
  if (lead.trim() !== "") {
    // the first key of a block list item shares its line with the dash (`- type: polygon`):
    // the next key moves up onto that line, or `{}` is left when there is none
    const pairs = entry.parent.pairs;
    const next = pairs.length > 1 ? pairs[1]![0] : undefined;
    const end = next !== undefined ? next.start.index : index.valueEnd(entry);
    return patch(text.slice(0, entry.key.start.index) + (next !== undefined ? "" : "{}\n") + text.slice(end), expected, `remove ${dotted(entry.path)}`);
  }
  const [start, end] = index.entryRange(entry);
  return patch(text.slice(0, start) + text.slice(end), expected, `remove ${dotted(entry.path)}`);
}

// -- list items -------------------------------------------------------------

function sequenceAt(index: SpanIndex, path: Path): SequenceNode {
  const node = nodeAt(index, path);
  if (node === undefined) throw new Refused(`${dotted(path)} is not in the file`);
  if (node.kind !== "sequence") throw new Refused(`${dotted(path)} is not a list`);
  return node;
}

/**
 * Each item of a block sequence as whole lines: from its leading comment
 * lines at the dash's indent to its value's last line, trailing blank
 * lines and shallower comments left to what follows (as `entryRange` cuts
 * a mapping entry). The dashes are found in the text: the lines inside
 * the sequence holding `-` at its column with nothing but spaces before.
 */
function blockItemRanges(index: SpanIndex, seq: SequenceNode, path: Path): [number, number][] {
  const text = index.text;
  const first = lineStart(text, seq.start.index);
  if (text.slice(first, seq.start.index).trim() !== "") throw new Refused(`${dotted(path)} shares a line with its parent; edit it in the text`);
  const column = seq.start.index - first;
  const dashes: number[] = [];
  for (let p = first; p < seq.end.index; p = lineEnd(text, p)) {
    const line = text.slice(p, lineEnd(text, p)).replace(/\n$/, "");
    if (line.slice(0, column).trim() === "" && line[column] === "-" && (line.length === column + 1 || line[column + 1] === " ")) dashes.push(p + column);
  }
  if (dashes.length !== seq.items.length || dashes.some((d, i) => d >= seq.items[i]!.start.index)) {
    throw new Refused(`${dotted(path)} has an item the editor cannot place; edit it in the text`);
  }
  return dashes.map((dash, i) => {
    let start = lineStart(text, dash);
    while (start > 0) {
      const prev = lineStart(text, start - 1);
      const line = text.slice(prev, start - 1);
      if (line.trim().startsWith("#") && line.length - line.trimStart().length === column) start = prev;
      else break;
    }
    const endIndex = seq.items[i]!.end.index;
    const head = lineStart(text, endIndex);
    let end = text.slice(head, endIndex).trim() === "" && head > dash ? head : lineEnd(text, Math.max(endIndex - 1, 0));
    const dashLine = lineStart(text, dash);
    while (end > dashLine) {
      const last = lineStart(text, end - 1);
      if (last <= dashLine) break;
      const line = text.slice(last, end).replace(/\n$/, "");
      const stripped = line.trim();
      if (stripped === "" || (stripped.startsWith("#") && line.length - line.trimStart().length <= column)) end = last;
      else break;
    }
    return [start, end];
  });
}

/** Each item's characters: a flow item's own, a block item's whole lines (`blockItemRanges`). */
function itemRanges(index: SpanIndex, seq: SequenceNode, path: Path): [number, number][] {
  return seq.flow ? seq.items.map((item) => [item.start.index, item.end.index]) : blockItemRanges(index, seq, path);
}

/** The characters of the list at `path` an item edit may touch: its items from the first's own comment lines to the last's end. */
export function listSpan(index: SpanIndex, path: Path): [number, number] {
  const seq = sequenceAt(index, path);
  if (seq.flow) return [seq.start.index, seq.end.index];
  const ranges = blockItemRanges(index, seq, path);
  return [ranges[0]![0], ranges[ranges.length - 1]![1]];
}

/** The separator the new item at `at` of a flow sequence takes: the one between the neighbours it lands by, or `, `. */
function flowSeparator(text: string, items: YamlNode[], at: number): string {
  const k = Math.min(Math.max(at - 1, 0), items.length - 2);
  if (k < 0) return ", ";
  const gap = text.slice(items[k]!.end.index, items[k + 1]!.start.index);
  return gap.includes("#") ? ", " : gap;
}

function listIndex(path: Path, seq: SequenceNode, at: number, insert: boolean): void {
  const length = seq.items.length;
  if (insert ? Number.isInteger(at) && at >= 0 && at <= length : Number.isInteger(at) && at >= 0 && at < length) return;
  const n = `${length} item${length === 1 ? "" : "s"}`;
  throw new Refused(insert ? `${dotted(path)} has ${n}: insert at 0 to ${length}` : `${dotted(path)} has ${n}; there is no item ${at}`);
}

function insertItemOn(index: SpanIndex, path: Path, at: number, value: Data, block: boolean): Patch {
  const what = `insert ${dotted(path)}.${at}`;
  const node = nodeAt(index, path);
  if (node === undefined || (node.kind === "scalar" && node.value === "" && node.style === null && index.get(path) !== undefined)) {
    // no list yet (the key is missing or empty): the first item makes it, as `setValue` writes a list
    if (at !== 0) throw new Refused(`${dotted(path)} has no items yet: insert at 0`);
    const made = setValueOn(index, path, [value], block);
    return patch(made.text, made.expected, what);
  }
  if (node.kind !== "sequence") throw new Refused(`${dotted(path)} is not a list`);
  listIndex(path, node, at, true);
  const expected = withData(index);
  const list = dataAt(expected, path);
  if (!Array.isArray(list)) throw new ShapeError("not a list");
  list.splice(at, 0, value);
  const text = index.text;
  const items = node.items;
  if (node.flow) {
    if (items.length === 0) return patch(text.slice(0, node.start.index) + `[${flow(value)}]` + text.slice(node.end.index), expected, what);
    const sep = flowSeparator(text, items, at);
    if (at === items.length) {
      const end = items[items.length - 1]!.end.index;
      return patch(text.slice(0, end) + sep + flow(value) + text.slice(end), expected, what);
    }
    const start = items[at]!.start.index;
    return patch(text.slice(0, start) + flow(value) + sep + text.slice(start), expected, what);
  }
  const ranges = blockItemRanges(index, node, path);
  const column = node.start.index - lineStart(text, node.start.index);
  const blockItems = items.some((item) => item.kind === "mapping" && !item.flow);
  const body = blockItems && value instanceof Map && value.size > 0 ? blockText(value, column + 2).slice(column + 2) : `${flow(value)}\n`;
  const line = " ".repeat(column) + "- " + body;
  const where = at === items.length ? ranges[items.length - 1]![1] : ranges[at]![0];
  return patch(text.slice(0, where) + line + text.slice(where), expected, what);
}

function removeItemOn(index: SpanIndex, path: Path, at: number): Patch {
  const what = `remove ${dotted(path)}.${at}`;
  const node = sequenceAt(index, path);
  listIndex(path, node, at, false);
  const text = index.text;
  const items = node.items;
  if (items.length === 1) {
    const holder = index.holder(node);
    if (!node.flow && holder !== undefined) {
      // an emptied block sequence cannot be written: its key goes, as an emptied block mapping's does
      const removed = removeOn(index, holder.path);
      return patch(removed.text, removed.expected, what);
    }
  }
  const expected = withData(index);
  deleteChild(dataAt(expected, path), at);
  if (items.length === 1) {
    const end = node.flow ? node.end.index : blockItemRanges(index, node, path)[0]![1];
    return patch(text.slice(0, node.start.index) + (node.flow ? "[]" : "[]\n") + text.slice(end), expected, what);
  }
  if (node.flow) {
    let start = items[at]!.start.index, end = items[at]!.end.index;
    if (at + 1 < items.length) end = items[at + 1]!.start.index; // eat the following separator
    else start = items[at - 1]!.end.index; // eat the preceding one
    return patch(text.slice(0, start) + text.slice(end), expected, what);
  }
  const [start, end] = blockItemRanges(index, node, path)[at]!;
  return patch(text.slice(0, start) + text.slice(end), expected, what);
}

function moveItemOn(index: SpanIndex, path: Path, from: number, to: number): Patch {
  const what = `move ${dotted(path)}.${from} to ${to}`;
  const node = sequenceAt(index, path);
  listIndex(path, node, from, false);
  listIndex(path, node, to, false);
  const expected = withData(index);
  const list = dataAt(expected, path);
  if (!Array.isArray(list)) throw new ShapeError("not a list");
  const [moved] = list.splice(from, 1);
  list.splice(to, 0, moved!);
  const text = index.text;
  if (from === to) return patch(text, expected, what);
  // the items' own text permutes; what lies between two slots (a separator, blank lines, a shallower comment) stays in its slot
  const ranges = itemRanges(index, node, path);
  const order = ranges.map((_, i) => i);
  order.splice(from, 1);
  order.splice(to, 0, from);
  let out = text.slice(0, ranges[0]![0]);
  for (let slot = 0; slot < order.length; slot++) {
    out += text.slice(...ranges[order[slot]!]!);
    if (slot + 1 < order.length) out += text.slice(ranges[slot]![1], ranges[slot + 1]![0]);
  }
  return patch(out + text.slice(ranges[ranges.length - 1]![1]), expected, what);
}

// -- element patches --------------------------------------------------------

export function elementAt(index: SpanIndex, path: Path): Entry {
  const entry = index.at(path);
  if (!isElement(index, entry)) throw new Refused(`${dotted(path)} is not an element`);
  if (entry.isFlow) throw new Refused(`${entry.name} is in a flow mapping; edit it in the text`);
  return entry;
}

function deleteElementOn(index: SpanIndex, path: Path): Patch {
  const entry = elementAt(index, path);
  const removed = removeOn(index, entry.path);
  return patch(removed.text, removed.expected, `delete ${entry.name}`);
}

/** The first of `_copy`, `_copy2`, ... that gives every id in `ids` a name no element in the file has. */
export function freshSuffix(index: SpanIndex, ids: string[], base = "_copy"): string {
  const taken = index.elementIds();
  for (let n = 1; ; n++) {
    const suffix = n === 1 ? base : `${base}${n}`;
    if (!ids.some((id) => taken.has(id + suffix))) return suffix;
  }
}

function duplicateElementOn(index: SpanIndex, path: Path): Patch {
  const entry = elementAt(index, path);
  const text = index.text;
  const [start, end] = index.entryRange(entry);
  const inside = index.elements().filter((e) => start <= e.key.start.index && e.key.start.index < end);
  const suffix = freshSuffix(index, inside.map((e) => e.name));
  let block = text.slice(start, end);
  for (const e of [...inside].sort((a, b) => b.key.start.index - a.key.start.index)) {
    const at = e.key.start.index - start;
    const width = e.key.end.index - e.key.start.index;
    block = block.slice(0, at) + keyText(e.name + suffix) + block.slice(at + width);
  }
  block = block.slice(lineStart(block, entry.key.start.index - start));
  const expected = withData(index);
  const parent = dataAt(expected, entry.path.slice(0, -1));
  const renamedPaths = new Set(inside.map((e) => pathKey(e.path.slice(entry.path.length))));
  const copied = renamedCopy(deepCopy(child(parent, entry.name)), renamedPaths, suffix, []);
  insertAfter(parent, entry.name, entry.name + suffix, copied);
  return patch(text.slice(0, end) + block + text.slice(end), expected, `duplicate ${entry.name} as ${entry.name + suffix}`);
}

function renamedCopy(node: Data, paths: Set<string>, suffix: string, here: Step[]): Data {
  if (node instanceof Map) {
    const out = new Map<DataKey, Data>();
    for (const [k, v] of node) {
      const inner = [...here, k as Step];
      out.set(paths.has(pathKey(inner)) ? `${String(k)}${suffix}` : k, renamedCopy(v, paths, suffix, inner));
    }
    return out;
  }
  if (Array.isArray(node)) return node.map((v, i) => renamedCopy(v, paths, suffix, [...here, i]));
  return node;
}

function moveElementOn(index: SpanIndex, path: Path, to: number): Patch {
  const entry = elementAt(index, path);
  const siblings = index.entries().filter((e) => e.parent === entry.parent);
  const here = siblings.indexOf(entry);
  if (!(to >= 0 && to < siblings.length)) throw new Refused(`${entry.name} cannot move to position ${to} of ${siblings.length}`);
  const expected = withData(index);
  const parent = dataAt(expected, entry.path.slice(0, -1));
  if (!(parent instanceof Map)) throw new ShapeError("not a mapping");
  const items = [...parent];
  const [moved] = items.splice(here, 1);
  items.splice(to, 0, moved!);
  rebuild(parent, items);
  if (to === here) return patch(index.text, expected, `move ${entry.name}`);
  const text = index.text;
  const [b0, b1] = index.entryRange(entry);
  const segment = text.slice(b0, b1);
  let result: string;
  if (to < here) {
    const [a0] = index.entryRange(siblings[to]!);
    result = text.slice(0, a0) + segment + text.slice(a0, b0) + text.slice(b1);
  } else {
    const a1 = index.valueEnd(siblings[to]!);
    result = text.slice(0, b0) + text.slice(b1, a1) + segment + text.slice(a1);
  }
  return patch(result, expected, `move ${entry.name} to position ${to}`);
}

const m = (...pairs: [string, Data][]): Map<DataKey, Data> => new Map(pairs);

/** What a new element of each type starts with, besides its colour. */
export const DEFAULTS: ReadonlyMap<string, Map<DataKey, Data>> = new Map([
  ["rectangle", m(["at", m(["anchor", "center"])], ["size", m(["width", "20%"], ["height", "10%"])])],
  ["ellipse", m(["at", m(["anchor", "center"])], ["size", m(["width", "20%"], ["height", "10%"])])],
  ["circle", m(["at", m(["anchor", "center"])], ["radius", "10%r"])],
  ["arc", m(["at", m(["anchor", "center"])], ["radius", "80%r"], ["thickness", "3px"],
    ["start_angle", "0deg"], ["sweep", "90deg"])],
  ["line", m(["at", m(["anchor", "center"])], ["to", m(["anchor", "center"], ["dx", "20%r"])], ["thickness", "2px"])],
  ["polygon", m(["points", [m(["anchor", "center"], ["dy", "-10%r"]),
    m(["anchor", "center"], ["dx", "-9%r"], ["dy", "5%r"]),
    m(["anchor", "center"], ["dx", "9%r"], ["dy", "5%r"])]])],
  ["text", m(["text", "Text"], ["font", "FONT_SMALL"], ["at", m(["anchor", "center"])])],
]);

/**
 * A colour the face already uses: the palette colour most element `color:`
 * keys name, else the palette's first colour, else white. The most used,
 * not the first, because the first is usually the background's; for the
 * same reason a tie goes to the first but that one.
 */
export function faceColor(index: SpanIndex): string {
  const counts = new Map<string, number>();
  for (const entry of index.entries()) {
    if (entry.name === "color" && entry.value.kind === "scalar" && entry.value.value.startsWith("color.")) {
      const name = entry.value.value;
      counts.set(name, (counts.get(name) ?? 0) + 1);
    }
  }
  if (counts.size > 0) {
    const most = Math.max(...counts.values());
    const tied = [...counts].filter(([, n]) => n === most).map(([name]) => name);
    return tied.length > 1 && tied[0] === counts.keys().next().value ? tied[1]! : tied[0]!;
  }
  const data = index.data;
  const resources = data instanceof Map ? data.get("resources") : undefined;
  const palette = resources instanceof Map ? resources.get("palette") : undefined;
  if (palette instanceof Map && palette.size > 0) return `color.${String(palette.keys().next().value)}`;
  return "#FFFFFF";
}

function addElementOn(index: SpanIndex, type: string, block: Path, after: string | undefined,
  elementId: string | undefined): Patch {
  const defaults = DEFAULTS.get(type);
  if (defaults === undefined) throw new Refused(`adding a ${type} is not supported yet; write it in the text`);
  const fields: Map<DataKey, Data> = new Map([["type", type], ...deepCopy(defaults), ["color", faceColor(index)]]);
  const taken = index.elementIds();
  let newId = elementId;
  if (!newId) {
    for (let n = 1; n < 10_000; n++) {
      const candidate = `new_${type}` + (n === 1 ? "" : String(n));
      if (!taken.has(candidate)) { newId = candidate; break; }
    }
  }
  if (newId === undefined) throw new ShapeError("no id left to give");
  if (taken.has(newId)) throw new Refused(`there is already an element called ${newId}`);
  const expected = withData(index);
  const text = index.text;
  const holder = index.get(block);
  if (holder === undefined) {
    if (block.length !== 1) throw new Refused(`${dotted(block)} does not exist`);
    setChild(expected, block[0]!, new Map([[newId, fields]]));
    const lines = [`${keyText(String(block[0]))}:`, `  ${keyText(newId)}:`,
      ...[...fields].map(([k, v]) => `    ${keyText(String(k))}: ${flow(v)}`)];
    const sep = text === "" || text.endsWith("\n\n") ? "" : "\n";
    return patch(text + sep + lines.join("\n") + "\n", expected, `add ${newId}`);
  }
  const mapping = holder.value;
  if (mapping.kind !== "mapping" || mapping.flow || mapping.pairs.length === 0) {
    throw new Refused(`${dotted(block)} is not a block of elements`);
  }
  const indent = blockIndent(mapping);
  const anchor = after !== undefined ? index.at([...block, after]) : lastEntry(index, mapping);
  const end = index.valueEnd(anchor);
  const lines = [" ".repeat(indent) + `${keyText(newId)}:`,
    ...[...fields].map(([k, v]) => " ".repeat(indent + 2) + `${keyText(String(k))}: ${flow(v)}`)];
  insertAfter(dataAt(expected, block), after, newId, fields);
  return patch(text.slice(0, end) + lines.join("\n") + "\n" + text.slice(end), expected, `add ${newId}`);
}

// -- the public operations: each runs on text with a final newline ----------

export function endedPatch(index: SpanIndex, op: (index: SpanIndex) => Patch): Patch {
  const [withNewline, added] = ended(index);
  const result = op(withNewline);
  return patch(restore(result.text, added), result.expected, result.what);
}

/**
 * Set the value at `path`: rewrite an existing scalar in place in its own
 * quoting, replace a flow value, or add the missing keys, as a nested flow
 * value under the deepest mapping that exists (in block style, with
 * `block`, when that mapping is a block mapping).
 */
export function setValue(index: SpanIndex, path: Path, value: Data, { block = false } = {}): Patch {
  return endedPatch(index, (i) => setValueOn(i, path, value, block));
}

/**
 * Several `setValue`s as one patch on `index`'s own text, when each path
 * holds a scalar already (not empty) and each value is one: every rewrite
 * is in place, so none moves another's span. `undefined` when one is not,
 * for `setValue` in turn instead.
 */
export function setScalars(index: SpanIndex, values: [Path, Data][]): Patch | undefined {
  const expected = withData(index);
  const spans: [number, number, string][] = [];
  for (const [path, value] of values) {
    const entry = index.get(path);
    if (entry === undefined || value instanceof Map || Array.isArray(value)) return undefined;
    const node = entry.value;
    if (node.kind !== "scalar" || (node.value === "" && node.style === null)) return undefined;
    setChild(dataAt(expected, path.slice(0, -1)), path[path.length - 1]!, value);
    spans.push([node.start.index, node.end.index, scalar(value, quoteStyle(node))]);
  }
  spans.sort((a, b) => b[0] - a[0] || b[1] - a[1] || (a[2] < b[2] ? 1 : a[2] > b[2] ? -1 : 0));
  for (let i = 0; i + 1 < spans.length; i++) if (spans[i]![0] < spans[i + 1]![1]) return undefined;
  let text = index.text;
  for (const [start, end, replacement] of spans) text = text.slice(0, start) + replacement + text.slice(end);
  return patch(text, expected, "set " + values.map(([p]) => dotted(p)).join(", "));
}

/** Remove the key at `path`. The last entry of a mapping, flow or block, takes its mapping's key with it, and so on upward. */
export function remove(index: SpanIndex, path: Path): Patch {
  return endedPatch(index, (i) => removeOn(i, path));
}

/**
 * Insert `value` as item `at` (0 to the length; the length appends) of the
 * list at `path`, in the list's own style: `- item` on its own line at the
 * list's indent, a mapping in block style when the list's items are block
 * mappings and in flow style otherwise, or between a flow list's brackets
 * with the separator its neighbours use. A list the file does not have yet
 * (the key missing, or empty) is made around its first item, in flow style
 * or, with `block` under a block mapping, as block lines.
 */
export function insertItem(index: SpanIndex, path: Path, at: number, value: Data, { block = false } = {}): Patch {
  return endedPatch(index, (i) => insertItemOn(i, path, at, value, block));
}

/**
 * Remove item `at` of the list at `path`, a block item with its own comment
 * lines. The last item of a block list takes the list's key with it (and so
 * on upward, as `remove` does); a flow list is left as `[]`.
 */
export function removeItem(index: SpanIndex, path: Path, at: number): Patch {
  return endedPatch(index, (i) => removeItemOn(i, path, at));
}

/** Move item `from` of the list at `path` to position `to`, a block item with its own comment lines. */
export function moveItem(index: SpanIndex, path: Path, from: number, to: number): Patch {
  return endedPatch(index, (i) => moveItemOn(i, path, from, to));
}

/** Delete an element with its leading comment lines. A block's only element takes the block's key with it. */
export function deleteElement(index: SpanIndex, path: Path): Patch {
  return endedPatch(index, (i) => deleteElementOn(i, path));
}

/**
 * Delete several elements as one patch, each as `deleteElement` deletes
 * one, in turn on the text the last left. An element inside another being
 * deleted goes with it rather than being deleted twice.
 */
export function deleteElements(index: SpanIndex, paths: Path[]): Patch {
  const seen = new Set<string>();
  const unique = paths.filter((p) => !seen.has(pathKey(p)) && seen.add(pathKey(p)));
  const kept = unique.filter((p) => !unique.some((q) => q.length < p.length && pathKey(p.slice(0, q.length)) === pathKey(q)));
  if (kept.length === 0) throw new Refused("there is nothing to delete");
  let result = deleteElement(index, kept[0]!);
  for (const path of kept.slice(1)) result = chain(result, (i) => deleteElement(i, path));
  return patch(result.text, result.expected, "delete " + kept.map((p) => String(p[p.length - 1])).join(", "));
}

/** Copy an element right after itself, every element id inside the copy renamed with one fresh suffix. */
export function duplicateElement(index: SpanIndex, path: Path): Patch {
  return endedPatch(index, (i) => duplicateElementOn(i, path));
}

/** Move an element to position `to` among its siblings (0 is first), its leading comments with it. */
export function moveElement(index: SpanIndex, path: Path, to: number): Patch {
  return endedPatch(index, (i) => moveElementOn(i, path, to));
}

/** Add a new element of `type` to `block`, after the element `after` or at the end, with `DEFAULTS` and `faceColor`. */
export function addElement(index: SpanIndex, type: string,
  { block = ["elements"] as Path, after, elementId }: { block?: Path; after?: string; elementId?: string } = {}): Patch {
  return endedPatch(index, (i) => addElementOn(i, type, block, after, elementId));
}

/** Rename the key at `path`, in place; refused when a sibling already has the new name. */
export function renameKey(index: SpanIndex, path: Path, renamed: string): Patch {
  return endedPatch(index, (i) => renameKeyOn(i, path, renamed));
}

/** Rewrite every string value (never a key) through `fn`, each in its own quoting. Block scalars are left alone. */
export function rewriteScalars(index: SpanIndex, fn: (s: string) => string, what: string): Patch {
  return endedPatch(index, (i) => rewriteScalarsOn(i, fn, what));
}

/** A whole `<prefix><name>` reference, inside expressions too. */
export function referencePattern(prefix: string, name: string): RegExp {
  return new RegExp(`(?<![A-Za-z0-9_.])${reEscape(prefix + name)}(?![A-Za-z0-9_])`, "g");
}

/** Rename a declared name, the key at `path`, and every reference to it written `<prefix><name>`, as one patch. */
export function renameReference(index: SpanIndex, path: Path, renamed: string, prefix: string): Patch {
  const old = String(path[path.length - 1]);
  const pattern = referencePattern(prefix, old);
  return chain(renameKey(index, path, renamed), (i) => rewriteScalars(
    i, (s) => s.replace(pattern, () => prefix + renamed), `refer to ${prefix}${renamed}`));
}

export function repointOn(index: SpanIndex, key: string, old: string, renamed: string): Patch {
  let text = index.text;
  const expected = withData(index);
  const nodes: ScalarNode[] = [];
  for (const element of index.elements()) {
    const entry = index.get([...element.path, key]);
    if (entry !== undefined && entry.value.kind === "scalar" && entry.value.value === old) {
      nodes.push(entry.value);
      setChild(dataAt(expected, element.path), key, renamed);
    }
  }
  for (const node of [...nodes].sort((a, b) => b.start.index - a.start.index)) {
    text = text.slice(0, node.start.index) + scalar(renamed, quoteStyle(node)) + text.slice(node.end.index);
  }
  return patch(text, expected, `point ${key}: ${old} at ${renamed}`);
}

/** Rename the `config: slots:` entry `old` and every element's `slot: <old>`, as one patch. */
export function renameSlot(index: SpanIndex, old: string, renamed: string): Patch {
  return chain(renameKey(index, ["config", "slots", old], renamed),
    (i) => endedPatch(i, (j) => repointOn(j, "slot", old, renamed)));
}

/** The ids of the elements drawing the `config: slots:` entry `name`. */
export function slotDrawers(index: SpanIndex, name: string): string[] {
  return index.elements()
    .filter((e) => e.value.kind === "mapping")
    .filter((e) => {
      const data = dataAt(index.data, e.path);
      return data instanceof Map && data.get("slot") === name;
    })
    .map((e) => e.name);
}

/** Remove the `config: slots:` entry `name`; with the last slot, the `slots:` key too (and `config:`, left with nothing). Refused while an element draws it. */
export function removeSlot(index: SpanIndex, name: string): Patch {
  index.at(["config", "slots", name]);
  const drawers = slotDrawers(index, name);
  if (drawers.length > 0) {
    const one = drawers.length === 1;
    throw new Refused(`${drawers.join(", ")} ${one ? "draws" : "draw"} the slot ${name}: delete ${one ? "it" : "them"} ` +
      "or point them at another slot first");
  }
  const config = child(index.data, "config");
  let path: Path = ["config", "slots", name];
  const slots = child(config, "slots");
  if (slots instanceof Map && slots.size === 1) path = config instanceof Map && config.size === 1 ? ["config"] : ["config", "slots"];
  const removed = remove(index, path);
  return patch(removed.text, removed.expected, `delete the slot ${name}`);
}

