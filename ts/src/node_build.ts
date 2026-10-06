// The build, end to end, on a host with the Connect IQ SDK: the design
// loaded, resolved and linted, the project generated and written, and each
// device compiled by `monkeyc`, its memory measured. Port of the Node half
// of wfb/build.py and wfb/process.py. Node only.
//
//     YAML -> schema -> IR -> per-device resolve -> lint -> generate -> monkeyc
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { cpus, homedir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { load, resolveAll, selectDevices, slug } from "./build.ts";

export { slug };
import type { Device, DeviceDatabase } from "./devices/device.ts";
import { DEVICE_REFERENCE } from "./devices/node.ts";
import type { Bag } from "./diagnostics.ts";
import { type GeneratedProject, generate } from "./emit/project.ts";
import { bakeFonts, type FontReader } from "./emit/resources.ts";
import * as strhash from "./emit/strhash.ts";
import type { Face } from "./ir/model.ts";
import { checkMemory, type MemoryStats } from "./lint.ts";
import { cwdFileExists, readFontFile } from "./node.ts";

/** Written into the build directory beside the `.prg`s: what built them. */
export const BUILD_INFO = "build-info.json";

/** Where each device's `monkeyc` writes, under the build directory: its own directory. */
export const WORK_DIR = ".monkeyc";

/** The most `monkeyc`s `defaultJobs` runs at once: each is its own JVM. */
export const MAX_DEFAULT_JOBS = 4;

/** Seconds one device's `monkeyc` may take before it is stopped. */
export const MONKEYC_TIMEOUT = 600;

/** The SDK and the developer key a build compiles and signs with. */
export class Toolchain {
  readonly sdk: string;
  readonly key: string;

  constructor(sdk: string, key: string) {
    this.sdk = sdk;
    this.key = key;
  }

  static discover(sdk: string | null = null, key: string | null = null): Toolchain | null {
    const expand = (path: string): string => (path.startsWith("~") ? join(homedir(), path.slice(1)) : path);
    const sdkPath = expand(sdk ?? process.env["CIQ_SDK"] ?? "");
    const keyPath = expand(key ?? process.env["WFB_KEY"] ?? join(homedir(), "ciq", "developer_key.der"));
    if (!sdkPath || !existsSync(join(sdkPath, "bin", "monkeyc"))) return null;
    return new Toolchain(sdkPath, keyPath);
  }

  get monkeyc(): string {
    return join(this.sdk, "bin", "monkeyc");
  }

  get version(): string {
    const text = join(this.sdk, "bin", "version.txt");
    return existsSync(text) ? readFileSync(text, "utf8").trim() : this.sdk.slice(this.sdk.lastIndexOf("/") + 1);
  }
}

/** The SDK release the device reference was extracted from, or `null`. */
export function referenceSdkVersion(reference: string = DEVICE_REFERENCE): string | null {
  const path = join(dirname(reference), "sdk-version.txt");
  try {
    return readFileSync(path, "utf8").trim() || null;
  } catch {
    return null;
  }
}

/** The SDK release this build compiles with, warning when the device reference came from another. */
export function checkSdk(toolchain: Toolchain, bag: Bag, reference: string = DEVICE_REFERENCE): string {
  const version = toolchain.version;
  const extracted = referenceSdkVersion(reference);
  const notes = ["run ./tools/setup-env.sh, or python3 tools/extract-device-reference.py, to extract it again"];
  if (extracted === null) {
    bag.note("sdk", `the device reference does not record its SDK, so it cannot be checked against SDK ${version}`, null, { notes });
  } else if (extracted !== version) {
    bag.warning("sdk", `the device reference was extracted from SDK ${extracted}, and this build compiles with SDK ${version}`, null, {
      notes: [
        "font metrics and palette sizes come from the reference, so text placement may not match what this SDK's devices measure",
        "run ./tools/setup-env.sh, or python3 tools/extract-device-reference.py, to extract it from this SDK",
      ],
    });
  }
  return version;
}

const FUNCTION_RE = /<functionEntry [^>]*endPc="(\d+)" name="([^"]+)" parent="([^"]+)" startPc="(\d+)"/g;

function unescapeXml(text: string): string {
  return text.replace(/&(lt|gt|amp|quot|apos|#\d+|#x[0-9a-fA-F]+);/g, (_, e: string) => {
    if (e === "lt") return "<";
    if (e === "gt") return ">";
    if (e === "amp") return "&";
    if (e === "quot") return '"';
    if (e === "apos") return "'";
    return String.fromCodePoint(e.startsWith("#x") ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10));
  });
}

/** Every compiled method's code, in bytes, from a `.prg.debug.xml`, keyed `Class.method`. */
export function methodCodeSizes(debugXml: string): Map<string, number> {
  const out = new Map<string, number>();
  for (const [, end, rawName, parent, start] of readFileSync(debugXml, "latin1").matchAll(FUNCTION_RE)) {
    const name = unescapeXml(rawName!);
    const short = name.startsWith("<globals/") ? name.slice(0, -1).split(">").pop()! : name;
    out.set(`${parent}.${short}`, Number(end) - Number(start) + 1);
  }
  return out;
}

export interface BuildResult {
  face: Face;
  project: GeneratedProject;
  devices: Device[];
  output_dir: string;
  products: Map<string, string>;
  memory: Map<string, MemoryStats>;
  duration: number;
  sdk_version: string | null;
}

/** A path as Python's `pathlib` prints it: no `.` components, no doubled or trailing slashes. */
export function pathStr(path: string): string {
  if (path === "") return ".";
  const absolute = path.startsWith("/");
  const parts = path.split("/").filter((p) => p !== "" && p !== ".");
  const joined = parts.join("/");
  return absolute ? "/" + joined : joined || ".";
}

/** What Python's `OSError.strerror` says for a Node error code. */
const STRERROR: Record<string, string> = {
  ENOENT: "No such file or directory", EISDIR: "Is a directory", EACCES: "Permission denied", ENOTDIR: "Not a directory",
};

/** A design file read from disk and loaded, or `null` with the reason in `bag`. */
export function loadDesign(path: string, bag: Bag): Face | null {
  let text: string;
  try {
    text = readFileSync(path, "utf8");
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code ?? "";
    bag.error("io", `cannot read ${path}: ${STRERROR[code] ?? (error as Error).message}`);
    return null;
  }
  bag.registerSource(path, text);
  return load(path, bag, text, cwdFileExists);
}


/** How many `monkeyc`s to run at once: one per device, at most one per CPU and `MAX_DEFAULT_JOBS`. */
export function defaultJobs(devices: number): number {
  return Math.max(1, Math.min(devices, cpus().length || 1, MAX_DEFAULT_JOBS));
}

/** Write the project's files under `root`, cleared first. */
export function writeProject(project: GeneratedProject, root: string, clean = true): string[] {
  if (clean && existsSync(root)) rmSync(root, { recursive: true, force: true });
  mkdirSync(root, { recursive: true });
  const written: string[] = [];
  for (const [relative, content] of project.files()) {
    const path = join(root, relative);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, content);
    written.push(path);
  }
  return written;
}

