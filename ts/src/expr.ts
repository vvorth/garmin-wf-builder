// The expression language: parse, type-check, and compile to Monkey C.
//
//
// ADR 0005: expressions are compiled, not interpreted.
// `heart_rate.current > user.hr_zone4 ? palette.hot : palette.text` becomes
// a Monkey C ternary over locals the generator has already fetched; no
// evaluator ships to the device.
//
// The language is deliberately small: literals, references, arithmetic,
// comparison, boolean operators, a ternary and a fixed function set. No
// loops, no user functions, no assignment, no state.
//
// Values keep Python's int/float distinction: a Number is a JavaScript
// integer, a Float a non-integral number or a `PyFloat` (an integral one).
// Integer arithmetic is exact (BigInt where it could leave the safe range),
// so a fold's overflow check sees the true value.
import * as catalog from "./catalog.ts";
import type { Type } from "./catalog.ts";
import { didYouMean, getCloseMatches } from "./diagnostics.ts";
import { PyFloat } from "./edit/yaml.ts";
import { stringLiteral } from "./mcsource.ts";
import { compareStrings, floatRepr, quoted } from "./py.ts";

// -- values -----------------------------------------------------------------------

/** A value an expression computes: Python's int (`number`/`bigint`), float (`number`/`PyFloat`), bool, str or None. */
export type ExprValue = number | bigint | PyFloat | boolean | string | null;

const isWhole = (v: unknown): v is number | bigint => typeof v === "bigint" || (typeof v === "number" && Number.isInteger(v));
const isFloatV = (v: unknown): boolean => v instanceof PyFloat || (typeof v === "number" && !Number.isInteger(v));
const isNum = (v: unknown): v is number | bigint | PyFloat => typeof v === "number" || typeof v === "bigint" || v instanceof PyFloat;
const toNumber = (v: number | bigint | PyFloat): number => (v instanceof PyFloat ? v.value : Number(v));
const big = (v: number | bigint): bigint => (typeof v === "bigint" ? v : BigInt(v));

/** An int, as a plain number when safe and a BigInt beyond. */
function intValue(v: bigint): number | bigint {
  return v >= BigInt(Number.MIN_SAFE_INTEGER) && v <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(v) : v;
}

/** A float result: boxed when integral, so it stays a float. */
function floatValue(v: number): number | PyFloat {
  return Number.isFinite(v) && Number.isInteger(v) ? new PyFloat(v) : v;
}

/** An expression value as a message prints it: `null`, `true` and `false` as the expression language spells them. */
export function valueText(v: unknown): string {
  if (v === null || v === undefined) return "null";
  if (v === true) return "true";
  if (v === false) return "false";
  if (typeof v === "bigint") return v.toString();
  if (v instanceof PyFloat) return floatRepr(v.value);
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : floatRepr(v);
  return String(v);
}

// -- tokens -----------------------------------------------------------------------

/** A syntax or type error, with an offset into the expression text. */
export class ExprError extends Error {
  readonly offset: number;
  readonly notes: string[];
  /** A diagnostic code more specific than the generic "expression": only `source-renamed` today. */
  readonly code: string | null;

  constructor(message: string, offset = 0, notes: string[] = [], code: string | null = null) {
    super(message);
    this.offset = offset;
    this.notes = notes;
    this.code = code;
  }
}

const TOKEN = /(?<ws>\s+)|(?<number>\d+\.\d+|\.\d+|\d+)|(?<string>'[^']*'|"[^"]*")|(?<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)|(?<op><=|>=|==|!=|&&|\|\||[-+*/%<>?:(),!])/uy;

const KEYWORDS = new Set(["and", "or", "not", "true", "false", "null"]);

export interface Token {
  kind: "number" | "string" | "name" | "op" | "keyword" | "end";
  text: string;
  offset: number;
}

/** The tokens of `text`; offsets are code-point offsets, as Python's. */
export function tokenize(text: string): Token[] {
  const points = Array.from(text);
  const tokens: Token[] = [];
  let pos = 0;
  let cp = 0;
  while (pos < text.length) {
    TOKEN.lastIndex = pos;
    const m = TOKEN.exec(text);
    if (m === null) throw new ExprError(`unexpected character ${quoted(points[cp])}`, cp);
    const value = m[0];
    const groups = m.groups!;
    let kind = (["ws", "number", "string", "name", "op"] as const).find((g) => groups[g] !== undefined)!;
    const start = cp;
    pos += value.length;
    cp += Array.from(value).length;
    if (kind === "ws") continue;
    if (kind === "name" && KEYWORDS.has(value)) {
      tokens.push({ kind: "keyword", text: value, offset: start });
      continue;
    }
    tokens.push({ kind, text: value, offset: start });
    void kind;
  }
  tokens.push({ kind: "end", text: "", offset: points.length });
  return tokens;
}

