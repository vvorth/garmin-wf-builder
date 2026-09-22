"""Element emitters for the plain drawing primitives: shape, text and progress."""

from __future__ import annotations

from collections.abc import Callable

from ... import formatting
from ...ir import Progress, local_name
from ...layout import PlacedIcon, PlacedProgress, PlacedShape, PlacedText, ResolvedFace
from .common import _color, _const_prefix, _field, _glyph_y_expr
from ..writer import Writer


def _emit_arc_span(w: Writer, prefix: str) -> None:
    """The two-line `WfbArc.drawSpan(...)` call against one arc's own
    `_CX/_CY/_RADIUS/_THICKNESS/_START/_SWEEP` constants -- identical whether
    it is a plain `shape: arc` or a `progress` arc's unfilled track, which is
    exactly why the two go through the one barrel helper: they cannot
    disagree about the angle convention or the full-circle case (drawArc
    draws a complete circle when start == end).
    """
    w.line(
        f"WfbArc.drawSpan(dc, Layout.{prefix}_CX, Layout.{prefix}_CY, "
        f"Layout.{prefix}_RADIUS,"
    )
    w.line(
        f"                Layout.{prefix}_THICKNESS, Layout.{prefix}_START, "
        f"Layout.{prefix}_SWEEP);"
    )


def _emit_shape(w: Writer, placed: PlacedShape) -> None:
    element = placed.element
    prefix = _const_prefix(placed.id)
    w.line(f"dc.setColor({_color(element.color)}, Graphics.COLOR_TRANSPARENT);")
    if element.shape == "rectangle":
        if element.filled:
            w.line(f"dc.fillRectangle(Layout.{prefix}_X, Layout.{prefix}_Y,")
            w.line(f"                 Layout.{prefix}_WIDTH, Layout.{prefix}_HEIGHT);")
        else:
            w.line(f"dc.setPenWidth(Layout.{prefix}_THICKNESS);")
            w.line(f"dc.drawRectangle(Layout.{prefix}_X, Layout.{prefix}_Y,")
            w.line(f"                 Layout.{prefix}_WIDTH, Layout.{prefix}_HEIGHT);")
            w.line("dc.setPenWidth(1);")
    elif element.shape == "rounded_rectangle":
        if element.filled:
            w.line(f"dc.fillRoundedRectangle(Layout.{prefix}_X, Layout.{prefix}_Y,")
            w.line(f"                        Layout.{prefix}_WIDTH, Layout.{prefix}_HEIGHT,")
            w.line(f"                        Layout.{prefix}_CORNER);")
        else:
            w.line(f"dc.setPenWidth(Layout.{prefix}_THICKNESS);")
            w.line(f"dc.drawRoundedRectangle(Layout.{prefix}_X, Layout.{prefix}_Y,")
            w.line(f"                        Layout.{prefix}_WIDTH, Layout.{prefix}_HEIGHT,")
            w.line(f"                        Layout.{prefix}_CORNER);")
            w.line("dc.setPenWidth(1);")
    elif element.shape == "arc":
        # The same barrel call a `progress` track uses, so the two arcs cannot
        # disagree about the angle convention or about the full-circle case
        # (drawArc draws a complete circle when start == end).
        _emit_arc_span(w, prefix)
    elif element.shape == "ellipse":
        if element.filled:
            w.line(f"dc.fillEllipse(Layout.{prefix}_CX, Layout.{prefix}_CY,")
            w.line(f"               Layout.{prefix}_RX, Layout.{prefix}_RY);")
        else:
            w.line(f"dc.setPenWidth(Layout.{prefix}_THICKNESS);")
            w.line(f"dc.drawEllipse(Layout.{prefix}_CX, Layout.{prefix}_CY,")
            w.line(f"               Layout.{prefix}_RX, Layout.{prefix}_RY);")
            w.line("dc.setPenWidth(1);")
    elif element.shape == "polygon":
        # There is no drawPolygon in Dc, only fillPolygon -- `filled: false` is
        # rejected in wfb/ir.py rather than silently filled here.
        w.line(f"dc.fillPolygon(Layout.{prefix}_POINTS);")
    elif element.shape == "circle":
        if element.filled:
            w.line(f"dc.fillCircle(Layout.{prefix}_CX, Layout.{prefix}_CY, Layout.{prefix}_RADIUS);")
        else:
            w.line(f"dc.setPenWidth({placed.thickness});")
            w.line(f"dc.drawCircle(Layout.{prefix}_CX, Layout.{prefix}_CY, Layout.{prefix}_RADIUS);")
            w.line("dc.setPenWidth(1);")
    elif element.shape == "line":
        w.line(f"dc.setPenWidth(Layout.{prefix}_THICKNESS);")
        w.line(
            f"dc.drawLine(Layout.{prefix}_CX, Layout.{prefix}_CY, "
            f"Layout.{prefix}_END_X, Layout.{prefix}_END_Y);"
        )
        w.line("dc.setPenWidth(1);")


