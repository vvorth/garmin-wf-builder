// A hand's or a needle's part, drawn turned about the frame's `cx`/`cy`
// by its `sin`/`cos` locals: a `Part` op (polygon, line, circle, through
// `WfbGeom`), or an arc's own `WfbArc.drawSpan`, its centre turned like a
// circle part's and its start angle shifted by `deg`, the frame's angle in
// degrees, since `dc.drawArc` takes degrees and nothing else.
import { type AodPick, ArcSpan, Bin, Const, FloatLit, type Num, NumLocal, type Op, Part, Shifted } from "../draw/program.ts";
import { discPerimeterOffsets } from "../ir/model.ts";
import type { TurnedPart } from "../layout.ts";

/** Whether any of `parts` is an arc, so the frame needs its angle in degrees (`deg`). */
export function hasArcPart(parts: readonly TurnedPart[]): boolean {
  return parts.some((part) => part.shape === "arc");
}

/** Whether any of `parts` turns a point, so the frame needs `sin`/`cos`: everything but an arc on the axis. */
export function needsTrig(parts: readonly TurnedPart[]): boolean {
  return parts.some((part) => part.shape !== "arc" || !part.onAxis);
}

/** One turned part at the frame's current angle; with `ring`, only its ring, the part drawn at every offset. */
export function turnedPart(part: TurnedPart, partPrefix: string, pen: AodPick, ring: number | null = null): Op[] {
  if (part.shape !== "arc") return [Part(part, partPrefix, true, pen, { ring })];
  let cx: Num = NumLocal("cx"), cy: Num = NumLocal("cy");
  if (!part.onAxis) {
    // The same rotation `WfbGeom` applies to a circle part's centre; `drawArc` truncates the Float as `fillCircle` does.
    const x = Const(`${partPrefix}_X`, part.x), y = Const(`${partPrefix}_Y`, part.y);
    cx = Bin("-", Bin("+", cx, Bin("*", x, NumLocal("cos"))), Bin("*", y, NumLocal("sin")));
    cy = Bin("+", Bin("+", cy, Bin("*", x, NumLocal("sin"))), Bin("*", y, NumLocal("cos")));
  }
  // Garmin's start is 90 minus the design angle, and the frame's own angle adds to the design angle.
  const start = Bin("-", FloatLit(90.0 - part.start_angle), NumLocal("deg"));
  const radius = Const(`${partPrefix}_RADIUS`, part.radius);
  const offsets: [number, number][] = ring !== null ? discPerimeterOffsets(ring) : [[0, 0]];
  return offsets.map(([dx, dy]) => ArcSpan(Shifted(cx, dx), Shifted(cy, dy), radius, pen, start, FloatLit(part.sweep), true));
}
