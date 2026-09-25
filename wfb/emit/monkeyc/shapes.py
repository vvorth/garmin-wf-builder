"""Element emitters for the plain drawing primitives: shape and text."""

from __future__ import annotations

from collections.abc import Callable

from ... import formatting
from ...layout import PlacedText, ResolvedFace
from .common import (
    NO_AOD, AodStyle, _aod_font_field, _color, _const_prefix, _field, _glyph_y_expr,
)
from ..writer import Writer


def _emit_arc_span(w: Writer, prefix: str, thickness_expr: str | None = None) -> None:
    """The two-line `WfbArc.drawSpan(...)` call against one arc's own
    `_CX/_CY/_RADIUS/_THICKNESS/_START/_SWEEP` constants -- identical whether
    it is a plain `shape: arc` or a `progress` arc's unfilled track, which is
    exactly why the two go through the one barrel helper: they cannot
    disagree about the angle convention or the full-circle case (drawArc
    draws a complete circle when start == end). ``thickness_expr`` defaults
    to the plain `Layout.<P>_THICKNESS` constant; a `progress` arc's track
    passes its own `aod: {thickness: ...}` ternary instead, so the unfilled
    track and the filled portion always agree on which pen width is current.
    """
    if thickness_expr is None:
        thickness_expr = f"Layout.{prefix}_THICKNESS"
    w.call("WfbArc.drawSpan", [
        f"dc, Layout.{prefix}_CX, Layout.{prefix}_CY, Layout.{prefix}_RADIUS",
        f"{thickness_expr}, Layout.{prefix}_START, Layout.{prefix}_SWEEP",
    ])


def _thickness_expr(prefix: str, placed, aod: AodStyle) -> str:
    """`Layout.<P>_THICKNESS`, ternary against `_AOD_THICKNESS` when this
    element's resolved `aod:` overrides `thickness:` (plan 14 §4.2)."""
    return aod.layout(prefix, "THICKNESS", placed.aod_thickness is not None)


def _emit_text(w: Writer, resolved: ResolvedFace, placed: PlacedText, guards: list[str],
              aod: AodStyle = NO_AOD) -> None:
    element = placed.element
    if element.literal is not None:
        _emit_text_draw(w, resolved, placed, f'"{element.literal}"', aod)
        return

    value_code = formatting.emit(
        element.format or "{}",
        element.value.code,
        element.value.value.type,
    )
    if aod.on and element.aod is not None and element.aod.format is not None:
        # `format:` changes the formatting code, not just an argument -- the
        # same "AOD redraws once a minute anyway, so dropping seconds is
        # free" reasoning plan 14 §2.3 states -- so both formatted strings
        # are built once, up front, and the ternary between them stands in
        # for `value_code` everywhere below, including inside a
        # placeholder/fallback substitution.
        aod_value_code = formatting.emit(
            element.aod.format, element.value.code, element.value.value.type)
        value_code = aod.value(aod_value_code, value_code)
    if element.when_absent in ("placeholder", "fallback") and guards:
        # Build the string once rather than duplicating the draw call in both
        # branches: a placeholder is a different *value*, not a different
        # draw; a fallback is the same, except its substitute is itself a
        # compiled expression rather than a literal string, run through the
        # same format spec the real value uses.
        if element.when_absent == "placeholder":
            w.comment("when_absent: placeholder")
            initial = f'"{element.placeholder}"'
        else:
            initial = formatting.emit(
                element.format or "{}",
                element.fallback.code,
                element.fallback.value.type,
            )
            w.comment("when_absent: fallback")
        available = " && ".join(f"{name} != null" for name in guards)
        w.line(f"var text = {initial};")
        with w.block(f"if ({available})"):
            w.line(f"text = {value_code};")
        w.blank()
        _emit_text_draw(w, resolved, placed, "text", aod)
        return
    _emit_text_draw(w, resolved, placed, value_code, aod)


#: `text.curve.direction` -> `Graphics.RadialTextDirection` (verified in
#: `$CIQ_SDK/bin/api.debug.xml`: `RADIAL_TEXT_DIRECTION_CLOCKWISE`/
#: `_COUNTER_CLOCKWISE`, both `Dc.drawRadialText`'s own documented values).
_RADIAL_DIRECTION = {
    "clockwise": "RADIAL_TEXT_DIRECTION_CLOCKWISE",
    "counter_clockwise": "RADIAL_TEXT_DIRECTION_COUNTER_CLOCKWISE",
}


