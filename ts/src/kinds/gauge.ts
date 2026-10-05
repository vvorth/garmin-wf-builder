// `type: gauge`: a value's fraction of a range, as an arc, a bar, a needle,
// segments or a scale, or the reading of a `config: slots:` slot. Port of
// wfb/kinds/gauge.py's build half.
import * as catalog from "../catalog.ts";
import * as complications from "../complications.ts";
import type { Data, DataKey } from "../edit/yaml.ts";
import * as expr from "../expr.ts";
import type { Builder } from "../ir/builder/index.ts";
import { type AnyHandPart, type Element, Expression, Gauge, HOLD_AUTO } from "../ir/model.ts";
import { arcBox, type Placed, PlacedGauge, type Resolver, rotatableParts, strokePad } from "../layout.ts";
import { degrees, formatG, isNumber, num, repr, roundHalfEven as round, str } from "../py.ts";
import { Box, IntBox } from "../units.ts";
import { type Common, ElementKind, register } from "./base.ts";
import { resolveSlotReference } from "./data.ts";

type Node = Map<DataKey, Data>;

/** A gauge's `absent: {value:}` is a fill fraction, so a constant one must be 0.0-1.0. */
function checkFallbackFraction(b: Builder, node: Node, element: Gauge): void {
  const fallback = element.fallback;
  if (element.absent !== "fallback" || fallback === null || !fallback.isConstant) return;
  let value: number;
  try {
    const n = expr.asNumber(fallback.constant);
    value = typeof n === "bigint" ? Number(n) : isNumber(n) ? num(n) : NaN;
  } catch (error) {
    if (error instanceof TypeError) return;
    throw error;
  }
  if (0.0 <= value && value <= 1.0) return;
  b.bag.error("when-absent", `${element.id}: a gauge's 'absent: {value:}' is a fill fraction, so it must `
    + `be between 0.0 and 1.0 -- got ${fallback.shown}`, b.fallbackSpan(node), {
    notes: [
      "unlike a text's 'absent: {value:}', which supplies the value and is "
      + "then formatted, a gauge's supplies the filled proportion "
      + "directly: either the value or the max can be the absent reading, "
      + "so the outcome is the only well-defined thing to substitute",
      "for 'half full' write 0.5, not the reading you would have shown",
    ],
  });
}

/** What a gauge with `slot:` does not read, and why. */
const NOT_BESIDE_SLOT: ReadonlyMap<string, string> = new Map([
  ["max", "the scale is the picked metric's own, and one 'max:' cannot fit every choice the wearer has"],
  ["bands", "'bands:' are fractions of one fixed scale; zones from the picked metric's own bands are not implemented yet"],
]);

/** The complication type `max: auto` scales by, or `null` with the reason reported. */
function autoScaleType(b: Builder, node: Node, elementId: string, value: Expression | null): string | null {
  if (value === null) return null; // the value's own error is already reported
  const ref = value.ast;
  if (ref === null || ref.kind !== "ref" || !ref.path.startsWith("complication.")) {
    b.bag.error("element", `${elementId}: 'max: auto' needs 'value:' to be a bare 'complication.<type>', got ${value.shown}`,
      b.doc.span(node, "max"), {
        notes: ["the scale is that complication type's own; write 'max:' as a number or an expression for anything else",
          "docs/guide/progress-and-graphs.md, \"Gauges on a slot\""],
      });
    return null;
  }
  const name = ref.path.slice("complication.".length);
  if (!complications.SCALE.has(name)) {
    b.bag.error("element", `${elementId}: 'max: auto' -- ${ref.path} has no scale of its own`, b.doc.span(node, "max"), {
      notes: ["types with one: " + [...complications.SCALE.keys()].sort().join(", "),
        "write 'max:' as a number or an expression for this one"],
    });
    return null;
  }
  return name;
}

/** Refuse the keys a gauge with `slot:` does not read. */
function checkSlotKeys(b: Builder, node: Node, elementId: string): boolean {
  let ok = true;
  for (const [key, why] of NOT_BESIDE_SLOT) {
    if (node.has(key)) {
      b.bag.error("element", `${elementId}: '${key}:' is not read beside 'slot:' -- ${why}`, b.doc.span(node, key),
        { notes: ["docs/guide/progress-and-graphs.md, \"Gauges on a slot\""] });
      ok = false;
    }
  }
  return ok;
}

