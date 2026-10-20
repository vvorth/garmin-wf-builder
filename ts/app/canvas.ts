// The canvas: the face as the worker drew it, selection, and the drag
// gestures. The frame arrives with its layers as JSON ops (the preview's
// own rasteriser draws them: `src/raster/canvas.ts`, which the server
// bundles), so hit-testing reads where each layer leaves ink. During a
// move the whole face is drawn here from the layers' ops, the dragged ones
// translated; a resize, an angle or a line's end is drawn as an outline. On
// release the gesture joins the editor's outbox (`outbox.ts`), which sends
// it to the worker, which writes it in the author's units and answers with
// the new face, whose frame then replaces the preview. Until it does, the
// canvas draws the gestures still on their way and takes the next press
// against where they will put things. Nothing here decides where anything
// lands.
//
// A frame entered into a hands, pattern or needle element (`frame.local`)
// shows that element's parts over a ghost of the face: the part's own frame
// is drawn over it (its axis, the 12 o'clock ray turned as the parts are,
// the `%r` ring), a press picks a part by its box (the ghost is one image),
// and a polygon's points, an element's or a part's, carry vertex handles
// (small squares; a `mirror: x` part's reflected half hollow and still) and
// segment handles (dots on each edge's middle): a vertex is dragged, or
// clicked to pick it (Delete then removes it), a segment is clicked or
// dragged to add a vertex there. Their previews are the polygon's outline
// with the point moved or added; nothing is redrawn from the layers inside
// an entered frame, since the ghost is not among them.

import { WorkerImage } from "./ui.ts";
import { html } from "htm/preact";
import type { JSX, VNode } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { Frame, FrameItem, FrameLocal, Gesture, Handle, JsonOp, LiveHandle, PointGesture, Skin, Summary } from "../src/studio/protocol.ts";
import type { Box, Placed } from "./hit.ts";
import { elementOf, handleAt, moveHandle, movedBy, together, topmost } from "./hit.ts";
import type { AnyGesture, Entry, GestureEntry, Guides, Preview } from "./outbox.ts";
import { offsets, shiftItems, unshown } from "./outbox.ts";
import * as raster from "./raster.js";
import {
  angleAt, dragHint, moveTargets, nearestTurn, resizeDelta, snapAngle, snapLength, snapMove,
} from "./snap.ts";

const ACCENT = "#4f9cf9";
const GUIDE = "#f5c04a";
const GRID_PERCENT = 5;     // the %r grid a move and a length snap to
const HANDLE = 5;           // a handle's half size, screen pixels
const GRIP = 11;            // the move handle's radius, screen pixels
const START = 3;            // screen pixels before a press becomes a drag

type Ctx = CanvasRenderingContext2D;
type Tiles = Awaited<ReturnType<typeof raster.inflateTiles>>;
type Ink = ReturnType<typeof raster.inkOf>;
/** How far each element (by id) still has to move, in device pixels: `outbox.ts`'s `offsets`. */
type Offsets = ReadonlyMap<string, [number, number]>;

/** A fallback layer's PNG as RGBA bytes. */
interface Rgba {
  width: number;
  height: number;
  data: Uint8ClampedArray;
}

/**
 * A frame's layer, ready to draw and hit-test: a JSON layer's `ops`, whose
 * ink is worked out the first time a press lands in its box (`inkAt`), or a
 * fallback layer the worker drew, its PNG decoded and placed at `origin`.
 */
interface PreparedLayer {
  id: string;
  kind: string;
  ops: JsonOp[] | null;
  origin: [number, number] | null;
  png: Rgba | null;
  box: Box | null;
  ink: Ink | undefined;
}

/** A frame's layers, ready to draw and hit-test, for the frame of `version`. */
interface Prepared {
  version: number;
  tiles: Tiles;
  layers: PreparedLayer[];
}

/** A layer read where a move not drawn yet will put it: its box shifted, its ink read through `base` at `off`. */
interface ShiftedLayer {
  id: string;
  box: Box | null;
  base: PreparedLayer;
  off: [number, number];
}

type MoveGesture = Extract<Gesture, { kind: "move" }>;
type ResizeGesture = Extract<Gesture, { kind: "resize" }>;
type TurnGesture = Extract<Gesture, { kind: "turn" }>;
type VertexGesture = Extract<PointGesture, { kind: "vertex" }>;
type AddVertexGesture = Extract<PointGesture, { kind: "add_vertex" }>;

// The handles as the worker sends them (`studio/drag.ts`'s `handles`):
// `Handle` declares every field optional, and each kind fills its own.
/** A line's end: which end. */
type EndHandle = Handle & { kind: "end"; part: "at" | "to" };
/** A size edge: the path of the size key it changes. */
type SizeHandle = Handle & { kind: "size"; key: string[] };
/** An arc's end: the angle key it turns, and the arc it sits on. */
type AngleHandle = Handle & { kind: "angle"; key: string; cx: number; cy: number; start: number; sweep: number };
/** A polygon's point: its index among the written points (a mirrored one names the point it reflects). */
type VertexHandle = Handle & { kind: "vertex"; index: number };
/** The middle of a polygon's edge: the written point it follows. */
type SegmentHandle = Handle & { kind: "segment"; after: number };

