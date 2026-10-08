// Geometry edits on one device: a drag in device pixels written back in the
// author's own units, to the key that sets it on that device..
//
// The override target: a drag writes the most specific source of the key
// for the viewed device (the device-id override, then the `shape:` one,
// then the `display:` one, then the element's own key), unless the caller
// names the scope. Every
// unit is linear in pixels, so a pixel delta is a division; the value is
// rounded to the coarsest step that still lands on the dragged pixel, which
// is checked by placing the patched text through the real layout.
import type { Device } from "../devices/device.ts";
import type { BakedFont } from "../fonts/bmfont.ts";
import type { FileExists } from "../ir/builder/index.ts";
import { type Element, type Face, Group, Position, Shape } from "../ir/model.ts";
import { type Placed, type ResolvedFace, Resolver, resolve } from "../layout.ts";
import { degrees, formatFixed, formatG, hypot, radians, roundHalfEven } from "../py.ts";
import { type Axis, Box, Length, UnitError } from "../units.ts";
import { type Loaded, loadText } from "./gate.ts";
import { number, type Patch, patch as makePatch, setScalars, setValue } from "./patch.ts";
import { dotted, indexFor, isElement, type Path, Refused, type SpanIndex } from "./spans.ts";
import type { Data } from "./yaml.ts";

export type Scope = "auto" | "all" | "device" | "shape";

/** Rounding steps, coarsest first, per unit. */
export const LENGTH_STEPS: Readonly<Record<string, readonly number[]>> = {
  "px": [10, 5, 1, 0.5, 0.1],
  "%": [10, 5, 1, 0.5, 0.1, 0.05, 0.01],
  "%r": [10, 5, 1, 0.5, 0.1, 0.05, 0.01],
  "pt": [1, 0.5, 0.1, 0.05, 0.01],
};
export const ANGLE_STEPS: Readonly<Record<string, readonly number[]>> = {
  deg: [15, 5, 1, 0.5, 0.1, 0.05, 0.01],
  rad: [0.1, 0.05, 0.01, 0.005, 0.001, 0.0005],
  turn: [0.05, 0.01, 0.005, 0.001, 0.0005, 0.0001],
};
const DEGREES_PER: Readonly<Record<string, number>> = { deg: 1.0, rad: 180.0 / Math.PI, turn: 360.0 };

/** The extent `size:` gave: a gauge records it, since its ticks grow its box past it. */
function sized(placed: Placed, axis: 0 | 1): number {
  const size = (placed as { size?: unknown }).size;
  if (Array.isArray(size) && size.length === 2) return Math.trunc(size[axis] as number);
  const box = placed.innerBox;
  return axis === 0 ? box.width : box.height;
}

/** The extent keys a resize may change, and what it measures on the placed element to check that it landed. */
export const EXTENTS: ReadonlyMap<string, (p: Placed) => number> = new Map([
  ["size\0width", (p: Placed) => sized(p, 0)],
  ["size\0height", (p: Placed) => sized(p, 1)],
  ["radius", (p: Placed) => Math.trunc((p as unknown as { radius: number }).radius)],
  ["thickness", (p: Placed) => Math.trunc((p as unknown as { thickness: number }).thickness)],
]);

// -- the override target ------------------------------------------------------------

export function selectorPaths(device: Device): [Path, Path] {
  return [["overrides", device.id], ["overrides", `shape:${device.shape}`]];
}

/** The author path a geometry `key` of `element` is written to on `device`. */
export function target(index: SpanIndex, element: Path, key: Path, device: Device, scope: Scope = "auto"): Path {
  const [byDevice, byShape] = selectorPaths(device);
  if (scope === "device") return [...element, ...byDevice, ...key];
  if (scope === "shape") return [...element, ...byShape, ...key];
  if (scope === "auto") {
    for (const selector of [byDevice, byShape, ["overrides", `display:${device.displayClass}`]]) {
      if (index.get([...element, ...selector, ...key]) !== undefined) return [...element, ...selector, ...key];
    }
  }
  return [...element, ...key];
}

