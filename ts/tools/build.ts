// Build a design with the TypeScript compiler, as `wfb build` does:
//   node tools/build.ts <design.yaml> [-d device ...] [-o out]
// Prints every diagnostic and each device's measured memory; exits 1 on an
// error, or on a warning with --strict.
import { parseArgs } from "node:util";
import { DeviceDatabase } from "../src/devices/device.ts";
import { NodeDeviceFiles } from "../src/devices/node.ts";
import { Bag } from "../src/diagnostics.ts";
import { NodeFontFiles } from "../src/fonts/node.ts";
import { installAssets } from "../src/node.ts";
import { build } from "../src/node_build.ts";

installAssets();
const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: { device: { type: "string", short: "d", multiple: true }, output: { type: "string", short: "o", default: "build-ts" }, strict: { type: "boolean", default: false } },
});
const bag = new Bag();
const db = new DeviceDatabase(NodeDeviceFiles.discover(), new NodeFontFiles());
const result = await build(positionals[0]!, { output: values.output!, bag, devicesOnly: values.device ?? null, db });
for (const d of bag.items) {
  console.log(`${d.severity}: [${d.code}] ${d.message}${d.span ? ` (${d.span})` : ""}`);
  for (const note of d.notes) console.log(`    ${note}`);
}
if (result !== null) for (const [device, product] of result.products) console.log(`built ${device}: ${product}`);
const bad = bag.items.some((d) => d.severity === "error" || (values.strict && d.severity === "warning"));
process.exitCode = result === null || bad ? 1 : 0;
