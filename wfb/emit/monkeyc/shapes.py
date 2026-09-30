"""Element emitters for the plain drawing primitives: shape and text."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from .common import AodStyle, glyph_y_expr
from ...ir import RING_OFFSETS
from ..writer import Writer

if TYPE_CHECKING:
    from ...layout import PlacedProgress, PlacedShape


def emit_arc_span(w: Writer, prefix: str, thickness_expr: str | None = None,
                  dx: int = 0, dy: int = 0) -> None:
    """The two-line `WfbArc.drawSpan(...)` call against one arc's own
    `_CX/_CY/_RADIUS/_THICKNESS/_START/_SWEEP` constants -- identical whether
    it is a plain `shape: arc` or a `progress` arc's unfilled track, which is
    exactly why the two go through the one barrel helper: they cannot
    disagree about the angle convention or the full-circle case (drawArc
    draws a complete circle when start == end). ``thickness_expr`` defaults
    to the plain `Layout.<P>_THICKNESS` constant; a `progress` arc's track
    passes its own `aod: {thickness: ...}` ternary instead, so the unfilled
    track and the filled portion always agree on which pen width is current.
    ``dx``/``dy`` shift the centre, for an `outline:` stamp.
    """
    if thickness_expr is None:
        thickness_expr = f"Layout.{prefix}_THICKNESS"
    cx = shifted(f"Layout.{prefix}_CX", dx)
    cy = shifted(f"Layout.{prefix}_CY", dy)
    w.call("WfbArc.drawSpan", [
        f"dc, {cx}, {cy}, Layout.{prefix}_RADIUS",
        f"{thickness_expr}, Layout.{prefix}_START, Layout.{prefix}_SWEEP",
    ])


def thickness_expr(prefix: str, placed: PlacedShape | PlacedProgress, aod: AodStyle) -> str:
    """`Layout.<P>_THICKNESS`, ternary against `_AOD_THICKNESS` when this
    element's resolved `aod:` overrides `thickness:` (plan 14 §4.2)."""
    return aod.layout(prefix, "THICKNESS", placed.aod_thickness is not None)


#: `text.curve.direction` -> `Graphics.RadialTextDirection` (verified in
#: `$CIQ_SDK/bin/api.debug.xml`: `RADIAL_TEXT_DIRECTION_CLOCKWISE`/
#: `_COUNTER_CLOCKWISE`, both `Dc.drawRadialText`'s own documented values).
RADIAL_DIRECTION = {
    "clockwise": "RADIAL_TEXT_DIRECTION_CLOCKWISE",
    "counter_clockwise": "RADIAL_TEXT_DIRECTION_COUNTER_CLOCKWISE",
}


def radial_radius_expr(radius_expr: str, vertical_align: str, direction: str | None,
                       font_expr: str) -> str:
    """`dc.drawRadialText`'s `radius` argument for `vertical_align`.

    Without `TEXT_JUSTIFY_VCENTER` the device puts the text's **baseline**
    on the circle, glyphs growing toward their own "up" -- outward under
    `clockwise`, inward under `counter_clockwise` (measured on the real
    simulator 2026-09-21, `docs/research/12-vector-fonts.md` §5.3). That is
    `bottom` as-is. `top` hangs the line box from the circle instead, so
    the baseline moves one `Graphics.getFontAscent` (it takes a
    `VectorFont`: `FontType` includes it) toward the glyphs' "down".
    `center` is `VCENTER` and needs no adjustment.
    """
    if vertical_align != "top":
        return radius_expr
    sign = "+" if direction == "counter_clockwise" else "-"
    return f"{radius_expr} {sign} Graphics.getFontAscent({font_expr})"


def shifted(expr: str, d: int) -> str:
    """``expr`` moved ``d`` pixels, as Monkey C: `Layout.P_CX - 1`."""
    if d == 0:
        return expr
    return f"{expr} {'+' if d > 0 else '-'} {abs(d)}"


def emit_outline(
    w: Writer, color_code: str, x_expr: str, y_expr: str,
    draw: Callable[[str, str], None], *, blank_after: bool = True,
) -> None:
    """The stamped ring ahead of a draw call's own (unshifted) interior pass:
    ``draw(x, y)`` at the anchor moved to each of the four points 1px away,
    in the ring colour (`emit_stamp`).

    ``draw`` emits exactly the call the interior pass makes at the given
    anchor: a screen-space anchor shift commutes with everything else the
    call does (research 14 §3.2), so one callback serves every stamp.
    ``draw`` never touches `dc`'s colour.  ``blank_after=False`` leaves out
    the trailing blank line, for a ring that is the whole body of an
    enclosing block.
    """
    emit_stamp(w, color_code, lambda dx, dy: draw(shifted(x_expr, dx), shifted(y_expr, dy)),
               blank_after=blank_after)


def emit_stamp(w: Writer, color_code: str, draw: Callable[[int, int], None], *,
               blank_after: bool = True) -> None:
    """The stamp itself (research 14, 19): set the ring colour once, then
    ``draw(dx, dy)`` for each of `wfb.ir.RING_OFFSETS`, unrolled.  Measured
    on a watch, a loop over an offsets array cost more than the draws it
    made (research 19 §4.6): four calls with literal offsets do the same
    work with nothing to read or count.  ``draw`` never sets a colour:
    every stamp shares the ring's."""
    w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
    for dx, dy in RING_OFFSETS:
        draw(dx, dy)
    if blank_after:
        w.blank()


def emit_plain_text_call(
    w: Writer, x_expr: str, y_expr: str, font_expr: str, value_code: str, justify: str,
    vertical_align: str,
) -> None:
    """One upright `dc.drawText` call at the given screen-space anchor --
    a text element's interior pass and every `outline:` stamp, an upright
    vector-font draw, and an icon's glyph."""
    y = glyph_y_expr(y_expr, vertical_align, font_expr)
    w.call("dc.drawText", [f"{x_expr}, {y}, {font_expr}", value_code, justify])