// -- the AST -----------------------------------------------------------------------

export type Node = Literal | Ref | Unary | Binary | Conditional | Call;

export interface Literal { kind: "literal"; value: ExprValue; type: Type; offset: number }
export interface Ref { kind: "ref"; path: string; offset: number }
export interface Unary { kind: "unary"; op: string; operand: Node; offset: number }
export interface Binary { kind: "binary"; op: string; left: Node; right: Node; offset: number }
export interface Conditional { kind: "conditional"; cond: Node; then: Node; otherwise: Node; offset: number }
export interface Call { kind: "call"; name: string; args: Node[]; offset: number }

export const literal = (value: ExprValue, type: Type, offset = 0): Literal => ({ kind: "literal", value, type, offset });

export function children(node: Node): Node[] {
  switch (node.kind) {
    case "unary": return [node.operand];
    case "binary": return [node.left, node.right];
    case "conditional": return [node.cond, node.then, node.otherwise];
    case "call": return [...node.args];
    default: return [];
  }
}

/** `node` and every node under it, pre-order. */
export function* walk(node: Node): Generator<Node> {
  yield node;
  for (const child of children(node)) yield* walk(child);
}

// -- functions ---------------------------------------------------------------------

/** Binary operator precedence; higher binds tighter. All left-associative. */
const BINARY: ReadonlyMap<string, number> = new Map([
  ["or", 1], ["||", 1], ["and", 2], ["&&", 2], ["==", 3], ["!=", 3],
  ["<", 4], ["<=", 4], [">", 4], [">=", 4], ["+", 5], ["-", 5], ["*", 6], ["/", 6], ["%", 6],
]);

export interface ExprFunction {
  arity: number;
  description: string;
  /** The result type, or `null` when it follows the arguments (Float if any is). */
  result: Type | null;
  /** Host evaluation over argument values; `null` means "no value". */
  host: (args: ExprValue[]) => ExprValue;
  /** Toybox module the emitted call needs, or `null` for a `WfbMath` barrel call. */
  module: string | null;
}

/** Python's `<` over two numbers of any kind; a non-number raises TypeError, as Python's comparison would. */
function less(a: ExprValue, b: ExprValue): boolean {
  if (isNum(a) && isNum(b)) {
    if (isWhole(a) && isWhole(b)) return big(a) < big(b);
    return toNumber(a) < toNumber(b);
  }
  if (typeof a === "boolean" || typeof b === "boolean") return less(numberOf(a), numberOf(b));
  if (typeof a === "string" && typeof b === "string") return compareStrings(a, b) < 0;
  throw new TypeError("'<' not supported");
}

function numberOf(v: ExprValue): number | bigint | PyFloat {
  if (v === true) return 1;
  if (v === false) return 0;
  if (isNum(v)) return v;
  throw new TypeError("not a number");
}

/** `Math.round`: halves rounded up, toward +infinity (-2.5 is -2), as the watch does (`docs/research/probes/text-of-values/`). */
function round(args: ExprValue[]): ExprValue {
  const x = toNumber(numberOf(args[0]!));
  const whole = Math.floor(x);
  return intValue(BigInt(whole) + (x - whole >= 0.5 ? 1n : 0n));
}

/** `WfbMath.clamp`, in its order: below `lo` first, then above `hi`. */
function clamp(args: ExprValue[]): ExprValue {
  const [value, lo, hi] = args as [ExprValue, ExprValue, ExprValue];
  if (less(value, lo)) return lo;
  if (less(hi, value)) return hi;
  return value;
}

/** `WfbMath.percent`: 0.0 for a goal <= 0, otherwise clamped to 0..100. */
function percent(args: ExprValue[]): ExprValue {
  const [value, goal] = args as [ExprValue, ExprValue];
  if (!less(0, goal!)) return new PyFloat(0);
  return clamp([floatValue(100.0 * toNumber(numberOf(value)) / toNumber(numberOf(goal))), new PyFloat(0), new PyFloat(100)]);
}

/** Monkey C's `%`: the remainder takes the dividend's sign. Integers only. */
function mod(a: ExprValue, b: ExprValue): ExprValue {
  if (!isWhole(a) || !isWhole(b)) throw new TypeError("% needs integers");
  const x = big(a), y = big(b);
  const remainder = (x < 0n ? -x : x) % (y < 0n ? -y : y);
  return intValue(x < 0n ? -remainder : remainder);
}

