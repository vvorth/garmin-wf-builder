// `type: data`: the element half of the native Data axis, drawing whatever
// complication the wearer picked for a `config: slots:` slot..
import type { Span } from "../diagnostics.ts";
import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import { ICON_SIZE_NOTE } from "../ir/builder/glyphs.ts";
import { type ConfigDataSlot, DataElement, type Element, type Expression, HOLD_AUTO } from "../ir/model.ts";
import { dataHoldMethod, dataIconMethod, fontResourceId } from "../ir/naming.ts";
import * as complications from "../complications.ts";
import * as icons from "../icons.ts";
import type { Face } from "../ir/model.ts";
import {
  alignmentShift, DATA_ICON_GAP, dataPairGeometry, garminCurveAngle, HIDDEN_BY_FONT, type IconTrack, justify, type LayoutFont, longer, type Placed, PlacedData,
  radialDirectionSign, radialSpacingRadius, radialTextBand, replaceFields, Resolver, resolvedCurve, textInk,
} from "../layout.ts";
import type { Device } from "../devices/device.ts";
import { flt } from "../draw/barrel.ts";
import { degrees, formatG, quoted, roundHalfEven, str, truthy } from "../py.ts";
import * as units from "../units.ts";
import { Box, IntBox, type Length, roundPx as round } from "../units.ts";
import { type Common, ElementKind, IconFont, type Refusal, register, TextRun } from "./base.ts";
import {
  AodRestyled, Assign, Bin, Blank, Call, Cmp, Comment, type Cond, Const, Conv, type DrawContext, Font, FontHeight, IconStep, If, IfNotNull, IsPulsing, Let,
  Lit, LoadFont, Local, LocalsSet, type Num, NumLocal, NumPick, type Op, type Paint, Paren, Return, SetColor, SlotIcon, SlotPull, SlotText,
  type Str, Text as DrawText, TextWidth,
} from "../draw/program.ts";
import { constPrefix, fontField, McLiteral } from "../emit/monkeyc/common.ts";
import type { Constants } from "../emit/monkeyc/layout_constants.ts";
import { configDataIds, configField } from "../ir/naming.ts";
import { DATA_SAMPLE } from "../sample.ts";

type Node = Map<DataKey, Data>;

/** Resolve a `slot: <name>` reference, a `data` element's or a gauge's, against `config: slots:`. */
export function resolveSlotReference(b: Builder, raw: string, span: Span | null): ConfigDataSlot | null {
  return b.config_data.resolve(b.bag, raw, span,
    { code: "complication-slot", message: `unknown slot ${quoted(raw)}`, note: "declared slots (config: slots:)", prefix: "" });
}

/** A data element's `color:`/`icon: {color:}` may not read anything absent-able. */
function checkSlotColorAbsence(b: Builder, node: Node, element: DataElement, key: string, color: Expression | null,
  note: string, label: string | null = null): void {
  if (color === null || !color.nullable) return;
  b.bag.error("complication-slot", `${element.id}: '${label || key}' reads ${quoted(color.shown)}, which can be absent`,
    b.doc.span(node, key), {
      notes: [note, "guard it in the expression instead, e.g. \"x != null and x > 100 ? color.hot : color.fg\""],
    });
}

/**
 * A radial reading takes its icon before or after the run, along the
 * circle; and with a radius the bake can resolve before layout, since the
 * icon's turns are baked from it.
 */
function checkRadialPair(b: Builder, node: Node, icon: Node, element: DataElement): void {
  const curve = element.curve!;
  if (curve.style !== "radial") return;
  if (element.icon_position !== "left" && element.icon_position !== "right") {
    b.bag.error("complication-slot", `${element.id}: a radial reading takes its icon before or after the run: `
      + "'icon: {position: left}' or 'icon: {position: right}', with any 'align:'",
    b.doc.span(icon, "position") ?? b.doc.span(node, "icon"), {
      notes: [`position: ${element.icon_position} would stack the icon across the run, outward or inward of the circle, `
        + "which moves the run off its own radius",
      `or draw the slot's icon as its own element: 'type: icon' with 'slot: ${element.slot}' and 'rotate:'`],
    });
    element.icon_size = null;
    return;
  }
  const radius = curve.radius;
  if (radius !== null && !(units.SIZE_UNITS as readonly string[]).includes(radius.unit)) {
    const curveNode = node.get("curve");
    b.bag.error("complication-slot", `${element.id}: beside an icon, 'curve: {radius:}' must be px or %r, not ${radius.unit}`,
      curveNode instanceof Map ? b.doc.span(curveNode, "radius") : b.doc.span(node, "curve"), {
        notes: ["the icon's turn is baked into its font before layout runs, so the radius it follows "
          + "cannot depend on a parent box (%) or an element's own font (pt)"],
      });
    element.icon_size = null;
  }
}

/** The types this slot can show that the build knows a rule for. */
function slotChoices(face: Face, element: DataElement): string[] {
  const slot = face.config_data.get(element.slot);
  if (slot === undefined) return [];
  if (slot.choices === "any") return complications.names();
  return slot.choices.filter((name) => complications.TYPES.has(name));
}

/** The widest plausible reading in `font`: the widest of the choices' readings, and the placeholder. */
function dataWidest(r: Resolver, element: DataElement, font: LayoutFont): string {
  let widest = "";
  for (const name of slotChoices(r.face, element)) {
    const candidate = complications.widestReading(name, element.unit, element.short);
    if (!widest || font.width(candidate) > font.width(widest)) widest = candidate;
  }
  if (element.absent === "placeholder" && element.placeholder) widest = longer(widest, element.placeholder);
  return widest;
}

/** Text the device supplies (a firmware string, a label): unbounded, so the whole alphabet. */
export const COMPLICATION_TEXT_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz ";

