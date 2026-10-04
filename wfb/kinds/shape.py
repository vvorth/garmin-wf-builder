"""`type: shape` -- the plain drawing primitives (rectangle, circle, line,
arc, ellipse, polygon)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TYPE_CHECKING

from .. import vocab
from ..ir import disc_perimeter_offsets
from ..ir.model import Element, Position, Shape
from ..layout import Placed, PlacedShape, alignment_shift, arc_box, stroke_pad
from ..units import Axis, Box, IntBox
from ..draw.program import (
    AodDimmed, AodPick, AodRestyled, ArcSpan, Blank, Const, DrawContext,
    FillPolygon, Grown, IfAod, Lit, Num, Op, Paint, Primitive, RingColor, SetColor, SetPen,
    Shifted,
)
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc.common import McLiteral, AodStyle, article, const_prefix
from . import ElementKind, shape_of

if TYPE_CHECKING:
    from ..ir.builder import Builder
    from ..ir.model import Face
    from ..layout import Resolver

#: Which geometry keys each `shape:` reads.  A key outside its own row
#: would be parsed and silently dropped, so `_check_shape_keys` rejects it
#: (a `radius:` typed onto a rounded_rectangle instead of `corner_radius:`,
#: say).  `color:`/`filled:` are common to every shape; `thickness:` is
#: checked separately, because whether it is read depends on `filled:`.
#: `polygon` and `line` carry no `align`/`vertical_align`: a polygon has no
#: single `at:` to align on, and a line's `at:`/`to:` are its two ends.
SHAPE_GEOMETRY_KEYS = {
    "rectangle": frozenset({"size", "align"}),
    "rounded_rectangle": frozenset({"size", "corner_radius", "align"}),
    "circle": frozenset({"radius", "align"}),
    "ellipse": frozenset({"size", "align"}),
    "line": frozenset({"to"}),
    "arc": frozenset({"radius", "start_angle", "sweep", "align"}),
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
        code="element", disc="type",
        extra_notes=lambda key: (
            [_SHAPE_NO_ALIGNMENT_REASON[shape]]
            if key == "align" and shape in _SHAPE_NO_ALIGNMENT_REASON
            else []
        ),
    )
    if "thickness" in node and shape not in ("line", "arc") \
            and bool(node.get("filled", True)):
        b.bag.error(
            "element",
            f"'thickness' is not used by a filled 'type: {vocab.kind(shape)}'",
            b.doc.span(node, "thickness") or b.doc.span(node),
            notes=["thickness is the pen width of a stroked shape; a filled shape has "
                   "no stroke to draw",
                   "add 'filled: false' to stroke this shape, or drop "
                   "'thickness' -- a ring round a filled shape is 'outline:'"],
        )


def _shape_filled_override(element: Shape, aod: AodStyle) -> bool:
    """Does this shape's resolved `aod:` flip `filled:` --
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



def _needs_thickness_constant(element: Shape) -> bool:
    """Does this `shape` need a `_THICKNESS` `Layout` constant at all -- the
    plain unfilled-outline case, or an `aod: {filled: false}` override on an
    otherwise-filled shape, which needs a pen width for the
    AOD-only outline draw even though the awake draw never did.  `line`/`arc`
    always need one regardless (there is no `filled` concept there), so
    neither call site of this helper is reached for them.
    """
    if not element.filled:
        return True
    aod = element.aod
    return aod is not None and aod.filled is False


#: The shapes whose `outline:` ring is one grown copy of the primitive
#:: the dilation of a filled circle is a circle `w` larger, and
#: of a filled rectangle a rounded rectangle `w` larger on every side with
#: its corner radius grown by `w`.  Every other shape is stamped -- an
#: ellipse's offset curve is not an ellipse, a stroke's or an arc's ends are
#: undocumented, and a polygon's sharp corners have no one-draw dilation.
_GROWN = frozenset({"circle", "rectangle", "rounded_rectangle"})




