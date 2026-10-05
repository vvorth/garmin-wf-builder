// `hand_sets:` and the part vocabulary a hand and a `pattern` template
// share, with the per-shape key and rejection-reason tables. Port of
// wfb/ir/builder/hands.py.
import type { Span } from "../../diagnostics.ts";
import * as expr from "../../expr.ts";
import * as formatting from "../../formatting.ts";
import { repr, str, truthy } from "../../py.ts";
import {
  type AnyHandPart, ArcPart, CirclePart, type Curve, type Expression, Hand, HandSet, LinePart, type Outline,
  PolygonPart, Position, RectanglePart, TextPart,
} from "../model.ts";
import { ConfigAxes } from "./config.ts";
import { allKeys } from "./glyphs.ts";
import { andPaths, list, type Node } from "./state.ts";

type KeyTable = ReadonlyMap<string, ReadonlySet<string>>;

/** The geometry keys each hand part shape reads, in the hand's own frame. */
export const HAND_PART_GEOMETRY_KEYS: KeyTable = new Map([
  ["polygon", new Set(["points"])],
  ["rectangle", new Set(["at", "size", "align"])],
  ["line", new Set(["at", "to"])],
  ["circle", new Set(["at", "radius", "align"])],
]);
const ALL_HAND_PART_GEOMETRY_KEYS = allKeys(HAND_PART_GEOMETRY_KEYS);

/** Hand part shapes that accept `filled:` at all. */
export const HAND_PART_FILLED_SHAPES: ReadonlySet<string> = new Set(["polygon", "rectangle", "circle"]);

/** Shapes for which `filled: false` is refused: Dc has no `drawPolygon`. */
export const HAND_PART_NO_UNFILLED: ReadonlySet<string> = new Set(["polygon", "rectangle"]);

/** `type:` values the hand-part schema accepts only so this message fires instead of an enum mismatch. */
export const HAND_PART_REJECTED_SHAPES: ReadonlyMap<string, string> = new Map([
  ["ellipse", "no Dc call draws a rotated ellipse -- approximate it with 'polygon'"],
  ["arc", "an arc part would need its start angle to rotate with the hand too, "
    + "which is not implemented yet (docs/limitations.md) -- "
    + "approximate a wedge with 'polygon', or use 'circle' for a disc"],
  ["text", "a bitmap font cannot rotate"],
  ["icon", "a bitmap font cannot rotate"],
]);

/** A pattern template part: the hand vocabulary plus `arc` and `text`. */
export const PATTERN_PART_GEOMETRY_KEYS: KeyTable = new Map([
  ...HAND_PART_GEOMETRY_KEYS,
  ["arc", new Set(["radius", "start_angle", "sweep"])],
  ["text", new Set(["at", "text", "font", "align", "curve", "unsupported", "outline"])],
]);
const ALL_PATTERN_PART_GEOMETRY_KEYS = allKeys(PATTERN_PART_GEOMETRY_KEYS);

/** The extra note when a rejected key is `align`. */
const HAND_PART_NO_ALIGNMENT_REASON: ReadonlyMap<string, string> = new Map([
  ["polygon", "every vertex is its own position; there is no single 'at:' "
    + "to align on -- a polygon part has no 'at:' of its own either"],
  ["line", "'at:' and 'to:' are the part's two ends"],
  ["arc", "an arc part is always centred on the copy's own origin -- there "
    + "is no 'at:' to offset in the first place"],
]);

/** Like `HAND_PART_REJECTED_SHAPES`, minus `arc` and `text`, which a pattern part can draw. */
export const PATTERN_PART_REJECTED_SHAPES: ReadonlyMap<string, string> = new Map([
  ["ellipse", "no Dc call draws a rotated or translated ellipse -- approximate it with 'polygon'"],
  ["icon", "a bitmap font cannot rotate or translate through this loop"],
]);

