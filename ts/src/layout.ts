// Stage 3: a device-independent design resolved to absolute pixels on one
// device (ADR 0004). Nothing relative survives into generated Monkey C, and
// the preview draws from the same resolved geometry the device does. Port
// of wfb/layout.py; each kind's own `resolve` is in `kinds/`.
//
// The placed classes keep the Python dataclasses' field names and order,
// so the oracle's dump compares field for field.
import { Device, FontMetric } from "./devices/device.ts";
import type { Span } from "./diagnostics.ts";
import type { BakedFont } from "./fonts/bmfont.ts";
import { overrideKey } from "./ir/builder/tree.ts";
import {
  type AnyHandPart, type Curve, drawSortKey, type Element, type Expression, type Face, type FontSpec, type Gauge, type Graph,
  Group, type HandsElement, type IconElement, make, type PatternElement, Position, type Shape, type Text, type TextPart,
  type DataElement,
} from "./ir/model.ts";
import * as kinds from "./kinds/index.ts";
import { degrees, hypot, pyMod, radians, roundHalfEven } from "./py.ts";
import * as units from "./units.ts";
import { visibleMask } from "./visible_area.ts";
import { Angle, type Axis, Box, IntBox, type Length } from "./units.ts";

const round = roundHalfEven;

export class Placed {
  element!: Element;
  /** The pixels this element can touch. */
  box!: IntBox;
  center: [number, number] = [0, 0];
  depth = 0;
  /** How far `box` was grown for `outline:` rings past what the kind placed. */
  ring_grow = 0;
  /** Every width this element draws a ring at. */
  ring_widths: number[] = [];

  static create<T extends Placed>(this: new () => T, init: Partial<T>): T { return make(this, init); }

  /** `box` without the ring growth. */
  get innerBox(): IntBox {
    return this.ring_grow ? this.box.inflate(-this.ring_grow) : this.box;
  }

  get id(): string { return this.element.id; }
  get kind(): string { return this.element.kind; }
}

/** The "parent box" of a hand/pattern part's own frame: zero-sized at the origin. */
const HAND_FRAME_BOX = new Box(0.0, 0.0, 0.0, 0.0);

/** Round half away from zero, so a mirrored `dx: -1.5px`/`1.5px` pair stays symmetric. */
export function roundHalfAway(value: number): number {
  return value < 0 ? Math.trunc(value - 0.5) : Math.trunc(value + 0.5);
}

/** How far a placement box's centre sits from the point `at:` resolves to. */
export function alignmentShift(width: number, height: number, align: string, verticalAlign: string): [number, number] {
  const dx = ({ left: width / 2, center: 0.0, right: -width / 2 } as Record<string, number>)[align]!;
  const dy = ({ top: height / 2, center: 0.0, bottom: -height / 2 } as Record<string, number>)[verticalAlign]!;
  return [dx, dy];
}

/** The author's arc angles in Garmin's `drawArc` convention. */
export function garminArc(start: number, sweep: number): [number, string] {
  return [pyMod(90.0 - start, 360.0), sweep >= 0 ? "ARC_CLOCKWISE" : "ARC_COUNTER_CLOCKWISE"];
}

/** `curve.angle` in `drawAngledText`/`drawRadialText`'s convention: a position for `radial`, a rotation for `angled`. */
export function garminCurveAngle(style: string, angle: Angle): number {
  if (style === "radial") return angle.toGarmin();
  return pyMod(-angle.degrees, 360.0);
}

export function radialDirectionSign(direction: string | null): number {
  return direction === "counter_clockwise" ? 1.0 : -1.0;
}

export function radialAlignOffset(align: string, totalAdvance: number): number {
  return ({ left: 0.0, center: totalAdvance / 2.0, right: totalAdvance } as Record<string, number>)[align]!;
}

/** The Garmin-degree interval a radial run sweeps, unordered. */
export function radialTextAngleSpan(curveAngleGarmin: number, direction: string | null, align: string,
  totalAdvance: number, radius: number, pad = 0.0): [number, number] {
  const sign = radialDirectionSign(direction);
  const offset = radialAlignOffset(align, totalAdvance);
  return [
    curveAngleGarmin - sign * degrees((offset + pad) / radius),
    curveAngleGarmin + sign * degrees((totalAdvance - offset + pad) / radius),
  ];
}

/** The radii `[inner, outer]` a radial run's ink spans. */
export function radialTextBand(radius: number, lineHeight: number, verticalAlign: string, direction: string | null,
  ascent: number, pad = 0.0): [number, number] {
  if (verticalAlign === "center") {
    const half = lineHeight / 2.0;
    return [radius - half - pad, radius + half + pad];
  }
  const [up, down] = verticalAlign === "bottom" ? [ascent, lineHeight - ascent] : [0.0, lineHeight];
  if (direction !== "counter_clockwise") return [radius - down - pad, radius + up + pad];
  return [radius - up - pad, radius + down + pad];
}

/** The axis-aligned bounding box of an annulus sector, in Garmin degrees. */
export function arcBbox(cx: number, cy: number, rInner: number, rOuter: number, thetaA: number, thetaB: number): Box {
  const thetaMin = Math.min(thetaA, thetaB), thetaMax = Math.max(thetaA, thetaB);
  const sweep = thetaMax - thetaMin;
  rInner = Math.max(0.0, rInner);
  const xs: number[] = [], ys: number[] = [];
  for (const theta of [thetaMin, thetaMax]) {
    const rad = radians(theta);
    const c = Math.cos(rad), s = Math.sin(rad);
    for (const r of [rInner, rOuter]) {
      xs.push(cx + r * c);
      ys.push(cy - r * s);
    }
  }
  if (sweep >= 360.0) {
    xs.push(cx - rOuter, cx + rOuter);
    ys.push(cy - rOuter, cy + rOuter);
  } else {
    for (const axis of [0.0, 90.0, 180.0, 270.0]) {
      if (pyMod(axis - thetaMin, 360.0) <= sweep) {
        const rad = radians(axis);
        xs.push(cx + rOuter * Math.cos(rad));
        ys.push(cy - rOuter * Math.sin(rad));
      }
    }
  }
  const minX = Math.min(...xs), minY = Math.min(...ys);
  return new Box(minX, minY, Math.max(...xs) - minX, Math.max(...ys) - minY);
}

