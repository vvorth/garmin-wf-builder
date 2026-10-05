// Baking a font: each glyph's outline rasterised at 16x by our own
// coverage rasteriser, cropped to its ink, area-averaged down as Pillow's
// BOX filter does, and thresholded at 128 for a 1-bit sheet; then packed
// and written as a BMFont. Port of wfb/fonts/bmfont.py's `bake` and
// `dilate`, with FreeType replaced, so a sheet differs from Python's at
// edge pixels (a recorded change).
//
// Rasterising large and averaging down recovers per-pixel coverage before
// the threshold, which keeps a symmetric glyph symmetric at small sizes;
// 16x is the measured knee (wfb/fonts/bmfont.py's `SUPERSAMPLE`). Outlines
// come from opentype.js, used nowhere else.
import opentype, { type Command, type Font } from "opentype.js";
import { discPerimeterOffsets } from "../ir/model.ts";
import { roundHalfEven } from "../py.ts";
import { BakedFont, GlyphBox, type Sheet } from "./bmfont.ts";
import type { FontFile } from "./files.ts";
import { bounds, flatten, type PathCommand, rasterise } from "./raster.ts";
import { nameRecord, readSfnt } from "./sfnt.ts";

export const SUPERSAMPLE = 16;
/** Where a glyph's ink sits inside its cell when `monospace` is on. */
export const ALIGNMENTS = ["left", "center", "right"] as const;
const PADDING = 1;
const MAX_SHEET = 1024;

/** One glyph's tile: one byte a pixel. */
interface Tile {
  width: number;
  height: number;
  pixels: Uint8Array;
}

const EMPTY: Tile = { width: 1, height: 1, pixels: new Uint8Array(1) };

interface Parsed {
  font: Font;
  upm: number;
  ascent: number;
  descent: number;
  face: string;
}

const parsed = new Map<string, Parsed>();

function load(source: FontFile): Parsed {
  let found = parsed.get(source.path);
  if (found === undefined) {
    const bytes = source.bytes;
    const font = opentype.parse(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer);
    const sfnt = readSfnt(bytes);
    if (sfnt === null) throw new Error(`${source.path}: not a TrueType or OpenType font`);
    const stem = source.path.slice(source.path.lastIndexOf("/") + 1).replace(/\.[^.]*$/, "");
    found = { font, upm: sfnt.unitsPerEm, ascent: sfnt.ascent, descent: sfnt.descent, face: nameRecord(bytes, 1) ?? stem };
    parsed.set(source.path, found);
  }
  return found;
}

/** FreeType's `FT_DivFix`: `a / b` in 16.16 fixed point, rounded. */
function divFix(a: number, b: number): number {
  const sign = (a < 0) !== (b < 0) ? -1 : 1;
  const [x, y] = [BigInt(Math.abs(a)), BigInt(Math.abs(b))];
  return sign * Number((x * 65536n + y / 2n) / y);
}

/** FreeType's `FT_MulFix`: `a * b / 65536`, rounded. */
function mulFix(a: number, b: number): number {
  const sign = (a < 0) !== (b < 0) ? -1 : 1;
  return sign * Number((BigInt(Math.abs(a)) * BigInt(Math.abs(b)) + 0x8000n) >> 16n);
}

/** The 16.16 scale from font units to 26.6 pixels at `size`. */
const scale = (p: Parsed, size: number): number => divFix(size * 64, p.upm);

/** FreeType's pixel ascent (rounded up) and descent (rounded down) at `size`, in its own fixed point. */
function metrics(p: Parsed, size: number): [number, number] {
  const s = scale(p, size);
  return [Math.ceil(mulFix(p.ascent, s) / 64), -Math.floor(mulFix(p.descent, s) / 64)];
}

/** A glyph's advance at `size`: its scaled advance in 26.6, rounded to a pixel. */
function advanceAt(p: Parsed, ch: string, size: number): number {
  return Math.floor((mulFix(p.font.charToGlyph(ch).advanceWidth ?? 0, scale(p, size)) + 32) / 64);
}

function commands(p: Parsed, ch: string, size: number, baseline: number): PathCommand[] {
  return p.font.charToGlyph(ch).getPath(0, baseline, size).commands.map((c: Command): PathCommand => {
    if (c.type === "Z") return { type: "Z" };
    if (c.type === "Q") return { type: "Q", x1: c.x1!, y1: c.y1!, x: c.x!, y: c.y! };
    if (c.type === "C") return { type: "C", x1: c.x1!, y1: c.y1!, x2: c.x2!, y2: c.y2!, x: c.x!, y: c.y! };
    return { type: c.type, x: c.x!, y: c.y! };
  });
}

