// `type: gauge`: a value's fraction of a range, as an arc, a bar, a needle,
// segments or a scale, or the reading of a `config: slots:` slot. Port of
// wfb/kinds/gauge.py's build half.
import * as catalog from "../catalog.ts";
import * as complications from "../complications.ts";
import type { Data, DataKey } from "../edit/yaml.ts";
import * as expr from "../expr.ts";
import type { Builder } from "../ir/builder/index.ts";
import { type AnyHandPart, type Element, Expression, Gauge, HOLD_AUTO } from "../ir/model.ts";
import { arcBox, type Placed, PlacedGauge, type Resolver, rotatableParts, strokePad } from "../layout.ts";
import { degrees, formatG, isNumber, num, repr, roundHalfEven as round, str } from "../py.ts";
import { Box, IntBox } from "../units.ts";
import { type Common, type ContrastSubject, ElementKind, type LiveHandle, type LiveHandleInput, register } from "./base.ts";
import { resolveSlotReference } from "./data.ts";
import {
  AodDimmed, AodPart, AodPick, AodRestyled, ArcProgress, ArcSpan, Assign, Bin, Blank, Call, Cmp, Comment, type Cond, Const, Conv,
  type DrawContext, FloatLit, For, Grown, If, Let, LetAutoScale, LetSlotPick, Lit, LocalsSet, NotPulsing, type Num, NumLocal,
  NumPick, type Op, type Paint, PaintPick, Paren, Part, Present, Primitive, Read, RingColor, SetColor, Shifted,
} from "../draw/program.ts";
import { flt } from "../draw/barrel.ts";
import { colorCode } from "../draw/printer.ts";
import { article, constPrefix } from "../emit/monkeyc/common.ts";
import * as lc from "../emit/monkeyc/layout_constants.ts";
import { discPerimeterOffsets } from "../ir/model.ts";
import { configDataIds, configField } from "../ir/naming.ts";
import type { RotatablePart } from "../layout.ts";
import { radians } from "../py.ts";
import { DATA_SAMPLE, SAMPLE_GOALS, SAMPLE_HEART_RATE_ZONES, SAMPLE_WEARER_AGE, SAMPLE_WEARER_SEX } from "../sample.ts";
import * as vocab from "../vocab.ts";

type Node = Map<DataKey, Data>;

/** A gauge's `absent: {value:}` is a fill fraction, so a constant one must be 0.0-1.0. */
function checkFallbackFraction(b: Builder, node: Node, element: Gauge): void {
  const fallback = element.fallback;
  if (element.absent !== "fallback" || fallback === null || !fallback.isConstant) return;
  let value: number;
  try {
    const n = expr.asNumber(fallback.constant);
    value = typeof n === "bigint" ? Number(n) : isNumber(n) ? num(n) : NaN;
  } catch (error) {
    if (error instanceof TypeError) return;
    throw error;
  }
  if (0.0 <= value && value <= 1.0) return;
  b.bag.error("when-absent", `${element.id}: a gauge's 'absent: {value:}' is a fill fraction, so it must `
    + `be between 0.0 and 1.0 -- got ${fallback.shown}`, b.fallbackSpan(node), {
    notes: [
      "unlike a text's 'absent: {value:}', which supplies the value and is "
      + "then formatted, a gauge's supplies the filled proportion "
      + "directly: either the value or the max can be the absent reading, "
      + "so the outcome is the only well-defined thing to substitute",
      "for 'half full' write 0.5, not the reading you would have shown",
    ],
  });
}

/** What a gauge with `slot:` does not read, and why. */
const NOT_BESIDE_SLOT: ReadonlyMap<string, string> = new Map([
  ["max", "the scale is the picked metric's own, and one 'max:' cannot fit every choice the wearer has"],
  ["bands", "'bands:' are fractions of one fixed scale; zones from the picked metric's own bands are not implemented yet"],
]);

/** The complication type `max: auto` scales by, or `null` with the reason reported. */
function autoScaleType(b: Builder, node: Node, elementId: string, value: Expression | null): string | null {
  if (value === null) return null; // the value's own error is already reported
  const ref = value.ast;
  if (ref === null || ref.kind !== "ref" || !ref.path.startsWith("complication.")) {
    b.bag.error("element", `${elementId}: 'max: auto' needs 'value:' to be a bare 'complication.<type>', got ${value.shown}`,
      b.doc.span(node, "max"), {
        notes: ["the scale is that complication type's own; write 'max:' as a number or an expression for anything else",
          "docs/guide/progress-and-graphs.md, \"Gauges on a slot\""],
      });
    return null;
  }
  const name = ref.path.slice("complication.".length);
  if (!complications.SCALE.has(name)) {
    b.bag.error("element", `${elementId}: 'max: auto' -- ${ref.path} has no scale of its own`, b.doc.span(node, "max"), {
      notes: ["types with one: " + [...complications.SCALE.keys()].sort().join(", "),
        "write 'max:' as a number or an expression for this one"],
    });
    return null;
  }
  return name;
}