/** The `TextPart` fields `buildTextPart` decides. */
type TextFields = Pick<TextPart, "text_value" | "text_literal" | "format" | "font" | "font_is_custom" | "curve" | "unsupported" | "outline">;

/** The `hand_sets:` block and hand/pattern parts. */
export class HandParts extends ConfigAxes {
  /** `hand_sets:`: named analog-hand sets, declared once, placed by name. */
  buildHands(raw: Node): void {
    for (const [name, spec] of raw as Map<string, Node>) {
      const span = this.doc.span(raw, name);
      this.hand_sets.declare(name, span);
      let ok = true;
      const hands = new Map<string, Hand | null>();
      for (const handName of ["hour", "minute", "second"]) {
        if (!spec.has(handName)) {
          hands.set(handName, null);
          continue;
        }
        const hand = this.buildHand(spec.get(handName) as Node, name, handName);
        if (hand === null) {
          ok = false;
          continue;
        }
        hands.set(handName, hand);
      }
      if (ok && [...hands.values()].every((hand) => hand === null)) {
        this.bag.error("hands", `hand_sets.${name}: declares none of hour, minute or second`, span, {
          notes: ["a hand set is a shape, like a fonts: entry -- it needs at "
            + "least one hand to be worth placing",
            "a set with only 'second:' is a valid small-seconds subdial"],
        });
        ok = false;
      }
      if (!ok) {
        this.hand_sets.reject(name);
        continue;
      }
      this.hand_sets.set(name, HandSet.create({
        name, hour: hands.get("hour") ?? null, minute: hands.get("minute") ?? null, second: hands.get("second") ?? null, span,
      }));
    }
  }

  private buildHand(spec: Node, setName: string, handName: string): Hand | null {
    const where = `hand_sets.${setName}.${handName}`;
    const [handColor, colorFailed] = this.ownedColor(spec, where, true);
    let ok = !colorFailed;
    const parts: AnyHandPart[] = [];
    list(spec.get("parts")).forEach((rawPart, index) => {
      const part = this.buildHandPart(rawPart as Node, where, index, handColor, colorFailed);
      if (part === null) {
        ok = false;
        return;
      }
      parts.push(part);
    });
    if (!ok) return null;
    return Hand.create({ parts, color: handColor });
  }

  /** `color:` on a hand, a pattern, or one of their parts, as `[color, failed]`. */
  ownedColor(node: Node, where: string, hand: boolean): [Expression | null, boolean] {
    if (!node.has("color")) return [null, false];
    const color = this.colorExpression(node, "color");
    if (color === null) return [null, true];
    if (hand && this.rejectHandDataColor(color, where, this.doc.span(node, "color"))) return [null, true];
    return [color, false];
  }

  /** A hand colour may not read a data source: a hand has no `absent:` to fall back through. */
  private rejectHandDataColor(color: Expression, where: string, span: Span | null): boolean {
    if (color.sources.length === 0) return false;
    this.bag.error("hands", `${where}.color: a hand colour cannot read data (${andPaths(color.sources)})`, span ?? color.span, {
      notes: ["allowed: 'color.<name>' (a swatch or a role) and literal "
        + "colours -- and conditionals over those",
        "a hand has no 'absent:' to fall back through if the "
        + "reading it named turned out absent"],
    });
    return true;
  }

