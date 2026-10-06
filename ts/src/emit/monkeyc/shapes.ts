// Spelling helpers for the plain drawing primitives the printer and view read.
import { discPerimeterOffsets } from "../../ir/model.ts";
import type { PlacedGauge, PlacedShape } from "../../layout.ts";
import type { Writer } from "../writer.ts";
import { type AodStyle, glyphYExpr, shifted } from "./common.ts";

export { shifted } from "./common.ts";

/** The two-line `WfbArc.drawSpan(...)` call against one arc's own constants. */
export function emitArcSpan(w: Writer, prefix: string, thicknessExpr: string | null = null, dx = 0, dy = 0): void {
  const pen = thicknessExpr ?? `Layout.${prefix}_THICKNESS`;
  w.call("WfbArc.drawSpan", [
    `dc, ${shifted(`Layout.${prefix}_CX`, dx)}, ${shifted(`Layout.${prefix}_CY`, dy)}, Layout.${prefix}_RADIUS`,
    `${pen}, Layout.${prefix}_START, Layout.${prefix}_SWEEP`,
  ]);
}

/** `Layout.<P>_THICKNESS`, ternary against `_AOD_THICKNESS` when overridden. */
export function thicknessExpr(prefix: string, placed: PlacedShape | PlacedGauge, aod: AodStyle): string {
  return aod.layout(prefix, "THICKNESS", placed.aod_thickness !== null);
}

/** `curve.direction` to `Graphics.RadialTextDirection`. */
export const RADIAL_DIRECTION: Readonly<Record<string, string>> = {
  clockwise: "RADIAL_TEXT_DIRECTION_CLOCKWISE",
  counter_clockwise: "RADIAL_TEXT_DIRECTION_COUNTER_CLOCKWISE",
};

/** `dc.drawRadialText`'s `radius` argument: `top` moves the baseline one font ascent toward the glyphs' "down". */
export function radialRadiusExpr(radiusExpr: string, verticalAlign: string, direction: string | null, fontExpr: string): string {
  if (verticalAlign !== "top") return radiusExpr;
  const sign = direction === "counter_clockwise" ? "+" : "-";
  return `${radiusExpr} ${sign} Graphics.getFontAscent(${fontExpr})`;
}

/** The stamped ring ahead of a draw call's own interior pass. */
export function emitOutline(w: Writer, colorCode: string, width: number, xExpr: string, yExpr: string,
  draw: (x: string, y: string) => void, { blankAfter = true } = {}): void {
  emitStamp(w, colorCode, width, (dx, dy) => draw(shifted(xExpr, dx), shifted(yExpr, dy)), { blankAfter });
}

/** Set the ring colour once, then `draw(dx, dy)` at each perimeter offset, unrolled. */
export function emitStamp(w: Writer, colorCode: string, width: number, draw: (dx: number, dy: number) => void, { blankAfter = true } = {}): void {
  w.line(`dc.setColor(${colorCode}, Graphics.COLOR_TRANSPARENT);`);
  for (const [dx, dy] of discPerimeterOffsets(width)) draw(dx, dy);
  if (blankAfter) w.blank();
}

/** One upright `dc.drawText` call at a screen-space anchor. */
export function emitPlainTextCall(w: Writer, xExpr: string, yExpr: string, fontExpr: string, valueCode: string, justify: string, verticalAlign: string): void {
  w.call("dc.drawText", [`${xExpr}, ${glyphYExpr(yExpr, verticalAlign, fontExpr)}, ${fontExpr}`, valueCode, justify]);
}
