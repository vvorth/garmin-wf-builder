// Device files from the SDK's folders on disk (`NodeDeviceFiles.discover`),
// and the SDK device reference beside them, extracted from the installed SDK
// when it is missing or stale. Node only: the browser bundle never imports
// this module.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { cacheHome, canWriteAt, findSdk, type Sdk, sdkManagerHomes } from "../sdk.ts";
import { DeviceError } from "./device.ts";
import type { DeviceFiles } from "./files.ts";
import { extractDeviceReference, referencePages, referenceVersion } from "./reference.ts";

export { DeviceError };

/** The repository root: `ts/src/devices/` is three levels below it. */
export const REPO_ROOT = resolve(fileURLToPath(import.meta.url), "../../../..");

/** The two places an extracted reference lives: the checkout's `.cache/`, and the user's cache when the checkout is not writable. */
const REFERENCE_HOMES = [join(REPO_ROOT, ".cache", "device-reference"), join(cacheHome(), "device-reference")];

/**
 * One JSON page per device, extracted from the installed SDK's device
 * reference: `WFB_DEVICE_REFERENCE` names a folder of such pages outright
 * (the fixture device's, `ts/test/fixtures/devices/reference`, beside
 * `WFB_DEVICES` naming its device folder); otherwise the first of the
 * checkout's `.cache/device-reference/devices` and the user cache's that
 * exists, else whichever of the two an extraction would write.
 */
export function locateDeviceReference(): string {
  const named = process.env["WFB_DEVICE_REFERENCE"];
  if (named) return named;
  const existing = REFERENCE_HOMES.map((home) => join(home, "devices")).find((dir) => existsSync(dir));
  return existing ?? join(canWriteAt(REFERENCE_HOMES[0]!) ? REFERENCE_HOMES[0]! : REFERENCE_HOMES[1]!, "devices");
}

export const DEVICE_REFERENCE = locateDeviceReference();

/**
 * The reference to read: `reference` as it stands when `WFB_DEVICE_REFERENCE`
 * names it, when no SDK with the pages is installed, or when it was extracted
 * from that SDK's release; otherwise freshly extracted from the SDK -- into
 * `reference`'s own folder when that can be written, else into the user's
 * cache -- with a line on stderr saying so. About a second for the whole
 * fleet.
 */
export function ensureDeviceReference(sdk: Sdk | null = findSdk(), reference: string = DEVICE_REFERENCE): string {
  if (process.env["WFB_DEVICE_REFERENCE"] || sdk === null || !existsSync(referencePages(sdk.root))) return reference;
  const home = dirname(reference);
  if (existsSync(reference) && referenceVersion(home) === sdk.version) return reference;
  const target = canWriteAt(home) ? home : REFERENCE_HOMES[1]!;
  process.stderr.write(`wfb: extracting the device reference from SDK ${sdk.version} (${sdk.root}) into ${target}\n`);
  extractDeviceReference(sdk.root, target, sdk.version);
  return join(target, "devices");
}

/** The SDK Manager's `Devices/` folder on each OS. */
export const DEFAULT_DEVICE_ROOTS = sdkManagerHomes().map((home) => join(home, "Devices"));

/** The SDK device reference has not been generated yet. */
export class DeviceReferenceMissing extends DeviceError {}

export class NodeDeviceFiles implements DeviceFiles {
  readonly root: string;
  readonly referenceDir: string;

  constructor(root: string, referenceDir: string = DEVICE_REFERENCE) {
    this.root = root;
    this.referenceDir = referenceDir;
  }

  /**
   * The first of `override`, `WFB_DEVICES` and the SDK Manager's folders
   * that holds devices. A missing device reference is refused, unless
   * `allowMissingReference`: the editor opens without one (an SDK not yet
   * installed) and reads every device without its page, as a device the
   * reference lacks is read anyway. `allowEmpty`: with no devices anywhere,
   * the first candidate, empty (the editor opens and says so).
   */
  static discover(override?: string, referenceDir: string = ensureDeviceReference(), { allowMissingReference = false, allowEmpty = false } = {}): NodeDeviceFiles {
    const candidates = [override, process.env["WFB_DEVICES"], ...DEFAULT_DEVICE_ROOTS]
      .filter((path): path is string => Boolean(path));
    if (!existsSync(referenceDir) && !allowMissingReference) {
      throw new DeviceReferenceMissing(
        `no SDK device reference at ${referenceDir}.  It is extracted from the installed SDK's own device pages ` +
        "the first time wfb needs it, so install the SDK (`wfb init` says how), or run node ts/tools/extract-device-reference.ts --sdk DIR.",
      );
    }
    for (const path of candidates) {
      if (existsSync(path) && readdirSync(path).length > 0) return new NodeDeviceFiles(path, referenceDir);
    }
    if (allowEmpty && candidates.length > 0) return new NodeDeviceFiles(candidates[0]!, referenceDir);
    throw new DeviceError(
      "no Connect IQ device definitions found.  They cannot be downloaded " +
      "(api.gcs.garmin.com returns HTTP 401): `wfb init` says how to get them, " +
      "or set WFB_DEVICES to a directory containing them.",
    );
  }

  ids(): string[] {
    if (!existsSync(this.root)) return [];
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
    if (!existsSync(this.referenceDir)) return [];
    return readdirSync(this.referenceDir).filter((name) => name.endsWith(".json")).map((name) => name.slice(0, -5)).sort();
  }
}