const isEnd = (h: Handle): h is EndHandle => h.kind === "end" && h.part !== undefined;
const isSize = (h: Handle): h is SizeHandle => h.kind === "size" && Array.isArray(h.key);
const isAngle = (h: Handle | undefined): h is AngleHandle => h !== undefined && h.kind === "angle" && typeof h.key === "string"
  && h.cx !== undefined && h.cy !== undefined && h.start !== undefined && h.sweep !== undefined;
const isVertex = (h: Handle): h is VertexHandle => h.kind === "vertex" && typeof h.index === "number";
const isSegment = (h: Handle): h is SegmentHandle => h.kind === "segment" && typeof h.after === "number";

/** A gesture under way: what is sent on release, with what its preview is drawn from (an `outbox.ts` `Preview`). */
type Own =
  | (MoveGesture & { guides: Guides })
  | (ResizeGesture & { handle: SizeHandle; to?: number })
  | (TurnGesture & { handle: AngleHandle })
  | (VertexGesture & { handle: VertexHandle; guides: Guides })
  | (AddVertexGesture & { handle: SegmentHandle });

/** What a drag acts on: the dragged item, or the selection as one (`together`). */
type Target = Placed & { box: Box; handles: readonly Handle[] };

/** A press on the canvas, not (yet) a drag. */
interface Press {
  ids: string[];
  /** Every element it moves: `ids` and, inside a group among them, its children. */
  moving: Set<string>;
  /** The element to select should the press turn out to be a click inside the selection. */
  click: string | null;
  handle: Handle | null;
  /** Where it began: device pixels, and screen pixels for the drag threshold. */
  x: number;
  y: number;
  sx: number;
  sy: number;
  gesture: null;
}

/** A press the pointer has moved `START` screen pixels from: a gesture on `item`. */
interface Dragging extends Omit<Press, "gesture"> {
  gesture: Own;
  item: Target;
  /** Alt held: placed freely, no snapping. */
  free: boolean;
}

type Drag = Press | Dragging;

const dragging = (d: Drag | null): d is Dragging => d !== null && d.gesture !== null;

type PointerEv = JSX.TargetedPointerEvent<HTMLElement>;

// A fallback layer's PNG as RGBA bytes.
async function decodePng(src: string): Promise<Rgba> {
  const img = new Image();
  img.src = src;
  await img.decode();
  const c = document.createElement("canvas");
  c.width = img.width; c.height = img.height;
  const ctx = c.getContext("2d");
  if (!ctx) throw new Error("no 2d canvas");
  ctx.drawImage(img, 0, 0);
  const data = ctx.getImageData(0, 0, img.width, img.height);
  return { width: data.width, height: data.height, data: data.data };
}

// A frame's layers, ready to draw and hit-test: its tiles inflated, a
// fallback layer's image decoded. A JSON layer's ink is worked out the
// first time a press lands in its box (`inkAt`).
async function prepare(frame: Frame): Promise<Prepared> {
  const tiles = await raster.inflateTiles(frame.tiles);
  const boxes = new Map<string, Box>(frame.items.map((i) => [i.id, i.box]));
  const layers = await Promise.all(frame.layers.map(async (l): Promise<PreparedLayer> => ({
    id: l.id, kind: l.kind, ops: l.ops || null, origin: l.origin || null,
    png: l.image ? await decodePng(l.image) : null,
    box: boxes.get(l.id) || null, ink: undefined,
  })));
  return { version: frame.version, tiles, layers };
}

// The layer's ink at device pixel (x, y), 0 or more. Layers come at the
// watch's native size.
function inkAt(frame: Frame, prepared: Prepared, layer: PreparedLayer, x: number, y: number): number {
  const px = Math.floor(x), py = Math.floor(y);
  if (layer.png) {
    if (!layer.origin) return 0;
    const ix = px - layer.origin[0], iy = py - layer.origin[1];
    if (ix < 0 || iy < 0 || ix >= layer.png.width || iy >= layer.png.height) return 0;
    return layer.png.data[(iy * layer.png.width + ix) * 4 + 3] ?? 0;
  }
  if (!layer.ops) return 0;
  if (layer.ink === undefined) {
    layer.ink = raster.inkOf(layer.ops, prepared.tiles, frame.width, frame.height, 1);
  }
  const b = layer.ink.box;
  if (!b || px < b[0] || py < b[1] || px >= b[2] || py >= b[3]) return 0;
  return layer.ink.mask[(py - b[1]) * (b[2] - b[0]) + (px - b[0])] ? 255 : 0;
}

