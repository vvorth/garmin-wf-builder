// `type: data`: the element half of the native Data axis, drawing whatever
// complication the wearer picked for a `config: slots:` slot. Port of
// wfb/kinds/data.py's build half.
import type { Span } from "../diagnostics.ts";
import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import { ICON_SIZE_NOTE } from "../ir/builder/glyphs.ts";
import { type ConfigDataSlot, DataElement, type Element, type Expression, HOLD_AUTO } from "../ir/model.ts";
import { dataHoldMethod, dataIconMethod } from "../ir/naming.ts";
import * as complications from "../complications.ts";
import * as icons from "../icons.ts";
import type { Face } from "../ir/model.ts";
import { alignmentShift, DATA_ICON_GAP, dataPairGeometry, longer, type Placed, PlacedData, type Resolver } from "../layout.ts";
import { formatG, repr, roundHalfEven as round, str, truthy } from "../py.ts";
import * as units from "../units.ts";
import { Box, IntBox } from "../units.ts";
import { type Common, ElementKind, IconFont, type Refusal, register, TextRun } from "./base.ts";
import {
  AodRestyled, Assign, Bin, Blank, Cmp, Comment, type Cond, Const, type DrawContext, Font, FontHeight, If, IsPulsing, Let, Lit,
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
    { code: "complication-slot", message: `unknown slot ${repr(raw)}`, note: "declared slots (config: slots:)", prefix: "" });
}

/** A data element's `color:`/`icon: {color:}` may not read anything absent-able. */
function checkSlotColorAbsence(b: Builder, node: Node, element: DataElement, key: string, color: Expression | null,
  note: string, label: string | null = null): void {
  if (color === null || !color.nullable) return;
  b.bag.error("complication-slot", `${element.id}: '${label || key}' reads ${repr(color.shown)}, which can be absent`,
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

/** The slot's multi-glyph icon font, or `null` when none of its choices has an icon. */
function iconRun(element: DataElement, face: Face): TextRun | null {
  if (element.icon_size === null) return null;
  const slot = face.config_data.get(element.slot);
  if (slot === undefined) return null;
  const mapped = slot.icons;
  if (mapped.size === 0) return null;
  const codepoints = new Set([...mapped.values()].map((si) => si.codepoint));
  const table = new Map([...mapped.values()].map((si): [string, string] => [si.key, si.codepoint]));
  if (slot.conditionIcons.size > 0) {
    // A weather choice's icon follows the pulled condition, so the font needs every condition's glyph.
    for (const c of icons.WEATHER_GLYPH_SET) codepoints.add(c);
    for (const name of icons.GARMIN_WEATHER_CONDITION_ICON.values()) table.set(name, icons.CATALOG.get(name)!.codepoint);
  }
  const glyphs = [...codepoints].sort(comparePoints).join("");
  const reference = mapped.get(slot.default) ?? [...mapped.values()].sort(byKey)[0]!;
  const key = icons.fontKey(element.icon_size, `slot_${element.slot}`, element.resolved_antialias);
  return new TextRun(`${element.id}.icon`, key, {
    span: element.span, icon: new IconFont(element.icon_size, glyphs, reference.codepoint, element.resolved_antialias), glyph_table: table,
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
    if (element.font_is_custom) runs.push(new TextRun(element.id, element.font, { glyphs: textGlyphs(element, face), span: element.span }));
    const icon = iconRun(element, face);
    if (icon !== null) runs.push(icon);
    return runs;
  }

  override resolve(r: Resolver, element: DataElement, parent: Box, depth: number): Placed {
    const [cx, cy] = r.point(element.at, parent);
    const font = r.fontForRef(element.font, element.font_is_custom);
    const widest = dataWidest(r, element);
    const textWidth = font.width(widest), lineHeight = font.lineHeight;
    let iconFontKey: string | null = null, iconPx = 0, iconWidth = 0;
    if (element.icon_size !== null) {
      const slot = r.face.config_data.get(element.slot);
      let referenceGlyph: string | null = null;
      if (slot !== undefined) {
        const mapped = slot.icons;
        if (mapped.size > 0) {
          const reference = mapped.get(slot.default) ?? [...mapped.values()].sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))[0]!;
          referenceGlyph = reference.codepoint;
        }
      }
      if (referenceGlyph !== null) {
        iconPx = units.pixelSize(element.icon_size, r.device.minorRadius);
        iconFontKey = icons.fontKey(element.icon_size, `slot_${element.slot}`, element.resolved_antialias);
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
    if (fontOk && b.isVectorFont(element.font, element.font_is_custom)) {
      b.bag.error("complication-slot", `${element.id}: 'font: font.${element.font}' is a 'face:' `
        + "(vector) font -- not accepted on a 'type: data' element", b.doc.span(node, "font"), {
        notes: [
          "a vector font is drawn straight from the device's own "
          + "resident face through Dc.drawText/drawAngledText/"
          + "drawRadialText -- a data element draws its reading "
          + "through a different path that only accepts a baked "
          + "bitmap font or one of the platform's fixed system fonts",
          "a vector font is only usable on a 'text' element",
          "declare this font with 'source:' instead, or point "
          + "'font:' at a baked or system font",
        ],
      });
    }

    if (element.on_hold !== null && element.on_hold !== HOLD_AUTO) {
      // A fixed target would disagree with the slot the moment the wearer repoints it.
      b.bag.error("complication-slot", `${element.id}: 'on_hold:' on a 'type: data' element only accepts `
        + `'auto', not ${repr(element.on_hold)}`, element.span, {
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
    const aod = ctx.aod;
    const prefix = constPrefix(p.id);
    const face = ctx.resolved.face;
    const slot = face.config_data.get(element.slot)!;
    const shown = ctx.shown(slot);
    const ctype = complications.TYPES.get(shown)!;
    const sample = DATA_SAMPLE.has(ctype.name) ? DATA_SAMPLE.get(ctype.name) : (ctype.value_type !== "string" ? 12 : "--");
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
    let iconFont: Font | null = null;
    if (p.icon_font_key !== null) {
      const icon = slot.icons.get(shown);
      let glyph: string | null = null;
      if (icon !== undefined) {
        glyph = icon.codepoint;
        if (slot.conditionIcons.has(shown) && typeof sample === "number" && Number.isInteger(sample)) {
          glyph = icons.CATALOG.get(icons.GARMIN_WEATHER_CONDITION_ICON.get(sample) ?? "weather_unknown")!.codepoint;
        }
      }
      ops.push(SlotIcon(fontField(p.icon_font_key), p.icon_font_key, dataIconMethod(element.id), guarded, glyph));
      iconFont = Font("iconFont", { baked: p.icon_font_key });
    }
    let code: string;
    if (p.font.is_custom) {
      ops.push(LoadFont("textFont", `_${fontField(p.font.reference)}`));
      code = "textFont";
    } else {
      code = `Graphics.${p.font.reference}`;
    }
    const font = Font(code, { baked: p.font.is_custom ? p.font.reference : null, metric: p.font.metric, px: p.font.px });
    ops.push(Blank(), SlotText({
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
    return out;
  }

  override describe(placed: Placed): string {
    return `a native Data-axis slot (\`slot: ${(placed as PlacedData).element.slot}\`)`;
  }
}

register(new DataKind());
