// Parts as the editor sees them: a hand's, a pattern's or a needle's parts
// found in the text (the Layers tree, a request's path), matched to the
// geometry the layout resolved for them, and placed where a frame draws
// them.
//
// A part is named by its author path: parts of different hands may share
// names. Under a hand the path is `["resources", "hand_sets", <set>,
// <hand>, "parts", <id>]`; under a pattern `[..., <element>, "parts",
// <id>]`; under a needle gauge `[..., <element>, "needle", <id>]`. The list
// form the format keeps as shorthand ends the path in the item's index, and
// the part's id is the `partN` the compiler gives it.
import { listPartId } from "../desugar.ts";
import { HAND_ANGLES, val } from "../draw/barrel.ts";
import { Evaluator, Stop } from "../draw/evaluator.ts";
import { context, program } from "../draw/index.ts";
import type { Op, WatchNumber } from "../draw/program.ts";
import { partOf, type PartTarget } from "../edit/geometry.ts";
import { HANDS } from "../edit/hands.ts";
import { nodeAt } from "../edit/patch.ts";
import { type Entry, isElement, lineStart, type Path, Refused, type SpanIndex } from "../edit/spans.ts";
import type { YamlNode } from "../edit/yaml.ts";
import type { AnyHandPart, HandsElement } from "../ir/model.ts";
import { type Placed, PlacedGauge, PlacedHands, PlacedPattern, type ResolvedFace, type ResolvedHandPart } from "../layout.ts";
import { newRenderer, type PreviewOptions, resolveStyleEntry, sampleValues } from "../preview.ts";
import { degrees, floorMod } from "../py.ts";
import { plain } from "./json.ts";
import type { TreeNode, Value } from "./protocol.ts";

/** What a request's path names: an element, a hand of a hand set, or a part of a hand, a pattern or a needle. */
export type Subject = "element" | "hand" | "part";

const isMap = (v: unknown): v is Map<unknown, unknown> => v instanceof Map;

function dataAt(data: unknown, path: Path): unknown {
  for (const step of path) {
    if (isMap(data) && data.has(step)) data = data.get(step);
    else if (Array.isArray(data) && typeof step === "number" && step >= 0 && step < data.length) data = data[step];
    else return undefined;
  }
  return data;
}

/** The key an element writes its parts under: a pattern's `parts`, a needle gauge's `needle`; `null` for any other element. */
export function partsKey(element: unknown): string | null {
  if (!isMap(element)) return null;
  const type = element.get("type");
  if (type === "pattern") return "parts";
  if (type === "gauge" && element.get("style") === "needle") return "needle";
  return null;
}

/** Whether `path` is a hand of a hand set: `["resources", "hand_sets", <set>, hour | minute | second]`. */
function isHandPath(index: SpanIndex, path: Path): boolean {
  return path.length === 4 && path[0] === "resources" && path[1] === "hand_sets" && (HANDS as readonly unknown[]).includes(path[3])
    && isMap(dataAt(index.data, path));
}

/** The element or hand whose parts the part at `path` is one of, or `null` when `path` names no part. */
function partOwner(index: SpanIndex, path: Path): Path | null {
  if (path.length < 3) return null;
  const key = path[path.length - 2];
  const owner = path.slice(0, -2);
  const part = dataAt(index.data, path);
  if (!isMap(part) || !part.has("type")) return null;
  if (key === "parts" && isHandPath(index, owner)) return owner;
  const entry = index.get(owner);
  if (entry === undefined || !isElement(index, entry)) return null;
  return partsKey(dataAt(index.data, owner)) === key ? owner : null;
}

/** What `path` names in the text, or `null`. */
export function subjectOf(index: SpanIndex, path: Path): Subject | null {
  if (partOwner(index, path) !== null) return "part";
  if (isHandPath(index, path)) return "hand";
  const entry = index.get(path);
  return entry !== undefined && isElement(index, entry) ? "element" : null;
}