/** Keys a `style: needle` gauge does not read. */
const NEEDLE_UNREAD: ReadonlyMap<string, string> = new Map([
  ["radius", "the needle's length is its parts' own geometry"],
  ["thickness", "a line part's own 'thickness:' is the needle's pen width"],
  ["size", "a needle has no box; its extent is the disc it sweeps"],
  ["track_color", "a needle draws no track -- draw the dial with its own 'style: arc' gauge or a pattern"],
  ["align", "'at:' is the axis the needle turns about, not a box"],
]);

/** `style: needle`'s parts, built exactly like an analog hand's. */
function buildNeedle(b: Builder, node: Node, element: Gauge): boolean {
  let ok = true;
  for (const [key, why] of NEEDLE_UNREAD) {
    if (node.has(key)) {
      b.bag.error("element", `${element.id}: '${key}:' is not read by 'style: needle' -- ${why}`, b.doc.span(node, key));
      ok = false;
    }
  }
  const colorFailed = node.has("color") && element.color === null;
  const parts: AnyHandPart[] = [];
  (Array.isArray(node.get("needle")) ? node.get("needle") as Data[] : []).forEach((raw, index) => {
    const part = b.buildHandPart(raw as Node, `${element.id}.needle`, index, element.color, colorFailed);
    if (part === null) {
      ok = false;
      return;
    }
    parts.push(part);
  });
  element.needle = parts;
  return ok;
}

/** Keys only one style reads, and which. */
const STYLE_ONLY_KEYS: ReadonlyMap<string, string> = new Map([
  ["needle", "needle"], ["count", "segments"], ["gap", "segments"], ["bands", "scale"], ["pointer", "scale"],
]);

const ARC_KEYS = ["radius", "thickness", "start_angle", "sweep"];

/** `style: segments`/`scale`: an arc's four keys or a bar's `size:`, exactly one, then their own keys. */
function buildTicked(b: Builder, node: Node, element: Gauge): boolean {
  const style = element.style;
  const arcGiven = ARC_KEYS.filter((key) => node.has(key));
  if (arcGiven.length > 0 && node.has("size")) {
    b.bag.error("element", `${element.id}: 'style: ${style}' draws on an arc or a bar, `
      + "not both -- give an arc's radius/thickness/start_angle/sweep, or a bar's size", b.doc.span(node, "size"));
    return false;
  }
  if (arcGiven.length === 0 && !node.has("size")) {
    b.bag.error("element", `${element.id}: 'style: ${style}' needs a track -- an arc's `
      + "radius, thickness, start_angle and sweep, or a bar's size", b.doc.span(node, "style"));
    return false;
  }
  const missing = arcGiven.length > 0 ? ARC_KEYS.filter((key) => !node.has(key)) : [];
  if (missing.length > 0) {
    b.bag.error("element", `${element.id}: an arc 'style: ${style}' also needs ` + missing.map(repr).join(", "),
      b.doc.span(node, "style"));
    return false;
  }
  if (style === "segments") {
    element.count = Math.trunc(num(node.get("count") as number));
    element.gap = b.length(node, "gap");
    return true;
  }
  element.pointer = b.length(node, "pointer");
  const bands: [number, Expression][] = [];
  let previous = 0.0;
  const raws = Array.isArray(node.get("bands")) ? node.get("bands") as Node[] : [];
  for (const [index, raw] of raws.entries()) {
    const to = num(raw.get("to") as number);
    if (to <= previous) {
      b.bag.error("element", `${element.id}.bands[${index}]: 'to: ${str(raw.get("to"))}' must be `
        + `greater than the previous band's (${formatG(previous)}) -- bands run in order along the track`, b.doc.span(raw, "to"));
      return false;
    }
    const color = b.colorExpression(raw, "color");
    if (color === null) return false;
    b.checkOtherAbsence(raw, element, "bands.color", color);
    bands.push([to, color]);
    previous = to;
  }
  element.bands = bands;
  return true;
}

