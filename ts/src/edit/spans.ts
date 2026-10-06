// The span index: every `key: value` entry of a design's text, with the
// exact character range of its key and value.
//
// The composed node tree (`./yaml.ts`) gives every node a start and an end
// mark, as ruamel's composer does. A patch rewrites those characters and
// nothing else, so every byte outside an edit is left alone.
//
// Two facts about the marks every range here relies on:
//
// - **A block value ends where the next token starts.** Its end mark sits
//   at the next key's column on the following line (or at the end of the
//   text), not at a line start.
// - A flow value's or a plain scalar's end mark sits inside its own last
//   line, just past its last character.
import { compose, construct, type Data, type MappingNode, type ScalarNode, type YamlNode, YamlError } from "./yaml.ts";

export { ordered, sameData } from "./yaml.ts";

/** One step of an author path: a mapping key or a sequence index. */
export type Step = string | number;
export type Path = readonly Step[];

/** The keys whose value is a mapping of element id to element. */
export const ELEMENT_BLOCKS: ReadonlySet<string> = new Set(["elements", "static", "children"]);

/** A patch that cannot be made, or that the gate would not accept. The message says why, in the author's terms. */
export class Refused extends Error {}

/** One `key: value` pair of a block or flow mapping. */
export class Entry {
  readonly path: Path;
  readonly key: ScalarNode;
  readonly value: YamlNode;
  /** The mapping holding this entry. */
  readonly parent: MappingNode;

  constructor(path: Path, key: ScalarNode, value: YamlNode, parent: MappingNode) {
    this.path = path;
    this.key = key;
    this.value = value;
    this.parent = parent;
  }

  get name(): string {
    return this.key.value;
  }

  /** Whether the mapping holding this entry is a flow mapping. */
  get isFlow(): boolean {
    return this.parent.flow;
  }
}

function invalid(error: YamlError): Refused {
  return new Refused(`the text is not valid YAML: ${error.message.trim() || "invalid YAML"}`);
}

/** `text`'s node tree and its plain data. */
function composed(text: string): [YamlNode | null, Data] {
  try {
    const node = compose(text);
    return [node, construct(node)];
  } catch (error) {
    if (error instanceof YamlError) throw invalid(error);
    throw error;
  }
}

export function composeText(text: string): YamlNode | null {
  return composed(text)[0];
}

/** The plain data `text` parses to: mappings in key order, lists and scalars. What the gate compares. */
export function parse(text: string): Data {
  return composed(text)[1];
}

export function lineStart(text: string, index: number): number {
  return text.lastIndexOf("\n", index - 1) + 1;
}

/** The index just past the newline ending the line `index` is on. */
export function lineEnd(text: string, index: number): number {
  const end = text.indexOf("\n", index);
  return end < 0 ? text.length : end + 1;
}

export function indentOf(text: string, index: number): number {
  const line = text.slice(lineStart(text, index), lineEnd(text, index));
  return line.length - line.replace(/^ +/, "").length;
}

/**
 * A design's text, its composed node tree and its plain data, with every
 * mapping entry addressable by its author path. Read-only: one index may
 * be shared (`indexFor`).
 */
export class SpanIndex {
  readonly text: string;
  readonly root: YamlNode | null;
  readonly data: Data;
  private readonly all: Entry[];
  private readonly byPath = new Map<string, Entry>();
  private readonly byPosition = new Map<string, Entry>();
  /** The entry whose value is a given node, by node identity. */
  private readonly holders = new Map<YamlNode, Entry>();

  constructor(text: string) {
    this.text = text;
    [this.root, this.data] = composed(text);
    this.all = this.root === null ? [] : [...entries(this.root, [])];
    for (const e of this.all) {
      this.byPath.set(pathKey(e.path), e);
      this.byPosition.set(`${e.key.start.line + 1}:${e.key.start.column + 1}`, e);
      this.holders.set(e.value, e);
    }
  }

  // -- lookup ---------------------------------------------------------------

  entries(): Entry[] {
    return [...this.all];
  }