/** Monkey C's `Number` is a 32-bit signed integer. */
export const NUMBER_MIN = -(2 ** 31);
export const NUMBER_MAX = 2 ** 31 - 1;

/** `value` wrapped to a 32-bit `Number`, two's complement: what `monkeyc`'s constant folder makes of an overflow. */
export function wrapNumber(value: number | bigint): number {
  const v = big(value) - BigInt(NUMBER_MIN);
  const m = 2n ** 32n;
  return Number(((v % m) + m) % m + BigInt(NUMBER_MIN));
}

function minMax(args: ExprValue[], pickSecond: (a: ExprValue, b: ExprValue) => boolean): ExprValue {
  const [a, b] = args as [ExprValue, ExprValue];
  return pickSecond(a, b) ? b : a;
}

function absValue(v: ExprValue): ExprValue {
  if (typeof v === "bigint") return v < 0n ? -v : v;
  if (v instanceof PyFloat) return new PyFloat(Math.abs(v.value));
  if (typeof v === "number") return Math.abs(v);
  if (typeof v === "boolean") return Number(v);
  throw new TypeError("bad operand type for abs()");
}

export const FUNCTIONS: ReadonlyMap<string, ExprFunction> = new Map<string, ExprFunction>([
  ["min", { arity: 2, description: "smaller of two numbers", result: null, module: null,
    host: (a) => minMax(a, (x, y) => less(y, x)) }],
  ["max", { arity: 2, description: "larger of two numbers", result: null, module: null,
    host: (a) => minMax(a, (x, y) => less(x, y)) }],
  ["clamp", { arity: 3, description: "clamp(value, lo, hi)", result: null, module: null, host: clamp }],
  ["round", { arity: 1, description: "round to the nearest whole number (.5 rounds up)", result: "number",
    module: "Toybox.Math", host: round }],
  ["floor", { arity: 1, description: "round down", result: "number", module: "Toybox.Math",
    host: (a) => intValue(BigInt(Math.floor(toNumber(numberOf(a[0]!))))) }],
  ["abs", { arity: 1, description: "absolute value", result: null, module: null, host: (a) => absValue(a[0]!) }],
  ["percent", { arity: 2, description: "percent(value, goal) -> 0..100", result: "float", module: null, host: percent }],
]);

/** Toybox modules the emitted code needs, keyed by expression function name. */
export const CALL_MODULES: ReadonlyMap<string, string> = new Map(
  [...FUNCTIONS].filter(([, f]) => f.module !== null).map(([name, f]) => [name, f.module!]));
/** Expression functions that compile to a support-barrel call. */
export const CALL_BARREL: ReadonlySet<string> = new Set([...FUNCTIONS].filter(([, f]) => f.module === null).map(([name]) => name));

// -- the parser ----------------------------------------------------------------------

export class Parser {
  readonly text: string;
  readonly tokens: Token[];
  pos = 0;

  constructor(text: string) {
    this.text = text;
    this.tokens = tokenize(text);
  }

  get current(): Token {
    return this.tokens[this.pos]!;
  }

  advance(): Token {
    return this.tokens[this.pos++]!;
  }

  expect(text: string): Token {
    if (this.current.text !== text) {
      throw new ExprError(`expected ${quoted(text)} but found ${quoted(this.current.text || "end of expression")}`, this.current.offset);
    }
    return this.advance();
  }

  parse(): Node {
    const node = this.parseTernary();
    if (this.current.kind !== "end") throw new ExprError(`unexpected ${quoted(this.current.text)}`, this.current.offset);
    return node;
  }

  parseTernary(): Node {
    const cond = this.parseBinary(0);
    if (this.current.text === "?") {
      const offset = this.advance().offset;
      const then = this.parseTernary();
      this.expect(":");
      const otherwise = this.parseTernary();
      return { kind: "conditional", cond, then, otherwise, offset };
    }
    return cond;
  }

  parseBinary(minPrec: number): Node {
    let left = this.parseUnary();
    for (;;) {
      const op = this.current.text;
      const prec = BINARY.get(op);
      if (prec === undefined || prec < minPrec) return left;
      const offset = this.advance().offset;
      const right = this.parseBinary(prec + 1);
      left = { kind: "binary", op: canonicalOp(op), left, right, offset };
    }
  }

