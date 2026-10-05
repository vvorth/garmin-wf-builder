// `type: data`: the element half of the native Data axis, drawing whatever
// complication the wearer picked for a `config: slots:` slot. Port of
// wfb/kinds/data.py's build half.
import type { Span } from "../diagnostics.ts";
import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import { ICON_SIZE_NOTE } from "../ir/builder/glyphs.ts";
import { type ConfigDataSlot, DataElement, type Element, type Expression, HOLD_AUTO } from "../ir/model.ts";
import { dataHoldMethod, dataIconMethod } from "../ir/naming.ts";
import { formatG, repr, str, truthy } from "../py.ts";
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
