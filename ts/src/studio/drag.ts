// What the canvas lets the author drag, and a drag described for the
// history.
//
// The handles of a placed element follow from what `edit/geometry.ts` can
// write back for it, so a handle never offers a drag the engine refuses:
//
// - the element itself: `move` (its `at:`; a line's `to:` with it);
// - a line's two ends: `move` of one `part`;
// - `size:` width and height: `resize`, on the edge that moves when the size
//   grows, given the element's alignment: a left-aligned box grows to the
//   right, a centred one both ways, so dragging its right edge by one pixel
//   is two pixels of width (`gain`);
// - `radius:`: `resize`, on the circle's right;
// - an arc's `start_angle` and `sweep`: `turn`, at the arc's two ends;
// - a polygon's points: `vertex` on each, and `segment` at each edge's
//   midpoint, where `add_vertex` inserts one.
//
// A part of an entered element (`partHandles`) gets the same handles for
// its own shape, each where the part is drawn: turned with its hand or
// copy. A `mirror: x` part's listed half is draggable; the reflected half's
// vertices are shown, `mirrored`, and not.
//
// All coordinates are device pixels.
import type { Device } from "../devices/device.ts";
import { ANGLES, EXTENTS, onAxis } from "../edit/geometry.ts";
import { forPlaced } from "../kinds/index.ts";
import { PatternTextAngle, patternTextAnchor } from "../kinds/pattern.ts";
import { type Placed, PlacedPattern, type ResolvedHandPart, textInk } from "../layout.ts";
import { formatG } from "../py.ts";
import { Box, type IntBox, Length, roundPx } from "../units.ts";
import type { PartPlacement } from "./parts.ts";
import type { Handle } from "./protocol.ts";

export type { Handle };

/** `align`'s and `vertical_align`'s values, as the edge a growing box moves: the handle's side and its gain. */
const X: Record<string, [string, number]> = { left: ["right", 1], center: ["right", 2], right: ["left", -1] };
const Y: Record<string, [string, number]> = { top: ["bottom", 1], center: ["bottom", 2], bottom: ["top", -1] };

type Loose = Record<string, unknown>;

function length(element: unknown, ...path: string[]): Length | null {
  let value: unknown = element;
  for (const step of path) value = value !== null && typeof value === "object" ? (value as Loose)[step] : undefined;
  return value instanceof Length ? value : null;
}

/** The handles of `placed` beyond moving it whole, each with what the browser may redraw by itself while it is dragged. */
export function handles(placed: Placed): Handle[] {
  const kind = forPlaced(placed);
  const out = rawHandles(placed);
  for (const handle of out) handle.live = kind.liveHandle(placed, handle);
  return out;
}

function rawHandles(placed: Placed): Handle[] {
  const element = placed.element as unknown as Loose;
  const p = placed as unknown as Loose;
  const out: Handle[] = [];
  if (element["shape"] === "line") {
    const [ex, ey] = p["end"] as [number, number];
    out.push({ kind: "end", part: "at", x: placed.center[0], y: placed.center[1] });
    out.push({ kind: "end", part: "to", x: ex, y: ey });
    return out;
  }
  if (element["shape"] === "polygon") return polygonHandles((p["points"] as [number, number][]) ?? [], (i) => i, null);
  const box = placed.innerBox;
  const [cx, cy] = placed.center;
  const width = length(element, "size", "width"), height = length(element, "size", "height");
  if (width !== null && EXTENTS.has("size\0width")) {
    const [side, gain] = X[String(element["align"] ?? "center")] ?? ["right", 2];
    out.push({ kind: "size", key: ["size", "width"], axis: "x", gain, x: side === "right" ? box.x + box.width : box.x, y: box.y + Math.floor(box.height / 2) });
  }
  if (height !== null) {
    const [side, gain] = Y[String(element["vertical_align"] ?? "center")] ?? ["bottom", 2];
    out.push({ kind: "size", key: ["size", "height"], axis: "y", gain, x: box.x + Math.floor(box.width / 2), y: side === "bottom" ? box.y + box.height : box.y });
  }
  const radius = p["radius"];
  if (length(element, "radius") !== null && typeof radius === "number" && Number.isInteger(radius) && radius > 0) {
    out.push({ kind: "size", key: ["radius"], axis: "x", gain: 1, x: cx + radius, y: cy });
    const start = p["start_angle"], sweep = p["sweep"];
    // The rule `turn` applies: among shapes only an arc has angles.
    if (typeof start === "number" && typeof sweep === "number" && [...ANGLES].every((k) => k in element)
      && Math.abs(sweep) < 360 && (element["shape"] ?? "arc") === "arc") {
      for (const [key, degrees] of [["start_angle", start], ["sweep", start + sweep]] as const) {
        const theta = degrees * Math.PI / 180;
        out.push({
          kind: "angle", key, cx, cy, start, sweep,
          x: roundPx(cx + radius * Math.sin(theta)), y: roundPx(cy - radius * Math.cos(theta)),
        });
      }
    }
  }
  return out;
}

