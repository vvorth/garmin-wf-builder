// Colour parsing and the palette rules.
//
// On a 64-colour panel each channel must be one of 0x00, 0x55, 0xAA or
// 0xFF; anything else is dithered by the firmware and looks grainy. The
// check is exact arithmetic against the device's documented palette size,
// and a warning, not an error, because a deliberate dithered colour is a
// legitimate choice.
//
// On a 2-colour panel (the Instinct family) only black and white are safe.
// The nearest safe colour is the one with the lower contrast ratio against
// it, the luminance measure the contrast lint uses. 8- and 14-colour panels
// have no known rule, and 65,536 colours need none.
//
// Both rules are tables here (`MIP64_SNAP`, `MONO_LUMINANCE`), which
// `Color.nearestLegal` and the preview's per-pixel snap both read, so a
// warning's "nearest" colour is exactly what the preview draws.
import { quoted } from "./py.ts";

const HEX = /^#?([0-9a-fA-F]{6})$/;
const SHORT_HEX = /^#?([0-9a-fA-F]{3})$/;

/** The four legal channel values on a 64-colour device. */
export const MIP64_LEVELS = [0x00, 0x55, 0xaa, 0xff] as const;

/** The 64-colour rule as a table: each channel value's nearest legal level (the lower on a tie, as Python's `min`). */
export const MIP64_SNAP: Uint8Array = Uint8Array.from({ length: 256 }, (_, value) => {
  let best: number = MIP64_LEVELS[0];
  for (const level of MIP64_LEVELS) if (Math.abs(level - value) < Math.abs(best - value)) best = level;
  return best;
});

/** Rec. 709 luminance weights, red, green, blue. */
export const LUMINANCE_WEIGHTS = [0.2126, 0.7152, 0.0722] as const;

