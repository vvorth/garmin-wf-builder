// `type: pattern`: one template drawn `count:` times, turned about `at:`
// (radial), stepped along `{dx, dy}` (linear) or in rows (grid). Port of
// wfb/kinds/pattern.py's build half.
import type { Data, DataKey } from "../edit/yaml.ts";
import * as expr from "../expr.ts";
import * as formatting from "../formatting.ts";
import { ABSENCE_IS_NORMAL } from "../ir/builder/absence.ts";
import type { Builder } from "../ir/builder/index.ts";
import { andPaths, dedupAppend } from "../ir/builder/state.ts";
import {
  type AnyHandPart, drawnCopies, type Element, type Expression, PATTERN_LOOP_INDEX, PatternElement, Position,
  ROLE_COLOR, ROLE_PART_VISIBLE, type TextPart,
} from "../ir/model.ts";
import type { Device } from "../devices/device.ts";
import {
  type Ink, type Placed, PlacedPattern, type ResolvedHandPart, type Resolver, type ResolvedTextPart, roundHalfAway, textInk,
} from "../layout.ts";
import { deepEqual, formatG, num, pyMod, roundHalfEven as round } from "../py.ts";
import { Box, IntBox } from "../units.ts";
import { type Common, ElementKind, type Refusal, register, TextRun } from "./base.ts";
import {
  AnyOf, AodDimmed, AodPart, AodPick, ArcSpan, Bin, Blank, Call, Cmp, Comment, type Cond, Const, Continue, type DrawContext,
  FloatLit, Font, FontDrop, For, If, IfNotNull, Let, Lit, LoadFont, type Num, NumLocal, type Op, type Paint, Paren, Part,
  PerCopy, Reading, RingColor, SetColor, SetPen, Shifted, type Str, StrLit, Text as DrawText, Truthy,
} from "../draw/program.ts";
import { colorCode } from "../draw/printer.ts";
import { constPrefix, fontField } from "../emit/monkeyc/common.ts";
import * as lc from "../emit/monkeyc/layout_constants.ts";
import { discPerimeterOffsets } from "../ir/model.ts";
import { radians } from "../py.ts";

type Node = Map<DataKey, Data>;

/** A text part's per-copy Garmin angle: its local copy-0 angle composed with the copy's own rotation. */
export class PatternTextAngle {
  readonly local: number;
  readonly start: number;
  readonly step: number;

  constructor(local: number, start: number, step: number) {
    this.local = local;
    this.start = start;
    this.step = step;
  }

  copyCurveAngle(index: number): number {
    return pyMod(this.local - (this.start + index * this.step), 360.0);
  }
}

/** The whole-pixel anchor of one copy of a text part, rounded half up as the device does. */
export function patternTextAnchor(part: ResolvedTextPart, ox: number, oy: number, s: number, c: number): [number, number] {
  return [Math.floor(ox + part.x * c - part.y * s + 0.5), Math.floor(oy + part.x * s + part.y * c + 0.5)];
}

/** `textInk` for copy `index` of a text part. */
function patternTextInk(part: ResolvedTextPart, ox: number, oy: number, s: number, c: number, index: number,
  start: number, step: number, device: Device): Ink {
  const [ax, ay] = patternTextAnchor(part, ox, oy, s, c);
  const angle = new PatternTextAngle(part.curve.angle_garmin, start, step).copyCurveAngle(index);
  return textInk(ax, ay, part.widths.length > 0 ? part.widths[index]! : 0, part.line_height, part.align, part.vertical_align, {
    curveStyle: part.curve.style, angleGarmin: angle, radiusPx: part.curve.radius_px, direction: part.curve.direction,
    metric: part.font.metric, pad: part.outline_width, device,
  });
}

/** `[minX, minY, maxX, maxY]` of one part's ink for one copy. */
function patternPartInk(part: ResolvedHandPart, ox: number, oy: number, s: number, c: number, index: number,
  start: number, step: number, device: Device): [number, number, number, number] {
  if (part.shape === "text") return patternTextInk(part, ox, oy, s, c, index, start, step, device).bounds();
  return part.ink(ox, oy, s, c);
}

