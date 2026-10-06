// The SDK's complication types, how a `data` element draws each one's
// reading, and a gauge's scale for each. The
// tables are `data/complications.json`, exported by tools/export_tables.py
// from the SDK's own Type table ($CIQ_SDK/doc/Toybox/Complications.html).
import data from "./data/complications.json" with { type: "json" };
import { Catalogue } from "./diagnostics.ts";
import { formatFixed, isInt, isNumber, num } from "./py.ts";
import { PyFloat } from "./edit/yaml.ts";

/** One `COMPLICATION_TYPE_*`: an `on_hold:` target, and the type behind a `complication.<name>` source. */
export interface ComplicationType {
  name: string;
  constant: string;
  since: string;
  value_type: "number" | "float" | "string";
  nullable: boolean;
  unit: string | null;
  doc: string;
}

export interface Scale {
  kind: "fixed" | "goal" | "heart_rate_zones" | "vo2max";
  source: string;
  minimum: number;
  maximum: number;
  goal: string | null;
  bands: number[];
}

export const TYPES: Catalogue<ComplicationType> = new Catalogue(Object.entries(data.types as Record<string, ComplicationType>));
/** The API level `Complications.exitTo` itself needs. */
export const EXIT_TO_API_LEVEL: string = data.exit_to_api_level;
/** The permission `Toybox.Complications` is gated by, available to a watch face. */
export const EXIT_TO_PERMISSION: string = data.exit_to_permission;
export const UNIT_SUFFIX: ReadonlyMap<string, string> = new Map(Object.entries(data.unit_suffix));
/** The groups the editor lists complication types under, in that order. */
export const CATEGORIES: readonly string[] = data.categories;
export const PRESENTATION: ReadonlyMap<string, readonly [string, string]> =
  new Map(Object.entries(data.presentation as unknown as Record<string, [string, string]>));
/** The longest reading `short: true` aims for, in characters. */
export const SHORT_LENGTH: number = data.short_length;
export const READING: ReadonlyMap<string, string> = new Map(Object.entries(data.reading));
export const COUNT_UNIT: ReadonlyMap<string, string> = new Map(Object.entries(data.count_unit));
export const WORDED: ReadonlySet<string> = new Set(data.worded);
export const WEATHER_CONDITION_TEXT: ReadonlyMap<number, readonly [string, string]> =
  new Map(Object.entries(data.weather_condition_text as unknown as Record<string, [string, string]>).map(([k, v]) => [Number(k), v]));
export const UNKNOWN_CONDITION: number = data.unknown_condition;
export const TRAINING_STATUS_SHORT: ReadonlyMap<string, string> = new Map(Object.entries(data.training_status_short));
const WIDEST: ReadonlyMap<string, string> = new Map(Object.entries(data.widest));
export const SCALE: ReadonlyMap<string, Scale> = new Map(Object.entries(data.scale as Record<string, Scale>));
/** The age decades `VO2MAX_RATINGS` has a row for: 20-29 to 70-79. */
export const VO2MAX_AGES: readonly [number, number] = data.vo2max_ages as [number, number];
export const VO2MAX_RATINGS: ReadonlyMap<string, readonly (readonly [number, number, number, number])[]> =
  new Map(Object.entries(data.vo2max_ratings as unknown as Record<string, [number, number, number, number][]>));

const isFloatValue = (value: unknown): boolean => value instanceof PyFloat || (typeof value === "number" && !Number.isInteger(value));

/**
 * The twin of `WfbComplications.mc`'s `count`: a count the device scaled to
 * thousands (a non-Number with the unit "K") multiplied back and rounded,
 * step for step in single precision as the watch computes it.
 */
export function countValue(value: unknown, unit: unknown): unknown {
  if (isFloatValue(value) && unit === "K") {
    const f = Math.fround;
    return Math.trunc(f(f(f(num(value as number)) * 1000) + 0.5));
  }
  return value;
}

/**
 * A pulled complication value as the watch draws it (`WfbReading.mc`'s
 * `formatValue`): a float to three significant figures without dropping an
 * integer digit, trailing zeros gone; everything else as `str()`.
 */
