// wfb -- build a Garmin Connect IQ watch face from a YAML design. Node only.
//
//     wfb validate design.yaml     # schema + semantic checks, no toolchain
//     wfb preview  design.yaml     # render to a PNG, with no simulator
//     wfb build    design.yaml     # generate Monkey C and compile it
import { accessSync, constants, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { parseArgs } from "node:util";
import { resolveAll, selectDevices } from "./build.ts";
import * as catalog from "./catalog.ts";
import { COMMANDS, MAIN } from "./cli_help.ts";
import * as complications from "./complications.ts";
import { type Device, DeviceDatabase, DeviceError, type FontMetric } from "./devices/device.ts";
import { DEVICE_REFERENCE, DeviceReferenceMissing, NodeDeviceFiles } from "./devices/node.ts";
import { Bag, type Diagnostic } from "./diagnostics.ts";
import { codeReport, planFor } from "./emit/monkeyc/profile.ts";
import { bakeFonts } from "./emit/resources.ts";
import { resolveRegistryKey } from "./fonts/files.ts";
import { deviceNeededNames, garminFontRoot, NodeFontFiles } from "./fonts/node.ts";
import * as icons from "./icons.ts";
import type { ResolvedFace } from "./layout.ts";
import type { MemoryStats } from "./lint.ts";
import { ICON_FONT, installAssets, readFontFile, SCHEMA } from "./node.ts";
import {
  BUILD_INFO, build as runBuild, type BuildResult, loadDesign, MAX_DEFAULT_JOBS, methodCodeSizes, pathStr,
  referenceSdkVersion, slug, Toolchain,
} from "./node_build.ts";
import { formatFixed, quoted } from "./py.ts";
import * as series from "./series.ts";
import * as starters from "./starters.ts";
import * as term from "./term.ts";
import { fill, wrap } from "./textwrap.ts";
import { VERSION } from "./version.ts";

const DEFAULT_OUTPUT = "build";
const DEFAULT_PROFILE_REPS = 10;

// -- output --

const out = (text = ""): void => {
  process.stdout.write(text + "\n");
};
const err = (text = ""): void => {
  process.stderr.write(text + "\n");
};

/** `error: <message>` on stderr, the label bold red when stderr is coloured. */
function error(message: string): void {
  err(`${term.style("error:", ["bold", "red"], term.shouldColor(process.stderr))} ${message}`);
}

/** A status word -- `generated`, `built`, `preview`, `pushed`, `screenshot` -- bold green when `color`. */
function status(label: string, color: boolean): string {
  return term.style(label, ["bold", "green"], color);
}

/** The `N.N%` memory share, green, yellow or red by how close it is to the limit. */
function memoryShare(share: number, color: boolean): string {
  return term.style(`${formatFixed(share, 1)}%`, [share >= 90 ? "red" : share >= 75 ? "yellow" : "green"], color);
}

/** Every diagnostic in `bag` on stderr. */
function printBag(bag: Bag, verbose: boolean): void {
  if (bag.items.length === 0) return;
  err(bag.render({ color: term.shouldColor(process.stderr), width: term.width(process.stderr), verbose }));
}

/** A command's closing `<before><word> -- <counts><after>` line. */
function verdict(bag: Bag, stream: NodeJS.WriteStream, word: string, styles: string[], before = "", after = ""): void {
  const color = term.shouldColor(stream);
  stream.write(`${before}${term.style(word, styles, color)} -- ${bag.summary({ color })}${after}\n`);
}

/** Thousands separated by commas, as Python's `:,`. */
function grouped(n: number): string {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

const basename = (path: string): string => path.slice(path.lastIndexOf("/") + 1);

/** `build`'s `built` lines, one per compiled device, the byte figures aligned. */
export function formatBuilt(products: ReadonlyMap<string, string>, memory: ReadonlyMap<string, MemoryStats>, color: boolean): string[] {
  const nameWidth = Math.max(0, ...[...products.values()].map((p) => basename(p).length));
  const lines: string[] = [];
  for (const [deviceId, path] of products) {
    const stats = memory.get(deviceId);
    const label = status("built", color);
    if (stats) {
      const share = 100.0 * stats.total / stats.limit;
      lines.push(`${label}      ${basename(path).padEnd(nameWidth)}  ${grouped(stats.total)} B / ${grouped(stats.limit)} B (${memoryShare(share, color)})`);
    } else {
      lines.push(`${label}      ${basename(path)}`);
    }
  }
  return lines;
}

function discoverDb(devicesDir: string | null, fontsDir: string | null = null): DeviceDatabase {
  return new DeviceDatabase(NodeDeviceFiles.discover(devicesDir ?? undefined), new NodeFontFiles(fontsDir));
}

const baker = (face: Parameters<typeof bakeFonts>[0], device: Device) => bakeFonts(face, device, readFontFile);

// -- the parser --

/** The values `-o` takes to write the image to stdout. */
const STDOUT_OUTPUT = ["-", "--"];

const isStdout = (output: unknown): boolean => typeof output === "string" && STDOUT_OUTPUT.includes(output);

/** Parsed arguments: each option's or positional's `dest` to its value. */
type Namespace = Record<string, unknown>;
type Handler = (args: Namespace) => Promise<number> | number;

/** A bad argument; `main` prints the command's usage line and this, and exits 2. */
class UsageError extends Error {}

/** A value converter: the parsed value, or a thrown message. */
type Convert = (text: string) => unknown;

const INT: Convert = (text) => {
  if (!/^\s*[+-]?\d+\s*$/.test(text)) throw new Error(`invalid int value: ${quoted(text)}`);
  return Number(text);
};
const FLOAT: Convert = (text) => {
  const value = Number(text);
  if (!text.trim() || Number.isNaN(value)) throw new Error(`invalid float value: ${quoted(text)}`);
  return value;
};
const POSITIVE_INT: Convert = (text) => {
  if (!/^\d+$/.test(text) || Number(text) < 1) throw new Error(`'${text}' is not a whole number of at least 1`);
  return Number(text);
};

interface Option {
  /** `-x`, `--long`, or both, short first. */
  flags: readonly string[];
  /** Default: the long flag, dashes to underscores. */
  dest?: string;
  /** `flag` is true when given; `append` collects every value; `value` (the default) keeps the last. */
  kind?: "flag" | "append" | "value";
  type?: Convert;
  choices?: readonly string[];
  default?: unknown;
  /** What a `value` option given bare takes (`--profile` alone). */
  bare?: unknown;
  metavar?: string;
  help?: string;
}

interface Positional { dest: string; optional?: boolean; many?: boolean; metavar?: string; help?: string }

interface Command { name: string; handler: Handler; summary: string; description: string; options: Option[]; positionals: Positional[] }

const longFlag = (o: Option): string => o.flags.find((f) => f.startsWith("--"))!;
const destOf = (o: Option): string => o.dest ?? longFlag(o).slice(2).replaceAll("-", "_");
const metavarOf = (o: Option): string => o.metavar ?? (o.choices ? `{${o.choices.join(",")}}` : destOf(o).toUpperCase());

const COLOR: Option = { flags: ["--color"], choices: term.MODES, default: null, help: "colour the output: auto (default), always or never" };
const HELP: Option = { flags: ["-h", "--help"], kind: "flag", help: "show this help message and exit" };
const VERBOSE: Option = { flags: ["-v", "--verbose"], kind: "flag", help: "show every note in full, with its source line and details" };
const DEVICES_DIR: Option = { flags: ["--devices-dir"], help: "device definitions directory" };
const DESIGN: Positional = { dest: "design", help: "the .yaml design file" };
const deviceOption = (verb: string): Option => ({
  flags: ["-d", "--device"], kind: "append", dest: "devices",
  help: `${verb} only this device (repeatable); any installed device, not just a listed target; defaults to all targets`,
});

function command(name: string, handler: Handler, options: Option[] = [], positionals: Positional[] = []): Command {
  const description = COMMANDS[name]!;
  return { name, handler, summary: description.split("\n")[0]!, description, options: [HELP, COLOR, ...options], positionals };
}

const COMMAND_LIST: readonly Command[] = [
  command("build", buildCommand, [
    VERBOSE, deviceOption("build"),
    { flags: ["-o", "--output"], default: DEFAULT_OUTPUT, help: `build directory (default: ${DEFAULT_OUTPUT})` },
    { flags: ["--no-compile"], kind: "flag", help: "generate the project but do not run monkeyc" },
    {
      flags: ["--profile"], type: INT, bare: DEFAULT_PROFILE_REPS, metavar: "REPS",
      help: `time every element's draw on the watch and show the average per call over it (default: ${DEFAULT_PROFILE_REPS} repetitions per sample) -- a build for measuring, not for wearing`,
    },
    { flags: ["-j", "--jobs"], type: POSITIVE_INT, metavar: "N", help: `compile up to N devices at once (default: one per device, at most one per CPU and at most ${MAX_DEFAULT_JOBS})` },
    { flags: ["--sdk"], help: "Connect IQ SDK root (default: $CIQ_SDK)" },
    { flags: ["--key"], help: "developer key .der (default: ~/ciq/developer_key.der)" },
    DEVICES_DIR,
  ], [DESIGN]),
  command("validate", validateCommand, [VERBOSE, deviceOption("check"), DEVICES_DIR], [DESIGN]),
  command("preview", previewCommand, [
    VERBOSE, deviceOption("render"),
    { flags: ["-o", "--output"], default: "build/preview", help: "directory to write the PNGs to (default: build/preview); `-o -` (or `-o --`) writes ONE PNG to stdout instead, for piping -- e.g. `wfb preview face.yaml -o -- | chafa`" },
    { flags: ["-q", "--quiet"], kind: "flag", help: "print nothing to stdout; errors and warnings still go to stderr (implied by `-o -`)" },
    { flags: ["--scale"], type: INT, default: 2, help: "enlarge the native-resolution frame this many times, each watch pixel a SCALE x SCALE block (default: 2)" },
    { flags: ["--no-quantise"], kind: "flag", help: "skip snapping colours to the device palette" },
    { flags: ["--style"], help: "render one 'config: style:' entry by name (default: the default entry)" },
    { flags: ["--all-styles"], kind: "flag", help: "render every 'config: style:' entry side by side, one PNG per device" },
    { flags: ["--time"], metavar: "HH:MM[:SS]", help: "render analog hands (and any time.*-bound element) at this time instead of the sample 10:09:42" },
    { flags: ["--units"], choices: ["metric", "statute"], help: "the watch's unit setting to render a 'units: auto' element under (default: metric)" },
    { flags: ["--asleep"], kind: "flag", help: "hide every awake-only second hand, simulating a sleeping glance (no mode/aod-set switch: 'always_on' membership used to do that too, but was removed -- see --aod)" },
    { flags: ["--aod"], kind: "flag", help: "render the AMOLED always-on-display frame: the resolved 'aod:' set, restyled, with every awake-only second hand hidden" },
    { flags: ["--minute"], type: INT, metavar: "N", help: "render minute N of the day (0-1439); sugar for --time, and mutually exclusive with it" },
    { flags: ["--heatmap"], kind: "flag", help: "sum the AOD frame (implies --aod) over every minute of the day into one PNG where a pixel lit every minute is white, and print the largest share of minutes any pixel was lit" },
    { flags: ["--skin"], kind: "flag", help: "draw the watch round the screen: the simulator skin from the device files; a device without one renders the bare screen, with a warning" },
    { flags: ["-w", "--watch"], kind: "flag", help: "re-render whenever the design or a font it uses changes" },
    { flags: ["--interval"], type: FLOAT, default: 0.4, help: "seconds between checks while watching (default: 0.4)" },
    DEVICES_DIR,
    { flags: ["--fonts"], dest: "fonts_dir", help: "Garmin ConnectIQ Fonts directory (default: $WFB_FONTS, vendor/fonts/, or the SDK Manager's per-OS install location); without it, any face the registry has no exact match for is drawn with a stand-in typeface -- see `wfb doctor`" },
  ], [DESIGN]),
  command("simulate", simulateCommand, [
    VERBOSE,
    { flags: ["-d", "--device"], help: "which device to run, target or not (default: the first target)" },
    { flags: ["-o", "--output"], default: DEFAULT_OUTPUT, help: `build directory (default: ${DEFAULT_OUTPUT})` },
    { flags: ["--screenshot"], help: "capture the simulator window to this PNG" },
    { flags: ["-f", "--follow"], kind: "flag", help: "stay attached and print the face's console output (System.println) until Ctrl-C" },
    { flags: ["--sdk"], help: "Connect IQ SDK root (default: $CIQ_SDK)" },
    { flags: ["--key"], help: "developer key .der (default: ~/ciq/developer_key.der)" },
    DEVICES_DIR,
  ], [DESIGN]),
  command("new", newCommand, [
    { flags: ["-t", "--template"], default: "dashboard", help: "which template to start from (default: dashboard)" },
    { flags: ["-o", "--output"], help: "where to write it (default: <name>.yaml in the current directory)" },
    { flags: ["--list"], kind: "flag", dest: "list_templates", help: "list the available templates and exit" },
  ], [{ dest: "name", optional: true, help: "the face's name, e.g. \"My Face\"" }]),
  command("studio", studioCommand, [
    { flags: ["--host"], default: "127.0.0.1", help: "the address to listen on (default: 127.0.0.1, loopback only)" },
    { flags: ["--allow-host"], kind: "append", dest: "allow_host", metavar: "NAME", help: "also answer requests addressed to NAME (a remote machine's or a proxy's name); repeatable. IP addresses and localhost are always answered" },
    { flags: ["--allow-any-host"], kind: "flag", dest: "allow_any_host", help: "answer requests addressed by any name, for debugging: a web page whose name points at this computer can then read the editor (warns)" },
    { flags: ["-p", "--port"], type: INT, default: 8765, help: "the port to listen on (default: 8765)" },
    DEVICES_DIR,
    { flags: ["--fonts"], dest: "fonts_dir", help: "Garmin ConnectIQ Fonts directory, as for `wfb preview`" },
  ]),
  command("devices", devicesCommand, [DEVICES_DIR]),
  command("fonts", fontsCommand, [
    { flags: ["-d", "--device"], kind: "append", dest: "device_flags", metavar: "DEVICE", help: "another device to inspect (repeatable; alternative or addition to the positional form)" },
    DEVICES_DIR,
  ], [{ dest: "devices", many: true, metavar: "DEVICE", help: "device(s) to inspect (repeatable; default: all installed devices, summarised)" }]),
  command("doctor", doctorCommand, [
    DEVICES_DIR,
    { flags: ["--fonts"], dest: "fonts_dir", help: "Garmin ConnectIQ Fonts directory (default: $WFB_FONTS, vendor/fonts/, or the SDK Manager's per-OS install location)" },
  ]),
  command("schema", schemaCommand, [{ flags: ["--path"], kind: "flag", help: "print the schema's path instead of its contents" }]),
  command("sources", sourcesCommand),
  command("complications", complicationsCommand),
  command("series", seriesCommand),
  command("help", helpCommand, [], [{ dest: "topic", optional: true, help: "a command name, e.g. `wfb help build`" }]),
];

const COMMAND_MAP: ReadonlyMap<string, Command> = new Map(COMMAND_LIST.map((c) => [c.name, c]));

const TOP_OPTIONS: readonly Option[] = [HELP, COLOR, { flags: ["--version"], kind: "flag", help: "show program's version number and exit" }];

function usageOf(c: Command | null): string {
  if (c === null) return "usage: wfb [-h] [--color {auto,always,never}] [--version] <command> ...";
  const positionals = c.positionals.map((p) => {
    const name = p.metavar ?? p.dest;
    return p.many ? `[${name} ...]` : p.optional ? `[${name}]` : name;
  });
  return ["usage: wfb", c.name, "[options]", ...positionals].join(" ");
}

/** Help rows: two-space indent, the help text from column 24, wrapped to the terminal. */
function helpRows(rows: [string, string][]): string[] {
  const width = (term.width(process.stdout) ?? 80) - 2;
  const lines: string[] = [];
  for (const [name, help] of rows) {
    const wrapped = help ? wrap(help, Math.max(11, width - 24)) : [];
    if (name.length <= 20 && wrapped.length > 0) {
      lines.push(`  ${name.padEnd(22)}${wrapped[0]}`);
      wrapped.shift();
    } else {
      lines.push(`  ${name}`);
    }
    lines.push(...wrapped.map((l) => " ".repeat(24) + l));
  }
  return lines;
}

const optionRow = (o: Option): [string, string] =>
  [o.kind === "flag" ? o.flags.join(", ") : `${o.flags.join(", ")} ${o.bare !== undefined ? `[${metavarOf(o)}]` : metavarOf(o)}`, o.help ?? ""];

function formatHelp(c: Command | null): string {
  const sections = [usageOf(c), c === null ? MAIN : c.description];
  if (c === null) {
    sections.push(["commands:", ...helpRows(COMMAND_LIST.map((x) => [x.name, x.summary]))].join("\n"));
    sections.push(["options:", ...helpRows(TOP_OPTIONS.map(optionRow))].join("\n"));
  } else {
    if (c.positionals.length) sections.push(["positional arguments:", ...helpRows(c.positionals.map((p) => [p.metavar ?? p.dest, p.help ?? ""]))].join("\n"));
    sections.push(["options:", ...helpRows(c.options.map(optionRow))].join("\n"));
  }
  return sections.join("\n\n") + "\n";
}

/** `--profile` given bare -> `--profile=<bare>`; `-o --` -> `--output=-`, before `--` can end the options. */
function normalise(argv: readonly string[], options: readonly Option[]): string[] {
  const out: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]!, next = argv[i + 1];
    const bare = options.find((o) => o.bare !== undefined && o.flags.includes(arg));
    if (bare !== undefined && (next === undefined || !/^\d+$/.test(next))) out.push(`${arg}=${bare.bare}`);
    else if ((arg === "-o" || arg === "--output") && next === "--") out.push("--output=-"), i++;
    else out.push(arg);
  }
  return out;
}

