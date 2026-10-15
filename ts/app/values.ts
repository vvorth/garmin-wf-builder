// Values as the author writes them: pure functions, no DOM, so Node can
// check them (test/page-modules.test.ts).

import type { ComplicationType, Diagnostic, EditOp, MipColor, PaletteEntry, Path, Severity, SlotEntry, Value } from "../src/studio/protocol.ts";

/** A colour's channels, 0 to 255. */
export type RGB = [number, number, number];

/** A length or angle as written: its number, its unit, and whether the unit was left off. */
export interface Quantity {
  number: number;
  unit: string;
  bare: boolean;
}

const NUMBER = /^\s*([+-]?(?:\d+\.?\d*|\.\d+))\s*([A-Za-z%]*)\s*$/;

// `12%r` -> {number: 12, unit: "%r", bare: false}; `12` (a YAML number) ->
// {number: 12, unit: <bareUnit>, bare: true}; anything else -> null.
export function parseQuantity(value: Value | undefined, bareUnit: string): Quantity | null {
  if (typeof value === "number") return { number: value, unit: bareUnit, bare: true };
  if (typeof value !== "string") return null;
  const m = value.match(NUMBER);
  if (!m) return null;
  return { number: Number(m[1]), unit: m[2] || bareUnit, bare: !m[2] };
}

// The value to write: a bare number stays bare while its unit is the bare
// one, so `12` is never rewritten as `"12px"`.
export function formatQuantity(number: number, unit: string, bareUnit: string, bare: boolean): number | string | null {
  if (!Number.isFinite(number)) return null;
  const n = Number(number.toFixed(6));
  if (bare && unit === bareUnit) return n;
  return `${n}${unit}`;
}

export const LENGTH_UNITS: string[] = ["px", "%", "%r", "pt"];
export const ANGLE_UNITS: string[] = ["deg", "rad", "turn"];

// `number` in unit `from` as the same quantity in unit `to`, or null where
// the two are not commensurable without a device: degrees and turns are
// (a turn is 360 degrees); `px`, `%`, `%r` and `pt` each measure against
// something only the watch knows (its screen, the parent box, a font),
// and a radian would round.
export function convertQuantity(number: number, from: string, to: string): number | null {
  if (from === to) return number;
  if (from === "deg" && to === "turn") return number / 360;
  if (from === "turn" && to === "deg") return number * 360;
  return null;
}

// The length units a key of an element of `type` may be written in: `pt`
// measures against the element's own font, which only text and data have.
export function lengthUnitsFor(type: string): string[] {
  return type === "text" || type === "data" ? LENGTH_UNITS : LENGTH_UNITS.filter((u) => u !== "pt");
}

// `#RGB` or `#RRGGBB` (the `#` optional, as the schema allows) -> [r, g, b].
export function parseHex(value: unknown): RGB | null {
  if (typeof value !== "string") return null;
  const m = value.trim().match(/^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/);
  if (!m) return null;
  const digits = m[1]!;
  const h = digits.length === 3 ? digits.split("").map((c) => c + c).join("") : digits;
  const channel = (i: number): number => parseInt(h.slice(i, i + 2), 16);
  return [channel(0), channel(2), channel(4)];
}

export function toHex(rgb: readonly number[]): string {
  return "#" + rgb.map((c) => c.toString(16).padStart(2, "0").toUpperCase()).join("");
}

const MIP = [0x00, 0x55, 0xaa, 0xff];

// Whether a 64-colour MIP panel shows the colour exactly (every channel
// one of 00/55/AA/FF), and the nearest one it does show.
export function mipLegal(rgb: readonly number[]): boolean {
  return rgb.every((c) => MIP.includes(c));
}

export function mipNearest(rgb: RGB): RGB {
  const near = (c: number): number => MIP.reduce((a, b) => (Math.abs(b - c) < Math.abs(a - c) ? b : a));
  return [near(rgb[0]), near(rgb[1]), near(rgb[2])];
}

// A `color.<name>` reference's name, or null.
export function colorName(value: unknown): string | null {
  const m = typeof value === "string" && value.match(/^color\.([A-Za-z_][A-Za-z0-9_]*)$/);
  return m ? m[1]! : null;
}

// A name the format accepts for a colour, font or style entry.
export function isIdentifier(text: string): boolean {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(text);
}

/** What a `config: style:` entry names: a layout, a scheme, or both. */
export interface StyleShape {
  layout?: string | null;
  scheme?: string | null;
}

// A new `config: style:` entry, shaped like the entries already there: once
// one entry names a layout or a scheme, every entry must. With none yet, a
// layout when the face has layouts, else a scheme.
export function newStyleEntry(entries: readonly StyleShape[], layouts: readonly string[], schemes: readonly string[]): { layout?: string; scheme?: string } {
  const like = entries[0];
  const entry: { layout?: string; scheme?: string } = {};
  if (like ? like.layout : layouts.length) entry.layout = like?.layout || layouts[0]!;
  if (like ? like.scheme : !layouts.length) entry.scheme = like?.scheme || schemes[0]!;
  return entry;
}