type Point = [number, number];

/** The four corners of an aligned text box rotated about its anchor by a Garmin angle. */
export function rotatedRectCorners(x: number, y: number, width: number, height: number, align: string, verticalAlign: string,
  garminAngle: number, pad = 0.0): [Point, Point, Point, Point] {
  const theta = radians(garminAngle);
  const c = Math.cos(theta), s = Math.sin(theta);
  const [dx, dy] = alignmentShift(width, height, align, verticalAlign);
  const cx = x + dx * c + dy * s, cy = y - dx * s + dy * c;
  const hw = width / 2.0 + pad, hh = height / 2.0 + pad;
  const corners = ([[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]] as const)
    .map(([lx, ly]): Point => [cx + lx * c + ly * s, cy - lx * s + ly * c]);
  return [corners[0]!, corners[1]!, corners[2]!, corners[3]!];
}

/** The farthest distance from `(px, py)` to any point of an annulus sector. */
export function annulusSectorReach(cx: number, cy: number, rInner: number, rOuter: number, thetaA: number, thetaB: number,
  px: number, py: number): number {
  const distC = hypot(cx - px, cy - py);
  const thetaMin = Math.min(thetaA, thetaB), thetaMax = Math.max(thetaA, thetaB);
  const sweep = thetaMax - thetaMin;
  rInner = Math.max(0.0, rInner);
  if (sweep >= 360.0 || distC < 1e-9) return distC + rOuter;
  const thetaFar = pyMod(degrees(Math.atan2(-(cy - py), cx - px)), 360.0);
  if (pyMod(thetaFar - thetaMin, 360.0) <= sweep) return distC + rOuter;
  let best = 0.0;
  for (const theta of [thetaMin, thetaMax]) {
    const rad = radians(theta);
    const c = Math.cos(rad), s = Math.sin(rad);
    for (const r of [rInner, rOuter]) best = Math.max(best, hypot(cx + r * c - px, cy - r * s - py));
  }
  return best;
}

// -- ink shapes ---------------------------------------------------------------------

/** The real ink of a drawn thing: its AABB, its bounds, its farthest reach from a point, and whether a point is inked. */
export interface Ink {
  box(): Box;
  bounds(): [number, number, number, number];
  reach(px: number, py: number): number;
  contains(px: number, py: number): boolean;
}

/** A screen-aligned rectangle: upright text. */
export class InkRect implements Ink {
  readonly left: number;
  readonly top: number;
  readonly width: number;
  readonly height: number;

  constructor(left: number, top: number, width: number, height: number) {
    this.left = left;
    this.top = top;
    this.width = width;
    this.height = height;
  }

  box(): Box { return new Box(this.left, this.top, this.width, this.height); }
  bounds(): [number, number, number, number] { return [this.left, this.top, this.left + this.width, this.top + this.height]; }
  reach(px: number, py: number): number {
    const [l, t, r, b] = this.bounds();
    return Math.max(...([[l, t], [r, t], [l, b], [r, b]] as const).map(([x, y]) => hypot(x - px, y - py)));
  }

  contains(px: number, py: number): boolean {
    const [l, t, r, b] = this.bounds();
    return l <= px && px <= r && t <= py && py <= b;
  }
}

/** Four real corners: angled text. */
export class InkQuad implements Ink {
  readonly corners: readonly Point[];

  constructor(corners: readonly Point[]) {
    this.corners = corners;
  }

  box(): Box {
    const [x0, y0, x1, y1] = this.bounds();
    return new Box(x0, y0, x1 - x0, y1 - y0);
  }

  bounds(): [number, number, number, number] {
    const xs = this.corners.map((p) => p[0]), ys = this.corners.map((p) => p[1]);
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }

  reach(px: number, py: number): number {
    return Math.max(...this.corners.map(([x, y]) => hypot(x - px, y - py)));
  }

  contains(px: number, py: number): boolean {
    const sides = new Set<boolean>();
    const n = this.corners.length;
    for (let i = 0; i < n; i++) {
      const [ax, ay] = this.corners[i]!, [bx, by] = this.corners[(i + 1) % n]!;
      const cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax);
      if (Math.abs(cross) > 1e-9) sides.add(cross > 0);
    }
    return sides.size <= 1;
  }
}

/** An annulus sector: radial text. */
export class InkSector implements Ink {
  readonly cx: number;
  readonly cy: number;
  readonly rInner: number;
  readonly rOuter: number;
  readonly thetaA: number;
  readonly thetaB: number;

  constructor(cx: number, cy: number, rInner: number, rOuter: number, thetaA: number, thetaB: number) {
    this.cx = cx;
    this.cy = cy;
    this.rInner = rInner;
    this.rOuter = rOuter;
    this.thetaA = thetaA;
    this.thetaB = thetaB;
  }

  box(): Box { return arcBbox(this.cx, this.cy, this.rInner, this.rOuter, this.thetaA, this.thetaB); }
  bounds(): [number, number, number, number] {
    const b = this.box();
    return [b.x, b.y, b.x + b.width, b.y + b.height];
  }

  reach(px: number, py: number): number {
    return annulusSectorReach(this.cx, this.cy, this.rInner, this.rOuter, this.thetaA, this.thetaB, px, py);
  }

  contains(px: number, py: number): boolean {
    const r = hypot(px - this.cx, py - this.cy);
    if (!(Math.max(0.0, this.rInner) <= r && r <= this.rOuter)) return false;
    const thetaMin = Math.min(this.thetaA, this.thetaB);
    const sweep = Math.max(this.thetaA, this.thetaB) - thetaMin;
    if (sweep >= 360.0 || r < 1e-9) return true;
    const theta = pyMod(degrees(Math.atan2(-(py - this.cy), px - this.cx)), 360.0);
    return pyMod(theta - thetaMin, 360.0) <= sweep;
  }
}

/** A full disc: every `circularExtent` kind. */
export class InkDisc implements Ink {
  readonly cx: number;
  readonly cy: number;
  readonly radius: number;

  constructor(cx: number, cy: number, radius: number) {
    this.cx = cx;
    this.cy = cy;
    this.radius = radius;
  }

