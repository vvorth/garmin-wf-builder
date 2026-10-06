// YAML as ruamel's safe loader reads it:
// the composed node tree, with ruamel's marks, tags and scalar values, and
// the plain data constructed from it.
//
// The `yaml` package parses; everything ruamel decides is restated here,
// because the patch engine cuts text at ruamel's marks and the gate
// compares ruamel's data:
//
// - **Marks.** A scalar or flow collection ends just past its last
//   character. A block mapping or sequence ends where the next token
//   starts, after blank lines and comments (or at the end of the text). An
//   empty value (`key:`) is a zero-width node at the next token. A block
//   scalar (`|`, `>`) ends after its trailing line breaks, having consumed
//   up to its own indent of spaces on the line where it stops.
// - **Tags.** A plain scalar's type is resolved from its text by ruamel's
//   YAML 1.2 implicit resolvers, which, unlike the YAML 1.2 core schema,
//   also resolve timestamps (`2026-10-05` is a date).
// - **Values.** Integers take ruamel's rules: underscores dropped, `0x`,
//   `0o` and `0b` prefixes, and a leading zero read as decimal (`017` is
//   17).
//
// Offsets (`Mark.index`) are UTF-16 code units, JavaScript's own, so text
// can be cut at them directly. `Mark.line` and `Mark.column` count code
// points, as ruamel's do.
import YAML from "yaml";

export interface Mark {
  index: number;
  line: number;
  column: number;
}

interface NodeBase {
  tag: string;
  start: Mark;
  end: Mark;
}

export interface ScalarNode extends NodeBase {
  kind: "scalar";
  /** `null` for plain, or `"`, `'`, `|`, `>`. */
  style: ScalarStyle;
  /** The scalar's text after unquoting, unescaping and folding: ruamel's `ScalarNode.value`. */
  value: string;
}

export interface SequenceNode extends NodeBase {
  kind: "sequence";
  flow: boolean;
  items: YamlNode[];
}

export interface MappingNode extends NodeBase {
  kind: "mapping";
  flow: boolean;
  pairs: [YamlNode, YamlNode][];
  /** The pairs a merge key (`<<`) brought in, once `flattenMapping` has run: ruamel's `node.merge`. */
  merge?: [YamlNode, YamlNode][];
}

export type YamlNode = ScalarNode | SequenceNode | MappingNode;
export type ScalarStyle = null | "\"" | "'" | "|" | ">";

/** Text that is not valid YAML, or that ruamel's safe loader refuses; `line` and `col` (1-based) where, when known. */
export class YamlError extends Error {
  readonly line: number | null;
  readonly col: number | null;

  constructor(message: string, line: number | null = null, col: number | null = null) {
    super(message);
    this.line = line;
    this.col = col;
  }
}

const TAG = "tag:yaml.org,2002:";

// -- resolving a plain scalar's type: ruamel's YAML 1.2 implicit resolvers --------

/** In ruamel's registration order, each with the first characters it applies to. */
const RESOLVERS: [string, RegExp, string][] = [
  ["bool", /^(?:true|True|TRUE|false|False|FALSE)$/, "tTfF"],
  ["float", new RegExp("^(?:[-+]?(?:[0-9][0-9_]*)\\.[0-9_]*(?:[eE][-+]?[0-9]+)?" +
    "|[-+]?(?:[0-9][0-9_]*)(?:[eE][-+]?[0-9]+)" +
    "|[-+]?\\.[0-9_]+(?:[eE][-+][0-9]+)?" +
    "|[-+]?\\.(?:inf|Inf|INF)" +
    "|\\.(?:nan|NaN|NAN))$"), "-+0123456789."],
  ["int", /^(?:[-+]?0b[0-1_]+|[-+]?0o?[0-7_]+|[-+]?[0-9_]+|[-+]?0x[0-9a-fA-F_]+)$/, "-+0123456789"],
  ["merge", /^(?:<<)$/, "<"],
  ["null", /^(?:~|null|Null|NULL|)$/, "~nN"],
  ["timestamp", new RegExp("^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]" +
    "|[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?" +
    "(?:[Tt]|[ \\t]+)[0-9][0-9]?" +
    ":[0-9][0-9]:[0-9][0-9](?:\\.[0-9]*)?" +
    "(?:[ \\t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$"), "0123456789"],
  ["value", /^(?:=)$/, "="],
];

