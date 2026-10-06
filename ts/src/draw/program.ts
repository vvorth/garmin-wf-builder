// The draw program: what one element draws, as values and ops..
//
// A kind lowers a placed element into a list of ops (`ElementKind.lower`).
// Every value an op takes is something both backends can read: the printer
// (`printer.ts`) spells it as Monkey C, the evaluator (`evaluator.ts`)
// computes it on the host. Nothing here knows any kind; a kind knows only
// these types.
//
// Each type is a plain object tagged by `t`, with the Python dataclass's
// name, and built by the function of the same name. A number keeps Python's
// int/float distinction as `expr.ts` does: an integral float is a `PyFloat`,
// since Monkey C's `/` truncates two `Number`s and not a `Float`.
import type { FontMetric } from "../devices/device.ts";
import type { PyFloat } from "../edit/yaml.ts";
import type { ConfigDataSlot, Element, Expression } from "../ir/model.ts";
import type { ResolvedFace, RotatablePart } from "../layout.ts";
import type { IntBox } from "../units.ts";
import * as complications from "../complications.ts";
import type { AodStyle, RingPass } from "../emit/monkeyc/common.ts";

/** A number as Python holds it: an int, a non-integral float, or a `PyFloat`. */
export type PyNum = number | PyFloat;

// -- numbers --------------------------------------------------------------------

/** A `Layout` constant: `Layout.<name>` on the watch, `value` on this device. */
export interface Const { t: "Const"; name: string; value: PyNum }
export const Const = (name: string, value: PyNum): Const => ({ t: "Const", name, value });

/** A number written into the call itself. */
export interface Lit { t: "Lit"; value: PyNum }
export const Lit = (value: PyNum): Lit => ({ t: "Lit", value });

/** `base` moved `by` pixels for one `outline:` stamp. */
export interface Shifted { t: "Shifted"; base: Num; by: number }
export const Shifted = (base: Num, by: number): Shifted => ({ t: "Shifted", base, by });

/** `base` grown by `times * by` for a grown ring copy. */
export interface Grown { t: "Grown"; base: Num; by: number; times: number }
export const Grown = (base: Num, by: number, times = 1): Grown => ({ t: "Grown", base, by, times });

/** `awake`, or `asleep` in the always-on frame; `asleep` is `null` with no override. */
export interface AodPick { t: "AodPick"; awake: Num; asleep: Num | null }
export const AodPick = (awake: Num, asleep: Num | null): AodPick => ({ t: "AodPick", awake, asleep });

/** A `Float` literal, spelt as `mc_float` spells one, with `suffix` after it. */
export interface FloatLit { t: "FloatLit"; value: number; suffix: string }
export const FloatLit = (value: number, suffix = ""): FloatLit => ({ t: "FloatLit", value, suffix });

/** A number local an earlier `Let` (or a `For`) assigned. */
export interface NumLocal { t: "NumLocal"; name: string }
export const NumLocal = (name: string): NumLocal => ({ t: "NumLocal", name });

/** A bound expression's own compiled code, at the sample readings on the host. */
export interface Read { t: "Read"; expr: Expression }
export const Read = (expr: Expression): Read => ({ t: "Read", expr });

/** `a <op> b`, printed bare. */
export interface Bin { t: "Bin"; op: string; a: Num; b: Num }
export const Bin = (op: string, a: Num, b: Num): Bin => ({ t: "Bin", op, a, b });

/** `(<inner>)`. */
export interface Paren { t: "Paren"; inner: Num }
export const Paren = (inner: Num): Paren => ({ t: "Paren", inner });

/** `fn(<args>)`: a `Math` or barrel function the evaluator transcribes. */
export interface Call { t: "Call"; fn: string; args: Num[] }
export const Call = (fn: string, args: Num[]): Call => ({ t: "Call", fn, args });

/** `<inner>.toNumber()` or `<inner>.toFloat()`. */
export interface Conv { t: "Conv"; inner: Num; method: string }
export const Conv = (inner: Num, method: string): Conv => ({ t: "Conv", inner, method });

/** `(<cond>) ? <then> : <otherwise>`, a number chosen at runtime. */
export interface NumPick { t: "NumPick"; cond: Cond; then: Num; otherwise: Num }
export const NumPick = (cond: Cond, then: Num, otherwise: Num): NumPick => ({ t: "NumPick", cond, then, otherwise });