  /** One primitive of a hand, or of a pattern template (`context: "pattern"`). */
  buildHandPart(node: Node, where: string, index: number, defaultColor: Expression | null, defaultColorFailed: boolean,
    context: "hand" | "pattern" = "hand"): AnyHandPart | null {
    const isHand = context === "hand";
    const noun = isHand ? "hand" : "pattern";
    const rejectedShapes = isHand ? HAND_PART_REJECTED_SHAPES : PATTERN_PART_REJECTED_SHAPES;
    const geometryKeys = isHand ? HAND_PART_GEOMETRY_KEYS : PATTERN_PART_GEOMETRY_KEYS;
    const partWhere = `${where}.parts[${index}]`;
    const shape = node.get("type") as string;
    const span = this.doc.span(node);
    if (rejectedShapes.has(shape)) {
      this.bag.error("element", `${partWhere}: 'type: ${shape}' is not accepted on a ${noun} part -- ${rejectedShapes.get(shape)}`,
        this.doc.span(node, "type") ?? span, { notes: ["the rotatable primitives are: " + [...geometryKeys.keys()].sort().join(", ")] });
      return null;
    }
    if (!geometryKeys.has(shape)) { // unreachable once the schema has run
      this.bag.error(isHand ? "hands" : "pattern", `${partWhere}: not a valid ${noun} part`, span);
      return null;
    }

    const [partColor, partColorFailed] = this.ownedColor(node, partWhere, isHand);
    let ok = !partColorFailed;
    const effectiveColor = partColor !== null ? partColor : defaultColor;
    if (effectiveColor === null && !defaultColorFailed && !partColorFailed) {
      const owner = isHand ? "its hand" : "this pattern";
      this.bag.error(isHand ? "hands" : "pattern", `${partWhere}: no colour -- neither this part nor ${owner} declares 'color:'`,
        span, { notes: [`set 'color:' on the part, or on the ${noun} as a default every part without one inherits`] });
      ok = false;
    }

    // `visible:` on a pattern part, compiled with `copy` bound. A constant `true` is dropped; `false` is kept.
    let partVisible: Expression | null = null;
    if (!isHand && node.has("visible")) {
      partVisible = this.visibleOf(node);
      if (partVisible === null) ok = false;
      else if (partVisible.constant !== null && truthy(partVisible.constant)) partVisible = null;
    }

    const points = list(node.get("points")).filter((raw) => raw instanceof Map).map((raw) => this.position(raw, node, "points"));
    const at = node.has("at") ? this.position(node.get("at"), node, "at") : new Position();
    const size = this.size(node.get("size"));
    const to = node.has("to") ? this.position(node.get("to"), node, "to") : null;
    const thickness = this.length(node, "thickness");
    const radius = this.length(node, "radius");
    const filled = truthy(node.has("filled") ? node.get("filled") : true);
    const startAngle = shape === "arc" ? this.angle(node, "start_angle") : null;
    const sweep = shape === "arc" ? this.angle(node, "sweep") : null;

    if (shape === "polygon" && points.length < 3) {
      this.require(node, "points", `${partWhere}: a polygon part needs points`);
      ok = false;
    }
    if (shape === "rectangle" && (size.width === null || size.height === null)) {
      this.require(node, "size", `${partWhere}: a rectangle part needs size.width and size.height`);
      ok = false;
    }
    if (shape === "line" && to === null) {
      this.require(node, "to", `${partWhere}: a line part needs a 'to' position`);
      ok = false;
    }
    if (shape === "circle" && radius === null) {
      this.require(node, "radius", `${partWhere}: a circle part needs a radius`);
      ok = false;
    }
    if (shape === "arc" && radius === null) {
      this.require(node, "radius", `${partWhere}: an arc part needs a radius`);
      ok = false;
    }

    if (!this.checkHandPartKeys(node, shape, partWhere, context)) ok = false;

    if (node.has("filled") && HAND_PART_NO_UNFILLED.has(shape) && !filled) {
      this.bag.error("element", `${partWhere}: 'filled: false' is not accepted on a ${noun} `
        + `'type: ${shape}' part -- Toybox.Graphics.Dc has fillPolygon but no drawPolygon`,
      this.doc.span(node, "filled") ?? span, {
        notes: shape === "rectangle" ? ["a rectangle part becomes a polygon at build time, so the same platform limit applies"] : [],
      });
      ok = false;
    }

    const [align, verticalAlign] = this.alignment(node);
    let textFields: TextFields | null = null;
    if (shape === "text") {
      textFields = this.buildTextPart(node, partWhere, verticalAlign);
      if (textFields === null) ok = false;
    }

    if (!ok) return null;
    const common = {
      color: effectiveColor, span, visible: partVisible,
      min_1px: node.has("min_1px") ? truthy(node.get("min_1px")) : null,
    };
    if (shape === "polygon") return PolygonPart.create({ ...common, points, filled });
    if (shape === "rectangle") return RectanglePart.create({ ...common, at, size, filled, align, vertical_align: verticalAlign });
    if (shape === "line") return LinePart.create({ ...common, at, to, thickness });
    if (shape === "circle") {
      return CirclePart.create({ ...common, at, radius, thickness, filled, align, vertical_align: verticalAlign });
    }
    if (shape === "arc") return ArcPart.create({ ...common, radius, thickness, start_angle: startAngle, sweep });
    return TextPart.create({ ...common, at, align, vertical_align: verticalAlign, ...textFields! });
  }