// The value at `path` inside nested `data`, or undefined.
export function at(data: unknown, path: readonly (string | number)[]): unknown {
  return path.reduce<unknown>((d, k) => (d == null ? undefined : (d as Record<string | number, unknown>)[k]), data);
}

// The name the editor gives a colour it adds (`src/edit/colors.ts`): its MIP
// name when it is one of the 64 (`mip`, the vocabulary's table), else `c`
// and its hex.
export function automaticName(rgb: RGB, mip: readonly MipColor[] | undefined): string {
  const hex = toHex(rgb);
  const named = (mip || []).find((m) => m.value === hex);
  return named ? named.name : "c" + hex.slice(1);
}

// What a pick of `rgb` writes: the swatch already holding it, or the name
// it will be added under.
export function swatchFor(rgb: RGB, palette: readonly PaletteEntry[] | undefined, mip: readonly MipColor[] | undefined): { name: string; adds: boolean } {
  const hex = toHex(rgb);
  const held = (palette || []).find((p) => { const v = parseHex(p.value); return v && toHex(v) === hex; });
  return held ? { name: held.name, adds: false } : { name: automaticName(rgb, mip), adds: true };
}

// sRGB channel -> linear, and the 2-colour rule: nearer white above the
// luminance where contrast with black equals contrast with white
// (`src/palette.ts's MONO_CROSSOVER`).
function linear(c: number): number {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}
const MONO_CROSSOVER = Math.sqrt(1.05 * 0.05) - 0.05;

// Whether a screen of each of `displays` (colour counts) shows `rgb` as
// written, and the nearest colour that every one of them does: the 64-colour
// snap, then black or white for a 2-colour screen.
export function safeOn(rgb: RGB, displays: readonly number[] | undefined): { ok: boolean; nearest: RGB } {
  let out = rgb;
  if ((displays || []).includes(64)) out = mipNearest(out);
  if ((displays || []).includes(2)) {
    const y = 0.2126 * linear(out[0]) + 0.7152 * linear(out[1]) + 0.0722 * linear(out[2]);
    out = y > MONO_CROSSOVER ? [255, 255, 255] : [0, 0, 0];
  }
  return { ok: toHex(out) === toHex(rgb), nearest: out };
}

// What removing the schemes does to the style entries
// (`src/edit/schemes.ts's removeTheme`): an entry naming only a scheme goes, one
// naming a layout stays, and a kept entry whose layout an earlier one has
// already is a duplicate the author resolves.
export function afterRemovingSchemes(entries: readonly StyleShape[] | undefined): { removed: number; duplicates: number } {
  const seen = new Set<string>();
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
// choice is one cache key on the worker.
export function picksParam(picks: Readonly<Record<string, string | undefined>> | null | undefined, slots: readonly SlotEntry[] | undefined): string {
  return (slots || [])
    .filter((s) => picks && picks[s.name] && picks[s.name] !== s.default)
    .map((s) => `${s.name}:${picks![s.name]}`).sort().join(",");
}

// A complication type's name for people, from the vocabulary.
export function typeLabel(vocab: { complication_types?: readonly ComplicationType[] } | null | undefined, name: string): string {
  const t = ((vocab && vocab.complication_types) || []).find((x) => x.name === name);
  return t ? t.label : name;
}

// The diagnostics' count per severity, `{error, warning, note}`.
export function severityCounts(items: readonly Diagnostic[]): Record<Severity, number> {
  const out: Record<Severity, number> = { error: 0, warning: 0, note: 0 };
  for (const d of items) out[d.severity] = (out[d.severity] || 0) + 1;
  return out;
}

// The diagnostics a filter shows ("all", or one severity), most severe
// first, in their own order within a severity.
export function shownDiagnostics(items: readonly Diagnostic[], filter: "all" | Severity = "all"): Diagnostic[] {
  const order: Record<string, number> = { error: 0, warning: 1, note: 2 };
  const kept = filter === "all" ? items : items.filter((d) => d.severity === filter);
  return kept.map((d, i): [Diagnostic, number] => [d, i])
    .sort(([a, i], [b, j]) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3) || i - j)
    .map(([d]) => d);
}

/**
 * The edits that accept the lint `code` on the element at `element`, with
 * `reason`: its `lint:` block written whole when it has none; else `code`
 * appended to the `allow:` it has (made when missing), and the reason set
 * only when it differs from the one written. `written` is the element's
 * `lint:` as written, or null.
 */
export function lintSteps(element: Path, code: string, reason: string, written: Value | null | undefined): EditOp[] {
  const lint: Path = [...element, "lint"];
  const block = written !== null && typeof written === "object" && !Array.isArray(written) ? written : null;
  if (block === null) return [{ op: "set", path: lint, value: { allow: [code], reason } }];
  const steps: EditOp[] = [];
  const allow = block["allow"];
  if (!Array.isArray(allow)) steps.push({ op: "set", path: [...lint, "allow"], value: [code] });
  else if (!allow.includes(code)) steps.push({ op: "insert_item", path: [...lint, "allow"], at: allow.length, value: code });
  if (reason !== "" && reason !== block["reason"]) steps.push({ op: "set", path: [...lint, "reason"], value: reason });
  return steps;
}