// What is under device pixel (x, y): by the layers' ink when they are
// ready, else the smallest drawn box holding the point. `frame.items` may
// be shifted (`shiftItems`) by `by`, the moves not drawn yet: a moved
// layer is read where it will be. In an entered frame the parts are picked
// by their boxes alone: the ghost round them is one image. An element
// locked in the editor is passed over: the press reaches what is under it.
function pick(frame: Frame, prepared: Prepared | null, x: number, y: number, by: Offsets = new Map(), locked: ReadonlySet<string> = new Set()): string | null {
  if (prepared && !frame.local) {
    const layers: readonly (PreparedLayer | ShiftedLayer)[] = by.size ? prepared.layers.map((l): PreparedLayer | ShiftedLayer => {
      const o = by.get(elementOf(l.id));
      if (!o) return l;
      const box: Box | null = l.box && [l.box[0] + o[0], l.box[1] + o[1], l.box[2], l.box[3]];
      return { id: l.id, box, base: l, off: o };
    }) : prepared.layers;
    const pickable = locked.size ? layers.filter((l) => !locked.has(elementOf(l.id))) : layers;
    const hit = topmost(pickable, x, y, (layer) => ("base" in layer
      ? inkAt(frame, prepared, layer.base, x - layer.off[0], y - layer.off[1])
      : inkAt(frame, prepared, layer, x, y)));
    if (hit) return elementOf(hit.id);
  }
  let best: FrameItem | null = null;
  for (const item of frame.items) {
    if (!item.drawn || locked.has(item.id)) continue;
    const [bx, by0, bw, bh] = item.box;
    if (x >= bx && y >= by0 && x < bx + bw && y < by0 + bh && (!best || bw * bh <= best.box[2] * best.box[3])) best = item;
  }
  return best ? best.id : null;
}

// The face drawn from its layers, each JSON layer's ops passed through
// `change(layer, ops)` and each fallback image shifted by `shift(layer)`
// frame pixels: what the worker will draw once a gesture lands. Drawn at
// the watch's native size and enlarged `s` times without smoothing, as the
// worker's frame is. Cleared to black inside the screen's own shape only,
// so the skin round a round screen stays visible.
function drawChanged(ctx: Ctx, frame: Frame, prepared: Prepared, change: (layer: PreparedLayer, ops: JsonOp[]) => readonly JsonOp[],
                     shift: (layer: PreparedLayer) => [number, number], s: number): void {
  const width = frame.width, height = frame.height;
  const im = raster.image(width, height, [0, 0, 0]);
  for (const l of prepared.layers) {
    if (l.ops) raster.drawOps(im, change(l, l.ops), prepared.tiles, 1);
    else if (l.png && l.origin) {
      const [dx, dy] = shift(l);
      raster.composite(im, l.png, l.origin[0] + dx, l.origin[1] + dy);
    }
  }
  const scratch = document.createElement("canvas");
  scratch.width = width; scratch.height = height;
  const sctx = scratch.getContext("2d");
  if (!sctx) return;
  // the rasteriser's pixels are a plain `Uint8ClampedArray` over an `ArrayBuffer` (`image()`), which its `Image` type leaves open
  sctx.putImageData(new ImageData(im.data as Uint8ClampedArray<ArrayBuffer>, width, height), 0, 0);
  ctx.save();
  if (frame.shape === "round") {
    ctx.beginPath();
    ctx.arc(width * s / 2, height * s / 2, Math.min(width, height) * s / 2, 0, Math.PI * 2);
    ctx.clip();
  }
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(scratch, 0, 0, width * s, height * s);
  ctx.restore();
}