  parseUnary(): Node {
    const token = this.current;
    if (token.text === "-" || token.text === "not" || token.text === "!") {
      this.advance();
      return { kind: "unary", op: token.text === "-" ? "-" : "not", operand: this.parseUnary(), offset: token.offset };
    }
    return this.parsePrimary();
  }

  parsePrimary(): Node {
    const token = this.advance();
    if (token.text === "(") {
      const node = this.parseTernary();
      this.expect(")");
      return node;
    }
    if (token.kind === "number") {
      if (token.text.includes(".")) return literal(floatValue(Number(token.text)), "float", token.offset);
      return literal(intValue(BigInt(token.text)), "number", token.offset);
    }
    if (token.kind === "string") return literal(token.text.slice(1, -1), "string", token.offset);
    if (token.kind === "keyword") {
      if (token.text === "true" || token.text === "false") return literal(token.text === "true", "boolean", token.offset);
      if (token.text === "null") return literal(null, "number", token.offset);
      throw new ExprError(`${quoted(token.text)} cannot start an expression`, token.offset);
    }
    if (token.kind === "name") {
      if (this.current.text === "(") return this.parseCall(token);
      return { kind: "ref", path: token.text, offset: token.offset };
    }
    throw new ExprError(`expected a value but found ${quoted(token.text || "end of expression")}`, token.offset);
  }

  parseCall(name: Token): Node {
    const fn = FUNCTIONS.get(name.text);
    if (fn === undefined) {
      throw new ExprError(`unknown function ${quoted(name.text)}`, name.offset,
        [`the expression language has exactly these functions: ${[...FUNCTIONS.keys()].sort().join(", ")}`]);
    }
    this.expect("(");
    const args: Node[] = [];
    if (this.current.text !== ")") {
      args.push(this.parseTernary());
      while (this.current.text === ",") {
        this.advance();
        args.push(this.parseTernary());
      }
    }
    this.expect(")");
    if (args.length !== fn.arity) {
      throw new ExprError(`${name.text}() takes ${fn.arity} argument(s), got ${args.length}`, name.offset, [fn.description]);
    }
    return { kind: "call", name: name.text, args, offset: name.offset };
  }
}

function canonicalOp(op: string): string {
  return op === "&&" ? "and" : op === "||" ? "or" : op;
}

export function parse(text: string): Node {
  return new Parser(text).parse();
}

// -- types and scope ---------------------------------------------------------------------

/** The static type of an expression, plus whether it may be absent. */
export class Value {
  readonly type: Type;
  readonly nullable: boolean;

  constructor(type: Type, nullable = false) {
    this.type = type;
    this.nullable = nullable;
  }

  toString(): string {
    return `${this.type}${this.nullable ? "?" : ""}`;
  }
}

/** A name the expression may refer to, and how to read it in Monkey C. */
export interface Binding {
  value: Value;
  /** The Monkey C expression producing it; for a nullable binding, the guarded local. */
  code: string;
  /** Set when the value is known at build time, enabling constant folding. */
  constant?: ExprValue;
}

/** The names in scope, and the sources an expression turned out to use. */
export class Scope {
  bindings = new Map<string, Binding>();
  used = new Set<string>();

  define(name: string, binding: Binding): void {
    this.bindings.set(name, binding);
  }

  lookup(name: string): Binding | undefined {
    const binding = this.bindings.get(name);
    if (binding !== undefined) this.used.add(name);
    return binding;
  }
}

/** The index of the copy being drawn, 0-based: bound only while a pattern's own expressions are compiled. */
export const COPY = "copy";

/** Does this (folded) expression read `COPY`? */
export function readsCopy(node: Node | null | undefined): boolean {
  if (node === null || node === undefined) return false;
  for (const n of walk(node)) if (n.kind === "ref" && n.path === COPY) return true;
  return false;
}

const NUMERIC_OPS = new Set(["+", "-", "*", "/", "%"]);
const DIVISION_OPS = new Set(["/", "%"]);
const COMPARISON_OPS = new Set(["<", "<=", ">", ">="]);
const EQUALITY_OPS = new Set(["==", "!="]);
const BOOLEAN_OPS = new Set(["and", "or"]);

