// `type: text`: a bound or literal string, optionally curved onto a
// `face:` (vector) font. Port of wfb/kinds/text.py's build half.
import * as catalog from "../catalog.ts";
import * as conversion from "../conversion.ts";
import type { Data, DataKey } from "../edit/yaml.ts";
import * as formatting from "../formatting.ts";
import type { Builder } from "../ir/builder/index.ts";
import { type Element, type Expression, Text, TextSegment } from "../ir/model.ts";
import { repr, str } from "../py.ts";
import type { Reading } from "../template.ts";
import { type Common, ElementKind, type Refusal, register } from "./base.ts";

type Node = Map<DataKey, Data>;

/** `antialias:` on a `text` element: a per-element key on a shared font resource. */
function rejectTextAntialias(b: Builder, node: Node, element: Text): void {
  const span = b.doc.span(node, "antialias");
  const notes = element.font_is_custom
    ? [`put it on 'fonts: ${element.font}: antialias:' instead -- the font this element references`]
    : [`this element uses the system font ${repr(element.font)}, which `
      + "has no 'antialias:' of its own to set -- only a custom 'fonts:' entry does"];
  b.bag.error("text-antialias", `${element.id}: 'antialias:' is not accepted on a 'text' element`, span, { notes });
}

type Units = [Expression, string, Expression, string[], number];

/** `units:`: the bound value rewritten to display in the wearer's units, or `null` once reported. */
function applyUnits(b: Builder, node: Node, value: Expression | null, reading: Reading | null): Units | null {
  const system = str(node.get("units"));
  const elementId = str(node.get("id") ?? "?");
  const span = b.doc.span(node, "units");
  if (value === null || reading === null) {
    if (reading === null) {
      b.bag.error("units", `${elementId}: 'units:' converts the reading in a placeholder, and this text is fixed`, span);
    }
    return null;
  }
  const raw = reading.expr.trim();
  const source = catalog.CATALOG.get(raw);
  const found = conversion.conversionFor(source);
  if (found === null) {
    const convertible = [...catalog.CATALOG].filter(([, s]) => conversion.conversionFor(s) !== null).map(([path]) => path).sort();
    const what = source !== undefined && source.unit
      ? `${repr(raw)} is in ${source.unit}, which 'units:' does not convert`
      : `${repr(raw)} is not a single source with a unit 'units:' converts`;
    b.bag.error("units", `${elementId}: ${what}`, b.doc.span(node, "text"), {
      notes: ["'units:' converts a placeholder that is exactly one of: " + convertible.join(", "),
        "write the bare source; the conversion replaces any "
        + "hand-written scaling such as 'activity.distance / 100000.0'"],
    });
    return null;
  }
  const converted = b.readingExpression(node, reading, "text", conversion.convertedText(raw, found, system));
  const label = b.compileExpression(conversion.labelText(found, system), span, "units");
  if (converted === null || label === null) return null;
  return [converted, system, label, conversion.labels(found, system), found.digits];
}

/** A duration `format:` reads seconds, so a bare source in minutes, hours or days is rewritten to seconds. */
function inSeconds(b: Builder, node: Node, value: Expression, reading: Reading): Expression {
  const spec = reading.format;
  if (spec === null || !formatting.isDuration(spec, value.value.type)) return value;
  const raw = reading.expr.trim();
  const source = catalog.CATALOG.get(raw);
  const factor = source !== undefined ? conversion.SECONDS_PER_UNIT.get(source.unit ?? "") ?? null : null;
  if (factor === null || factor === 1) return value;
  const scaled = b.readingExpression(node, reading, "text", `${raw} * ${factor}`);
  return scaled === null ? value : scaled;
}

/** The readings after the first of a template with several placeholders. */
function buildMore(b: Builder, node: Node, element: Text, entries: Reading[]): TextSegment[] {
  if (entries.length === 0) return [];
  if (node.has("units")) {
    b.bag.error("format", `${element.id}: 'units:' converts the reading of a text with `
      + `one placeholder, and this text has ${entries.length + 1}`, b.doc.span(node, "units"),
    { notes: ["give the converted reading a text element of its own"] });
  }
  if (node.get("absent") instanceof Map) {
    b.bag.error("format", `${element.id}: 'absent: {value:}' substitutes the reading of `
      + `a text with one placeholder, and this text has ${entries.length + 1}`, b.fallbackSpan(node), {
      notes: ["write 'absent: hide' or a text to draw instead "
        + "('absent: \"--\"'); the text is absent when any reading is"],
    });
  }
  const out: TextSegment[] = [];
  for (const entry of entries) {
    let value = b.readingExpression(node, entry);
    if (value === null) continue;
    value = inSeconds(b, node, value, entry);
    const fmt = entry.format ?? "{}";
    b.checkFormat(node, value, fmt);
    out.push(TextSegment.create({ value, format: fmt }));
  }
  return out;
}

