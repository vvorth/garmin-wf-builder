// `type: text`: a bound or literal string, optionally curved onto a
// `face:` (vector) font. Port of wfb/kinds/text.py's build half.
import * as catalog from "../catalog.ts";
import * as conversion from "../conversion.ts";
import type { Data, DataKey } from "../edit/yaml.ts";
import * as formatting from "../formatting.ts";
import type { Builder } from "../ir/builder/index.ts";
import { type Element, type Expression, Text, TextSegment } from "../ir/model.ts";
import {
  HIDDEN_BY_FONT, justify, longer, type Placed, PlacedText, replaceFields, type Resolver, resolvedCurve, textInk,
} from "../layout.ts";
import { repr, roundHalfEven as round, str } from "../py.ts";
import type { Box } from "../units.ts";
import type { Reading } from "../template.ts";
import { type Common, ElementKind, type Refusal, register, TextRun } from "./base.ts";

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

function source(value: Expression): catalog.Source | null {
  return value.sources.length > 0 ? catalog.get(value.sources[0]!) ?? null : null;
}

/** The widest label `{unit}` can show, or `""` without `units:`. */
function widestLabel(element: Text): string {
  let best = "";
  for (const label of element.unit_labels) if (Array.from(label).length > Array.from(best).length) best = label;
  return best;
}

/** The widest string a `fallback:` could render, through the value's own format spec. */
function fallbackWidest(fallback: Expression, spec: string, unitWidest = ""): string {
  if (fallback.value.type === "string" && fallback.constant !== null) return str(fallback.constant);
  return formatting.widest(spec, source(fallback), fallback.value.type, fallback.scale, { unitWidest });
}

/** The widest string this text can draw: its literal, or its readings, placeholder and fallback. */
function widestText(element: Text): string {
  if (element.literal !== null) return element.literal;
  if (element.value === null) return "";
  const spec = element.format || "{}";
  let widest = formatting.widest(spec, source(element.value), element.value.value.type, element.value.scale,
    { digits: element.unit_digits, unitWidest: widestLabel(element) });
  for (const [value, moreSpec] of element.segments().slice(1)) widest += formatting.widest(moreSpec, source(value), value.value.type, value.scale);
  if (element.absent === "placeholder" && element.placeholder) widest = longer(widest, element.placeholder);
  if (element.absent === "fallback" && element.fallback !== null) widest = longer(widest, fallbackWidest(element.fallback, spec, widestLabel(element)));
  return widest;
}

/** The characters the element's font must hold, and those its `aod: {font:}` override must. */
function textGlyphs(element: Text): [Set<string>, Set<string>] {
  if (element.literal !== null) return [new Set(element.literal), new Set(element.literal)];
  if (element.value === null) return [new Set(), new Set()];
  const spec = element.format || "{}";
  const options = { digits: element.unit_digits, unitLabels: element.unit_labels };
  const valueGlyphs = formatting.glyphs(spec, source(element.value), element.value.value.type, element.value.scale, options);
  const glyphs = new Set(valueGlyphs);
  const aod = element.aod;
  const aodSpec = aod !== null && aod.format !== null ? aod.format : spec;
  const aodGlyphs = aodSpec === spec ? new Set(valueGlyphs)
    : formatting.glyphs(aodSpec, source(element.value), element.value.value.type, element.value.scale, options);
  for (const [value, moreSpec] of element.segments().slice(1)) {
    for (const c of formatting.glyphs(moreSpec, source(value), value.value.type, value.scale)) glyphs.add(c);
  }
  if (element.placeholder) for (const c of element.placeholder) glyphs.add(c);
  if (element.absent === "fallback" && element.fallback !== null) {
    const fallback = element.fallback;
    const more = fallback.value.type === "string" && fallback.constant !== null ? new Set(str(fallback.constant))
      : formatting.glyphs(spec, source(fallback), fallback.value.type, fallback.scale);
    for (const c of more) glyphs.add(c);
  }
  return [glyphs, aodGlyphs];
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

  override textRuns(element: Text): TextRun[] {
    const aod = element.aod;
    const aodFont = aod !== null && aod.font_is_custom ? aod.font : null;
    if (!element.font_is_custom && aodFont === null) return [];
    const [glyphs, aodGlyphs] = textGlyphs(element);
    const runs: TextRun[] = [];
    if (element.font_is_custom) {
      const widest = widestText(element);
      runs.push(new TextRun(element.id, element.font, {
        glyphs, samples: [widest], sample_note: `the widest rendering of this element is ${repr(widest)}`,
        span: element.span, unsupported: element.unsupported, curve: element.curve,
      }));
    }
    // Whatever the element's own font is, this baked one draws asleep, and it needs the glyphs.
    if (aodFont !== null) runs.push(new TextRun(element.id, aodFont, { glyphs: aodGlyphs, span: element.span, aod_only: true }));
    return runs;
  }

  override hiddenReason(placed: Placed): string | null {
    return (placed as PlacedText).font.available ? null : HIDDEN_BY_FONT;
  }

  override resolve(r: Resolver, element: Text, parent: Box, depth: number): Placed {
    const font = r.textFont(element.font, element.font_is_custom, element.curve);
    const widest = widestText(element);
    const width = font.width(widest);
    const lineHeight = font.lineHeight;
    const [x, y] = r.point(element.at, parent);
    let curve = resolvedCurve(element.curve);
    if (element.curve !== null && curve.style === "radial" && element.curve.radius !== null) {
      curve = replaceFields(curve, {
        radius_px: round(r.extent(element.curve.radius, parent, "minor", 0, null, element.resolved_min_1px, "curve.radius")),
      });
    }
    // The box holds whichever ring is wider, awake or AOD.
    const aodRing = element.aod !== null ? element.aod.outline : null;
    const ringPx = Math.max(...[element.outline, aodRing].map((ring) => (ring !== null ? ring.width : 0)));
    const box = textInk(x, y, width, lineHeight, element.align, element.vertical_align, {
      curveStyle: curve.style, angleGarmin: curve.angle_garmin, radiusPx: curve.radius_px, direction: curve.direction,
      metric: font.metric, pad: ringPx, device: r.device,
    }).box();
    return PlacedText.create({
      element, box: box.rounded(), center: [round(x), round(y)], depth, anchor_point: [round(x), round(y)],
      justify: justify(element), font: font.resolved(), widest, measured_width: round(width),
      width_is_estimated: font.baked === null, curve, line_height: lineHeight,
    });
  }

  override aodRefusal(key: string, _shape: string | null, literalText: boolean): Refusal | null {
    if (key === "text" && literalText) return ["format", "'aod: {text:}' restyles a placeholder, and this text is fixed", []];
    return null;
  }
}

register(new TextKind());
