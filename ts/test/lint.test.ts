// The lint's registry and suppression: what an author may silence, and the
// one rule that decides whether they did.
import assert from "node:assert/strict";
import { test } from "node:test";
import { ALL_CODES, sorted, SUPPRESSIBLE, suppressed } from "../src/lint.ts";

test("every suppressible code is a real code", () => {
  for (const code of SUPPRESSIBLE) assert.ok(ALL_CODES.has(code), code);
});

test("a code is suppressed only when it is suppressible and some owner allows it", () => {
  assert.equal(suppressed("contrast", [new Set(["contrast"])]), true);
  assert.equal(suppressed("contrast", [new Set(), new Set(["contrast"])]), true);
  assert.equal(suppressed("contrast", [new Set(["safe-area"])]), false);
  // A hard platform limit stays, whatever an element writes.
  assert.equal(suppressed("partial-update", [new Set(["partial-update"])]), false);
  assert.equal(suppressed("api-gated-unguardable", [new Set(["api-gated-unguardable"])]), false);
});

test("sorted orders by code point, as Python does", () => {
  // UTF-16 order would put U+1F600 (a surrogate pair) before U+FF5E.
  assert.deepEqual(sorted(["\u{1F600}", "～", "b", "B"]), ["B", "b", "～", "\u{1F600}"]);
});
