// Format specs: what they compile to, and how wide they can get. Port of
// wfb/formatting.py.
//
// ADR 0005 §4: `format:` uses Python-style specs. Two jobs come out of one
// declaration: the Monkey C that renders the value, and the widest
// plausible rendering, which makes "does this label overflow its slot?" a
// static check and decides which glyphs a subsetted font must contain.
//
// Time specs use strftime codes, plus `%h`: the hour the user has asked to
// see, 24-hour zero-padded or 12-hour unpadded, following
// `DeviceSettings.is24Hour`. The same codes on a Number or Float read the
// value as seconds: a duration, or a time of day. The largest unit a spec
// uses carries the whole total, every smaller unit wraps at the next one
// up, and a `-` flag drops the zero-padding.
import { isNumeric, type Source, type Type } from "./catalog.ts";
import { stringLiteral } from "./mcsource.ts";
import { floatRepr, formatFixed, isNumber, num, repr, roundHalfEven } from "./py.ts";
import { PyFloat } from "./edit/yaml.ts";

const FIELD = /\{(?:(?<unit>unit)|:(?<spec>[^}]*))?\}/g;
const NUMERIC_SPEC = /^(?<zero>0)?(?<width>\d+)?(?:\.(?<precision>\d+))?(?<kind>[dfs])$/;

export class FormatError extends Error {}

export interface LiteralPart { kind: "literal"; text: string }
export interface FieldPart { kind: "field"; spec: string }
export interface UnitField { kind: "unit" }
export type Part = LiteralPart | FieldPart | UnitField;

/** One strftime code, or literal text between codes. */
export interface TimePart { code: string | null; text: string }

/** The generated reader locals a strftime code's Monkey C reads off. */
export interface Readers { clock: string; settings: string; date: string; date_short: string }

export const DEFAULT_READERS: Readers = { clock: "clock", settings: "settings", date: "date", date_short: "dateShort" };

type Values = ReadonlyMap<string, unknown>;

/** One strftime code, its Monkey C and its host rendering side by side. */
export interface Code {
  description: string;
  /** The widest string the code can produce. */
  widest: string;
  emit: (r: Readers) => string;
  render: (v: Values) => string;
  /** A catalogue path the code reads beyond the value's own reader. */
  extra_path: string | null;
}

/** Python's `format(n, "<flags>d")`: zero padding goes after the sign. */
function formatInt(n: number, flags: string): string {
  const zero = flags.startsWith("0");
  const width = Number(flags.replace(/^0/, "") || 0);
  const text = String(Math.abs(n));
  const sign = n < 0 ? "-" : "";
  if (zero) return sign + text.padStart(Math.max(0, width - sign.length), "0");
  return (sign + text).padStart(width, " ");
}

/** Python's `format(x, "<flags>.<p>f")`. */
function formatFloatSpec(x: number, flags: string, precision: number): string {
  const zero = flags.startsWith("0");
  const width = Number(flags.replace(/^0/, "") || 0);
  const text = formatFixed(x, precision);
  if (!zero) return text.padStart(width, " ");
  const negative = text.startsWith("-");
  const body = negative ? text.slice(1) : text;
  return (negative ? "-" : "") + body.padStart(Math.max(0, width - (negative ? 1 : 0)), "0");
}

const pct = (): Code => ({ description: "a literal percent sign", widest: "%", emit: () => "\"%\"", render: () => "%", extra_path: null });
const int = (v: unknown, fallback: number): number => Math.trunc(Number(v ?? fallback));
const hour = (v: Values): number => int(v.get("time.hour"), 10);
const hour12 = (v: Values): number => (hour(v) % 12) || 12;
const day = (v: Values): number => int(v.get("date.day"), 3);
const year = (v: Values): number => int(v.get("date.year"), 2026);
const pyTruthy = (v: unknown): boolean => !(v === undefined ? false : v === null || v === false || v === 0 || v === "");
const valueStr = (v: unknown): string => (v === true ? "True" : v === false ? "False" : v === null ? "None" : String(v));

const code = (description: string, widest: string, emit: (r: Readers) => string, render: (v: Values) => string,
  extra_path: string | null = null): Code => ({ description, widest, emit, render, extra_path });

