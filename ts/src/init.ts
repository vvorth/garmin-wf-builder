// `wfb init`: what Garmin's SDK Manager has to put on this machine before
// `wfb` can compile -- the Connect IQ SDK and the device definitions, with
// Garmin's font files beside them -- whether it is there, and how to get it
// there. Garmin's server hands out the SDK Manager freely but the device
// files only to a signed-in account, and the SDK's licence is personal, so
// this command can only point: it never installs any of them. Node only.
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { platform } from "node:os";
import { basename, join } from "node:path";
import { DEFAULT_DEVICE_ROOTS } from "./devices/node.ts";
import { garminFontRoot } from "./fonts/node.ts";
import { findSdk, type Sdk, sdkCandidates, sdkManagerHome, sdkManagerHomes } from "./sdk.ts";

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
    if (!inContainer && host !== "unknown" && host !== "mac") lines.push("   `wfb init --download DIR --accept-license` fetches it into DIR for you.");
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

/**
 * Fetch the SDK Manager's archive for `host` into `dir` and return its
 * path. The caller has shown the agreement notice and had it accepted.
 */
export async function downloadSdkManager(host: Exclude<Host, "unknown">, dir: string): Promise<string> {
  const url = SDK_MANAGER_DOWNLOADS[host];
  const response = await fetch(url, { signal: AbortSignal.timeout(600_000) });
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  mkdirSync(dir, { recursive: true });
  const path = join(dir, basename(new URL(url).pathname));
  writeFileSync(path, bytes);
  return path;
}
