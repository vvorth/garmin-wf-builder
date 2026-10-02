// Values as the author writes them: pure functions, no DOM, so Node can
// check them (tests/test_studio_frontend.py).

const NUMBER = /^\s*([+-]?(?:\d+\.?\d*|\.\d+))\s*([A-Za-z%]*)\s*$/;

// `12%r` -> {number: 12, unit: "%r", bare: false}; `12` (a YAML number) ->
// {number: 12, unit: <bareUnit>, bare: true}; anything else -> null.
export function parseQuantity(value, bareUnit) {
  if (typeof value === "number") return { number: value, unit: bareUnit, bare: true };
  if (typeof value !== "string") return null;
  const m = value.match(NUMBER);
  if (!m) return null;
  return { number: Number(m[1]), unit: m[2] || bareUnit, bare: !m[2] };
}

// The value to write: a bare number stays bare while its unit is the bare
// one, so `12` is never rewritten as `"12px"`.
export function formatQuantity(number, unit, bareUnit, bare) {
  if (!Number.isFinite(number)) return null;
  const n = Number(number.toFixed(6));
  if (bare && unit === bareUnit) return n;
  return `${n}${unit}`;
}

export const LENGTH_UNITS = ["px", "%", "%r", "pt"];
export const ANGLE_UNITS = ["deg", "rad", "turn"];

// `#RGB` or `#RRGGBB` (the `#` optional, as the schema allows) -> [r, g, b].
export function parseHex(value) {
  if (typeof value !== "string") return null;
  const m = value.trim().match(/^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/);
  if (!m) return null;
  const h = m[1].length === 3 ? m[1].split("").map((c) => c + c).join("") : m[1];
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}

export function toHex(rgb) {
  return "#" + rgb.map((c) => c.toString(16).padStart(2, "0").toUpperCase()).join("");
}

const MIP = [0x00, 0x55, 0xaa, 0xff];

// Whether a 64-colour MIP panel shows the colour exactly (every channel
// one of 00/55/AA/FF), and the nearest one it does show.
export function mipLegal(rgb) {
  return rgb.every((c) => MIP.includes(c));
}

export function mipNearest(rgb) {
  return rgb.map((c) => MIP.reduce((a, b) => (Math.abs(b - c) < Math.abs(a - c) ? b : a)));
}

// A `color.<name>` reference's name, or null.
export function colorName(value) {
  const m = typeof value === "string" && value.match(/^color\.([A-Za-z_][A-Za-z0-9_]*)$/);
  return m ? m[1] : null;
}

// A name the format accepts for a colour, font or style entry.
export function isIdentifier(text) {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(text);
}

// A new `config: style:` entry, shaped like the entries already there: once
// one entry names a layout or a scheme, every entry must. With none yet, a
// layout when the face has layouts, else a scheme.
export function newStyleEntry(entries, layouts, schemes) {
  const like = entries[0];
  const entry = {};
  if (like ? like.layout : layouts.length) entry.layout = (like && like.layout) || layouts[0];
  if (like ? like.scheme : !layouts.length) entry.scheme = (like && like.scheme) || schemes[0];
  return entry;
}

// The value at `path` inside nested `data`, or undefined.
export function at(data, path) {
  return path.reduce((d, k) => (d == null ? undefined : d[k]), data);
}