def _ring_copy(prefix: str, width: int, index: int) -> str:
    """A polygon's ``index``-th shifted copy for its ``width`` px ring:
    `<P>_RING_0` at 1px, `<P>_RING2_0` wider."""
    return f"{prefix}_RING_{index}" if width == 1 else f"{prefix}_RING{width}_{index}"




def _grown(shape: str, c: Callable[[str], Const], width: int) -> Primitive:
    """The one grown copy a filled circle or rectangle rings as: a circle
    ``width`` px larger, or a rounded rectangle ``width`` px larger on
    every side with its corner grown by ``width``."""
    if shape == "circle":
        return Primitive("fillCircle", ((c("CX"), c("CY"), Grown(c("RADIUS"), width)),))
    corner: Num = Grown(c("CORNER"), width) if shape == "rounded_rectangle" else Lit(width)
    return Primitive("fillRoundedRectangle", (
        (Grown(c("X"), width, -1), Grown(c("Y"), width, -1)),
        (Grown(c("WIDTH"), width, 2), Grown(c("HEIGHT"), width, 2)),
        (corner,),
    ))


def _stroke_pen(element: Shape, flips: bool, thickness: Callable[[], AodPick]) -> AodPick | None:
    """The pen width a stroked line or outlined shape draws with, when it is
    the same in every frame, so a ring's stamps can set it once around all
    of them.  `None` for a filled shape, an arc (its barrel call sets its
    own) or an `aod: {filled: ...}` flip."""
    if element.shape == "line":
        return thickness()
    if element.shape in _FILLABLE_SHAPES and not element.filled and not flips:
        return thickness()
    return None


