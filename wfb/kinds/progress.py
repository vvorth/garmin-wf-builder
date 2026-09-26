"""`type: progress` -- a bound fraction, drawn as an arc, a bar, or a
gauge needle."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .. import expr
from ..catalog import Type
from ..ir.model import Element, Expression, Progress
from ..layout import Placed, PlacedProgress, arc_box
from ..preview import arc_span
from ..units import Axis, Box
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc import rotated, shapes
from ..emit.monkeyc.common import NO_AOD, AodStyle, article, const_prefix, mc_float
from ..emit.writer import Writer
from . import ElementKind

if TYPE_CHECKING:
    from ..ir.builder import Builder
    from ..layout import Resolver
    from ..preview import Renderer

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


#: Keys a `style: needle` progress does not read: the needle's shape is its
#: parts, and `at:` is the axis it turns about, not a box.
_NEEDLE_UNREAD = {
    "radius": "the needle's length is its parts' own geometry",
    "thickness": "a line part's own 'thickness:' is the needle's pen width",
    "size": "a needle has no box; its extent is the disc it sweeps",
    "track_color": "a needle draws no track -- draw the dial with its own "
                   "'style: arc' progress or a pattern",
    "align": "'at:' is the axis the needle turns about, not a box",
    "vertical_align": "'at:' is the axis the needle turns about, not a box",
}


def _build_needle(b, node: dict, element: Progress) -> bool:
    """`style: needle`'s parts, built exactly like an analog hand's
    (`Builder.build_hand_part`), with the element's own `color:` as every
    part's default.  False when anything was reported."""
    ok = True
    for key, why in _NEEDLE_UNREAD.items():
        if key in node:
            b.bag.error("element", f"{element.id}: '{key}:' is not read by 'style: needle' -- {why}",
                        b.doc.span(node, key))
            ok = False
    color_failed = "color" in node and element.color is None
    parts = []
    for index, raw in enumerate(node.get("needle") or []):
        part = b.build_hand_part(raw, f"{element.id}.needle", index, element.color, color_failed)
        if part is None:
            ok = False
            continue
        parts.append(part)
    element.needle = tuple(parts)
    return ok


def _needle_angle_rad(placed: PlacedProgress, fraction: float) -> float:
    """The needle's angle, radians clockwise from 12 -- the host twin of the
    `start + fraction * sweep` line `emit_draw` writes."""
    return math.radians(placed.start_angle) + fraction * math.radians(placed.sweep)


def _emit_needle(w: Writer, element: Progress, placed: PlacedProgress, prefix: str,
                 fraction_expr: str, aod: AodStyle) -> None:
    """`style: needle`: one `sin`/`cos` pair for the needle's angle, then each
    part rotated and drawn -- an analog hand's own draw (`wfb.kinds.hands.
    _emit_one_hand`) with `start + fraction * sweep` in place of the clock.
    The angle's two constants are device-independent, so they are inlined
    rather than written to every device's `Layout`."""
    start = math.radians(placed.start_angle)
    sweep = math.radians(placed.sweep)
    w.line(f"var cx = Layout.{prefix}_CX;")
    w.line(f"var cy = Layout.{prefix}_CY;")
    w.line(f"var angle = {mc_float(start)} + ({fraction_expr}) * {mc_float(sweep)};")
    w.line("var sin = Math.sin(angle);")
    w.line("var cos = Math.cos(angle);")
    thickness_override = rotated.aod_thickness_override(placed, prefix)
    current = None
    for index, part in enumerate(placed.needle):
        part_prefix = f"{prefix}_NEEDLE_{index}"
        color = aod.part_color(element, part.color)
        if color != current:
            w.line(f"dc.setColor({color}, Graphics.COLOR_TRANSPARENT);")
            current = color
        rotated.emit_transformed_part(
            w, part, part_prefix, radial=True,
            thickness_expr=aod.value(thickness_override, f"Layout.{part_prefix}_THICKNESS"))


