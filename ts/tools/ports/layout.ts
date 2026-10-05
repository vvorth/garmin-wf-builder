// The port of the `layout` stage: the design's IR, resolved on one device
// with the fonts the oracle baked (its `fonts` dump), until the bake is
// ported.
import { createHash } from "node:crypto";
import { load } from "../../src/build.ts";
import { DeviceDatabase } from "../../src/devices/device.ts";
import { Bag } from "../../src/diagnostics.ts";
import { BakedFont, GlyphBox } from "../../src/fonts/bmfont.ts";
import { NodeFontFiles } from "../../src/fonts/node.ts";
import { resolve } from "../../src/layout.ts";
import { repoFileExists } from "../../src/node.ts";
import type { Case } from "../stages.ts";
import { irJson } from "./ir.ts";

let database: DeviceDatabase | null = null;

/** One device database for the whole run, so every case shares its measured faces. */
function db(input: Case): DeviceDatabase {
  if (database === null) database = new DeviceDatabase(input.files, new NodeFontFiles());
  return database;
}

interface DumpedFont {
  name: string; face: string; size: number; line_height: number; base: number; sheet_width: number; sheet_height: number;
  glyphs: Record<string, Omit<GlyphBox, never>>; antialias: boolean; monospace: boolean; cell_width: number;
  fnt_name: string; png_name: string; sheet: { mode: string; size: [number, number]; bytes: string } | null;
}

/** The oracle's baked fonts for this device, rebuilt. */
export function bakedFonts(input: Case): Map<string, BakedFont> {
  const dump = input.oracle("fonts") as Record<string, DumpedFont>;
  const out = new Map<string, BakedFont>();
  for (const [name, f] of Object.entries(dump)) {
    out.set(name, BakedFont.create({
      name: f.name, face: f.face, size: f.size, line_height: f.line_height, base: f.base,
      sheet_width: f.sheet_width, sheet_height: f.sheet_height,
      glyphs: new Map(Object.entries(f.glyphs).map(([ch, g]) => [ch, GlyphBox.create(g)])),
      antialias: f.antialias, monospace: f.monospace, cell_width: f.cell_width, fnt_name: f.fnt_name, png_name: f.png_name,
      sheet: f.sheet === null ? null : {
        mode: f.sheet.mode, width: f.sheet.size[0], height: f.sheet.size[1], bytes: new Uint8Array(Buffer.from(f.sheet.bytes, "base64")),
      },
    }));
  }
  return out;
}

export function layout(input: Case): unknown {
  const bag = new Bag();
  const face = load(input.path, bag, input.text, repoFileExists);
  if (face === null) return null;
  const device = db(input).get(input.device!);
  return irJson(resolve(face, device, bakedFonts(input)), true, {
    sheet: (sheet) => ({
      $image: createHash("sha256").update(sheet.bytes).digest("hex"), mode: sheet.mode, size: [sheet.width, sheet.height],
    }),
  });
}