/** `{unit}` in a template (or its `aod:` twin) is the label of a `units:` conversion, so it needs one. */
function checkUnitField(b: Builder, node: Node, element: Text): void {
  if (node.has("units")) return;
  const aod = node.get("aod");
  const ownAod = element.aod_own ?? new Map<string, unknown>();
  const checks: [string, unknown, ReturnType<Builder["doc"]["span"]>][] = [
    ["text", element.format, b.doc.span(node, "text")],
    ["aod.text", ownAod.get("text"), aod instanceof Map ? b.doc.span(aod, "text") : null],
  ];
  for (const [where, spec, span] of checks) {
    if (spec && formatting.hasUnitField(str(spec))) {
      b.bag.error("format", `${element.id}.${where}: '{unit}' is the label of a `
        + "'units:' conversion, and this element has no 'units:'", span,
      { notes: ["add 'units: auto' to show the wearer's own units"] });
    }
  }
}

class TextKind extends ElementKind<Text> {
  readonly name = "text";
  readonly irClass = Text;
  override readonly ringed = true;

  build(b: Builder, node: Node, common: Common): Element {
    const [literal, readings] = b.textReadings(node);
    const first = readings[0] ?? null;
    let value = first !== null ? b.readingExpression(node, first) : null;
    let units: Units | null = null;
    if (node.has("units")) {
      units = applyUnits(b, node, value, first);
      if (units !== null) value = units[0];
    } else if (value !== null && first !== null) {
      value = inSeconds(b, node, value, first);
    }
    const [align, verticalAlign] = b.alignment(node);
    const color = b.colorExpression(node, "color");
    const element = Text.create({
      ...common, value, literal, format: first !== null ? first.format : null, color, align, vertical_align: verticalAlign,
      ...b.absence(node),
    });
    if (units !== null) [, element.units, element.unit_label, element.unit_labels, element.unit_digits] = units;
    if (value !== null) element.more = buildMore(b, node, element, readings.slice(1));
    checkUnitField(b, node, element);
    const fontOk = b.resolveFont(node, element);
    if (node.has("antialias")) rejectTextAntialias(b, node, element);
    const fontIsVector = b.isVectorFont(element.font, element.font_is_custom);
    const fontNote = b.fontKindNote(element.font, element.font_is_custom);
    if (node.has("curve")) {
      element.curve = b.buildCurve(node, element.id, { verticalAlign: element.vertical_align, fontOk, fontIsVector, fontNote });
    }
    if (fontOk && node.has("unsupported") && !element.inSubscreen) b.checkUnsupported(node, element.id, fontIsVector, fontNote);
    if (node.has("outline")) element.outline = b.buildOutline(node, "outline", element.id, element);
    const ownAodFormat = element.aod_own !== null && element.aod_own.has("text");
    const aodFormatSpan = ownAodFormat ? b.doc.span(node.get("aod"), "text") ?? b.doc.span(node, "aod") : null;
    if (value !== null) {
      const nullable = element.segments().find(([v]) => v.nullable)?.[0] ?? value;
      b.checkAbsence(node, element, nullable, element.absent, element.placeholder, element.fallback);
      b.checkFormat(node, value, element.format);
      if (ownAodFormat && element.aod_own !== null) {
        // An `aod: {text:}` inherited from a group is checked once inheritance is resolved.
        b.checkFormatSpec(value, str(element.aod_own.get("text")), aodFormatSpan);
      }
    } else if (first === null) {
      // A fixed `text:` has no reading for its `aod:` twin to restyle.
      const refusal = b.aodRefusal("text", "text", null, true);
      if (ownAodFormat && refusal !== null) {
        const [code, what, notes] = refusal;
        b.bag.error(code, `${element.id}.aod.text: ${what}`, aodFormatSpan, { notes });
      }
    }
    b.checkOtherAbsence(node, element, "color", element.color);
    b.checkReachableSubstitute(node, element, "'color'", element.segments().map(([v]) => v), [element.color]);
    return element;
  }

  override aodRefusal(key: string, _shape: string | null, literalText: boolean): Refusal | null {
    if (key === "text" && literalText) return ["format", "'aod: {text:}' restyles a placeholder, and this text is fixed", []];
    return null;
  }
}

register(new TextKind());