// `k`: canvas pixels per screen pixel, so a handle is the same size on the
// screen at every zoom. A vertex is a smaller square, filled with the accent
// when it is the picked one and hollow when it is a mirrored point's (shown,
// not dragged); a segment's middle is a dot.
function drawHandle(ctx: Ctx, h: Handle, s: number, k: number, picked = false): void {
  const { x, y } = h;
  ctx.setLineDash([]);
  ctx.fillStyle = picked ? ACCENT : "#fff";
  ctx.strokeStyle = ACCENT;
  ctx.lineWidth = 1.5 * k;
  if (h.kind === "segment") {
    ctx.beginPath();
    ctx.arc(x * s, y * s, 3 * k, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    return;
  }
  const r = (h.kind === "vertex" ? HANDLE - 1 : HANDLE) * k;
  if (!h.mirrored) ctx.fillRect(x * s - r, y * s - r, r * 2, r * 2);
  ctx.strokeRect(x * s - r, y * s - r, r * 2, r * 2);
}

// An entered element's own frame over the ghost: the axis cross at its
// origin, the ring at 100 %r with ticks along the 12 o'clock ray at every
// 25 %r, the ray turned by the angle the parts are drawn at.
function drawLocalFrame(ctx: Ctx, local: FrameLocal, frame: Frame, s: number, k: number): void {
  const [ox, oy] = local.origin;
  const R = local.radius * 100;
  ctx.save();
  ctx.strokeStyle = "rgba(79, 156, 249, 0.55)";
  ctx.lineWidth = k;
  ctx.setLineDash([3 * k, 4 * k]);
  ctx.beginPath();
  ctx.moveTo(0, oy * s); ctx.lineTo(frame.width * s, oy * s);
  ctx.moveTo(ox * s, 0); ctx.lineTo(ox * s, frame.height * s);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(ox * s, oy * s, R * s, 0, Math.PI * 2);
  ctx.stroke();
  // the ray: where the parts' own "up" points
  const t = (local.angle * Math.PI) / 180, ux = Math.sin(t), uy = -Math.cos(t);
  ctx.setLineDash([]);
  ctx.strokeStyle = "rgba(79, 156, 249, 0.9)";
  ctx.beginPath();
  ctx.moveTo(ox * s, oy * s);
  ctx.lineTo((ox + ux * R) * s, (oy + uy * R) * s);
  ctx.stroke();
  for (const share of [0.25, 0.5, 0.75, 1]) {
    const px = ox + ux * R * share, py = oy + uy * R * share, tick = 4 * k;
    ctx.beginPath();
    ctx.moveTo(px * s - uy * tick, py * s + ux * tick);
    ctx.lineTo(px * s + uy * tick, py * s - ux * tick);
    ctx.stroke();
  }
  ctx.restore();
}

/** A screen delta turned into a frame drawn at `angle` degrees, and back. */
const toLocal = (dx: number, dy: number, angle: number): [number, number] => {
  const t = (angle * Math.PI) / 180;
  return [dx * Math.cos(t) + dy * Math.sin(t), -dx * Math.sin(t) + dy * Math.cos(t)];
};
const fromLocal = (dx: number, dy: number, angle: number): [number, number] => toLocal(dx, dy, -angle);

// The polygon's outline once a vertex gesture lands: its vertex handles in
// drawn order, the dragged point moved (a mirrored twin by the delta
// reflected across the part's axis, which is turned by `angle`), or the
// new point put after the one it follows.
function outlineAfter(item: Placed, g: VertexGesture | AddVertexGesture, angle: number): [number, number][] {
  const vertices = (item.handles ?? []).filter(isVertex);
  if (g.kind === "vertex") {
    const [lx, ly] = toLocal(g.dx, g.dy, angle);
    const [mx, my] = fromLocal(-lx, ly, angle);
    return vertices.map((h) => (h.index !== g.index ? [h.x, h.y] : h.mirrored ? [h.x + mx, h.y + my] : [h.x + g.dx, h.y + g.dy]));
  }
  const points: [number, number][] = vertices.map((h) => [h.x, h.y]);
  points.splice(g.after + 1, 0, [g.x, g.y]);
  return points;
}

function strokePolygon(ctx: Ctx, points: readonly (readonly [number, number])[], s: number): void {
  if (points.length < 2) return;
  ctx.beginPath();
  points.forEach(([x, y], i) => { if (i === 0) ctx.moveTo(x * s, y * s); else ctx.lineTo(x * s, y * s); });
  ctx.closePath();
  ctx.stroke();
}

// The move handle: a disc with four arrows, the same size at every zoom.
function drawGrip(ctx: Ctx, x: number, y: number, s: number, k: number): void {
  const cx = x * s, cy = y * s, r = GRIP * k, a = 3 * k, reach = r - 3 * k;
  ctx.setLineDash([]);
  ctx.fillStyle = "#fff";
  ctx.strokeStyle = ACCENT;
  ctx.lineWidth = 1.5 * k;
  ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
  ctx.beginPath();
  for (const [ux, uy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
    const tx = cx + ux * reach, ty = cy + uy * reach;
    ctx.moveTo(cx, cy); ctx.lineTo(tx, ty);
    ctx.moveTo(tx - ux * a + uy * a, ty - uy * a + ux * a); ctx.lineTo(tx, ty);
    ctx.lineTo(tx - ux * a - uy * a, ty - uy * a - ux * a);
  }
  ctx.stroke();
}

function guides(ctx: Ctx, g: Guides, frame: Frame, s: number): void {
  ctx.setLineDash([3, 3]);
  ctx.strokeStyle = GUIDE;
  ctx.lineWidth = 1;
  for (const x of g.x) { ctx.beginPath(); ctx.moveTo(x * s, 0); ctx.lineTo(x * s, frame.height * s); ctx.stroke(); }
  for (const y of g.y) { ctx.beginPath(); ctx.moveTo(0, y * s); ctx.lineTo(frame.width * s, y * s); ctx.stroke(); }
}

// The box a resize would give: the moving edge follows the handle; a
// centred box grows both ways.
function resizedBox(box: Box, handle: Handle, delta: number): Box {
  let [x, y, w, h] = box;
  if (handle.key?.[0] === "radius") return box;
  const gain = handle.gain ?? 1;
  if (handle.axis === "x") {
    if (gain === 2) { x -= delta / 2; w += delta; } else if (gain < 0) { x -= delta; w += delta; } else w += delta;
  } else {
    if (gain === 2) { y -= delta / 2; h += delta; } else if (gain < 0) { y -= delta; h += delta; } else h += delta;
  }
  return [x, y, w, h];
}

// The face with each element `by` (a Map from id to [dx, dy] device
// pixels) names moved by that much.
function drawMoved(ctx: Ctx, frame: Frame, prepared: Prepared, by: Offsets, s: number): void {
  const off = (l: PreparedLayer): [number, number] | undefined => by.get(elementOf(l.id));
  drawChanged(ctx, frame, prepared, (l, ops) => {
    const o = off(l);
    return o ? raster.translateOps(ops, o[0], o[1]) : ops;
  }, (l) => off(l) || [0, 0], s);
}

// `by` with every element of `moving` moved (dx, dy) further.
function plus(by: Offsets, moving: Iterable<string>, dx: number, dy: number): Map<string, [number, number]> {
  const out = new Map(by);
  for (const id of moving) {
    const [x, y] = out.get(id) || [0, 0];
    out.set(id, [x + dx, y + dy]);
  }
  return out;
}

// The face with the element `id` drawn as a live handle (`live`, which the
// worker declares only where it predicts the edit exactly) leaves it.
function drawLive(ctx: Ctx, frame: Frame, prepared: Prepared, id: string, live: LiveHandle, g: Extract<Preview, { kind: "resize" | "turn" }>, s: number): void {
  const change = g.kind === "turn" ? { degrees: g.degrees } : { delta: g.delta };
  drawChanged(ctx, frame, prepared,
              (l, ops) => (l.id === id ? raster.liveOps(ops, live, change) : ops),
              () => [0, 0], s);
}

// The preview of a gesture in progress, or of one sent and not yet drawn.
// `moving`: every element the gesture moves (a group's children included).
// `by`: the moves sent before it and not drawn yet, which `item` already
// carries. `angle`: the frame the item's points are drawn in, for a part.
function drawPreview(ctx: Ctx, frame: Frame, prepared: Prepared | null, item: Placed, moving: Iterable<string>, g: Preview, s: number,
                     by: Offsets = new Map(), angle = 0): void {
  if (prepared && by.size && !(g.kind === "move" && g.part === "both")) {
    drawMoved(ctx, frame, prepared, by, s);
  }
  ctx.setLineDash([6, 4]);
  ctx.strokeStyle = ACCENT;
  ctx.lineWidth = 2;
  if (g.kind === "vertex" || g.kind === "add_vertex") {
    strokePolygon(ctx, outlineAfter(item, g, angle), s);
  } else if (g.kind === "remove_vertex") {
    strokePolygon(ctx, (item.handles ?? []).filter(isVertex).filter((h) => h.index !== g.index).map((h) => [h.x, h.y]), s);
  } else if (g.kind !== "move" && g.handle && g.handle.live && prepared && !by.size) {
    drawLive(ctx, frame, prepared, item.id, g.handle.live, g as Extract<Preview, { kind: "resize" | "turn" }>, s);
  } else if (g.kind === "move" && g.part === "both") {
    if (prepared) drawMoved(ctx, frame, prepared, plus(by, moving, g.dx, g.dy), s);
    if (item.box) {
      const [x, y, w, h] = item.box;
      ctx.setLineDash([6, 4]);
      ctx.strokeStyle = ACCENT;
      ctx.strokeRect((x + g.dx) * s - 1, (y + g.dy) * s - 1, w * s + 2, h * s + 2);
    }
  } else if (g.kind === "move") {
    const ends = (item.handles ?? []).filter((h) => h.kind === "end");
    const fixed = ends.find((h) => h.part !== g.part), end = ends.find((h) => h.part === g.part);
    if (fixed && end) {
      ctx.beginPath();
      ctx.moveTo(fixed.x * s, fixed.y * s);
      ctx.lineTo((end.x + g.dx) * s, (end.y + g.dy) * s);
      ctx.stroke();
    }
  } else if (g.kind === "resize" && g.key[0] === "radius") {
    if (g.to !== undefined) {
      ctx.beginPath();
      ctx.arc(item.center[0] * s, item.center[1] * s, Math.max(0, g.to) * s, 0, Math.PI * 2);
      ctx.stroke();
    }
  } else if (g.kind === "resize") {
    if (g.handle && item.box) {
      const [x, y, w, h] = resizedBox(item.box, g.handle, g.delta);
      ctx.strokeRect(x * s, y * s, w * s, h * s);
    }
  } else if (g.kind === "turn") {
    const h = g.handle;
    if (isAngle(h)) {
      const start = g.key === "start_angle" ? g.degrees : h.start;
      const sweep = g.key === "sweep" ? g.degrees : h.sweep;
      const r = Math.hypot(h.x - h.cx, h.y - h.cy) || 1;
      const rad = (d: number): number => ((d - 90) * Math.PI) / 180;
      ctx.beginPath();
      ctx.arc(h.cx * s, h.cy * s, r * s, rad(start), rad(start + sweep), sweep < 0);
      ctx.stroke();
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      const end = g.key === "start_angle" ? start : start + sweep;
      ctx.moveTo(h.cx * s, h.cy * s);
      ctx.lineTo((h.cx + r * Math.sin((end * Math.PI) / 180)) * s, (h.cy - r * Math.cos((end * Math.PI) / 180)) * s);
      ctx.stroke();
    }
  }
  if ("guides" in g && g.guides) guides(ctx, g.guides, frame, s);
}

// What a gesture in progress sends on release, and what its preview draws.
// `g.moving`: every element it moves, none of which is a snapping target.
// Null for a handle of a shape the canvas does not know (the worker sends
// none such).
function gestureAt(frame: Frame, item: Target, g: Press | Dragging, x: number, y: number, free: boolean): Own | null {
  const dx = x - g.x, dy = y - g.y;
  const targets = moveTargets(frame.items, g.moving, frame.width, frame.height, frame.minor_radius,
                              free ? 0 : GRID_PERCENT);
  if (g.handle === null) {
    const snapped = free ? { dx: Math.round(dx), dy: Math.round(dy), guides: { x: [], y: [] } }
      : snapMove(item, dx, dy, targets, 4);
    return { kind: "move", part: "both", dx: snapped.dx, dy: snapped.dy, guides: snapped.guides };
  }
  const h = g.handle;
  // a point dragged snaps as a line's end does
  const pointMove = (): { dx: number; dy: number; guides: Guides } => (free ? { dx: Math.round(dx), dy: Math.round(dy), guides: { x: [], y: [] } }
    : snapMove({ box: [h.x, h.y, 0, 0] as Box, center: [h.x, h.y] as [number, number] }, dx, dy, targets, 4));
  if (isEnd(h)) {
    const snapped = pointMove();
    return { kind: "move", part: h.part, dx: snapped.dx, dy: snapped.dy, guides: snapped.guides };
  }
  if (isVertex(h)) {
    const snapped = pointMove();
    return { kind: "vertex", index: h.index, dx: snapped.dx, dy: snapped.dy, guides: snapped.guides, handle: h };
  }
  if (isSegment(h)) {
    const snapped = pointMove();
    return { kind: "add_vertex", after: h.after, x: h.x + snapped.dx, y: h.y + snapped.dy, handle: h };
  }
  if (isSize(h)) {
    if (h.key[0] === "radius") {
      const r0 = h.x - item.center[0];
      const to = free ? Math.round(r0 + dx) : snapLength(r0 + dx, frame.minor_radius, GRID_PERCENT);
      return { kind: "resize", key: h.key, delta: to - r0, to, handle: h };
    }
    let delta = resizeDelta(h, dx, dy);
    // a font's size is pixels of font, not of the box: it does not snap to the box grid
    if (!free && h.key[0] !== "font") {
      const extent = h.axis === "x" ? item.box[2] : item.box[3];
      delta = snapLength(extent + delta, frame.minor_radius, GRID_PERCENT) - extent;
    }
    return { kind: "resize", key: h.key, delta, handle: h };
  }
  if (!isAngle(h)) return null;
  // an arc's end: its angle about the centre
  let degrees = angleAt(h.cx, h.cy, x, y);
  if (!free) degrees = snapAngle(degrees);
  if (h.key === "sweep") degrees = nearestTurn(degrees - h.start, h.sweep);
  else degrees = nearestTurn(degrees, h.start);
  return { kind: "turn", key: h.key, degrees, handle: h };
}

function changed(gesture: Own): boolean {
  if (gesture.kind === "move" || gesture.kind === "vertex") return gesture.dx !== 0 || gesture.dy !== 0;
  if (gesture.kind === "resize") return gesture.delta !== 0;
  if (gesture.kind === "add_vertex") return true;
  return Math.abs(gesture.degrees - (gesture.key === "sweep" ? gesture.handle.sweep : gesture.handle.start)) >= 0.5;
}

// What a released gesture sends: the gesture without what only its preview
// needs (the handle, the guides, a radius's new value).
function sent(g: Own): AnyGesture {
  const preview: Preview = g;
  const { handle: _handle, guides: _guides, to: _to, ...rest } = preview;
  return rest;
}

const NO_LOCKS: ReadonlySet<string> = new Set();

/** The handles a press may take: a mirrored vertex is shown, never dragged. */
const pressable = (item: FrameItem): FrameItem => ({ ...item, handles: item.handles.filter((h) => !h.mirrored) });

export interface CanvasProps {
  /** The face as the worker drew it. */
  frame: Frame;
  selected: string | null;
  /** The elements added to the selection with Ctrl/Cmd/Shift. */
  extra?: string[];
  /** The face's blocks, for what a group carries. */
  tree?: Summary["tree"];
  /** The editor's outbox. */
  queue?: readonly Entry[];
  /** The picked point of the selected polygon, highlighted among its vertex handles. */
  vertex?: number | null;
  onPick: (id: string | null, additive: boolean) => void;
  /** A vertex handle clicked: its point is picked (null: the pick is dropped). */
  onVertex?: ((index: number | null) => void) | undefined;
  /** A gesture released: the ids it acts on, what to send, and what the canvas drew it from. */
  onDrag: (ids: string[], gesture: AnyGesture, shown: Pick<GestureEntry, "item" | "moving" | "preview">) => void;
  /** Screen (CSS) pixels per watch pixel; the frame was drawn at `frame.scale` and is shown at the zoom (that scale when absent). */
  zoom?: number;
  /** The watch drawn round the screen, at the frame's scale, with where the screen sits in it. */
  skin?: Skin | null;
  /** Elements locked in the editor (with what is inside a locked group): never picked, and neither they nor a selection holding one is dragged. */
  locked?: ReadonlySet<string>;
}

/**
 * The face, its selection and the drag gestures. Escape cancels a drag
 * under way, and goes no further (with none, the editor's own Escape
 * deselects).
 */
export function Canvas({ frame, selected, extra = [], tree = [], queue = [], vertex = null, onPick, onVertex, onDrag,
                         zoom = frame.scale, skin = null, locked = NO_LOCKS }: CanvasProps): VNode {
  const overlay = useRef<HTMLCanvasElement | null>(null);
  const [drag, setDragState] = useState<Drag | null>(null);     // a press, maybe a gesture
  // The handlers read the press from a ref: two pointer events can arrive
  // before the re-render the first one scheduled.
  const dragRef = useRef<Drag | null>(null);
  const setDrag = (value: Drag | null): void => { dragRef.current = value; setDragState(value); };
  const [prepared, setPrepared] = useState<Prepared | null>(null);  // the frame's layers, ready
  // an entered frame's layers are the element's alone, so nothing is redrawn from them: the ghost is only in the image
  const usable = prepared && prepared.version === frame.version && !frame.local ? prepared : null;

  useEffect(() => {
    if (frame.local) return;
    let live = true;
    prepare(frame).then((p) => { if (live) setPrepared(p); }, () => {});
    return () => { live = false; };
  }, [frame]);
  // the gestures this frame does not show yet; their moves, per element,
  // or null when one is not a move; and the frame's items where those
  // moves will put them, which every press and snap reads
  const waiting = useMemo(() => unshown(queue, frame.version), [queue, frame.version]);
  const moves = useMemo(() => offsets(waiting), [waiting]);
  const by: Offsets = moves || new Map();
  const seen: Frame = useMemo(() => ({ ...frame, items: shiftItems(frame.items, by) }), [frame, moves]);

  const item = seen.items.find((i) => i.id === selected);
  const others = seen.items.filter((i) => extra.includes(i.id));
  const live = dragging(drag) ? drag : null;
  const last = waiting[waiting.length - 1];
  // the frame a part's points are drawn in: its own angle, else the entered frame's; an element's is the screen's
  const angleOf = (one: Placed | undefined): number => (one && "angle" in one && typeof one.angle === "number" ? one.angle : frame.local ? frame.local.angle : 0);

  useEffect(() => {
    const c = overlay.current;
    if (!c) return;
    const s = frame.scale;
    c.width = frame.width * s; c.height = frame.height * s;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, c.width, c.height);
    const k = s / zoom;
    if (frame.local) drawLocalFrame(ctx, frame.local, frame, s, k);
    if (live) { drawPreview(ctx, frame, usable, live.item, live.moving, live.gesture, s, by, angleOf(live.item)); return; }
    if (last && !moves) {
      drawPreview(ctx, frame, usable, last.item, last.moving, last.preview, s, new Map(), angleOf(last.item));
      return;
    }
    if (moves && moves.size && usable) drawMoved(ctx, frame, usable, moves, s);
    if (!item) return;
    ctx.setLineDash([6 * k, 4 * k]);
    ctx.strokeStyle = ACCENT;
    ctx.lineWidth = 2 * k;
    for (const one of [item, ...others]) {
      const [x, y, w, h] = one.box;
      ctx.strokeRect(x * s - k, y * s - k, w * s + 2 * k, h * s + 2 * k);
    }
    // handles act on one element, so a selection of several shows none; a locked one has none to drag
    if ([item.id, ...extra].some((id) => locked.has(id))) return;
    if (!others.length) for (const hd of item.handles) drawHandle(ctx, hd, s, k, isVertex(hd) && !hd.mirrored && hd.index === vertex);
    const grip = moveHandle(seen.items, [item.id, ...extra], (GRIP + 2) / zoom);
    if (grip) drawGrip(ctx, grip.x, grip.y, s, k);
  }, [frame, seen, usable, selected, extra, live, waiting, zoom, vertex, locked]);

  // The pointer in device pixels (`x`, `y`), and on the screen (`sx`, `sy`).
  const point = (e: PointerEv): { x: number; y: number; sx: number; sy: number } => {
    const rect = e.currentTarget.getBoundingClientRect();
    const k = (frame.width * frame.scale) / (rect.width || frame.width * frame.scale);
    return { x: ((e.clientX - rect.left) * k) / frame.scale, y: ((e.clientY - rect.top) * k) / frame.scale,
             sx: e.clientX, sy: e.clientY };
  };

  // A press on a handle drags it (`handleAt`: inside a thin element it is
  // a move); on the move handle, the whole selection
  // (a group with its children); on an element that is itself selected,
  // the whole selection too, and if it turns out to be a click, just that
  // element. A press anywhere else, a selected group's member included,
  // selects what is under it and drags that. Ctrl/Cmd/Shift adds to the
  // selection.
  const down = (e: PointerEv): void => {
    if (e.button !== 0) return;
    const p = point(e);
    const chosen = [selected, ...extra].filter((id): id is string => id !== null);
    // a selection holding a locked element offers no handle and no grip: it is moved from Properties only
    const fixed = chosen.some((id) => locked.has(id));
    const grip = fixed ? null : moveHandle(seen.items, chosen, (GRIP + 2) / zoom);
    const onGrip = grip !== null && Math.hypot((grip.x - p.x) * zoom, (grip.y - p.y) * zoom) <= GRIP + 2;
    const handle = !fixed && !onGrip && item && !extra.length ? handleAt(pressable(item), p.x, p.y, zoom, HANDLE + 2) : null;
    const under = handle || onGrip ? null : pick(seen, usable, p.x, p.y, by, locked);
    if (!handle && !onGrip && (e.ctrlKey || e.metaKey || e.shiftKey)) {
      if (under) onPick(under, true);
      return;
    }
    let ids: string[], click: string | null = null;
    if (handle && item) ids = [item.id];
    else if (onGrip) ids = chosen;
    else if (under && chosen.includes(under) && !fixed) {
      ids = chosen;
      click = under;
    } else {
      if (under !== selected || extra.length) onPick(under, false);
      if (!under) return;
      ids = [under];
    }
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setDrag({ ids, moving: movedBy(tree, ids), click, handle: handle || null,
              x: p.x, y: p.y, sx: p.sx, sy: p.sy, gesture: null });
  };

  const move = (e: PointerEv): void => {
    const drag = dragRef.current;
    if (!drag) return;
    if (!drag.gesture && Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) < START) return;
    const target = drag.ids.length > 1 ? together(seen.items, drag.ids)
      : seen.items.find((i) => i.id === drag.ids[0]);
    if (!target) return;
    const p = point(e);
    const gesture = gestureAt(seen, target, drag, p.x, p.y, e.altKey);
    if (!gesture) return;
    setDrag({ ...drag, item: target, free: e.altKey, gesture });
  };

  const up = (): void => {
    const drag = dragRef.current;
    if (!drag) return;
    setDrag(null);
    if (!dragging(drag)) {
      // a click inside the selection: select what is under it
      if (drag.click && (drag.click !== selected || extra.length)) onPick(drag.click, false);
      // a click on a vertex picks it; on a segment's middle, adds a vertex there
      const h = drag.handle;
      if (h && isVertex(h) && onVertex) onVertex(h.index);
      else if (h && isSegment(h) && item) {
        const g: Own = { kind: "add_vertex", after: h.after, x: h.x, y: h.y, handle: h };
        onDrag(drag.ids, sent(g), { item, moving: drag.moving, preview: g });
      }
      return;
    }
    const g = drag.gesture;
    if (!changed(g)) return;
    if (g.kind === "vertex" && onVertex) onVertex(g.index);
    onDrag(drag.ids, sent(g), { item: drag.item, moving: drag.moving, preview: g });
  };

  useEffect(() => {
    // in the capture phase, ahead of the editor's shortcuts
    const onKey = (e: KeyboardEvent): void => {
      if (e.key !== "Escape" || !dragRef.current) return;
      setDrag(null);
      e.stopImmediatePropagation();
    };
    addEventListener("keydown", onKey, true);
    return () => removeEventListener("keydown", onKey, true);
  }, []);

  // the screen, and round it the skin when shown, all at the zoom
  const w = frame.width * zoom, h = frame.height * zoom;
  const at: [number, number] = skin ? [skin.x / skin.scale * zoom, skin.y / skin.scale * zoom] : [0, 0];
  const box: [number, number] = skin ? [skin.width / skin.scale * zoom, skin.height / skin.scale * zoom] : [w, h];
  const screen = `left:${at[0]}px;top:${at[1]}px;width:${w}px;height:${h}px`;
  const enteredId = frame.local ? seen.items.find((i) => !i.path && !i.drawn)?.id ?? null : null;
  return html`<div class=${"canvas" + (frame.local ? " entered" : "")} style=${`width:${box[0]}px;height:${box[1]}px`}>
    <img class="frame" src=${frame.frame} style=${screen} alt="the face on ${frame.device}" />
    ${skin ? html`<img class="skin" src=${skin.image} style=${`width:${box[0]}px;height:${box[1]}px`} alt="" />` : null}
    <canvas ref=${overlay} style=${screen}></canvas>
    <div class=${"hit" + (drag && drag.gesture ? " dragging" : "")} style=${screen}
         onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${() => setDrag(null)}></div>
    ${enteredId !== null ? html`<div class="entered-label" role="status" title="the parts of this element, in its own frame; the rest of the face is a ghost">in <code>${enteredId}</code> · Esc leaves</div>` : null}
    ${waiting.length ? html`<div class="saving">saving…</div>` : null}
    ${live ? html`<div class=${"drag-hint" + (live.free ? " free" : "")} role="status">${dragHint(live.gesture, live.free)}</div>` : null}
  </div>`;
}

