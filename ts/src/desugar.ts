// Rewrite a lowered design's element blocks into the one shape the IR
// builder reads. Port of wfb/desugar.py.
//
// Three rewrites live here. The first turns an element mapping, keyed by
// id, into the list the builder walks, the key injected as the element's
// `id`. Spans are the whole difficulty: a diagnostic must point at the
// author's own line, so the rewritten sequence holds the same mapping
// bodies, each item's position taken from the key that named it, and the
// injected `id` key recorded in the body's own `lc`.
//
// The second is the top-level `static:` block, folded into one `group`
// carrying `static: true` at the front of `elements:` (an opaque static
// buffer must draw first). Its id, `STATIC_GROUP_ID`, is reserved.
//
// The third is a `layouts:` entry's own `static:`/`elements:`, folded into
// two groups appended to the top-level `elements:`, their ids from
// `layoutIds`. A layout body is left holding only what remains (`lint:`).
//
// What the schema cannot see, a YAML alias giving one body two keys, is
// reported here (`element-mapping`).
import type { Bag, Span } from "./diagnostics.ts";
import type { Data, DataKey } from "./edit/yaml.ts";
import { PyError, repr } from "./py.ts";
import { ensureLc, insertKey, lcOf, type YamlDocument } from "./yamlsrc.ts";

type Dict = Map<DataKey, Data>;
const isDict = (x: unknown): x is Dict => x instanceof Map;

/** The schema's `#/$defs/identifier`. */
export const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** The id the top-level `static:` block's synthetic group is given; reserved. */
export const STATIC_GROUP_ID = "static";

/** The reserved element ids one `layouts: <name>:` body's halves become: `[staticId, elementsId]`. */
export function layoutIds(name: string): [string, string] {
  return [`layout_${name}_static`, `layout_${name}`];
}

/** Normalise `doc` in place. `false` (with diagnostics) if it cannot be. */
export function desugar(doc: YamlDocument, bag: Bag): boolean {
  const data = doc.data;
  if (!isDict(data)) return true; // the format check reports this properly
  let ok = rewrite(doc, data, "elements", bag);
  ok = staticBlock(doc, data, bag) && ok;
  return layoutsBlock(doc, data, bag) && ok;
}

/** A `group` this pass mints around `children`, every key's position recorded at `span` (the author's own key). */
function syntheticGroup(groupId: string, children: Data, isStatic: boolean, span: Span | null): Dict {
  const group: Dict = new Map();
  const lc = ensureLc(group);
  group.set("id", groupId);
  group.set("type", "group");
  if (isStatic) group.set("static", true);
  group.set("children", children);
  if (span !== null) {
    const line = span.line - 1, col = span.col - 1;
    lc.line = line;
    lc.col = col;
    for (const key of group.keys()) lc.addKvLineCol(key, [line, col, line, col]);
  }
  return group;
}

/** `data.elements`, created empty when absent. */
function elementsList(data: Dict): Data {
  let elements = data.get("elements");
  if (elements === undefined || elements === null) {
    const created: Data[] = [];
    ensureLc(created);
    data.set("elements", created);
    elements = created;
  }
  return elements;
}

/** Python's truthiness of a block's value. */
function empty(node: Data | undefined): boolean {
  if (node === undefined || node === null || node === false || node === "" || node === 0) return true;
  if (node instanceof Map) return node.size === 0;
  if (Array.isArray(node)) return node.length === 0;
  return false;
}

function staticBlock(doc: YamlDocument, data: Dict, bag: Bag): boolean {
  if (!data.has("static")) return true;
  const node = data.get("static")!;
  const span = doc.span(data, "static", "key");
  if (empty(node)) {
    data.delete("static");
    return true;
  }
  const group = syntheticGroup(STATIC_GROUP_ID, node, true, span);
  const ok = rewrite(doc, group, "children", bag);
  const elements = elementsList(data);
  if (!Array.isArray(elements)) return false; // leaving `elements:` as written keeps that diagnostic honest
  for (const existing of elements) {
    if (isDict(existing) && existing.get("id") === STATIC_GROUP_ID) {
      bag.error("static", `the id ${repr(STATIC_GROUP_ID)} is reserved while a top-level \`static:\` block is present`,
        doc.span(existing, "id") ?? span,
        { notes: ["the block is rewritten into a group under that id, and two elements cannot share one", "rename this element"] });
      return false;
    }
  }
  elements.unshift(group);
  const lc = lcOf(elements);
  if (lc !== undefined) {
    // Every existing item shifted one place along.
    const shifted = new Map<DataKey, number[]>();
    for (const [index, value] of lc.data ?? []) shifted.set((index as number) + 1, value);
    if (span !== null) {
      const line = span.line - 1, col = span.col - 1;
      shifted.set(0, [line, col, line, col]);
    }
    lc.data = shifted;
  }
  data.delete("static");
  return ok;
}

