// Terminal presentation: whether to colour a stream, and the styles used.
//
//
// Colour is decided per stream, so `wfb build 2>log` still colours stdout on
// a terminal while the log stays plain. The precedence, highest first:
//
// 1. `--color always|never` on the command line (`setMode`);
// 2. `NO_COLOR` set to anything non-empty disables colour (no-color.org);
// 3. `FORCE_COLOR` or `CLICOLOR_FORCE` set to anything non-empty enables it;
// 4. otherwise colour only a TTY whose `TERM` is not `dumb`.
//
// Nothing here changes *what* is printed, only how it looks: with colour off
// every helper returns its text unchanged.

export const MODES = ["auto", "always", "never"] as const;
export type Mode = (typeof MODES)[number];

let mode: Mode = "auto";

const RESET = "\x1b[0m";
const CODES: Record<string, string> = {
  bold: "1", dim: "2", red: "31", green: "32", yellow: "33", blue: "34", magenta: "35", cyan: "36",
};

/** What a stream tells us about itself: Node's `process.stdout` fits. */
export interface Stream {
  isTTY?: boolean;
  columns?: number;
}

function env(name: string): string | undefined {
  const proc = (globalThis as { process?: { env: Record<string, string | undefined> } }).process;
  return proc?.env[name];
}

/** Set the process-wide colour mode. */
export function setMode(value: string): void {
  if (!(MODES as readonly string[]).includes(value)) {
    throw new RangeError(`colour mode must be one of ${MODES.join(", ")}, not '${value}'`);
  }
  mode = value as Mode;
}

/** Whether text written to `stream` should carry ANSI colour. */
export function shouldColor(stream: Stream): boolean {
  if (mode === "always") return true;
  if (mode === "never") return false;
  if (env("NO_COLOR")) return false;
  if (env("FORCE_COLOR") || env("CLICOLOR_FORCE")) return true;
  if (env("TERM") === "dumb") return false;
  return stream.isTTY === true;
}

/**
 * The terminal width to wrap prose at, or `null` for "do not wrap". Only a
 * real terminal is wrapped: piped output keeps one logical line per line.
 */
export function width(stream: Stream, fallback = 100): number | null {
  if (stream.isTTY !== true) return null;
  return Math.max(60, stream.columns ?? fallback);
}

/** Wrap `text` in the named SGR styles when `enabled`; else return it as is. */
export function style(text: string, names: readonly string[], enabled: boolean): string {
  if (!enabled || names.length === 0 || !text) return text;
  return `\x1b[${names.map((n) => CODES[n]!).join(";")}m${text}${RESET}`;
}

/** Severity to styles, shared by diagnostics and the CLI's summary counts. */
export const SEVERITY_STYLE: Readonly<Record<string, readonly string[]>> = {
  error: ["bold", "red"],
  warning: ["bold", "yellow"],
  note: ["bold", "cyan"],
};
