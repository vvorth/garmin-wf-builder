import assert from "node:assert/strict";
import { test } from "node:test";
import { compare } from "../tools/compare.ts";

test("equal values have no differences, whatever their key order", () => {
  assert.deepEqual(compare({ a: 1, b: [1, { c: "x" }] }, { b: [1, { c: "x" }], a: 1 }), []);
});

test("Python's 1.0 and JavaScript's 1 are the same number", () => {
  assert.deepEqual(compare(JSON.parse("{\"x\": 1.0}"), { x: 1 }), []);
});

test("a changed leaf is reported at its path", () => {
  assert.deepEqual(compare({ a: { b: [1, 2] } }, { a: { b: [1, 3] } }), [
    { path: "$.a.b[1]", expected: 2, actual: 3 },
  ]);
});

test("a missing and an extra key are each reported", () => {
  assert.deepEqual(compare({ a: 1, "two words": 2 }, { a: 1, c: 3 }), [
    { path: "$[\"two words\"]", expected: 2, actual: undefined },
    { path: "$.c", expected: undefined, actual: 3 },
  ]);
});

test("arrays of different lengths report the length, then the shared items", () => {
  assert.deepEqual(compare([1, 2, 3], [1, 9]), [
    { path: "$.length", expected: 3, actual: 2 },
    { path: "$[1]", expected: 2, actual: 9 },
  ]);
});

test("null is not an empty object, and a string is not a number", () => {
  assert.equal(compare({ a: null }, { a: {} }).length, 1);
  assert.equal(compare({ a: "1" }, { a: 1 }).length, 1);
});

test("the report stops at the limit", () => {
  const many = Array.from({ length: 50 }, (_, i) => i);
  assert.equal(compare(many, many.map((n) => n + 1), 5).length, 5);
});
