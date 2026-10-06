// The IR's data model: constants, every element and value class, `Face`,
// and the tree and draw-order helpers that read it. Port of
// wfb/ir/model.py; the semantic pass that builds it is ./builder/.
//
// The classes keep the Python dataclasses' field names (snake_case) and
// declaration order, so the IR compares field for field with the oracle's
// dump. A class is built with `Class.create({...})`: its defaults first,
// then the given fields, as a dataclass's constructor does.
import * as catalog from "../catalog.ts";
import * as complications from "../complications.ts";
import type { Span } from "../diagnostics.ts";
import type * as expr from "../expr.ts";
import * as icons from "../icons.ts";
import type { Color } from "../palette.ts";
import type { SeriesDef } from "../series.ts";
import * as units from "../units.ts";
import type { Angle, Length } from "../units.ts";
import { configField, fontResourceId, pascal } from "./naming.ts";

/** Build an instance of `cls` from its defaults and `init`. */
export function make<T extends object>(cls: new () => T, init: Partial<T>): T {
  return Object.assign(new cls(), init);
}

/** `modes:` means only the two MIP partial-update modes. */
export const MODES = ["active", "low_power"] as const;

/** Every key the schema accepts on a `group`, and what it does to the members. */
export const GROUP_KEYS: ReadonlyMap<string, string> = new Map([
  ["type", "structural"], ["at", "structural"], ["size", "structural"], ["align", "structural"],
  ["children", "structural"], ["visible", "conjoined"], ["antialias", "nearest"], ["min_1px", "nearest"],
  ["sleep_update", "nearest"], ["z", "nearest"], ["aod", "merged"], ["lint", "union"],
  ["on_hold", "group"], ["outline", "group"], ["unsupported", "group"], ["overrides", "structural"],
]);

export const ROLE_VALUE = "value";
export const ROLE_MAX = "max";
export const ROLE_MIN = "min";
export const ROLE_FALLBACK = "fallback";
export const ROLE_COLOR = "color";
export const ROLE_TRACK_COLOR = "track_color";
export const ROLE_ICON_COLOR = "icon_color";
export const ROLE_OUTLINE_COLOR = "outline_color";
export const ROLE_UNIT_LABEL = "unit_label";
export const ROLE_PART_VISIBLE = "part_visible";
export const ROLE_PART_TEXT = "part_text";
export const ROLE_VISIBLE = "visible";

/** `on_hold: auto`, resolved once the element has a value binding to resolve from. */
export const HOLD_AUTO = "auto";
/** The Monkey C a pattern colour's `copy` compiles to: the drawing loop's index. */
export const PATTERN_LOOP_INDEX = "i";
/** `Dc.fillPolygon`'s 64-point limit less the two corners a filled graph closes with. */
export const GRAPH_AREA_MAX_SAMPLES = 62;
/** `outline:`'s widest ring: every offset set research 14 measured stops at r=3. */
export const MAX_OUTLINE_WIDTH = 3;
/** System fonts an author may name directly, instead of a baked custom font. */
export const SYSTEM_FONTS = [
  "FONT_XTINY", "FONT_TINY", "FONT_SMALL", "FONT_MEDIUM", "FONT_LARGE",
  "FONT_NUMBER_MILD", "FONT_NUMBER_MEDIUM", "FONT_NUMBER_HOT",
  "FONT_NUMBER_THAI_HOT", "FONT_SYSTEM_MEDIUM", "FONT_SYSTEM_LARGE",
] as const;

// -- leaf value types ---------------------------------------------------------

export class Position {
  anchor = "center";
  dx: Length | null = null;
  dy: Length | null = null;
  angle: Angle | null = null;
  radius: Length | null = null;

  static create(init: Partial<Position> = {}): Position { return make(Position, init); }

  get isPolar(): boolean {
    return this.angle !== null;
  }
}

export class Size {
  width: Length | null = null;
  height: Length | null = null;

  static create(init: Partial<Size> = {}): Size { return make(Size, init); }
}

/** A compiled expression: the author's text, and the Monkey C it became. */
export class Expression {
  text = "";
  code = "";
  value!: expr.Value;
  /** Catalogue paths this expression reads, in first-use order. */
  sources: string[] = [];
  /** Support-barrel functions and Toybox modules the emitted code needs. */
  barrel: Set<string> = new Set();
  modules: Set<string> = new Set();
  span: Span | null = null;
  /** Set when the whole expression folded to a build-time constant. */
  constant: expr.ExprValue = null;
  /** The folded syntax tree, for the host preview to evaluate. */
  ast: expr.Node | null = null;
  /** What the author wrote, when it is not `text` alone: a template's placeholder expression. */
  author: string | null = null;

