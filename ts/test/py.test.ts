// Python semantics the port reproduces. Each case is one where the obvious
// JavaScript gives a different answer, so the test fails against it.
import assert from "node:assert/strict";
import { test } from "node:test";
import { Timestamp } from "../src/edit/yaml.ts";
import { canonical, floatHex, formatFixed, jsonString, repr, roundHalfEven, splitlines, truthy } from "../src/py.ts";

test("f'{x:.6f}' rounds the exact binary value half to even, where toFixed rounds a tie away", () => {
  assert.equal((1 / 128).toFixed(6), "0.007813");
  assert.equal(formatFixed(1 / 128, 6), "0.007812");
  assert.equal(formatFixed(3 / 128, 6), "0.023438"); // a tie that rounds up to even
  assert.equal(formatFixed(-1 / 128, 6), "-0.007812");
  assert.equal(formatFixed(2.5, 0), "2");
  assert.equal(formatFixed(0.1, 6), "0.100000");
  assert.equal(formatFixed(1e21, 2), "1000000000000000000000.00");
});

test("round() is half to even", () => {
  assert.deepEqual([0.5, 1.5, 2.5, -0.5, -1.5, 2.6].map(roundHalfEven), [0, 2, 2, 0, -2, 3]);
});

test("repr() quotes as Python does, switching quotes around an apostrophe", () => {
  assert.equal(repr("abc"), "'abc'");
  assert.equal(repr("it's"), "\"it's\"");
  assert.equal(repr("both ' and \""), "'both \\' and \"'");
  assert.equal(repr("tab\there"), "'tab\\there'");
  assert.equal(repr(null), "None");
});

test("json.dumps(ensure_ascii=False) keeps non-ASCII and escapes control characters", () => {
  assert.equal(jsonString("°C \u0001 \"q\""), "\"°C \\u0001 \\\"q\\\"\"");
});

test("splitlines(keepends=True) splits on every boundary Python knows", () => {
  assert.deepEqual(splitlines("a\r\nb\rc\u2028d\ne"), ["a\r\n", "b\r", "c\u2028", "d\n", "e"]);
  assert.deepEqual(splitlines("a\n"), ["a\n"]);
});

test("truthiness: empty containers and zero are false, NaN is true", () => {
  assert.deepEqual([0, "", null, [], new Map(), false].map(truthy), [false, false, false, false, false, false]);
  assert.deepEqual([NaN, "0", [0], new Map([["a", 1]])].map(truthy), [true, true, true, true]);
});

test("float.hex() matches Python's", () => {
  assert.equal(floatHex(1.5), "0x1.8000000000000p+0");
  assert.equal(floatHex(0.1), "0x1.999999999999ap-4");
  assert.equal(floatHex(-3), "-0x1.8000000000000p+1");
  assert.equal(floatHex(5e-324), "0x0.0000000000001p-1022");
});

test("canonical data: 1 and 1.0 are one value, other floats are exact, mappings keep order", () => {
  const data = new Map<string | number, unknown>([["b", 1], ["a", [0.5, "é", null, true]], [2, new Timestamp("2026-10-05")]]);
  assert.equal(canonical(data as never), "{\"b\":i1,\"a\":[x0x1.0000000000000p-1,\"\\u00e9\",n,t],i2:T2026-10-05}");
});