/** A part located in the text: its path, its owner (an element, or a hand), the hand and set for a hand part, and its id. */
export interface PartRef {
  path: Path;
  owner: Path;
  /** The hand (`hour`, `minute`, `second`) and its set, for a hand part. */
  hand: string | null;
  set: string | null;
  /** The part's own id: its key, or the list form's `partN`. */
  id: string;
  /** The part's mapping as written. */
  written: Map<unknown, unknown>;
}

/** The part at `path`, or refused. */
export function partRef(index: SpanIndex, path: Path): PartRef {
  const owner = partOwner(index, path);
  if (owner === null) throw new Refused(`${path.map(String).join(".")} is not a part`);
  const last = path[path.length - 1]!;
  const hand = isHandPath(index, owner);
  return {
    path: [...path], owner, hand: hand ? String(owner[3]) : null, set: hand ? String(owner[2]) : null,
    id: typeof last === "number" ? listPartId(last) : String(last), written: dataAt(index.data, path) as Map<unknown, unknown>,
  };
}

/** A frame item's id, a tree path joined with "/", back as the path: a step of digits is a list index. */
export function pathOfId(id: string): Path {
  return id.split("/").map((step) => (/^\d+$/.test(step) ? Number(step) : step));
}

// -- the tree --

/** The 1-based first and last lines of `node`, the value of `entry` when it has one (an item of a list has none). */
function linesOf(index: SpanIndex, node: YamlNode, entry: Entry | undefined): [number, number] {
  const text = index.text;
  if (entry !== undefined) return [entry.key.start.line + 1, text.slice(0, index.valueEnd(entry)).split("\n").length - 1];
  let end = node.end.index;
  // a block value's end mark sits at the next token; the value's last line is the one before it
  const head = lineStart(text, end);
  if (text.slice(head, end).trim() === "" && end > node.start.index) end = head - 1;
  while (end > node.start.index) {
    const from = lineStart(text, end - 1);
    const line = text.slice(from, end).trim();
    if (line === "" || line.startsWith("#")) end = from - 1;
    else break;
  }
  return [node.start.line + 1, text.slice(0, Math.max(end, node.start.index)).split("\n").length];
}

/** The tree nodes of the parts under `[...owner, key]`: an id-keyed mapping's entries, or the list form's items. */
export function partNodes(index: SpanIndex, owner: Path, key: string): TreeNode[] {
  const written = dataAt(index.data, [...owner, key]);
  const out: TreeNode[] = [];
  const node = (path: Path, id: string, part: unknown, lines: [number, number]): void => {
    out.push({ kind: "part", id, type: plain(isMap(part) ? part.get("type") ?? null : null) as Value, path: [...path], line: lines[0], end: lines[1], children: [] });
  };
  if (isMap(written)) {
    for (const [id, part] of written) {
      const path: Path = [...owner, key, String(id)];
      const entry = index.get(path);
      if (entry === undefined || !isMap(part)) continue;
      node(path, String(id), part, linesOf(index, entry.value, entry));
    }
  } else if (Array.isArray(written)) {
    written.forEach((part, i) => {
      const path: Path = [...owner, key, i];
      const item = nodeAt(index, path);
      if (item === undefined || !isMap(part)) return;
      node(path, listPartId(i), part, linesOf(index, item, undefined));
    });
  }
  return out;
}

/** The hands of the set a `type: hands` element places, each with its parts; none when the set is not declared. */
export function handNodes(index: SpanIndex, element: unknown): TreeNode[] {
  const set = isMap(element) ? element.get("set") : undefined;
  if (typeof set !== "string") return [];
  const out: TreeNode[] = [];
  for (const hand of HANDS) {
    const path: Path = ["resources", "hand_sets", set, hand];
    const entry = index.get(path);
    if (entry === undefined || !isMap(dataAt(index.data, path))) continue;
    const [line, end] = linesOf(index, entry.value, entry);
    out.push({ kind: "hand", id: hand, type: "hand", path: [...path], line, end, children: partNodes(index, path, "parts") });
  }
  return out;
}