/** Refuse the keys a gauge with `slot:` does not read. */
function checkSlotKeys(b: Builder, node: Node, elementId: string): boolean {
  let ok = true;
  for (const [key, why] of NOT_BESIDE_SLOT) {
    if (node.has(key)) {
      b.bag.error("element", `${elementId}: '${key}:' is not read beside 'slot:' -- ${why}`, b.doc.span(node, key),
        { notes: ["docs/guide/progress-and-graphs.md, \"Gauges on a slot\""] });
      ok = false;
    }
  }
  return ok;
}

/** Keys a `style: needle` gauge does not read. */
const NEEDLE_UNREAD: ReadonlyMap<string, string> = new Map([
  ["radius", "the needle's length is its parts' own geometry"],
  ["thickness", "a line part's own 'thickness:' is the needle's pen width"],
  ["size", "a needle has no box; its extent is the disc it sweeps"],
  ["track_color", "a needle draws no track -- draw the dial with its own 'style: arc' gauge or a pattern"],
  ["align", "'at:' is the axis the needle turns about, not a box"],
]);

/** `style: needle`'s parts, built exactly like an analog hand's. */
function buildNeedle(b: Builder, node: Node, element: Gauge): boolean {
  let ok = true;
  for (const [key, why] of NEEDLE_UNREAD) {
    if (node.has(key)) {
      b.bag.error("element", `${element.id}: '${key}:' is not read by 'style: needle' -- ${why}`, b.doc.span(node, key));
      ok = false;
    }
  }
  const colorFailed = node.has("color") && element.color === null;
  const parts: AnyHandPart[] = [];
  (Array.isArray(node.get("needle")) ? node.get("needle") as Data[] : []).forEach((raw, index) => {
    const part = b.buildHandPart(raw as Node, `${element.id}.needle`, index, element.color, colorFailed);
    if (part === null) {
      ok = false;
      return;
    }
    parts.push(part);
  });
  element.needle = parts;
  return ok;
}

/** Keys only one style reads, and which. */
const STYLE_ONLY_KEYS: ReadonlyMap<string, string> = new Map([
  ["needle", "needle"], ["count", "segments"], ["gap", "segments"], ["bands", "scale"], ["pointer", "scale"],
]);

const ARC_KEYS = ["radius", "thickness", "start_angle", "sweep"];

/** `style: segments`/`scale`: an arc's four keys or a bar's `size:`, exactly one, then their own keys. */
function buildTicked(b: Builder, node: Node, element: Gauge): boolean {
  const style = element.style;
  const arcGiven = ARC_KEYS.filter((key) => node.has(key));
  if (arcGiven.length > 0 && node.has("size")) {
    b.bag.error("element", `${element.id}: 'style: ${style}' draws on an arc or a bar, `
      + "not both -- give an arc's radius/thickness/start_angle/sweep, or a bar's size", b.doc.span(node, "size"));
    return false;
  }
  if (arcGiven.length === 0 && !node.has("size")) {
    b.bag.error("element", `${element.id}: 'style: ${style}' needs a track -- an arc's `
      + "radius, thickness, start_angle and sweep, or a bar's size", b.doc.span(node, "style"));
    return false;
  }
  const missing = arcGiven.length > 0 ? ARC_KEYS.filter((key) => !node.has(key)) : [];
  if (missing.length > 0) {
    b.bag.error("element", `${element.id}: an arc 'style: ${style}' also needs ` + missing.map(repr).join(", "),
      b.doc.span(node, "style"));
    return false;
  }
  if (style === "segments") {
    element.count = Math.trunc(num(node.get("count") as number));
    element.gap = b.length(node, "gap");
    return true;
  }
  element.pointer = b.length(node, "pointer");
  const bands: [number, Expression][] = [];
  let previous = 0.0;
  const raws = Array.isArray(node.get("bands")) ? node.get("bands") as Node[] : [];
  for (const [index, raw] of raws.entries()) {
    const to = num(raw.get("to") as number);
    if (to <= previous) {
      b.bag.error("element", `${element.id}.bands[${index}]: 'to: ${str(raw.get("to"))}' must be `
        + `greater than the previous band's (${formatG(previous)}) -- bands run in order along the track`, b.doc.span(raw, "to"));
      return false;
    }
    const color = b.colorExpression(raw, "color");
    if (color === null) return false;
    b.checkOtherAbsence(raw, element, "bands.color", color);
    bands.push([to, color]);
    previous = to;
  }
  element.bands = bands;
  return true;
}

