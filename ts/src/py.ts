// Python's semantics where the compiler's behaviour depends on them, so a
// port reads like the code it came from and produces the same text:
// truthiness, `repr` of a string, `json.dumps`, `str.splitlines`,
// `f"{x:.6f}"` and `round()`.
import { type Data, type DataKey, PyFloat, Timestamp } from "./edit/yaml.ts";

/** Python's truthiness: `None`, `False`, `0`, `""` and empty containers are false. */
export function truthy(value: unknown): boolean {
  if (value instanceof PyFloat) return value.value !== 0;
  if (value === null || value === undefined || value === false || value === 0 || value === "") return false;
  if (typeof value === "number" && Number.isNaN(value)) return true;
  if (Array.isArray(value)) return value.length > 0;
  if (value instanceof Map || value instanceof Set) return value.size > 0;
  return true;
}

/** Python's `a or b`. */
export function or<T, U>(a: T, b: U): T | U {
  return truthy(a) ? a : b;
}

export function isDict(value: unknown): value is Map<DataKey, Data> {
  return value instanceof Map;
}

/** `value.get(key)` when `value` is a dict, else `undefined`: Python's `(x or {}).get(k)` without the `or`. */
export function get(value: unknown, key: DataKey): Data | undefined {
  return value instanceof Map ? value.get(key) : undefined;
}

/**
 * Python's `repr()` as an f-string's `!r` writes it: of a string, `None`, a
 * number, a bool, a dict (a `Map`, or a plain object such as a schema), a
 * list or a date.
 */
export function repr(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (value === true) return "True";
  if (value === false) return "False";
  if (typeof value === "number") return Number.isInteger(value) ? pyStr(value) : floatRepr(value);
  if (value instanceof PyFloat) return floatRepr(value.value);
  if (value instanceof Timestamp) return timestampRepr(value.iso);
  if (value instanceof Map) return `{${[...value].map(([k, v]) => `${repr(k)}: ${repr(v)}`).join(", ")}}`;
  if (Array.isArray(value)) return `[${value.map(repr).join(", ")}]`;
  if (typeof value === "object") return `{${Object.entries(value).map(([k, v]) => `${repr(k)}: ${repr(v)}`).join(", ")}}`;
  if (typeof value !== "string") return String(value);
  const quote = value.includes("'") && !value.includes("\"") ? "\"" : "'";
  let out = quote;
  for (const ch of value) {
    const c = ch.codePointAt(0)!;
    if (ch === quote || ch === "\\") out += "\\" + ch;
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (ch === "\t") out += "\\t";
    else if (c < 0x20 || c === 0x7f) out += "\\x" + c.toString(16).padStart(2, "0");
    else out += ch;
  }
  return out + quote;
}

/** `datetime.date(2026, 10, 5)` or `datetime.datetime(...)`, from an isoformat. */
function timestampRepr(iso: string): string {
  const m = /^(\d+)-(\d+)-(\d+)(?:T(\d+):(\d+):(\d+)(?:\.(\d+))?)?/.exec(iso);
  if (m === null) return iso;
  const parts = [m[1], m[2], m[3]].map(Number);
  if (m[4] === undefined) return `datetime.date(${parts.join(", ")})`;
  const time = [m[4], m[5], m[6]].map(Number);
  const micro = m[7] ? [Number(m[7])] : [];
  while (time.length > 2 && time[time.length - 1] === 0 && micro.length === 0) time.pop();
  return `datetime.datetime(${[...parts, ...time, ...micro].join(", ")})`;
}

/** Python's `str()` of a number: `1.0` for an integral float is not recoverable here, so integers print as integers. */
export function pyStr(value: number): string {
  if (Number.isNaN(value)) return "nan";
  if (!Number.isFinite(value)) return value > 0 ? "inf" : "-inf";
  if (Number.isInteger(value) && Math.abs(value) < 1e16) return String(value);
  return String(value);
}

/** Python's `json.dumps(text, ensure_ascii=False)` of a string. */
export function jsonString(text: string): string {
  let out = "\"";
  for (const ch of text) {
    const c = ch.codePointAt(0)!;
    if (ch === "\"") out += "\\\"";
    else if (ch === "\\") out += "\\\\";
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (ch === "\t") out += "\\t";
    else if (ch === "\b") out += "\\b";
    else if (ch === "\f") out += "\\f";
    else if (c < 0x20) out += "\\u" + c.toString(16).padStart(4, "0");
    else out += ch;
  }
  return out + "\"";
}