  /** A pattern text part's strings are fixed at build time, so a format following a device setting has nothing to follow. */
  private checkPartFormatSettings(node: Node, value: Expression, partWhere: string, spec: string): void {
    let extra: string[];
    try {
      extra = formatting.extraPaths(spec, value.value.type);
    } catch (error) {
      if (error instanceof formatting.FormatError) return; // `checkFormat` already reported it
      throw error;
    }
    if (extra.length > 0) {
      this.bag.error("format", `${partWhere}.text: ${repr(spec)} follows the watch's 12/24-hour `
        + "setting, which a pattern text part cannot read", this.doc.span(node, "text"), {
        notes: ["a pattern text part's strings are fixed at build time; "
          + "use '%H' for 24-hour or '%l %p' for 12-hour"],
      });
    }
  }

  /** The `type: text` half of a pattern part, or `null` once any of its own checks failed. */
  private buildTextPart(node: Node, partWhere: string, verticalAlign: string): TextFields | null {
    let ok = true;
    let textValue: Expression | null = null;
    let textLiteral: string | null = null;
    let textFormat: string | null = null;
    const [literal, readings] = this.textReadings(node);
    if (!node.has("text")) {
      this.bag.error("pattern", `${partWhere}: a text part needs a 'text:' -- fixed text, or a `
        + "placeholder whose expression reads 'copy'", this.doc.span(node));
      ok = false;
    } else if (readings.length > 0) {
      const value = this.readingExpression(node, readings[0]!);
      if (value === null) {
        ok = false; // already reported
      } else {
        const badRefs = [...new Set([...expr.walk(value.ast!)]
          .filter((ref): ref is expr.Ref => ref.kind === "ref" && ref.path !== expr.COPY).map((ref) => ref.path))].sort();
        if (badRefs.length > 0) {
          this.bag.error("pattern", `${partWhere}.text: a pattern text part's placeholder may read only 'copy', not `
            + badRefs.join(", "), value.span, {
            notes: ["every copy's string must be known at build time, for font subsetting and extents",
              "data in a pattern text part is not implemented (docs/limitations.md)"],
          });
          ok = false;
        } else if (!["number", "float", "string"].includes(value.value.type)) {
          this.bag.error("pattern", `${partWhere}.text: the placeholder must be a number or a string, got ${value.value}`, value.span);
          ok = false;
        } else {
          textValue = value;
          if (readings[0]!.format !== null) {
            textFormat = readings[0]!.format;
            this.checkFormat(node, value, textFormat);
            this.checkPartFormatSettings(node, value, partWhere, textFormat);
          }
        }
      }
    } else if (literal !== null) {
      textLiteral = literal;
    } else {
      ok = false; // a malformed template, already reported
    }

    let font = "FONT_MEDIUM", fontIsCustom = false, fontOk = true;
    if (node.has("font")) {
      const resolved = this.fontReference(str(node.get("font")), this.doc.span(node, "font"));
      if (resolved === null) ok = fontOk = false;
      else [font, fontIsCustom] = resolved;
    }
    const fontIsVector = this.isVectorFont(font, fontIsCustom);

    let curve: Curve | null = null;
    if (node.has("curve")) {
      curve = this.buildCurve(node, partWhere, { verticalAlign, fontOk, fontIsVector });
      if (curve === null) ok = false;
    }
    if (fontOk && node.has("unsupported")) this.checkUnsupported(node, partWhere, fontIsVector);

    // A failed `outline:` aborts the part; `outline: none` (or no key) is not a failure.
    let outline: Outline | null = null;
    if (node.has("outline")) {
      outline = this.buildOutline(node, "outline", partWhere);
      const raw = node.get("outline");
      if (outline === null && raw !== null && raw !== undefined && raw !== "none") ok = false;
    }

    if (!ok) return null;
    return {
      text_value: textValue, text_literal: textLiteral, format: textFormat, font, font_is_custom: fontIsCustom, curve,
      unsupported: (node.get("unsupported") ?? null) as string | null, outline,
    };
  }

