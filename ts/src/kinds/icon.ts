// `type: icon`: one glyph drawn from a baked icon font, static or chosen at
// runtime from a bound value (`icon: {for:}`): its build half.
import * as catalog from "../catalog.ts";
import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import { ICON_SIZE_NOTE } from "../ir/builder/glyphs.ts";
import { type Element, type Face, IconElement } from "../ir/model.ts";
import * as icons from "../icons.ts";
import { alignmentShift, justify, type Placed, PlacedIcon, type Resolver } from "../layout.ts";
import { quoted, str } from "../py.ts";
import * as units from "../units.ts";
import { Box, roundPx as round } from "../units.ts";
import { type Common, ElementKind, IconFont, register, TextRun } from "./base.ts";
import {
  AodDimmed, AodRestyled, Blank, Comment, Const, type DrawContext, Font, Glyph, IconChoice, IfNotNull, LoadFont, type Op,
  type Paint, RingColor, SetColor, Shifted, type Str, StrLit,
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
    let glyphKey: string, measureCodepoint: string;
    if (element.isDynamic) {
      // The real glyph is chosen on the device; measure the one `bakeSize` used.
      glyphKey = icons.DYNAMIC_WEATHER_TAG;
      measureCodepoint = icons.WEATHER_BAKE_REFERENCE_GLYPH;
    } else {
      glyphKey = measureCodepoint = element.codepoint;
    }
    const key = icons.fontKey(element.size, glyphKey, element.resolved_antialias, element.turn);
    const font = r.fonts.get(key);
    const [width, height] = font !== undefined ? font.measure(measureCodepoint) : [px, px];
    // The lint box only: the runtime `drawText` anchor stays put; alignment is a device-side justify.
    const [dx, dy] = alignmentShift(width, height, element.align, element.vertical_align);
    let box = new Box(cx + dx - width / 2, cy + dy - height / 2, width, height);
    const cell = element.turn !== 0 ? box.rounded() : null;
    const ink = element.turn !== 0 && font !== undefined ? font.glyphs.get(measureCodepoint) : undefined;
    if (ink !== undefined && ink.width > 0) {
      // A turned glyph's ink can leave its cell, so the box covers both.
      const x0 = Math.min(box.x, box.x + ink.xoffset), y0 = Math.min(box.y, box.y + ink.yoffset);
      const x1 = Math.max(box.x + width, box.x + ink.xoffset + ink.width), y1 = Math.max(box.y + height, box.y + ink.yoffset + ink.height);
      box = new Box(x0, y0, x1 - x0, y1 - y0);
    }
    return PlacedIcon.create({
      element, box: box.rounded(), center: [round(cx), round(cy)], depth, size: px, font_key: key, codepoint: measureCodepoint,
      anchor_point: [round(cx), round(cy)], justify: justify(element), cell,
    });
  }

  override textRuns(element: IconElement): TextRun[] {
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
    if (name === undefined || name === null) {
      b.bag.error("icon", "an icon element needs one 'icon:'", b.doc.span(node), {
        notes: ["'icon:' names a glyph from the built-in catalogue (run `wfb sources` for the list)",
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

  override lower(ctx: DrawContext, placed: Placed): Op[] {
    const p = placed as PlacedIcon;
    const element = p.element;
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
      Glyph(Shifted(x, dx), Shifted(y, dy), face, glyph, p.justify, element.vertical_align, p.cell ?? p.innerBox, p.center);
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
    if (element.value_for !== null) return `an icon chosen at runtime from ${quoted(element.value_for.text)}`;
    return `the ${quoted(element.icon)} icon`;
  }
}

register(new IconKind());
