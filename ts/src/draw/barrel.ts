// The barrel's arithmetic, transcribed from `runtime-lib/*.mc`..
//
// The evaluator computes what a barrel call draws with these functions, so
// the preview draws what the watch draws by construction. Each keeps Monkey
// C's own number semantics: `toNumber` truncates toward zero, `%` takes the
// dividend's sign. A number keeps the Number/Float distinction (`WatchNumber`),
// since a result's type decides how a later `/` divides.
import { WholeFloat } from "../edit/yaml.ts";
import { radians } from "../py.ts";
import type { WatchNumber } from "./program.ts";

/** Is `v` a Python float? */
export function isFloat(v: unknown): boolean {
  return v instanceof WholeFloat || (typeof v === "number" && !Number.isInteger(v));
}

/** `v`'s value. */
export function val(v: WatchNumber): number {
  return v instanceof WholeFloat ? v.value : v;
}

/** `x` as a Python float. */
export function flt(x: number): WatchNumber {
  return Number.isFinite(x) && Number.isInteger(x) ? new WholeFloat(x) : x;
}

/** Monkey C `Float.toNumber`: truncates toward zero. */
export function toNumber(x: WatchNumber): number {
  return Math.trunc(val(x));
}

/** Monkey C `%` on `Number`s: the result takes the dividend's sign. */
export function mcMod(a: number, b: number): number {
  return Math.trunc(a % b);
}

/** `WfbArc.roundAway`: half away from zero. */
export function roundAway(degrees: number): number {
  return degrees < 0.0 ? Math.trunc(degrees - 0.5) : Math.trunc(degrees + 0.5);
}

/** A `dc.drawArc` call, `[start, end, clockwise]` in Garmin's degrees. */
export type ArcCall = [number, number, boolean];

/** `WfbArc.drawSpan`: the `dc.drawArc` call it makes, or `null` when it makes none. */
export function drawSpan(startDegrees: number, sweepDegrees: number): ArcCall | null {
  let sweep = roundAway(sweepDegrees);
  if (sweep === 0) return null;
  if (sweep > 360) sweep = 360;
  if (sweep < -360) sweep = -360;
  let start = mcMod(roundAway(startDegrees), 360);
  if (start < 0) start += 360;
  let end = mcMod(start - sweep, 360);
  if (end < 0) end += 360;
  return [start, end, sweep > 0];
}

/** `WfbArc.drawProgress`: `fraction` of the sweep through `drawSpan`. */
export function drawProgress(startDegrees: number, sweepDegrees: number, fraction: number): ArcCall | null {
  if (fraction <= 0.0) return null;
  return drawSpan(startDegrees, sweepDegrees * (fraction > 1.0 ? 1.0 : fraction));
}

/** A `dc.drawArc` call as Pillow's `[start, end]`, clockwise from 3 o'clock. */
export function pillowArc([start, end, clockwise]: ArcCall): [number, number] {
  if (start === end) return [0 - start, 360 - start];
  let [a, b] = clockwise ? [0 - start, 0 - end] : [0 - end, 0 - start]; // `0 -`: no JavaScript -0
  while (b <= a) b += 360;
  return [a, b];
}

/** `WfbGeom.rotatedX`: the anchor turned clockwise about `cx`, rounded half up. */
export function rotatedX(x: number, y: number, cx: number, sin: number, cos: number): number {
  return Math.trunc(Math.floor(cx + x * cos - y * sin + 0.5));
}

/** `WfbGeom.rotatedY`, the same for `y`. */
export function rotatedY(x: number, y: number, cy: number, sin: number, cos: number): number {
  return Math.trunc(Math.floor(cy + x * sin + y * cos + 0.5));
}

/** `WfbMath.clamp`. */
function clamp(value: WatchNumber, lo: WatchNumber, hi: WatchNumber): WatchNumber {
  if (val(value) < val(lo)) return lo;
  if (val(value) > val(hi)) return hi;
  return value;
}

/** `WfbMath.percent`: `value` as a percentage of `goal`, 0 to 100; 0 for a goal at or below zero. */
function percent(value: WatchNumber, goal: WatchNumber): WatchNumber {
  if (val(goal) <= 0) return flt(0);
  return clamp(flt(100.0 * val(value) / val(goal)), flt(0), flt(100));
}

/** `WfbScale.share`: how full a gauge on `scale` is for `reading`, 0.0 to 1.0. */
export function share(reading: number, scale: readonly [number, number]): number {
  const low = scale[0];
  const full = (reading - low) / (scale[1] - low);
  if (full < 0.0) return 0.0;
  return full > 1.0 ? 1.0 : full;
}

/** The host's stand-in for a pulled `Complications.Complication`. */
export class Pulled {
  readonly value: unknown;
  readonly unit: unknown;

  constructor(value: unknown, unit: unknown = null) {
    this.value = value;
    this.unit = unit;
  }
}

/** `WfbScale.fraction`: `share` of the pulled value, a "K" count multiplied back; `null` for a non-number. */
function scaleFraction(c: Pulled, scale: readonly [number, number]): WatchNumber | null {
  const value = c.value;
  if (!(typeof value === "number" || value instanceof WholeFloat)) return null;
  let reading = val(value);
  if (isFloat(value) && c.unit === "K") reading *= 1000;
  return flt(share(reading, scale));
}

/** `WfbHands.hourAngle`, in radians clockwise from 12: half a degree a minute. */
export function hourAngle(hour: number, minute: number): number {
  return radians((((hour % 12) + 12) % 12 * 60 + minute) * 0.5);
}

