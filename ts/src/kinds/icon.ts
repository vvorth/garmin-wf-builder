// `type: icon`: one glyph drawn from a baked icon font, static or chosen at
// runtime from a bound value (`icon: {for:}`): its build half.
import * as catalog from "../catalog.ts";
import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import { ICON_SIZE_NOTE } from "../ir/builder/glyphs.ts";
import { type Element, type Face, HOLD_AUTO, IconElement } from "../ir/model.ts";
import { configDataIds, configField, dataIconMethod } from "../ir/naming.ts";
import { DATA_SAMPLE } from "../sample.ts";
import { resolveSlotReference, slotIconFontKey, slotIconRun, slotReferenceGlyph, slotSample, slotSampleGlyph } from "./data.ts";
import * as icons from "../icons.ts";
import { alignmentShift, justify, type Placed, PlacedIcon, type Resolver } from "../layout.ts";
import { quoted, str } from "../py.ts";
import * as units from "../units.ts";
import { Box, roundPx as round } from "../units.ts";
import { type Common, ElementKind, IconFont, register, TextRun } from "./base.ts";
import {
  AodDimmed, AodRestyled, Blank, Comment, Const, type DrawContext, Font, Glyph, IconChoice, If, IfNotNull, IsPulsing, LoadFont, Local,
  LocalsSet, type Op, type Paint, Return, RingColor, SetColor, Shifted, SlotIcon, SlotPull, type Str, StrLit,
} from "../draw/program.ts";
import { constPrefix, fontField } from "../emit/monkeyc/common.ts";
import type { Constants } from "../emit/monkeyc/layout_constants.ts";
import { discPerimeterOffsets } from "../ir/model.ts";
import { bakedRing, bakedRingLocal } from "./text.ts";

type Node = Map<DataKey, Data>;
type Placement = Pick<IconElement, "size" | "color" | "align" | "vertical_align" | "rotate">;

/** `icon: {codepoint: "U+F0BC"}`: a codepoint the catalogue does not name, spelled so it survives a review. */
function buildGlyphIcon(b: Builder, node: Node, spec: Node, common: Common, placement: Placement): Element {
  const raw = str(spec.get("codepoint"));
  const character = b.resolveIconGlyph(raw, b.doc.span(spec, "codepoint") ?? b.doc.span(node, "icon")) ?? icons.FALLBACK_CODEPOINT;
  return IconElement.create({ ...common, icon: raw.toUpperCase(), codepoint: character, ...placement });
}

class IconKind extends ElementKind<IconElement> {
  readonly name = "icon";
  readonly irClass = IconElement;
  override readonly ringed = true;

  override resolve(r: Resolver, element: IconElement, parent: Box, depth: number): Placed {
    const [cx, cy] = r.point(element.at, parent);
    // Independent of `parent`: an icon's font is baked once, before any box is resolved.
    const px = units.pixelSize(element.size, r.device.minorRadius);
    let key: string, measureCodepoint: string;
    if (element.slot !== null) {
      // The glyph follows the wearer's pick; every glyph fits a `size:` square, so measure the default pick's.
      key = slotIconFontKey(element.slot, element.size, element.resolved_antialias, element.turn);
      measureCodepoint = slotReferenceGlyph(r.face.config_data.get(element.slot)) ?? icons.FALLBACK_CODEPOINT;
    } else if (element.isDynamic) {
      // The real glyph is chosen on the device; every glyph fits a `size:` square, so measure one.
      key = icons.fontKey(element.size, icons.DYNAMIC_WEATHER_TAG, element.resolved_antialias, element.turn);
      measureCodepoint = icons.WEATHER_BAKE_REFERENCE_GLYPH;
    } else {
      key = icons.fontKey(element.size, element.codepoint, element.resolved_antialias, element.turn);
      measureCodepoint = element.codepoint;
    }
    const font = r.fonts.get(key);
    const [width, height] = font !== undefined ? font.measure(measureCodepoint) : [px, px];
    // The lint box only: the runtime `drawText` anchor stays put; alignment is a device-side justify.
    const [dx, dy] = alignmentShift(width, height, element.align, element.vertical_align);
    const box = new Box(cx + dx - width / 2, cy + dy - height / 2, width, height);
    return PlacedIcon.create({
      element, box: box.rounded(), center: [round(cx), round(cy)], depth, size: px, font_key: key, codepoint: measureCodepoint,
      anchor_point: [round(cx), round(cy)], justify: justify(element),
    });
  }

