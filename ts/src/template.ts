// Format 2's `text:` template: `"{expr:spec}"` with literal text around it.
//
//
// - `{{` and `}}` are a literal `{` and `}`.
// - `{expr}` and `{expr:spec}` are a placeholder. The expression ends at
//   the first `:` outside parentheses, brackets and quotes, so a ternary is
//   parenthesised: `"{(x > 0 ? x : 0):d}"`. `spec` runs to the closing `}`
//   and is exactly a format spec: `d`, `.1f`, `%H:%M`, a duration.
// - `{unit}` is the label of the unit a `units:` conversion displays in.
//
// Offsets count code points, as Python's do, so a caret lands on the same
// character.
import { ExprError, tokenize } from "./expr.ts";

const V1_FIELD = /\{(?:(?<unit>unit)|:(?<spec>[^}]*))?\}/g;
const OPEN: Readonly<Record<string, string>> = { "(": ")", "[": "]" };

/** A malformed template, with an offset into its text. */
export class TemplateError extends Error {
  readonly offset: number;

  constructor(message: string, offset: number) {
    super(message);
    this.offset = offset;
  }
}

export interface LiteralPiece { kind: "literal"; text: string }
export interface Placeholder { kind: "placeholder"; expr: string; spec: string | null; offset: number }
export interface UnitPiece { kind: "unit" }
export type Piece = LiteralPiece | Placeholder | UnitPiece;

export class Template {
  readonly pieces: readonly Piece[];

  constructor(pieces: readonly Piece[]) {
    this.pieces = pieces;
  }

  get placeholders(): Placeholder[] {
    return this.pieces.filter((p): p is Placeholder => p.kind === "placeholder");
  }

  get placeholder(): Placeholder | null {
    return this.placeholders[0] ?? null;
  }

  /** The text of a template with no placeholder. */
  get literal(): string {
    return this.pieces.map((p) => (p.kind === "literal" ? p.text : "")).join("");
  }
}

const startsWith = (chars: string[], i: number, s: string): boolean => [...s].every((c, k) => chars[i + k] === c);

export function parseTemplate(text: string): Template {
  const chars = Array.from(text);
  const pieces: Piece[] = [];
  let buf = "";
  const flush = (): void => {
    if (buf) { pieces.push({ kind: "literal", text: buf }); buf = ""; }
  };
  let i = 0;
  while (i < chars.length) {
    const ch = chars[i]!;
    if (ch === "{") {
      if (startsWith(chars, i, "{{")) { buf += "{"; i += 2; continue; }
      flush();
      const [piece, next] = placeholderAt(chars, i);
      pieces.push(piece);
      i = next;
      continue;
    }
    if (ch === "}") {
      if (startsWith(chars, i, "}}")) { buf += "}"; i += 2; continue; }
      throw new TemplateError("a single '}' outside a placeholder; write '}}' for a literal brace", i);
    }
    buf += ch;
    i++;
  }
  flush();
  return new Template(pieces);
}

/** Python's `str.strip()`. */
function strip(text: string): string {
  return text.replace(/^\s+|\s+$/gu, "");
}

function placeholderAt(chars: string[], start: number): [Placeholder | UnitPiece, number] {
  let i = start + 1;
  const depth: string[] = [];
  let quote: string | null = null;
  const n = chars.length;
  while (i < n) {
    const ch = chars[i]!;
    if (quote) {
      if (ch === quote) quote = null;
    } else if (ch === "'" || ch === "\"") {
      quote = ch;
    } else if (ch in OPEN) {
      depth.push(OPEN[ch]!);
    } else if (depth.length > 0 && ch === depth[depth.length - 1]) {
      depth.pop();
    } else if (depth.length === 0 && (ch === ":" || ch === "}")) {
      break;
    } else if (ch === "{") {
      throw new TemplateError("'{' inside a placeholder", i);
    }
    i++;
  }
  if (i >= n) throw new TemplateError("a '{' with no closing '}'; write '{{' for a literal brace", start);
  const expr = chars.slice(start + 1, i).join("");
  if (chars[i] === "}") {
    if (strip(expr) === "unit") return [{ kind: "unit" }, i + 1];
    return [{ kind: "placeholder", expr: strip(expr), spec: null, offset: start + 1 }, i + 1];
  }
  const close = chars.indexOf("}", i + 1);
  if (close < 0) throw new TemplateError("a '{' with no closing '}'", start);
  const spec = chars.slice(i + 1, close).join("");
  if (spec.includes("{")) throw new TemplateError("'{' inside a placeholder's format spec", i + 1);
  return [{ kind: "placeholder", expr: strip(expr), spec: spec || null, offset: start + 1 }, close + 1];
}