/** `c`'s arguments from `argv`, or `null` for `--help`. */
function parseCommand(c: Command, argv: readonly string[]): Namespace | null {
  const config: Record<string, { type: "string" | "boolean"; short?: string; multiple?: boolean }> = {};
  for (const o of c.options) {
    const short = o.flags.find((f) => !f.startsWith("--"));
    config[longFlag(o).slice(2)] = { type: o.kind === "flag" ? "boolean" : "string", ...(short ? { short: short.slice(1) } : {}), ...(o.kind === "append" ? { multiple: true } : {}) };
  }
  let parsed;
  try {
    parsed = parseArgs({ args: normalise(argv, c.options), options: config, allowPositionals: true, strict: true });
  } catch (e) {
    throw new UsageError((e as Error).message.split(/\.\s/)[0]!);
  }
  if (parsed.values["help"]) return null;
  const args: Namespace = { command: c.name, handler: c.handler };
  for (const o of c.options) {
    const given = parsed.values[longFlag(o).slice(2)];
    const name = o.flags.join("/");
    const convert = (text: string): unknown => {
      if (o.choices && !o.choices.includes(text)) throw new UsageError(`argument ${name}: invalid choice: ${quoted(text)} (choose from ${o.choices.join(", ")})`);
      try {
        return o.type ? o.type(text) : text;
      } catch (e) {
        throw new UsageError(`argument ${name}: ${(e as Error).message}`);
      }
    };
    if (o.kind === "flag") args[destOf(o)] = given === true;
    else if (given === undefined) args[destOf(o)] = o.default ?? null;
    else args[destOf(o)] = Array.isArray(given) ? given.map((g) => convert(g as string)) : convert(given as string);
  }
  const rest = [...parsed.positionals];
  for (const p of c.positionals) {
    if (p.many) args[p.dest] = rest.splice(0);
    else if (rest.length) args[p.dest] = rest.shift();
    else if (p.optional) args[p.dest] = null;
    else throw new UsageError(`the following arguments are required: ${p.dest}`);
  }
  if (rest.length) throw new UsageError(`unrecognized arguments: ${rest.join(" ")}`);
  return args;
}

