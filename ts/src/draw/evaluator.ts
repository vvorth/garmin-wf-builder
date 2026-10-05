// Backend 2: a draw program painted on the host. Port of
// wfb/draw/evaluator.py.
//
// It emulates the `Dc` calls a program makes on the preview's own
// `Renderer`: its canvas, its glyph sources and its sample readings. A
// barrel call is computed with its transcription (`barrel.ts`), so an arc
// covers the degrees the watch's `drawArc` covers.
import type { ExprValue } from "../expr.ts";
import * as expr from "../expr.ts";
import * as complications from "../complications.ts";
import * as formatting from "../formatting.ts";
import * as icons from "../icons.ts";
import type { Expression } from "../ir/model.ts";
import { discPerimeterOffsets } from "../ir/model.ts";
import type { Renderer, RGB } from "../preview.ts";
import { arc as pillowArcDraw, polygon, primitive as pillowPrimitive } from "../raster/pillow.ts";
import { str, truthy } from "../py.ts";
import { SAMPLE_GOALS, SAMPLE_HEART_RATE_ZONES, SAMPLE_WEARER_AGE, SAMPLE_WEARER_SEX } from "../sample.ts";
import type { BakedFont, GlyphBox } from "../fonts/bmfont.ts";
import * as barrel from "./barrel.ts";
import { flt, isFloat, Pulled, val } from "./barrel.ts";
import {
  type Cond, FillPolygon, type Font, type For, Lit, type Num, type Op, type Paint, Primitive, type PyNum, SetPen, type Str,
  type Part, type SeriesDraw, type SlotText, type LetAutoScale, type ArcSpan, type ArcProgress, type Text, type Glyph,
} from "./program.ts";

/** The sample readings, by catalogue path. */
export type Values = ReadonlyMap<string, ExprValue>;

/** A guard or a `Return` ended the element: it draws nothing more. */
export class Stop extends Error {}

/** A `Continue`: the next turn of the innermost `For`. */
class Next extends Error {}

/** How tightly each operator a `Bin` prints binds, as Monkey C parses it. */
const PRECEDENCE: Record<string, number> = { "*": 2, "/": 2, "%": 2, "+": 1, "-": 1 };

/** A program local: a number, a string, a pulled complication, a scale, a series, or absent. */
export type LocalValue = unknown;

/** A bound expression at the sample readings: its value, or `null` when absent. */
export function readValue(e: Expression, values: Values): ExprValue {
  if (e.constant !== null) return e.constant;
  if (e.ast === null) return null;
  return expr.evaluate(e.ast, values);
}

/** A reading as a number the program computes with. */
function asNum(value: unknown): PyNum {
  const n = expr.asNumber(value);
  return typeof n === "bigint" ? Number(n) : n;
}

/** One Monkey C operator on two numbers: two `Number`s stay whole, and `/` and `%` on them truncate. */
function arith(a: PyNum | null, op: string, b: PyNum | null): PyNum | null {
  if (a === null || b === null) return null;
  const whole = !isFloat(a) && !isFloat(b);
  const x = val(a), y = val(b);
  if (op === "+") return whole ? x + y : flt(x + y);
  if (op === "-") return whole ? x - y : flt(x - y);
  if (op === "*") return whole ? x * y : flt(x * y);
  if (op === "/") return whole ? Math.trunc(x / y) : flt(x / y);
  if (whole) return barrel.mcMod(x, y);
  return flt(x % y);
}

/** The host's `dc.getTextWidthInPixels`/`dc.getFontHeight`: a baked sheet's metrics, else the device face's. */
export class Measure {
  readonly renderer: Renderer;

  constructor(renderer: Renderer) {
    this.renderer = renderer;
  }

  textWidth(text: string, font: Font): number {
    const r = this.renderer;
    const baked = font.baked !== null ? r.resolved.fonts.get(font.baked) : undefined;
    if (baked !== undefined) return baked.measure(text)[0];
    if (font.metric !== null) return r.resolved.device.db.measure.measure(text, font.metric)[0];
    return 0;
  }

  fontHeight(font: Font): number {
    const r = this.renderer;
    const baked = font.baked !== null ? r.resolved.fonts.get(font.baked) : undefined;
    if (baked !== undefined) return Math.trunc(baked.line_height);
    if (font.metric !== null) return Math.trunc(r.resolved.device.db.measure.lineHeight(font.metric));
    return font.px;
  }
}