/** `step:`/`start:` as `[stepDegrees, startDegrees, stepPosition]`, or `null` once an error is reported. */
function patternSteps(b: Builder, node: Node, common: Common, count: number): [number, number, Position | null] | null {
  const elementId = common.id;
  const stepRaw = node.get("step");
  const pattern = node.get("pattern") as string;
  if (pattern !== "radial") {
    if (node.has("start")) {
      b.bag.error("pattern", `${elementId}.start: not accepted on 'pattern: ${pattern}' -- `
        + "only a radial pattern has a start copy angle", b.doc.span(node, "start"),
      { notes: ["'step: {dx, dy}' already places copy 0 relative to 'at:'"] });
      return null;
    }
    if (stepRaw === undefined || stepRaw === null) {
      b.bag.error("pattern", `${elementId}.step: a ${pattern} pattern needs a 'step: {dx, dy}' between copies`,
        b.doc.span(node) ?? common.span,
        { notes: ["radial's angle default (360deg / count) has no equivalent -- there is no natural spacing to assume"] });
      return null;
    }
    if (!(stepRaw instanceof Map)) {
      b.bag.error("pattern", `${elementId}.step: 'pattern: ${pattern}' takes {dx, dy} for 'step:', not an angle`,
        b.doc.span(node, "step"), { notes: ["an angle 'step:' is for 'pattern: radial'"] });
      return null;
    }
    return [0.0, 0.0, b.position(stepRaw, node, "step")];
  }
  if (stepRaw instanceof Map) {
    b.bag.error("pattern", `${elementId}.step: 'pattern: radial' takes an angle for 'step:' (default 360deg / count), not {dx, dy}`,
      b.doc.span(node, "step"), { notes: ["'{dx, dy}' is for 'pattern: linear' and 'pattern: grid'"] });
    return null;
  }
  let stepDegrees: number;
  if (stepRaw === undefined || stepRaw === null) {
    stepDegrees = 360.0 / count;
  } else {
    const stepAngle = b.angle(node, "step");
    if (stepAngle === null) return null; // already reported
    stepDegrees = stepAngle.degrees;
  }
  const startAngle = node.has("start") ? b.angle(node, "start") : null;
  if (node.has("start") && startAngle === null) return null; // already reported
  const startDegrees = startAngle !== null ? startAngle.degrees : 0.0;

  if (stepDegrees === 0.0) {
    b.bag.error("pattern", `${elementId}.step: 'step: 0deg' draws every copy on top of copy 0`,
      b.doc.span(node, "step") ?? common.span, {
        notes: ["a radial pattern's whole point is turning between "
          + "copies -- give it a nonzero step, or write one "
          + "element if a single copy is all you want"],
      });
    return null;
  }
  if (count > 1) {
    const span = Math.abs(stepDegrees) * (count - 1);
    if (span >= 360.0 - 1e-9) {
      const wrapIndex = Math.min(count - 1, Math.ceil(360.0 / Math.abs(stepDegrees)));
      b.bag.error("pattern", `${elementId}: copies 0 and ${wrapIndex} land on the same `
        + `angle -- 'step:' x (count - 1) = ${formatG(span)}deg reaches a full turn`, b.doc.span(node, "step") ?? common.span, {
        notes: [`count: ${count}, step: ${formatG(stepDegrees)}deg -- `
          + "reduce count or step so the copies do not wrap past 360deg"],
      });
      return null;
    }
  }
  return [stepDegrees, startDegrees, null];
}

/** Fill each text part's per-copy strings, as the host preview evaluates an ordinary text element. */
function renderPatternTexts(b: Builder, elementId: string, parts: AnyHandPart[], count: number): boolean {
  let ok = true;
  for (const part of parts) {
    if (part.shape !== "text") continue;
    if (part.text_literal !== null) {
      part.texts = Array.from({ length: count }, () => part.text_literal!);
      continue;
    }
    const value = part.text_value!;
    const texts: string[] = [];
    let complete = true;
    for (let i = 0; i < count; i++) {
      const v = expr.evaluate(value.ast!, new Map([[expr.COPY, i]]));
      if (v === null) {
        b.bag.error("pattern", `${elementId}: a pattern text part's value could not be evaluated for copy ${i}`, value.span,
          { notes: ["expected a copy-only expression to evaluate for every copy index"] });
        ok = false;
        complete = false;
        break;
      }
      texts.push(formatting.render(part.format ?? "{}", v, value.value.type));
    }
    if (complete) part.texts = texts;
  }
  return ok;
}

