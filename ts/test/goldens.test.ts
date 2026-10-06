// The compiler's output frozen: every corpus design's diagnostics, and each
// example's and fixture's diagnostics, generated projects and previews.
// These replace the Python oracle: a difference is an output change, to be
// explained, then accepted with `WFB_UPDATE_GOLDENS=1 npm test` (or
// `node tools/goldens.ts`) and reviewed in the diff of test/goldens/.
import assert from "node:assert/strict";
import { test } from "node:test";
import { corpusDiagnostics, exampleDesigns, exampleGoldens, read, write } from "../tools/goldens.ts";

const update = process.env["WFB_UPDATE_GOLDENS"] === "1";

/** The first line where `want` and `got` part, for a readable failure. */
function firstDifference(want: string, got: string): string {
  const a = want.split("\n"), b = got.split("\n");
  const i = a.findIndex((line, n) => line !== b[n]);
  const at = i < 0 ? a.length : i;
  return `line ${at + 1}:\n  - ${a[at] ?? "(end)"}\n  + ${b[at] ?? "(end)"}`;
}

function compare(name: string, got: Record<string, unknown>): void {
  if (update) {
    write(name, got);
    return;
  }
  const want = read(name) as Record<string, unknown> | null;
  assert.ok(want !== null, `no ${name}: run WFB_UPDATE_GOLDENS=1 npm test`);
  const changed: string[] = [];
  for (const key of new Set([...Object.keys(want), ...Object.keys(got)])) {
    const [a, b] = [JSON.stringify(want[key] ?? null, null, 1), JSON.stringify(got[key] ?? null, null, 1)];
    if (a === b) continue;
    const [wa, gb] = [typeof want[key] === "string" ? want[key] as string : a, typeof got[key] === "string" ? got[key] as string : b];
    changed.push(`${key}: ${firstDifference(wa, gb)}`);
  }
  assert.deepEqual(changed.slice(0, 10), [], `${changed.length} of ${Object.keys(want).length} changed in ${name}`);
}

test("every corpus design's diagnostics are as frozen", () => {
  compare("corpus-diagnostics.json", corpusDiagnostics());
});

test("every example's diagnostics, projects and previews are as frozen", () => {
  compare("examples.json", Object.fromEntries(exampleDesigns().map((p) => [p, exampleGoldens(p)])));
});
