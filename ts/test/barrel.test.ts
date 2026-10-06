// The barrel's arithmetic (src/draw/barrel.ts), transcribed from
// runtime-lib/, checked two ways: the .mc source still says what is
// transcribed, and sweeps against an independent model of what the watch
// draws. Each sweep is also run against the broken twin it replaces and seen
// to fail. Monkey C cannot run here, so the barrel is read, not executed.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { REPO_ROOT } from "../src/devices/node.ts";
import { type ArcCall, drawProgress, drawSpan, mcMod, pillowArc, roundAway, rotatedX, rotatedY, toNumber } from "../src/draw/barrel.ts";
import { CATALOG, GARMIN_WEATHER_CONDITION_ICON } from "../src/icons.ts";
import { garminArc } from "../src/layout.ts";
import { previewOptions, render } from "../src/preview.ts";
import { resolved } from "./designs.ts";

const raw = (name: string): string => readFileSync(join(REPO_ROOT, "runtime-lib", name), "utf8");
const source = (name: string): string => raw(name).replace(/\s+/g, " ");

const STATEMENTS: Record<string, string[]> = {
  "WfbArc.mc": [
    "if (fraction <= 0.0 || radius <= 0) { return; }",
    "var swept = sweepDegrees * ((fraction > 1.0) ? 1.0 : fraction);",
    "drawSpan(dc, cx, cy, radius, penWidth, startDegrees, swept);",
    "if (radius <= 0) { return; }",
    "var sweep = roundAway(sweepDegrees);",
    "if (sweep == 0) { return; }",
    "if (sweep > 360) { sweep = 360; }",
    "if (sweep < -360) { sweep = -360; }",
    "var start = roundAway(startDegrees) % 360;",
    "if (start < 0) { start += 360; }",
    "var end = (start - sweep) % 360;",
    "if (end < 0) { end += 360; }",
    "? Graphics.ARC_CLOCKWISE : Graphics.ARC_COUNTER_CLOCKWISE;",
    "dc.drawArc(cx, cy, radius, direction, start, end);",
    "? (degrees - 0.5).toNumber() : (degrees + 0.5).toNumber();",
  ],
  "WfbGeom.mc": [
    "return Math.floor(cx + x * cos - y * sin + 0.5).toNumber();",
    "return Math.floor(cy + x * sin + y * cos + 0.5).toNumber();",
    "out[i] = [cx + x * cos - y * sin, cy + x * sin + y * cos];",
    "dc.fillCircle(cx + x * cos - y * sin, cy + x * sin + y * cos, r);",
  ],
  "WfbMath.mc": [
    "if (goal <= 0) { return 0.0; }",
    "var pct = 100.0 * value.toFloat() / goal.toFloat();",
    "return clamp(pct, 0.0, 100.0) as Float;",
  ],
  "WfbScale.mc": [
    "var low = scale[0].toFloat();",
    "var full = (reading.toFloat() - low) / (scale[1].toFloat() - low);",
    "if (full < 0.0) { return 0.0; }",
    "return (full > 1.0) ? 1.0 : full;",
  ],
  "WfbSeries.mc": [
    "if (span <= 0.0) { span = 1.0; }",
    "if (v == null) { havePrevious = false; continue; }",
    "var cx = x + (i * w / (n - 1));",
    "var cy = y + h - ((v - lo) * h / span).toNumber();",
    "run[count] = [x + ((end - 1) * w / (n - 1)), y + h];",
    "run[count + 1] = [x + (start * w / (n - 1)), y + h];",
    "var pitch = w / n;",
    "var barHeight = ((v - lo) * h / span).toNumber();",
    "if (barHeight < 1) { barHeight = 1; }",
    "x + (i * pitch) + ((pitch - barWidth) / 2), y + h - barHeight,",
  ],
  "WfbRing.mc": ["dc.drawLine(ax - 1, ay, bx - 1, by);", "dc.drawCircle(px - 1, py, r);"],
};

test("the transcription matches the barrel source", () => {
  for (const [name, statements] of Object.entries(STATEMENTS)) {
    const body = source(name);
    for (const s of statements) assert.ok(body.includes(s), `${name} no longer contains ${s}`);
  }
  // The shape of the full-ring bug: each angle made whole on its own, after the decision to draw.
  assert.ok(!source("WfbArc.mc").includes("startDegrees.toNumber()"));
  assert.ok(!source("WfbArc.mc").includes("endDegrees.toNumber()"));
});