  static create(init: Partial<Expression>): Expression { return make(Expression, init); }

  /** The expression as a diagnostic quotes it: the author's own text. */
  get shown(): string {
    return this.author ?? this.text;
  }

  get nullable(): boolean {
    return this.value.nullable;
  }

  /** The constant factor `source / 1000` applies to its source, or 1.0. */
  get scale(): number {
    const node = this.ast;
    if (node === null || node.kind !== "binary" || (node.op !== "/" && node.op !== "*")) return 1.0;
    if (node.right.kind !== "literal") return 1.0;
    const v = node.right.value;
    const factor = typeof v === "boolean" ? Number(v) : typeof v === "number" ? v : typeof v === "bigint" ? Number(v)
      : v !== null && typeof v === "object" && "value" in v ? (v as { value: number }).value : NaN;
    if (Number.isNaN(factor) || factor === 0) return 1.0;
    return node.op === "/" ? 1.0 / factor : factor;
  }

  get isConstant(): boolean {
    return this.constant !== null;
  }
}

/** One `fonts:` entry: a baked bitmap sheet (`source:`) or a vector device-resident face (`face:`). */
export class FontSpec {
  name = "";
  size!: Length;
  span: Span | null = null;
  source: string | null = null;
  glyphs: string | null = null;
  antialias = false;
  monospace = false;
  align = "center";
  face: string[] | null = null;
  unsupported: string | null = null;

  static create(init: Partial<FontSpec>): FontSpec { return make(FontSpec, init); }

  get isBaked(): boolean { return this.source !== null; }
  get isVector(): boolean { return this.face !== null; }
  get resourceId(): string { return fontResourceId(this.name); }

  /** The pixel height this font draws at, on a screen with this minor radius. */
  pixelSize(minorRadius: number): number {
    return units.pixelSize(this.size, minorRadius);
  }
}

/** `curve:` on a text element: angled or radial, vector fonts only. */
export class Curve {
  style = "";
  angle!: Angle;
  radius: Length | null = null;
  direction: string | null = null;

  static create(init: Partial<Curve>): Curve { return make(Curve, init); }
}

/** `outline:`: a ring of `width` px round what an element draws. */
export class Outline {
  color!: Expression;
  width = 1;

  static create(init: Partial<Outline>): Outline { return make(Outline, init); }
}

/** The resolved `aod:` override for one element; `Element.aod` is null when the element is hidden in AOD. */
export class AodOverride {
  color: Expression | null = null;
  track_color: Expression | null = null;
  icon_color: Expression | null = null;
  thickness: Length | null = null;
  bar_width: Length | null = null;
  filled: boolean | null = null;
  font: string | null = null;
  font_is_custom = false;
  format: string | null = null;
  outline: Outline | null = null;
  outline_none = false;
  visible: Expression | null = null;
  visible_override: Expression | null = null;

  static create(init: Partial<AodOverride> = {}): AodOverride { return make(AodOverride, init); }
}

/** One colour an element draws with, tagged with its role. */
export class ColorRole {
  label = "";
  expression!: Expression;
  role = "";
  is_glyph = false;
  aod = false;

  static create(init: Partial<ColorRole>): ColorRole { return make(ColorRole, init); }
}

const role = (label: string, expression: Expression, r: string, isGlyph: boolean, aod = false): ColorRole =>
  ColorRole.create({ label, expression, role: r, is_glyph: isGlyph, aod });

/** Which of an AOD colour's three cases applies: the override, the dimmed awake colour, or the awake one. */
export function aodColorChoice(aod: AodOverride | null, key: "color" | "track_color" | "icon_color", dimSet: boolean): ["override" | "dim" | "awake", Expression | null] {
  if (aod !== null) {
    const override = aod[key];
    if (override !== null) return ["override", override];
  }
  return dimSet ? ["dim", null] : ["awake", null];
}

/** The ring a text element draws in the AOD frame, and how its colour is chosen. */
export function aodOutlineChoice(awake: Outline | null, aod: AodOverride | null, dimSet: boolean): [Outline | null, string] {
  if (aod !== null && aod.outline_none) return [null, "override"];
  if (aod !== null && aod.outline !== null) return [aod.outline, "override"];
  return [awake, dimSet ? "dim" : "awake"];
}