  box(): Box { return new Box(this.cx - this.radius, this.cy - this.radius, 2 * this.radius, 2 * this.radius); }
  bounds(): [number, number, number, number] {
    return [this.cx - this.radius, this.cy - this.radius, this.cx + this.radius, this.cy + this.radius];
  }

  reach(px: number, py: number): number { return hypot(this.cx - px, this.cy - py) + this.radius; }
  contains(px: number, py: number): boolean { return hypot(px - this.cx, py - this.cy) <= this.radius; }
}

/** The ink of one measured run anchored at `(x, y)`: upright, angled or radial. */
export function textInk(x: number, y: number, width: number, height: number, align: string, verticalAlign: string,
  { curveStyle, angleGarmin, radiusPx, direction, metric, pad, device }: {
    curveStyle: string | null; angleGarmin: number; radiusPx: number; direction: string | null;
    metric: FontMetric | null; pad: number; device: Device;
  }): Ink {
  if (curveStyle === "angled") return new InkQuad(rotatedRectCorners(x, y, width, height, align, verticalAlign, angleGarmin, pad));
  if (curveStyle === "radial") {
    if (radiusPx <= 0) return new InkDisc(x, y, radiusPx + height + pad);
    const [a, b] = radialTextAngleSpan(angleGarmin, direction, align, width, radiusPx, pad);
    const ascent = metric !== null ? device.db.measure.ascent(metric) : height;
    const [inner, outer] = radialTextBand(radiusPx, height, verticalAlign, direction, ascent, pad);
    return new InkSector(x, y, inner, outer, a, b);
  }
  const [dx, dy] = alignmentShift(width, height, align, verticalAlign);
  const w = width + 2 * pad, h = height + 2 * pad;
  return new InkRect(x + dx - w / 2, y + dy - h / 2, w, h);
}

/** How far a stroked outline's ink reaches past its declared edge. */
export function strokePad(pen: number): number {
  return Math.floor(pen / 2) + 1;
}

/** What `shape: arc` and a gauge arc share once radius and pen are resolved. */
export function arcBox(radius: number, pen: number, cx: number, cy: number, align: string, verticalAlign: string,
  startAngle: Angle | null, sweepAngle: Angle | null): [IntBox, number, number, number, number, number, string] {
  const [dx, dy] = alignmentShift(2 * radius, 2 * radius, align, verticalAlign);
  cx += dx;
  cy += dy;
  const reach = radius + strokePad(pen);
  const box = new Box(cx - reach, cy - reach, 2 * reach, 2 * reach);
  const start = (startAngle ?? new Angle(0.0)).degrees;
  const sweep = (sweepAngle ?? new Angle(360.0)).degrees;
  const [garminStart, direction] = garminArc(start, sweep);
  return [box.rounded(), cx, cy, start, sweep, garminStart, direction];
}

export class PlacedShape extends Placed {
  declare element: Shape;
  radius = 0;
  corner_radius = 0;
  thickness = 1;
  end: [number, number] = [0, 0];
  rx = 0;
  ry = 0;
  /** The rectangle `fillRectangle`/`drawRectangle` gets, when it is not `box`. */
  rect: IntBox | null = null;
  points: [number, number][] = [];
  start_angle = 0.0;
  sweep = 360.0;
  garmin_start = 90.0;
  garmin_direction = "ARC_CLOCKWISE";
  aod_thickness: number | null = null;
}

/** A text font resolved for one device. */
export class ResolvedFont {
  reference = "";
  is_custom = false;
  px = 0;
  metric: FontMetric | null = null;
  /** Vector fonts only: the face this device publishes, or empty. */
  face = "";
  is_vector = false;
  available = true;

  static create(init: Partial<ResolvedFont> = {}): ResolvedFont { return make(ResolvedFont, init); }
}

/** A text's `curve:` resolved for one device. */
export class ResolvedCurve {
  style: string | null = null;
  angle_degrees = 0.0;
  angle_garmin = 0.0;
  radius_px = 0;
  direction: string | null = null;

  static create(init: Partial<ResolvedCurve> = {}): ResolvedCurve { return make(ResolvedCurve, init); }
}

/** `curve:`'s style, angles and direction; the caller resolves the radius. */
export function resolvedCurve(curve: Curve | null): ResolvedCurve {
  if (curve === null) return new ResolvedCurve();
  return ResolvedCurve.create({
    style: curve.style, angle_degrees: curve.angle.degrees, angle_garmin: garminCurveAngle(curve.style, curve.angle),
    radius_px: 0, direction: curve.direction,
  });
}

export class PlacedText extends Placed {
  declare element: Text;
  anchor_point: [number, number] = [0, 0];
  justify: string[] = [];
  font: ResolvedFont = new ResolvedFont();
  widest = "";
  measured_width = 0;
  width_is_estimated = false;
  curve: ResolvedCurve = new ResolvedCurve();
  line_height = 0.0;
}

export class PlacedGauge extends Placed {
  declare element: Gauge;
  radius = 0;
  thickness = 1;
  start_angle = 0.0;
  sweep = 360.0;
  garmin_start = 90.0;
  garmin_direction = "ARC_CLOCKWISE";
  size: [number, number] = [0, 0];
  aod_thickness: number | null = null;
  needle: RotatablePart[] = [];
  reach = 0.0;
  cell = 0.0;
  step = 0.0;
  pointer = 0;
  band_spans: [number, number][] = [];
  rect: IntBox | null = null;
}

export class PlacedIcon extends Placed {
  declare element: IconElement;
  size = 0;
  font_key = "";
  codepoint = "?";
  anchor_point: [number, number] = [0, 0];
  justify: string[] = [];
}

export class PlacedGraph extends Placed {
  declare element: Graph;
  thickness = 1;
  bar_width = 1;
  size: [number, number] = [0, 0];
  aod_thickness: number | null = null;
  aod_bar_width: number | null = null;
}

type Bounds = [number, number, number, number];

/** A part-frame point put through one copy's rotation and offset. */
function transformed(x: number, y: number, ox: number, oy: number, s: number, c: number): Point {
  return [ox + x * c - y * s, oy + x * s + y * c];
}

/** What every resolved hand or pattern part carries; `shape` is a class constant, as Python's `ClassVar`. */
export abstract class ResolvedPart {
  abstract get shape(): string;
  color: Expression | null = null;
  /** The farthest ink from the frame's origin; 0 for a text part. */
  reach = 0.0;
}

