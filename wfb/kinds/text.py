"""`type: text` -- a bound or literal string, optionally curved onto a
`face:` (vector) font."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dataclasses import replace

from .. import catalog, expr, formatting
from ..catalog import Type
from ..devices import FontMetric
from ..fonts import BakedFont
from ..ir.model import Element, Expression, Text
from ..layout import Placed, PlacedText, _longer, resolved_curve, text_ink
from ..units import Axis, Box
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc import shapes
from ..emit.monkeyc.common import NO_AOD, AodStyle, _aod_font_field, _color, _const_prefix, _field
from ..emit.writer import Writer
from . import ElementKind, TextRun

if TYPE_CHECKING:
    from ..ir.builder import Builder
    from ..layout import Resolver
    from ..preview import _Renderer


def _reject_text_antialias(b, node: dict, element: Text) -> None:
    """`antialias:` on a `text` element -- a per-element key on a shared resource.

    A text element draws through a font declared in `fonts:`, and that
    font is one bitmap resource shared by every element that references
    it (`font: font.clock` is a name, not a private copy) -- so
    anti-aliasing cannot vary per element the way it can on a shape's own
    outline or an icon's own, per-glyph font.  The schema still parses
    `antialias:` here rather than rejecting it as an unknown key, purely
    so this can name the actual font instead of jsonschema's generic
    "unknown key" message: by the time `_resolve_font` above has run,
    `element.font` is the real answer, not a guess.
    """
    span = b.doc.span(node, "antialias")
    if element.font_is_custom:
        notes = [f"put it on 'fonts: {element.font}: antialias:' instead -- "
                 f"the font this element references"]
    else:
        notes = [f"this element uses the system font {element.font!r}, which "
                 "has no 'antialias:' of its own to set -- only a custom "
                 "'fonts:' entry does"]
    b.bag.error(
        "text-antialias",
        f"{element.id}: 'antialias:' is not accepted on a 'text' element",
        span,
        notes=notes,
    )


def _widest_text(element: Text) -> str:
    if element.literal is not None:
        return element.literal
    if element.value is None:
        return ""
    source = catalog.get(element.value.sources[0]) if element.value.sources else None
    spec = element.format or "{}"
    widest = formatting.widest(spec, source, element.value.value.type,
                               element.value.scale)
    if element.when_absent == "placeholder" and element.placeholder:
        widest = _longer(widest, element.placeholder)
    if element.when_absent == "fallback" and element.fallback is not None:
        # 'fallback:' is drawn through the exact same format spec as the
        # real value (see `wfb.kinds.text.TextKind.emit_draw`), so its widest
        # rendering has to be considered too -- otherwise a font baked
        # from the *value*'s digit range alone can come up short for a
        # wider fallback (e.g. a longer literal string on a nullable
        # STRING source).
        widest = _longer(widest, _fallback_widest(element.fallback, spec))
    return widest


def _fallback_widest(fallback_expr: Expression, spec: str) -> str:
    """The widest string a `fallback:` expression could render, through the
    same format spec the bound value uses (see `wfb.kinds.text.TextKind.emit_draw`).

    A literal string fallback (`fallback: "N/A"`) renders exactly as written,
    the same way `placeholder:` already does above -- `formatting.widest`'s
    digit-based estimate has no way to guess the content of an arbitrary
    string, so a literal one is used verbatim.  Anything else (typically a
    numeric literal, or an expression over a non-nullable source) goes
    through the same digit-count estimate the bound value itself uses, keyed
    off the fallback's own source when it has one.
    """
    if fallback_expr.value.type is Type.STRING and fallback_expr.constant is not None:
        return str(fallback_expr.constant)
    source = catalog.get(fallback_expr.sources[0]) if fallback_expr.sources else None
    return formatting.widest(spec, source, fallback_expr.value.type, fallback_expr.scale)



def _glyphs(element: Text) -> tuple[set[str], set[str]]:
    """The characters `element`'s font must hold, and those its own `aod:
    {font: ...}` override must: the same string, through its own `format:`
    override if it has one -- never the "0123456789" an empty set would
    otherwise bake with."""
    if element.literal is not None:
        return set(element.literal), set(element.literal)
    if element.value is None:
        return set(), set()
    source = catalog.get(element.value.sources[0]) if element.value.sources else None
    spec = element.format or "{}"
    value_glyphs = formatting.glyphs(spec, source, element.value.value.type, element.value.scale)
    glyphs = set(value_glyphs)
    aod = element.aod
    aod_spec = aod.format if aod is not None and aod.format is not None else spec
    aod_glyphs = (
        set(value_glyphs) if aod_spec == spec
        else formatting.glyphs(aod_spec, source, element.value.value.type, element.value.scale)
    )
    if element.placeholder:
        glyphs |= set(element.placeholder)
    if element.when_absent == "fallback" and element.fallback is not None:
        # 'fallback:' is drawn through the same format spec as the real
        # value -- a literal string fallback renders exactly as written,
        # the same way 'placeholder:' is handled above; anything else goes
        # through the same digit-set formatting.glyphs already adds for
        # the value.
        fallback = element.fallback
        if fallback.value.type is catalog.Type.STRING and fallback.constant is not None:
            glyphs |= set(str(fallback.constant))
        else:
            fallback_source = catalog.get(fallback.sources[0]) if fallback.sources else None
            glyphs |= formatting.glyphs(spec, fallback_source, fallback.value.type, fallback.scale)
    return glyphs, aod_glyphs

def _text_font(renderer, placed: PlacedText) -> tuple[BakedFont | None, FontMetric | None]:
    """The baked font (or `None` for a system one) and metric a non-vector
    `text` element draws with, after its `aod: {font: ...}` override --
    the same scope as codegen's `wfb.kinds.text._emit_text_draw`:
    an override naming a *different* baked font swaps the sheet, one
    naming a system `FONT_*` swaps the metric. A vector override is a
    build error (`Builder._build_aod_authored`), so the `is_vector`
    check is defensive."""
    element = placed.element
    font: BakedFont | None = (
        renderer.resolved.fonts.get(placed.font.reference) if placed.font.is_custom else None
    )
    metric = placed.font.metric
    aod_font = renderer._aod_field(element, "font", None)
    if aod_font is None or aod_font == placed.font.reference:
        return font, metric
    if element.aod.font_is_custom:
        override_spec = renderer.resolved.face.fonts.get(aod_font)
        if override_spec is not None and not override_spec.is_vector:
            override_font = renderer.resolved.fonts.get(aod_font)
            if override_font is not None:
                return override_font, None
    else:
        override_metric = renderer.resolved.device.system_fonts.get(aod_font)
        if override_metric is not None:
            return None, override_metric
    return font, metric


def _text_value(renderer, placed: PlacedText) -> str | None:
    element = placed.element
    if element.literal is not None:
        return element.literal
    if element.value is None:
        return None
    spec = renderer._aod_field(element, "format", element.format) or "{}"
    value_type = element.value.value.type
    if value_type in (Type.TIME, Type.DATE):
        return formatting.render(spec, None, value_type, renderer.values)
    value = expr.evaluate(element.value.ast, renderer.values) if element.value.ast else None
    if value is None:
        if element.when_absent == "placeholder":
            return element.placeholder
        if element.when_absent == "fallback" and element.fallback and element.fallback.ast:
            value = expr.evaluate(element.fallback.ast, renderer.values)
            if value is None:
                return None
        else:
            return None
    return formatting.render(spec, value, value_type)


def _emit_text_draw(w: Writer, resolved, placed: PlacedText, value_code: str,
                    aod: AodStyle = NO_AOD) -> None:
    element = placed.element
    prefix = _const_prefix(placed.id)
    justify = " | ".join(f"Graphics.{flag}" for flag in placed.justify)
    color_code = aod.color(element, "color")
    if placed.font.is_vector:
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
                    and element.aod.font != placed.font.reference):
                override_expr = f"_{_aod_font_field(element.aod.font)}"
    if placed.font.is_custom:
        w.line(f"var font = _{_field(placed.font.reference)};")
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
        font_expr = aod.value(override_expr, f"Graphics.{placed.font.reference}")
    if element.outline is not None:
        shapes._emit_outline_loop(
            w, element.outline.width, _color(element.outline.color),
            f"Layout.{prefix}_X", f"Layout.{prefix}_Y",
            lambda x, y: shapes._emit_plain_text_call(
                w, x, y, font_expr, value_code, justify, element.vertical_align),
        )
    w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
    shapes._emit_plain_text_call(
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
    if placed.curve.style == "angled":
        w.call("dc.drawAngledText", [
            f"{x_expr}, {y_expr}, font, {value_code}", f"{justify}, Layout.{prefix}_ANGLE",
        ])
    elif placed.curve.style == "radial":
        direction = shapes._RADIAL_DIRECTION[placed.curve.direction or "clockwise"]
        radius = shapes._radial_radius_expr(f"Layout.{prefix}_RADIUS", element.vertical_align,
                                            placed.curve.direction, "font")
        w.call("dc.drawRadialText", [
            f"{x_expr}, {y_expr}, font, {value_code}",
            f"{justify}, Layout.{prefix}_ANGLE, {radius}",
            f"Graphics.{direction}",
        ])
    else:
        shapes._emit_plain_text_call(w, x_expr, y_expr, "font", value_code, justify,
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
    field = f"_{_field(placed.font.reference)}"
    w.line(f"var font = {field};")
    with w.block("if (font != null)"):
        if element.outline is not None:
            shapes._emit_outline_loop(
                w, element.outline.width, _color(element.outline.color),
                f"Layout.{prefix}_X", f"Layout.{prefix}_Y",
                lambda x, y: _emit_vector_draw_call(w, placed, prefix, justify, value_code, x, y),
            )
        w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
        _emit_vector_draw_call(
            w, placed, prefix, justify, value_code, f"Layout.{prefix}_X", f"Layout.{prefix}_Y")


class TextKind(ElementKind):
    name = "text"
    ir_class = Text
    placed_class = PlacedText

    def build(self, b: Builder, node: dict, common: dict, path: tuple) -> Element:
        value = b._expression(node, "value") if "value" in node else None
        align, vertical_align = b._alignment(node)
        element = Text(
            **common,
            value=value,
            literal=node.get("text"),
            format=node.get("format"),
            color=b._color_expression(node, "color"),
            align=align,
            vertical_align=vertical_align,
            when_absent=node.get("when_absent"),
            placeholder=node.get("placeholder"),
            fallback=b._expression(node, "fallback") if "fallback" in node else None,
            if_unavailable=node.get("if_unavailable"),
        )
        font_ok = b._resolve_font(node, element)
        if "antialias" in node:
            _reject_text_antialias(b, node, element)
        font_is_vector = b._is_vector_font(element.font, element.font_is_custom)
        font_note = b._font_kind_note(element.font, element.font_is_custom)
        if "curve" in node:
            element.curve = b._build_curve(
                node, element.id, vertical_align=element.vertical_align, font_ok=font_ok,
                font_is_vector=font_is_vector, font_note=font_note)
        if font_ok and "if_unavailable" in node:
            b._check_if_unavailable(node, element.id, font_is_vector, font_note)
        if "outline" in node:
            element.outline = b._build_outline(node, "outline", element.id, element=element)
        own_aod_format = element.aod_own is not None and "format" in element.aod_own
        aod_format_span = (b.doc.span(node.get("aod"), "format") or b.doc.span(node, "aod")
                           if own_aod_format else None)
        if value is not None:
            b._check_absence(node, element, value, element.when_absent, element.placeholder,
                             element.fallback)
            b._check_format(node, value, element.format)
            if own_aod_format:
                # An `aod: {format: ...}` inherited from a group is checked
                # in `_resolve_aod` instead, once inheritance is resolved.
                b._check_format_spec(value, str(element.aod_own["format"]), aod_format_span)
        else:
            # A fixed `text:` has no bound value for `format:`, or its
            # `aod:` twin, to format.
            b._check_format_not_on_literal(node, element.id)
            refusal = b._aod_refusal("format", "text", None, literal_text=True)
            if own_aod_format and refusal is not None:
                code, what, notes = refusal
                b.bag.error(code, f"{element.id}.aod.format: {what}", aod_format_span,
                           notes=notes)
        b._check_other_absence(node, element, "color", element.color)
        b._check_reachable_substitute(node, element, "'color'",
                                      (element.value,), (element.color,))
        return element

    def resolve(self, r: Resolver, element: Text, parent: Box, depth: int) -> Placed:
        font = r._text_font(element.font, element.font_is_custom, element.id, element.curve)
        widest = _widest_text(element)
        # A baked sheet measures exactly; anything else is an estimate --
        # still a conservative, non-zero one for an *unavailable* vector
        # font, whose metric locates no face and falls to Pillow's default.
        width = font.width(widest)
        line_height = font.line_height

        x, y = r._point(element.at, parent)
        curve = resolved_curve(element.curve)
        if curve.style == "radial" and element.curve.radius is not None:
            curve = replace(curve, radius_px=round(r._extent(
                element.curve.radius, parent, Axis.MINOR, 0,
                min_1px=element.resolved_min_1px, what="curve.radius")))
        ring_px = float(element.outline.width) if element.outline is not None else 0.0
        box = text_ink(
            x, y, width, line_height, element.align, element.vertical_align,
            curve_style=curve.style, angle_garmin=curve.angle_garmin,
            radius_px=curve.radius_px, direction=curve.direction, metric=font.metric,
            pad=ring_px, fonts_root=r.device.fonts_root).box()

        return PlacedText(
            element, box.rounded(), (round(x), round(y)), depth,
            anchor_point=(round(x), round(y)),
            justify=r._justify(element),
            font=font.resolved(),
            widest=widest,
            measured_width=round(width),
            width_is_estimated=font.baked is None,
            curve=curve,
            line_height=line_height,
        )

    def aod_refusal(self, key, shape, literal_text):
        if key == "format" and literal_text:
            return ("format", "'aod: {format: ...}' applies only to 'value:', not a fixed 'text:'", [])
        return None

    def text_runs(self, element: Text, face) -> list[TextRun]:
        aod = element.aod
        aod_font = aod.font if aod is not None and aod.font_is_custom else None
        if not element.font_is_custom and aod_font is None:
            return []
        glyphs, aod_glyphs = _glyphs(element)
        runs = []
        if element.font_is_custom:
            widest = _widest_text(element)
            runs.append(TextRun(
                element.id, element.font, glyphs=frozenset(glyphs), samples=(widest,),
                sample_note=f"the widest rendering of this element is {widest!r}",
                span=element.span, if_unavailable=element.if_unavailable, curve=element.curve))
        if aod_font is not None:
            # Whatever the element's own font is: a system or `face:` font
            # draws awake, this baked one asleep, and it still needs the glyphs.
            runs.append(TextRun(element.id, aod_font, glyphs=frozenset(aod_glyphs),
                                span=element.span, aod_only=True))
        return runs

    def draw_preview(self, renderer: _Renderer, placed: PlacedText) -> None:
        element = placed.element
        text = _text_value(renderer, placed)
        if text is None:
            return
        color = renderer._aod_color(element, "color", element.color)
        if placed.font.is_vector:
            # A `face:` font draws upright, angled or radial, never through a
            # baked sheet; `font.available is False` is `if_unavailable: hide`
            # on this device, which draws nothing, as the watch does.
            if not placed.font.available:
                return

            def draw(anchor, fill, box=None):
                renderer._draw_vector_text(
                    text, anchor, element.align, element.vertical_align, placed.font.metric,
                    fill, placed.curve.style, placed.curve.angle_garmin,
                    placed.curve.radius_px, placed.curve.direction, box=box)
        else:
            font, metric = _text_font(renderer, placed)

            def draw(anchor, fill, box=None):
                renderer._draw_text(font, text, anchor, element.align, element.vertical_align,
                                    metric, fill, box=box)
        outline = element.outline
        renderer._draw_outlined(draw, placed.anchor_point, color,
                                renderer._color(outline.color) if outline is not None else None,
                                outline.width if outline is not None else 0, box=placed.box)

    def emit_draw(self, w: Writer, resolved, placed: PlacedText, guards: list[str],
                  plan, aod: AodStyle = NO_AOD) -> None:
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

    def describe(self, placed: PlacedText) -> str:
        return "text" if placed.element.value is not None else "fixed text"

    def layout_constants(self, prefix: str, placed: PlacedText) -> "layout_constants_mod.Constants":
        # For `curve: {style: radial}` this is the *centre of the circle*
        # (plan 11 §2.2's `at:` reinterpretation, `PlacedText.anchor_point`'s
        # own docstring), not a `drawText`-style anchor -- still `_X`/`_Y`,
        # since the codegen call site reads it that way regardless.
        note = f'widest rendering "{placed.widest}" is {placed.measured_width} px'
        if placed.width_is_estimated:
            note += " (estimated)"
        out: "layout_constants_mod.Constants" = [
            (f"{prefix}_X", placed.anchor_point[0], ""),
            (f"{prefix}_Y", placed.anchor_point[1], ""),
            (f"{prefix}_WIDTH", placed.measured_width, note),
        ]
        if placed.curve.style is not None:
            # Both angle conventions in the comment, the same `arc`
            # precedent `_arc_constants`'s own `_START` follows -- keeps the
            # conversion auditable without having to re-derive it.
            author_note = (
                f"{placed.curve.angle_degrees:g}deg clockwise from 12 o'clock"
                if placed.curve.style == "radial"
                else f"{placed.curve.angle_degrees:g}deg clockwise rotation from upright"
            )
            out.append((
                f"{prefix}_ANGLE", float(placed.curve.angle_garmin),
                f"{author_note}, in Garmin's convention",
            ))
            if placed.curve.style == "radial":
                out.append((f"{prefix}_RADIUS", placed.curve.radius_px, ""))
        return out


KIND = TextKind()
