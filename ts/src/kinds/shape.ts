// `type: rectangle`, `circle`, `ellipse`, `line`, `arc`, `polygon`: the
// drawing primitives.
import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import { allKeys } from "../ir/builder/glyphs.ts";
import { type Element, type Face, Shape } from "../ir/model.ts";
import { arcBox, alignmentShift, type Placed, PlacedShape, type Resolver, strokePad } from "../layout.ts";
import { Position } from "../ir/model.ts";
import { truthy } from "../py.ts";
import { Box, roundPx as round } from "../units.ts";
import { type Common, ElementKind, type LiveHandle, type LiveHandleInput, type Refusal, register, shapeOf } from "./base.ts";
import {
  AodDimmed, AodPick, AodRestyled, ArcSpan, Blank, Const, type DrawContext, FillPolygon, Grown, IfAod, Lit, type Num, type Op,
  type Paint, Primitive, RingColor, SetColor, SetPen, Shifted,
} from "../draw/program.ts";
import { type AodStyle, article, constPrefix, McLiteral } from "../emit/monkeyc/common.ts";
import * as lc from "../emit/monkeyc/layout_constants.ts";
import { discPerimeterOffsets } from "../ir/model.ts";

type Node = Map<DataKey, Data>;

/** Which geometry keys each `shape:` reads; a key outside its own row is refused. */
export const SHAPE_GEOMETRY_KEYS: ReadonlyMap<string, ReadonlySet<string>> = new Map([
  ["rectangle", new Set(["size", "corner_radius", "align"])],
  ["circle", new Set(["radius", "align"])],
  ["ellipse", new Set(["size", "align"])],
  ["line", new Set(["to"])],
  ["arc", new Set(["radius", "start_angle", "sweep", "align"])],
  ["polygon", new Set(["points"])],
]);

/** The extra note when the rejected key is `align`. */
const SHAPE_NO_ALIGNMENT_REASON: ReadonlyMap<string, string> = new Map([
  ["polygon", "every vertex is its own position; there is no single 'at:' "
    + "to align on -- a polygon has no 'at:' of its own either"],
  ["line", "'at:' and 'to:' are the line's two ends"],
]);

const ALL_SHAPE_GEOMETRY_KEYS = allKeys(SHAPE_GEOMETRY_KEYS);

/** Reject a geometry key the chosen shape does not read; `thickness:` depends on `filled:`. */
function checkShapeKeys(b: Builder, node: Node, shape: string): void {
  b.checkForeignKeys(node, shape, SHAPE_GEOMETRY_KEYS, ALL_SHAPE_GEOMETRY_KEYS, {
    code: "element", disc: "type",
    extraNotes: (key) => (key === "align" && SHAPE_NO_ALIGNMENT_REASON.has(shape) ? [SHAPE_NO_ALIGNMENT_REASON.get(shape)!] : []),
  });
  if (node.has("thickness") && shape !== "line" && shape !== "arc" && truthy(node.has("filled") ? node.get("filled") : true)) {
    b.bag.error("element", `'thickness' is not used by a filled 'type: ${shape}'`,
      b.doc.span(node, "thickness") ?? b.doc.span(node), {
        notes: ["thickness is the pen width of a stroked shape; a filled shape has no stroke to draw",
          "add 'filled: false' to stroke this shape, or drop "
          + "'thickness' -- a ring round a filled shape is 'outline:'"],
      });
  }
}

/** Does this shape's resolved `aod:` flip `filled:`, in a build with AOD code? */
function shapeFilledOverride(element: Shape, aod: AodStyle): boolean {
  return aod.on && element.aod !== null && element.aod.filled !== null && element.aod.filled !== element.filled;
}

/** The shapes with both a `Dc.fill<Name>` and a `Dc.draw<Name>`: the call's name and argument groups. */
const FILLABLE_SHAPES: ReadonlyMap<string, [string, string[][]]> = new Map([
  ["rectangle", ["Rectangle", [["X", "Y"], ["WIDTH", "HEIGHT"]]]],
  ["rounded_rectangle", ["RoundedRectangle", [["X", "Y"], ["WIDTH", "HEIGHT"], ["CORNER"]]]],
  ["ellipse", ["Ellipse", [["CX", "CY"], ["RX", "RY"]]]],
  ["circle", ["Circle", [["CX", "CY", "RADIUS"]]]],
]);

