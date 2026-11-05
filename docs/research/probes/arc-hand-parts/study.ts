// Sweep a hand built from arcs through every angle it can take and look for
// artifacts: parts breaking into fragments, arcs drifting off the hand's own
// angle, asymmetry of an arc meant to sit symmetrically on a blade.
import { writeFileSync, mkdirSync } from "node:fs";
import { resolved } from "../../../../ts/test/designs.ts";
import { render, previewOptions, pngBytes, enlarge } from "../../../../ts/src/preview.ts";
import type { Image } from "../../../../ts/src/raster/pillow.ts";

const OUT = "./out";
mkdirSync(OUT, { recursive: true });

const head = `
format: 2
face: { id: 1b2c3d4e-0000-4000-8000-000000000002, name: Arc Study, version: 1.0.0 }
build: { targets: [fenix8solar47mm] }
resources:
  palette: { black: "#000000", white: "#FFFFFF", red: "#FF0000", cyan: "#00FFFF", green: "#00FF00" }
`;
// R = minor radius = 130 px on fenix8solar47mm (260 px screen).
const designs: Record<string, string> = {
  // the hour hand: a stem, an off-axis crescent (white) and an on-axis halo (cyan), the halo alone in a second colour
  hour: head + `
  hand_sets:
    s:
      hour:
        color: color.white
        parts:
          stem: { type: rectangle, at: { dy: -18%r }, size: { width: 4%r, height: 40%r } }
          crescent: { type: arc, at: { dy: -46%r }, radius: 10%r, thickness: 3px, start_angle: 240deg, sweep: 240deg }
          halo: { type: arc, radius: 24%r, thickness: 2px, start_angle: -12deg, sweep: 24deg, color: color.cyan }
elements:
  bg: { type: rectangle, at: { anchor: center }, size: { width: 100%, height: 100% }, color: color.black }
  hands: { type: hands, set: s, at: { anchor: center } }
`,
  // the minute hand: a mirrored blade (white) with an arc collar (cyan) whose ends straddle the blade symmetrically
  minute: head + `
  hand_sets:
    s:
      minute:
        color: color.white
        parts:
          blade: { type: polygon, mirror: x, points: [{ dx: -1.5%r, dy: 6%r }, { dx: -1.5%r, dy: -60%r }, { dy: -66%r }] }
          collar: { type: arc, radius: 30%r, thickness: 4px, start_angle: -6deg, sweep: 12deg, color: color.cyan }
elements:
  bg: { type: rectangle, at: { anchor: center }, size: { width: 100%, height: 100% }, color: color.black }
  hands: { type: hands, set: s, at: { anchor: center } }
`,
  // a Solaria-style date needle: a line blade and a near-closed ring ("moon") at its tip, the ring open toward the axis
  date: head + `
elements:
  bg: { type: rectangle, at: { anchor: center }, size: { width: 100%, height: 100% }, color: color.black }
  date_hand:
    type: gauge
    style: needle
    value: date.day - 1
    max: 30
    at: { anchor: center }
    start_angle: 0deg
    sweep: 348.387deg
    color: color.white
    needle:
      blade: { type: line, at: { dy: 4%r }, to: { dy: -50%r }, thickness: 2px }
      moon: { type: arc, at: { dy: -58%r }, radius: 8%r, thickness: 2px, start_angle: 200deg, sweep: 320deg, color: color.cyan }
      hub: { type: circle, radius: 2%r }
`,
};