/** Infer the type of `node`, raising `ExprError` on a mismatch. */
export function check(node: Node, scope: Scope): Value {
  switch (node.kind) {
    case "literal":
      if (node.type === "number" && isWhole(node.value) && big(node.value) > BigInt(NUMBER_MAX)) {
        throw new ExprError(`${valueText(node.value)} is too large for a whole number`, node.offset,
          [`Monkey C's Number is 32-bit: at most ${NUMBER_MAX}`, "write it with a decimal point to make it a Float"]);
      }
      return new Value(node.type);
    case "ref": {
      const binding = scope.lookup(node.path);
      if (binding === undefined) throw unknownRef(node, scope);
      return binding.value;
    }
    case "unary": {
      const inner = check(node.operand, scope);
      if (node.op === "-") {
        requireNumeric(inner, "-", node.offset);
        return new Value(inner.type, inner.nullable);
      }
      requireType(inner, "boolean", "not", node.offset);
      return new Value("boolean", inner.nullable);
    }
    case "binary": {
      const left = check(node.left, scope), right = check(node.right, scope);
      const nullable = left.nullable || right.nullable;
      if (NUMERIC_OPS.has(node.op)) {
        requireNumeric(left, node.op, node.offset);
        requireNumeric(right, node.op, node.offset);
        if (node.op === "%" && (left.type === "float" || right.type === "float")) {
          throw new ExprError(`% needs two whole numbers, got ${left} % ${right}`, node.offset,
            ["Monkey C has no remainder of a Float ('monkeyc' refuses it); wrap the Float side in floor() or round() first"]);
        }
        if (node.op === "/" || left.type === "float" || right.type === "float") return new Value("float", nullable);
        return new Value("number", nullable);
      }
      if (COMPARISON_OPS.has(node.op)) {
        requireNumeric(left, node.op, node.offset);
        requireNumeric(right, node.op, node.offset);
        return new Value("boolean", nullable);
      }
      if (EQUALITY_OPS.has(node.op)) {
        if (left.type !== right.type && !(catalog.isNumeric(left.type) && catalog.isNumeric(right.type))) {
          throw new ExprError(`cannot compare ${left} with ${right}`, node.offset, ["the two sides of == and != must have the same type"]);
        }
        return new Value("boolean", nullable);
      }
      if (BOOLEAN_OPS.has(node.op)) {
        requireType(left, "boolean", node.op, node.offset);
        requireType(right, "boolean", node.op, node.offset);
        return new Value("boolean", nullable);
      }
      throw new ExprError(`unknown operator ${quoted(node.op)}`, node.offset);
    }
    case "conditional": {
      const cond = check(node.cond, scope);
      requireType(cond, "boolean", "?:", node.offset);
      const then = check(node.then, scope), otherwise = check(node.otherwise, scope);
      let merged: Type;
      if (then.type !== otherwise.type) {
        if (catalog.isNumeric(then.type) && catalog.isNumeric(otherwise.type)) {
          merged = then.type === "float" || otherwise.type === "float" ? "float" : "number";
        } else {
          throw new ExprError(`the two branches of ?: have different types: ${then} and ${otherwise}`, node.offset);
        }
      } else {
        merged = then.type;
      }
      return new Value(merged, cond.nullable || then.nullable || otherwise.nullable);
    }
    case "call": {
      const args = node.args.map((a) => check(a, scope));
      const nullable = args.some((a) => a.nullable);
      for (const arg of args) requireNumeric(arg, `${node.name}()`, node.offset);
      let result = FUNCTIONS.get(node.name)!.result;
      if (result === null) result = args.some((a) => a.type === "float") ? "float" : "number";
      return new Value(result, nullable);
    }
  }
}

function unknownRef(node: Ref, scope: Scope): ExprError {
  if (node.path === COPY) {
    return new ExprError(
      `${quoted(COPY)} is only defined in a 'type: pattern' element's colours, its parts' 'visible:' and a text part's placeholder`,
      node.offset,
      [`${quoted(COPY)} is the index of the copy being drawn, 0-based -- nothing but a pattern has copies`,
        "to hide some copies, put 'visible:' on the parts, or use 'skip:'"]);
  }
  const renamed = catalog.renamedTo(node.path);
  if (renamed !== undefined) {
    return new ExprError(`${quoted(node.path)} has been renamed to ${quoted(renamed)}`, node.offset,
      ["complications now have their own namespace -- 'complication.<type>' is always read through Toybox.Complications, " +
        "and every other catalogue path is always a direct API read",
      "the value is unchanged; only the path moves",
      "run `wfb sources` for the current catalogue"], "source-renamed");
  }
  // Prefer suggestions from the same namespace.
  const namespace = node.path.includes(".") ? node.path.split(".", 1)[0]! : "";
  const siblings = [...scope.bindings.keys()].filter((name) => name.startsWith(`${namespace}.`)).sort(compareStrings);
  let near = getCloseMatches(node.path, siblings, 3, 0.4);
  if (near.length === 0 && siblings.length === 0) near = catalog.CATALOG.suggest(node.path);
  let note: string;
  if (near.length > 0) note = didYouMean(near)[0]!;
  else if (siblings.length > 0) note = `${namespace} has: ` + siblings.join(", ");
  else note = "known namespaces: " + [...catalog.namespaces().keys()].sort(compareStrings).join(", ") + ", color";
  return new ExprError(`unknown data source ${quoted(node.path)}`, node.offset, [note]);
}