/** The stamped-ring offsets for one ring width: every integer point on the outer shell of a disc of this radius. */
export function discPerimeterOffsets(radius: number): [number, number][] {
  const lo = (radius - 1) * (radius - 1), hi = radius * radius;
  const out: [number, number][] = [];
  for (let dx = -radius; dx <= radius; dx++) {
    for (let dy = -radius; dy <= radius; dy++) {
      const d2 = dx * dx + dy * dy;
      if (lo < d2 && d2 <= hi) out.push([dx, dy]);
    }
  }
  return out;
}

// -- on-device configuration ------------------------------------------------------

/** The runtime symbol that gates the whole on-device config feature. */
export const CONFIG_SYMBOL = "Toybox.Application.WatchFaceConfig.getSettings";

export class ConfigChoice {
  color!: Color;
  label: string | null = null;

  static create(init: Partial<ConfigChoice>): ConfigChoice { return make(ConfigChoice, init); }
}

export class ConfigAxis {
  key = "";
  resource_tag = "";
  settings_field = "";

  static create(init: Partial<ConfigAxis>): ConfigAxis { return make(ConfigAxis, init); }
}

export const CONFIG_AXES: ReadonlyMap<string, ConfigAxis> = new Map([
  ["accent_color", ConfigAxis.create({ key: "accent_color", resource_tag: "accentColors", settings_field: "accentColor" })],
  ["data_color", ConfigAxis.create({ key: "data_color", resource_tag: "dataColors", settings_field: "complicationColor" })],
]);

/** The role a colour axis binds (`color.<role>`) when it writes no `role:`. */
export const CONFIG_AXIS_ROLES: ReadonlyMap<string, string> = new Map([["accent_color", "accent"], ["data_color", "data"]]);

export class ConfigColor {
  name = "";
  default!: Color;
  /** `"any"`, or the explicit picklist the editor offers. */
  choices: "any" | ConfigChoice[] = "any";
  span: Span | null = null;
  role = "";

  static create(init: Partial<ConfigColor>): ConfigColor { return make(ConfigColor, init); }

  get allowAny(): boolean { return this.choices === "any"; }
  get axis(): ConfigAxis { return CONFIG_AXES.get(this.name)!; }
  get field(): string { return configField(this.name); }
}

export class ColorScheme {
  name = "";
  label: string | null = null;
  colors: Map<string, Color> = new Map();
  span: Span | null = null;

  static create(init: Partial<ColorScheme>): ColorScheme { return make(ColorScheme, init); }
}

export class LayoutDecl {
  name = "";
  lint_allow: Set<string> = new Set();
  lint_reason: string | null = null;
  span: Span | null = null;

  static create(init: Partial<LayoutDecl>): LayoutDecl { return make(LayoutDecl, init); }
}

export class StyleEntry {
  name = "";
  label: string | null = null;
  colors: string | null = null;
  layout: string | null = null;
  lint_allow: Set<string> = new Set();
  lint_reason: string | null = null;
  span: Span | null = null;

  static create(init: Partial<StyleEntry>): StyleEntry { return make(StyleEntry, init); }
}

export class ConfigStyle {
  default = "";
  entries: StyleEntry[] = [];
  span: Span | null = null;

  static create(init: Partial<ConfigStyle>): ConfigStyle { return make(ConfigStyle, init); }

  get defaultEntry(): StyleEntry {
    return this.entries.find((e) => e.name === this.default)!;
  }

  /** This entry's `styleId`: its position in `choices:` order. */
  index(name: string): number {
    return this.entries.findIndex((e) => e.name === name);
  }
}

export class ConfigDataSlot {
  name = "";
  default = "";
  /** `"any"`, or the explicit picklist, as complication type names. */
  choices: "any" | string[] = "any";
  /** Per-choice icon override; `null` for an explicit `icon: none`. */
  icon_overrides: Map<string, icons.SlotIcon | null> = new Map();
  label: string | null = null;
  span: Span | null = null;

  static create(init: Partial<ConfigDataSlot>): ConfigDataSlot { return make(ConfigDataSlot, init); }

  get allowAny(): boolean { return this.choices === "any"; }
  get field(): string { return configField(`data_${this.name}`); }

  /** The weather types whose icon follows the pulled condition: every weather choice left on its catalogue icon. */
  get conditionIcons(): Set<string> {
    return new Set([...this.icons.keys()].filter((name) => complications.READING.get(name) === "condition" && !this.icon_overrides.has(name)));
  }

