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
  type AnyHandPart, drawnCopies, type Element, type Expression, PATTERN_LOOP_INDEX, PatternElement, type Position,
  ROLE_COLOR, ROLE_PART_VISIBLE,
} from "../ir/model.ts";
import { deepEqual, formatG, num } from "../py.ts";
import { type Common, ElementKind, type Refusal, register } from "./base.ts";

type Node = Map<DataKey, Data>;

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

  override aodRefusal(key: string): Refusal | null {
    if (key === "font") {
      return ["aod", "a pattern's 'aod: {font: ...}' override is not implemented yet",
        ["restyle this pattern's colour/thickness in AOD instead, or drop the font override for now"]];
    }
    return null;
  }
}

register(new PatternKind());
