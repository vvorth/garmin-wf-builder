// The slow suite (`npm run test:slow`): real `monkeyc` builds. Every design
// the Python suite's slow tests built (test/corpus/slow-designs.json.gz),
// and every example and fixture, that loads with no error builds on all of
// its targets with no warning or error from `monkeyc` itself. Lints are the
// goldens' business, not this suite's.
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { gunzipSync } from "node:zlib";
import { REPO_ROOT } from "../src/devices/node.ts";
import { Bag } from "../src/diagnostics.ts";
import { build, loadDesign, Toolchain } from "../src/node_build.ts";
import { db, exampleDesigns } from "../tools/goldens.ts";

const toolchain = Toolchain.discover();
const work = mkdtempSync(join(tmpdir(), "wfb-slow-"));

interface Corpus {
  blobs: Record<string, { text: string } | { base64: string } | { repo: string }>;
  designs: { id: string; design: string; files: Record<string, string> }[];
}

/** The slow corpus's designs written out, `_repo_/` back to this repository: their paths. */
function slowDesigns(): string[] {
  const corpus = JSON.parse(gunzipSync(readFileSync(join(REPO_ROOT, "ts", "test", "corpus", "slow-designs.json.gz"))).toString()) as Corpus;
  return corpus.designs.map((d) => {
    for (const [name, key] of Object.entries(d.files)) {
      const blob = corpus.blobs[key]!;
      const path = join(work, d.id, name);
      mkdirSync(dirname(path), { recursive: true });
      if ("text" in blob) writeFileSync(path, blob.text.replaceAll("_repo_/", REPO_ROOT + "/"));
      else if ("base64" in blob) writeFileSync(path, Buffer.from(blob.base64, "base64"));
      else writeFileSync(path, readFileSync(join(REPO_ROOT, blob.repo)));
    }
    return join(work, d.id, d.design);
  });
}

async function check(path: string): Promise<void> {
  const loaded = new Bag();
  const face = loadDesign(path, loaded);
  if (face === null || !loaded.ok()) return; // written to be refused: the goldens hold that
  const bag = new Bag();
  const result = await build(path, { output: join(work, "out", String(Math.random()).slice(2)), bag, db, toolchain });
  const compiler = bag.items.filter((d) => d.code === "monkeyc" || d.severity === "error");
  assert.deepEqual(compiler.map((d) => `${d.severity}: ${d.message}`), [], path);
  assert.ok(result !== null);
  assert.deepEqual([...result.products.keys()].sort(), result.devices.map((d) => d.id).sort(), path);
}

test("the toolchain is installed", () => {
  assert.ok(toolchain !== null, "set CIQ_SDK, or run tools/setup-env.sh");
});

test("every slow-test design builds with nothing from monkeyc", async () => {
  for (const path of slowDesigns()) await check(path);
});

test("every example and fixture builds with nothing from monkeyc", async () => {
  for (const design of exampleDesigns()) {
    if (design.includes("/dashboard/")) continue; // the user's playground
    await check(join(REPO_ROOT, design));
  }
});