/** strftime codes for a clock reading. */
export const TIME_CODES: ReadonlyMap<string, Code> = new Map([
  ["H", code("hour, 24-hour, zero-padded", "23", (r) => `${r.clock}.hour.format("%02d")`, (v) => formatInt(hour(v), "02"))],
  ["I", code("hour, 12-hour, zero-padded", "12", (r) => `WfbTime.hour12(${r.clock}.hour).format("%02d")`, (v) => formatInt(hour12(v), "02"))],
  ["l", code("hour, 12-hour, unpadded", "12", (r) => `WfbTime.hour12(${r.clock}.hour).format("%d")`, (v) => String(hour12(v)))],
  // `WfbTime.displayHour`: zero-padded 24-hour, or unpadded 12-hour, following `DeviceSettings.is24Hour`.
  ["h", code("hour, following the device's 12/24-hour setting", "23", (r) => `WfbTime.displayHour(${r.clock}.hour, ${r.settings}.is24Hour)`,
    (v) => (pyTruthy(v.has("device.is_24_hour") ? v.get("device.is_24_hour") : true) ? formatInt(hour(v), "02") : String(hour12(v))),
    "device.is_24_hour")],
  ["M", code("minute, zero-padded", "59", (r) => `${r.clock}.min.format("%02d")`, (v) => formatInt(int(v.get("time.minute"), 9), "02"))],
  ["S", code("second, zero-padded", "59", (r) => `${r.clock}.sec.format("%02d")`, (v) => formatInt(int(v.get("time.second"), 0), "02"))],
  ["p", code("AM or PM", "AM", (r) => `WfbTime.meridiem(${r.clock}.hour)`, (v) => (hour(v) < 12 ? "AM" : "PM"))],
  ["%", pct()],
]);

/** strftime codes for a date reading. Widths assume English: the weekday and month arrive localised. */
export const DATE_CODES: ReadonlyMap<string, Code> = new Map([
  ["a", code("abbreviated weekday, e.g. Thu", "Wed", (r) => `${r.date}.day_of_week`, (v) => valueStr(v.get("date.day_of_week") ?? "Wed"))],
  ["d", code("day of the month, zero-padded", "30", (r) => `${r.date}.day.format("%02d")`, (v) => formatInt(day(v), "02"))],
  ["e", code("day of the month, unpadded", "30", (r) => `${r.date}.day.format("%d")`, (v) => String(day(v)))],
  ["b", code("abbreviated month, e.g. Sep", "Sep", (r) => `${r.date}.month`, (v) => valueStr(v.get("date.month") ?? "Sep"))],
  // FORMAT_MEDIUM's `month` is a localised String: the Number month exists only under FORMAT_SHORT.
  ["m", code("month number, zero-padded", "12", (r) => `(${r.date_short}.month as Number).format("%02d")`,
    (v) => formatInt(int(v.get("date.month_number"), 9), "02"), "date.weekday")],
  ["Y", code("four-digit year", "2026", (r) => `${r.date}.year.format("%04d")`, (v) => formatInt(year(v), "04"))],
  ["y", code("two-digit year", "26", (r) => `(${r.date}.year % 100).format("%02d")`, (v) => formatInt(((year(v) % 100) + 100) % 100, "02"))],
  ["%", pct()],
]);

/** One strftime code read off a number of seconds. */
export interface DurationCode {
  description: string;
  /** Seconds per unit: the largest in a spec leads. */
  unit: number;
  widest_leading: string;
  widest_wrapped: string;
  emit: (valueCode: string, r: Readers, lead: boolean) => string;
  render: (seconds: number, values: Values, lead: boolean) => string;
  /** A time-of-day code: always wraps at 24 hours, and a spec using one carries no sign. */
  clock: boolean;
  extra_path: string | null;
}

const partCode = (valueCode: string, unit: number, wrap: number): string => `WfbTime.durationPart(${valueCode}, ${unit}, ${wrap})`;
const part = (seconds: number, unit: number, wrap: number): number => {
  const whole = Math.floor(seconds / unit);
  return wrap ? whole % wrap : whole;
};

function field(unit: number, wrap: number, pad: boolean, what: string, widestLeading: string): DurationCode {
  const fmt = pad ? "%02d" : "%d";
  return {
    description: `${what}${pad ? "" : ", unpadded"} -- the whole total when it is the largest unit`,
    unit, widest_leading: widestLeading, widest_wrapped: wrap === 60 ? "59" : "23",
    emit: (v, _r, lead) => `${partCode(v, unit, lead ? 0 : wrap)}.format("${fmt}")`,
    render: (n, _values, lead) => formatInt(part(n, unit, lead ? 0 : wrap), pad ? "02" : ""),
    clock: false, extra_path: null,
  };
}