export function formatValue(value: unknown): string {
  if (!isFloatValue(value)) return pyStrValue(value);
  const v = num(value as number);
  const magnitude = Math.abs(v);
  const decimals = magnitude >= 100 ? 0 : magnitude >= 10 ? 1 : 2;
  let text = formatFixed(v, decimals);
  if (decimals) text = text.replace(/0+$/, "").replace(/\.$/, "");
  return text;
}

function pyStrValue(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (value === true) return "True";
  if (value === false) return "False";
  return String(value);
}

export function label(name: string): string {
  return PRESENTATION.get(name)![0];
}

export function category(name: string): string {
  return PRESENTATION.get(name)![1];
}

export function get(name: string): ComplicationType | undefined {
  return TYPES.get(name);
}

export function names(): string[] {
  return [...TYPES.keys()].sort();
}

/** The `DeviceSettings` a reading follows. */
export interface ReadingSettings {
  is_24_hour: boolean;
  statute_distance: boolean;
  statute_elevation: boolean;
  statute_temperature: boolean;
  statute_pace: boolean;
}

export const DEFAULT_SETTINGS: ReadingSettings = {
  is_24_hour: true, statute_distance: false, statute_elevation: false, statute_temperature: false, statute_pace: false,
};

/** `WfbReading.rounded`: nearest whole number, halves away from zero. */
function rounded(value: number): number {
  return value < 0 ? -Math.trunc(-value + 0.5) : Math.trunc(value + 0.5);
}

function suffixed(number: string, suffix: string, short: boolean): string {
  if (short && Array.from(number).length + Array.from(suffix).length > SHORT_LENGTH) return number;
  return number + suffix;
}

function count(value: unknown, deviceUnit: unknown): string {
  if (isFloatValue(value)) {
    if (deviceUnit === "K") return `${formatFixed(num(value as number), 1)}K`;
    return formatValue(value) + (typeof deviceUnit === "string" ? deviceUnit : "");
  }
  const whole = Math.trunc(num(value as number));
  if (Math.abs(whole) >= 10000) return `${formatFixed(whole / 1000.0, 1)}K`;
  return String(whole);
}

const two = (n: number): string => String(n).padStart(2, "0");

function duration(seconds: number): string {
  const total = Math.max(Math.trunc(seconds), 0);
  const hours = Math.floor(total / 3600), minutes = Math.floor(total / 60) % 60, secs = total % 60;
  return hours ? `${hours}:${two(minutes)}:${two(secs)}` : `${minutes}:${two(secs)}`;
}

function clock(seconds: number, is24Hour: boolean): string {
  const whole = Math.trunc(seconds);
  const minutes = ((Math.floor(whole / 60) % 1440) + 1440) % 1440;
  const hour = Math.floor(minutes / 60);
  return `${is24Hour ? two(hour) : String(hour % 12 || 12)}:${two(minutes % 60)}`;
}

function highLowShort(text: string): string {
  const found = text.match(/-?\d+/g) ?? [];
  return found.length === 2 ? `${found[0]}/${found[1]}` : text;
}

function inCaseOf(short: string, reported: string): string {
  return reported === reported.toUpperCase() ? short.toUpperCase() : short;
}

/** A `Weather.CONDITION_*` as a slot names it. */
export function conditionText(condition: number, short: boolean): string {
  const [longName, shortName] = WEATHER_CONDITION_TEXT.get(condition) ?? WEATHER_CONDITION_TEXT.get(UNKNOWN_CONDITION)!;
  return short ? shortName : longName;
}

/**
 * The text a `data` element draws for type `name` reading `value`, or
 * `null` when the reading counts as absent: the twin of the generated
 * `SlotText.reading` and the `WfbReading.mc` helpers it calls.
 */
