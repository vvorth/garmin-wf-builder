// Re-bakes dump_bakes.py's fonts without Pillow and compares every glyph
// tile, offset, advance and line metric with wfb.fonts.bmfont.bake.
//
// Outlines come from opentype.js; coverage is Skia's (@napi-rs/canvas, the
// rasteriser behind Chrome's canvas). Three bakers:
//   outline+pillowbox  the glyph outline filled at 16x, then Pillow's BOX
//                      resample transcribed, then the 128 threshold: the
//                      current pipeline with Pillow and FreeType removed
//   outline+area       the same outline, a plain exact area average instead
//   native fillText    the platform text engine (canvas fillText at 16x),
//                      then the same transcribed BOX
//   node fonts.mjs bakes.json <repo>
import { createCanvas, GlobalFonts } from "@napi-rs/canvas";
import opentype from "opentype.js";
import { readFileSync } from "node:fs";

const [bakesPath, repo] = process.argv.slice(2);
const bakes = JSON.parse(readFileSync(bakesPath, "utf8"));
const SS = 16, PAD = SS * 2;

// Pillow's ImagingResample with the BOX filter, 8 bits per channel:
// precompute_coeffs + normalize_coeffs_8bpc, horizontal pass then vertical.
function coeffs(inSize, outSize) {
  const scale = inSize / outSize, filterscale = Math.max(scale, 1), support = filterscale * 0.5;
  const PB = 22, rows = [];
  for (let xx = 0; xx < outSize; xx++) {
    const center = (xx + 0.5) * scale, ss = 1 / filterscale;
    let xmin = Math.trunc(center - support + 0.5); if (xmin < 0) xmin = 0;
    let xmax = Math.trunc(center + support + 0.5); if (xmax > inSize) xmax = inSize; xmax -= xmin;
    const k = []; let ww = 0;
    for (let x = 0; x < xmax; x++) {
      const t = (x + xmin - center + 0.5) * ss; const w = t > -0.5 && t <= 0.5 ? 1 : 0; k.push(w); ww += w;
    }
    rows.push({ xmin, k: k.map((w) => { const v = ww ? w / ww : 0;
      return v < 0 ? Math.trunc(-0.5 + v * (1 << PB)) : Math.trunc(0.5 + v * (1 << PB)); }) });
  }
  return rows;
}
function pillowBox(src, W, H, w, h) {
  const PB = 22, clip = (v) => (v < 0 ? 0 : v > 255 ? 255 : v);
  let tmp = src, tw = W;
  if (w !== W) {
    const cs = coeffs(W, w); tmp = new Uint8Array(w * H); tw = w;
    for (let y = 0; y < H; y++) for (let x = 0; x < w; x++) {
      const { xmin, k } = cs[x]; let s = 1 << (PB - 1);
      for (let i = 0; i < k.length; i++) s += src[y * W + xmin + i] * k[i];
      tmp[y * w + x] = clip(Math.floor(s / (1 << PB)));
    }
  }
  if (h === H) return tmp;
  const cs = coeffs(H, h), out = new Uint8Array(tw * h);
  for (let y = 0; y < h; y++) {
    const { xmin, k } = cs[y];
    for (let x = 0; x < tw; x++) {
      let s = 1 << (PB - 1);
      for (let i = 0; i < k.length; i++) s += tmp[(xmin + i) * tw + x] * k[i];
      out[y * tw + x] = clip(Math.floor(s / (1 << PB)));
    }
  }
  return out;
}
function areaAverage(src, W, H, w, h) {
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const x0 = (x * W) / w, x1 = ((x + 1) * W) / w, y0 = (y * H) / h, y1 = ((y + 1) * H) / h;
    let s = 0, a = 0;
    for (let yy = Math.floor(y0); yy < Math.ceil(y1); yy++) for (let xx = Math.floor(x0); xx < Math.ceil(x1); xx++) {
      const f = (Math.min(xx + 1, x1) - Math.max(xx, x0)) * (Math.min(yy + 1, y1) - Math.max(yy, y0));
      s += src[yy * W + xx] * f; a += f;
    }
    out[y * w + x] = Math.round(s / a);
  }
  return out;
}
const fontCache = new Map();
function load(source) {
  if (!fontCache.has(source)) {
    const bytes = readFileSync(`${repo}/${source}`);
    const font = opentype.parse(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length));
    const family = `probe${fontCache.size}`;
    GlobalFonts.registerFromPath(`${repo}/${source}`, family);
    fontCache.set(source, { font, family });
  }
  return fontCache.get(source);
}
// One canvas, reused while the glyph size repeats.
let shared = null;
function canvasFor(w, h) {
  if (!shared || shared.w !== w || shared.h !== h) shared = { w, h, ctx: createCanvas(w, h).getContext("2d") };
  return shared.ctx;
}
// Python's round(): half to even.
const pyRound = (v) => { const f = Math.floor(v), d = v - f; return d > 0.5 ? f + 1 : d < 0.5 ? f : (f % 2 === 0 ? f : f + 1); };
// One glyph at SS x size, the pen at (ox, oy + ceiled ascender), as Pillow's
// "la" anchor puts it; returns the tile and its offsets from the pen's top.
function glyph(source, size, ch, antialias, how) {
  const { font, family } = load(source);
  const big = size * SS, upm = font.unitsPerEm;
  const asc = Math.ceil((font.tables.hhea.ascender * big) / upm);
  // The canvas spans the outline's own bounds plus PAD each way, so only
  // the glyph's pixels are read back.
  const bb = font.getPath(ch, 0, asc, big).getBoundingBox();
  if (!(bb.x2 > bb.x1)) return null;
  const ox = PAD - Math.floor(bb.x1), oy = PAD - Math.floor(bb.y1);
  const Wc = Math.ceil(bb.x2) - Math.floor(bb.x1) + 2 * PAD, Hc = Math.ceil(bb.y2) - Math.floor(bb.y1) + 2 * PAD;
  const x = canvasFor(Wc, Hc);
  x.clearRect(0, 0, Wc, Hc);
  x.fillStyle = "#fff";
  if (how === "native") {
    x.font = `${big}px ${family}`; x.textBaseline = "alphabetic"; x.fillText(ch, ox, oy + asc);
  } else {
    const p = font.getPath(ch, ox, oy + asc, big); p.fill = "#fff"; p.draw(x);
  }
  const d = x.getImageData(0, 0, Wc, Hc).data;
  let x0 = Wc, y0 = Hc, x1 = -1, y1 = -1;
  for (let yy = 0; yy < Hc; yy++) for (let xx = 0; xx < Wc; xx++) if (d[(yy * Wc + xx) * 4 + 3]) {
    if (xx < x0) x0 = xx; if (xx > x1) x1 = xx; if (yy < y0) y0 = yy; if (yy > y1) y1 = yy;
  }
  if (x1 < 0) return null;
  const W = x1 - x0 + 1, H = y1 - y0 + 1, crop = new Uint8Array(W * H);
  for (let yy = 0; yy < H; yy++) for (let xx = 0; xx < W; xx++) crop[yy * W + xx] = d[((y0 + yy) * Wc + x0 + xx) * 4 + 3];
  const w = Math.max(1, pyRound(W / SS)), h = Math.max(1, pyRound(H / SS));
  let tile = how === "area" ? areaAverage(crop, W, H, w, h) : pillowBox(crop, W, H, w, h);
  if (!antialias) tile = tile.map((v) => (v >= 128 ? 255 : 0));
  return { w, h, xo: pyRound((x0 - ox) / SS), yo: pyRound((y0 - oy) / SS), tile };
}
const results = {};
const metric = { bakes: bakes.length, base: 0, line: 0, glyphs: 0, adv: 0 };
for (const b of bakes) {
  const { font } = load(b.source);
  const upm = font.unitsPerEm;
  const asc = Math.ceil((font.tables.hhea.ascender * b.size) / upm);
  const desc = Math.ceil((-font.tables.hhea.descender * b.size) / upm);
  if (asc === b.base) metric.base++;
  if (asc + desc === b.line_height) metric.line++;
  for (const [ch, g] of Object.entries(b.glyphs)) {
    metric.glyphs++;
    if (pyRound((font.charToGlyph(ch).advanceWidth * b.size) / upm) === g.adv) metric.adv++;
  }
  for (const how of ["outline+pillowbox", "outline+area", "native fillText"]) {
    const R = (results[`${how} aa=${b.antialias}`] ??= { glyphs: 0, identical: 0, placed_same: 0, diff_px: 0, ink_px: 0, worst: [] });
    const mode = how === "outline+area" ? "area" : how === "native fillText" ? "native" : "outline";
    for (const [ch, g] of Object.entries(b.glyphs)) {
      if (!g.w) continue;
      const ref = Buffer.from(g.tile, "base64");
      const mine = glyph(b.source, b.size, ch, b.antialias, mode);
      R.glyphs++;
      const ink = ref.reduce((a, v) => a + (v ? 1 : 0), 0); R.ink_px += ink;
      if (!mine) { R.diff_px += ink; R.worst.push([ink, `${b.source.split("/").pop()} ${b.size}px '${ch}' not drawn`]); continue; }
      if (mine.xo === g.xo && mine.yo === g.yo && mine.w === g.w && mine.h === g.h) R.placed_same++;
      // Compared on the pen grid, over the union of both boxes. An
      // anti-aliased pixel counts as different past 8 levels of 255.
      const X0 = Math.min(g.xo, mine.xo), Y0 = Math.min(g.yo, mine.yo);
      const X1 = Math.max(g.xo + g.w, mine.xo + mine.w), Y1 = Math.max(g.yo + g.h, mine.yo + mine.h);
      let n = 0;
      for (let y = Y0; y < Y1; y++) for (let x = X0; x < X1; x++) {
        const a = x >= g.xo && x < g.xo + g.w && y >= g.yo && y < g.yo + g.h ? ref[(y - g.yo) * g.w + x - g.xo] : 0;
        const m = x >= mine.xo && x < mine.xo + mine.w && y >= mine.yo && y < mine.yo + mine.h ? mine.tile[(y - mine.yo) * mine.w + x - mine.xo] : 0;
        if (b.antialias ? Math.abs(a - m) > 8 : a !== m) n++;
        if (b.antialias) R.max_grey_diff = Math.max(R.max_grey_diff || 0, Math.abs(a - m));
      }
      if (n === 0) R.identical++;
      R.diff_px += n;
      // Split: glyphs whose box and offsets agree (a raster difference) and
      // those placed a pixel apart (a rounding of the ink box).
      const same = mine.xo === g.xo && mine.yo === g.yo && mine.w === g.w && mine.h === g.h;
      if (same) { R.same_box_diff_px = (R.same_box_diff_px || 0) + n; R.same_box_ink_px = (R.same_box_ink_px || 0) + ink; }
      if (n) R.worst.push([n, `${b.source.split("/").pop()} ${b.size}px aa=${b.antialias} '${ch}'`]);
    }
  }
}
for (const [how, R] of Object.entries(results)) {
  R.worst = R.worst.sort((a, b) => b[0] - a[0]).slice(0, 3).map(([n, w]) => `${n} px ${w}`);
  R.diff_share = `${((R.diff_px / R.ink_px) * 100).toFixed(2)}% of Pillow's ink pixels`;
  console.log(how.padEnd(28), JSON.stringify(R));
}
console.log("metrics:", JSON.stringify(metric));