export class ResolvedPolygonPart extends ResolvedPart {
  get shape(): "polygon" { return "polygon"; }
  points: [number, number][] = [];

  static create(init: Partial<ResolvedPolygonPart>): ResolvedPolygonPart { return make(ResolvedPolygonPart, init); }

  ink(ox: number, oy: number, s: number, c: number): Bounds {
    const pts = this.points.map(([x, y]) => transformed(x, y, ox, oy, s, c));
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }
}

export class ResolvedLinePart extends ResolvedPart {
  get shape(): "line" { return "line"; }
  x1 = 0;
  y1 = 0;
  x2 = 0;
  y2 = 0;
  thickness = 1;

  static create(init: Partial<ResolvedLinePart>): ResolvedLinePart { return make(ResolvedLinePart, init); }

  ink(ox: number, oy: number, s: number, c: number): Bounds {
    const [x1, y1] = transformed(this.x1, this.y1, ox, oy, s, c), [x2, y2] = transformed(this.x2, this.y2, ox, oy, s, c);
    const pad = this.thickness / 2.0;
    return [Math.min(x1, x2) - pad, Math.min(y1, y2) - pad, Math.max(x1, x2) + pad, Math.max(y1, y2) + pad];
  }
}

export class ResolvedCirclePart extends ResolvedPart {
  get shape(): "circle" { return "circle"; }
  x = 0;
  y = 0;
  radius = 0;
  thickness = 1;
  filled = true;

  static create(init: Partial<ResolvedCirclePart>): ResolvedCirclePart { return make(ResolvedCirclePart, init); }

  ink(ox: number, oy: number, s: number, c: number): Bounds {
    const [px, py] = transformed(this.x, this.y, ox, oy, s, c);
    const pad = this.radius + (this.filled ? 0.0 : this.thickness / 2.0);
    return [px - pad, py - pad, px + pad, py + pad];
  }
}

export class ResolvedArcPart extends ResolvedPart {
  get shape(): "arc" { return "arc"; }
  x = 0;
  y = 0;
  radius = 0;
  thickness = 1;
  start_angle = 0.0;
  sweep = 0.0;

  static create(init: Partial<ResolvedArcPart>): ResolvedArcPart { return make(ResolvedArcPart, init); }

  ink(ox: number, oy: number, s: number, c: number): Bounds {
    const [px, py] = transformed(0.0, 0.0, ox, oy, s, c);
    const pad = this.radius + this.thickness / 2.0;
    return [px - pad, py - pad, px + pad, py + pad];
  }
}

export class ResolvedTextPart extends ResolvedPart {
  get shape(): "text" { return "text"; }
  x = 0;
  y = 0;
  font: ResolvedFont = new ResolvedFont();
  justify: string[] = [];
  align = "center";
  vertical_align = "center";
  line_height = 0;
  texts: string[] = [];
  widths: number[] = [];
  curve: ResolvedCurve = new ResolvedCurve();
  outline_width = 0;
  outline_color: Expression | null = null;

  static create(init: Partial<ResolvedTextPart>): ResolvedTextPart { return make(ResolvedTextPart, init); }
}

export type ResolvedHandPart = ResolvedPolygonPart | ResolvedLinePart | ResolvedCirclePart | ResolvedArcPart | ResolvedTextPart;
export type RotatablePart = ResolvedPolygonPart | ResolvedLinePart | ResolvedCirclePart;

/** `parts` as a hand's or needle's own, which the builder guarantees. */
export function rotatableParts(parts: readonly ResolvedHandPart[], owner: string): RotatablePart[] {
  return parts.map((part) => {
    if (part instanceof ResolvedArcPart || part instanceof ResolvedTextPart) {
      throw new Error(`${owner}: a ${part.shape} part cannot turn with a hand`);
    }
    return part;
  });
}

export class ResolvedHand {
  parts: RotatablePart[] = [];

  static create(init: Partial<ResolvedHand>): ResolvedHand { return make(ResolvedHand, init); }
}

export class PlacedHands extends Placed {
  declare element: HandsElement;
  hour: ResolvedHand | null = null;
  minute: ResolvedHand | null = null;
  second: ResolvedHand | null = null;
  reach = 0.0;
  aod_thickness: number | null = null;
}

export class PlacedPattern extends Placed {
  declare element: PatternElement;
  parts: ResolvedHandPart[] = [];
  copies: number[] = [];
  start = 0.0;
  step = 0.0;
  dx = 0;
  dy = 0;
  columns = 0;
  reach = 0.0;
  aod_thickness: number | null = null;

  /** `[ox, oy, sin, cos]` for copy `index`: a rotation about `center`, or a translation. */
  transform(index: number): [number, number, number, number] {
    if (this.element.pattern === "radial") {
      const theta = radians(this.start + index * this.step);
      return [this.center[0], this.center[1], Math.sin(theta), Math.cos(theta)];
    }
    if (this.element.pattern === "grid") {
      const column = pyMod(index, this.columns), row = Math.floor(index / this.columns);
      return [this.center[0] + column * this.dx, this.center[1] + row * this.dy, 0.0, 1.0];
    }
    return [this.center[0] + index * this.dx, this.center[1] + index * this.dy, 0.0, 1.0];
  }
}

/** The gap between a data element's icon and reading when `icon_gap:` is not authored. */
export const DATA_ICON_GAP = 4;

/** The icon+reading pair's extent, and each piece's offset from its top-left. */
export interface SlotPairGeometry {
  width: number;
  height: number;
  iconX: number;
  iconY: number;
  textX: number;
  textY: number;
}

export function dataPairGeometry(position: string, iconW: number, iconH: number, textW: number, textH: number, gap: number): SlotPairGeometry {
  const hasIcon = iconW > 0 || iconH > 0;
  gap = hasIcon ? gap : 0;
  if (position === "top" || position === "bottom") {
    const width = Math.max(iconW, textW);
    const height = iconH + gap + textH;
    const iconX = hasIcon ? Math.floor((width - iconW) / 2) : 0;
    const textX = Math.floor((width - textW) / 2);
    if (position === "top") return { width, height, iconX, iconY: 0, textX, textY: iconH + gap };
    return { width, height, iconX, iconY: textH + gap, textX, textY: 0 };
  }
  const width = textW + (hasIcon ? iconW + gap : 0);
  const height = Math.max(iconH, textH);
  const iconY = Math.floor((height - iconH) / 2), textY = Math.floor((height - textH) / 2);
  if (position === "right") return { width, height, iconX: textW + gap, iconY, textX: 0, textY };
  return { width, height, iconX: 0, iconY, textX: hasIcon ? iconW + gap : 0, textY };
}

