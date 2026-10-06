// The kind registry agrees with the schema: every element `type:` is built by
// a registered kind, and every kind is reached from one.
import assert from "node:assert/strict";
import { test } from "node:test";
import { kindOf, names } from "../src/kinds/index.ts";
import { installAssets } from "../src/node.ts";
import { ELEMENT_TYPES } from "../src/validate.ts";

installAssets();

test("every schema element type has a kind, and every kind a schema type", () => {
  const reached = new Set(ELEMENT_TYPES().map((type) => kindOf(new Map([["type", type]]))));
  assert.deepEqual([...reached].sort(), [...names()].sort());
});