/** Build `path` into `output`. `jobs` is how many `monkeyc`s run at once. */
export async function build(given: string, { output, bag, devicesOnly = null, db, toolchain = null, compilePrg = true, clean = true, profile = null, jobs = null, read = readFontFile }: {
  output: string; bag: Bag; devicesOnly?: string[] | null; db: DeviceDatabase; toolchain?: Toolchain | null; compilePrg?: boolean;
  clean?: boolean; profile?: number | null; jobs?: number | null; read?: FontReader;
}): Promise<BuildResult | null> {
  const started = performance.now();
  const path = pathStr(given);
  const face = loadDesign(path, bag);
  if (face === null) return null;
  const devices = selectDevices(face, db, bag, devicesOnly);
  if (devices.length === 0 || !bag.ok()) return null;
  const [resolved] = resolveAll(face, devices, bag, (f, device) => bakeFonts(f, device, read));
  if (!bag.ok()) return null;
  const buildDir = resolve(output, slug(face.name));
  const project = generate(face, devices, read, { resolved, profile });
  for (const d of project.divergences) {
    bag.error("shared-source", `internal error: the shared ${d.path} differs between ${d.first} and ${d.other}`, null, {
      notes: [
        `${d.first}: ${d.first_line.trim()}`,
        `${d.other}: ${d.other_line.trim()}`,
        "one view and one delegate serve every target, so a per-device fact belongs in Layout.mc; this is a compiler bug -- please report it",
        "building the targets separately with -d works around it",
      ],
    });
  }
  if (project.divergences.length > 0) return null;
  for (const collision of project.string_collisions) {
    const shown = [...collision.strings].map(([s, paths]) => `${strhash.describe(s)} (${paths.join(", ")})`).join(" and ");
    bag.error("string-label", `monkeyc cannot compile this design: ${shown} share the string label str___${collision.hash}`, null, {
      notes: [
        "monkeyc names each string constant by its Java hash code and crashes (\"A critical error has occurred\") when two different strings share one",
        "change one of the two strings, or pick a different icon for one of them",
      ],
    });
  }
  if (project.string_collisions.length > 0) return null;
  try {
    writeProject(project, buildDir, clean);
  } catch (error) {
    bag.error("io", `cannot write the build directory ${buildDir}: ${(error as Error).message}`, null, {
      notes: ["the directory may be left over from a build run as a different user; remove it and try again"],
    });
    return null;
  }
  const result: BuildResult = {
    face, project, devices, output_dir: buildDir, products: new Map(), memory: new Map(), duration: 0, sdk_version: null,
  };
  if (compilePrg) {
    const tools = toolchain ?? Toolchain.discover();
    if (tools === null) {
      bag.warning("toolchain", "no Connect IQ SDK found, so nothing was compiled", null, {
        notes: ["set CIQ_SDK, or run ./tools/setup-env.sh", `the generated project is complete and is in ${buildDir}`],
      });
    } else {
      result.sdk_version = checkSdk(tools, bag);
      await compileAll(result, tools, bag, jobs);
      writeBuildInfo(result);
    }
  }
  result.duration = (performance.now() - started) / 1000;
  return result;
}