export async function main(argv: string[] = process.argv.slice(2)): Promise<number> {
  let color: string | null = null;
  let i = 0;
  let current: Command | null = null;
  let args: Namespace | null;
  try {
    for (; i < argv.length && argv[i]!.startsWith("-"); i++) {
      const arg = argv[i]!;
      if (arg === "-h" || arg === "--help") {
        process.stdout.write(formatHelp(null));
        return 0;
      }
      if (arg === "--version") {
        out(`wfb ${VERSION}`);
        return 0;
      }
      if (arg === "--color" || arg.startsWith("--color=")) {
        color = arg === "--color" ? argv[++i] ?? null : arg.slice("--color=".length);
        if (color === null || !(term.MODES as readonly string[]).includes(color)) throw new UsageError(`argument --color: invalid choice: ${quoted(color ?? "")} (choose from ${term.MODES.join(", ")})`);
        continue;
      }
      throw new UsageError(`unrecognized arguments: ${arg}`);
    }
    if (i === argv.length) {
      process.stdout.write(formatHelp(null));
      return 2;
    }
    current = COMMAND_MAP.get(argv[i]!) ?? null;
    if (current === null) throw new UsageError(`argument command: invalid choice: ${quoted(argv[i])} (choose from ${[...COMMAND_MAP.keys()].join(", ")})`);
    const rest = argv.slice(i + 1);
    args = parseCommand(current, rest.length === 1 && rest[0] === "help" ? ["--help"] : rest);
  } catch (e) {
    if (!(e instanceof UsageError)) throw e;
    err(usageOf(current));
    err(`wfb${current ? ` ${current.name}` : ""}: error: ${e.message}`);
    return 2;
  }
  if (args === null) {
    process.stdout.write(formatHelp(current));
    return 0;
  }
  term.setMode((args["color"] as string | null) || color || "auto");
  installAssets();
  try {
    return await (args["handler"] as Handler)(args);
  } catch (e) {
    if (e instanceof DeviceError || e instanceof icons.IconFontMissing) {
      error(e.message);
      return 1;
    }
    throw e;
  }
}

