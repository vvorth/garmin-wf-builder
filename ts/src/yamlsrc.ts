// YAML loading that keeps source spans attached to the parsed document.
// Port of wfb/yamlsrc.py.
//
// ruamel's round-trip loader annotates every mapping and sequence with an
// `lc` object: the 0-based line and column of the collection, and of each
// key, value and item. The document's mappings here are `Map`s and its
// sequences arrays, so their `lc` lives in a side table (`lcOf`), with the
// same semantics: a collection the compiler mints (`ensureLc`) has an `lc`
// with no line at all, and a position recorded for a key is read back as
// ruamel's `lc.key`/`lc.value`/`lc.item` read it.
import { Bag, Span } from "./diagnostics.ts";
import { compose, construct, type Data, type DataKey, mappingKey, PyFloat, Timestamp, type YamlNode, YamlError } from "./edit/yaml.ts";
import { PyError } from "./py.ts";

/** ruamel's `LineCol`: a collection's own position and its entries'. */
export class LineCol {
  line: number | null = null;
  col: number | null = null;
  /** Key or index to `[line, col]` or `[keyLine, keyCol, valueLine, valueCol]`; `null` until a position is added. */
  data: Map<DataKey, number[]> | null = null;

  addKvLineCol(key: DataKey, value: number[]): void {
    (this.data ??= new Map()).set(key, value);
  }

  addIdxLineCol(index: number, value: number[]): void {
    (this.data ??= new Map()).set(index, value);
  }

  private kv(k: DataKey, x: number, y: number): [number, number] | null {
    if (this.data === null) return null;
    const entry = this.data.get(k);
    if (entry === undefined) throw new PyError("KeyError", String(k));
    const a = entry[x], b = entry[y];
    if (a === undefined || b === undefined) throw new PyError("IndexError");
    return [a, b];
  }

  key(k: DataKey): [number, number] | null { return this.kv(k, 0, 1); }
  value(k: DataKey): [number, number] | null { return this.kv(k, 2, 3); }
  item(i: number): [number, number] | null { return this.kv(i, 0, 1); }
}

const LCS = new WeakMap<object, LineCol>();

/** A collection's `lc`, or `undefined` for anything that is not a document collection. */
export function lcOf(node: unknown): LineCol | undefined {
  return node !== null && typeof node === "object" ? LCS.get(node) : undefined;
}

/** A collection the compiler mints (`CommentedMap()`, `CommentedSeq()`): an `lc` with no position yet. */
export function ensureLc(node: Map<DataKey, Data> | Data[]): LineCol {
  let lc = LCS.get(node);
  if (lc === undefined) {
    lc = new LineCol();
    LCS.set(node, lc);
  }
  return lc;
}

/** What the author wrote where the compiler now reads one key of a lowered format 2 document. */
export class Origin {
  readonly key: string;
  readonly text: string | null;
  /** `[rewritten offset, author offset]` pairs, ascending. */
  readonly offsets: readonly (readonly [number, number])[];
  /** What a diagnostic quotes for this value, when not `text` itself. */
  readonly quote: string | null;

  constructor(key: string, text: string | null = null, offsets: readonly (readonly [number, number])[] = [], quote: string | null = null) {
    this.key = key;
    this.text = text;
    this.offsets = offsets;
    this.quote = quote;
  }

  authorOffset(offset: number): number {
    let baseRewritten = 0, baseAuthor = 0;
    for (const [rewritten, author] of this.offsets) {
      if (rewritten > offset) break;
      baseRewritten = rewritten;
      baseAuthor = author;
    }
    return baseAuthor + (offset - baseRewritten);
  }
}

export type SpanOf = "value" | "key";

/** A parsed YAML file plus the machinery to locate any node inside it. */
export class YamlDocument {
  readonly path: string;
  readonly text: string;
  data: Data;
  /** The `format:` the author wrote: 2 for a document `lower` rewrote, 1 otherwise. */
  format = 1;
  private readonly origins = new WeakMap<object, Map<DataKey, Origin>>();

  constructor(path: string, text: string, data: Data) {
    this.path = path;
    this.text = text;
    this.data = data;
  }

  // -- format 2 origins --------------------------------------------------------

  setOrigin(node: object, key: DataKey, origin: Origin): void {
    let byKey = this.origins.get(node);
    if (byKey === undefined) {
      byKey = new Map();
      this.origins.set(node, byKey);
    }
    byKey.set(key, origin);
  }

