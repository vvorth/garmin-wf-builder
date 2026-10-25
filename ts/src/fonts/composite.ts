// Glyphs the icon font does not have, drawn here and baked as its own. A
// composite borrows a base glyph from the font (its advance, and the ink
// box it fills), and draws its own outline in that box, so it bakes,
// measures and draws like any other glyph of the font. Its code point sits
// in the Supplementary Private Use Area-B, which the icon font leaves
// empty.
//
// The solar level steps are a disc with a lightning bolt cut out. From
// `SOLAR_ARCS_FROM_PX` across, eight arcs around the disc light up
// clockwise from 12 o'clock, one per step; smaller, every step is the same
// static star (eight triangular teeth around the disc), because arcs a
// pixel or two thick do not read. The arcs and the teeth each form one
// orbit of the square's symmetries (rotations by 90 degrees and the four
// mirrors), and the glyph is centred on the pixel grid, so every arc, and
// every tooth, gets the same pixels, flipped or turned.
import type { PathCommand } from "./raster.ts";

/** A composite's outline, and the box its pixels are cut from when it is upright. */
export interface CompositeOutline {
  commands: PathCommand[];
  /** `[x0, y0, x1, y1]`, whole output pixels from the pen, holding all the ink. */
  frame: [number, number, number, number];
}

export interface Composite {
  /** The icon font glyph it borrows its advance and ink box from. */
  readonly base: string;
  /** The outline in the base's ink box (`[x0, y0, x1, y1]`, in pixels, y down); `pixel` is one output pixel in those units. */
  outline(box: readonly [number, number, number, number], pixel: number): CompositeOutline;
}

/** `md-lightning_bolt_circle`: the solar steps' advance and ink box. */
const BOLT_CIRCLE = "\u{F0820}";
/** The first solar step's code point; the step with `k` of 8 arcs lit is `SOLAR_FIRST + k`. */
export const SOLAR_FIRST = 0x10f000;
/** The narrowest solar step, in output pixels across, that draws arcs; anything smaller draws the static star. */
export const SOLAR_ARCS_FROM_PX = 22;

type Point = [number, number];

/** The point at `angle` radians clockwise from 12 o'clock on a circle of `r`, in the unit design (radius 1, y down). */
const at = (r: number, angle: number): Point => [r * Math.sin(angle), -r * Math.cos(angle)];

/** Twice the polygon's signed area; positive turns clockwise on screen (y down). */
function shoelace(ps: readonly Point[]): number {
  let sum = 0;
  ps.forEach(([x0, y0], i) => {
    const [x1, y1] = ps[(i + 1) % ps.length]!;
    sum += x0 * y1 - x1 * y0;
  });
  return sum;
}

/** The polygon turning clockwise (`turn` 1, ink) or the other way (`turn` -1, a hole under nonzero winding). */
function turning(ps: Point[], turn: number): Point[] {
  return Math.sign(shoelace(ps)) === turn ? ps : [...ps].reverse();
}

/** A circle of `r`, as a polygon fine enough at any icon size. */
const disc = (r: number): Point[] => Array.from({ length: 128 }, (_, i) => at(r, (i / 128) * 2 * Math.PI));

/** The ring between `inner` and `outer` from `a0` to `a1` radians clockwise from 12. */
function sector(inner: number, outer: number, a0: number, a1: number): Point[] {
  const n = 24, ps: Point[] = [];
  for (let i = 0; i <= n; i++) ps.push(at(outer, a0 + ((a1 - a0) * i) / n));
  for (let i = n; i >= 0; i--) ps.push(at(inner, a0 + ((a1 - a0) * i) / n));
  return ps;
}

/** A lightning bolt `height` tall about the centre; `stroke` is its width as a share of its half-width. */
function bolt(height: number, stroke: number): Point[] {
  const hw = 0.38;
  return ([[0.12, -0.5], [-hw, 0.05], [-hw + 2 * hw * stroke, 0.05], [-0.12, 0.5], [hw, -0.05], [hw - 2 * hw * stroke, -0.05]] as Point[])
    .map(([x, y]): Point => [x * height, y * height]);
}

const DEGREE = Math.PI / 180;

/** The dynamic step: the carved disc, and the first `lit` of eight arcs, each an eighth of the turn less a 10 degree gap. */
function arcsStep(lit: number): Point[][] {
  const inkParts = Array.from({ length: lit }, (_, k) => sector(0.78, 1, (k * 45 + 5) * DEGREE, ((k + 1) * 45 - 5) * DEGREE));
  return [turning(disc(0.68), 1), turning(bolt(0.68 * 1.65, 0.5), -1), ...inkParts.map((p) => turning(p, 1))];
}

/**
 * The static star: the carved disc and eight teeth whose bases meet edge to
 * edge on it. The teeth point at 22.5 degrees past each axis and diagonal,
 * not at them, so all eight are mirror images or turns of one another; the
 * whole star is then scaled until its widest tips touch the box, as the
 * arcs do.
 */
function starStep(): Point[][] {
  const r = 0.64, w = (2 * Math.PI) / 8, scale = 1 / Math.cos(22.5 * DEGREE);
  const teeth = Array.from({ length: 8 }, (_, k): Point[] => {
    const a = (22.5 + k * 45) * DEGREE;
    return [...Array.from({ length: 9 }, (_, i) => at(r * 0.96, a - w / 2 + (w * i) / 8)), at(1, a)];
  });
  return [turning(disc(r), 1), turning(bolt(r * 1.65, 0.5), -1), ...teeth.map((t) => turning(t, 1))]
    .map((p) => p.map(([x, y]): Point => [x * scale, y * scale]));
}

/** The solar step with `lit` of 8 arcs. */
function solarStep(lit: number): Composite {
  return {
    base: BOLT_CIRCLE,
    outline([x0, y0, x1, y1], pixel) {
      // A whole number of pixels across, its edges on pixel boundaries from the pen, so its centre is a pixel's corner or centre.
      const across = Math.max(1, Math.round((x1 - x0 + y1 - y0) / 2 / pixel));
      const snap = (c: number): number => Math.round(c / pixel - across / 2) * pixel + (across * pixel) / 2;
      const cx = snap((x0 + x1) / 2), cy = snap((y0 + y1) / 2), radius = (across * pixel) / 2;
      const parts = across >= SOLAR_ARCS_FROM_PX ? arcsStep(lit) : starStep();
      const commands = parts.flatMap((ps): PathCommand[] => [
        ...ps.map(([x, y], i): PathCommand => ({ type: i === 0 ? "M" : "L", x: cx + x * radius, y: cy + y * radius })),
        { type: "Z" },
      ]);
      return { commands, frame: [cx - radius, cy - radius, cx + radius, cy + radius] };
    },
  };
}

/** Every composite, by its code point. */
export const COMPOSITES: ReadonlyMap<string, Composite> = new Map(
  Array.from({ length: 9 }, (_, k): [string, Composite] => [String.fromCodePoint(SOLAR_FIRST + k), solarStep(k)]),
);