/** The tag ruamel resolves a plain scalar's value to. */
export function resolvePlain(value: string): string {
  // ruamel looks resolvers up by the value's first character, or "" for an empty value.
  const first = value === "" ? "" : value[0]!;
  for (const [tag, regexp, firsts] of RESOLVERS) {
    const applies = first === "" ? tag === "null" : firsts.includes(first);
    if (applies && regexp.test(value)) return TAG + tag;
  }
  return TAG + "str";
}

// -- marks -----------------------------------------------------------------------

/** Line starts and code-point columns for one text. */
class Lines {
  private readonly text: string;
  private readonly starts: number[] = [0];
  private readonly ascii: boolean;

  constructor(text: string) {
    this.text = text;
    for (let i = 0; i < text.length; i++) if (text.charCodeAt(i) === 10) this.starts.push(i + 1);
    this.ascii = !/[\uD800-\uDFFF]/.test(text);
  }

  mark(index: number): Mark {
    let lo = 0, hi = this.starts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (this.starts[mid]! <= index) lo = mid; else hi = mid - 1;
    }
    const start = this.starts[lo]!;
    const column = this.ascii ? index - start : [...this.text.slice(start, index)].length;
    return { index, line: lo, column };
  }
}

/** Where the next token starts at or after `p`: past spaces, tabs, line breaks and comments. */
function nextToken(text: string, p: number): number {
  while (p < text.length) {
    const c = text[p];
    if (c === " " || c === "\t" || c === "\n" || c === "\r") p++;
    else if (c === "#") {
      const nl = text.indexOf("\n", p);
      p = nl < 0 ? text.length : nl;
    } else break;
  }
  return p;
}

/**
 * Where ruamel's block scalar ends: its header at `header`, its content at
 * `indent` spaces (`indent` < 0 to detect it from the first non-empty
 * line, at least `minIndent`). ruamel moves the end mark only past a line
 * break, never past spaces: after the header's line, each line is content
 * while it reaches the indent, or a break while it is blank, and the end is
 * the start of the first line that is neither (or the end of the text).
 */
function blockScalarEnd(text: string, header: number, indent: number, minIndent: number): number {
  const headerEnd = text.indexOf("\n", header);
  if (headerEnd < 0) return text.length;
  let p = headerEnd + 1;
  if (indent < 0) {
    indent = minIndent;
    for (let q = p; q < text.length;) {
      let spaces = 0;
      while (text[q + spaces] === " ") spaces++;
      if (text[q + spaces] === "\n") { q += spaces + 1; continue; }
      if (q + spaces < text.length) indent = Math.max(minIndent, spaces);
      break;
    }
  }
  while (p < text.length) {
    let spaces = 0;
    while (text[p + spaces] === " ") spaces++;
    const blank = p + spaces >= text.length || text[p + spaces] === "\n";
    if (!blank && spaces < indent) break;
    const nl = text.indexOf("\n", p);
    p = nl < 0 ? text.length : nl + 1;
  }
  return p;
}

// -- composing -------------------------------------------------------------------

type AstNode = YAML.Scalar | YAML.YAMLMap | YAML.YAMLSeq | YAML.Alias;

/** The composed node tree ruamel's safe loader builds for `text`, or `null` for an empty document. */
export function compose(text: string): YamlNode | null {
  const doc = YAML.parseDocument(text, { schema: "failsafe", keepSourceTokens: true, uniqueKeys: false });
  if (doc.errors.length > 0) {
    const error = doc.errors[0]!;
    const pos = error.linePos?.[0];
    throw new YamlError(error.message.split("\n")[0]!, pos?.line ?? null, pos?.col ?? null);
  }
  const lines = new Lines(text);
  const anchors = new Map<string, YamlNode>();
  if (doc.contents === null) return null;
  return new Composer(text, lines, anchors).node(doc.contents as AstNode, 0);
}

class Composer {
  private readonly text: string;
  private readonly lines: Lines;
  private readonly anchors: Map<string, YamlNode>;

  constructor(text: string, lines: Lines, anchors: Map<string, YamlNode>) {
    this.text = text;
    this.lines = lines;
    this.anchors = anchors;
  }