type Mask = { w: number; h: number; on: Uint8Array };
function maskOf(im: Image, color: [number, number, number]): Mask {
  const on = new Uint8Array(im.width * im.height);
  for (let i = 0, p = 0; i < im.data.length; i += 4, p++) {
    if (im.data[i] === color[0] && im.data[i + 1] === color[1] && im.data[i + 2] === color[2]) on[p] = 1;
  }
  return { w: im.width, h: im.height, on };
}
/** Connected components (8-neighbour) of a mask: each one's pixel list. */
function components(m: Mask): [number, number][][] {
  const seen = new Uint8Array(m.w * m.h);
  const out: [number, number][][] = [];
  for (let p = 0; p < m.on.length; p++) {
    if (!m.on[p] || seen[p]) continue;
    const comp: [number, number][] = [];
    const stack = [p]; seen[p] = 1;
    while (stack.length) {
      const q = stack.pop()!; const x = q % m.w, y = (q - x) / m.w; comp.push([x, y]);
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        const nx = x + dx, ny = y + dy; if (nx < 0 || ny < 0 || nx >= m.w || ny >= m.h) continue;
        const n = ny * m.w + nx; if (m.on[n] && !seen[n]) { seen[n] = 1; stack.push(n); }
      }
    }
    out.push(comp);
  }
  return out;
}
/** The mean angle (degrees clockwise from 12, about (cx, cy)) of pixels, by vector sum. */
function meanAngle(pixels: [number, number][], cx: number, cy: number): number {
  let sx = 0, sy = 0;
  for (const [x, y] of pixels) { const dx = x + 0.5 - cx, dy = y + 0.5 - cy; const r = Math.hypot(dx, dy) || 1; sx += dx / r; sy += dy / r; }
  return ((Math.atan2(sx, -sy) * 180 / Math.PI) + 360) % 360;
}
const angDiff = (a: number, b: number): number => { let d = (a - b) % 360; if (d > 180) d -= 360; if (d < -180) d += 360; return d; };
/** Signed count: pixels left of the hand's axis minus those right of it (the axis pointing at `deg`). */
function sideBalance(pixels: [number, number][], cx: number, cy: number, deg: number): number {
  const th = deg * Math.PI / 180, ux = Math.sin(th), uy = -Math.cos(th); // unit vector along the hand
  let left = 0, right = 0;
  for (const [x, y] of pixels) { const dx = x + 0.5 - cx, dy = y + 0.5 - cy; const cross = ux * dy - uy * dx; if (cross > 0.5) right++; else if (cross < -0.5) left++; }
  return left - right;
}

const device = "fenix8solar47mm";
const WHITE: [number, number, number] = [255, 255, 255], CYAN: [number, number, number] = [0, 255, 255];
const sheet: Image[] = [];
function frame(text: string, opts: Parameters<typeof previewOptions>[0]): Image {
  return render(resolved(text, device), previewOptions({ scale: 1, quantise: false, mask_shape: false, ...opts }));
}
const summary: string[] = [];
function report(name: string, rows: Record<string, number>[]): void {
  const keys = Object.keys(rows[0]!);
  const line = (k: string) => { const v = rows.map((r) => r[k]!); return `${k}: min ${Math.min(...v).toFixed(2)} max ${Math.max(...v).toFixed(2)} mean ${(v.reduce((a, b) => a + b, 0) / v.length).toFixed(2)}`; };
  summary.push(`== ${name} (${rows.length} frames)`, ...keys.map(line));
}

