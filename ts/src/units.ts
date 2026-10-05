// Lengths and angles, and the rules for resolving them to device pixels.
// Port of wfb/units.py.
//
// ADR 0004: absolute pixels are not the primary model. A length is one of
//
//   `12px`   device pixels, verbatim
//   `30%`    of the parent box, along the axis being resolved
//   `38%r`   of the screen's minor radius: what keeps a round design
//            circular on a non-square screen
//   `1.5pt`  multiples of a reference font's real pixel height on this device
//
// Angles are degrees with 12 o'clock = 0 and clockwise positive, because
// that is how a watch designer thinks. Garmin's `drawArc` uses 3 o'clock = 0
// and counter-clockwise positive; `Angle.toGarmin` converts.
import { degrees, formatG, isNumber, num, pyMod, repr, roundHalfEven } from "./py.ts";

export class UnitError extends Error {}

/** `minor` is for radii, thicknesses and other quantities with no natural axis; `%` then resolves against the parent box's smaller dimension. */
export type Axis = "x" | "y" | "minor";

const LENGTH = /^\s*(?<num>[+-]?(?:\d+\.?\d*|\.\d+))\s*(?<unit>%r|%|px|pt)?\s*$/;
const ANGLE = /^\s*(?<num>[+-]?(?:\d+\.?\d*|\.\d+))\s*(?<unit>deg|rad|turn)?\s*$/;
const DURATION = /^\s*(?<num>\d+)\s*(?<unit>m|h|d)\s*$/;

export type LengthUnit = "px" | "%" | "%r" | "pt";

export class Length {
  readonly value: number;
  readonly unit: LengthUnit;

  constructor(value: number, unit: LengthUnit) {
    this.value = value;
    this.unit = unit;
  }

  static parse(raw: unknown, what = "length"): Length {
    if (raw instanceof Length) return raw;
    if (typeof raw === "boolean") throw new UnitError(`${what}: expected a length, got a boolean`);
    if (isNumber(raw)) return new Length(num(raw), "px");
    if (typeof raw !== "string") throw new UnitError(`${what}: expected a length such as '12px' or '30%', got ${repr(raw)}`);
    const m = LENGTH.exec(raw);
    if (!m) throw new UnitError(`${what}: ${repr(raw)} is not a length.  Use px, %, %r or pt, e.g. '12px', '-4%', '38%r'`);
    return new Length(Number(m.groups!["num"]), (m.groups!["unit"] ?? "px") as LengthUnit);
  }

  /** Resolve to device pixels within `box`. */
  resolve(box: Box, axis: Axis, minorRadius: number, fontPx: number | null = null): number {
    if (this.unit === "px") return this.value;
    if (this.unit === "%r") return this.value / 100.0 * minorRadius;
    if (this.unit === "%") {
      const extent = axis === "x" ? box.width : axis === "y" ? box.height : Math.min(box.width, box.height);
      return this.value / 100.0 * extent;
    }
    if (fontPx === null) throw new UnitError("pt units need a reference font; none is in scope here");
    return this.value * fontPx;
  }

  equals(other: Length): boolean {
    return this.value === other.value && this.unit === other.unit;
  }

  toString(): string {
    return `${formatG(this.value)}${this.unit}`;
  }
}

/** True when `length` is a nonzero `%`/`%r` length whose resolved magnitude is under 1 px. */
export function isSubPixelLength(length: Length | null, value: number): boolean {
  return length !== null && (length.unit === "%" || length.unit === "%r") && Math.abs(value) > 0 && Math.abs(value) < 1;
}

/** A nonzero relative length never resolves to less than 1 px, when `min_1px:` switches this on (`enabled`). */
export function atLeastOnePx(length: Length | null, value: number, enabled: boolean): number {
  if (enabled && isSubPixelLength(length, value)) return value < 0 || Object.is(value, -0) ? -1.0 : 1.0;
  return value;
}

/** The units a size resolved before layout may use: `%` and `pt` need context that does not exist yet. */
export const SIZE_UNITS = ["px", "%r"] as const;

/** Resolve a `px`/`%r` length to whole device pixels, with no box in scope. */
export function pixelSize(length: Length | null, minorRadius: number, fallback = 24.0): number {
  if (length === null) return roundHalfEven(fallback);
  return Math.max(1, roundHalfEven(length.resolve(UNUSED_BOX, "minor", minorRadius)));
}

/** Degrees, 12 o'clock = 0, clockwise positive. */
export class Angle {
  readonly degrees: number;

  constructor(value: number) {
    this.degrees = value;
  }

  static parse(raw: unknown, what = "angle"): Angle {
    if (raw instanceof Angle) return raw;
    if (typeof raw === "boolean") throw new UnitError(`${what}: expected an angle, got a boolean`);
    if (isNumber(raw)) return new Angle(num(raw));
    if (typeof raw !== "string") throw new UnitError(`${what}: expected an angle such as '45deg', got ${repr(raw)}`);
    const m = ANGLE.exec(raw);
    if (!m) throw new UnitError(`${what}: ${repr(raw)} is not an angle.  Use deg, rad or turn, e.g. '45deg'`);
    let value = Number(m.groups!["num"]);
    const unit = m.groups!["unit"] ?? "deg";
    if (unit === "rad") value = degrees(value);
    else if (unit === "turn") value *= 360.0;
    return new Angle(value);
  }

