// The part of Python's argparse the CLI uses, ported so `wfb`'s usage
// lines, help pages, error messages and exit codes read as they did:
// options and positionals interleaved, abbreviated long options, `-xVALUE`
// and `--x=VALUE`, `nargs` `?`, `*` and sub-commands, `store`,
// `store_true`, `append`, `version` and `help`, with the default
// `HelpFormatter` layout over a raw description. Help is never coloured.
import { repr } from "./py.ts";
import { wrap } from "./textwrap.ts";

/** A sub-command positional's nargs: the command name, then everything after it. */
export const PARSER = "A...";

type Nargs = null | 0 | "?" | "*" | typeof PARSER;

/** A namespace: each action's `dest` to its value. */
export type Namespace = Record<string, unknown>;

/** A `type` that rejects its input with this message, verbatim. */
export class ArgumentTypeError extends Error {}

/** The parser stopped: `-h`, `--version` or an error. The CLI writes `stdout` and `stderr` and exits `status`. */
export class ParserExit extends Error {
  readonly status: number;
  readonly stdout: string;
  readonly stderr: string;

  constructor(status: number, stdout: string, stderr: string) {
    super(stderr || stdout);
    this.status = status;
    this.stdout = stdout;
    this.stderr = stderr;
  }
}

class ArgumentError extends Error {
  constructor(action: Action | null, message: string) {
    super(action === null ? message : `argument ${actionName(action)}: ${message}`);
  }
}

/** A value converter, named as Python names the type in "invalid int value". */
export interface ValueType {
  name: string;
  convert(text: string): unknown;
}

export const INT: ValueType = {
  name: "int",
  convert(text) {
    const t = text.trim().replace(/_/g, "");
    if (!/^[+-]?\d+$/.test(t)) throw new RangeError();
    return Number.parseInt(t, 10);
  },
};

export const FLOAT: ValueType = {
  name: "float",
  convert(text) {
    const t = text.trim().toLowerCase();
    if (!/^[+-]?((\d[\d_]*)?\.?\d[\d_]*(e[+-]?\d+)?|\d[\d_]*\.|inf(inity)?|nan)$/.test(t)) throw new RangeError();
    const n = Number(t.replace(/_/g, "").replace(/inf(inity)?/, "Infinity").replace("nan", "NaN"));
    return n;
  },
};

export interface ArgumentOptions {
  action?: "store" | "store_true" | "append" | "version" | "help";
  dest?: string;
  nargs?: "?" | "*";
  const?: unknown;
  default?: unknown;
  type?: ValueType;
  choices?: readonly string[];
  metavar?: string;
  help?: string | null;
  version?: string;
}

interface Action {
  optionStrings: string[];
  dest: string;
  nargs: Nargs;
  kind: "store" | "store_true" | "append" | "version" | "help" | "parsers";
  const: unknown;
  default: unknown;
  type: ValueType | null;
  choices: readonly string[] | null;
  metavar: string | null;
  help: string | null;
  required: boolean;
  version: string | null;
  /** A sub-command action's parsers, and their help lines in order. */
  parsers: Map<string, ArgumentParser> | null;
  subactions: Action[];
}

function actionName(action: Action): string {
  if (action.optionStrings.length > 0) return action.optionStrings.join("/");
  if (action.metavar !== null) return action.metavar;
  return action.dest;
}

function nargsPattern(action: Action): string {
  const option = action.optionStrings.length > 0;
  switch (action.nargs) {
    case null: return option ? "(A)" : "(-*A-*)";
    case 0: return option ? "()" : "(-*)";
    case "?": return option ? "(A?)" : "(-*A?-*)";
    case "*": return option ? "(A*)" : "(-*[A-]*)";
    default: return option ? "(A[AO]*)" : "(-*A[-AO]*)";
  }
}