/**
 * A polygon's handles from its drawn `points`: a `vertex` on each of the
 * first `listed` (every one, when `null`), the rest `mirrored` and naming
 * the listed point `twin` gives, and a `segment` at the midpoint of each
 * edge between listed points (the closing edge too, when nothing is
 * mirrored).
 */
function polygonHandles(points: readonly (readonly [number, number])[], twin: (i: number) => number, listed: number | null): Handle[] {
  const out: Handle[] = [];
  const count = listed ?? points.length;
  points.forEach(([x, y], i) => {
    if (i < count) out.push({ kind: "vertex", index: i, x, y });
    else out.push({ kind: "vertex", index: twin(i), mirrored: true, x, y });
  });
  const edges = listed === null ? points.length : Math.max(count - 1, 0);
  for (let i = 0; i < edges; i++) {
    const [ax, ay] = points[i]!, [bx, by] = points[(i + 1) % points.length]!;
    out.push({ kind: "segment", after: i, x: roundPx((ax + bx) / 2), y: roundPx((ay + by) / 2) });
  }
  return out;
}

/** A point of a part's frame on the screen, through its copy's or hand's transform. */
function placedAt(t: readonly [number, number, number, number], x: number, y: number): [number, number] {
  const [ox, oy, s, c] = t;
  return [ox + x * c - y * s, oy + x * s + y * c];
}

/** `[x0, y0, x1, y1]` as a box of whole pixels. */
function boxOf([x0, y0, x1, y1]: readonly [number, number, number, number]): IntBox {
  return new Box(x0, y0, x1 - x0, y1 - y0).rounded();
}

