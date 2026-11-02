// Extracts the per-device reference from the Connect IQ SDK's offline docs
// (`ts/src/devices/reference.ts` does the work).
//
// `wfb` extracts it itself, into the checkout's `.cache/device-reference/`
// (or `$XDG_CACHE_HOME/wfb/device-reference/` when the checkout is not
// writable), whenever it is missing or came from another SDK release than
// the one found; `tools/setup-env.sh` runs this tool for the same result up
// front. The output is derived data, never committed.
//
//   node ts/tools/extract-device-reference.ts [--sdk ~/ciq/sdks/9.3.0] [--out DIR] [--sdk-version 9.3.0]
import { join } from "node:path";
import { parseArgs } from "node:util";
import { REPO_ROOT } from "../src/devices/node.ts";
import { extractDeviceReference } from "../src/devices/reference.ts";
import { expandHome, findSdk, sdkVersion } from "../src/sdk.ts";

const { values } = parseArgs({
  options: {
    // An SDK root; by default the one `wfb` would compile with.
    sdk: { type: "string", default: "" },
    // The SDK release, when --sdk has no bin/version.txt (an SDK pruned to its doc pages).
    "sdk-version": { type: "string", default: "" },
    out: { type: "string", default: join(REPO_ROOT, ".cache", "device-reference") },
  },
});
const sdk = values.sdk ? expandHome(values.sdk) : findSdk()?.root;
if (sdk === undefined) {
  console.error("error: no Connect IQ SDK found; pass --sdk, or run `wfb init`");
  process.exit(1);
}
const out = expandHome(values.out!);
try {
  const count = extractDeviceReference(sdk, out, values["sdk-version"] || sdkVersion(sdk));
  console.log(`parsed ${count} devices -> ${out}`);
} catch (error) {
  console.error(`error: ${(error as Error).message}`);
  process.exit(1);
}
