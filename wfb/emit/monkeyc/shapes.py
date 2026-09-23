"""Element emitters for the plain drawing primitives: shape, text and progress."""

from __future__ import annotations

from collections.abc import Callable

from ... import formatting
from ...ir import Progress, local_name
from ...layout import PlacedIcon, PlacedProgress, PlacedShape, PlacedText, ResolvedFace
from .common import (
    AodDim, _aod_color, _aod_font_field, _aod_value, _color, _const_prefix, _field,
    _glyph_y_expr, _jitter_terms,
)
from ..writer import Writer


def _emit_arc_span(w: Writer, prefix: str, thickness_expr: str | None = None,
                   jitter: tuple[str, str] = ("", "")) -> None:
    """The two-line `WfbArc.drawSpan(...)` call against one arc's own
    `_CX/_CY/_RADIUS/_THICKNESS/_START/_SWEEP` constants -- identical whether
    it is a plain `shape: arc` or a `progress` arc's unfilled track, which is
    exactly why the two go through the one barrel helper: they cannot
    disagree about the angle convention or the full-circle case (drawArc
    draws a complete circle when start == end). ``thickness_expr`` defaults
    to the plain `Layout.<P>_THICKNESS` constant; a `progress` arc's track
    passes its own `aod: {thickness: ...}` ternary instead, so the unfilled
    track and the filled portion always agree on which pen width is current.
    ``jitter`` (`_jitter_terms`) shifts the centre only -- the radius does
    not move, an offset is a translation, not a resize.
    """
    if thickness_expr is None:
        thickness_expr = f"Layout.{prefix}_THICKNESS"
    dx, dy = jitter
    w.line(
        f"WfbArc.drawSpan(dc, Layout.{prefix}_CX{dx}, Layout.{prefix}_CY{dy}, "
        f"Layout.{prefix}_RADIUS,"
    )
    w.line(
        f"                {thickness_expr}, Layout.{prefix}_START, "
        f"Layout.{prefix}_SWEEP);"
    )


def _thickness_expr(prefix: str, placed, aod: bool) -> str:
    """`Layout.<P>_THICKNESS`, ternary against `_AOD_THICKNESS` when this
    element's resolved `aod:` overrides `thickness:` (plan 14 §4.2) and
    this build ever emits AOD code (`aod`) -- the plain constant otherwise,
    byte-identical to before this override existed.
    """
    base = f"Layout.{prefix}_THICKNESS"
    override = f"Layout.{prefix}_AOD_THICKNESS" if placed.aod_thickness is not None else None
    return _aod_value(aod, override, base)


def _circle_thickness_expr(placed, aod: bool) -> str:
    """A circle's own pen width is a plain per-device literal, not a
    `Layout` constant (`_layout_constants`'s own note on why) -- so its
    `aod: {thickness: ...}` override is inlined the same way."""
    override = str(placed.aod_thickness) if placed.aod_thickness is not None else None
    return _aod_value(aod, override, str(placed.thickness))


def _shape_filled_override(element, aod: bool) -> bool:
    """Does this shape's resolved `aod:` flip `filled:` (plan 14 §4.2) --
    `True` only when this build ever emits AOD code, an override exists, and
    it actually differs from the awake `filled:`; a same-valued override
    changes nothing and is not worth a runtime branch.
    """
    return (
        aod and element.aod is not None and element.aod.filled is not None
        and element.aod.filled != element.filled
    )


