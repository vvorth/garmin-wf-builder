// A baked font: a BMFont sheet's glyph boxes and line metrics, which layout
// places text with. The data half of wfb/fonts/bmfont.py; rasterising and
// writing the sheet come with the bake.
import { make } from "../ir/model.ts";

export class GlyphBox {
  char = "";
  x = 0;
  y = 0;
  width = 0;
  height = 0;
  xoffset = 0;
  yoffset = 0;
  xadvance = 0;

  static create(init: Partial<GlyphBox>): GlyphBox { return make(GlyphBox, init); }
}

/** The packed glyph sheet, one byte a pixel (`"L"` mode). */
export interface Sheet {
  mode: string;
  width: number;
  height: number;
  bytes: Uint8Array;
}

export class BakedFont {
  name = "";
  face = "";
  size = 0;
  line_height = 0;
  base = 0;
  sheet_width = 0;
  sheet_height = 0;
  glyphs: Map<string, GlyphBox> = new Map();
  antialias = false;
  /** Every glyph was given the same advance, `cell_width`. */
  monospace = false;
  cell_width = 0;
  fnt_name = "";
  png_name = "";
  sheet: Sheet | null = null;

  static create(init: Partial<BakedFont>): BakedFont { return make(BakedFont, init); }

  /** The pixel extent of `text`: `[advance width, line height]`. */
  measure(text: string): [number, number] {
    let width = 0;
    for (const ch of text) width += this.glyphs.get(ch)?.xadvance ?? 0;
    return [width, this.line_height];
  }

  /** Characters `text` needs that this font does not hold. */
  missing(text: string): Set<string> {
    return new Set(Array.from(text).filter((ch) => !this.glyphs.has(ch)));
  }
}
