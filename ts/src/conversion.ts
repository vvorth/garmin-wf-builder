// Unit conversion for a `text` element's `units:` (ADR 0005 §4)..
//
// The builder rewrites the bound value into an ordinary expression over the
// source and one `device.<quantity>_units` setting (`convertedText`), then
// compiles it like any other value, so null guards, the read plan,
// permissions and the preview treat it as an expression the author wrote.
// A quantity is decided per source (`Source.quantity`), not from the unit.
import type { Source } from "./catalog.ts";
import { floatRepr } from "./py.ts";

/** One displayed unit: `value * factor + offset`, labelled `label`, or `factor / value` when `reciprocal`. */
export interface Display {
  label: string;
  factor: number;
  offset: number;
  reciprocal: boolean;
}

export interface Conversion {
  /** The catalogue path of the `DeviceSettings` field that picks the system at runtime. */
  setting: string;
  metric: Display;
  statute: Display;
  /** Digits before the decimal point either display can reach. */
  digits: number;
}

const display = (label: string, factor: number, offset = 0.0, reciprocal = false): Display => ({ label, factor, offset, reciprocal });

const KM_FROM_CM = display("km", 1 / 100000);
const MI_FROM_CM = display("mi", 1 / 160934.4);
const KM_FROM_M = display("km", 1 / 1000);
const MI_FROM_M = display("mi", 1 / 1609.344);
const METRES = display("m", 1.0);
const FEET = display("ft", 1 / 0.3048);
const CELSIUS = display("°C", 1.0);
const FAHRENHEIT = display("°F", 1.8, 32.0);
const KMH = display("km/h", 3.6);
const MPH = display("mph", 3600 / 1609.344);
const PER_KM = display("/km", 1000.0, 0.0, true);
const PER_MI = display("/mi", 1609.344, 0.0, true);

const conv = (setting: string, metric: Display, statute: Display, digits: number): Conversion => ({ setting, metric, statute, digits });

/** `quantity\0unit` to how to display it. */
export const CONVERSIONS: ReadonlyMap<string, Conversion> = new Map([
  ["distance\0cm", conv("device.distance_units", KM_FROM_CM, MI_FROM_CM, 3)],
  ["distance\0meters", conv("device.distance_units", KM_FROM_M, MI_FROM_M, 4)],
  ["elevation\0m", conv("device.elevation_units", METRES, FEET, 5)],
  ["elevation\0meters", conv("device.elevation_units", METRES, FEET, 5)],
  ["temperature\0celsius", conv("device.temperature_units", CELSIUS, FAHRENHEIT, 3)],
  ["temperature\0degrees Celsius", conv("device.temperature_units", CELSIUS, FAHRENHEIT, 3)],
  ["speed\0m/s", conv("device.distance_units", KMH, MPH, 3)],
  ["pace\0meters/second", conv("device.pace_units", PER_KM, PER_MI, 5)],
]);

/** Seconds in one of a catalogue unit, for a duration `format:` over a bare source. */
export const SECONDS_PER_UNIT: ReadonlyMap<string, number> = new Map([
  ["seconds", 1], ["seconds since local midnight", 1], ["minutes", 60], ["hours", 3600], ["days", 86400],
]);

/** The conversion a source takes, or `null` when it has no quantity `units:` knows. */
export function conversionFor(source: Source | null | undefined): Conversion | null {
  if (source === null || source === undefined || source.quantity === null || source.unit === null) return null;
  return CONVERSIONS.get(`${source.quantity}\0${source.unit}`) ?? null;
}

/** A float literal the expression language parses back exactly: shortest round-trip digits, never in exponent form. */
export function literal(value: number): string {
  const quoted = floatRepr(value);
  const m = /^(-?)(\d)(?:\.(\d+))?e([+-]\d+)$/.exec(quoted);
  let text = quoted;
  if (m !== null) {
    const [, sign, lead, rest = "", exp] = m;
    const digits = lead! + rest;
    const point = 1 + Number(exp);
    if (point <= 0) text = `${sign}0.${"0".repeat(-point)}${digits}`;
    else if (point >= digits.length) text = `${sign}${digits}${"0".repeat(point - digits.length)}`;
    else text = `${sign}${digits.slice(0, point)}.${digits.slice(point)}`;
  }
  return text.includes(".") ? text : text + ".0";
}

function scaled(path: string, d: Display): string {
  if (d.reciprocal) return `(${path} > 0 ? ${literal(d.factor)} / ${path} : 0.0)`;
  let text = d.factor === 1.0 ? path : `${path} * ${literal(d.factor)}`;
  if (d.offset) text = `${text} + ${literal(d.offset)}`;
  return text;
}

/** The expression text a bare source becomes under `units: <system>`. */
export function convertedText(path: string, c: Conversion, system: string): string {
  if (system === "metric") return scaled(path, c.metric);
  if (system === "statute") return scaled(path, c.statute);
  return `${c.setting} == 1 ? ${scaled(path, c.statute)} : ${scaled(path, c.metric)}`;
}

/** The expression text `{unit}` renders. */
export function labelText(c: Conversion, system: string): string {
  if (system === "metric") return `"${c.metric.label}"`;
  if (system === "statute") return `"${c.statute.label}"`;
  return `${c.setting} == 1 ? "${c.statute.label}" : "${c.metric.label}"`;
}

/** Every label `{unit}` can render under `system`. */
export function labels(c: Conversion, system: string): string[] {
  if (system === "metric") return [c.metric.label];
  if (system === "statute") return [c.statute.label];
  return [c.metric.label, c.statute.label];
}
