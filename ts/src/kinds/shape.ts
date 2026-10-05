// `type: rectangle`, `circle`, `ellipse`, `line`, `arc`, `polygon`: the
// drawing primitives. Port of wfb/kinds/shape.py's build half.
import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import { allKeys } from "../ir/builder/glyphs.ts";
import { type Element, Shape } from "../ir/model.ts";
import { truthy } from "../py.ts";
import { type Common, ElementKind, type Refusal, register, shapeOf } from "./base.ts";

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

  /** Dc has `fillPolygon` and no `drawPolygon`, so `aod: {filled:}` on a polygon has nothing to switch to. */
  override aodRefusal(key: string, shape: string | null): Refusal | null {
    if (key === "filled" && shape === "polygon") {
      return ["aod", "'aod: {filled: ...}' is not accepted on 'type: polygon' -- "
        + "Toybox.Graphics.Dc has fillPolygon but no drawPolygon",
      ["for an outline, draw the edges as separate 'type: line' elements, and override those instead"]];
    }
    return null;
  }
}

register(new ShapeKind());
