// Codegen helpers: the writer's layout, and the string labels monkeyc would collide on.
import assert from "node:assert/strict";
import { test } from "node:test";
import { collisions, javaStringHash, stringLiterals } from "../src/emit/strhash.ts";
import { Writer } from "../src/emit/writer.ts";

test("two glyphs 993 codepoints apart share monkeyc's string label", () => {
  // the `distance` and `temperature` glyphs, reproduced against a real build
  assert.equal(javaStringHash("\u{F08F0}"), 1798574);
  assert.equal(javaStringHash("\u{F050F}"), 1798574);
  assert.notEqual(javaStringHash("\u{F08F0}"), javaStringHash("\u{F0510}"));
  const found = collisions(new Map([["a.mc", 'var a = "\u{F08F0}";'], ["b.mc", 'var b = "\u{F050F}"; // "\u{F08F0}"']]));
  assert.equal(found.length, 1);
  // by code point: U+F050F first; the copy in b.mc's comment is not a literal
  assert.deepEqual([...found[0]!.strings.values()], [["b.mc"], ["a.mc"]]);
});

test("a string literal is read past escapes, and comments and chars are skipped", () => {
  assert.deepEqual(stringLiterals('x("a\\"b"); // "c"\n/* "d" */ var c = \'"\';'), ['a"b']);
});

test("the writer indents blocks and aligns a wrapped call under its first argument", () => {
  const w = new Writer();
  w.block("function f()", () => w.call("g", ["a, b", "c"]));
  w.blank().blank();
  assert.equal(w.render(), "function f() {\n    g(a, b,\n      c);\n}\n");
});