def _emit_shape(w: Writer, placed: PlacedShape, aod: bool = False, dim: AodDim = None) -> None:
    element = placed.element
    prefix = _const_prefix(placed.id)
    color_code = _aod_color(element, "color", _color(element.color), aod, dim)
    w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
    filled_override = _shape_filled_override(element, aod)
    # `aod: {jitter: ...}` (plan 14 §5.2): '' for both unless this element
    # resolves into a jittered AOD scope -- see `_jitter_terms`.
    dx, dy = _jitter_terms(placed, aod)

    if element.shape == "rectangle":
        thickness_expr = _thickness_expr(prefix, placed, aod)

        def draw_filled() -> None:
            w.line(f"dc.fillRectangle(Layout.{prefix}_X{dx}, Layout.{prefix}_Y{dy},")
            w.line(f"                 Layout.{prefix}_WIDTH, Layout.{prefix}_HEIGHT);")

        def draw_outline() -> None:
            w.line(f"dc.setPenWidth({thickness_expr});")
            w.line(f"dc.drawRectangle(Layout.{prefix}_X{dx}, Layout.{prefix}_Y{dy},")
            w.line(f"                 Layout.{prefix}_WIDTH, Layout.{prefix}_HEIGHT);")
            w.line("dc.setPenWidth(1);")

        _emit_filled_toggle(w, element.filled, filled_override, draw_filled, draw_outline)
    elif element.shape == "rounded_rectangle":
        thickness_expr = _thickness_expr(prefix, placed, aod)

        def draw_filled() -> None:
            w.line(f"dc.fillRoundedRectangle(Layout.{prefix}_X{dx}, Layout.{prefix}_Y{dy},")
            w.line(f"                        Layout.{prefix}_WIDTH, Layout.{prefix}_HEIGHT,")
            w.line(f"                        Layout.{prefix}_CORNER);")

        def draw_outline() -> None:
            w.line(f"dc.setPenWidth({thickness_expr});")
            w.line(f"dc.drawRoundedRectangle(Layout.{prefix}_X{dx}, Layout.{prefix}_Y{dy},")
            w.line(f"                        Layout.{prefix}_WIDTH, Layout.{prefix}_HEIGHT,")
            w.line(f"                        Layout.{prefix}_CORNER);")
            w.line("dc.setPenWidth(1);")

        _emit_filled_toggle(w, element.filled, filled_override, draw_filled, draw_outline)
    elif element.shape == "arc":
        # The same barrel call a `progress` track uses, so the two arcs cannot
        # disagree about the angle convention or about the full-circle case
        # (drawArc draws a complete circle when start == end).
        _emit_arc_span(w, prefix, _thickness_expr(prefix, placed, aod), (dx, dy))
    elif element.shape == "ellipse":
        thickness_expr = _thickness_expr(prefix, placed, aod)

        def draw_filled() -> None:
            w.line(f"dc.fillEllipse(Layout.{prefix}_CX{dx}, Layout.{prefix}_CY{dy},")
            w.line(f"               Layout.{prefix}_RX, Layout.{prefix}_RY);")

        def draw_outline() -> None:
            w.line(f"dc.setPenWidth({thickness_expr});")
            w.line(f"dc.drawEllipse(Layout.{prefix}_CX{dx}, Layout.{prefix}_CY{dy},")
            w.line(f"               Layout.{prefix}_RX, Layout.{prefix}_RY);")
            w.line("dc.setPenWidth(1);")

        _emit_filled_toggle(w, element.filled, filled_override, draw_filled, draw_outline)
    elif element.shape == "polygon":
        # There is no drawPolygon in Dc, only fillPolygon -- `filled: false`
        # is rejected in wfb/ir/builder.py rather than silently filled here,
        # and an `aod: {filled: ...}` override on a polygon is rejected
        # there too (`Builder._build_aod_authored`, a friendly build error,
        # not a schema restriction: the schema does not discriminate by
        # `shape:` value), so `filled_override` is never true here.
        if dx or dy:
            # `_POINTS` is a build-time-constant `Array<Point2D>` -- there is
            # no single X/Y to append a jitter term to, so each vertex is
            # rebuilt as its own two-element array instead, one line per
            # point (the point count is known at build time, from
            # `placed.points`, so this is exactly as static as the
            # unjittered call, just spelled out rather than a bare constant
            # reference).
            w.line("dc.fillPolygon([")
            count = len(placed.points)
            for i in range(count):
                comma = "," if i < count - 1 else ""
                w.line(
                    f"    [Layout.{prefix}_POINTS[{i}][0]{dx}, "
                    f"Layout.{prefix}_POINTS[{i}][1]{dy}]{comma}"
                )
            w.line("]);")
        else:
            w.line(f"dc.fillPolygon(Layout.{prefix}_POINTS);")
    elif element.shape == "circle":
        thickness_expr = _circle_thickness_expr(placed, aod)

        def draw_filled() -> None:
            w.line(f"dc.fillCircle(Layout.{prefix}_CX{dx}, Layout.{prefix}_CY{dy}, "
                  f"Layout.{prefix}_RADIUS);")

        def draw_outline() -> None:
            w.line(f"dc.setPenWidth({thickness_expr});")
            w.line(f"dc.drawCircle(Layout.{prefix}_CX{dx}, Layout.{prefix}_CY{dy}, "
                  f"Layout.{prefix}_RADIUS);")
            w.line("dc.setPenWidth(1);")

        _emit_filled_toggle(w, element.filled, filled_override, draw_filled, draw_outline)
    elif element.shape == "line":
        thickness_expr = _thickness_expr(prefix, placed, aod)
        w.line(f"dc.setPenWidth({thickness_expr});")
        w.line(
            f"dc.drawLine(Layout.{prefix}_CX{dx}, Layout.{prefix}_CY{dy}, "
            f"Layout.{prefix}_END_X{dx}, Layout.{prefix}_END_Y{dy});"
        )
        w.line("dc.setPenWidth(1);")


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