/** `base`, less the font's height for `vertical_align: bottom`; the host places the line itself. */
export interface FontDrop { t: "FontDrop"; base: Num; valign: string; font: string }
export const FontDrop = (base: Num, valign: string, font: string): FontDrop => ({ t: "FontDrop", base, valign, font });

/** `WfbHands.<function>(clock)`: a hand's angle from the clock. */
export interface HandAngle { t: "HandAngle"; function: string; hand: string }
export const HandAngle = (fn: string, hand: string): HandAngle => ({ t: "HandAngle", function: fn, hand });

/** `dc.getTextWidthInPixels(<text>, <font>)`. */
export interface TextWidth { t: "TextWidth"; text: Str; font: Font }
export const TextWidth = (text: Str, font: Font): TextWidth => ({ t: "TextWidth", text, font });

/** `dc.getFontHeight(<font>)`. */
export interface FontHeight { t: "FontHeight"; font: Font }
export const FontHeight = (font: Font): FontHeight => ({ t: "FontHeight", font });

export type Num = Const | Lit | Shifted | Grown | AodPick | FloatLit | NumLocal | Read | Bin | Paren | Call | Conv
  | NumPick | FontDrop | HandAngle | TextWidth | FontHeight;

// -- conditions -----------------------------------------------------------------

/** `a != null && ...` over the value guards; on the host, every probe evaluates. */
export interface Present { t: "Present"; guards: string[]; probes: Expression[] }
export const Present = (guards: readonly string[], probes: readonly Expression[]): Present =>
  ({ t: "Present", guards: [...guards], probes: [...probes] });

/** `a != null && ...` over locals the program assigned. */
export interface LocalsSet { t: "LocalsSet"; names: string[] }
export const LocalsSet = (names: readonly string[]): LocalsSet => ({ t: "LocalsSet", names: [...names] });

/** `a <op> b`. */
export interface Cmp { t: "Cmp"; op: string; a: Num; b: Num }
export const Cmp = (op: string, a: Num, b: Num): Cmp => ({ t: "Cmp", op, a, b });

/** `_pulsing != <unique>`: never false on the host. */
export interface NotPulsing { t: "NotPulsing"; unique: number }
export const NotPulsing = (unique: number): NotPulsing => ({ t: "NotPulsing", unique });

/** `a || b || ...`. */
export interface AnyOf { t: "AnyOf"; conds: Cond[] }
export const AnyOf = (conds: readonly Cond[]): AnyOf => ({ t: "AnyOf", conds: [...conds] });

/** An expression's own code as the condition; false on the host when absent. */
export interface Truthy { t: "Truthy"; expr: Expression }
export const Truthy = (expr: Expression): Truthy => ({ t: "Truthy", expr });

/** `!_sleeping`. */
export interface NotSleeping { t: "NotSleeping" }
export const NotSleeping = (): NotSleeping => ({ t: "NotSleeping" });

/** `_pulsing == <unique>`: never true on the host. */
export interface IsPulsing { t: "IsPulsing"; unique: number }
export const IsPulsing = (unique: number): IsPulsing => ({ t: "IsPulsing", unique });

export type Cond = Present | LocalsSet | Cmp | NotPulsing | AnyOf | Truthy | NotSleeping | IsPulsing;

// -- strings --------------------------------------------------------------------

/** A string written into the call. */
export interface StrLit { t: "StrLit"; text: string }
export const StrLit = (text: string): StrLit => ({ t: "StrLit", text });

/** One reading through its format spec; absent when the reading is. */
export interface Reading { t: "Reading"; spec: string; value: Expression; unit: Expression | null }
export const Reading = (spec: string, value: Expression, unit: Expression | null = null): Reading =>
  ({ t: "Reading", spec, value, unit });

/** Readings and literals drawn as one string; absent when any part is. */
export interface Concat { t: "Concat"; parts: (StrLit | Reading)[] }
export const Concat = (parts: readonly (StrLit | Reading)[]): Concat => ({ t: "Concat", parts: [...parts] });

/** A string local an earlier `LetText` assigned. */
export interface Local { t: "Local"; name: string }
export const Local = (name: string): Local => ({ t: "Local", name });