/** Does this shape need a `_THICKNESS` constant: an outline, or an `aod: {filled: false}` override. */
function needsThicknessConstant(element: Shape): boolean {
  if (!element.filled) return true;
  return element.aod !== null && element.aod.filled === false;
}

/** The shapes whose `outline:` ring is one grown copy of the primitive. */
const GROWN = new Set(["circle", "rectangle"]);

/** A polygon's `index`-th shifted copy for its `width` px ring. */
function ringCopy(prefix: string, width: number, index: number): string {
  return width === 1 ? `${prefix}_RING_${index}` : `${prefix}_RING${width}_${index}`;
}

/** The one grown copy a filled circle or rectangle rings as. */
function grown(shape: string, rounded: boolean, c: (suffix: string) => Const, width: number): Primitive {
  if (shape === "circle") return Primitive("fillCircle", [[c("CX"), c("CY"), Grown(c("RADIUS"), width)]]);
  const corner: Num = rounded ? Grown(c("CORNER"), width) : Lit(width);
  return Primitive("fillRoundedRectangle", [
    [Grown(c("X"), width, -1), Grown(c("Y"), width, -1)],
    [Grown(c("WIDTH"), width, 2), Grown(c("HEIGHT"), width, 2)],
    [corner],
  ]);
}

/** The pen a stroked shape draws with, when it is the same in every frame; `null` otherwise. */
function strokePen(element: Shape, flips: boolean, thickness: () => AodPick): AodPick | null {
  if (element.shape === "line") return thickness();
  if (FILLABLE_SHAPES.has(element.shape) && !element.filled && !flips) return thickness();
  return null;
}

class ShapeKind extends ElementKind<Shape> {
  readonly name = "shape";
  readonly irClass = Shape;
  override readonly antialiased = true;
  override readonly ringed = true;

  build(b: Builder, node: Node, common: Common): Element {
    const shape = shapeOf(node)!;
    const rawPoints = Array.isArray(node.get("points")) ? node.get("points") as Data[] : [];
    const [align, verticalAlign] = b.alignment(node);
    const size = b.size(node.get("size"));
    const radius = b.length(node, "radius");
    const cornerRadius = b.length(node, "corner_radius");
    const to = node.has("to") ? b.position(node.get("to"), node, "to") : null;
    const points = rawPoints.filter((raw) => raw instanceof Map).map((raw) => b.position(raw, node, "points"));
    const startAngle = b.angle(node, "start_angle");
    const sweep = b.angle(node, "sweep");
    const thickness = b.length(node, "thickness");
    const color = b.colorExpression(node, "color");
    const element = Shape.create({
      ...common, shape, size, radius, corner_radius: cornerRadius, to, points, start_angle: startAngle, sweep, thickness, color,
      filled: truthy(node.has("filled") ? node.get("filled") : true), align, vertical_align: verticalAlign,
    });
    if (shape === "circle" && element.radius === null) b.require(node, "radius", "a circle needs a radius");
    if (shape === "rectangle" && (element.size.width === null || element.size.height === null)) {
      b.require(node, "size", "a rectangle needs size.width and size.height");
    }
    if (shape === "line" && element.to === null) b.require(node, "to", "a line needs a 'to' position");
    checkShapeKeys(b, node, shape);
    if (shape === "arc") {
      if (element.radius === null) b.require(node, "radius", "an arc needs a radius");
      if (node.has("filled")) {
        // Constraint 3: no fillArc, fillSector or drawSector anywhere in the API.
        b.bag.error("element", "'filled' is not accepted on 'type: arc' -- Connect IQ has no filled-arc primitive",
          b.doc.span(node, "filled") ?? b.doc.span(node), {
            notes: ["there is no fillArc, fillSector or drawSector in "
              + "Toybox.Graphics.Dc: an arc is setPenWidth + drawArc and "
              + "nothing else, so 'thickness' is its only weight control",
            "for a solid disc use 'type: circle'; for a solid wedge, approximate it with 'type: polygon'"],
          });
      }
    }
    if (shape === "ellipse" && (element.size.width === null || element.size.height === null)) {
      b.require(node, "size", "an ellipse needs size.width and size.height");
    }
    if (shape === "polygon") {
      if (element.points.length < 3) b.require(node, "points", "a polygon needs at least 3 points");
      if (!element.filled) {
        // Dc has fillPolygon and no drawPolygon.
        b.bag.error("element", "'filled: false' is not accepted on 'type: polygon' -- "
          + "Toybox.Graphics.Dc has fillPolygon but no drawPolygon", b.doc.span(node, "filled") ?? b.doc.span(node), {
          notes: ["for an outline, draw the edges as 'type: line' "
            + "elements, which is what a drawPolygon would have compiled to anyway"],
        });
      }
    }
    return element;
  }