function requireType(value: Value, want: Type, op: string, offset: number): void {
  if (value.type !== want) throw new ExprError(`${op} needs a ${want}, got ${value}`, offset);
}

function requireNumeric(value: Value, op: string, offset: number): void {
  if (!catalog.isNumeric(value.type)) {
    const hint = value.type === "color" ? ["colours are not numbers here -- arithmetic on a palette entry is almost always a mistake"] : [];
    throw new ExprError(`${op} needs a number, got ${value}`, offset, hint);
  }
}

// -- constant folding and emission ----------------------------------------------------------

/**
 * Replace any subtree whose value is known at build time with a literal.
 * `foldColors: false` leaves palette references as references, so the
 * emitted code names `Palette.ACCENT`; the linter folds them for the value.
 */
export function fold(node: Node, scope: Scope, foldColors = true): Node {
  switch (node.kind) {
    case "literal":
      return node;
    case "ref": {
      const binding = scope.bindings.get(node.path);
      if (binding === undefined || binding.constant === undefined || binding.constant === null) return node;
      if (!foldColors && binding.value.type === "color") return node;
      return literal(binding.constant, binding.value.type, node.offset);
    }
    case "unary": {
      const operand = fold(node.operand, scope, foldColors);
      if (operand.kind === "literal" && operand.value !== null) {
        if (node.op === "-") return literal(negate(operand.value), operand.type, node.offset);
        return literal(!truthyValue(operand.value), "boolean", node.offset);
      }
      return { ...node, operand };
    }
    case "binary": {
      const left = fold(node.left, scope, foldColors), right = fold(node.right, scope, foldColors);
      if (DIVISION_OPS.has(node.op) && isZero(right)) {
        throw new ExprError(node.op === "/" ? "division by zero" : "remainder of a division by zero", node.offset,
          ["the divisor is always 0 here, and monkeyc refuses to compile that"]);
      }
      if ((node.op === "+" || node.op === "-" || node.op === "*") && left.kind === "literal" && right.kind === "literal"
        && isWhole(left.value) && isWhole(right.value)) {
        const a = big(left.value), b = big(right.value);
        const exact = node.op === "+" ? a + b : node.op === "-" ? a - b : a * b;
        if (exact < BigInt(NUMBER_MIN) || exact > BigInt(NUMBER_MAX)) {
          throw new ExprError(`${valueText(left.value)} ${node.op} ${valueText(right.value)} is ${exact}, too large for a whole number`, node.offset,
            [`Monkey C's Number is 32-bit (${NUMBER_MIN} to ${NUMBER_MAX}), so the watch would wrap it round to ${wrapNumber(exact)}`,
              "make one side a Float (write it with a decimal point) to compute it in floating point"]);
        }
      }
      if (left.kind === "literal" && right.kind === "literal" && left.value !== null && right.value !== null
        && left.type !== "color" && right.type !== "color") {
        const folded = apply(node.op, left.value, right.value);
        if (folded !== null) return literal(folded[0], folded[1], node.offset);
      }
      return { ...node, left, right };
    }
    case "conditional": {
      const cond = fold(node.cond, scope, foldColors);
      const then = fold(node.then, scope, foldColors);
      const otherwise = fold(node.otherwise, scope, foldColors);
      if (cond.kind === "literal" && typeof cond.value === "boolean") return cond.value ? then : otherwise;
      return { ...node, cond, then, otherwise };
    }
    case "call": {
      const args = node.args.map((a) => fold(a, scope, foldColors));
      const literals = args.filter((a): a is Literal => a.kind === "literal" && a.value !== null);
      if (literals.length === args.length) {
        const values = literals.map((a) => a.value);
        const folded = applyCall(node.name, values);
        if (folded !== null) return literal(folded[0], folded[1], node.offset);
      }
      return { ...node, args };
    }
  }
}