export class PlacedData extends Placed {
  declare element: DataElement;
  anchor_point: [number, number] = [0, 0];
  font: ResolvedFont = new ResolvedFont();
  widest = "";
  icon_font_key: string | null = null;
  icon_px = 0;
  icon_position = "left";
  icon_gap_px = DATA_ICON_GAP;
  highlight: IntBox | null = null;
}

/** Who a `SubPixelLength` or `ResolveWarning` is recorded against. */
interface Owner {
  id: string;
  span: Span | null;
  element: Element;
}

/** A nonzero %/%r extent that resolved below 1 px on this device with `min_1px` off. */
export class SubPixelLength {
  owner = "";
  key = "";
  length!: Length;
  value = 0;
  span: Span | null = null;
  element!: Element;

  static create(init: Partial<SubPixelLength>): SubPixelLength { return make(SubPixelLength, init); }
}

/** `ResolvedFace.hidden` reasons: the code of the lint that reports each. */
export const HIDDEN_BY_SUBSCREEN = "subscreen";
export const HIDDEN_BY_FONT = "font-unavailable";

/** Something this device's resolve could not check. */
export class ResolveWarning {
  message = "";
  span: Span | null = null;
  element!: Element;

  static create(init: Partial<ResolveWarning>): ResolveWarning { return make(ResolveWarning, init); }
}

export class ResolvedFace {
  face!: Face;
  device!: Device;
  /** Flattened, in draw order. */
  items: Placed[] = [];
  fonts: Map<string, BakedFont> = new Map();
  screen!: IntBox;
  warnings: ResolveWarning[] = [];
  sub_pixel: SubPixelLength[] = [];
  /** The items that do not draw on this device, each mapped to why. */
  hidden: Map<string, string> = new Map();

  static create(init: Partial<ResolvedFace>): ResolvedFace { return make(ResolvedFace, init); }

  /** `items` less `hidden`: what this device actually draws. */
  get shownItems(): Placed[] {
    return this.items.filter((p) => !this.hidden.has(p.id));
  }

  /** This face less what the device does not draw. */
  drawnOnly(): ResolvedFace {
    if (this.hidden.size === 0) return this;
    return ResolvedFace.create({
      ...this, items: this.shownItems,
      sub_pixel: this.sub_pixel.filter((sp) => !this.hidden.has(sp.element.id)),
      warnings: this.warnings.filter((w) => !this.hidden.has(w.element.id)),
    });
  }

  /** Everything that actually paints in `mode`: never a group. */
  drawnInMode(mode: string): Placed[] {
    return this.items.filter((p) => p.kind !== "group" && p.element.modes.includes(mode));
  }

  /** The tightest rectangle covering everything drawn in `mode`. */
  clipFor(mode: string): IntBox | null {
    const drawn = this.drawnInMode(mode);
    let boxes = drawn.filter((p) => !this.hidden.has(p.id)).map((p) => p.box);
    if (boxes.length === 0) boxes = drawn.map((p) => p.box);
    if (boxes.length === 0) return null;
    let clip = boxes[0]!;
    for (const box of boxes.slice(1)) clip = clip.union(box);
    return clip.inflate(1).clampTo(this.device.width, this.device.height);
  }
}

/** One text font, resolved for this device. */
export class LayoutFont {
  readonly px: number;
  readonly reference: string;
  readonly isCustom: boolean;
  readonly baked: BakedFont | null;
  readonly metric: FontMetric | null;
  readonly face: string;
  readonly isVector: boolean;
  readonly available: boolean;
  readonly device: Device;

  constructor(device: Device, px: number, reference: string, isCustom: boolean, baked: BakedFont | null, metric: FontMetric | null,
    face = "", isVector = false, available = true) {
    this.device = device;
    this.px = px;
    this.reference = reference;
    this.isCustom = isCustom;
    this.baked = baked;
    this.metric = metric;
    this.face = face;
    this.isVector = isVector;
    this.available = available;
  }

  /** `text`'s advance: exact for a baked sheet, an estimate for a system or vector font, 0 with no metrics. */
  width(text: string): number {
    if (this.baked !== null) return this.baked.measure(text)[0];
    return this.metric !== null ? this.device.db.measure.measure(text, this.metric)[0] : 0;
  }

  get lineHeight(): number {
    if (this.baked !== null) return this.baked.line_height;
    return this.metric !== null ? this.device.db.measure.lineHeight(this.metric) : this.px;
  }

  resolved(): ResolvedFont {
    return ResolvedFont.create({
      reference: this.reference, is_custom: this.isCustom, px: this.px, metric: this.metric,
      face: this.face, is_vector: this.isVector, available: this.available,
    });
  }
}

/** `element` with these fields replaced, as `dataclasses.replace`. */
export function replaceFields<T extends object>(element: T, fields: Partial<T> | ReadonlyMap<string, unknown>): T {
  const values = fields instanceof Map ? Object.fromEntries(fields) : fields;
  return Object.assign(Object.create(Object.getPrototypeOf(element)) as T, element, values);
}

/** Per-device layout: every element of one face placed on one device, in whole pixels. */
export class Resolver {
  readonly face: Face;
  readonly device: Device;
  readonly fonts: Map<string, BakedFont>;
  readonly screen: Box;
  readonly minorRadius: number;
  items: Placed[] = [];
  hidden = new Map<string, string>();
  warnings: ResolveWarning[] = [];
  subPixel: SubPixelLength[] = [];
  private owner: Owner | null = null;

  constructor(face: Face, device: Device, fonts: Map<string, BakedFont>) {
    this.face = face;
    this.device = device;
    this.fonts = fonts;
    this.screen = new Box(0, 0, device.width, device.height);
    this.minorRadius = device.minorRadius;
  }