class ProgressKind(ElementKind):
    name = "progress"
    ir_class = Progress
    placed_class = PlacedProgress
    antialiased = True

    def build(self, b: Builder, node: dict, common: dict, path: tuple) -> Element | None:
        value = b.expression(node, "value")
        maximum = b.expression(node, "max")
        align, vertical_align = b.alignment(node)
        element = Progress(
            **common,
            style=node["style"],
            value=value,
            maximum=maximum,
            radius=b.length(node, "radius"),
            thickness=b.length(node, "thickness"),
            start_angle=b.angle(node, "start_angle"),
            sweep=b.angle(node, "sweep"),
            size=b.size(node.get("size")),
            color=b.color_expression(node, "color"),
            track_color=b.color_expression(node, "track_color"),
            when_absent=node.get("when_absent"),
            fallback=b.expression(node, "fallback") if "fallback" in node else None,
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
            b.check_absence(node, element, probe, element.when_absent, None, element.fallback,
                            key="value")
            _check_fallback_fraction(b, node, element)
        if element.style == "needle":
            if not _build_needle(b, node, element):
                return None
        elif "needle" in node:
            b.bag.error("element", f"{element.id}: 'needle:' is read only by 'style: needle'",
                        b.doc.span(node, "needle"))
            return None
        b.check_other_absence(node, element, "color", element.color)
        b.check_other_absence(node, element, "track_color", element.track_color)
        b.check_reachable_substitute(node, element, "'color'/'track_color'",
                                     (element.value, element.maximum),
                                     (element.color, element.track_color))
        return element

    def resolve(self, r: Resolver, element: Progress, parent: Box, depth: int) -> Placed:
        cx, cy = r.point(element.at, parent)
        min_1px = element.resolved_min_1px
        if element.style == "arc":
            radius = round(r.extent(element.radius, parent, Axis.MINOR, 0,
                                    min_1px=min_1px, what="radius"))
            thickness = max(1, round(r.extent(element.thickness, parent, Axis.MINOR, 1,
                                              min_1px=min_1px, what="thickness")))
            # The author's clockwise-positive angle becomes Garmin's
            # counter-clockwise one; a positive sweep therefore draws clockwise
            # on the device.  `shape: arc` calls the same helper.
            box, cx, cy, start, sweep, garmin_start, direction = arc_box(
                radius, thickness, cx, cy, element.align, element.vertical_align,
                element.start_angle, element.sweep)
            aod_thickness = r.aod_extent(element, "thickness", parent, 1)
            return PlacedProgress(
                element, box, (round(cx), round(cy)), depth,
                radius=radius, thickness=thickness,
                start_angle=start, sweep=sweep,
                garmin_start=garmin_start,
                garmin_direction=direction,
                aod_thickness=aod_thickness,
            )
        if element.style == "needle":
            parts, reach = r.resolve_parts(list(element.needle), f"{element.id}.needle",
                                           min_1px=min_1px)
            box = Box(cx - reach, cy - reach, 2 * reach, 2 * reach)
            return PlacedProgress(
                element, box.rounded(), (round(cx), round(cy)), depth,
                start_angle=element.start_angle.degrees, sweep=element.sweep.degrees,
                needle=parts, reach=reach,
                aod_thickness=r.aod_extent(element, "thickness", parent, 1),
            )
        box, cx, cy = r.sized_box(element, parent, cx, cy)
        return PlacedProgress(element, box.rounded(min_1px=min_1px), (round(cx), round(cy)), depth,
                              size=(round(box.width), round(box.height)))

    def circular_extent(self, placed: PlacedProgress):
        if placed.element.style == "arc":
            return (placed.center[0], placed.center[1], placed.radius + placed.thickness / 2.0)
        if placed.element.style == "needle":
            return (placed.center[0], placed.center[1], placed.reach)
        return None

    def draw_preview(self, renderer: Renderer, placed: PlacedProgress) -> None:
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
        if element.style == "needle":
            angle = _needle_angle_rad(placed, fraction)
            sin_t, cos_t = math.sin(angle), math.cos(angle)
            for part in placed.needle:
                renderer.hand_part(placed, part, placed.center[0] * s, placed.center[1] * s,
                                   sin_t, cos_t)
            return
        color = renderer.aod_color(element, "color", element.color)

        if element.style == "arc":
            cx, cy, r = placed.center[0] * s, placed.center[1] * s, placed.radius * s
            width = max(1, renderer.aod_geometry(placed, "thickness", placed.thickness) * s)
            box = [cx - r, cy - r, cx + r, cy + r]
            # The whole-degree rule WfbArc.drawSpan applies on the device --
            # see `arc_span`.
            track = arc_span(placed.start_angle, placed.sweep)
            if element.track_color is not None and track is not None:
                track_color = renderer.aod_color(element, "track_color", element.track_color)
                renderer.draw.arc(box, *track, fill=track_color, width=width)
            fill = arc_span(placed.start_angle, placed.sweep * fraction) if fraction > 0 else None
            if fill is not None:
                renderer.draw.arc(box, *fill, fill=color, width=width)
            return

        box = renderer.rect(placed.box)
        if element.track_color is not None:
            track_color = renderer.aod_color(element, "track_color", element.track_color)
            renderer.draw.rectangle(box, fill=track_color)
        filled = int(placed.box.width * fraction) * s
        if filled > 0:
            renderer.draw.rectangle([box[0], box[1], box[0] + filled, box[3]], fill=color)

    def emit_draw(self, w: Writer, resolved, placed: PlacedProgress, guards: list[str], plan,
                  aod: AodStyle = NO_AOD) -> None:
        element = placed.element
        prefix = const_prefix(placed.id)
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
        if element.style == "needle":
            _emit_needle(w, element, placed, prefix, fraction_expr, aod)
            return
        if element.style == "arc":
            thickness_expr = shapes.thickness_expr(prefix, placed, aod)
            if element.track_color is not None:
                w.comment("the unfilled track")
                w.line(f"dc.setColor({track_color_code}, Graphics.COLOR_TRANSPARENT);")
                shapes.emit_arc_span(w, prefix, thickness_expr)
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
        return article(f"{placed.element.style} progress indicator")

    def layout_constants(self, prefix: str,
                         placed: PlacedProgress) -> "layout_constants_mod.Constants":
        out: "layout_constants_mod.Constants" = [
            (f"{prefix}_CX", placed.center[0], ""),
            (f"{prefix}_CY", placed.center[1], ""),
        ]
        if placed.element.style == "arc":
            out.extend(layout_constants_mod.arc_constants(prefix, placed))
            out.extend(layout_constants_mod.aod_thickness_constant(prefix, placed))
        elif placed.element.style == "needle":
            out.extend(layout_constants_mod.aod_thickness_constant(
                prefix, placed, layout_constants_mod.EVERY_PART_NOTE))
            for index, part in enumerate(placed.needle):
                out.extend(layout_constants_mod.hand_part_constants(
                    f"{prefix}_NEEDLE_{index}", "needle", index, part))
        else:
            out.extend(layout_constants_mod.box_constants(prefix, placed.box))
        return out

    def contrast_subjects(self, placed: PlacedProgress):
        """A needle yields each part's own effective colour, like a hand's
        (`wfb.kinds.hands.HandsKind.contrast_subjects`); the other styles
        judge the element's `color:`."""
        if placed.element.style != "needle":
            yield from super().contrast_subjects(placed)
            return
        for index, part in enumerate(placed.needle):
            yield f"{placed.id}.needle[{index}]", part.color, None, True


KIND = ProgressKind()
