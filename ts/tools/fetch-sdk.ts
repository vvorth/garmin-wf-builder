// Downloads and unpacks the Connect IQ SDK, stripped to the compiler, for a
// machine that will mount or point `wfb` at it (the container's smoke test
// does; `tools/setup-env.sh` installs the whole SDK instead). Downloading
// the SDK accepts Garmin's Connect IQ Developer Agreement
// (https://developer.garmin.com/connect-iq/sdk/), which licenses it to the
// person downloading, for developing and testing: a pruned SDK is still
// Garmin's, and is not to be put in an image or an archive for others.
//
// The full SDK is 309 MB. `doc/`, `resources/` and `samples/` are
// documentation; `share/` and the simulator, ERA, MonkeyMotion, the language
// server and the FIT graph tool are GUI and analysis programs a build does
// not run. What is kept (`prunedSdkKeeps` in `ts/src/sdk.ts`) -- the compiler,
// its API database and the resource XSD, the per-device reference pages
// under `doc/docs/Device_Reference/` that `wfb` extracts the device reference
// from, and the SDK's own licence texts and third-party notices -- is about
// 48 MB and builds every target. Pruned files are skipped before they are
// inflated, so the archive never needs its full size in memory.
//
//   node ts/tools/fetch-sdk.ts URL [DESTINATION]
//   node ts/tools/fetch-sdk.ts --newest [--version 9.3.0] [DESTINATION]
//
// `--newest` looks the newest Linux release up in Garmin's `sdks.json`
// (`SDK_BASE_URL` names a mirror), `--version` one release.
import { chmodSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { parseArgs } from "node:util";
import { unzipSync } from "fflate";
import { listSdks, pickLinuxSdk, SDK_DOWNLOADS } from "../src/init.ts";
import { prunedSdkKeeps } from "../src/sdk.ts";

const EXECUTABLE = ["monkeyc", "monkeydo"];
const BASE_URL = process.env["SDK_BASE_URL"] || SDK_DOWNLOADS;

const { values, positionals } = parseArgs({
  options: { newest: { type: "boolean", default: false }, version: { type: "string" } },
  allowPositionals: true,
});

/** The Linux archive of the newest release in `sdks.json`, or of `version`. */
async function newestArchive(version: string | undefined): Promise<string> {
  const chosen = pickLinuxSdk(await listSdks(BASE_URL), version);
  if (chosen === null) throw new Error(version ? `sdks.json lists no Linux SDK ${version}` : "sdks.json lists no Linux SDK");
  return `${BASE_URL}/${chosen.linux}`;
}

let url: string, destination: string;
if (values.newest) {
  url = await newestArchive(values.version);
  destination = positionals[0] ?? "/opt/ciq";
} else {
  if (positionals[0] === undefined) throw new Error("usage: fetch-sdk.ts URL [DESTINATION], or --newest [--version X] [DESTINATION]");
  [url, destination = "/opt/ciq"] = positionals as [string, string?];
}

console.log(`fetching ${url}`);
const response = await fetch(url, { signal: AbortSignal.timeout(600_000) });
if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
const archive = new Uint8Array(await response.arrayBuffer());
console.log(`fetched ${Math.floor(archive.length / (1024 * 1024))} MB`);

const files = unzipSync(archive, { filter: (file) => !file.name.endsWith("/") && prunedSdkKeeps(file.name) });
let size = 0;
for (const [name, content] of Object.entries(files)) {
  const path = join(destination, name);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content);
  size += content.length;
}
for (const name of EXECUTABLE) {
  const path = join(destination, "bin", name);
  if (existsSync(path)) chmodSync(path, 0o755);
}
if (!existsSync(join(destination, "bin", "monkeybrains.jar"))) throw new Error(`the archive has no bin/monkeybrains.jar: not a Connect IQ SDK`);
console.log(`pruned SDK is ${Math.floor(size / (1024 * 1024))} MB at ${destination}`);
