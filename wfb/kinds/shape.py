"""`type: shape` -- the plain drawing primitives (rectangle, circle, line,
arc, ellipse, polygon)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from ..ir.model import Element, Position, Shape
from ..layout import Placed, PlacedShape, alignment_shift, arc_box, stroke_pad
from ..preview import arc_span
from ..units import Axis, Box, IntBox
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc import shapes
from ..emit.monkeyc.common import McLiteral, NO_AOD, AodStyle, article, const_prefix
from ..emit.writer import Writer
from . import ElementKind

if TYPE_CHECKING:
    from ..ir.builder import Builder
    from ..emit.monkeyc.readplan import ReadPlan
    from ..layout import ResolvedFace, Resolver
    from ..preview import Renderer

#: Which geometry keys each `shape:` reads.  A key outside its own row
#: would be parsed and silently dropped, so `_check_shape_keys` rejects it
#: (a `radius:` typed onto a rounded_rectangle instead of `corner_radius:`,
#: say).  `color:`/`filled:` are common to every shape; `thickness:` is
#: checked separately, because whether it is read depends on `filled:`.
#: `polygon` and `line` carry no `align`/`vertical_align`: a polygon has no
#: single `at:` to align on, and a line's `at:`/`to:` are its two ends.
SHAPE_GEOMETRY_KEYS = {
    "rectangle": frozenset({"size", "align", "vertical_align"}),
    "rounded_rectangle": frozenset({"size", "corner_radius", "align", "vertical_align"}),
    "circle": frozenset({"radius", "align", "vertical_align"}),
    "ellipse": frozenset({"size", "align", "vertical_align"}),
    "line": frozenset({"to"}),
    "arc": frozenset({"radius", "start_angle", "sweep", "align", "vertical_align"}),
    "polygon": frozenset({"points"}),
}

#: The extra note `_check_shape_keys` adds when the rejected key is
#: `align`/`vertical_align`.
_SHAPE_NO_ALIGNMENT_REASON = {
    "polygon": "every vertex is its own position; there is no single 'at:' "
               "to align on -- a polygon has no 'at:' of its own either",
    "line": "'at:' and 'to:' are the line's two ends",
}

_ALL_SHAPE_GEOMETRY_KEYS = frozenset().union(*SHAPE_GEOMETRY_KEYS.values())


def _check_shape_keys(b: Builder, node: dict[str, Any], shape: str) -> None:
    """Reject a geometry key the chosen `shape:` does not read.

    Without this check, an unread key would be parsed by the schema,
    resolved into the IR, and then never looked at -- so `shape:
    rounded_rectangle` with a `radius:` (rather than `corner_radius:`)
    would draw square corners and say nothing, and `thickness:` on a
    shape left filled would do nothing at all.  ADR 0009's rule applies:
    a design must not quietly lose something it asked for.

    `thickness:` is checked separately from the table because whether it
    is read depends on `filled:`, not on the shape: a `line` and an `arc`
    always use it, any other shape uses it only when outlined.
    """
    b.check_foreign_keys(
        node, shape, SHAPE_GEOMETRY_KEYS, _ALL_SHAPE_GEOMETRY_KEYS,
        code="element", disc="shape",
        extra_notes=lambda key: (
            [_SHAPE_NO_ALIGNMENT_REASON[shape]]
            if key in ("align", "vertical_align") and shape in _SHAPE_NO_ALIGNMENT_REASON
            else []
        ),
    )
    if "thickness" in node and shape not in ("line", "arc") \
            and bool(node.get("filled", True)):
        b.bag.error(
            "element",
            f"'thickness' is not used by a filled 'shape: {shape}'",
            b.doc.span(node, "thickness") or b.doc.span(node),
            notes=["thickness is the pen width of an outline; a filled shape has "
                   "no outline to draw",
                   "add 'filled: false' to outline this shape, or drop "
                   "'thickness'"],
        )


def _shape_filled_override(element, aod: AodStyle) -> bool:
    """Does this shape's resolved `aod:` flip `filled:` (plan 14 §4.2) --
    `True` only when this build ever emits AOD code, an override exists, and
    it actually differs from the awake `filled:`; a same-valued override
    changes nothing and is not worth a runtime branch.
    """
    return (
        aod.on and element.aod is not None and element.aod.filled is not None
        and element.aod.filled != element.filled
    )


#: The shapes with both a `Dc.fill<Name>` and a `Dc.draw<Name>` primitive:
#: `shape:` -> (`<Name>`, the call's argument groups, one wrapped line each,
#: as `Layout.<P>_<suffix>` suffixes).
_FILLABLE_SHAPES: dict[str, tuple[str, tuple[tuple[str, ...], ...]]] = {
    "rectangle": ("Rectangle", (("X", "Y"), ("WIDTH", "HEIGHT"))),
    "rounded_rectangle": ("RoundedRectangle", (("X", "Y"), ("WIDTH", "HEIGHT"), ("CORNER",))),
    "ellipse": ("Ellipse", (("CX", "CY"), ("RX", "RY"))),
    "circle": ("Circle", (("CX", "CY", "RADIUS"),)),
}


def _emit_filled_toggle(w: Writer, filled: bool, override: bool,
                        draw_filled, draw_outline) -> None:
    """Emit ``draw_filled``/``draw_outline`` for the awake state, or, when
    ``override`` (`_shape_filled_override`), wrap both in
    ``if (_aod) { <opposite> } else { <awake> }`` -- the "changes the draw
    call itself, not just an argument" shape `filled: true -> false`
    deserves (plan 14 §1). The `else` branch is byte-identical to what the
    element would have emitted with no `filled` override at all, so a
    design that never overrides `filled:` sees no change here.
    """
    if not override:
        (draw_filled if filled else draw_outline)()
        return
    with w.block("if (_aod)"):
        (draw_outline if filled else draw_filled)()
    with w.block("else"):
        (draw_filled if filled else draw_outline)()


def _needs_thickness_constant(element) -> bool:
    """Does this `shape` need a `_THICKNESS` `Layout` constant at all -- the
    plain unfilled-outline case, or an `aod: {filled: false}` override on an
    otherwise-filled shape (plan 14 §4.2), which needs a pen width for the
    AOD-only outline draw even though the awake draw never did.  `line`/`arc`
    always need one regardless (there is no `filled` concept there), so
    neither call site of this helper is reached for them.
    """
    if not element.filled:
        return True
    aod = element.aod
    return aod is not None and aod.filled is False


class ShapeKind(ElementKind[Shape, PlacedShape]):
    name = "shape"
    ir_class = Shape
    placed_class = PlacedShape
    antialiased = True

    def build(self, b: Builder, node: dict[str, Any], common: dict[str, Any], path: tuple[str | int, ...]) -> Element:
        shape = node["shape"]
        raw_points = node.get("points") or []
        align, vertical_align = b.alignment(node)
        element = Shape(
            **common,
            shape=shape,
            size=b.size(node.get("size")),
            radius=b.length(node, "radius"),
            corner_radius=b.length(node, "corner_radius"),
            to=b.position(node.get("to"), node, "to") if "to" in node else None,
            points=[b.position(raw, node, "points")
                    for raw in raw_points if isinstance(raw, dict)],
            start_angle=b.angle(node, "start_angle"),
            sweep=b.angle(node, "sweep"),
            thickness=b.length(node, "thickness"),
            color=b.color_expression(node, "color"),
            filled=bool(node.get("filled", True)),
            align=align,
            vertical_align=vertical_align,
        )
        if shape == "circle" and element.radius is None:
            b.require(node, "radius", "a circle needs a radius")
        if shape == "rectangle" and (element.size.width is None or element.size.height is None):
            b.require(node, "size", "a rectangle needs size.width and size.height")
        if shape == "rounded_rectangle" and element.corner_radius is None:
            b.require(node, "corner_radius", "a rounded rectangle needs a corner_radius")
        if shape == "line" and element.to is None:
            b.require(node, "to", "a line needs a 'to' position")
        _check_shape_keys(b, node, shape)
        if shape == "arc":
            if element.radius is None:
                b.require(node, "radius", "an arc needs a radius")
            if "filled" in node:
                # CLAUDE.md constraint 3: there is no fillArc, fillSector or
                # drawSector anywhere in the API.  Silently ignoring `filled:`
                # here would promise a solid sector the platform cannot draw.
                b.bag.error(
                    "element",
                    "'filled' is not accepted on 'shape: arc' -- Connect IQ has no "
                    "filled-arc primitive",
                    b.doc.span(node, "filled") or b.doc.span(node),
                    notes=["there is no fillArc, fillSector or drawSector in "
                           "Toybox.Graphics.Dc: an arc is setPenWidth + drawArc and "
                           "nothing else, so 'thickness' is its only weight control",
                           "for a solid disc use 'shape: circle'; for a solid wedge, "
                           "approximate it with 'shape: polygon'"],
                )
        if shape == "ellipse" and (element.size.width is None or element.size.height is None):
            b.require(node, "size", "an ellipse needs size.width and size.height")
        if shape == "polygon":
            if len(element.points) < 3:
                b.require(node, "points", "a polygon needs at least 3 points")
            if not element.filled:
                # Dc has fillPolygon and no drawPolygon -- confirmed against
                # $CIQ_SDK/doc/Toybox/Graphics/Dc.html and each target's own
                # api.debug.xml.  An outline would have to be emitted as N
                # drawLine calls, which is a different element, not this one.
                b.bag.error(
                    "element",
                    "'filled: false' is not accepted on 'shape: polygon' -- "
                    "Toybox.Graphics.Dc has fillPolygon but no drawPolygon",
                    b.doc.span(node, "filled") or b.doc.span(node),
                    notes=["for an outline, draw the edges as 'shape: line' "
                           "elements, which is what a drawPolygon would have "
                           "compiled to anyway"],
                )
        return element

    def resolve(self, r: Resolver, element: Shape, parent: Box, depth: int) -> Placed:
        cx, cy = r.point(element.at, parent)
        min_1px = element.resolved_min_1px
        pen = max(1, round(r.extent(element.thickness, parent, Axis.MINOR, 1,
                                    min_1px=min_1px, what="thickness")))
        aod_thickness = r.aod_extent(element, "thickness", parent, 1)

        def placed(box: IntBox, x: float, y: float, **fields) -> PlacedShape:
            return PlacedShape(element, box, (round(x), round(y)), depth,
                               thickness=pen, aod_thickness=aod_thickness, **fields)

        if element.shape == "circle":
            radius = round(r.extent(element.radius, parent, Axis.MINOR, 0,
                                    min_1px=min_1px, what="radius"))
            # Aligned by the full circle; an outline's pen pad is added
            # around the already-moved centre, so it never moves the shift.
            dx, dy = alignment_shift(2 * radius, 2 * radius, element.align, element.vertical_align)
            cx, cy = cx + dx, cy + dy
            reach = radius if element.filled else radius + stroke_pad(pen)
            return placed(Box(cx - reach, cy - reach, 2 * reach, 2 * reach).rounded(), cx, cy,
                          radius=radius)

        if element.shape == "line":
            # No `align:` on a line (rejected in `wfb.ir`): `at:`/`to:` are
            # its two ends, so there is no single box to align.
            ex, ey = r.point(element.to or Position(), parent)
            box = Box(min(cx, ex) - pen, min(cy, ey) - pen,
                      abs(ex - cx) + 2 * pen, abs(ey - cy) + 2 * pen)
            return placed(box.rounded(), cx, cy, end=(round(ex), round(ey)))

        if element.shape == "arc":
            radius = round(r.extent(element.radius, parent, Axis.MINOR, 0,
                                    min_1px=min_1px, what="radius"))
            box, cx, cy, start, sweep, garmin_start, direction = arc_box(
                radius, pen, cx, cy, element.align, element.vertical_align,
                element.start_angle, element.sweep)
            return placed(box, cx, cy, radius=radius, start_angle=start, sweep=sweep,
                          garmin_start=garmin_start, garmin_direction=direction)

        if element.shape == "polygon":
            points = tuple(
                (round(px), round(py))
                for px, py in (r.point(point, parent) for point in element.points)
            )
            if not points:
                # `wfb.ir` has already errored; keep resolving so the rest of
                # the design still gets checked.
                return PlacedShape(element, Box(cx, cy, 0, 0).rounded(),
                                   (round(cx), round(cy)), depth)
            xs = [px for px, _ in points]
            ys = [py for _, py in points]
            box = Box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            centre = (round(sum(xs) / len(xs)), round(sum(ys) / len(ys)))
            return PlacedShape(element, box.rounded(), centre, depth, points=points)

        # rectangle, rounded_rectangle, ellipse: aligned by the declared
        # `size:`, before any outline pad is added.
        sized, cx, cy = r.sized_box(element, parent, cx, cy)

        if element.shape == "ellipse":
            rx = round(sized.width / 2)
            ry = round(sized.height / 2)
            pad = 0 if element.filled else stroke_pad(pen)
            box = Box(cx - rx - pad, cy - ry - pad, 2 * (rx + pad), 2 * (ry + pad))
            return placed(box.rounded(), cx, cy, rx=rx, ry=ry)

        corner = round(r.length(element.corner_radius, parent, Axis.MINOR, 0))
        # `min_1px=min_1px`: `width`/`height` come straight from `extent`,
        # the "float extent of at least 1 px" `Box.rounded` protects.
        rect = sized.rounded(min_1px=min_1px)
        if element.filled:
            return placed(rect, cx, cy, corner_radius=corner)
        pad = stroke_pad(pen)
        reach = Box(rect.x - pad, rect.y - pad,
                    rect.width + 2 * pad, rect.height + 2 * pad).rounded()
        return placed(reach, cx, cy, corner_radius=corner, rect=rect)

    def aod_refusal(self, key, shape, literal_text):
        """`Dc` has `fillPolygon` and no `drawPolygon`, so an `aod: {filled:
        ...}` override on a polygon has no outline primitive to switch to --
        the same reason the awake element's own `filled: false` is already
        refused (`build`, below)."""
        if key == "filled" and shape == "polygon":
            return (
                "aod",
                "'aod: {filled: ...}' is not accepted on 'shape: polygon' -- "
                "Toybox.Graphics.Dc has fillPolygon but no drawPolygon",
                ["for an outline, draw the edges as separate 'shape: line' "
                 "elements, and override those instead"],
            )
        return None

    def circular_extent(self, placed: PlacedShape):
        element = placed.element
        if element.shape == "arc":
            return (placed.center[0], placed.center[1], placed.radius + placed.thickness / 2.0)
        if element.shape == "circle":
            reach = placed.radius + (0 if element.filled else placed.thickness / 2.0)
            return (placed.center[0], placed.center[1], reach)
        return None

    def draw_preview(self, renderer: Renderer, placed: PlacedShape) -> None:
        element = placed.element
        fill = renderer.aod_color(element, "color", element.color)
        filled = renderer.aod_field(element, "filled", element.filled)
        thickness = renderer.aod_geometry(placed, "thickness", placed.thickness)
        s = renderer.scale
        if element.shape == "rectangle":
            box = renderer.rect(placed.rect or placed.box)
            if filled:
                renderer.draw.rectangle(box, fill=fill)
            else:
                renderer.draw.rectangle(box, outline=fill, width=max(1, thickness * s))
        elif element.shape == "rounded_rectangle":
            box = renderer.rect(placed.rect or placed.box)
            radius = placed.corner_radius * s
            if filled:
                renderer.draw.rounded_rectangle(box, radius=radius, fill=fill)
            else:
                renderer.draw.rounded_rectangle(box, radius=radius, outline=fill,
                                                width=max(1, thickness * s))
        elif element.shape == "arc":
            # Same whole-degree rule the generated code gets from
            # WfbArc.drawSpan -- see `arc_span`.
            cx, cy = placed.center[0] * s, placed.center[1] * s
            r = placed.radius * s
            span = arc_span(placed.start_angle, placed.sweep)
            if r > 0 and span is not None:
                renderer.draw.arc([cx - r, cy - r, cx + r, cy + r], *span,
                                  fill=fill, width=max(1, thickness * s))
        elif element.shape == "ellipse":
            cx, cy = placed.center
            rx, ry = placed.rx, placed.ry
            box = [(cx - rx) * s, (cy - ry) * s, (cx + rx) * s, (cy + ry) * s]
            if filled:
                renderer.draw.ellipse(box, fill=fill)
            else:
                renderer.draw.ellipse(box, outline=fill, width=max(1, thickness * s))
        elif element.shape == "polygon":
            if len(placed.points) >= 3:
                renderer.draw.polygon([(x * s, y * s) for x, y in placed.points], fill=fill)
        elif element.shape == "circle":
            cx, cy = placed.center
            r = placed.radius
            box = [(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s]
            if filled:
                renderer.draw.ellipse(box, fill=fill)
            else:
                renderer.draw.ellipse(box, outline=fill, width=max(1, thickness * s))
        elif element.shape == "line":
            renderer.draw.line(
                [placed.center[0] * s, placed.center[1] * s, placed.end[0] * s, placed.end[1] * s],
                fill=fill, width=max(1, thickness * s),
            )

    def emit_draw(self, w: Writer, resolved: ResolvedFace, placed: PlacedShape,
                  value_guards: list[str] | None, plan: ReadPlan,
                  aod: AodStyle = NO_AOD) -> None:
        element = placed.element
        prefix = const_prefix(placed.id)
        w.line(f"dc.setColor({aod.color(element, 'color')}, Graphics.COLOR_TRANSPARENT);")

        if element.shape in _FILLABLE_SHAPES:
            name, groups = _FILLABLE_SHAPES[element.shape]
            args = [", ".join(f"Layout.{prefix}_{suffix}" for suffix in group) for group in groups]
            if element.shape == "circle":
                # A circle's pen width is a plain per-device literal, not a
                # `Layout` constant (`layout_constants`), so its `aod:
                # {thickness: ...}` override is inlined the same way.
                override = str(placed.aod_thickness) if placed.aod_thickness is not None else None
                thickness_expr = aod.value(override, str(placed.thickness))
            else:
                thickness_expr = shapes.thickness_expr(prefix, placed, aod)

            def draw_filled() -> None:
                w.call(f"dc.fill{name}", args)

            def draw_outline() -> None:
                w.line(f"dc.setPenWidth({thickness_expr});")
                w.call(f"dc.draw{name}", args)
                w.line("dc.setPenWidth(1);")

            _emit_filled_toggle(w, element.filled, _shape_filled_override(element, aod),
                                draw_filled, draw_outline)
        elif element.shape == "arc":
            # The same barrel call a `progress` track uses, so the two arcs cannot
            # disagree about the angle convention or about the full-circle case
            # (drawArc draws a complete circle when start == end).
            shapes.emit_arc_span(w, prefix, shapes.thickness_expr(prefix, placed, aod))
        elif element.shape == "polygon":
            # There is no drawPolygon in Dc, only fillPolygon -- `filled: false`
            # and an `aod: {filled: ...}` override on a polygon are both rejected
            # in wfb/ir/builder.py (`Builder._build_aod_authored`), so there is
            # never an outline form to switch to here.
            w.line(f"dc.fillPolygon(Layout.{prefix}_POINTS);")
        elif element.shape == "line":
            w.line(f"dc.setPenWidth({shapes.thickness_expr(prefix, placed, aod)});")
            w.line(
                f"dc.drawLine(Layout.{prefix}_CX, Layout.{prefix}_CY, "
                f"Layout.{prefix}_END_X, Layout.{prefix}_END_Y);"
            )
            w.line("dc.setPenWidth(1);")

    def describe(self, placed: PlacedShape) -> str:
        element = placed.element
        if element.shape == "polygon":
            return f"a polygon of {len(element.points)} points"
        noun = article(element.shape.replace("_", " "))
        if (element.shape in ("rectangle", "rounded_rectangle", "circle", "ellipse")
                and not element.filled):
            return f"{noun}, outlined"
        return noun

    def layout_constants(self, prefix: str,
                         placed: PlacedShape) -> "layout_constants_mod.Constants":
        element = placed.element
        out: "layout_constants_mod.Constants" = []
        if element.shape in ("circle", "line", "arc", "ellipse"):
            out.append((f"{prefix}_CX", placed.center[0], ""))
            out.append((f"{prefix}_CY", placed.center[1], ""))
        if element.shape == "circle":
            out.append((f"{prefix}_RADIUS", placed.radius, ""))
            # A circle's own pen width is inlined as a plain literal at the
            # draw call site (`emit_draw`), not routed through `Layout` --
            # unlike every other shape here, so its `aod_thickness` override
            # is inlined there too, never as a constant.
        elif element.shape == "line":
            out.append((f"{prefix}_END_X", placed.end[0], ""))
            out.append((f"{prefix}_END_Y", placed.end[1], ""))
            out.append((f"{prefix}_THICKNESS", placed.thickness, ""))
            out.extend(layout_constants_mod.aod_thickness_constant(prefix, placed))
        elif element.shape == "arc":
            out.extend(layout_constants_mod.arc_constants(prefix, placed))
            out.extend(layout_constants_mod.aod_thickness_constant(prefix, placed))
        elif element.shape == "ellipse":
            out.append((f"{prefix}_RX", placed.rx, "semi-axis along x"))
            out.append((f"{prefix}_RY", placed.ry, "semi-axis along y"))
            if _needs_thickness_constant(element):
                out.append((f"{prefix}_THICKNESS", placed.thickness, "pen width"))
                out.extend(layout_constants_mod.aod_thickness_constant(prefix, placed))
        elif element.shape == "polygon":
            points = ", ".join(f"[{x}, {y}]" for x, y in placed.points)
            out.append((
                f"{prefix}_POINTS",
                McLiteral("Array<Graphics.Point2D>", f"[{points}]"),
                f"{len(placed.points)} vertices; fillPolygon's own limit is 64",
            ))
        else:
            rect = placed.rect or placed.box
            out.extend(layout_constants_mod.box_constants(prefix, rect))
            if element.shape == "rounded_rectangle":
                out.append((f"{prefix}_CORNER", placed.corner_radius, ""))
            if _needs_thickness_constant(element):
                out.append((f"{prefix}_THICKNESS", placed.thickness, "pen width"))
                out.extend(layout_constants_mod.aod_thickness_constant(prefix, placed))
        return out


KIND = ShapeKind()
