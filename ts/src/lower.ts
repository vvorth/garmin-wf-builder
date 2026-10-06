// Check what the schema cannot in a format 2 document, before the builder.
//
//
// The builder reads the author's keys as written; this pass, between the
// schema and `desugar`, checks the format 2 semantics a JSON Schema cannot
// express:
//
// - every `color.<name>`: unknown, a name that is both a swatch and a role,
//   a role where a build-time colour is needed, a format 1 spelling;
// - every `text:` template: it parses, a ternary inside a placeholder is
//   parenthesised, `{unit}` has a reading to label, several placeholders
//   only where several are drawn, and an `aod: {text:}` restyle reads the
//   element's own expression;
// - every drawn text (a template, an `absent:` placeholder) is one line.
//
// It changes one thing: a compass alias (`align: NE`, `anchor: SW`) is
// spelled out. And it records, for a nested key the builder compiles
// (`outline.color`, `absent.value`), the dotted name a diagnostic gives it
// (`Origin`).
import { compareStrings, getCloseMatches } from "./difflib.ts";
import type { Bag, Span } from "./diagnostics.ts";
import type { Data, DataKey } from "./edit/yaml.ts";
import { ExprError, tokenize, type Token } from "./expr.ts";
import { controlCharacter } from "./mcsource.ts";
import { repr } from "./py.ts";
import {
  aodFormat, parseTemplate, type Placeholder, segments, stripTemplateParens, type Template, TemplateError, toValueFormat,
} from "./template.ts";
import { Origin, type SpanOf, type YamlDocument } from "./yamlsrc.ts";

type Dict = Map<DataKey, Data>;
const isDict = (x: unknown): x is Dict => x instanceof Map;

/** A compass alias, and the anchor name it stands for (`align:` and `anchor:`). */
export const COMPASS: ReadonlyMap<string, string> = new Map([
  ["N", "top"], ["NE", "top_right"], ["E", "right"], ["SE", "bottom_right"],
  ["S", "bottom"], ["SW", "bottom_left"], ["W", "left"], ["NW", "top_left"],
]);

class Lowering {
  readonly doc: YamlDocument;
  readonly bag: Bag;
  swatches = new Set<string>();
  roles = new Set<string>();
  ok = true;
  /** One YAML node aliased under two keys is lowered once; `desugar` reports the alias itself. */
  private readonly lowered = new Set<object>();

  constructor(doc: YamlDocument, bag: Bag) {
    this.doc = doc;
    this.bag = bag;
  }

  names(): string[] {
    return [...new Set([...this.swatches, ...this.roles])].sort(compareStrings);
  }

  span(node: unknown, key?: DataKey, of: SpanOf = "value"): Span | null {
    return this.doc.span(node, key, of);
  }

  error(code: string, message: string, span: Span | null, ...notes: string[]): void {
    this.bag.error(code, message, span, { notes });
    this.ok = false;
  }

  // -- colours -------------------------------------------------------------------

  gatherColors(data: Dict): void {
    const resources = data.get("resources");
    const palette = isDict(resources) ? resources.get("palette") : undefined;
    if (isDict(palette)) this.swatches = new Set([...palette.keys()].map(String));
    const declared = new Map<string, [object, DataKey]>(); // role -> (node, key) that declared it
    const theme = data.get("theme");
    const schemes = isDict(theme) ? theme.get("schemes") : undefined;
    if (isDict(schemes)) {
      for (const scheme of schemes.values()) {
        const colors = isDict(scheme) ? scheme.get("colors") : undefined;
        if (isDict(colors)) {
          for (const role of colors.keys()) {
            if (!declared.has(role as string)) declared.set(role as string, [colors, role]);
            this.roles.add(role as string);
          }
        }
      }
    }
    const config = data.get("config");
    if (isDict(config)) {
      for (const [axis, fallback] of [["accent_color", "accent"], ["data_color", "data"]] as const) {
        const body = config.get(axis);
        if (!isDict(body)) continue;
        const role = (body.has("role") ? body.get("role") : fallback) as string;
        const where: [object, DataKey] = body.has("role") ? [body, "role"] : [config, axis];
        const seen = declared.get(role);
        if (seen !== undefined && seen[0] !== config) {
          this.error("color", `the role ${repr(role)} is both a 'theme:' scheme role and the role 'config: ${axis}:' binds`,
            this.span(where[0], where[1], "key"),
            `'color.${role}' would mean two different colours`,
            "rename the scheme role, or give the axis another with 'role:'");
          continue;
        }
        declared.set(role, where);
        this.roles.add(role);
      }
    }
    for (const name of [...this.swatches].filter((n) => this.roles.has(n)).sort(compareStrings)) {
      const [node, key] = declared.get(name)!;
      for (const span of [this.span(palette, name, "key"), this.span(node, key, "key")]) {
        this.error("color", `'color.${name}' is both a palette swatch and a colour role`, span,
          "format 2 has one colour namespace: a role is looked up first, then a swatch, and a name that is both is refused rather than shadowed",
          "rename the palette swatch or the role");
      }
    }
  }