/** The ink bounds `[x0, y0, x1, y1]` (exclusive) of the nonzero pixels, or `null`. */
function inkBox(pixels: Uint8Array, width: number, height: number): [number, number, number, number] | null {
  let x0 = width, y0 = height, x1 = -1, y1 = -1;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (pixels[y * width + x]) {
        if (x < x0) x0 = x;
        if (x > x1) x1 = x;
        if (y < y0) y0 = y;
        if (y > y1) y1 = y;
      }
    }
  }
  return x1 < 0 ? null : [x0, y0, x1 + 1, y1 + 1];
}

/** Pillow's BOX resampling weights, 8-bit precision. */
function boxCoefficients(inSize: number, outSize: number): { min: number; k: number[] }[] {
  const scale = inSize / outSize, filterscale = Math.max(scale, 1), support = filterscale * 0.5, PB = 22;
  const rows: { min: number; k: number[] }[] = [];
  for (let xx = 0; xx < outSize; xx++) {
    const center = (xx + 0.5) * scale, ss = 1 / filterscale;
    const min = Math.max(0, Math.trunc(center - support + 0.5));
    const max = Math.min(inSize, Math.trunc(center + support + 0.5)) - min;
    const weights: number[] = [];
    let total = 0;
    for (let x = 0; x < max; x++) {
      const t = (x + min - center + 0.5) * ss;
      const w = t > -0.5 && t <= 0.5 ? 1 : 0;
      weights.push(w);
      total += w;
    }
    rows.push({ min, k: weights.map((w) => {
      const v = total ? w / total : 0;
      return v < 0 ? Math.trunc(-0.5 + v * (1 << PB)) : Math.trunc(0.5 + v * (1 << PB));
    }) });
  }
  return rows;
}

/** Pillow's `resize(..., BOX)` of an 8-bit image: horizontal pass, then vertical. */
function boxResize(src: Uint8Array, w: number, h: number, outW: number, outH: number): Uint8Array {
  const PB = 22, clip = (v: number): number => (v < 0 ? 0 : v > 255 ? 255 : v);
  let tmp = src, tw = w;
  if (outW !== w) {
    const cs = boxCoefficients(w, outW);
    tmp = new Uint8Array(outW * h);
    tw = outW;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < outW; x++) {
        const { min, k } = cs[x]!;
        let s = 1 << (PB - 1);
        for (let i = 0; i < k.length; i++) s += src[y * w + min + i]! * k[i]!;
        tmp[y * outW + x] = clip(Math.floor(s / (1 << PB)));
      }
    }
  }
  if (outH === h) return tmp;
  const cs = boxCoefficients(h, outH), out = new Uint8Array(tw * outH);
  for (let y = 0; y < outH; y++) {
    const { min, k } = cs[y]!;
    for (let x = 0; x < tw; x++) {
      let s = 1 << (PB - 1);
      for (let i = 0; i < k.length; i++) s += tmp[(min + i) * tw + x]! * k[i]!;
      out[y * tw + x] = clip(Math.floor(s / (1 << PB)));
    }
  }
  return out;
}

/** One glyph rasterised at 16x, and where its ink starts relative to the pen and the line's top; `null` for no ink. */
function rasteriseGlyph(p: Parsed, size: number, ch: string, antialias: boolean): [Tile, number, number] | null {
  const big = size * SUPERSAMPLE;
  const [ascent] = metrics(p, big);
  const segments = flatten(commands(p, ch, big, ascent));
  const b = bounds(segments);
  if (b === null) return null;
  // An integer-aligned canvas over the outline, a pixel of margin each way.
  const left = Math.floor(b[0]) - 1, top = Math.floor(b[1]) - 1;
  const width = Math.ceil(b[2]) - left + 2, height = Math.ceil(b[3]) - top + 2;
  const canvas = rasterise(segments, left, top, width, height);
  const ink = inkBox(canvas, width, height);
  if (ink === null) return null;
  const [ix0, iy0, ix1, iy1] = ink;
  const cw = ix1 - ix0, ch2 = iy1 - iy0;
  const crop = new Uint8Array(cw * ch2);
  for (let y = 0; y < ch2; y++) crop.set(canvas.subarray((iy0 + y) * width + ix0, (iy0 + y) * width + ix1), y * cw);
  const tw = Math.max(1, roundHalfEven(cw / SUPERSAMPLE)), th = Math.max(1, roundHalfEven(ch2 / SUPERSAMPLE));
  const pixels = boxResize(crop, cw, ch2, tw, th);
  if (!antialias) for (let i = 0; i < pixels.length; i++) pixels[i] = pixels[i]! >= 128 ? 255 : 0;
  return [{ width: tw, height: th, pixels }, roundHalfEven((left + ix0) / SUPERSAMPLE), roundHalfEven((top + iy0) / SUPERSAMPLE)];
}