  /** Reject a geometry key this part's shape does not read, plus the `thickness`/`filled` rules. */
  private checkHandPartKeys(node: Node, shape: string, partWhere: string, context: "hand" | "pattern"): boolean {
    const isHand = context === "hand";
    const noun = isHand ? "hand" : "pattern";
    const geometryKeys = isHand ? HAND_PART_GEOMETRY_KEYS : PATTERN_PART_GEOMETRY_KEYS;
    const all = isHand ? ALL_HAND_PART_GEOMETRY_KEYS : ALL_PATTERN_PART_GEOMETRY_KEYS;
    const extraNotes = (key: string): string[] => {
      const notes: string[] = [];
      if (!isHand && shape === "arc" && key === "at") {
        notes.push("an arc part is always centred on the copy's own origin -- there is no separate centre to offset");
      }
      if (key === "align" && HAND_PART_NO_ALIGNMENT_REASON.has(shape)) notes.push(HAND_PART_NO_ALIGNMENT_REASON.get(shape)!);
      return notes;
    };
    let ok = this.checkForeignKeys(node, shape, geometryKeys, all, {
      code: "element", disc: "type", prefix: `${partWhere}: `, qualifier: `a ${noun} `, suffix: " part", extraNotes,
    });
    const filled = truthy(node.has("filled") ? node.get("filled") : true);
    const thicknessAlways = isHand ? ["line"] : ["line", "arc"];
    const thicknessOk = thicknessAlways.includes(shape) || (shape === "circle" && !filled);
    if (node.has("thickness") && !thicknessOk) {
      const reason = shape === "circle" ? "a filled 'type: circle' part" : `a ${noun} 'type: ${shape}' part`;
      const only = "'line'" + (!isHand ? " and 'arc'" : "");
      this.bag.error("element", `${partWhere}: 'thickness' is not used by ${reason}`,
        this.doc.span(node, "thickness") ?? this.doc.span(node), {
          notes: shape === "circle"
            ? ["thickness is the pen width of a stroke; add 'filled: false' to a circle part to stroke it, or drop 'thickness'"]
            : [`only ${only} and an unfilled 'circle' part read 'thickness'`],
        });
      ok = false;
    }
    if (node.has("filled") && !HAND_PART_FILLED_SHAPES.has(shape)) {
      const filledNote = shape === "line" ? "a line has no notion of being filled or not"
        : shape === "text" ? "glyphs have no notion of being filled or not"
          : "an arc has no notion of being filled or not -- Toybox.Graphics.Dc has no filled-arc primitive";
      this.bag.error("element", `${partWhere}: 'filled' is not used by a ${noun} 'type: ${shape}' part`,
        this.doc.span(node, "filled") ?? this.doc.span(node), { notes: [filledNote] });
      ok = false;
    }
    return ok;
  }
}