function layoutsBlock(doc: YamlDocument, data: Dict, bag: Bag): boolean {
  if (!data.has("layouts")) return true;
  const layouts = data.get("layouts");
  if (!isDict(layouts)) return true; // the schema reports this
  const elements = elementsList(data);
  if (!Array.isArray(elements)) return false;
  // Every id already spoken for, recursively, so a layout's generated id is
  // checked against an ordinary element and against another layout's.
  const existingIds = new Map<string, string>();
  collectIds(elements, existingIds, "an element");
  let ok = true;
  for (const [name, body] of layouts) {
    if (typeof name !== "string" || !IDENTIFIER.test(name)) continue; // the schema reports this
    if (!isDict(body)) continue; // the schema reports this
    const [staticId, elementsId] = layoutIds(name);
    for (const [generatedId, key, wrapStatic] of [[staticId, "static", true], [elementsId, "elements", false]] as const) {
      const node = body.get(key);
      if (empty(node)) {
        if (body.has(key)) body.delete(key); // an empty list/mapping: treated as absent
        continue;
      }
      const keySpan = doc.span(body, key, "key");
      const claimant = existingIds.get(generatedId);
      if (claimant !== undefined) {
        bag.error("layouts", `layouts.${name}.${key}: the generated id ${repr(generatedId)} collides with ${claimant}`, keySpan,
          { notes: [`'layouts: ${name}:' needs id ${repr(generatedId)} for its own ${repr(key)} content`,
            "rename the layout, or whatever already claims that id"] });
        ok = false;
        continue;
      }
      const group = syntheticGroup(generatedId, node!, wrapStatic, keySpan);
      ok = rewrite(doc, group, "children", bag) && ok;
      collectIds(group, existingIds, `layout ${repr(name)}`);
      const idx = elements.length;
      elements.push(group);
      const lc = lcOf(elements);
      if (lc !== undefined && keySpan !== null) lc.addIdxLineCol(idx, [keySpan.line - 1, keySpan.col - 1]);
      body.delete(key);
    }
  }
  return ok;
}

/** Recursively collect every element id under `node` into `out`, first claim wins. */
function collectIds(node: Data | undefined, out: Map<string, string>, label: string): void {
  if (Array.isArray(node)) {
    for (const item of node) collectIds(item, out, label);
    return;
  }
  if (!isDict(node)) return;
  const elementId = node.get("id");
  if (typeof elementId === "string" && !out.has(elementId)) out.set(elementId, label);
  collectIds(node.get("children"), out, label);
}

/** Convert the element mapping at `parent[key]` to a list, then recurse into each group's `children:`. */
function rewrite(doc: YamlDocument, parent: Data, key: string, bag: Bag): boolean {
  let node = isDict(parent) ? parent.get(key) : undefined;
  let ok = true;
  if (isDict(node)) {
    const converted = toSequence(doc, node, bag);
    ok = converted !== null;
    if (converted !== null) {
      (parent as Dict).set(key, converted);
      node = converted;
    }
  }
  if (Array.isArray(node)) {
    for (const body of node) {
      // A group is the only element that owns further elements.
      if (isDict(body) && body.get("type") === "group") ok = rewrite(doc, body, "children", bag) && ok;
    }
  }
  return ok;
}

/** The list the IR builder reads, built from `mapping` with every span carried across. */
function toSequence(doc: YamlDocument, mapping: Dict, bag: Bag): Data[] | null {
  const seq: Data[] = [];
  const seqLc = ensureLc(seq);
  const lc = lcOf(mapping);
  if (lc !== undefined) {
    seqLc.line = lc.line;
    seqLc.col = lc.col;
  }
  let ok = true;
  const seen = new Map<object, DataKey>();
  let index = 0;
  for (const [name, body] of mapping) {
    const pos = keyPosition(mapping, name);
    if (pos !== null) seqLc.addIdxLineCol(index, [...pos]);
    const keySpan = doc.span(mapping, name, "key");
    if (isDict(body)) ok = injectId(body, name, pos, keySpan, seen, bag) && ok;
    seq.push(body);
    index++;
  }
  return ok ? seq : null;
}

function injectId(body: Dict, name: DataKey, pos: [number, number] | null, keySpan: Span | null,
  seen: Map<object, DataKey>, bag: Bag): boolean {
  const earlier = seen.get(body);
  if (earlier !== undefined) {
    bag.error("element-mapping", `the body under ${repr(name)} is the same node as the one under ${repr(earlier)}`, keySpan,
      { notes: ["a YAML alias cannot give two elements two different ids; write the second one out"] });
    return false;
  }
  seen.set(body, name);
  // `CommentedMap.insert(0, "id", name)`: the key first, or after a merge key's keys.
  insertKey(body, 0, "id", name);
  if (pos !== null) {
    // Key and value positions both point at the author's key, the only text there is for this pair.
    ensureLc(body).addKvLineCol("id", [pos[0], pos[1], pos[0], pos[1]]);
  }
  return true;
}

function keyPosition(mapping: Dict, name: DataKey): [number, number] | null {
  const lc = lcOf(mapping);
  if (lc === undefined) return null;
  try {
    return lc.key(name);
  } catch (error) {
    if (error instanceof PyError) return null;
    throw error;
  }
}
