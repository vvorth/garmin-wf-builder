import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { MemoryDeviceFiles, readJson } from "../src/devices/files.ts";
import { DEVICE_REFERENCE, DeviceError, NodeDeviceFiles } from "../src/devices/node.ts";

test("memory device files list only devices with a compiler.json", () => {
  const files = new MemoryDeviceFiles();
  files.add("b", "compiler.json", "{\"deviceFamily\": \"round-260x260\"}");
  files.add("a", "compiler.json", "{}");
  files.add("c", "simulator.json", "{}");
  assert.deepEqual(files.ids(), ["a", "b"]);
  assert.deepEqual(readJson(files, "b", "compiler.json"), { deviceFamily: "round-260x260" });
  assert.equal(files.file("b", "simulator.json"), undefined);
  assert.equal(files.reference("b"), undefined);
});

test("discovery refuses a missing device reference, naming how to make it", () => {
  assert.throws(() => NodeDeviceFiles.discover(undefined, "/nonexistent/reference"),
    (error: unknown) => error instanceof DeviceError && /setup-env\.sh/.test(error.message));
});

// The installed SDK devices are this project's environment (tools/setup-env.sh),
// so their absence fails rather than skips.
test("the installed devices read as wfb/devices.py reads them", () => {
  const files = NodeDeviceFiles.discover();
  const ids = files.ids();
  for (const id of ["fenix8solar47mm", "fenix8solar51mm", "fr955", "fenix847mm"]) {
    assert.ok(ids.includes(id), `${id} is installed`);
  }
  const compiler = readJson(files, "fenix847mm", "compiler.json") as { deviceFamily: string; resolution: { width: number } };
  assert.equal(compiler.deviceFamily, "round-454x454");
  assert.equal(compiler.resolution.width, 454);
  const onDisk = readFileSync(join(files.root, "fr955", "simulator.json"));
  assert.deepEqual(files.file("fr955", "simulator.json"), new Uint8Array(onDisk));
  assert.ok(existsSync(join(DEVICE_REFERENCE, "fr955.json")));
  assert.equal(typeof files.reference("fr955"), "object");
  assert.equal(files.reference("no-such-device"), undefined);
});
