// Fonts, icons and the text decorations shared by `text` elements and
// pattern text parts: `outline:`, `curve:`, `unsupported:`, icon names and
// glyphs, and the per-`shape:`/`style:` foreign-key check..
import type { Span } from "../../diagnostics.ts";
import * as icons from "../../icons.ts";
import { isNumber, num, repr, str } from "../../py.ts";
import { Curve, type Element, MAX_OUTLINE_WIDTH, Outline } from "../model.ts";
import { AbsenceChecks } from "./absence.ts";
import type { Node } from "./state.ts";

/** "No `icon:` override declared" and "declared, invalid, already reported"; `null` is an explicit `icon: none`. */
export const NO_ICON_OVERRIDE = Symbol("no override");
export const ICON_OVERRIDE_ERROR = Symbol("error");

/** Which key each `curve:` `style:` reads: only `radial` has a circle for `radius:`/`direction:` to describe. */
export const CURVE_STYLE_KEYS: ReadonlyMap<string, ReadonlySet<string>> = new Map([
  ["angled", new Set<string>()],
  ["radial", new Set(["radius", "direction"])],
]);

/** Every key of every row of a key table. */
export function allKeys(table: ReadonlyMap<string, ReadonlySet<string>>): Set<string> {
  return new Set([...table.values()].flatMap((keys) => [...keys]));
}

const ALL_CURVE_STYLE_KEYS = allKeys(CURVE_STYLE_KEYS);

/** The note on an icon size given in a unit other than `px`/`%r`. */
export const ICON_SIZE_NOTE = "an icon's font is baked once, before layout runs, so its size "
  + "cannot depend on a parent box (%) or an element's own font (pt)";

export interface ForeignKeyOptions {
  code: string;
  disc: string;
  prefix?: string;
  qualifier?: string;
  suffix?: string;
  emptyLabel?: string;
  extraNotes?: (key: string) => string[];
}

/** Text, font and icon helpers shared across element kinds. */
export class GlyphHelpers extends AbsenceChecks {
  /** Reject a key from another row of `table` that `chosen`'s own row does not read. */
  checkForeignKeys(node: Node, chosen: string, table: ReadonlyMap<string, ReadonlySet<string>>, all: ReadonlySet<string>,
    { code, disc, prefix = "", qualifier = "", suffix = "", emptyLabel = "(no geometry keys)", extraNotes }: ForeignKeyOptions): boolean {
    let ok = true;
    const own = table.get(chosen)!;
    for (const key of [...all].filter((k) => !own.has(k)).sort()) {
      if (!node.has(key)) continue;
      const owners = [...table].filter(([, keys]) => keys.has(key)).map(([s]) => s).sort();
      const notes = [
        `'${disc}: ${chosen}' reads: ` + ([...own].sort().join(", ") || emptyLabel),
        `${repr(key)} belongs to ` + owners.map((s) => `'${disc}: ${s}'`).join(" and "),
      ];
      if (extraNotes !== undefined) notes.push(...extraNotes(key));
      this.bag.error(code, `${prefix}${repr(key)} is not used by ${qualifier}'${disc}: ${chosen}'${suffix}`,
        this.doc.span(node, key) ?? this.doc.span(node), { notes });
      ok = false;
    }
    return ok;
  }

  /** `outline:` on an element, or (with no `element`) on a pattern's text or hand part. */
  buildOutline(node: Node, key: string, label: string, element: Element | null = null): Outline | null {
    const raw = node.get(key);
    if (raw === undefined || raw === null || raw === "none") return null;
    const span = this.doc.span(node, key);
    let color, colorSpan, width: unknown, widthSpan;
    if (raw instanceof Map) {
      color = this.colorExpression(raw, "color");
      colorSpan = this.doc.span(raw, "color") ?? span;
      width = raw.has("width") ? raw.get("width") : 1;
      widthSpan = this.doc.span(raw, "width") ?? span;
    } else {
      color = this.colorExpression(node, key);
      colorSpan = span;
      width = 1;
      widthSpan = span;
    }
    if (color === null) return null;
    const w = isNumber(width) ? num(width) : Number(width);
    if (w > MAX_OUTLINE_WIDTH) {
      this.bag.error("outline", `${label}: 'outline: width: ${str(width)}' is more than ${MAX_OUTLINE_WIDTH}px`, widthSpan, {
        notes: [
          `a ring is 1 to ${MAX_OUTLINE_WIDTH}px: a wider one was never `
          + "measured to still read as an outline rather than a second, "
          + "blockier glyph, and each pixel more is a stamp of more draws",
          "see docs/guide/outlines.md",
        ],
      });
      return null;
    }
    if (element !== null) this.checkOtherAbsence(node, element, "outline.color", color, colorSpan);
    return Outline.create({ color, width: w });
  }

  private checkCurveKeys(node: Node, style: string): void {
    if (!CURVE_STYLE_KEYS.has(style)) return; // the schema has already rejected an unknown style
    this.checkForeignKeys(node, style, CURVE_STYLE_KEYS, ALL_CURVE_STYLE_KEYS, {
      code: "text-curve", disc: "style", emptyLabel: "(nothing)",
      extraNotes: () => (style === "angled"
        ? ["an angled line has no circle for it to describe -- 'radius:'/'direction:' only mean something with 'style: radial'"]
        : []),
    });
  }

  /** Whether a resolved `[font, isCustom]` names a `face:` (vector) font. */
  isVectorFont(font: string, isCustom: boolean): boolean {
    return isCustom && this.fonts.get(font)!.isVector;
  }

  /** What kind of (non-vector) font a `text` element's `font:` resolved to. */
  fontKindNote(font: string, isCustom: boolean): string {
    if (isCustom) return `'font: font.${font}' is a baked bitmap font, declared with 'source:'`;
    return `'font: ${font}' is one of the platform's fixed system fonts`;
  }

