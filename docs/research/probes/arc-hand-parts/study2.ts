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

// ---------- A. crescent hour hand at three lengths: 1/2, 1/4, 1/8 of the screen (130, 65, 32 px)
const lengthSheet: Image[] = [];
for (const L of [130, 65, 32]) {
  const rr = Math.max(2, Math.round(L / 5)), pen = L >= 65 ? 3 : 2, stemW = L >= 65 ? 5 : 3;
  const tipC = L - rr, stemTop = tipC + rr - 1; // the arc's circle spans tipC-rr .. tipC+rr; the stem stops inside it
  const stemH = stemTop + 6, stemMid = (stemTop - 6) / 2;
  const text = head(`a${L}`) + `
  hand_sets:
    s:
      hour:
        color: color.white
        parts:
          stem: { type: rectangle, at: { dy: -${stemMid}px }, size: { width: ${stemW}px, height: ${stemH}px } }
          crescent: { type: arc, at: { dy: -${tipC}px }, radius: ${rr}px, thickness: ${pen}px, start_angle: 240deg, sweep: 240deg, color: color.cyan }
elements:
${bg}  hands: { type: hands, set: s, at: { anchor: center } }
`;
  const r = resolved(text, device); const rows: Record<string, number>[] = [];
  const keep: Image[] = [];
  for (let k = 0; k < 720; k++) {
    const im = frameAt(r, { time: [Math.floor(k / 60), k % 60, 0] });
    const arc = pixels(im, CYAN), stem = pixels(im, WHITE);
    rows.push({ arc_px: arc.length, arc_pieces: components(arc), stem_pieces: components(stem), touching: components([...arc, ...stem]) === 1 ? 1 : 0 });
    if (k % 45 === 0 || k === 1 || k === 91) keep.push(im);
  }
  stats(`A. crescent hand, tip ${L} px from the axis (arc r ${rr}, pen ${pen})`, rows);
  lengthSheet.push(...keep.slice(0, 9));
}
writeFileSync(`${OUT}/A-lengths.png`, pngBytes(sheetOf(lengthSheet, 9, 2, [0, 0, 260, 260])));

// ---------- B. date needle: 31 steps and 60 steps, line blade + near-closed ring tip; also a bare hand of arcs on the axis
for (const [steps, sweep] of [[31, 348.387], [60, 354.0], [60, 360.0]] as const) {
  const text = head(`b${steps}${Math.round(sweep)}`) + `
elements:
${bg}  needle:
    type: gauge
    style: needle
    value: date.day - 1
    max: ${steps - 1}
    at: { anchor: center }
    start_angle: 0deg
    sweep: ${sweep}deg
    color: color.white
    needle:
      blade: { type: line, at: { dy: 4px }, to: { dy: -78px }, thickness: 2px }
      moon: { type: arc, at: { dy: -90px }, radius: 10px, thickness: 2px, start_angle: 200deg, sweep: 320deg, color: color.cyan }
      ring: { type: arc, radius: 40px, thickness: 3px, start_angle: -6deg, sweep: 12deg, color: color.green }
`;
  const r = resolved(text, device); const rows: Record<string, number>[] = []; const keep: Image[] = [];
  for (let d = 1; d <= Math.min(steps, 31); d++) {
    const im = frameAt(r, { date: [2026, 12, d] });
    const moon = pixels(im, CYAN), ring = pixels(im, GREEN), blade = pixels(im, WHITE);
    const deg = (d - 1) / (steps - 1) * sweep;
    rows.push({ moon_px: moon.length, moon_pieces: components(moon), ring_px: ring.length, ring_pieces: components(ring), blade_pieces: components(blade), off_whole_deg: Math.round(Math.abs(deg - Math.round(deg)) * 100) / 100 });
    keep.push(im);
  }
  stats(`B. needle, ${steps} steps over ${sweep}deg (days 1..${Math.min(steps, 31)} shown)`, rows);
  if (steps === 60 && sweep === 354.0) writeFileSync(`${OUT}/B-needle-60.png`, pngBytes(sheetOf(keep, 8, 2, [30, 30, 200, 200])));
  if (steps === 31) writeFileSync(`${OUT}/B-needle-31.png`, pngBytes(sheetOf(keep, 8, 2, [30, 30, 200, 200])));
}