// -- the sweeps --

/** The whole-degree cells a `dc.drawArc` call covers, clockwise from 3 o'clock, from the SDK's definition. */
function deviceCells(call: ArcCall | null): Set<number> {
  if (call === null) return new Set();
  const [start, end, clockwise] = call;
  const length = mcMod((clockwise ? start - end : end - start) + 360, 360) || 360;
  const first = clockwise ? -start : -end;
  return new Set(Array.from({ length }, (_, i) => (((first + i) % 360) + 360) % 360));
}

function pillowCells(span: [number, number] | null): Set<number> {
  if (span === null) return new Set();
  const [a, b] = span;
  return new Set(Array.from({ length: b - a }, (_, i) => (((a + i) % 360) + 360) % 360));
}

const evaluatorCells = (start: number, sweep: number): Set<number> => {
  const call = drawSpan(garminArc(start, sweep)[0], sweep);
  return pillowCells(call === null ? null : pillowArc(call));
};
const watchCells = (start: number, sweep: number): Set<number> => deviceCells(drawSpan(garminArc(start, sweep)[0], sweep));

/** The old preview twin: it rounded the author's start, the watch the Garmin start. */
function authorArcSpan(startAngle: number, sweep: number): [number, number] | null {
  const whole = Math.max(-360, Math.min(360, roundAway(sweep)));
  if (whole === 0) return null;
  const start = roundAway(startAngle) - 90;
  const end = start + whole;
  return whole > 0 ? [start, end] : [end, start];
}

const START_ANGLES = Array.from({ length: 720 }, (_, i) => i / 2);
const SWEEPS = [0.3, -0.3, 0.5, -0.5, 1.0, -28.0, 32.0, 45.5, -90.0, 180.5, 359.6, -360.0, 400.0];

test("the evaluator covers the degrees the watch covers, and the sweep catches the old twin", () => {
  const disagree: number[] = [];
  for (const start of START_ANGLES) {
    for (const sweep of SWEEPS) {
      assert.deepEqual(evaluatorCells(start, sweep), watchCells(start, sweep), `${start} ${sweep}`);
      if (!sameSet(pillowCells(authorArcSpan(start, sweep)), watchCells(start, sweep))) disagree.push(start);
    }
  }
  assert.ok(disagree.length > 0, "the sweep no longer separates the old twin from the watch");
  assert.ok(disagree.every((s) => s % 1 === 0.5));
});

const sameSet = (a: Set<number>, b: Set<number>): boolean => a.size === b.size && [...a].every((x) => b.has(x));

test("drawProgress is drawSpan of the clamped fraction", () => {
  for (const start of [0.0, 77.5, 302.0, 359.5]) {
    for (const sweep of [32.0, -32.0, 359.6, 0.4]) {
      for (const fraction of [-0.1, 0.0, 0.001, 0.02, 0.5, 1.0, 1.7]) {
        const expected = fraction <= 0 ? null : drawSpan(start, sweep * Math.min(fraction, 1.0));
        assert.deepEqual(drawProgress(start, sweep, fraction), expected);
      }
    }
  }
});

test("roundAway rounds half away from zero", () => {
  const cases: [number, number][] = [[0.0, 0], [0.49, 0], [0.5, 1], [1.5, 2], [2.4999, 2], [-0.49, 0], [-0.5, -1], [-1.5, -2], [-2.4999, -2]];
  for (const [value, expected] of cases) assert.equal(roundAway(value) + 0, expected, String(value));
});

test("the rotated anchor rounds half up, where truncation would not", () => {
  for (let degrees = 0; degrees < 360; degrees += 7) {
    const theta = (degrees * Math.PI) / 180;
    const [sin, cos] = [Math.sin(theta), Math.cos(theta)];
    for (const x of [-37, -1, 0, 3, 41]) {
      for (const y of [-52, -2, 0, 5, 60]) {
        for (const cx of [-3, 0, 130]) {
          assert.equal(rotatedX(x, y, cx, sin, cos), Math.floor(cx + x * cos - y * sin + 0.5));
          assert.equal(rotatedY(x, y, cx, sin, cos), Math.floor(cx + x * sin + y * cos + 0.5));
        }
      }
    }
  }
  assert.equal(rotatedX(-1.6, 0, 0, 0.0, 1.0), -2);
  assert.equal(toNumber(-1.6 + 0.5), -1);
});

