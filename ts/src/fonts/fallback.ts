// A device `FONT_*` symbol's `FontMetric` turned into a measurable face, for
// layout (measuring) and the preview (drawing). Port of
// wfb/fonts/fallback.py.
//
// System fonts are estimated: `locate` finds the device's own font file
// (the Garmin font root) or a pinned free stand-in, measured at the
// device's published metrics. A `.cft` is a bitmap face whose own height
// and ascent override the metric's line box. For an outline face the em is
// `em_px`, else `size_px * upm / (ascent - descent)`; the line box is
// `height_px`, else `size_px`; the baseline is `ascent_px`, else
// `round(em * ascent / upm)`. Each glyph advances by its `hmtx` width at
// the whole-pixel em, rounded to a whole pixel on its own, with no kerning:
// the device model the metrics probe verified.
import type { FontMetric } from "../devices/device.ts";
import { roundHalfEven } from "../py.ts";
import { type CftFont, loadCft } from "./cft.ts";
import { type FontFile, type FontFiles, locate } from "./files.ts";
import pillowFont from "../data/pillow-default-font.json" with { type: "json" };
import { readSfnt, type Sfnt } from "./sfnt.ts";

/** A flat width per character, when no face at all is available. */
export const CRUDE_WIDTH_RATIO = 0.55;

/**
 * Pillow's bundled default face (Aileron Regular), which a font with no file
 * at all is measured with. Its size metrics are FreeType's (each of ascent
 * and descent rounded up); its advances are the face's own, unhinted, where
 * Pillow's are FreeType's hinted ones, so a width can differ by a pixel.
 */
let pillowSfnt: Sfnt | null | undefined;

/** Pillow's default face's file. */
export const PILLOW_DEFAULT_FILE: FontFile = { path: "<Pillow default>", bytes: base64Bytes(pillowFont.ttf) };

function pillowDefault(): Sfnt | null {
  if (pillowSfnt === undefined) pillowSfnt = readSfnt(PILLOW_DEFAULT_FILE.bytes);
  return pillowSfnt;
}

function base64Bytes(text: string): Uint8Array {
  const binary = atob(text);
  return Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
}

/** Pillow's default face at the size whose ascent plus descent is nearest `pixelHeight`: `[sfnt, size, ascent, descent]`. */
function pillowDefaultAt(pixelHeight: number): [Sfnt, number, number, number] | null {
  const sfnt = pillowDefault();
  if (sfnt === null || pixelHeight <= 0) return null;
  const metrics = (size: number): [number, number] =>
    [Math.ceil(sfnt.ascent * size / sfnt.unitsPerEm), Math.ceil(-sfnt.descent * size / sfnt.unitsPerEm)];
  const [a, d] = metrics(100);
  const size = Math.max(6, roundHalfEven(100 * pixelHeight / (a + d)));
  return [sfnt, size, ...metrics(size)];
}

/** A system font, ready to measure: one of an outline face, a bitmap face or Pillow's default. */
export class SystemFace {
  readonly lineHeight: number;
  private readonly baselinePx: number | null;
  readonly match: string;
  readonly path: string | null;
  readonly layoutEm: number | null;
  readonly scale: number;
  readonly bitmap: CftFont | null;
  readonly sfnt: Sfnt | null;
  /** The outline file glyphs are drawn from, and the pixel size they are drawn at (the exact em, scaled). */
  readonly file: FontFile | null;
  readonly drawSize: number;

  constructor(fields: {
    lineHeight: number; baseline: number | null; match: string; path?: string | null; layoutEm?: number | null;
    scale?: number; bitmap?: CftFont | null; sfnt?: Sfnt | null; file?: FontFile | null; drawSize?: number;
  }) {
    this.lineHeight = fields.lineHeight;
    this.baselinePx = fields.baseline;
    this.match = fields.match;
    this.path = fields.path ?? null;
    this.layoutEm = fields.layoutEm ?? null;
    this.scale = fields.scale ?? 1.0;
    this.bitmap = fields.bitmap ?? null;
    this.sfnt = fields.sfnt ?? null;
    this.file = fields.file ?? null;
    this.drawSize = fields.drawSize ?? 0;
  }

  /** Where the baseline sits, down from the line box's top. */
  get baseline(): number {
    return this.baselinePx!;
  }

