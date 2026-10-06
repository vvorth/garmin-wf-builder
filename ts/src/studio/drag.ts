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
// - an arc's `start_angle` and `sweep`: `turn`, at the arc's two ends.
//
// All coordinates are device pixels.
import { ANGLES, EXTENTS } from "../edit/geometry.ts";
import { forPlaced } from "../kinds/index.ts";
import type { LiveHandle } from "../kinds/base.ts";
import type { Placed } from "../layout.ts";
import { formatG, roundHalfEven } from "../py.ts";
import { Length } from "../units.ts";

export interface Handle {
  kind: "end" | "size" | "angle";
  part?: "at" | "to";
  key?: string | string[];
  axis?: "x" | "y";
  gain?: number;
  x: number;
  y: number;
  cx?: number;
  cy?: number;
  start?: number;
  sweep?: number;
  live?: LiveHandle | null;
}

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
  if (element["shape"] === "polygon") return out;
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
          x: roundHalfEven(cx + radius * Math.sin(theta)), y: roundHalfEven(cy - radius * Math.cos(theta)),
        });
      }
    }
  }
  return out;
}

const signed = (n: number): string => (n >= 0 ? `+${n}` : String(n));

/** A drag in the author's terms, for the history: "move clock by (+6, -3) px on fr955". */
export function describe(gesture: Loose, elementId: string, device: string): string {
  const kind = gesture["kind"];
  if (kind === "move") {
    const part = gesture["part"] ?? "both";
    const what = part === "both" ? elementId : `${elementId}'s ${part === "at" ? "start" : "end"}`;
    return `move ${what} by (${signed(Number(gesture["dx"]))}, ${signed(Number(gesture["dy"]))}) px on ${device}`;
  }
  if (kind === "resize") {
    return `resize ${elementId}.${(gesture["key"] as string[]).join(".")} by ${signed(Number(gesture["delta"]))} px on ${device}`;
  }
  return `turn ${elementId}.${String(gesture["key"])} to ${formatG(Number(gesture["degrees"]))}° on ${device}`;
}