/** The 64 colours a MIP panel shows, named: `[name, "#RRGGBB", label]`, white to black. */
export const MIP64_NAMED: readonly (readonly [string, string, string])[] = [
  ["white", "#FFFFFF", "White"],
  ["shalimar", "#FFFFAA", "Shalimar"],
  ["laser_lemon", "#FFFF55", "Laser Lemon"],
  ["yellow", "#FFFF00", "Yellow"],
  ["lavender_rose", "#FFAAFF", "Lavender Rose"],
  ["sundown", "#FFAAAA", "Sundown"],
  ["texas_rose", "#FFAA55", "Texas Rose"],
  ["web_orange", "#FFAA00", "Web Orange"],
  ["pink_flamingo", "#FF55FF", "Pink Flamingo"],
  ["brilliant_rose", "#FF55AA", "Brilliant Rose"],
  ["sunset_orange", "#FF5555", "Sunset Orange"],
  ["international_orange", "#FF5500", "International Orange"],
  ["magenta_fuchsia", "#FF00FF", "Magenta Fuchsia"],
  ["hollywood_cerise", "#FF00AA", "Hollywood Cerise"],
  ["razzmatazz", "#FF0055", "Razzmatazz"],
  ["red", "#FF0000", "Red"],
  ["pale_turquoise", "#AAFFFF", "Pale Turquoise"],
  ["mint_green", "#AAFFAA", "Mint Green"],
  ["conifer", "#AAFF55", "Conifer"],
  ["spring_bud", "#AAFF00", "Spring Bud"],
  ["perano", "#AAAAFF", "Perano"],
  ["silver_chalice", "#AAAAAA", "Silver Chalice"],
  ["olive_green", "#AAAA55", "Olive Green"],
  ["citrus", "#AAAA00", "Citrus"],
  ["medium_purple", "#AA55FF", "Medium Purple"],
  ["violet_blue", "#AA55AA", "Violet Blue"],
  ["apple_blossom", "#AA5555", "Apple Blossom"],
  ["rust", "#AA5500", "Rust"],
  ["electric_violet", "#AA00FF", "Electric Violet"],
  ["dark_magenta", "#AA00AA", "Dark Magenta"],
  ["jazzberry_jam", "#AA0055", "Jazzberry Jam"],
  ["bright_red", "#AA0000", "Bright Red"],
  ["baby_blue", "#55FFFF", "Baby Blue"],
  ["medium_aquamarine", "#55FFAA", "Medium Aquamarine"],
  ["screamin_green", "#55FF55", "Screamin' Green"],
  ["bright_green", "#55FF00", "Bright Green"],
  ["cornflower_blue", "#55AAFF", "Cornflower Blue"],
  ["cadet_blue", "#55AAAA", "Cadet Blue"],
  ["fruit_salad", "#55AA55", "Fruit Salad"],
  ["kelly_green", "#55AA00", "Kelly Green"],
  ["neon_blue", "#5555FF", "Neon Blue"],
  ["rich_blue", "#5555AA", "Rich Blue"],
  ["emperor", "#555555", "Emperor"],
  ["verdun_green", "#555500", "Verdun Green"],
  ["electric_indigo", "#5500FF", "Electric Indigo"],
  ["indigo", "#5500AA", "Indigo"],
  ["tyrian_purple", "#550055", "Tyrian Purple"],
  ["maroon", "#550000", "Maroon"],
  ["aqua", "#00FFFF", "Aqua"],
  ["medium_green", "#00FFAA", "Medium Green"],
  ["malachite", "#00FF55", "Malachite"],
  ["green", "#00FF00", "Green"],
  ["azure_radiance", "#00AAFF", "Azure Radiance"],
  ["persian_green", "#00AAAA", "Persian Green"],
  ["pigment_green", "#00AA55", "Pigment Green"],
  ["japanese_laurel", "#00AA00", "Japanese Laurel"],
  ["navy_blue", "#0055FF", "Navy Blue"],
  ["cobalt", "#0055AA", "Cobalt"],
  ["mosque", "#005555", "Mosque"],
  ["dark_green", "#005500", "Dark Green"],
  ["blue", "#0000FF", "Blue"],
  ["midnight_blue", "#0000AA", "Midnight Blue"],
  ["navy", "#000055", "Navy"],
  ["black", "#000000", "Black"],
];

const MIP64_BY_VALUE = new Map(MIP64_NAMED.map(([name, hex]) => [hex, name]));
const MIP64_LABELS = new Map(MIP64_NAMED.map(([name, , label]) => [name, label]));

/** The MIP name of a `#RRGGBB` value, or `undefined` when the colour is not one of the 64. */
export function mip64Name(value: string): string | undefined {
  return MIP64_BY_VALUE.get(value.toUpperCase());
}

/** The MIP label of a `#RRGGBB` value ("Azure Radiance"), or `undefined` when the colour is not one of the 64. */
export function mip64Label(value: string): string | undefined {
  const name = mip64Name(value);
  return name === undefined ? undefined : MIP64_LABELS.get(name);
}

/**
 * The 39 of the 64 that look good on a MIP panel and apart from each other,
 * by name, in the editor picker's order: the six hue families, then the
 * grays. A `choices: any` colour setting offers exactly these. Left out:
 * the pastels (`FF` with `AA`, off-white on the panel), the muted mixes
 * (`AA` with `55`, gray), `rust` and `citrus` (brown and olive),
 * `tyrian_purple` and `mosque`, and one of every pair that looks alike.
 * Chosen from a model of a measured MIP panel and photos of all 64 on a
 * fēnix 8 Solar, the dark colours by eye on the watch
 * (docs/research/37-mip-colour-appearance.md, 38-mip-colours-on-a-watch.md).
 */
