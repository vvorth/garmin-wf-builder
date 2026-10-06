// The front end of a build: a design's text through every load pass to its
// IR, the devices it builds for, and each one resolved and linted. Port of
// wfb/build.py's `load`, `select_devices` and `resolve_all`.
import type { Bag } from "./diagnostics.ts";
import { compareVersions, type Device, type DeviceDatabase, DeviceError } from "./devices/device.ts";
import { FontFileError } from "./fonts/bake.ts";
import type { BakedFont } from "./fonts/bmfont.ts";
import { resolve, type ResolvedFace } from "./layout.ts";
import * as lint from "./lint.ts";
import { desugar } from "./desugar.ts";
import type { YamlNode } from "./edit/yaml.ts";
import { build as buildIr, type FileExists } from "./ir/builder/index.ts";
import type { Face } from "./ir/model.ts";
import { lower } from "./lower.ts";
import { validate } from "./validate.ts";
import { load as loadYaml } from "./yamlsrc.ts";

/**
 * Parse and validate a design into its IR, or report why not: YAML, the
 * schema on the author's own document, lowering, desugaring, then the IR.
 * `node` is the text already composed; `fileExists` answers for a baked
 * font's `source:`, relative to the design's own path.
 */
export function load(path: string, bag: Bag, text: string, fileExists: FileExists, node?: YamlNode | null): Face | null {
  const doc = loadYaml(path, bag, text, node);
  if (doc === null) return null;
  if (!validate(doc, bag)) return null;
  if (!lower(doc, bag)) return null;
  if (!desugar(doc, bag)) return null;
  return buildIr(doc, bag, fileExists);
}

/** The API floor every generated manifest declares. */
export const BASE_API_LEVEL = "3.1.0";

/**
 * The devices to resolve and build for: `only` (`-d`) when given, the
 * design's `targets:` otherwise. `only` may name any installed device; one
 * the design does not list draws a note.
 */
export function selectDevices(face: Face, db: DeviceDatabase, bag: Bag, only: readonly string[] | null = null): Device[] {
  const wanted = only !== null && only.length > 0 ? [...new Set(only)] : [...face.targets];
  const devices: Device[] = [];
  for (const deviceId of wanted) {
    let device: Device;
    try {
      device = db.get(deviceId);
    } catch (error) {
      if (!(error instanceof DeviceError)) throw error;
      bag.error("target", error.message);
      continue;
    }
    if (!device.supportsWatchface) {
      bag.error("target", `${deviceId} cannot run a watch face at all`);
      continue;
    }
    if (compareVersions(device.apiLevel, BASE_API_LEVEL) < 0) {
      bag.error("target", `${deviceId} is below the ${BASE_API_LEVEL} floor this compiler requires (its own ConnectIQ ceiling is ${device.apiLevel})`, null, {
        notes: [`every generated manifest declares minApiLevel="${BASE_API_LEVEL}" (wfb/emit/manifest.py's BASE_API_LEVEL); a device below `
          + "that floor cannot build at all, whether or not the design uses anything that floor actually needs"],
      });
      continue;
    }
    if (!face.targets.includes(deviceId)) {
      bag.note("target", `${deviceId} is not one of this design's targets; using it anyway because -d asked for it`, null, {
        notes: ["targets: " + face.targets.join(", ")],
      });
    }
    devices.push(device);
  }
  lint.checkOverrideSelectors(face, db.ids(), devices, bag);
  return devices;
}

/** How a build gets a device's baked fonts: the bake itself, or (for parity) fonts baked elsewhere. */
export type Baker = (face: Face, device: Device) => Map<string, BakedFont>;

/** Resolve and lint the design once per target device, then the checks that need every target resolved. */
export function resolveAll(face: Face, devices: readonly Device[], bag: Bag, baker: Baker): [Map<string, ResolvedFace>, Map<string, Map<string, BakedFont>>] {
  lint.runDesign(face, bag);
  const resolved = new Map<string, ResolvedFace>();
  const baked = new Map<string, Map<string, BakedFont>>();
  for (const device of devices) {
    let fonts: Map<string, BakedFont>;
    try {
      fonts = baker(face, device);
    } catch (error) {
      if (!(error instanceof FontFileError)) throw error;
      bag.error("font", `${device.id}: ${error.message}`);
      continue;
    }
    baked.set(device.id, fonts);
    const result = resolve(face, device, fonts);
    resolved.set(device.id, result);
    lint.run(result, bag);
  }
  lint.checkVectorFontAvailability(face, resolved, bag);
  lint.checkSubscreenAvailability(face, resolved, bag);
  lint.checkSharedViewTargets(resolved, bag);
  return [resolved, baked];
}

/** A design name as a file name: lower case, every other character a single dash. */
export function slug(name: string): string {
  const cleaned = Array.from(name, (c) => (/[\p{L}\p{N}]/u.test(c) ? c.toLowerCase() : "-")).join("");
  return cleaned.replace(/-+/g, "-").replace(/^-+|-+$/g, "") || "face";
}