  unknownColor(name: string, span: Span | null): void {
    const names = this.names();
    const near = getCloseMatches(name, names, 3, 0.5);
    const note = near.length > 0 ? `did you mean ${near.map((n) => `color.${n}`).join(", ")}?`
      : names.length > 0 ? `declared colours: ${names.map((n) => `color.${n}`).join(", ")}`
        : "declare it under 'resources: palette:', or as a 'theme: schemes:' role";
    this.error("color", `unknown colour 'color.${name}'`, span, note);
  }

  /**
   * Whether every `color.<name>` in `node[key]` (or `text`) names a declared
   * colour (a palette swatch where `swatchOnly`) and no format 1 colour
   * reference is left; each mistake reported.
   */
  checkRefs(node: Dict | Data[], key: DataKey, { author = null, swatchOnly = false, text = null }:
    { author?: string | null; swatchOnly?: boolean; text?: string | null } = {}): boolean {
    const raw = text === null ? itemOf(node, key) : text;
    if (typeof raw !== "string") return true;
    let tokens: Token[];
    try {
      tokens = tokenize(raw);
    } catch (error) {
      if (error instanceof ExprError) return true; // the builder reports the syntax error
      throw error;
    }
    let ok = true;
    for (const token of tokens) {
      if (token.kind !== "name") continue;
      const v1 = format1Ref(token.text);
      if (v1 !== null) {
        this.error("color", `${repr(token.text)} is format 1's spelling of a colour`, this.span(node, key), `format 2 writes ${repr(v1)}`);
        ok = false;
        continue;
      }
      if (!token.text.startsWith("color.")) continue;
      const parts = token.text.split(".");
      if (parts.length !== 2) continue;
      const name = parts[1]!;
      const span = this.span(node, key);
      if (!this.swatches.has(name) && !this.roles.has(name)) {
        this.unknownColor(name, span);
        ok = false;
        continue;
      }
      if (swatchOnly && !this.swatches.has(name)) {
        this.error("color", `'color.${name}' is a colour role, but ${repr(author ?? key)} needs a build-time colour`, span,
          "a role follows the active style's scheme or the wearer's pick, so it has no single value when the face is built",
          "name a palette swatch, or write the colour as '#RRGGBB'");
        ok = false;
      }
    }
    return ok;
  }

  /** Check the colour references in `node[key]`, and record the key's author name for the builder's diagnostics. */
  exprKey(node: Dict, key: string, author: string | null = null): void {
    if (!node.has(key) || typeof node.get(key) !== "string") return;
    if (this.checkRefs(node, key, { author })) this.doc.setOrigin(node, key, new Origin(author ?? key, node.get(key) as string));
  }

  /** A colour that must be a build-time literal: a hex literal, or a `color.<swatch>`. */
  swatch(node: Dict | Data[], key: DataKey, author: string): void {
    const value = itemOf(node, key);
    if (typeof value === "string" && value.startsWith("color.")) this.checkRefs(node, key, { author, swatchOnly: true });
  }

  // -- the document ----------------------------------------------------------------