/** Python's `str.splitlines(keepends=True)`: every line boundary Python knows. */
export function splitlines(text: string): string[] {
  const out: string[] = [];
  const re = new RegExp("\\r\\n|[\\n\\r\\v\\f\\x1c\\x1d\\x1e\\x85\\u2028\\u2029]", "g");
  let last = 0;
  for (let m = re.exec(text); m !== null; m = re.exec(text)) {
    out.push(text.slice(last, m.index + m[0].length));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/**
 * Python's `f"{value:.{digits}f}"`: the exact binary value rounded half to
 * even, where JavaScript's `toFixed` rounds an exact tie away from zero
 * (`1/128` is `0.007812` in Python, `0.007813` from `toFixed(6)`).
 */
export function formatFixed(value: number, digits: number): string {
  if (!Number.isFinite(value)) return pyStr(value);
  const negative = value < 0 || Object.is(value, -0);
  const [num, den] = exactFraction(Math.abs(value));
  const scale = 10n ** BigInt(digits);
  const scaled = num * scale;
  let q = scaled / den;
  const r = scaled % den;
  if (r * 2n > den || (r * 2n === den && q % 2n === 1n)) q += 1n;
  let text = q.toString().padStart(digits + 1, "0");
  if (digits > 0) text = `${text.slice(0, -digits)}.${text.slice(-digits)}`;
  return (negative ? "-" : "") + text;
}

/** A finite non-negative double as an exact fraction `num / den`. */
function exactFraction(value: number): [bigint, bigint] {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, value);
  const bits = view.getBigUint64(0);
  const exponent = Number((bits >> 52n) & 0x7ffn);
  let mantissa = bits & ((1n << 52n) - 1n);
  let e: number;
  if (exponent === 0) e = -1074;
  else { mantissa |= 1n << 52n; e = exponent - 1075; }
  return e >= 0 ? [mantissa << BigInt(e), 1n] : [mantissa, 1n << BigInt(-e)];
}

/** Python's `round(value)`: half to even, to an integer. */
export function roundHalfEven(value: number): number {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (diff > 0.5) return floor + 1;
  if (diff < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}

/** A deep copy of YAML data: Python's `copy.deepcopy` over dicts, lists and scalars. */
export function deepCopy<T extends Data>(value: T): T {
  return copyData(value) as T;
}

function copyData(value: Data): Data {
  if (value instanceof Map) {
    const out = new Map<DataKey, Data>();
    for (const [k, v] of value) out.set(k, copyData(v));
    return out;
  }
  if (Array.isArray(value)) return value.map(copyData);
  return value;
}

/** Python's `float.hex()`. */
export function floatHex(value: number): string {
  if (Number.isNaN(value)) return "nan";
  if (!Number.isFinite(value)) return value > 0 ? "inf" : "-inf";
  if (value === 0) return Object.is(value, -0) ? "-0x0.0p+0" : "0x0.0p+0";
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, value);
  const bits = view.getBigUint64(0);
  const sign = bits >> 63n ? "-" : "";
  const exponent = Number((bits >> 52n) & 0x7ffn);
  const mantissa = bits & ((1n << 52n) - 1n);
  const lead = exponent === 0 ? "0" : "1";
  const e = exponent === 0 ? -1022 : exponent - 1023;
  return `${sign}0x${lead}.${mantissa.toString(16).padStart(13, "0")}p${e >= 0 ? "+" : ""}${e}`;
}

/**
 * tools/oracle_patches.py's `canonical`: one string for YAML data that
 * Python writes identically, for hashing intended data across languages.
 */
export function canonical(data: Data): string {
  if (data instanceof PyFloat) return canonical(data.value);
  if (data === null) return "n";
  if (data === true) return "t";
  if (data === false) return "f";
  if (typeof data === "number") {
    if (Number.isFinite(data) && Number.isInteger(data) && Math.abs(data) < 2 ** 53) return `i${data}`;
    return `x${floatHex(data)}`;
  }
  if (typeof data === "string") return asciiJson(data);
  if (data instanceof Timestamp) return `T${data.iso}`;
  if (data instanceof Map) return `{${[...data].map(([k, v]) => `${canonical(k)}:${canonical(v)}`).join(",")}}`;
  return `[${data.map(canonical).join(",")}]`;
}

/** Python's `json.dumps(text, ensure_ascii=True)`. */
function asciiJson(text: string): string {
  let out = "\"";
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]!;
    const c = text.charCodeAt(i);
    if (ch === "\"") out += "\\\"";
    else if (ch === "\\") out += "\\\\";
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (ch === "\t") out += "\\t";
    else if (ch === "\b") out += "\\b";
    else if (ch === "\f") out += "\\f";
    else if (c < 0x20 || c > 0x7e) out += "\\u" + c.toString(16).padStart(4, "0");
    else out += ch;
  }
  return out + "\"";
}

