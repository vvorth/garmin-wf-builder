// The slow suite (`npm run test:slow`): real `monkeyc` builds. Every design
// the Python suite's slow tests built (test/corpus/slow-designs.json.gz),
// and every example and fixture, that loads with no error builds on all of
// its targets with no warning or error from `monkeyc` itself. Lints are the
// goldens' business, not this suite's.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { gunzipSync } from "node:zlib";
import { REPO_ROOT } from "../src/devices/node.ts";
import { Bag } from "../src/diagnostics.ts";
import { build, exportApp, loadDesign, Toolchain } from "../src/node_build.ts";
import { javaBinary } from "../src/sdk.ts";
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
  assert.deepEqual([...result.memory.keys()].sort(), result.devices.map((d) => d.id).sort(), `${path}: every device's memory measured`);
}

test("the toolchain is installed", () => {
  assert.ok(toolchain !== null, "set CIQ_SDK, or run tools/setup-env.sh");
});

test("every slow-test design builds with nothing from monkeyc", async () => {
  for (const path of slowDesigns()) await check(path);
});

test("every example and fixture builds with nothing from monkeyc", async () => {
  for (const design of exampleDesigns()) {
    await check(join(REPO_ROOT, design));
  }
});

test("an export is one 7z .iq, every target's memory measured, with nothing from monkeyc", async () => {
  const bag = new Bag();
  const path = join(REPO_ROOT, "examples", "features", "graph", "face.yaml");
  const result = await exportApp(path, { output: join(work, "export"), bag, db, toolchain, known: new Map() });
  assert.deepEqual(bag.items.filter((d) => d.code === "monkeyc" || d.severity === "error").map((d) => `${d.severity}: ${d.message}`), []);
  assert.ok(result !== null && result.iq !== null);
  assert.match(result.iq, /feature-graph-1\.0\.0\.iq$/);
  assert.deepEqual([...readFileSync(result.iq).subarray(0, 6)], [0x37, 0x7a, 0xbc, 0xaf, 0x27, 0x1c]);
  assert.deepEqual([...result.memory.keys()].sort(), result.devices.map((d) => d.id).sort());
});

/**
 * Every entry of a 7z archive, by name: listed with the Apache Commons
 * Compress classes inside the SDK's own compiler jar (`monkeyc -e` writes
 * the `.iq` with them), as neither Node nor a guaranteed system tool reads 7z.
 */
function list7z(archive: string): string[] {
  const source = join(work, "List7z.java");
  writeFileSync(source, [
    "import org.apache.commons.compress.archivers.sevenz.SevenZArchiveEntry;",
    "import org.apache.commons.compress.archivers.sevenz.SevenZFile;",
    "public class List7z {",
    "  @SuppressWarnings(\"deprecation\")",
    "  public static void main(String[] args) throws Exception {",
    "    try (SevenZFile f = new SevenZFile(new java.io.File(args[0]))) {",
    "      for (SevenZArchiveEntry e : f.getEntries()) System.out.println(e.getName());",
    "    }",
    "  }",
    "}",
    "",
  ].join("\n"));
  const jar = join(toolchain!.sdk, "bin", "monkeybrains.jar");
  return execFileSync(javaBinary(), ["-cp", jar, source, archive], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).split("\n").filter(Boolean);
}

/** A device's part numbers, as the `.iq` names its directories. */
const partNumbers = (id: string): string[] =>
  (db.get(id).compiler["partNumbers"] as { number: string }[]).map((p) => p.number);

test("an export carries phone settings for a settings-menu device and none for a native-editor one", async () => {
  const bag = new Bag();
  const path = join(REPO_ROOT, "examples", "features", "config", "face.yaml");
  const result = await exportApp(path, { output: join(work, "export-config"), bag, db, toolchain, known: new Map() });
  assert.deepEqual(bag.items.filter((d) => d.code === "monkeyc" || d.severity === "error").map((d) => `${d.severity}: ${d.message}`), []);
  assert.ok(result !== null && result.iq !== null);
  const entries = list7z(result.iq);
  const settings = entries.filter((e) => e.endsWith("-settings.json"));
  assert.deepEqual(settings, partNumbers("fr955").map((pn) => `${pn}/${pn}-settings.json`), entries.join("\n"));
  for (const id of ["fenix8solar47mm", "fenix8solar51mm"]) {
    for (const pn of partNumbers(id)) {
      assert.ok(entries.includes(`${pn}/feature-config-1.0.0.prg`), `${id}: ${pn}`);
      assert.ok(!entries.some((e) => e.startsWith(`${pn}/`) && e.includes("settings")), `${id}: ${pn} has no settings`);
    }
  }
});
