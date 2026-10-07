// Spelling helpers for the plain drawing primitives the printer and view read.
import type { PlacedGauge, PlacedShape } from "../../layout.ts";
import type { AodStyle } from "./common.ts";

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