/** `awake`, or `asleep` in the always-on frame. */
export interface AodStr { t: "AodStr"; asleep: Str; awake: Str }
export const AodStr = (asleep: Str, awake: Str): AodStr => ({ t: "AodStr", asleep, awake });

/** A dynamic weather icon's glyph. */
export interface IconChoice { t: "IconChoice"; value: Expression }
export const IconChoice = (value: Expression): IconChoice => ({ t: "IconChoice", value });

/** A pattern text part's string: `printed` on the watch, the copy's own on the host. */
export interface PerCopy { t: "PerCopy"; printed: Str; texts: string[]; var: string }
export const PerCopy = (printed: Str, texts: readonly string[], v = "i"): PerCopy =>
  ({ t: "PerCopy", printed, texts: [...texts], var: v });

export type Str = StrLit | Reading | Concat | Local | AodStr | IconChoice | PerCopy;

// -- colours and fonts ----------------------------------------------------------

/** A colour expression; `null` is `Graphics.COLOR_WHITE`. */
export interface Color { t: "Color"; expr: Expression | null }
export const Color = (expr: Expression | null): Color => ({ t: "Color", expr });

/** `element`'s own `key` colour as the always-on frame restyles it. */
export interface AodRestyled { t: "AodRestyled"; element: Element; key: "color" | "track_color" | "icon_color"; awake: Paint | null }
export const AodRestyled = (element: Element, key: "color" | "track_color" | "icon_color", awake: Paint | null = null): AodRestyled =>
  ({ t: "AodRestyled", element, key, awake });

/** `expr` dimmed in the always-on frame and unchanged otherwise. */
export interface AodDimmed { t: "AodDimmed"; element: Element; expr: Expression | null }
export const AodDimmed = (element: Element, expr: Expression | null): AodDimmed => ({ t: "AodDimmed", element, expr });

/** `awake`, or `asleep` in the always-on frame. */
export interface AodPaint { t: "AodPaint"; asleep: Paint; awake: Paint }
export const AodPaint = (asleep: Paint, awake: Paint): AodPaint => ({ t: "AodPaint", asleep, awake });

/** The `ringColor` parameter of a `ring<Id>` method. */
export interface RingColor { t: "RingColor" }
export const RingColor = (): RingColor => ({ t: "RingColor" });

/** One part's own colour of a `hands`/`pattern`/needle element. */
export interface AodPart { t: "AodPart"; element: Element; expr: Expression | null }
export const AodPart = (element: Element, expr: Expression | null): AodPart => ({ t: "AodPart", element, expr });

/** `(<cond>) ? <then> : <otherwise>`, a colour chosen at runtime. */
export interface PaintPick { t: "PaintPick"; cond: Cond; then: Paint; otherwise: Paint }
export const PaintPick = (cond: Cond, then: Paint, otherwise: Paint): PaintPick => ({ t: "PaintPick", cond, then, otherwise });

export type Paint = Color | AodRestyled | AodDimmed | AodPaint | RingColor | AodPart | PaintPick;

/** The font a text call names. */
export interface Font {
  /** How the call spells it: a local, or `Graphics.FONT_*`. */
  code: string;
  /** The `ResolvedFace.fonts` key of a baked sheet. */
  baked: string | null;
  /** The device face a system or vector font draws with. */
  metric: FontMetric | null;
  /** A `face:` font. */
  vector: boolean;
  /** The font drawn in the always-on frame instead; `code` already names the choice. */
  asleep: Font | null;
  /** The nominal pixel size, the host's height for a font it cannot measure. */
  px: number;
}
export const Font = (code: string, { baked = null, metric = null, vector = false, asleep = null, px = 0 }:
  Partial<Omit<Font, "code">> = {}): Font => ({ code, baked, metric, vector, asleep, px });

// -- ops ------------------------------------------------------------------------

export interface SetColor { t: "SetColor"; color: Paint; note: string }
export const SetColor = (color: Paint, note = ""): SetColor => ({ t: "SetColor", color, note });

/** `dc.setPenWidth(<width>)`; `null` resets it to 1. */
export interface SetPen { t: "SetPen"; width: Num | null; note: string }
export const SetPen = (width: Num | null, note = ""): SetPen => ({ t: "SetPen", width, note });

