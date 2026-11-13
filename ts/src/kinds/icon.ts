// `type: icon`: one glyph drawn from a baked icon font, static or chosen at
// runtime from a bound value (`icon: {for:}`): its build half.
import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import { ICON_SIZE_NOTE } from "../ir/builder/glyphs.ts";
import { type Element, type Face, HOLD_AUTO, IconElement } from "../ir/model.ts";
import { configDataIds, configField, dataIconMethod, localName } from "../ir/naming.ts";
import {
  comparePoints, resolveSlotReference, slotIconFontKey, slotIconRun, slotReferenceGlyph, slotSample, slotSampleGlyph, withSubstitute,
} from "./data.ts";
import * as icons from "../icons.ts";
import { alignmentShift, justify, type Placed, PlacedIcon, type Resolver } from "../layout.ts";
import { quoted, str } from "../py.ts";
import * as vocab from "../vocab.ts";
import * as units from "../units.ts";
import { Box, roundPx as round } from "../units.ts";
import { type Common, ElementKind, IconFont, register, TextRun } from "./base.ts";
import {
  AodDimmed, AodRestyled, Blank, Comment, Const, type DrawContext, Font, Glyph, IconChoice, If, IfNotNull, IsPulsing, LoadFont, Local,
  LocalsSet, type Op, type Paint, Present, Return, RingColor, SetColor, Shifted, SlotIcon, SlotPull, type Str, StrLit, StrPick,
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

/** What `icon: {for:}` accepts: every source an icon rule follows. */
function forSources(): string[] {
  return [...icons.RULE_OF_SOURCE.keys()].sort();
}

/**
 * A dynamic icon's font tag: one font per rule and size, shared by every
 * element following it. A steps rule's tag says how it splits the reading
 * (`level_<name>` over a range, `count_<name>` at thresholds); a table's is
 * its name.
 */
function dynamicTag(rule: icons.IconRule): string {
  if (rule.kind === "table") return rule.name;
  return `${rule.range !== null ? "level" : "count"}_${rule.name}`;
}

/** The glyph a dynamic icon's font is measured and sized by. */
function dynamicReference(rule: icons.IconRule): string {
  if (rule.kind === "table") return icons.WEATHER_BAKE_REFERENCE_GLYPH;
  return icons.CATALOG.get(rule.range !== null ? rule.steps[0]! : rule.plain)!.codepoint;
}

/** What a dynamic icon's generated comment says its rule does with the reading. */
function choiceSaid(rule: icons.IconRule): string {
  if (rule.kind === "table") return `a name ('${rule.plain}' without a reading) -> a glyph`;
  if (rule.range !== null) return `a step, '${rule.plain}' without a reading`;
  if (icons.readsBoolean(rule)) return `'${rule.steps[0]}' when off, else '${rule.steps[1]}'`;
  const bands = icons.thresholdRanges(rule).map((band) => `'${band.name}' ${icons.thresholdSaid(band)}`).join(", ");
  return `${bands}, else '${rule.steps[rule.steps.length - 1]}'`;
}

/**
 * The glyph `absent: {icon:}` draws instead of the rule's while the reading is
 * absent, or `null`: none was written, or the reading can never be absent.
 */
function substituteGlyph(element: IconElement): string | null {
  if (element.absent !== "icon" || element.absent_icon === null) return null;
  if (element.slot === null && !(element.value_for?.nullable ?? false)) return null;
  return element.absent_icon.codepoint;
}

/** `absent:` on an icon: `hide`, or `{icon: <name or {codepoint:}>}` drawn instead; only an icon that follows data has a reading to lose. */
function buildAbsent(b: Builder, node: Node, element: IconElement): void {
  if (!node.has("absent")) return;
  const raw = node.get("absent");
  const span = b.doc.span(node, "absent");
  if (element.slot === null && element.value_for === null) {
    // A `for:` refused already has its error; any other icon is fixed.
    const icon = node.get("icon");
    if (!(icon instanceof Map && icon.has("for"))) {
      b.bag.error("when-absent", `${element.id}: 'absent:' needs an icon that follows data ('icon: {for:}' or 'slot:')`, span, {
        notes: ["a fixed icon has no reading, so it is never absent -- drop 'absent:', or use 'visible:' to hide it"],
      });
    }
    return;
  }
  if (raw === "hide") {
    element.absent = "hide";
  } else if (raw instanceof Map) {
    const spec = raw.get("icon");
    let name: string, codepoint: string | null;
    if (spec instanceof Map) {
      name = str(spec.get("codepoint")).toUpperCase();
      codepoint = b.resolveIconGlyph(str(spec.get("codepoint")), b.doc.span(spec, "codepoint") ?? b.doc.span(raw, "icon"));
    } else {
      name = str(spec);
      codepoint = b.resolveIconName(name, b.doc.span(raw, "icon") ?? span);
    }
    if (codepoint === null) return;
    element.absent = "icon";
    element.absent_icon = { name, codepoint };
  } else {
    throw new Error("the schema allows 'absent: hide' or {icon:} on an icon");
  }
  if (element.value_for !== null) b.checkAbsence(node, element, element.value_for, element.absent, null, null, "icon");
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
      key = icons.fontKey(element.size, dynamicTag(element.rule!), element.resolved_antialias, element.turn);
      measureCodepoint = dynamicReference(element.rule!);
    } else {
      key = icons.fontKey(element.size, element.codepoint, element.resolved_antialias, element.turn);
      measureCodepoint = element.codepoint;
    }
    // A substitute the rule's font lacks gives the font a key of its own (`textRuns`).
    if (substituteGlyph(element) !== null) key = this.textRuns(element, r.face)[0]?.font ?? key;
    const font = r.fonts.get(key);
    let [width, height] = font !== undefined ? font.measure(measureCodepoint) : [px, px];
    // A glyph chosen on the watch can be any the font holds: the box is as wide as the widest.
    if (font !== undefined && (element.slot !== null || element.isDynamic)) width = font.widestAdvance();
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
      const run = slotIconRun(element.id, face, element.slot, element.size, element.resolved_antialias, element.turn, element.span, null,
        substituteGlyph(element));
      return run !== null ? [run] : [];
    }
    let glyphKey: string, glyphs: string, reference: string, table: Map<string, string> | null = null;
    const rule = element.rule;
    if (rule !== null) {
      // The glyph follows the reading, so the font holds every one the rule can draw, its plain one included.
      table = icons.ruleGlyphTable(rule);
      glyphKey = dynamicTag(rule);
      glyphs = [...new Set(table.values())].sort(comparePoints).join("");
      reference = dynamicReference(rule);
    } else {
      glyphKey = glyphs = reference = element.codepoint;
    }
    // `absent: {icon:}` draws while the reading is absent, so the font holds it too.
    if (element.isDynamic) [glyphKey, glyphs] = withSubstitute(glyphKey, glyphs, substituteGlyph(element));
    const key = icons.fontKey(element.size, glyphKey, element.resolved_antialias, element.turn);
    return [new TextRun(element.id, key, {
      span: element.span, icon: new IconFont(element.size, glyphs, reference, element.resolved_antialias, element.turn), glyph_table: table,
      rules: rule !== null ? [rule.name] : [],
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
          "or is {for: <source>}, choosing one at runtime from a bound value: "
          + `one of ${forSources().join(", ")}`],
      });
    }
    const size = b.bakedSizeLength(node, "size", { code: "icon", label: "icon size", note: ICON_SIZE_NOTE });
    const [align, verticalAlign] = b.alignment(node);
    // Every spelling of `icon:` shares these keys.
    const placement: Placement = { size, color: b.colorExpression(node, "color"), align, vertical_align: verticalAlign, rotate: b.angle(node, "rotate") };

    if (dynamic !== null) {
      let valueFor = b.expression(dynamic, "for");
      if (valueFor !== null && (valueFor.ast === null || valueFor.ast.kind !== "ref" || valueFor.sources.length !== 1
        || !forSources().includes(valueFor.sources[0]!))) {
        b.bag.error("icon", `icon: {for:} must be exactly one of: ${forSources().join(", ")} -- not ${quoted(valueFor.shown)}`,
          b.doc.span(dynamic, "for") ?? b.doc.span(node, "icon"), {
            notes: ["the glyph lookup needs the raw reading: a weather condition's Weather.CONDITION_* value, "
              + "a 0-100 level, a count, an on/off setting or the moon's age, so arithmetic or a conditional is refused"],
          });
        valueFor = null;
      }
      const variant = valueFor !== null ? b.iconVariant(dynamic, icons.RULE_OF_SOURCE.get(valueFor.sources[0]!)!, valueFor.shown) : null;
      const element = IconElement.create({ ...common, icon: null, codepoint: icons.FALLBACK_CODEPOINT, value_for: valueFor, variant, ...placement });
      buildAbsent(b, node, element);
      return element;
    }
    let element: IconElement;
    if (spec !== null) {
      element = buildGlyphIcon(b, node, spec, common, placement) as IconElement;
    } else {
      if (typeof name !== "string") throw new Error("the schema requires 'icon:'");
      const codepoint = b.resolveIconName(name, b.doc.span(node, "icon")) ?? icons.FALLBACK_CODEPOINT;
      element = IconElement.create({ ...common, icon: name, codepoint, ...placement });
    }
    buildAbsent(b, node, element);
    return element;
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
    buildAbsent(b, node, element);
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
      SlotPull(configField(`data_${element.slot}`), ctx.complications_guarded, ctx.dataSample(shown) ?? null),
      SlotIcon(fontField(p.font_key), p.font_key, dataIconMethod(element.id), ctx.complications_guarded,
        slotSampleGlyph(slot, shown, slotSample(shown, ctx)),
        element.absent !== null ? { glyph: substituteGlyph(element), shown: vocab.absent(element) } : null),
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
      const rule = element.rule!;
      ops.push(Comment(`${quoted(element.value_for.text)} -> ${choiceSaid(rule)} (IconGlyphs)`));
      glyph = IconChoice(element.value_for, rule.name);
      const substitute = substituteGlyph(element);
      if (substitute !== null) {
        ops.push(Comment(`${vocab.absent(element)} -- drawn instead while the reading is absent`));
        glyph = StrPick(Present([localName(element.value_for.sources[0]!)], [element.value_for]), glyph, StrLit(substitute));
      }
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

  /**
   * A dynamic icon draws while the reading is absent: its rule's plain glyph,
   * or its `absent: {icon:}`. `absent: hide` guards it instead.
   */
  override drawsWhileAbsent(element: IconElement): boolean {
    return element.isDynamic && element.absent !== "hide";
  }

  override ringDraws(element: IconElement, face: Face): number {
    return bakedRing(element, face, 1) !== null ? 1 : super.ringDraws(element, face);
  }

  override describe(placed: Placed): string {
    const element = (placed as PlacedIcon).element;
    if (element.slot !== null) return `the icon of slot ${quoted(element.slot)}'s pick`;
    if (element.value_for !== null) {
      const rule = element.rule!, source = quoted(element.value_for.text);
      if (rule.kind === "table") return `an icon chosen at runtime from ${source}`;
      if (rule.cyclic) return `an icon stepping round with ${source}`;
      if (rule.range !== null) return `an icon filling with ${source}`;
      return icons.readsBoolean(rule) ? `an icon switching with ${source}` : `an icon emptying when ${source} is 0`;
    }
    return `the ${quoted(element.icon)} icon`;
  }
}

register(new IconKind());