/** Every character the slot's reading could render, whichever choice the wearer picks. */
function textGlyphs(element: DataElement, face: Face): Set<string> {
  const glyphs = new Set<string>();
  for (const name of slotChoices(face, element)) {
    for (const c of complications.readingGlyphs(name, element.unit, element.short)) glyphs.add(c);
    if (["text", "training_status", "high_low"].includes(complications.READING.get(name)!)) for (const c of COMPLICATION_TEXT_ALPHABET) glyphs.add(c);
  }
  if (element.placeholder) for (const c of element.placeholder) glyphs.add(c);
  if (element.label !== "none") for (const c of COMPLICATION_TEXT_ALPHABET) glyphs.add(c);
  return glyphs;
}

const byKey = (a: icons.SlotIcon, b: icons.SlotIcon): number => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0);

/** The glyph a slot's icon font is sized and measured by: the default choice's, else the first by name; `null` with no icons. */
export function slotReferenceGlyph(slot: ConfigDataSlot | undefined): string | null {
  if (slot === undefined || slot.icons.size === 0) return null;
  return (slot.icons.get(slot.default) ?? [...slot.icons.values()].sort(byKey)[0]!).codepoint;
}

/** The icon font key of slot `slotName` at this size, anti-aliasing and turn: one font however many elements draw it. */
export function slotIconFontKey(slotName: string, size: Length | null, antialias: boolean, turn = 0): string {
  return icons.fontKey(size, `slot_${slotName}`, antialias, turn);
}

/** The sample frame's icon for `shown`: its catalogue glyph, or a weather type's for the sample condition. */
export function slotSampleGlyph(slot: ConfigDataSlot, shown: string, sample: unknown): string | null {
  const icon = slot.icons.get(shown);
  if (icon === undefined) return null;
  if (slot.conditionIcons.has(shown) && typeof sample === "number" && Number.isInteger(sample)) {
    return icons.CATALOG.get(icons.GARMIN_WEATHER_CONDITION_ICON.get(sample) ?? "weather_unknown")!.codepoint;
  }
  return icon.codepoint;
}

/** The sample reading a slot showing `shown` draws on the host. */
export function slotSample(shown: string): unknown {
  const ctype = complications.TYPES.get(shown)!;
  return DATA_SAMPLE.has(ctype.name) ? DATA_SAMPLE.get(ctype.name) : (ctype.value_type !== "string" ? 12 : "--");
}

/** A radial pair's pinned icon: the run's fixed end, its radius and the gap, for the bake and the layout to resolve per device. */
function pinnedTurn(element: DataElement): icons.PinnedTurn {
  const curve = element.curve!;
  return new icons.PinnedTurn(garminCurveAngle("radial", curve.angle), curve.radius!,
    element.icon_gap ?? new units.Length(DATA_ICON_GAP, "px"), element.align === "right", curve.direction);
}

/** A radial pair whose icon sits at the run's fixed end, so its place does not depend on the reading's width. */
function isPinned(element: DataElement): boolean {
  return (element.align === "left" && element.icon_position === "left") || (element.align === "right" && element.icon_position === "right");
}

/** A radial reading's run on `device`: the circle `radius:` names, its spacing radius, and the widest reading in its own font. */
function runGeometry(face: Face, element: DataElement, device: Device): icons.RunGeometry {
  const r = new Resolver(face, device, new Map());
  const font = r.textFont(element.font, element.font_is_custom, element.curve);
  const radius = round(units.pixelSize(element.curve!.radius, device.minorRadius));
  const ascent = font.metric !== null ? device.db.measure.ascent(font.metric) : font.lineHeight;
  return {
    radius, spacing: radialSpacingRadius(radius, element.vertical_align, element.curve!.direction, ascent, font.lineHeight),
    widest: font.available ? font.width(dataWidest(r, element, font)) : 0,
  };
}

/** A radial pair's icon at the free end, or beside a centred run: its turns are steps baked per device. */
function steppedTurn(element: DataElement, face: Face): icons.SteppedTurn {
  const curve = element.curve!;
  const place: icons.FreePlace = element.align === "center" ? (element.icon_position === "left" ? "center_left" : "center_right")
    : element.align === "left" ? "after" : "before";
  return new icons.SteppedTurn(garminCurveAngle("radial", curve.angle), element.icon_gap ?? new units.Length(DATA_ICON_GAP, "px"),
    place, curve.direction, (device) => runGeometry(face, element, device));
}

/**
 * A data element's icon font key and the turn it is baked at. An angled pair
 * turns by the curve's own angle; a radial icon's turn is per device, so its
 * font is this element's own, under one name on every device: one pinned
 * turn, or, at the free end, steps (`icons.stepKey`) the watch picks from.
 */
function dataIconFont(element: DataElement, face: Face): [string, number | icons.PinnedTurn | icons.SteppedTurn] {
  const curve = element.curve;
  const plain = (turn: number): [string, number] => [slotIconFontKey(element.slot, element.icon_size, element.resolved_antialias, turn), turn];
  if (curve === null || element.icon_upright) return plain(0);
  if (curve.style === "angled") return plain(icons.normalTurn(curve.angle.degrees));
  const id = constPrefix(element.id).toLowerCase();
  if (isPinned(element)) return [icons.fontKey(element.icon_size, `slot_${element.slot}_pinned_${id}`, element.resolved_antialias), pinnedTurn(element)];
  return [icons.fontKey(element.icon_size, `slot_${element.slot}_steps_${id}`, element.resolved_antialias), steppedTurn(element, face)];
}