// -- where a frame draws a part --

/** One part as a frame draws it: what a gesture targets, its IR and resolved geometry, and copy 0's (or the hand's) transform `[ox, oy, sin, cos]`. */
export interface PartPlacement {
  target: PartTarget;
  ir: AnyHandPart;
  resolved: ResolvedHandPart;
  transform: [number, number, number, number];
  written: Map<unknown, unknown>;
}

/** The element `elementPath` names as placed on `resolved`, when it is a hands, pattern or needle element. */
export function enteredElement(index: SpanIndex, resolved: ResolvedFace, elementPath: Path): Placed {
  const entry = index.get(elementPath);
  if (entry === undefined || !isElement(index, entry)) throw new Refused(`${elementPath.map(String).join(".")} is not an element`);
  const placed = resolved.items.find((p) => p.id === entry.name);
  if (placed === undefined) throw new Refused(`${entry.name} is not drawn on ${resolved.device.id}`);
  if (!(placed instanceof PlacedHands || placed instanceof PlacedPattern || (placed instanceof PlacedGauge && placed.element.style === "needle"))) {
    throw new Refused(`${entry.name} has no parts to enter: only a hands, a pattern or a needle gauge has`);
  }
  return placed;
}

/** Each hand's angle, in degrees clockwise from 12, at the time the frame shows. */
function handAngles(resolved: ResolvedFace, options: PreviewOptions): Map<string, number> {
  const values = sampleValues(resolved, options, resolveStyleEntry(resolved.face, options.style));
  const unit = (name: string): number => Math.trunc(Number(values.get(`time.${name}`) ?? 0));
  const [hour, minute, second] = [unit("hour"), unit("minute"), unit("second")];
  return new Map([...HAND_ANGLES].map(([hand, angle]) => [hand, degrees(angle(hour, minute, second))]));
}

/** Runs a needle's program up to its first part and keeps the angle it was about to draw at. */
class AngleProbe extends Evaluator {
  angle: number | null = null;

  override step(op: Op): void {
    if (op.t === "Part") {
      const found = this.locals.get("angle");
      this.angle = found !== undefined && found !== null ? degrees(val(found as WatchNumber)) : null;
      throw new Stop();
    }
    super.step(op);
  }
}

/** The angle a needle is drawn at in the frame `options` describes: its start angle plus the sample reading's share of its sweep. */
function needleAngle(resolved: ResolvedFace, placed: PlacedGauge, options: PreviewOptions): number {
  const values = sampleValues(resolved, options, resolveStyleEntry(resolved.face, options.style));
  const renderer = newRenderer(resolved, options, values, [0, 0, 0]);
  const probe = new AngleProbe(renderer);
  if (renderer.shows(placed)) probe.runProgram(program(context(renderer, placed), placed, renderer.readPlan));
  return probe.angle ?? placed.start_angle;
}

/** A radial pattern's first drawn copy: its transform and angle (a linear or grid pattern's copies are not turned). */
function patternCopy(placed: PlacedPattern): [[number, number, number, number], number] {
  const first = placed.copies[0] ?? 0;
  const angle = placed.element.pattern === "radial" ? placed.start + first * placed.step : 0.0;
  return [placed.transform(first), angle];
}

const turned = (ox: number, oy: number, angle: number): [number, number, number, number] => {
  const theta = angle * Math.PI / 180;
  return [ox, oy, Math.sin(theta), Math.cos(theta)];
};