function orderedUnique(text: string): string[] {
  return [...new Set(Array.from(text))];
}

function isEmpty(tile: Tile): boolean {
  return tile.width === 1 && tile.height === 1 && !tile.pixels[0];
}

type Rendered = [string, Tile, number, number, number];

/** Shelf-pack the tiles into the smallest power-of-two square that fits. */
function pack(tiles: readonly Tile[]): [number, [number, number][]] {
  const widest = Math.max(...tiles.map((t) => t.width)) + PADDING;
  const total = tiles.reduce((n, t) => n + t.width + PADDING, 0);
  let side = 16;
  while (side < MAX_SHEET) {
    if (side >= widest && shelve(tiles, side)[1] <= side) break;
    side *= 2;
  }
  if (side > MAX_SHEET || total === 0) throw new Error("glyph sheet would exceed 1024x1024 -- reduce the font size or glyph set");
  return [side, shelve(tiles, side)[0]];
}

function shelve(tiles: readonly Tile[], side: number): [[number, number][], number] {
  const placements: [number, number][] = [];
  let x = 0, y = 0, rowHeight = 0;
  for (const tile of tiles) {
    if (x + tile.width + PADDING > side) {
      x = 0;
      y += rowHeight + PADDING;
      rowHeight = 0;
    }
    placements.push([x, y]);
    x += tile.width + PADDING;
    rowHeight = Math.max(rowHeight, tile.height);
  }
  return [placements, y + rowHeight];
}

function paste(sheet: Sheet, tile: Tile, x: number, y: number): void {
  for (let row = 0; row < tile.height; row++) sheet.bytes.set(tile.pixels.subarray(row * tile.width, (row + 1) * tile.width), (y + row) * sheet.width + x);
}

/** The shared advance of a monospaced bake: the widest advance, never narrower than the widest ink. */
function cellWidth(rendered: readonly Rendered[]): number {
  const widestAdvance = Math.max(...rendered.map((r) => r[4]));
  const widestInk = Math.max(0, ...rendered.filter((r) => !isEmpty(r[1])).map((r) => r[1].width));
  return Math.max(1, widestAdvance, widestInk);
}

function inkOffset(align: string, cell: number, inkWidth: number): number {
  if (align === "left") return 0;
  if (align === "right") return cell - inkWidth;
  return roundHalfEven((cell - inkWidth) / 2);
}

/** Lay `rendered` out on a sheet as `font`'s glyphs; `cell` replaces each advance and left bearing when given. */
function place(font: BakedFont, rendered: readonly Rendered[], monospaceAlign: string | null): BakedFont {
  const [side, placements] = pack(rendered.map((r) => r[1]));
  font.sheet_width = font.sheet_height = side;
  font.sheet = { mode: "L", width: side, height: side, bytes: new Uint8Array(side * side) };
  rendered.forEach(([ch, tile, left0, top, advance0], i) => {
    const [x, y] = placements[i]!;
    const empty = isEmpty(tile);
    if (!empty) paste(font.sheet!, tile, x, y);
    const inkWidth = empty ? 0 : tile.width;
    let left = left0, advance = advance0;
    if (monospaceAlign !== null) {
      // The cell replaces the natural advance and the natural left bearing alike.
      advance = font.cell_width;
      left = empty ? 0 : inkOffset(monospaceAlign, font.cell_width, inkWidth);
    }
    font.glyphs.set(ch, GlyphBox.create({
      char: ch, x, y, width: inkWidth, height: empty ? 0 : tile.height, xoffset: left, yoffset: top, xadvance: advance,
    }));
  });
  return font;
}

export interface BakeOptions {
  name: string;
  size: number;
  glyphs: string;
  antialias?: boolean;
  monospace?: boolean;
  align?: string;
}