def _emit_text(w: Writer, resolved: ResolvedFace, placed: PlacedText, guards: list[str]) -> None:
    element = placed.element
    if element.literal is not None:
        _emit_text_draw(w, placed, f'"{element.literal}"')
        return

    value_code = formatting.emit(
        element.format or "{}",
        element.value.code,
        element.value.value.type,
    )
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
        _emit_text_draw(w, placed, "text")
        return
    _emit_text_draw(w, placed, value_code)


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
    draw: Callable[[str, str], None],
) -> None:
    """The stamp loop `outline:` runs ahead of a text draw call's own
    (unshifted) interior pass (plan 15 §5, §8): loops over
    `Layout.OUTLINE_OFFSETS_<width>` (the disc-perimeter table
    `wfb.emit.monkeyc.layout_constants` already emitted for this width),
    calling `draw` at each shifted screen-space anchor in the ring colour.

    `draw(x_expr, y_expr)` emits exactly the draw-call line(s) the interior
    pass would emit at that anchor -- everything else about the call
    (font, value, justify, angle, radius, direction) is left to `draw`
    itself, unaffected by which anchor it was given: a screen-space anchor
    shift commutes with whatever the call does with the rest of its
    arguments (research 14 §3.2), so the very same callback the caller
    already built for its own interior draw serves every stamp too.
    """
    w.line(f"var offsets = Layout.OUTLINE_OFFSETS_{width};")
    w.line("var i = 0;")
    with w.block("while (i < offsets.size())"):
        w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
        draw(f"{x_expr} + offsets[i]", f"{y_expr} + offsets[i + 1]")
        w.line("i += 2;")
    w.blank()


def _emit_plain_text_call(
    w: Writer, x_expr: str, y_expr: str, font_expr: str, value_code: str, justify: str,
    vertical_align: str,
) -> None:
    """One `dc.drawText` call against a baked or system font, at the given
    screen-space anchor -- shared by the interior pass and every
    `outline:` stamp (plan 15 §5, §8), the only difference between them
    being which anchor is passed in.
    """
    y = _glyph_y_expr(y_expr, vertical_align, font_expr)
    w.line(f"dc.drawText({x_expr}, {y}, {font_expr},")
    w.line(f"            {value_code},")
    w.line(f"            {justify});")


def _emit_text_draw(w: Writer, placed: PlacedText, value_code: str) -> None:
    element = placed.element
    prefix = _const_prefix(placed.id)
    justify = " | ".join(f"Graphics.{flag}" for flag in placed.justify)
    if placed.font_is_vector:
        _emit_vector_text_draw(w, placed, prefix, justify, value_code)
        return
    if placed.font_is_custom:
        w.line(f"var font = _{_field(placed.font_reference)};")
        with w.block("if (font == null)"):
            w.line("return;  // the font resource failed to load")
        w.blank()
        font_expr = "font"
    else:
        font_expr = f"Graphics.{placed.font_reference}"
    if element.outline is not None:
        _emit_outline_loop(
            w, element.outline.width, _color(element.outline.color),
            f"Layout.{prefix}_X", f"Layout.{prefix}_Y",
            lambda x, y: _emit_plain_text_call(
                w, x, y, font_expr, value_code, justify, element.vertical_align),
        )
    w.line(f"dc.setColor({_color(element.color)}, Graphics.COLOR_TRANSPARENT);")
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
        w.line(f"dc.drawAngledText({x_expr}, {y_expr}, font, {value_code},")
        w.line(f"                  {justify}, Layout.{prefix}_ANGLE);")
    elif placed.curve_style == "radial":
        direction = _RADIAL_DIRECTION[placed.curve_direction or "clockwise"]
        radius = _radial_radius_expr(f"Layout.{prefix}_RADIUS", element.vertical_align,
                                     placed.curve_direction, "font")
        w.line(f"dc.drawRadialText({x_expr}, {y_expr}, font, {value_code},")
        w.line(f"                  {justify}, Layout.{prefix}_ANGLE, {radius},")
        w.line(f"                  Graphics.{direction});")
    else:
        y = _glyph_y_expr(y_expr, element.vertical_align, "font")
        w.line(f"dc.drawText({x_expr}, {y}, font,")
        w.line(f"            {value_code},")
        w.line(f"            {justify});")


