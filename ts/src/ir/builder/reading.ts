// Reading one key of a node: expressions, colours, lengths, angles,
// positions, sizes, alignment and font references, each reporting its own
// error on the author's line.
import * as catalog from "../../catalog.ts";
import { Span } from "../../diagnostics.ts";
import type { Data } from "../../edit/yaml.ts";
import * as expr from "../../expr.ts";
import { Color, ColorError } from "../../palette.ts";
import { quoted, str } from "../../py.ts";
import * as template from "../../template.ts";
import * as units from "../../units.ts";
import { Angle, Length, UnitError } from "../../units.ts";
import { Origin } from "../../yamlsrc.ts";
import { type DataElement, Expression, Position, Size, SYSTEM_FONTS, type Text } from "../model.ts";
import { BuilderState, type Node } from "./state.ts";

/** Matches `expr.check`'s "unknown data source" message for an unbound `color.<name>`. */
const COLOR_RE = /^unknown data source 'color\.([A-Za-z_][A-Za-z0-9_]*)'$/;

/** Shift a span to point inside the expression string, not just at its key. */
function offsetSpan(span: Span | null, offset: number): Span | null {
  return span === null ? null : new Span(span.path, span.line, span.col + offset);
}

/** What `absent:` splits into. */
export interface Absence {
  absent: string | null;
  placeholder: string | null;
  fallback: Expression | null;
}

/** Coercion helpers: a key of a node in, a typed value (or `null`, after reporting why) out. */
export class Readers extends BuilderState {
  /** `align:` as `[horizontal, vertical]`, each defaulting to `"center"`. */
  alignment(node: Node): [string, string] {
    const value = str(node.get("align") ?? "center");
    const vertical = (["top", "bottom"] as const).find((v) => value === v || value.startsWith(v + "_"));
    if (vertical === undefined) return [value, "center"];
    return [value.slice(vertical.length + 1) || "center", vertical];
  }

  /** `absent:` as the IR's three fields. */
  absence(node: Node): Absence {
    const value = node.get("absent");
    if (value === undefined || value === null || value === "hide") {
      return { absent: (value ?? null) as string | null, placeholder: null, fallback: null };
    }
    if (value instanceof Map) return { absent: "fallback", placeholder: null, fallback: this.expression(value, "value") };
    return { absent: "placeholder", placeholder: str(value), fallback: null };
  }

  /** Where `absent: {value: ...}`'s expression is written. */
  fallbackSpan(node: Node): Span | null {
    const absent = node.get("absent");
    return (absent instanceof Map ? this.doc.span(absent, "value") : null) ?? this.doc.span(node, "absent");
  }

  /** `node[key]`'s template as `[literal, readings]`; `[null, []]` when unwritten or malformed. */
  textReadings(node: Node, key = "text"): [string | null, template.Reading[]] {
    const raw = node.get(key);
    if (typeof raw !== "string") return [null, []];
    try {
      return template.readings(raw);
    } catch (error) {
      if (error instanceof template.TemplateError) return [null, []];
      throw error;
    }
  }

  /** One reading of `node[key]`'s template compiled; `text`, when given, is compiled instead. */
  readingExpression(node: Node, reading: template.Reading, key = "text", text: string | null = null): Expression | null {
    const origin = text === null ? new Origin(key, str(node.get(key)), [[0, reading.offset]], reading.quote) : null;
    return this.compileExpression(text ?? reading.expr, this.doc.span(node, key), key, origin);
  }

  /** Report `message` as an `element` error on `node[key]`'s line, or the node's own. */
  require(node: Node, key: string, message: string): void {
    this.bag.error("element", message, this.doc.span(node, key) ?? this.doc.span(node));
  }

  // -- coercion helpers -----------------------------------------------------

  /** `node[key]` parsed, type-checked and compiled, or `null` when absent or reported. */
  expression(node: Node, key: string): Expression | null {
    const raw = node.get(key);
    if (raw === undefined || raw === null) return null;
    return this.compileExpression(str(raw), this.doc.span(node, key), key, this.doc.origin(node, key) ?? null);
  }