/** One `Dc` fill or draw call; `args` in the groups the printer wraps. */
export interface Primitive { t: "Primitive"; name: string; args: Num[][] }
export const Primitive = (name: string, args: readonly (readonly Num[])[]): Primitive =>
  ({ t: "Primitive", name, args: args.map((g) => [...g]) });

/** `dc.fillPolygon(Layout.<const>)`, whose vertices are `points`. */
export interface FillPolygon { t: "FillPolygon"; const: string; points: [number, number][] }
export const FillPolygon = (constName: string, points: readonly (readonly [number, number])[]): FillPolygon =>
  ({ t: "FillPolygon", const: constName, points: points.map(([x, y]) => [x, y]) });

/** `WfbArc.drawSpan`, in Garmin's convention. */
export interface ArcSpan { t: "ArcSpan"; cx: Num; cy: Num; radius: Num; pen: Num; start: Num; sweep: Num; pen_first: boolean }
export const ArcSpan = (cx: Num, cy: Num, radius: Num, pen: Num, start: Num, sweep: Num, penFirst = false): ArcSpan =>
  ({ t: "ArcSpan", cx, cy, radius, pen, start, sweep, pen_first: penFirst });

/** `WfbArc.drawProgress`: `fraction` of the span. */
export interface ArcProgress { t: "ArcProgress"; cx: Num; cy: Num; radius: Num; pen: Num; start: Num; sweep: Num; fraction: Num }
export const ArcProgress = (cx: Num, cy: Num, radius: Num, pen: Num, start: Num, sweep: Num, fraction: Num): ArcProgress =>
  ({ t: "ArcProgress", cx, cy, radius, pen, start, sweep, fraction });

/** One polygon, line or circle part through the barrel, rotated or translated; `ring` its ring instead. */
export interface Part { t: "Part"; part: RotatablePart; prefix: string; radial: boolean; pen: Num; set_pen: boolean; ring: number | null }
export const Part = (part: RotatablePart, prefix: string, radial: boolean, pen: Num,
  { setPen = true, ring = null }: { setPen?: boolean; ring?: number | null } = {}): Part =>
  ({ t: "Part", part, prefix, radial, pen, set_pen: setPen, ring });

/** A graph's once-a-minute rebuild; on the host, the stand-in series. */
export interface SeriesRebuild {
  t: "SeriesRebuild"; built: string; method: string; series: string; minimum: string; maximum: string;
  samples: (number | null)[]; min_auto: boolean; max_auto: boolean;
}
export const SeriesRebuild = (built: string, method: string, series: string, minimum: string, maximum: string,
  samples: readonly (number | null)[], minAuto: boolean, maxAuto: boolean): SeriesRebuild =>
  ({ t: "SeriesRebuild", built, method, series, minimum, maximum, samples: [...samples], min_auto: minAuto, max_auto: maxAuto });

/** `WfbSeries.drawLine`/`drawArea`/`drawBars` of the cached series. */
export interface SeriesDraw { t: "SeriesDraw"; style: string; x: Num; y: Num; w: Num; h: Num; width: Num | null; series: string; lo: Num; hi: Num }
export const SeriesDraw = (style: string, x: Num, y: Num, w: Num, h: Num, width: Num | null, series: string, lo: Num, hi: Num): SeriesDraw =>
  ({ t: "SeriesDraw", style, x, y, w, h, width, series, lo, hi });

/** `var <local> = <source>;`, with an early return for `on_null: "return"`. The host always has the font. */
export interface LoadFont { t: "LoadFont"; local: string; source: string; on_null: string; note: string }
export const LoadFont = (local: string, source: string, { onNull = "return", note = "the font resource failed to load" } = {}): LoadFont =>
  ({ t: "LoadFont", local, source, on_null: onNull, note });

/** `dc.drawText`, or `drawAngledText`/`drawRadialText` under a `style`. */
export interface Text {
  t: "Text"; x: Num; y: Num; font: Font; text: Str; justify: string[]; valign: string;
  align: string | null; style: string | null; angle: Num | null; radius: Const | null; direction: string | null;
  box: IntBox | null; shift_y: boolean; split_x: boolean; joined: boolean;
}
export const Text = (x: Num, y: Num, font: Font, text: Str, justify: readonly string[], valign: string,
  { align = null, style = null, angle = null, radius = null, direction = null, box = null, shiftY = true, splitX = false, joined = false }: {
    align?: string | null; style?: string | null; angle?: Num | null; radius?: Const | null; direction?: string | null;
    box?: IntBox | null; shiftY?: boolean; splitX?: boolean; joined?: boolean;
  } = {}): Text =>
  ({ t: "Text", x, y, font, text, justify: [...justify], valign, align, style, angle, radius, direction, box, shift_y: shiftY, split_x: splitX, joined });