def _radial_radius_expr(radius_expr: str, vertical_align: str, direction: str | None,
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


def _emit_outline_loop(
    w: Writer, width: int, color_code: str, x_expr: str, y_expr: str,
    draw: Callable[[str, str], None], *, index_var: str = "i", offsets_var: str = "offsets",
) -> None:
    """The stamp loop `outline:` runs ahead of a text draw call's own
    (unshifted) interior pass (plan 15 §5, §8): loops over
    `Layout.OUTLINE_OFFSETS_<width>` (`layout_constants`' disc-perimeter
    table for this width), calling ``draw(x, y)`` at each shifted
    screen-space anchor in the ring colour.

    ``draw`` emits exactly the call the interior pass makes at the given
    anchor: a screen-space anchor shift commutes with everything else the
    call does (research 14 §3.2), so one callback serves every stamp.  The
    ring colour is set once before the loop -- every stamp shares it, and
    ``draw`` never touches `dc`'s colour.

    ``index_var``/``offsets_var`` let a pattern's `shape: text` part pick
    names that cannot collide with its copy loop's own `i`, or with another
    outlined part in the same method: Monkey C rejects redefining a
    variable anywhere in one method (`Redefinition of variable 'i'`, from a
    real `monkeyc` run).
    """
    w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
    w.line(f"var {offsets_var} = Layout.OUTLINE_OFFSETS_{width};")
    w.line(f"var {index_var} = 0;")
    with w.block(f"while ({index_var} < {offsets_var}.size())"):
        draw(f"{x_expr} + {offsets_var}[{index_var}]", f"{y_expr} + {offsets_var}[{index_var} + 1]")
        w.line(f"{index_var} += 2;")
    w.blank()


def _emit_plain_text_call(
    w: Writer, x_expr: str, y_expr: str, font_expr: str, value_code: str, justify: str,
    vertical_align: str,
) -> None:
    """One upright `dc.drawText` call at the given screen-space anchor --
    a text element's interior pass and every `outline:` stamp, an upright
    vector-font draw, and an icon's glyph."""
    y = _glyph_y_expr(y_expr, vertical_align, font_expr)
    w.call("dc.drawText", [f"{x_expr}, {y}, {font_expr}", value_code, justify])


def _emit_text_draw(w: Writer, resolved: ResolvedFace, placed: PlacedText, value_code: str,
                    aod: AodStyle = NO_AOD) -> None:
    element = placed.element
    prefix = _const_prefix(placed.id)
    justify = " | ".join(f"Graphics.{flag}" for flag in placed.justify)
    color_code = aod.color(element, "color")
    if placed.font_is_vector:
        _emit_vector_text_draw(w, placed, prefix, justify, value_code, color_code)
        return
    override_expr = None
    if aod.on and element.aod is not None and element.aod.font is not None:
        if not element.aod.font_is_custom:
            override_expr = f"Graphics.{element.aod.font}"
        else:
            override_spec = resolved.face.fonts.get(element.aod.font)
            # A `face:` (vector) font override never reaches codegen at all
            # -- it is a friendly build error (`Builder._build_aod_
            # authored`, docs/limitations.md §2), so `override_spec.
            # is_vector` is defensive here, not a live case. Naming the
            # *same* resource the element already draws with while awake is
            # a legitimate no-op (nothing to load a second time).
            if (override_spec is not None and not override_spec.is_vector
                    and element.aod.font != placed.font_reference):
                override_expr = f"_{_aod_font_field(element.aod.font)}"
    if placed.font_is_custom:
        w.line(f"var font = _{_field(placed.font_reference)};")
        if override_expr is not None:
            w.line(f"var fontFinal = _aod ? {override_expr} : font;")
            with w.block("if (fontFinal == null)"):
                w.line("return;  // no font resource for this frame")
            w.blank()
            font_expr = "fontFinal"
        else:
            with w.block("if (font == null)"):
                w.line("return;  // the font resource failed to load")
            w.blank()
            font_expr = "font"
    else:
        font_expr = aod.value(override_expr, f"Graphics.{placed.font_reference}")
    if element.outline is not None:
        _emit_outline_loop(
            w, element.outline.width, _color(element.outline.color),
            f"Layout.{prefix}_X", f"Layout.{prefix}_Y",
            lambda x, y: _emit_plain_text_call(
                w, x, y, font_expr, value_code, justify, element.vertical_align),
        )
    w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
    _emit_plain_text_call(
        w, f"Layout.{prefix}_X", f"Layout.{prefix}_Y", font_expr, value_code, justify,
        element.vertical_align)


def _emit_vector_draw_call(
    w: Writer, placed: PlacedText, prefix: str, justify: str, value_code: str,
    x_expr: str, y_expr: str,
) -> None:
    """One `dc.drawText`/`drawAngledText`/`drawRadialText` call against a
    `face:` (vector) font, at the given screen-space anchor -- shared by
    the interior pass and every `outline:` stamp (plan 15 §5, §8): `angle`/
    `radius`/`direction`/justify stay exactly what the interior pass would
    have used regardless of which anchor `x_expr`/`y_expr` name, since a
    screen-space anchor shift commutes with the rest of the call's
    arguments (research 14 §3.2, §5's own table).
    """
    element = placed.element
    if placed.curve_style == "angled":
        w.call("dc.drawAngledText", [
            f"{x_expr}, {y_expr}, font, {value_code}", f"{justify}, Layout.{prefix}_ANGLE",
        ])
    elif placed.curve_style == "radial":
        direction = _RADIAL_DIRECTION[placed.curve_direction or "clockwise"]
        radius = _radial_radius_expr(f"Layout.{prefix}_RADIUS", element.vertical_align,
                                     placed.curve_direction, "font")
        w.call("dc.drawRadialText", [
            f"{x_expr}, {y_expr}, font, {value_code}",
            f"{justify}, Layout.{prefix}_ANGLE, {radius}",
            f"Graphics.{direction}",
        ])
    else:
        _emit_plain_text_call(w, x_expr, y_expr, "font", value_code, justify,
                              element.vertical_align)


def _emit_vector_text_draw(
    w: Writer, placed: PlacedText, prefix: str, justify: str, value_code: str, color_code: str,
) -> None:
    """A `face:` (vector) font's draw call (plan 11 §3-4): plain
    `dc.drawText` with no `curve:`, or `dc.drawAngledText`/`dc.
    drawRadialText` under one.

    **Gate 4 is never omitted, on any device, in either `if_unavailable:`
    mode** (`docs/research/12-vector-fonts.md` §1: `Graphics.getVectorFont`
    can return `null` instead of throwing, so a null font has to simply
    draw nothing, always) -- captured into the local `font` first, exactly
    the way `_emit_text_draw`'s own baked-font branch above already reads a
    nullable field, because narrowing a repeated *field* access does not
    survive across statements in Monkey C (`docs/lore/monkeyc.md`:
    `_staticBuffer.getDc()` fails even right after `if (_staticBuffer !=
    null)`) -- only a local's narrowing does.  The `if` *wraps* the draw
    call here, rather than the baked branch's early `return`, so a curved
    element reads as "an ordinarily-missing thing, drawn as nothing" rather
    than "a load failure", matching how plan 11 §3's own generated-code
    example presents it.

    **`outline:`'s stamp loop moves inside this same guard** (plan 15 §5):
    a missing vector font draws nothing at all, ring included, exactly as
    it draws nothing today -- one `if (font != null)`, never two.
    """
    element = placed.element
    field = f"_{_field(placed.font_reference)}"
    w.line(f"var font = {field};")
    with w.block("if (font != null)"):
        if element.outline is not None:
            _emit_outline_loop(
                w, element.outline.width, _color(element.outline.color),
                f"Layout.{prefix}_X", f"Layout.{prefix}_Y",
                lambda x, y: _emit_vector_draw_call(w, placed, prefix, justify, value_code, x, y),
            )
        w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
        _emit_vector_draw_call(
            w, placed, prefix, justify, value_code, f"Layout.{prefix}_X", f"Layout.{prefix}_Y")
