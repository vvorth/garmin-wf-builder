// Device files from the SDK's folders on disk (`NodeDeviceFiles.discover`).
// Node only: the
// browser bundle never imports this module.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DeviceError } from "./device.ts";
import type { DeviceFiles } from "./files.ts";

export { DeviceError };

/** The repository root: `ts/src/devices/` is three levels below it. */
export const REPO_ROOT = resolve(fileURLToPath(import.meta.url), "../../../..");

/** One JSON page per device, extracted from the installed SDK's device reference. */
export const DEVICE_REFERENCE = join(REPO_ROOT, ".cache", "device-reference", "devices");

export const DEFAULT_DEVICE_ROOTS = [
  join(homedir(), ".Garmin", "ConnectIQ", "Devices"),
  join(homedir(), "Library", "Application Support", "Garmin", "ConnectIQ", "Devices"),
];

/** The SDK device reference has not been generated yet. */
export class DeviceReferenceMissing extends DeviceError {}

export class NodeDeviceFiles implements DeviceFiles {
  readonly root: string;
  readonly referenceDir: string;

  constructor(root: string, referenceDir: string = DEVICE_REFERENCE) {
    this.root = root;
    this.referenceDir = referenceDir;
  }

  /** The first of `override`, `WFB_DEVICES` and the SDK Manager's folders that holds devices. */
  static discover(override?: string, referenceDir: string = DEVICE_REFERENCE): NodeDeviceFiles {
    const candidates = [override, process.env["WFB_DEVICES"], ...DEFAULT_DEVICE_ROOTS]
      .filter((path): path is string => Boolean(path));
    if (!existsSync(referenceDir)) {
      throw new DeviceReferenceMissing(
        `no SDK device reference at ${referenceDir}.  It is generated from the installed SDK: ` +
        "run ./tools/setup-env.sh, or node ts/tools/extract-device-reference.ts on its own.",
      );
    }
    for (const path of candidates) {
      if (existsSync(path) && readdirSync(path).length > 0) return new NodeDeviceFiles(path, referenceDir);
    }
    throw new DeviceError(
      "no Connect IQ device definitions found.  They cannot be downloaded " +
      "(api.gcs.garmin.com returns HTTP 401); run ./tools/setup-env.sh, " +
      "or set WFB_DEVICES to a directory containing them.",
    );
  }

  ids(): string[] {
    return readdirSync(this.root).filter((id) => existsSync(join(this.root, id, "compiler.json"))).sort();
  }

  file(id: string, name: string): Uint8Array | undefined {
    const path = join(this.root, id, name);
    if (!existsSync(path)) return undefined;
    // A plain Uint8Array, not a Buffer, so Node and the browser hand the
    // compiler the same type.
    const bytes = readFileSync(path);
    return new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  }

  reference(id: string): unknown {
    const path = join(this.referenceDir, `${id}.json`);
    return existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : undefined;
  }

  referenceIds(): string[] {
    return readdirSync(this.referenceDir).filter((name) => name.endsWith(".json")).map((name) => name.slice(0, -5)).sort();
  }
}
