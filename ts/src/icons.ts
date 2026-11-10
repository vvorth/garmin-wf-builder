// Icons: the catalogue's names, codepoint spellings, the icon rules (an
// icon that follows a reading) and the complication icon table. Baking and
// measuring a glyph come with the font stage. The tables are
// `data/icons.json`.
//
// Whether the icon font has a codepoint is read from its character map,
// handed in as a set (`setIconFontGlyphs`): Node reads the installed font,
// the browser receives it from the server.
import { familyPath, get as sourceOf } from "./catalog.ts";
import data from "./data/icons.json" with { type: "json" };
import type { Device } from "./devices/device.ts";
import { WholeFloat } from "./edit/yaml.ts";
import { COMPOSITES } from "./fonts/composite.ts";
import { formatG, num } from "./py.ts";
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

/** Is this character in the icon font's own character map, or a composite of a glyph that is? */
export function fontHas(character: string): boolean {
  if (available === undefined || typeof available === "string") {
    throw new IconFontMissing(available ?? "the icon font is not installed: run tools/setup-env.sh, or node ts/tools/fetch-icon-font.ts");
  }
  return available.has(character) || available.has(COMPOSITES.get(character)?.base ?? "");
}

/** A catalogue name's glyph, or `null` if the catalogue does not name it. */
export function resolveCodepoint(name: string): string | null {
  return CATALOG.get(name)?.codepoint ?? null;
}

const UNIT_WORD: Readonly<Record<string, string>> = { "%r": "pctr", "%": "pct", px: "px", pt: "pt" };

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

export const WEATHER_BAKE_REFERENCE_GLYPH: string = CATALOG.get("weather_rainy")!.codepoint;

/** Each complication type with a catalogue icon of its own. */
export const COMPLICATION_ICON: ReadonlyMap<string, string> = new Map(Object.entries(data.complication_icon));

/**
 * An icon that follows a reading: a rule from `data/icons.json`'s `rules`.
 * A `steps` rule orders its glyphs along a numeric reading, split into equal
 * bands over `range` or at `thresholds`; a `table` rule maps an
 * enumeration's values to names one by one. `plain` is drawn without a
 * reading, and, for a table, for a value the map does not name. The watch
 * chooses with `IconGlyphs.<name>Icon`, generated from this.
 */
export interface IconRule {
  readonly name: string;
  readonly kind: "steps" | "table";
  /** What the reading is, as the editor names it. */
  readonly label: string;
  readonly plain: string;
  /** The sources whose reading the rule follows, as `icon: {for:}` and a slot's type name them. */
  readonly sources: readonly string[];
  /** A steps rule's glyphs, lowest band first; empty for a table. */
  readonly steps: readonly string[];
  /** Equal bands over `[lo, hi]`; `null` where `thresholds` splits them, and for a table. */
  readonly range: readonly [number, number] | null;
  /** `range` wraps round: band 0 is centred on `lo` and takes the half-band either side of it. */
  readonly cyclic: boolean;
  /** Band k is the count of thresholds at or below the reading; `null` where `range` splits them, and for a table. */
  readonly thresholds: readonly number[] | null;
  /** A table rule's value to catalogue name; empty for a steps rule. */
  readonly map: ReadonlyMap<number, string>;
  /** A complication source that carries none of the rule's reading itself, to the source read beside it. */
  readonly follows: ReadonlyMap<string, string>;
}

interface RuleJson {
  kind: "steps" | "table"; label: string; plain: string; sources: string[];
  steps?: string[]; range?: [number, number]; cyclic?: boolean; thresholds?: number[];
  map?: Record<string, string>; follows?: Record<string, string>;
}

/** Every icon rule, in the table's order: the order `IconGlyphs` defines their choosers in. */
export const RULES: ReadonlyMap<string, IconRule> = new Map(Object.entries(data.rules as unknown as Record<string, RuleJson>).map(([name, r]) => [name, {
  name, kind: r.kind, label: r.label, plain: r.plain, sources: r.sources, steps: r.steps ?? [], range: r.range ?? null,
  cyclic: r.cyclic ?? false, thresholds: r.thresholds ?? null,
  map: new Map(Object.entries(r.map ?? {}).map(([k, v]) => [Number(k), v])), follows: new Map(Object.entries(r.follows ?? {})),
}]));

/** Rules by source; an indexed path (`weather.daily_forecast[1].condition`) finds its family's, listed with `[n]`. */
class RulesBySource extends Map<string, IconRule> {
  override get(source: string): IconRule | undefined {
    return super.get(source) ?? (source.includes("[") ? super.get(familyPath(source)) : undefined);
  }

  override has(source: string): boolean {
    return this.get(source) !== undefined;
  }
}

/** The rule each source's reading follows. */
export const RULE_OF_SOURCE: ReadonlyMap<string, IconRule> = new RulesBySource([...RULES.values()].flatMap((rule) => rule.sources.map((s) => [s, rule] as const)));

/** A source whose icon follows a rule's reading taken beside it (a temperature the weather condition): the rule and the source read. */
export const RULE_FOLLOWED: ReadonlyMap<string, { rule: IconRule; source: string }> =
  new Map([...RULES.values()].flatMap((rule) => [...rule.follows].map(([s, source]) => [s, { rule, source }] as const)));

/**
 * The band a reading falls in, of a steps rule's `steps.length`. Over a
 * range: truncated, as the watch's `toNumber()` truncates, then clamped, or,
 * cyclic, shifted half a band and wrapped round. At thresholds: how many are
 * at or below the reading.
 */