// --- hour hand: every half degree (720 minutes of twelve hours)
{
  const rows: Record<string, number>[] = []; const r = resolved(designs.hour!, device);
  const cx = r.device.width / 2, cy = r.device.height / 2;
  for (let k = 0; k < 720; k++) {
    const h = Math.floor(k / 60), m = k % 60, deg = k * 0.5;
    const im = render(r, previewOptions({ scale: 1, quantise: false, mask_shape: false, time: [h, m, 0] }));
    const white = components(maskOf(im, WHITE)), cyan = components(maskOf(im, CYAN));
    const halo = cyan.flat(); const crescent = white.slice().sort((a, b) => b.length - a.length)[1] ?? [];
    // the crescent's own centre, as the hand turns it
    const th = deg * Math.PI / 180, ccx = cx + 60 * Math.sin(th), ccy = cy - 60 * Math.cos(th);
    rows.push({
      white_components: white.length, cyan_components: cyan.length,
      halo_px: halo.length, crescent_px: crescent.length,
      halo_angle_error: angDiff(meanAngle(halo, cx, cy), deg),
      crescent_axis_error: angDiff(meanAngle(crescent, ccx, ccy), deg),
      crescent_balance: sideBalance(crescent, ccx, ccy, deg),
    });
    if (k % 30 === 0) sheet.push(im);
  }
  report("hour hand: stem + off-axis crescent (white), on-axis halo (cyan)", rows);
  // the stem is cut in two by the halo drawn over it (document order), so three white pieces are the design, not a break
  const bad = rows.map((r, i) => [i, r] as const).filter(([, r]) => r.white_components !== 3 || r.cyan_components !== 1);
  summary.push(`frames with an unexpected component count: ${bad.length}` + (bad.length ? " at half-degrees " + bad.slice(0, 20).map(([i]) => i).join(",") : ""));
  report("  ... on a whole degree (even half-degrees)", rows.filter((_, i) => i % 2 === 0));
  report("  ... on a half degree (odd half-degrees): the arc is rounded to the next whole degree", rows.filter((_, i) => i % 2 === 1));
  // zoomed crops of the hand's upper half at a few angles, 6x, for the eye
  const crops: Image[] = [];
  for (const k of [0, 1, 21, 90, 91, 149, 180, 241, 300, 301, 541, 719]) {
    const h = Math.floor(k / 60), m = k % 60;
    const im = render(r, previewOptions({ scale: 1, quantise: false, mask_shape: false, time: [h, m, 0] }));
    const crop: Image = { width: 160, height: 160, data: new Uint8ClampedArray(160 * 160 * 4) };
    for (let y = 0; y < 160; y++) crop.data.set(im.data.subarray(((y + 50) * im.width + 50) * 4, ((y + 50) * im.width + 210) * 4), y * 160 * 4);
    crops.push(enlarge(crop, 5));
  }
  const cols = 4, w = crops[0]!.width, hh = crops[0]!.height, rowsN = Math.ceil(crops.length / cols);
  const big: Image = { width: w * cols, height: hh * rowsN, data: new Uint8ClampedArray(w * cols * hh * rowsN * 4) };
  crops.forEach((e, i) => { const ox = (i % cols) * w, oy = Math.floor(i / cols) * hh;
    for (let y = 0; y < e.height; y++) big.data.set(e.data.subarray(y * e.width * 4, (y + 1) * e.width * 4), ((oy + y) * big.width + ox) * 4); });
  writeFileSync(`${OUT}/hour-zoom.png`, pngBytes(big));
}
// --- minute hand: 60 positions
{
  const rows: Record<string, number>[] = []; const r = resolved(designs.minute!, device);
  const cx = r.device.width / 2, cy = r.device.height / 2;
  for (let m = 0; m < 60; m++) {
    const im = render(r, previewOptions({ scale: 1, quantise: false, mask_shape: false, time: [10, m, 0] }));
    const deg = m * 6, cyan = components(maskOf(im, CYAN)), white = components(maskOf(im, WHITE));
    const collar = cyan.flat();
    rows.push({ white_components: white.length, cyan_components: cyan.length, collar_px: collar.length,
      collar_angle_error: angDiff(meanAngle(collar, cx, cy), deg), collar_balance: sideBalance(collar, cx, cy, deg) });
    if (m % 5 === 0) sheet.push(im);
  }
  report("minute hand: blade (white) + symmetric collar arc (cyan)", rows);
}
// --- date needle: 31 days, angle = (day-1)/30 * 348.387 (fractions of a degree)
{
  const rows: Record<string, number>[] = []; const r = resolved(designs.date!, device);
  const cx = r.device.width / 2, cy = r.device.height / 2;
  for (let d = 1; d <= 31; d++) {
    const im = render(r, previewOptions({ scale: 1, quantise: false, mask_shape: false, date: [2026, 12, d] }));
    const deg = (d - 1) / 30 * 348.387; const th = deg * Math.PI / 180, mcx = cx + 75 * Math.sin(th), mcy = cy - 75 * Math.cos(th);
    const cyan = components(maskOf(im, CYAN)), white = components(maskOf(im, WHITE)); const moon = cyan.flat();
    rows.push({ white_components: white.length, cyan_components: cyan.length, moon_px: moon.length,
      moon_balance: sideBalance(moon, mcx, mcy, deg),
      requested_deg_fraction: deg - Math.round(deg) });
    sheet.push(im);
  }
  report("date needle: line blade (white) + off-axis ring open toward the axis (cyan)", rows);
}
// --- contact sheet: every frame kept above, 3x, 8 per row
{
  const k = 3, cols = 8, w = sheet[0]!.width, h = sheet[0]!.height, rowsN = Math.ceil(sheet.length / cols);
  const big: Image = { width: w * k * cols, height: h * k * rowsN, data: new Uint8ClampedArray(w * k * cols * h * k * rowsN * 4) };
  sheet.forEach((im, i) => {
    const e = enlarge(im, k), ox = (i % cols) * w * k, oy = Math.floor(i / cols) * h * k;
    for (let y = 0; y < e.height; y++) big.data.set(e.data.subarray(y * e.width * 4, (y + 1) * e.width * 4), ((oy + y) * big.width + ox) * 4);
  });
  writeFileSync(`${OUT}/sheet.png`, pngBytes(big));
}
writeFileSync(`${OUT}/summary.txt`, summary.join("\n") + "\n");
console.log(summary.join("\n"));
