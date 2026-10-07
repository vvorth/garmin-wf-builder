// The draw program: Monkey C's arithmetic in the evaluator, and the barrel's arcs.
import assert from "node:assert/strict";
import { test } from "node:test";
import { drawProgress, drawSpan, pillowArc } from "../src/draw/barrel.ts";
import { numValue } from "../src/draw/evaluator.ts";
import { Bin, Const, FloatLit, Lit, Paren } from "../src/draw/program.ts";
import { PyFloat } from "../src/edit/yaml.ts";

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
