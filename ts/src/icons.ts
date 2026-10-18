// Icons: the catalogue's names, codepoint spellings, and the weather and
// complication icon tables. Baking
// and measuring a glyph come with the font stage. The tables are
// `data/icons.json`, exported by tools/export_tables.py.
//
// Whether the icon font has a codepoint is read from its character map,
// handed in as a set (`setIconFontGlyphs`): Node reads the installed font,
// the browser receives it from the server.
import data from "./data/icons.json" with { type: "json" };
import { formatG } from "./py.ts";
import { type Length, pixelSize } from "./units.ts";

export interface Icon { name: string; codepoint: string; description: string }

/** One resolved icon for one complication type: a catalogue name (or `U+XXXX`) and the character itself. */
export class SlotIcon {
  readonly key: string;
  readonly codepoint: string;

  constructor(key: string, codepoint: string) {
    this.key = key;
    this.codepoint = codepoint;
  }
}

export const CATALOG: ReadonlyMap<string, Icon> = new Map(Object.entries(data.catalog as Record<string, Icon>));

/** The glyph drawn for an unknown icon. */
export const FALLBACK_CODEPOINT = "";

export function names(): string[] {
  return [...CATALOG.keys()].sort();
}

const CODEPOINT = /^[Uu]\+([0-9A-Fa-f]{1,6})$/;

/** `"U+F0BC"` to the character, or `null` when it is not that notation. */
export function parseCodepoint(text: string): string | null {
  const m = CODEPOINT.exec(text.trim());
  if (m === null) return null;
  const value = parseInt(m[1]!, 16);
  return value <= 0x10ffff ? String.fromCodePoint(value) : null;
}

/** The canonical `"U+XXXX"` spelling for a character: at least 4 hex digits, upper case. */
export function codepointKey(character: string): string {
  return `U+${character.codePointAt(0)!.toString(16).toUpperCase().padStart(4, "0")}`;
}

/** The catalogue name for a character, if it has one. */
export function nameForCodepoint(character: string): string | null {
  for (const [name, icon] of CATALOG) if (icon.codepoint === character) return name;
  return null;
}

/** The icon font is not installed; the message names the fix. */
export class IconFontMissing extends Error {}

let available: ReadonlySet<string> | string | undefined;

/** The icon font's character map, as characters, or why there is none (the `IconFontMissing` message). */
export function setIconFontGlyphs(glyphs: ReadonlySet<string> | string): void {
  available = glyphs;
}

/** Is this character in the icon font's own character map? */
export function fontHas(character: string): boolean {
  if (available === undefined || typeof available === "string") {
    throw new IconFontMissing(available ?? "the icon font is not installed: run tools/setup-env.sh, or node ts/tools/fetch-icon-font.ts");
  }
  return available.has(character);
}

/** A catalogue name's glyph, or `null` if the catalogue does not name it. */
export function resolveCodepoint(name: string): string | null {
  return CATALOG.get(name)?.codepoint ?? null;
}

const UNIT_WORD: Readonly<Record<string, string>> = { "%r": "pctr", "%": "pct", px: "px", pt: "pt" };

export const DYNAMIC_WEATHER_TAG = "weather";

/** `degrees` as a turn in [0, 360): what a font key and a bake are told. */
export function normalTurn(degrees: number): number {
  const turn = ((degrees % 360) + 360) % 360;
  return turn === 0 ? 0 : turn;
}

/**
 * A radial pair's icon pinned to the run's fixed end: where its centre sits
 * on the circle and how far its glyphs turn. Every input is per device (the
 * radius, the gap, the reference glyph's advance at its baked size), so the
 * bake and the layout each resolve it here, with the same arithmetic.
 */
export class PinnedTurn {
  /** The run's fixed end, in Garmin degrees (3 o'clock = 0, counter-clockwise). */
  readonly startGarmin: number;
  readonly radius: Length;
  readonly gap: Length;
  /** The icon sits after the run's end (`align: right`), not before its start. */
  readonly after: boolean;
  readonly direction: string | null;

  constructor(startGarmin: number, radius: Length, gap: Length, after: boolean, direction: string | null) {
    this.startGarmin = startGarmin;
    this.radius = radius;
    this.gap = gap;
    this.after = after;
    this.direction = direction;
  }

  /** The icon centre's Garmin angle: the gap plus half the reference advance, as arc length past the fixed end. */
  angle(minorRadius: number, advance: number): number {
    // A clockwise run walks towards smaller Garmin angles.
    const sign = this.direction === "counter_clockwise" ? 1 : -1;
    const along = (pixelSize(this.gap, minorRadius) + advance / 2) / pixelSize(this.radius, minorRadius);
    return this.startGarmin + (this.after ? sign : -sign) * (along * 180) / Math.PI;
  }

  /** Degrees clockwise to bake the glyphs at: tops outward on a clockwise run, inward on a counter-clockwise one. */
  turn(minorRadius: number, advance: number): number {
    return normalTurn((this.direction === "counter_clockwise" ? 270 : 90) - this.angle(minorRadius, advance));
  }
}

/** The synthetic font name for every icon declared at this `size:`, glyph, anti-aliasing setting and turn. */
export function fontKey(length: Length | null, glyphKey: string, antialias = false, rotate = 0): string {
  let unitValue: string;
  if (length === null) unitValue = "default";
  else unitValue = `${formatG(length.value).replaceAll(".", "p").replaceAll("-", "neg")}${UNIT_WORD[length.unit]}`;
  const glyphId = Array.from(glyphKey).length === 1 ? `u${glyphKey.codePointAt(0)!.toString(16)}` : glyphKey;
  const turn = normalTurn(rotate);
  const turnId = turn === 0 ? "" : `_r${formatG(turn).replaceAll(".", "p")}`;
  return `icon_${unitValue}_${glyphId}${turnId}${antialias ? "_aa" : ""}`;
}

/** `Weather.CONDITION_*` to the catalogue name its glyph comes from. */
export const GARMIN_WEATHER_CONDITION_ICON: ReadonlyMap<number, string> =
  new Map(Object.entries(data.garmin_weather_condition_icon).map(([k, v]) => [Number(k), v]));

/** Every weather glyph, sorted by code point. */
export const WEATHER_GLYPH_SET: string = [...new Set([...GARMIN_WEATHER_CONDITION_ICON.values()].map((n) => CATALOG.get(n)!.codepoint))]
  .sort((a, b) => a.codePointAt(0)! - b.codePointAt(0)!).join("");

/** The catalogue name `WfbWeather.chooseIcon` returns for `condition`, or `weather_unknown`. */
export function chooseWeatherIcon(condition: unknown): string {
  if (typeof condition !== "number") return "weather_unknown";
  return GARMIN_WEATHER_CONDITION_ICON.get(Math.trunc(condition)) ?? "weather_unknown";
}

export const WEATHER_BAKE_REFERENCE_GLYPH: string = CATALOG.get("weather_rain")!.codepoint;

/** Each complication type with a catalogue icon of its own. */
export const COMPLICATION_ICON: ReadonlyMap<string, string> = new Map(Object.entries(data.complication_icon));