export const MIP_RECOMMENDED: readonly string[] = [
  "sunset_orange", "razzmatazz", "red", "international_orange", "jazzberry_jam", "bright_red", "maroon",
  "texas_rose", "web_orange", "yellow", "verdun_green",
  "conifer", "screamin_green", "bright_green", "green", "malachite", "kelly_green", "japanese_laurel", "dark_green",
  "medium_aquamarine", "aqua", "azure_radiance", "pigment_green",
  "neon_blue", "navy_blue", "blue", "electric_indigo", "midnight_blue", "navy",
  "medium_purple", "pink_flamingo", "electric_violet", "magenta_fuchsia", "indigo", "dark_magenta",
  "white", "silver_chalice", "emperor", "black",
];

const PASTEL = "a pastel: looks off-white on the watch";
const MUTED = "a muted mix: looks gray on the watch";
const LIKE = (label: string): string => `looks like ${label} on the watch`;

/**
 * Why each of the 64 that `MIP_RECOMMENDED` leaves out is left out, as the
 * editor's colour picker says it; a look-alike names the recommended colour
 * nearest it on the watch.
 */
export const MIP_LEFT_OUT: Readonly<Record<string, string>> = {
  shalimar: PASTEL, lavender_rose: PASTEL, sundown: PASTEL, pale_turquoise: PASTEL, mint_green: PASTEL, perano: PASTEL,
  olive_green: MUTED, violet_blue: MUTED, apple_blossom: MUTED, cadet_blue: MUTED, fruit_salad: MUTED, rich_blue: MUTED,
  rust: "looks brown on the watch", citrus: "looks olive on the watch",
  tyrian_purple: "dark: dim on the watch, and hard to see on black", mosque: "dark: dim on the watch, and hard to see on black",
  laser_lemon: LIKE("Conifer"), spring_bud: LIKE("Yellow"), brilliant_rose: LIKE("Pink Flamingo"),
  hollywood_cerise: LIKE("Magenta Fuchsia"), baby_blue: LIKE("Medium Aquamarine"), cornflower_blue: LIKE("Azure Radiance"),
  medium_green: LIKE("Aqua"), persian_green: LIKE("Azure Radiance"), cobalt: LIKE("Navy Blue"),
};

export class ColorError extends Error {}

export class Color {
  readonly r: number;
  readonly g: number;
  readonly b: number;

  constructor(r: number, g: number, b: number) {
    this.r = r;
    this.g = g;
    this.b = b;
  }

  static parse(raw: unknown, what = "color"): Color {
    if (raw instanceof Color) return raw;
    if (typeof raw === "number" && Number.isInteger(raw)) return new Color((raw >> 16) & 0xff, (raw >> 8) & 0xff, raw & 0xff);
    if (typeof raw !== "string") throw new ColorError(`${what}: expected a colour such as '#FF8000', got ${quoted(raw)}`);
    const text = raw.trim();
    let m = HEX.exec(text);
    if (m) {
      const v = parseInt(m[1]!, 16);
      return new Color((v >> 16) & 0xff, (v >> 8) & 0xff, v & 0xff);
    }
    m = SHORT_HEX.exec(text);
    if (m) {
      const d = m[1]!;
      return new Color(parseInt(d[0]! + d[0]!, 16), parseInt(d[1]! + d[1]!, 16), parseInt(d[2]! + d[2]!, 16));
    }
    throw new ColorError(`${what}: ${quoted(raw)} is not a colour.  Use '#RRGGBB' or '#RGB'`);
  }

  get value(): number {
    return (this.r << 16) | (this.g << 8) | this.b;
  }

  asMonkeyc(): string {
    return `0x${this.value.toString(16).toUpperCase().padStart(6, "0")}`;
  }

  equals(other: Color): boolean {
    return this.r === other.r && this.g === other.g && this.b === other.b;
  }

  /** Whether the panel is known to show this colour as written: the 64-colour MIP rule, or black and white on a 2-colour panel. */
  isPaletteLegal(displayColors: number | null): boolean {
    if (displayColors === 64) return [this.r, this.g, this.b].every((c) => (MIP64_LEVELS as readonly number[]).includes(c));
    if (displayColors === 2) return this.equals(BLACK) || this.equals(WHITE);
    return true;
  }