  /** `curve:` on a `text` element or a pattern's text part. */
  buildCurve(node: Node, label: string, { verticalAlign, fontOk, fontIsVector, fontNote = null }:
    { verticalAlign: string; fontOk: boolean; fontIsVector: boolean; fontNote?: string | null }): Curve | null {
    const raw = node.get("curve") as Node;
    const span = this.doc.span(node, "curve");
    const style = raw.get("style") as string;
    this.checkCurveKeys(raw, style);
    const angle = this.angle(raw, "angle");
    if (angle === null) return null;
    const radius = style === "radial" ? this.length(raw, "radius") : null;
    const direction = style === "radial" ? str(raw.get("direction") ?? "clockwise") : null;
    if (fontOk && !fontIsVector) {
      this.bag.error("text-curve", `${label}: 'curve:' needs a 'face:' (vector) font`, span, {
        notes: [
          "\"These APIs only support scalable fonts and do not support "
          + "custom fonts loaded as resources\" ($CIQ_SDK/doc/docs/"
          + "Core_Topics/Graphics.html §Scalable Fonts)",
          ...(fontNote !== null ? [fontNote] : []),
          "declare this font with 'face:' instead of 'source:', or point "
          + "'font:' at one that already does",
        ],
      });
    }
    if (verticalAlign === "bottom" && style === "angled") {
      this.bag.error("text-curve", `${label}: a bottom alignment ('align: bottom', 'bottom_left', ...) is `
        + "not accepted under 'curve: {style: angled}'", this.doc.span(node, "align") ?? span, {
        notes: [
          "an upright text's 'bottom' is implemented by subtracting the "
          + "font's own height from the anchor in screen space -- once the "
          + "baseline is rotated that subtraction no longer points along "
          + "the text's own vertical axis, so the ink would land somewhere "
          + "this compiler cannot predict",
          "align it to the top or the centre instead ('curve: {style: "
          + "radial}' accepts all three)",
        ],
      });
    }
    return Curve.create({ style, angle, radius, direction });
  }

  /** `unsupported:` on a `text` element or a pattern text part: meaningful only for a `face:` font. */
  checkUnsupported(node: Node, label: string, fontIsVector: boolean, fontNote: string | null = null): void {
    if (fontIsVector) return;
    this.bag.error("text-curve", `${label}: 'unsupported:' is not accepted here`, this.doc.span(node, "unsupported"), {
      notes: [
        "'unsupported:' governs a device-resident 'face:' font "
        + "failing to publish a face on some target device -- nothing "
        + "about a baked or system font can ever be unsupported",
        ...(fontNote !== null ? [fontNote] : []),
        "drop 'unsupported:', or point 'font:' at a 'face:' font",
      ],
    });
  }

  /** A catalogue name to its codepoint, or `null` plus a reported error. */
  resolveIconName(name: string, span: Span | null): string | null {
    const codepoint = icons.resolveCodepoint(name);
    if (codepoint === null) {
      this.bag.error("icon", `unknown icon ${repr(name)}`, span, {
        notes: [
          "the catalogue has: " + icons.names().join(", "),
          "for a glyph the catalogue does not name, write its codepoint, "
          + "'icon: \"U+XXXX\"' -- see ts/assets/icons/README.md",
        ],
      });
    }
    return codepoint;
  }

  /** `"U+F0BC"` to the character, or `null` plus a reported error. */
  resolveIconGlyph(raw: string, span: Span | null): string | null {
    const character = icons.parseCodepoint(raw);
    if (character === null) {
      this.bag.error("icon", `an icon codepoint is written 'U+XXXX', not ${repr(raw)}`, span, {
        notes: ["e.g. icon: \"U+F0BC\" -- 1 to 6 hex digits, case-insensitive",
          "or name an icon from the built-in catalogue"],
      });
      return null;
    }
    if (!icons.fontHas(character)) {
      this.bag.error("icon", `the icon font has no glyph at ${raw.toUpperCase()}`, span, {
        notes: [
          "checked against the icon font's own character map, the same "
          + "way a custom text font's coverage is checked",
          "https://www.nerdfonts.com/cheat-sheet lists the codepoints this "
          + "font actually carries",
        ],
      });
      return null;
    }
    const named = icons.nameForCodepoint(character);
    if (named !== null) {
      this.bag.note("icon", `glyph ${raw.toUpperCase()} is in the catalogue as ${repr(named)} -- `
        + `'icon: ${named}' says the same thing and survives a font update`, span);
    }
    return character;
  }

  /** A `config: slots:` choice's own `icon:`, if it declares one. */
  resolveChoiceIconOverride(item: Node, what: string, fallbackSpan: Span | null):
    icons.SlotIcon | null | typeof NO_ICON_OVERRIDE | typeof ICON_OVERRIDE_ERROR {
    if (!item.has("icon")) return NO_ICON_OVERRIDE;
    const rawIcon = item.get("icon");
    const span = this.doc.span(item, "icon") ?? fallbackSpan;
    if (rawIcon === "none") return null;
    if (typeof rawIcon !== "string") {
      this.bag.error("config", `${what}.icon: expected a string, got ${repr(rawIcon)}`, span);
      return ICON_OVERRIDE_ERROR;
    }
    if (!icons.isCodepointSpelling(rawIcon)) {
      const codepoint = this.resolveIconName(rawIcon, span);
      if (codepoint === null) return ICON_OVERRIDE_ERROR;
      return new icons.SlotIcon(rawIcon, codepoint);
    }
    const character = this.resolveIconGlyph(rawIcon, span);
    if (character === null) return ICON_OVERRIDE_ERROR;
    return new icons.SlotIcon(icons.codepointKey(character), character);
  }
}