/** `segments`' cell and step, or `scale`'s pointer and band spans, on the track already placed. */
function resolveTicked(r: Resolver, element: Gauge, placed: PlacedGauge, parent: Box): void {
  const min1px = element.resolved_min_1px;
  const arc = element.geometry === "arc";
  const length = arc ? placed.sweep : placed.size[0];
  if (element.style === "segments") {
    let gap = r.extent(element.gap, parent, "minor", 2, null, min1px, "gap");
    if (arc) {
      gap = placed.radius > 0 ? degrees(gap / placed.radius) : 0.0;
      gap = Math.abs(gap) * (placed.sweep < 0 || Object.is(placed.sweep, -0) ? -1 : 1);
    }
    const count = element.count!;
    placed.cell = (length - (count - 1) * gap) / count;
    placed.step = placed.cell + gap;
    return;
  }
  placed.pointer = element.pointer !== null
    ? round(r.extent(element.pointer, parent, "minor", 1, null, min1px, "pointer"))
    : arc ? placed.thickness : placed.size[1];
  const spans: [number, number][] = [];
  let previous = 0.0;
  for (const [to] of element.bands) {
    if (arc) spans.push([placed.start_angle + previous * placed.sweep, (to - previous) * placed.sweep]);
    else spans.push([Math.trunc(length * previous), Math.trunc(length * to)]);
    previous = to;
  }
  placed.band_spans = spans;
  // The dot reaches past the track: grow the box the lints read, keeping the bar's own rectangle for drawing.
  const [cx, cy] = placed.center;
  if (arc) {
    const reach = placed.radius + Math.max(strokePad(placed.thickness), placed.pointer);
    placed.box = new Box(cx - reach, cy - reach, 2 * reach, 2 * reach).rounded();
  } else {
    const bar = placed.box;
    placed.rect = bar;
    const dy = Math.max(0, placed.pointer - Math.floor(bar.height / 2));
    placed.box = new IntBox(bar.x - placed.pointer, bar.y - dy, bar.width + 2 * placed.pointer, bar.height + 2 * dy);
  }
}

/** The generated module each slot gauge's scale comes from. */
export const SLOT_SCALE_MODULE = "SlotScale";

/** Whether `absent: hide` still draws this gauge's value-independent parts; a needle hides whole. */
export function keepsTrack(element: Gauge): boolean {
  return element.absent === "hide" && element.style !== "needle";
}

/** The fallback fill fraction, a Float in 0.0-1.0: a constant bare, anything else clamped on device. */
function fallbackNum(element: Gauge): Num {
  const fallback = element.fallback!;
  if (fallback.isConstant) {
    const n = expr.asNumber(fallback.constant);
    return FloatLit(typeof n === "bigint" ? Number(n) : num(n), "f");
  }
  return Conv(Call("WfbMath.clamp", [Read(fallback), FloatLit(0.0), FloatLit(1.0)]), "toFloat");
}

/** `body`, inside `if (<cond>)` when there is one. */
function wrap(cond: Cond | null, body: Op[]): Op[] {
  return cond !== null ? [If(cond, body)] : body;
}

/** One gauge's program: `lower`'s helpers, sharing the placed gauge, its constants and its paints. */
class Lowering {
  readonly ctx: DrawContext;
  readonly placed: PlacedGauge;
  readonly element: Gauge;
  readonly prefix: string;
  readonly consts: Map<string, number | import("../edit/yaml.ts").PyFloat>;
  readonly color: Paint;
  readonly track: Paint | null;
  /** The ring to draw: an outlined group's pass, else the gauge's own. */
  readonly stamp: [Paint, number] | null = null;

  constructor(ctx: DrawContext, placed: PlacedGauge, kind: GaugeKind) {
    this.ctx = ctx;
    this.placed = placed;
    this.element = placed.element;
    this.prefix = constPrefix(placed.id);
    this.consts = lc.numericConstants(kind.layoutConstants(this.prefix, placed));
    this.color = AodRestyled(this.element, "color");
    this.track = this.element.track_color !== null ? AodRestyled(this.element, "track_color") : null;
    if (ctx.ring !== null) this.stamp = [RingColor(), ctx.ring.width];
    else if (this.element.outline !== null) this.stamp = [AodDimmed(this.element, this.element.outline.color), this.element.outline.width];
  }