// ---------- C. awkward cases on the hour hand, every half degree
const cases: [string, string, Rgb][] = [
  ["tiny arc r2 pen1 at the tip", "{ type: arc, at: { dy: -100px }, radius: 2px, thickness: 1px, start_angle: 180deg, sweep: 270deg }", CYAN],
  ["tiny arc r3 pen2 full ring", "{ type: arc, at: { dy: -100px }, radius: 3px, thickness: 2px }", CYAN],
  ["1-degree sweep at r 100", "{ type: arc, radius: 100px, thickness: 3px, start_angle: -0.5deg, sweep: 1deg }", CYAN],
  ["2-degree sweep at r 60", "{ type: arc, radius: 60px, thickness: 2px, start_angle: -1deg, sweep: 2deg }", CYAN],
  ["0.4-degree sweep (draws nothing)", "{ type: arc, radius: 60px, thickness: 2px, sweep: 0.4deg }", CYAN],
  ["wrapping start 350 sweep 20", "{ type: arc, radius: 80px, thickness: 3px, start_angle: 350deg, sweep: 20deg }", CYAN],
  ["negative sweep -20 from 10", "{ type: arc, radius: 80px, thickness: 3px, start_angle: 10deg, sweep: -20deg }", CYAN],
  ["start -370 (a turn and ten back)", "{ type: arc, radius: 80px, thickness: 3px, start_angle: -370deg, sweep: 20deg }", CYAN],
  ["even pen 4, r 50, 90 sweep", "{ type: arc, radius: 50px, thickness: 4px, start_angle: -45deg, sweep: 90deg }", CYAN],
  ["thick pen 9, r 40, 60 sweep", "{ type: arc, radius: 40px, thickness: 9px, start_angle: -30deg, sweep: 60deg }", CYAN],
  ["off the rim: r 30 at 125 px", "{ type: arc, at: { dy: -125px }, radius: 30px, thickness: 3px, start_angle: 270deg, sweep: 180deg }", CYAN],
  ["off-axis sideways: at dx 20", "{ type: arc, at: { dx: 20px, dy: -60px }, radius: 12px, thickness: 2px, start_angle: 90deg, sweep: 180deg }", CYAN],
  ["polar at: angle 30 radius 70", "{ type: arc, at: { angle: 30deg, radius: 70px }, radius: 10px, thickness: 2px, sweep: 300deg }", CYAN],
  ["full 360 off-axis ring", "{ type: arc, at: { dy: -70px }, radius: 15px, thickness: 1px }", CYAN],
];
const caseSheet: Image[] = [];
for (const [name, part, color] of cases) {
  const text = head("c") + `
  hand_sets:
    s:
      hour:
        color: color.white
        parts:
          blade: { type: line, to: { dy: -110px }, thickness: 1px }
          probe: ${part.slice(0, part.lastIndexOf("}")) + ", color: color.cyan }"}
elements:
${bg}  hands: { type: hands, set: s, at: { anchor: center } }
`;
  let r; try { r = resolved(text, device); } catch (e) { say(`C. ${name}: REFUSED: ${(e as Error).message.split("\n")[0]}`); continue; }
  const rows: Record<string, number>[] = [];
  for (let k = 0; k < 720; k += 1) {
    const im = frameAt(r, { time: [Math.floor(k / 60), k % 60, 0] });
    const px = pixels(im, color);
    rows.push({ px: px.length, pieces: components(px) });
    if (k === 0 || k === 61 || k === 150 || k === 211) caseSheet.push(im);
  }
  stats(`C. ${name}`, rows);
}
writeFileSync(`${OUT}/C-cases.png`, pngBytes(sheetOf(caseSheet, 8, 2, [0, 0, 260, 260])));