// -- commands --

async function buildCommand(args: Namespace): Promise<number> {
  const bag = new Bag();
  const result = await runBuild(args["design"] as string, {
    output: args["output"] as string, bag, devicesOnly: (args["devices"] as string[] | null) ?? null,
    db: discoverDb(args["devices_dir"] as string | null),
    toolchain: Toolchain.discover(args["sdk"] as string | null, args["key"] as string | null),
    compilePrg: !args["no_compile"], profile: args["profile"] as number | null, jobs: args["jobs"] as number | null,
  });
  const verboseFlag = Boolean(args["verbose"]);
  let shown = bag;
  if (result !== null && !verboseFlag) {
    // The "built" lines give each built device's measured memory.
    shown = bag.only((d: Diagnostic) => !(d.code === "memory" && d.severity === "note" && result.products.has(d.message.split(":", 1)[0]!)));
  }
  printBag(shown, verboseFlag);
  if (result === null || !bag.ok()) {
    verdict(bag, process.stderr, "failed", ["bold", "red"], "\nbuild ");
    return 1;
  }
  const color = term.shouldColor(process.stdout);
  out();
  out(`${status("generated", color)}  ${result.output_dir}`);
  for (const line of formatBuilt(result.products, result.memory, color)) out(line);
  if (result.products.size === 0 && args["no_compile"]) out("           (not compiled: --no-compile)");
  if (result.sdk_version !== null) out(`${status("sdk", color)}        Connect IQ ${result.sdk_version}, recorded in ${BUILD_INFO}`);
  if (args["profile"] && result.products.size > 0) printProfileReport(result, args["profile"] as number);
  verdict(bag, process.stdout, "succeeded", ["bold", "green"], "\nbuild ", ` in ${formatFixed(result.duration, 1)}s`);
  return 0;
}

/** `--profile`'s code-size table for the first target built, also written to `profile.txt`. */
function printProfileReport(result: BuildResult, reps: number): void {
  const [deviceId, prg] = [...result.products][0]!;
  const debug = `${prg}.debug.xml`;
  if (!existsSync(debug)) return;
  const plan = planFor(result.project.resolved.get(deviceId)!, reps);
  const lines = codeReport(plan, result.face, methodCodeSizes(debug));
  const report = join(result.output_dir, "profile.txt");
  writeFileSync(report, lines.join("\n") + "\n");
  out(`\ncode per entry (${deviceId}; draw time is on the watch), also in ${report}:`);
  for (const line of lines) out(`  ${line}`);
}

function validateCommand(args: Namespace): number {
  const bag = new Bag();
  const design = pathStr(args["design"] as string);
  const face = loadDesign(design, bag);
  if (face !== null) {
    let db: DeviceDatabase | null = null;
    try {
      db = discoverDb(args["devices_dir"] as string | null);
    } catch (e) {
      if (!(e instanceof DeviceError)) throw e;
      bag.note("devices", e.message);
    }
    if (db !== null) {
      const devices = selectDevices(face, db, bag, (args["devices"] as string[] | null) ?? null);
      if (devices.length > 0) resolveAll(face, devices, bag, baker);
    }
  }
  printBag(bag, Boolean(args["verbose"]));
  if (face === null || !bag.ok()) {
    verdict(bag, process.stderr, "invalid", ["red"], "\n");
    return 1;
  }
  verdict(bag, process.stdout, "ok", ["bold", "green"], `${design}: `);
  return 0;
}

/** `HH:MM` or `HH:MM:SS`, or `null`. */
function parsePreviewTime(text: string): [number, number, number] | null {
  const parts = text.split(":");
  if ((parts.length !== 2 && parts.length !== 3) || !parts.every((p) => /^\d+$/.test(p))) return null;
  const [hour, minute] = [Number(parts[0]), Number(parts[1])];
  const second = parts.length === 3 ? Number(parts[2]) : 0;
  if (!(hour < 24 && minute < 60 && second < 60)) return null;
  return [hour, minute, second];
}

class FlagError extends Error {}

/** Check `preview`'s flag combinations and return the moment to render (`null`: the sample time). */
function previewTime(args: Namespace, minutesPerDay: number): [number, number, number] | null {
  const exclusive: [string, boolean][][] = [
    [["--style", args["style"] != null], ["--all-styles", Boolean(args["all_styles"])]],
    [["--time", args["time"] != null], ["--minute", args["minute"] != null], ["--heatmap", Boolean(args["heatmap"])]],
  ];
  for (const flags of exclusive) {
    const given = flags.filter(([, on]) => on).map(([name]) => name);
    if (given.length > 1) throw new FlagError(`${given.join(" and ")} are mutually exclusive`);
  }
  if (args["heatmap"] && args["all_styles"]) throw new FlagError("--heatmap renders one panel; use --style to pick it, not --all-styles");
  if (args["time"] != null) {
    const time = parsePreviewTime(args["time"] as string);
    if (time === null) throw new FlagError(`--time ${quoted(args["time"])} is not HH:MM or HH:MM:SS`);
    return time;
  }
  if (args["minute"] != null) {
    const minute = args["minute"] as number;
    if (!(minute >= 0 && minute < minutesPerDay)) throw new FlagError(`--minute ${minute} is not 0..${minutesPerDay - 1}`);
    return [Math.floor(minute / 60), minute % 60, 0];
  }
  return null;
}

