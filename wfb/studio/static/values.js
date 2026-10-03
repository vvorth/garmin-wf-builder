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

// The name the editor gives a colour it adds (`wfb.edit.colors`): its MIP
// name when it is one of the 64 (`mip`, the vocabulary's table), else `c`
// and its hex.
export function automaticName(rgb, mip) {
  const hex = toHex(rgb);
  const named = (mip || []).find((m) => m.value === hex);
  return named ? named.name : "c" + hex.slice(1);
}

// What a pick of `rgb` writes: the swatch already holding it, or the name
// it will be added under.
export function swatchFor(rgb, palette, mip) {
  const hex = toHex(rgb);
  const held = (palette || []).find((p) => { const v = parseHex(p.value); return v && toHex(v) === hex; });
  return held ? { name: held.name, adds: false } : { name: automaticName(rgb, mip), adds: true };
}

// sRGB channel -> linear, and the 2-colour rule: nearer white above the
// luminance where contrast with black equals contrast with white
// (`wfb.palette.MONO_CROSSOVER`).
function linear(c) {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}
const MONO_CROSSOVER = Math.sqrt(1.05 * 0.05) - 0.05;

// Whether a screen of each of `displays` (colour counts) shows `rgb` as
// written, and the nearest colour that every one of them does: the 64-colour
// snap, then black or white for a 2-colour screen.
export function safeOn(rgb, displays) {
  let out = rgb;
  if ((displays || []).includes(64)) out = mipNearest(out);
  if ((displays || []).includes(2)) {
    const y = 0.2126 * linear(out[0]) + 0.7152 * linear(out[1]) + 0.0722 * linear(out[2]);
    out = y > MONO_CROSSOVER ? [255, 255, 255] : [0, 0, 0];
  }
  return { ok: toHex(out) === toHex(rgb), nearest: out };
}

// What removing the schemes does to the style entries
// (`wfb.edit.schemes.remove_theme`): an entry naming only a scheme goes, one
// naming a layout stays, and a kept entry whose layout an earlier one has
// already is a duplicate the author resolves.
export function afterRemovingSchemes(entries) {
  const seen = new Set();
  let removed = 0, duplicates = 0;
  for (const e of entries || []) {
    if (!e.layout) { removed += 1; continue; }
    if (seen.has(e.layout)) duplicates += 1;
    seen.add(e.layout);
  }
  return { removed, duplicates };
}

// The editor's "showing" as a query value (`picks=top:heart_rate,...`):
// only slots shown with something other than their default, sorted, so one
// choice is one cache key on the server.
export function picksParam(picks, slots) {
  return (slots || [])
    .filter((s) => picks && picks[s.name] && picks[s.name] !== s.default)
    .map((s) => `${s.name}:${picks[s.name]}`).sort().join(",");
}

// A complication type's name for people, from the vocabulary.
export function typeLabel(vocab, name) {
  const t = ((vocab && vocab.complication_types) || []).find((x) => x.name === name);
  return t ? t.label : name;
}