  document(data: Dict): void {
    this.gatherColors(data);
    if (!this.ok) return;
    this.topLevel(data);
    for (const holder of this.scopes(data)) {
      for (const block of ["static", "elements"]) {
        const mapping = holder.get(block);
        if (isDict(mapping)) for (const body of mapping.values()) if (isDict(body)) this.element(body);
      }
    }
  }

  *scopes(data: Dict): Generator<Dict> {
    yield data;
    const layouts = data.get("layouts");
    if (isDict(layouts)) for (const body of layouts.values()) if (isDict(body)) yield body;
  }

  topLevel(data: Dict): void {
    const resources = data.get("resources");
    if (isDict(resources)) {
      const handSets = resources.get("hand_sets");
      if (isDict(handSets)) {
        for (const handSet of handSets.values()) {
          if (!isDict(handSet)) continue;
          for (const hand of handSet.values()) {
            if (isDict(hand)) {
              this.exprKey(hand, "color");
              this.parts(hand.get("parts"));
            }
          }
        }
      }
    }
    const theme = data.get("theme");
    if (isDict(theme)) {
      const schemes = theme.get("schemes");
      if (isDict(schemes)) {
        for (const scheme of schemes.values()) {
          const colors = isDict(scheme) ? scheme.get("colors") : undefined;
          if (isDict(colors)) for (const role of [...colors.keys()]) this.swatch(colors, role, `theme.schemes: ${String(role)}`);
        }
      }
    }
    const config = data.get("config");
    if (isDict(config)) this.config(config);
  }

  config(config: Dict): void {
    for (const axis of ["accent_color", "data_color"]) {
      const body = config.get(axis);
      if (!isDict(body)) continue;
      if (body.has("default")) this.swatch(body, "default", `config.${axis}.default`);
      const choices = body.get("choices");
      if (Array.isArray(choices)) {
        choices.forEach((choice, index) => {
          if (typeof choice === "string") this.swatch(choices, index, `config.${axis}.choices`);
        });
      }
    }
  }

  // -- elements ----------------------------------------------------------------------

  element(node: Dict): void {
    if (this.lowered.has(node)) return;
    this.lowered.add(node);
    const kind = node.get("type");
    this.common(node);
    if (kind === "text") this.text(node, true);
    else if (kind === "gauge") {
      this.exprKey(node, "value");
      this.exprKey(node, "max");
      const bands = node.get("bands");
      if (Array.isArray(bands)) for (const band of bands) if (isDict(band)) this.exprKey(band, "color");
      this.parts(node.get("needle"));
    } else if (kind === "icon") {
      const icon = node.get("icon");
      if (isDict(icon)) this.exprKey(icon, "for", "icon.for");
    } else if (kind === "data") {
      const icon = node.get("icon");
      if (isDict(icon)) this.exprKey(icon, "color", "icon.color");
    } else if (kind === "pattern") {
      this.parts(node.get("parts"), true);
    } else if (kind === "graph") {
      this.exprKey(node, "min");
      this.exprKey(node, "max");
    } else if (kind === "group") {
      const children = node.get("children");
      if (isDict(children)) for (const child of children.values()) if (isDict(child)) this.element(child);
    }
    this.absent(node);
    this.aod(node);
  }

  common(node: Dict): void {
    this.align(node);
    for (const key of ["color", "track_color", "visible"]) this.exprKey(node, key);
    if (node.has("outline")) this.outline(node);
    for (const key of ["at", "to"]) anchor(node.get(key));
    const overrides = node.get("overrides");
    if (isDict(overrides)) {
      for (const patch of overrides.values()) {
        if (isDict(patch)) {
          this.align(patch);
          anchor(patch.get("at"));
        }
      }
    }
    const points = node.get("points");
    if (Array.isArray(points)) for (const point of points) anchor(point);
  }

  align(node: Dict): void {
    const value = node.get("align");
    if (typeof value === "string" && COMPASS.has(value)) node.set("align", COMPASS.get(value)!);
  }

  outline(node: Dict): void {
    const outline = node.get("outline");
    if (isDict(outline)) this.exprKey(outline, "color", "outline.color");
    else if (outline !== "none") this.exprKey(node, "outline");
  }