  c(suffix: string): Const {
    const name = `${this.prefix}_${suffix}`;
    return Const(name, this.consts.get(name)!);
  }

  thickness(): AodPick {
    return AodPick(this.c("THICKNESS"), this.placed.aod_thickness !== null ? this.c("AOD_THICKNESS") : null);
  }

  ops(): Op[] {
    const element = this.element;
    if (element.slot !== null) return this.slotGauge();
    const probes = [element.value, element.maximum].filter((e): e is Expression => e !== null);
    if (element.auto_scale !== null) {
      const ast = element.value!.ast as expr.Ref;
      const reader = catalog.READERS.get(catalog.CATALOG.get(ast.path)!.reader)!.name;
      const constant = complications.TYPES.get(element.auto_scale)!.constant;
      return [
        Comment(`max: auto -- ${ast.path}'s own scale`),
        LetAutoScale(reader, SLOT_SCALE_MODULE, constant, element.auto_scale, element.value!),
        Comment("no scale (an unset goal, no profile, ...) hides the whole gauge"),
        If(LocalsSet(["scale"]), this.bound(Call("WfbScale.share", [Read(element.value!), NumLocal("scale")]), probes)),
      ];
    }
    const fraction = Bin("/", Call("WfbMath.percent", [Read(element.value!), Read(element.maximum!)]), FloatLit(100.0));
    return this.bound(fraction, probes);
  }

  /** A gauge bound to a value: `absent:`'s policy over `fraction`, then each style's drawing. */
  bound(fraction: Num, probes: Expression[]): Op[] {
    const element = this.element;
    const guards = this.ctx.value_guards;
    const present = keepsTrack(element) && guards.length > 0 ? Present(guards, probes) : null;
    const ops: Op[] = [];
    if (element.absent === "fallback" && guards.length > 0) {
      ops.push(Comment(vocab.absent(element as never)), Let("fraction", fallbackNum(element)),
        If(Present(guards, probes), [Assign("fraction", fraction)]), Blank());
      fraction = NumLocal("fraction");
    }
    return [...ops, ...this.styles(fraction, present)];
  }

  /** A gauge on a `config: slots:` slot: the wearer's pick, against its own scale. */
  slotGauge(): Op[] {
    const element = this.element;
    const face = this.ctx.resolved.face;
    const slot = face.config_data.get(element.slot!);
    const shown = slot !== undefined ? this.ctx.shown(slot) : null;
    const sample = shown !== null ? DATA_SAMPLE.get(shown) ?? null : null;
    const scale = shown !== null ? complications.scaleFor(shown, {
      goals: SAMPLE_GOALS, heartRateZones: SAMPLE_HEART_RATE_ZONES, sex: SAMPLE_WEARER_SEX, age: SAMPLE_WEARER_AGE, value: sample,
    }) : null;
    const reading = NumLocal("reading");
    const hasReading = LocalsSet(["reading"]);
    const inner: Op[] = [Let("reading", Call("WfbScale.fraction", [NumLocal("pulled"), NumLocal("scale")]))];
    if (element.absent === "fallback") {
      inner.push(Comment(vocab.absent(element as never)), Let("fraction", NumPick(hasReading, reading, fallbackNum(element))),
        ...this.styles(NumLocal("fraction"), null));
    } else if (keepsTrack(element)) {
      inner.push(...this.styles(reading, hasReading));
    } else {
      inner.push(If(hasReading, this.styles(reading, null)));
    }
    const body: Op[] = [
      Comment(`slot: ${element.slot} -- the wearer's pick, against its own scale`),
      LetSlotPick(configField(`data_${element.slot}`), SLOT_SCALE_MODULE, this.ctx.complications_guarded, sample, scale),
      Comment("a pick with no scale hides the whole gauge, track included"),
      If(LocalsSet(["scale", "pulled"]), inner),
    ];
    return [
      Comment("the editor is animating this slot -- its drawable draws it (drawSlot)"),
      If(NotPulsing(configDataIds(face).get(element.slot!)!), body),
    ];
  }

  styles(fraction: Num, present: Cond | null): Op[] {
    const style = this.element.style;
    if (style === "needle") return this.needle(fraction);
    if (style === "segments" || style === "scale") return this.ticked(fraction, present);
    if (style === "arc") return this.arc(fraction, present);
    return this.bar(fraction, present);
  }