/** `segments`' cell and step, or `scale`'s pointer and band spans, on the track already placed. */
function resolveTicked(r: Resolver, element: Gauge, placed: PlacedGauge, parent: Box): void {
  const min1px = element.resolved_min_1px;
  const arc = element.geometry === "arc";
  const length = arc ? placed.sweep : placed.size[0];
  if (element.style === "segments") {
    let gap = r.extent(element.gap, parent, "minor", 2, null, min1px, "gap");
    if (arc) {
      gap = placed.radius > 0 ? degrees(gap / placed.radius) : 0.0;
      gap = Math.abs(gap) * (placed.sweep < 0 || Object.is(placed.sweep, -0) ? -1 : 1);
    }
    const count = element.count!;
    placed.cell = (length - (count - 1) * gap) / count;
    placed.step = placed.cell + gap;
    return;
  }
  placed.pointer = element.pointer !== null
    ? round(r.extent(element.pointer, parent, "minor", 1, null, min1px, "pointer"))
    : arc ? placed.thickness : placed.size[1];
  const spans: [number, number][] = [];
  let previous = 0.0;
  for (const [to] of element.bands) {
    if (arc) spans.push([placed.start_angle + previous * placed.sweep, (to - previous) * placed.sweep]);
    else spans.push([Math.trunc(length * previous), Math.trunc(length * to)]);
    previous = to;
  }
  placed.band_spans = spans;
  // The dot reaches past the track: grow the box the lints read, keeping the bar's own rectangle for drawing.
  const [cx, cy] = placed.center;
  if (arc) {
    const reach = placed.radius + Math.max(strokePad(placed.thickness), placed.pointer);
    placed.box = new Box(cx - reach, cy - reach, 2 * reach, 2 * reach).rounded();
  } else {
    const bar = placed.box;
    placed.rect = bar;
    const dy = Math.max(0, placed.pointer - Math.floor(bar.height / 2));
    placed.box = new IntBox(bar.x - placed.pointer, bar.y - dy, bar.width + 2 * placed.pointer, bar.height + 2 * dy);
  }
}

class GaugeKind extends ElementKind<Gauge> {
  readonly name = "gauge";
  readonly irClass = Gauge;
  override readonly antialiased = true;
  override readonly ringed = true;

  override ringRefusal(element: Gauge): string | null {
    if (element.style === "segments" || element.style === "scale") return `on a 'style: ${element.style}' gauge is not implemented yet`;
    return null;
  }

  override resolve(r: Resolver, element: Gauge, parent: Box, depth: number): Placed {
    const [cx, cy] = r.point(element.at, parent);
    const min1px = element.resolved_min_1px;
    if (element.geometry === "arc") {
      const radius = round(r.extent(element.radius, parent, "minor", 0, null, min1px, "radius"));
      const thickness = Math.max(1, round(r.extent(element.thickness, parent, "minor", 1, null, min1px, "thickness")));
      const [box, ax, ay, start, sweep, garminStart, direction] = arcBox(radius, thickness, cx, cy, element.align, element.vertical_align,
        element.start_angle, element.sweep);
      const aodThickness = r.aodExtent(element, "thickness", parent, 1);
      const placed = PlacedGauge.create({
        element, box, center: [round(ax), round(ay)], depth, radius, thickness, start_angle: start, sweep,
        garmin_start: garminStart, garmin_direction: direction, aod_thickness: aodThickness,
      });
      if (element.style === "segments" || element.style === "scale") resolveTicked(r, element, placed, parent);
      return placed;
    }
    if (element.style === "needle") {
      const [parts, reach] = r.resolveParts(element.needle, `${element.id}.needle`, min1px);
      const disc = new Box(cx - reach, cy - reach, 2 * reach, 2 * reach);
      return PlacedGauge.create({
        element, box: disc.rounded(), center: [round(cx), round(cy)], depth,
        start_angle: element.start_angle!.degrees, sweep: element.sweep!.degrees,
        needle: rotatableParts(parts, `${element.id}.needle`), reach, aod_thickness: r.aodExtent(element, "thickness", parent, 1),
      });
    }
    const [sized, sx, sy] = r.sizedBox(element, parent, cx, cy);
    const placed = PlacedGauge.create({
      element, box: sized.rounded(min1px), center: [round(sx), round(sy)], depth, size: [round(sized.width), round(sized.height)],
    });
    if (element.style === "segments" || element.style === "scale") resolveTicked(r, element, placed, parent);
    return placed;
  }