/** The terminal width help wraps to, as Python finds it: `$COLUMNS`, the terminal, else 80. */
function terminalColumns(): number {
  const proc = (globalThis as { process?: { env: Record<string, string | undefined>; stdout?: { isTTY?: boolean; columns?: number } } }).process;
  const env = Number.parseInt(proc?.env["COLUMNS"] ?? "", 10);
  if (env > 0) return env;
  if (proc?.stdout?.isTTY && proc.stdout.columns) return proc.stdout.columns;
  return 80;
}

export interface ParserOptions {
  prog: string;
  /** Printed as given (`RawDescriptionHelpFormatter`). */
  description?: string | null;
  addHelp?: boolean;
}

/** One command's options and positionals, with argparse's parsing and help. */
export class ArgumentParser {
  readonly prog: string;
  readonly description: string | null;
  readonly actions: Action[] = [];
  private readonly defaults: Namespace = {};
  private readonly optionActions = new Map<string, Action>();

  constructor({ prog, description = null, addHelp = true }: ParserOptions) {
    this.prog = prog;
    this.description = description;
    if (addHelp) this.addArgument(["-h", "--help"], { action: "help", help: "show this help message and exit" });
  }

  /** `add_argument`: option strings (`-x`, `--xx`) or one positional name. */
  addArgument(names: readonly string[], options: ArgumentOptions = {}): void {
    const kind = options.action ?? "store";
    const isOption = names[0]!.startsWith("-");
    let dest = options.dest;
    if (dest === undefined) {
      if (!isOption) dest = names[0]!;
      else {
        const long = names.find((n) => n.startsWith("--")) ?? names[0]!;
        dest = long.replace(/^-+/, "").replace(/-/g, "_");
      }
    }
    const zero = kind === "store_true" || kind === "version" || kind === "help";
    const action: Action = {
      optionStrings: isOption ? [...names] : [],
      dest,
      nargs: zero ? 0 : options.nargs ?? null,
      kind,
      const: kind === "store_true" ? true : options.const ?? null,
      default: options.default !== undefined ? options.default : kind === "store_true" ? false : null,
      type: options.type ?? null,
      choices: options.choices ?? null,
      metavar: options.metavar ?? null,
      help: options.help ?? null,
      required: !isOption && (options.nargs === undefined),
      version: options.version ?? null,
      parsers: null,
      subactions: [],
    };
    if (kind === "help" || kind === "version") action.default = SUPPRESS;
    if (kind === "version" && options.help === undefined) action.help = "show program's version number and exit";
    this.actions.push(action);
    for (const name of action.optionStrings) this.optionActions.set(name, action);
  }

  /** `add_subparsers(dest=...)`; returns a function adding one sub-command parser. */
  addSubparsers(dest: string): (name: string, options: { help: string; description: string }) => ArgumentParser {
    const action: Action = {
      optionStrings: [], dest, nargs: PARSER, kind: "parsers", const: null, default: null, type: null, choices: null,
      metavar: null, help: null, required: false, version: null, parsers: new Map(), subactions: [],
    };
    this.actions.push(action);
    return (name, { help, description }) => {
      const parser = new ArgumentParser({ prog: `${this.prog} ${name}`, description });
      action.parsers!.set(name, parser);
      action.subactions.push({
        optionStrings: [], dest: name, nargs: null, kind: "store", const: null, default: null, type: null, choices: null,
        metavar: name, help, required: false, version: null, parsers: null, subactions: [],
      });
      return parser;
    };
  }

  /** Every sub-command's parser, by name. */
  subparsers(): Map<string, ArgumentParser> {
    return this.actions.find((a) => a.parsers !== null)?.parsers ?? new Map();
  }

  setDefaults(values: Namespace): void {
    Object.assign(this.defaults, values);
  }

  /** `parse_args`: the namespace, or a `ParserExit` thrown for help, the version or an error. */
  parseArgs(args: readonly string[]): Namespace {
    const [namespace, extras] = this.parseKnownArgs(args);
    if (extras.length > 0) this.error(`unrecognized arguments: ${extras.join(" ")}`);
    return namespace;
  }