function placement(index: SpanIndex, resolved: ResolvedFace, placed: Placed, ref: PartRef, drawn: number,
  transform: [number, number, number, number]): PartPlacement {
  const angle = floorMod(drawn, 360.0);
  const hand = ref.hand;
  const name = hand !== null ? `${hand}.${ref.id} of ${placed.id}` : `${ref.id} of ${placed.id}`;
  // a linear or grid pattern's parts measure `%` against the box the pattern sits in, a needle's against a square of its smaller side
  const frame = placed instanceof PlacedPattern || placed instanceof PlacedGauge ? placed.part_frame : null;
  const target: PartTarget = {
    path: ref.path, elementId: placed.id, hand, id: ref.id, origin: [transform[0], transform[1]], angle, name,
    ...(frame !== null ? { frame } : {}),
  };
  const [ir, part] = partOf(resolved.face, placed, target);
  return { target, ir, resolved: part, transform, written: ref.written };
}

/**
 * The parts the element at `elementPath` draws, where the frame `options`
 * describes draws them: every hand's parts at its hand's angle (an
 * `awake`-only second hand left out of an asleep frame), a pattern's at its
 * first drawn copy, a needle's at the sample reading. With the frame's
 * angle: the hour hand's (else the first hand's), the copy's, the needle's.
 */
export function enteredParts(index: SpanIndex, resolved: ResolvedFace, elementPath: Path, options: PreviewOptions): [Placed, number, PartPlacement[]] {
  const placed = enteredElement(index, resolved, elementPath);
  const out: PartPlacement[] = [];
  if (placed instanceof PlacedHands) {
    const angles = handAngles(resolved, options);
    const set = (placed.element as HandsElement).hands;
    let frameAngle: number | null = null;
    for (const hand of HANDS) {
      if ((placed as unknown as Record<string, unknown>)[hand] === null) continue;
      if (hand === "second" && options.asleep && (placed.element as HandsElement).seconds === "awake") continue;
      const angle = angles.get(hand)!;
      frameAngle ??= angle;
      for (const node of partNodes(index, ["resources", "hand_sets", set, hand], "parts")) {
        out.push(placement(index, resolved, placed, partRef(index, node.path), angle, turned(placed.center[0], placed.center[1], angle)));
      }
    }
    return [placed, floorMod(frameAngle ?? 0.0, 360.0), out];
  }
  if (placed instanceof PlacedPattern) {
    const [transform, angle] = patternCopy(placed);
    for (const node of partNodes(index, elementPath, "parts")) out.push(placement(index, resolved, placed, partRef(index, node.path), angle, transform));
    return [placed, floorMod(angle, 360.0), out];
  }
  const gauge = placed as PlacedGauge;
  const angle = needleAngle(resolved, gauge, options);
  for (const node of partNodes(index, elementPath, "needle")) {
    out.push(placement(index, resolved, placed, partRef(index, node.path), angle, turned(gauge.center[0], gauge.center[1], angle)));
  }
  return [placed, floorMod(angle, 360.0), out];
}

/**
 * Where the part `ref` is drawn, for a gesture on it: by the first element
 * placing its hand set, or by its pattern or gauge, at the angle the frame
 * `options` describes draws it.
 */
export function partPlacement(index: SpanIndex, resolved: ResolvedFace, ref: PartRef, options: PreviewOptions): PartPlacement {
  let placed: Placed | undefined;
  if (ref.set !== null) {
    placed = resolved.items.find((p) => p instanceof PlacedHands && (p.element as HandsElement).hands === ref.set);
    if (placed === undefined) throw new Refused(`no element places the hand set ${ref.set} on ${resolved.device.id}`);
    const angle = handAngles(resolved, options).get(ref.hand!)!;
    return placement(index, resolved, placed, ref, angle, turned(placed.center[0], placed.center[1], angle));
  }
  placed = enteredElement(index, resolved, ref.owner);
  if (placed instanceof PlacedPattern) {
    const [transform, angle] = patternCopy(placed);
    return placement(index, resolved, placed, ref, angle, transform);
  }
  const gauge = placed as PlacedGauge;
  const angle = needleAngle(resolved, gauge, options);
  return placement(index, resolved, placed, ref, angle, turned(gauge.center[0], gauge.center[1], angle));
}