/** `n` on this device, in the always-on frame when `aod`: a number, or `null` when a reading in it is absent. */
export function numValue(n: Num, aod = false, env: ReadonlyMap<string, LocalValue> = new Map(), values: Values = new Map(),
  measure: Measure | null = null): PyNum | null {
  const value = (m: Num): PyNum | null => numValue(m, aod, env, values, measure);
  switch (n.t) {
    case "TextWidth": {
      if (measure === null) throw new Error("a text measurement evaluated without a renderer");
      const text = strValue(n.text, values, env, aod);
      return text !== null ? measure.textWidth(text, n.font) : null;
    }
    case "FontHeight":
      if (measure === null) throw new Error("a text measurement evaluated without a renderer");
      return measure.fontHeight(n.font);
    case "Const": case "Lit": return n.value;
    case "FloatLit": return flt(n.value);
    case "NumLocal": return env.get(n.name) as PyNum | null;
    case "Read": {
      const found = readValue(n.expr, values);
      return found === null ? null : asNum(found);
    }
    case "AodPick": return value(aod && n.asleep !== null ? n.asleep : n.awake);
    case "Paren": return value(n.inner);
    case "Call": {
      const args = n.args.map(value);
      if (args.some((arg) => arg === null)) return null;
      return barrel.CALLS.get(n.fn)!(...(args as PyNum[]));
    }
    case "Conv": {
      const inner = value(n.inner);
      if (inner === null) return null;
      return n.method === "toNumber" ? barrel.toNumber(inner) : flt(val(inner));
    }
    case "NumPick": return value(condValue(n.cond, aod, env, values) ? n.then : n.otherwise);
    case "FontDrop": return value(n.base);
    case "HandAngle": {
      const unit = (u: string): number => Math.trunc(val(asNum(values.get(`time.${u}`) || 0)));
      return flt(barrel.HAND_ANGLES.get(n.hand)!(unit("hour"), unit("minute"), unit("second")));
    }
    default: {
      // A chain of infix operators, printed bare: evaluate it the way Monkey
      // C parses the printed text, not the way the tree nests.
      const terms: (PyNum | null)[] = [];
      const ops: string[] = [];
      flatten(n, terms, ops, value);
      for (const level of [2, 1]) {
        let i = 0;
        while (i < ops.length) {
          if (PRECEDENCE[ops[i]!] === level) {
            terms.splice(i, 2, arith(terms[i]!, ops[i]!, terms[i + 1]!));
            ops.splice(i, 1);
          } else {
            i++;
          }
        }
      }
      return terms[0]!;
    }
  }
}

/** `n`'s printed infix chain as its terms and operators. */
function flatten(n: Num, terms: (PyNum | null)[], ops: string[], value: (m: Num) => PyNum | null): void {
  if (n.t === "Bin") {
    flatten(n.a, terms, ops, value);
    ops.push(n.op);
    flatten(n.b, terms, ops, value);
  } else if (n.t === "Shifted" && n.by !== 0) {
    flatten(n.base, terms, ops, value);
    ops.push(n.by > 0 ? "+" : "-");
    terms.push(Math.abs(n.by));
  } else if (n.t === "Grown") {
    flatten(n.base, terms, ops, value);
    const amount = n.by * n.times;
    ops.push(amount >= 0 ? "+" : "-");
    terms.push(Math.abs(amount));
  } else if (n.t === "Shifted") {
    flatten(n.base, terms, ops, value);
  } else {
    terms.push(value(n));
  }
}

/** Python's `a == b` between two program numbers (or absences). */
function numEquals(a: PyNum | null, b: PyNum | null): boolean {
  if (a === null || b === null) return a === b;
  return val(a) === val(b);
}

