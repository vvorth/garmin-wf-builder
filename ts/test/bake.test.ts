// The font bake: deterministic output, FreeType's metrics, and the PNG round trip.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { REPO_ROOT } from "../src/devices/node.ts";
import { bake, dilate, toFnt } from "../src/fonts/bake.ts";
import { decodePng, encodePng } from "../src/png.ts";

const OPEN_SANS = "ts/test/fixtures/slice/assets/OpenSans-Regular.ttf";
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

/** One glyph's tile out of a sheet, as rows of 0/1. */
function tile(font: ReturnType<typeof bake>, ch: string): number[][] {
  const g = font.glyphs.get(ch)!, sheet = font.sheet!;
  return Array.from({ length: g.height }, (_, y) => Array.from({ length: g.width }, (_, x) => (sheet.bytes[(g.y + y) * sheet.width + g.x + x]! ? 1 : 0)));
}

/** The share of ink two same-sized tiles agree on (intersection over union). */
function agreement(a: number[][], b: number[][]): number {
  if (a.length !== b.length || a[0]!.length !== b[0]!.length) return 0;
  let both = 0, either = 0;
  a.forEach((row, y) => row.forEach((v, x) => { both += v & b[y]![x]!; either += v | b[y]![x]!; }));
  return both / either;
}

test("a turned bake turns each glyph clockwise, not counter-clockwise", () => {
  // "L" has no symmetry that would make the two directions agree.
  const upright = tile(bake(file(OPEN_SANS), { name: "a", size: 40, glyphs: "L" }), "L");
  const turned = tile(bake(file(OPEN_SANS), { name: "a", size: 40, glyphs: "L", rotate: 90 }), "L");
  const h = upright.length, w = upright[0]!.length;
  const clockwise = Array.from({ length: w }, (_, y) => Array.from({ length: h }, (_, x) => upright[h - 1 - x]![y]!));
  const counter = Array.from({ length: w }, (_, y) => Array.from({ length: h }, (_, x) => upright[x]![w - 1 - y]!));
  assert.ok(agreement(turned, clockwise) > 0.9, `clockwise agreement ${agreement(turned, clockwise)}`);
  assert.ok(agreement(turned, counter) < 0.6, `counter-clockwise agreement ${agreement(turned, counter)}`);
});

test("a turned glyph turns about the point a centred drawText anchors", () => {
  // Half a turn mirrors the ink centre through the pivot: half the advance, half the line.
  const upright = bake(file(OPEN_SANS), { name: "a", size: 40, glyphs: "L" });
  const half = bake(file(OPEN_SANS), { name: "a", size: 40, glyphs: "L", rotate: 180 });
  const g0 = upright.glyphs.get("L")!, g1 = half.glyphs.get("L")!;
  const px = g0.xadvance / 2, py = upright.line_height / 2;
  const c0 = [g0.xoffset + g0.width / 2 - px, g0.yoffset + g0.height / 2 - py];
  const c1 = [g1.xoffset + g1.width / 2 - px, g1.yoffset + g1.height / 2 - py];
  assert.ok(Math.abs(c0[0]! + c1[0]!) <= 1 && Math.abs(c0[1]! + c1[1]!) <= 1, `centres ${c0} and ${c1}`);
  assert.equal(g1.xadvance, g0.xadvance);
});