/** A slot's multi-glyph icon font, or `null` when none of its choices has an icon. */
export function slotIconRun(label: string, face: Face, slotName: string, size: Length | null, antialias: boolean,
  turn: number | icons.PinnedTurn | icons.SteppedTurn, span: Span | null, key: string | null = null): TextRun | null {
  const slot = face.config_data.get(slotName);
  const reference = slotReferenceGlyph(slot);
  if (slot === undefined || reference === null) return null;
  const mapped = slot.icons;
  const codepoints = new Set([...mapped.values()].map((si) => si.codepoint));
  const table = new Map([...mapped.values()].map((si): [string, string] => [si.key, si.codepoint]));
  if (slot.conditionIcons.size > 0) {
    // A weather choice's icon follows the pulled condition, so the font needs every condition's glyph.
    for (const c of icons.WEATHER_GLYPH_SET) codepoints.add(c);
    for (const name of icons.GARMIN_WEATHER_CONDITION_ICON.values()) table.set(name, icons.CATALOG.get(name)!.codepoint);
  }
  const glyphs = [...codepoints].sort(comparePoints).join("");
  return new TextRun(label, key ?? slotIconFontKey(slotName, size, antialias, turn as number), {
    span, icon: new IconFont(size, glyphs, reference, antialias, turn), glyph_table: table,
  });
}

/** Python's string order: by code point. */
export function comparePoints(a: string, b: string): number {
  const x = Array.from(a), y = Array.from(b);
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const d = x[i]!.codePointAt(0)! - y[i]!.codePointAt(0)!;
    if (d !== 0) return d;
  }
  return x.length - y.length;
}

/** The box the native editor gets with a slot's drawable: the slot's rows, and every column the pair could reach. */
export function highlightBox(box: IntBox, anchorX: number, align: string, screenWidth: number): IntBox {
  let left: number, right: number;
  if (align === "left") [left, right] = [anchorX, screenWidth];
  else if (align === "right") [left, right] = [0, anchorX];
  else {
    const half = Math.max(Math.min(anchorX, screenWidth - anchorX), 0);
    [left, right] = [anchorX - half, anchorX + half];
  }
  return new IntBox(left, box.y, right - left, box.height).union(box);
}

/** The generated module a data element's reading is formatted by. */
export const SLOT_TEXT_MODULE = "SlotText";

type DrawFn = (x: Num, y: Num, face: Font, string: Str, justify: readonly string[]) => Op;

/** Any pair but the fast path: its alignment computed on the watch from the measured text and icon. */
function generalPair(element: DataElement, placed: PlacedData, prefix: string, font: Font, iconFont: Font | null,
  iconShown: Cond | null, textPaint: Paint, iconPaint: Paint | null, draw: DrawFn): Op[] {
  const cx = Const(`${prefix}_CX`, placed.anchor_point[0]);
  const cy = Const(`${prefix}_CY`, placed.anchor_point[1]);
  const gapValue: Num = element.icon_gap !== null ? Const(`${prefix}_ICON_GAP`, placed.icon_gap_px) : Lit(DATA_ICON_GAP);
  const hasIcon = iconShown !== null;
  const text = Local("text"), glyph = Local("iconGlyph");
  const ops: Op[] = [SetColor(textPaint)];
  const row = placed.icon_position === "left" || placed.icon_position === "right";
  let lead: string, trail: string, mainAlign: string, crossAlign: string, size: string, iconLocal: string, start: string;
  let center: Const, textSize: Num, iconSize: Num | null, justify: string[];
  if (row) {
    [lead, trail, mainAlign, crossAlign] = ["left", "right", element.align, element.vertical_align];
    [size, iconLocal, start, center] = ["Width", "iconGlyphWidth", "startX", cx];
    textSize = TextWidth(text, font);
    iconSize = iconFont !== null ? TextWidth(glyph, iconFont) : null;
    justify = ["TEXT_JUSTIFY_LEFT", "TEXT_JUSTIFY_VCENTER"];
  } else {
    [lead, trail, mainAlign, crossAlign] = ["top", "bottom", element.vertical_align, element.align];
    [size, iconLocal, start, center] = ["Height", "iconHeight", "startY", cy];
    textSize = FontHeight(font);
    iconSize = iconFont !== null ? FontHeight(iconFont) : null;
    justify = ["TEXT_JUSTIFY_CENTER"];
  }
  const textLocal = `text${size}`, total = `total${size}`;
  const position = placed.icon_position;
  if ((position === trail && hasIcon) || mainAlign !== lead) ops.push(Let(textLocal, textSize));
  if (position === lead || mainAlign !== lead) {
    ops.push(Let(iconLocal, Lit(0)));
    if (iconShown !== null && iconSize !== null) ops.push(If(iconShown, [Assign(iconLocal, iconSize)]));
  }
  if (position === lead || (position === trail && hasIcon) || mainAlign !== lead) {
    ops.push(Let("gap", iconShown !== null ? NumPick(iconShown, gapValue, Lit(0)) : Lit(0)));
  }
  const pieces = Bin("+", Bin("+", NumLocal(iconLocal), NumLocal("gap")), NumLocal(textLocal));
  if (mainAlign === lead) {
    ops.push(Let(start, center));
  } else if (mainAlign === trail) {
    ops.push(Let(total, pieces), Let(start, Bin("-", center, NumLocal(total))));
  } else {
    ops.push(Let(total, pieces), Let(start, Bin("-", center, Bin("/", NumLocal(total), Lit(2)))));
  }

  let cross: Num;
  if (row) {
    if (crossAlign === "center") {
      cross = cy;
    } else {
      ops.push(Let("rowHeight", FontHeight(font)));
      if (iconShown !== null && iconFont !== null) {
        ops.push(If(iconShown, [Let("iconRowHeight", FontHeight(iconFont)),
          If(Cmp(">", NumLocal("iconRowHeight"), NumLocal("rowHeight")), [Assign("rowHeight", NumLocal("iconRowHeight"))])]));
      }
      ops.push(Let("rowY", Bin(crossAlign === "top" ? "+" : "-", cy, Bin("/", NumLocal("rowHeight"), Lit(2)))));
      cross = NumLocal("rowY");
    }
  } else if (crossAlign === "center") {
    cross = cx;
  } else {
    ops.push(Let("textWidth", TextWidth(text, font)), Let("iconGlyphWidth", Lit(0)));
    if (iconShown !== null && iconFont !== null) ops.push(If(iconShown, [Assign("iconGlyphWidth", TextWidth(glyph, iconFont))]));
    ops.push(Let("pairWidth", NumPick(Cmp(">", NumLocal("iconGlyphWidth"), NumLocal("textWidth")), NumLocal("iconGlyphWidth"), NumLocal("textWidth"))));
    ops.push(Let("pairX", Bin(crossAlign === "left" ? "+" : "-", cx, Bin("/", NumLocal("pairWidth"), Lit(2)))));
    cross = NumLocal("pairX");
  }

  const at = (offset: string | null): [Num, Num] => {
    let along: Num = NumLocal(start);
    if (offset !== null) along = Bin("+", Bin("+", along, NumLocal(offset)), NumLocal("gap"));
    return row ? [along, cross] : [cross, along];
  };
  const setIconColor = (): Op[] => (iconPaint !== null ? [SetColor(iconPaint)] : []);

  if (position === lead) {
    if (iconShown !== null && iconFont !== null) ops.push(If(iconShown, [...setIconColor(), draw(...at(null), iconFont, glyph, justify)]));
    if (iconPaint !== null && iconFont !== null) ops.push(SetColor(textPaint));
    ops.push(draw(...at(iconLocal), font, text, justify));
  } else {
    ops.push(draw(...at(null), font, text, justify));
    if (iconShown !== null && iconFont !== null) ops.push(If(iconShown, [...setIconColor(), draw(...at(textLocal), iconFont, glyph, justify)]));
  }
  return ops;
}