  get(path: Path): Entry | undefined {
    return this.byPath.get(pathKey(path));
  }

  at(path: Path): Entry {
    const entry = this.get(path);
    if (entry === undefined) throw new Refused(`${dotted(path)} is not in the file`);
    return entry;
  }

  /** The entry whose key starts at 1-based `line` and `col`: an `Element.span`. */
  atSpan(span: { line: number; col: number } | null | undefined): Entry | undefined {
    return span ? this.byPosition.get(`${span.line}:${span.col}`) : undefined;
  }

  /** The entry whose value is `mapping`, or `undefined` at the top. */
  holder(mapping: YamlNode): Entry | undefined {
    return this.holders.get(mapping);
  }

  /** Every element entry, in document order: a key of an element block whose value is a mapping with a `type:`. */
  elements(): Entry[] {
    return this.all.filter((e) => isElement(this, e));
  }

  elementIds(): Set<string> {
    return new Set(this.elements().map((e) => e.name));
  }

  // -- ranges ---------------------------------------------------------------

  /**
   * Whole lines, from the entry's leading comment lines (at the key's own
   * indent) to its value's last line, newline included. Trailing blank
   * lines and shallower comments are left to what follows.
   */
  entryRange(entry: Entry): [number, number] {
    const text = this.text;
    let start = lineStart(text, entry.key.start.index);
    const indent = entry.key.start.column;
    while (start > 0) {
      const prev = lineStart(text, start - 1);
      const line = text.slice(prev, start - 1);
      if (line.trim().startsWith("#") && line.length - line.trimStart().length === indent) start = prev;
      else break;
    }
    return [start, this.valueEnd(entry)];
  }

  /** Just past the newline of the value's last line, skipping the blank lines and comments a block value's end mark swallows. */
  valueEnd(entry: Entry): number {
    const text = this.text;
    const endIndex = entry.value.end.index;
    const head = lineStart(text, endIndex);
    let end = text.slice(head, endIndex).trim() === "" && endIndex > entry.key.start.index
      ? head
      : lineEnd(text, Math.max(endIndex - 1, 0));
    const keyLine = lineStart(text, entry.key.start.index);
    const indent = entry.key.start.column;
    while (end > keyLine) {
      const last = lineStart(text, end - 1);
      if (last <= keyLine) break;
      const line = text.slice(last, end).replace(/\n$/, "");
      const stripped = line.trim();
      if (stripped === "" || (stripped.startsWith("#") && line.length - line.trimStart().length <= indent)) end = last;
      else break;
    }
    return end;
  }
}

const cache = new Map<string, SpanIndex>();

/** `text`'s index, shared: an editor reads the same version's index for its tree, its inspector and its next patch. */
export function indexFor(text: string): SpanIndex {
  const hit = cache.get(text);
  if (hit !== undefined) {
    cache.delete(text);
    cache.set(text, hit);
    return hit;
  }
  const index = new SpanIndex(text);
  cache.set(text, index);
  if (cache.size > 16) cache.delete(cache.keys().next().value!);
  return index;
}

export function isElement(index: SpanIndex, entry: Entry): boolean {
  if (entry.value.kind !== "mapping") return false;
  if (!entry.value.pairs.some(([k]) => k.kind === "scalar" && k.value === "type")) return false;
  const block = index.holder(entry.parent);
  return block !== undefined && ELEMENT_BLOCKS.has(block.name);
}

export function dotted(path: Path): string {
  return path.map(String).join(".");
}

/** A path as a map key: steps keep their type, so `["0"]` and `[0]` differ. */
export function pathKey(path: Path): string {
  return JSON.stringify(path);
}

function* entries(node: YamlNode, path: Step[]): Generator<Entry> {
  if (node.kind === "mapping") {
    for (const [k, v] of node.pairs) {
      if (k.kind === "scalar") {
        const here = [...path, k.value];
        yield new Entry(here, k, v, node);
        yield* entries(v, here);
      }
    }
  } else if (node.kind === "sequence") {
    for (let i = 0; i < node.items.length; i++) yield* entries(node.items[i]!, [...path, i]);
  }
}
