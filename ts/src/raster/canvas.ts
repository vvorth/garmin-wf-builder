// What the editor's canvas (`ts/app/canvas.js`) draws with: the preview's
// own rasteriser, and the frame's layers moved, inked and dragged. The
// studio server bundles this module for the page (`/dist/raster.js`), so
// the browser draws with the very code the preview does.
import { drawProgress, drawSpan } from "../draw/barrel.ts";
import { drawOps, image, type JsonNum, type JsonOp, type Tile, unpackTiles } from "./pillow.ts";

export { composite, drawOps, image } from "./pillow.ts";

const num = (n: JsonNum): number => (typeof n === "object" ? n.value + n.add : n);

/**
 * The frame's packed tiles (`{data: base64, index}`), inflated with the
 * platform's own `DecompressionStream` (zlib is its "deflate").
 */
export async function inflateTiles(packed: { data: string; index: Parameters<typeof unpackTiles>[1] }): Promise<Record<string, Tile>> {
  const raw = Uint8Array.from(atob(packed.data), (c) => c.charCodeAt(0));
  if (raw.length === 0) return {};
  const stream = new Blob([raw]).stream().pipeThrough(new DecompressionStream("deflate"));
  return unpackTiles(new Uint8Array(await new Response(stream).arrayBuffer()), packed.index);
}

// Which numbers of each op are x and which are y, by the `Dc` call's own
// signature: what moving an element by (dx, dy) device pixels changes.
const XY = new Set([
  "fillRectangle", "drawRectangle", "fillRoundedRectangle", "drawRoundedRectangle",
  "fillCircle", "drawCircle", "fillEllipse", "drawEllipse",
]);

const shifted = (n: JsonNum, d: number): JsonNum => (typeof n === "object" ? { ...n, add: n.add + d } : n + d);

/** `ops` moved by whole device pixels: what the server draws once the element's position has moved that far. */
export function translateOps(ops: readonly JsonOp[], dx: number, dy: number): JsonOp[] {
  return ops.map((op) => {
    const name = op.op;
    if (name === "fillPolygon") return { ...op, points: (op["points"] as [number, number][]).map(([x, y]) => [x + dx, y + dy]) };
    if (name === "arc") return { ...op, cx: shifted(op["cx"] as JsonNum, dx), cy: shifted(op["cy"] as JsonNum, dy) };
    if (name === "text" || name === "glyph") return { ...op, x: shifted(op["x"] as JsonNum, dx), y: shifted(op["y"] as JsonNum, dy) };
    const a = op["args"] as JsonNum[];
    if (name === "drawLine") return { ...op, args: [shifted(a[0]!, dx), shifted(a[1]!, dy), shifted(a[2]!, dx), shifted(a[3]!, dy)] };
    if (XY.has(name)) return { ...op, args: [shifted(a[0]!, dx), shifted(a[1]!, dy), ...a.slice(2)] };
    return op;
  });
}

/**
 * Where a layer's ops leave ink: drawn on black and on white, a pixel is
 * ink where the grounds' difference, as luma, falls short of 255 -- the
 * coverage `src/draw/layers.ts's matte` takes (Pillow's "RGB" to "L").
 * `box` is in frame pixels (exclusive ends), `mask` one byte a pixel over it.
 */
export function inkOf(ops: readonly JsonOp[], tiles: Record<string, Tile>, width: number, height: number, scale: number): { box: [number, number, number, number] | null; mask: Uint8Array } {
  const black = image(width, height, [0, 0, 0]), white = image(width, height, [255, 255, 255]);
  drawOps(black, ops, tiles, scale);
  drawOps(white, ops, tiles, scale);
  let x0 = width, y0 = height, x1 = -1, y1 = -1;
  const full = new Uint8Array(width * height);
  for (let i = 0, p = 0; p < full.length; i += 4, p++) {
    const dr = Math.max(0, white.data[i]! - black.data[i]!);
    const dg = Math.max(0, white.data[i + 1]! - black.data[i + 1]!);
    const db = Math.max(0, white.data[i + 2]! - black.data[i + 2]!);
    if (((dr * 19595 + dg * 38470 + db * 7471 + 0x8000) >> 16) < 255) {
      full[p] = 1;
      const x = p % width, y = (p - x) / width;
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }
  }
  if (x1 < 0) return { box: null, mask: new Uint8Array(0) };
  const w = x1 - x0 + 1, mask = new Uint8Array(w * (y1 - y0 + 1));
  for (let y = y0; y <= y1; y++) mask.set(full.subarray(y * width + x0, y * width + x1 + 1), (y - y0) * w);
  return { box: [x0, y0, x1 + 1, y1 + 1], mask };
}

/** A live handle as the server's `handles` sends it: the constants a size moves, or the angle constant it sets. */
export type Live = { consts: Record<string, number>; angle?: undefined } | { consts?: undefined; angle: string };

/**
 * `ops` as they will be once a live handle has been dragged: `delta`
 * device pixels of extent for a size handle, `degrees` (12 o'clock,
 * clockwise) for an angle. An arc whose angles moved has its `drawArc`
 * call worked out again, as `drawSpan` does.
 */
export function liveOps(ops: readonly JsonOp[], live: Live, { delta = 0, degrees = 0 } = {}): JsonOp[] {
  let set: (n: unknown) => unknown;
  if (live.consts) {
    const consts = live.consts;
    set = (n) => (n !== null && typeof n === "object" && (n as { const: string }).const in consts
      ? { ...n, add: (n as { add: number }).add + consts[(n as { const: string }).const]! * delta } : n);
  } else {
    const angle = live.angle;
    const value = angle.endsWith("_START") ? (((90 - degrees) % 360) + 360) % 360 : degrees;
    set = (n) => (n !== null && typeof n === "object" && (n as { const: string }).const === angle ? { ...n, value, add: 0 } : n);
  }
  const walk = (x: unknown): unknown => (Array.isArray(x) ? x.map(walk)
    : x && typeof x === "object" && !("const" in x) ? Object.fromEntries(Object.entries(x).map(([k, v]) => [k, walk(v)]))
    : set(x));
  return ops.map((op) => {
    const out = walk(op) as JsonOp;
    if (op.op === "arc" && (out["start"] !== op["start"] || out["sweep"] !== op["sweep"])) {
      // a gauge's fill is its fraction of the sweep (`drawProgress`)
      const start = num(out["start"] as JsonNum), sweep = num(out["sweep"] as JsonNum);
      out["call"] = "fraction" in op ? drawProgress(start, sweep, op["fraction"] as number) : drawSpan(start, sweep);
    }
    return out;
  });
}