/** One element-level `absent:` check for a pattern: every nullable colour and part `visible:`, reported once. */
function checkPatternAbsence(b: Builder, node: Node, element: PatternElement): void {
  const nullable: Expression[] = [];
  for (const [role, expression] of element.boundExpressions()) {
    if ((role === ROLE_COLOR || role === ROLE_PART_VISIBLE) && expression.nullable && !nullable.some((e) => deepEqual(e, expression))) {
      nullable.push(expression);
    }
  }
  if (nullable.length > 0) {
    if (element.absent !== null) return;
    const sources = [...b.nullableSources(nullable)].sort();
    b.bag.error("when-absent", `${element.id}: reads ${andPaths(sources)}, which can be absent, so 'absent: hide' is required`,
      nullable[0]!.span, {
        notes: [
          ABSENCE_IS_NORMAL,
          "a pattern has no text or value to use instead -- absence hides "
          + "the whole pattern, every copy and every part, because the "
          + "reading is taken once per frame, before the loop",
          "add 'absent: hide' to the pattern",
        ],
      });
    return;
  }
  if (element.absent !== null) {
    b.bag.note("when-absent", `${element.id}: 'absent:' has no effect -- nothing this pattern reads is ever absent`,
      b.doc.span(node, "absent"));
  }
}

/** Does this pattern's loop compute a `sin`/`cos` pair: a radial one with a part that is not an arc. */
function patternNeedsMath(placed: PlacedPattern): boolean {
  if (placed.element.pattern !== "radial") return false;
  return placed.parts.some((part) => part.shape !== "arc");
}

/** The loop's skip test: `skip_every:` first, then every `skip:` index it does not already cover. */
function patternSkipTerms(element: PatternElement): Cond[] {
  const i = NumLocal("i");
  const terms: Cond[] = [];
  if (element.skip_every !== null) terms.push(Cmp("==", Bin("%", i, Lit(element.skip_every)), Lit(0)));
  for (const index of element.skip) {
    if (element.skip_every === null || pyMod(index, element.skip_every) !== 0) terms.push(Cmp("==", i, Lit(index)));
  }
  return terms;
}

/** The radial loop's `angle` in radians, and the degrees comment beside it. */
function patternAngle(element: PatternElement): [Num, string] {
  const i = NumLocal("i");
  const step = Bin("*", i, FloatLit(radians(element.step_angle)));
  const comment = `(${formatG(element.start_angle)} + ${formatG(element.step_angle)} i) degrees`;
  if (element.start_angle === 0.0) return [step, comment];
  return [Bin("+", FloatLit(radians(element.start_angle)), step), comment];
}

/** One template part, drawn for the current copy `i`; with `ring`, only its ring. */
function lowerPart(element: PatternElement, prefix: string, index: number, part: ResolvedHandPart, radial: boolean,
  hoistPen: boolean, textFonts: Map<string, string>, pen: AodPick, stamp: [Paint, number] | null, ring: number | null): Op[] {
  const partPrefix = `${prefix}_${index}`;
  if (part.shape === "text") return lowerTextPart(element, part, partPrefix, index, radial, textFonts, stamp, ring);
  if (part.shape !== "arc") return [Part(part, partPrefix, radial, pen, { setPen: !hoistPen, ring })];
  const g0 = FloatLit(90.0 - (part.start_angle + element.start_angle));
  const start: Num = radial ? Bin("-", g0, Bin("*", NumLocal("i"), FloatLit(element.step_angle))) : g0;
  const [cx, cy] = radial ? [NumLocal("cx"), NumLocal("cy")] : [NumLocal("ox"), NumLocal("oy")];
  const radius = Const(`${partPrefix}_RADIUS`, part.radius);
  const offsets: [number, number][] = ring !== null ? discPerimeterOffsets(ring) : [[0, 0]];
  return offsets.map(([dx, dy]) => ArcSpan(Shifted(cx, dx), Shifted(cy, dy), radius, pen, start, FloatLit(part.sweep), true));
}

