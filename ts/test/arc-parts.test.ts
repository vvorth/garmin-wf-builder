// `type: arc` as a part of a hand or a needle: its centre turns like a
// circle part's, its start angle turns with the hand in whole degrees.
import assert from "node:assert/strict";
import { test } from "node:test";
import { previewOptions, render } from "../src/preview.ts";
import type { Image } from "../src/raster/pillow.ts";
import { errors, generated, MINIMAL, resolved, view } from "./designs.ts";

const HEAD = `
format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
    cyan: "#00FFFF"
`;
const BG = `  background: { type: rectangle, at: { anchor: center }, size: { width: 100%, height: 100% }, color: color.bg }\n`;

/** A face with one hand set `s` holding `hands` (YAML under `hand_sets: s:`), placed at the centre. */
const handFace = (hands: string, element = ""): string => HEAD + `  hand_sets:\n    s:\n${hands}\nelements:\n${BG}  hands: { type: hands, set: s, at: { anchor: center }${element} }\n`;

const CRESCENT = `      hour:
        color: color.fg
        parts:
          stem: { type: rectangle, at: { dy: -18%r }, size: { width: 4%r, height: 40%r } }
          crescent: { type: arc, at: { dy: -46%r }, radius: 10%r, thickness: 3px, start_angle: 240deg, sweep: 240deg, color: color.cyan }
          halo: { type: arc, radius: 24%r, thickness: 2px, start_angle: -12deg, sweep: 24deg }
`;

const frame = (text: string, options: Record<string, unknown>): Image =>
  render(resolved(text), previewOptions({ scale: 1, quantise: false, mask_shape: false, ...options }));
const lit = (im: Image, [r, g, b]: [number, number, number]): [number, number][] => {
  const out: [number, number][] = [];
  for (let i = 0, p = 0; i < im.data.length; i += 4, p++) if (im.data[i] === r && im.data[i + 1] === g && im.data[i + 2] === b) out.push([p % im.width, Math.floor(p / im.width)]);
  return out;
};
/** How many 8-connected pieces `pixels` make. */
function pieces(pixels: [number, number][], width = 260): number {
  const set = new Set(pixels.map(([x, y]) => y * width + x)), seen = new Set<number>();
  let n = 0;
  for (const p of set) {
    if (seen.has(p)) continue;
    n++;
    const stack = [p];
    seen.add(p);
    while (stack.length > 0) {
      const q = stack.pop()!, x = q % width, y = (q - x) / width;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { const m = (y + dy) * width + x + dx; if (set.has(m) && !seen.has(m)) { seen.add(m); stack.push(m); } }
    }
  }
  return n;
}

test("an arc part turns with its hand: the centre like a circle's, the start angle in degrees through WfbArc.drawSpan", () => {
  const v = view(handFace(CRESCENT));
  assert.match(v, /var deg = WfbHands\.hourDegrees\(clock\);/);
  // off the axis: the centre is rotated as a circle part's is, as a Float drawArc truncates
  assert.match(v, /WfbArc\.drawSpan\(dc, cx \+ Layout\.HANDS_HOUR_1_X \* cos - Layout\.HANDS_HOUR_1_Y \* sin, cy \+ Layout\.HANDS_HOUR_1_X \* sin \+ Layout\.HANDS_HOUR_1_Y \* cos, Layout\.HANDS_HOUR_1_RADIUS, Layout\.HANDS_HOUR_1_THICKNESS,\s+-150\.0 - deg, 240\.0\)/);
  // on the axis: the axis itself, and no centre constants
  assert.match(v, /WfbArc\.drawSpan\(dc, cx, cy, Layout\.HANDS_HOUR_2_RADIUS, Layout\.HANDS_HOUR_2_THICKNESS,\s+102\.0 - deg, 24\.0\)/);
  const layout = [...generated(handFace(CRESCENT))].find(([name]) => name.endsWith("fenix8solar47mm/Layout.mc"))![1];
  assert.match(layout, /HANDS_HOUR_1_X as Number = 0;/);
  assert.match(layout, /HANDS_HOUR_1_Y as Number = -60;/);
  assert.doesNotMatch(layout, /HANDS_HOUR_2_X/);
});

