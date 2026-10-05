// The font bake: deterministic output, FreeType's metrics, and the PNG round trip.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { REPO_ROOT } from "../src/devices/node.ts";
import { bake, dilate, toFnt } from "../src/fonts/bake.ts";
import { decodePng, encodePng } from "../src/png.ts";

const OPEN_SANS = "tests/fixtures/slice/assets/OpenSans-Regular.ttf";
const file = (path: string) => {
  const bytes = readFileSync(join(REPO_ROOT, path));
  return { path, bytes: new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength) };
};
const sha = (b: Uint8Array): string => createHash("sha256").update(b).digest("hex");

test("baking twice gives the same sheet and metrics", () => {
  const a = bake(file(OPEN_SANS), { name: "a", size: 33, glyphs: "Fri 11:11Wed 00:00" });
  const b = bake(file(OPEN_SANS), { name: "a", size: 33, glyphs: "Fri 11:11Wed 00:00" });
  assert.equal(sha(a.sheet!.bytes), sha(b.sheet!.bytes));
  assert.equal(toFnt(a), toFnt(b));
});

test("line metrics and advances are FreeType's: Open Sans at 33 px", () => {
  // Pillow's getmetrics() and getlength(), rounded, for this file at this size.
  const font = bake(file(OPEN_SANS), { name: "a", size: 33, glyphs: "Fri 11:11Wed 00:00" });
  assert.equal(font.line_height, 46);
  assert.equal(font.base, 36);
  assert.equal(font.measure("Fri 11:11")[0], 132);
  assert.equal(font.measure("Wed 00:00")[0], 164);
});

test("a monospaced bake gives every glyph one advance", () => {
  const font = bake(file(OPEN_SANS), { name: "a", size: 33, glyphs: "Fri 11:11Wed 00:00", monospace: true });
  assert.equal(font.measure("Fri 11:11")[0], font.measure("Wed 00:00")[0]);
});

test("a ring font grows each glyph by its width and keeps the advances", () => {
  const base = bake(file(OPEN_SANS), { name: "a", size: 20, glyphs: "08" });
  const ring = dilate(base, { name: "a_ring_glyphs", glyphs: "08", width: 2 });
  for (const ch of "08") {
    const g = base.glyphs.get(ch)!, r = ring.glyphs.get(ch)!;
    assert.deepEqual([r.width, r.height, r.xoffset, r.yoffset, r.xadvance], [g.width + 4, g.height + 4, g.xoffset - 2, g.yoffset - 2, g.xadvance]);
  }
});

test("a sheet's PNG decodes back to its pixels", () => {
  const font = bake(file(OPEN_SANS), { name: "a", size: 20, glyphs: "0123456789", antialias: true });
  const png = encodePng(font.sheet!.width, font.sheet!.height, font.sheet!.bytes);
  const back = decodePng(png)!;
  const grey = back.pixels.filter((_, i) => i % 4 === 0);
  assert.equal(sha(grey), sha(font.sheet!.bytes));
});