  parseKnownArgs(args: readonly string[], namespace: Namespace = {}): [Namespace, string[]] {
    for (const action of this.actions) {
      if (!(action.dest in namespace) && action.default !== SUPPRESS) namespace[action.dest] = action.default;
    }
    for (const [dest, value] of Object.entries(this.defaults)) if (!(dest in namespace)) namespace[dest] = value;
    let extras: string[];
    try {
      extras = this.parse([...args], namespace);
    } catch (error) {
      if (error instanceof ArgumentError) this.error(error.message);
      throw error;
    }
    const unrecognized = namespace[UNRECOGNIZED] as string[] | undefined;
    if (unrecognized !== undefined) {
      extras.push(...unrecognized);
      delete namespace[UNRECOGNIZED];
    }
    return [namespace, extras];
  }

  /** `error`: the usage and `<prog>: error: <message>` on stderr, status 2. */
  error(message: string): never {
    throw new ParserExit(2, "", `${this.formatUsage()}${this.prog}: error: ${message}\n`);
  }

  // -- parsing --

  private parseOptional(arg: string): [Action | null, string, string | null][] | null {
    if (!arg || arg[0] !== "-") return null;
    const exact = this.optionActions.get(arg);
    if (exact !== undefined) return [[exact, arg, null]];
    if (arg.length === 1) return null;
    const eq = arg.indexOf("=");
    if (eq >= 0) {
      const found = this.optionActions.get(arg.slice(0, eq));
      if (found !== undefined) return [[found, arg.slice(0, eq), arg.slice(eq + 1)]];
    }
    const tuples = this.optionTuples(arg);
    if (tuples.length > 0) return tuples;
    if (/^-\d+$|^-\d*\.\d+$/.test(arg)) return null;
    if (arg.includes(" ")) return null;
    return [[null, arg, null]];
  }

  private optionTuples(option: string): [Action, string, string | null][] {
    const out: [Action, string, string | null][] = [];
    const eq = option.indexOf("=");
    const prefix = eq >= 0 ? option.slice(0, eq) : option;
    const explicit = eq >= 0 ? option.slice(eq + 1) : null;
    if (option[1] === "-") {
      for (const [name, action] of this.optionActions) if (name.startsWith(prefix)) out.push([action, name, explicit]);
    } else {
      const short = option.slice(0, 2), shortExplicit = option.slice(2);
      for (const [name, action] of this.optionActions) {
        if (name === short) out.push([action, name, shortExplicit]);
        else if (name.startsWith(prefix)) out.push([action, name, explicit]);
      }
    }
    return out;
  }