class ShapeKind(ElementKind[Shape, PlacedShape]):
    name = "shape"
    ir_class = Shape
    placed_class = PlacedShape
    antialiased = True
    ringed = True

    def ring_draws(self, element: Shape, face: Face) -> int:
        # MIP partial updates never see an AOD `filled:` flip.
        return (1 if element.shape in _GROWN and element.filled
                else super().ring_draws(element, face))

    def build(self, b: Builder, node: dict[str, Any], common: dict[str, Any], path: tuple[str | int, ...]) -> Element:
        shape = shape_of(node)
        assert shape is not None  # this kind builds the primitives only
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
                    "'filled' is not accepted on 'type: arc' -- Connect IQ has no "
                    "filled-arc primitive",
                    b.doc.span(node, "filled") or b.doc.span(node),
                    notes=["there is no fillArc, fillSector or drawSector in "
                           "Toybox.Graphics.Dc: an arc is setPenWidth + drawArc and "
                           "nothing else, so 'thickness' is its only weight control",
                           "for a solid disc use 'type: circle'; for a solid wedge, "
                           "approximate it with 'type: polygon'"],
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
                    "'filled: false' is not accepted on 'type: polygon' -- "
                    "Toybox.Graphics.Dc has fillPolygon but no drawPolygon",
                    b.doc.span(node, "filled") or b.doc.span(node),
                    notes=["for an outline, draw the edges as 'type: line' "
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

        def placed(box: IntBox, x: float, y: float, **fields: Any) -> PlacedShape:
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
            arc_ink, cx, cy, start, sweep, garmin_start, direction = arc_box(
                radius, pen, cx, cy, element.align, element.vertical_align,
                element.start_angle, element.sweep)
            return placed(arc_ink, cx, cy, radius=radius, start_angle=start, sweep=sweep,
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
        outer = Box(rect.x - pad, rect.y - pad,
                    rect.width + 2 * pad, rect.height + 2 * pad).rounded()
        return placed(outer, cx, cy, corner_radius=corner, rect=rect)

    def aod_refusal(self, key: str, shape: str | None,
                    literal_text: bool) -> tuple[str, str, list[str]] | None:
        """`Dc` has `fillPolygon` and no `drawPolygon`, so an `aod: {filled:
        ...}` override on a polygon has no outline primitive to switch to --
        the same reason the awake element's own `filled: false` is already
        refused (`build`, below)."""
        if key == "filled" and shape == "polygon":
            return (
                "aod",
                "'aod: {filled: ...}' is not accepted on 'type: polygon' -- "
                "Toybox.Graphics.Dc has fillPolygon but no drawPolygon",
                ["for an outline, draw the edges as separate 'type: line' "
                 "elements, and override those instead"],
            )
        return None

    def circular_extent(self, placed: PlacedShape) -> tuple[float, float, float] | None:
        element = placed.element
        if element.shape == "arc":
            return (placed.center[0], placed.center[1], placed.radius + placed.thickness / 2.0)
        if element.shape == "circle":
            reach = placed.radius + (0 if element.filled else placed.thickness / 2.0)
            return (placed.center[0], placed.center[1], reach)
        return None

    def lower(self, ctx: DrawContext, placed: PlacedShape) -> list[Op]:
        """The primitive, after its `outline:` ring when it has one.  A
        filled circle or rectangle rings as one grown copy of itself, a
        polygon as its shifted copies baked into `Layout`, and every other
        shape as a stamp at the ring's offsets, with the pen set once around
        the stamps when it is the same in every frame.  With `ctx.ring`
        (an outlined group's pass), only the ring is drawn, in its colour."""
        element = placed.element
        aod = ctx.aod
        prefix = const_prefix(placed.id)
        consts = {name: Const(name, value) for name, value, _
                  in self.layout_constants(prefix, placed) if isinstance(value, (int, float))}

        def c(suffix: str) -> Const:
            return consts[f"{prefix}_{suffix}"]

        flips = _shape_filled_override(element, aod)

        def thickness() -> AodPick:
            """The pen width, with its `aod: {thickness: ...}` override.  A
            circle's is a literal at the call site, never a constant
            (`layout_constants`)."""
            asleep = placed.aod_thickness
            if element.shape == "circle":
                return AodPick(Lit(placed.thickness),
                               Lit(asleep) if asleep is not None else None)
            return AodPick(c("THICKNESS"), c("AOD_THICKNESS") if asleep is not None else None)

        def primitive(dx: int = 0, dy: int = 0, set_pen: bool = True) -> list[Op]:
            """The shape's own `Dc` call(s), moved ``dx``/``dy`` for one
            stamp.  ``set_pen=False``: the caller set the pen around
            several of these."""
            if element.shape in _FILLABLE_SHAPES:
                name, groups = _FILLABLE_SHAPES[element.shape]
                first = groups[0]
                head = ((Shifted(c(first[0]), dx), Shifted(c(first[1]), dy))
                        + tuple(c(s) for s in first[2:]))
                args = (head,) + tuple(tuple(c(s) for s in group) for group in groups[1:])
                filled: list[Op] = [Primitive(f"fill{name}", args)]

                def stroked() -> list[Op]:
                    body: list[Op] = [Primitive(f"draw{name}", args)]
                    return [SetPen(thickness()), *body, SetPen(None)] if set_pen else body

                awake = filled if element.filled else stroked()
                if not flips:
                    return awake
                # `filled:` changes the draw call itself in the always-on
                # frame, not an argument.
                return [IfAod(tuple(stroked() if element.filled else filled), tuple(awake))]
            if element.shape == "arc":
                # The barrel call a gauge's arc track makes too, so the two
                # agree on the angle convention and the full circle.
                return [ArcSpan(Shifted(c("CX"), dx), Shifted(c("CY"), dy), c("RADIUS"),
                                thickness(), c("START"), c("SWEEP"))]
            if element.shape == "polygon":
                # `Dc` has no drawPolygon: `filled: false` and an `aod:
                # {filled: ...}` override are refused at build time.
                return [FillPolygon(f"{prefix}_POINTS", tuple(placed.points))]
            line: list[Op] = [Primitive("drawLine", ((
                Shifted(c("CX"), dx), Shifted(c("CY"), dy),
                Shifted(c("END_X"), dx), Shifted(c("END_Y"), dy)),))]
            return [SetPen(thickness()), *line, SetPen(None)] if set_pen else line

        ops: list[Op] = []
        ring = ctx.ring
        outline = element.outline
        if ring is not None or outline is not None:
            paint: Paint = (RingColor() if ring is not None
                            else AodDimmed(element, outline.color if outline else None))
            width = ring.width if ring is not None else (outline.width if outline else 1)
            offsets = disc_perimeter_offsets(width)
            if element.shape in _GROWN and element.filled and not flips:
                ops += [SetColor(paint), _grown(element.shape, c, width)]
            elif element.shape == "polygon":
                ops.append(SetColor(paint))
                ops += [FillPolygon(_ring_copy(prefix, width, index),
                                    tuple((x + dx, y + dy) for x, y in placed.points))
                        for index, (dx, dy) in enumerate(offsets)]
            else:
                pen = _stroke_pen(element, flips, thickness)
                if pen is not None:
                    ops.append(SetPen(pen))
                ops.append(SetColor(paint))
                for dx, dy in offsets:
                    ops += primitive(dx, dy, set_pen=pen is None)
                if pen is not None:
                    ops.append(SetPen(None))
            if ring is not None:
                return ops
            ops.append(Blank())
        ops.append(SetColor(AodRestyled(element, "color")))
        ops += primitive()
        return ops

    def describe(self, placed: PlacedShape) -> str:
        element = placed.element
        if element.shape == "polygon":
            return f"a polygon of {len(element.points)} points"
        noun = article(element.shape.replace("_", " "))
        if (element.shape in ("rectangle", "rounded_rectangle", "circle", "ellipse")
                and not element.filled):
            return f"{noun}, outlined"
        return noun

    def live_handle(self, placed: PlacedShape, handle: dict[str, Any]) -> dict[str, Any] | None:
        """A box's size dragged at an edge that is not centred keeps the
        other edge where it is: the extent grows by the drag and the near
        edge (`X`/`Y`) moves with it when it is the one dragged.  A centred
        circle's or arc's radius moves nothing else.  An arc's angles are
        its `_START` (Garmin's convention) and `_SWEEP`."""
        element = placed.element
        prefix = const_prefix(placed.id)
        raw = handle.get("key")
        key = tuple(raw) if isinstance(raw, list) else (raw,)
        if handle["kind"] == "angle" and element.shape == "arc":
            return {"angle": f"{prefix}_START" if key == ("start_angle",) else f"{prefix}_SWEEP"}
        if handle["kind"] != "size":
            return None
        if key == ("radius",):
            centred = element.align == "center" and element.vertical_align == "center"
            if element.shape in ("circle", "arc") and centred:
                return {"consts": {f"{prefix}_RADIUS": 1}}
            return None
        if element.shape in ("rectangle", "rounded_rectangle") and handle["gain"] in (1, -1):
            extent, edge = ("WIDTH", "X") if key == ("size", "width") else ("HEIGHT", "Y")
            consts = {f"{prefix}_{extent}": 1}
            if handle["gain"] == -1:
                consts[f"{prefix}_{edge}"] = -1
            return {"consts": consts}
        return None

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
            # draw call site (`lower`), not routed through `Layout` --
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
            for width in placed.ring_widths:
                # Its ring: the polygon shifted to each offset point, at
                # build time -- native fills and no loop on the watch.
                for index, (dx, dy) in enumerate(disc_perimeter_offsets(width)):
                    shifted = ", ".join(f"[{x + dx}, {y + dy}]" for x, y in placed.points)
                    out.append((
                        _ring_copy(prefix, width, index),
                        McLiteral("Array<Graphics.Point2D>", f"[{shifted}]"),
                        f"the {width}px ring's stamp at ({dx}, {dy})" if width > 1
                        else f"the ring's stamp at ({dx}, {dy})",
                    ))
        else:
            rect = placed.rect or placed.inner_box
            out.extend(layout_constants_mod.box_constants(prefix, rect))
            if element.shape == "rounded_rectangle":
                out.append((f"{prefix}_CORNER", placed.corner_radius, ""))
            if _needs_thickness_constant(element):
                out.append((f"{prefix}_THICKNESS", placed.thickness, "pen width"))
                out.extend(layout_constants_mod.aod_thickness_constant(prefix, placed))
        return out


KIND = ShapeKind()
