"""`type: progress` -- a bound fraction, drawn as an arc or a bar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import expr
from ..catalog import Type
from ..ir.model import Element, Expression, Progress
from ..layout import Placed, PlacedProgress, _arc_box
from ..preview import arc_span
from ..units import Axis, Box
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc import shapes
from ..emit.monkeyc.common import NO_AOD, AodStyle, _article, _const_prefix
from ..emit.writer import Writer
from . import ElementKind

if TYPE_CHECKING:
    from ..ir.builder import Builder
    from ..layout import Resolver
    from ..preview import _Renderer

def _check_fallback_fraction(b, node: dict, element: Progress) -> None:
    """A `progress` fallback is a **fill fraction**, so it must be 0.0-1.0.

    This is the one place `fallback:` means something other than "the
    value" -- for a progress, either the value or the max can be the
    absent reading, so the outcome is the only well-defined substitute
    (see `_fallback_fraction`).  That makes an out-of-range constant a
    plausible mistake -- writing the *step count* you wanted rather than
    the fraction -- and it is the one path not already clamped by
    `WfbMath.percent`, so a bar could be drawn wider than its own box.  Only a build-time constant is checked here; a
    computed fallback is clamped on device instead.
    """
    fallback = element.fallback
    if element.when_absent != "fallback" or fallback is None or not fallback.is_constant:
        return
    try:
        value = float(fallback.constant)
    except (TypeError, ValueError):
        return
    if 0.0 <= value <= 1.0:
        return
    b.bag.error(
        "when-absent",
        f"{element.id}: a progress fallback is a fill fraction, so it must be "
        f"between 0.0 and 1.0 -- got {fallback.text}",
        b.doc.span(node, "fallback"),
        notes=[
            "unlike a text fallback, which supplies the value and is then "
            "formatted, a progress fallback supplies the filled proportion "
            "directly: either the value or the max can be the absent reading, "
            "so the outcome is the only well-defined thing to substitute",
            "for 'half full' write 0.5, not the reading you would have shown",
        ],
    )


def _fallback_fraction(element: Progress) -> str:
    """The `progress` fallback, as a Float in 0.0-1.0.

    Two things have to be true of it, and neither is automatic.  It must be a
    **Float**: `fraction` is reassigned from `_fraction()` (a Float) in the
    branch below, and a `var` first bound to a Number makes the whole thing a
    `PolyType<Float or Number>` that `WfbArc.drawProgress`'s `Float` parameter
    rejects under `-l 3`.  And it must be **in range**: the real path is
    clamped by `WfbMath.percent`, so an unclamped fallback is the one way a
    bar could be drawn wider than its own box.  A constant is checked at build
    time (`_check_fallback_fraction`) and emitted bare; anything else is
    clamped on device.
    """
    fallback = element.fallback
    if fallback.is_constant:
        return f"{float(fallback.constant)}f"
    return f"WfbMath.clamp({fallback.code}, 0.0, 1.0).toFloat()"


def _fraction(element: Progress) -> str:
    return f"WfbMath.percent({element.value.code}, {element.maximum.code}) / 100.0"


class ProgressKind(ElementKind):
    name = "progress"
    ir_class = Progress
    placed_class = PlacedProgress
    antialiased = True

    def build(self, b: Builder, node: dict, common: dict, path: tuple) -> Element:
        value = b._expression(node, "value")
        maximum = b._expression(node, "max")
        align, vertical_align = b._alignment(node)
        element = Progress(
            **common,
            style=node["style"],
            value=value,
            maximum=maximum,
            radius=b._length(node, "radius"),
            thickness=b._length(node, "thickness"),
            start_angle=b._angle(node, "start_angle"),
            sweep=b._angle(node, "sweep"),
            size=b._size(node.get("size")),
            color=b._color_expression(node, "color"),
            track_color=b._color_expression(node, "track_color"),
            when_absent=node.get("when_absent"),
            fallback=b._expression(node, "fallback") if "fallback" in node else None,
            align=align,
            vertical_align=vertical_align,
        )
        for name, bound in (("value", value), ("max", maximum)):
            if bound and not bound.value.type.is_numeric():
                b.bag.error(
                    "type",
                    f"progress {name} must be a number, got {bound.value}",
                    b.doc.span(node, name),
                )
        if value is not None or maximum is not None:
            combined = expr.Value(
                Type.NUMBER,
                bool((value and value.nullable) or (maximum and maximum.nullable)),
            )
            probe = Expression("value/max", "", combined, (), frozenset(), frozenset(), None)
            b._check_absence(node, element, probe, element.when_absent, None, element.fallback,
                             key="value")
            _check_fallback_fraction(b, node, element)
        b._check_other_absence(node, element, "color", element.color)
        b._check_other_absence(node, element, "track_color", element.track_color)
        b._check_reachable_substitute(node, element, "'color'/'track_color'",
                                      (element.value, element.maximum),
                                      (element.color, element.track_color))
        return element

    def resolve(self, r: Resolver, element: Progress, parent: Box, depth: int) -> Placed:
        cx, cy = r._point(element.at, parent)
        min_1px = element.resolved_min_1px
        if element.style == "arc":
            radius = round(r._extent(element.radius, parent, Axis.MINOR, 0,
                                     min_1px=min_1px, what="radius"))
            thickness = max(1, round(r._extent(element.thickness, parent, Axis.MINOR, 1,
                                               min_1px=min_1px, what="thickness")))
            # The author's clockwise-positive angle becomes Garmin's
            # counter-clockwise one; a positive sweep therefore draws clockwise
            # on the device.  `shape: arc` calls the same helper.
            box, cx, cy, start, sweep, garmin_start, direction = _arc_box(
                radius, thickness, cx, cy, element.align, element.vertical_align,
                element.start_angle, element.sweep)
            aod_thickness = r._aod_extent(element, "thickness", parent, 1)
            return PlacedProgress(
                element, box, (round(cx), round(cy)), depth,
                radius=radius, thickness=thickness,
                start_angle=start, sweep=sweep,
                garmin_start=garmin_start,
                garmin_direction=direction,
                aod_thickness=aod_thickness,
            )
        box, cx, cy = r._sized_box(element, parent, cx, cy)
        return PlacedProgress(element, box.rounded(min_1px=min_1px), (round(cx), round(cy)), depth,
                              size=(round(box.width), round(box.height)))

    def circular_extent(self, placed: PlacedProgress):
        if placed.element.style == "arc":
            return (placed.center[0], placed.center[1], placed.radius + placed.thickness / 2.0)
        return None

    def draw_preview(self, renderer: _Renderer, placed: PlacedProgress) -> None:
        element = placed.element
        value = expr.evaluate(element.value.ast, renderer.values) if element.value.ast else None
        maximum = (expr.evaluate(element.maximum.ast, renderer.values)
                   if element.maximum.ast else None)
        if value is None or maximum is None:
            if element.when_absent == "hide":
                return
            # `fallback:` on a progress substitutes the fill fraction itself,
            # not the value, as the device does (`_fallback_fraction`).
            fraction = 0.0
            if element.when_absent == "fallback" and element.fallback is not None \
                    and element.fallback.ast is not None:
                substitute = expr.evaluate(element.fallback.ast, renderer.values)
                if substitute is not None:
                    fraction = min(1.0, max(0.0, float(substitute)))
        else:
            fraction = (
                0.0 if not maximum or maximum <= 0
                else min(1.0, max(0.0, value / maximum))
            )
        s = renderer.scale
        color = renderer._aod_color(element, "color", element.color)

        if element.style == "arc":
            cx, cy, r = placed.center[0] * s, placed.center[1] * s, placed.radius * s
            width = max(1, renderer._aod_geometry(placed, "thickness", placed.thickness) * s)
            box = [cx - r, cy - r, cx + r, cy + r]
            # The whole-degree rule WfbArc.drawSpan applies on the device --
            # see `arc_span`.
            track = arc_span(placed.start_angle, placed.sweep)
            if element.track_color is not None and track is not None:
                track_color = renderer._aod_color(element, "track_color", element.track_color)
                renderer.draw.arc(box, *track, fill=track_color, width=width)
            fill = arc_span(placed.start_angle, placed.sweep * fraction) if fraction > 0 else None
            if fill is not None:
                renderer.draw.arc(box, *fill, fill=color, width=width)
            return

        box = renderer._rect(placed.box)
        if element.track_color is not None:
            track_color = renderer._aod_color(element, "track_color", element.track_color)
            renderer.draw.rectangle(box, fill=track_color)
        filled = int(placed.box.width * fraction) * s
        if filled > 0:
            renderer.draw.rectangle([box[0], box[1], box[0] + filled, box[3]], fill=color)

    def emit_draw(self, w: Writer, resolved, placed: PlacedProgress, guards: list[str], plan,
                  aod: AodStyle = NO_AOD) -> None:
        element = placed.element
        prefix = _const_prefix(placed.id)
        fraction_expr = _fraction(element)
        color_code = aod.color(element, "color")
        track_color_code = (aod.color(element, "track_color")
                            if element.track_color is not None else None)
        if element.when_absent == "fallback" and guards:
            # The fill fraction falls back, not the raw value/max -- 'fallback:'
            # supplies a number in the same 0.0-1.0 range _fraction() computes, so
            # it slots into exactly the same drawProgress/fillRectangle call the
            # real reading would have used.  (This is why a `progress` fallback
            # means something different from a `text` one, which supplies the
            # *value* and is then formatted; for progress either half of the pair
            # can be the absent reading, so the outcome is the only well-defined
            # thing to substitute.  `_check_fallback_fraction` checks it is
            # in range and `draw_preview` renders the same substitution.)
            w.comment("when_absent: fallback")
            available = " && ".join(f"{name} != null" for name in guards)
            w.line(f"var fraction = {_fallback_fraction(element)};")
            with w.block(f"if ({available})"):
                w.line(f"fraction = {fraction_expr};")
            w.blank()
            fraction_expr = "fraction"
        if element.style == "arc":
            thickness_expr = shapes._thickness_expr(prefix, placed, aod)
            if element.track_color is not None:
                w.comment("the unfilled track")
                w.line(f"dc.setColor({track_color_code}, Graphics.COLOR_TRANSPARENT);")
                shapes._emit_arc_span(w, prefix, thickness_expr)
                w.blank()
            w.comment("the filled portion")
            w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
            w.call("WfbArc.drawProgress", [
                f"dc, Layout.{prefix}_CX, Layout.{prefix}_CY, Layout.{prefix}_RADIUS",
                f"{thickness_expr}, Layout.{prefix}_START, Layout.{prefix}_SWEEP",
                fraction_expr,
            ])
            return

        if element.track_color is not None:
            w.line(f"dc.setColor({track_color_code}, Graphics.COLOR_TRANSPARENT);")
            w.line(
                f"dc.fillRectangle(Layout.{prefix}_X, Layout.{prefix}_Y, "
                f"Layout.{prefix}_WIDTH, Layout.{prefix}_HEIGHT);"
            )
            w.blank()
        w.line(f"var filled = (Layout.{prefix}_WIDTH * {fraction_expr}).toNumber();")
        w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
        w.line(
            f"dc.fillRectangle(Layout.{prefix}_X, Layout.{prefix}_Y, filled, Layout.{prefix}_HEIGHT);"
        )

    def describe(self, placed: PlacedProgress) -> str:
        return _article(f"{placed.element.style} progress indicator")

    def layout_constants(self, prefix: str,
                         placed: PlacedProgress) -> "layout_constants_mod.Constants":
        out: "layout_constants_mod.Constants" = [
            (f"{prefix}_CX", placed.center[0], ""),
            (f"{prefix}_CY", placed.center[1], ""),
        ]
        if placed.element.style == "arc":
            out.extend(layout_constants_mod._arc_constants(prefix, placed))
            out.extend(layout_constants_mod._aod_thickness_constant(prefix, placed))
        else:
            out.extend(layout_constants_mod._box_constants(prefix, placed.box))
        return out


KIND = ProgressKind()
