"""Element emitters for `type: hands` and `type: pattern` -- geometry rotated on-device."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ir import RING_OFFSETS
from ..writer import Writer

if TYPE_CHECKING:
    from ...layout import (
        PlacedHands, PlacedPattern, PlacedProgress, ResolvedCirclePart, ResolvedLinePart,
        ResolvedPolygonPart,
    )


def aod_thickness_override(placed: PlacedHands | PlacedPattern | PlacedProgress,
                           prefix: str) -> str | None:
    """The element-level `aod: {thickness: ...}` constant a hands/pattern
    element applies uniformly to every part's pen width (plan 14 §5.1), or
    `None` when it has none."""
    return f"Layout.{prefix}_AOD_THICKNESS" if placed.aod_thickness is not None else None


def emit_transformed_part(w: Writer, part: ResolvedPolygonPart | ResolvedLinePart | ResolvedCirclePart,
                          part_prefix: str, *, radial: bool,
                          thickness_expr: str, set_pen: bool = True) -> None:
    """One polygon/line/circle part at the current copy's origin: rotated
    about `(cx, cy)` through `WfbGeom.*Rotated` (a hand, or a radial
    pattern), or translated by `(ox, oy)` (a linear pattern, which never
    rotates, so plain `Dc` calls do).

    A line or outlined circle brackets its draw in its own pen width
    (``thickness_expr``) unless ``set_pen`` is false: a pattern whose
    stroked parts share one width hoists the pen around its whole loop.
    """
    constant = f"Layout.{part_prefix}"
    stroked = part.shape == "line" or (part.shape == "circle" and not part.filled)
    if stroked and set_pen:
        w.line(f"dc.setPenWidth({thickness_expr});")
    if part.shape == "polygon":
        if radial:
            w.line(f"WfbGeom.fillRotated(dc, {constant}_POINTS, cx, cy, sin, cos);")
        else:
            w.line(f"WfbGeom.fillTranslated(dc, {constant}_POINTS, ox, oy);")
    elif part.shape == "line":
        if radial:
            w.call("WfbGeom.drawLineRotated", [
                f"dc, {constant}_X1, {constant}_Y1",
                f"{constant}_X2, {constant}_Y2, cx, cy, sin, cos",
            ])
        else:
            w.call("dc.drawLine", [
                f"ox + {constant}_X1, oy + {constant}_Y1", f"ox + {constant}_X2, oy + {constant}_Y2",
            ])
    else:  # circle
        verb = "fill" if part.filled else "draw"
        if radial:
            w.call(f"WfbGeom.{verb}CircleRotated", [
                f"dc, {constant}_X, {constant}_Y, {constant}_RADIUS", "cx, cy, sin, cos",
            ])
        else:
            w.line(f"dc.{verb}Circle(ox + {constant}_X, oy + {constant}_Y, {constant}_RADIUS);")
    if stroked and set_pen:
        w.line("dc.setPenWidth(1);")



def _shifted(expr: str, by: int) -> str:
    return expr if by == 0 else f"{expr} {'+' if by > 0 else '-'} {abs(by)}"


def emit_part_ring(w: Writer, part: ResolvedPolygonPart | ResolvedLinePart | ResolvedCirclePart,
                   part_prefix: str, *, radial: bool,
                   thickness_expr: str, set_pen: bool = True) -> None:
    """One polygon/line/circle part's 1px `outline:` ring, in whatever
    colour is set (research 19): the part transformed **once**, then drawn
    at the four offsets -- no per-offset rotation or allocation (the stamp
    cost research 19 §4.5 measured).  A filled circle is its own exact
    dilation one pixel larger: one draw.  Pen width as
    `emit_transformed_part`."""
    constant = f"Layout.{part_prefix}"
    stroked = part.shape == "line" or (part.shape == "circle" and not part.filled)
    if stroked and set_pen:
        w.line(f"dc.setPenWidth({thickness_expr});")
    if part.shape == "polygon":
        if radial:
            w.line(f"WfbGeom.ringRotated(dc, {constant}_POINTS, cx, cy, sin, cos);")
        else:
            w.line(f"WfbGeom.ringTranslated(dc, {constant}_POINTS, ox, oy);")
    elif part.shape == "line":
        if radial:
            w.call("WfbGeom.ringLineRotated", [
                f"dc, {constant}_X1, {constant}_Y1",
                f"{constant}_X2, {constant}_Y2, cx, cy, sin, cos",
            ])
        else:
            for dx, dy in RING_OFFSETS:
                w.call("dc.drawLine", [
                    f"{_shifted(f'ox + {constant}_X1', dx)}, {_shifted(f'oy + {constant}_Y1', dy)}",
                    f"{_shifted(f'ox + {constant}_X2', dx)}, {_shifted(f'oy + {constant}_Y2', dy)}",
                ])
    elif part.filled:
        if radial:
            w.call("WfbGeom.fillCircleRotated", [
                f"dc, {constant}_X, {constant}_Y, {constant}_RADIUS + 1", "cx, cy, sin, cos",
            ])
        else:
            w.line(f"dc.fillCircle(ox + {constant}_X, oy + {constant}_Y, {constant}_RADIUS + 1);")
    elif radial:
        w.call("WfbGeom.ringCircleRotated", [
            f"dc, {constant}_X, {constant}_Y, {constant}_RADIUS", "cx, cy, sin, cos",
        ])
    else:
        for dx, dy in RING_OFFSETS:
            w.line(f"dc.drawCircle({_shifted(f'ox + {constant}_X', dx)}, "
                   f"{_shifted(f'oy + {constant}_Y', dy)}, {constant}_RADIUS);")
    if stroked and set_pen:
        w.line("dc.setPenWidth(1);")
