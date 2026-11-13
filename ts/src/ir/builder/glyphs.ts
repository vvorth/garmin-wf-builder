// Fonts, icons and the text decorations shared by `text` elements and
// pattern text parts: `outline:`, `curve:`, `unsupported:`, icon names and
// glyphs, and the per-`shape:`/`style:` foreign-key check..
import { didYouMean, getCloseMatches, type Span } from "../../diagnostics.ts";
import * as icons from "../../icons.ts";
import { isNumber, num, quoted, str } from "../../py.ts";
import { Curve, type Element, MAX_OUTLINE_WIDTH, Outline } from "../model.ts";
import { AbsenceChecks } from "./absence.ts";
import { andPaths, type Node } from "./state.ts";
import type { DataKey } from "../../edit/yaml.ts";

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
        `${quoted(key)} belongs to ` + owners.map((s) => `'${disc}: ${s}'`).join(" and "),
      ];
      if (extraNotes !== undefined) notes.push(...extraNotes(key));
      this.bag.error(code, `${prefix}${quoted(key)} is not used by ${qualifier}'${disc}: ${chosen}'${suffix}`,
        this.doc.span(node, key) ?? this.doc.span(node), { notes });
      ok = false;
    }
    return ok;
  }

  /** `outline:` on an element, or (with no `element`) on a pattern's text or hand part. */
  buildOutline(node: Node, key: string, label: string, element: Element | null = null): Outline | null {
    const raw = node.get(key);
    if (raw === undefined || raw === null || raw === "none") return null;
    if (!(raw instanceof Map)) throw new Error(`${label}: the schema admits only {color, width} for 'outline:'`);
    const span = this.doc.span(node, key);
    const color = this.colorExpression(raw, "color");
    const colorSpan = this.doc.span(raw, "color") ?? span;
    const width: unknown = raw.has("width") ? raw.get("width") : 1;
    const widthSpan = this.doc.span(raw, "width") ?? span;
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

  /** A catalogue name to its codepoint, or `null` plus a reported error; `suggest` adds the nearest names. */
  resolveIconName(name: string, span: Span | null, suggest = false): string | null {
    const codepoint = icons.resolveCodepoint(name);
    if (codepoint === null) {
      this.bag.error("icon", `unknown icon ${quoted(name)}`, span, {
        notes: [
          ...(suggest ? didYouMean(getCloseMatches(name, icons.names(), 3, 0.5)) : []),
          "the catalogue has: " + icons.names().join(", "),
          "for a glyph the catalogue does not name, write its codepoint, "
          + "'icon: {codepoint: \"U+XXXX\"}' -- see ts/assets/icons/README.md",
        ],
      });
    }
    return codepoint;
  }

  /** `{codepoint: "U+F0BC"}`'s string to the character, or `null` plus a reported error. */
  resolveIconGlyph(raw: string, span: Span | null): string | null {
    const character = icons.parseCodepoint(raw);
    if (character === null) {
      this.bag.error("icon", `an icon codepoint is written 'U+XXXX', not ${quoted(raw)}`, span, {
        notes: ["e.g. icon: {codepoint: \"U+F0BC\"} -- 1 to 6 hex digits, case-insensitive",
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
      this.bag.note("icon", `glyph ${raw.toUpperCase()} is in the catalogue as ${quoted(named)} -- `
        + `'icon: ${named}' says the same thing and survives a font update`, span);
    }
    return character;
  }

  /**
   * The `variant:` written in `container` (an `icon: {for:}` or a slot choice)
   * for an icon following `rule` (none for an icon following no reading),
   * `what` naming the source or type: `null` when none is written, and after
   * its error when the icon has no variants. The schema's enum is every
   * family's variants (`data.test.ts`), so a written variant is the rule's own.
   */
  iconVariant(container: Node, rule: icons.IconRule | undefined, what: string): string | null {
    const written = container.get("variant");
    if (written === undefined || written === null) return null;
    const variant = String(written), span = this.doc.span(container, "variant");
    if (rule === undefined || rule.variants.length === 0) {
      this.bag.error("icon", `variant: ${quoted(variant)} -- ${what}'s icon has no variants`, span, {
        notes: [`only ${icons.variantFamilies().join(", ")} icons come in variants`],
      });
      return null;
    }
    return variant;
  }

  /**
   * One glyph of an `icons:` set, checked as an element's own `icon:` is: a
   * catalogue name as written, or a codepoint in its canonical `U+XXXX`
   * spelling; `null` after its error.
   */
  private iconSetGlyph(set: Node, key: DataKey): string | null {
    const raw = set.get(key);
    const span = this.doc.span(set, key);
    if (raw instanceof Map) {
      const character = this.resolveIconGlyph(str(raw.get("codepoint")), this.doc.span(raw, "codepoint") ?? span);
      return character !== null ? icons.codepointKey(character) : null;
    }
    const name = str(raw);
    return this.resolveIconName(name, span, true) !== null ? name : null;
  }

  /**
   * `icons:` written in `container` (an `icon: {for:}`) over `family`, the
   * rule `what` (the source as written) follows: the author's own glyph per
   * state, keyed as the reading is (band starts for a level or a count,
   * `off`/`on` for an on/off reading, built-in glyph names for an overlay).
   * `null` when none is written, and after an error: the first wrong key
   * stops the key checks, each wrong glyph has its own error.
   */
  iconSet(container: Node, family: icons.IconRule, what: string): icons.CustomSet | null {
    if (!container.has("icons")) return null;
    const set = container.get("icons");
    const setSpan = this.doc.span(container, "icons");
    if (!(set instanceof Map)) throw new Error("the schema requires 'icons:' to be a mapping");
    if (container.has("variant")) {
      this.bag.error("icon", `'icons:' and 'variant:' both choose ${what}'s glyphs -- 'variant:' picks a built-in set; `
        + "'icons:' is your own complete set, keep one", setSpan);
      return null;
    }
    const keys = [...set.keys()];
    const builtIn = icons.stateKeys(family).map((k) => String(k)).join(", ");
    const keySpan = (key: DataKey): Span | null => this.doc.span(set, key, "key") ?? setSpan;
    const glyphs = new Map<DataKey, string>();
    const glyphsOk = (): boolean => {
      let ok = true;
      for (const key of keys) {
        const glyph = this.iconSetGlyph(set, key);
        if (glyph === null) ok = false;
        else glyphs.set(key, glyph);
      }
      return ok;
    };

    if (icons.readsBoolean(family)) {
      for (const key of keys) {
        if (key === "off" || key === "on") continue;
        this.bag.error("icon", `icons: key ${quoted(key)} -- ${what} is on or off, so its keys are 'off' and 'on'`, keySpan(key), {
          notes: [`e.g. icons: {off: ${family.steps[0]}, on: ${family.steps[1]}}`],
        });
        return null;
      }
      const missing = ["off", "on"].filter((k) => !set.has(k));
      if (missing.length > 0) {
        this.bag.error("icon", `icons: needs both 'off' and 'on' for ${what} -- ${andPaths(missing)} ${missing.length === 1 ? "is" : "are"} missing`,
          setSpan, { notes: [`e.g. icons: {off: ${family.steps[0]}, on: ${family.steps[1]}}`] });
        return null;
      }
      if (!glyphsOk()) return null;
      return { kind: "onoff", off: glyphs.get("off")!, on: glyphs.get("on")! };
    }

    if (family.kind === "table" || family.cyclic) {
      const names = icons.ruleNames(family);
      for (const key of keys) {
        if (typeof key === "string" && names.includes(key)) continue;
        this.bag.error("icon", `icons: key ${quoted(key)} is not a glyph ${what}'s icon draws -- its keys are the names of its built-in glyphs`,
          keySpan(key), {
            notes: [...didYouMean(getCloseMatches(String(key), names, 3, 0.5)), `its glyphs: ${builtIn}`,
              "each key names a built-in glyph to replace; the glyphs not named keep their own"],
          });
        return null;
      }
      if (keys.length === 0) {
        this.bag.error("icon", `icons: is empty -- name at least one of ${what}'s built-in glyphs to replace`, setSpan, {
          notes: [`its glyphs: ${builtIn}`],
        });
        return null;
      }
      if (!glyphsOk()) return null;
      return { kind: "overlay", replace: new Map(keys.map((key) => [key as string, glyphs.get(key)!])) };
    }

    // An ordered number: a level over `range`, or a count from 0.
    const count = family.range === null;
    const [bottom, top] = family.range ?? [0, null];
    const said = count ? `${what} is a count, keyed by whole numbers from ${bottom}` : `${what} is a level, keyed by numbers from ${bottom} to ${top}`;
    const example = `e.g. its built-in set starts its glyphs at ${builtIn}`;
    for (const key of keys) {
      if (typeof key === "number") {
        let problem: string | null = null;
        if (key < bottom) problem = `is below ${bottom}, where the reading starts`;
        else if (top !== null && key > top) problem = `is above ${top}, the top of the reading`;
        else if (count && !Number.isInteger(key)) problem = "is not a whole number";
        if (problem === null) continue;
        this.bag.error("icon", `icons: key ${quoted(key)} ${problem} -- ${said}`, keySpan(key), {
          notes: ["each key is the reading where its glyph starts", example],
        });
        return null;
      }
      const asNumber = typeof key === "string" && key.trim() !== "" ? Number(key) : NaN;
      if (Number.isFinite(asNumber)) {
        this.bag.error("icon", `icons: key ${quoted(key)} is quoted -- write it unquoted (${key}:), as ${what}'s keys are numbers`, keySpan(key), {
          notes: ["each key is the reading where its glyph starts", example],
        });
        return null;
      }
      this.bag.error("icon", `icons: key ${quoted(key)} is not a reading -- ${said}`, keySpan(key), {
        notes: ["each key is the reading where its glyph starts", example,
          ...(key === "off" || key === "on" ? ["'off' and 'on' key an on/off reading: device.do_not_disturb, device.phone_connected"] : [])],
      });
      return null;
    }
    const numbers = keys as number[];
    if (numbers.length < 2) {
      this.bag.error("icon", `icons: has ${numbers.length === 0 ? "no keys" : "one key"} -- a set over ${what} needs at least two, `
        + "one where each glyph starts", setSpan, {
        notes: [example, "a single glyph that never changes is 'icon: <name>'"],
      });
      return null;
    }
    const lowest = Math.min(...numbers);
    if (lowest !== bottom) {
      this.bag.error("icon", `icons: needs a key at ${bottom}, where ${what}'s reading starts -- the lowest written is ${quoted(lowest)}`,
        setSpan, { notes: ["each key is the reading where its glyph starts, so the first glyph needs one at the bottom", example] });
      return null;
    }
    if (!glyphsOk()) return null;
    return { kind: "numeric", entries: numbers.map((key) => [key, glyphs.get(key)!] as const) };
  }

  /** A `config: slots:` choice's own `icon:`, if it declares one. */
  resolveChoiceIconOverride(item: Node, what: string, fallbackSpan: Span | null):
    icons.SlotIcon | null | typeof NO_ICON_OVERRIDE | typeof ICON_OVERRIDE_ERROR {
    if (!item.has("icon")) return NO_ICON_OVERRIDE;
    const rawIcon = item.get("icon");
    const span = this.doc.span(item, "icon") ?? fallbackSpan;
    if (rawIcon === "none") return null;
    if (rawIcon instanceof Map) {
      // `{codepoint: "U+XXXX"}`: a glyph the catalogue does not name.
      const character = this.resolveIconGlyph(str(rawIcon.get("codepoint")), this.doc.span(rawIcon, "codepoint") ?? span);
      if (character === null) return ICON_OVERRIDE_ERROR;
      return new icons.SlotIcon(icons.codepointKey(character), character);
    }
    if (typeof rawIcon !== "string") {
      this.bag.error("config", `${what}.icon: expected a catalogue name, 'none' or {codepoint: "U+XXXX"}, got ${quoted(rawIcon)}`, span);
      return ICON_OVERRIDE_ERROR;
    }
    const codepoint = this.resolveIconName(rawIcon, span);
    if (codepoint === null) return ICON_OVERRIDE_ERROR;
    return new icons.SlotIcon(rawIcon, codepoint);
  }
}