// -- units -----------------------------------------------------------------------

/** How the author writes a value: its unit, and whether as a bare number. */
export class Spelling {
  readonly unit: string;
  readonly bare: boolean;

  constructor(unit: string, bare = false) {
    this.unit = unit;
    this.bare = bare;
  }

  write(value: number): Data {
    if (this.bare) return Number.isInteger(value) ? value : Number(number(value));
    return `${number(value)}${this.unit}`;
  }
}

export function lengthSpelling(raw: Data | undefined): Spelling {
  return new Spelling(Length.parse(raw).unit, typeof raw !== "string");
}

export function angleSpelling(raw: Data | undefined): Spelling {
  if (typeof raw !== "string") return new Spelling("deg", true);
  const text = raw.trim();
  const unit = ["turn", "rad", "deg"].find((u) => text.endsWith(u)) ?? "deg";
  return new Spelling(unit, !text.endsWith(unit));
}

export function pxPerUnit(unit: string, axis: Axis, parent: Box, minorRadius: number, fontPx: number | null = null): number {
  if (unit === "px") return 1.0;
  if (unit === "%r") return minorRadius / 100.0;
  if (unit === "%") return (axis === "x" ? parent.width : axis === "y" ? parent.height : Math.min(parent.width, parent.height)) / 100.0;
  if (unit === "pt") {
    if (fontPx === null) throw new Refused("a pt length has no pixel size here; write it in px, % or %r");
    return fontPx;
  }
  throw new Refused(`unknown unit '${unit}'`);
}

/** `round(round(value / step) * step, 6)`. */
export function rounded(value: number, step: number): number {
  return Number(formatFixed(roundHalfEven(value / step) * step, 6));
}

/** `ideal` rounded to each step, coarsest first, keeping those within half a pixel, each once; the finest always. */
export function candidates(ideal: number, steps: readonly number[], pxPer: number): number[] {
  const out: number[] = [];
  for (const step of steps) {
    const value = rounded(ideal, step);
    if (Math.abs(value - ideal) * Math.abs(pxPer) < 0.5 && !out.includes(value)) out.push(value);
  }
  const finest = rounded(ideal, steps[steps.length - 1]!);
  if (!out.includes(finest)) out.push(finest);
  return out;
}

// -- the viewed device -------------------------------------------------------------

/** Bakes a face's fonts for one device. */
export type Baker = (face: Face, device: Device) => Map<string, BakedFont>;

/** One design's text placed on one device: the face, its baked fonts, its layout and its author index. */
export class View {
  readonly path: string;
  readonly device: Device;
  readonly fileExists: FileExists;
  readonly bake: Baker;
  readonly index: SpanIndex;
  readonly loaded: Loaded;
  readonly face: Face;
  readonly fonts: Map<string, BakedFont>;
  readonly resolved: ResolvedFace;
  /** The last text placed, loaded: what a caller's gate can reuse. */
  tried: Loaded | null = null;

  constructor(path: string, text: string, device: Device, fileExists: FileExists, bake: Baker,
    { loaded = null, resolved = null }: { loaded?: Loaded | null; resolved?: ResolvedFace | null } = {}) {
    this.path = path;
    this.device = device;
    this.fileExists = fileExists;
    this.bake = bake;
    this.index = indexFor(text);
    this.loaded = loaded !== null && loaded.text === text ? loaded : loadText(path, text, fileExists);
    if (this.loaded.face === null) {
      throw new Refused("the design does not load: " + this.loaded.errors.slice(0, 1).map((d) => d.message).join("; "));
    }
    this.face = this.loaded.face;
    if (resolved !== null && resolved.face === this.face) {
      this.fonts = resolved.fonts;
      this.resolved = resolved;
    } else {
      this.fonts = bake(this.face, device);
      this.resolved = this.place(this.loaded);
    }
  }

  place(loaded: Loaded, rebake = false): ResolvedFace {
    const face = loaded.face!;
    return resolve(face, this.device, rebake ? this.bake(face, this.device) : this.fonts);
  }