/** An exception Python would raise outside `Refused` (`KeyError`, `IndexError`, ...), named so a crash compares across languages. */
export class PyError extends Error {
  readonly pyType: string;

  constructor(pyType: string, message = "") {
    super(message || pyType);
    this.pyType = pyType;
  }
}

/** Python's `container[step]` over YAML data: a dict's key, a list's index. */
export function item(container: unknown, step: DataKey): Data {
  if (container instanceof Map) {
    if (!container.has(step)) throw new PyError("KeyError", String(step));
    return container.get(step)!;
  }
  if (Array.isArray(container)) {
    if (typeof step !== "number" || !Number.isInteger(step)) throw new PyError("TypeError", "list indices must be integers");
    const i = step < 0 ? container.length + step : step;
    if (i < 0 || i >= container.length) throw new PyError("IndexError", "list index out of range");
    return container[i] as Data;
  }
  throw new PyError("TypeError", `${typeof container} is not subscriptable`);
}

/** Python's `container[step] = value` over YAML data. */
export function setItem(container: unknown, step: DataKey, value: Data): void {
  if (container instanceof Map) { container.set(step, value); return; }
  if (Array.isArray(container)) {
    if (typeof step !== "number" || !Number.isInteger(step)) throw new PyError("TypeError", "list indices must be integers");
    const i = step < 0 ? container.length + step : step;
    if (i < 0 || i >= container.length) throw new PyError("IndexError", "list assignment index out of range");
    container[i] = value;
    return;
  }
  throw new PyError("TypeError", `${typeof container} does not support item assignment`);
}

/** Python's `del container[step]` over YAML data. */
export function delItem(container: unknown, step: DataKey): void {
  if (container instanceof Map) {
    if (!container.delete(step)) throw new PyError("KeyError", String(step));
    return;
  }
  if (Array.isArray(container)) {
    if (typeof step !== "number") throw new PyError("TypeError", "list indices must be integers");
    const i = step < 0 ? container.length + step : step;
    if (i < 0 || i >= container.length) throw new PyError("IndexError", "list assignment index out of range");
    container.splice(i, 1);
    return;
  }
  throw new PyError("TypeError", `${typeof container} does not support item deletion`);
}

/** A string for a regular expression that matches `text` literally: Python's `re.escape`. */
export function reEscape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\\/-]/g, "\\$&");
}

/** Python's `a % b` on floats or ints: the result takes the divisor's sign. */
export function pyMod(a: number, b: number): number {
  if (b === 0) throw new PyError("ZeroDivisionError", "modulo by zero");
  const r = a % b;
  return r !== 0 && (r < 0) !== (b < 0) ? r + b : r;
}

/** Python's `a // b`. */
export function floorDiv(a: number, b: number): number {
  if (b === 0) throw new PyError("ZeroDivisionError", "division by zero");
  return Math.floor(a / b);
}

/** Python's `math.degrees`: `x / (pi / 180)`, as CPython computes it. */
export function degrees(x: number): number {
  return x / (Math.PI / 180.0);
}

/** Python's `math.radians`: `x * (pi / 180)`. */
export function radians(x: number): number {
  return x * (Math.PI / 180.0);
}

/**
 * Python's `repr()` of a float: the shortest digits that round-trip, as
 * `1.0`, `0.1`, `1e-05` or `1e+16` (exponent form below 1e-4 and from 1e16).
 */