  resolve(): ResolvedFace {
    this.resolveList(this.face.elements, this.screen, 0);
    // Static content first, then `z`, then document order: `drawSortKey`, stable.
    const keyed = this.items.map((p, i) => [drawSortKey(p.element), i, p] as const);
    keyed.sort((a, b) => {
      for (let k = 0; k < 4; k++) if (a[0][k] !== b[0][k]) return a[0][k]! - b[0][k]!;
      return a[1] - b[1];
    });
    this.items = keyed.map(([, , p]) => p);
    return ResolvedFace.create({
      face: this.face, device: this.device, items: this.items, fonts: this.fonts, sub_pixel: this.subPixel,
      screen: new IntBox(0, 0, this.device.width, this.device.height), warnings: this.warnings, hidden: new Map(this.hidden),
    });
  }

  private resolveList(elements: readonly Element[], parent: Box, depth: number, hidden: string | null = null, ring = 0): void {
    for (const original of elements) {
      const element = this.forDevice(original);
      let here = parent, reason = hidden;
      if (element.inSubscreen) {
        const window = this.device.subscreen;
        if (window === null) reason = HIDDEN_BY_SUBSCREEN;
        else here = new Box(...window);
      }
      this.ownedBy({ id: element.id, span: element.span, element }, () => {
        if (element instanceof Group) {
          const box = this.groupBox(element, here);
          this.items.push(Placed.create({
            element, box: box.rounded(element.resolved_min_1px), center: [round(box.centerX), round(box.centerY)], depth,
          }));
          const inner = ring + (element.outline !== null ? element.outline.width : 0);
          this.resolveList(element.items, box, depth + 1, reason, inner);
        } else {
          const kind = kinds.forElement(element);
          const placed = kind.resolve(this, element, here, depth);
          const own = element.outline !== null ? element.outline.width : 0;
          // A `text` element's own ring is already in its ink box.
          const grow = ring + (element.kind === "text" ? 0 : own);
          if (grow) {
            placed.ring_grow = grow;
            placed.box = placed.box.inflate(grow);
          }
          if (own || ring) placed.ring_widths = kinds.ringWidths(element, this.face);
          this.items.push(placed);
          reason = reason || kind.hiddenReason(placed);
        }
      });
      if (reason !== null) this.hidden.set(element.id, reason);
    }
  }

  /** `element` with this device's `overrides:` applied: a device id's patch, else its shape's. */
  forDevice<E extends Element>(element: E): E {
    if (element.overrides.size === 0) return element;
    const shape = this.device.shape, device = this.device.id;
    const pick = (key: string): Map<string, unknown> | undefined => {
      const fields = element.overrides.get(key);
      return fields !== undefined && fields.size > 0 ? fields : undefined;
    };
    const fields = pick(overrideKey(shape, device)) ?? pick(overrideKey(null, device)) ?? pick(overrideKey(shape, null));
    return fields !== undefined ? replaceFields(element, fields) : element;
  }

  /** Record every `SubPixelLength` and `ResolveWarning` inside `body` against `owner`. */
  private ownedBy<T>(owner: Owner, body: () => T): T {
    const previous = this.owner;
    this.owner = owner;
    try {
      return body();
    } finally {
      this.owner = previous;
    }
  }

  // -- per-kind ------------------------------------------------------------------

  /** The "size, then align" box every `size:`-placed kind shares, and its shifted centre. */
  sizedBox(element: Group | Shape | Gauge | Graph, parent: Box, cx: number, cy: number): [Box, number, number] {
    const min1px = element.resolved_min_1px;
    const width = this.extent(element.size.width, parent, "x", parent.width, null, min1px, "size.width");
    const height = this.extent(element.size.height, parent, "y", parent.height, null, min1px, "size.height");
    const [dx, dy] = alignmentShift(width, height, element.align, element.vertical_align);
    cx += dx;
    cy += dy;
    return [new Box(cx - width / 2, cy - height / 2, width, height), cx, cy];
  }

  private groupBox(element: Group, parent: Box): Box {
    const [cx, cy] = this.point(element.at, parent);
    return this.sizedBox(element, parent, cx, cy)[0];
  }

  /** `fontForRef`, plus gates 1-3 for a `face:` (vector) font. */
  textFont(font: string, isCustom: boolean, curve: Curve | null): LayoutFont {
    const resolved = this.fontForRef(font, isCustom);
    if (!resolved.isCustom) return resolved;
    const spec = this.face.fonts.get(font)!;
    if (!spec.isVector) return resolved;
    const [face, available] = this.resolveVectorFace(spec, curve);
    return new LayoutFont(this.device, resolved.px, resolved.reference, resolved.isCustom, null,
      this.vectorFontMetric(face, resolved.px), face, true, available);
  }

  private vectorGate1Ok(curveStyle: string | null): boolean {
    const device = this.device;
    if (!device.hasSymbol(Device.VECTOR_FONT_SYMBOL)) return false;
    if (curveStyle === "angled" && !device.hasSymbol(Device.DRAW_ANGLED_TEXT_SYMBOL)) return false;
    if (curveStyle === "radial" && !device.hasSymbol(Device.DRAW_RADIAL_TEXT_SYMBOL)) return false;
    return true;
  }

  /** The first of `spec.face`'s candidates this device publishes, or `["", false]`. */
  private resolveVectorFace(spec: FontSpec, curve: Curve | null): [string, boolean] {
    if (!this.vectorGate1Ok(curve !== null ? curve.style : null)) return ["", false];
    for (const name of spec.face ?? []) if (this.device.scalableFaces.includes(name)) return [name, true];
    return ["", false];
  }

  /** A synthetic metric for a vector face, so it measures exactly like a system font. */
  private vectorFontMetric(faceName: string, fontPx: number): FontMetric {
    const filename = this.device.scalableFaceFiles.get(faceName) ?? faceName;
    return new FontMetric(faceName || "vector", faceName, filename, fontPx);
  }

  /** Every part of one `parts:` list, and the farthest reach among them. */
  resolveParts(parts: readonly AnyHandPart[], owner: string, min1px: boolean): [ResolvedHandPart[], number] {
    const resolved: ResolvedHandPart[] = [];
    let reach = 0.0;
    parts.forEach((part, index) => {
      const p = this.ownedBy({ ...this.owner!, id: `${owner}.parts[${index}]`, span: part.span }, () => this.handPartGeometry(part, min1px));
      resolved.push(p);
      reach = Math.max(reach, p.reach);
    });
    return [resolved, reach];
  }

