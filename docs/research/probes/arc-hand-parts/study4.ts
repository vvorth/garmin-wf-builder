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


// ---------- G. mending a serpentine's joints: overlap each bend past its joint, or bridge the joint with a dot
function serpentine2(r: number, bends: number, pen: number, overlap: number, dots: boolean, from = 20): string {
  const parts: string[] = [`          root: { type: line, at: { dy: 6px }, to: { dy: -${from}px }, thickness: ${pen}px }`];
  for (let i = 0; i < bends; i++) {
    const cy = from + r * (2 * i + 1), dir = i % 2 === 0 ? 1 : -1;
    // the bend starts `overlap` degrees before its joint and ends `overlap` after the next
    parts.push(`          bend${i}: { type: arc, at: { dy: -${cy}px }, radius: ${r}px, thickness: ${pen}px, start_angle: ${180 + dir * overlap}deg, sweep: ${dir * -(180 + 2 * overlap)}deg }`);
    if (dots) parts.push(`          dot${i}: { type: circle, at: { dy: -${from + 2 * r * i}px }, radius: ${Math.max(1, Math.ceil(pen / 2))}px }`);
  }
  const top = from + 2 * r * bends;
  if (dots) parts.push(`          dot${bends}: { type: circle, at: { dy: -${top}px }, radius: ${Math.max(1, Math.ceil(pen / 2))}px }`);
  parts.push(`          tip: { type: line, at: { dy: -${top}px }, to: { dy: -${top + 12}px }, thickness: ${pen}px }`);
  return parts.join("\n");
}

// zoomed joints: the pen-2 and pen-1 serpentine second hand, unmended beside mended (10 deg overlap), at broken seconds
const rows: Image[] = [];
for (const [pen, secs] of [[2, [3, 14, 29]], [1, [0, 7, 22]]] as const) {
  for (const sec of secs) {
    for (const overlap of [0, 10]) {
      const text = head("z") + `
  hand_sets:
    s:
      second:
        color: color.cyan
        parts:
${serpentine2(12, 4, pen, overlap, false)}
elements:
${bg}  hands: { type: hands, set: s, at: { anchor: center } }
`;
      const im = frameAt(resolved(text, device), { time: [10, 10, sec] });
      // crop a 70x70 window centred on the chain's middle (dy -68 along the hand)
      const th = sec * 6 * Math.PI / 180, mx = 130 + 68 * Math.sin(th), my = 130 - 68 * Math.cos(th);
      const x0 = Math.max(0, Math.min(190, Math.round(mx - 35))), y0 = Math.max(0, Math.min(190, Math.round(my - 35)));
      const crop: Image = { width: 70, height: 70, data: new Uint8ClampedArray(70 * 70 * 4) };
      for (let y = 0; y < 70; y++) crop.data.set(im.data.subarray(((y + y0) * 260 + x0) * 4, ((y + y0) * 260 + x0 + 70) * 4), y * 70 * 4);
      // paint a 1 px grey frame so tiles read apart
      for (let i = 0; i < 70; i++) for (const [x, y] of [[i, 0], [i, 69], [0, i], [69, i]]) crop.data.set([60, 60, 60, 255], (y * 70 + x) * 4);
      rows.push(enlarge(crop, 6));
    }
  }
}
writeFileSync(`${OUT}/Z-serpentine-joints.png`, pngBytes(sheetOf(rows, 6, 1)));
console.log("written");