function writeBuildInfo(result: BuildResult): void {
  const info = {
    sdk: result.sdk_version,
    device_reference_sdk: referenceSdkVersion(),
    devices: result.devices.map((d) => d.id),
    products: [...result.products.values()].map((p) => p.slice(p.lastIndexOf("/") + 1)).sort(),
  };
  writeFileSync(join(result.output_dir, BUILD_INFO), JSON.stringify(info, null, 2) + "\n");
}

/** One device's `monkeyc` run: its exit status (`null` when stopped), its output less the JVM's noise, and its `.prg`. */
interface Compiled {
  returncode: number | null;
  text: string;
  output: string;
}

/** Compile every device, `jobs` at a time, and report each run in device order. */
async function compileAll(result: BuildResult, toolchain: Toolchain, bag: Bag, jobs: number | null): Promise<void> {
  const work = join(result.output_dir, WORK_DIR);
  const workers = Math.max(1, jobs ?? defaultJobs(result.devices.length));
  try {
    const runs: Compiled[] = new Array(result.devices.length);
    let next = 0;
    await Promise.all(Array.from({ length: Math.min(workers, result.devices.length) }, async () => {
      while (next < result.devices.length) {
        const index = next++;
        runs[index] = await runMonkeyc(result, result.devices[index]!, toolchain, work);
      }
    }));
    result.devices.forEach((device, index) => report(result, device, runs[index]!, bag));
  } finally {
    rmSync(work, { recursive: true, force: true });
  }
}