/**
 * A radial pair's icon whose place follows the reading: its angle from the
 * measured width, its point on the middle of the run's band, and (unless
 * upright) the baked step nearest its turn, loaded only when the step changes.
 */
function trackedIcon(p: PlacedData, prefix: string, font: Font, iconFont: Font, iconShown: Cond, iconPaint: Paint | null, draw: DrawFn): Op[] {
  const track = p.icon_track!;
  const k = (name: string, value: number, float = true): Const => Const(`${prefix}_ICON_${name}`, float ? flt(value) : value);
  const width = NumLocal("textWidth"), theta = NumLocal("iconTheta");
  const ops: Op[] = [
    Let("textWidth", TextWidth(Local("text"), font)),
    Let("iconTheta", Bin("+", k("THETA", track.theta), Bin("*", k("PER_PX", track.per_px), width))),
  ];
  if (track.steps > 0) {
    const last = k("LAST", track.steps - 1, false);
    ops.push(Let("iconStep", Conv(Paren(Bin("+", Bin("*", width, k("STEP_PER_PX", track.steps_per_px)), Lit(flt(0.5)))), "toNumber")),
      If(Cmp(">", NumLocal("iconStep"), last), [Assign("iconStep", last)]),
      IconStep(fontField(p.icon_font_key!), p.icon_font_key!, `${prefix}_ICON_STEPS`, NumLocal("iconStep")));
  }
  const rounded = (n: Num): Num => Conv(Paren(Bin("+", n, Lit(flt(0.5)))), "toNumber");
  const r = k("R", track.middle);
  const x = rounded(Bin("+", Const(`${prefix}_CX`, p.anchor_point[0]), Bin("*", r, Call("Math.cos", [theta]))));
  const y = rounded(Bin("-", Const(`${prefix}_CY`, p.anchor_point[1]), Bin("*", r, Call("Math.sin", [theta]))));
  ops.push(If(iconShown, [...(iconPaint !== null ? [SetColor(iconPaint)] : []),
    draw(x, y, iconFont, Local("iconGlyph"), ["TEXT_JUSTIFY_CENTER", "TEXT_JUSTIFY_VCENTER"])]));
  return ops;
}

class DataKind extends ElementKind<DataElement> {
  readonly name = "data";
  readonly irClass = DataElement;
  override readonly extraSymbols = [dataIconMethod, dataHoldMethod];
  override readonly staticForbidden = [
    "a data element",
    "its reading is pulled fresh every frame, and the wearer can "
    + "repoint it to a different complication at any time -- a buffer "
    + "filled once would freeze both",
  ] as const;

  override textRuns(element: DataElement, face: Face): TextRun[] {
    const runs: TextRun[] = [];
    if (element.font_is_custom) {
      runs.push(new TextRun(element.id, element.font, {
        glyphs: textGlyphs(element, face), span: element.span, unsupported: element.unsupported, curve: element.curve,
      }));
    }
    const [key, turn] = dataIconFont(element, face);
    const icon = element.icon_size === null ? null
      : slotIconRun(`${element.id}.icon`, face, element.slot, element.icon_size, element.resolved_antialias, turn, element.span, key);
    if (icon !== null) runs.push(icon);
    return runs;
  }

  override hiddenReason(placed: Placed): string | null {
    return (placed as PlacedData).font.available ? null : HIDDEN_BY_FONT;
  }

