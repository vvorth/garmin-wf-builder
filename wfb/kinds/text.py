"""`type: text` -- a bound or literal string, optionally curved onto a
`face:` (vector) font."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from dataclasses import replace

from .. import catalog, conversion, expr, formatting
from ..catalog import Type
from ..devices import FontMetric
from ..fonts import BakedFont
from ..ir.model import Element, Expression, Text, aod_outline_choice
from ..layout import Placed, PlacedText, longer, resolved_curve, text_ink
from ..units import Axis, Box
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc import shapes
from ..emit.monkeyc.common import NO_AOD, AodStyle, aod_font_field, const_prefix, font_field, mc_color
from ..emit.writer import Writer
from . import ElementKind, TextRun

if TYPE_CHECKING:
    from ..ir.builder import Builder
    from ..ir.model import Face
    from ..emit.monkeyc.readplan import ReadPlan
    from ..layout import ResolvedFace, Resolver
    from ..preview import Renderer


def _reject_text_antialias(b: Builder, node: dict[str, Any], element: Text) -> None:
    """`antialias:` on a `text` element -- a per-element key on a shared resource.

    A text element draws through a font declared in `fonts:`, and that
    font is one bitmap resource shared by every element that references
    it (`font: font.clock` is a name, not a private copy) -- so
    anti-aliasing cannot vary per element the way it can on a shape's own
    outline or an icon's own, per-glyph font.  The schema still parses
    `antialias:` here rather than rejecting it as an unknown key, purely
    so this can name the actual font instead of jsonschema's generic
    "unknown key" message: by the time `resolve_font` above has run,
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
                               element.value.scale, digits=element.unit_digits,
                               unit_widest=_widest_label(element))
    if element.when_absent == "placeholder" and element.placeholder:
        widest = longer(widest, element.placeholder)
    if element.when_absent == "fallback" and element.fallback is not None:
        # 'fallback:' is drawn through the exact same format spec as the
        # real value (see `wfb.kinds.text.TextKind.emit_draw`), so its widest
        # rendering has to be considered too -- otherwise a font baked
        # from the *value*'s digit range alone can come up short for a
        # wider fallback (e.g. a longer literal string on a nullable
        # STRING source).
        widest = longer(widest, _fallback_widest(element.fallback, spec, _widest_label(element)))
    return widest