const clockHourCode = (v: string): string => partCode(v, 3600, 24);
const clockHour = (n: number): number => part(n, 3600, 24);

/** strftime codes for a Number or Float of seconds: a duration, or a time of day. */
export const DURATION_CODES: ReadonlyMap<string, DurationCode> = new Map([
  ["H", field(3600, 24, true, "hours", "88")],
  ["-H", field(3600, 24, false, "hours", "88")],
  ["M", field(60, 60, true, "minutes", "88")],
  ["-M", field(60, 60, false, "minutes", "88")],
  ["S", field(1, 60, true, "seconds", "88888")],
  ["-S", field(1, 60, false, "seconds", "88888")],
  ["h", {
    description: "hour of the day, following the device's 12/24-hour setting", unit: 3600, widest_leading: "23", widest_wrapped: "23",
    emit: (v, r) => `WfbTime.displayHour(${clockHourCode(v)}, ${r.settings}.is24Hour)`,
    render: (n, values) => (pyTruthy(values.has("device.is_24_hour") ? values.get("device.is_24_hour") : true)
      ? formatInt(clockHour(n), "02") : String((clockHour(n) % 12) || 12)),
    clock: true, extra_path: "device.is_24_hour",
  }],
  ["I", {
    description: "hour of the day, 12-hour, zero-padded", unit: 3600, widest_leading: "12", widest_wrapped: "12",
    emit: (v) => `WfbTime.hour12(${clockHourCode(v)}).format("%02d")`,
    render: (n) => formatInt((clockHour(n) % 12) || 12, "02"), clock: true, extra_path: null,
  }],
  ["l", {
    description: "hour of the day, 12-hour, unpadded", unit: 3600, widest_leading: "12", widest_wrapped: "12",
    emit: (v) => `WfbTime.hour12(${clockHourCode(v)}).format("%d")`,
    render: (n) => String((clockHour(n) % 12) || 12), clock: true, extra_path: null,
  }],
  ["p", {
    description: "AM or PM of the time of day", unit: 3600, widest_leading: "AM", widest_wrapped: "AM",
    emit: (v) => `WfbTime.meridiem(${clockHourCode(v)})`,
    render: (n) => (clockHour(n) < 12 ? "AM" : "PM"), clock: true, extra_path: null,
  }],
  ["%", {
    description: "a literal percent sign", unit: 0, widest_leading: "%", widest_wrapped: "%",
    emit: () => "\"%\"", render: () => "%", clock: false, extra_path: null,
  }],
]);

/** Split a format string into literals and fields. */
export function parse(spec: string): Part[] {
  const parts: Part[] = [];
  let pos = 0;
  for (const m of spec.matchAll(FIELD)) {
    if (m.index > pos) parts.push({ kind: "literal", text: spec.slice(pos, m.index) });
    parts.push(m.groups!["unit"] ? { kind: "unit" } : { kind: "field", spec: m.groups!["spec"] ?? "" });
    pos = m.index + m[0].length;
  }
  if (pos < spec.length) parts.push({ kind: "literal", text: spec.slice(pos) });
  if (!parts.some((p) => p.kind === "field")) throw new FormatError(`${repr(spec)} has no placeholder -- a fixed string needs no format`);
  return parts;
}

/** Split a strftime-style field spec into codes and literal text; a `-` flag is part of the code it modifies. */
export function parseTime(spec: string, codes: ReadonlyMap<string, unknown> = TIME_CODES): TimePart[] {
  const what = codes === DATE_CODES ? "date" : codes === DURATION_CODES ? "duration" : "time";
  const chars = Array.from(spec);
  const parts: TimePart[] = [];
  let buffer = "";
  let index = 0;
  while (index < chars.length) {
    const char = chars[index]!;
    if (char === "%" && index + 1 < chars.length) {
      let c = chars[index + 1]!;
      if (c === "-" && index + 2 < chars.length) c = chars[index + 1]! + chars[index + 2]!;
      if (!codes.has(c)) {
        throw new FormatError(`unknown ${what} code %${c} -- supported: ${[...codes.keys()].map((k) => `%${k}`).join(", ")}`);
      }
      if (buffer) { parts.push({ code: null, text: buffer }); buffer = ""; }
      if (c === "%") buffer = "%";
      else parts.push({ code: c, text: "" });
      index += 1 + Array.from(c).length;
      continue;
    }
    buffer += char;
    index++;
  }
  if (buffer) parts.push({ code: null, text: buffer });
  return parts;
}

