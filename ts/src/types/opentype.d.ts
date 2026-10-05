// The part of opentype.js (which ships no types) this package uses.
declare module "opentype.js" {
  interface Command {
    type: "M" | "L" | "Q" | "C" | "Z";
    x?: number;
    y?: number;
    x1?: number;
    y1?: number;
    x2?: number;
    y2?: number;
  }
  interface Path {
    commands: Command[];
  }
  interface Glyph {
    index: number;
    advanceWidth?: number;
    getPath(x: number, y: number, fontSize: number): Path;
  }
  interface Font {
    tables: Record<string, unknown>;
    unitsPerEm: number;
    charToGlyph(ch: string): Glyph;
  }
  const opentype: { parse(buffer: ArrayBuffer): Font };
  export default opentype;
  export type { Command, Font, Glyph, Path };
}