/** Render once: the exit code and the files the design depends on. */
async function renderPreview(args: Namespace, db: DeviceDatabase, blurb = true): Promise<[number, string[]]> {
  const preview = await import("./preview.ts");
  const design = pathStr(args["design"] as string);
  const toStdout = isStdout(args["output"]);
  const quiet = toStdout || Boolean(args["quiet"]);
  const style = (args["style"] as string | null) ?? null;
  const allStyles = Boolean(args["all_styles"]), heatmap = Boolean(args["heatmap"]);
  const verboseFlag = Boolean(args["verbose"]);
  let time: [number, number, number] | null;
  try {
    time = previewTime(args, preview.MINUTES_PER_DAY);
  } catch (e) {
    if (!(e instanceof FlagError)) throw e;
    error(e.message);
    return [1, [design]];
  }
  const bag = new Bag();
  const face = loadDesign(design, bag);
  if (face === null) {
    printBag(bag, verboseFlag);
    return [1, [design]];
  }
  const watched = [design, ...[...face.fonts.values()].map((spec) => spec.source).filter((s): s is string => s !== null)];
  let devices = selectDevices(face, db, bag, (args["devices"] as string[] | null) ?? null);
  if (devices.length === 0) {
    printBag(bag, verboseFlag);
    return [1, watched];
  }
  // One stream, one image: the first device asked for, or the first target.
  if (toStdout) devices = devices.slice(0, 1);
  const [resolved] = resolveAll(face, devices, bag, baker);
  printBag(bag, verboseFlag);
  if (!bag.ok()) return [1, watched];

  let sample: Map<string, number> | null = null;
  if (args["units"] != null) {
    const setting = args["units"] === "statute" ? 1 : 0;
    sample = new Map(["distance", "elevation", "temperature", "pace"].map((name) => [`device.${name}_units`, setting]));
  }
  const skin = Boolean(args["skin"]);
  const scale = args["scale"] as number;
  const options = preview.previewOptions({
    scale, quantise: !args["no_quantise"], style, time, asleep: Boolean(args["asleep"]), aod: heatmap || Boolean(args["aod"]),
    sample, skin,
  });
  const color = term.shouldColor(process.stdout);
  const label = status("preview", color);
  const usedFaces: import("./preview.ts").UsedFaces = new Map();
  const results = [...resolved.values()] as ResolvedFace[];
  try {
    for (const [deviceId, result] of resolved) {
      let note = `${result.device.width}x${result.device.height} at ${scale}x`;
      let image: import("./preview.ts").Frame;
      let suffix: string;
      if (heatmap) {
        const [heat, peak] = preview.renderAodHeatmap(result, options, usedFaces);
        image = heat;
        suffix = "--heatmap";
        note += `, max ${formatFixed(peak * 100, 1)}% of minutes any one pixel was lit`;
      } else if (allStyles) {
        image = preview.renderAllStyles(result, options, usedFaces);
        suffix = "--all-styles";
      } else {
        image = preview.render(result, options, usedFaces);
        suffix = "";
      }
      if (style !== null) suffix = `--${style}${suffix}`;
      if (skin && preview.hasSkin(result.device)) {
        suffix += "--skin";
        note += ", in the simulator skin";
      }
      const bytes = preview.pngBytes(image);
      if (toStdout) {
        process.stdout.write(bytes);
        continue;
      }
      const path = join(args["output"] as string, `${deviceId}${suffix}.png`);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, bytes);
      if (!quiet) out(`${label}    ${path}  (${note})`);
    }
  } catch (e) {
    if (!(e instanceof preview.UnknownStyleError)) throw e;
    error(e.message);
    return [1, watched];
  }
  // Warnings, not progress: stderr, after every device has recorded its faces.
  for (const warning of [
    preview.standInWarning(usedFaces),
    preview.monoGuessWarning(results.map((r) => r.device), options.quantise),
    preview.skinMissingWarning(results.map((r) => r.device), skin),
  ]) {
    if (warning) err(warning);
  }
  if (blurb && !quiet) {
    out();
    for (const line of [
      "Rendered from the same resolved geometry the generated code uses, so the",
      "two cannot disagree about position.  Glyph rendering and arc caps are",
      "approximations -- the simulator is authoritative for those.",
    ]) out(term.style(line, ["dim"], color));
  }
  return [0, watched];
}

async function previewCommand(args: Namespace): Promise<number> {
  if (isStdout(args["output"]) && args["watch"]) {
    error("-o - writes one image and exits; it cannot be combined with --watch");
    return 1;
  }
  const db = discoverDb(args["devices_dir"] as string | null, args["fonts_dir"] as string | null);
  if (!args["watch"]) {
    if (!(args["quiet"] || isStdout(args["output"]))) out();
    return (await renderPreview(args, db))[0];
  }
  const stamps = (paths: string[]): Map<string, number> =>
    new Map(paths.map((p) => {
      try {
        return [p, statSync(p).mtimeMs];
      } catch {
        return [p, 0];
      }
    }));
  const same = (a: Map<string, number>, b: Map<string, number>): boolean => a.size === b.size && [...a].every(([k, v]) => b.get(k) === v);
  const quiet = Boolean(args["quiet"]);
  const color = term.shouldColor(process.stdout);
  if (!quiet) out(`watching ${pathStr(args["design"] as string)} -- press Ctrl-C to stop\n`);
  let [code, watched] = await renderPreview(args, db, false);
  let seen = stamps(watched);
  let stopped = false;
  process.once("SIGINT", () => { stopped = true; });
  while (!stopped) {
    await new Promise((done) => setTimeout(done, (args["interval"] as number) * 1000));
    if (stopped) break;
    const current = stamps(watched);
    if (same(current, seen)) continue;
    seen = current;
    if (!quiet) {
      const now = new Date();
      const clock = [now.getHours(), now.getMinutes(), now.getSeconds()].map((n) => String(n).padStart(2, "0")).join(":");
      out(`\n${term.style(`--- ${clock} ---`, ["dim"], color)}`);
    }
    [code, watched] = await renderPreview(args, db, false);
    for (const [k, v] of stamps(watched)) seen.set(k, v);
  }
  if (!quiet) out("\nstopped watching");
  return code;
}

async function simulateCommand(args: Namespace): Promise<number> {
  const { push, screenshot, SimulatorError } = await import("./simulate.ts");
  const bag = new Bag();
  const toolchain = Toolchain.discover(args["sdk"] as string | null, args["key"] as string | null);
  const device = (args["device"] as string | null) ?? null;
  const result = await runBuild(args["design"] as string, {
    output: args["output"] as string, bag, devicesOnly: device ? [device] : null,
    db: discoverDb(args["devices_dir"] as string | null), toolchain, compilePrg: true,
  });
  printBag(bag, Boolean(args["verbose"]));
  if (toolchain === null || result === null || result.products.size === 0) {
    err("\nnothing to run -- the build produced no .prg");
    return 1;
  }
  const deviceId = device ?? result.devices[0]!.id;
  const prg = result.products.get(deviceId);
  if (prg === undefined) {
    err(`\nno build for ${deviceId}`);
    return 1;
  }
  let session: Awaited<ReturnType<typeof push>>;
  try {
    session = await push(toolchain, prg, deviceId);
  } catch (e) {
    if (!(e instanceof SimulatorError)) throw e;
    err(`\nsimulator: ${e.message}`);
    for (const hint of e.hints) err(`  ${hint}`);
    err("\n  `wfb preview` renders the same resolved geometry with no simulator.");
    return 1;
  }
  const color = term.shouldColor(process.stdout);
  out(`\n${status("pushed", color)} ${basename(prg)} to the ${deviceId} simulator`);
  if (args["screenshot"]) {
    try {
      const [path, note] = await screenshot(args["screenshot"] as string);
      out(`${status("screenshot", color)} ${path}`);
      if (note) err(`  ${note}`);
    } catch (e) {
      err(`screenshot failed: ${(e as Error).message}`);
      return 1;
    }
  }
  if (!args["follow"]) {
    out(`console output: ${session.log}`);
    return 0;
  }
  out("following the face's console output (Ctrl-C to stop)");
  let interrupted = false;
  process.once("SIGINT", () => { interrupted = true; });
  for await (const chunk of session.follow()) {
    process.stdout.write(chunk);
    if (interrupted) break;
  }
  if (interrupted) out(`\nstopped following; the face is still running, and its output still goes to ${session.log}`);
  return 0;
}

