// A baked font: a BMFont sheet's glyph boxes and line metrics, which layout
// places text with. Rasterising and writing the sheet are `bake.ts`.
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
  /** Degrees clockwise every glyph was baked turned. */
  rotate = 0;
  /** A turned font's advances before its cells grew to hold the turned ink; empty when upright. */
  unturned_advances: Map<string, number> = new Map();
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

  /** The widest advance of any glyph the font holds: the worst case of a glyph chosen on the watch. */
  widestAdvance(): number {
    let widest = 0;
    for (const glyph of this.glyphs.values()) widest = Math.max(widest, glyph.xadvance);
    return widest;
  }

  /** `ch`'s advance as the upright glyph has it: what spacing round a turned glyph is measured from. */
  unturnedAdvance(ch: string): number {
    return this.unturned_advances.get(ch) ?? this.glyphs.get(ch)?.xadvance ?? 0;
  }

  /** Characters `text` needs that this font does not hold. */
  missing(text: string): Set<string> {
    return new Set(Array.from(text).filter((ch) => !this.glyphs.has(ch)));
  }
}