  /** Complication type to icon, for every choice that ends up with one. */
  get icons(): Map<string, icons.SlotIcon> {
    if (this.choices === "any") {
      return new Map([...icons.COMPLICATION_ICON].map(([name, catalogueName]) =>
        [name, new icons.SlotIcon(catalogueName, icons.CATALOG.get(catalogueName)!.codepoint)]));
    }
    const result = new Map<string, icons.SlotIcon>();
    for (const name of this.choices) {
      if (this.icon_overrides.has(name)) {
        const override = this.icon_overrides.get(name)!;
        if (override !== null) result.set(name, override);
        continue;
      }
      const catalogueName = icons.COMPLICATION_ICON.get(name);
      if (catalogueName !== undefined) result.set(name, new icons.SlotIcon(catalogueName, icons.CATALOG.get(catalogueName)!.codepoint));
    }
    return result;
  }
}

// -- elements ---------------------------------------------------------------------

export type OverrideKey = string; // `JSON.stringify([shape, device])`

export class Element {
  /** The `boundExpressions` roles an `absent:` policy on this kind governs. */
  static readonly VALUE_ROLES: ReadonlySet<string> = new Set();

  id = "";
  kind = "";
  at: Position = new Position();
  modes: string[] = [];
  z: number | null = null;
  span: Span | null = null;
  lint_allow: Set<string> = new Set();
  lint_reason: string | null = null;
  on_hold: string | null = null;
  unsupported: string | null = null;
  /** `overrides:`: the geometry fields this element takes on a device, keyed by `[shape, device]`. */
  overrides: Map<OverrideKey, Map<string, unknown>> = new Map();
  override_selectors: [string, Span | null][] = [];
  visible: Expression | null = null;
  static = false;
  static_root: string | null = null;
  static_rank: number | null = null;
  layout: string | null = null;
  antialias: boolean | null = null;
  resolved_antialias = false;
  min_1px: boolean | null = null;
  resolved_min_1px = false;
  sleep_update: boolean | null = null;
  resolved_sleep_update = false;
  resolved_z = 0;
  inherited_lint_allow: Set<string> = new Set();
  align = "center";
  vertical_align = "center";
  aod_own: Map<string, unknown> | null = null;
  aod_own_hide = false;
  aod_ancestor_hidden = false;
  aod: AodOverride | null = null;
  outline: Outline | null = null;

  get valueRoles(): ReadonlySet<string> {
    return (this.constructor as typeof Element).VALUE_ROLES;
  }

  /** Every lint code this element accepts: its own `lint: allow` and every enclosing group's. */
  get allLintAllow(): Set<string> {
    return new Set([...this.lint_allow, ...this.inherited_lint_allow]);
  }

  /** The stable Monkey C symbol derived from the element id. */
  get symbol(): string {
    return pascal(this.id);
  }

  get inSubscreen(): boolean {
    return this.at.anchor === "subscreen";
  }

  children(): Element[] {
    return [];
  }

  /** Every compiled expression on this element, tagged with its role, its outline and `visible:` included. */
  boundExpressions(): [string, Expression][] {
    const out = this.ownRoles();
    if (this.outline !== null) out.push([ROLE_OUTLINE_COLOR, this.outline.color]);
    if (this.visible !== null) out.push([ROLE_VISIBLE, this.visible]);
    return out;
  }

  expressions(): Expression[] {
    return this.boundExpressions().map(([, e]) => e);
  }

  protected ownRoles(): [string, Expression][] {
    return [];
  }

  /** Every colour this element draws with, one `ColorRole` each. */
  colorRoles(): ColorRole[] {
    const isGlyph = this.kind !== "shape";
    const out: ColorRole[] = [];
    const self = this as unknown as Record<string, unknown>;
    const color = self["color"] as Expression | null | undefined;
    if (color) out.push(role(this.id, color, "ink", isGlyph));
    const track = self["track_color"] as Expression | null | undefined;
    if (track) out.push(role(this.id, track, "track", isGlyph));
    const icon = self["icon_color"] as Expression | null | undefined;
    if (icon) out.push(role(this.id, icon, "icon", isGlyph));
    if (this.outline !== null) out.push(role(this.id, this.outline.color, "ring", isGlyph));
    if (this.aod !== null) {
      for (const [field, r] of [["color", "ink"], ["track_color", "track"], ["icon_color", "icon"]] as const) {
        const override = this.aod[field];
        if (override !== null) out.push(role(this.id, override, r, isGlyph, true));
      }
      if (this.aod.outline !== null) out.push(role(this.id, this.aod.outline.color, "ring", isGlyph, true));
    }
    return out;
  }
}