/** Rasterise `glyphs` from `source` at `size` pixels. */
export function bake(source: FontFile, { name, size, glyphs, antialias = false, monospace = false, align = "center" }: BakeOptions): BakedFont {
  if (!(ALIGNMENTS as readonly string[]).includes(align)) throw new Error(`font '${name}': unknown align '${align}'`);
  const chars = orderedUnique(glyphs);
  if (chars.length === 0) throw new Error(`font '${name}': no glyphs to bake`);
  const p = load(source);
  const [ascent, descent] = metrics(p, size);
  const rendered: Rendered[] = chars.map((ch) => {
    // The advance and the line metrics stay at the target size, as FreeType scales them.
    const advance = advanceAt(p, ch, size);
    const found = rasteriseGlyph(p, size, ch, antialias);
    return found === null ? [ch, EMPTY, 0, 0, advance] : [ch, found[0], found[1], found[2], advance];
  });
  const font = BakedFont.create({
    name, face: p.face, size, line_height: ascent + descent, base: ascent, antialias, monospace,
    cell_width: monospace ? cellWidth(rendered) : 0, fnt_name: `${name}.fnt`, png_name: `${name}.png`,
  });
  return place(font, rendered, monospace ? align : null);
}

/**
 * A companion to `base` holding `glyphs` dilated by `width` px: ink wherever
 * the glyph or any of its `discPerimeterOffsets(width)` shifts is, the
 * brightest of them for an anti-aliased sheet. Offsets move by `-width`;
 * advances and line metrics stay `base`'s, so one draw makes the ring.
 */
export function dilate(base: BakedFont, { name, glyphs, width = 1 }: { name: string; glyphs: string; width?: number }): BakedFont {
  const sheet = base.sheet;
  if (sheet === null) throw new Error(`${base.name}: no sheet to dilate`);
  const rendered: Rendered[] = [];
  for (const ch of orderedUnique(glyphs)) {
    const box = base.glyphs.get(ch);
    if (box === undefined) continue;
    if (box.width === 0 || box.height === 0) {
      rendered.push([ch, EMPTY, 0, 0, box.xadvance]);
      continue;
    }
    const gw = box.width + 2 * width, gh = box.height + 2 * width;
    const grown = new Uint8Array(gw * gh);
    for (const [dx, dy] of [[0, 0] as [number, number], ...discPerimeterOffsets(width)]) {
      for (let row = 0; row < box.height; row++) {
        for (let col = 0; col < box.width; col++) {
          const v = sheet.bytes[(box.y + row) * sheet.width + box.x + col]!;
          const at = (row + width + dy) * gw + col + width + dx;
          if (v > grown[at]!) grown[at] = v;
        }
      }
    }
    rendered.push([ch, { width: gw, height: gh, pixels: grown }, box.xoffset - width, box.yoffset - width, box.xadvance]);
  }
  if (rendered.length === 0) throw new Error(`font '${name}': no glyphs to dilate`);
  const ring = BakedFont.create({
    name, face: base.face, size: base.size, line_height: base.line_height, base: base.base, antialias: base.antialias,
    monospace: base.monospace, cell_width: base.cell_width, fnt_name: `${name}.fnt`, png_name: `${name}.png`,
  });
  return place(ring, rendered, null);
}

/** The BMFont text a baked font is written as. */
export function toFnt(font: BakedFont): string {
  const lines = [
    `info face="${font.face}" size=${-font.size} bold=0 italic=0 charset="" unicode=1 stretchH=100 smooth=${font.antialias ? 1 : 0} `
    + `aa=1 padding=0,0,0,0 spacing=${PADDING},${PADDING} outline=0`,
    `common lineHeight=${font.line_height} base=${font.base} scaleW=${font.sheet_width} scaleH=${font.sheet_height} pages=1 packed=0 `
    + "alphaChnl=0 redChnl=4 greenChnl=4 blueChnl=4",
    `page id=0 file="${font.png_name}"`,
    `chars count=${font.glyphs.size}`,
  ];
  for (const ch of [...font.glyphs.keys()].sort((a, b) => a.codePointAt(0)! - b.codePointAt(0)!)) {
    const g = font.glyphs.get(ch)!;
    lines.push(`char id=${ch.codePointAt(0)} x=${g.x} y=${g.y} width=${g.width} height=${g.height} `
      + `xoffset=${g.xoffset} yoffset=${g.yoffset} xadvance=${g.xadvance} page=0 chnl=15`);
  }
  lines.push("kernings count=0");
  return lines.join("\n") + "\n";
}

/**
 * A glyph's ink height at `size`, as a grid-fitted box measures it: from the
 * floor of its top to the ceiling of its bottom, in pixels.
 */
export function inkHeight(source: FontFile, ch: string, size: number): number {
  const p = load(source);
  const b = bounds(flatten(commands(p, ch, Math.max(1, size), 0)));
  return b === null ? 0 : Math.max(0, Math.ceil(b[3]) - Math.floor(b[1]));
}