def _fallback_widest(fallback_expr: Expression, spec: str, unit_widest: str = "") -> str:
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
    return formatting.widest(spec, source, fallback_expr.value.type, fallback_expr.scale,
                             unit_widest=unit_widest)



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
    units = {"digits": element.unit_digits, "unit_labels": element.unit_labels}
    value_glyphs = formatting.glyphs(spec, source, element.value.value.type, element.value.scale,
                                     **units)
    glyphs = set(value_glyphs)
    aod = element.aod
    aod_spec = aod.format if aod is not None and aod.format is not None else spec
    aod_glyphs = (
        set(value_glyphs) if aod_spec == spec
        else formatting.glyphs(aod_spec, source, element.value.value.type, element.value.scale,
                               **units)
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

def _widest_label(element: Text) -> str:
    """The widest label `{unit}` can show, or ``""`` without `units:`."""
    return max(element.unit_labels, key=len, default="")


def _text_font(renderer: Renderer, placed: PlacedText) -> tuple[BakedFont | None, FontMetric | None]:
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
    aod_font = renderer.aod_field(element, "font", None)
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


def _text_value(renderer: Renderer, placed: PlacedText) -> str | None:
    element = placed.element
    if element.literal is not None:
        return element.literal
    if element.value is None:
        return None
    spec = renderer.aod_field(element, "format", element.format) or "{}"
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
    unit_text = (str(expr.evaluate(element.unit_label.ast, renderer.values))
                 if element.unit_label is not None and element.unit_label.ast is not None
                 else None)
    return formatting.render(spec, value, value_type, unit_text=unit_text)


def _aod_ring(element: Text, dim_set: bool):
    """`aod_outline_choice` for this element's AOD frame; `(None, "awake")`
    when the element is not drawn in AOD at all."""
    if element.aod is None:
        return None, "awake"
    return aod_outline_choice(element.outline, element.aod, dim_set)


def _emit_ring(w: Writer, element: Text, aod: AodStyle, x_expr: str, y_expr: str,
               draw) -> None:
    """The `outline:` stamp loop ahead of the interior pass
    (`shapes.emit_outline_loop`), for the awake ring and the AOD frame's own
    (`aod_outline_choice`): one loop when both frames have a ring -- the
    offsets table and the colour each an `_aod ? ... : ...` ternary only
    where they differ -- or one loop under `if (_aod)`/`if (!_aod)` when
    only one frame has a ring.  With no AOD code in this build, or this
    element hidden in AOD, only the awake ring exists.
    """
    awake = element.outline
    if not aod.on or element.aod is None:
        if awake is not None:
            shapes.emit_outline_loop(w, f"Layout.OUTLINE_OFFSETS_{awake.width}",
                                     mc_color(awake.color), x_expr, y_expr, draw)
        return
    asleep, choice = _aod_ring(element, aod.dim is not None)
    if awake is None and asleep is None:
        return
    if awake is None or asleep is None:
        ring = asleep if awake is None else awake
        with w.block("if (_aod)" if awake is None else "if (!_aod)"):
            shapes.emit_outline_loop(w, f"Layout.OUTLINE_OFFSETS_{ring.width}",
                                     mc_color(ring.color), x_expr, y_expr, draw,
                                     blank_after=False)
        w.blank()
        return
    offsets = aod.value(
        f"Layout.OUTLINE_OFFSETS_{asleep.width}" if asleep.width != awake.width else None,
        f"Layout.OUTLINE_OFFSETS_{awake.width}")
    color = (aod.value(mc_color(asleep.color), mc_color(awake.color)) if choice == "override"
             else aod.dimmed(element, awake.color))
    shapes.emit_outline_loop(w, offsets, color, x_expr, y_expr, draw)


def _emit_text_draw(w: Writer, resolved, placed: PlacedText, value_code: str,
                    aod: AodStyle = NO_AOD) -> None:
    element = placed.element
    prefix = const_prefix(placed.id)
    justify = " | ".join(f"Graphics.{flag}" for flag in placed.justify)
    color_code = aod.color(element, "color")
    if placed.font.is_vector:
        _emit_vector_text_draw(w, placed, prefix, justify, value_code, color_code, aod)
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
                override_expr = f"_{aod_font_field(element.aod.font)}"
    if placed.font.is_custom:
        w.line(f"var font = _{font_field(placed.font.reference)};")
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
    _emit_ring(
        w, element, aod, f"Layout.{prefix}_X", f"Layout.{prefix}_Y",
        lambda x, y: shapes.emit_plain_text_call(
            w, x, y, font_expr, value_code, justify, element.vertical_align),
    )
    w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
    shapes.emit_plain_text_call(
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
        direction = shapes.RADIAL_DIRECTION[placed.curve.direction or "clockwise"]
        radius = shapes.radial_radius_expr(f"Layout.{prefix}_RADIUS", element.vertical_align,
                                           placed.curve.direction, "font")
        w.call("dc.drawRadialText", [
            f"{x_expr}, {y_expr}, font, {value_code}",
            f"{justify}, Layout.{prefix}_ANGLE, {radius}",
            f"Graphics.{direction}",
        ])
    else:
        shapes.emit_plain_text_call(w, x_expr, y_expr, "font", value_code, justify,
                                    element.vertical_align)


def _emit_vector_text_draw(
    w: Writer, placed: PlacedText, prefix: str, justify: str, value_code: str, color_code: str,
    aod: AodStyle,
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
    field = f"_{font_field(placed.font.reference)}"
    w.line(f"var font = {field};")
    with w.block("if (font != null)"):
        _emit_ring(
            w, element, aod, f"Layout.{prefix}_X", f"Layout.{prefix}_Y",
            lambda x, y: _emit_vector_draw_call(w, placed, prefix, justify, value_code, x, y),
        )
        w.line(f"dc.setColor({color_code}, Graphics.COLOR_TRANSPARENT);")
        _emit_vector_draw_call(
            w, placed, prefix, justify, value_code, f"Layout.{prefix}_X", f"Layout.{prefix}_Y")


def _apply_units(b: Builder, node: dict[str, Any], value: Expression | None):
    """`units:` on a `text` element (ADR 0005 §4): the bound value rewritten
    to display in the wearer's units (`wfb.conversion`), as ``(value,
    system, label, labels, digits)``, or `None` when it was reported.

    Only a `value:` that is exactly one source with a quantity converts: a
    conversion needs the unit the value is *in*, which an arbitrary
    expression over the source no longer states."""
    system = str(node["units"])
    element_id = node.get("id", "?")
    span = b.doc.span(node, "units")
    if value is None:
        if "value" not in node:
            b.bag.error("units", f"{element_id}: 'units:' converts a bound 'value:', "
                        "not a fixed 'text:'", span)
        return None
    raw = str(node["value"]).strip()
    source = catalog.CATALOG.get(raw)
    found = conversion.conversion_for(source)
    if found is None:
        convertible = sorted(path for path, s in catalog.CATALOG.items()
                             if conversion.conversion_for(s) is not None)
        what = (f"{raw!r} is in {source.unit}, which 'units:' does not convert"
                if source is not None and source.unit else
                f"{raw!r} is not a single source with a unit 'units:' converts")
        b.bag.error(
            "units", f"{element_id}: {what}", b.doc.span(node, "value"),
            notes=["'units:' converts a 'value:' that is exactly one of: "
                   + ", ".join(convertible),
                   "write the bare source; the conversion replaces any "
                   "hand-written scaling such as 'activity.distance / 100000.0'"])
        return None
    value_span = b.doc.span(node, "value")
    converted = b.compile_expression(conversion.converted_text(raw, found, system),
                                     value_span, "value")
    label = b.compile_expression(conversion.label_text(found, system), span, "units")
    if converted is None or label is None:
        return None
    return converted, system, label, conversion.labels(found, system), found.digits


def _check_unit_field(b: Builder, node: dict[str, Any], element: Text) -> None:
    """`{unit}` in `format:` (or its `aod:` twin) is the label of a
    `units:` conversion, so it needs one.  A `units:` that was written but
    failed is reported once, where it failed, not again here."""
    if "units" in node:
        return
    aod = node.get("aod")
    for where, spec, span in (
        ("format", element.format, b.doc.span(node, "format")),
        ("aod.format", aod.get("format") if isinstance(aod, dict) else None,
         b.doc.span(aod, "format") if isinstance(aod, dict) else None),
    ):
        if spec and formatting.has_unit_field(str(spec)):
            b.bag.error("format", f"{element.id}.{where}: '{{unit}}' is the label of a "
                        "'units:' conversion, and this element has no 'units:'",
                        span, notes=["add 'units: auto' to show the wearer's own units"])


class TextKind(ElementKind[Text, PlacedText]):
    name = "text"
    ir_class = Text
    placed_class = PlacedText

    def build(self, b: Builder, node: dict[str, Any], common: dict[str, Any], path: tuple[str | int, ...]) -> Element:
        value = b.expression(node, "value") if "value" in node else None
        units = None
        if "units" in node:
            units = _apply_units(b, node, value)
            if units is not None:
                value = units[0]
        align, vertical_align = b.alignment(node)
        element = Text(
            **common,
            value=value,
            literal=node.get("text"),
            format=node.get("format"),
            color=b.color_expression(node, "color"),
            align=align,
            vertical_align=vertical_align,
            when_absent=node.get("when_absent"),
            placeholder=node.get("placeholder"),
            fallback=b.expression(node, "fallback") if "fallback" in node else None,
            if_unavailable=node.get("if_unavailable"),
        )
        if units is not None:
            _, element.units, element.unit_label, element.unit_labels, element.unit_digits = units
        _check_unit_field(b, node, element)
        font_ok = b.resolve_font(node, element)
        if "antialias" in node:
            _reject_text_antialias(b, node, element)
        font_is_vector = b.is_vector_font(element.font, element.font_is_custom)
        font_note = b.font_kind_note(element.font, element.font_is_custom)
        if "curve" in node:
            element.curve = b.build_curve(
                node, element.id, vertical_align=element.vertical_align, font_ok=font_ok,
                font_is_vector=font_is_vector, font_note=font_note)
        if font_ok and "if_unavailable" in node:
            b.check_if_unavailable(node, element.id, font_is_vector, font_note)
        if "outline" in node:
            element.outline = b.build_outline(node, "outline", element.id, element=element)
        own_aod_format = element.aod_own is not None and "format" in element.aod_own
        aod_format_span = (b.doc.span(node.get("aod"), "format") or b.doc.span(node, "aod")
                           if own_aod_format else None)
        if value is not None:
            b.check_absence(node, element, value, element.when_absent, element.placeholder,
                            element.fallback)
            b.check_format(node, value, element.format)
            if own_aod_format:
                # An `aod: {format: ...}` inherited from a group is checked
                # in `_resolve_aod` instead, once inheritance is resolved.
                b.check_format_spec(value, str(element.aod_own["format"]), aod_format_span)
        else:
            # A fixed `text:` has no bound value for `format:`, or its
            # `aod:` twin, to format.
            b.check_format_not_on_literal(node, element.id)
            refusal = b.aod_refusal("format", "text", None, literal_text=True)
            if own_aod_format and refusal is not None:
                code, what, notes = refusal
                b.bag.error(code, f"{element.id}.aod.format: {what}", aod_format_span,
                           notes=notes)
        b.check_other_absence(node, element, "color", element.color)
        b.check_reachable_substitute(node, element, "'color'",
                                     (element.value,), (element.color,))
        return element

    def resolve(self, r: Resolver, element: Text, parent: Box, depth: int) -> Placed:
        font = r.text_font(element.font, element.font_is_custom, element.id, element.curve)
        widest = _widest_text(element)
        # A baked sheet measures exactly; anything else is an estimate --
        # still a conservative, non-zero one for an *unavailable* vector
        # font, whose metric locates no face and falls to Pillow's default.
        width = font.width(widest)
        line_height = font.line_height

        x, y = r.point(element.at, parent)
        curve = resolved_curve(element.curve)
        if curve.style == "radial" and element.curve.radius is not None:
            curve = replace(curve, radius_px=round(r.extent(
                element.curve.radius, parent, Axis.MINOR, 0,
                min_1px=element.resolved_min_1px, what="curve.radius")))
        # The box holds whichever ring is wider, awake or AOD.
        aod_ring = element.aod.outline if element.aod is not None else None
        ring_px = float(max(ring.width if ring is not None else 0
                            for ring in (element.outline, aod_ring)))
        box = text_ink(
            x, y, width, line_height, element.align, element.vertical_align,
            curve_style=curve.style, angle_garmin=curve.angle_garmin,
            radius_px=curve.radius_px, direction=curve.direction, metric=font.metric,
            pad=ring_px, fonts_root=r.device.fonts_root).box()

        return PlacedText(
            element, box.rounded(), (round(x), round(y)), depth,
            anchor_point=(round(x), round(y)),
            justify=r.justify(element),
            font=font.resolved(),
            widest=widest,
            measured_width=round(width),
            width_is_estimated=font.baked is None,
            curve=curve,
            line_height=line_height,
        )

    def aod_refusal(self, key: str, shape: str | None,
                    literal_text: bool) -> tuple[str, str, list[str]] | None:
        if key == "format" and literal_text:
            return ("format", "'aod: {format: ...}' applies only to 'value:', not a fixed 'text:'", [])
        return None

    def text_runs(self, element: Text, face: Face) -> list[TextRun]:
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

    def draw_preview(self, renderer: Renderer, placed: PlacedText) -> None:
        element = placed.element
        text = _text_value(renderer, placed)
        if text is None:
            return
        color = renderer.aod_color(element, "color", element.color)
        if placed.font.is_vector:
            # A `face:` font draws upright, angled or radial, never through a
            # baked sheet; `font.available is False` is `if_unavailable: hide`
            # on this device, which draws nothing, as the watch does.
            if not placed.font.available:
                return

            def draw(anchor, fill, box=None):
                renderer.draw_vector_text(
                    text, anchor, element.align, element.vertical_align, placed.font.metric,
                    fill, placed.curve.style, placed.curve.angle_garmin,
                    placed.curve.radius_px, placed.curve.direction, box=box)
        else:
            font, metric = _text_font(renderer, placed)

            def draw(anchor, fill, box=None):
                renderer.draw_text(font, text, anchor, element.align, element.vertical_align,
                                   metric, fill, box=box)
        outline, ring_color = element.outline, None
        if renderer.options.aod:
            outline, choice = _aod_ring(element, renderer.resolved.face.aod_dim is not None)
            if outline is not None:
                ring_color = (renderer.color(outline.color) if choice == "override"
                              else renderer.aod_dimmed(element, outline.color))
        elif outline is not None:
            ring_color = renderer.color(outline.color)
        renderer.draw_outlined(draw, placed.anchor_point, color, ring_color,
                               outline.width if outline is not None else 0, box=placed.box)

    def emit_draw(self, w: Writer, resolved: ResolvedFace, placed: PlacedText,
                  value_guards: list[str] | None, plan: ReadPlan,
                  aod: AodStyle = NO_AOD) -> None:
        element = placed.element
        if element.literal is not None:
            _emit_text_draw(w, resolved, placed, f'"{element.literal}"', aod)
            return

        value = element.value
        assert value is not None  # a text without a literal binds `value:`
        unit_code = element.unit_label.code if element.unit_label is not None else None
        value_code = formatting.emit(
            element.format or "{}",
            value.code,
            value.value.type,
            unit_code=unit_code,
        )
        if aod.on and element.aod is not None and element.aod.format is not None:
            # `format:` changes the formatting code, not just an argument -- the
            # same "AOD redraws once a minute anyway, so dropping seconds is
            # free" reasoning plan 14 §2.3 states -- so both formatted strings
            # are built once, up front, and the ternary between them stands in
            # for `value_code` everywhere below, including inside a
            # placeholder/fallback substitution.
            aod_value_code = formatting.emit(
                element.aod.format, value.code, value.value.type,
                unit_code=unit_code)
            value_code = aod.value(aod_value_code, value_code)
        if element.when_absent in ("placeholder", "fallback") and value_guards:
            # Build the string once rather than duplicating the draw call in both
            # branches: a placeholder is a different *value*, not a different
            # draw; a fallback is the same, except its substitute is itself a
            # compiled expression rather than a literal string, run through the
            # same format spec the real value uses.
            if element.when_absent == "placeholder":
                w.comment("when_absent: placeholder")
                initial = f'"{element.placeholder}"'
            else:
                assert element.fallback is not None  # when_absent: fallback sets it
                initial = formatting.emit(
                    element.format or "{}",
                    element.fallback.code,
                    element.fallback.value.type,
                    unit_code=unit_code,
                )
                w.comment("when_absent: fallback")
            available = " && ".join(f"{name} != null" for name in value_guards)
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
            # precedent `arc_constants`'s own `_START` follows -- keeps the
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