/** `command`'s output and exit code; on a timeout, the command and everything it started are killed. */
export function runProcess(command: string[], cwd: string, timeoutSeconds: number): Promise<{ code: number | null; stdout: string; stderr: string; timedOut: boolean }> {
  return new Promise((done) => {
    const child = spawn(command[0]!, command.slice(1), { cwd, detached: true, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "", stderr = "", timedOut = false;
    child.stdout.setEncoding("utf8").on("data", (chunk: string) => { stdout += chunk; });
    child.stderr.setEncoding("utf8").on("data", (chunk: string) => { stderr += chunk; });
    const timer = setTimeout(() => {
      timedOut = true;
      try {
        process.kill(-child.pid!, "SIGKILL");
      } catch {
        // the group has already gone
      }
    }, timeoutSeconds * 1000);
    child.on("close", (code) => {
      clearTimeout(timer);
      done({ code, stdout, stderr, timedOut });
    });
  });
}

async function runMonkeyc(result: BuildResult, device: Device, toolchain: Toolchain, work: string): Promise<Compiled> {
  const name = `${slug(result.face.name)}-${device.id}.prg`;
  const staged = join(work, device.id, name);
  mkdirSync(dirname(staged), { recursive: true });
  // Typecheck and optimization levels live in the generated jungle, so a hand-run monkeyc reproduces this build.
  const command = [toolchain.monkeyc, "-f", "monkey.jungle", "-d", device.id, "-o", staged, "-y", toolchain.key, "-w", "--no-gen-styles", "--build-stats", "0"];
  const output = join(result.output_dir, name);
  const run = await runProcess(command, result.output_dir, MONKEYC_TIMEOUT);
  if (run.timedOut) return { returncode: null, text: `monkeyc took longer than ${MONKEYC_TIMEOUT} s and was stopped`, output };
  for (const suffix of ["", ".debug.xml"]) {
    const built = join(dirname(staged), name + suffix);
    if (existsSync(built)) renameSync(built, join(result.output_dir, name + suffix));
  }
  return { returncode: run.code, text: stripNoise(run.stdout + run.stderr), output };
}

function report(result: BuildResult, device: Device, run: Compiled, bag: Bag): void {
  const lines = run.text.split(/\r\n|\r|\n/);
  for (const line of lines) {
    const stripped = line.trim();
    if (stripped.startsWith("ERROR:")) bag.error("monkeyc", stripped.slice("ERROR:".length).trim());
    else if (stripped.startsWith("WARNING:")) bag.warning("monkeyc", stripped.slice("WARNING:".length).trim());
  }
  if (run.returncode === null) {
    bag.error("monkeyc", `${device.id}: ${run.text}`);
    return;
  }
  if (run.returncode !== 0 || !existsSync(run.output)) {
    const rest = lines.filter((line) => line.trim() && !line.trim().startsWith("ERROR:") && !line.trim().startsWith("WARNING:"));
    bag.error("monkeyc", `${device.id}: build failed`, null, { notes: rest.slice(-6) });
    return;
  }
  result.products.set(device.id, run.output);
  const stats = checkMemory(device, run.text, bag);
  if (stats !== null) {
    result.memory.set(device.id, stats);
  } else {
    bag.warning("memory", `${device.id}: could not parse monkeyc's --build-stats output, so this build was not checked against the watch-face memory limit`, null, {
      notes: ["the .prg itself compiled fine; this is a gap in this diagnostic, not evidence the design is too big"],
    });
  }
}

const NOISE = /^.*JAVA_TOOL_OPTIONS.*$\n?/gm;
/** The JVM's own deprecated-reflective-access notice, printed when a `<watchface-config>` resource compiles. */
const JVM_NOISE = /^.*(?:sun\.misc\.Unsafe|protobuf\.UnsafeUtil).*$\n?/gm;

function stripNoise(text: string): string {
  return text.replace(NOISE, "").replace(JVM_NOISE, "");
}
