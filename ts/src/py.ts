// Python's semantics where the compiler's behaviour depends on them, so a
// port reads like the code it came from and produces the same text:
// truthiness, `repr` of a string, `json.dumps`, `str.splitlines`,
// `f"{x:.6f}"` and `round()`.
import { type Data, type DataKey, Timestamp } from "./edit/yaml.ts";

/** Python's truthiness: `None`, `False`, `0`, `""` and empty containers are false. */
export function truthy(value: unknown): boolean {
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

/** Python's `repr()` of a string, `None`, a number or a bool, as an f-string's `!r` writes it. */
export function repr(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (value === true) return "True";
  if (value === false) return "False";
  if (typeof value === "number") return pyStr(value);
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
