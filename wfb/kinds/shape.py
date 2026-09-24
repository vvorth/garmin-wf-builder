"""`type: shape` -- the plain drawing primitives (rectangle, circle, line,
arc, ellipse, polygon)."""

from __future__ import annotations

from ..ir.model import Shape
from ..layout import PlacedShape, Resolver
from ..preview import _Renderer
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc import shapes
from ..emit.monkeyc.common import _article
from . import ElementKind


def _aod_refusal(key, shape, literal_text):
    """`Dc` has `fillPolygon` and no `drawPolygon`, so an `aod: {filled:
    ...}` override on a polygon has no outline primitive to switch to --
    the same reason the awake element's own `filled: false` is already
    refused (`Builder._build_shape`)."""
    if key == "filled" and shape == "polygon":
        return (
            "aod",
            "'aod: {filled: ...}' is not accepted on 'shape: polygon' -- "
            "Toybox.Graphics.Dc has fillPolygon but no drawPolygon",
            ["for an outline, draw the edges as separate 'shape: line' "
             "elements, and override those instead"],
        )
    return None


def circular_extent(placed: PlacedShape):
    element = placed.element
    if element.shape == "arc":
        return (placed.center[0], placed.center[1], placed.radius + placed.thickness / 2.0)
    if element.shape == "circle":
        reach = placed.radius + (0 if element.filled else placed.thickness / 2.0)
        return (placed.center[0], placed.center[1], reach)
    return None


def describe(placed: PlacedShape) -> str:
    element = placed.element
    if element.shape == "polygon":
        return f"a polygon of {len(element.points)} points"
    noun = _article(element.shape.replace("_", " "))
    if (element.shape in ("rectangle", "rounded_rectangle", "circle", "ellipse")
            and not element.filled):
        return f"{noun}, outlined"
    return noun


KIND = ElementKind(
    name="shape",
    ir_class=Shape,
    placed_class=PlacedShape,
    build=lambda b, node, common, path: b._build_shape(node, common),
    resolve=Resolver._resolve_shape,
    aod_refusal=_aod_refusal,
    antialiased=True,
    circular_extent=circular_extent,
    draw_preview=_Renderer._shape,
    emit_draw=lambda w, resolved, placed, value_guards, plan, aod: shapes._emit_shape(
        w, placed, aod),
    describe=describe,
    layout_constants=layout_constants_mod._shape_constants,
)
