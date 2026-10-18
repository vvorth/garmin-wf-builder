// `type: data`: the element half of the native Data axis, drawing whatever
// complication the wearer picked for a `config: slots:` slot..
import type { Span } from "../diagnostics.ts";
import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import { ICON_SIZE_NOTE } from "../ir/builder/glyphs.ts";
import { type ConfigDataSlot, DataElement, type Element, type Expression, HOLD_AUTO } from "../ir/model.ts";
import { dataHoldMethod, dataIconMethod } from "../ir/naming.ts";
import * as complications from "../complications.ts";
import * as icons from "../icons.ts";
import type { Face } from "../ir/model.ts";
import {
  alignmentShift, DATA_ICON_GAP, dataPairGeometry, HIDDEN_BY_FONT, justify, longer, type Placed, PlacedData, replaceFields, type Resolver,
  resolvedCurve, textInk,
} from "../layout.ts";
import { flt } from "../draw/barrel.ts";
import { formatG, quoted, str, truthy } from "../py.ts";
import * as units from "../units.ts";
import { Box, IntBox, type Length, roundPx as round } from "../units.ts";
import { type Common, ElementKind, IconFont, type Refusal, register, TextRun } from "./base.ts";
import {
  AodRestyled, Assign, Bin, Blank, Cmp, Comment, type Cond, Const, type DrawContext, Font, FontHeight, If, IfNotNull, IsPulsing, Let, Lit,
  LoadFont, Local, LocalsSet, type Num, NumLocal, NumPick, type Op, type Paint, Return, SetColor, SlotIcon, SlotPull, SlotText,
  type Str, Text as DrawText, TextWidth,
} from "../draw/program.ts";
import { constPrefix, fontField } from "../emit/monkeyc/common.ts";
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

/** The types this slot can show that the build knows a rule for. */
function slotChoices(face: Face, element: DataElement): string[] {
  const slot = face.config_data.get(element.slot);
  if (slot === undefined) return [];
  if (slot.choices === "any") return complications.names();
  return slot.choices.filter((name) => complications.TYPES.has(name));
}

/** The widest plausible reading: the widest of the choices' readings, and the placeholder. */
function dataWidest(r: Resolver, element: DataElement): string {
  const font = r.fontForRef(element.font, element.font_is_custom);
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

/** A slot's multi-glyph icon font, or `null` when none of its choices has an icon. */
export function slotIconRun(label: string, face: Face, slotName: string, size: Length | null, antialias: boolean, turn: number,
  span: Span | null): TextRun | null {
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
  return new TextRun(label, slotIconFontKey(slotName, size, antialias, turn), {
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
    const icon = element.icon_size === null ? null
      : slotIconRun(`${element.id}.icon`, face, element.slot, element.icon_size, element.resolved_antialias, 0, element.span);
    if (icon !== null) runs.push(icon);
    return runs;
  }

  override hiddenReason(placed: Placed): string | null {
    return (placed as PlacedData).font.available ? null : HIDDEN_BY_FONT;
  }

  override resolve(r: Resolver, element: DataElement, parent: Box, depth: number): Placed {
    const [cx, cy] = r.point(element.at, parent);
    const font = r.textFont(element.font, element.font_is_custom, element.curve);
    const widest = dataWidest(r, element);
    const textWidth = font.width(widest), lineHeight = font.lineHeight;
    if (element.curve !== null) {
      let curve = resolvedCurve(element.curve);
      if (curve.style === "radial" && element.curve.radius !== null) {
        curve = replaceFields(curve, {
          radius_px: round(r.extent(element.curve.radius, parent, "minor", 0, null, element.resolved_min_1px, "curve.radius")),
        });
      }
      const box = textInk(cx, cy, textWidth, lineHeight, element.align, element.vertical_align, {
        curveStyle: curve.style, angleGarmin: curve.angle_garmin, radiusPx: curve.radius_px, direction: curve.direction,
        metric: font.metric, pad: 0, device: r.device,
      }).box().rounded();
      return PlacedData.create({
        element, box, center: [round(cx), round(cy)], depth, anchor_point: [round(cx), round(cy)], font: font.resolved(), widest,
        icon_position: element.icon_position, highlight: box, curve, measured_width: round(textWidth), line_height: lineHeight,
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
      if (element.curve !== null && element.icon_size !== null) {
        b.bag.error("complication-slot", `${element.id}: a curved reading takes no 'icon:' here`, b.doc.span(node, "icon"), {
          notes: ["draw the slot's icon as its own element, placed and turned freely: "
            + "'type: icon' with 'slot: " + element.slot + "' and 'rotate:'"],
        });
      }
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
    if (p.curve.style !== null) {
      const angle = Const(`${prefix}_ANGLE`, flt(p.curve.angle_garmin));
      const radius = p.curve.style === "radial" ? Const(`${prefix}_RADIUS`, p.curve.radius_px) : null;
      return [...ops, SetColor(textPaint), DrawText(cx, cy, font, text, justify(element), element.vertical_align, {
        align: element.align, style: p.curve.style, angle, radius, direction: p.curve.direction, box: p.innerBox,
      })];
    }
    const iconShown = iconFont !== null ? LocalsSet(["iconGlyph", "iconFont"]) : null;
    const draw: DrawFn = (x, y, face_, string, justify) =>
      DrawText(x, y, face_, string, justify, justify.includes("TEXT_JUSTIFY_VCENTER") ? "center" : "top", { joined: true });
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
    if (p.element.icon_gap !== null) out.push([`${prefix}_ICON_GAP`, p.icon_gap_px, "icon: {gap:} resolved for this device"]);
    if (p.curve.style !== null) {
      const authorNote = p.curve.style === "radial"
        ? `${formatG(p.curve.angle_degrees)}deg clockwise from 12 o'clock`
        : `${formatG(p.curve.angle_degrees)}deg clockwise rotation from upright`;
      out.push([`${prefix}_ANGLE`, flt(p.curve.angle_garmin), `${authorNote}, in Garmin's convention`]);
      if (p.curve.style === "radial") out.push([`${prefix}_RADIUS`, p.curve.radius_px, ""]);
    }
    return out;
  }

  override describe(placed: Placed): string {
    return `a native Data-axis slot (\`slot: ${(placed as PlacedData).element.slot}\`)`;
  }
}

register(new DataKind());