  placed(elementId: string, resolved: ResolvedFace | null = null): Placed {
    const found = (resolved ?? this.resolved).items.find((item) => item.id === elementId);
    if (found === undefined) throw new Refused(`${elementId} is not drawn on ${this.device.id}`);
    return found;
  }

  element(elementId: string): Element {
    const found = this.face.walk().find((e) => e.id === elementId);
    if (found === undefined) throw new Refused(`there is no element called ${elementId}`);
    return found;
  }

  authorPath(elementId: string): Path {
    const entry = this.index.atSpan(this.element(elementId).span);
    if (entry === undefined || !isElement(this.index, entry)) {
      // the `static:` block's own group, or a layout's: a container, not an element
      throw new Refused(`${elementId} is a block, not an element: move what is in it`);
    }
    return entry.path;
  }

  /** The element with this device's overrides merged in. */
  effective(elementId: string): Element {
    return new Resolver(this.face, this.device, this.fonts).forDevice(this.element(elementId));
  }

  parentBox(elementId: string): Box {
    const element = this.element(elementId);
    const parent = parentGroup(this.face.elements, element);
    if (parent !== null) {
      const b = this.placed(parent.id).box;
      return new Box(b.x, b.y, b.width, b.height);
    }
    if (element.inSubscreen && this.device.subscreen !== null) return new Box(...this.device.subscreen);
    return new Box(0, 0, this.device.width, this.device.height);
  }

  tryPatch(patch: Patch, elementId: string, rebake = false): Placed | null {
    const loaded = loadText(this.path, patch.text, this.fileExists);
    this.tried = loaded;
    if (loaded.face === null) return null;
    return this.placed(elementId, this.place(loaded, rebake));
  }
}

function parentGroup(elements: readonly Element[], target: Element): Group | null {
  for (const element of elements) {
    if (element instanceof Group) {
      if (element.items.some((child) => child === target || child.id === target.id)) return element;
      const found = parentGroup(element.items, target);
      if (found !== null) return found;
    }
  }
  return null;
}

// -- moves and resizes -----------------------------------------------------------

/** A geometry edit in the author's units: the patch, and whether it landed on the dragged pixel. */
export interface Converted {
  patch: Patch;
  landed: boolean;
}

/** One author key a move or resize writes, and its candidate values, coarsest first. */
interface Key {
  write: Path;
  spelling: Spelling;
  values: number[];
}

function apply(index: SpanIndex, keys: Key[], level: number): Patch {
  const whats = keys.map((k) => dotted(k.write)).join(", ");
  const valueAt = (k: Key): Data => k.spelling.write(k.values[Math.min(level, k.values.length - 1)]!);
  // keys already written are rewritten in place, with no index between them
  const together = setScalars(index, keys.map((k): [Path, Data] => [k.write, valueAt(k)]));
  if (together !== undefined) return makePatch(together.text, together.expected, `set ${whats}`);
  let result: Patch | null = null;
  let current = index;
  for (const key of keys) {
    result = setValue(current, key.write, valueAt(key));
    current = indexFor(result.text);
  }
  return makePatch(result!.text, result!.expected, `set ${whats}`);
}

function settle(view: View, keys: Key[], elementId: string, landed: (p: Placed) => boolean, rebake = false): Converted {
  if (keys.length === 0) return { patch: makePatch(view.index.text, view.index.data, "nothing to change"), landed: true };
  const levels = Math.max(...keys.map((k) => k.values.length));
  let result: Patch | null = null;
  for (let level = 0; level < levels; level++) {
    result = apply(view.index, keys, level);
    const placed = view.tryPatch(result, elementId, rebake);
    if (placed !== null && landed(placed)) return { patch: result, landed: true };
  }
  return { patch: result!, landed: false };
}

function dataAt(index: SpanIndex, path: Path): Data {
  let data: Data = index.data;
  for (const step of path) data = data instanceof Map ? data.get(step)! : (data as Data[])[step as number]!;
  return data;
}

