// Geometry edits on one device: a drag in device pixels written back in the
// author's own units, to the key that sets it on that device.
//
// The subject of a gesture is an element (its id) or a part of one
// (`PartTarget`: a hand's, a pattern's or a needle's part, located in the
// text and drawn at an angle). A part lives in its own frame, origin at the
// axis and +y down, turned by the angle it is drawn at, so a delta on the
// screen is turned back into that frame first (`toLocal`). Its lengths are
// px or %r, which the frame's zero-sized box resolves (`HAND_FRAME`), and in
// a linear or grid pattern also %, of the box the pattern sits in, or in a
// needle %, of a square of that box's smaller side (`PartTarget.frame`).
//
// The override target: a drag writes the most specific source of the key
// for the viewed device (the device-id override, then the `shape:` one,
// then the `display:` one, then the element's own key), unless the caller
// names the scope. An override replaces the element's key whole, so a
// scope that has no `at:`/`size:` yet first gets a copy of the one the
// device reads, and the drag then changes one leaf of that copy. Every
// unit is linear in pixels, so a pixel delta is a division; the value is
// rounded to the coarsest step that still lands on the dragged pixel, which
// is checked by placing the patched text through the real layout.
import type { Device } from "../devices/device.ts";
import type { BakedFont } from "../fonts/bmfont.ts";
import type { FileExists } from "../ir/builder/index.ts";
import {
  type AnyHandPart, type Element, type Face, type Gauge, Group, type HandsElement, type PatternElement, Position, Shape,
} from "../ir/model.ts";
import {
  type Placed, PlacedGauge, PlacedHands, PlacedPattern, PlacedText, type ResolvedFace, type ResolvedHandPart, ResolveError, Resolver, resolve,
  roundHalfAway,
} from "../layout.ts";
import { degrees, floorMod, formatFixed, formatG, hypot, radians, roundHalfEven } from "../py.ts";
import { type Axis, Box, Length, UnitError } from "../units.ts";
import { userNames } from "./colors.ts";
import { type Loaded, loadText } from "./gate.ts";
import { child, insertItem, number, type Patch, patch as makePatch, removeItem, setScalars, setValue } from "./patch.ts";
import { dotted, indexFor, isElement, type Path, Refused, type SpanIndex } from "./spans.ts";
import type { Data } from "./yaml.ts";

/**
 * Where a geometry edit is written: `all` the element's own key, `device`,
 * `shape` and `display` the viewed device's override of that selector, and
 * `auto` the most specific source the viewed device reads.
 */
export type Scope = "auto" | "all" | "device" | "shape" | "display";
export const SCOPES: readonly Scope[] = ["auto", "all", "device", "shape", "display"];

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

/** The `overrides:` selectors `device` reads, most specific first: its id, its shape, its display class. */
export function selectorPaths(device: Device): [Path, Path, Path] {
  return [["overrides", device.id], ["overrides", `shape:${device.shape}`], ["overrides", `display:${device.displayClass}`]];
}

/** The selector a named override scope writes on `device`: `fr955`, `shape:round`, `display:amoled`. */
export function selectorFor(device: Device, scope: "device" | "shape" | "display"): string {
  const [byDevice, byShape, byDisplay] = selectorPaths(device);
  return String((scope === "device" ? byDevice : scope === "shape" ? byShape : byDisplay)[1]);
}

/** The author path a geometry `key` of `element` is written to on `device`. */
export function target(index: SpanIndex, element: Path, key: Path, device: Device, scope: Scope = "auto"): Path {
  const [byDevice, byShape, byDisplay] = selectorPaths(device);
  if (scope === "device") return [...element, ...byDevice, ...key];
  if (scope === "shape") return [...element, ...byShape, ...key];
  if (scope === "display") return [...element, ...byDisplay, ...key];
  if (scope === "auto") {
    // An override's key is read whole, so a leaf goes under it even when the override does not hold that leaf yet.
    for (const selector of [byDevice, byShape, byDisplay]) {
      if (index.get([...element, ...selector, key[0]!]) !== undefined) return [...element, ...selector, ...key];
    }
  }
  return [...element, ...key];
}

/** `value`'s mappings and lists copied, so a seeded override shares no node with its source. */
function cloned(value: Data): Data {
  if (value instanceof Map) return new Map([...value].map(([k, v]) => [k, cloned(v)]));
  if (Array.isArray(value)) return value.map(cloned);
  return value;
}

/**
 * `index` with the override that `scope` names on `device` holding the
 * whole of `element`'s `head` key (`at` or `size`): a copy of the one the
 * device reads today, or `{anchor: center}` for an `at:` the element never
 * wrote. An override replaces the key whole, so a leaf written under it
 * next must not leave a partial key behind. Unchanged for `auto` and `all`,
 * and when the override already holds the key.
 */
