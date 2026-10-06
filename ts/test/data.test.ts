// The tables in src/data/ that copy files elsewhere are up to date with them.
import assert from "node:assert/strict";
import { test } from "node:test";
import { exportData } from "../tools/export-data.ts";

test("src/data's copies of runtime-lib/ and templates/ are fresh", () => {
  assert.deepEqual(exportData(true), [], "run node ts/tools/export-data.ts");
});
