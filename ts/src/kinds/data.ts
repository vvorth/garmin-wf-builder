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
import { type Common, ElementKind, type Refusal, register } from "./base.ts";

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
}

register(new DataKind());