  arc(fraction: Num, present: Cond | null): Op[] {
    const c = (s: string): Const => this.c(s);
    const thickness = this.thickness();
    const span = (dx = 0, dy = 0): ArcSpan => ArcSpan(Shifted(c("CX"), dx), Shifted(c("CY"), dy), c("RADIUS"), thickness, c("START"), c("SWEEP"));
    const lit = (dx = 0, dy = 0): ArcProgress =>
      ArcProgress(Shifted(c("CX"), dx), Shifted(c("CY"), dy), c("RADIUS"), thickness, c("START"), c("SWEEP"), fraction);
    const ops: Op[] = [];
    if (this.stamp !== null) {
      const [paint, width] = this.stamp;
      const offsets = discPerimeterOffsets(width);
      if (this.element.track_color !== null) ops.push(SetColor(paint), ...offsets.map(([dx, dy]) => span(dx, dy)));
      else ops.push(...wrap(present, [SetColor(paint), ...offsets.map(([dx, dy]) => lit(dx, dy))]));
      if (this.ctx.ring !== null) return ops;
      ops.push(Blank());
    }
    if (this.track !== null) ops.push(Comment("the unfilled track"), SetColor(this.track), span(), Blank());
    ops.push(Comment(present === null ? "the filled portion"
      : "the filled portion -- absent: hide, so only while the value is present"));
    return [...ops, ...wrap(present, [SetColor(this.color), lit()])];
  }

  bar(fraction: Num, present: Cond | null): Op[] {
    const c = (s: string): Const => this.c(s);
    const rect = (width: Num, dx = 0, dy = 0): Primitive => Primitive("fillRectangle", [[Shifted(c("X"), dx), Shifted(c("Y"), dy), width, c("HEIGHT")]]);
    const grown = (width: Num): Op[] => {
      const [paint, ring] = this.stamp!;
      return [SetColor(paint), Primitive("fillRoundedRectangle", [
        [Grown(c("X"), ring, -1), Grown(c("Y"), ring, -1)],
        [Grown(width, ring, 2), Grown(c("HEIGHT"), ring, 2)],
        [Lit(ring)]])];
    };
    const ops: Op[] = [];
    const ringOnly = this.ctx.ring !== null;
    if (this.stamp !== null && this.element.track_color !== null) {
      ops.push(...grown(c("WIDTH")));
      if (ringOnly) return ops;
      ops.push(Blank());
    }
    if (this.track !== null) ops.push(SetColor(this.track), rect(c("WIDTH")), Blank());
    if (present !== null) ops.push(Comment("the fill -- absent: hide, so only while the value is present"));
    const filled = NumLocal("filled");
    const body: Op[] = [Let("filled", Conv(Paren(Bin("*", c("WIDTH"), fraction)), "toNumber"))];
    if (this.stamp !== null && this.element.track_color === null) {
      body.push(If(Cmp(">", filled, Lit(0)), grown(filled)));
      if (ringOnly) return [...ops, ...wrap(present, body)];
    }
    body.push(SetColor(this.color), rect(filled));
    return [...ops, ...wrap(present, body)];
  }

