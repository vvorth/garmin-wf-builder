// Driving the Connect IQ simulator. Node only.
//
// The simulator is a GUI application. On macOS it is the SDK's
// `ConnectIQ.app` bundle, started with `open`; on Linux it is the bare
// `simulator` binary, which needs a display; on Windows it is
// `simulator.exe`. This module starts it when it is not already up, pushes a
// built `.prg` with `monkeydo`, and, where the simulator cannot run, says so
// precisely, pointing at `wfb preview`.
//
// On Windows `monkeydo` is run as the JVM it launches (`monkeydoCommand`):
// the SDK's `bin/monkeydo` there is a bash script with CRLF line ends, and
// Node will not spawn its `monkeydo.bat` without a shell, whose quoting the
// batch file's own `%1` handling then breaks.
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
import { javaBinary } from "./sdk.ts";

/** The ports `monkeydo` tries, in order. */
export const SIMULATOR_PORTS = [1234, 1235, 1236, 1237, 1238];

const IS_MAC = process.platform === "darwin";
const IS_WINDOWS = process.platform === "win32";

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
  return join(toolchain.install, "bin", "ConnectIQ.app");
}

/** Start the simulator if it is not already up, and wait until it accepts a push. */
export async function launch(toolchain: Toolchain, wait = 45.0): Promise<void> {
  if (await isRunning()) return;
  if (IS_MAC) launchMac(toolchain);
  else if (IS_WINDOWS) launchWindows(toolchain);
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
  if (IS_WINDOWS) {
    throw new SimulatorError(`the simulator did not start within ${Math.round(wait)} s`, [
      "start it once by hand to see why:",
      `  "${windowsSimulator(toolchain)}"`,
    ]);
  }
  throw new SimulatorError("the simulator did not start", missingLibraryHints(toolchain));
}

function windowsSimulator(toolchain: Toolchain): string {
  return join(toolchain.install, "bin", "simulator.exe");
}

function launchWindows(toolchain: Toolchain): void {
  const binary = windowsSimulator(toolchain);
  if (!existsSync(binary)) {
    throw new SimulatorError(`${binary} not found`, [
      "the simulator comes with a full SDK from Garmin's SDK Manager,",
      "not with a pruned one",
    ]);
  }
  spawn(binary, [], { stdio: "ignore", detached: true }).unref();
}

/** `monkeydo`'s command line: the SDK's launcher, or on Windows the JVM it runs. */
function monkeydoCommand(toolchain: Toolchain, prg: string, deviceId: string): string[] {
  const bin = join(toolchain.install, "bin");
  if (!IS_WINDOWS) return [join(bin, "monkeydo"), prg, deviceId];
  return [
    javaBinary(), "-classpath", join(bin, "monkeybrains.jar"), "com.garmin.monkeybrains.monkeydodeux.MonkeyDoDeux",
    "-f", prg, "-d", deviceId, "-s", join(bin, "shell.exe"),
  ];
}

function launchMac(toolchain: Toolchain): void {
  const bundle = macBundle(toolchain);
  if (!existsSync(bundle)) {
    throw new SimulatorError(`${bundle} not found`, [
      "the simulator is the SDK Manager's own install's:",
      "  ~/Library/Application Support/Garmin/ConnectIQ/Sdks/connectiq-sdk-mac-*",
      "which wfb finds by itself when CIQ_SDK and --sdk name nothing else",
    ]);
  }
  const opened = spawnSync("open", ["-a", bundle], { encoding: "utf8" });
  if (opened.status !== 0) throw new SimulatorError(opened.stderr.trim() || "`open` could not start ConnectIQ.app");
}

function launchLinux(toolchain: Toolchain): void {
  const binary = join(toolchain.install, "bin", "simulator");
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
      if (IS_WINDOWS) {
        // No process groups: taskkill's /T ends the JVM and the shell.exe it started.
        spawnSync("taskkill", ["/PID", String(this.process.pid), "/T", "/F"], { stdio: "ignore" });
        return;
      }
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
  const [command, ...args] = monkeydoCommand(toolchain, prg, deviceId);
  // Detached on POSIX so `stop` can signal its process group; on Windows
  // that would give the JVM a console window of its own.
  const child = spawn(command!, args, { stdio: ["ignore", sink, sink], detached: !IS_WINDOWS, windowsHide: true });
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
  if (IS_WINDOWS) return ["Windows' own record of the crash is in Event Viewer, under Windows Logs > Application"];
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
  if (IS_WINDOWS) return [screenshotWindows(path), null];
  return [screenshotX11(path), null];
}

// Draws the simulator's main window into a bitmap with PrintWindow
// (PW_RENDERFULLCONTENT, 2), so the capture is the window even when another
// one covers it. DPI-aware, or GetWindowRect reports scaled bounds and the
// capture is cropped. The path arrives in WFB_SHOT, never in the script text.
const WINDOW_PS = `
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class WfbWin {
  public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
}
'@
[WfbWin]::SetProcessDPIAware() | Out-Null
$p = Get-Process simulator -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if ($null -eq $p) { exit 3 }
$r = New-Object WfbWin+RECT
[WfbWin]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object System.Drawing.Bitmap ($r.Right - $r.Left), ($r.Bottom - $r.Top)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
[WfbWin]::PrintWindow($p.MainWindowHandle, $hdc, 2) | Out-Null
$g.ReleaseHdc($hdc)
$bmp.Save($env:WFB_SHOT, [System.Drawing.Imaging.ImageFormat]::Png)
`;

function screenshotWindows(path: string): string {
  const result = spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", WINDOW_PS], {
    env: { ...process.env, WFB_SHOT: path }, stdio: "ignore", windowsHide: true,
  });
  if (result.status === 3) throw new SimulatorError("the simulator window was not found");
  if (result.status !== 0) throw new SimulatorError(`powershell failed (exit ${result.status})`);
  return path;
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
  const binary = join(toolchain.install, "bin", "simulator");
  if (!existsSync(binary) || which("ldd") === null) return [];
  const result = spawnSync("ldd", [binary], { encoding: "utf8" });
  const missing = [...new Set(result.stdout.split("\n").filter((l) => l.includes("not found")).map((l) => l.split("=>")[0]!.trim()))].sort();
  return missing.length === 0 ? [] : [`unresolved shared libraries: ${missing.join(", ")}`];
}