/** An icon's glyph: on the host, its tile at the measured box's top-left, moved with `x`/`y` from `origin`. */
export interface Glyph { t: "Glyph"; x: Num; y: Num; font: Font; glyph: Str; justify: string[]; valign: string; box: IntBox; origin: [number, number] }
export const Glyph = (x: Num, y: Num, font: Font, glyph: Str, justify: readonly string[], valign: string, box: IntBox, origin: readonly [number, number]): Glyph =>
  ({ t: "Glyph", x, y, font, glyph, justify: [...justify], valign, box, origin: [origin[0], origin[1]] });

/** `var text = <initial>; if (<guards> != null) { text = <value>; }`. */
export interface LetText { t: "LetText"; initial: Str; value: Str; guards: string[]; name: string }
export const LetText = (initial: Str, value: Str, guards: readonly string[], name = "text"): LetText =>
  ({ t: "LetText", initial, value, guards: [...guards], name });

/** `if (<local> != null) { <body> }`; on the host the body runs unless `present` says otherwise. */
export interface IfNotNull { t: "IfNotNull"; local: string; body: Op[]; present: boolean }
export const IfNotNull = (local: string, body: readonly Op[], present = true): IfNotNull => ({ t: "IfNotNull", local, body: [...body], present });

/** `if (_aod) { <then> } else { <otherwise> }`. */
export interface IfAod { t: "IfAod"; then: Op[]; otherwise: Op[] }
export const IfAod = (then: readonly Op[], otherwise: readonly Op[] = []): IfAod => ({ t: "IfAod", then: [...then], otherwise: [...otherwise] });

/** `if (!_aod) { <body> }`. */
export interface IfAwake { t: "IfAwake"; body: Op[] }
export const IfAwake = (body: readonly Op[]): IfAwake => ({ t: "IfAwake", body: [...body] });

export interface Let { t: "Let"; name: string; value: Num; note: string }
export const Let = (name: string, value: Num, note = ""): Let => ({ t: "Let", name, value, note });

export interface Assign { t: "Assign"; name: string; value: Num }
export const Assign = (name: string, value: Num): Assign => ({ t: "Assign", name, value });

export interface If { t: "If"; cond: Cond; then: Op[]; otherwise: Op[] }
export const If = (cond: Cond, then: readonly Op[], otherwise: readonly Op[] = []): If => ({ t: "If", cond, then: [...then], otherwise: [...otherwise] });

/** `for (var <var> = 0; <var> < <bound>; <var>++)`; with `copy`, a pattern's copies. */
export interface For { t: "For"; var: string; bound: Num; body: Op[]; copy: boolean }
export const For = (v: string, bound: Num, body: readonly Op[], copy = false): For => ({ t: "For", var: v, bound, body: [...body], copy });

export interface Continue { t: "Continue" }
export const Continue = (): Continue => ({ t: "Continue" });

/** The wearer's pick on a `config: slots:` slot and its scale. */
export interface LetSlotPick { t: "LetSlotPick"; field: string; module: string; guarded: boolean; sample: unknown; scale: [number, number] | null }
export const LetSlotPick = (field: string, module: string, guarded: boolean, sample: unknown, scale: [number, number] | null): LetSlotPick =>
  ({ t: "LetSlotPick", field, module, guarded, sample, scale });

/** `max: auto`'s scale. */
export interface LetAutoScale { t: "LetAutoScale"; reader: string; module: string; constant: string; type_name: string; value: Expression }
export const LetAutoScale = (reader: string, module: string, constant: string, typeName: string, value: Expression): LetAutoScale =>
  ({ t: "LetAutoScale", reader, module, constant, type_name: typeName, value });

export interface Return { t: "Return" }
export const Return = (): Return => ({ t: "Return" });

