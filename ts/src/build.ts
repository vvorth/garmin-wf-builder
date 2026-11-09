// The front end of a build: a design's text through every load pass to its
// IR, the devices it builds for, and each one resolved and linted..
import { Bag, type Diagnostic } from "./diagnostics.ts";
import { compareVersions, type Device, type DeviceDatabase, DeviceError } from "./devices/device.ts";
import { FontFileError } from "./fonts/bake.ts";
import type { BakedFont } from "./fonts/bmfont.ts";
import { resolve, ResolveError, type ResolvedFace } from "./layout.ts";
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
 * the design does not list draws a note unless `noteUnlisted` is false.
 */
export function selectDevices(face: Face, db: DeviceDatabase, bag: Bag, only: readonly string[] | null = null, noteUnlisted = true): Device[] {
  const wanted = only !== null && only.length > 0 ? [...new Set(only)] : [...face.targets];
  bag.devices = wanted;
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
        notes: [`every generated manifest declares minApiLevel="${BASE_API_LEVEL}" (BASE_API_LEVEL); a device below `
          + "that floor cannot build at all, whether or not the design uses anything that floor actually needs"],
      });
      continue;
    }
    if (noteUnlisted && !face.targets.includes(deviceId)) {
      bag.note("target", `${deviceId} is not one of this design's targets; using it anyway because -d asked for it`, null, {
        notes: ["targets: " + face.targets.join(", ")],
      });
    }
    devices.push(device);
  }
  lint.checkOverrideSelectors(face, db.ids(), devices, bag);
  return devices;
}

/** Every installed device a generated face can run on: a watch face at or above the API floor. */
export function faceCapableDevices(db: DeviceDatabase): string[] {
  return db.ids().filter((id) => {
    try {
      const device = db.get(id);
      return device.supportsWatchface && compareVersions(device.apiLevel, BASE_API_LEVEL) >= 0;
    } catch (error) {
      if (error instanceof DeviceError) return false;
      throw error;
    }
  });
}

/** What a run of `dropUnsupported` ends with. */
export interface DropOutcome<T> {
  /** The last pass's result: `null` when it failed, or when no device was left to pass. */
  result: T | null;
  /** The last pass's diagnostics, then one `device-dropped` note per dropped device (and `devices` when none is left). */
  bag: Bag;
  /** The candidates the last pass ran on, in candidate order. */
  kept: string[];
  /** Each dropped device, in the order dropped, with the errors that dropped it. */
  dropped: Map<string, Diagnostic[]>;
}

/**
 * Run `pass` over `candidates`, dropping each device that cannot draw the
 * design. When a pass ends with errors and every one of them is attributed
 * to devices (`Diagnostic.devices`), those devices leave the set and the
 * pass runs again on the rest, in a fresh bag: the shared view, the guards
 * and the cross-device checks all depend on the set, so what the smaller
 * set reports is worked out anew rather than filtered from the larger one.
 * It stops at a pass with no error, or with one the design itself owns,
 * which then fails as it would have without dropping. `dropped` carries
 * the devices an earlier run dropped (the export's memory check), which
 * stay out and are reported with the rest.
 */
export function dropUnsupported<T>(candidates: readonly string[], pass: (ids: string[], bag: Bag) => T | null,
  dropped: Map<string, Diagnostic[]> = new Map(), what: "export" | "build" = "export"): DropOutcome<T> {
  let kept = candidates.filter((id) => !dropped.has(id));
  for (;;) {
    if (kept.length === 0) {
      const bag = new Bag();
      reportDropped(bag, dropped, what, true);
      return { result: null, bag, kept, dropped };
    }
    const bag = new Bag();
    const result = pass(kept, bag);
    const errors = bag.errors;
    const attributed = errors.length > 0 && errors.every((d) => d.devices !== null);
    const drop = attributed ? kept.filter((id) => errors.some((d) => d.devices!.includes(id))) : [];
    if (drop.length === 0) {
      reportDropped(bag, dropped, what);
      return { result, bag, kept, dropped };
    }
    for (const id of drop) dropped.set(id, errors.filter((d) => d.devices!.includes(id)));
    kept = kept.filter((id) => !drop.includes(id));
  }
}

