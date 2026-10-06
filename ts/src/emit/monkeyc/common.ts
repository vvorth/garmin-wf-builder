// Shared small helpers and types for the Monkey C generation. Port of the
// parts of wfb/emit/monkeyc/common.py the draw program reads.
import type { Element, Expression } from "../../ir/model.ts";
import { aodColorChoice } from "../../ir/model.ts";
import { elementConstPrefix } from "../../ir/naming.ts";
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