/** The keys a move of `position` (`at:` or a line's `to:`) by `(dx, dy)` px writes. */
function positionKeys(view: View, elementId: string, element: Path, prefix: string, position: Position,
  dx: number, dy: number, scope: Scope): Key[] {
  const parent = view.parentBox(elementId);
  const minor = view.device.minorRadius;
  const index = view.index;
  const source = (key: string): Data | undefined => {
    const entry = index.get(target(index, element, [prefix, key], view.device));
    return entry !== undefined ? dataAt(index, entry.path) : undefined;
  };
  const keys: Key[] = [];
  if (position.isPolar) {
    const rRaw = source("radius"), aRaw = source("angle");
    const rSpell = lengthSpelling(rRaw ?? position.radius!.toString());
    const aSpell = angleSpelling(aRaw ?? `${formatG(position.angle!.degrees)}deg`);
    const rPer = pxPerUnit(rSpell.unit, "minor", parent, minor);
    const rPx = position.radius!.resolve(parent, "minor", minor);
    const theta = radians(position.angle!.degrees);
    const ox = rPx * Math.sin(theta) + dx, oy = -rPx * Math.cos(theta) + dy;
    const newR = hypot(ox, oy);
    let newDeg = newR ? degrees(Math.atan2(ox, -oy)) : position.angle!.degrees;
    // stay on the author's side of the circle: 350deg dragged a little clockwise is 352deg, not -8deg
    newDeg += 360.0 * roundHalfEven((position.angle!.degrees - newDeg) / 360.0);
    const perDeg = DEGREES_PER[aSpell.unit]!;
    const aPer = radians(perDeg) * Math.max(newR, 1.0);
    keys.push({ write: target(index, element, [prefix, "angle"], view.device, scope), spelling: aSpell,
      values: candidates(newDeg / perDeg, ANGLE_STEPS[aSpell.unit]!, aPer) });
    keys.push({ write: target(index, element, [prefix, "radius"], view.device, scope), spelling: rSpell,
      values: candidates(newR / rPer, LENGTH_STEPS[rSpell.unit]!, rPer) });
    return keys;
  }
  for (const [key, delta, axis, length] of [["dx", dx, "x", position.dx], ["dy", dy, "y", position.dy]] as const) {
    if (!delta) continue;
    const raw = source(key);
    let spelling: Spelling;
    if (raw !== undefined) {
      spelling = lengthSpelling(raw);
    } else {
      const sibling = source(key === "dx" ? "dy" : "dx");
      spelling = sibling !== undefined ? lengthSpelling(sibling) : new Spelling("%r");
    }
    if (spelling.unit === "pt") {
      throw new Refused(`${dotted([...element, prefix, key])} is in pt, which has no pixel size for a position; write it in px, % or %r`);
    }
    const per = pxPerUnit(spelling.unit, axis, parent, minor);
    const current = length !== null ? length.resolve(parent, axis, minor) / per : 0.0;
    keys.push({ write: target(index, element, [prefix, key], view.device, scope), spelling,
      values: candidates(current + delta / per, LENGTH_STEPS[spelling.unit]!, per) });
  }
  return keys;
}

export type Part = "both" | "at" | "to";

/** Move `elementId` by `(dx, dy)` device pixels; a line's `part` "at" or "to" moves that end alone. */
export function move(view: View, elementId: string, dx: number, dy: number, scope: Scope = "auto", part: Part = "both"): Converted {
  const element = view.authorPath(elementId);
  const effective = view.effective(elementId);
  if (effective instanceof Shape && effective.shape === "polygon") throw new Refused(`${elementId} is a polygon: move its points: in the text`);
  const line = effective instanceof Shape && effective.shape === "line";
  if (part !== "both" && !line) throw new Refused(`${elementId} is not a line: it has no ends to move apart`);
  const before = view.placed(elementId);
  const keys: Key[] = [];
  const checks: ((p: Placed) => boolean)[] = [];
  if (part === "both" || part === "at") {
    keys.push(...positionKeys(view, elementId, element, "at", effective.at, dx, dy, scope));
    const goal = [before.center[0] + dx, before.center[1] + dy];
    checks.push((p) => p.center[0] === goal[0] && p.center[1] === goal[1]);
  }
  if (line && (part === "both" || part === "to")) {
    const to = (effective as Shape).to ?? new Position();
    keys.push(...positionKeys(view, elementId, element, "to", to, dx, dy, scope));
    const end = (before as unknown as { end: [number, number] }).end;
    const endGoal = [end[0] + dx, end[1] + dy];
    checks.push((p) => {
      const e = (p as unknown as { end: [number, number] }).end;
      return e[0] === endGoal[0] && e[1] === endGoal[1];
    });
  }
  return settle(view, keys, elementId, (p) => checks.every((c) => c(p)));
}