/** `WfbHands.minuteAngle`: 6 degrees a minute. */
export function minuteAngle(_hour: number, minute: number): number {
  return radians(minute * 6.0);
}

/** `WfbHands.secondAngle`: 6 degrees a second. */
export function secondAngle(_hour: number, _minute: number, second: number): number {
  return radians(second * 6.0);
}

type Arg = WatchNumber | Pulled | [number, number];

/** The functions a program's `Call` may name, by their Monkey C name. */
export const CALLS: ReadonlyMap<string, (...args: Arg[]) => WatchNumber | null> = new Map<string, (...args: never[]) => WatchNumber | null>([
  ["Math.sin", (x: WatchNumber) => flt(Math.sin(val(x)))],
  ["Math.cos", (x: WatchNumber) => flt(Math.cos(val(x)))],
  ["Math.round", (x: WatchNumber) => flt(Math.floor(val(x) + 0.5))],
  ["WfbMath.clamp", clamp],
  ["WfbMath.percent", percent],
  ["WfbScale.share", (reading: WatchNumber, scale: [number, number]) => flt(share(val(reading), scale))],
  ["WfbScale.fraction", scaleFraction],
  ["WfbGeom.rotatedX", (x: WatchNumber, y: WatchNumber, cx: WatchNumber, s: WatchNumber, c: WatchNumber) => rotatedX(val(x), val(y), val(cx), val(s), val(c))],
  ["WfbGeom.rotatedY", (x: WatchNumber, y: WatchNumber, cy: WatchNumber, s: WatchNumber, c: WatchNumber) => rotatedY(val(x), val(y), val(cy), val(s), val(c))],
]) as unknown as ReadonlyMap<string, (...args: Arg[]) => WatchNumber | null>;

/** Each hand's angle twin, by hand name. */
export const HAND_ANGLES: ReadonlyMap<string, (hour: number, minute: number, second: number) => number> = new Map([
  ["hour", hourAngle], ["minute", minuteAngle], ["second", secondAngle],
]);

/** Monkey C `/` on two `Number`s: truncates toward zero. */
function wholeDiv(a: number, b: number): number {
  return Math.trunc(a / b);
}

function span(lo: number, hi: number): number {
  const s = hi - lo;
  return s <= 0.0 ? 1.0 : s;
}

/** `WfbSeries.drawLine`'s `dc.drawLine` calls, as `[x1, y1, x2, y2]`. */
export function seriesLine(x: number, y: number, w: number, h: number, values: readonly (number | null)[], lo: number, hi: number): [number, number, number, number][] {
  const n = values.length;
  if (n < 2) return [];
  const s = span(lo, hi);
  const out: [number, number, number, number][] = [];
  let have = false, px = 0, py = 0;
  values.forEach((v, i) => {
    if (v === null) {
      have = false;
      return;
    }
    const cx = x + wholeDiv(i * w, n - 1);
    const cy = y + h - Math.trunc((v - lo) * h / s);
    if (have) out.push([px, py, cx, cy]);
    [px, py, have] = [cx, cy, true];
  });
  return out;
}

/** `WfbSeries.drawArea`'s `dc.fillPolygon` calls: one per run of two or more present samples. */
export function seriesArea(x: number, y: number, w: number, h: number, values: readonly (number | null)[], lo: number, hi: number): [number, number][][] {
  const n = values.length;
  if (n < 2) return [];
  const s = span(lo, hi);
  const out: [number, number][][] = [];
  let i = 0;
  while (i < n) {
    if (values[i] === null) {
      i++;
      continue;
    }
    const start = i;
    let end = i;
    while (end < n && values[end] !== null) end++;
    if (end - start >= 2) {
      const run: [number, number][] = [];
      for (let j = start; j < end; j++) {
        const v = values[j]!;
        run.push([x + wholeDiv(j * w, n - 1), y + h - Math.trunc((v - lo) * h / s)]);
      }
      run.push([x + wholeDiv((end - 1) * w, n - 1), y + h]);
      run.push([x + wholeDiv(start * w, n - 1), y + h]);
      out.push(run);
    }
    i = end;
  }
  return out;
}

/** `WfbSeries.drawBars`'s `dc.fillRectangle` calls, as `[x, y, w, h]`. */
export function seriesBars(x: number, y: number, w: number, h: number, barWidth: number, values: readonly (number | null)[], lo: number, hi: number): [number, number, number, number][] {
  const n = values.length;
  if (n < 1) return [];
  const s = span(lo, hi);
  const pitch = wholeDiv(w, n);
  const out: [number, number, number, number][] = [];
  values.forEach((v, i) => {
    if (v === null) return;
    let barHeight = Math.trunc((v - lo) * h / s);
    if (barHeight < 1) barHeight = 1;
    out.push([x + i * pitch + wholeDiv(pitch - barWidth, 2), y + h - barHeight, barWidth, barHeight]);
  });
  return out;
}

/** `WfbSeries.autoMin`: the least present sample, 0.0 with none. */
export function autoMin(values: readonly (number | null)[]): WatchNumber {
  const present = values.filter((v): v is number => v !== null);
  return flt(present.length > 0 ? Math.min(...present) : 0.0);
}

/** `WfbSeries.autoMax`: the greatest present sample, 0.0 with none. */
export function autoMax(values: readonly (number | null)[]): WatchNumber {
  const present = values.filter((v): v is number => v !== null);
  return flt(present.length > 0 ? Math.max(...present) : 0.0);
}