  ticked(fraction: Num, present: Cond | null): Op[] {
    const element = this.element, placed = this.placed;
    const c = (s: string): Const => this.c(s);
    const arc = element.geometry === "arc";
    const thickness = arc ? this.thickness() : null;
    const span = (start: Num, sweep: Num): ArcSpan => ArcSpan(c("CX"), c("CY"), c("RADIUS"), thickness!, start, sweep);
    const barRect = (x0: Num, x1: Num): Op[] => [Let("x0", x0),
      Primitive("fillRectangle", [[Bin("+", c("X"), NumLocal("x0")), c("Y"), Bin("-", x1, NumLocal("x0")), c("HEIGHT")]])];
    const i = NumLocal("i");
    if (element.style === "segments") {
      const count = element.count!;
      const litValue = Conv(Paren(Bin("+", Bin("*", Paren(fraction), Lit(count)), FloatLit(0.5))), "toNumber");
      const ops: Op[] = present === null ? [Let("lit", litValue)] : [
        Comment("absent: hide -- every cell draws unlit while the value is absent"),
        Let("lit", Lit(0)), If(present, [Assign("lit", litValue)])];
      if (this.track === null) ops.push(SetColor(this.color));
      const cell: Op[] = [];
      if (this.track !== null) cell.push(SetColor(PaintPick(Cmp("<", i, NumLocal("lit")), this.color, this.track)));
      if (arc) cell.push(span(Bin("-", c("START"), Bin("*", i, c("STEP"))), c("CELL")));
      else cell.push(...barRect(Conv(Paren(Bin("*", i, c("STEP"))), "toNumber"), Conv(Paren(Bin("+", Bin("*", i, c("STEP")), c("CELL"))), "toNumber")));
      const bound: Num = this.track === null ? NumLocal("lit") : Lit(count);
      return [...ops, For("i", bound, cell)];
    }
    const ops: Op[] = [];
    if (this.track !== null) {
      ops.push(Comment("the track"), SetColor(this.track),
        arc ? span(c("START"), c("SWEEP")) : Primitive("fillRectangle", [[c("X"), c("Y"), c("WIDTH"), c("HEIGHT")]]));
    }
    element.bands.forEach(([, bandColor], index) => {
      const band = `BAND_${index}`;
      ops.push(Comment(`band ${index}`), SetColor(AodDimmed(element, bandColor)));
      if (arc) ops.push(span(c(`${band}_START`), c(`${band}_SWEEP`)));
      else ops.push(Primitive("fillRectangle", [[Bin("+", c("X"), c(`${band}_X0`)), c("Y"), Bin("-", c(`${band}_X1`), c(`${band}_X0`)), c("HEIGHT")]]));
    });
    ops.push(Comment(present === null ? "the pointer" : "the pointer -- absent: hide, so only while the value is present"));
    const pointer: Op[] = [SetColor(this.color)];
    if (arc) {
      const angle = NumLocal("angle");
      const offset = (fn: string): Conv => Conv(Call("Math.round", [Bin("*", c("RADIUS"), Call(fn, [angle]))]), "toNumber");
      pointer.push(
        Let("angle", Bin("+", FloatLit(radians(placed.start_angle)), Bin("*", Paren(fraction), FloatLit(radians(placed.sweep))))),
        Primitive("fillCircle", [[Bin("+", c("CX"), offset("Math.sin"))], [Bin("-", c("CY"), offset("Math.cos"))], [c("POINTER")]]),
      );
    } else {
      pointer.push(Primitive("fillCircle", [
        [Bin("+", c("X"), Conv(Paren(Bin("*", c("WIDTH"), Paren(fraction))), "toNumber"))],
        [Bin("+", c("Y"), Bin("/", c("HEIGHT"), Lit(2)))],
        [c("POINTER")]]));
    }
    return [...ops, ...wrap(present, pointer)];
  }

  needle(fraction: Num): Op[] {
    const element = this.element, placed = this.placed, prefix = this.prefix;
    const c = (s: string): Const => this.c(s);
    const angle = NumLocal("angle");
    const ops: Op[] = [
      Let("cx", c("CX")), Let("cy", c("CY")),
      Let("angle", Bin("+", FloatLit(radians(placed.start_angle)), Bin("*", Paren(fraction), FloatLit(radians(placed.sweep))))),
      Let("sin", Call("Math.sin", [angle])),
      Let("cos", Call("Math.cos", [angle])),
    ];
    const asleep = placed.aod_thickness !== null ? Const(`${prefix}_AOD_THICKNESS`, placed.aod_thickness) : null;
    const pen = (partPrefix: string, part: RotatablePart): AodPick =>
      AodPick(Const(`${partPrefix}_THICKNESS`, "thickness" in part ? part.thickness : 1), asleep);
    const parts = placed.needle.map((part, index): [string, RotatablePart] => [`${prefix}_NEEDLE_${index}`, part]);
    if (this.stamp !== null) {
      const [paint, width] = this.stamp;
      ops.push(SetColor(paint));
      for (const [partPrefix, part] of parts) ops.push(Part(part, partPrefix, true, pen(partPrefix, part), { ring: width }));
      if (this.ctx.ring !== null) return ops;
    }
    let current: string | null = null;
    for (const [partPrefix, part] of parts) {
      const paint = AodPart(element, part.color);
      const code = colorCode(paint, this.ctx.aod);
      if (code !== current) {
        ops.push(SetColor(paint));
        current = code;
      }
      ops.push(Part(part, partPrefix, true, pen(partPrefix, part)));
    }
    return ops;
  }
}

class GaugeKind extends ElementKind<Gauge> {
  readonly name = "gauge";
  readonly irClass = Gauge;
  override readonly antialiased = true;
  override readonly ringed = true;

  override ringRefusal(element: Gauge): string | null {
    if (element.style === "segments" || element.style === "scale") return `on a 'style: ${element.style}' gauge is not implemented yet`;
    return null;
  }