/** The per-copy Garmin-degrees angle a text part's own `curve:` draws at. */
function textAngle(element: PatternElement, part: ResolvedTextPart): Num {
  const radial = element.pattern === "radial";
  const terms = new PatternTextAngle(part.curve.angle_garmin, element.start_angle, radial ? element.step_angle : 0.0);
  const g0 = FloatLit(terms.local - terms.start);
  return radial ? Bin("-", g0, Bin("*", NumLocal("i"), FloatLit(terms.step))) : g0;
}

/** One copy's `shape: text` part, or with `ring` only its ring; a vector font's draws inside its null check. */
function lowerTextPart(element: PatternElement, part: ResolvedTextPart, partPrefix: string, index: number, radial: boolean,
  textFonts: Map<string, string>, stamp: [Paint, number] | null, ring: number | null): Op[] {
  const irPart = element.parts[index] as TextPart;
  const printed: Str = irPart.text_literal !== null ? StrLit(irPart.text_literal) : Reading(irPart.format || "{}", irPart.text_value!);
  const text = PerCopy(printed, part.texts);
  const fontCode = part.font.is_custom ? textFonts.get(part.font.reference)! : `Graphics.${part.font.reference}`;
  const vector = part.font.is_vector;
  const font = Font(fontCode, {
    baked: part.font.is_custom && !vector ? part.font.reference : null, metric: part.font.metric, vector,
  });
  const style = part.curve.style;
  const px = Const(`${partPrefix}_X`, part.x), py = Const(`${partPrefix}_Y`, part.y);
  let x: Num, y: Num;
  if (radial) {
    const cy: Num = style !== null ? NumLocal("cy") : FontDrop(NumLocal("cy"), part.vertical_align, fontCode);
    x = Call("WfbGeom.rotatedX", [px, py, NumLocal("cx"), NumLocal("sin"), NumLocal("cos")]);
    y = Call("WfbGeom.rotatedY", [px, py, cy, NumLocal("sin"), NumLocal("cos")]);
  } else {
    x = Bin("+", NumLocal("ox"), px);
    const oy = Bin("+", NumLocal("oy"), py);
    y = style !== null ? oy : FontDrop(oy, part.vertical_align, fontCode);
  }
  const angle = style !== null ? textAngle(element, part) : null;
  const call = (dx = 0, dy = 0): DrawText => DrawText(Shifted(x, dx), Shifted(y, dy), font, text, part.justify, part.vertical_align, {
    align: part.align, style, angle, radius: style === "radial" ? Const(`${partPrefix}_RADIUS`, part.curve.radius_px) : null,
    direction: part.curve.direction, shiftY: false, splitX: radial || style !== null,
  });
  let body: Op[];
  if (ring !== null) {
    body = [SetColor(stamp![0]), ...discPerimeterOffsets(ring).map(([dx, dy]) => call(dx, dy))];
  } else {
    body = [];
    if (part.outline_color !== null) {
      body.push(SetColor(AodDimmed(element, part.outline_color)), ...discPerimeterOffsets(part.outline_width).map(([dx, dy]) => call(dx, dy)),
        Blank(), SetColor(AodPart(element, part.color)));
    }
    body.push(call());
  }
  if (vector) return [IfNotNull(fontCode, body, part.font.available)];
  return body;
}

class PatternKind extends ElementKind<PatternElement> {
  readonly name = "pattern";
  readonly irClass = PatternElement;
  override readonly antialiased = true;
  override readonly ringed = true;

  override ringRefusal(element: PatternElement): string | null {
    if (element.parts.some((part) => part.shape === "text" && part.outline !== null)) {
      return "round a pattern with a ringed text part is not implemented yet: drop the part's own 'outline:' or the pattern's";
    }
    return null;
  }