  override resolve(r: Resolver, element: DataElement, parent: Box, depth: number): Placed {
    const [cx, cy] = r.point(element.at, parent);
    const font = r.textFont(element.font, element.font_is_custom, element.curve);
    const widest = dataWidest(r, element, font);
    const textWidth = font.width(widest), lineHeight = font.lineHeight;
    if (element.curve !== null) {
      let curve = resolvedCurve(element.curve);
      if (curve.style === "radial" && element.curve.radius !== null) {
        curve = replaceFields(curve, {
          radius_px: round(r.extent(element.curve.radius, parent, "minor", 0, null, element.resolved_min_1px, "curve.radius")),
        });
      }
      const reference = element.icon_size !== null ? slotReferenceGlyph(r.face.config_data.get(element.slot)) : null;
      const [iconKey, turnOf] = reference !== null ? dataIconFont(element, r.face) : [null, 0];
      // A stepped icon has no font under its own key: step 0 stands for every step's metrics.
      const iconFont = iconKey === null ? undefined : r.fonts.get(turnOf instanceof icons.SteppedTurn ? icons.stepKey(iconKey, 0) : iconKey);
      const iconPx = reference !== null ? units.pixelSize(element.icon_size, r.device.minorRadius) : 0;
      const iconWidth = reference === null ? 0 : iconFont !== undefined ? iconFont.measure(reference)[0] : iconPx;
      // Every glyph of a slot's font fits a `size:` square, so `size:` places the icon whichever the wearer picks.
      const pinWidth = iconPx;
      const gapPx = element.icon_gap !== null ? units.pixelSize(element.icon_gap, r.device.minorRadius) : DATA_ICON_GAP;
      let width = textWidth, height = lineHeight, inkAngle = curve.angle_garmin, iconPoint: [number, number] | null = null, iconTurn = 0;
      let iconTrack: IconTrack | null = null;
      const middle = (): number => {
        const ascent = font.metric !== null ? r.device.db.measure.ascent(font.metric) : lineHeight;
        const [inner, outer] = radialTextBand(curve.radius_px, lineHeight, element.vertical_align, curve.direction, ascent);
        return (inner + outer) / 2;
      };
      if (reference !== null && curve.style === "angled") {
        // The upright pair, turned whole about the anchor.
        const geometry = dataPairGeometry(element.icon_position, iconWidth, iconPx, textWidth, lineHeight, gapPx);
        [width, height] = [geometry.width, Math.max(geometry.height, 1)];
        iconTurn = element.icon_upright ? 0 : icons.normalTurn(curve.angle_degrees);
      } else if (reference !== null && !isPinned(element)) {
        // The icon follows the reading's width round the circle, computed on the watch; the turn snaps to a baked step.
        const free = steppedTurn(element, r.face);
        const path = free.path(r.device, pinWidth);
        let steps = 0, stepsPerPx = 0, turns: number[] = [], widestIcon = iconWidth;
        if (turnOf instanceof icons.SteppedTurn) {
          const baked = free.steps(r.device, pinWidth);
          [steps, stepsPerPx] = [baked.count, baked.perPx];
          for (let i = 0; i < steps; i++) {
            // The bake resolved the same steps from the same inputs; a step it did not bake would be a wrong glyph on the watch.
            const step = r.fonts.get(icons.stepKey(iconKey!, i));
            const turn = free.turnAt(baked.first + i * baked.size);
            if (step === undefined || step.rotate !== turn) throw new Error(`${element.id}: step ${i} of ${iconKey} was not baked at ${turn}deg on ${r.device.id}`);
            turns.push(turn);
            widestIcon = Math.max(widestIcon, step.measure(reference)[0]);
          }
          if (r.fonts.has(icons.stepKey(iconKey!, steps))) throw new Error(`${element.id}: ${iconKey} has more steps baked than ${r.device.id} reaches`);
        }
        iconTrack = { theta: path.theta, per_px: path.perPx, middle: middle(), steps, steps_per_px: stepsPerPx, turns };
        // A centred pair's text is centred off the authored angle so the pair, not the text, centres on it.
        curve = replaceFields(curve, { angle_garmin: path.textGarmin });
        // The lint sector: the pair along the run from the authored angle, as the alignment lays it out.
        width = textWidth + gapPx + widestIcon;
        if (element.vertical_align === "center") height = Math.max(lineHeight, iconPx);
      } else if (reference !== null) {
        // Centred half the reference glyph's advance plus the gap past the run's fixed end, in the middle of the run's band.
        const pin = pinnedTurn(element);
        const theta = pin.angle(r.device.minorRadius, pinWidth) * Math.PI / 180;
        iconTurn = element.icon_upright ? 0 : pin.turn(r.device.minorRadius, pinWidth);
        const mid = middle();
        iconPoint = [round(cx + mid * Math.cos(theta)), round(cy - mid * Math.sin(theta))];
        // The lint sector grows by the icon and its gap on the icon's side of the fixed end.
        const lead = gapPx + iconWidth;
        width = textWidth + lead;
        const sign = radialDirectionSign(curve.direction);
        inkAngle = curve.angle_garmin + (element.align === "right" ? sign : -sign) * degrees(lead / curve.radius_px);
        // shortcut: off a centred band the icon is assumed no taller than the line; widen the band if that ever bites.
        if (element.vertical_align === "center") height = Math.max(lineHeight, iconPx);
      }
      const box = textInk(cx, cy, width, height, element.align, element.vertical_align, {
        curveStyle: curve.style, angleGarmin: inkAngle, radiusPx: curve.radius_px, direction: curve.direction,
        metric: font.metric, pad: 0, device: r.device,
      }).box().rounded();
      return PlacedData.create({
        element, box, center: [round(cx), round(cy)], depth, anchor_point: [round(cx), round(cy)], font: font.resolved(), widest,
        icon_font_key: iconKey, icon_px: iconPx, icon_position: element.icon_position, icon_gap_px: gapPx, highlight: box, curve,
        measured_width: round(width), line_height: height, ink_angle_garmin: inkAngle, icon_point: iconPoint, icon_turn: iconTurn,
        icon_track: iconTrack,
      });
    }
    let iconFontKey: string | null = null, iconPx = 0, iconWidth = 0;
    if (element.icon_size !== null) {
      const referenceGlyph = slotReferenceGlyph(r.face.config_data.get(element.slot));
      if (referenceGlyph !== null) {
        iconPx = units.pixelSize(element.icon_size, r.device.minorRadius);
        iconFontKey = slotIconFontKey(element.slot, element.icon_size, element.resolved_antialias);
        const iconFont = r.fonts.get(iconFontKey);
        iconWidth = iconFont !== undefined ? iconFont.measure(referenceGlyph)[0] : iconPx;
      }
    }
    const gapPx = element.icon_gap !== null ? units.pixelSize(element.icon_gap, r.device.minorRadius) : DATA_ICON_GAP;
    const geometry = dataPairGeometry(element.icon_position, iconWidth, iconPx, textWidth, lineHeight, gapPx);
    const height = Math.max(geometry.height, 1);
    // The lint box only: the device centres the real pair on the unshifted anchor at runtime.
    const [dx, dy] = alignmentShift(geometry.width, height, element.align, element.vertical_align);
    const rounded = new Box(cx + dx - geometry.width / 2, cy + dy - height / 2, geometry.width, height).rounded();
    return PlacedData.create({
      element, box: rounded, center: [round(cx), round(cy)], depth, anchor_point: [round(cx), round(cy)],
      font: font.resolved(), widest, icon_font_key: iconFontKey, icon_px: iconPx, icon_position: element.icon_position,
      icon_gap_px: gapPx, highlight: highlightBox(rounded, round(cx), element.align, r.device.width),
    });
  }