  private parse(argStrings: string[], namespace: Namespace): string[] {
    const optionIndices = new Map<number, [Action | null, string, string | null][]>();
    let pattern = "";
    for (let i = 0; i < argStrings.length; i++) {
      if (argStrings[i] === "--") {
        pattern += "-" + "A".repeat(argStrings.length - i - 1);
        break;
      }
      const tuples = this.parseOptional(argStrings[i]!);
      if (tuples === null) pattern += "A";
      else {
        optionIndices.set(i, tuples);
        pattern += "O";
      }
    }

    const seen = new Set<Action>();
    const takeAction = (action: Action, strings: string[], optionString: string | null = null): void => {
      seen.add(action);
      this.act(action, namespace, this.values(action, strings), optionString);
    };

    const extras: string[] = [];
    const consumeOptional = (start: number): number => {
      const tuples = optionIndices.get(start)!;
      if (tuples.length > 1) {
        throw new ArgumentError(null, `ambiguous option: ${argStrings[start]} could match ${tuples.map((t) => t[1]).join(", ")}`);
      }
      let [action, optionString, explicit] = tuples[0]!;
      const pending: [Action, string[], string][] = [];
      let stop: number;
      for (;;) {
        if (action === null) {
          extras.push(argStrings[start]!);
          return start + 1;
        }
        if (explicit !== null) {
          const count = this.matchArgument(action, "A");
          if (count === 0 && optionString[1] !== "-" && explicit !== "") {
            pending.push([action, [], optionString]);
            const next = "-" + explicit[0]!;
            const found = this.optionActions.get(next);
            if (found === undefined) {
              extras.push("-" + explicit);
              stop = start + 1;
              break;
            }
            action = found;
            optionString = next;
            explicit = explicit.slice(1) || null;
            if (explicit !== null && explicit[0] === "=") explicit = explicit.slice(1);
          } else if (count === 1) {
            stop = start + 1;
            pending.push([action, [explicit], optionString]);
            break;
          } else {
            throw new ArgumentError(action, `ignored explicit argument ${repr(explicit)}`);
          }
        } else {
          const from = start + 1;
          const count = this.matchArgument(action, pattern.slice(from));
          stop = from + count;
          pending.push([action, argStrings.slice(from, stop), optionString]);
          break;
        }
      }
      for (const [a, args, option] of pending) takeAction(a, args, option);
      return stop;
    };

    const positionals = this.actions.filter((a) => a.optionStrings.length === 0);
    const consumePositionals = (start: number): number => {
      const counts = this.matchPartial(positionals, pattern.slice(start));
      counts.forEach((count, i) => {
        const action = positionals[i]!;
        const args = argStrings.slice(start, start + count);
        if (action.nargs === PARSER) {
          if (pattern[start] === "-") args.splice(args.indexOf("--"), 1);
        } else if (pattern.slice(start, start + count).includes("-")) {
          args.splice(args.indexOf("--"), 1);
        }
        start += count;
        takeAction(action, args);
      });
      positionals.splice(0, counts.length);
      return start;
    };

    let start = 0;
    const maxOption = optionIndices.size > 0 ? Math.max(...optionIndices.keys()) : -1;
    while (start <= maxOption) {
      let next = start;
      while (next <= maxOption && !optionIndices.has(next)) next++;
      if (start !== next) {
        const end = consumePositionals(start);
        if (end > start) {
          start = end;
          continue;
        }
        start = end;
      }
      if (!optionIndices.has(start)) {
        extras.push(...argStrings.slice(start, next));
        start = next;
      }
      start = consumeOptional(start);
    }
    const stop = consumePositionals(start);
    extras.push(...argStrings.slice(stop));

    const missing = this.actions.filter((a) => !seen.has(a) && a.required).map(actionName);
    if (missing.length > 0) throw new ArgumentError(null, `the following arguments are required: ${missing.join(", ")}`);
    return extras;
  }

  private matchArgument(action: Action, pattern: string): number {
    const match = new RegExp("^" + nargsPattern(action)).exec(pattern);
    if (match === null) {
      const message = action.nargs === null ? "expected one argument"
        : action.nargs === "?" ? "expected at most one argument" : "expected at least one argument";
      throw new ArgumentError(action, message);
    }
    return match[1]!.length;
  }

  private matchPartial(actions: readonly Action[], pattern: string): number[] {
    for (let i = actions.length; i > 0; i--) {
      const match = new RegExp("^" + actions.slice(0, i).map(nargsPattern).join("")).exec(pattern);
      if (match === null) continue;
      const result = match.slice(1).map((g) => g!.length);
      if (match[0].length < pattern.length && pattern[match[0].length] === "O") {
        while (result.length > 0 && result[result.length - 1] === 0) result.pop();
      }
      return result;
    }
    return [];
  }

  private value(action: Action, text: string): unknown {
    if (action.type === null) return text;
    try {
      return action.type.convert(text);
    } catch (error) {
      if (error instanceof ArgumentTypeError) throw new ArgumentError(action, error.message);
      throw new ArgumentError(action, `invalid ${action.type.name} value: ${repr(text)}`);
    }
  }

