// Shared small helpers and types for the Monkey C generation.
import type { Element, Expression, Face } from "../../ir/model.ts";
import { aodColorChoice, DataElement, slotOf } from "../../ir/model.ts";
import { configDataIds, elementConstPrefix } from "../../ir/naming.ts";
import * as kinds from "../../kinds/index.ts";
import { type Placed, PlacedText, type ResolvedFace } from "../../layout.ts";
import { stringLiteral } from "../../mcsource.ts";
import { VERSION } from "../../version.ts";
import type { PyNum } from "../../draw/program.ts";
import { isFloat, val } from "../../draw/barrel.ts";
import { Color } from "../../palette.ts";
import { floatRepr } from "../../py.ts";

export { type Guards, NO_GUARDS } from "../../availability.ts";

/** A layout constant whose value is not a plain number: a polygon's point array. */
export class McLiteral {
  readonly type: string;
  readonly code: string;

  constructor(type: string, code: string) {
    this.type = type;
    this.code = code;
  }
}

export const constPrefix = elementConstPrefix;

/** The view field a `fonts:` entry is loaded into, less its leading underscore. */
export function fontField(name: string): string {
  const parts = name.replaceAll("-", "_").split("_").filter((p) => p);
  return "font" + parts.map((p) => p.slice(0, 1).toUpperCase() + p.slice(1)).join("");
}

/** The view field a baked font used only by an `aod: {font: ...}` override is loaded into. */
export function aodFontField(name: string): string {
  return `${fontField(name)}Aod`;
}

/** A colour expression's Monkey C, or `Graphics.COLOR_WHITE` when there is none. */
export function mcColor(expression: Expression | null): string {
  return expression === null ? "Graphics.COLOR_WHITE" : expression.code;
}

/** `aod: {dim: ...}` as an integer ratio, or `null` for no dimming. */
export type AodDim = [number, number] | null;

/** A colour with no `aod:` override, dimmed: a pre-dimmed literal for a constant, else `WfbColor.dim`. */
function dimColorCode(expression: Expression | null, awakeCode: string, dim: [number, number]): string {
  const [num, den] = dim;
  if (expression === null || expression.isConstant) {
    const value = expression !== null ? expression.constant : 0xffffff;
    return Color.parse(value).dim(num, den).asMonkeyc();
  }
  return `WfbColor.dim(${awakeCode}, ${num}, ${den})`;
}

/**
 * How this build restyles a draw call for the AMOLED always-on frame: every
 * override becomes an inline `_aod ? <aod> : <awake>` ternary. With `on`
 * false every method hands back the awake code unchanged.
 */
export class AodStyle {
  readonly on: boolean;
  readonly dim: AodDim;

  constructor(on = false, dim: AodDim = null) {
    this.on = on;
    this.dim = dim;
  }

  /** `(_aod ? <override> : <awake>)`, or `awakeCode` alone with no override. */
  value(override: string | null, awakeCode: string): string {
    if (!this.on || override === null) return awakeCode;
    return `(_aod ? ${override} : ${awakeCode})`;
  }

  /** `Layout.<P>_<suffix>`, ternary against `Layout.<P>_AOD_<suffix>` when overridden. */
  layout(prefix: string, suffix: string, hasOverride: boolean): string {
    return this.value(hasOverride ? `Layout.${prefix}_AOD_${suffix}` : null, `Layout.${prefix}_${suffix}`);
  }

  /** One colour argument of an element shown in AOD: its override, else dimmed, else unchanged. */
  color(element: Element, key: "color" | "track_color" | "icon_color", awakeCode: string | null = null): string {
    const expression = ((element as unknown as Record<string, unknown>)[key] ?? null) as Expression | null;
    const awake = awakeCode ?? mcColor(expression);
    if (!this.on || element.aod === null) return awake;
    const [choice, override] = aodColorChoice(element.aod, key, this.dim !== null);
    return this.render(choice, override, expression, awake);
  }

  /** `color`'s rule for one `hands`/`pattern` part. */
  partColor(element: Element, colorExpr: Expression | null): string {
    const awake = mcColor(colorExpr);
    if (!this.on || element.aod === null) return awake;
    const [choice, override] = aodColorChoice(element.aod, "color", this.dim !== null);
    return this.render(choice, override, colorExpr, awake);
  }