  nearestLegal(displayColors: number | null): Color {
    if (displayColors === 64) return new Color(MIP64_SNAP[this.r]!, MIP64_SNAP[this.g]!, MIP64_SNAP[this.b]!);
    if (displayColors === 2) {
      const units = MONO_LUMINANCE[0]![this.r]! + MONO_LUMINANCE[1]![this.g]! + MONO_LUMINANCE[2]![this.b]!;
      return units > MONO_THRESHOLD ? WHITE : BLACK;
    }
    return this;
  }

  /** WCAG relative luminance: Rec. 709 primaries over sRGB-degamma'd channels. */
  relativeLuminance(): number {
    const [red, green, blue] = LUMINANCE_WEIGHTS;
    return red * srgbChannelToLinear(this.r) + green * srgbChannelToLinear(this.g) + blue * srgbChannelToLinear(this.b);
  }

  contrastRatio(other: Color): number {
    const a = this.relativeLuminance(), b = other.relativeLuminance();
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  }

  /** `#RRGGBB`, upper case: Python's `str(color)`. */
  toString(): string {
    return `#${this.value.toString(16).toUpperCase().padStart(6, "0")}`;
  }

  /** Scale the luminance by `num/den` (`aod: {dim: ...}`), each channel by `dimChannel`'s integer arithmetic. */
  dim(num: number, den: number): Color {
    return new Color(dimChannel(this.r, num, den), dimChannel(this.g, num, den), dimChannel(this.b, num, den));
  }
}

export const BLACK = new Color(0x00, 0x00, 0x00);
export const WHITE = new Color(0xff, 0xff, 0xff);

/** The relative luminance at which a colour's contrast against black equals its contrast against white: about 0.179. */
export const MONO_CROSSOVER = Math.sqrt(1.05 * 0.05) - 0.05;

/** Whether `Color.isPaletteLegal` can answer for this palette size: 2 and 64 have a rule, 65,536 needs none. */
export function hasPaletteRule(displayColors: number | null): boolean {
  return displayColors === 2 || displayColors === 64 || (displayColors !== null && displayColors >= 65536);
}

/** One 0-255 sRGB channel as linear 0-1, the sRGB EOTF. */
export function srgbChannelToLinear(value: number): number {
  const s = value / 255.0;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

/** Relative luminance 1.0 in the integer units of `MONO_LUMINANCE`. */
export const MONO_SCALE = 65535;

/** Python's `round()`: half to even. Here a tie needs an exact `.5`, which these products never land on. */
function round(value: number): number {
  const floor = Math.floor(value);
  const diff = value - floor;
  return diff > 0.5 ? floor + 1 : diff < 0.5 ? floor : floor % 2 === 0 ? floor : floor + 1;
}

/** The 2-colour rule as tables: each channel value's share of relative luminance, in 1/`MONO_SCALE` units, one table per channel. */
export const MONO_LUMINANCE: readonly Int32Array[] = LUMINANCE_WEIGHTS.map((weight) =>
  Int32Array.from({ length: 256 }, (_, value) => round(weight * srgbChannelToLinear(value) * MONO_SCALE)));

/** `MONO_CROSSOVER` in `MONO_LUMINANCE`'s units. */
export const MONO_THRESHOLD = round(MONO_CROSSOVER * MONO_SCALE);

/**
 * One 0-255 channel scaled by `num/den`, rounded to the nearest integer
 * (ties up) with integer arithmetic only, so the build, the generated
 * `WfbColor.dim` and the preview agree bit for bit.
 */
export function dimChannel(value: number, num: number, den: number): number {
  return Math.max(0, Math.min(255, Math.floor((value * num + Math.floor(den / 2)) / den)));
}

/** An `aod: {dim: ...}` factor as the `[num, den]` ratio `dimChannel` uses, over 1000. */
export function dimFraction(dim: number): [number, number] {
  return [round(dim * 1000), 1000];
}
