// Reads one simulator screenshot of the icon-vcenter probe and prints, per
// row, where each glyph's ink landed in watch pixels against where the
// compiler's model puts it.
//
//   node docs/research/probes/icon-vcenter/measure.ts <screenshot.png> <project dir> <device>
//
// <project dir> is the folder build.sh generated (the one holding
// monkey.jungle); <device> is the device the screenshot shows. The script
// needs nothing but Node: it reads the PNG with the repository's own decoder.
//
// How it maps the screenshot: each row's 1 px red line has a known row
// (LINE_<ROW>_Y) and width (LINE_<ROW>_WIDTH) in the device's Layout.mc, so
// its red run in the screenshot gives the scale (screenshot px per watch px)
// and the offset, line by line. A white pixel's watch row is then
// LINE_Y + (its screenshot row - the line's first screenshot row) / scale.
// Nothing outside the bands around the lines is read, so the simulator's
// bezel and window do not matter.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { decodePng } from "../../../../ts/src/png.ts";

const [shot, project, device] = process.argv.slice(2);
if (!shot || !project || !device) {
  console.error("usage: node measure.ts <screenshot.png> <project dir> <device>");
  process.exit(2);
}

/** The probe's rows, top to bottom, with the size key in their icon font's file name. */
const ROWS: [string, string][] = [["S10", "10pctr"], ["S15", "15pctr"], ["S20", "20pctr"], ["S25", "25pctr"], ["P30", "30px"]];
const HEART = 0xf05f6, H = 72;

const layoutText = readFileSync(join(project, `source-${device}`, "Layout.mc"), "utf8");
const constant = (name: string): number => {
  const m = new RegExp(`const ${name} as Number = (-?\\d+);`).exec(layoutText);
  if (m === null) throw new Error(`${name} is not in ${device}'s Layout.mc`);
  return Number(m[1]);
};

interface Fnt { lineHeight: number; base: number; glyphs: Map<number, { yoffset: number; height: number }> }
function readFnt(path: string): Fnt {
  const text = readFileSync(path, "utf8");
  const common = /common lineHeight=(\d+) base=(\d+)/.exec(text)!;
  const glyphs = new Map<number, { yoffset: number; height: number }>();
  for (const m of text.matchAll(/^char id=(\d+) .*?height=(\d+) .*?yoffset=(-?\d+)/gm)) {
    glyphs.set(Number(m[1]), { height: Number(m[2]), yoffset: Number(m[3]) });
  }
  return { lineHeight: Number(common[1]), base: Number(common[2]), glyphs };
}
const fontDir = join(project, `resources-${device}`, "fonts");
const fntFiles = readdirSync(fontDir).filter((f) => f.endsWith(".fnt"));
const iconFont = (key: string): Fnt => readFnt(join(fontDir, fntFiles.find((f) => f.startsWith(`icon_${key}_`))!));
const textFont = readFnt(join(fontDir, "probe.fnt"));

const image = decodePng(new Uint8Array(readFileSync(shot)));
if (image === null) throw new Error(`${shot} is not a PNG this decoder reads`);
const { width: W, height: Ht, pixels: data } = image;
const at = (x: number, y: number): [number, number, number] => {
  const i = (y * W + x) * 4;
  return [data[i]!, data[i + 1]!, data[i + 2]!];
};
const isRed = ([r, g, b]: [number, number, number]): boolean => r > 170 && g < 90 && b < 90;
const isInk = ([r, g, b]: [number, number, number]): boolean => Math.min(r, g, b) > 150;

// The red lines: runs of screenshot rows holding a long red stretch.
interface Line { top: number; bottom: number; left: number; right: number }
const lines: Line[] = [];
for (let y = 0; y < Ht; y++) {
  let left = -1, right = -1, count = 0;
  for (let x = 0; x < W; x++) {
    if (isRed(at(x, y))) { count++; if (left < 0) left = x; right = x; }
  }
  if (count < 40) continue;
  const last = lines.at(-1);
  if (last !== undefined && y === last.bottom + 1) { last.bottom = y; last.left = Math.min(last.left, left); last.right = Math.max(last.right, right); }
  else lines.push({ top: y, bottom: y, left, right });
}
if (lines.length !== ROWS.length) {
  throw new Error(`found ${lines.length} red reference lines, expected ${ROWS.length}: is this a screenshot of the probe on ${device}?`);
}

