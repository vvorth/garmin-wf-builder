// Part emitters for `type: hands`, `type: pattern` and a needle: geometry
// rotated or translated on the device. Port of wfb/emit/monkeyc/rotated.py.
import { discPerimeterOffsets } from "../../ir/model.ts";
import type { PlacedGauge, PlacedHands, PlacedPattern, RotatablePart } from "../../layout.ts";
import type { Writer } from "../writer.ts";

/** The element-level `aod: {thickness:}` constant every part's pen applies, or `null`. */
export function aodThicknessOverride(placed: PlacedHands | PlacedPattern | PlacedGauge, prefix: string): string | null {
  return placed.aod_thickness !== null ? `Layout.${prefix}_AOD_THICKNESS` : null;
}

/** One part at the current copy's origin: rotated through `WfbGeom`, or translated with plain `Dc` calls. */
export function emitTransformedPart(w: Writer, part: RotatablePart, partPrefix: string,
  { radial, thicknessExpr, setPen = true }: { radial: boolean; thicknessExpr: string; setPen?: boolean }): void {
  const constant = `Layout.${partPrefix}`;
  const stroked = part.shape === "line" || (part.shape === "circle" && !part.filled);
  if (stroked && setPen) w.line(`dc.setPenWidth(${thicknessExpr});`);
  if (part.shape === "polygon") {
    w.line(radial ? `WfbGeom.fillRotated(dc, ${constant}_POINTS, cx, cy, sin, cos);` : `WfbGeom.fillTranslated(dc, ${constant}_POINTS, ox, oy);`);
  } else if (part.shape === "line") {
    if (radial) {
      w.call("WfbGeom.drawLineRotated", [`dc, ${constant}_X1, ${constant}_Y1`, `${constant}_X2, ${constant}_Y2, cx, cy, sin, cos`]);
    } else {
      w.call("dc.drawLine", [`ox + ${constant}_X1, oy + ${constant}_Y1`, `ox + ${constant}_X2, oy + ${constant}_Y2`]);
    }
  } else {
    const verb = part.filled ? "fill" : "draw";
    if (radial) w.call(`WfbGeom.${verb}CircleRotated`, [`dc, ${constant}_X, ${constant}_Y, ${constant}_RADIUS`, "cx, cy, sin, cos"]);
    else w.line(`dc.${verb}Circle(ox + ${constant}_X, oy + ${constant}_Y, ${constant}_RADIUS);`);
  }
  if (stroked && setPen) w.line("dc.setPenWidth(1);");
}

function moved(expr: string, by: number): string {
  return by === 0 ? expr : `${expr} ${by > 0 ? "+" : "-"} ${Math.abs(by)}`;
}

/** One part's `width` px `outline:` ring, the part transformed once and drawn at every offset. */
export function emitPartRing(w: Writer, part: RotatablePart, partPrefix: string, width: number,
  { radial, thicknessExpr, setPen = true }: { radial: boolean; thicknessExpr: string; setPen?: boolean }): void {
  const constant = `Layout.${partPrefix}`;
  const stroked = part.shape === "line" || (part.shape === "circle" && !part.filled);
  const [ring, offsets] = width === 1 ? ["WfbRing", ""] : ["WfbRingWide", `, Layout.OUTLINE_OFFSETS_${width}`];
  if (stroked && setPen) w.line(`dc.setPenWidth(${thicknessExpr});`);
  if (part.shape === "polygon") {
    w.line(radial ? `${ring}.rotated(dc, ${constant}_POINTS, cx, cy, sin, cos${offsets});` : `${ring}.translated(dc, ${constant}_POINTS, ox, oy${offsets});`);
  } else if (part.shape === "line") {
    if (radial && width > 1) {
      w.call("WfbRingWide.lineRotated", [`dc, [${constant}_X1, ${constant}_Y1, ${constant}_X2, ${constant}_Y2]`, `cx, cy, sin, cos${offsets}`]);
    } else if (radial) {
      w.call("WfbRing.lineRotated", [`dc, ${constant}_X1, ${constant}_Y1`, `${constant}_X2, ${constant}_Y2, cx, cy, sin, cos`]);
    } else {
      for (const [dx, dy] of discPerimeterOffsets(width)) {
        w.call("dc.drawLine", [
          `${moved(`ox + ${constant}_X1`, dx)}, ${moved(`oy + ${constant}_Y1`, dy)}`,
          `${moved(`ox + ${constant}_X2`, dx)}, ${moved(`oy + ${constant}_Y2`, dy)}`,
        ]);
      }
    }
  } else if (part.filled) {
    if (radial) w.call("WfbGeom.fillCircleRotated", [`dc, ${constant}_X, ${constant}_Y, ${constant}_RADIUS + ${width}`, "cx, cy, sin, cos"]);
    else w.line(`dc.fillCircle(ox + ${constant}_X, oy + ${constant}_Y, ${constant}_RADIUS + ${width});`);
  } else if (radial) {
    w.call(`${ring}.circleRotated`, [`dc, ${constant}_X, ${constant}_Y, ${constant}_RADIUS`, `cx, cy, sin, cos${offsets}`]);
  } else {
    for (const [dx, dy] of discPerimeterOffsets(width)) {
      w.line(`dc.drawCircle(${moved(`ox + ${constant}_X`, dx)}, ${moved(`oy + ${constant}_Y`, dy)}, ${constant}_RADIUS);`);
    }
  }
  if (stroked && setPen) w.line("dc.setPenWidth(1);");
}