  build(b: Builder, node: Node, common: Common): Element {
    const slotRaw = node.get("slot");
    const slot = resolveSlotReference(b, str(slotRaw), b.doc.span(node, "slot"));

    const rawIcon = node.get("icon");
    const icon: Node = rawIcon instanceof Map ? rawIcon : new Map();
    const iconSize = b.bakedSizeLength(icon, "size", { code: "complication-slot", label: "icon: {size:}", note: ICON_SIZE_NOTE });
    const iconPosition = (icon.get("position") ?? "left") as string;
    let iconGap = b.bakedSizeLength(icon, "gap", {
      code: "complication-slot", label: "icon: {gap:}",
      note: "the same restriction the icon's size has -- an icon's font is "
        + "baked once, before layout runs, so the gap that sits "
        + "against it cannot depend on a parent box (%) or an "
        + "element's own font (pt)",
    });
    if (iconGap !== null && iconGap.value < 0) {
      b.bag.error("complication-slot", `icon: {gap:} must not be negative, got ${formatG(iconGap.value)}${iconGap.unit}`,
        b.doc.span(icon, "gap"));
      iconGap = null;
    }
    const iconColor = b.colorExpression(icon, "color");

    if (node.has("format")) {
      b.bag.error("complication-slot", `${common.id}: 'format:' is not accepted on a 'type: data' element`,
        b.doc.span(node, "format"), {
          notes: [
            "Complications.Complication.value is a String or Number or "
            + "Float or Long or Double union whose concrete type genuinely "
            + "varies by which choice the wearer picks -- a format string "
            + "written for one choice would be silently wrong for another",
            "this element formats each type by its own rule instead (a "
            + "time of day, a duration, a pace, a rounded temperature, ...); "
            + "use 'unit:', 'short:' and 'label:' to adjust it",
          ],
        });
    }

    const color = b.colorExpression(node, "color");
    const [align, verticalAlign] = b.alignment(node);
    const absence = b.absence(node);
    const element = DataElement.create({
      ...common,
      slot: slot !== null ? slot.name : str(slotRaw),
      icon_size: iconSize,
      color,
      icon_position: iconPosition,
      icon_gap: iconGap,
      icon_color: iconColor,
      icon_upright: icon.get("upright") === true,
      label: (node.get("label") ?? "none") as string,
      unit: truthy(node.get("unit") ?? false),
      short: truthy(node.get("short") ?? false),
      absent: absence.absent || "hide",
      placeholder: absence.placeholder,
      align,
      vertical_align: verticalAlign,
    });
    const fontOk = b.resolveFont(node, element);
    const fontIsVector = fontOk && b.isVectorFont(element.font, element.font_is_custom);
    const fontNote = b.fontKindNote(element.font, element.font_is_custom);
    if (node.has("curve")) {
      element.curve = b.buildCurve(node, element.id, { verticalAlign: element.vertical_align, fontOk, fontIsVector, fontNote });
      if (element.curve !== null && element.icon_size !== null) checkRadialPair(b, node, icon, element);
    }
    if (icon.has("upright") && !node.has("curve")) {
      b.bag.error("complication-slot", `${element.id}: 'icon: {upright:}' applies only beside 'curve:'`, b.doc.span(icon, "upright"), {
        notes: ["an upright reading's icon is already upright"],
      });
    }
    if (fontOk && node.has("unsupported") && !element.inSubscreen) b.checkUnsupported(node, element.id, fontIsVector, fontNote);

    if (element.on_hold !== null && element.on_hold !== HOLD_AUTO) {
      // A fixed target would disagree with the slot the moment the wearer repoints it.
      b.bag.error("complication-slot", `${element.id}: 'on_hold:' on a 'type: data' element only accepts `
        + `'auto', not ${quoted(element.on_hold)}`, element.span, {
        notes: [
          "a slot already draws whatever complication the wearer chose in "
          + "the native editor -- opening a fixed, different glance on hold "
          + "would silently disagree with what is on screen the moment the "
          + "wearer repoints it",
          "'on_hold: auto' opens the glance the wearer's own current pick "
          + "belongs to (Complications.exitTo on this slot's own id), "
          + "resolved fresh on every hold rather than fixed at build time",
          "to always launch one fixed glance regardless of what this slot "
          + "shows, bind a plain 'text'/'icon' element to the matching "
          + "'complication.<name>' source and put 'on_hold: <name>' there instead",
        ],
      });
      element.on_hold = null;
    }

    if (color === null) {
      b.require(node, "color", "a data element needs a color");
    } else {
      checkSlotColorAbsence(b, node, element, "color", color,
        "a data element's colour has no 'absent:' of its own -- 'absent:' "
        + "governs the pulled reading, not the element's appearance");
    }
    checkSlotColorAbsence(b, icon, element, "color", iconColor,
      "a data element's colours have no 'absent:' of their own -- "
      + "'absent:' governs the pulled reading, not the element's appearance", "icon: {color:}");
    return element;
  }

