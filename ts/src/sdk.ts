// The Connect IQ SDK on disk, for the commands that compile: where one is
// installed, which of its files the compiler needs, how `monkeyc` is run,
// and a writable copy of the compiler when the install itself is read-only.
// Node only: the browser bundle never imports this module.
import { accessSync, constants, copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join } from "node:path";

export interface Sdk {
  /** The SDK's root: `bin/monkeybrains.jar` is under it. */
  root: string;
  /** Its release, `9.3.0`: `bin/version.txt`, else the folder's name. */
  version: string;
}

/** `~` at the start of a path, as a shell would expand it. */
export const expandHome = (path: string): string => (path.startsWith("~") ? join(homedir(), path.slice(1)) : path);

/** The SDK Manager's own folder on each OS: `Sdks/`, `Devices/` and `Fonts/` sit under it. */
export function sdkManagerHomes(): string[] {
  const homes = [join(homedir(), ".Garmin", "ConnectIQ"), join(homedir(), "Library", "Application Support", "Garmin", "ConnectIQ")];
  const appdata = process.env["APPDATA"];
  if (appdata) homes.push(join(appdata, "Garmin", "ConnectIQ"));
  return homes;
}

/** The SDK Manager's folder that exists on this machine, or `null`. */
export function sdkManagerHome(): string | null {
  return sdkManagerHomes().find((home) => existsSync(home)) ?? null;
}

/** Whether `dir` is an SDK root: the compiler is under its `bin/`. */
export const isSdkRoot = (dir: string): boolean => existsSync(join(dir, "bin", "monkeybrains.jar"));

/** The release an SDK root is: its `bin/version.txt`, else the version in its folder's name, else the name. */
export function sdkVersion(root: string): string {
  const file = join(root, "bin", "version.txt");
  if (existsSync(file)) {
    const version = readFileSync(file, "utf8").trim();
    if (version) return version;
  }
  // The SDK Manager unpacks to connectiq-sdk-<os>-<version>-<date>-<hash>.
  const named = /^connectiq-sdk-\w+-(\d+(?:\.\d+)*)/.exec(basename(root));
  return named ? named[1]! : basename(root);
}

const byNewestVersion = (a: Sdk, b: Sdk): number => b.version.localeCompare(a.version, "en", { numeric: true }) || a.root.localeCompare(b.root);

/** The SDKs at `dir`: `dir` itself when it is an SDK root, else every child that is, newest release first. */
export function sdksIn(dir: string): Sdk[] {
  if (!existsSync(dir)) return [];
  if (isSdkRoot(dir)) return [{ root: dir, version: sdkVersion(dir) }];
  let children: string[];
  try {
    children = readdirSync(dir);
  } catch {
    return [];
  }
  return children.map((name) => join(dir, name)).filter(isSdkRoot).map((root) => ({ root, version: sdkVersion(root) })).sort(byNewestVersion);
}

/**
 * The SDK the SDK Manager marks current, when `current-sdk.cfg` under its
 * folder names one of `installed` (by its path, or by its folder's name).
 */
function currentSdk(home: string, installed: Sdk[]): Sdk | null {
  const cfg = join(home, "current-sdk.cfg");
  if (!existsSync(cfg)) return null;
  const named = readFileSync(cfg, "utf8").trim().replace(/[\\/]+$/, "");
  if (named === "") return null;
  const leaf = named.split(/[\\/]/).pop();
  return installed.find((sdk) => sdk.root === named || basename(sdk.root) === leaf) ?? null;
}

/** Where `wfb init --download-sdk` puts an SDK when it cannot write where one is looked for: the cache's own `sdks/`. */
export const downloadedSdks = (): string => join(cacheHome(), "sdks");

/** Where an SDK is looked for, in order; each may be an SDK root or a folder of them. */
export function sdkCandidates(override: string | null = null): string[] {
  const dirs = [override, process.env["CIQ_SDK"]].filter((dir): dir is string => Boolean(dir)).map(expandHome);
  for (const home of sdkManagerHomes()) dirs.push(join(home, "Sdks"));
  dirs.push(join(homedir(), "ciq", "sdks"), downloadedSdks());
  return dirs;
}

/**
 * The SDK to compile with: the first of `override`, `CIQ_SDK`, the SDK
 * Manager's `Sdks/` folder (its current SDK, else the newest), `~/ciq/sdks`
 * (where `tools/setup-env.sh` installs one) and the cache's `sdks/` (where
 * `wfb init --download-sdk` puts one it could put nowhere better) that
 * holds one.
 */
export function findSdk(override: string | null = null): Sdk | null {
  for (const dir of sdkCandidates(override)) {
    const found = sdksIn(dir);
    if (found.length === 0) continue;
    if (basename(dir) === "Sdks") {
      const current = currentSdk(dirname(dir), found);
      if (current !== null) return current;
    }
    return found[0]!;
  }
  return null;
}