  /** Check a `text:` template; with `several`, a template with more than one placeholder is accepted. */
  text(node: Dict, several = false): void {
    if (typeof node.get("text") !== "string") return;
    const template = this.template(node, "text", { several });
    if (template === null || template.placeholder === null) return;
    for (const segment of segments(template)) {
      let expr: string | null;
      try {
        [expr] = toValueFormat(segment);
      } catch (error) {
        if (error instanceof TemplateError) {
          this.error("format", `text: ${error.message}`, this.span(node, "text"));
          return;
        }
        throw error;
      }
      if (!this.checkRefs(node, "text", { text: stripTemplateParens(expr!)[0] })) return;
    }
  }

  template(node: Dict, key: string, { aod = false, several = false }: { aod?: boolean; several?: boolean } = {}): Template | null {
    const raw = node.get(key) as string;
    if (!this.oneLine(node, key)) return null;
    let template: Template;
    try {
      template = parseTemplate(raw);
    } catch (error) {
      if (error instanceof TemplateError) {
        this.error("format", `${key}: ${error.message}`, this.span(node, key),
          "'{{' and '}}' are a literal brace; a placeholder is '{expr}' or '{expr:spec}'");
        return null;
      }
      throw error;
    }
    const placeholders = template.placeholders;
    if (placeholders.length > 1 && !several) {
      this.error("format", `${key}: only a 'text' element's own 'text:' takes several placeholders; this one reads one`,
        this.span(node, key),
        "a pattern's text part, and an element's 'aod: {text:}', draw a single reading",
        "docs/limitations.md, \"Not implemented yet\"");
      return null;
    }
    const hasUnit = template.pieces.some((p) => p.kind === "unit");
    if (placeholders.length > 1 && hasUnit) {
      this.error("format", `${key}: '{unit}' labels the reading of a 'units:' conversion, and this text has several readings`,
        this.span(node, key), "'units:' converts a text with one placeholder");
      return null;
    }
    if (template.placeholder === null && hasUnit) {
      this.error("format", `${key}: '{unit}' needs a placeholder to be the unit of`, this.span(node, key));
      return null;
    }
    if (!aod && placeholders.some((p) => !p.expr)) {
      this.error("format", `${key}: the placeholder has no expression`, this.span(node, key),
        "write the reading inside the braces: \"{time.hour:02d}\"");
      return null;
    }
    if (placeholders.some(openTernary)) {
      this.error("format", `${key}: a ternary inside a placeholder must be parenthesised`, this.span(node, key),
        "the expression ends at the first ':' outside parentheses, so \"{a ? b : c}\" reads as the expression 'a ? b' with the format spec ' c'",
        "write \"{(a ? b : c)}\"");
      return null;
    }
    return template;
  }

  /** Whether the drawn text at `key` holds no control character: a text is measured and drawn as one line. */
  oneLine(node: Dict, key: string, author: string | null = null): boolean {
    const raw = node.get(key);
    const bad = typeof raw === "string" ? controlCharacter(raw) : null;
    if (bad === null) return true;
    this.error("format", `${author ?? key}: a text is drawn on one line, so it cannot hold a line break or a tab (found '${bad}')`,
      this.span(node, key), "draw each line as its own element");
    return false;
  }

  absent(node: Dict): void {
    const value = node.get("absent");
    if (typeof value === "string") this.oneLine(node, "absent");
    if (isDict(value)) this.exprKey(value, "value", "absent.value");
  }

  aod(node: Dict): void {
    const aod = node.get("aod");
    if (!isDict(aod)) return;
    for (const key of ["color", "track_color", "visible"]) this.exprKey(aod, key, `aod.${key}`);
    if (aod.has("outline")) this.outline(aod);
    const icon = aod.get("icon");
    if (isDict(icon)) this.exprKey(icon, "color", "aod.icon.color");
    if (typeof aod.get("text") === "string") this.aodText(node, aod);
  }