/** The devices whose measured memory is at or over their watch-face limit. */
export function overMemoryLimit(memory: ReadonlyMap<string, lint.MemoryStats>): string[] {
  return [...memory].filter(([, stats]) => stats.total >= stats.limit).map(([id]) => id);
}

/** The codes of the errors that dropped a device, each once, in order. */
export function droppedCodes(errors: readonly Diagnostic[]): string[] {
  return [...new Set(errors.map((d) => d.code))];
}

/** The most dropping errors a `device-dropped` note quotes; the rest it counts. */
export const DROP_REASONS_SHOWN = 5;

/** One `device-dropped` note per dropped device, and a `devices` error when nothing is left at all. */
function reportDropped(bag: Bag, dropped: ReadonlyMap<string, readonly Diagnostic[]>, what: "export" | "build", nothingLeft = false): void {
  for (const [id, errors] of dropped) {
    const reasons = [...new Set(errors.map((d) => d.message.split("\n", 1)[0]!))];
    const more = reasons.length - DROP_REASONS_SHOWN;
    bag.note("device-dropped", `${id}: dropped from the ${what} (${droppedCodes(errors).join(", ")})`, null, {
      notes: more > 0
        ? [...reasons.slice(0, DROP_REASONS_SHOWN), `and ${more} more; \`wfb validate -d\` with this device lists every one`]
        : reasons,
    });
  }
  if (nothingLeft) {
    const message = dropped.size > 0 ? `nothing left to ${what}: every candidate device was dropped`
      : `nothing to ${what}: no installed device can run a watch face`;
    bag.error("devices", message, null, {
      notes: [...[...dropped].map(([id, errors]) => `${id}: ${droppedCodes(errors).join(", ")}`),
        "name devices with -d to see every diagnostic for them, or change the design so some of them can draw it"],
    });
  }
}

/** How a build gets a device's baked fonts: the bake itself, or (for parity) fonts baked elsewhere. */
export type Baker = (face: Face, device: Device) => Map<string, BakedFont>;

/** Resolve and lint the design once per target device, then the checks that need every target resolved. */
export function resolveAll(face: Face, devices: readonly Device[], bag: Bag, baker: Baker): [Map<string, ResolvedFace>, Map<string, Map<string, BakedFont>>] {
  lint.runDesign(face, bag);
  const resolved = new Map<string, ResolvedFace>();
  const baked = new Map<string, Map<string, BakedFont>>();
  const failed = new Set<string>();
  for (const device of devices) {
    let fonts: Map<string, BakedFont>;
    try {
      fonts = baker(face, device);
    } catch (error) {
      if (!(error instanceof FontFileError)) throw error;
      if (error.span === null) {
        bag.error("font", `${device.id}: ${error.message}`);
        continue;
      }
      // The design's own line, said once however many targets bake it.
      const key = JSON.stringify([error.message, error.span.toString()]);
      if (!failed.has(key)) bag.error("font", error.message, error.span, { notes: error.notes });
      failed.add(key);
      continue;
    }
    baked.set(device.id, fonts);
    let result: ResolvedFace;
    try {
      result = resolve(face, device, fonts);
    } catch (error) {
      if (!(error instanceof ResolveError)) throw error;
      // What the layout cannot resolve is an error on the author's line, said once however many targets hit it.
      const key = JSON.stringify([error.message, error.span?.toString() ?? null]);
      if (!failed.has(key)) bag.error("resolve", error.message, error.span);
      failed.add(key);
      continue;
    }
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

/** A built face's file name, `<stem>-<version>-<device>.prg`; a version with no letter or digit is left out. */
export function prgName(stem: string, version: string, device: string): string {
  const cleaned = Array.from(version, (c) => (/[\p{L}\p{N}.+_]/u.test(c) ? c : "-")).join("")
    .replace(/-+/g, "-").replace(/^[-.]+|[-.]+$/g, "");
  return /[\p{L}\p{N}]/u.test(cleaned) ? `${stem}-${cleaned}-${device}.prg` : `${stem}-${device}.prg`;
}