/** Does this format use strftime codes? Only the field is inspected: a `%` in the literal text is punctuation. */
export function isTimeSpec(spec: string): boolean {
  let parts: Part[];
  try {
    parts = parse(spec);
  } catch (error) {
    if (error instanceof FormatError) return false;
    throw error;
  }
  return parts.some((p) => p.kind === "field" && p.spec.includes("%"));
}

/** Is this a duration format: strftime codes on a Number or Float of seconds? */
export function isDuration(spec: string, valueType: Type): boolean {
  return isNumeric(valueType) && isTimeSpec(spec);
}

function durationField(spec: string): [TimePart[], number, boolean] {
  const parts = parseTime(spec, DURATION_CODES);
  const rows = parts.filter((p) => p.code !== null).map((p) => DURATION_CODES.get(p.code!)!);
  const leading = rows.reduce((m, row) => Math.max(m, row.unit), 0);
  return [parts, leading, !rows.some((row) => row.clock)];
}

const leads = (row: DurationCode, leading: number): boolean => !row.clock && row.unit === leading;

/** A whole TIME/DATE spec as one run of codes and literal text, every field parsed against its type's table. */
export function strftimeParts(spec: string, valueType: Type): [TimePart[], ReadonlyMap<string, Code>] {
  const codes = valueType === "date" ? DATE_CODES : TIME_CODES;
  const parts: TimePart[] = [];
  for (const p of parse(spec)) {
    if (p.kind === "literal") parts.push({ code: null, text: p.text });
    else if (p.kind === "unit") throw new FormatError("{unit} needs 'units:' on the element");
    else parts.push(...parseTime(p.spec, codes));
  }
  return [parts, codes];
}

/** A numeric field spec as `[kind, flags, precision]`, shared by the device's code and the preview. */
function numericSpec(spec: string): [string, string, string | null] {
  const m = NUMERIC_SPEC.exec(spec);
  if (!m) throw new FormatError(`${repr(spec)} is not a supported format spec -- after the ':' use d, 02d or .1f, or no spec at all`);
  const g = m.groups!;
  return [g["kind"]!, `${g["zero"] ? "0" : ""}${g["width"] ?? ""}`, g["precision"] ?? null];
}

// -- Monkey C ---------------------------------------------------------------------------

export function hasUnitField(spec: string): boolean {
  try {
    return parse(spec).some((p) => p.kind === "unit");
  } catch (error) {
    if (error instanceof FormatError) return false;
    throw error;
  }
}

/** Compile a format spec to a Monkey C String expression; `unitCode` is what a `{unit}` field compiles to. */
export function emit(spec: string, valueCode: string, valueType: Type,
  { readers = DEFAULT_READERS, unitCode = null }: { readers?: Readers; unitCode?: string | null } = {}): string {
  if (isDuration(spec, valueType)) return emitDuration(spec, valueCode, readers, unitCode);
  if (valueType === "date" || isTimeSpec(spec)) {
    const [parts, codes] = strftimeParts(spec, valueType);
    const pieces = parts.map((p) => (p.code === null ? stringLiteral(p.text) : codes.get(p.code)!.emit(readers)));
    return pieces.length > 0 ? pieces.join(" + ") : "\"\"";
  }
  return parse(spec).map((p) => {
    if (p.kind === "literal") return stringLiteral(p.text);
    if (p.kind === "unit") {
      if (unitCode === null) throw new FormatError("{unit} needs 'units:' on the element");
      return `(${unitCode})`;
    }
    return emitNumeric(p.spec, valueCode, valueType);
  }).join(" + ");
}

