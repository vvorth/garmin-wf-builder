// The editor's data as JSON: YAML values (a mapping is a `Map`, a float a
// `WholeFloat`) as plain objects for an answer, and Python's `json.dumps`
// spelling where a value is shown as text.
import { WholeFloat, Timestamp } from "../edit/yaml.ts";
import { floatRepr } from "../py.ts";

/** `value` with every `Map` an object, every `WholeFloat` a number, every `Timestamp` its text. */
export function plain(value: unknown): unknown {
  if (value instanceof WholeFloat) return value.value;
  if (value instanceof Timestamp) return value.iso;
  if (value instanceof Map) return Object.fromEntries([...value].map(([k, v]) => [String(k), plain(v)]));
  if (Array.isArray(value)) return value.map(plain);
  if (value instanceof Uint8Array) return value;
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, plain(v)]));
  }
  return value;
}

/** Python's `json.dumps(value)`: `", "` and `": "` separators, ASCII only. */
export function jsonDumps(value: unknown): string {
  if (value instanceof WholeFloat) return floatRepr(value.value);
  if (value instanceof Timestamp) return ascii(value.iso);
  if (value === null || value === undefined) return "null";
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : floatRepr(value);
  if (typeof value === "string") return ascii(value);
  if (value instanceof Map) return `{${[...value].map(([k, v]) => `${ascii(String(k))}: ${jsonDumps(v)}`).join(", ")}}`;
  if (Array.isArray(value)) return `[${value.map(jsonDumps).join(", ")}]`;
  return `{${Object.entries(value as object).map(([k, v]) => `${ascii(k)}: ${jsonDumps(v)}`).join(", ")}}`;
}

function ascii(text: string): string {
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
