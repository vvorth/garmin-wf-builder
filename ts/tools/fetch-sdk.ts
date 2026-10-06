// Downloads and unpacks the Connect IQ SDK, stripped to the compiler. Run at
// image build time (see the Dockerfile).
//
// The full SDK is 309 MB. `doc/`, `resources/` and `samples/` are
// documentation; `share/` and the simulator, ERA, MonkeyMotion, the language
// server and the FIT graph tool are GUI and analysis programs the container
// does not run. What is left -- the compiler, its API database and the
// resource XSD -- is about 26 MB and builds every target correctly. Pruned
// files are skipped before they are inflated, so the archive never needs its
// full size in memory.
//
// One part of `doc/` is data rather than documentation: the per-device pages
// under `doc/docs/Device_Reference/`, which
// `ts/tools/extract-device-reference.ts` reads. `--device-reference DIR`
// writes them to `DIR/doc/docs/Device_Reference/`, so `DIR` can be passed to
// that tool as `--sdk`.
//
//   node ts/tools/fetch-sdk.ts URL [DESTINATION] [--device-reference DIR]
import { chmodSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { parseArgs } from "node:util";
import { unzipSync } from "fflate";

const PRUNE_TREES = ["doc/", "samples/", "resources/", "share/"];
const PRUNE_BIN = new Set([
  "simulator", "connectiq", "connectiq.bat",
  "monkeymotion", "monkeygraph", "monkeygraph.bat",
  "era", "era.bat", "era.jar",
  "LanguageServer.jar", "fit-graph.jar",
  "shell", "mdd", "mdd.bat", "extdata",
  "barrelbuild", "barrelbuild.bat", "barreltest", "barreltest.bat",
  "monkeydoc", "monkeydoc.bat", "monkeym", "monkeym.bat",
]);
const EXECUTABLE = ["monkeyc", "monkeydo"];
const DEVICE_REFERENCE = "doc/docs/Device_Reference/";

const { values, positionals } = parseArgs({ options: { "device-reference": { type: "string" } }, allowPositionals: true });
const [url, destination = "/opt/ciq"] = positionals;
if (url === undefined) throw new Error("usage: fetch-sdk.ts URL [DESTINATION] [--device-reference DIR]");
const reference = values["device-reference"];

console.log(`fetching ${url}`);
const response = await fetch(url, { signal: AbortSignal.timeout(600_000) });
if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
const archive = new Uint8Array(await response.arrayBuffer());
console.log(`fetched ${Math.floor(archive.length / (1024 * 1024))} MB`);

/** Where an archive member goes, or null when it is pruned. */
function target(name: string): string | null {
  if (name.startsWith(DEVICE_REFERENCE)) return reference ? join(reference, name) : null;
  if (PRUNE_TREES.some((tree) => name.startsWith(tree))) return null;
  if (!name.includes("/") && name.endsWith(".html")) return null;
  const [top, entry] = name.split("/");
  if (top === "bin" && entry !== undefined && PRUNE_BIN.has(entry)) return null;
  return join(destination, name);
}

const files = unzipSync(archive, { filter: (file) => !file.name.endsWith("/") && target(file.name) !== null });
let size = 0;
for (const [name, content] of Object.entries(files)) {
  const path = target(name)!;
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content);
  if (!(reference && name.startsWith(DEVICE_REFERENCE))) size += content.length;
}
if (reference && !existsSync(join(reference, DEVICE_REFERENCE))) throw new Error(`the SDK archive has no ${DEVICE_REFERENCE}`);
for (const name of EXECUTABLE) {
  const path = join(destination, "bin", name);
  if (!existsSync(path)) throw new Error(`the SDK archive has no bin/${name}`);
  chmodSync(path, 0o755);
}
// monkeyc rewrites it on every run, as whoever runs the container.
if (existsSync(join(destination, "bin", "default.jungle"))) chmodSync(join(destination, "bin", "default.jungle"), 0o664);
console.log(`pruned SDK is ${Math.floor(size / (1024 * 1024))} MB`);