function emitDuration(spec: string, valueCode: string, readers: Readers, unitCode: string | null): string {
  const pieces: string[] = [];
  for (const p of parse(spec)) {
    if (p.kind === "literal") pieces.push(stringLiteral(p.text));
    else if (p.kind === "unit") {
      if (unitCode === null) throw new FormatError("{unit} needs 'units:' on the element");
      pieces.push(`(${unitCode})`);
    } else {
      const [parts, leading, signed] = durationField(p.spec);
      if (signed) pieces.push(`WfbTime.durationSign(${valueCode})`);
      for (const tp of parts) {
        if (tp.code === null) pieces.push(stringLiteral(tp.text));
        else {
          const row = DURATION_CODES.get(tp.code)!;
          pieces.push(row.emit(valueCode, readers, leads(row, leading)));
        }
      }
    }
  }
  return pieces.length > 0 ? pieces.join(" + ") : "\"\"";
}

function emitNumeric(spec: string, valueCode: string, valueType: Type): string {
  if (spec === "") return `${valueCode}.toString()`;
  const [kind, flags, precision] = numericSpec(spec);
  if (kind === "s") return `${valueCode}.toString()`;
  if (kind === "d") return `${valueType === "float" ? `${valueCode}.toNumber()` : valueCode}.format("%${flags}d")`;
  return `${valueCode}.format("%${flags}.${precision || 1}f")`;
}

/** Extra catalogue paths a strftime spec's own codes need read, beyond the value's own reader. */
export function extraPaths(spec: string, valueType: Type): string[] {
  let paths: (string | null)[];
  if (isDuration(spec, valueType)) {
    paths = parse(spec).filter((f): f is FieldPart => f.kind === "field")
      .flatMap((f) => parseTime(f.spec, DURATION_CODES))
      .filter((p) => p.code !== null).map((p) => DURATION_CODES.get(p.code!)!.extra_path);
  } else {
    const [parts, table] = strftimeParts(spec, valueType);
    paths = parts.filter((p) => p.code !== null).map((p) => table.get(p.code!)!.extra_path);
  }
  return [...new Set(paths.filter((p): p is string => p !== null))];
}

// -- the host rendering: what the preview shows ------------------------------------------

/** The host-side rendering of `spec` for `value`: what the preview draws in place of `emit`'s Monkey C. */
export function render(spec: string, value: unknown, valueType: Type, values: Values = new Map(), unitText: string | null = null): string {
  if (isDuration(spec, valueType)) return renderDuration(spec, value, values, unitText);
  if (valueType === "date" || valueType === "time") {
    const [parts, codes] = strftimeParts(spec, valueType);
    return parts.map((p) => (p.code === null ? p.text : codes.get(p.code)!.render(values))).join("");
  }
  let out = "";
  for (const p of parse(spec)) {
    if (p.kind === "literal") out += p.text;
    else if (p.kind === "unit") {
      if (unitText === null) throw new FormatError("{unit} needs 'units:' on the element");
      out += unitText;
    } else out += renderNumericField(p.spec, value);
  }
  return out;
}

function renderDuration(spec: string, value: unknown, values: Values, unitText: string | null): string {
  if (!isNumber(value)) throw new Error("a duration renders a number");
  const whole = Math.trunc(num(value));
  let out = "";
  for (const p of parse(spec)) {
    if (p.kind === "literal") out += p.text;
    else if (p.kind === "unit") {
      if (unitText === null) throw new FormatError("{unit} needs 'units:' on the element");
      out += unitText;
    } else {
      const [parts, leading, signed] = durationField(p.spec);
      if (signed && whole < 0) out += "-";
      for (const tp of parts) {
        if (tp.code === null) out += tp.text;
        else {
          const row = DURATION_CODES.get(tp.code)!;
          out += row.render(Math.abs(whole), values, leads(row, leading));
        }
      }
    }
  }
  return out;
}

/** Python's `str()` of a value a field shows: a float as its repr. */
function str(value: unknown): string {
  if (value instanceof PyFloat) return floatRepr(value.value);
  if (typeof value === "number" && !Number.isInteger(value)) return floatRepr(value);
  return valueStr(value);
}

function renderNumericField(spec: string, value: unknown): string {
  if (spec === "") return str(value);
  const [kind, flags, precision] = numericSpec(spec);
  if (kind === "s") return str(value);
  if (!isNumber(value)) throw new Error("a numeric spec renders a number");
  if (kind === "d") return formatInt(Math.trunc(num(value)), flags);
  return formatFloatSpec(num(value), flags, Number(precision || 1));
}

// -- static analysis: the widest rendering, and the glyph set -----------------------------