async function studioCommand(args: Namespace): Promise<number> {
  const { serve } = await import("./studio/server.ts");
  let db: DeviceDatabase;
  try {
    db = discoverDb(args["devices_dir"] as string | null, args["fonts_dir"] as string | null);
  } catch (e) {
    if (!(e instanceof DeviceError)) throw e;
    error(e.message);
    return 1;
  }
  await serve({
    host: args["host"] as string, allowHosts: (args["allow_host"] as string[] | null) ?? [], allowAnyHost: args["allow_any_host"] === true,
    port: args["port"] as number, db,
    fontsDir: (args["fonts_dir"] as string | null) ?? null,
  });
  return 0;
}

function newCommand(args: Namespace): number {
  const templates = starters.names();
  if (args["list_templates"]) {
    for (const name of templates) out(`  ${name.padEnd(12)} ${starters.blurb(name)}`);
    return 0;
  }
  const name = args["name"] as string | null;
  if (!name) {
    error("a face name is required");
    err(`       usage: wfb new "My Face" [--template ${templates.join("|")}]`);
    return 1;
  }
  const template = args["template"] as string;
  if (!templates.includes(template)) {
    error(`no template ${quoted(template)}`);
    err(`       available: ${templates.join(", ")}`);
    return 1;
  }
  const destination = pathStr((args["output"] as string | null) ?? `${slug(name)}.yaml`);
  if (existsSync(destination)) {
    error(`${destination} already exists`);
    return 1;
  }
  const text = starters.instantiate(template, name);
  mkdirSync(dirname(destination), { recursive: true });
  writeFileSync(destination, text);
  out(`created ${destination}  (from the ${quoted(template)} template)`);
  out();
  out("next:");
  out(`  wfb preview ${destination} --watch     # render as you edit`);
  out(`  wfb build   ${destination}             # compile it`);
  return 0;
}

/** How far `doctor`'s explanatory lines are indented: under the detail column. */
const DOCTOR_INDENT = " ".repeat(19);