export function formatReading(name: string, value: unknown, deviceUnit: unknown = null,
  { unit = false, short = false, settings = DEFAULT_SETTINGS }: { unit?: boolean; short?: boolean; settings?: ReadingSettings } = {}): string | null {
  if (value === null || value === undefined) return null;
  const kind = READING.get(name);
  if (typeof value === "string") {
    if (kind === "training_status" && short) {
      const abbreviation = TRAINING_STATUS_SHORT.get(value.toUpperCase());
      return abbreviation !== undefined ? inCaseOf(abbreviation, value) : value;
    }
    if (kind === "high_low" && short) return highLowShort(value);
    return value;
  }
  const number = isNumber(value) && typeof value !== "boolean" ? num(value) : typeof value === "boolean" ? Number(value) : 0.0;
  if (kind === "count" || kind === "vo2max") {
    if (kind === "vo2max" && Math.trunc(number) === 0) return null;
    return suffixed(count(value, deviceUnit), unit ? COUNT_UNIT.get(name) ?? "" : "", short);
  }
  if (kind === "percent") return String(rounded(number)) + (unit ? "%" : "");
  if (kind === "condition") return conditionText(Math.trunc(number), short);
  if (kind === "clock") return clock(number, settings.is_24_hour);
  if (kind === "duration") return duration(Math.trunc(number));
  if (kind === "hours") return `${Math.floor((Math.max(Math.trunc(number), 0) + 59) / 60)}h`;
  if (kind === "temperature") {
    const statute = settings.statute_temperature;
    const degrees = statute ? number * 1.8 + 32.0 : number;
    return String(rounded(degrees)) + (unit ? (statute ? "°F" : "°C") : "°");
  }
  if (kind === "elevation") {
    const statute = settings.statute_elevation;
    return suffixed(String(rounded(statute ? number / 0.3048 : number)), unit ? (statute ? "ft" : "m") : "", short);
  }
  if (kind === "distance") {
    const statute = settings.statute_distance;
    return suffixed(formatFixed(number / (statute ? 1609.344 : 1000.0), 1), unit ? (statute ? "mi" : "km") : "", short);
  }
  if (kind === "pressure") return suffixed(String(rounded(number / 100.0)), unit ? "hPa" : "", short);
  if (kind === "pace") {
    if (number <= 0) return null;
    const statute = settings.statute_pace;
    return suffixed(duration(rounded((statute ? 1609.344 : 1000.0) / number)), unit ? (statute ? "/mi" : "/km") : "", short);
  }
  let suffix = "";
  if (unit) suffix = typeof deviceUnit === "string" ? deviceUnit : UNIT_SUFFIX.get(pyStrValue(deviceUnit)) ?? "";
  return suffixed(formatValue(value), suffix, short);
}

function unitSuffixFor(name: string, kind: string): string {
  if (kind === "count") return COUNT_UNIT.get(name) ?? "";
  return ({ percent: "%", temperature: "C", elevation: "ft", distance: "km", pressure: "hPa", pace: "/km" } as Record<string, string>)[kind] ?? "";
}

/** The first longest of `values`, as Python's `max(..., key=len)` picks it. */
function longest(values: Iterable<string>): string {
  let best: string | undefined;
  for (const v of values) if (best === undefined || Array.from(v).length > Array.from(best).length) best = v;
  return best ?? "";
}

/** The widest reading type `name` plausibly draws, under the element's `unit:`/`short:`. */
export function widestReading(name: string, unit: boolean, short: boolean): string {
  const kind = READING.get(name)!;
  if (kind === "condition") return longest([...WEATHER_CONDITION_TEXT.values()].map((n) => (short ? n[1] : n[0])));
  if (kind === "training_status" && short) return longest(TRAINING_STATUS_SHORT.values());
  if (kind === "high_low" && short) return "-88/-88";
  return suffixed(WIDEST.get(kind)!, unit ? unitSuffixFor(name, kind) : "", short);
}

/** Every character type `name`'s reading can draw that a rule of its own produces. */
export function readingGlyphs(name: string, unit: boolean, short: boolean): Set<string> {
  const kind = READING.get(name)!;
  const glyphs = new Set("0123456789-");
  const extra: Record<string, string> = { count: ".K", clock: ":", duration: ":", pace: ":", hours: "h", temperature: "°", distance: "." };
  for (const c of extra[kind] ?? "") glyphs.add(c);
  const add = (text: string): void => { for (const c of text) glyphs.add(c); };
  if (unit) {
    if (kind === "temperature") add("CF");
    else if (kind === "elevation") add("mft");
    else if (kind === "distance" || kind === "pace") add("/kmi");
    else add(unitSuffixFor(name, kind));
  }
  if (kind === "condition") for (const n of WEATHER_CONDITION_TEXT.values()) add(short ? n[1] : n[0]);
  if (kind === "training_status" && short) for (const a of TRAINING_STATUS_SHORT.values()) { add(a); add(a.toUpperCase()); }
  if (kind === "high_low" && short) add("/");
  return glyphs;
}