/** Python's truthiness of an expression value. */
function truthyValue(v: ExprValue): boolean {
  if (v === null || v === false || v === "") return false;
  if (v instanceof PyFloat) return v.value !== 0;
  if (typeof v === "bigint") return v !== 0n;
  if (typeof v === "number") return v !== 0;
  return true;
}

/** `value` as the number a numeric literal or reading holds; `TypeError` for anything else. */
export function asNumber(value: unknown): number | bigint | PyFloat {
  if (isNum(value)) return value;
  if (typeof value === "boolean") return Number(value);
  throw new TypeError(`expected a number, got ${quoted(value)}`);
}

function negate(value: ExprValue): ExprValue {
  const n = asNumber(value);
  if (n instanceof PyFloat) return new PyFloat(-n.value);
  if (isWhole(n)) return wrapNumber(-big(n));
  return -n;
}

function isLiteral(node: Node): boolean {
  return node.kind === "literal" || (node.kind === "unary" && node.op === "-" && node.operand.kind === "literal");
}

/** Is `node` a numeric literal 0 (or 0.0)? */
function isZero(node: Node): boolean {
  return node.kind === "literal" && catalog.isNumeric(node.type) && isNum(node.value) && toNumber(node.value) === 0;
}

function numericType(value: ExprValue): Type {
  return isFloatV(value) ? "float" : "number";
}

/** Python's `a op b` for the foldable operators; TypeError for a pair the operator does not take. */
function hostBinary(op: string, a: ExprValue, b: ExprValue): ExprValue {
  switch (op) {
    case "+": case "-": case "*": {
      if (typeof a === "string" && typeof b === "string" && op === "+") return a + b;
      if (typeof a === "string" || typeof b === "string" || a === null || b === null) throw new TypeError("unsupported operand");
      const x = numberOf(a), y = numberOf(b);
      if (isWhole(x) && isWhole(y)) {
        const p = big(x), q = big(y);
        return intValue(op === "+" ? p + q : op === "-" ? p - q : p * q);
      }
      const p = toNumber(x), q = toNumber(y);
      return floatValue(op === "+" ? p + q : op === "-" ? p - q : p * q);
    }
    case "/": {
      if (!(isNum(a) || typeof a === "boolean") || !(isNum(b) || typeof b === "boolean")) throw new TypeError("unsupported operand");
      return floatValue(toNumber(numberOf(a)) / toNumber(numberOf(b)));
    }
    case "%": return mod(a, b);
    case "<": return less(a, b);
    case "<=": return !less(b, a);
    case ">": return less(b, a);
    case ">=": return !less(a, b);
    case "==": return pyEquals(a, b);
    case "!=": return !pyEquals(a, b);
    case "and": return truthyValue(a) && truthyValue(b);
    case "or": return truthyValue(a) || truthyValue(b);
    default: throw new TypeError("unknown operator");
  }
}

function pyEquals(a: ExprValue, b: ExprValue): boolean {
  const an = typeof a === "boolean" ? Number(a) : a, bn = typeof b === "boolean" ? Number(b) : b;
  if (isNum(an) && isNum(bn)) return isWhole(an) && isWhole(bn) ? big(an) === big(bn) : toNumber(an) === toNumber(bn);
  return an === bn;
}

/** `a op b` on the host, typed; `null` when it has no value. */
export function apply(op: string, a: ExprValue, b: ExprValue): [ExprValue, Type] | null {
  if ((op === "/" || op === "%") && pyEquals(b, 0)) return null;
  if (!["+", "-", "*", "/", "%", "<", "<=", ">", ">=", "==", "!=", "and", "or"].includes(op)) return null;
  let result: ExprValue;
  try {
    result = hostBinary(op, a, b);
  } catch (error) {
    if (error instanceof TypeError) return null;
    throw error;
  }
  if (COMPARISON_OPS.has(op) || EQUALITY_OPS.has(op) || BOOLEAN_OPS.has(op)) return [truthyValue(result), "boolean"];
  if (isWhole(result)) result = wrapNumber(result);
  return [result, op === "/" ? "float" : numericType(result)];
}

function applyCall(name: string, args: ExprValue[]): [ExprValue, Type] | null {
  const fn = FUNCTIONS.get(name);
  if (fn === undefined) return null;
  let value: ExprValue;
  try {
    value = fn.host(args);
  } catch (error) {
    if (error instanceof TypeError || error instanceof RangeError) return null;
    throw error;
  }
  if (value === null) return null;
  return [value, fn.result ?? numericType(value)];
}