export function floatRepr(value: number): string {
  if (Number.isNaN(value)) return "nan";
  if (!Number.isFinite(value)) return value > 0 ? "inf" : "-inf";
  if (value === 0) return Object.is(value, -0) ? "-0.0" : "0.0";
  const [digits, exponent] = shortestDigits(Math.abs(value));
  const sign = value < 0 ? "-" : "";
  // `exponent` is the decimal exponent of the first digit: value = 0.d1d2... * 10^(exponent + 1).
  if (exponent < -4 || exponent >= 16) {
    const mantissa = digits.length > 1 ? `${digits[0]}.${digits.slice(1)}` : digits;
    return `${sign}${mantissa}e${exponent < 0 ? "-" : "+"}${String(Math.abs(exponent)).padStart(2, "0")}`;
  }
  if (exponent < 0) return `${sign}0.${"0".repeat(-exponent - 1)}${digits}`;
  if (digits.length <= exponent + 1) return `${sign}${digits}${"0".repeat(exponent + 1 - digits.length)}.0`;
  return `${sign}${digits.slice(0, exponent + 1)}.${digits.slice(exponent + 1)}`;
}

/** The shortest round-trip decimal digits of a positive finite double, and its first digit's exponent. */
function shortestDigits(value: number): [string, number] {
  const text = value.toExponential(); // JavaScript also prints the shortest round-trip digits
  const [mantissa, exp] = text.split("e");
  return [mantissa!.replace(".", ""), Number(exp)];
}

/**
 * Python's `format(value, "g")` (precision 6): six significant digits, the
 * exponent form below 1e-4 or from 1e6, trailing zeros dropped.
 */
export function formatG(value: number, precision = 6): string {
  if (Number.isNaN(value)) return "nan";
  if (!Number.isFinite(value)) return value > 0 ? "inf" : "-inf";
  if (value === 0) return Object.is(value, -0) ? "-0" : "0";
  const p = precision === 0 ? 1 : precision;
  // Round to p significant digits exactly, then pick the notation from the rounded exponent.
  const [num, den] = exactFraction(Math.abs(value));
  let exponent = Math.floor(Math.log10(Math.abs(value)));
  let digits = roundSignificant(num, den, exponent, p);
  if (digits.length > p) { exponent += 1; digits = digits.slice(0, p); }
  else if (BigInt(digits) < 10n ** BigInt(p - 1)) {
    exponent -= 1;
    digits = roundSignificant(num, den, exponent, p);
  }
  const sign = value < 0 ? "-" : "";
  const trimmed = digits.replace(/0+$/, "") || "0";
  if (exponent < -4 || exponent >= p) {
    const mantissa = trimmed.length > 1 ? `${trimmed[0]}.${trimmed.slice(1)}` : trimmed;
    return `${sign}${mantissa}e${exponent < 0 ? "-" : "+"}${String(Math.abs(exponent)).padStart(2, "0")}`;
  }
  if (exponent < 0) return `${sign}0.${"0".repeat(-exponent - 1)}${trimmed}`;
  if (trimmed.length <= exponent + 1) return `${sign}${trimmed}${"0".repeat(exponent + 1 - trimmed.length)}`;
  return `${sign}${trimmed.slice(0, exponent + 1)}.${trimmed.slice(exponent + 1)}`;
}

/** `num/den` rounded half to even to `p` significant digits, the first at 10^exponent: the digits as a string. */
function roundSignificant(num: bigint, den: bigint, exponent: number, p: number): string {
  const shift = p - 1 - exponent;
  let n = num, d = den;
  if (shift >= 0) n *= 10n ** BigInt(shift); else d *= 10n ** BigInt(-shift);
  let q = n / d;
  const r = n % d;
  if (r * 2n > d || (r * 2n === d && q % 2n === 1n)) q += 1n;
  return q.toString();
}

/** Python's `isinstance(x, (int, float)) and not isinstance(x, bool)`. */
export function isNumber(value: unknown): value is number | PyFloat {
  return typeof value === "number" || value instanceof PyFloat;
}

/** Python's `isinstance(x, int) and not isinstance(x, bool)`. */
export function isInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

/** Python's `isinstance(x, float)`: a boxed integral float, or any non-integral number. */
export function isFloat(value: unknown): boolean {
  return value instanceof PyFloat || (typeof value === "number" && !Number.isInteger(value));
}

/** A number's value, boxed or not. */
export function num(value: number | PyFloat): number {
  return value instanceof PyFloat ? value.value : value;
}