  override aodRefusal(key: string): Refusal | null {
    if (key === "font") {
      return ["aod", "a data element's 'aod: {font: ...}' override is not implemented yet",
        ["restyle this element's 'color:'/'icon: {color:}' in AOD instead, or drop the font override for now"]];
    }
    return null;
  }

  override lower(ctx: DrawContext, placed: Placed): Op[] {
    const p = placed as PlacedData;
    const element = p.element;
    const face = ctx.resolved.face;
    const slot = face.config_data.get(element.slot)!;
    const shown = ctx.shown(slot);
    const guarded = ctx.complications_guarded;
    const ops: Op[] = [
      Comment("the editor is animating this exact slot right now -- skip it, or the"),
      Comment("system draws it twice while it pulses (SDK sample's own comment);"),
      Comment("drawSlot lifts this for the editor's own drawable"),
      If(IsPulsing(configDataIds(face).get(element.slot)!), [Return()]),
      Blank(),
      Comment(`slot: ${element.slot}`),
      SlotPull(configField(`data_${element.slot}`), guarded, DATA_SAMPLE.get(shown) ?? null),
    ];
    if (p.icon_font_key !== null) {
      ops.push(SlotIcon(fontField(p.icon_font_key), p.icon_font_key, dataIconMethod(element.id), guarded,
        slotSampleGlyph(slot, shown, slotSample(shown))));
    }
    let font: Font;
    if (p.font.is_vector) {
      // A device-resident face: null where the device publishes none, and then nothing draws.
      ops.push(LoadFont("textFont", `_${fontField(p.font.reference)}`, { onNull: "none" }));
      font = Font("textFont", { metric: p.font.metric, vector: true });
    } else if (p.font.is_custom) {
      ops.push(LoadFont("textFont", `_${fontField(p.font.reference)}`));
      font = Font("textFont", { baked: p.font.reference, metric: p.font.metric, px: p.font.px });
    } else {
      font = Font(`Graphics.${p.font.reference}`, { metric: p.font.metric, px: p.font.px });
    }
    const drawing = this.drawing(ctx, p, font);
    return p.font.is_vector ? [...ops, Blank(), IfNotNull("textFont", drawing)] : [...ops, Blank(), ...drawing];
  }

  /** The reading, and its icon: pulled into `text`, then drawn curved, or as a pair centred on the watch. */
  private drawing(ctx: DrawContext, p: PlacedData, font: Font): Op[] {
    const element = p.element;
    const aod = ctx.aod;
    const prefix = constPrefix(p.id);
    const shown = ctx.shown(ctx.resolved.face.config_data.get(element.slot)!);
    const ctype = complications.TYPES.get(shown)!;
    const sample = slotSample(shown);
    const guarded = ctx.complications_guarded;
    const iconFont = p.icon_font_key !== null ? Font("iconFont", { baked: p.icon_font_key }) : null;
    const ops: Op[] = [];
    ops.push(SlotText({
      module: SLOT_TEXT_MODULE, guarded, unit: element.unit, short: element.short, label: element.label, absent: element.absent,
      placeholder: element.placeholder, type_name: ctype.name, sample,
      label_sample: ({ short: "Now ", long: "Current " } as Record<string, string>)[element.label ?? ""] ?? "",
    }));
    const textPaint = AodRestyled(element, "color");
    const hasOverride = aod.on && element.aod !== null && element.aod.icon_color !== null;
    let iconPaint: Paint | null;
    if (element.icon_color === null && !hasOverride) iconPaint = null;
    else if (element.icon_color !== null) iconPaint = AodRestyled(element, "icon_color");
    else iconPaint = AodRestyled(element, "icon_color", textPaint);
    const text = Local("text"), glyphText = Local("iconGlyph");
    const cx = Const(`${prefix}_CX`, p.anchor_point[0]), cy = Const(`${prefix}_CY`, p.anchor_point[1]);
    const iconShown = iconFont !== null ? LocalsSet(["iconGlyph", "iconFont"]) : null;
    const centred = ["TEXT_JUSTIFY_CENTER", "TEXT_JUSTIFY_VCENTER"];
    let draw: DrawFn = (x, y, face_, string, justify) =>
      DrawText(x, y, face_, string, justify, justify.includes("TEXT_JUSTIFY_VCENTER") ? "center" : "top", { joined: true });
    if (p.curve.style !== null) {
      const angle = Const(`${prefix}_ANGLE`, flt(p.curve.angle_garmin));
      if (p.curve.style === "radial" || iconFont === null || iconShown === null) {
        const radius = p.curve.style === "radial" ? Const(`${prefix}_RADIUS`, p.curve.radius_px) : null;
        ops.push(SetColor(textPaint), DrawText(cx, cy, font, text, justify(element), element.vertical_align, {
          align: element.align, style: p.curve.style, angle, radius, direction: p.curve.direction, box: p.innerBox,
        }));
        if (iconFont !== null && iconShown !== null && p.icon_point !== null) {
          // Pinned at a build-time point; its font is baked turned to face the way the run does there.
          const at = (axis: "X" | "Y", value: number): Const => Const(`${prefix}_ICON_${axis}`, value);
          ops.push(If(iconShown, [...(iconPaint !== null ? [SetColor(iconPaint)] : []),
            draw(at("X", p.icon_point[0]), at("Y", p.icon_point[1]), iconFont, glyphText, centred)]));
        } else if (iconFont !== null && iconShown !== null && p.icon_track !== null) {
          ops.push(...trackedIcon(p, prefix, font, iconFont, iconShown, iconPaint, draw));
        }
        return ops;
      }
      // An angled pair: the upright pair's points, turned about the anchor; the icon centred on its turned centre.
      const rad = p.curve.angle_degrees * Math.PI / 180;
      const cos = Const(`${prefix}_COS`, flt(Math.cos(rad))), sin = Const(`${prefix}_SIN`, flt(Math.sin(rad)));
      const rounded = (n: Num): Num => Conv(Paren(Bin("+", n, Lit(flt(0.5)))), "toNumber");
      const offset = (n: Num, c: Const): Num | null => (n.t === "Const" && n.name === c.name ? null : Paren(Bin("-", n, c)));
      const plus = (base: Num, op: string, d: Num | null, k: Const): Num => (d === null ? base : Bin(op, base, Bin("*", d, k)));
      const turned = (x: Num, y: Num): [Num, Num] => {
        const along = offset(x, cx), across = offset(y, cy);
        return [rounded(plus(plus(cx, "+", along, cos), "-", across, sin)), rounded(plus(plus(cy, "+", along, sin), "+", across, cos))];
      };
      const upright = draw;
      draw = (x, y, face_, string, justify) => {
        const row = justify.includes("TEXT_JUSTIFY_VCENTER");
        if (face_ === iconFont) {
          const centre: [Num, Num] = row ? [Bin("+", x, Bin("/", TextWidth(string, face_), Lit(2))), y]
            : [x, Bin("+", y, Bin("/", FontHeight(face_), Lit(2)))];
          return upright(...turned(...centre), face_, string, centred);
        }
        return DrawText(...turned(x, y), face_, string, justify, row ? "center" : "top", { style: "angled", angle, box: p.innerBox });
      };
    }
    const fast = p.icon_position === "left" && element.icon_gap === null && iconPaint === null
      && element.align === "center" && element.vertical_align === "center";
    if (fast) {
      const row = ["TEXT_JUSTIFY_LEFT", "TEXT_JUSTIFY_VCENTER"];
      ops.push(SetColor(textPaint), Let("textWidth", TextWidth(text, font)), Let("iconWidth", Lit(0)));
      if (iconFont !== null && iconShown !== null) {
        ops.push(If(iconShown, [Assign("iconWidth", Bin("+", TextWidth(glyphText, iconFont), Lit(DATA_ICON_GAP)))]));
      }
      ops.push(Let("totalWidth", Bin("+", NumLocal("iconWidth"), NumLocal("textWidth"))),
        Let("startX", Bin("-", cx, Bin("/", NumLocal("totalWidth"), Lit(2)))));
      if (iconFont !== null && iconShown !== null) ops.push(If(iconShown, [draw(NumLocal("startX"), cy, iconFont, glyphText, row)]));
      ops.push(draw(Bin("+", NumLocal("startX"), NumLocal("iconWidth")), cy, font, text, row));
      return ops;
    }
    return [...ops, ...generalPair(element, p, prefix, font, iconFont, iconShown, textPaint, iconPaint, draw)];
  }