export function levelBand(rule: Pick<IconRule, "steps" | "range" | "cyclic" | "thresholds">, value: number): number {
  const bands = rule.steps.length;
  if (rule.range === null) return (rule.thresholds ?? []).filter((t) => t <= value).length;
  const [lo, hi] = rule.range;
  if (rule.cyclic) return ((Math.trunc(((value - lo) / (hi - lo)) * bands + 0.5) % bands) + bands) % bands;
  return Math.min(bands - 1, Math.max(0, Math.trunc(((value - lo) * bands) / (hi - lo))));
}

/** A reading as a steps rule bands it: a number (a whole float too), a boolean as 0 or 1; `null` for no reading. */
function numericReading(reading: unknown): number | null {
  if (typeof reading === "number") return reading;
  if (reading instanceof WholeFloat) return num(reading);
  if (typeof reading === "boolean") return reading ? 1 : 0;
  return null;
}

/** The catalogue name `rule` draws for `reading`: its plain icon without one, and for a value a table does not name. */
export function ruleIconName(rule: IconRule, reading: unknown): string {
  const value = numericReading(reading);
  if (value === null) return rule.plain;
  if (rule.kind === "table") return typeof reading === "boolean" ? rule.plain : rule.map.get(Math.trunc(value)) ?? rule.plain;
  return rule.steps[levelBand(rule, value)]!;
}

/**
 * Every source `rule` follows is an on/off reading, read as 0 or 1 (a rule's
 * sources are one type: `data.test.ts`). The watch binds it as a
 * `Lang.Boolean`, so its chooser compares with `true` and `false`.
 */
export function readsBoolean(rule: IconRule): boolean {
  return rule.sources.every((source) => sourceOf(source)?.type === "boolean");
}

/** A number as a rule's summary shows it: at most two decimals, no trailing zeros. */
function shortNumber(value: number): string {
  return String(Number(value.toFixed(2)));
}

/**
 * One line saying what `rule` draws, as `wfb sources` prints it under a
 * source: its glyphs in order and how the reading splits among them.
 */
export function ruleSummary(rule: IconRule): string {
  if (rule.kind === "table") {
    return `${rule.name} — ${new Set(rule.map.values()).size} glyphs over the ${rule.map.size} values it names (${rule.plain} for any other)`;
  }
  if (readsBoolean(rule)) return `${rule.name} — ${rule.steps.join(" / ")} (off / on)`;
  if (rule.range === null) {
    const thresholds = rule.thresholds ?? [];
    const said = rule.steps.map((_, k) => {
      const lower = k === 0 ? 0 : thresholds[k - 1]!;
      if (k === thresholds.length) return `${lower}+`;
      return thresholds[k]! - lower === 1 ? String(lower) : `${lower}–${thresholds[k]! - 1}`;
    });
    return `${rule.name} — ${rule.steps.join(" / ")} (${said.join(" / ")})`;
  }
  const [lo, hi] = rule.range;
  const unit = sourceOf(rule.sources[0]!)?.unit;
  const unitSaid = unit === "percent" ? "%" : unit ? ` ${unit}` : "";
  const cyclic = rule.cyclic ? ", cyclic" : "";
  return `${rule.name} — ${rule.steps.join(", ")} (${rule.steps.length} bands over ${shortNumber(lo)}–${shortNumber(hi)}${unitSaid}${cyclic})`;
}

/** The name of the generated `IconGlyphs` function choosing `rule`'s glyph. */
export function ruleFunction(rule: IconRule): string {
  return `${rule.name}Icon`;
}

/** Every catalogue name `rule` can draw, its plain one first. */
export function ruleNames(rule: IconRule): string[] {
  return [...new Set([rule.plain, ...(rule.kind === "table" ? rule.map.values() : rule.steps)])];
}

/** Every glyph `rule` can draw, its plain one included: catalogue name to glyph. */
export function ruleGlyphTable(rule: IconRule): Map<string, string> {
  return new Map(ruleNames(rule).map((name) => [name, CATALOG.get(name)!.codepoint]));
}

/**
 * A steps rule split at thresholds: a comparison per threshold, which a
 * slot's icon method writes inline rather than calling the generated chooser.
 */
export function choosesInline(rule: IconRule): boolean {
  return rule.thresholds !== null;
}

/**
 * A thresholds rule's bands below its last, in order: each from `lower` up
 * to, not including, `upper`, and the name it draws. A count, or a boolean
 * read as 0 or 1, is never below 0, so the first band starts there.
 */
export function thresholdRanges(rule: IconRule): { lower: number; upper: number; name: string }[] {
  const thresholds = rule.thresholds ?? [];
  return thresholds.map((upper, k) => ({ lower: k === 0 ? 0 : thresholds[k - 1]!, upper, name: rule.steps[k]! }));
}

/** How a thresholds band reads: `at 0` for a band one value wide, else `below <upper>`. */
export function thresholdSaid(band: { lower: number; upper: number }): string {
  return band.upper - band.lower === 1 ? `at ${band.lower}` : `below ${band.upper}`;
}

/** The rule complication type `type`'s icon follows: its `complication.<type>` source's, or that of the reading it reads beside it. */
export function complicationRule(type: string): IconRule | undefined {
  return RULE_OF_SOURCE.get(`complication.${type}`) ?? RULE_FOLLOWED.get(`complication.${type}`)?.rule;
}