  /** `ast` as a node; `parentIndent` is the column of the block collection holding it. */
  node(ast: AstNode | null, parentIndent: number, emptyAt?: number): YamlNode {
    if (ast === null) return this.empty(emptyAt ?? this.text.length);
    if (YAML.isAlias(ast)) {
      const target = this.anchors.get(ast.source);
      if (target === undefined) {
        const at = this.lines.mark(ast.range![0]);
        throw new YamlError(`found undefined alias ${ast.source}`, at.line + 1, at.column + 1);
      }
      return target;
    }
    const range = ast.range!;
    let out: YamlNode;
    if (YAML.isScalar(ast)) {
      out = this.scalar(ast, range, parentIndent);
    } else if (YAML.isMap(ast)) {
      const flow = Boolean(ast.flow);
      const indent = this.lines.mark(range[0]).column;
      const pairs: [YamlNode, YamlNode][] = [];
      for (const pair of ast.items as YAML.Pair<AstNode | null, AstNode | null>[]) {
        const key = this.node(pair.key, indent, this.afterKeyIndicator(pair) ?? range[0]);
        const value = this.node(pair.value, indent, this.afterValueIndicator(pair, key.end.index));
        pairs.push([key, value]);
      }
      out = { kind: "mapping", tag: this.tag(ast, "map"), flow, pairs,
        start: this.lines.mark(range[0]), end: this.lines.mark(flow ? range[1] : nextToken(this.text, range[1])) };
    } else {
      const flow = Boolean(ast.flow);
      const indent = this.lines.mark(range[0]).column;
      const items = (ast.items as (AstNode | null)[]).map((item) => this.node(item, indent, range[0]));
      out = { kind: "sequence", tag: this.tag(ast, "seq"), flow, items,
        start: this.lines.mark(range[0]), end: this.lines.mark(flow ? range[1] : nextToken(this.text, range[1])) };
    }
    if (ast.anchor) {
      // ruamel's node starts at its properties: the anchor, not the content after it.
      const at = this.text.lastIndexOf(`&${ast.anchor}`, range[0]);
      if (at >= 0 && at < out.start.index) out.start = this.lines.mark(at);
      this.anchors.set(ast.anchor, out);
    }
    return out;
  }

  private scalar(ast: YAML.Scalar, range: [number, number, number], parentIndent: number): ScalarNode {
    const value = String(ast.value ?? "");
    const style: ScalarStyle =
      ast.type === "QUOTE_DOUBLE" ? "\"" : ast.type === "QUOTE_SINGLE" ? "'"
      : ast.type === "BLOCK_LITERAL" ? "|" : ast.type === "BLOCK_FOLDED" ? ">" : null;
    if (style === null && value === "" && range[0] === range[1]) return this.empty(range[0]);
    let end = range[1];
    if (style === "|" || style === ">") {
      const header = this.text.slice(range[0], this.text.indexOf("\n", range[0]) >>> 0);
      const digit = /[1-9]/.exec(header);
      const minIndent = parentIndent + 1;
      end = blockScalarEnd(this.text, range[0], digit ? minIndent + Number(digit[0]) - 1 : -1, minIndent);
    }
    const tag = ast.tag ?? (style === null ? resolvePlain(value) : TAG + "str");
    return { kind: "scalar", tag, style, value, start: this.lines.mark(range[0]), end: this.lines.mark(end) };
  }

  /** A zero-width empty plain scalar at the next token from `at`, as ruamel marks one. */
  private empty(at: number): ScalarNode {
    const mark = this.lines.mark(nextToken(this.text, at));
    return { kind: "scalar", tag: TAG + "null", style: null, value: "", start: mark, end: mark };
  }

  private tag(ast: YAML.YAMLMap | YAML.YAMLSeq, kind: string): string {
    return ast.tag ?? TAG + kind;
  }

  private afterKeyIndicator(pair: YAML.Pair<unknown, unknown>): number | undefined {
    const start = (pair.srcToken as { start?: { offset: number; source: string }[] } | undefined)?.start;
    const indicator = start?.find((t) => t.source === "?");
    return indicator === undefined ? undefined : indicator.offset + 1;
  }

  private afterValueIndicator(pair: YAML.Pair<unknown, unknown>, fallback: number): number {
    const sep = (pair.srcToken as { sep?: { type: string; offset: number }[] } | undefined)?.sep;
    const indicator = sep?.find((t) => t.type === "map-value-ind");
    return indicator === undefined ? fallback : indicator.offset + 1;
  }
}

// -- constructing data: ruamel's safe constructor --------------------------------

/**
 * A float whose value is integral (`1.0`, `0.0`, `1e3`). Python keeps it a
 * `float`, apart from the `int` 1, and the compiler types and prints the
 * two differently (`0.0` is a Float reading, `0` a Number). Every other
 * number in YAML data is a plain number: a non-integral one can only be a
 * float, and an integral one is an int.
 */