def _emit_text(w: Writer, resolved: ResolvedFace, placed: PlacedText, guards: list[str],
              aod: bool = False, dim: AodDim = None) -> None:
    element = placed.element
    if element.literal is not None:
        _emit_text_draw(w, resolved, placed, f'"{element.literal}"', aod, dim)
        return

    value_code = formatting.emit(
        element.format or "{}",
        element.value.code,
        element.value.value.type,
    )
    if aod and element.aod is not None and element.aod.format is not None:
        # `format:` changes the formatting code, not just an argument -- the
        # same "AOD redraws once a minute anyway, so dropping seconds is
        # free" reasoning plan 14 §2.3 states -- so both formatted strings
        # are built once, up front, and the ternary between them stands in
        # for `value_code` everywhere below, including inside a
        # placeholder/fallback substitution.
        aod_value_code = formatting.emit(
            element.aod.format, element.value.code, element.value.value.type)
        value_code = _aod_value(True, aod_value_code, value_code)
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
        _emit_text_draw(w, resolved, placed, "text", aod, dim)
        return
    _emit_text_draw(w, resolved, placed, value_code, aod, dim)


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

    **The ring colour is set once, before the loop, not once per stamp.**
    Every stamp draws in the same `color_code` -- `width:`/the offset table
    change *where* each stamp lands, never *what colour* it lands in
    (§2.3/§8: `outline.color` is one fixed expression per element, not a
    per-offset one) -- and `draw` itself is always one of
    `_emit_plain_text_call`/`_emit_vector_draw_call`, both pure `dc.
    drawText`/`drawAngledText`/`drawRadialText` calls that never touch
    `dc`'s colour state themselves. So nothing between one `dc.setColor`
    and the next stamp can change it, and re-issuing the identical call on
    every iteration was pure waste -- `Dc`'s colour is state that persists
    across calls, not a per-draw argument, so setting it once before the
    `while` is behaviourally identical and strictly fewer device-side
    calls. (The *interior* pass's own `dc.setColor`, at each call site
    below, is untouched: it sets a different colour and runs only once,
    after this loop, not inside it, so there was never a duplicate there
    to remove.)

    `index_var`/`offsets_var` default to `"i"`/`"offsets"` -- the exact
    names slice 1 always used, so every pre-slice-2 caller (a standalone
    `text` element, one generated method per element) is byte-for-byte
    unaffected. A pattern's own `shape: text` part (plan 15 §14 slice 2)
    passes distinct names instead: every part of one pattern shares a
    single generated method (`_emit_pattern`'s per-copy loop body), which
    already declares its own `var i` for the copy index, and more than one
    outlined text part in the same pattern would otherwise also collide
    with each other's `offsets`/`i` -- Monkey C rejects redefining a
    variable even across what look like separate straight-line statements
    in the same method, confirmed by a real `monkeyc` run
    (`Redefinition of variable 'i'`) before this parameter existed.
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
    """One `dc.drawText` call against a baked or system font, at the given
    screen-space anchor -- shared by the interior pass and every
    `outline:` stamp (plan 15 §5, §8), the only difference between them
    being which anchor is passed in.
    """
    y = _glyph_y_expr(y_expr, vertical_align, font_expr)
    w.line(f"dc.drawText({x_expr}, {y}, {font_expr},")
    w.line(f"            {value_code},")
    w.line(f"            {justify});")


def _emit_text_draw(w: Writer, resolved: ResolvedFace, placed: PlacedText, value_code: str,
                    aod: bool = False, dim: AodDim = None) -> None:
    element = placed.element
    prefix = _const_prefix(placed.id)
    justify = " | ".join(f"Graphics.{flag}" for flag in placed.justify)
    color_code = _aod_color(element, "color", _color(element.color), aod, dim)
    jitter = _jitter_terms(placed, aod)
    if placed.font_is_vector:
        _emit_vector_text_draw(w, placed, prefix, justify, value_code, color_code, jitter)
        return
    dx, dy = jitter
    override_expr = None
    if aod and element.aod is not None and element.aod.font is not None:
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
        base_font_expr = f"Graphics.{placed.font_reference}"
        font_expr = _aod_value(aod, override_expr, base_font_expr)
    if element.outline is not None:
        _emit_outline_loop(
            w, element.outline.width, _color(element.outline.color),
            f"Layout.{prefix}_X{dx}", f"Layout.{prefix}_Y{dy}",
            lambda x, y: _emit_plain_text_call(
                w, x, y, font_expr, value_code, justify, element.vertical_align),
        )
    w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
    _emit_plain_text_call(
        w, f"Layout.{prefix}_X{dx}", f"Layout.{prefix}_Y{dy}", font_expr, value_code, justify,
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
    color_code: str | None = None, jitter: tuple[str, str] = ("", ""),
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
    dx, dy = jitter
    w.line(f"var font = {field};")
    with w.block("if (font != null)"):
        if element.outline is not None:
            _emit_outline_loop(
                w, element.outline.width, _color(element.outline.color),
                f"Layout.{prefix}_X{dx}", f"Layout.{prefix}_Y{dy}",
                lambda x, y: _emit_vector_draw_call(w, placed, prefix, justify, value_code, x, y),
            )
        w.line(f"dc.setColor({color_code if color_code is not None else _color(element.color)}, "
              "Graphics.COLOR_TRANSPARENT);")
        _emit_vector_draw_call(
            w, placed, prefix, justify, value_code, f"Layout.{prefix}_X{dx}",
            f"Layout.{prefix}_Y{dy}")


def _emit_progress(w: Writer, placed: PlacedProgress, guards: list[str], aod: bool = False,
                   dim: AodDim = None) -> None:
    element = placed.element
    prefix = _const_prefix(placed.id)
    fraction_expr = _fraction(element)
    color_code = _aod_color(element, "color", _color(element.color), aod, dim)
    dx, dy = _jitter_terms(placed, aod)
    track_color_code = (
        _aod_color(element, "track_color", _color(element.track_color), aod, dim)
        if element.track_color is not None else None
    )
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
        thickness_expr = _thickness_expr(prefix, placed, aod)
        if element.track_color is not None:
            w.comment("the unfilled track")
            w.line(f"dc.setColor({track_color_code}, Graphics.COLOR_TRANSPARENT);")
            _emit_arc_span(w, prefix, thickness_expr, (dx, dy))
            w.blank()
        w.comment("the filled portion")
        w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
        w.line(
            f"WfbArc.drawProgress(dc, Layout.{prefix}_CX{dx}, Layout.{prefix}_CY{dy}, "
            f"Layout.{prefix}_RADIUS,"
        )
        w.line(
            f"                    {thickness_expr}, Layout.{prefix}_START, "
            f"Layout.{prefix}_SWEEP,"
        )
        w.line(f"                    {fraction_expr});")
        return

    if element.track_color is not None:
        w.line(f"dc.setColor({track_color_code}, Graphics.COLOR_TRANSPARENT);")
        w.line(
            f"dc.fillRectangle(Layout.{prefix}_X{dx}, Layout.{prefix}_Y{dy}, "
            f"Layout.{prefix}_WIDTH, Layout.{prefix}_HEIGHT);"
        )
        w.blank()
    w.line(f"var filled = (Layout.{prefix}_WIDTH * {fraction_expr}).toNumber();")
    w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
    w.line(
        f"dc.fillRectangle(Layout.{prefix}_X{dx}, Layout.{prefix}_Y{dy}, filled, "
        f"Layout.{prefix}_HEIGHT);"
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


def _emit_icon(w: Writer, placed: PlacedIcon, aod: bool = False, dim: AodDim = None) -> None:
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
    dx, dy = _jitter_terms(placed, aod)
    y_expr = _glyph_y_expr(f"Layout.{prefix}_CY{dy}", element.vertical_align, "font")
    color_code = _aod_color(element, "color", _color(element.color), aod, dim)
    w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
    w.line(f"dc.drawText(Layout.{prefix}_CX{dx}, {y_expr}, font,")
    w.line(f"            {glyph_expr},")
    w.line(f"            {justify});")