export class Group extends Element {
  size: Size = new Size();
  items: Element[] = [];

  static create(init: Partial<Group>): Group { return make(Group, init); }

  override children(): Element[] {
    return this.items;
  }
}

export class Shape extends Element {
  shape = "rectangle";
  size: Size = new Size();
  radius: Length | null = null;
  corner_radius: Length | null = null;
  to: Position | null = null;
  points: Position[] = [];
  start_angle: Angle | null = null;
  sweep: Angle | null = null;
  thickness: Length | null = null;
  color: Expression | null = null;
  filled = true;

  static create(init: Partial<Shape>): Shape { return make(Shape, init); }

  /** A rectangle that writes `corner_radius:`. */
  get rounded(): boolean {
    return this.shape === "rectangle" && this.corner_radius !== null;
  }

  protected override ownRoles(): [string, Expression][] {
    return this.color ? [[ROLE_COLOR, this.color]] : [];
  }
}

/** One primitive of a hand, or of a pattern template, in its own frame: drawn pointing at 12 o'clock. */
export abstract class HandPart {
  abstract get shape(): string;
  color: Expression | null = null;
  span: Span | null = null;
  visible: Expression | null = null;
  min_1px: boolean | null = null;
}

export class PolygonPart extends HandPart {
  get shape(): "polygon" { return "polygon"; }
  points: Position[] = [];
  filled = true;

  static create(init: Partial<PolygonPart>): PolygonPart { return make(PolygonPart, init); }
}

export class RectanglePart extends HandPart {
  get shape(): "rectangle" { return "rectangle"; }
  at: Position = new Position();
  size: Size = new Size();
  filled = true;
  align = "center";
  vertical_align = "center";

  static create(init: Partial<RectanglePart>): RectanglePart { return make(RectanglePart, init); }
}

export class LinePart extends HandPart {
  get shape(): "line" { return "line"; }
  at: Position = new Position();
  to: Position | null = null;
  thickness: Length | null = null;

  static create(init: Partial<LinePart>): LinePart { return make(LinePart, init); }
}

export class CirclePart extends HandPart {
  get shape(): "circle" { return "circle"; }
  at: Position = new Position();
  radius: Length | null = null;
  thickness: Length | null = null;
  filled = true;
  align = "center";
  vertical_align = "center";

  static create(init: Partial<CirclePart>): CirclePart { return make(CirclePart, init); }
}

/** Pattern-only; always centred on the copy's own origin. */
export class ArcPart extends HandPart {
  get shape(): "arc" { return "arc"; }
  radius: Length | null = null;
  thickness: Length | null = null;
  start_angle: Angle | null = null;
  sweep: Angle | null = null;

  static create(init: Partial<ArcPart>): ArcPart { return make(ArcPart, init); }
}

/** Pattern-only: upright glyphs whose anchor turns or steps with the copy. */
export class TextPart extends HandPart {
  get shape(): "text" { return "text"; }
  at: Position = new Position();
  text_value: Expression | null = null;
  text_literal: string | null = null;
  format: string | null = null;
  font = "FONT_MEDIUM";
  font_is_custom = false;
  align = "center";
  vertical_align = "center";
  texts: string[] = [];
  curve: Curve | null = null;
  unsupported: string | null = null;
  outline: Outline | null = null;

  static create(init: Partial<TextPart>): TextPart { return make(TextPart, init); }
}

export type AnyHandPart = PolygonPart | RectanglePart | LinePart | CirclePart | ArcPart | TextPart;

export class Hand {
  parts: AnyHandPart[] = [];
  color: Expression | null = null;

  static create(init: Partial<Hand> = {}): Hand { return make(Hand, init); }
}

export class HandSet {
  name = "";
  hour: Hand | null = null;
  minute: Hand | null = null;
  second: Hand | null = null;
  span: Span | null = null;

  static create(init: Partial<HandSet>): HandSet { return make(HandSet, init); }

  /** The declared hands, in fixed draw order: hour, minute, second. */
  hands(): [string, Hand][] {
    return ([["hour", this.hour], ["minute", this.minute], ["second", this.second]] as [string, Hand | null][])
      .filter((pair): pair is [string, Hand] => pair[1] !== null);
  }
}