  /** One hand or pattern part in whole pixels in its own frame, rounded half away from zero. */
  private handPartGeometry(part: AnyHandPart, min1px: boolean): ResolvedHandPart {
    const effective = part.min_1px !== null ? part.min_1px : min1px;
    if (part.shape === "polygon") {
      const points = part.points.map((p): [number, number] => {
        const [x, y] = this.handPoint(p);
        return [roundHalfAway(x), roundHalfAway(y)];
      });
      const reach = points.length > 0 ? Math.max(...points.map(([x, y]) => hypot(x, y))) : 0.0;
      return ResolvedPolygonPart.create({ color: part.color, reach, points });
    }
    if (part.shape === "rectangle") {
      let [cx, cy] = this.handPoint(part.at);
      const width = this.handExtent(part.size.width, 0, effective, "size.width");
      const height = this.handExtent(part.size.height, 0, effective, "size.height");
      const [dx, dy] = alignmentShift(width, height, part.align, part.vertical_align);
      cx += dx;
      cy += dy;
      const hw = width / 2.0, hh = height / 2.0;
      const points = ([[cx - hw, cy - hh], [cx + hw, cy - hh], [cx + hw, cy + hh], [cx - hw, cy + hh]] as const)
        .map(([x, y]): [number, number] => [roundHalfAway(x), roundHalfAway(y)]);
      const reach = Math.max(...points.map(([x, y]) => hypot(x, y)));
      return ResolvedPolygonPart.create({ color: part.color, reach, points });
    }
    if (part.shape === "line") {
      const [x1, y1] = this.handPoint(part.at);
      const [x2, y2] = this.handPoint(part.to!);
      const thickness = Math.max(1, roundHalfAway(this.handExtent(part.thickness, 1, effective, "thickness")));
      const reach = Math.max(hypot(x1, y1), hypot(x2, y2)) + thickness / 2.0;
      return ResolvedLinePart.create({
        color: part.color, reach, x1: roundHalfAway(x1), y1: roundHalfAway(y1), x2: roundHalfAway(x2), y2: roundHalfAway(y2), thickness,
      });
    }
    if (part.shape === "arc") {
      const radius = roundHalfAway(this.handExtent(part.radius, 0, effective, "radius"));
      const thickness = Math.max(1, roundHalfAway(this.handExtent(part.thickness, 1, effective, "thickness")));
      const startAngle = (part.start_angle ?? new Angle(0.0)).degrees;
      const sweep = (part.sweep ?? new Angle(360.0)).degrees;
      return ResolvedArcPart.create({ color: part.color, reach: radius + thickness / 2.0, radius, thickness, start_angle: startAngle, sweep });
    }
    if (part.shape === "text") {
      const [x0, y0] = this.handPoint(part.at);
      const font = this.textFont(part.font, part.font_is_custom, part.curve);
      let curve = resolvedCurve(part.curve);
      if (part.curve !== null && curve.style === "radial" && part.curve.radius !== null) {
        curve = replaceFields(curve, { radius_px: roundHalfAway(this.handExtent(part.curve.radius, 0, effective, "curve.radius")) });
      }
      const outline = part.outline;
      return ResolvedTextPart.create({
        color: part.color, reach: 0.0, x: roundHalfAway(x0), y: roundHalfAway(y0), font: font.resolved(),
        justify: Resolver.justify(part), align: part.align, vertical_align: part.vertical_align, line_height: font.lineHeight,
        texts: part.texts, widths: part.texts.map((t) => font.width(t)), curve,
        outline_width: outline !== null ? outline.width : 0, outline_color: outline !== null ? outline.color : null,
      });
    }
    // circle
    let [cx, cy] = this.handPoint(part.at);
    const radius = roundHalfAway(this.handExtent(part.radius, 0, effective, "radius"));
    const [dx, dy] = alignmentShift(2 * radius, 2 * radius, part.align, part.vertical_align);
    cx += dx;
    cy += dy;
    const thickness = Math.max(1, roundHalfAway(this.handExtent(part.thickness, 1, effective, "thickness")));
    const penReach = part.filled ? radius : radius + thickness / 2.0;
    return ResolvedCirclePart.create({
      color: part.color, reach: hypot(cx, cy) + penReach, x: roundHalfAway(cx), y: roundHalfAway(cy), radius, thickness, filled: part.filled,
    });
  }

  private handPoint(at: Position): [number, number] {
    return this.point(at, HAND_FRAME_BOX);
  }

  private handExtent(length: Length | null, defaultValue: number, min1px: boolean, what: string): number {
    return this.extent(length, HAND_FRAME_BOX, "minor", defaultValue, null, min1px, what);
  }

  // -- helpers ------------------------------------------------------------------

  /** `at:` resolved to a point inside `parent`: its anchor, then `dx`/`dy`, or polar `angle`/`radius`. */
  point(at: Position, parent: Box): [number, number] {
    const [ax, ay] = parent.anchorPoint(at.anchor);
    if (at.angle !== null) {
      const radius = this.length(at.radius, parent, "minor", 0);
      const theta = radians(at.angle.degrees);
      return [ax + radius * Math.sin(theta), ay - radius * Math.cos(theta)];
    }
    return [ax + this.length(at.dx, parent, "x", 0), ay + this.length(at.dy, parent, "y", 0)];
  }

  /** `length` in pixels along `axis` of `parent`, or `defaultValue`. For a position. */
  length(length: Length | null, parent: Box, axis: Axis, defaultValue: number, fontPx: number | null = null): number {
    if (length === null) return defaultValue;
    return length.resolve(parent, axis, this.minorRadius, fontPx);
  }

  /** `length`, then at least one pixel with `min1px`; a sub-pixel relative length is recorded otherwise. For a size. */
  extent(length: Length | null, parent: Box, axis: Axis, defaultValue: number, fontPx: number | null, min1px: boolean, what: string): number {
    const value = this.length(length, parent, axis, defaultValue, fontPx);
    if (!min1px && units.isSubPixelLength(length, value)) this.recordSubPixel(what, length!, value);
    return units.atLeastOnePx(length, value, min1px);
  }