  private check(action: Action, value: unknown): void {
    const choices = action.parsers !== null ? [...action.parsers.keys()] : action.choices;
    if (choices === null || choices.includes(value as string)) return;
    throw new ArgumentError(action, `invalid choice: ${repr(String(value))} (choose from ${choices.join(", ")})`);
  }

  private values(action: Action, strings: string[]): unknown {
    if (strings.length === 0 && action.nargs === "?") {
      const value = action.optionStrings.length > 0 ? action.const : action.default;
      return typeof value === "string" ? this.value(action, value) : value;
    }
    if (strings.length === 0 && action.nargs === "*" && action.optionStrings.length === 0) {
      return action.default !== null ? action.default : [];
    }
    if (strings.length === 1 && (action.nargs === null || action.nargs === "?")) {
      const value = this.value(action, strings[0]!);
      this.check(action, value);
      return value;
    }
    if (action.nargs === PARSER) {
      const values = strings.map((s) => this.value(action, s));
      this.check(action, values[0]);
      return values;
    }
    const values = strings.map((s) => this.value(action, s));
    for (const v of values) this.check(action, v);
    return values;
  }

  private act(action: Action, namespace: Namespace, values: unknown, _optionString: string | null): void {
    switch (action.kind) {
      case "store": namespace[action.dest] = values; return;
      case "store_true": namespace[action.dest] = true; return;
      case "append": namespace[action.dest] = [...((namespace[action.dest] as unknown[] | null) ?? []), values]; return;
      case "help": throw new ParserExit(0, this.formatHelp(), "");
      case "version": throw new ParserExit(0, `${action.version}\n`, "");
      case "parsers": {
        const [name, ...rest] = values as string[];
        namespace[action.dest] = name;
        const [sub, subExtras] = action.parsers!.get(name!)!.parseKnownArgs(rest);
        Object.assign(namespace, sub);
        if (subExtras.length > 0) namespace[UNRECOGNIZED] = [...((namespace[UNRECOGNIZED] as string[]) ?? []), ...subExtras];
        return;
      }
    }
  }

  // -- help --

  private metavar(action: Action, fallback: string): string {
    if (action.metavar !== null) return action.metavar;
    if (action.parsers !== null) return `{${[...action.parsers.keys()].join(",")}}`;
    if (action.choices !== null) return `{${action.choices.join(",")}}`;
    return fallback;
  }

  private formatArgs(action: Action, fallback: string): string {
    const m = this.metavar(action, fallback);
    switch (action.nargs) {
      case null: return m;
      case "?": return `[${m}]`;
      case "*": return `[${m} ...]`;
      case 0: return "";
      default: return `${m} ...`;
    }
  }

  private invocation(action: Action): string {
    if (action.optionStrings.length === 0) return this.metavar(action, action.dest);
    if (action.nargs === 0) return action.optionStrings.join(", ");
    return `${action.optionStrings.join(", ")} ${this.formatArgs(action, action.dest.toUpperCase())}`;
  }

  private usageParts(): [string[], string[]] {
    const optionals: string[] = [], positionals: string[] = [];
    for (const action of this.actions) {
      if (action.optionStrings.length === 0) {
        positionals.push(this.formatArgs(action, action.dest));
      } else {
        const option = action.optionStrings[0]!;
        const part = action.nargs === 0 ? option : `${option} ${this.formatArgs(action, action.dest.toUpperCase())}`;
        optionals.push(action.required ? part : `[${part}]`);
      }
    }
    return [optionals, positionals];
  }