export class HandsElement extends Element {
  hands = "";
  seconds: string | null = null;
  colors: Expression[] = [];

  static create(init: Partial<HandsElement>): HandsElement { return make(HandsElement, init); }

  protected override ownRoles(): [string, Expression][] {
    return this.colors.map((e) => [ROLE_COLOR, e]);
  }

  override colorRoles(): ColorRole[] {
    const out = this.colors.map((e) => role(this.id, e, "ink", false));
    if (this.outline !== null) out.push(role(this.id, this.outline.color, "ring", false));
    if (this.aod !== null && this.aod.color !== null) out.push(role(this.id, this.aod.color, "ink", false, true));
    return out;
  }
}

export class PatternElement extends Element {
  pattern = "radial";
  count = 1;
  step_angle = 0.0;
  start_angle = 0.0;
  step: Position | null = null;
  columns: number | null = null;
  skip: number[] = [];
  skip_every: number | null = null;
  parts: AnyHandPart[] = [];
  color: Expression | null = null;
  colors: Expression[] = [];
  absent: string | null = null;

  static create(init: Partial<PatternElement>): PatternElement { return make(PatternElement, init); }

  /** Copy indices actually drawn, ascending. */
  drawnIndices(): number[] {
    return drawnCopies(this.count, this.skip, this.skip_every);
  }

  protected override ownRoles(): [string, Expression][] {
    const out: [string, Expression][] = this.colors.map((e) => [ROLE_COLOR, e]);
    for (const part of this.parts) {
      if (part.visible !== null) out.push([ROLE_PART_VISIBLE, part.visible]);
      if (part.shape === "text" && part.text_value !== null) out.push([ROLE_PART_TEXT, part.text_value]);
    }
    return out;
  }

  override colorRoles(): ColorRole[] {
    const isGlyph = this.kind !== "shape";
    const out: ColorRole[] = [];
    if (this.color !== null) out.push(role(this.id, this.color, "ink", isGlyph));
    this.parts.forEach((part, index) => {
      const label = `${this.id}.parts[${index}]`;
      const partIsGlyph = part.shape === "text";
      if (part.color !== null) out.push(role(label, part.color, "ink", partIsGlyph));
      if (part.shape === "text" && part.outline !== null) out.push(role(label, part.outline.color, "ring", partIsGlyph));
    });
    if (this.outline !== null) out.push(role(this.id, this.outline.color, "ring", isGlyph));
    if (this.aod !== null && this.aod.color !== null) out.push(role(this.id, this.aod.color, "ink", isGlyph, true));
    return out;
  }
}

/** A later reading of a `text:` template with several placeholders. */
export class TextSegment {
  value!: Expression;
  format = "";

  static create(init: Partial<TextSegment>): TextSegment { return make(TextSegment, init); }
}

export class Text extends Element {
  static override readonly VALUE_ROLES: ReadonlySet<string> = new Set([ROLE_VALUE]);

  value: Expression | null = null;
  literal: string | null = null;
  format: string | null = null;
  more: TextSegment[] = [];
  font = "FONT_MEDIUM";
  font_is_custom = false;
  color: Expression | null = null;
  absent: string | null = null;
  placeholder: string | null = null;
  fallback: Expression | null = null;
  curve: Curve | null = null;
  units: string | null = null;
  unit_label: Expression | null = null;
  unit_labels: string[] = [];
  unit_digits: number | null = null;

  static create(init: Partial<Text>): Text { return make(Text, init); }

  /** Every reading with the format that draws it, in order. */
  segments(): [Expression, string][] {
    if (this.value === null) return [];
    return [[this.value, this.format || "{}"], ...this.more.map((s): [Expression, string] => [s.value, s.format])];
  }

  protected override ownRoles(): [string, Expression][] {
    const out: [string, Expression][] = [];
    const add = (r: string, e: Expression | null): void => { if (e) out.push([r, e]); };
    add(ROLE_VALUE, this.value);
    for (const segment of this.more) add(ROLE_VALUE, segment.value);
    add(ROLE_COLOR, this.color);
    add(ROLE_FALLBACK, this.fallback);
    if (this.unit_label !== null) out.push([ROLE_UNIT_LABEL, this.unit_label]);
    return out;
  }
}

export class Gauge extends Element {
  static override readonly VALUE_ROLES: ReadonlySet<string> = new Set([ROLE_VALUE, ROLE_MAX]);