/** Whether `c` holds on the host, in a sleeping frame when `asleep` (the always-on frame is one). */
export function condValue(c: Cond, aod = false, env: ReadonlyMap<string, LocalValue> = new Map(), values: Values = new Map(), asleep = false): boolean {
  switch (c.t) {
    case "Present": return c.probes.every((probe) => readValue(probe, values) !== null);
    case "LocalsSet": return c.names.every((name) => env.get(name) !== null && env.get(name) !== undefined);
    case "Cmp": {
      const a = numValue(c.a, aod, env, values), b = numValue(c.b, aod, env, values);
      if (c.op === "==") return numEquals(a, b);
      if (c.op === "!=") return !numEquals(a, b);
      if (a === null || b === null) return false;
      const x = val(a), y = val(b);
      return ({ "<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y } as Record<string, boolean>)[c.op]!;
    }
    case "AnyOf": return c.conds.some((term) => condValue(term, aod, env, values));
    case "Truthy": {
      const e = c.expr;
      if (e.constant !== null) return truthy(e.constant);
      if (e.ast === null) return true;
      return truthy(expr.evaluate(e.ast, values));
    }
    case "NotSleeping": return !(asleep || aod);
    case "IsPulsing": return false;
    case "NotPulsing": return true;
  }
}

/** `s` at the sample readings, in the always-on frame when `aod`, or `null` when a reading in it is absent. */
export function strValue(s: Str, values: Values, env: ReadonlyMap<string, LocalValue>, aod = false): string | null {
  switch (s.t) {
    case "AodStr": return strValue(aod ? s.asleep : s.awake, values, env, aod);
    case "StrLit": return s.text;
    case "Reading": {
      const valueType = s.value.value.type;
      if (valueType === "time" || valueType === "date") return formatting.render(s.spec, null, valueType, values);
      const reading = s.value.ast !== null ? expr.evaluate(s.value.ast, values) : null;
      if (reading === null) return null;
      const unit = s.unit !== null && s.unit.ast !== null ? str(expr.evaluate(s.unit.ast, values)) : null;
      return formatting.render(s.spec, reading, valueType, values, unit);
    }
    case "Concat": {
      const parts = s.parts.map((part) => strValue(part, values, env, aod));
      if (parts.some((part) => part === null)) return null;
      return parts.join("");
    }
    case "IconChoice": {
      const reading = s.value.ast !== null ? expr.evaluate(s.value.ast, values) : null;
      return icons.CATALOG.get(icons.chooseWeatherIcon(reading))!.codepoint;
    }
    case "PerCopy": return s.texts[Math.trunc(val(env.get(s.var) as PyNum))]!;
    case "Local": return (env.get(s.name) ?? null) as string | null;
  }
}

/** Paints one element's program into a `Renderer`, keeping the `Dc` state and the program's locals between ops. */
export class Evaluator {
  readonly renderer: Renderer;
  /** What `RingColor` paints: an outlined group's colour, for a ring pass. */
  readonly ringColor: RGB | null;
  color: RGB = [255, 255, 255];
  pen = 1;
  /** The program's locals. */
  readonly locals = new Map<string, LocalValue>();

  constructor(renderer: Renderer, ringColor: RGB | null = null) {
    this.renderer = renderer;
    this.ringColor = ringColor;
  }

  num(n: Num): PyNum | null {
    const r = this.renderer;
    return numValue(n, r.options.aod, this.locals, r.values, new Measure(r));
  }

  /** `num`, known present. */
  n(n: Num): number {
    return val(this.num(n)!);
  }

  cond(c: Cond): boolean {
    const r = this.renderer;
    return condValue(c, r.options.aod, this.locals, r.values, r.options.asleep);
  }

  string(s: Str): string | null {
    const r = this.renderer;
    return strValue(s, r.values, this.locals, r.options.aod);
  }

  paint(c: Paint): RGB {
    const r = this.renderer;
    switch (c.t) {
      case "Color": return r.color(c.expr);
      case "AodRestyled": {
        if (c.awake !== null) {
          const override = c.element.aod !== null ? c.element.aod[c.key] : null;
          if (r.options.aod && override !== null) return r.color(override);
          return this.paint(c.awake);
        }
        return r.aodColor(c.element, c.key, ((c.element as unknown as Record<string, unknown>)[c.key] ?? null) as Expression | null);
      }
      case "AodDimmed": return r.aodDimmed(c.element, c.expr);
      case "AodPaint": return this.paint(r.options.aod ? c.asleep : c.awake);
      case "AodPart": return r.aodColor(c.element, "color", c.expr);
      case "PaintPick": return this.paint(this.cond(c.cond) ? c.then : c.otherwise);
      case "RingColor":
        if (this.ringColor === null) throw new Error("a ring pass painted without its group's colour");
        return this.ringColor;
    }
  }

  run(ops: readonly Op[]): void {
    for (const op of ops) this.step(op);
  }

  /** Run `body(op.body)` once per turn of `op`, the loop variable bound, and for a pattern's copies `copy` too. */
  loop(op: For, body: (ops: readonly Op[]) => void): void {
    const r = this.renderer;
    const saved = r.values;
    try {
      const bound = Math.trunc(this.n(op.bound));
      for (let i = 0; i < bound; i++) {
        this.locals.set(op.var, i);
        if (op.copy) r.values = new Map([...saved, [expr.COPY, i]]);
        try {
          body(op.body);
        } catch (error) {
          if (!(error instanceof Next)) throw error;
        }
      }
    } finally {
      r.values = saved;
    }
  }

  /** `run` a whole element's program, which a guard may end early. */
  runProgram(ops: readonly Op[]): void {
    try {
      this.run(ops);
    } catch (error) {
      if (!(error instanceof Stop)) throw error;
    }
  }

  step(op: Op): void {
    const r = this.renderer;
    switch (op.t) {
      case "SetColor": this.color = this.paint(op.color); break;
      case "SetPen": this.pen = op.width !== null ? Math.trunc(this.n(op.width)) : 1; break;
      case "Primitive": this.primitive(op); break;
      case "FillPolygon":
        if (op.points.length >= 3) polygon(r.image, op.points.map(([x, y]): [number, number] => [x * r.scale, y * r.scale]), this.color);
        break;
      case "ArcSpan":
        this.arc(op, barrel.drawSpan(this.n(op.start), this.n(op.sweep)));
        this.pen = 1; // the barrel resets it
        break;
      case "ArcProgress":
        this.arc(op, barrel.drawProgress(this.n(op.start), this.n(op.sweep), this.n(op.fraction)));
        this.pen = 1;
        break;
      case "Part": this.run(partOps(op, this)); break;
      case "SeriesRebuild": {
        const samples = [...op.samples];
        this.locals.set(op.series, samples);
        this.locals.set(op.minimum, op.min_auto ? barrel.autoMin(samples) : 0);
        this.locals.set(op.maximum, op.max_auto ? barrel.autoMax(samples) : 0);
        break;
      }
      case "SeriesDraw": this.run(seriesOps(op, this)); break;
      case "Let": case "Assign": this.locals.set(op.name, this.num(op.value)); break;
      case "If": this.run(this.cond(op.cond) ? op.then : op.otherwise); break;
      case "For": this.loop(op, (body) => this.run(body)); break;
      case "Continue": throw new Next();
      case "Return": throw new Stop();
      case "SlotPull": this.locals.set("pulled", new Pulled(op.sample)); break;
      case "SlotIcon":
        this.locals.set("iconFont", r.resolved.fonts.get(op.key) ? op.key : null);
        this.locals.set("iconGlyph", op.glyph);
        break;
      case "SlotText": this.locals.set("text", slotText(op, r.values)); break;
      case "LetSlotPick":
        this.locals.set("pulled", new Pulled(op.sample));
        this.locals.set("scale", op.scale);
        break;
      case "LetAutoScale": this.locals.set("scale", autoScale(op, r.values)); break;
      case "VisibleGuard": if (!r.visible(op.expr)) throw new Stop(); break;
      case "NullGuard": if (op.sources.some((path) => (r.values.get(path) ?? null) === null)) throw new Stop(); break;
      case "AntiAlias": break; // the host has no anti-alias switch
      case "Text": this.text(op); break;
      case "Glyph": this.glyph(op); break;
      case "LetText": {
        const value = this.string(op.value);
        this.locals.set(op.name, value !== null ? value : this.string(op.initial));
        break;
      }
      case "IfNotNull": if (op.present) this.run(op.body); break;
      case "IfAod": this.run(r.options.aod ? op.then : op.otherwise); break;
      case "IfAwake": if (!r.options.aod) this.run(op.body); break;
      case "LoadFont": case "Comment": case "Blank": break;
    }
  }

  private primitive(op: Primitive): void {
    const r = this.renderer;
    const v = op.args.flat().map((n) => this.n(n));
    if (!["Rectangle", "RoundedRectangle", "Circle", "Ellipse"].includes(op.name.slice(4)) && op.name !== "drawLine") {
      throw new Error(`no host emulation for dc.${op.name}`);
    }
    pillowPrimitive(r.image, op.name, v, this.color, this.pen, r.scale);
  }

  private arc(op: ArcSpan | ArcProgress, call: barrel.ArcCall | null): void {
    const r = this.renderer;
    const radius = this.n(op.radius);
    if (radius <= 0 || call === null) return;
    const s = r.scale;
    const cx = this.n(op.cx) * s, cy = this.n(op.cy) * s, rr = radius * s;
    const [start, end] = barrel.pillowArc(call);
    pillowArcDraw(r.image, [cx - rr, cy - rr, cx + rr, cy + rr], start, end, this.color, Math.max(1, Math.trunc(this.n(op.pen)) * s));
  }

  private text(op: Text): void {
    const r = this.renderer;
    const text = this.string(op.text);
    if (text === null) return;
    const anchor: [number, number] = [Math.trunc(this.n(op.x)), Math.trunc(this.n(op.y))];
    const align = op.align ?? justifyAlign(op.justify);
    const face = r.options.aod && op.font.asleep !== null ? op.font.asleep : op.font;
    if (face.vector) {
      r.drawVectorText(text, anchor, align, op.valign, face.metric, this.color, op.style,
        op.angle !== null ? this.n(op.angle) : 0.0, op.radius !== null ? Math.trunc(val(op.radius.value)) : 0, op.direction, op.box);
      return;
    }
    const font = face.baked !== null ? r.resolved.fonts.get(face.baked) ?? null : null;
    r.drawText(font, text, anchor, align, op.valign, face.metric, this.color, op.box);
  }

  private glyph(op: Glyph): void {
    const text = this.string(op.glyph);
    if (text === null || op.font.baked === null) return;
    pasteGlyph(this.renderer, op.font.baked, text, op.box.x + this.n(op.x) - op.origin[0], op.box.y + this.n(op.y) - op.origin[1], this.color);
  }
}

/** The `align` a text call's justify flags name. */
export function justifyAlign(justify: readonly string[]): string {
  for (const flag of justify) {
    if (flag === "TEXT_JUSTIFY_LEFT") return "left";
    if (flag === "TEXT_JUSTIFY_RIGHT") return "right";
  }
  return "center";
}

/** `char`'s `GlyphBox` in `font`, or `null` when there is no font, no sheet or no such glyph. */
export function bakedGlyph(font: BakedFont | null | undefined, char: string | null): GlyphBox | null {
  if (font === null || font === undefined || font.sheet === null || char === null) return null;
  return font.glyphs.get(char) ?? null;
}

/** `char`'s tile from the baked sheet `fontKey`, its box's top-left at device `(x, y)`. */
export function pasteGlyph(renderer: Renderer, fontKey: string, char: string, x: number, y: number, color: RGB): void {
  const font = renderer.resolved.fonts.get(fontKey);
  const glyph = bakedGlyph(font, char);
  if (glyph === null || font === undefined || font.sheet === null) return;
  const s = renderer.scale;
  renderer.pasteGlyph(font.sheet, glyph, x * s, y * s, color);
}

/** What one `Part` call draws, as plain `Dc` ops over device numbers: the barrel's own transform. */
export function partOps(op: Part, ev: Evaluator): Op[] {
  const part = op.part;
  const env = ev.locals;
  const get = (name: string): number => val(env.get(name) as PyNum);
  let at: (x: number, y: number) => [number, number];
  if (op.radial) {
    const cx = get("cx"), cy = get("cy"), sin = get("sin"), cos = get("cos");
    at = (x, y) => [cx + (x * cos - y * sin), cy + (x * sin + y * cos)];
  } else {
    const ox = get("ox"), oy = get("oy");
    at = (x, y) => [ox + x, oy + y];
  }
  const stroked = part.shape === "line" || (part.shape === "circle" && !part.filled);
  const offsets: [number, number][] = op.ring === null ? [[0, 0]] : discPerimeterOffsets(op.ring);
  let body: Op[];
  if (part.shape === "polygon") {
    const points = part.points.map(([x, y]) => at(x, y));
    body = offsets.map(([dx, dy]) => FillPolygon(`${op.prefix}_POINTS`, points.map(([x, y]): [number, number] => [x + dx, y + dy])));
  } else if (part.shape === "line") {
    const [x1, y1] = at(part.x1, part.y1), [x2, y2] = at(part.x2, part.y2);
    body = offsets.map(([dx, dy]) => Primitive("drawLine", [[Lit(flt(x1 + dx)), Lit(flt(y1 + dy)), Lit(flt(x2 + dx)), Lit(flt(y2 + dy))]]));
  } else {
    const [x, y] = at(part.x, part.y);
    if (part.filled) {
      const grow = op.ring ?? 0;
      body = [Primitive("fillCircle", [[Lit(flt(x)), Lit(flt(y)), Lit(part.radius + grow)]])];
    } else {
      body = offsets.map(([dx, dy]) => Primitive("drawCircle", [[Lit(flt(x + dx)), Lit(flt(y + dy)), Lit(part.radius)]]));
    }
  }
  if (stroked && op.set_pen) return [SetPen(op.pen), ...body, SetPen(null)];
  return body;
}

/** What one `WfbSeries.draw*` call draws, as plain `Dc` ops over device numbers. */
export function seriesOps(op: SeriesDraw, ev: Evaluator): Op[] {
  const values = ev.locals.get(op.series) as (number | null)[];
  const [x, y, w, h] = [op.x, op.y, op.w, op.h].map((n) => Math.trunc(ev.n(n))) as [number, number, number, number];
  const lo = ev.num(op.lo), hi = ev.num(op.hi);
  if (lo === null || hi === null) return [];
  if (op.style === "line") {
    const lines: Op[] = barrel.seriesLine(x, y, w, h, values, val(lo), val(hi))
      .map(([x1, y1, x2, y2]) => Primitive("drawLine", [[Lit(x1), Lit(y1), Lit(x2), Lit(y2)]]));
    return lines.length > 0 ? [SetPen(op.width), ...lines, SetPen(null)] : [];
  }
  if (op.style === "area") {
    return barrel.seriesArea(x, y, w, h, values, val(lo), val(hi)).map((run) => FillPolygon("", run));
  }
  const bar = Math.trunc(ev.n(op.width!));
  return barrel.seriesBars(x, y, w, h, bar, values, val(lo), val(hi))
    .map(([bx, by, bw, bh]) => Primitive("fillRectangle", [[Lit(bx), Lit(by), Lit(bw), Lit(bh)]]));
}

/** A data element's reading on the host: the sample formatted at the preview's sample settings, behind the label. */
export function slotText(op: SlotText, values: Values): string {
  const statute = (key: string): boolean => {
    const v = values.get(`device.${key}_units`);
    return v === 1 || (v instanceof Object && "value" in v && (v as { value: number }).value === 1);
  };
  const is24 = values.has("device.is_24_hour") ? truthy(values.get("device.is_24_hour")) : true;
  const settings: complications.ReadingSettings = {
    is_24_hour: is24, statute_distance: statute("distance"), statute_elevation: statute("elevation"),
    statute_temperature: statute("temperature"), statute_pace: statute("pace"),
  };
  const reading = complications.formatReading(op.type_name, op.sample, null, { unit: op.unit, short: op.short, settings });
  if (reading === null) return op.absent === "placeholder" ? op.placeholder || "" : "";
  return op.label_sample + reading;
}

/** `max: auto`'s scale on the host: the type's own for the sample wearer, or `null`. */
export function autoScale(op: LetAutoScale, values: Values): [number, number] | null {
  const value = readValue(op.value, values);
  return complications.scaleFor(op.type_name, {
    goals: SAMPLE_GOALS, heartRateZones: SAMPLE_HEART_RATE_ZONES, sex: SAMPLE_WEARER_SEX, age: SAMPLE_WEARER_AGE, value,
  });
}

/** Paint `ops` into `renderer`'s current image. */
export function evaluate(ops: readonly Op[], renderer: Renderer): void {
  new Evaluator(renderer).runProgram(ops);
}
