// Study 2: hand lengths, 60-step needles, and awkward cases for arc parts.
import { writeFileSync, mkdirSync } from "node:fs";
import { resolved } from "../../../../ts/test/designs.ts";
import { render, previewOptions, pngBytes, enlarge } from "../../../../ts/src/preview.ts";
import type { Image } from "../../../../ts/src/raster/pillow.ts";

const OUT = "./out";
mkdirSync(OUT, { recursive: true });
const device = "fenix8solar47mm"; // 260 x 260, R = 130
const head = (name: string) => `
format: 2
face: { id: 1b2c3d4e-0000-4000-8000-000000000002, name: Arc ${name}, version: 1.0.0 }
build: { targets: [${device}] }
resources:
  palette: { black: "#000000", white: "#FFFFFF", red: "#FF0000", cyan: "#00FFFF", green: "#00FF00", gray: "#555555" }
`;
const bg = `  bg: { type: rectangle, at: { anchor: center }, size: { width: 100%, height: 100% }, color: color.black }\n`;
type Px = [number, number]; type Rgb = [number, number, number];
const WHITE: Rgb = [255, 255, 255], CYAN: Rgb = [0, 255, 255], RED: Rgb = [255, 0, 0], GREEN: Rgb = [0, 255, 0];
function pixels(im: Image, c: Rgb): Px[] { const out: Px[] = []; for (let i = 0, p = 0; i < im.data.length; i += 4, p++) if (im.data[i] === c[0] && im.data[i + 1] === c[1] && im.data[i + 2] === c[2]) out.push([p % im.width, Math.floor(p / im.width)]); return out; }
function components(px: Px[], w = 260): number { const set = new Set(px.map(([x, y]) => y * w + x)); const seen = new Set<number>(); let n = 0;
  for (const p of set) { if (seen.has(p)) continue; n++; const st = [p]; seen.add(p); while (st.length) { const q = st.pop()!; const x = q % w, y = (q - x) / w;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { const m = (y + dy) * w + x + dx; if (set.has(m) && !seen.has(m)) { seen.add(m); st.push(m); } } } } return n; }
const key = (px: Px[]) => new Set(px.map(([x, y]) => y * 1000 + x));
function sameSet(a: Px[], b: Px[]): number { const A = key(a), B = key(b); let d = 0; for (const p of A) if (!B.has(p)) d++; for (const p of B) if (!A.has(p)) d++; return d; }
const lines: string[] = [];
const say = (s: string) => { lines.push(s); console.log(s); };
function stats(name: string, rows: Record<string, number>[]) {
  say(`== ${name} (${rows.length} frames)`);
  for (const k of Object.keys(rows[0]!)) { const v = rows.map((r) => r[k]!); say(`  ${k}: min ${Math.min(...v)} max ${Math.max(...v)} mean ${(v.reduce((a, b) => a + b, 0) / v.length).toFixed(2)}`); }
}
function sheetOf(frames: Image[], cols: number, k: number, crop: [number, number, number, number] | null = null): Image {
  const cut = (im: Image): Image => { if (!crop) return im; const [x0, y0, w, h] = crop; const o: Image = { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) };
    for (let y = 0; y < h; y++) o.data.set(im.data.subarray(((y + y0) * im.width + x0) * 4, ((y + y0) * im.width + x0 + w) * 4), y * w * 4); return o; };
  const tiles = frames.map((f) => enlarge(cut(f), k)); const w = tiles[0]!.width, h = tiles[0]!.height, rows = Math.ceil(tiles.length / cols);
  const big: Image = { width: w * cols, height: h * rows, data: new Uint8ClampedArray(w * cols * h * rows * 4) };
  tiles.forEach((t, i) => { const ox = (i % cols) * w, oy = Math.floor(i / cols) * h; for (let y = 0; y < h; y++) big.data.set(t.data.subarray(y * w * 4, (y + 1) * w * 4), ((oy + y) * big.width + ox) * 4); });
  return big;
}
/** Two frames overlaid: pixels lit in only `a` red, only `b` green, both white. */
function overlay(a: Image, b: Image, c: Rgb): Image {
  const o: Image = { width: a.width, height: a.height, data: new Uint8ClampedArray(a.data.length) };
  for (let i = 0; i < a.data.length; i += 4) { const ia = a.data[i] === c[0] && a.data[i + 1] === c[1] && a.data[i + 2] === c[2]; const ib = b.data[i] === c[0] && b.data[i + 1] === c[1] && b.data[i + 2] === c[2];
    const col = ia && ib ? [255, 255, 255] : ia ? [255, 0, 0] : ib ? [0, 255, 0] : [0, 0, 0]; o.data.set([...col, 255], i); }
  return o;
}
const frameAt = (r: ReturnType<typeof resolved>, o: Record<string, unknown>) => render(r, previewOptions({ scale: 1, quantise: false, mask_shape: false, ...o }));