/** Compile to a Monkey C expression. */
export function emit(node: Node, scope: Scope): string {
  switch (node.kind) {
    case "literal": return emitLiteral(node);
    case "ref": return scope.bindings.get(node.path)!.code;
    case "unary": {
      const inner = emit(node.operand, scope);
      return node.op === "-" ? `(-${inner})` : `(!${inner})`;
    }
    case "binary": {
      const op = node.op === "and" ? "&&" : node.op === "or" ? "||" : node.op;
      let leftCode = emit(node.left, scope);
      const rightCode = emit(node.right, scope);
      if (DIVISION_OPS.has(node.op) && !isLiteral(node.right)) {
        // A divisor only known on the watch can be 0 there: the guarded barrel call gives 0 rather than dividing by it.
        return `WfbMath.${node.op === "/" ? "div" : "mod"}(${leftCode}, ${rightCode})`;
      }
      if (node.op === "/" && !hasFloatOperand(node.left, node.right, scope)) {
        // `check` types `/` as Float, but Monkey C's `Number / Number` truncates: coerce one side.
        leftCode = node.left.kind === "literal" ? `(${leftCode}).toFloat()` : `${leftCode}.toFloat()`;
      }
      return `(${leftCode} ${op} ${rightCode})`;
    }
    case "conditional":
      return `(${emit(node.cond, scope)} ? ${emit(node.then, scope)} : ${emit(node.otherwise, scope)})`;
    case "call": {
      const args = node.args.map((a) => emit(a, scope));
      return CALL_BARREL.has(node.name) ? `WfbMath.${node.name}(${args.join(", ")})` : `Math.${node.name}(${args[0]}).toNumber()`;
    }
  }
}

function hasFloatOperand(left: Node, right: Node, scope: Scope): boolean {
  return check(left, scope).type === "float" || check(right, scope).type === "float";
}

function emitLiteral(node: Literal): string {
  const value = node.value;
  if (value === null) return "null";
  if (node.type === "boolean") return value ? "true" : "false";
  if (node.type === "string") return stringLiteral(typeof value === "string" ? value : valueText(value));
  if (node.type === "color") {
    const n = asNumber(value);
    return `0x${Math.trunc(toNumber(n)).toString(16).toUpperCase().padStart(6, "0")}`;
  }
  if (node.type === "float") return `${floatRepr(toNumber(asNumber(value)))}f`;
  const n = asNumber(value);
  if (pyEquals(n as ExprValue, NUMBER_MIN)) return `(${NUMBER_MIN + 1} - 1)`;
  return isWhole(n) ? big(n).toString() : String(Math.trunc(toNumber(n)));
}

/** Parse, type-check, fold and emit in one step; colours stay named (`Palette.NAME`) by default. */
export function compileExpression(text: string, scope: Scope, foldColors = false): [string, Value, Node] {
  const node = parse(text);
  const value = check(node, scope);
  const folded = fold(node, scope, foldColors);
  return [emit(folded, scope), value, folded];
}

// -- host-side evaluation, for the preview ------------------------------------------------------

/** Evaluate an expression on the host against sample readings; `null` when any input is absent. */
export function evaluate(node: Node, values: ReadonlyMap<string, ExprValue>): ExprValue {
  switch (node.kind) {
    case "literal": return node.value;
    case "ref": return values.get(node.path) ?? null;
    case "unary": {
      const inner = evaluate(node.operand, values);
      if (inner === null) return null;
      return node.op === "-" ? negate(inner) : !truthyValue(inner);
    }
    case "binary": {
      const left = evaluate(node.left, values), right = evaluate(node.right, values);
      if (node.op === "and") return left !== null && right !== null ? truthyValue(left) && truthyValue(right) : null;
      if (node.op === "or") return left !== null && right !== null ? truthyValue(left) || truthyValue(right) : null;
      if (left === null || right === null) return null;
      // `WfbMath.div`/`WfbMath.mod`: a zero divisor gives 0
      if (DIVISION_OPS.has(node.op) && pyEquals(right, 0)) return node.op === "/" ? new PyFloat(0) : 0;
      const folded = apply(node.op, left, right);
      return folded ? folded[0] : null;
    }
    case "conditional": {
      const cond = evaluate(node.cond, values);
      if (cond === null) return null;
      return evaluate(truthyValue(cond) ? node.then : node.otherwise, values);
    }
    case "call": {
      const args = node.args.map((a) => evaluate(a, values));
      if (args.some((a) => a === null)) return null;
      const folded = applyCall(node.name, args);
      return folded ? folded[0] : null;
    }
  }
}