// -- the whole-degree rule: a sub-degree fill once drew the whole bezel ring --

const fullCircle = (call: ArcCall | null): boolean => call !== null && call[0] === call[1];

/** The pre-fix barrel, kept only so the tests below are seen to catch it. */
function oldDrawArc(start: number, sweep: number): ArcCall | null {
  if (sweep >= 360) sweep = 359.9;
  if (sweep <= -360) sweep = -359.9;
  if (sweep === 0) return null;
  let end = start - sweep;
  while (end < 0) end += 360;
  while (end >= 360) end -= 360;
  return [Math.trunc(start), Math.trunc(end), sweep > 0];
}

test("a small fill never draws the full circle; the old barrel did", () => {
  for (const [start, sweep] of [[212.0, 32.0], [180.0, -28.0], [180.0, 28.0], [148.0, -32.0]] as const) {
    for (const fraction of [0.001, 0.005, 0.01, 0.02, 0.03]) {
      assert.ok(!fullCircle(drawSpan(garminArc(start, sweep)[0], sweep * fraction)), `${start} ${sweep} ${fraction}`);
    }
  }
  const steps = garminArc(148.0, -32.0)[0];
  assert.ok(fullCircle(oldDrawArc(steps, -32.0 * 0.02)));
});

test("only a full sweep draws a full circle; under half a degree draws nothing", () => {
  for (const sweep of [360.0, -360.0, 400.0, -720.0]) assert.ok(fullCircle(drawSpan(302.0, sweep)));
  for (const sweep of [0.0, 0.49, -0.49]) assert.equal(drawSpan(302.0, sweep), null);
  for (const sweep of [0.5, -0.5, 0.9, -0.9]) {
    const [start, end] = drawSpan(302.0, sweep)!;
    assert.equal(mcMod(start - end + 360, 360), sweep > 0 ? 1 : 359);
  }
  for (let start = 0; start < 3600; start += 7) {
    for (let sweep = -3594; sweep < 3595; sweep += 13) assert.ok(!fullCircle(drawSpan(start / 10, sweep / 10)), `${start} ${sweep}`);
  }
});

const STEPS_ARC = `
format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm]
resources:
  palette:
    fill: "#00FF00"
elements:
  arc_steps:
    type: gauge
    style: arc
    value: activity.steps
    max: activity.step_goal
    at: { anchor: center }
    radius: 97%r
    thickness: 4%r
    start_angle: 148deg
    sweep: -32deg
    color: color.fill
    absent: hide
`;

test("the preview of a barely started step arc has no fill", () => {
  const r = resolved(STEPS_ARC);
  for (const [steps, expectFill] of [[50, false], [2000, true]] as const) {
    const sample = new Map<string, number>([["activity.steps", steps], ["activity.step_goal", 10000]]);
    const { data } = render(r, previewOptions({ sample: sample as never, mask_shape: false }));
    let green = false;
    for (let i = 0; i < data.length && !green; i += 4) green = data[i] === 0 && data[i + 1] === 255 && data[i + 2] === 0;
    assert.equal(green, expectFill, String(steps));
  }
});

// -- WfbWeather.mc: the hand-written twin of GARMIN_WEATHER_CONDITION_ICON --

test("WfbWeather.mc names the catalogue's icon for every condition, and only ASCII", () => {
  const text = raw("WfbWeather.mc");
  const cases = new Map([...text.matchAll(/case (\d+): return "(\w+)";/g)].map((m) => [Number(m[1]), m[2]!]));
  assert.deepEqual([...cases.keys()].sort((a, b) => a - b), Array.from({ length: 54 }, (_, i) => i));
  for (const [condition, name] of cases) {
    assert.equal(name, GARMIN_WEATHER_CONDITION_ICON.get(condition), `condition ${condition}`);
    assert.ok(CATALOG.has(name), name);
  }
  assert.equal(/default: return "(\w+)";/.exec(text)![1], "weather_unknown");
  assert.equal(/condition == null[\s\S]*?\n\s*return "(\w+)";/.exec(text)![1], "weather_unknown");
  assert.ok([...text].every((c) => c.charCodeAt(0) < 128));
});