test("a hand that is all arcs on the axis computes no sin/cos, and a needle's arc gets the needle's angle in degrees", () => {
  const v = view(handFace(`      second: { color: color.fg, parts: { mark: { type: arc, radius: 16%r, thickness: 3px, start_angle: -5deg, sweep: 10deg } } }`));
  assert.match(v, /var deg = WfbHands\.secondDegrees\(clock\);/);
  assert.doesNotMatch(v, /Math\.sin/);
  const needle = HEAD + `elements:\n${BG}  n:
    type: gauge
    style: needle
    value: date.day - 1
    max: 30
    at: { anchor: center }
    start_angle: 0deg
    sweep: 348.387deg
    color: color.fg
    needle:
      blade: { type: line, at: { dy: 4%r }, to: { dy: -20%r }, thickness: 2px }
      moon: { type: arc, at: { dy: -24%r }, radius: 4%r, thickness: 2px, start_angle: 200deg, sweep: 320deg }
`;
  const nv = view(needle);
  assert.match(nv, /var deg = 0\.0 \+ \(WfbMath\.percent\(\(dateDay - 1\), 30\) \/ 100\.0\) \* 348\.387;/);
  assert.match(nv, /WfbArc\.drawSpan\(dc, cx \+ Layout\.N_NEEDLE_1_X \* cos - Layout\.N_NEEDLE_1_Y \* sin/);
});

test("the refusals: filled on an arc part, a pattern arc's at:, an arc with no radius; text and ellipse stay refused", () => {
  const messages = (hands: string) => errors(handFace(hands)).map((d) => d.message);
  assert.match(messages(`      hour: { color: color.fg, parts: { a: { type: arc, radius: 10px, filled: false } } }`).join("\n"), /'filled' is not used by a hand 'type: arc' part/);
  assert.match(messages(`      hour: { color: color.fg, parts: { a: { type: arc, thickness: 2px } } }`).join("\n"), /an arc part needs a radius/);
  assert.match(messages(`      hour: { color: color.fg, parts: { a: { type: ellipse, size: { width: 4px, height: 8px } } } }`).join("\n"), /'type: ellipse' is not accepted on a hand part/);
  const pattern = MINIMAL + `  ring:
    type: pattern
    pattern: radial
    at: { anchor: center }
    count: 12
    parts: { a: { type: arc, at: { dy: -10px }, radius: 10px, sweep: 10deg, color: color.fg } }
`;
  assert.match(errors(pattern).map((d) => d.message).join("\n"), /'at' is not used by a pattern 'type: arc' part/);
});

test("an on-axis arc part at minute m draws the pixels a fixed type: arc at start + 6m draws", () => {
  const hand = handFace(`      minute: { color: color.cyan, parts: { a: { type: arc, radius: 90px, thickness: 3px, start_angle: 20deg, sweep: 50deg } } }`);
  for (const m of [0, 7, 23, 52]) {
    const fixed = HEAD + `elements:\n${BG}  a: { type: arc, at: { anchor: center }, radius: 90px, thickness: 3px, start_angle: ${20 + 6 * m}deg, sweep: 50deg, color: color.cyan }\n`;
    assert.deepEqual(lit(frame(hand, { time: [0, m, 0] }), [0, 255, 255]), lit(frame(fixed, {}), [0, 255, 255]), `minute ${m}`);
  }
});

test("a crescent-tipped hour hand sweeps every half degree in one piece, its arc within three pixels of itself", () => {
  const counts: number[] = [];
  for (let k = 0; k < 720; k += 5) {
    const im = frame(handFace(CRESCENT), { time: [Math.floor(k / 60), k % 60, 0] });
    const arc = lit(im, [0, 255, 255]);
    assert.equal(pieces(arc), 1, `the crescent is in pieces at ${k / 2} degrees`);
    counts.push(arc.length);
  }
  assert.ok(Math.max(...counts) - Math.min(...counts) <= 3, `arc pixel counts ranged ${Math.min(...counts)}..${Math.max(...counts)}`);
});

/** A serpentine second hand: `bends` semicircles of radius `r` chained up the hand, each overlapping its joints by `overlap` degrees. */
function serpentine(r: number, bends: number, pen: number, overlap: number): string {
  const parts = [`          root: { type: line, at: { dy: 6px }, to: { dy: -20px }, thickness: ${pen}px }`];
  for (let i = 0; i < bends; i++) {
    const cy = 20 + r * (2 * i + 1), dir = i % 2 === 0 ? 1 : -1;
    parts.push(`          bend${i}: { type: arc, at: { dy: -${cy}px }, radius: ${r}px, thickness: ${pen}px, start_angle: ${180 + dir * overlap}deg, sweep: ${dir * -(180 + 2 * overlap)}deg }`);
  }
  return `      second:\n        color: color.cyan\n        parts:\n${parts.join("\n")}\n`;
}

test("chained arcs: a pen-2 serpentine overlapping its joints by 10 degrees holds together every second; butted pen-1 bends do not", () => {
  const brokenAt = (hands: string): number[] => {
    const out: number[] = [];
    for (let s = 0; s < 60; s++) if (pieces(lit(frame(handFace(hands), { time: [10, 10, s] }), [0, 255, 255])) > 1) out.push(s);
    return out;
  };
  assert.deepEqual(brokenAt(serpentine(12, 4, 2, 10)), []);
  assert.ok(brokenAt(serpentine(12, 4, 1, 0)).length > 30, "the contrast: butted 1 px bends come apart at most seconds");
});