  override circularExtent(placed: Placed): [number, number, number] | null {
    const p = placed as PlacedGauge;
    if (p.element.geometry === "arc") return [p.center[0], p.center[1], p.radius + Math.max(p.thickness / 2.0, p.pointer)];
    if (p.element.style === "needle") return [p.center[0], p.center[1], p.reach];
    return null;
  }

  build(b: Builder, node: Node, common: Common): Element | null {
    let slot = null;
    if (node.has("slot")) {
      slot = resolveSlotReference(b, str(node.get("slot")), b.doc.span(node, "slot"));
      if (slot === null || !checkSlotKeys(b, node, common.id)) return null;
    }
    const rawMax = node.get("max");
    const auto = slot === null && typeof rawMax === "string" && rawMax.trim() === "auto";
    const value = slot === null ? b.expression(node, "value") : null;
    const maximum = slot === null && !auto ? b.expression(node, "max") : null;
    const [align, verticalAlign] = b.alignment(node);
    const absence = b.absence(node);
    const autoScale = auto ? autoScaleType(b, node, common.id, value) : null;
    const radius = b.length(node, "radius");
    const thickness = b.length(node, "thickness");
    const startAngle = b.angle(node, "start_angle");
    const sweep = b.angle(node, "sweep");
    const size = b.size(node.get("size"));
    const color = b.colorExpression(node, "color");
    const trackColor = b.colorExpression(node, "track_color");
    const element = Gauge.create({
      ...common,
      style: node.get("style") as string,
      value,
      maximum,
      slot: slot !== null ? slot.name : null,
      auto_scale: autoScale,
      radius, thickness, start_angle: startAngle, sweep, size, color, track_color: trackColor,
      absent: absence.absent,
      fallback: absence.fallback,
      align,
      vertical_align: verticalAlign,
    });
    for (const [name, bound] of [["value", value], ["max", maximum]] as const) {
      if (bound && !catalog.isNumeric(bound.value.type)) {
        b.bag.error("type", `gauge ${name} must be a number, got ${bound.value}`, b.doc.span(node, name));
      }
    }
    if (auto && element.auto_scale === null) return null;
    if (slot !== null) {
      // The wearer's pick can always be absent: no reading yet, or a type this watch does not have.
      const reading = Expression.create({ text: `the reading of slot ${slot.name}`, code: "", value: new expr.Value("number", true) });
      b.checkAbsence(node, element, reading, element.absent, null, element.fallback, "slot");
      checkFallbackFraction(b, node, element);
      if (element.on_hold === HOLD_AUTO) {
        b.bag.error("on-hold", `${element.id}: 'on_hold: auto' on a gauge with 'slot:' is not implemented yet`,
          b.doc.span(node, "on_hold"), {
            notes: ["put 'on_hold: auto' on the slot's 'type: data' element, which launches whatever the wearer picked"],
          });
        return null;
      }
    } else if (value !== null || maximum !== null) {
      const combined = new expr.Value("number", Boolean((value && value.nullable) || (maximum && maximum.nullable)));
      const probe = Expression.create({ text: "value/max", code: "", value: combined });
      b.checkAbsence(node, element, probe, element.absent, null, element.fallback, "value");
      checkFallbackFraction(b, node, element);
    }
    for (const [key, owner] of STYLE_ONLY_KEYS) {
      if (node.has(key) && element.style !== owner) {
        b.bag.error("element", `${element.id}: '${key}:' is read only by 'style: ${owner}'`, b.doc.span(node, key));
        return null;
      }
    }
    if (element.style === "needle") {
      if (!buildNeedle(b, node, element)) return null;
    } else if (element.style === "segments" || element.style === "scale") {
      if (!buildTicked(b, node, element)) return null;
    }
    b.checkOtherAbsence(node, element, "color", element.color);
    b.checkOtherAbsence(node, element, "track_color", element.track_color);
    b.checkReachableSubstitute(node, element, "'color'/'track_color'", [element.value, element.maximum],
      [element.color, element.track_color]);
    return element;
  }
}

register(new GaugeKind());