  override textRuns(element: IconElement, face: Face): TextRun[] {
    if (element.slot !== null) {
      const run = slotIconRun(element.id, face, element.slot, element.size, element.resolved_antialias, element.turn, element.span);
      return run !== null ? [run] : [];
    }
    let glyphKey: string, glyphs: string, reference: string, table: Map<string, string> | null = null;
    if (element.isDynamic) {
      // The glyph is chosen on the device, so the font holds every one it could be.
      glyphKey = icons.DYNAMIC_WEATHER_TAG;
      glyphs = icons.WEATHER_GLYPH_SET;
      reference = icons.WEATHER_BAKE_REFERENCE_GLYPH;
      table = new Map([...new Set(icons.GARMIN_WEATHER_CONDITION_ICON.values())].map((name) => [name, icons.CATALOG.get(name)!.codepoint]));
    } else {
      glyphKey = glyphs = reference = element.codepoint;
    }
    const key = icons.fontKey(element.size, glyphKey, element.resolved_antialias, element.turn);
    return [new TextRun(element.id, key, {
      span: element.span, icon: new IconFont(element.size, glyphs, reference, element.resolved_antialias, element.turn), glyph_table: table,
    })];
  }

  build(b: Builder, node: Node, common: Common): Element {
    const name = node.get("icon");
    const spec = name instanceof Map ? name : null;
    const dynamic = spec !== null && spec.has("for") ? spec : null;
    if (node.has("slot")) return this.buildSlot(b, node, common);
    if (name === undefined || name === null) {
      b.bag.error("icon", "an icon element needs one 'icon:' or 'slot:'", b.doc.span(node), {
        notes: ["'slot:' names a 'config: slots:' slot: the glyph follows whatever the wearer picks there",
          "'icon:' names a glyph from the built-in catalogue (run `wfb sources` for the list)",
          "or is {codepoint: \"U+XXXX\"}, any codepoint in the icon font -- for "
          + "the ~10,000 glyphs the catalogue does not name",
          "or is {for: <expression>}, choosing one at runtime from a "
          + "bound value -- see WEATHER_CONDITION_SOURCES in ts/src/catalog.ts for what it accepts"],
      });
    }
    const size = b.bakedSizeLength(node, "size", { code: "icon", label: "icon size", note: ICON_SIZE_NOTE });
    const [align, verticalAlign] = b.alignment(node);
    // Every spelling of `icon:` shares these keys.
    const placement: Placement = { size, color: b.colorExpression(node, "color"), align, vertical_align: verticalAlign, rotate: b.angle(node, "rotate") };

    if (dynamic !== null) {
      let valueFor = b.expression(dynamic, "for");
      if (valueFor !== null && (valueFor.ast === null || valueFor.ast.kind !== "ref" || valueFor.sources.length !== 1
        || !catalog.WEATHER_CONDITION_SOURCES.has(valueFor.sources[0]!))) {
        b.bag.error("icon", "icon: {for:} must be exactly one of: "
          + `${[...catalog.WEATHER_CONDITION_SOURCES].sort().join(", ")} -- not ${quoted(valueFor.shown)}`,
        b.doc.span(dynamic, "for") ?? b.doc.span(node, "icon"), {
          notes: ["arithmetic or a conditional would break the condition-to-glyph "
            + "lookup, which needs the raw Weather.CONDITION_* value"],
        });
        valueFor = null;
      }
      return IconElement.create({ ...common, icon: null, codepoint: icons.FALLBACK_CODEPOINT, value_for: valueFor, ...placement });
    }
    if (spec !== null) return buildGlyphIcon(b, node, spec, common, placement);
    if (typeof name !== "string") throw new Error("the schema requires 'icon:'");
    const codepoint = b.resolveIconName(name, b.doc.span(node, "icon")) ?? icons.FALLBACK_CODEPOINT;
    return IconElement.create({ ...common, icon: name, codepoint, ...placement });
  }

