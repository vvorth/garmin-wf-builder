// Driving the Connect IQ simulator. Node only.
//
// The simulator is a GUI application. On macOS it is the SDK's
// `ConnectIQ.app` bundle, started with `open`; on Linux it is the bare
// `simulator` binary, which needs a display. This module starts it when it
// is not already up, pushes a built `.prg` with `monkeydo`, and, where the
// simulator cannot run, says so precisely, pointing at `wfb preview`.
//
// The simulator is found by its TCP port, not by process name: `monkeydo`
// reaches it on the first of 127.0.0.1:1234-1238 that answers
// (`ShellUtils.findSimulatorPort` in `bin/monkeybrains.jar`), so a port that
// answers is exactly the condition a push needs, on every OS.
//
// `monkeydo` does not return once the app is loaded. It stays connected,
// printing the app's `System.println` output, until the app or the simulator
// exits, and prints nothing when the load succeeds. `push` therefore runs it
// in the background, logging to a file, and calls the push good once it has
// survived a short settle window with the simulator still up.
import { type ChildProcess, spawn, spawnSync } from "node:child_process";
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, readSync, rmSync } from "node:fs";
import { createConnection } from "node:net";
import { dirname, join } from "node:path";
import type { Toolchain } from "./node_build.ts";

/** The ports `monkeydo` tries, in order. */
export const SIMULATOR_PORTS = [1234, 1235, 1236, 1237, 1238];

const IS_MAC = process.platform === "darwin";

export class SimulatorError extends Error {
  readonly hints: string[];

  constructor(message: string, hints: string[] = []) {
    super(message);
    this.hints = hints;
  }
}

const sleep = (seconds: number): Promise<void> => new Promise((done) => setTimeout(done, seconds * 1000));

function answers(port: number): Promise<boolean> {
  return new Promise((done) => {
    const socket = createConnection({ host: "127.0.0.1", port, timeout: 200 });
    const finish = (ok: boolean): void => {
      socket.destroy();
      done(ok);
    };
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
  });
}

/** The port a running simulator answers on, or `null`. */
export async function simulatorPort(): Promise<number | null> {
  for (const port of SIMULATOR_PORTS) if (await answers(port)) return port;
  return null;
}

export async function isRunning(): Promise<boolean> {
  return (await simulatorPort()) !== null;
}

function which(tool: string): string | null {
  for (const dir of (process.env["PATH"] ?? "").split(":")) {
    if (dir && existsSync(join(dir, tool))) return join(dir, tool);
  }
  return null;
}

function macBundle(toolchain: Toolchain): string {
  return join(toolchain.sdk, "bin", "ConnectIQ.app");
}

/** Start the simulator if it is not already up, and wait until it accepts a push. */
export async function launch(toolchain: Toolchain, wait = 45.0): Promise<void> {
  if (await isRunning()) return;
  if (IS_MAC) launchMac(toolchain);
  else launchLinux(toolchain);
  const deadline = performance.now() + wait * 1000;
  while (performance.now() < deadline) {
    if (await isRunning()) return;
    await sleep(0.3);
  }
  if (IS_MAC) {
    throw new SimulatorError(`the simulator did not start within ${Math.round(wait)} s`, [
      "open it once by hand to see why -- the first launch after an SDK",
      "update can stop on a macOS security prompt:",
      `  open -a "${macBundle(toolchain)}"`,
    ]);
  }
  throw new SimulatorError("the simulator did not start", missingLibraryHints(toolchain));
}

function launchMac(toolchain: Toolchain): void {
  const bundle = macBundle(toolchain);
  if (!existsSync(bundle)) {
    throw new SimulatorError(`${bundle} not found`, [
      "CIQ_SDK should name the SDK Manager's own install:",
      "  ~/Library/Application Support/Garmin/ConnectIQ/Sdks/connectiq-sdk-mac-*",
      "./tools/setup-env.sh prints the export for it",
    ]);
  }
  const opened = spawnSync("open", ["-a", bundle], { encoding: "utf8" });
  if (opened.status !== 0) throw new SimulatorError(opened.stderr.trim() || "`open` could not start ConnectIQ.app");
}

function launchLinux(toolchain: Toolchain): void {
  const binary = join(toolchain.sdk, "bin", "simulator");
  if (!existsSync(binary)) throw new SimulatorError(`${binary} not found`);
  if (!process.env["DISPLAY"]) {
    throw new SimulatorError("no DISPLAY is set, and the Connect IQ simulator is a GUI application", [
      "run it on a desktop session, or under Xvfb:",
      "  Xvfb :99 -screen 0 1400x1000x24 &  DISPLAY=:99 wfb simulate ...",
    ]);
  }
  spawn(binary, [], { stdio: "ignore", detached: true }).unref();
}

/** A `monkeydo` left running against the simulator, and its log. */
export class Session {
  readonly process: ChildProcess;
  readonly log: string;
  exitCode: number | null = null;

  constructor(process: ChildProcess, log: string) {
    this.process = process;
    this.log = log;
    process.once("exit", (code) => {
      this.exitCode = code ?? -1;
    });
  }

  /** The app's console output as it arrives, until `monkeydo` exits. */
  async *follow(): AsyncGenerator<string> {
    const fd = openSync(this.log, "r");
    const buffer = Buffer.alloc(65536);
    try {
      for (;;) {
        const n = readSync(fd, buffer, 0, buffer.length, null);
        if (n > 0) yield buffer.toString("utf8", 0, n);
        else if (this.exitCode !== null) return;
        else await sleep(0.2);
      }
    } finally {
      closeSync(fd);
    }
  }

  /** Disconnect `monkeydo` and the `shell` it drives. */
  stop(): void {
    if (this.exitCode === null && this.process.pid !== undefined) {
      try {
        process.kill(-this.process.pid, "SIGTERM");
      } catch {
        // already gone
      }
    }
  }
}