export class PyFloat {
  readonly value: number;

  constructor(value: number) {
    this.value = value;
  }
}

/** A YAML timestamp, kept as ruamel's `isoformat()` of it. */
export class Timestamp {
  readonly iso: string;

  constructor(iso: string) {
    this.iso = iso;
  }
}

export type DataKey = string | number | boolean | null;
export type Data = null | boolean | number | PyFloat | string | Timestamp | Data[] | Map<DataKey, Data>;

/** The plain data ruamel's safe constructor builds from `node`. */
export function construct(node: YamlNode | null): Data {
  if (node === null) return null;
  if (node.kind === "sequence") return node.items.map(construct);
  if (node.kind === "mapping") {
    flattenMapping(node);
    const out = new Map<DataKey, Data>();
    if (node.merge !== undefined) {
      // The merged pairs first, then every pair (merged and own) again, unchecked: an own key wins, in the merged key's place.
      for (const [k, v] of node.merge) out.set(mappingKey(k), construct(v));
      const again = new Map<DataKey, Data>();
      for (const [k, v] of node.pairs) again.set(mappingKey(k), construct(v));
      for (const [k, v] of again) out.set(k, v);
      return out;
    }
    for (const [k, v] of node.pairs) {
      const key = mappingKey(k);
      if (out.has(key)) throw new YamlError(`found duplicate key "${String(key)}"`, k.start.line + 1, k.start.column + 1);
      out.set(key, construct(v));
    }
    return out;
  }
  return scalarValue(node);
}

const MERGE_TAG = TAG + "merge";

/** Is `k` a merge key, `<<`? */
export function isMergeKey(k: YamlNode): boolean {
  return k.kind === "scalar" && k.tag === MERGE_TAG;
}

function mergeSourceError(found: YamlNode, sequence: boolean): YamlError {
  const what = sequence ? "expected a mapping for merging" : "expected a mapping or list of mappings for merging";
  return new YamlError(`${what}, but found ${found.kind}`, found.start.line + 1, found.start.column + 1);
}

function duplicateMergeError(k: YamlNode): YamlError {
  return new YamlError("found duplicate merge key \"<<\"", k.start.line + 1, k.start.column + 1);
}

/**
 * ruamel's safe `flatten_mapping`: take the merge key's pairs out of `node`
 * and put the pairs it names in front of its own, as `node.merge` too. A
 * list of mappings merges the last first, so an earlier one wins. Mutates
 * `node`, as ruamel does: the span index then sees the merged pairs.
 */
export function flattenMapping(node: MappingNode): void {
  const merge: [YamlNode, YamlNode][] = [];
  let index = 0;
  while (index < node.pairs.length) {
    const [k, v] = node.pairs[index]!;
    if (!isMergeKey(k)) {
      index++;
      continue;
    }
    if (merge.length > 0) throw duplicateMergeError(k);
    node.pairs.splice(index, 1);
    if (v.kind === "mapping") {
      flattenMapping(v);
      merge.push(...v.pairs);
    } else if (v.kind === "sequence") {
      const submerge: [YamlNode, YamlNode][][] = [];
      for (const sub of v.items) {
        if (sub.kind !== "mapping") throw mergeSourceError(sub, true);
        flattenMapping(sub);
        submerge.push(sub.pairs);
      }
      for (const pairs of submerge.reverse()) merge.push(...pairs);
    } else {
      throw mergeSourceError(v, false);
    }
  }
  if (merge.length > 0) {
    node.merge = merge;
    node.pairs = [...merge, ...node.pairs];
  }
}

/**
 * ruamel's round-trip `flatten_mapping`: take the merge key out of `node`
 * and return the nodes of the mappings it names, in order; the round-trip
 * constructor then adds each one's keys the mapping lacks, after its own.
 */
export function mergeSources(node: MappingNode): { sources: MappingNode[]; position: number } {
  const sources: MappingNode[] = [];
  let position = -1;
  let merged = false;
  let index = 0;
  while (index < node.pairs.length) {
    const [k, v] = node.pairs[index]!;
    if (!isMergeKey(k)) {
      index++;
      continue;
    }
    if (merged) throw duplicateMergeError(k);
    merged = true;
    position = index;
    node.pairs.splice(index, 1);
    if (v.kind === "mapping") {
      sources.push(v);
    } else if (v.kind === "sequence") {
      for (const sub of v.items) {
        if (sub.kind !== "mapping") throw mergeSourceError(sub, true);
        sources.push(sub);
      }
    } else {
      throw mergeSourceError(v, false);
    }
  }
  return { sources, position };
}

