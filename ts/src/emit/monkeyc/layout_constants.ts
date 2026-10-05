// `Layout.mc`'s per-device constants, the blocks every kind builds its own
// from. Port of the shared helpers of wfb/emit/monkeyc/layout_constants.py;
// the module itself is written with the rest of codegen.
import type { PyNum } from "../../draw/program.ts";
import { flt } from "../../draw/barrel.ts";
import type { PlacedGauge, PlacedGraph, PlacedHands, PlacedPattern, PlacedShape, ResolvedHandPart } from "../../layout.ts";
import { formatG } from "../../py.ts";
import type { IntBox } from "../../units.ts";
import { McLiteral } from "./common.ts";

/** One `Layout` block: `[name, value, note]` per constant. */
export type Constants = [string, PyNum | string | boolean | McLiteral, string][];

/** The `_X/_Y/_WIDTH/_HEIGHT` quartet for one resolved box. */
export function boxConstants(prefix: string, box: IntBox, note = ""): Constants {
  return [
    [`${prefix}_X`, box.x, note],
    [`${prefix}_Y`, box.y, ""],
    [`${prefix}_WIDTH`, box.width, ""],
    [`${prefix}_HEIGHT`, box.height, ""],
  ];
}

/** The `_RADIUS/_THICKNESS/_START/_SWEEP` quartet for one resolved arc. */
export function arcConstants(prefix: string, placed: PlacedShape | PlacedGauge): Constants {
  return [
    [`${prefix}_RADIUS`, placed.radius, ""],
    [`${prefix}_THICKNESS`, placed.thickness, "pen width; there is no filled-arc primitive"],
    [`${prefix}_START`, flt(placed.garmin_start),
      `${formatG(placed.start_angle)}deg clockwise from 12 o'clock, in Garmin's convention`],
    [`${prefix}_SWEEP`, flt(placed.sweep), "clockwise-positive degrees"],
  ];
}

/** `{prefix}_AOD_THICKNESS`, only when the element's resolved `aod:` overrides `thickness:`. */
export function aodThicknessConstant(prefix: string, placed: PlacedShape | PlacedGauge | PlacedGraph | PlacedHands | PlacedPattern,
  note = "aod: thickness override"): Constants {
  if (placed.aod_thickness === null) return [];
  return [[`${prefix}_AOD_THICKNESS`, placed.aod_thickness, note]];
}

/** One override, applied uniformly to every part of a hands/pattern element. */
export const EVERY_PART_NOTE = "aod: thickness override, applied to every part";

/** The `Layout` constants for one resolved hand part, or one pattern template part. */
export function handPartConstants(partPrefix: string, owner: string, index: number, part: ResolvedHandPart): Constants {
  if (part.shape === "text") {
    const out: Constants = [
      [`${partPrefix}_X`, part.x, `${owner}, part ${index}: text (the anchor)`],
      [`${partPrefix}_Y`, part.y, ""],
    ];
    if (part.curve.style === "radial") out.push([`${partPrefix}_RADIUS`, part.curve.radius_px, "curve: radial's own circle radius"]);
    return out;
  }
  if (part.shape === "polygon") {
    const points = part.points.map(([x, y]) => `[${x}, ${y}]`).join(", ");
    return [[`${partPrefix}_POINTS`, new McLiteral("Array<Graphics.Point2D>", `[${points}]`),
      `${owner}, part ${index}: a ${part.points.length}-vertex polygon`]];
  }
  if (part.shape === "line") {
    return [
      [`${partPrefix}_X1`, part.x1, `${owner}, part ${index}: a line`],
      [`${partPrefix}_Y1`, part.y1, ""],
      [`${partPrefix}_X2`, part.x2, ""],
      [`${partPrefix}_Y2`, part.y2, ""],
      [`${partPrefix}_THICKNESS`, part.thickness, "pen width"],
    ];
  }
  if (part.shape === "arc") {
    return [
      [`${partPrefix}_RADIUS`, part.radius, `${owner}, part ${index}: an arc`],
      [`${partPrefix}_THICKNESS`, part.thickness, "pen width; there is no filled-arc primitive"],
    ];
  }
  const out: Constants = [
    [`${partPrefix}_X`, part.x, `${owner}, part ${index}: a circle`],
    [`${partPrefix}_Y`, part.y, ""],
    [`${partPrefix}_RADIUS`, part.radius, ""],
  ];
  if (!part.filled) out.push([`${partPrefix}_THICKNESS`, part.thickness, "pen width; there is no filled-arc-style outline shortcut here"]);
  return out;
}

/** The numeric constants of `constants`, by name: what a kind's `lower` names. */
export function numericConstants(constants: Constants): Map<string, PyNum> {
  const out = new Map<string, PyNum>();
  for (const [name, value] of constants) if (typeof value === "number" || (typeof value === "object" && !(value instanceof McLiteral))) out.set(name, value as PyNum);
  return out;
}