// -- a gauge's automatic scale --------------------------------------------------

/** A decimal string as an exact fraction. */
function decimalFraction(text: string): [bigint, bigint] {
  const m = /^(-?)(\d*)(?:\.(\d*))?(?:e([+-]?\d+))?$/i.exec(text)!;
  const digits = BigInt((m[2] || "0") + (m[3] ?? ""));
  let exponent = -(m[3] ?? "").length + Number(m[4] ?? 0);
  let n = digits, d = 1n;
  if (exponent >= 0) n *= 10n ** BigInt(exponent); else d = 10n ** BigInt(-exponent);
  void exponent;
  return [m[1] === "-" ? -n : n, d];
}

/** `value` to one decimal, a half rounding up: `Decimal(repr(value)).quantize(Decimal("0.1"), ROUND_HALF_UP)`. */
function tenth(value: number): number {
  const [n, d] = decimalFraction(String(value));
  const scaled = n * 10n;
  const sign = scaled < 0n ? -1n : 1n;
  const abs = scaled < 0n ? -scaled : scaled;
  let q = abs / d;
  if ((abs % d) * 2n >= d) q += 1n;
  return Number(sign * q) / 10;
}

/** A VO2 max scale's two ends: the three middle bands' average width beyond each edge, to one decimal. */
export function vo2maxEnds(fair: number, superior: number): [number, number] {
  const [ln, ld] = decimalFraction(String(fair));
  const [hn, hd] = decimalFraction(String(superior));
  // width = (hi - lo) / 3, exactly; Decimal's 28 digits only matter far below a tenth.
  const wn = hn * ld - ln * hd, wd = hd * ld * 3n;
  const lo = Number(ln * wd - wn * ld) / Number(ld * wd);
  const hi = Number(hn * wd + wn * hd) / Number(hd * wd);
  return [tenth(lo), tenth(hi)];
}

export function vo2maxScale(sex: string | null, age: number | null): [number, number] | null {
  const rows = VO2MAX_RATINGS.get(sex ?? "");
  if (rows === undefined || age === null || !(age >= VO2MAX_AGES[0] && age < VO2MAX_AGES[1] && Number.isInteger(age))) return null;
  const [fair, , , superior] = rows[Math.floor((age - 20) / 10)]!;
  return vo2maxEnds(fair, superior);
}

/** Zone 1's minimum to zone 5's maximum, out of six heart-rate zone values. */
export function heartRateScale(zones: readonly number[] | null): [number, number] | null {
  if (zones === null || zones.length < 6 || zones[0]! >= zones[5]!) return null;
  return [zones[0]!, zones[5]!];
}

/** An app complication's own `ranges`: the first value to the last. */
export function rangesScale(ranges: readonly number[] | null): [number, number] | null {
  if (ranges === null || ranges.length < 2 || ranges[0]! >= ranges[ranges.length - 1]!) return null;
  return [ranges[0]!, ranges[ranges.length - 1]!];
}

/** The twin of the generated `SlotScale.scale`: type `name`'s `[minimum, maximum]` for a wearer, or `null`. */
export function scaleFor(name: string, { goals, heartRateZones, sex, age, value = null }: {
  goals: ReadonlyMap<string, number>; heartRateZones: readonly number[] | null; sex: string | null; age: number | null; value?: unknown;
}): [number, number] | null {
  const scale = SCALE.get(name);
  if (scale === undefined) return null;
  if (scale.kind === "fixed") return [scale.minimum, scale.maximum];
  if (scale.kind === "goal") {
    const goal = goals.get(scale.goal!);
    return goal !== undefined && goal > 0 ? [0.0, goal] : null;
  }
  if (scale.kind === "heart_rate_zones") return heartRateScale(heartRateZones);
  if (isInt(value) && value === 0) return null;
  return vo2maxScale(sex, age);
}

/** The twin of `WfbScale.fraction`: how full a gauge on `scale` is for a pulled `value`, 0.0 to 1.0. */
export function scaleFraction(value: unknown, unit: unknown, scale: readonly [number, number]): number | null {
  if (!isNumber(value)) return null;
  let reading = num(value);
  if (isFloatValue(value) && unit === "K") reading *= 1000;
  const [low, high] = scale;
  return Math.min(1.0, Math.max(0.0, (reading - low) / (high - low)));
}