/**
 * Send a built `.prg` to the simulator, starting it first if need be.
 * `monkeydo`'s output goes to `simulator.log` beside the `.prg`.
 */
export async function push(toolchain: Toolchain, prg: string, deviceId: string, settle = 6.0): Promise<Session> {
  await launch(toolchain);
  const log = join(dirname(prg), "simulator.log");
  const sink = openSync(log, "w");
  const child = spawn(join(toolchain.sdk, "bin", "monkeydo"), [prg, deviceId], { stdio: ["ignore", sink, sink], detached: true });
  closeSync(sink);
  const session = new Session(child, log);
  const deadline = performance.now() + settle * 1000;
  while (performance.now() < deadline) {
    if (!(await isRunning())) {
      session.stop();
      throw new SimulatorError("the simulator exited while loading the app", crashHints(toolchain));
    }
    if (session.exitCode !== null) {
      if (session.exitCode !== 0) {
        const output = readFileSync(log, "utf8").trim();
        const lines = output.split(/\r?\n/);
        throw new SimulatorError(output ? lines[lines.length - 1]! : `monkeydo failed (exit ${session.exitCode})`, monkeydoHints(output));
      }
      return session;
    }
    await sleep(0.25);
  }
  return session;
}

function monkeydoHints(output: string): string[] {
  if (output.includes("Java Runtime") || output.includes("java: command not found")) {
    return ["monkeydo needs a Java runtime on PATH (`wfb doctor` checks for one)"];
  }
  if (output.includes("not properly signed")) {
    return ["the simulator rejected the signature: build again with the same developer key (`--key`)"];
  }
  return [];
}

function crashHints(toolchain: Toolchain): string[] {
  if (IS_MAC) return ["the simulator's own crash report is in Console.app, under Crash Reports"];
  return [
    "this is an environment problem, not a problem with the built face:",
    "it reproduces with an unmodified SDK sample .prg on Linux",
    "(docs/limitations.md, \"The simulator crashes when an app is pushed\")",
    ...missingLibraryHints(toolchain),
  ];
}

/** Capture the simulator window: the file, and a note when only a fallback capture was possible. */
export async function screenshot(path: string): Promise<[string, string | null]> {
  mkdirSync(dirname(path), { recursive: true });
  if (IS_MAC) return screenshotMac(path);
  return [screenshotX11(path), null];
}

function run(command: string, args: string[]): void {
  const result = spawnSync(command, args, { stdio: "ignore" });
  if (result.status !== 0) throw new SimulatorError(`${command} failed (exit ${result.status})`);
}

async function screenshotMac(path: string): Promise<[string, string | null]> {
  const window = await macSimulatorWindow();
  if (window !== null) {
    run("screencapture", ["-x", "-o", `-l${window}`, path]);
    return [path, null];
  }
  run("screencapture", ["-x", path]);
  return [path, "the simulator window was not found, so this is the whole screen"];
}

// Picks the simulator's largest on-screen, normal-layer window by owning pid.
// kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements == 17;
// kCGNullWindowID is a C macro JXA cannot see, so it is spelled 0.
const WINDOW_JXA = `
ObjC.import('CoreGraphics');
function run(argv) {
  var pid = parseInt(argv[0], 10);
  var windows = ObjC.deepUnwrap(ObjC.castRefToObject(
      $.CGWindowListCopyWindowInfo(17, 0)));
  var best = '', area = 0;
  windows.forEach(function (w) {
    if (w.kCGWindowOwnerPID !== pid || w.kCGWindowLayer !== 0) return;
    var size = w.kCGWindowBounds.Width * w.kCGWindowBounds.Height;
    if (size > area) { area = size; best = String(w.kCGWindowNumber); }
  });
  return best;
}
`;

/** The CoreGraphics window number of the simulator, found through the pid listening on its port. */
async function macSimulatorWindow(): Promise<number | null> {
  const port = await simulatorPort();
  if (port === null || which("lsof") === null || which("osascript") === null) return null;
  const owner = spawnSync("lsof", ["-nP", `-iTCP:${port}`, "-sTCP:LISTEN", "-t"], { encoding: "utf8" });
  const pids = owner.stdout.split(/\s+/).filter(Boolean);
  if (pids.length === 0) return null;
  const found = spawnSync("osascript", ["-l", "JavaScript", "-e", WINDOW_JXA, pids[0]!], { encoding: "utf8" });
  const number = found.stdout.trim();
  return /^\d+$/.test(number) ? Number(number) : null;
}

function screenshotX11(path: string): string {
  const tool = which("import") ?? which("xwd");
  if (tool === null) throw new SimulatorError("no X capture tool found", ["install imagemagick (`import`) or x11-apps (`xwd`)"]);
  if (tool.endsWith("import")) {
    run(tool, ["-window", "root", path]);
  } else {
    const raw = path.replace(/\.[^./]*$/, "") + ".xwd";
    run(tool, ["-root", "-out", raw]);
    run("convert", [raw, path]);
    rmSync(raw, { force: true });
  }
  return path;
}

/** Shared libraries the simulator binary cannot resolve. */
function missingLibraryHints(toolchain: Toolchain): string[] {
  const binary = join(toolchain.sdk, "bin", "simulator");
  if (!existsSync(binary) || which("ldd") === null) return [];
  const result = spawnSync("ldd", [binary], { encoding: "utf8" });
  const missing = [...new Set(result.stdout.split("\n").filter((l) => l.includes("not found")).map((l) => l.split("=>")[0]!.trim()))].sort();
  return missing.length === 0 ? [] : [`unresolved shared libraries: ${missing.join(", ")}`];
}