  /** Every check returns on its own violation, so one mistake is one error. */
  build(b: Builder, node: Node, common: Common): Element | null {
    const elementId = common.id;
    const count = num(node.get("count") as number);
    if (common.modes.includes("low_power")) {
      b.bag.error("pattern", `${elementId}: 'sleep_update: true' is not accepted on a pattern`,
        b.doc.span(node, "sleep_update") ?? common.span, {
          notes: ["a fixed pattern gains nothing from onPartialUpdate -- its "
            + "geometry never changes -- and its clip would be its whole extent"],
        });
      return null;
    }
    const steps = patternSteps(b, node, common, count);
    if (steps === null) return null;
    const pattern = node.get("pattern") as string;
    const columns = (node.get("columns") ?? null) as number | null;
    if (pattern === "grid" && columns === null) {
      b.bag.error("pattern", `${elementId}: 'pattern: grid' needs 'columns:' -- how many copies per row`,
        b.doc.span(node, "pattern"), { notes: ["'count:' is the total, so the last row may be partial"] });
      return null;
    }
    if (pattern !== "grid" && columns !== null) {
      b.bag.error("pattern", `${elementId}.columns: read only by 'pattern: grid'`, b.doc.span(node, "columns"));
      return null;
    }
    const [stepDegrees, startDegrees, stepPosition] = steps;

    const rawSkip = Array.isArray(node.get("skip")) ? node.get("skip") as number[] : [];
    const skip = [...new Set(rawSkip.map((i) => Math.trunc(num(i))))].sort((x, y) => x - y);
    const outOfRange = skip.filter((i) => i >= count);
    if (outOfRange.length > 0) {
      b.bag.error("pattern", `${elementId}.skip: index` + (outOfRange.length > 1 ? "es" : "")
        + ` ${outOfRange.join(", ")} out of range for 'count: ${count}' (0..${count - 1})`, b.doc.span(node, "skip"));
      return null;
    }
    const skipEvery = (node.get("skip_every") ?? null) as number | null;
    if (skipEvery !== null && skipEvery > count) {
      b.bag.error("pattern", `${elementId}.skip_every: ${skipEvery} is greater than 'count: ${count}', so it skips nothing`,
        b.doc.span(node, "skip_every"));
      return null;
    }
    if (drawnCopies(count, skip, skipEvery).length === 0) {
      b.bag.error("pattern", `${elementId}: 'skip:'/'skip_every:' leave every copy undrawn`,
        b.doc.span(node, "skip_every") ?? b.doc.span(node, "skip") ?? common.span,
        { notes: ["remove the element, or skip fewer copies"] });
      return null;
    }

    const parts: AnyHandPart[] = [];
    // `copy`, the index of the copy being drawn, exists only here: the generated loop's own index.
    b.scope.define(expr.COPY, { value: new expr.Value("number"), code: PATTERN_LOOP_INDEX });
    let elementColor: Expression | null, colorFailed: boolean, ok: boolean;
    try {
      // Any source is allowed here: `checkPatternAbsence` polices absence for the whole element.
      [elementColor, colorFailed] = b.ownedColor(node, elementId, false);
      ok = !colorFailed;
      (Array.isArray(node.get("parts")) ? node.get("parts") as Data[] : []).forEach((rawPart, index) => {
        const part = b.buildHandPart(rawPart as Node, elementId, index, elementColor, colorFailed, "pattern");
        if (part === null) {
          ok = false;
          return;
        }
        parts.push(part);
      });
    } finally {
      b.scope.bindings.delete(expr.COPY);
    }
    if (!ok || !renderPatternTexts(b, elementId, parts, count)) return null;

    const colors: Expression[] = [];
    dedupAppend(colors, elementColor);
    for (const part of parts) {
      dedupAppend(colors, part.color);
      if (part.shape === "text" && part.outline !== null) dedupAppend(colors, part.outline.color);
    }
    const element = PatternElement.create({
      ...common,
      pattern,
      count,
      step_angle: stepDegrees,
      start_angle: startDegrees,
      step: stepPosition,
      columns,
      skip,
      skip_every: skipEvery,
      parts,
      color: elementColor,
      colors,
      absent: (node.get("absent") ?? null) as string | null,
    });
    checkPatternAbsence(b, node, element);
    return element;
  }

