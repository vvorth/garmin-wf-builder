// Icons: the catalogue's names, codepoint spellings, and the weather and
// complication icon tables. Baking
// and measuring a glyph come with the font stage. The tables are
// `data/icons.json`, exported by tools/export_tables.py.
//
// Whether the icon font has a codepoint is read from its character map,
// handed in as a set (`setIconFontGlyphs`): Node reads the installed font,
// the browser receives it from the server.
import data from "./data/icons.json" with { type: "json" };
import type { Device } from "./devices/device.ts";
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

/** Degrees between two baked turns of a free-end radial icon: the worst snap is half of it. */
export const TURN_STEP = 3;

/** Where a radial pair's icon sits when its place depends on the reading's width. */
export type FreePlace = "after" | "before" | "center_left" | "center_right";

/** A radial run on one device: its circle's radius, the radius its advances are laid out along, and its widest reading. */
export interface RunGeometry {
  radius: number;
  spacing: number;
  /** In pixels; 0 where the reading does not draw. */
  widest: number;
}

/** A free-end icon's path: its centre is at `theta + perPx * textWidth` radians (Garmin's convention). */
export interface IconPath {
  theta: number;
  perPx: number;
  /** Where the text is drawn, Garmin degrees: a centred pair's text is shifted so the pair centres on the authored angle. */
  textGarmin: number;
}

/** A free-end icon's baked turns on one device: step `i` is the icon centred at `first + i * size` radians. */
export interface IconSteps {
  first: number;
  size: number;
  count: number;
  /** The step for a reading of width `w` is `round(w * perPx)`. */
  perPx: number;
}

/**
 * A radial pair's icon at the run's free end, or beside a centred run: its
 * angle follows the reading's width, which only the watch knows. Its glyphs
 * are baked at `TURN_STEP` steps covering every angle the widest reading can
 * push it to on a device, and the watch draws the nearest. The bake and the
 * layout resolve it here, with the same arithmetic.
 */
export class SteppedTurn {
  /** The authored angle, in Garmin degrees. */
  readonly startGarmin: number;
  readonly gap: Length;
  readonly place: FreePlace;
  readonly direction: string | null;
  readonly run: (device: Device) => RunGeometry;

  constructor(startGarmin: number, gap: Length, place: FreePlace, direction: string | null, run: (device: Device) => RunGeometry) {
    this.startGarmin = startGarmin;
    this.gap = gap;
    this.place = place;
    this.direction = direction;
    this.run = run;
  }

  /**
   * The icon centre's angle as a function of the reading's width, for a
   * reference glyph of this upright advance. The reading spans `width /
   * spacing` radians; the gap and the icon are arc lengths on the run's circle.
   */
  path(device: Device, advance: number): IconPath {
    // A clockwise run walks towards smaller Garmin angles; `ahead` is +1 where the icon follows the run.
    const sign = this.direction === "counter_clockwise" ? 1 : -1;
    const { radius, spacing } = this.run(device);
    const gap = pixelSize(this.gap, device.minorRadius);
    const centred = this.place === "center_left" || this.place === "center_right";
    const ahead = this.place === "after" || this.place === "center_right" ? 1 : -1;
    const k = (sign * ahead) / (centred ? 2 : 1);
    // Free end: width/spacing + (gap + advance/2)/radius past the fixed end. Centred: the pair spans
    // width/spacing + (gap + advance)/radius about the authored angle, so the icon sits half of width/spacing + gap/radius off it.
    const lead = (centred ? gap : gap + advance / 2) / radius;
    const shift = centred ? (-ahead * sign * (advance + gap)) / 2 / radius : 0;
    return { theta: (this.startGarmin * Math.PI) / 180 + k * lead, perPx: k / spacing, textGarmin: this.startGarmin + (shift * 180) / Math.PI };
  }

  /** The turns baked on `device`: from the shortest reading's angle to the widest's, `TURN_STEP` apart. */
  steps(device: Device, advance: number): IconSteps {
    const { theta, perPx } = this.path(device, advance);
    const step = (TURN_STEP * Math.PI) / 180;
    const sweep = Math.abs(perPx) * this.run(device).widest;
    return { first: theta, size: perPx < 0 ? -step : step, count: Math.floor(sweep / step + 0.5) + 1, perPx: Math.abs(perPx) / step };
  }

  /** Degrees clockwise to bake an icon centred at `theta` radians: tops outward on a clockwise run, inward on a counter-clockwise one. */
  turnAt(theta: number): number {
    return normalTurn((this.direction === "counter_clockwise" ? 270 : 90) - (theta * 180) / Math.PI);
  }
}

/** The font key of step `index` of a free-end icon's font `key`. */
export function stepKey(key: string, index: number): string {
  return `${key}_s${index}`;
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