  private usage(width: number): string {
    const prefix = "usage: ";
    const prog = this.prog;
    const [optParts, posParts] = this.usageParts();
    let usage = [prog, ...optParts, ...posParts].join(" ");
    if (prefix.length + usage.length > width) {
      const lines = (parts: string[], indent: string, first: string | null = null): string[] => {
        const out: string[] = [];
        let line: string[] = [];
        let length = first !== null ? first.length - 1 : indent.length - 1;
        for (const part of parts) {
          if (length + 1 + part.length > width && line.length > 0) {
            out.push(indent + line.join(" "));
            line = [];
            length = indent.length - 1;
          }
          line.push(part);
          length += part.length + 1;
        }
        if (line.length > 0) out.push(indent + line.join(" "));
        if (first !== null) out[0] = out[0]!.slice(indent.length);
        return out;
      };
      let result: string[];
      if (prefix.length + prog.length <= 0.75 * width) {
        const indent = " ".repeat(prefix.length + prog.length + 1);
        if (optParts.length > 0) result = [...lines([prog, ...optParts], indent, prefix), ...lines(posParts, indent)];
        else if (posParts.length > 0) result = lines([prog, ...posParts], indent, prefix);
        else result = [prog];
      } else {
        const indent = " ".repeat(prefix.length);
        result = lines([...optParts, ...posParts], indent);
        if (result.length > 1) result = [...lines(optParts, indent), ...lines(posParts, indent)];
        result = [prog, ...result];
      }
      usage = result.join("\n");
    }
    return `${prefix}${usage}\n\n`;
  }

  formatUsage(): string {
    return finish(this.usage(terminalColumns() - 2));
  }

  formatHelp(): string {
    const width = terminalColumns() - 2;
    const maxHelpPosition = Math.min(24, Math.max(width - 20, 4));
    const groups: [string, Action[]][] = [
      ["positional arguments", this.actions.filter((a) => a.optionStrings.length === 0)],
      ["options", this.actions.filter((a) => a.optionStrings.length > 0)],
    ];
    let maxLength = 0;
    for (const [, actions] of groups) {
      for (const action of actions) {
        maxLength = Math.max(maxLength, this.invocation(action).length + 2);
        for (const sub of action.subactions) maxLength = Math.max(maxLength, this.invocation(sub).length + 4);
      }
    }
    const helpPosition = Math.min(maxLength + 2, maxHelpPosition);
    const helpWidth = Math.max(width - helpPosition, 11);
    const formatAction = (action: Action, indent: number): string => {
      const actionWidth = helpPosition - indent - 2;
      const header = this.invocation(action);
      const parts: string[] = [];
      let indentFirst = 0;
      if (!action.help) parts.push(`${" ".repeat(indent)}${header}\n`);
      else if (header.length <= actionWidth) parts.push(`${" ".repeat(indent)}${header.padEnd(actionWidth)}  `);
      else {
        parts.push(`${" ".repeat(indent)}${header}\n`);
        indentFirst = helpPosition;
      }
      if (action.help && action.help.trim()) {
        const lines = wrap(action.help.replace(/[ \t\n\r\f\v]+/g, " ").trim(), helpWidth);
        parts.push(`${" ".repeat(indentFirst)}${lines[0]}\n`);
        for (const line of lines.slice(1)) parts.push(`${" ".repeat(helpPosition)}${line}\n`);
      } else if (!parts[0]!.endsWith("\n")) parts.push("\n");
      for (const sub of action.subactions) parts.push(formatAction(sub, indent + 2));
      return parts.join("");
    };
    let text = this.usage(width);
    if (this.description) text += this.description + "\n\n";
    for (const [heading, actions] of groups) {
      if (actions.length === 0) continue;
      text += `\n${heading}:\n${actions.map((a) => formatAction(a, 2)).join("")}\n`;
    }
    return finish(text);
  }
}

const SUPPRESS = Symbol("SUPPRESS");
const UNRECOGNIZED = "_unrecognized_args";

function finish(text: string): string {
  return text.replace(/\n\n\n+/g, "\n\n").replace(/^\n+|\n+$/g, "") + "\n";
}