  override resolve(r: Resolver, element: Shape, parent: Box, depth: number): Placed {
    let [cx, cy] = r.point(element.at, parent);
    const min1px = element.resolved_min_1px;
    const pen = Math.max(1, round(r.extent(element.thickness, parent, "minor", 1, null, min1px, "thickness")));
    const aodThickness = r.aodExtent(element, "thickness", parent, 1);
    const placed = (box: PlacedShape["box"], x: number, y: number, fields: Partial<PlacedShape> = {}): PlacedShape =>
      PlacedShape.create({ element, box, center: [round(x), round(y)], depth, thickness: pen, aod_thickness: aodThickness, ...fields });

    if (element.shape === "circle") {
      const radius = round(r.extent(element.radius, parent, "minor", 0, null, min1px, "radius"));
      const [dx, dy] = alignmentShift(2 * radius, 2 * radius, element.align, element.vertical_align);
      cx += dx;
      cy += dy;
      const reach = element.filled ? radius : radius + strokePad(pen);
      return placed(new Box(cx - reach, cy - reach, 2 * reach, 2 * reach).rounded(), cx, cy, { radius });
    }
    if (element.shape === "line") {
      // No `align:` on a line: `at:` and `to:` are its two ends.
      const [ex, ey] = r.point(element.to ?? new Position(), parent);
      const box = new Box(Math.min(cx, ex) - pen, Math.min(cy, ey) - pen, Math.abs(ex - cx) + 2 * pen, Math.abs(ey - cy) + 2 * pen);
      return placed(box.rounded(), cx, cy, { end: [round(ex), round(ey)] });
    }
    if (element.shape === "arc") {
      const radius = round(r.extent(element.radius, parent, "minor", 0, null, min1px, "radius"));
      const [ink, ax, ay, start, sweep, garminStart, direction] = arcBox(radius, pen, cx, cy, element.align, element.vertical_align,
        element.start_angle, element.sweep);
      return placed(ink, ax, ay, { radius, start_angle: start, sweep, garmin_start: garminStart, garmin_direction: direction });
    }
    if (element.shape === "polygon") {
      const points = element.points.map((p): [number, number] => {
        const [px, py] = r.point(p, parent);
        return [round(px), round(py)];
      });
      if (points.length === 0) {
        // The builder has already reported it; keep resolving the rest of the design.
        return PlacedShape.create({ element, box: new Box(cx, cy, 0, 0).rounded(), center: [round(cx), round(cy)], depth });
      }
      const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
      const box = new Box(Math.min(...xs), Math.min(...ys), Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
      const centre: [number, number] = [round(xs.reduce((a, b) => a + b, 0) / xs.length), round(ys.reduce((a, b) => a + b, 0) / ys.length)];
      return PlacedShape.create({ element, box: box.rounded(), center: centre, depth, points });
    }
    // rectangle, ellipse: aligned by the declared `size:`, before any outline pad.
    const [sized, sx, sy] = r.sizedBox(element, parent, cx, cy);
    if (element.shape === "ellipse") {
      const rx = round(sized.width / 2), ry = round(sized.height / 2);
      const pad = element.filled ? 0 : strokePad(pen);
      const box = new Box(sx - rx - pad, sy - ry - pad, 2 * (rx + pad), 2 * (ry + pad));
      return placed(box.rounded(), sx, sy, { rx, ry });
    }
    const corner = round(r.length(element.corner_radius, parent, "minor", 0));
    const rect = sized.rounded();
    if (element.filled) return placed(rect, sx, sy, { corner_radius: corner });
    const pad = strokePad(pen);
    const outer = new Box(rect.x - pad, rect.y - pad, rect.width + 2 * pad, rect.height + 2 * pad).rounded();
    return placed(outer, sx, sy, { corner_radius: corner, rect });
  }

  override circularExtent(placed: Placed): [number, number, number] | null {
    const p = placed as PlacedShape;
    if (p.element.shape === "arc") return [p.center[0], p.center[1], p.radius + p.thickness / 2.0];
    if (p.element.shape === "circle") return [p.center[0], p.center[1], p.radius + (p.element.filled ? 0 : p.thickness / 2.0)];
    return null;
  }

  /** Dc has `fillPolygon` and no `drawPolygon`, so `aod: {filled:}` on a polygon has nothing to switch to. */
  override aodRefusal(key: string, shape: string | null): Refusal | null {
    if (key === "filled" && shape === "polygon") {
      return ["aod", "'aod: {filled: ...}' is not accepted on 'type: polygon' -- "
        + "Toybox.Graphics.Dc has fillPolygon but no drawPolygon",
      ["for an outline, draw the edges as separate 'type: line' elements, and override those instead"]];
    }
    return null;
  }

  override lower(ctx: DrawContext, placed: Placed): Op[] {
    const p = placed as PlacedShape;
    const element = p.element;
    const aod = ctx.aod;
    const prefix = constPrefix(p.id);
    const consts = lc.numericConstants(this.layoutConstants(prefix, p));
    const c = (suffix: string): Const => Const(`${prefix}_${suffix}`, consts.get(`${prefix}_${suffix}`)!);
    const flips = shapeFilledOverride(element, aod);

    const thickness = (): AodPick => {
      const asleep = p.aod_thickness;
      if (element.shape === "circle") return AodPick(Lit(p.thickness), asleep !== null ? Lit(asleep) : null);
      return AodPick(c("THICKNESS"), asleep !== null ? c("AOD_THICKNESS") : null);
    };

    const primitive = (dx = 0, dy = 0, setPen = true): Op[] => {
      const fillable = FILLABLE_SHAPES.get(element.shape);
      if (fillable !== undefined) {
        const [name, groups] = FILLABLE_SHAPES.get(element.rounded ? "rounded_rectangle" : element.shape)!;
        const first = groups[0]!;
        const head: Num[] = [Shifted(c(first[0]!), dx), Shifted(c(first[1]!), dy), ...first.slice(2).map(c)];
        const args = [head, ...groups.slice(1).map((group) => group.map(c))];
        const filled: Op[] = [Primitive(`fill${name}`, args)];
        const stroked = (): Op[] => {
          const body: Op[] = [Primitive(`draw${name}`, args)];
          return setPen ? [SetPen(thickness()), ...body, SetPen(null)] : body;
        };
        const awake = element.filled ? filled : stroked();
        if (!flips) return awake;
        return [IfAod(element.filled ? stroked() : filled, awake)];
      }
      if (element.shape === "arc") {
        return [ArcSpan(Shifted(c("CX"), dx), Shifted(c("CY"), dy), c("RADIUS"), thickness(), c("START"), c("SWEEP"))];
      }
      if (element.shape === "polygon") return [FillPolygon(`${prefix}_POINTS`, p.points)];
      const line: Op[] = [Primitive("drawLine", [[Shifted(c("CX"), dx), Shifted(c("CY"), dy), Shifted(c("END_X"), dx), Shifted(c("END_Y"), dy)]])];
      return setPen ? [SetPen(thickness()), ...line, SetPen(null)] : line;
    };

    const ops: Op[] = [];
    const ring = ctx.ring;
    const outline = element.outline;
    if (ring !== null || outline !== null) {
      const paint: Paint = ring !== null ? RingColor() : AodDimmed(element, outline !== null ? outline.color : null);
      const width = ring !== null ? ring.width : (outline !== null ? outline.width : 1);
      const offsets = discPerimeterOffsets(width);
      if (GROWN.has(element.shape) && element.filled && !flips) {
        ops.push(SetColor(paint), grown(element.shape, element.rounded, c, width));
      } else if (element.shape === "polygon") {
        ops.push(SetColor(paint));
        offsets.forEach(([dx, dy], index) => {
          ops.push(FillPolygon(ringCopy(prefix, width, index), p.points.map(([x, y]): [number, number] => [x + dx, y + dy])));
        });
      } else {
        const pen = strokePen(element, flips, thickness);
        if (pen !== null) ops.push(SetPen(pen));
        ops.push(SetColor(paint));
        for (const [dx, dy] of offsets) ops.push(...primitive(dx, dy, pen === null));
        if (pen !== null) ops.push(SetPen(null));
      }
      if (ring !== null) return ops;
      ops.push(Blank());
    }
    ops.push(SetColor(AodRestyled(element, "color")));
    ops.push(...primitive());
    return ops;
  }

  override liveHandle(placed: Placed, handle: LiveHandleInput): LiveHandle | null {
    const element = placed.element as Shape;
    const prefix = constPrefix(placed.id);
    const key = (Array.isArray(handle.key) ? handle.key : [handle.key]).join(".");
    if (handle.kind === "angle" && element.shape === "arc") return { angle: key === "start_angle" ? `${prefix}_START` : `${prefix}_SWEEP` };
    if (handle.kind !== "size") return null;
    if (key === "radius") {
      const centred = element.align === "center" && element.vertical_align === "center";
      return (element.shape === "circle" || element.shape === "arc") && centred ? { consts: { [`${prefix}_RADIUS`]: 1 } } : null;
    }
    if (element.shape === "rectangle" && (handle.gain === 1 || handle.gain === -1)) {
      const [extent, edge] = key === "size.width" ? ["WIDTH", "X"] : ["HEIGHT", "Y"];
      const consts: Record<string, number> = { [`${prefix}_${extent}`]: 1 };
      if (handle.gain === -1) consts[`${prefix}_${edge}`] = -1;
      return { consts };
    }
    return null;
  }

  override layoutConstants(prefix: string, placed: Placed): lc.Constants {
    const p = placed as PlacedShape;
    const element = p.element;
    const out: lc.Constants = [];
    if (["circle", "line", "arc", "ellipse"].includes(element.shape)) {
      out.push([`${prefix}_CX`, p.center[0], ""], [`${prefix}_CY`, p.center[1], ""]);
    }
    if (element.shape === "circle") {
      out.push([`${prefix}_RADIUS`, p.radius, ""]);
    } else if (element.shape === "line") {
      out.push([`${prefix}_END_X`, p.end[0], ""], [`${prefix}_END_Y`, p.end[1], ""], [`${prefix}_THICKNESS`, p.thickness, ""]);
      out.push(...lc.aodThicknessConstant(prefix, p));
    } else if (element.shape === "arc") {
      out.push(...lc.arcConstants(prefix, p), ...lc.aodThicknessConstant(prefix, p));
    } else if (element.shape === "ellipse") {
      out.push([`${prefix}_RX`, p.rx, "semi-axis along x"], [`${prefix}_RY`, p.ry, "semi-axis along y"]);
      if (needsThicknessConstant(element)) out.push([`${prefix}_THICKNESS`, p.thickness, "pen width"], ...lc.aodThicknessConstant(prefix, p));
    } else if (element.shape === "polygon") {
      const points = p.points.map(([x, y]) => `[${x}, ${y}]`).join(", ");
      out.push([`${prefix}_POINTS`, new McLiteral("Array<Graphics.Point2D>", `[${points}]`),
        `${p.points.length} vertices; fillPolygon's own limit is 64`]);
      for (const width of p.ring_widths) {
        discPerimeterOffsets(width).forEach(([dx, dy], index) => {
          const moved = p.points.map(([x, y]) => `[${x + dx}, ${y + dy}]`).join(", ");
          out.push([ringCopy(prefix, width, index), new McLiteral("Array<Graphics.Point2D>", `[${moved}]`),
            width > 1 ? `the ${width}px ring's stamp at (${dx}, ${dy})` : `the ring's stamp at (${dx}, ${dy})`]);
        });
      }
    } else {
      out.push(...lc.boxConstants(prefix, p.rect ?? p.innerBox));
      if (element.rounded) out.push([`${prefix}_CORNER`, p.corner_radius, ""]);
      if (needsThicknessConstant(element)) out.push([`${prefix}_THICKNESS`, p.thickness, "pen width"], ...lc.aodThicknessConstant(prefix, p));
    }
    return out;
  }

  override ringDraws(element: Shape, face: Face): number {
    return GROWN.has(element.shape) && element.filled ? 1 : super.ringDraws(element, face);
  }

  override describe(placed: Placed): string {
    const element = (placed as PlacedShape).element;
    if (element.shape === "polygon") return `a polygon of ${element.points.length} points`;
    const noun = article(element.rounded ? "rounded rectangle" : element.shape);
    if (["rectangle", "circle", "ellipse"].includes(element.shape) && !element.filled) return `${noun}, outlined`;
    return noun;
  }
}

register(new ShapeKind());