def _emit_vector_text_draw(
    w: Writer, placed: PlacedText, prefix: str, justify: str, value_code: str,
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
        w.line(f"dc.setColor({_color(element.color)}, Graphics.COLOR_TRANSPARENT);")
        _emit_vector_draw_call(
            w, placed, prefix, justify, value_code, f"Layout.{prefix}_X", f"Layout.{prefix}_Y")


def _emit_progress(w: Writer, placed: PlacedProgress, guards: list[str]) -> None:
    element = placed.element
    prefix = _const_prefix(placed.id)
    fraction_expr = _fraction(element)
    if element.when_absent == "fallback" and guards:
        # The fill fraction falls back, not the raw value/max -- 'fallback:'
        # supplies a number in the same 0.0-1.0 range _fraction() computes, so
        # it slots into exactly the same drawProgress/fillRectangle call the
        # real reading would have used.  (This is why a `progress` fallback
        # means something different from a `text` one, which supplies the
        # *value* and is then formatted; for progress either half of the pair
        # can be the absent reading, so the outcome is the only well-defined
        # thing to substitute.  wfb/ir.py checks it is in range and
        # wfb/preview.py renders the same substitution.)
        w.comment("when_absent: fallback")
        available = " && ".join(f"{name} != null" for name in guards)
        w.line(f"var fraction = {_fallback_fraction(element)};")
        with w.block(f"if ({available})"):
            w.line(f"fraction = {fraction_expr};")
        w.blank()
        fraction_expr = "fraction"
    if element.style == "arc":
        if element.track_color is not None:
            w.comment("the unfilled track")
            w.line(f"dc.setColor({_color(element.track_color)}, Graphics.COLOR_TRANSPARENT);")
            _emit_arc_span(w, prefix)
            w.blank()
        w.comment("the filled portion")
        w.line(f"dc.setColor({_color(element.color)}, Graphics.COLOR_TRANSPARENT);")
        w.line(
            f"WfbArc.drawProgress(dc, Layout.{prefix}_CX, Layout.{prefix}_CY, "
            f"Layout.{prefix}_RADIUS,"
        )
        w.line(
            f"                    Layout.{prefix}_THICKNESS, Layout.{prefix}_START, "
            f"Layout.{prefix}_SWEEP,"
        )
        w.line(f"                    {fraction_expr});")
        return

    if element.track_color is not None:
        w.line(f"dc.setColor({_color(element.track_color)}, Graphics.COLOR_TRANSPARENT);")
        w.line(
            f"dc.fillRectangle(Layout.{prefix}_X, Layout.{prefix}_Y, "
            f"Layout.{prefix}_WIDTH, Layout.{prefix}_HEIGHT);"
        )
        w.blank()
    w.line(f"var filled = (Layout.{prefix}_WIDTH * {fraction_expr}).toNumber();")
    w.line(f"dc.setColor({_color(element.color)}, Graphics.COLOR_TRANSPARENT);")
    w.line(
        f"dc.fillRectangle(Layout.{prefix}_X, Layout.{prefix}_Y, filled, Layout.{prefix}_HEIGHT);"
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
    time (wfb/ir.py) and emitted bare; anything else is clamped on device.
    """
    fallback = element.fallback
    if fallback.is_constant:
        return f"{float(fallback.constant)}f"
    return f"WfbMath.clamp({fallback.code}, 0.0, 1.0).toFloat()"


def _fraction(element: Progress) -> str:
    return f"WfbMath.percent({element.value.code}, {element.maximum.code}) / 100.0"


def _emit_icon(w: Writer, placed: PlacedIcon) -> None:
    """A `drawText` call against the icon's baked glyph -- see `wfb.icons`:
    an icon is a one-character string drawn with a bitmap font, the same
    mechanism any other bound text uses, not a hand-drawn shape.

    A *dynamic* icon (`icon_for:`) draws the same way, except the glyph
    string is resolved in two steps at runtime instead of being a literal
    baked in at build time: `WfbWeather.chooseIcon` picks a catalogue *name*
    from the bound value, and `IconGlyphs.glyph` (generated per project,
    directly from `wfb.icon_catalog.CATALOG`) turns that name into the actual
    character -- the same table any static icon's build-time lookup uses, not
    a second, weather-only one. The font still has every glyph that call
    could return, baked in ahead of time (`wfb.emit.resources.icon_font_specs`).

    `align`/`vertical_align` place the glyph the same way a `text` element
    does: `placed.justify` (`Resolver._justify`) picks the `TEXT_JUSTIFY_*`
    flags, and `_glyph_y_expr` handles `bottom`'s missing platform flag by
    subtracting the *icon* font's own `dc.getFontHeight` -- the anchor
    itself (`Layout.<P>_CX/_CY`) never moves; center/center yields the same
    literal flags whether or not `align`/`vertical_align` are given.
    """
    element = placed.element
    prefix = _const_prefix(placed.id)
    w.line(f"var font = _{_field(placed.font_key)};")
    with w.block("if (font == null)"):
        w.line("return;  // the icon font resource failed to load")
    w.blank()
    if element.is_dynamic:

        condition_local = local_name(element.value_for.sources[0])
        w.comment(f"{element.value_for.text!r} -> a name (WfbWeather) -> a glyph (IconGlyphs)")
        glyph_expr = f"IconGlyphs.glyph(WfbWeather.chooseIcon({condition_local}))"
    else:
        w.comment(f"{element.icon!r}")
        glyph_expr = f'"{element.codepoint}"'
    justify = " | ".join(f"Graphics.{flag}" for flag in placed.justify)
    y_expr = _glyph_y_expr(f"Layout.{prefix}_CY", element.vertical_align, "font")
    w.line(f"dc.setColor({_color(element.color)}, Graphics.COLOR_TRANSPARENT);")
    w.line(f"dc.drawText(Layout.{prefix}_CX, {y_expr}, font,")
    w.line(f"            {glyph_expr},")
    w.line(f"            {justify});")