  /** The `aod:` override of `thickness`/`bar_width`, or `null` when there is none. */
  aodExtent(element: Element, key: "thickness" | "bar_width", parent: Box, defaultValue: number): number | null {
    const aodLength = element.aod !== null ? element.aod[key] : null;
    if (aodLength === null) return null;
    return Math.max(1, round(this.extent(aodLength, parent, "minor", defaultValue, null, true, "aod")));
  }

  private recordSubPixel(key: string, length: Length, value: number): void {
    const owner = this.owner!;
    this.subPixel.push(SubPixelLength.create({ owner: owner.id, key, length, value, span: owner.span, element: owner.element }));
  }

  /** A `font:` reference for this device, before any vector gate. */
  fontForRef(font: string, isCustom: boolean): LayoutFont {
    if (isCustom) {
      const baked = this.fonts.get(font) ?? null;
      const size = baked !== null ? baked.size : this.face.fonts.get(font)!.pixelSize(this.minorRadius);
      return new LayoutFont(this.device, size, font, true, baked, null);
    }
    const metric = this.device.systemFonts.get(font) ?? null;
    if (metric === null) {
      const owner = this.owner!;
      this.warnings.push(ResolveWarning.create({
        message: `${owner.id}: no pixel metrics for ${font} on ${this.device.id}; text extent is not checked`,
        span: owner.span, element: owner.element,
      }));
    }
    return new LayoutFont(this.device, metric !== null ? metric.size_px : 0, font, false, null, metric);
  }

  static justify(element: Text | TextPart | IconElement): string[] {
    return justify(element);
  }
}

/** `TEXT_JUSTIFY_*` flags for anything with `align`/`vertical_align`. */
export function justify(element: Text | TextPart | IconElement): string[] {
  const flag = ({ left: "TEXT_JUSTIFY_LEFT", center: "TEXT_JUSTIFY_CENTER", right: "TEXT_JUSTIFY_RIGHT" } as Record<string, string>)[element.align]!;
  return element.vertical_align === "center" ? [flag, "TEXT_JUSTIFY_VCENTER"] : [flag];
}

/** `candidate` if strictly longer than `current`, else `current`. */
export function longer(current: string, candidate: string): string {
  return Array.from(candidate).length > Array.from(current).length ? candidate : current;
}

export function resolve(face: Face, device: Device, fonts: Map<string, BakedFont>): ResolvedFace {
  return new Resolver(face, device, fonts).resolve();
}

/** How much of a round screen's outer edge the bezel effectively crops. */
export const BEZEL_MARGIN = 0.02;

/** Is the box inside the (rectangular) framebuffer? */
export function insideScreen(box: IntBox, device: Device): boolean {
  return box.x >= 0 && box.y >= 0 && box.right <= device.width && box.bottom <= device.height;
}

/** `[cx, cy, radius]` for an element that is genuinely round, its ring growth included. */
export function circularExtent(placed: Placed): [number, number, number] | null {
  const extent = kinds.forElement(placed.element).circularExtent(placed);
  if (extent === null || !placed.ring_grow) return extent;
  return [extent[0], extent[1], extent[2] + placed.ring_grow];
}

/** The real ink where it is tighter than `placed.box`: a round kind's disc, or a curved text's sector or quad. */
function shapeInk(placed: Placed, device: Device): Ink | null {
  const circle = circularExtent(placed);
  if (circle !== null) return new InkDisc(...circle);
  if (placed instanceof PlacedText && placed.curve.style !== null) {
    const outline = placed.element.outline;
    return textInk(placed.anchor_point[0], placed.anchor_point[1], placed.measured_width, placed.line_height,
      placed.element.align, placed.element.vertical_align, {
        curveStyle: placed.curve.style, angleGarmin: placed.curve.angle_garmin, radiusPx: placed.curve.radius_px,
        direction: placed.curve.direction, metric: placed.font.metric, pad: outline !== null ? outline.width : 0.0,
        device,
      });
  }
  return null;
}

/** The farthest any of `placed`'s ink reaches from a point; `null` when the box already is the shape. */
export function visibleReach(placed: Placed, device: Device, cx: number, cy: number): number | null {
  const ink = shapeInk(placed, device);
  return ink === null ? null : ink.reach(cx, cy);
}

/**
 * Visibility that respects the element's shape: a round screen is the
 * analytic circle less `BEZEL_MARGIN`; any other is the skin's own mask,
 * with one pixel of tolerance; without a skin, by shape alone.
 */
export function insideVisibleAreaFor(placed: Placed, device: Device): boolean | null {
  if (device.shape !== "round") {
    const mask = visibleMask(device);
    if (mask === null) return insideVisibleArea(placed.box, device);
    const box = placed.box;
    return mask.admits(shapeInk(placed, device) ?? new InkRect(box.x, box.y, box.width, box.height));
  }
  const reach = visibleReach(placed, device, device.width / 2, device.height / 2);
  if (reach === null) return insideVisibleArea(placed.box, device);
  return reach <= device.minorRadius * (1.0 - BEZEL_MARGIN) + 0.5;
}

/** Is every corner of the box within the screen's visible part, by shape alone? `null`: not checked. */
export function insideVisibleArea(box: IntBox, device: Device): boolean | null {
  if (device.shape === "round") {
    const cx = device.width / 2, cy = device.height / 2;
    const radius = device.minorRadius * (1.0 - BEZEL_MARGIN);
    return ([[box.x, box.y], [box.right, box.y], [box.x, box.bottom], [box.right, box.bottom]] as const)
      .every(([x, y]) => hypot(x - cx, y - cy) <= radius + 0.5);
  }
  if (device.shape === "rectangle") return insideScreen(box, device);
  return null;
}

/** Does this element deliberately cover the whole framebuffer? */
export function isFullBleed(box: IntBox, device: Device): boolean {
  return box.x <= 0 && box.y <= 0 && box.right >= device.width && box.bottom >= device.height;
}

/** The region in which any element is guaranteed visible: the inscribed square on a round screen. */
export function safeArea(device: Device): Box | null {
  if (device.shape === "round") {
    const radius = device.minorRadius * (1.0 - BEZEL_MARGIN);
    const side = radius * Math.SQRT2;
    return new Box(device.width / 2 - side / 2, device.height / 2 - side / 2, side, side);
  }
  if (device.shape === "rectangle") return new Box(0, 0, device.width, device.height);
  return null;
}
