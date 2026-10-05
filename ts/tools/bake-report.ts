// How the TS bake's glyphs compare with Python's (FreeType's), over every
// text font the corpus bakes on every device: per glyph, whether the tile's
// box and offsets agree, and how many ink pixels differ where they do.
//   node tools/bake-report.ts
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { load } from "../src/build.ts";
import { DeviceDatabase } from "../src/devices/device.ts";
import { NodeDeviceFiles, REPO_ROOT } from "../src/devices/node.ts";
import { Bag } from "../src/diagnostics.ts";
import { bakeFonts } from "../src/emit/resources.ts";
import { NodeFontFiles } from "../src/fonts/node.ts";
import { installAssets, repoFileExists } from "../src/node.ts";
import { readFont } from "./ports/layout.ts";

installAssets();
const ORACLE = join(REPO_ROOT, ".cache", "oracle");
const index = JSON.parse(readFileSync(join(ORACLE, "index.json"), "utf8")) as { designs: { id: string; path: string; devices: string[] }[] };
const db = new DeviceDatabase(NodeDeviceFiles.discover(), new NodeFontFiles());
const rows = new Map<string, { glyphs: number; identical: number; sameBox: number; ink: number; inkDiff: number; boxInk: number; boxInkDiff: number }>();
for (const design of index.designs) {
  if (design.devices.length === 0) continue;
  const face = load(design.path, new Bag(), readFileSync(join(REPO_ROOT, design.path), "utf8"), repoFileExists);
  if (face === null) continue;
  for (const device of design.devices) {
    const oracle = JSON.parse(readFileSync(join(ORACLE, design.id, device, "fonts.json"), "utf8"));
    const baked = bakeFonts(face, db.get(device), readFont);
    for (const [name, font] of baked) {
      if (name.startsWith("icon_")) continue; // sized differently: a deviation of its own
      const want = oracle[name];
      if (want === undefined || font.sheet === null || want.sheet === null) continue;
      const sheet = Buffer.from(want.sheet.bytes, "base64");
      const aa = font.antialias ? "aa" : "1-bit";
      const key = `${font.face} ${aa}`;
      const row = rows.get(key) ?? { glyphs: 0, identical: 0, sameBox: 0, ink: 0, inkDiff: 0, boxInk: 0, boxInkDiff: 0 };
      rows.set(key, row);
      for (const [ch, g] of font.glyphs) {
        const w = want.glyphs[ch];
        row.glyphs++;
        const same = g.width === w.width && g.height === w.height && g.xoffset === w.xoffset && g.yoffset === w.yoffset;
        let ink = 0, diff = 0;
        const at = (bytes: Uint8Array | Buffer, side: number, x: number, y: number, gx: number, gy: number, gw: number, gh: number): number =>
          x < gw && y < gh ? bytes[(gy + y) * side + gx + x]! : 0;
        const width = Math.max(g.width, w.width), height = Math.max(g.height, w.height);
        for (let y = 0; y < height; y++) {
          for (let x = 0; x < width; x++) {
            const a = at(font.sheet.bytes, font.sheet.width, x, y, g.x, g.y, g.width, g.height);
            const b = at(sheet, want.sheet.size[0], x, y, w.x, w.y, w.width, w.height);
            if (a || b) ink++;
            if ((font.antialias ? Math.abs(a - b) > 32 : a !== b)) diff++;
          }
        }
        row.ink += ink;
        row.inkDiff += diff;
        if (same) {
          row.sameBox++;
          row.boxInk += ink;
          row.boxInkDiff += diff;
          if (diff === 0) row.identical++;
        }
      }
    }
  }
}
const pct = (a: number, b: number): string => (b ? `${(100 * a / b).toFixed(2)} %` : "-");
console.log("| font | glyphs | identical | same box and offsets | differing ink, all | ... where the box agrees |");
console.log("|---|---:|---:|---:|---:|---:|");
for (const [key, r] of [...rows].sort()) {
  console.log(`| ${key} | ${r.glyphs} | ${r.identical} | ${r.sameBox} | ${pct(r.inkDiff, r.ink)} | ${pct(r.boxInkDiff, r.boxInk)} |`);
}