/**
 * `template` cut into one template per placeholder, in order, whose
 * concatenation is the whole: the first keeps the literal text before it,
 * and each keeps the literal text (and `{unit}`) after it.
 */
export function segments(template: Template): Template[] {
  const out: Piece[][] = [];
  let lead: Piece[] = [];
  for (const piece of template.pieces) {
    if (piece.kind === "placeholder") {
      out.push(out.length === 0 ? [...lead, piece] : [piece]);
      lead = [];
    } else if (out.length > 0) {
      out[out.length - 1]!.push(piece);
    } else {
      lead.push(piece);
    }
  }
  if (out.length === 0) return [template];
  return out.map((pieces) => new Template(pieces));
}

/**
 * `[expression, format]`: the compiler's internal `value:` and `format:`
 * for a one-placeholder template; `format` is `null` when the template is
 * its placeholder alone with no spec. A template with no placeholder is
 * `[null, null]`.
 */
export function toValueFormat(template: Template): [string | null, string | null] {
  const placeholder = template.placeholder;
  if (placeholder === null) return [null, null];
  if (template.pieces.length === 1 && placeholder.spec === null) return [placeholder.expr, null];
  const fmt = template.pieces.map((piece) => {
    if (piece.kind === "literal") return piece.text;
    if (piece.kind === "unit") return "{unit}";
    return piece.spec ? `{:${piece.spec}}` : "{}";
  }).join("");
  const fields = [...fmt.matchAll(V1_FIELD)].length;
  const expected = template.pieces.filter((p) => p.kind !== "literal").length;
  if (fields !== expected) {
    throw new TemplateError("literal braces next to the placeholder that the compiler would read as a second field", 0);
  }
  return [placeholder.expr, fmt];
}

/** One placeholder of a `text:` template, as the builder compiles it. */
export interface Reading {
  /** The expression, with a ternary's template parentheses dropped. */
  expr: string;
  /** Its format string, or `null` for the first reading when that is its placeholder alone with no spec. */
  format: string | null;
  /** Where `expr` starts in the template, for a caret inside it. */
  offset: number;
  /** The placeholder's expression as written, which a diagnostic quotes. */
  quote: string;
}

/** `[literal, readings]`: a template with no placeholder is its literal text; otherwise one `Reading` per placeholder. */
export function readings(raw: string): [string | null, Reading[]] {
  const template = parseTemplate(raw);
  if (template.placeholder === null) return [template.literal, []];
  const out: Reading[] = [];
  for (const segment of segments(template)) {
    const placeholder = segment.placeholder!;
    let [expr, fmt] = toValueFormat(segment);
    const [stripped, dropped] = stripTemplateParens(expr!);
    const offset = placeholder.offset + leadingSpace(raw, placeholder.offset) + dropped;
    if (out.length > 0 && fmt === null) fmt = "{}";
    out.push({ expr: stripped, format: fmt, offset, quote: placeholder.expr });
  }
  return [null, out];
}

/** An `aod: {text:}` restyle's format string: the template with its placeholder's expression set aside. */
export function aodFormat(raw: string): string {
  const template = parseTemplate(raw);
  const stripped = new Template(template.pieces.map((p) => (p.kind === "placeholder" ? { ...p, expr: "x" } : p)));
  const [, fmt] = toValueFormat(stripped);
  return fmt ?? "{}";
}

/** A ternary's template parentheses dropped: the expression, and how many characters went from its front. */
export function stripTemplateParens(expr: string): [string, number] {
  const text = strip(expr);
  if (!(text.startsWith("(") && text.endsWith(")"))) return [expr, 0];
  const chars = Array.from(text);
  let depth = 0;
  for (let index = 0; index < chars.length; index++) {
    if (chars[index] === "(") depth++;
    else if (chars[index] === ")") {
      depth--;
      if (depth === 0 && index !== chars.length - 1) return [expr, 0]; // "(a) + (b)"
    }
  }
  const inner = chars.slice(1, -1).join("");
  if (!topLevelColon(inner)) return [expr, 0];
  return [inner, 1];
}

function topLevelColon(expr: string): boolean {
  let tokens;
  try {
    tokens = tokenize(expr);
  } catch (error) {
    if (error instanceof ExprError) return false;
    throw error;
  }
  let depth = 0;
  for (const token of tokens) {
    if (token.text === "(") depth++;
    else if (token.text === ")") depth--;
    else if (token.kind === "op" && token.text === ":" && depth === 0) return true;
  }
  return false;
}

/** How many spaces open the placeholder expression at code-point `offset`. */
export function leadingSpace(raw: string, offset: number): number {
  const rest = Array.from(raw).slice(offset).join("");
  return Array.from(rest).length - Array.from(rest.replace(/^\s+/u, "")).length;
}