  /** Each character's advance, in this face's (scaled) pixels. */
  advances(text: string): number[] {
    if (this.bitmap !== null) return this.bitmap.advances(text).map((a) => a * this.scale);
    if (this.sfnt === null || this.layoutEm === null) throw new Error("an outline face without its font");
    const { cmap, advances, unitsPerEm } = this.sfnt;
    const em = this.layoutEm;
    return Array.from(text, (ch) => roundHalfEven((advances[cmap.get(ch.codePointAt(0)!) ?? 0] ?? advances[0] ?? 0) * em / unitsPerEm) * this.scale);
  }

  width(text: string): number {
    return this.advances(text).reduce((a, b) => a + b, 0);
  }
}

/** Measures system fonts through one set of font files, caching each face as Python's `lru_cache` does. */
export class FontMeasure {
  readonly files: FontFiles;
  private readonly faces = new Map<string, SystemFace | null>();
  private readonly parsed = new Map<string, Sfnt | CftFont | null>();

  constructor(files: FontFiles) {
    this.files = files;
  }

  private sfnt(path: string, bytes: Uint8Array): Sfnt | null {
    if (!this.parsed.has(path)) this.parsed.set(path, readSfnt(bytes));
    return this.parsed.get(path) as Sfnt | null;
  }

  private cft(path: string, bytes: Uint8Array): CftFont | null {
    if (!this.parsed.has(path)) this.parsed.set(path, loadCft(path, bytes));
    return this.parsed.get(path) as CftFont | null;
  }

  /** The one place a `FontMetric` becomes a measurable face; `null` when the metric has no size. */
  systemFace(metric: FontMetric, scale = 1.0): SystemFace | null {
    const key = `${metric.key}\0${scale}`;
    if (!this.faces.has(key)) this.faces.set(key, this.makeFace(metric, scale));
    return this.faces.get(key)!;
  }

  private makeFace(metric: FontMetric, scale: number): SystemFace | null {
    if (metric.size_px <= 0) return null;
    const lineHeightPx = metric.height_px !== null ? metric.height_px : metric.size_px;
    const pillow = (match: string): SystemFace | null => {
      const found = pillowDefaultAt(roundHalfEven(metric.size_px * scale));
      if (found === null) return null;
      const [sfnt, size, ascent, descent] = found;
      return new SystemFace({
        lineHeight: roundHalfEven(lineHeightPx * scale),
        baseline: roundHalfEven((ascent / Math.max(1, ascent + descent)) * lineHeightPx * scale),
        match, layoutEm: size, sfnt, file: PILLOW_DEFAULT_FILE, drawSize: size,
      });
    };
    const [file, match] = locate(this.files, metric.font, metric.face || null);
    if (file === null) return pillow("none");
    if (file.path.toLowerCase().endsWith(".cft")) {
      const bitmap = this.cft(file.path, file.bytes);
      if (bitmap === null) return pillow(match);
      return new SystemFace({
        lineHeight: roundHalfEven(bitmap.height * scale), baseline: roundHalfEven(bitmap.ascent * scale),
        match, path: file.path, scale, bitmap,
      });
    }
    const sfnt = this.sfnt(file.path, file.bytes);
    if (sfnt === null) return pillow(match);
    const { unitsPerEm: upm, ascent, descent } = sfnt;
    let em = metric.em_px;
    if (em === null) {
      const ratio = (ascent - descent) / upm;
      em = ratio ? metric.size_px / ratio : metric.size_px;
    }
    const baselinePx = metric.ascent_px !== null ? metric.ascent_px : roundHalfEven(em * ascent / upm);
    return new SystemFace({
      lineHeight: roundHalfEven(lineHeightPx * scale), baseline: roundHalfEven(baselinePx * scale), match,
      path: file.path, layoutEm: Math.max(1, roundHalfEven(em)), scale, sfnt, file, drawSize: em * scale,
    });
  }

  /** The pixel width of `text` at `metric`'s size, and whether it came from a real face. */
  measure(text: string, metric: FontMetric): [number, boolean] {
    if (!text) return [0, true];
    const face = this.systemFace(metric);
    if (face === null) return [roundHalfEven(Array.from(text).length * metric.size_px * CRUDE_WIDTH_RATIO), false];
    return [roundHalfEven(face.width(text)), true];
  }

  /** The line box height layout measures with. */
  lineHeight(metric: FontMetric): number {
    const face = this.systemFace(metric);
    if (face !== null) return face.lineHeight;
    return metric.height_px !== null ? metric.height_px : metric.size_px;
  }

  /** The baseline's distance below the line box's top: the stand-in for `Graphics.getFontAscent`. */
  ascent(metric: FontMetric): number {
    const face = this.systemFace(metric);
    if (face !== null) return face.baseline;
    if (metric.ascent_px !== null) return metric.ascent_px;
    return this.lineHeight(metric);
  }
}