/** The ink of a drawn part as a box, its centre, and its handles, all in device pixels. */
export function partGeometry(p: PartPlacement, owner: Placed, device: Device): [IntBox, [number, number], Handle[]] {
  const { resolved: part, ir, transform: t, written } = p;
  const at = (x: number, y: number): [number, number] => placedAt(t, x, y);
  const whole = (x: number, y: number): [number, number] => [roundPx(x), roundPx(y)];
  if (part.shape === "polygon") {
    const points = part.points.map(([x, y]) => at(x, y));
    const box = boxOf(part.ink(...t));
    const center = whole(points.reduce((a, [x]) => a + x, 0) / points.length, points.reduce((a, [, y]) => a + y, 0) / points.length);
    if (ir.shape === "rectangle") {
      // a rectangle part resolves to its corners: its size handles sit on the edges that grow, turned with it
      const [p0, p1, p2] = part.points as [[number, number], [number, number], [number, number]];
      const width = p1[0] - p0[0], height = p2[1] - p1[1];
      const [wSide, wGain] = X[ir.align] ?? ["right", 2], [hSide, hGain] = Y[ir.vertical_align] ?? ["bottom", 2];
      const cx = (p0[0] + p1[0]) / 2, cy = (p1[1] + p2[1]) / 2;
      const [wx, wy] = at(wSide === "right" ? p1[0] : p0[0], cy), [hx, hy] = at(cx, hSide === "bottom" ? p2[1] : p1[1]);
      const handles: Handle[] = [
        { kind: "size", key: ["size", "width"], axis: "x", gain: wGain, x: roundPx(wx), y: roundPx(wy) },
        { kind: "size", key: ["size", "height"], axis: "y", gain: hGain, x: roundPx(hx), y: roundPx(hy) },
      ];
      return [box, center, width > 0 && height > 0 ? handles : []];
    }
    const listed = written.has("mirror") && ir.shape === "polygon" ? (Array.isArray(written.get("points")) ? (written.get("points") as unknown[]).length : 0) : null;
    // the reflected half, in reverse order of the listed points that are off the axis
    const twins: number[] = [];
    if (listed !== null && ir.shape === "polygon") {
      for (let i = listed - 1; i >= 0; i--) if (!onAxis(ir.points[i]!)) twins.push(i);
    }
    const screen = points.map(([x, y]) => whole(x, y));
    return [box, center, polygonHandles(screen, (i) => twins[i - (listed ?? 0)] ?? i, listed)];
  }
  if (part.shape === "line") {
    const [x1, y1] = whole(...at(part.x1, part.y1)), [x2, y2] = whole(...at(part.x2, part.y2));
    return [boxOf(part.ink(...t)), [x1, y1], [{ kind: "end", part: "at", x: x1, y: y1 }, { kind: "end", part: "to", x: x2, y: y2 }]];
  }
  if (part.shape === "circle") {
    const center = whole(...at(part.x, part.y));
    const [hx, hy] = whole(...at(part.x + part.radius, part.y));
    return [boxOf(part.ink(...t)), center, part.radius > 0 ? [{ kind: "size", key: ["radius"], axis: "x", gain: 1, x: hx, y: hy }] : []];
  }
  if (part.shape === "arc") {
    const [cx, cy] = whole(t[0], t[1]);
    const frameAngle = Math.atan2(t[2], t[3]) * 180 / Math.PI;
    const start = part.start_angle + frameAngle;
    const handles: Handle[] = [];
    if (Math.abs(part.sweep) < 360 && part.radius > 0) {
      for (const [key, deg] of [["start_angle", start], ["sweep", start + part.sweep]] as const) {
        const theta = deg * Math.PI / 180;
        handles.push({ kind: "angle", key, cx, cy, start, sweep: part.sweep, x: roundPx(cx + part.radius * Math.sin(theta)), y: roundPx(cy - part.radius * Math.cos(theta)) });
      }
    }
    return [boxOf(part.ink(...t)), [cx, cy], handles];
  }
  // text: its first drawn copy's ink, no handles beyond moving it
  const [ox, oy, s, c] = t;
  const [ax, ay] = patternTextAnchor(part, ox, oy, s, c);
  const pattern = owner instanceof PlacedPattern ? owner : null;
  const copy = pattern !== null ? pattern.copies[0] ?? 0 : 0;
  const angle = new PatternTextAngle(part.curve.angle_garmin, pattern?.start ?? 0.0, pattern?.step ?? 0.0).copyCurveAngle(copy);
  const ink = textInk(ax, ay, part.widths[copy] ?? 0, part.line_height, part.align, part.vertical_align, {
    curveStyle: part.curve.style, angleGarmin: angle, radiusPx: part.curve.radius_px, direction: part.curve.direction,
    metric: part.font.metric, pad: part.outline_width, device,
  });
  return [ink.box().rounded(), [ax, ay], []];
}

const signed = (n: number): string => (n >= 0 ? `+${n}` : String(n));

/**
 * A drag in the author's terms, for the history: "move clock by (+6, -3)
 * px on fr955", "move vertex 2 of chevron by (+1, +0) px on fr955", "add a
 * vertex to hour.blade of clock on fr955". `what` names the subject (an
 * element by id, a part by its element and id), `where` the device or the
 * override selector it was written on.
 */
export function describe(gesture: Loose, what: string, where: string): string {
  const kind = gesture["kind"];
  const by = (): string => `by (${signed(Number(gesture["dx"]))}, ${signed(Number(gesture["dy"]))}) px`;
  if (kind === "move") {
    const part = gesture["part"] ?? "both";
    const moved = part === "both" ? what : `${what}'s ${part === "at" ? "start" : "end"}`;
    return `move ${moved} ${by()} on ${where}`;
  }
  if (kind === "vertex") return `move vertex ${Number(gesture["index"])} of ${what} ${by()} on ${where}`;
  if (kind === "add_vertex") return `add a vertex to ${what} on ${where}`;
  if (kind === "remove_vertex") return `remove vertex ${Number(gesture["index"])} of ${what} on ${where}`;
  if (kind === "resize") {
    return `resize ${what}.${(gesture["key"] as string[]).join(".")} by ${signed(Number(gesture["delta"]))} px on ${where}`;
  }
  return `turn ${what}.${String(gesture["key"])} to ${formatG(Number(gesture["degrees"]))}° on ${where}`;
}