  override resolve(r: Resolver, element: Gauge, parent: Box, depth: number): Placed {
    const [cx, cy] = r.point(element.at, parent);
    const min1px = element.resolved_min_1px;
    if (element.geometry === "arc") {
      const radius = round(r.extent(element.radius, parent, "minor", 0, null, min1px, "radius"));
      const thickness = Math.max(1, round(r.extent(element.thickness, parent, "minor", 1, null, min1px, "thickness")));
      const [box, ax, ay, start, sweep, garminStart, direction] = arcBox(radius, thickness, cx, cy, element.align, element.vertical_align,
        element.start_angle, element.sweep);
      const aodThickness = r.aodExtent(element, "thickness", parent, 1);
      const placed = PlacedGauge.create({
        element, box, center: [round(ax), round(ay)], depth, radius, thickness, start_angle: start, sweep,
        garmin_start: garminStart, garmin_direction: direction, aod_thickness: aodThickness,
      });
      if (element.style === "segments" || element.style === "scale") resolveTicked(r, element, placed, parent);
      return placed;
    }
    if (element.style === "needle") {
      const [parts, reach] = r.resolveParts(element.needle, `${element.id}.needle`, min1px);
      const disc = new Box(cx - reach, cy - reach, 2 * reach, 2 * reach);
      return PlacedGauge.create({
        element, box: disc.rounded(), center: [round(cx), round(cy)], depth,
        start_angle: element.start_angle!.degrees, sweep: element.sweep!.degrees,
        needle: rotatableParts(parts, `${element.id}.needle`), reach, aod_thickness: r.aodExtent(element, "thickness", parent, 1),
      });
    }
    const [sized, sx, sy] = r.sizedBox(element, parent, cx, cy);
    const placed = PlacedGauge.create({
      element, box: sized.rounded(min1px), center: [round(sx), round(sy)], depth, size: [round(sized.width), round(sized.height)],
    });
    if (element.style === "segments" || element.style === "scale") resolveTicked(r, element, placed, parent);
    return placed;
  }

  override circularExtent(placed: Placed): [number, number, number] | null {
    const p = placed as PlacedGauge;
    if (p.element.geometry === "arc") return [p.center[0], p.center[1], p.radius + Math.max(p.thickness / 2.0, p.pointer)];
    if (p.element.style === "needle") return [p.center[0], p.center[1], p.reach];
    return null;
  }

  build(b: Builder, node: Node, common: Common): Element | null {
    let slot = null;
    if (node.has("slot")) {
      slot = resolveSlotReference(b, str(node.get("slot")), b.doc.span(node, "slot"));
      if (slot === null || !checkSlotKeys(b, node, common.id)) return null;
    }
    const rawMax = node.get("max");
    const auto = slot === null && typeof rawMax === "string" && rawMax.trim() === "auto";
    const value = slot === null ? b.expression(node, "value") : null;
    const maximum = slot === null && !auto ? b.expression(node, "max") : null;
    const [align, verticalAlign] = b.alignment(node);
    const absence = b.absence(node);
    const autoScale = auto ? autoScaleType(b, node, common.id, value) : null;
    const radius = b.length(node, "radius");
    const thickness = b.length(node, "thickness");
    const startAngle = b.angle(node, "start_angle");
    const sweep = b.angle(node, "sweep");
    const size = b.size(node.get("size"));
    const color = b.colorExpression(node, "color");
    const trackColor = b.colorExpression(node, "track_color");
    const element = Gauge.create({
      ...common,
      style: node.get("style") as string,
      value,
      maximum,
      slot: slot !== null ? slot.name : null,
      auto_scale: autoScale,
      radius, thickness, start_angle: startAngle, sweep, size, color, track_color: trackColor,
      absent: absence.absent,
      fallback: absence.fallback,
      align,
      vertical_align: verticalAlign,
    });
    for (const [name, bound] of [["value", value], ["max", maximum]] as const) {
      if (bound && !catalog.isNumeric(bound.value.type)) {
        b.bag.error("type", `gauge ${name} must be a number, got ${bound.value}`, b.doc.span(node, name));
      }
    }
    if (auto && element.auto_scale === null) return null;
    if (slot !== null) {
      // The wearer's pick can always be absent: no reading yet, or a type this watch does not have.
      const reading = Expression.create({ text: `the reading of slot ${slot.name}`, code: "", value: new expr.Value("number", true) });
      b.checkAbsence(node, element, reading, element.absent, null, element.fallback, "slot");
      checkFallbackFraction(b, node, element);
      if (element.on_hold === HOLD_AUTO) {
        b.bag.error("on-hold", `${element.id}: 'on_hold: auto' on a gauge with 'slot:' is not implemented yet`,
          b.doc.span(node, "on_hold"), {
            notes: ["put 'on_hold: auto' on the slot's 'type: data' element, which launches whatever the wearer picked"],
          });
        return null;
      }
    } else if (value !== null || maximum !== null) {
      const combined = new expr.Value("number", Boolean((value && value.nullable) || (maximum && maximum.nullable)));
      const probe = Expression.create({ text: "value/max", code: "", value: combined });
      b.checkAbsence(node, element, probe, element.absent, null, element.fallback, "value");
      checkFallbackFraction(b, node, element);
    }
    for (const [key, owner] of STYLE_ONLY_KEYS) {
      if (node.has(key) && element.style !== owner) {
        b.bag.error("element", `${element.id}: '${key}:' is read only by 'style: ${owner}'`, b.doc.span(node, key));
        return null;
      }
    }
    if (element.style === "needle") {
      if (!buildNeedle(b, node, element)) return null;
    } else if (element.style === "segments" || element.style === "scale") {
      if (!buildTicked(b, node, element)) return null;
    }
    b.checkOtherAbsence(node, element, "color", element.color);
    b.checkOtherAbsence(node, element, "track_color", element.track_color);
    b.checkReachableSubstitute(node, element, "'color'/'track_color'", [element.value, element.maximum],
      [element.color, element.track_color]);
    return element;
  }

