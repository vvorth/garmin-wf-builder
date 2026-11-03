// `wfb doctor` as data: everything a build needs, whether it is there, and
// what to do about anything missing, for the command line to print and the
// editor's server to send. Node only.
import { existsSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { DeviceError } from "./devices/device.ts";
import { DeviceReferenceMissing, ensureDeviceReference, NodeDeviceFiles } from "./devices/node.ts";
import { referencePages, referenceVersion } from "./devices/reference.ts";
import { resolveRegistryKey } from "./fonts/files.ts";
import { deviceNeededNames, garminFontRoot, NodeFontFiles } from "./fonts/node.ts";
import { checkForNewerSdk, updateNotice } from "./init.ts";
import { ICON_FONT, SCHEMA } from "./node.ts";
import { Toolchain } from "./node_build.ts";
import { nodeRefusal } from "./node_version.ts";
import { writableDir } from "./sdk.ts";
import type { DoctorReport } from "./studio/protocol.ts";
import { VERSION } from "./version.ts";

export type { DoctorReport };


export interface DoctorOptions {
  devicesDir?: string | null;
  fontsDir?: string | null;
}

/** `doc/docs/Device_Reference`, as it sits under `root`, for a message. */
const relativePages = (root: string): string => referencePages(root).slice(root.length + 1);

/** Every file under `root`, relative, sorted. */
function filesUnder(root: string): string[] {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (entry.isFile()) out.push(relative(root, path));
    }
  };
  try {
    walk(root);
  } catch {
    // unreadable: what was read
  }
  return out.sort();
}

/** The registry's stand-ins for what `deviceIds` need, as `wfb doctor` reports them. */
function systemFonts(deviceIds: string[], devicesRoot: string, fonts: NodeFontFiles, referenceDir: string): DoctorReport["systemFonts"] {
  // "unmapped" is a deliberate registry decision (a CJK/RTL-only face), never missing.
  const tierOf = new Map<string, string>();
  const lacking: string[] = [];
  for (const deviceId of deviceIds) {
    let deviceMissing = false;
    for (const [name, face] of deviceNeededNames(deviceId, devicesRoot, referenceDir)) {
      if (!tierOf.has(name)) {
        if (fonts.root !== null && fonts.garminAnyPath(name) !== undefined) tierOf.set(name, "garmin");
        else {
          const key = resolveRegistryKey(name, face);
          tierOf.set(name, key === null ? "unmapped" : fonts.tierFor(key) ?? "missing");
        }
      }
      if (tierOf.get(name) === "missing") deviceMissing = true;
    }
    if (deviceMissing) lacking.push(deviceId);
  }
  const counts = new Map<string, number>();
  for (const tier of tierOf.values()) counts.set(tier, (counts.get(tier) ?? 0) + 1);
  const summary = ["garmin", "installed", "cached", "missing", "unmapped"].filter((l) => counts.get(l)).map((l) => `${counts.get(l)} ${l}`).join(", ");
  return {
    lacking, summary,
    hints: lacking.length === 0 ? [] : [`(${summary} font names) -- run node ts/tools/fetch-system-fonts.ts;`, "not blocking, falls back to a substitute face at build time"],
  };
}