  style = "arc";
  value: Expression | null = null;
  maximum: Expression | null = null;
  slot: string | null = null;
  auto_scale: string | null = null;
  radius: Length | null = null;
  thickness: Length | null = null;
  start_angle: Angle | null = null;
  sweep: Angle | null = null;
  size: Size = new Size();
  color: Expression | null = null;
  track_color: Expression | null = null;
  absent: string | null = null;
  fallback: Expression | null = null;
  needle: AnyHandPart[] = [];
  count: number | null = null;
  gap: Length | null = null;
  bands: [number, Expression][] = [];
  pointer: Length | null = null;

  static create(init: Partial<Gauge>): Gauge { return make(Gauge, init); }

  /** What the track is: arc, bar or needle; segments and scale are whichever their keys describe. */
  get geometry(): string {
    if (this.style === "arc" || this.style === "bar" || this.style === "needle") return this.style;
    return this.radius !== null ? "arc" : "bar";
  }

  protected override ownRoles(): [string, Expression][] {
    const out: [string, Expression][] = [];
    const add = (r: string, e: Expression | null): void => { if (e) out.push([r, e]); };
    add(ROLE_VALUE, this.value);
    add(ROLE_MAX, this.maximum);
    add(ROLE_COLOR, this.color);
    add(ROLE_TRACK_COLOR, this.track_color);
    add(ROLE_FALLBACK, this.fallback);
    for (const part of this.needle) if (part.color !== null && part.color !== this.color) out.push([ROLE_COLOR, part.color]);
    for (const [, color] of this.bands) out.push([ROLE_COLOR, color]);
    return out;
  }

  override colorRoles(): ColorRole[] {
    const out = super.colorRoles();
    this.needle.forEach((part, index) => {
      if (part.color !== null && part.color !== this.color) out.push(role(`${this.id}.needle[${index}]`, part.color, "ink", false));
    });
    this.bands.forEach(([, color], index) => out.push(role(`${this.id}.bands[${index}]`, color, "track", false)));
    return out;
  }
}

export class IconElement extends Element {
  icon: string | null = "steps";
  codepoint = "?";
  value_for: Expression | null = null;
  size: Length | null = null;
  color: Expression | null = null;

  static create(init: Partial<IconElement>): IconElement { return make(IconElement, init); }

  get isDynamic(): boolean {
    return this.value_for !== null;
  }

  protected override ownRoles(): [string, Expression][] {
    const out: [string, Expression][] = [];
    if (this.color) out.push([ROLE_COLOR, this.color]);
    if (this.value_for) out.push([ROLE_VALUE, this.value_for]);
    return out;
  }
}

export class DataElement extends Element {
  slot = "";
  font = "FONT_SMALL";
  font_is_custom = false;
  icon_size: Length | null = null;
  color: Expression | null = null;
  icon_position = "left";
  icon_gap: Length | null = null;
  icon_color: Expression | null = null;
  label = "none";
  unit = false;
  short = false;
  absent = "hide";
  placeholder: string | null = null;

  static create(init: Partial<DataElement>): DataElement { return make(DataElement, init); }

  protected override ownRoles(): [string, Expression][] {
    const out: [string, Expression][] = [];
    if (this.color) out.push([ROLE_COLOR, this.color]);
    if (this.icon_color) out.push([ROLE_ICON_COLOR, this.icon_color]);
    return out;
  }
}

export class Graph extends Element {
  series = "";
  series_def: SeriesDef | null = null;
  range_kind = "duration";
  range_value = 0;
  buckets = 40;
  style = "line";
  thickness: Length | null = null;
  bar_width: Length | null = null;
  min_auto = true;
  max_auto = true;
  min: Expression | null = null;
  max: Expression | null = null;
  size: Size = new Size();
  color: Expression | null = null;
  sample_count = 0;

  static create(init: Partial<Graph>): Graph { return make(Graph, init); }

  protected override ownRoles(): [string, Expression][] {
    const out: [string, Expression][] = [];
    if (this.color) out.push([ROLE_COLOR, this.color]);
    if (this.min) out.push([ROLE_MIN, this.min]);
    if (this.max) out.push([ROLE_MAX, this.max]);
    return out;
  }
}