const halfUp = (n: number): number => Math.ceil(n / 2);
const rows: string[][] = [["row", "lineHeight", "base", "line y", "scale", "new: model ink", "new: seen ink", "new Δ",
  "old (VCENTER): seen line top", "old: y − top", "text (VCENTER): seen line top", "text: y − top"]];

ROWS.forEach(([row, key], i) => {
  const line = lines[i]!;
  const y = constant(`LINE_${row}_Y`), lineX = constant(`LINE_${row}_X`), lineW = constant(`LINE_${row}_WIDTH`);
  const scale = (line.right - line.left + 1) / lineW;
  const toRow = (sy: number): number => Math.floor(y + (sy - line.top) / scale + 1e-6);
  const toSx = (dx: number): number => Math.round(line.left + (dx - lineX) * scale);
  const font = iconFont(key), heart = font.glyphs.get(HEART)!, h = textFont.glyphs.get(H)!;
  const band = Math.ceil(font.lineHeight * 0.75 * scale);
  // x windows, in watch px: each glyph's own width about its centre (so a round screen's edge stays
  // out), and never past halfway to the next glyph
  const newX = constant(`NEW_${row}_CX`), oldX = constant(`OLD_${row}_CX`), textX = constant(`TEXT_${row}_X`);
  const iconHalf = Math.ceil(font.lineHeight * 0.45), textHalf = Math.ceil(constant(`TEXT_${row}_WIDTH`) / 2) + 2;
  const mid1 = (newX + oldX) / 2, mid2 = (oldX + textX) / 2;
  const windows: [number, number][] = [
    [newX - iconHalf, Math.min(newX + iconHalf, mid1)],
    [Math.max(oldX - iconHalf, mid1), Math.min(oldX + iconHalf, mid2)],
    [Math.max(textX - textHalf, mid2), textX + textHalf],
  ];
  const ink = windows.map(([a, b]) => {
    // the rows holding ink; the glyph is the unbroken run of them nearest the line (a screen's edge or
    // anything else in the window is a separate run)
    const inked = new Set<number>();
    // no further than halfway to the neighbouring rows' lines, so a row never reads its neighbour's ink
    const from = Math.max(0, line.top - band, i > 0 ? Math.ceil((lines[i - 1]!.bottom + line.top) / 2) : 0);
    const to = Math.min(Ht - 1, line.bottom + band, i < lines.length - 1 ? Math.floor((line.bottom + lines[i + 1]!.top) / 2) : Ht - 1);
    for (let sy = from; sy <= to; sy++) {
      for (let sx = Math.max(0, toSx(a)); sx <= Math.min(W - 1, toSx(b)); sx++) {
        if (isInk(at(sx, sy))) inked.add(toRow(sy));
      }
    }
    if (inked.size === 0) return null;
    const sorted = [...inked].sort((p, q) => p - q);
    const runs: [number, number][] = [];
    for (const r of sorted) {
      const run = runs.at(-1);
      if (run !== undefined && r === run[1] + 1) run[1] = r;
      else runs.push([r, r]);
    }
    const distance = ([p, q]: [number, number]): number => (y < p ? p - y : y > q ? y - q : 0);
    return runs.reduce((best, run) => (distance(run) < distance(best) ? run : best));
  });
  const top = constant(`NEW_${row}_TOP`);
  const model = [top + heart.yoffset, top + heart.yoffset + heart.height - 1];
  const [seenNew, seenOld, seenText] = ink;
  const oldTop = seenOld ? seenOld[0] - heart.yoffset : null;
  const textTop = seenText ? seenText[0] - h.yoffset : null;
  rows.push([row, String(font.lineHeight), String(font.base), String(y), scale.toFixed(2),
    `${model[0]}–${model[1]}`, seenNew ? `${seenNew[0]}–${seenNew[1]}` : "none", seenNew ? String(seenNew[0] - model[0]) : "?",
    oldTop === null ? "none" : `${oldTop} (model ${y - halfUp(font.lineHeight)})`, oldTop === null ? "?" : String(y - oldTop),
    textTop === null ? "none" : `${textTop} (model ${y - halfUp(textFont.lineHeight)})`, textTop === null ? "?" : String(y - textTop)]);
});

console.log(`${device}: text font lineHeight ${textFont.lineHeight}, base ${textFont.base}; 'new Δ' is seen − model (positive: the watch draws lower)`);
const widths = rows[0]!.map((_, c) => Math.max(...rows.map((r) => r[c]!.length)));
for (const r of rows) console.log(`| ${r.map((cell, c) => cell.padEnd(widths[c]!)).join(" | ")} |`);
