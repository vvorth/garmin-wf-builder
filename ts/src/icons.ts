// Icons: the catalogue's names, codepoint spellings, and the weather and
// complication icon tables. Port of wfb/icons.py's build-time half; baking
// and measuring a glyph come with the font stage. The tables are
// `data/icons.json`, exported by tools/export_tables.py.
//
// Whether the icon font has a codepoint is read from its character map,
// handed in as a set (`setIconFontGlyphs`): Node reads the installed font,
// the browser receives it from the server.
import data from "./data/icons.json" with { type: "json" };
import { formatG } from "./py.ts";
import type { Length } from "./units.ts";

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

/** Whether `text` is written `U+XXXX`: an `icon:` naming a codepoint rather than a catalogue entry. */
export function isCodepointSpelling(text: string): boolean {
  return CODEPOINT.test(text);
}

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
    throw new IconFontMissing(available ?? "the icon font is not installed: run tools/setup-env.sh, or python3 tools/fetch-icon-font.py");
  }
  return available.has(character);
}

/** A catalogue name's glyph, or `null` if the catalogue does not name it. */
export function resolveCodepoint(name: string): string | null {
  return CATALOG.get(name)?.codepoint ?? null;
}

const UNIT_WORD: Readonly<Record<string, string>> = { "%r": "pctr", "%": "pct", px: "px", pt: "pt" };

export const DYNAMIC_WEATHER_TAG = "weather";

/** The synthetic font name for every icon declared at this `size:`, glyph and anti-aliasing setting. */
export function fontKey(length: Length | null, glyphKey: string, antialias = false): string {
  let unitValue: string;
  if (length === null) unitValue = "default";
  else unitValue = `${formatG(length.value).replaceAll(".", "p").replaceAll("-", "neg")}${UNIT_WORD[length.unit]}`;
  const glyphId = Array.from(glyphKey).length === 1 ? `u${glyphKey.codePointAt(0)!.toString(16)}` : glyphKey;
  return `icon_${unitValue}_${glyphId}${antialias ? "_aa" : ""}`;
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