  override layoutConstants(prefix: string, placed: Placed): Constants {
    const p = placed as PlacedData;
    const out: Constants = [
      [`${prefix}_CX`, p.anchor_point[0], "the icon+reading pair is centred here at runtime"],
      [`${prefix}_CY`, p.anchor_point[1], ""],
    ];
    if (p.element.icon_gap !== null && p.icon_point === null && p.icon_track === null) out.push([`${prefix}_ICON_GAP`, p.icon_gap_px, "icon: {gap:} resolved for this device"]);
    if (p.curve.style !== null) {
      const authorNote = p.curve.style === "radial"
        ? `${formatG(p.curve.angle_degrees)}deg clockwise from 12 o'clock`
        : `${formatG(p.curve.angle_degrees)}deg clockwise rotation from upright`;
      out.push([`${prefix}_ANGLE`, flt(p.curve.angle_garmin), `${authorNote}, in Garmin's convention`]);
      if (p.curve.style === "radial") out.push([`${prefix}_RADIUS`, p.curve.radius_px, ""]);
      if (p.icon_point !== null) {
        out.push([`${prefix}_ICON_X`, p.icon_point[0], `the pinned icon's centre; its font is baked turned ${formatG(p.icon_turn)}deg here`],
          [`${prefix}_ICON_Y`, p.icon_point[1], ""]);
      } else if (p.icon_track !== null) {
        const t = p.icon_track;
        out.push([`${prefix}_ICON_THETA`, flt(t.theta), "the icon's centre for an empty reading, radians in Garmin's convention"],
          [`${prefix}_ICON_PER_PX`, flt(t.per_px), "radians it moves per pixel of reading, laid out along the run's baseline circle"],
          [`${prefix}_ICON_R`, flt(t.middle), "the middle of the run's band"]);
        if (t.steps > 0) {
          const keys = Array.from({ length: t.steps }, (_, i) => `Rez.Fonts.${fontResourceId(icons.stepKey(p.icon_font_key!, i))}`);
          out.push([`${prefix}_ICON_STEP_PER_PX`, flt(t.steps_per_px), `the nearest of ${t.steps} turns is step round(width * this)`],
            [`${prefix}_ICON_LAST`, t.steps - 1, ""],
            [`${prefix}_ICON_STEPS`, new McLiteral("Array<ResourceId>", `[${keys.join(", ")}]`),
              `the icon baked turned ${t.turns.map((turn) => formatG(roundHalfEven(turn * 10) / 10)).join(", ")}deg`]);
        }
      } else if (p.curve.style === "angled" && p.icon_font_key !== null) {
        const rad = p.curve.angle_degrees * Math.PI / 180;
        out.push([`${prefix}_COS`, flt(Math.cos(rad)), "the pair turns about the anchor by the curve's angle"], [`${prefix}_SIN`, flt(Math.sin(rad)), ""]);
      }
    }
    return out;
  }

  override describe(placed: Placed): string {
    return `a native Data-axis slot (\`slot: ${(placed as PlacedData).element.slot}\`)`;
  }
}

register(new DataKind());