export class Face {
  format = 2;
  uuid = "";
  name = "";
  version = "";
  entry = "";
  targets: string[] = [];
  palette: Map<string, Color> = new Map();
  fonts: Map<string, FontSpec> = new Map();
  elements: Element[] = [];
  source_path = "";
  antialias = false;
  min_1px = false;
  config: Map<string, ConfigColor> = new Map();
  palette_labels: Map<string, string> = new Map();
  color_scheme: Map<string, ColorScheme> = new Map();
  /** The scheme roles some expression reads: only these become view fields. */
  scheme_roles_used: Set<string> = new Set();
  layouts: string[] = [];
  layout_decls: Map<string, LayoutDecl> = new Map();
  config_style: ConfigStyle | null = null;
  config_data: Map<string, ConfigDataSlot> = new Map();
  hands: Map<string, HandSet> = new Map();
  aod_default_hide = true;
  aod_lint_allow: Set<string> = new Set();
  aod_lint_reason: string | null = null;
  aod_dim: number | null = null;
  aod_mask = true;

  static create(init: Partial<Face>): Face { return make(Face, init); }

  /** The single on/off switch for the whole on-device config feature. */
  get hasConfig(): boolean {
    return this.config.size > 0 || this.config_style !== null || this.config_data.size > 0;
  }

  /** The label the generated `<style>` and the preview both show for one style entry. */
  styleLabel(entry: StyleEntry): string | null {
    if (entry.label !== null) return entry.label;
    if (entry.colors !== null && entry.layout === null) return this.color_scheme.get(entry.colors)!.label;
    return null;
  }

  /** Every element, parents before children, in document order. */
  walk(): Element[] {
    return walkElements(this.elements);
  }

  drawOrder(): Element[] {
    return drawOrder(this.elements);
  }

  staticRoots(): Element[] {
    return this.walk().filter((e) => e.static);
  }

  /** Permissions, readers and modules implied by every binding. */
  requirements(): catalog.Requirements {
    const req = new catalog.Requirements();
    for (const element of this.walk()) {
      for (const expression of element.expressions()) {
        for (const path of expression.sources) {
          const source = catalog.get(path);
          if (source) req.add(source);
        }
      }
    }
    return req;
  }

  barrelFunctions(): Set<string> {
    const used = new Set<string>();
    for (const element of this.walk()) for (const expression of element.expressions()) for (const f of expression.barrel) used.add(f);
    return used;
  }
}

/** Copy indices actually drawn, ascending: `0..count-1` minus `skip` and every multiple of `skipEvery`. */
export function drawnCopies(count: number, skip: readonly number[], skipEvery: number | null): number[] {
  const out: number[] = [];
  for (let i = 0; i < count; i++) if (!skip.includes(i) && (skipEvery === null || i % skipEvery !== 0)) out.push(i);
  return out;
}

/** The `config: slots:` slot `element` draws, if any. */
export function slotOf(element: Element): string | null {
  if (element instanceof DataElement) return element.slot;
  if (element instanceof Gauge) return element.slot;
  return null;
}

/** Flatten a tree of elements, parents before children, in document order. */
export function walkElements(elements: readonly Element[]): Element[] {
  const out: Element[] = [];
  const visit = (items: readonly Element[]): void => {
    for (const item of items) {
      out.push(item);
      visit(item.children());
    }
  };
  visit(elements);
  return out;
}

const compareKeys = (a: readonly number[], b: readonly number[]): number => {
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i]! - b[i]!;
  return 0;
};

/** Draw order as the author wrote it: layer, then document order stable-sorted by `z`. */
export function authoredDrawOrder(elements: readonly Element[]): Element[] {
  return walkElements(elements).filter((e) => e.kind !== "group")
    .sort((a, b) => compareKeys([a.layout === null ? 0 : 1, a.resolved_z], [b.layout === null ? 0 : 1, b.resolved_z]));
}

/** The sort key that puts an element in draw order, static content first. */
export function drawSortKey(element: Element): [number, number, number, number] {
  const layer = element.layout === null ? 0 : 1;
  const z = element.resolved_z;
  if (element.static_root === null) return [1, layer, 0, z];
  return [0, layer, element.static_rank ?? 0, z];
}

/** The flattened list of elements that actually paint, in drawing order. */
export function drawOrder(elements: readonly Element[]): Element[] {
  return walkElements(elements).filter((e) => e.kind !== "group").sort((a, b) => compareKeys(drawSortKey(a), drawSortKey(b)));
}

/** True only when `a` and `b` belong to different layouts, so they are never on screen together. */
export function neverTogether(a: Element, b: Element): boolean {
  return a.layout !== null && b.layout !== null && a.layout !== b.layout;
}