  override lower(ctx: DrawContext, placed: Placed): Op[] {
    return new Lowering(ctx, placed as PlacedGauge, this).ops();
  }

  override drawsWhileAbsent(element: Gauge): boolean {
    return keepsTrack(element);
  }

  override liveHandle(placed: Placed, handle: LiveHandleInput): LiveHandle | null {
    const element = placed.element as Gauge;
    if (element.style !== "arc") return null;
    const prefix = constPrefix(placed.id);
    const key = (Array.isArray(handle.key) ? handle.key : [handle.key]).join(".");
    if (handle.kind === "angle") return { angle: key === "start_angle" ? `${prefix}_START` : `${prefix}_SWEEP` };
    const centred = (element.align ?? "center") === "center" && (element.vertical_align ?? "center") === "center";
    if (handle.kind === "size" && key === "radius" && centred) return { consts: { [`${prefix}_RADIUS`]: 1 } };
    return null;
  }

  override layoutConstants(prefix: string, placed: Placed): lc.Constants {
    const p = placed as PlacedGauge;
    const element = p.element;
    const out: lc.Constants = [[`${prefix}_CX`, p.center[0], ""], [`${prefix}_CY`, p.center[1], ""]];
    if (element.geometry === "arc") {
      out.push(...lc.arcConstants(prefix, p), ...lc.aodThicknessConstant(prefix, p));
    } else if (element.style === "needle") {
      out.push(...lc.aodThicknessConstant(prefix, p, lc.EVERY_PART_NOTE));
      p.needle.forEach((part, index) => out.push(...lc.handPartConstants(`${prefix}_NEEDLE_${index}`, "needle", index, part)));
    } else {
      out.push(...lc.boxConstants(prefix, p.rect ?? p.innerBox));
    }
    if (element.style === "segments") {
      const unit = element.geometry === "arc" ? "degrees" : "px";
      out.push([`${prefix}_CELL`, flt(p.cell), `one cell, ${unit}`], [`${prefix}_STEP`, flt(p.step), `cell start to cell start, ${unit}`]);
    } else if (element.style === "scale") {
      out.push([`${prefix}_POINTER`, p.pointer, "the value dot's radius"]);
      p.band_spans.forEach(([a, b], index) => {
        if (element.geometry === "arc") {
          out.push([`${prefix}_BAND_${index}_START`, flt(90.0 - a), `${formatG(a)}deg clockwise from 12 o'clock, in Garmin's convention`],
            [`${prefix}_BAND_${index}_SWEEP`, flt(b), "clockwise-positive degrees"]);
        } else {
          out.push([`${prefix}_BAND_${index}_X0`, Math.trunc(a), "px from the bar's left"], [`${prefix}_BAND_${index}_X1`, Math.trunc(b), ""]);
        }
      });
    }
    return out;
  }

  override contrastSubjects(placed: Placed): ContrastSubject[] {
    const p = placed as PlacedGauge;
    if (p.element.style !== "needle") return super.contrastSubjects(placed);
    const ring = p.element.outline !== null ? p.element.outline.color : null;
    return p.needle.map((part, index): ContrastSubject => [`${p.id}.needle[${index}]`, part.color, ring, true]);
  }

  override describe(placed: Placed): string {
    return article(`${(placed as PlacedGauge).element.style} gauge`);
  }
}

register(new GaugeKind());
