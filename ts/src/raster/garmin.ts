// Garmin's own rasterisation, where a simulator capture has pinned it down
// (docs/research/probes/garmin-raster/): each rule lights the device
// pixels the watch lights, and a pixel is painted as an s x s block. The
// rules are exact on the MIP verification devices (fenix8solar47mm,
// fenix8solar51mm, fr955); the AMOLED fenix847mm anti-aliases its edges
// instead, which they do not model.
import { type Image, polygon, rectangle, type Rgb } from "./pillow.ts";

/**
 * Whether `(x, y)`, from the centre, is inside Garmin's disc of radius
 * `radius`: x² + y² <= radius², but for the right, top and bottom axis
 * points (the left one stays in).
 */
function inDisc(x: number, y: number, radius: number): boolean {
  return x * x + y * y <= radius * radius && !(y === 0 && x === radius) && !(x === 0 && Math.abs(y) === radius);
}

/** Every pixel within `extent` of `(cx, cy)` that `lit` says the watch lights, painted in row runs. */
function paint(im: Image, cx: number, cy: number, extent: number, lit: (x: number, y: number) => boolean, color: Rgb, s: number): void {
  for (let y = -extent; y <= extent; y++) {
    for (let x = -extent; x <= extent; x++) {
      if (!lit(x, y)) continue;
      let end = x;
      while (end + 1 <= extent && lit(end + 1, y)) end++;
      rectangle(im, [(cx + x) * s, (cy + y) * s, (cx + end + 1) * s - 1, (cy + y + 1) * s - 1], { fill: color });
      x = end;
    }
  }
}

// A Float coordinate is truncated toward zero, as Monkey C's toNumber does: exact
// on a radial pattern's runtime-rotated polygons and lines.
const whole = (v: number): number => Math.trunc(v);

/** `dc.fillCircle`: Garmin's disc. Exact on radii 1-12. */
export function fillCircle(im: Image, cx: number, cy: number, r: number, color: Rgb, s: number): void {
  const radius = whole(r);
  paint(im, whole(cx), whole(cy), radius, (x, y) => inDisc(x, y, radius), color, s);
}

/** `dc.drawCircle` with a `pen` px pen: the disc of radius r + pen/2 less the disc of r - pen/2. Exact on radii 8 and 9 at pens 1-4. */
export function drawCircle(im: Image, cx: number, cy: number, r: number, pen: number, color: Rgb, s: number): void {
  const radius = whole(r), half = Math.max(1, pen) / 2;
  paint(im, whole(cx), whole(cy), Math.ceil(radius + half),
    (x, y) => inDisc(x, y, radius + half) && !inDisc(x, y, radius - half), color, s);
}

/** Whether `(x, y)` is inside Garmin's ellipse of semi-axes `rx`, `ry`: `inDisc` stretched, the same axis points left out. */
function inEllipse(x: number, y: number, rx: number, ry: number): boolean {
  if (rx <= 0 || ry <= 0) return false;
  return (x * x) / (rx * rx) + (y * y) / (ry * ry) <= 1 && !(y === 0 && x === rx) && !(x === 0 && Math.abs(y) === ry);
}

/** `dc.fillEllipse`. */
export function fillEllipse(im: Image, cx: number, cy: number, rx: number, ry: number, color: Rgb, s: number): void {
  const [a, b] = [whole(rx), whole(ry)];
  paint(im, whole(cx), whole(cy), Math.max(a, b), (x, y) => inEllipse(x, y, a, b), color, s);
}

/** `dc.drawEllipse` with a `pen` px pen: the ellipse grown by pen/2 less the one shrunk by it. */
export function drawEllipse(im: Image, cx: number, cy: number, rx: number, ry: number, pen: number, color: Rgb, s: number): void {
  const [a, b] = [whole(rx), whole(ry)], half = Math.max(1, pen) / 2;
  paint(im, whole(cx), whole(cy), Math.ceil(Math.max(a, b) + half),
    (x, y) => inEllipse(x, y, a + half, b + half) && !inEllipse(x, y, a - half, b - half), color, s);
}

/** Where a `p` px pen's square brush reaches either side of a 1 px path: `[before, after]`, leaning left and up. */
const brush = (pen: number): [number, number] => {
  const p = Math.max(1, Math.trunc(pen));
  return [Math.floor(p / 2), p - 1 - Math.floor(p / 2)];
};