// ---------- D. agreement checks
{
  // D1: a full 360 arc part (pen 1) against an unfilled circle part at the same centre: the same pixels at every angle?
  const text = head("d1") + `
  hand_sets:
    s:
      hour: { color: color.cyan, parts: { a: { type: arc, at: { dy: -70px }, radius: 15px, thickness: 1px } } }
      minute: { color: color.red, parts: { c: { type: circle, at: { dy: -70px }, radius: 15px, filled: false, thickness: 1px } } }
elements:
${bg}  hands: { type: hands, set: s, at: { anchor: center } }
`;
  const r = resolved(text, device); let maxDiff = 0, total = 0;
  for (let m = 0; m < 60; m++) { // both hands at the same whole-degree angle: 12:00 hour at m*0.5... use minute m and hour 0 at minute 12m? simpler: compare hour at 2h:m... 
    // hour angle = (h*60+m)*0.5 deg, minute angle = m*6: equal when h*60+m = 12m  ->  h = 11m/60; use m = 0, h = 0 only. Instead draw each alone and compare at matching angles.
  }
  // draw the arc hand alone at hour angle 6m deg (h = m/5 for m multiple of 5), the circle hand alone at minute m
  const arcOnly = resolved(text.replace(/      minute:.*\n/, ""), device), circOnly = resolved(text.replace(/      hour:.*\n/, ""), device);
  for (let m = 0; m < 60; m++) {
    const a = frameAt(arcOnly, { time: [0, 12 * m % 720 / 60 | 0, 0] }); // hour hand at (12m) half-degrees = 6m degrees, via h:m
  }
  const rows: Record<string, number>[] = [];
  for (let m = 0; m < 60; m++) {
    const totalHalfDeg = 12 * m; const h = Math.floor(totalHalfDeg / 60), mm = totalHalfDeg % 60;
    const a = pixels(frameAt(arcOnly, { time: [h, mm, 0] }), CYAN), c = pixels(frameAt(circOnly, { time: [0, m, 0] }), RED);
    rows.push({ arc_px: a.length, circle_px: c.length, differing: sameSet(a, c) });
  }
  stats("D1. a full-ring arc part vs an unfilled circle part, same centre, every 6 degrees", rows);
}
{
  // D2: a hand arc at a whole-degree angle against a static `type: arc` drawn at the composed angle: identical?
  const rows: Record<string, number>[] = [];
  for (const m of [0, 7, 15, 23, 30, 45, 52]) {
    const hand = head("d2") + `
  hand_sets:
    s: { minute: { color: color.cyan, parts: { a: { type: arc, radius: 90px, thickness: 3px, start_angle: 20deg, sweep: 50deg } } } }
elements:
${bg}  hands: { type: hands, set: s, at: { anchor: center } }
`;
    const fixed = head("d3") + `
elements:
${bg}  a: { type: arc, at: { anchor: center }, radius: 90px, thickness: 3px, start_angle: ${20 + 6 * m}deg, sweep: 50deg, color: color.cyan }
`;
    rows.push({ minute: m, differing: sameSet(pixels(frameAt(resolved(hand, device), { time: [0, m, 0] }), CYAN), pixels(frameAt(resolved(fixed, device), {}), CYAN)) });
  }
  stats("D2. an on-axis arc part at minute m vs a fixed type: arc at start+6m", rows);
}
{
  // D3: the half-degree lag made visible: hour frames k and k+1 overlaid for the collar and the crescent (red = k only, green = k+1 only)
  const text = head("d4") + `
  hand_sets:
    s:
      hour:
        color: color.white
        parts:
          stem: { type: rectangle, at: { dy: -50px }, size: { width: 5px, height: 110px } }
          crescent: { type: arc, at: { dy: -110px }, radius: 16px, thickness: 3px, start_angle: 240deg, sweep: 240deg }
          collar: { type: arc, radius: 60px, thickness: 4px, start_angle: -10deg, sweep: 20deg }
elements:
${bg}  hands: { type: hands, set: s, at: { anchor: center } }
`;
  const r = resolved(text, device); const tiles: Image[] = [];
  for (const k of [0, 60, 90, 180, 270, 420]) {
    const a = frameAt(r, { time: [Math.floor(k / 60), k % 60, 0] }), b = frameAt(r, { time: [Math.floor((k + 1) / 60), (k + 1) % 60, 0] });
    tiles.push(overlay(a, b, WHITE));
  }
  writeFileSync(`${OUT}/D-half-degree-overlay.png`, pngBytes(sheetOf(tiles, 3, 3, [0, 0, 260, 260])));
  say("D3. overlay written: D-half-degree-overlay.png (red = whole-degree frame only, green = the next half-degree frame only, white = both)");
}
// ---------- E. outline and AOD with arc parts
{
  const text = head("e1") + `
  hand_sets:
    s:
      hour:
        color: color.white
        parts:
          stem: { type: rectangle, at: { dy: -50px }, size: { width: 5px, height: 110px } }
          crescent: { type: arc, at: { dy: -110px }, radius: 16px, thickness: 3px, start_angle: 240deg, sweep: 240deg }
elements:
${bg}  hands: { type: hands, set: s, at: { anchor: center }, outline: { color: color.red, width: 2 } }
`;
  const r = resolved(text, device); const rows: Record<string, number>[] = []; const tiles: Image[] = [];
  for (let k = 0; k < 720; k += 3) {
    const im = frameAt(r, { time: [Math.floor(k / 60), k % 60, 0] });
    const ring = pixels(im, RED), ink = pixels(im, WHITE);
    rows.push({ ring_px: ring.length, ring_pieces: components(ring), ink_pieces: components(ink) });
    if (k % 180 === 0 || k === 93) tiles.push(im);
  }
  stats("E1. outline: {width: 2} round a crescent hand (ring pieces: 1 = the ring closes round the hand; 2 = stem and crescent ringed apart)", rows);
  writeFileSync(`${OUT}/E-outline.png`, pngBytes(sheetOf(tiles, 5, 2, [0, 0, 260, 260])));
}