/**
 * A mapping key as ruamel's constructor hashes it: by value, so `1.0` and
 * `1` are one key. A collection cannot be a key; a merge key (`<<`) has been
 * flattened away before any key is read.
 */
export function mappingKey(k: YamlNode): DataKey {
  const key = construct(k);
  if (key instanceof Map || Array.isArray(key)) throw new YamlError("found unhashable key", k.start.line + 1, k.start.column + 1);
  return key instanceof PyFloat ? key.value : key instanceof Timestamp ? key.iso : key;
}

const BOOLS: Record<string, boolean> = { yes: true, no: false, y: true, n: false, true: true, false: false, on: true, off: false };

function scalarValue(node: ScalarNode): Data {
  const value = node.value;
  switch (node.tag.slice(TAG.length)) {
    case "null": return null;
    case "bool": return BOOLS[value.toLowerCase()] ?? value;
    case "int": return constructInt(value);
    case "float": {
      const number = constructFloat(value);
      return Number.isInteger(number) ? new PyFloat(number) : number;
    }
    case "timestamp": return constructTimestamp(value);
    default: return value;
  }
}

function constructInt(text: string): number {
  let s = text.replaceAll("_", "");
  const sign = s[0] === "-" ? -1 : 1;
  if (s[0] === "-" || s[0] === "+") s = s.slice(1);
  if (s === "0") return 0;
  if (s.startsWith("0b")) return sign * parseInt(s.slice(2), 2);
  if (s.startsWith("0x")) return sign * parseInt(s.slice(2), 16);
  if (s.startsWith("0o")) return sign * parseInt(s.slice(2), 8);
  return sign * parseInt(s, 10);
}

function constructFloat(text: string): number {
  let s = text.replaceAll("_", "").toLowerCase();
  const sign = s[0] === "-" ? -1 : 1;
  if (s[0] === "-" || s[0] === "+") s = s.slice(1);
  if (s === ".inf") return sign * Infinity;
  if (s === ".nan") return NaN;
  return sign * Number(s);
}

function constructTimestamp(text: string): Timestamp {
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:(?:[Tt]|[ \t]+)(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d*))?(?:[ \t]*(Z|[-+]\d{1,2}(?::\d{2})?))?)?$/.exec(text);
  if (m === null) throw new YamlError(`failed to construct timestamp from "${text}"`);
  const pad = (n: string | undefined, w = 2): string => (n ?? "0").padStart(w, "0");
  const date = `${m[1]}-${pad(m[2])}-${pad(m[3])}`;
  if (m[4] === undefined) return new Timestamp(date);
  // Python's isoformat: microseconds only when non-zero, six digits.
  const micro = m[7] ? m[7].slice(0, 6).padEnd(6, "0") : "";
  const time = `${pad(m[4])}:${m[5]}:${m[6]}${micro && Number(micro) !== 0 ? `.${micro}` : ""}`;
  let zone = "";
  if (m[8] === "Z") zone = "+00:00";
  else if (m[8]) {
    const [h, mm] = m[8].slice(1).split(":");
    zone = `${m[8][0]}${pad(h)}:${pad(mm)}`;
  }
  return new Timestamp(`${date}T${time}${zone}`);
}

/** `text`'s plain data: dicts as Maps in key order, lists and scalars. What the gate compares. */
export function parse(text: string): Data {
  return construct(compose(text));
}

/** `data` with every mapping as its list of pairs, so equality checks key order too. */
export function ordered(data: Data): unknown {
  if (data instanceof Map) return [...data].map(([k, v]) => [k, ordered(v)]);
  if (Array.isArray(data)) return data.map(ordered);
  return data;
}

/** Deep equality of two `Data` values, key order included. */
export function sameData(a: Data, b: Data): boolean {
  if (a instanceof Map && b instanceof Map) {
    if (a.size !== b.size) return false;
    const ea = [...a], eb = [...b];
    return ea.every(([k, v], i) => Object.is(k, eb[i]![0]) && sameData(v, eb[i]![1]));
  }
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => sameData(v, b[i]!));
  if (a instanceof Timestamp && b instanceof Timestamp) return a.iso === b.iso;
  const x = a instanceof PyFloat ? a.value : a, y = b instanceof PyFloat ? b.value : b;
  if (typeof x === "number" && typeof y === "number") return x === y || (Number.isNaN(x) && Number.isNaN(y));
  return x === y;
}