  /** `text` compiled as `expression` does for an authored key, reported against `span` under `key`. */
  compileExpression(text: string, span: Span | null, key: string, origin: Origin | null = null): Expression | null {
    const before = new Set(this.scope.used);
    this.scope.used.clear();
    let value: expr.Value, folded: expr.Node, code: string, resolved: expr.Node;
    try {
      const nodeAst = expr.parse(text);
      value = expr.check(nodeAst, this.scope);
      // Emit from a fold that keeps palette names; the build-time constant comes from one that resolves them.
      folded = expr.fold(nodeAst, this.scope, false);
      code = expr.emit(folded, this.scope);
      resolved = expr.fold(nodeAst, this.scope);
    } catch (error) {
      if (!(error instanceof expr.ExprError)) throw error;
      let message = error.message, notes = error.notes, errorCode = error.code ?? "expression";
      // An unbound `color.<name>` that reaches here is a scheme role no style picks.
      const match = COLOR_RE.exec(message);
      const declared = new Set([...this.color_scheme.values()].flatMap((scheme) => [...scheme.colors.keys()]));
      if (match !== null && declared.has(match[1]!)) {
        errorCode = "config";
        message = `color.${match[1]} is a role of 'theme: schemes:', but no 'config: style:' entry picks a scheme`;
        notes = ["add a 'config: style:' entry with 'scheme:', or make it a palette colour"];
      }
      let offset = origin === null ? error.offset : origin.authorOffset(error.offset);
      if (this.quotedAt(span)) offset += 1; // the offset is into the value, after its opening quote
      this.bag.error(errorCode, `${origin !== null ? origin.key : key}: ${message}`, offsetSpan(span, offset), { notes });
      for (const path of before) this.scope.used.add(path);
      return null;
    }
    const used = [...this.scope.used].filter((p) => catalog.CATALOG.has(p));
    for (const path of before) this.scope.used.add(path);
    const barrel = new Set<string>(), modules = new Set<string>();
    for (const c of expr.walk(folded)) {
      if (c.kind !== "call") continue;
      if (expr.CALL_BARREL.has(c.name)) barrel.add(c.name);
      const module = expr.CALL_MODULES.get(c.name);
      if (module !== undefined) modules.add(module);
    }
    const constant = resolved.kind === "literal" ? resolved.value : null;
    let author: string | null = null;
    if (origin !== null && origin.text !== null) author = origin.quote ?? origin.text;
    return Expression.create({
      text, code, value, sources: used.sort(), barrel, modules, span, constant, ast: folded, author,
    });
  }

  /** Does a quoted scalar open at `span`? */
  private quotedAt(span: Span | null): boolean {
    if (span === null || span.path !== this.doc.path) return false;
    const lines = this.doc.text.split("\n");
    if (!(0 < span.line && span.line <= lines.length)) return false;
    const line = Array.from(lines[span.line - 1]!);
    return 0 < span.col && span.col <= line.length && (line[span.col - 1] === "'" || line[span.col - 1] === "\"");
  }

  /** `node[key]` as a colour expression: a bare `#RRGGBB` literal (with a `raw-color` note) or any colour-typed expression. */
  colorExpression(node: Node, key: string): Expression | null {
    const raw = node.get(key);
    if (raw === undefined || raw === null) return null;
    const span = this.doc.span(node, key);
    const text = str(raw);
    if (text.startsWith("#")) {
      let color: Color;
      try {
        color = Color.parse(text, key);
      } catch (error) {
        if (!(error instanceof ColorError)) throw error;
        this.bag.error("color", error.message, span);
        return null;
      }
      this.bag.note("raw-color", `${this.doc.authorKey(node, key)}: ${text} is a literal colour -- prefer a named palette swatch`,
        span, { notes: ["palette entries keep a design's colours consistent and lintable"] });
      return Expression.create({
        text, code: color.asMonkeyc(), value: new expr.Value("color"), sources: [], barrel: new Set(), modules: new Set(),
        span, constant: color.value, ast: expr.literal(color.value, "color"),
      });
    }
    const bound = this.expression(node, key);
    if (bound !== null && bound.value.type !== "color") {
      this.bag.error("type", `${this.doc.authorKey(node, key)} must be a colour, got ${bound.value}`, span, {
        notes: ["known palette swatches: " + ([...this.palette.keys()].sort().map((n) => `color.${n}`).join(", ") || "(none)")],
      });
      return null;
    }
    return bound;
  }