  /** `expression` dimmed by `dim` in the AOD frame, else unchanged. */
  dimmed(element: Element, expression: Expression | null): string {
    const awake = mcColor(expression);
    if (!this.on || element.aod === null) return awake;
    return this.render(this.dim !== null ? "dim" : "awake", null, expression, awake);
  }

  private render(choice: string, override: Expression | null, expression: Expression | null, awakeCode: string): string {
    if (choice === "override") return this.value(override!.code, awakeCode);
    if (choice === "dim" && this.dim !== null) return this.value(dimColorCode(expression, awakeCode, this.dim), awakeCode);
    return awakeCode;
  }
}

/** No AOD code at all. */
export const NO_AOD = new AodStyle();

/** One `outline:` ring for a kind's draw program to paint instead of its interior. */
export class RingPass {
  readonly color: string;
  readonly width: number;

  constructor(color: string, width = 1) {
    this.color = color;
    this.width = width;
  }

  get widthCode(): string {
    return String(this.width);
  }
}

/** `expr` grown by `times * amount`, folded to one literal when `amount` is one. */
export function plus(expr: string, amount: string, times = 1): string {
  if (/^\d+$/.test(amount.replace(/^-+/, ""))) {
    const value = times * Number(amount);
    return value >= 0 ? `${expr} + ${value}` : `${expr} - ${-value}`;
  }
  const sign = times > 0 ? "+" : "-";
  return Math.abs(times) === 1 ? `${expr} ${sign} ${amount}` : `${expr} ${sign} ${Math.abs(times)} * ${amount}`;
}

/** A bare `Float` literal: Python's `repr`, with a decimal point. */
export function mcFloat(value: number): string {
  const text = floatRepr(value);
  return text.includes(".") || text.includes("e") ? text : `${text}.0`;
}

/** The `y` a glyph draw hands `dc.drawText`: `bottom` subtracts the font's own height. */
export function glyphYExpr(yExpr: string, verticalAlign: string, fontExpr: string): string {
  if (verticalAlign !== "bottom") return yExpr;
  return `${yExpr} - dc.getFontHeight(${fontExpr})`;
}

/** `noun` with `a` or `an` before it. */
export function article(noun: string): string {
  return `${"aeiou".includes(noun.slice(0, 1).toLowerCase()) && noun.length > 0 ? "an" : "a"} ${noun}`;
}

/** `expr` moved `d` pixels, as Monkey C. */
export function shifted(expr: string, d: number): string {
  if (d === 0) return expr;
  return `${expr} ${d > 0 ? "+" : "-"} ${Math.abs(d)}`;
}

/** `a`, `a and b`, `a, b and c`, for a generated comment. */
export function andList(items: Iterable<string>): string {
  const list = [...items];
  if (list.length <= 1) return list.join("");
  return list.slice(0, -1).join(", ") + " and " + list[list.length - 1];
}

/** One generated file, and where it belongs in the project. */
export interface SourceFile {
  path: string;
  text: string;
}