/** Everything a build needs, checked; `problems` and `verdict` sum it up. */
export async function doctorReport({ devicesDir = null, fontsDir = null }: DoctorOptions = {}): Promise<DoctorReport> {
  const inContainer = process.env["WFB_CONTAINER"] === "1";
  const problems: string[] = [];
  let blocking = 0;
  const fail = (fix: string, blocks = true): void => {
    problems.push(fix);
    if (blocks) blocking++;
  };

  const nodeProblem = nodeRefusal(process.versions.node);
  if (nodeProblem !== null) fail("install a patched Node");

  // The SDK first: the device reference is extracted from its doc pages when missing or stale.
  const toolchain = Toolchain.discover();
  const sdk = toolchain === null ? null : { root: toolchain.install, version: toolchain.version };
  const referenceDir = ensureDeviceReference(sdk);
  const haveReference = existsSync(referenceDir) && statSync(referenceDir).isDirectory();
  const reference: DoctorReport["reference"] = {
    // A reference named outright (WFB_DEVICE_REFERENCE) is shown as named; an extracted one by its folder.
    dir: process.env["WFB_DEVICE_REFERENCE"] ? referenceDir : dirname(referenceDir),
    ok: haveReference, sdkVersion: haveReference ? referenceVersion(dirname(referenceDir)) : null, hints: [],
  };
  if (!haveReference) {
    reference.hints = sdk === null
      ? ["it is extracted from the SDK's own device pages once an SDK is installed (`wfb init`)"]
      : [`SDK ${sdk.version} at ${sdk.root} has no ${relativePages(sdk.root)}, so run`, "node ts/tools/extract-device-reference.ts --sdk DIR on a full SDK"];
    fail("extract the SDK device reference");
  }

  const haveIcons = existsSync(ICON_FONT);
  if (!haveIcons) fail("install the icon font");

  // Garmin's own font files: optional, and never downloaded here.
  const fontsRoot = garminFontRoot(fontsDir);
  const garminFonts: DoctorReport["garminFonts"] = { root: fontsRoot, files: fontsRoot === null ? [] : filesUnder(fontsRoot), hints: [] };
  if (fontsRoot === null) {
    garminFonts.hints = inContainer
      ? ["mount the SDK Manager's folder at /vendor, or its Fonts directory:", `  -v <SDK Manager's Fonts dir>:${process.env["WFB_FONTS"] || "/vendor/Fonts"}:ro`, "-- see docs/container.md"]
      : ["copy the SDK Manager's Fonts directory into vendor/fonts/,", "or set WFB_FONTS / pass --fonts DIR -- see docs/container.md"];
  }

  const devices: DoctorReport["devices"] = { root: null, ids: [], error: null, hints: [] };
  let fonts: DoctorReport["systemFonts"] = null;
  try {
    const files = NodeDeviceFiles.discover(devicesDir ?? undefined, referenceDir);
    devices.root = files.root;
    devices.ids = files.ids();
    fonts = systemFonts(devices.ids, files.root, new NodeFontFiles(fontsDir), referenceDir);
  } catch (e) {
    if (e instanceof DeviceReferenceMissing) {
      devices.error = "not checked: the device reference is missing";
    } else if (e instanceof DeviceError) {
      devices.error = e.message;
      devices.hints = inContainer
        ? ["they cannot be downloaded -- api.gcs.garmin.com returns HTTP 401 -- so mount the", `SDK Manager's folder at /vendor, or its Devices folder at ${process.env["WFB_DEVICES"] || "/vendor/Devices"} (\`wfb init\` prints the mount)`]
        : ["they cannot be downloaded -- api.gcs.garmin.com returns HTTP 401; Garmin's SDK Manager", "downloads them for a signed-in account: `wfb init` says how, step by step,", "or set WFB_DEVICES to a folder of them copied from another machine."];
      fail("install the device definitions");
    } else throw e;
  }

  let sdkHints: string[] = [];
  let newerSdk: DoctorReport["newerSdk"] = null;
  let referenceStale: DoctorReport["referenceStale"] = null;
  let key: DoctorReport["key"] = null;
  let canCompile = false;
  if (toolchain === null) {
    sdkHints = inContainer
      ? [`mount the SDK Manager's folder at /vendor, or its Sdks folder at ${process.env["CIQ_SDK"] || "/vendor/Sdks"} (\`wfb init\` prints the mount)`]
      : ["Garmin's SDK Manager installs it: `wfb init` says how, or set CIQ_SDK to an SDK you have"];
    fail("install the Connect IQ SDK", false);
  } else {
    const newer = await checkForNewerSdk(toolchain.version);
    if (newer !== null) newerSdk = { version: newer.version, how: updateNotice(toolchain.version, newer, inContainer).split("; ")[1]! };
    const extracted = referenceSdkVersionOf(referenceDir);
    if (haveReference && extracted !== null && extracted !== toolchain.version) {
      referenceStale = { extracted, hints: [`SDK ${toolchain.version} has no ${relativePages(toolchain.install)}, so run`, "node ts/tools/extract-device-reference.ts --sdk DIR on a full SDK"] };
      fail("extract the device reference from this SDK", false);
    }
    canCompile = true;
    const keyDir = dirname(toolchain.key);
    if (existsSync(toolchain.key)) key = { path: toolchain.key, state: "present", hints: [] };
    else if (writableDir(keyDir)) key = { path: toolchain.key, state: "will-generate", hints: [] };
    else {
      canCompile = false;
      key = {
        path: toolchain.key, state: "missing",
        hints: [
          `and ${keyDir} is not writable.  Create one with:`,
          "  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 \\",
          "    -out key.pem",
          "  openssl pkcs8 -topk8 -inform PEM -outform DER \\",
          `    -in key.pem -out ${toolchain.key} -nocrypt`,
        ],
      };
      fail("generate a developer key", false);
    }
  }

  return {
    wfb: VERSION,
    node: { version: process.versions.node, path: process.execPath, problem: nodeProblem },
    schema: { path: SCHEMA, ok: existsSync(SCHEMA) },
    reference, iconFont: { path: ICON_FONT, ok: haveIcons }, garminFonts, devices, systemFonts: fonts,
    sdk: toolchain === null ? null : { version: toolchain.version, install: toolchain.install, compiler: toolchain.sdk, copied: toolchain.copied },
    sdkHints, newerSdk, referenceStale, key,
    verdict: blocking > 0 ? "not ready" : canCompile ? "ready" : "partial",
    problems, inContainer,
  };
}

/** The SDK release the reference at `referenceDir` (its `devices/` folder) was extracted from. */
function referenceSdkVersionOf(referenceDir: string): string | null {
  return referenceVersion(dirname(referenceDir));
}