export function seeded(index: SpanIndex, element: Path, head: string, device: Device, scope: Scope): SpanIndex {
  if (scope === "auto" || scope === "all") return index;
  const place = [...element, "overrides", selectorFor(device, scope), head];
  if (index.get(place) !== undefined) return index;
  const source = index.get(target(index, element, [head], device));
  let value: Data;
  if (source !== undefined) value = cloned(dataAt(index, source.path));
  else if (head === "at") value = new Map<string, Data>([["anchor", "center"]]);
  else return index;
  if (!(value instanceof Map)) return index;
  return indexFor(setValue(index, place, value).text);
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

  /** `loaded` laid out on the device; refused, with the reason, when it cannot be. */
  place(loaded: Loaded, rebake = false): ResolvedFace {
    const face = loaded.face!;
    try {
      return resolve(face, this.device, rebake ? this.bake(face, this.device) : this.fonts);
    } catch (error) {
      if (error instanceof ResolveError) throw new Refused(error.message);
      throw error;
    }
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

function settle(view: View, index: SpanIndex, keys: Key[], elementId: string, landed: (p: Placed) => boolean, rebake = false): Converted {
  // nothing to change writes nothing: not even the override a seeded `index` holds
  if (keys.length === 0) return { patch: makePatch(view.index.text, view.index.data, "nothing to change"), landed: true };
  const levels = Math.max(...keys.map((k) => k.values.length));
  let result: Patch | null = null;
  for (let level = 0; level < levels; level++) {
    result = apply(index, keys, level);
    const placed = view.tryPatch(result, elementId, rebake);
    if (placed !== null && landed(placed)) return { patch: result, landed: true };
  }
  return { patch: result!, landed: false };
}

function dataAt(index: SpanIndex, path: Path): Data {
  let data: Data = index.data;
  for (const step of path) data = child(data, step);
  return data;
}

/**
 * The keys a move of `position` (an `at:`, a line's `to:`, one of a
 * polygon's `points`) by `(dx, dy)` px writes, on `index` (the view's text,
 * seeded): the keys under `[...owner, ...prefix]`, resolved against
 * `parent`. With `overridable`, the key the viewed device reads, or the
 * `scope` named, is written (an `at:`); a point or a part's position has
 * no overrides and is written where it is.
 */
function positionKeys(view: View, index: SpanIndex, owner: Path, prefix: Path, position: Position,
  dx: number, dy: number, scope: Scope, parent: Box, overridable = true): Key[] {
  const minor = view.device.minorRadius;
  const place = (key: string, forWriting: boolean): Path =>
    (overridable ? target(index, owner, [...prefix, key], view.device, forWriting ? scope : "auto") : [...owner, ...prefix, key]);
  const source = (key: string): Data | undefined => {
    const entry = index.get(place(key, false));
    return entry !== undefined ? dataAt(index, entry.path) : undefined;
  };
  const per = (unit: string, axis: Axis): number => {
    const value = pxPerUnit(unit, axis, parent, minor);
    if (!value) throw new Refused(`${dotted([...owner, ...prefix])} is in %, which has no extent in this part's frame (a radial pattern's or a hand's); write it in px or %r`);
    return value;
  };
  const keys: Key[] = [];
  if (position.isPolar) {
    const rRaw = source("radius"), aRaw = source("angle");
    const rSpell = lengthSpelling(rRaw ?? position.radius!.toString());
    const aSpell = angleSpelling(aRaw ?? `${formatG(position.angle!.degrees)}deg`);
    const rPer = per(rSpell.unit, "minor");
    const rPx = position.radius!.resolve(parent, "minor", minor);
    const theta = radians(position.angle!.degrees);
    const ox = rPx * Math.sin(theta) + dx, oy = -rPx * Math.cos(theta) + dy;
    const newR = hypot(ox, oy);
    let newDeg = newR ? degrees(Math.atan2(ox, -oy)) : position.angle!.degrees;
    // stay on the author's side of the circle: 350deg dragged a little clockwise is 352deg, not -8deg
    newDeg += 360.0 * roundHalfEven((position.angle!.degrees - newDeg) / 360.0);
    const perDeg = DEGREES_PER[aSpell.unit]!;
    const aPer = radians(perDeg) * Math.max(newR, 1.0);
    keys.push({ write: place("angle", true), spelling: aSpell, values: candidates(newDeg / perDeg, ANGLE_STEPS[aSpell.unit]!, aPer) });
    keys.push({ write: place("radius", true), spelling: rSpell, values: candidates(newR / rPer, LENGTH_STEPS[rSpell.unit]!, rPer) });
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
      throw new Refused(`${dotted([...owner, ...prefix, key])} is in pt, which has no pixel size for a position; write it in px, % or %r`);
    }
    const pxPer = per(spelling.unit, axis);
    const current = length !== null ? length.resolve(parent, axis, minor) / pxPer : 0.0;
    keys.push({ write: place(key, true), spelling, values: candidates(current + delta / pxPer, LENGTH_STEPS[spelling.unit]!, pxPer) });
  }
  return keys;
}

export type Part = "both" | "at" | "to";

/**
 * Move `subject` by `(dx, dy)` device pixels: an element's `at:` (a line's
 * `to:` with it; `part` "at" or "to" moves that end alone), every point of
 * a polygon element, or a part (`movePart`).
 */
export function move(view: View, subject: Subject, dx: number, dy: number, scope: Scope = "auto", part: Part = "both"): Converted {
  if (isPart(subject)) return movePart(view, subject, dx, dy, scope, part);
  const elementId = subject;
  const element = view.authorPath(elementId);
  const effective = view.effective(elementId);
  const line = effective instanceof Shape && effective.shape === "line";
  if (part !== "both" && !line) throw new Refused(`${elementId} is not a line: it has no ends to move apart`);
  if (effective instanceof Shape && effective.shape === "polygon") return movePolygon(view, elementId, dx, dy, scope);
  const before = view.placed(elementId);
  const parent = view.parentBox(elementId);
  const keys: Key[] = [];
  const checks: ((p: Placed) => boolean)[] = [];
  // a named scope writes the whole at: there (a line's to: is no override key, and the gate says so)
  const index = part === "to" ? view.index : seeded(view.index, element, "at", view.device, scope);
  if (part === "both" || part === "at") {
    keys.push(...positionKeys(view, index, element, ["at"], effective.at, dx, dy, scope, parent));
    const goal = [before.center[0] + dx, before.center[1] + dy];
    checks.push((p) => p.center[0] === goal[0] && p.center[1] === goal[1]);
  }
  if (line && (part === "both" || part === "to")) {
    const to = (effective as Shape).to ?? new Position();
    keys.push(...positionKeys(view, index, element, ["to"], to, dx, dy, scope, parent));
    const end = (before as unknown as { end: [number, number] }).end;
    const endGoal = [end[0] + dx, end[1] + dy];
    checks.push((p) => {
      const e = (p as unknown as { end: [number, number] }).end;
      return e[0] === endGoal[0] && e[1] === endGoal[1];
    });
  }
  return settle(view, index, keys, elementId, (p) => checks.every((c) => c(p)));
}

/** The angle keys `turn` writes. */
export const ANGLES: ReadonlySet<string> = new Set(["start_angle", "sweep"]);

/** Set an arc's `key` to `degreesValue` (12 o'clock = 0, clockwise) in the author's unit; on an arc part, `turnPart`. */
export function turn(view: View, subject: Subject, key: string, degreesValue: number, scope: Scope = "auto"): Converted {
  if (isPart(subject)) return turnPart(view, subject, key, degreesValue, scope);
  const elementId = subject;
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
  return settle(view, view.index, keys, elementId, (p) => Math.abs(Number((p as unknown as Record<string, number>)[key]) - degreesValue) < 0.5);
}

/** Change the extent `key` (`["size", "width"]`, `["radius"]`, `["thickness"]`) by `delta` device pixels; on a part, `resizePart`. */
export function resize(view: View, subject: Subject, key: readonly string[], delta: number, scope: Scope = "auto"): Converted {
  if (isPart(subject)) return resizePart(view, subject, key, delta, scope);
  if (key.length === 2 && key[0] === "font" && key[1] === "size") return resizeFont(view, subject, delta, scope);
  const elementId = subject;
  const measure = EXTENTS.get(key.join("\0"));
  if (measure === undefined) throw new Refused(`${dotted(key)} is not a size, radius or thickness`);
  const element = view.authorPath(elementId);
  const effective = view.effective(elementId);
  let length: unknown = effective;
  for (const step of key) length = length !== null && typeof length === "object" ? (length as Record<string, unknown>)[step] : undefined;
  if (!(length instanceof Length)) throw new Refused(`${elementId} has no ${dotted(key)} to resize`);
  const goal = measure(view.placed(elementId)) + delta;
  if (goal < 1) throw new Refused(`${elementId}'s ${dotted(key)} cannot be smaller than 1 px`);
  // a named scope writes the whole size: there; a radius is one scalar
  const index = key.length > 1 ? seeded(view.index, element, key[0]!, view.device, scope) : view.index;
  const entry = index.get(target(index, element, key, view.device));
  const spelling = entry !== undefined ? lengthSpelling(dataAt(index, entry.path)) : new Spelling(length.unit);
  const axis: Axis = key[key.length - 1] === "width" ? "x" : key[key.length - 1] === "height" ? "y" : "minor";
  const per = pxPerUnit(spelling.unit, axis, view.parentBox(elementId), view.device.minorRadius);
  let current: number;
  try {
    current = length.resolve(view.parentBox(elementId), axis, view.device.minorRadius) / per;
  } catch (error) {
    if (error instanceof UnitError) throw new Refused(error.message);
    throw error;
  }
  const keys = [{ write: target(index, element, key, view.device, scope), spelling,
    values: candidates(current + delta / per, LENGTH_STEPS[spelling.unit]!, per) }];
  return settle(view, index, keys, elementId, (p) => measure(p) === goal, effective.kind === "icon");
}

/** The key that sizes a font. */
export const FONT_SIZE: readonly string[] = ["font", "size"];

/**
 * Grow a text's baked font by `delta` pixels: the element's own `font.size`
 * when its font is written inline, or the shared `resources: fonts:`
 * entry's `size:` when only this element draws with it (another element
 * using it would change too, so that is refused, naming them). A font's
 * size is the same on every watch, so there is no override to write. The
 * landing is checked with the fonts baked again at each candidate size,
 * since the size a sheet is baked at is what places the text.
 */
function resizeFont(view: View, elementId: string, delta: number, scope: Scope): Converted {
  if (scope === "device" || scope === "shape" || scope === "display") {
    throw new Refused(`a font's size is the same on every watch: ${elementId}'s font has no override to write`);
  }
  const element = view.authorPath(elementId);
  const placed = view.placed(elementId);
  if (!(placed instanceof PlacedText) || !placed.font.is_custom || placed.font.is_vector) {
    throw new Refused(`${elementId} does not draw in a font baked from a file, so it has no size to change here`);
  }
  const written = view.index.get([...element, "font"]) !== undefined ? dataAt(view.index, [...element, "font"]) : undefined;
  let sizePath: Path;
  if (written instanceof Map) {
    sizePath = [...element, "font", "size"];
  } else if (typeof written === "string" && written.startsWith("font.")) {
    const name = written.slice("font.".length);
    const others = userNames(view.index, name, "font.").filter((user) => user !== elementId);
    if (others.length > 0) {
      throw new Refused(`the font ${name} is shared with ${others.join(", ")}: change its size in the Face tab's Fonts, or give ${elementId} its own font`);
    }
    sizePath = ["resources", "fonts", name, "size"];
  } else {
    throw new Refused(`${elementId}'s font is not written where its size can be changed`);
  }
  if (view.index.get(sizePath) === undefined) throw new Refused(`${dotted(sizePath)} is not written`);
  const raw = dataAt(view.index, sizePath);
  const spelling = lengthSpelling(raw);
  if (spelling.unit !== "px" && spelling.unit !== "%r") throw new Refused(`${dotted(sizePath)} is in ${spelling.unit}; a font's size is px or %r`);
  const goal = placed.font.px + delta;
  if (goal < 1) throw new Refused(`${elementId}'s font cannot be smaller than 1 px`);
  const per = pxPerUnit(spelling.unit, "minor", HAND_FRAME, view.device.minorRadius);
  const current = Length.parse(raw).resolve(HAND_FRAME, "minor", view.device.minorRadius) / per;
  const keys = [{ write: sizePath, spelling, values: candidates(current + delta / per, LENGTH_STEPS[spelling.unit]!, per) }];
  return settle(view, view.index, keys, elementId, (p) => p instanceof PlacedText && p.font.px === goal, true);
}

// -- parts ---------------------------------------------------------------------------

/** A part's own frame: zero-sized at the axis, so `%` has no extent and `%r` is the screen's minor radius. */
export const HAND_FRAME = new Box(0.0, 0.0, 0.0, 0.0);

/**
 * A part a gesture is made on: where it is written (`path`, its author
 * path), the element whose placement draws it (`elementId`: a `hands`
 * element placing its set, the pattern, the gauge), its hand for a hand
 * part, its id (the author's key, or `partN` in the list form), the
 * screen position of its frame's origin and the angle it is drawn at, in
 * degrees clockwise from 12 o'clock, and how a history label names it
 * ("hour.blade of clock").
 */
export interface PartTarget {
  path: Path;
  elementId: string;
  hand: string | null;
  id: string;
  origin: [number, number];
  angle: number;
  name: string;
  /** The box the part's `%` lengths measure against: a linear or grid pattern's parent box, a needle's square; `HAND_FRAME` when omitted. */
  frame?: Box;
}

/** The box `target`'s `%` lengths measure against. */
const frameOf = (target: PartTarget): Box => target.frame ?? HAND_FRAME;

/** What a gesture is made on: an element, by id, or a part. */
export type Subject = string | PartTarget;

export function isPart(subject: Subject): subject is PartTarget {
  return typeof subject !== "string";
}

/** `(dx, dy)` on the screen as a delta in the frame of something drawn turned by `angle` degrees. */
export function toLocal(dx: number, dy: number, angle: number): [number, number] {
  const theta = radians(angle);
  const c = Math.cos(theta), s = Math.sin(theta);
  // a component that is zero but for the trigonometry's last digit writes no key
  const exact = (v: number): number => (Math.abs(v) < 1e-9 ? 0 : v);
  return [exact(dx * c + dy * s), exact(-dx * s + dy * c)];
}

/** A position in a part's own frame, in px, exactly as the layout resolves it (an offset from the origin, `%` measured against `frame`). */
export function localPoint(at: Position, minorRadius: number, frame: Box = HAND_FRAME): [number, number] {
  if (at.angle !== null) {
    const radius = at.radius !== null ? at.radius.resolve(frame, "minor", minorRadius) : 0;
    const theta = radians(at.angle.degrees);
    return [radius * Math.sin(theta), -radius * Math.cos(theta)];
  }
  return [at.dx !== null ? at.dx.resolve(frame, "x", minorRadius) : 0, at.dy !== null ? at.dy.resolve(frame, "y", minorRadius) : 0];
}

/** Whether a `mirror: x` part's point lies on the axis, so the mirror shares it rather than reflecting it. */
export function onAxis(point: Position): boolean {
  if (point.isPolar) return floorMod(point.angle!.degrees, 180) === 0;
  return point.dx === null || point.dx.value === 0;
}

/** The IR part and its resolved geometry that `target` names in `placed`, the element drawing it, on `face`. */
export function partOf(face: Face, placed: Placed, target: PartTarget): [AnyHandPart, ResolvedHandPart] {
  let built: readonly AnyHandPart[] | undefined, drawn: readonly ResolvedHandPart[] | undefined;
  if (placed instanceof PlacedHands && target.hand !== null) {
    const set = face.hands.get((placed.element as HandsElement).hands);
    const hand = set !== undefined ? (set as unknown as Record<string, { parts: AnyHandPart[] } | null>)[target.hand] : null;
    built = hand?.parts;
    drawn = (placed as unknown as Record<string, { parts: ResolvedHandPart[] } | null>)[target.hand]?.parts;
  } else if (placed instanceof PlacedPattern) {
    built = (placed.element as PatternElement).parts;
    drawn = placed.parts;
  } else if (placed instanceof PlacedGauge) {
    built = (placed.element as Gauge).needle;
    drawn = placed.needle;
  }
  const ir = built?.find((p) => p.id === target.id);
  const resolved = drawn?.find((p) => p.id === target.id);
  if (ir === undefined || resolved === undefined) throw new Refused(`${target.name} is not drawn on ${placed.element.id}`);
  return [ir, resolved];
}

/** The part's mapping as written, and how many points its `points:` lists. */
function writtenPart(view: View, target: PartTarget): [Map<unknown, unknown>, number] {
  const data = dataAt(view.index, target.path);
  if (!(data instanceof Map)) throw new Refused(`${target.name} is not a part`);
  const points = data.get("points");
  return [data, Array.isArray(points) ? points.length : 0];
}

/** The reference points of a resolved part in its own frame: a polygon's vertices, a line's ends, a circle's or text's centre. */
function anchorsOf(part: ResolvedHandPart): [number, number][] {
  if (part.shape === "polygon") return part.points.map(([x, y]) => [x, y]);
  if (part.shape === "line") return [[part.x1, part.y1], [part.x2, part.y2]];
  if (part.shape === "arc") return [[0, 0]];
  return [[part.x, part.y]];
}

/** `points` each moved by `(dx, dy)`, rounded as the layout rounds a part. */
const shifted = (points: readonly (readonly [number, number])[], dx: number, dy: number): [number, number][] =>
  points.map(([x, y]) => [roundHalfAway(x + dx), roundHalfAway(y + dy)]);

const samePoints = (a: readonly (readonly [number, number])[], b: readonly (readonly [number, number])[]): boolean =>
  a.length === b.length && a.every(([x, y], i) => b[i]![0] === x && b[i]![1] === y);

/** A resolved polygon part's points; any other part has none. */
const polygonPoints = (part: ResolvedHandPart): [number, number][] => (part.shape === "polygon" ? part.points : []);

/** The part `target` names in the face the last tried patch loaded, placed by the element drawing it. */
function partAfter(view: View, target: PartTarget, placed: Placed): [AnyHandPart, ResolvedHandPart] {
  const face = view.tried !== null && view.tried.face !== null ? view.tried.face : view.face;
  return partOf(face, placed, target);
}

function refusePartScope(target: PartTarget, scope: Scope): void {
  if (scope !== "auto" && scope !== "all") throw new Refused(`${target.name} cannot be written for ${scope}: a part has no overrides`);
}

/** Move a part by `(dx, dy)` screen pixels: a polygon's every point, a line's `at:` and `to:` (or one of them, `part`), else its `at:`. */
function movePart(view: View, target: PartTarget, dx: number, dy: number, scope: Scope, part: Part): Converted {
  refusePartScope(target, scope);
  const placed = view.placed(target.elementId);
  const [ir, before] = partOf(view.face, placed, target);
  const [written, listed] = writtenPart(view, target);
  let [ldx, ldy] = toLocal(dx, dy, target.angle);
  if (part !== "both" && ir.shape !== "line") throw new Refused(`${target.name} is not a line: it has no ends to move apart`);
  const keys: Key[] = [];
  if (ir.shape === "polygon") {
    // a mirrored outline moves along its axis: a sideways move would break the symmetry it lists
    if (written.has("mirror")) ldx = 0;
    for (let i = 0; i < listed; i++) {
      keys.push(...positionKeys(view, view.index, target.path, ["points", i], ir.points[i]!, ldx, ldy, "all", frameOf(target), false));
    }
    const goal = shifted(polygonPoints(before), ldx, ldy);
    return settle(view, view.index, keys, target.elementId, (p) => samePoints(polygonPoints(partAfter(view, target, p)[1]), goal));
  }
  if (ir.shape === "arc") throw new Refused(`${target.name} is an arc part: it is centred on the axis and has no at: to move`);
  const goals: [number, number][] = [];
  const checks: ((anchors: [number, number][], after: AnyHandPart) => boolean)[] = [];
  if (part === "both" || part === "at") {
    keys.push(...positionKeys(view, view.index, target.path, ["at"], ir.at, ldx, ldy, "all", frameOf(target), false));
    if (ir.shape === "rectangle") {
      // a rectangle resolves to its corners; its `at:` is checked where the author's values put it
      const [x, y] = localPoint(ir.at, view.device.minorRadius, frameOf(target));
      const goal: [number, number] = [roundHalfAway(x + ldx), roundHalfAway(y + ldy)];
      checks.push((_, after) => {
        const [ax, ay] = localPoint((after as { at: Position }).at, view.device.minorRadius, frameOf(target));
        return roundHalfAway(ax) === goal[0] && roundHalfAway(ay) === goal[1];
      });
    } else {
      goals.push(shifted([anchorsOf(before)[0]!], ldx, ldy)[0]!);
      checks.push((anchors) => anchors[0]![0] === goals[0]![0] && anchors[0]![1] === goals[0]![1]);
    }
  }
  if (ir.shape === "line" && (part === "both" || part === "to")) {
    keys.push(...positionKeys(view, view.index, target.path, ["to"], ir.to ?? new Position(), ldx, ldy, "all", frameOf(target), false));
    const end = shifted([anchorsOf(before)[1]!], ldx, ldy)[0]!;
    checks.push((anchors) => anchors[1]![0] === end[0] && anchors[1]![1] === end[1]);
  }
  return settle(view, view.index, keys, target.elementId, (p) => {
    const [after, resolved] = partAfter(view, target, p);
    const anchors = anchorsOf(resolved);
    return checks.every((c) => c(anchors, after));
  });
}

/** Move a polygon element by `(dx, dy)` device pixels: every point. */
function movePolygon(view: View, elementId: string, dx: number, dy: number, scope: Scope): Converted {
  if (scope !== "auto" && scope !== "all") throw new Refused(`${elementId} is a polygon: its points cannot be overridden per device`);
  const element = view.authorPath(elementId);
  const effective = view.effective(elementId) as Shape;
  const before = view.placed(elementId) as unknown as { points: [number, number][] };
  const parent = view.parentBox(elementId);
  const keys: Key[] = [];
  effective.points.forEach((point, i) => keys.push(...positionKeys(view, view.index, element, ["points", i], point, dx, dy, "all", parent, false)));
  const goal = before.points.map(([x, y]): [number, number] => [x + dx, y + dy]);
  return settle(view, view.index, keys, elementId, (p) => samePoints((p as unknown as { points: [number, number][] }).points, goal));
}

/** The polygon element `elementId`'s path, effective element, placed points and parent box; refused for any other element. */
function polygonElement(view: View, elementId: string): [Path, Shape, [number, number][], Box] {
  const effective = view.effective(elementId);
  if (!(effective instanceof Shape) || effective.shape !== "polygon") throw new Refused(`${elementId} is not a polygon: it has no points`);
  return [view.authorPath(elementId), effective, (view.placed(elementId) as unknown as { points: [number, number][] }).points, view.parentBox(elementId)];
}

function pointIndex(index: number, count: number, name: string): number {
  if (!Number.isInteger(index) || index < 0 || index >= count) throw new Refused(`${name} has no point ${index}: it has ${count}`);
  return index;
}

/** Move point `index` of a polygon element, or of a polygon part, by `(dx, dy)` screen pixels. */
export function vertex(view: View, subject: Subject, index: number, dx: number, dy: number, scope: Scope = "auto"): Converted {
  if (isPart(subject)) {
    refusePartScope(subject, scope);
    const placed = view.placed(subject.elementId);
    const [ir, before] = partOf(view.face, placed, subject);
    if (ir.shape !== "polygon") throw new Refused(`${subject.name} is not a polygon: it has no points`);
    const [written, listed] = writtenPart(view, subject);
    const i = pointIndex(index, listed, subject.name);
    let [ldx, ldy] = toLocal(dx, dy, subject.angle);
    // a mirrored outline's point on the axis stays on it
    if (written.has("mirror") && onAxis(ir.points[i]!)) ldx = 0;
    const keys = positionKeys(view, view.index, subject.path, ["points", i], ir.points[i]!, ldx, ldy, "all", frameOf(subject), false);
    const goal = shifted([polygonPoints(before)[i]!], ldx, ldy)[0]!;
    return settle(view, view.index, keys, subject.elementId, (p) => {
      const point = polygonPoints(partAfter(view, subject, p)[1])[i];
      return point !== undefined && point[0] === goal[0] && point[1] === goal[1];
    });
  }
  if (scope !== "auto" && scope !== "all") throw new Refused(`${subject} is a polygon: its points cannot be overridden per device`);
  const [element, effective, points, parent] = polygonElement(view, subject);
  const i = pointIndex(index, effective.points.length, subject);
  const keys = positionKeys(view, view.index, element, ["points", i], effective.points[i]!, dx, dy, "all", parent, false);
  const goal = [points[i]![0] + dx, points[i]![1] + dy];
  return settle(view, view.index, keys, subject, (p) => {
    const point = (p as unknown as { points: [number, number][] }).points[i];
    return point !== undefined && point[0] === goal[0] && point[1] === goal[1];
  });
}

/** The unit the point after and before an insertion are written in: the first length either has, else `%r`. */
function neighbourSpelling(points: Data, after: number): Spelling {
  if (!Array.isArray(points)) return new Spelling("%r");
  for (const at of [after, after + 1 < points.length ? after + 1 : 0]) {
    const point = points[at];
    if (!(point instanceof Map)) continue;
    for (const key of ["dx", "dy", "radius"]) if (point.has(key)) return lengthSpelling(point.get(key) as Data);
  }
  return new Spelling("%r");
}

/**
 * Insert a point after point `after` of a polygon element or part, at
 * `(x, y)` on the screen, written as `dx`/`dy` in the unit its neighbours
 * use (an element's point keeps the neighbour's `anchor:`).
 */
export function addVertex(view: View, subject: Subject, after: number, x: number, y: number): Converted {
  const minor = view.device.minorRadius;
  let path: Path, elementId: string, count: number, parent: Box, local: [number, number], anchor: Data | undefined;
  let landed: (p: Placed) => boolean;
  if (isPart(subject)) {
    const placed = view.placed(subject.elementId);
    const [ir] = partOf(view.face, placed, subject);
    if (ir.shape !== "polygon") throw new Refused(`${subject.name} is not a polygon: it has no points`);
    [, count] = writtenPart(view, subject);
    path = subject.path;
    elementId = subject.elementId;
    parent = frameOf(subject);
    local = toLocal(x - subject.origin[0], y - subject.origin[1], subject.angle);
    const goal: [number, number] = [roundHalfAway(local[0]), roundHalfAway(local[1])];
    landed = (p) => {
      const point = polygonPoints(partAfter(view, subject, p)[1])[after + 1];
      return point !== undefined && point[0] === goal[0] && point[1] === goal[1];
    };
  } else {
    const [element, effective, , box] = polygonElement(view, subject);
    path = element;
    elementId = subject;
    count = effective.points.length;
    parent = box;
    const neighbour = effective.points[pointIndex(after, count, subject)]!;
    const [ax, ay] = parent.anchorPoint(neighbour.anchor);
    local = [x - ax, y - ay];
    const written = dataAt(view.index, [...element, "points", after]);
    anchor = written instanceof Map ? written.get("anchor") as Data | undefined : undefined;
    landed = (p) => {
      const point = (p as unknown as { points: [number, number][] }).points[after + 1];
      return point !== undefined && point[0] === x && point[1] === y;
    };
  }
  pointIndex(after, count, isPart(subject) ? subject.name : subject);
  const pointsPath: Path = [...path, "points"];
  const spelling = neighbourSpelling(dataAt(view.index, pointsPath), after);
  if (spelling.unit === "pt") throw new Refused(`${dotted(pointsPath)} is in pt, which has no pixel size for a position; write it in px, % or %r`);
  const perX = pxPerUnit(spelling.unit, "x", parent, minor), perY = pxPerUnit(spelling.unit, "y", parent, minor);
  if (!perX || !perY) throw new Refused(`${dotted(pointsPath)} is in %, which has no extent in a part's own frame; write it in px or %r`);
  const xs = candidates(local[0] / perX, LENGTH_STEPS[spelling.unit]!, perX), ys = candidates(local[1] / perY, LENGTH_STEPS[spelling.unit]!, perY);
  const what = `add a point to ${dotted(pointsPath)}`;
  let result: Patch | null = null;
  for (let level = 0; level < Math.max(xs.length, ys.length); level++) {
    const point = new Map<string, Data>();
    if (anchor !== undefined) point.set("anchor", anchor);
    point.set("dx", spelling.write(xs[Math.min(level, xs.length - 1)]!));
    point.set("dy", spelling.write(ys[Math.min(level, ys.length - 1)]!));
    result = makePatch(...(({ text, expected }: Patch): [string, Data, string] => [text, expected, what])(insertItem(view.index, pointsPath, after + 1, point)));
    const placed = view.tryPatch(result, elementId);
    if (placed !== null && landed(placed)) return { patch: result, landed: true };
  }
  return { patch: result!, landed: false };
}

/** Remove point `index` of a polygon element or part; a polygon keeps at least three points (a mirrored part's count is the compiler's to check). */
export function removeVertex(view: View, subject: Subject, index: number): Converted {
  let path: Path, count: number, name: string, mirrored = false;
  if (isPart(subject)) {
    const [ir] = partOf(view.face, view.placed(subject.elementId), subject);
    if (ir.shape !== "polygon") throw new Refused(`${subject.name} is not a polygon: it has no points`);
    const [written, listed] = writtenPart(view, subject);
    [path, count, name, mirrored] = [subject.path, listed, subject.name, written.has("mirror")];
  } else {
    const [element, effective] = polygonElement(view, subject);
    [path, count, name] = [element, effective.points.length, subject];
  }
  pointIndex(index, count, name);
  if (!mirrored && count <= 3) throw new Refused(`${name} needs at least 3 points: it has ${count}`);
  const removed = removeItem(view.index, [...path, "points"], index);
  return { patch: makePatch(removed.text, removed.expected, `remove point ${index} of ${dotted(path)}`), landed: true };
}

/** Each resolved extent a part's `resize` may change, by the key written, and the part shapes that have it. */
const PART_EXTENTS: ReadonlyMap<string, [shapes: readonly string[], measure: (p: ResolvedHandPart) => number]> = new Map([
  ["radius", [["circle", "arc"], (p) => (p as { radius: number }).radius]],
  ["thickness", [["line", "arc", "circle"], (p) => (p as { thickness: number }).thickness]],
  ["size\0width", [["rectangle"], (p) => (p as { points: [number, number][] }).points[1]![0] - (p as { points: [number, number][] }).points[0]![0]]],
  ["size\0height", [["rectangle"], (p) => (p as { points: [number, number][] }).points[2]![1] - (p as { points: [number, number][] }).points[1]![1]]],
]);

/** Change a part's extent `key` (`radius`, `thickness`, `size.width`, `size.height`) by `delta` pixels. */
function resizePart(view: View, target: PartTarget, key: readonly string[], delta: number, scope: Scope): Converted {
  refusePartScope(target, scope);
  const found = PART_EXTENTS.get(key.join("\0"));
  if (found === undefined) throw new Refused(`${dotted(key)} is not a radius, thickness or size`);
  const [shapes, measure] = found;
  const [ir, before] = partOf(view.face, view.placed(target.elementId), target);
  if (!shapes.includes(ir.shape)) throw new Refused(`${target.name} has no ${dotted(key)} to resize`);
  if (ir.shape === "circle" && key[0] === "thickness" && ir.filled) throw new Refused(`${target.name} is filled: it has no thickness to resize`);
  const goal = measure(before) + delta;
  if (goal < 1) throw new Refused(`${target.name}'s ${dotted(key)} cannot be smaller than 1 px`);
  let length: unknown = ir;
  for (const step of key) length = length !== null && typeof length === "object" ? (length as Record<string, unknown>)[step] : undefined;
  const write: Path = [...target.path, ...key];
  const entry = view.index.get(write);
  const spelling = entry !== undefined ? lengthSpelling(dataAt(view.index, entry.path)) : new Spelling(length instanceof Length ? length.unit : "px");
  const axis: Axis = key.join(".") === "size.width" ? "x" : key.join(".") === "size.height" ? "y" : "minor";
  const frame = frameOf(target);
  const per = pxPerUnit(spelling.unit, axis, frame, view.device.minorRadius);
  if (!per) throw new Refused(`${dotted(write)} is in %, which has no extent in this part's frame (a radial pattern's or a hand's); write it in px or %r`);
  // an unwritten thickness is the layout's 1 px
  const current = length instanceof Length ? length.resolve(frame, axis, view.device.minorRadius) / per : 1 / per;
  const keys = [{ write, spelling, values: candidates(current + delta / per, LENGTH_STEPS[spelling.unit]!, per) }];
  return settle(view, view.index, keys, target.elementId, (p) => measure(partAfter(view, target, p)[1]) === goal);
}

/** Set an arc part's `start_angle` (from the angle on the screen) or `sweep` (the author's value) in the author's unit. */
function turnPart(view: View, target: PartTarget, key: string, degreesValue: number, scope: Scope): Converted {
  refusePartScope(target, scope);
  if (!ANGLES.has(key)) throw new Refused(`${key} is not start_angle or sweep`);
  const [ir] = partOf(view.face, view.placed(target.elementId), target);
  if (ir.shape !== "arc") throw new Refused(`${target.name} has no ${key}: only an arc part has angles`);
  let value = degreesValue;
  if (key === "start_angle") {
    value -= target.angle;
    // stay on the author's side of the circle
    const current = ir.start_angle !== null ? ir.start_angle.degrees : 0.0;
    value += 360.0 * roundHalfEven((current - value) / 360.0);
  }
  const write: Path = [...target.path, key];
  const entry = view.index.get(write);
  const spelling = entry !== undefined ? angleSpelling(dataAt(view.index, entry.path)) : new Spelling("deg");
  const per = DEGREES_PER[spelling.unit]!;
  const keys = [{ write, spelling, values: candidates(value / per, ANGLE_STEPS[spelling.unit]!, per) }];
  return settle(view, view.index, keys, target.elementId,
    (p) => Math.abs((partAfter(view, target, p)[1] as unknown as Record<string, number>)[key]! - value) < 0.5);
}
