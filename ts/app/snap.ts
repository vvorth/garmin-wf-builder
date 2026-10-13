// Snapping a drag: pure functions, no DOM, so Node can check them
// (test/page-modules.test.ts). All lengths are device pixels.

import type { Gesture, Handle } from "../src/studio/protocol.ts";
import type { Box, Placed } from "./hit.ts";

/** The lines a move may snap to, the grid about the screen centre (0: none), and that centre. */
export interface Targets {
  xs: number[];
  ys: number[];
  grid: number;
  cx: number;
  cy: number;
}

/** A move, snapped: whole pixels, and the guide lines it snapped to, for drawing. */
export interface SnappedMove {
  dx: number;
  dy: number;
  guides: { x: number[]; y: number[] };
}

// The lines a moved element may snap to: the screen's centre lines, every
// other element's centre and edges, and a grid of `gridPercent` %r about
// the screen centre. `moving`: the id being moved, or a Set of the ids
// moving together, none of which is a target.
export function moveTargets(items: readonly Placed[], moving: string | ReadonlySet<string>, width: number, height: number, minorRadius: number, gridPercent: number): Targets {
  const xs = [width / 2], ys = [height / 2];
  const skip = moving instanceof Set ? moving : new Set([moving]);
  for (const item of items) {
    if (skip.has(item.id) || !item.box) continue;
    const [x, y, w, h] = item.box;
    xs.push(x, x + w, item.center[0]);
    ys.push(y, y + h, item.center[1]);
  }
  const grid = gridPercent > 0 ? (minorRadius * gridPercent) / 100 : 0;
  return { xs, ys, grid, cx: width / 2, cy: height / 2 };
}

function nearestOnGrid(value: number, origin: number, grid: number): number {
  return origin + Math.round((value - origin) / grid) * grid;
}

/** The shift that snaps one axis, the line it lands on, and whether that line is the grid's. */
interface AxisSnap {
  d: number;
  line: number;
  grid?: boolean;
}

// One axis: the smallest shift (within `threshold`) that puts one of the
// element's own lines (`own`: its two edges and its centre, moved by
// `delta`) on a guide; failing that, its centre on the grid. An axis the
// drag has not moved along (under a pixel) does not snap at all, so a
// horizontal drag never nudges the element up or down.
function snapAxis(own: readonly number[], centre: number, delta: number, lines: readonly number[], grid: number, origin: number, threshold: number): AxisSnap | null {
  if (Math.abs(delta) < 1) return null;
  let best: AxisSnap | null = null;
  for (const o of own) {
    const at = o + delta;
    for (const t of lines) {
      const d = t - at;
      if (Math.abs(d) <= threshold && (!best || Math.abs(d) < Math.abs(best.d))) best = { d, line: t };
    }
  }
  if (!best && grid) {
    const g = nearestOnGrid(centre + delta, origin, grid);
    const d = g - (centre + delta);
    if (Math.abs(d) <= threshold) best = { d, line: g, grid: true };
  }
  return best;
}

// A move by (dx, dy), snapped: whole device pixels, and the guide lines
// it snapped to, for drawing.
export function snapMove(item: { box: Box; center: [number, number] }, dx: number, dy: number, targets: Targets, threshold = 4): SnappedMove {
  const [x, y, w, h] = item.box;
  const sx = snapAxis([x, item.center[0], x + w], item.center[0], dx, targets.xs, targets.grid, targets.cx, threshold);
  const sy = snapAxis([y, item.center[1], y + h], item.center[1], dy, targets.ys, targets.grid, targets.cy, threshold);
  return {
    dx: Math.round(dx + (sx ? sx.d : 0)),
    dy: Math.round(dy + (sy ? sy.d : 0)),
    guides: { x: sx ? [sx.line] : [], y: sy ? [sy.line] : [] },
  };
}

// A length's new value in pixels, snapped to the %r grid within threshold.
export function snapLength(px: number, minorRadius: number, gridPercent: number, threshold = 3): number {
  if (!(gridPercent > 0)) return Math.round(px);
  const grid = (minorRadius * gridPercent) / 100;
  const g = Math.round(px / grid) * grid;
  return Math.round(Math.abs(g - px) <= threshold ? g : px);
}

// An angle (degrees, 12 o'clock = 0, clockwise) snapped to a multiple of
// 30 within 3 degrees, else to a multiple of 6.
export function snapAngle(degrees: number): number {
  const thirty = Math.round(degrees / 30) * 30;
  if (Math.abs(thirty - degrees) <= 3) return thirty;
  return Math.round(degrees / 6) * 6;
}

// The angle of point (x, y) about (cx, cy), 12 o'clock = 0, clockwise.
export function angleAt(cx: number, cy: number, x: number, y: number): number {
  const a = (Math.atan2(x - cx, -(y - cy)) * 180) / Math.PI;
  return a < 0 ? a + 360 : a;
}

// `value` moved by whole turns to lie nearest `near`: an arc's end
// dragged past 12 o'clock keeps sweeping the same way.
export function nearestTurn(value: number, near: number): number {
  return value + 360 * Math.round((near - value) / 360);
}

// A resize handle's new extent change from a pointer delta: the handle's
// own axis, times its gain (2 for a centred box, -1 for one growing the
// other way; a handle without one moves pixel for pixel).
export function resizeDelta(handle: Pick<Handle, "axis" | "gain">, dx: number, dy: number): number {
  return Math.round((handle.axis === "y" ? dy : dx) * (handle.gain ?? 1));
}

// What the canvas says during a drag: how far it has gone, and whether it
// snaps or, with Alt held (`free`), places freely, so the key that turns
// snapping off is on the screen while it matters.
export function dragHint(gesture: Gesture, free: boolean): string {
  const signed = (n: number): string => (n > 0 ? `+${n}` : n < 0 ? `−${-n}` : "0");
  const what = gesture.kind === "move" ? `${signed(gesture.dx)}, ${signed(gesture.dy)} px`
    : gesture.kind === "resize" ? `${signed(gesture.delta)} px`
    : `${Math.round(gesture.degrees)}°`;
  return `${what} · ${free ? "placed freely (Alt)" : "snapping · hold Alt to place freely"}`;
}
