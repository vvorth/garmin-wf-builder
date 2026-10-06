// Garmin's own rasterisation, where a simulator capture has pinned it down
// (docs/research/probes/garmin-raster/): each rule lights the device
// pixels the watch lights, and a pixel is painted as an s x s block. The
// rules are exact on the MIP verification devices (fenix8solar47mm,
// fenix8solar51mm, fr955); the AMOLED fenix847mm anti-aliases its edges
// instead, which they do not model.
import { type Image, rectangle, type Rgb } from "./pillow.ts";

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

// ponytail: a Float argument is truncated, as Monkey C's toNumber does; unverified, the probe draws whole pixels only
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