// How long the face must stay unchanged before the strip draws it again.
export const STRIP_SETTLE_MS = 250;

/** What the strip draws each target at: the editor's view of the face. */
export interface StripView {
  /** The device shown on the canvas, marked in the strip. */
  device: string | null;
  style?: string;
  date?: string;
  asleep?: boolean;
  aod?: boolean;
  /** The time follows the clock. */
  now?: boolean;
  /** `HH:MM` or `HH:MM:SS`. */
  time?: string;
}

export interface StripProps {
  doc: Pick<Summary, "id" | "version" | "targets">;
  view: StripView;
  /** `slot:type,slot:type`: what each slot is drawn showing. */
  picks: string | null;
  onDevice: (device: string) => void;
}

/**
 * One small frame per target, the selected device marked; a click views it.
 * The thumbnails follow the face once it has been still for
 * `STRIP_SETTLE_MS`: long enough that a run of drags is not a run of
 * thumbnails per target. (An edit never waits on them: the worker answers
 * thumbnails last, so the settle is only this coalescing.)
 */
export function Strip({ doc, view, picks, onDevice }: StripProps): VNode | null {
  const [version, setVersion] = useState(doc.version);
  useEffect(() => { setVersion(doc.version); }, [doc.id]);
  useEffect(() => {
    if (version === doc.version) return;
    const timer = setTimeout(() => setVersion(doc.version), STRIP_SETTLE_MS);
    return () => clearTimeout(timer);
  }, [doc.version]);
  if (doc.targets.length < 2) return null;
  const args = (device: string) => ({
    id: doc.id, device, v: version, style: view.style, date: view.date, asleep: view.asleep, aod: view.aod, picks,
    // following the clock, the thumbnails change once a minute, not every second
    time: view.now && view.time ? view.time.slice(0, 5) : view.time,
  });
  return html`<div class="strip">
    ${doc.targets.map((t) => html`<button class=${t === view.device ? "on" : ""} title=${t} onClick=${() => onDevice(t)}>
      <${WorkerImage} op="thumbnail" args=${args(t)} alt=${t} /><span>${t}</span></button>`)}
  </div>`;
}