/** The design's path as a generated header names it: relative when it is, else the bare file name. */
export function sourceLabel(path: string): string {
  if (path.startsWith("/") || path.startsWith("..")) return path.slice(path.lastIndexOf("/") + 1);
  return path.replace(/^\.\//, "");
}

export function header(face: Face, extra = ""): string {
  const lines = [
    `Generated by garmin-wf-builder ${VERSION} -- do not edit.`,
    `Source:    ${sourceLabel(face.source_path)}`,
    `Face:      ${face.name} (format ${face.format})`,
  ];
  if (extra) lines.push(extra);
  lines.push("Regenerate with `wfb build`.  Edits here are lost on the next build;");
  lines.push("hand-written Monkey C belongs in a `raw` element instead (ADR 0007).");
  return lines.join("\n");
}

/** Elements a hold does something with, in draw order. */
export function holdTargets(face: Face): Element[] {
  return face.walk().filter((e) => e.on_hold !== null);
}

/** Every `data` element, in draw order. */
export function dataElements(face: Face): DataElement[] {
  return face.walk().filter((e): e is DataElement => e instanceof DataElement);
}

/** A delegate is needed for a hold target or for `config:`'s re-read. */
export function needsDelegate(face: Face): boolean {
  return holdTargets(face).length > 0 || face.hasConfig;
}

/** One declared slot the native editor can select, with every element that draws it. */
export class EditorSlot {
  readonly name: string;
  readonly unique: number;
  readonly elements: Element[];

  constructor(name: string, unique: number, elements: Element[]) {
    this.name = name;
    this.unique = unique;
    this.elements = elements;
  }

  get constPrefix(): string {
    return `CONFIG_DATA_${this.name.toUpperCase()}`;
  }

  get drawMethod(): string {
    return "drawSlot" + this.name.split("_").map((part) => part.slice(0, 1).toUpperCase() + part.slice(1).toLowerCase()).join("");
  }
}

/** Every slot some element draws, each with all its elements, in document order. */
export function editorSlots(face: Face): EditorSlot[] {
  const ids = configDataIds(face);
  const groups = new Map<string, Element[]>();
  for (const element of face.walk()) {
    const name = slotOf(element);
    if (name !== null && ids.has(name)) {
      if (!groups.has(name)) groups.set(name, []);
      groups.get(name)!.push(element);
    }
  }
  return [...groups].map(([name, elements]) => new EditorSlot(name, ids.get(name)!, elements));
}

/** The view's public accessor for its layout field. */
export const CONFIG_LAYOUT_METHOD = "configLayout";

/** Every bitmap font resource this view loads in `onLayout`, in first-appearance draw order, each ring font after its base. */
export function loadedFonts(resolved: ResolvedFace): string[] {
  const face = resolved.face;
  const loaded = [...new Set(kinds.placedTextRuns(resolved.items, face).filter(([, run]) => !run.aod_only && !run.isVector(face)).map(([, run]) => run.font))];
  const after = new Map<string, number>();
  for (const [ring, [base]] of kinds.ringFonts(face)) {
    if (!loaded.includes(base)) continue;
    after.set(base, (after.get(base) ?? 0) + 1);
    loaded.splice(loaded.indexOf(base) + after.get(base)!, 0, ring);
  }
  return loaded;
}

/** Baked fonts named only by a text's `aod: {font:}` override, loaded on entering sleep. */
export function aodOnlyFonts(resolved: ResolvedFace): string[] {
  const awake = new Set(loadedFonts(resolved));
  const out: string[] = [];
  for (const placed of resolved.items) {
    if (!(placed instanceof PlacedText)) continue;
    const aod = placed.element.aod;
    if (aod === null || aod.font === null || !aod.font_is_custom) continue;
    if (aod.font === placed.font.reference || awake.has(aod.font) || out.includes(aod.font)) continue;
    const spec = resolved.face.fonts.get(aod.font);
    if (spec === undefined || spec.isVector) continue;
    out.push(aod.font);
  }
  return out;
}

/** Every `face:` font a text or pattern text part draws with, in first-appearance draw order. */
export function vectorFontsUsedIn(resolved: ResolvedFace): string[] {
  const face = resolved.face;
  return [...new Set(kinds.placedTextRuns(resolved.items, face).filter(([, run]) => !run.aod_only && run.isVector(face)).map(([, run]) => run.font))];
}

export function describe(placed: Placed): string {
  return kinds.forPlaced(placed).describe(placed);
}

/** A `Layout` constant's declared Monkey C type. */
export function mcType(value: PyNum | string | boolean | McLiteral): string {
  if (value instanceof McLiteral) return value.type;
  if (typeof value === "boolean") return "Boolean";
  if (typeof value === "string") return "String";
  return isFloat(value) ? "Float" : "Number";
}

export function mcBool(value: boolean): string {
  return value ? "true" : "false";
}

/** A `Layout` constant's value as Monkey C: a Float with a trailing `f`. */
export function mcNumber(value: PyNum | string | boolean | McLiteral): string {
  if (value instanceof McLiteral) return value.code;
  if (typeof value === "boolean") return mcBool(value);
  if (typeof value === "string") return stringLiteral(value);
  if (isFloat(value)) return `${floatRepr(val(value))}f`;
  return String(Math.trunc(val(value)));
}

/** `element`'s own `outline:` as a `RingPass`, dimmed like every AOD colour, or `null`. */
export function ownRing(element: Element, aod: AodStyle = NO_AOD): RingPass | null {
  const outline = element.outline;
  if (outline === null) return null;
  return new RingPass(aod.dimmed(element, outline.color), outline.width);
}