/** `dc.drawRectangle` with a `pen` px pen: the brush stamped along the 1 px outline of x..x+w-1, y..y+h-1. Exact at pens 1-4. */
export function drawRectangle(im: Image, x: number, y: number, w: number, h: number, pen: number, color: Rgb, s: number): void {
  [x, y, w, h] = [whole(x), whole(y), whole(w), whole(h)];
  const [a, b] = brush(pen);
  const [l, t, r, btm] = [x - a, y - a, x + w - 1 + b, y + h - 1 + b];
  const fill = (x0: number, y0: number, x1: number, y1: number): void => {
    if (x1 >= x0 && y1 >= y0) rectangle(im, [x0 * s, y0 * s, (x1 + 1) * s - 1, (y1 + 1) * s - 1], { fill: color });
  };
  // The hole is what no edge's brush reaches: inside x + b .. x + w - 1 - a, exclusive.
  const [hl, ht, hr, hb] = [x + b + 1, y + b + 1, x + w - 2 - a, y + h - 2 - a];
  if (hl > hr || ht > hb) return fill(l, t, r, btm);
  fill(l, t, r, ht - 1);
  fill(l, hb + 1, r, btm);
  fill(l, ht, hl - 1, hb);
  fill(hr + 1, ht, r, hb);
}

/**
 * `dc.fillRoundedRectangle`: the pixels whose centre lies in the rectangle
 * x..x+w, y..y+h with corners of radius r. Exact at r 2, 3 and 5 on 20x14
 * and 21x15.
 */
export function fillRoundedRectangle(im: Image, x: number, y: number, w: number, h: number, r: number, color: Rgb, s: number): void {
  [x, y, w, h] = [whole(x), whole(y), whole(w), whole(h)];
  // ponytail: a radius past half the short side is clamped to it, as Pillow does; unprobed
  const radius = Math.max(0, Math.min(r, w / 2, h / 2));
  for (let py = y; py < y + h; py++) {
    // Each row's inset from the corner arc it crosses, if any: centres at x + radius, y + radius and their mirrors.
    const qy = py + 0.5;
    const dy = qy < y + radius ? y + radius - qy : qy > y + h - radius ? qy - (y + h - radius) : 0;
    const inset = dy > 0 ? radius - Math.sqrt(Math.max(0, radius * radius - dy * dy)) : 0;
    // A pixel is in when its centre px + 0.5 >= x + inset, and px + 0.5 <= x + w - inset.
    const left = Math.ceil(x + inset - 0.5), right = Math.floor(x + w - inset - 0.5);
    if (right >= left) rectangle(im, [left * s, py * s, (right + 1) * s - 1, (py + 1) * s - 1], { fill: color });
  }
}

/**
 * `dc.drawRoundedRectangle` with a `pen` px pen: drawRectangle's stroke,
 * with each corner square replaced by drawCircle's ring about the corner's
 * centre, its axis exceptions included. The right corners' squares take in
 * their centre column, the left ones' do not. Exact at a 2 px pen on radii 2,
 * 3 and 5 at 20x14 and 21x15; other pens are unprobed.
 */
export function drawRoundedRectangle(im: Image, x: number, y: number, w: number, h: number, r: number, pen: number, color: Rgb, s: number): void {
  [x, y, w, h] = [whole(x), whole(y), whole(w), whole(h)];
  const radius = whole(Math.max(0, Math.min(r, w / 2, h / 2)));
  const [a, b] = brush(pen);
  const half = Math.max(1, pen) / 2;
  const cl = x + radius, cr = x + w - 1 - radius, ct = y + radius, cb = y + h - 1 - radius;
  const ring = (dx: number, dy: number): boolean => inDisc(dx, dy, radius + half) && !inDisc(dx, dy, radius - half);
  const lit = (px: number, py: number): boolean => {
    const zx = px < cl ? cl : px >= cr ? cr : null;
    const zy = py < ct ? ct : py > cb ? cb : null;
    if (zx !== null && zy !== null) return ring(px - zx, py - zy);
    const onH = (py >= y - a && py <= y + b) || (py >= y + h - 1 - a && py <= y + h - 1 + b);
    const onV = (px >= x - a && px <= x + b) || (px >= x + w - 1 - a && px <= x + w - 1 + b);
    return (onH && px >= x - a && px <= x + w - 1 + b) || (onV && py >= y - a && py <= y + h - 1 + b);
  };
  for (let py = y - pen - 1; py <= y + h + pen; py++) for (let px = x - pen - 1; px <= x + w + pen; px++) {
    if (lit(px, py)) rectangle(im, [px * s, py * s, (px + 1) * s - 1, (py + 1) * s - 1], { fill: color });
  }
}

/**
 * `dc.drawLine` with a `pen` px pen: the pixels whose centre lies in the
 * segment swept by a pen x pen square centred on it. A pixel on the swept
 * outline counts when that edge faces left, or straight up. Exact over 50
 * lines (pens 1-4, every direction) and over a radial pattern's lines,
 * whose Float end points are truncated.
 */