/** The angle keys `turn` writes. */
export const ANGLES: ReadonlySet<string> = new Set(["start_angle", "sweep"]);

/** Set an arc's `key` to `degreesValue` (12 o'clock = 0, clockwise) in the author's unit. */
export function turn(view: View, elementId: string, key: string, degreesValue: number, scope: Scope = "auto"): Converted {
  if (!ANGLES.has(key)) throw new Refused(`${key} is not start_angle or sweep`);
  const element = view.authorPath(elementId);
  const effective = view.effective(elementId) as unknown as Record<string, unknown>;
  const shape = effective["shape"];
  const placed = view.placed(elementId) as unknown as Record<string, unknown>;
  if ((shape !== undefined && shape !== "arc") || !(key in effective) || !(key in placed)) throw new Refused(`${elementId} has no ${key}`);
  const entry = view.index.get(target(view.index, element, [key], view.device));
  const spelling = entry !== undefined ? angleSpelling(dataAt(view.index, entry.path)) : new Spelling("deg");
  const per = DEGREES_PER[spelling.unit]!;
  const keys = [{ write: target(view.index, element, [key], view.device, scope), spelling,
    values: candidates(degreesValue / per, ANGLE_STEPS[spelling.unit]!, per) }];
  return settle(view, keys, elementId, (p) => Math.abs(Number((p as unknown as Record<string, number>)[key]) - degreesValue) < 0.5);
}

/** Change the extent `key` (`["size", "width"]`, `["radius"]`, `["thickness"]`) by `delta` device pixels. */
export function resize(view: View, elementId: string, key: readonly string[], delta: number, scope: Scope = "auto"): Converted {
  const measure = EXTENTS.get(key.join("\0"));
  if (measure === undefined) throw new Refused(`${dotted(key)} is not a size, radius or thickness`);
  const element = view.authorPath(elementId);
  const effective = view.effective(elementId);
  let length: unknown = effective;
  for (const step of key) length = length !== null && typeof length === "object" ? (length as Record<string, unknown>)[step] : undefined;
  if (!(length instanceof Length)) throw new Refused(`${elementId} has no ${dotted(key)} to resize`);
  const goal = measure(view.placed(elementId)) + delta;
  if (goal < 1) throw new Refused(`${elementId}'s ${dotted(key)} cannot be smaller than 1 px`);
  const entry = view.index.get(target(view.index, element, key, view.device));
  const spelling = entry !== undefined ? lengthSpelling(dataAt(view.index, entry.path)) : new Spelling(length.unit);
  const axis: Axis = key[key.length - 1] === "width" ? "x" : key[key.length - 1] === "height" ? "y" : "minor";
  const per = pxPerUnit(spelling.unit, axis, view.parentBox(elementId), view.device.minorRadius);
  let current: number;
  try {
    current = length.resolve(view.parentBox(elementId), axis, view.device.minorRadius) / per;
  } catch (error) {
    if (error instanceof UnitError) throw new Refused(error.message);
    throw error;
  }
  const keys = [{ write: target(view.index, element, key, view.device, scope), spelling,
    values: candidates(current + delta / per, LENGTH_STEPS[spelling.unit]!, per) }];
  return settle(view, keys, elementId, (p) => measure(p) === goal, effective.kind === "icon");
}