  /** `Dc.drawArc`'s convention: 3 o'clock = 0, counter-clockwise positive. */
  toGarmin(): number {
    return pyMod(90.0 - this.degrees, 360.0);
  }

  toString(): string {
    return `${formatG(this.degrees)}deg`;
  }
}

/** A plain span of time, minutes, hours or days, whole numbers only: a `graph`'s `range:`. */
export class Duration {
  readonly seconds: number;

  constructor(seconds: number) {
    this.seconds = seconds;
  }

  static parse(raw: unknown, what = "duration"): Duration {
    if (raw instanceof Duration) return raw;
    if (typeof raw !== "string") throw new UnitError(`${what}: expected a duration such as '30m', '4h' or '7d', got ${repr(raw)}`);
    const m = DURATION.exec(raw);
    if (!m) throw new UnitError(`${what}: ${repr(raw)} is not a duration.  Use m, h or d, e.g. '30m', '4h', '7d'`);
    const factor = { m: 60, h: 3600, d: 86400 }[m.groups!["unit"] as "m" | "h" | "d"];
    return new Duration(Number(m.groups!["num"]) * factor);
  }

  toString(): string {
    if (this.seconds % 86400 === 0) return `${this.seconds / 86400}d`;
    if (this.seconds % 3600 === 0) return `${this.seconds / 3600}h`;
    return `${Math.floor(this.seconds / 60)}m`;
  }
}

/** The nine box positions, as (fraction of width, fraction of height), and the subscreen's centre. */
export const ANCHORS: ReadonlyMap<string, readonly [number, number]> = new Map([
  ["top_left", [0.0, 0.0]], ["top", [0.5, 0.0]], ["top_right", [1.0, 0.0]],
  ["left", [0.0, 0.5]], ["center", [0.5, 0.5]], ["right", [1.0, 0.5]],
  ["bottom_left", [0.0, 1.0]], ["bottom", [0.5, 1.0]], ["bottom_right", [1.0, 1.0]],
  // The centre of the parent box: layout passes a subscreen-anchored element the subscreen window as its parent.
  ["subscreen", [0.5, 0.5]],
] as const);

/** An axis-aligned rectangle in device pixels. */
export class Box {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;

  constructor(x: number, y: number, width: number, height: number) {
    this.x = x;
    this.y = y;
    this.width = width;
    this.height = height;
  }

  get left(): number { return this.x; }
  get top(): number { return this.y; }
  get right(): number { return this.x + this.width; }
  get bottom(): number { return this.y + this.height; }
  get centerX(): number { return this.x + this.width / 2.0; }
  get centerY(): number { return this.y + this.height / 2.0; }

  anchorPoint(anchor: string): [number, number] {
    const f = ANCHORS.get(anchor);
    if (f === undefined) throw new UnitError(`unknown anchor ${repr(anchor)}.  Valid anchors: ${[...ANCHORS.keys()].sort().join(", ")}`);
    return [this.x + f[0] * this.width, this.y + f[1] * this.height];
  }

  /**
   * Snap to whole pixels: each edge rounded half to even, the width and
   * height the difference of the rounded edges. With `min1px`, a box at
   * least 1 px wide or high never rounds to 0 there (the one tie
   * `atLeastOnePx`'s own clamp would otherwise lose).
   */
  rounded(min1px = false): IntBox {
    const left = roundHalfEven(this.x), top = roundHalfEven(this.y);
    let width = roundHalfEven(this.right) - left, height = roundHalfEven(this.bottom) - top;
    if (min1px) {
      if (this.width >= 1 && width < 1) width = 1;
      if (this.height >= 1 && height < 1) height = 1;
    }
    return new IntBox(left, top, width, height);
  }
}

/** A stand-in for `Length.resolve`'s box where there is none: `pixelSize` resolves only `px`/`%r`, which never read it. */
const UNUSED_BOX = new Box(0.0, 0.0, 0.0, 0.0);

/** A rectangle snapped to whole pixels: what reaches generated code. */
export class IntBox {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;

  constructor(x: number, y: number, width: number, height: number) {
    this.x = x;
    this.y = y;
    this.width = width;
    this.height = height;
  }

  get right(): number { return this.x + this.width; }
  get bottom(): number { return this.y + this.height; }

  union(other: IntBox): IntBox {
    const x = Math.min(this.x, other.x), y = Math.min(this.y, other.y);
    return new IntBox(x, y, Math.max(this.right, other.right) - x, Math.max(this.bottom, other.bottom) - y);
  }

  inflate(by: number): IntBox {
    return new IntBox(this.x - by, this.y - by, this.width + 2 * by, this.height + 2 * by);
  }

  /** Intersect with `(0, 0, width, height)`; a box off the frame clamps to an empty one, never a negative one. */
  clampTo(width: number, height: number): IntBox {
    const x0 = Math.max(0, Math.min(this.x, width)), y0 = Math.max(0, Math.min(this.y, height));
    const x1 = Math.max(0, Math.min(this.right, width)), y1 = Math.max(0, Math.min(this.bottom, height));
    return new IntBox(x0, y0, Math.max(0, x1 - x0), Math.max(0, y1 - y0));
  }

  get area(): number {
    return Math.max(0, this.width) * Math.max(0, this.height);
  }
}
