// The draw program: the Pillow rasteriser against the browser's reference
// copy, Monkey C's arithmetic in the evaluator, and the barrel's arcs.
import assert from "node:assert/strict";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { REPO_ROOT } from "../src/devices/node.ts";
import { drawProgress, drawSpan, pillowArc } from "../src/draw/barrel.ts";
import { numValue } from "../src/draw/evaluator.ts";
import { Bin, Const, FloatLit, Lit, Paren } from "../src/draw/program.ts";
import { PyFloat } from "../src/edit/yaml.ts";
import * as pillow from "../src/raster/pillow.ts";

// ts/app/raster.js is checked pixel for pixel against Pillow itself (tests/test_studio_raster.py).
const reference = await import(pathToFileURL(join(REPO_ROOT, "ts", "app", "raster.js")).href) as {
  image(w: number, h: number, ground?: number[]): pillow.Image;
  drawOps(im: pillow.Image, ops: unknown[], tiles: Record<string, unknown>, scale: number): void;
};

/** A sweep of every primitive the draw program emits, at awkward sizes and positions. */
function sweep(): pillow.JsonOp[] {
  const ops: pillow.JsonOp[] = [];
  let seed = 7;
  const rand = (n: number): number => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return (seed / 2147483648) * n;
  };
  for (let i = 0; i < 60; i++) {
    ops.push({ op: "color", rgb: [Math.floor(rand(256)), Math.floor(rand(256)), Math.floor(rand(256))] });
    ops.push({ op: "pen", width: 1 + Math.floor(rand(5)) });
    // A box under a pixel wide is one Pillow refuses; `Dc` sizes are whole pixels.
    const x = rand(60) - 5, y = rand(60) - 5, w = 1 + rand(30), h = 1 + rand(30);
    ops.push({ op: ["fillRectangle", "drawRectangle"][i % 2]!, args: [x, y, w, h] });
    ops.push({ op: ["fillRoundedRectangle", "drawRoundedRectangle"][i % 2]!, args: [x, y, w + 4, h + 4, rand(8)] });
    ops.push({ op: ["fillCircle", "drawCircle"][i % 2]!, args: [x, y, rand(20)] });
    ops.push({ op: ["fillEllipse", "drawEllipse"][i % 2]!, args: [x, y, rand(20), rand(12)] });
    ops.push({ op: "drawLine", args: [x, y, rand(64), rand(64)] });
    ops.push({ op: "fillPolygon", const: "", points: [[x, y], [rand(64), rand(64)], [rand(64), rand(64)], [rand(64), rand(64)]] });
    const call = drawSpan(rand(720) - 360, rand(720) - 360);
    ops.push({ op: "arc", cx: x, cy: y, radius: rand(25), pen: 1 + Math.floor(rand(6)), call });
  }
  return ops;
}

test("the Pillow rasteriser draws every primitive as the browser's reference copy does", () => {
  const ops = sweep();
  let refused = 0;
  for (const scale of [1, 2]) {
    const ours = pillow.image(64 * scale, 64 * scale), theirs = reference.image(64 * scale, 64 * scale);
    let color: pillow.JsonOp = { op: "color", rgb: [255, 255, 255] }, pen: pillow.JsonOp = { op: "pen", width: 1 };
    for (const op of ops) {
      if (op.op === "color") color = op;
      if (op.op === "pen") pen = op;
      // Pillow refuses some boxes (an outline wider than its rectangle): both copies must refuse the same ones.
      const run = (draw: () => void): string | null => {
        try {
          draw();
          return null;
        } catch (error) {
          return String(error);
        }
      };
      const a = run(() => pillow.drawOps(ours, [color, pen, op], {}, scale));
      const b = run(() => reference.drawOps(theirs, [color, pen, op], {}, scale));
      assert.equal(a, b);
      if (a !== null) refused++;
    }
    assert.deepEqual(Buffer.from(ours.data), Buffer.from(theirs.data));
  }
  assert.ok(refused < ops.length / 4, `${refused} refused`);
});

test("a chain of operators evaluates as Monkey C parses the printed text", () => {
  // `Layout.W * 3 / 2`: two Numbers divide whole, left to right.
  assert.equal(numValue(Bin("/", Bin("*", Const("W", 7), Lit(3)), Lit(2))), 10);
  // `Layout.X + 7 / 2` binds `/` first, whatever way the tree nests: 2 + 3, not 9 / 2.
  assert.equal(numValue(Bin("/", Bin("+", Const("X", 2), Lit(7)), Lit(2))), 5);
  assert.equal(numValue(Bin("/", Paren(Bin("+", Const("X", 2), Lit(7))), Lit(2))), 4);
  // `-7 / 2` truncates toward zero, and `%` keeps the dividend's sign.
  assert.equal(numValue(Bin("/", Lit(-7), Lit(2))), -3);
  assert.equal(numValue(Bin("%", Lit(-7), Lit(2))), -1);
  // A Float on either side divides exactly, even when it is a whole number.
  const half = numValue(Bin("/", Lit(new PyFloat(7)), Lit(2)));
  assert.equal(half, 3.5);
  assert.equal(numValue(Bin("/", Lit(7), FloatLit(2.0))), 3.5);
});

test("an arc's dc.drawArc call: whole degrees, the full circle, and the fill fraction", () => {
  assert.deepEqual(drawSpan(90, 90), [90, 0, true]);
  assert.deepEqual(drawSpan(90, -90), [90, 180, false]);
  assert.deepEqual(drawSpan(-0.5, 359.5), [359, 359, true]); // half away from zero, both ways
  assert.equal(drawSpan(10, 0.4), null);
  assert.deepEqual(pillowArc([90, 90, true]), [-90, 270]);
  assert.deepEqual(pillowArc([90, 0, true]), [-90, 0]);
  assert.equal(drawProgress(90, 360, 0), null);
  assert.deepEqual(drawProgress(90, 360, 2), drawSpan(90, 360));
  assert.deepEqual(drawProgress(90, 360, 0.25), [90, 0, true]);
});