  /** Resolve a `font:` name to `[reference, isCustom]`, or `null` (reported, unless declared and then rejected). */
  fontReference(name: string, span: Span | null): [string, boolean] | null {
    if (!name.startsWith("font.")) {
      if ((SYSTEM_FONTS as readonly string[]).includes(name)) return [name, false];
      this.bag.error("font", `unknown font ${quoted(name)}`, span,
        { notes: ["use 'font.<name>' for a custom font, or a system font: " + SYSTEM_FONTS.join(", ")] });
      return null;
    }
    const key = name.slice("font.".length);
    const spec = this.fonts.resolve(this.bag, key, span,
      { code: "font", message: `unknown font ${quoted(name)}`, note: "declared fonts", prefix: "font." });
    return spec !== null ? [key, true] : null;
  }

  /** Set `font`/`font_is_custom` from `node.font`; false only when an explicit `font:` failed to resolve. */
  resolveFont(node: Node, element: Text | DataElement): boolean {
    const raw = node.get("font");
    if (raw === undefined || raw === null) return true;
    const resolved = this.fontReference(str(raw), this.doc.span(node, "font"));
    if (resolved !== null) {
      [element.font, element.font_is_custom] = resolved;
      return true;
    }
    return false;
  }

  /** An `at:`-style position from `raw` (`node[key]`); the default centre when absent or reported. */
  position(raw: Data | undefined, node: Node, key: string, { allowSubscreen = false } = {}): Position {
    if (!(raw instanceof Map)) return new Position();
    const span = this.doc.span(node, key);
    if (raw.get("anchor") === "subscreen" && !allowSubscreen) {
      this.bag.error("subscreen", `'anchor: subscreen' is not accepted in '${key}:' here`,
        this.doc.span(raw, "anchor") ?? span, {
          notes: ["it is accepted only on a top-level element's own 'at:'; that "
            + "element's other positions ('to:', 'points:', a group's children) "
            + "are then already laid out inside the subscreen window"],
        });
      return new Position();
    }
    try {
      return Position.create({
        anchor: (raw.get("anchor") ?? "center") as string,
        dx: raw.has("dx") ? Length.parse(raw.get("dx"), "dx") : null,
        dy: raw.has("dy") ? Length.parse(raw.get("dy"), "dy") : null,
        angle: raw.has("angle") ? Angle.parse(raw.get("angle"), "angle") : null,
        radius: raw.has("radius") ? Length.parse(raw.get("radius"), "radius") : null,
      });
    } catch (error) {
      if (!(error instanceof UnitError)) throw error;
      this.bag.error("units", error.message, span);
      return new Position();
    }
  }

  /** A `size: {width, height}`; empty when absent or reported. */
  size(raw: Data | undefined): Size {
    if (!(raw instanceof Map)) return new Size();
    try {
      return Size.create({
        width: raw.has("width") ? Length.parse(raw.get("width"), "width") : null,
        height: raw.has("height") ? Length.parse(raw.get("height"), "height") : null,
      });
    } catch (error) {
      if (!(error instanceof UnitError)) throw error;
      this.bag.error("units", error.message, this.doc.span(raw));
      return new Size();
    }
  }

  length(node: Node, key: string): Length | null {
    if (!node.has(key)) return null;
    try {
      return Length.parse(node.get(key), key);
    } catch (error) {
      if (!(error instanceof UnitError)) throw error;
      this.bag.error("units", error.message, this.doc.span(node, key));
      return null;
    }
  }

  /** `key`'s length, rejected unless it is `px`/`%r`: a size baked before layout runs. */
  bakedSizeLength(node: Node, key: string, { code, label, note }: { code: string; label: string; note: string }): Length | null {
    const length = this.length(node, key);
    if (length !== null && !(units.SIZE_UNITS as readonly string[]).includes(length.unit)) {
      this.bag.error(code, `${label} must be px or %r, not ${length.unit}`, this.doc.span(node, key), { notes: [note] });
      return null;
    }
    return length;
  }

  angle(node: Node, key: string): Angle | null {
    if (!node.has(key)) return null;
    try {
      return Angle.parse(node.get(key), key);
    } catch (error) {
      if (!(error instanceof UnitError)) throw error;
      this.bag.error("units", error.message, this.doc.span(node, key));
      return null;
    }
  }
}
