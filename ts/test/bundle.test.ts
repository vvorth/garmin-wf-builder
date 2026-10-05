// Everything reachable from the browser entry must run in a browser: a
// `node:` import anywhere below src/browser.ts fails this bundle.
import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";

test("the browser bundle builds with no Node module reachable", async () => {
  const result = await build({
    entryPoints: [new URL("../src/browser.ts", import.meta.url).pathname],
    bundle: true, write: false, platform: "browser", format: "esm", logLevel: "silent",
  }).catch((error: { errors?: { text: string }[] }) => error);
  assert.ok(!("errors" in result) || result.errors?.length === 0,
    JSON.stringify((result as { errors?: unknown }).errors));
  const text = new TextDecoder().decode((result as { outputFiles: { contents: Uint8Array }[] }).outputFiles[0]!.contents);
  assert.doesNotMatch(text, /from ["']node:|require\(["']node:/);
});
