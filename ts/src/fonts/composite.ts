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
//
// Body Battery is a head and shoulders inside a tapering gauge, the outline
// of the watch's own icon, which no glyph in the font has; like the solar
// arcs, its gauge's segments merge into one band when small.
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

/** Body Battery's code point. */
export const BODY_BATTERY = 0x10f010;
/** The narrowest Body Battery, in output pixels across, whose gauge is drawn in segments; smaller, it is one band. */
export const BODY_BATTERY_SEGMENTS_FROM_PX = 22;

/** The top half of an ellipse about `(cx, cy)`, closed along its axis. */
function dome(cx: number, cy: number, rx: number, ry: number): Point[] {
  const n = 48;
  return Array.from({ length: n + 1 }, (_, i): Point => {
    const a = Math.PI + (Math.PI * i) / n;
    return [cx + rx * Math.cos(a), cy + ry * Math.sin(a)];
  });
}

/** `points` moved by `(dx, dy)`. */
const moved = (points: Point[], dx: number, dy: number): Point[] => points.map(([x, y]): Point => [x + dx, y + dy]);

/**
 * Body Battery, after the watch's own icon: a head and shoulders inside a
 * gauge that sweeps clockwise from bottom left to top right, growing from a
 * hairline to a thick band. The gauge sits low, around the head rather than
 * above it, and the whole is centred in the box and scaled until its longer
 * side fills it. From `BODY_BATTERY_SEGMENTS_FROM_PX` across the gauge is
 * four segments; smaller, gaps a pixel wide do not read, so it is one band,
 * starting a little later so it clears the shoulder. It is not the plain
 * 'battery' glyph, which means the device's charge.
 */
function bodyBatteryParts(across: number): Point[][] {
  // The thin end is never under about a pixel and a quarter, or it breaks into dots.
  const segmented = across >= BODY_BATTERY_SEGMENTS_FROM_PX, [thin, thick] = [Math.max(0.07, 2.5 / across), 0.3];
  // Small, the gap between the gauge's start and the shoulder is under a pixel, so the gauge starts later.
  const [from, to] = [segmented ? -135 : -122, 55], n = 24, drop = 0.28;
  const count = segmented ? 4 : 1, gap = segmented ? 10 : 0, step = (to - from) / count;
  const width = (a: number): number => thin + ((thick - thin) * (a - from)) / (to - from);
  const gauge = Array.from({ length: count }, (_, k): Point[] => {
    const [a0, a1] = [from + k * step + gap / 2, from + (k + 1) * step - gap / 2];
    const angles = Array.from({ length: n + 1 }, (_, i) => a0 + ((a1 - a0) * i) / n);
    return moved([...angles.map((a) => at(1, a * DEGREE)), ...[...angles].reverse().map((a) => at(1 - width(a), a * DEGREE))], 0, drop);
  });
  const parts = [...gauge, disc(0.27).map(([x, y]): Point => [x, y + 0.04]), dome(0, 0.98, 0.64, 0.5)];
  const xs = parts.flat().map((q) => q[0]), ys = parts.flat().map((q) => q[1]);
  const [cx, cy] = [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
  const half = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) / 2;
  return parts.map((q) => turning(q.map(([x, y]): Point => [(x - cx) / half, (y - cy) / half]), 1));
}

/** Body Battery in the round box of `md-lightning_bolt_circle`, centred on the pixel grid as the solar steps are. */
const BODY_BATTERY_COMPOSITE: Composite = {
  base: BOLT_CIRCLE,
  outline([x0, y0, x1, y1], pixel) {
    const across = Math.max(1, Math.round((x1 - x0 + y1 - y0) / 2 / pixel));
    const snap = (c: number): number => Math.round(c / pixel - across / 2) * pixel + (across * pixel) / 2;
    const cx = snap((x0 + x1) / 2), cy = snap((y0 + y1) / 2), radius = (across * pixel) / 2;
    const commands = bodyBatteryParts(across).flatMap((ps): PathCommand[] => [
      ...ps.map(([x, y], i): PathCommand => ({ type: i === 0 ? "M" : "L", x: cx + x * radius, y: cy + y * radius })),
      { type: "Z" },
    ]);
    return { commands, frame: [cx - radius, cy - radius, cx + radius, cy + radius] };
  },
};

/**
 * A composite as an SVG path in a 24-unit square, for a page that draws
 * glyphs with the icon font, which lacks it. Drawn 24 pixels across: the
 * solar steps' arcs and Body Battery's segments, as a larger icon shows them.
 */
export function compositeSvgPath(ch: string): string | null {
  const composite = COMPOSITES.get(ch);
  if (composite === undefined) return null;
  const n = (v: number): string => String(Math.round(v * 100) / 100);
  return composite.outline([0, 0, 24, 24], 1).commands.map((c) => {
    switch (c.type) {
      case "M": case "L": return `${c.type}${n(c.x)} ${n(c.y)}`;
      case "Q": return `Q${n(c.x1)} ${n(c.y1)} ${n(c.x)} ${n(c.y)}`;
      case "C": return `C${n(c.x1)} ${n(c.y1)} ${n(c.x2)} ${n(c.y2)} ${n(c.x)} ${n(c.y)}`;
      case "Z": return "Z";
    }
  }).join("");
}

/** Every composite, by its code point. */
export const COMPOSITES: ReadonlyMap<string, Composite> = new Map([
  ...Array.from({ length: 9 }, (_, k): [string, Composite] => [String.fromCodePoint(SOLAR_FIRST + k), solarStep(k)]),
  [String.fromCodePoint(BODY_BATTERY), BODY_BATTERY_COMPOSITE],
]);
