// `wfb export`'s checks that need no SDK: reading `monkeyc`'s build stats
// in either layout, splitting an export's run per device, the app id
// warnings, and which devices `--all-devices` takes.
import assert from "node:assert/strict";
import { join } from "node:path";
import { test } from "node:test";
import { faceCapableDevices } from "../src/build.ts";
import { DeviceDatabase } from "../src/devices/device.ts";
import { NodeDeviceFiles, REPO_ROOT } from "../src/devices/node.ts";
import { Bag } from "../src/diagnostics.ts";
import { NodeFontFiles } from "../src/fonts/node.ts";
import { checkMemory } from "../src/lint.ts";
import { checkAppId, statsByDevice } from "../src/node_build.ts";
import { face, MINIMAL } from "./designs.ts";

const FIXTURE_DEVICES = join(REPO_ROOT, "ts", "test", "fixtures", "devices");
const db = new DeviceDatabase(NodeDeviceFiles.discover(FIXTURE_DEVICES, join(FIXTURE_DEVICES, "reference")), new NodeFontFiles());

/** `--build-stats 0` through SDK 9.2.0: grouped by section. */
const STATS_9_2 = `Build Stats:
  Data:
    Foreground: 742 bytes
  Code:
    Foreground: 2467 bytes
  Total PRG Size: 101276 bytes
`;

/** The same figures from SDK 9.3.0: grouped by segment. */
function stats93(device: string, code: number, data: number): string {
  return `
Build Stats:
  Device: ${device}
  Foreground:
    Code: ${code} bytes
    Data: ${data} bytes
    Total: ${code + data} bytes (0.41% of 786432 available)
  Extended Code:
    Page Size: 4096 bytes
    Number of Pages: 0
    Total Size: 0 bytes
  Total PRG Size: 9372 bytes
  Build Time: 0.708 seconds
`;
}

test("build stats read in the 9.2.0 and the 9.3.0 layout alike", () => {
  const device = db.get("wfbtest");
  for (const [label, text, prg] of [["9.2.0", STATS_9_2, 101276], ["9.3.0", stats93("wfbtest", 2467, 742), 9372]] as const) {
    const stats = checkMemory(device, text, new Bag());
    assert.ok(stats !== null, label);
    assert.deepEqual({ code: stats.code, data: stats.data, total: stats.total, prg: stats.prg }, { code: 2467, data: 742, total: 3209, prg }, label);
  }
  assert.equal(checkMemory(device, "BUILD SUCCESSFUL\n", new Bag()), null);
});

test("an export's run splits per device, the first block of a device built for two part numbers kept", () => {
  const text = "BUILDING FOR 3 DEVICES\n" + stats93("a", 100, 10) + "1 OUT OF 3 DEVICES BUILT\n"
    + stats93("a", 999, 99) + stats93("b", 200, 20) + "BUILD SUCCESSFUL\n";
  const blocks = statsByDevice(text);
  assert.deepEqual([...blocks.keys()], ["a", "b"]);
  const device = db.get("wfbtest");
  assert.equal(checkMemory(device, blocks.get("a")!, new Bag())!.total, 110);
  assert.equal(checkMemory(device, blocks.get("b")!, new Bag())!.total, 220);
});

test("an app id another face uses, or one no generator wrote, warns; a random one of its own does not", () => {
  const f = face(MINIMAL);
  const id = f.uuid;
  const warnings = (known: Map<string, string>): string[] => {
    const bag = new Bag();
    checkAppId(f, bag, known);
    return bag.items.map((d) => `${d.severity}[${d.code}]`);
  };
  assert.deepEqual(warnings(new Map()), []);
  assert.deepEqual(warnings(new Map([[id, "face.yaml"]])), [], "its own file is not a collision");
  assert.deepEqual(warnings(new Map([[id, "examples/other/face.yaml"]])), ["warning[app-id]"]);
  f.uuid = "22222222-3333-4444-5555-666666666666";
  assert.deepEqual(warnings(new Map()), ["warning[app-id]"]);
});

test("--all-devices takes every installed device that can run a face at the floor", () => {
  assert.deepEqual(faceCapableDevices(db), ["wfbtest"]);
});