// ---------- F. a serpentine hand: chained semicircles bulging left and right, then a straight tip (the Louis Erard case)
function serpentine(r: number, bends: number, pen: number, from = 20): string {
  const parts: string[] = [`          root: { type: line, at: { dy: 6px }, to: { dy: -${from}px }, thickness: ${pen}px }`];
  for (let i = 0; i < bends; i++) {
    const cy = from + r * (2 * i + 1), sweep = i % 2 === 0 ? 180 : -180;
    parts.push(`          bend${i}: { type: arc, at: { dy: -${cy}px }, radius: ${r}px, thickness: ${pen}px, start_angle: 180deg, sweep: ${sweep}deg }`);
  }
  const top = from + 2 * r * bends;
  parts.push(`          tip: { type: line, at: { dy: -${top}px }, to: { dy: -${top + 12}px }, thickness: ${pen}px }`);
  return parts.join("\n");
}
const serpSheet: Image[] = [];
for (const [label, r, bends, pen, hand, frames] of [
  ["second hand, r 12, 4 bends, pen 2", 12, 4, 2, "second", 60],
  ["second hand, r 7, 7 bends, pen 1", 7, 7, 1, "second", 60],
  ["hour hand, r 12, 4 bends, pen 2 (half degrees)", 12, 4, 2, "hour", 720],
  ["hour hand, r 7, 7 bends, pen 3 (half degrees)", 7, 7, 3, "hour", 720],
  ["hour hand, r 4, 12 bends, pen 1 (half degrees)", 4, 12, 1, "hour", 720],
] as const) {
  const text = head("f") + `
  hand_sets:
    s:
      ${hand}:
        color: color.cyan
        parts:
${serpentine(r, bends, pen)}
elements:
${bg}  hands: { type: hands, set: s, at: { anchor: center } }
`;
  const rr = resolved(text, device); const rows: Record<string, number>[] = []; const broken: number[] = [];
  for (let k = 0; k < frames; k++) {
    const time: [number, number, number] = hand === "second" ? [10, 10, k] : [Math.floor(k / 60), k % 60, 0];
    const im = frameAt(rr, { time });
    const px = pixels(im, CYAN); const pieces = components(px);
    rows.push({ px: px.length, pieces });
    if (pieces > 1) broken.push(k);
    if ((hand === "second" && k % 5 === 0) || (hand === "hour" && (k % 90 === 0 || k === 1 || k === 91 || k === 271))) serpSheet.push(im);
  }
  stats(`F. serpentine ${label}`, rows);
  say(`   frames where the chain is not one piece: ${broken.length}` + (broken.length ? ` (${broken.slice(0, 24).join(", ")}${broken.length > 24 ? ", ..." : ""})` : ""));
}
writeFileSync(`${OUT}/F-serpentine.png`, pngBytes(sheetOf(serpSheet, 12, 2, [0, 0, 260, 260])));
writeFileSync(`${OUT}/summary2.txt`, lines.join("\n") + "\n");