/** The wearer's pick on a config slot, pulled fresh. */
export interface SlotPull { t: "SlotPull"; field: string; guarded: boolean; sample: unknown }
export const SlotPull = (field: string, guarded: boolean, sample: unknown): SlotPull => ({ t: "SlotPull", field, guarded, sample });

/** A data element's icon, chosen from the picked type. */
export interface SlotIcon { t: "SlotIcon"; font: string; key: string; method: string; guarded: boolean; glyph: string | null }
export const SlotIcon = (font: string, key: string, method: string, guarded: boolean, glyph: string | null): SlotIcon =>
  ({ t: "SlotIcon", font, key, method, guarded, glyph });

/** A data element's reading, its label in front, or under `absent:` its placeholder or nothing. */
export interface SlotText {
  t: "SlotText"; module: string; guarded: boolean; unit: boolean; short: boolean; label: string | null; absent: string | null;
  placeholder: string | null; type_name: string; sample: unknown; label_sample: string;
}
export const SlotText = (fields: Omit<SlotText, "t">): SlotText => ({ t: "SlotText", ...fields });

/** `visible:`: nothing more is drawn when the condition does not hold. */
export interface VisibleGuard { t: "VisibleGuard"; expr: Expression; locals: string[]; negated: string }
export const VisibleGuard = (expr: Expression, locals: readonly string[], negated: string): VisibleGuard =>
  ({ t: "VisibleGuard", expr, locals: [...locals], negated });

/** The element hides while a reading it is bound to is absent. */
export interface NullGuard { t: "NullGuard"; locals: string[]; sources: string[]; note: string }
export const NullGuard = (locals: readonly string[], sources: readonly string[], note: string): NullGuard =>
  ({ t: "NullGuard", locals: [...locals], sources: [...sources], note });

/** `applyAntiAlias(dc, <on>);`; the host has no switch. */
export interface AntiAlias { t: "AntiAlias"; on: boolean; comment: boolean }
export const AntiAlias = (on: boolean, comment = false): AntiAlias => ({ t: "AntiAlias", on, comment });

export interface Comment { t: "Comment"; text: string }
export const Comment = (text: string): Comment => ({ t: "Comment", text });

export interface Blank { t: "Blank" }
export const Blank = (): Blank => ({ t: "Blank" });

export type Op = SetColor | SetPen | Primitive | FillPolygon | ArcSpan | ArcProgress | Part | SeriesRebuild | SeriesDraw
  | LoadFont | Text | Glyph | LetText | IfNotNull | IfAod | IfAwake | Let | Assign | If | For | Continue | Return
  | SlotPull | SlotIcon | SlotText | LetSlotPick | LetAutoScale | VisibleGuard | NullGuard | AntiAlias | Comment | Blank;

// -- what lowering is given ------------------------------------------------------

/** Everything a kind's `lower` reads besides the placed element. */
export class DrawContext {
  readonly resolved: ResolvedFace;
  readonly aod: AodStyle;
  /** The reading locals whose absence substitutes the element's value. */
  readonly value_guards: readonly string[];
  /** The outlined group's ring pass to draw instead of the element. */
  readonly ring: RingPass | null;
  /** `Toybox.Complications` may be absent on some target. */
  readonly complications_guarded: boolean;
  /** On the host only, the type each slot is drawn showing, as `[slot, type]` pairs. */
  readonly picks: readonly (readonly [string, string])[];

  constructor(resolved: ResolvedFace, aod: AodStyle, valueGuards: readonly string[] = [], ring: RingPass | null = null,
    { complicationsGuarded = false, picks = [] }: { complicationsGuarded?: boolean; picks?: readonly (readonly [string, string])[] } = {}) {
    this.resolved = resolved;
    this.aod = aod;
    this.value_guards = valueGuards;
    this.ring = ring;
    this.complications_guarded = complicationsGuarded;
    this.picks = picks;
  }

  /** The type `slot` is drawn showing: its pick, when it has one the slot may show, else its `default:`. */
  shown(slot: ConfigDataSlot): string {
    const pick = new Map(this.picks.map(([a, b]) => [a, b])).get(slot.name);
    if (pick !== undefined && (slot.choices === "any" ? complications.TYPES.has(pick) : slot.choices.includes(pick))) return pick;
    return slot.default;
  }
}