  /** `slot:` instead of `icon:`: the glyph of whatever the wearer picked for that slot. */
  private buildSlot(b: Builder, node: Node, common: Common): Element {
    const raw = str(node.get("slot"));
    const slot = resolveSlotReference(b, raw, b.doc.span(node, "slot"));
    if (node.has("icon")) {
      b.bag.error("icon", `${common.id}: 'icon:' and 'slot:' both choose the glyph -- keep one`, b.doc.span(node, "icon"), {
        notes: ["with 'slot:', the glyph is the icon of whatever the wearer picked for that slot, chosen on the watch",
          "a per-choice icon is set in the slot's own 'choices:' list: { type: <name>, icon: <name> }"],
      });
    }
    const size = b.bakedSizeLength(node, "size", { code: "icon", label: "icon size", note: ICON_SIZE_NOTE });
    const [align, verticalAlign] = b.alignment(node);
    const element = IconElement.create({
      ...common, icon: null, codepoint: icons.FALLBACK_CODEPOINT, slot: slot !== null ? slot.name : raw,
      size, color: b.colorExpression(node, "color"), align, vertical_align: verticalAlign, rotate: b.angle(node, "rotate"),
    });
    if (element.on_hold !== null && element.on_hold !== HOLD_AUTO) {
      // A fixed target would disagree with the slot the moment the wearer repoints it.
      b.bag.error("on-hold", `${element.id}: 'on_hold:' on an icon with 'slot:' only accepts 'auto', not ${quoted(element.on_hold)}`,
        b.doc.span(node, "on_hold"), {
          notes: ["'on_hold: auto' opens the glance of whatever the wearer picked for this slot, read at every hold"],
        });
      element.on_hold = null;
    }
    return element;
  }

  /** A slot icon: pulled each frame, then drawn when the pick has a glyph. */
  private lowerSlot(ctx: DrawContext, p: PlacedIcon): Op[] {
    const element = p.element;
    const face = ctx.resolved.face;
    const slot = face.config_data.get(element.slot!)!;
    const shown = ctx.shown(slot);
    if (!ctx.resolved.fonts.has(p.font_key)) return [Comment(`no choice of slot ${element.slot} has an icon`)];
    const ops: Op[] = [
      Comment("the editor is animating this slot -- its drawable draws it (drawSlot)"),
      If(IsPulsing(configDataIds(face).get(element.slot!)!), [Return()]),
      Blank(),
      Comment(`slot: ${element.slot} -- the icon of the wearer's pick`),
      SlotPull(configField(`data_${element.slot}`), ctx.complications_guarded, DATA_SAMPLE.get(shown) ?? null),
      SlotIcon(fontField(p.font_key), p.font_key, dataIconMethod(element.id), ctx.complications_guarded,
        slotSampleGlyph(slot, shown, slotSample(shown))),
    ];
    const prefix = constPrefix(p.id);
    const x = Const(`${prefix}_CX`, p.center[0]), y = Const(`${prefix}_CY`, p.center[1]);
    const glyph = Local("iconGlyph"), shownGlyph = LocalsSet(["iconGlyph", "iconFont"]);
    const draw = (font: Font, dx = 0, dy = 0): Glyph =>
      Glyph(Shifted(x, dx), Shifted(y, dy), font, glyph, p.justify, element.vertical_align, p.innerBox, p.center);
    const font = Font("iconFont", { baked: p.font_key });
    const ringOps = (paint: Paint, width: number): Op[] => {
      const baked = bakedRing(element, face, width);
      if (baked === null) return [If(shownGlyph, [SetColor(paint), ...discPerimeterOffsets(width).map(([dx, dy]) => draw(font, dx, dy))])];
      const local = bakedRingLocal(width);
      return [LoadFont(local, `_${fontField(baked)}`, { onNull: "none" }),
        IfNotNull(local, [If(shownGlyph, [SetColor(paint), draw(Font(local, { baked }))])])];
    };
    if (ctx.ring !== null) return [...ops, ...ringOps(RingColor(), ctx.ring.width)];
    if (element.outline !== null) ops.push(...ringOps(AodDimmed(element, element.outline.color), element.outline.width), Blank());
    return [...ops, If(shownGlyph, [SetColor(AodRestyled(element, "color")), draw(font)])];
  }

