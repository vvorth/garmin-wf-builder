// `wfb init`: what Garmin's SDK Manager has to put on this machine before
// `wfb` can compile -- the Connect IQ SDK and the device definitions, with
// Garmin's font files beside them -- whether it is there, and how to get it
// there. Garmin's server hands out the SDK Manager and the SDK itself
// freely but the device files only to a signed-in account, so this command
// points, and downloads at most the two free ones onto the user's own
// machine (the Linux SDK into the SDK Manager's folder, where `wfb` and the
// SDK Manager both look), once the user has accepted Garmin's agreement.
// Node only.
import { chmodSync, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { homedir, platform } from "node:os";
import { basename, dirname, join } from "node:path";
import { unzipSync } from "fflate";
import { DEFAULT_DEVICE_ROOTS } from "./devices/node.ts";
import { garminFontRoot } from "./fonts/node.ts";
import { cacheHome, canWriteAt, downloadedSdks, expandHome, findSdk, isSdkRoot, type Sdk, sdkCandidates, sdkManagerHome, sdkManagerHomes, sdkVersion } from "./sdk.ts";

/** Every SDK Manager folder this machine could have, for a report of where things were looked for. */
export const MANAGER_HOMES = sdkManagerHomes;

/** The operating system the SDK Manager runs on; `unknown` inside the container, whose host is not its own OS. */
export type Host = "mac" | "linux" | "windows" | "unknown";

export const SDK_PAGE = "https://developer.garmin.com/connect-iq/sdk/";
const MANAGER = "https://developer.garmin.com/downloads/connect-iq/sdk-manager";

/** The SDK Manager's download per OS, as Garmin's SDK page links it. */
export const SDK_MANAGER_DOWNLOADS: Record<Exclude<Host, "unknown">, string> = {
  mac: `${MANAGER}/connectiq-sdk-manager.dmg`,
  linux: `${MANAGER}/connectiq-sdk-manager-linux.zip`,
  windows: `${MANAGER}/connectiq-sdk-manager-windows.zip`,
};

/** Where the SDK Manager keeps what it downloads, per OS, as a user would write it. */
export const SDK_MANAGER_FOLDERS: Record<Exclude<Host, "unknown">, string> = {
  mac: "~/Library/Application Support/Garmin/ConnectIQ",
  linux: "~/.Garmin/ConnectIQ",
  windows: "%APPDATA%\\Garmin\\ConnectIQ",
};

export const HOST_NAMES: Record<Exclude<Host, "unknown">, string> = { mac: "macOS", linux: "Linux", windows: "Windows" };

export function detectHost(inContainer: boolean, os: string = platform()): Host {
  if (inContainer) return "unknown";
  return os === "darwin" ? "mac" : os === "win32" ? "windows" : os === "linux" ? "linux" : "unknown";
}

export interface Survey {
  /** The SDK Manager's folder, when one exists. */
  managerHome: string | null;
  sdk: Sdk | null;
  /** Where an SDK was looked for. */
  sdkLookedIn: string[];
  /** The device definitions' folder and how many devices it holds. */
  devices: { root: string; count: number } | null;
  devicesLookedIn: string[];
  fonts: string | null;
}

/** What is on this machine: the SDK Manager's folder, an SDK, device definitions and Garmin's fonts. */
export function survey(devicesDir: string | null = null, fontsDir: string | null = null): Survey {
  const devicesLookedIn = [devicesDir, process.env["WFB_DEVICES"], ...DEFAULT_DEVICE_ROOTS].filter((p): p is string => Boolean(p));
  let devices: Survey["devices"] = null;
  for (const root of devicesLookedIn) {
    if (!existsSync(root)) continue;
    const count = readdirSync(root).filter((id) => existsSync(join(root, id, "compiler.json"))).length;
    if (count > 0) {
      devices = { root, count };
      break;
    }
  }
  return {
    managerHome: sdkManagerHome(),
    sdk: findSdk(),
    sdkLookedIn: sdkCandidates(),
    devices,
    devicesLookedIn,
    fonts: garminFontRoot(fontsDir),
  };
}

/** Whether `survey` has what compiling needs: an SDK and device definitions. */
export const complete = (found: Survey): boolean => found.sdk !== null && found.devices !== null;

/** The container's mounts for the SDK Manager's folder `home` (a path, or a shell's `$HOME`-relative spelling). */
function mounts(home: string): string[] {
  return [
    `-v "${home}/Sdks:/sdk:ro"`,
    `-v "${home}/Devices:/devices:ro"`,
    `-v "${home}/Fonts:/fonts:ro"`,
  ];
}

/**
 * The `docker run` for this machine: the SDK Manager's folders mounted,
 * the key and cache volumes kept, the project directory at `/work`. With a
 * `home` found on this machine its real path; otherwise each OS's spelling.
 */
export function dockerLines(host: Host, managerHome: string | null, image = "vvorth/garmin-wf-builder"): string[] {
  const home = managerHome ?? (host === "unknown" ? SDK_MANAGER_FOLDERS.mac : SDK_MANAGER_FOLDERS[host]).replace(/^~/, "$HOME");
  const lines = [
    `docker run --rm -v "$PWD:/work" \\`,
    ...mounts(home).map((mount) => `  ${mount} \\`),
    "  -v wfb-keys:/keys -v wfb-cache:/cache \\",
    `  ${image} build my-face.yaml`,
  ];
  if (managerHome === null) {
    lines.push(
      "",
      `(${host === "unknown" ? "macOS" : HOST_NAMES[host]} paths shown${host === "unknown" ? "" : ", for the SDK Manager's default folder"}.`
      + ` On Linux the folders are under ~/.Garmin/ConnectIQ; on Windows under %APPDATA%\\Garmin\\ConnectIQ, with \`\${PWD}\` for \`$PWD\` in PowerShell.)`,
    );
  }
  return lines;
}

/**
 * The steps left, numbered, for what `found` lacks. `inContainer`: the
 * steps happen on the computer running Docker, which then mounts the
 * folders; `host` is that computer's OS when known.
 */
export function steps(found: Survey, host: Host, inContainer: boolean): string[] {
  const lines: string[] = [];
  let n = 0;
  const step = (first: string, ...rest: string[]): void => {
    n++;
    lines.push(`${n}. ${first}`, ...rest.map((line) => (line === "" ? "" : `   ${line}`)));
  };
  const where = inContainer ? "On the computer running Docker, d" : "D";
  if (found.managerHome === null || found.sdk === null || found.devices === null) {
    if (host === "unknown") {
      step(`${where}ownload Garmin's Connect IQ SDK Manager:`,
        ...(["mac", "linux", "windows"] as const).map((os) => `  ${HOST_NAMES[os].padEnd(8)} ${SDK_MANAGER_DOWNLOADS[os]}`));
    } else {
      step(`${where}ownload Garmin's Connect IQ SDK Manager for ${HOST_NAMES[host]}:`, `  ${SDK_MANAGER_DOWNLOADS[host]}`);
    }
    lines.push(
      `   Downloading it accepts Garmin's Connect IQ Developer Agreement (${SDK_PAGE}), which`,
      "   licenses the SDK to you alone, for developing and testing: that is why neither the SDK nor",
      "   the device files are part of this project or its image.",
    );
    if (host === "linux") {
      lines.push("   `wfb init --download-manager --accept-license` fetches it here; `wfb init --download-sdk --accept-license`",
        "   fetches the SDK itself into the SDK Manager's folder, leaving the SDK Manager only the watches.");
    } else if (host === "windows") {
      lines.push("   `wfb init --download-manager --accept-license` fetches it here.");
    }
    if (inContainer && found.sdk === null) {
      lines.push("   The container can fetch the SDK itself: mount an empty folder read-write at /sdk and run",
        "   `docker run --rm -v \"$HOME/.Garmin/ConnectIQ/Sdks:/sdk\" vvorth/garmin-wf-builder init --download-sdk --accept-license`,",
        "   then mount that folder read-only as below. The watches still come from the SDK Manager.");
    }
  }
  if (found.sdk === null || found.devices === null) {
    const wants = found.sdk === null && found.devices === null ? "the newest SDK on its SDK tab and, on its Devices tab, every watch you build for"
      : found.sdk === null ? "the newest SDK on its SDK tab" : "every watch you build for, on its Devices tab";
    const folders = host === "unknown"
      ? (["mac", "linux", "windows"] as const).map((os) => `  ${HOST_NAMES[os].padEnd(8)} ${SDK_MANAGER_FOLDERS[os]}`)
      : [`  ${found.managerHome ?? SDK_MANAGER_FOLDERS[host]}`];
    step("Open it, sign in with a Garmin account (a free one will do), and download", wants + ". They land under", ...folders,
      "with the SDK in Sdks/, the watches in Devices/ and Garmin's font files in Fonts/.");
  }
  if (inContainer) {
    step("Mount those folders when you run the image:", ...dockerLines(host, null).map((line) => (line === "" ? "" : `  ${line}`)));
    lines.push("   Then `docker run ... vvorth/garmin-wf-builder doctor` checks everything is in place.");
  } else {
    step("Run `wfb doctor`: it checks everything is in place and names what is not.");
  }
  return lines;
}

/** `url`'s bytes, `log` told the size first. */
async function fetchBytes(url: string, log: (line: string) => void): Promise<Uint8Array> {
  const response = await fetch(url, { signal: AbortSignal.timeout(900_000) });
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
  const length = Number(response.headers.get("content-length"));
  log(`downloading ${url}${length > 0 ? ` (${Math.round(length / (1024 * 1024))} MB)` : ""} ...`);
  return new Uint8Array(await response.arrayBuffer());
}

/**
 * Fetch the SDK Manager's archive for `host` into `dir` and return its
 * path. The caller has shown the agreement notice and had it accepted.
 */
export async function downloadSdkManager(host: Exclude<Host, "unknown">, dir: string, log: (line: string) => void = () => {}): Promise<string> {
  const url = SDK_MANAGER_DOWNLOADS[host];
  const bytes = await fetchBytes(url, log);
  mkdirSync(dir, { recursive: true });
  const path = join(dir, basename(new URL(url).pathname));
  writeFileSync(path, bytes);
  return path;
}

/** Garmin's SDK downloads; `SDK_BASE_URL` names a mirror that reproduces the same paths. */
export const SDK_DOWNLOADS = "https://developer.garmin.com/downloads/connect-iq/sdks";

/** One entry of Garmin's `sdks.json`: a release and its archive per OS. */
export interface SdkRelease { version: string; release?: string; linux?: string; mac?: string; windows?: string }

/** The newest release with a Linux archive, or the one `version` names; `null` when the list has none. */
export function pickLinuxSdk(releases: SdkRelease[], version?: string): (SdkRelease & { linux: string }) | null {
  const linux = releases.filter((r): r is SdkRelease & { linux: string } => Boolean(r.linux) && (!version || r.version === version));
  linux.sort((a, b) => a.version.localeCompare(b.version, "en", { numeric: true }));
  return linux.at(-1) ?? null;
}

/** Garmin's list of SDK releases. */
export async function listSdks(baseUrl: string = process.env["SDK_BASE_URL"] || SDK_DOWNLOADS): Promise<SdkRelease[]> {
  const response = await fetch(`${baseUrl}/sdks.json`, { signal: AbortSignal.timeout(60_000) });
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${baseUrl}/sdks.json`);
  return (await response.json()) as SdkRelease[];
}

/**
 * Where `--download-sdk` puts the SDK: in the container the folder mounted
 * at `CIQ_SDK` when it can be written, else the cache's `sdks/` (kept by a
 * `/cache` volume, and where `findSdk` looks); on a Linux host the SDK
 * Manager's own `Sdks` folder, so the SDK Manager and `wfb` both see it.
 */
export function sdkDownloadFolder(inContainer: boolean, writable: (path: string) => boolean = canWriteAt): string {
  if (inContainer) return process.env["CIQ_SDK"] && writable(process.env["CIQ_SDK"]) ? process.env["CIQ_SDK"] : downloadedSdks();
  return join(homedir(), ".Garmin", "ConnectIQ", "Sdks");
}

/** A release newer than `current`: the newest Linux release in `releases` when it is, else `null`. */
export function newerThan(current: string, releases: SdkRelease[]): (SdkRelease & { linux: string }) | null {
  const newest = pickLinuxSdk(releases);
  return newest !== null && newest.version.localeCompare(current, "en", { numeric: true }) > 0 ? newest : null;
}

/** How long a fetched `sdks.json` answers the update check before it is fetched again. */
export const UPDATE_CHECK_MAX_AGE_MS = 24 * 60 * 60 * 1000;

/**
 * Whether a newer SDK than `current` is out, by Garmin's `sdks.json`:
 * fetched at most once a day (the copy kept at `<cache>/sdks.json`), with a
 * short timeout, and `null` -- no notice -- when it cannot be fetched, so
 * an offline machine is never slowed or nagged. `WFB_NO_UPDATE_CHECK=1`
 * turns the check off altogether.
 */
export async function checkForNewerSdk(current: string, {
  cacheFile = join(cacheHome(), "sdks.json"), maxAgeMs = UPDATE_CHECK_MAX_AGE_MS, timeoutMs = 3000, now = Date.now(),
  fetchList = async (): Promise<SdkRelease[]> => {
    const baseUrl = process.env["SDK_BASE_URL"] || SDK_DOWNLOADS;
    const response = await fetch(`${baseUrl}/sdks.json`, { signal: AbortSignal.timeout(timeoutMs) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return (await response.json()) as SdkRelease[];
  },
}: { cacheFile?: string; maxAgeMs?: number; timeoutMs?: number; now?: number; fetchList?: () => Promise<SdkRelease[]> } = {}): Promise<(SdkRelease & { linux: string }) | null> {
  if (process.env["WFB_NO_UPDATE_CHECK"] === "1") return null;
  let releases: SdkRelease[] | null = null;
  try {
    if (existsSync(cacheFile) && now - statSync(cacheFile).mtimeMs < maxAgeMs) releases = JSON.parse(readFileSync(cacheFile, "utf8")) as SdkRelease[];
  } catch {
    releases = null;
  }
  if (releases === null) {
    try {
      releases = await fetchList();
      mkdirSync(dirname(cacheFile), { recursive: true });
      writeFileSync(cacheFile, JSON.stringify(releases));
    } catch {
      return null;
    }
  }
  return newerThan(current, releases);
}

/** The one-line notice for a newer SDK, for stderr. */
export function updateNotice(current: string, newer: SdkRelease, inContainer: boolean): string {
  const how = inContainer
    ? "download it with the SDK Manager, or run the image with -e WFB_ACCEPT_LICENSE=1 and no SDK mounted to fetch it"
    : "download it with the SDK Manager, or `wfb init --download-sdk --accept-license` on Linux";
  return `wfb: Connect IQ SDK ${newer.version} is available (installed: ${current}); ${how}`;
}

/**
 * Unpack an SDK archive as the SDK Manager lays one out: `folder/<name>/`
 * with the archive's own tree inside and the `bin/` programs executable.
 * Built beside the target and renamed into place, so an interrupted run
 * leaves nothing half-made.
 */
export function unpackSdk(archive: Uint8Array, folder: string, name: string): Sdk {
  const root = join(folder, name);
  const staging = `${root}.tmp`;
  rmSync(staging, { recursive: true, force: true });
  const files = unzipSync(archive, { filter: (file) => !file.name.endsWith("/") });
  for (const [path, content] of Object.entries(files)) {
    const target = join(staging, path);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, content);
    if (path.startsWith("bin/") && !path.slice(4).includes("/") && !/\.[a-z0-9]+$/i.test(path)) chmodSync(target, 0o755);
  }
  if (!isSdkRoot(staging)) {
    rmSync(staging, { recursive: true, force: true });
    throw new Error("the archive holds no bin/monkeybrains.jar: not a Connect IQ SDK");
  }
  rmSync(root, { recursive: true, force: true });
  renameSync(staging, root);
  return { root, version: sdkVersion(root) };
}

/**
 * Download the newest Linux SDK (or `version`) into `folder` and return
 * it; one already there is left alone. The caller has shown the agreement
 * notice and had it accepted. The whole SDK, as `tools/setup-env.sh`
 * installs it: the compiler, the docs the device reference is extracted
 * from, the simulator for a desktop that can run it.
 */
export async function downloadSdk(folder: string, { version, log = () => {} }: { version?: string | undefined; log?: (line: string) => void } = {}): Promise<Sdk> {
  const release = pickLinuxSdk(await listSdks(), version);
  if (release === null) throw new Error(version ? `Garmin lists no Linux SDK ${version}` : "Garmin lists no Linux SDK");
  const name = release.linux.replace(/\.zip$/, "");
  const target = join(expandHome(folder), name);
  if (isSdkRoot(target)) {
    log(`SDK ${release.version} is already at ${target}`);
    return { root: target, version: sdkVersion(target) };
  }
  const baseUrl = process.env["SDK_BASE_URL"] || SDK_DOWNLOADS;
  const archive = await fetchBytes(`${baseUrl}/${release.linux}`, log);
  log(`unpacking into ${target} ...`);
  mkdirSync(expandHome(folder), { recursive: true });
  return unpackSdk(archive, expandHome(folder), name);
}