/** Known upper bounds, so the overflow lint is exact rather than guessed. */
const SOURCE_DIGITS: ReadonlyMap<string, number> = new Map([
  ["activity.steps", 5], ["activity.step_goal", 5], ["activity.calories", 5], ["activity.distance", 7],
  ["activity.floors_climbed", 3], ["activity.floors_climbed_goal", 3], ["activity.move_bar_level", 1],
  ["activity.active_minutes_week", 4], ["activity.active_minutes_week_goal", 4], ["heart_rate.current", 3],
  ["system.battery", 3], ["system.battery_in_days", 3], ["device.notification_count", 2], ["device.alarm_count", 2],
  ["time.hour", 2], ["time.minute", 2], ["time.second", 2],
]);

/** Used when the bound source has no documented range. */
export const DEFAULT_DIGITS = 5;

function maxDigits(source: Source | null, scale = 1.0): number {
  let digits = source === null ? DEFAULT_DIGITS : SOURCE_DIGITS.get(source.path) ?? DEFAULT_DIGITS;
  if (scale && scale !== 1.0) digits = Math.max(1, digits - Math.max(0, roundHalfEven(Math.log10(1.0 / scale))));
  return digits;
}

export function digitsAreKnown(source: Source | null): boolean {
  return source !== null && SOURCE_DIGITS.has(source.path);
}

/** The widest string this binding can plausibly render. */
export function widest(spec: string, source: Source | null, valueType: Type, scale = 1.0,
  { digits = null, unitWidest = "" }: { digits?: number | null; unitWidest?: string } = {}): string {
  if (isDuration(spec, valueType)) return widestDuration(spec, unitWidest);
  if (valueType === "date" || isTimeSpec(spec)) {
    const [parts, codes] = strftimeParts(spec, valueType);
    return parts.map((p) => (p.code === null ? p.text : codes.get(p.code)!.widest)).join("");
  }
  let out = "";
  for (const p of parse(spec)) {
    if (p.kind === "literal") { out += p.text; continue; }
    if (p.kind === "unit") { out += unitWidest; continue; }
    const m = p.spec ? NUMERIC_SPEC.exec(p.spec) : null;
    if (digits === null) digits = maxDigits(source, scale);
    if (m && m.groups!["kind"] === "f") {
      const precision = Number(m.groups!["precision"] || 1);
      // A zero precision prints no decimal point at all.
      out += "8".repeat(digits) + (precision ? "." + "8".repeat(precision) : "");
    } else {
      const width = m && m.groups!["width"] ? Number(m.groups!["width"]) : 0;
      out += "8".repeat(Math.max(digits, width));
    }
  }
  return out;
}

function widestDuration(spec: string, unitWidest: string): string {
  let out = "";
  for (const p of parse(spec)) {
    if (p.kind === "literal") out += p.text;
    else if (p.kind === "unit") out += unitWidest;
    else {
      const [parts, leading] = durationField(p.spec);
      for (const tp of parts) {
        if (tp.code === null) out += tp.text;
        else {
          const row = DURATION_CODES.get(tp.code)!;
          out += leads(row, leading) ? row.widest_leading : row.widest_wrapped;
        }
      }
    }
  }
  return out;
}

/** Every character this binding can render: the font's required subset. */
export function glyphs(spec: string, source: Source | null, valueType: Type, scale = 1.0,
  { digits = null, unitLabels = [] }: { digits?: number | null; unitLabels?: readonly string[] } = {}): Set<string> {
  const out = new Set(widest(spec, source, valueType, scale, { digits }));
  for (const label of unitLabels) for (const c of label) out.add(c);
  const add = (chars: string): void => { for (const c of chars) out.add(c); };
  if (valueType === "date") {
    // The weekday and month are localised strings chosen by the firmware: the full alphabet has to be present.
    add("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ");
    return out;
  }
  add("0123456789");
  if (isDuration(spec, valueType)) {
    for (const p of parse(spec)) {
      if (p.kind === "field") {
        const [parts, , signed] = durationField(p.spec);
        if (signed) out.add("-");
        if (parts.some((tp) => tp.code === "p")) add("AMP");
      }
    }
  } else if (isTimeSpec(spec)) {
    if (spec.includes("%p")) add("AMP");
  } else {
    for (const p of parse(spec)) {
      if (p.kind === "field") {
        out.add("-"); // a negative value is always possible
        if (p.spec.endsWith("f")) out.add(".");
      }
    }
  }
  return out;
}