export function drawLine(im: Image, x0: number, y0: number, x1: number, y1: number, pen: number, color: Rgb, s: number): void {
  [x0, y0, x1, y1] = [whole(x0), whole(y0), whole(x1), whole(y1)];
  const h = Math.max(1, Math.trunc(pen)) / 2;
  const corners: [number, number][] = [];
  for (const [ex, ey] of [[x0, y0], [x1, y1]] as const) for (const dx of [-h, h]) for (const dy of [-h, h]) corners.push([ex + dx, ey + dy]);
  const hull = convexHull(corners);
  // Each edge with the inside on its left; its outward normal is (dy, -dx).
  const edges = hull.map((a, i) => {
    const b = hull[(i + 1) % hull.length]!;
    const [nx, ny] = [b[1] - a[1], a[0] - b[0]];
    return { a, b, keep: nx < 0 || (nx === 0 && ny < 0) };
  });
  const inside = (x: number, y: number): boolean => edges.every(({ a, b, keep }) => {
    const c = cross(a, b, [x, y]);
    return c > 0 || (c === 0 && keep);
  });
  const [left, right] = [Math.floor(Math.min(x0, x1) - h), Math.ceil(Math.max(x0, x1) + h)];
  for (let y = Math.floor(Math.min(y0, y1) - h); y <= Math.ceil(Math.max(y0, y1) + h); y++) {
    for (let x = left; x <= right; x++) {
      if (!inside(x, y)) continue;
      let end = x;
      while (end + 1 <= right && inside(end + 1, y)) end++;
      rectangle(im, [x * s, y * s, (end + 1) * s - 1, (y + 1) * s - 1], { fill: color });
      x = end;
    }
  }
}

type Point = readonly [number, number];
const cross = (o: Point, a: Point, b: Point): number => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);

/** The convex hull of `points`, counter-clockwise on screen axes (inside on each edge's left), no collinear points. */
function convexHull(points: Point[]): Point[] {
  const sorted = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const half = (list: Point[]): Point[] => {
    const out: Point[] = [];
    for (const p of list) {
      while (out.length >= 2 && cross(out[out.length - 2]!, out[out.length - 1]!, p) <= 0) out.pop();
      out.push(p);
    }
    return out.slice(0, -1);
  };
  return [...half(sorted), ...half([...sorted].reverse())];
}

/**
 * `dc.fillPolygon`: Pillow's scanline fill, and every edge drawn as a 1 px
 * `drawLine`, which lights the right and bottom edges Pillow leaves out.
 * Exact over six shapes (triangles, a quad, a thin one, a sliver) and a
 * radial pattern's runtime-rotated ones.
 */
export function fillPolygon(im: Image, points: readonly (readonly [number, number])[], color: Rgb, s: number): void {
  polygon(im, points.map(([x, y]): [number, number] => [x * s, y * s]), color);
  points.forEach(([x, y], i) => {
    const [nx, ny] = points[(i + 1) % points.length]!;
    drawLine(im, x, y, nx, ny, 1, color, s);
  });
}

/**
 * `dc.drawArc` as the barrel calls it (`[start, end, clockwise]` in Garmin's
 * degrees, counter-clockwise from 3 o'clock): `drawCircle`'s ring of radius
 * r - 1/2 (an odd pen) or r (an even one), cut to the pixels whose angle
 * from the centre lies in the span, both ends included. Within 0-5 pixels a
 * shape, all at the ends, over pens 1-3, radii 14-120 and odd starts and
 * sweeps.
 */
export function drawArc(im: Image, cx: number, cy: number, r: number, pen: number, [start, end, clockwise]: [number, number, boolean], color: Rgb, s: number): void {
  // An odd pen's ring is centred half a pixel in, an even pen's on the radius itself.
  const pens = Math.max(1, Math.trunc(pen)), radius = whole(r) - (pens % 2 === 0 ? 0 : 0.5), half = pens / 2;
  // The span counter-clockwise from `lo`, `length` degrees; start == end is the whole circle.
  const lo = clockwise ? end : start;
  const length = ((((clockwise ? start - end : end - start) % 360) + 360) % 360) || 360;
  const inSpan = (x: number, y: number): boolean => {
    if (length === 360) return true;
    const theta = (Math.atan2(-y, x) * 180) / Math.PI;
    return ((((theta - lo) % 360) + 360) % 360) <= length;
  };
  paint(im, whole(cx), whole(cy), Math.ceil(radius + half),
    (x, y) => inDisc(x, y, radius + half) && !inDisc(x, y, radius - half) && inSpan(x, y), color, s);
}