  override lower(ctx: DrawContext, placed: Placed): Op[] {
    const p = placed as PlacedIcon;
    const element = p.element;
    if (element.slot !== null) return this.lowerSlot(ctx, p);
    const prefix = constPrefix(p.id);
    const font = Font("font", { baked: p.font_key });
    const ops: Op[] = [LoadFont("font", `_${fontField(p.font_key)}`, { note: "the icon font resource failed to load" }), Blank()];
    let glyph: Str;
    if (element.value_for !== null) {
      ops.push(Comment(`${quoted(element.value_for.text)} -> a name (WfbWeather) -> a glyph (IconGlyphs)`));
      glyph = IconChoice(element.value_for);
    } else {
      ops.push(Comment(quoted(element.icon)));
      glyph = StrLit(element.codepoint);
    }
    const x = Const(`${prefix}_CX`, p.center[0]), y = Const(`${prefix}_CY`, p.center[1]);
    const draw = (face: Font, dx = 0, dy = 0): Glyph =>
      Glyph(Shifted(x, dx), Shifted(y, dy), face, glyph, p.justify, element.vertical_align, p.innerBox, p.center);
    const ringOps = (paint: Paint, width: number): Op[] => {
      const baked = bakedRing(element, ctx.resolved.face, width);
      if (baked === null) return [SetColor(paint), ...discPerimeterOffsets(width).map(([dx, dy]) => draw(font, dx, dy))];
      const local = bakedRingLocal(width);
      return [LoadFont(local, `_${fontField(baked)}`, { onNull: "none" }), IfNotNull(local, [SetColor(paint), draw(Font(local, { baked }))])];
    };
    if (ctx.ring !== null) return [...ops, ...ringOps(RingColor(), ctx.ring.width)];
    if (element.outline !== null) ops.push(...ringOps(AodDimmed(element, element.outline.color), element.outline.width), Blank());
    return [...ops, SetColor(AodRestyled(element, "color")), draw(font)];
  }

  override layoutConstants(prefix: string, placed: Placed): Constants {
    const p = placed as PlacedIcon;
    const isDefault = p.element.align === "center" && p.element.vertical_align === "center";
    const note = isDefault ? "" : "the anchor drawText justifies the glyph from, not its centre";
    return [[`${prefix}_CX`, p.center[0], note], [`${prefix}_CY`, p.center[1], note]];
  }

  override ringDraws(element: IconElement, face: Face): number {
    return bakedRing(element, face, 1) !== null ? 1 : super.ringDraws(element, face);
  }

  override describe(placed: Placed): string {
    const element = (placed as PlacedIcon).element;
    if (element.slot !== null) return `the icon of slot ${quoted(element.slot)}'s pick`;
    if (element.value_for !== null) return `an icon chosen at runtime from ${quoted(element.value_for.text)}`;
    return `the ${quoted(element.icon)} icon`;
  }
}

register(new IconKind());