  override resolve(r: Resolver, element: PatternElement, parent: Box, depth: number): Placed {
    const [cx, cy] = r.point(element.at, parent);
    const center: [number, number] = [round(cx), round(cy)];
    let [parts, reach] = r.resolveParts(element.parts, element.id, element.resolved_min_1px);
    let start: number, step: number, dx = 0, dy = 0;
    if (element.pattern === "radial") {
      [start, step] = [element.start_angle, element.step_angle];
    } else {
      start = step = 0.0;
      reach = 0.0; // only a radial pattern reports a disc
      const stepPosition = element.step ?? new Position();
      dx = roundHalfAway(r.length(stepPosition.dx, parent, "x", 0));
      dy = roundHalfAway(r.length(stepPosition.dy, parent, "y", 0));
    }
    const aodThickness = r.aodExtent(element, "thickness", parent, 1);
    const placed = PlacedPattern.create({
      element, box: new IntBox(0, 0, 0, 0), center, depth, parts, copies: element.drawnIndices(), start, step, dx, dy,
      columns: element.columns ?? 0, reach, aod_thickness: aodThickness,
    });
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity, textReach = 0.0;
    for (const index of placed.copies) {
      const [ox, oy, s, c] = placed.transform(index);
      for (const part of parts) {
        let bounds: [number, number, number, number];
        if (part.shape === "text") {
          const ink = patternTextInk(part, ox, oy, s, c, index, start, step, r.device);
          bounds = ink.bounds();
          // The real ink's farthest point, not its AABB's corners.
          if (element.pattern === "radial") textReach = Math.max(textReach, ink.reach(center[0], center[1]));
        } else {
          bounds = patternPartInk(part, ox, oy, s, c, index, 0.0, 0.0, r.device);
        }
        minX = Math.min(minX, bounds[0]);
        minY = Math.min(minY, bounds[1]);
        maxX = Math.max(maxX, bounds[2]);
        maxY = Math.max(maxY, bounds[3]);
      }
    }
    const box = minX > maxX ? new Box(cx, cy, 0, 0) : new Box(minX, minY, maxX - minX, maxY - minY);
    placed.box = box.rounded();
    if (textReach > placed.reach) placed.reach = textReach;
    return placed;
  }

  override textRuns(element: PatternElement): TextRun[] {
    // Every drawn copy's string is known at build time, so a text part's font needs exactly those.
    const drawn = element.drawnIndices();
    const runs: TextRun[] = [];
    element.parts.forEach((part, index) => {
      if (part.shape !== "text" || !part.font_is_custom) return;
      const samples = drawn.map((i) => part.texts[i]!);
      runs.push(new TextRun(`${element.id}.parts[${index}]`, part.font, {
        glyphs: new Set(samples.join("")), samples, part_index: index, span: part.span, unsupported: part.unsupported, curve: part.curve,
      }));
    });
    return runs;
  }

  override circularExtent(placed: Placed): [number, number, number] | null {
    const p = placed as PlacedPattern;
    return p.element.pattern === "radial" ? [p.center[0], p.center[1], p.reach] : null;
  }

  override aodRefusal(key: string): Refusal | null {
    if (key === "font") {
      return ["aod", "a pattern's 'aod: {font: ...}' override is not implemented yet",
        ["restyle this pattern's colour/thickness in AOD instead, or drop the font override for now"]];
    }
    return null;
  }