function doctorSystemFonts(deviceIds: string[], devicesRoot: string, fonts: NodeFontFiles, ok: string, absent: string,
  hint: (...lines: string[]) => void): void {
  // "unmapped" is a deliberate registry decision (a CJK/RTL-only face), never missing.
  const tierOf = new Map<string, string>();
  const lacking: string[] = [];
  for (const deviceId of deviceIds) {
    let deviceMissing = false;
    for (const [name, face] of deviceNeededNames(deviceId, devicesRoot)) {
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
  if (lacking.length === 0) {
    out(`${ok} system fonts     all ${deviceIds.length} devices covered (${summary} font names)`);
    return;
  }
  const shown = lacking.slice(0, 4).join(", ") + (lacking.length > 4 ? " ..." : "");
  out(`${absent} system fonts     ${lacking.length} of ${deviceIds.length} devices lack a stand-in: ${shown}`);
  hint(`(${summary} font names) -- run node ts/tools/fetch-system-fonts.ts;`, "not blocking, falls back to a substitute face at build time");
}

function doctorCommand(args: Namespace): number {
  const color = term.shouldColor(process.stdout);
  const ok = term.style("  ok ", ["green"], color);
  const missing = term.style("MISSING", ["bold", "red"], color);
  const absent = term.style(" none", ["yellow"], color);
  const problems: string[] = [];
  let blocking = 0;
  const hint = (...lines: string[]): void => {
    for (const line of lines) out(DOCTOR_INDENT + line);
  };
  const fail = (fix: string, hints: string[], blocks = true): void => {
    hint(...hints);
    problems.push(fix);
    if (blocks) blocking++;
  };

  out(`wfb ${VERSION}`);
  out(`  node             ${process.version.slice(1)}  (${process.execPath})`);
  out(`${existsSync(SCHEMA) ? ok : missing} schema           ${SCHEMA}`);

  const haveReference = existsSync(DEVICE_REFERENCE) && statSync(DEVICE_REFERENCE).isDirectory();
  out(`${haveReference ? ok : missing} device reference ${dirname(DEVICE_REFERENCE)}`);
  if (!haveReference) fail("generate the SDK device reference", ["run tools/setup-env.sh, or node ts/tools/extract-device-reference.ts"]);

  const haveIcons = existsSync(ICON_FONT);
  out(`${haveIcons ? ok : missing} icon font        ${ICON_FONT}`);
  if (!haveIcons) fail("install the icon font", ["run tools/setup-env.sh, or node ts/tools/fetch-icon-font.ts"]);

  // Garmin's own font files: optional, and never downloaded here.
  const fontsDir = (args["fonts_dir"] as string | null) ?? null;
  const fontsRoot = garminFontRoot(fontsDir);
  if (fontsRoot !== null) {
    out(`${ok} Garmin fonts     ${fontsRoot}  (previews draw exact glyph shapes)`);
  } else {
    out(`${absent} Garmin fonts     not found (optional; previews draw stand-in typefaces for any face the registry has no exact match for)`);
    if (process.env["WFB_CONTAINER"] === "1") {
      const mount = process.env["WFB_FONTS"] || "/fonts";
      hint("mount the SDK Manager's Fonts directory:", `  -v <SDK Manager's Fonts dir>:${mount}:ro`, "-- see docs/container.md");
    } else {
      hint("copy the SDK Manager's Fonts directory into vendor/fonts/,", "or set WFB_FONTS / pass --fonts DIR -- see docs/container.md");
    }
  }

  try {
    const files = NodeDeviceFiles.discover((args["devices_dir"] as string | null) ?? undefined);
    const ids = files.ids();
    out(`${ok} devices          ${ids.length} installed: ${ids.slice(0, 4).join(", ")}${ids.length > 4 ? " ..." : ""}`);
    hint(files.root);
    doctorSystemFonts(ids, files.root, new NodeFontFiles(fontsDir), ok, absent, hint);
  } catch (e) {
    if (e instanceof DeviceReferenceMissing) {
      out(`${absent} devices          not checked: the device reference above is missing`);
    } else if (e instanceof DeviceError) {
      out(`${missing} devices`);
      fail("install the device definitions", [
        "they cannot be downloaded -- api.gcs.garmin.com returns HTTP 401.",
        "copy them from a machine where the Connect IQ SDK",
        "Manager has installed them:",
        "  macOS  ~/Library/Application Support/Garmin/ConnectIQ/Devices",
        "  Linux  ~/.Garmin/ConnectIQ/Devices",
        "then set WFB_DEVICES to that directory.",
      ]);
    } else throw e;
  }

  let canCompile = false;
  const toolchain = Toolchain.discover();
  if (toolchain === null) {
    out(`${missing} Connect IQ SDK`);
    fail("install the Connect IQ SDK", ["set CIQ_SDK, or run tools/setup-env.sh"], false);
  } else {
    out(`${ok} Connect IQ SDK   ${toolchain.version}  (${toolchain.sdk})`);
    const extracted = referenceSdkVersion();
    if (extracted !== null && extracted !== toolchain.version) {
      out(`${missing} device reference extracted from SDK ${extracted}`);
      fail("extract the device reference from this SDK", ["run tools/setup-env.sh, or node ts/tools/extract-device-reference.ts"], false);
    }
    const keyDir = dirname(toolchain.key);
    canCompile = true;
    if (existsSync(toolchain.key)) {
      out(`${ok} developer key    ${toolchain.key}`);
    } else if (writable(keyDir)) {
      // The first build that needs a key creates it.
      out(`${ok} developer key    will be generated at ${toolchain.key}`);
    } else {
      canCompile = false;
      out(`${missing} developer key    expected at ${toolchain.key},`);
      fail("generate a developer key", [
        `and ${keyDir} is not writable.  Create one with:`,
        "  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 \\",
        "    -out key.pem",
        "  openssl pkcs8 -topk8 -inform PEM -outform DER \\",
        `    -in key.pem -out ${toolchain.key} -nocrypt`,
      ], false);
    }
  }

  out();
  if (blocking === 0 && canCompile) {
    out(`${term.style("ready", ["green"], color)}: validate, preview and build all work.`);
    return 0;
  }
  if (blocking === 0) {
    out(`${term.style("partial", ["yellow"], color)}: validate and preview work; \`wfb build\` cannot compile yet.`);
    out("         fix: " + problems.join("; "));
    return 0;
  }
  out(`${term.style("not ready", ["red"], color)}: ${problems.join("; ")}`);
  return 1;
}

/** Python's `os.access(dir, os.W_OK)`. */
function writable(dir: string): boolean {
  try {
    accessSync(dir, constants.W_OK);
    return true;
  } catch {
    return false;
  }
}

function schemaCommand(args: Namespace): number {
  if (args["path"]) {
    out(SCHEMA);
    return 0;
  }
  process.stdout.write(readFileSync(SCHEMA, "utf8"));
  return 0;
}

function devicesCommand(args: Namespace): number {
  const db = discoverDb(args["devices_dir"] as string | null);
  const color = term.shouldColor(process.stdout);
  const header = `${"id".padEnd(24)} ${"screen".padEnd(12)} ${"shape".padEnd(12)} ${"display".padEnd(8)} ${"colors".padEnd(7)} ${"api".padEnd(8)} ${"watch face".padEnd(10)} family`;
  out(term.style(header, ["bold"], color));
  for (const id of db.ids()) {
    const device = db.get(id);
    const limit = device.supportsWatchface ? `${Math.floor(device.watchfaceMemoryLimit / 1024)} KB` : "-";
    const colors = device.displayColors ? String(device.displayColors) : "?";
    out(`${device.id.padEnd(24)} ${device.width}x${String(device.height).padEnd(8)} ${device.shape.padEnd(12)} ${device.displayType.padEnd(8)} ${colors.padEnd(7)} ${device.apiLevel.padEnd(8)} ${limit.padEnd(10)} ${device.deviceFamily}`);
  }
  return 0;
}

const dim = (text: string, color: boolean): string => term.style(text, ["dim"], color);

/** The vector-text entry points `fonts` reports, by the name it prints. */
const VECTOR_GATES: [string, string][] = [
  ["getVectorFont", "Graphics.getVectorFont"],
  ["drawRadialText", "Dc.drawRadialText"],
  ["drawAngledText", "Dc.drawAngledText"],
];

function printAllDeviceFontsSummary(db: DeviceDatabase): void {
  const color = term.shouldColor(process.stdout);
  const ids = db.ids();
  if (ids.length === 0) {
    out("no installed devices found");
    return;
  }
  ids.forEach((id, i) => {
    if (i > 0) out();
    const device = db.get(id);
    out(`${term.style(device.id, ["bold"], color)} (${device.width}x${device.height} ${device.shape}, CIQ ${device.apiLevel})`);
    if (!device.supportsWatchface) {
      out("  cannot run a watch face");
      return;
    }
    const gates = VECTOR_GATES.filter(([, symbol]) => device.hasSymbol(symbol)).map(([name]) => name);
    const hasVector = gates.includes("getVectorFont");
    out(`  vector text:   ${gates.length > 0 ? gates.join(", ") : dim("none", color)}`);
    const faces = device.scalableFaces;
    if (faces.length > 0 && hasVector) {
      out(fill(`  scalable (${faces.length}): ` + faces.join(", "), 88, { subsequentIndent: "    " }));
    } else if (faces.length > 0) {
      out(`  scalable:      ${dim("none", color)} usable (${faces.length} published, no Graphics.getVectorFont)`);
    } else {
      out(`  scalable:      ${dim("none", color)} (no vector fonts)`);
    }
    const system = [...device.systemFonts.values()];
    if (system.length > 0) {
      out(fill(`  system (${system.length}):   ` + system.map((m) => `${m.symbol} (${m.size_px}px)`).join(", "), 88, { subsequentIndent: "    " }));
    } else {
      out(`  system:        ${dim("none", color)}`);
    }
  });
  out(term.style("\nrun `wfb fonts <device>` for full metrics and font files for a specific device", ["dim"], color));
}

function printDeviceFontsDetailed(device: Device): void {
  const color = term.shouldColor(process.stdout);
  const parts = [`${device.width}x${device.height} ${device.shape}`, `CIQ ${device.apiLevel}`];
  if (device.displayType) parts.push(device.displayType.toUpperCase());
  if (device.displayColors) parts.push(`${device.displayColors} colors`);
  out(`${term.style(device.id, ["bold"], color)} (${parts.join(", ")})`);
  if (!device.supportsWatchface) {
    out();
    out("  cannot run a watch face");
    return;
  }
  const hasVector = device.hasSymbol("Graphics.getVectorFont");
  const hasRadial = device.hasSymbol("Dc.drawRadialText");
  const hasAngled = device.hasSymbol("Dc.drawAngledText");
  const faces = device.scalableFaces;
  out();
  out(term.style(`Scalable (vector) fonts (${faces.length}):`, ["bold"], color));
  if (hasVector) {
    if (hasRadial && hasAngled) out("  Graphics.getVectorFont: yes (Dc.drawRadialText, Dc.drawAngledText)");
    else if (hasRadial) out("  Graphics.getVectorFont: yes; curve: {style: radial} available (Dc.drawRadialText); angled unavailable (no Dc.drawAngledText)");
    else if (hasAngled) out("  Graphics.getVectorFont: yes; curve: {style: angled} available (Dc.drawAngledText); radial unavailable (no Dc.drawRadialText)");
    else out("  Graphics.getVectorFont: yes, but curve: (radial/angled text) is unavailable on this device");
    out("  Use in face.yaml: under 'fonts:' with 'face: [<name>, ...]' (required for radial/angled text)");
  } else {
    out("  Graphics.getVectorFont: not available on this device");
  }
  if (faces.length > 0 && hasVector) {
    out();
    out(term.style(`  ${"Face Name".padEnd(32)} ${"File / Stem".padEnd(30)}`.trimEnd(), ["bold"], color));
    out(`  ${"-".repeat(30).padEnd(32)} ${"-".repeat(28).padEnd(30)}`.trimEnd());
    for (const face of faces) out(`  ${face.padEnd(32)} ${(device.scalableFaceFiles.get(face) ?? "-").padEnd(30)}`.trimEnd());
  } else if (faces.length > 0) {
    out(`  ${dim("none usable", color)} (${faces.length} published, no Graphics.getVectorFont)`);
  } else {
    out(`  ${dim("none (no vector fonts published)", color)}`);
  }
  out();
  const system = [...device.systemFonts.values()];
  out(term.style(`System fonts (${system.length}):`, ["bold"], color));
  out("  Use in face.yaml: directly as 'font: <symbol>' (e.g. font: FONT_SMALL)");
  if (system.length > 0) {
    out();
    out(term.style(`  ${"Symbol".padEnd(24)} ${"Line Height".padEnd(12)} ${"Em Size".padEnd(10)} ${"File / Stem".padEnd(28)} ${"Face Name".padEnd(20)}`.trimEnd(), ["bold"], color));
    out(`  ${"-".repeat(22).padEnd(24)} ${"-".repeat(11).padEnd(12)} ${"-".repeat(8).padEnd(10)} ${"-".repeat(26).padEnd(28)} ${"-".repeat(18).padEnd(20)}`.trimEnd());
    for (const m of system as FontMetric[]) {
      const em = m.em_px !== null ? `${formatFixed(m.em_px, 1)} px` : "-";
      out(`  ${m.symbol.padEnd(24)} ${`${m.size_px} px`.padEnd(12)} ${em.padEnd(10)} ${m.font.padEnd(28)} ${m.face.padEnd(20)}`.trimEnd());
    }
  } else {
    out(`  ${dim("none recorded in reference database", color)}`);
  }
}

function fontsCommand(args: Namespace): number {
  const db = discoverDb(args["devices_dir"] as string | null);
  const names: string[] = [];
  for (const name of [...(args["devices"] as string[]), ...((args["device_flags"] as string[] | null) ?? [])]) {
    if (!names.includes(name)) names.push(name);
  }
  if (names.length === 0) {
    printAllDeviceFontsSummary(db);
    return 0;
  }
  // Resolve every name first, so a typo cannot leave earlier output behind.
  const devices = names.map((name) => db.get(name));
  devices.forEach((device, i) => {
    if (i > 0) out();
    printDeviceFontsDetailed(device);
  });
  return 0;
}

/** The colours a design declares, listed by `sources` after the catalogue. */
const CONFIG_SOURCES: [string, string, string][] = [
  ["color.<swatch>", "color", "a 'resources: palette:' swatch, fixed at build time"],
  ["color.<role>", "color", "a 'theme: schemes:' role, following the active 'config: style:' entry's 'scheme:' (<styles>, Settings.styleId)"],
  ["color.accent", "color", "the role the one accent-colour axis binds, 'config: accent_color:' (<accentColors>, Settings.accentColor); 'role:' renames it"],
  ["color.data", "color", "the role the one data-colour axis binds, 'config: data_color:' (<dataColors>, Settings.complicationColor); 'role:' renames it"],
];

function sourcesCommand(): number {
  const color = term.shouldColor(process.stdout);
  for (const [namespace, paths] of catalog.namespaces()) {
    out(`\n${term.style(namespace, ["bold"], color)}`);
    for (const path of paths) {
      const source = catalog.CATALOG.get(path)!;
      const flags: string[] = [];
      if (catalog.guardNeeded(source)) flags.push("nullable");
      if (source.permissions.length > 0) flags.push("needs " + source.permissions.join("+"));
      if (source.launch_complication) flags.push(`on_hold: auto -> ${source.launch_complication}`);
      const suffix = flags.length > 0 ? `  [${flags.join(", ")}]` : "";
      const ref = source.source_ref ? `  (${source.source_ref})` : "";
      out(`  ${path.padEnd(34)} ${source.type.padEnd(8)} ${source.doc}${suffix}${ref}`);
    }
  }
  out(`\n${term.style("config", ["bold"], color)}  (declared per design in 'config:' -- fēnix 8 Solar's native editor only, see docs/guide/configuration.md)`);
  for (const [path, kind, doc] of CONFIG_SOURCES) out(`  ${path.padEnd(34)} ${kind.padEnd(8)} ${doc}`);
  out(`\nicons: ${icons.names().join(", ")}`);
  out("\nrun `wfb complications` for the full list of on_hold: targets");
  return 0;
}

function complicationsCommand(): number {
  const names = complications.names();
  const width = Math.max(...names.map((n) => n.length));
  const labelWidth = Math.max(...names.map((n) => complications.label(n).length));
  const iconWidth = Math.max(...names.map((n) => (icons.COMPLICATION_ICON.get(n) ?? "").length));
  for (const group of complications.CATEGORIES) {
    out(`${group}:`);
    for (const name of names.filter((n) => complications.category(n) === group)) {
      const entry = complications.TYPES.get(name)!;
      const since = entry.since === complications.EXIT_TO_API_LEVEL ? "" : `  (since ${entry.since})`;
      const icon = icons.COMPLICATION_ICON.get(name) ?? "";
      out(`  ${name.padEnd(width)}  ${complications.label(name).padEnd(labelWidth)}  icon: ${icon.padEnd(iconWidth)}  Complications.${entry.constant}${since}`);
    }
  }
  out(`\n${complications.TYPES.size} complication types. Use one as \`on_hold:\` on any element:`);
  out("  hr:\n    type: icon\n    icon: heart\n    on_hold: heart_rate");
  out("\n...or let the compiler pick one from the element's own value binding:");
  out("  hr:\n    type: icon\n    icon: heart\n    on_hold: auto");
  return 0;
}

function seriesCommand(): number {
  const names = series.names();
  const width = Math.max(...names.map((n) => n.length));
  for (const name of names) {
    const entry = series.SERIES.get(name)!;
    const flags: string[] = [];
    if (entry.interval_seconds !== null) flags.push(`1 sample / ${entry.interval_seconds}s`);
    if (entry.max_count !== null) flags.push(`max ${entry.max_count}`);
    if (entry.unit) flags.push(entry.unit);
    const suffix = flags.length > 0 ? `  [${flags.join(", ")}]` : "";
    out(`  ${name.padEnd(width)}  ${entry.value_type.padEnd(6)} ${entry.doc}${suffix}  (${entry.source_ref})`);
  }
  out(`\n${series.SERIES.size} series. Use one on a \`graph\` element:`);
  out("    hr_graph:\n      type: graph\n      series: heart_rate\n      range: 4h\n      style: line\n      color: color.accent");
  return 0;
}

function helpCommand(args: Namespace): number {
  const topic = args["topic"] as string | null;
  if (!topic) {
    process.stdout.write(formatHelp(null));
    return 0;
  }
  const target = COMMAND_MAP.get(topic);
  if (target === undefined) {
    error(`no such command ${quoted(topic)}`);
    err(`       commands: ${[...COMMAND_MAP.keys()].sort().join(", ")}`);
    return 1;
  }
  process.stdout.write(formatHelp(target));
  return 0;
}

if (process.argv[1] !== undefined && import.meta.filename === (await import("node:fs")).realpathSync(process.argv[1])) {
  process.exitCode = await main();
}