  aodText(node: Dict, aod: Dict): void {
    const own = node.get("type") === "text" ? node.get("text") : undefined;
    const ownTemplate = typeof own === "string" ? templateOf(own) : null;
    if (ownTemplate !== null && ownTemplate.placeholders.length > 1) {
      this.error("format", "aod.text: restyling a text with several placeholders is not implemented yet", this.span(aod, "text"),
        "the always-on frame draws the same template; its other 'aod:' overrides (colour, font, outline) still apply",
        "docs/limitations.md, \"Not implemented yet\"");
      return;
    }
    const template = this.template(aod, "text", { aod: true });
    if (template === null) return;
    const placeholder = template.placeholder;
    if (placeholder !== null && placeholder.expr) {
      const parsed = ownTemplate !== null ? ownTemplate.placeholder : null;
      const expected = parsed !== null ? parsed.expr : null;
      if (expected === null || normalise(placeholder.expr) !== normalise(expected)) {
        this.error("format", "aod.text: the placeholder must read the element's own expression" + (expected ? ` (${expected})` : ""),
          this.span(aod, "text"),
          "the always-on frame may restyle the reading -- its literal text and format spec -- but not change what is read",
          "write the same expression, or leave the braces empty: \"{:%H %M}\"");
        return;
      }
    }
    if (placeholder === null) {
      this.error("format", "aod.text: needs the element's placeholder", this.span(aod, "text"),
        "the always-on frame restyles the reading; it cannot replace it with fixed text");
      return;
    }
    try {
      aodFormat(String(aod.get("text")));
    } catch (error) {
      if (error instanceof TemplateError) this.error("format", `aod.text: ${error.message}`, this.span(aod, "text"));
      else throw error;
    }
  }

  parts(parts: unknown, pattern = false): void {
    if (!Array.isArray(parts)) return;
    for (const part of parts) {
      if (!isDict(part)) continue;
      this.align(part);
      for (const key of ["color", "visible"]) this.exprKey(part, key);
      if (part.has("outline")) this.outline(part);
      if (pattern && part.get("type") === "text") this.text(part);
    }
  }
}

function itemOf(node: Dict | Data[], key: DataKey): Data | undefined {
  return node instanceof Map ? node.get(key) : node[key as number];
}

/** Rewrite the format 2 `doc` into the internal shape in place. `false` (with diagnostics) when it cannot be. */
export function lower(doc: YamlDocument, bag: Bag): boolean {
  doc.format = 2;
  const lowering = new Lowering(doc, bag);
  if (isDict(doc.data)) lowering.document(doc.data);
  return lowering.ok;
}

/** The format 2 spelling of a format 1 colour reference (any name under `palette.` or `config.`), or `null`. */
function format1Ref(name: string): string | null {
  const parts = name.split(".");
  if (parts[0] === "palette") return parts.length === 2 ? `color.${parts[1]}` : "color.<name>";
  if (parts[0] !== "config") return null;
  if (parts.length === 3 && parts[1] === "colors") return `color.${parts[2]}`;
  if (name === "config.accent_color") return "color.accent";
  if (name === "config.data_color") return "color.data";
  return "color.<role>";
}

function anchor(position: unknown): void {
  if (!isDict(position)) return;
  const value = position.get("anchor");
  if (typeof value === "string" && COMPASS.has(value)) position.set("anchor", COMPASS.get(value)!);
}

/** `{a ? b : c}`: the expression stopped at a ternary's `:`. */
function openTernary(placeholder: Placeholder): boolean {
  if (placeholder.spec === null) return false;
  let tokens: Token[];
  try {
    tokens = tokenize(placeholder.expr);
  } catch (error) {
    if (error instanceof ExprError) return false;
    throw error;
  }
  let depth = 0;
  for (const token of tokens) {
    if (token.text === "(") depth++;
    else if (token.text === ")") depth--;
    else if (token.kind === "op" && token.text === "?" && depth === 0) return true;
  }
  return false;
}

function templateOf(raw: string): Template | null {
  try {
    return parseTemplate(raw);
  } catch (error) {
    if (error instanceof TemplateError) return null;
    throw error;
  }
}

function normalise(expr: string): string {
  try {
    return tokenize(expr).map((t) => t.text).join(" ");
  } catch (error) {
    if (error instanceof ExprError) return expr.trim();
    throw error;
  }
}
