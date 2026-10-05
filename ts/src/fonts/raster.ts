// A deterministic coverage rasteriser: a path's outline, flattened to line
// segments, filled with the exact area each pixel it covers (the signed-area
// accumulation of font-rs and stb_truetype), then clamped, which fills by
// nonzero winding for the outlines fonts hold. Plain double arithmetic
// throughout, so the same path gives the same bytes in every browser and in
// Node; no platform canvas is involved.

/** One drawing command, in pixel coordinates, y down. */
export type PathCommand =
  | { type: "M"; x: number; y: number }
  | { type: "L"; x: number; y: number }
  | { type: "Q"; x1: number; y1: number; x: number; y: number }
  | { type: "C"; x1: number; y1: number; x2: number; y2: number; x: number; y: number }
  | { type: "Z" };

/** How far a flattened curve may stray from the true one, in pixels. */
const TOLERANCE = 0.05;

type Segment = [number, number, number, number];

/** The path as closed polylines' segments. */
export function flatten(commands: readonly PathCommand[]): Segment[] {
  const out: Segment[] = [];
  let sx = 0, sy = 0, cx = 0, cy = 0, open = false;
  const line = (x: number, y: number): void => {
    if (x !== cx || y !== cy) out.push([cx, cy, x, y]);
    cx = x;
    cy = y;
  };
  const close = (): void => {
    if (open) line(sx, sy);
    open = false;
  };
  for (const c of commands) {
    if (c.type === "M") {
      close();
      sx = cx = c.x;
      sy = cy = c.y;
      open = true;
    } else if (c.type === "L") {
      line(c.x, c.y);
    } else if (c.type === "Q") {
      const dd = Math.hypot(cx - 2 * c.x1 + c.x, cy - 2 * c.y1 + c.y);
      const n = Math.max(1, Math.ceil(Math.sqrt(dd / (4 * TOLERANCE))));
      const x0 = cx, y0 = cy;
      for (let i = 1; i <= n; i++) {
        const t = i / n, u = 1 - t;
        line(u * u * x0 + 2 * u * t * c.x1 + t * t * c.x, u * u * y0 + 2 * u * t * c.y1 + t * t * c.y);
      }
    } else if (c.type === "C") {
      const dd = Math.max(Math.hypot(cx - 2 * c.x1 + c.x2, cy - 2 * c.y1 + c.y2), Math.hypot(c.x1 - 2 * c.x2 + c.x, c.y1 - 2 * c.y2 + c.y));
      const n = Math.max(1, Math.ceil(Math.sqrt((3 * dd) / (4 * TOLERANCE))));
      const x0 = cx, y0 = cy;
      for (let i = 1; i <= n; i++) {
        const t = i / n, u = 1 - t;
        line(u * u * u * x0 + 3 * u * u * t * c.x1 + 3 * u * t * t * c.x2 + t * t * t * c.x,
          u * u * u * y0 + 3 * u * u * t * c.y1 + 3 * u * t * t * c.y2 + t * t * t * c.y);
      }
    } else {
      close();
    }
  }
  close();
  return out;
}

/** The segments' bounds, `[minX, minY, maxX, maxY]`, or `null` for none. */
export function bounds(segments: readonly Segment[]): [number, number, number, number] | null {
  if (segments.length === 0) return null;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [ax, ay, bx, by] of segments) {
    x0 = Math.min(x0, ax, bx);
    y0 = Math.min(y0, ay, by);
    x1 = Math.max(x1, ax, bx);
    y1 = Math.max(y1, ay, by);
  }
  return [x0, y0, x1, y1];
}

/**
 * Fill `segments`, offset by `(-originX, -originY)`, into a `width` x
 * `height` coverage image, one byte a pixel (0..255, rounded). Every
 * segment must lie inside the image, at least a pixel from its right edge.
 */
export function rasterise(segments: readonly Segment[], originX: number, originY: number, width: number, height: number): Uint8Array {
  const acc = new Float64Array(width * height + 1);
  for (const [ax, ay, bx, by] of segments) {
    let x0 = ax - originX, y0 = ay - originY, x1 = bx - originX, y1 = by - originY;
    if (y0 === y1) continue;
    let dir = 1;
    if (y0 > y1) {
      dir = -1;
      [x0, y0, x1, y1] = [x1, y1, x0, y0];
    }
    const dxdy = (x1 - x0) / (y1 - y0);
    let x = x0;
    if (y0 < 0) {
      x -= y0 * dxdy;
      y0 = 0;
    }
    const yEnd = Math.min(height, y1);
    for (let y = Math.floor(y0); y < Math.ceil(yEnd); y++) {
      const row = y * width;
      const dy = Math.min(y + 1, yEnd) - Math.max(y, y0);
      const xNext = x + dxdy * dy;
      const d = dy * dir;
      const [l, r] = x < xNext ? [x, xNext] : [xNext, x];
      const lFloor = Math.floor(l), rCeil = Math.ceil(r);
      if (rCeil <= lFloor + 1) {
        const mid = 0.5 * (x + xNext) - lFloor;
        acc[row + lFloor]! += d - d * mid;
        acc[row + lFloor + 1]! += d * mid;
      } else {
        const s = 1 / (r - l);
        const lf = l - lFloor;
        const a0 = 0.5 * s * (1 - lf) * (1 - lf);
        const rf = r - rCeil + 1;
        const am = 0.5 * s * rf * rf;
        acc[row + lFloor]! += d * a0;
        if (rCeil === lFloor + 2) {
          acc[row + lFloor + 1]! += d * (1 - a0 - am);
        } else {
          const a1 = s * (1.5 - lf);
          acc[row + lFloor + 1]! += d * (a1 - a0);
          for (let xi = lFloor + 2; xi < rCeil - 1; xi++) acc[row + xi]! += d * s;
          const a2 = a1 + (rCeil - lFloor - 3) * s;
          acc[row + rCeil - 1]! += d * (1 - a2 - am);
        }
        acc[row + rCeil]! += d * am;
      }
      x = xNext;
    }
  }
  const out = new Uint8Array(width * height);
  let sum = 0;
  for (let i = 0; i < width * height; i++) {
    if (i % width === 0) sum = 0; // each row's areas sum to nothing: start every row clean
    sum += acc[i]!;
    out[i] = Math.round(Math.min(1, Math.abs(sum)) * 255);
  }
  return out;
}