// The GUI and analysis programs beside the compiler in `bin/`: the simulator,
// its shell, ERA, MonkeyMotion, the language server, the FIT graph tool, the
// barrel and documentation tools, and their images and native libraries.
const PRUNE_BIN = new Set([
  "simulator", "connectiq", "connectiq.bat",
  "monkeymotion", "monkeygraph", "monkeygraph.bat",
  "era", "era.bat", "era.jar",
  "LanguageServer.jar", "fit-graph.jar",
  "shell", "mdd", "mdd.bat", "extdata",
  "barrelbuild", "barrelbuild.bat", "barreltest", "barreltest.bat",
  "monkeydoc", "monkeydoc.bat", "monkeym", "monkeym.bat",
]);
const PRUNE_SUFFIXES = [".exe", ".dll", ".png", ".bat", ".py", ".sar", ".json"];

/**
 * Whether the compiler needs `path` (relative to the SDK root, `/`
 * separated): the files of `bin/` but the programs above, and nothing from
 * `doc/`, `samples/`, `resources/` or `share/`. What is left -- the compiler
 * jar, its API database, the resource schema and the launcher scripts -- is
 * about 26 MB and builds every target.
 */
export function compilerNeeds(path: string): boolean {
  const [top, entry, ...rest] = path.split("/");
  if (top !== "bin" || entry === undefined || entry === "" || rest.length > 0) return false;
  if (PRUNE_BIN.has(entry)) return false;
  return !PRUNE_SUFFIXES.some((suffix) => entry.endsWith(suffix));
}

/** The device reference pages, the one part of `doc/` that is data (`ts/src/devices/reference.ts` reads it). */
export const DEVICE_REFERENCE_PAGES = "doc/docs/Device_Reference";

/**
 * What a pruned SDK keeps (`ts/tools/fetch-sdk.ts`): the compiler's files,
 * the device reference pages, and the SDK's own licence texts and
 * third-party notices.
 */
export const prunedSdkKeeps = (path: string): boolean =>
  compilerNeeds(path) || path.startsWith(`${DEVICE_REFERENCE_PAGES}/`) || path.startsWith("resources/readme/licenses/");

/** `wfb`'s cache: `$XDG_CACHE_HOME/wfb`, else `~/.cache/wfb`. */
export function cacheHome(): string {
  return join(process.env["XDG_CACHE_HOME"] || join(homedir(), ".cache"), "wfb");
}

/** Whether the running user may write into `dir` (which exists). */
export function writableDir(dir: string): boolean {
  try {
    accessSync(dir, constants.W_OK);
    return true;
  } catch {
    return false;
  }
}

/** Whether `path` could be created or replaced: its nearest existing ancestor (or itself) is writable. */
export function canWriteAt(path: string): boolean {
  let probe = path;
  while (!existsSync(probe)) {
    const parent = dirname(probe);
    if (parent === probe) return false;
    probe = parent;
  }
  return writableDir(probe);
}

/** The `java` to run the compiler with: `$JAVA_HOME/bin/java`, else the one on `PATH`. */
export function javaBinary(): string {
  const home = process.env["JAVA_HOME"];
  return home ? join(home, "bin", "java") : "java";
}

/**
 * `monkeyc`, as the SDK's own `bin/monkeyc` launcher runs it: the JVM on
 * `monkeybrains.jar`. Running the JVM directly means the launcher's shell
 * (bash; the Windows SDK's copy has CRLF line ends) is not needed, and a
 * timeout or interrupt reaches the JVM itself rather than a script around it.
 */
export function monkeycCommand(root: string): string[] {
  return [javaBinary(), "-Xms1g", "-Dfile.encoding=UTF-8", "-Dapple.awt.UIElement=true", "-classpath", join(root, "bin", "monkeybrains.jar"), "com.garmin.monkeybrains.Monkeybrains"];
}

export interface CompilerRoot extends Sdk {
  /** Whether `root` is a copy of the installed SDK's compiler files rather than the install itself. */
  copied: boolean;
}

/** Whether the copy at `copy` is of `sdk`: the same release and the same compiler jar. */
function sameCompiler(sdk: Sdk, copy: string): boolean {
  if (!isSdkRoot(copy) || sdkVersion(copy) !== sdk.version) return false;
  const jar = (root: string): number => statSync(join(root, "bin", "monkeybrains.jar")).size;
  return jar(copy) === jar(sdk.root);
}

/**
 * The root to compile from. `monkeyc` rewrites `bin/default.jungle` on every
 * run, so the SDK's `bin/` has to be writable; when it is not (a read-only
 * mount, a shared install), the compiler's files are copied once per release
 * under `into` (`<cache>/sdk/<version>`) and compiled from there. The copy is
 * reused while it matches the install.
 */
export function compilerRoot(sdk: Sdk, into: string = join(cacheHome(), "sdk"), writable: (dir: string) => boolean = writableDir): CompilerRoot {
  if (writable(join(sdk.root, "bin"))) return { ...sdk, copied: false };
  const copy = join(into, sdk.version);
  if (!sameCompiler(sdk, copy)) {
    const staging = `${copy}.tmp`;
    rmSync(staging, { recursive: true, force: true });
    mkdirSync(join(staging, "bin"), { recursive: true });
    for (const name of readdirSync(join(sdk.root, "bin"))) {
      if (!compilerNeeds(`bin/${name}`)) continue;
      const source = join(sdk.root, "bin", name);
      if (!statSync(source).isFile()) continue;
      copyFileSync(source, join(staging, "bin", name));
    }
    rmSync(copy, { recursive: true, force: true });
    renameSync(staging, copy);
  }
  return { root: copy, version: sdk.version, copied: true };
}