// ---------- H. the minimum overlap, by bend radius, pen and bend angle
// A tangent-continuous chain of `bends` arcs, each sweeping `theta` degrees, bulging alternately left and
// right, starting at (0, -from) heading up the hand. Each arc is extended `overlap` degrees past both joints.
// Optionally a filled dot of radius ceil(pen/2) at each joint instead.
function chain(r: number, bends: number, pen: number, theta: number, overlap: number, dots: boolean, from = 14): string {
  const parts: string[] = [`          root: { type: line, at: { dy: 6px }, to: { dy: -${from}px }, thickness: ${pen}px }`];
  // state: point P and heading h (degrees clockwise from 12, the format's convention)
  let px = 0, py = -from, h = 0;
  const dir = (deg: number): [number, number] => [Math.sin(deg * Math.PI / 180), -Math.cos(deg * Math.PI / 180)];
  for (let i = 0; i < bends; i++) {
    const side = i % 2 === 0 ? -1 : 1; // -1: bulge left (centre to the right of the heading), turning counter-clockwise
    // the centre lies on the normal: heading + 90 (right) when turning clockwise, heading - 90 when counter-clockwise
    const [nx, ny] = dir(h + side * -90);
    const cx = px + r * nx, cy = py + r * ny;
    // the start point P seen from the centre is at angle (h + side*90); the arc sweeps side*theta... check: turning left (ccw) means the angle about the centre decreases
    const a0 = h - side * -90; // angle of P about the centre = heading - (normal direction) + 180 ... compute directly below
    const angP = Math.atan2(px - cx, -(py - cy)) * 180 / Math.PI; // clockwise from 12
    const sweep = side * theta; // left bulge: counter-clockwise (negative) sweep
    const start = angP - side * overlap;
    parts.push(`          bend${i}: { type: arc, at: { dx: ${cx.toFixed(3)}px, dy: ${cy.toFixed(3)}px }, radius: ${r}px, thickness: ${pen}px, start_angle: ${start.toFixed(3)}deg, sweep: ${(sweep + 2 * side * overlap).toFixed(3)}deg }`);
    if (dots) parts.push(`          dot${i}: { type: circle, at: { dx: ${px.toFixed(3)}px, dy: ${py.toFixed(3)}px }, radius: ${Math.max(1, Math.ceil(pen / 2))}px }`);
    // the end point: rotate P about the centre by sweep
    const angE = (angP + sweep) * Math.PI / 180;
    px = cx + r * Math.sin(angE); py = cy - r * Math.cos(angE);
    h += sweep;
    void a0;
  }
  if (dots) parts.push(`          dotEnd: { type: circle, at: { dx: ${px.toFixed(3)}px, dy: ${py.toFixed(3)}px }, radius: ${Math.max(1, Math.ceil(pen / 2))}px }`);
  const [tx, ty] = dir(h);
  parts.push(`          tip: { type: line, at: { dx: ${px.toFixed(3)}px, dy: ${py.toFixed(3)}px }, to: { dx: ${(px + 10 * tx).toFixed(3)}px, dy: ${(py + 10 * ty).toFixed(3)}px }, thickness: ${pen}px }`);
  return parts.join("\n");
}
function brokenFrames(hands: string, step: number): number {
  const rr = resolved(head("h") + `\n  hand_sets:\n    s:\n      hour:\n        color: color.cyan\n        parts:\n${hands}\nelements:\n${bg}  hands: { type: hands, set: s, at: { anchor: center } }\n`, device);
  let broken = 0;
  for (let k = 0; k < 720; k += step) {
    const im = frameAt(rr, { time: [Math.floor(k / 60), k % 60, 0] });
    if (components(pixels(im, CYAN)) > 1) broken++;
  }
  return broken;
}
const out: string[] = ["| bend angle | radius px | pen px | broken at overlap 0 (of 360) | smallest overlap with 0 broken | ... as px along the arc | dots instead (broken) |", "|---|---|---|---|---|---|---|"];
const STEP = 2; // every whole degree of the hour hand: 360 frames
for (const theta of [180, 120, 90]) {
  for (const r of [4, 8, 16, 32]) {
    const bends = Math.max(2, Math.min(6, Math.floor(96 / (r * (theta === 180 ? 2 : theta === 120 ? 1.73 : 1.41)))));
    for (const pen of [1, 2, 3]) {
      const at0 = brokenFrames(chain(r, bends, pen, theta, 0, false), STEP);
      let found: number | null = null;
      for (const ov of [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30]) {
        if (brokenFrames(chain(r, bends, pen, theta, ov, false), STEP) === 0) { found = ov; break; }
      }
      const dots = brokenFrames(chain(r, bends, pen, theta, 0, true), STEP);
      const px = found === null ? "-" : (found * Math.PI / 180 * r).toFixed(2);
      out.push(`| ${theta} | ${r} | ${pen} | ${at0} | ${found === null ? "none up to 30" : found} | ${px} | ${dots} |`);
      console.log(out[out.length - 1]);
    }
  }
}
writeFileSync(`${OUT}/H-min-overlap.md`, out.join("\n") + "\n");