  override lower(ctx: DrawContext, placed: Placed): Op[] {
    const p = placed as PlacedPattern;
    const element = p.element;
    const aod = ctx.aod;
    const prefix = constPrefix(p.id);
    const override = p.aod_thickness !== null ? Const(`${prefix}_AOD_THICKNESS`, p.aod_thickness) : null;
    const live = p.parts.map((part, index): [number, ResolvedHandPart] => [index, part]).filter(([index]) => {
      const visible = element.parts[index]!.visible;
      return !(visible !== null && visible.isConstant);
    });
    const radial = element.pattern === "radial";
    const i = NumLocal("i");
    const ops: Op[] = [];
    if (radial) ops.push(Let("cx", Const(`${prefix}_X`, p.center[0])), Let("cy", Const(`${prefix}_Y`, p.center[1])));

    const textFonts = new Map<string, string>();
    const vectorTextFonts = new Set<string>();
    for (const [, part] of live) {
      if (part.shape === "text" && part.font.is_custom && !textFonts.has(part.font.reference)) {
        textFonts.set(part.font.reference, `font${textFonts.size}`);
        if (part.font.is_vector) vectorTextFonts.add(part.font.reference);
      }
    }
    for (const [reference, local] of textFonts) {
      ops.push(LoadFont(local, `_${fontField(reference)}`, { onNull: vectorTextFonts.has(reference) ? "none" : "return" }), Blank());
    }

    const paints = live.map(([, part]) => AodPart(element, part.color));
    const codes = paints.map((paint) => colorCode(paint, aod));
    const distinct = [...new Set(codes)];
    const perCopy = live.some(([, part]) => part.color !== null && expr.readsCopy(part.color.ast));
    let stamp: [Paint, number] | null = null;
    if (ctx.ring !== null) stamp = [RingColor(), ctx.ring.width];
    else if (element.outline !== null) stamp = [AodDimmed(element, element.outline.color), element.outline.width];
    const hoistColor = distinct.length === 1 && !perCopy && stamp === null;
    const penParts = live.filter(([, part]) => part.shape === "line" || (part.shape === "circle" && !part.filled));
    const hasArc = live.some(([, part]) => part.shape === "arc");
    const hoistPen = penParts.length > 0 && !hasArc
      && new Set(penParts.map(([, part]) => (part as { thickness: number }).thickness)).size === 1;
    const pen = (index: number, part: ResolvedHandPart): AodPick =>
      AodPick(Const(`${prefix}_${index}_THICKNESS`, "thickness" in part ? part.thickness : 1), override);

    if (hoistColor) ops.push(SetColor(paints[0]!, "hoisted: one colour"));
    if (hoistPen) ops.push(SetPen(pen(...penParts[0]!), "hoisted: one pen, no arc"));

    const body: Op[] = [];
    const skip = patternSkipTerms(element);
    if (skip.length > 0) body.push(If(AnyOf(skip), [Continue()]));
    if (radial) {
      if (patternNeedsMath(p)) {
        const [angle, note] = patternAngle(element);
        body.push(Let("angle", angle, note), Let("sin", Call("Math.sin", [NumLocal("angle")])), Let("cos", Call("Math.cos", [NumLocal("angle")])));
      }
    } else {
      const x0 = Const(`${prefix}_X`, p.center[0]), y0 = Const(`${prefix}_Y`, p.center[1]);
      const dx = Const(`${prefix}_DX`, p.dx), dy = Const(`${prefix}_DY`, p.dy);
      if (element.pattern === "grid") {
        const columns = Lit(element.columns!);
        body.push(Let("ox", Bin("+", x0, Bin("*", Paren(Bin("%", i, columns)), dx))),
          Let("oy", Bin("+", y0, Bin("*", Paren(Bin("/", i, columns)), dy))));
      } else {
        body.push(Let("ox", Bin("+", x0, Bin("*", i, dx))), Let("oy", Bin("+", y0, Bin("*", i, dy))));
      }
    }

    const parts = (ring: number | null): Op[] => {
      const out: Op[] = [];
      let current = hoistColor ? codes[0]! : null;
      live.forEach(([index, part], k) => {
        if (ring === null && !hoistColor && codes[k] !== current) {
          out.push(SetColor(paints[k]!));
          current = codes[k]!;
        }
        const drawn = lowerPart(element, prefix, index, part, radial, hoistPen, textFonts, pen(index, part), stamp, ring);
        const visible = element.parts[index]!.visible;
        if (visible !== null) out.push(Comment(`visible: ${visible.text}`), If(Truthy(visible), drawn));
        else out.push(...drawn);
      });
      return out;
    };
    if (stamp !== null) body.push(SetColor(stamp[0]), ...parts(stamp[1]));
    if (ctx.ring === null) body.push(...parts(null));
    ops.push(For("i", Lit(element.count), body, true));
    if (hoistPen) ops.push(SetPen(null));
    return ops;
  }

  override layoutConstants(prefix: string, placed: Placed): lc.Constants {
    const p = placed as PlacedPattern;
    const radial = p.element.pattern === "radial";
    const out: lc.Constants = [
      [`${prefix}_X`, p.center[0], radial ? "the centre every copy turns about" : "copy 0's origin"],
      [`${prefix}_Y`, p.center[1], ""],
    ];
    if (!radial) {
      out.push([`${prefix}_DX`, p.dx, p.element.pattern === "grid" ? "step between columns, whole pixels" : "step between copies, whole pixels"],
        [`${prefix}_DY`, p.dy, ""]);
    }
    out.push(...lc.aodThicknessConstant(prefix, p, lc.EVERY_PART_NOTE));
    p.parts.forEach((part, index) => out.push(...lc.handPartConstants(`${prefix}_${index}`, "template", index, part)));
    return out;
  }
}

register(new PatternKind());
