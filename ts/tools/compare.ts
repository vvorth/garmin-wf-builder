// Structural comparison of a TypeScript stage's output with the oracle's
// JSON (tools/oracle.py), reporting where they first part.

/** One place two JSON values differ: its path (`$.elements[3].at.dx`) and both sides. */
export interface Difference {
  path: string;
  expected: unknown;
  actual: unknown;
}

const key = (path: string, name: string): string =>
  /^[A-Za-z_$][\w$]*$/.test(name) ? `${path}.${name}` : `${path}[${JSON.stringify(name)}]`;

/**
 * Every difference between `expected` (the oracle) and `actual` (the
 * port), up to `limit`. Numbers compare by value, so Python's `1.0` equals
 * JavaScript's `1`; object key order is ignored, array order is not.
 */
export function compare(expected: unknown, actual: unknown, limit = 20, path = "$"): Difference[] {
  const out: Difference[] = [];
  walk(expected, actual, path, out, limit);
  return out;
}

function walk(expected: unknown, actual: unknown, path: string, out: Difference[], limit: number): void {
  if (out.length >= limit) return;
  if (Object.is(expected, actual) || (typeof expected === "number" && expected === actual)) return;
  if (Array.isArray(expected) && Array.isArray(actual)) {
    if (expected.length !== actual.length) {
      out.push({ path: `${path}.length`, expected: expected.length, actual: actual.length });
    }
    const n = Math.min(expected.length, actual.length);
    for (let i = 0; i < n; i++) walk(expected[i], actual[i], `${path}[${i}]`, out, limit);
    return;
  }
  if (isObject(expected) && isObject(actual)) {
    for (const name of Object.keys(expected)) {
      if (!(name in actual)) out.push({ path: key(path, name), expected: expected[name], actual: undefined });
      else walk(expected[name], actual[name], key(path, name), out, limit);
      if (out.length >= limit) return;
    }
    for (const name of Object.keys(actual)) {
      if (!(name in expected)) out.push({ path: key(path, name), expected: undefined, actual: actual[name] });
      if (out.length >= limit) return;
    }
    return;
  }
  out.push({ path, expected, actual });
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