  origin(node: object, key: DataKey): Origin | undefined {
    return this.origins.get(node)?.get(key);
  }

  /** The name the author wrote for `node[key]`. */
  authorKey(node: object, key: string): string {
    return this.origins.get(node)?.get(key)?.key ?? key;
  }

  // -- span lookup ----------------------------------------------------------------

  /**
   * Locate `node`, or `node[key]` when a key or index is given. `of: "key"`
   * locates the mapping key rather than its value, the right anchor for
   * "unknown key" diagnostics.
   */
  span(node: unknown, key?: DataKey, of: SpanOf = "value"): Span | null {
    const lc = lcOf(node);
    if (lc === undefined) return null;
    const own = (): Span => {
      if (lc.line === null || lc.col === null) throw new PyError("TypeError", "unsupported operand type(s) for +: 'NoneType' and 'int'");
      return new Span(this.path, lc.line + 1, lc.col + 1);
    };
    if (key === undefined) return own();
    let pos: [number, number] | null;
    try {
      if (typeof key === "number" && !(node instanceof Map)) pos = lc.item(key);
      else if (of === "key") pos = lc.key(key);
      else pos = lc.value(key);
    } catch (error) {
      if (error instanceof PyError && ["KeyError", "IndexError", "AttributeError", "TypeError"].includes(error.pyType)) return own();
      throw error;
    }
    return pos === null ? null : new Span(this.path, pos[0] + 1, pos[1] + 1);
  }

  /** Locate a node addressed by a jsonschema-style path of keys and indices. */
  spanForPath(parts: readonly DataKey[]): Span | null {
    let node: Data | undefined = this.data;
    let span = this.span(node);
    for (const part of parts) {
      try {
        // A node this compiler minted (`desugar`) can carry an `lc` with no line at all, which `span` does not survive.
        span = this.span(node, part) ?? span;
      } catch (error) {
        if (!(error instanceof PyError)) throw error;
      }
      if (node instanceof Map) {
        if (!node.has(part)) break;
        node = node.get(part);
      } else if (Array.isArray(node) && typeof part === "number" && part >= -node.length && part < node.length) {
        node = node[part < 0 ? node.length + part : part];
      } else {
        break;
      }
    }
    return span;
  }
}

/** The round-trip data for `node`, every collection's positions recorded as ruamel's constructor records them. */
function roundTrip(node: YamlNode, built: Map<YamlNode, Data>): Data {
  const seen = built.get(node);
  if (seen !== undefined) return seen; // an alias: the same object, as ruamel constructs it once
  if (node.kind === "mapping") {
    const out = new Map<DataKey, Data>();
    built.set(node, out);
    const lc = ensureLc(out);
    lc.line = node.start.line;
    lc.col = node.start.column;
    for (const [k, v] of node.pairs) {
      const key = mappingKey(k);
      if (out.has(key)) throw new YamlError(`found duplicate key "${String(key)}"`, k.start.line + 1, k.start.column + 1);
      out.set(key, roundTrip(v, built));
      lc.addKvLineCol(key, [k.start.line, k.start.column, v.start.line, v.start.column]);
    }
    return out;
  }
  if (node.kind === "sequence") {
    const out: Data[] = [];
    built.set(node, out);
    const lc = ensureLc(out);
    lc.line = node.start.line;
    lc.col = node.start.column;
    node.items.forEach((item, i) => {
      out.push(roundTrip(item, built));
      lc.addIdxLineCol(i, [item.start.line, item.start.column]);
    });
    return out;
  }
  return construct(node);
}

/**
 * Parse `path`'s `text`, reporting a diagnostic and returning `null` on
 * failure. `node` is `text` already composed (the editor's `SpanIndex`
 * root), which is then only constructed, not scanned again.
 */
export function load(path: string, bag: Bag, text: string, node?: YamlNode | null): YamlDocument | null {
  bag.registerSource(path, text);
  let data: Data;
  try {
    const root = node === undefined ? compose(text) : node;
    data = root === null ? null : roundTrip(root, new Map());
  } catch (error) {
    if (!(error instanceof YamlError)) throw error;
    const span = error.line !== null && error.col !== null ? new Span(path, error.line, error.col) : null;
    bag.error("yaml", error.message.trim() || "invalid YAML", span);
    return null;
  }
  if (data === null) {
    bag.error("yaml", "the document is empty", new Span(path, 1, 1));
    return null;
  }
  return new YamlDocument(path, text, data);
}

export { PyFloat, Timestamp };
