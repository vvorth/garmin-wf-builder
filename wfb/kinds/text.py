"""`type: text` -- a bound or literal string, optionally curved onto a
`face:` (vector) font."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TYPE_CHECKING

from dataclasses import replace

from .. import catalog, conversion, formatting, vocab
from ..catalog import Type
from ..ir.model import Element, Expression, Outline, Text, TextSegment, aod_outline_choice
from ..layout import HIDDEN_BY_FONT, Placed, PlacedText, longer, resolved_curve, text_ink
from ..units import Axis, Box
from ..draw.program import (
    AodDimmed, AodPaint, AodRestyled, AodStr, Blank, Color, Comment, Concat, Const, DrawContext,
    Font, IfAod, IfAwake, IfNotNull, LetText, Local, LoadFont, Op, Paint, Reading, RingColor,
    SetColor, Shifted, Str, StrLit, Text as DrawText,
)
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc.common import AodStyle, aod_font_field, const_prefix, font_field
from ..ir import disc_perimeter_offsets
from . import ElementKind, TextRun, ring_font, ring_widths

if TYPE_CHECKING:
    from ..ir.builder import Builder
    from ..ir.model import Face
    from ..layout import Resolver


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


def _source(value: Expression) -> catalog.Source | None:
    return catalog.get(value.sources[0]) if value.sources else None


def _widest_text(element: Text) -> str:
    if element.literal is not None:
        return element.literal
    if element.value is None:
        return ""
    spec = element.format or "{}"
    widest = formatting.widest(spec, _source(element.value), element.value.value.type,
                               element.value.scale, digits=element.unit_digits,
                               unit_widest=_widest_label(element))
    for value, more_spec in element.segments()[1:]:
        widest += formatting.widest(more_spec, _source(value), value.value.type, value.scale)
    if element.absent == "placeholder" and element.placeholder:
        widest = longer(widest, element.placeholder)
    if element.absent == "fallback" and element.fallback is not None:
        # 'fallback:' is drawn through the exact same format spec as the
        # real value (see `wfb.kinds.text.TextKind.lower`), so its widest
        # rendering has to be considered too -- otherwise a font baked
        # from the *value*'s digit range alone can come up short for a
        # wider fallback (e.g. a longer literal string on a nullable
        # STRING source).
        widest = longer(widest, _fallback_widest(element.fallback, spec, _widest_label(element)))
    return widest


def _fallback_widest(fallback_expr: Expression, spec: str, unit_widest: str = "") -> str:
    """The widest string a `fallback:` expression could render, through the
    same format spec the bound value uses (see `wfb.kinds.text.TextKind.lower`).

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
    value_glyphs = formatting.glyphs(spec, source, element.value.value.type, element.value.scale,
                                     digits=element.unit_digits, unit_labels=element.unit_labels)
    glyphs = set(value_glyphs)
    aod = element.aod
    aod_spec = aod.format if aod is not None and aod.format is not None else spec
    aod_glyphs = (
        set(value_glyphs) if aod_spec == spec
        else formatting.glyphs(aod_spec, source, element.value.value.type, element.value.scale,
                               digits=element.unit_digits, unit_labels=element.unit_labels)
    )
    for value, more_spec in element.segments()[1:]:
        glyphs |= formatting.glyphs(more_spec, _source(value), value.value.type, value.scale)
    if element.placeholder:
        glyphs |= set(element.placeholder)
    if element.absent == "fallback" and element.fallback is not None:
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





def _aod_ring(element: Text, dim_set: bool) -> tuple[Outline | None, str]:
    """`aod_outline_choice` for this element's AOD frame; `(None, "awake")`
    when the element is not drawn in AOD at all."""
    if element.aod is None:
        return None, "awake"
    return aod_outline_choice(element.outline, element.aod, dim_set)





def baked_ring(element: Element, face: Face, width: int) -> str | None:
    """The ring font this element draws its ``width`` px ring with
    (`kinds.ring_font`), or `None` when it stamps."""
    found = ring_font(element, face, width)
    return found[0] if found is not None else None


def baked_ring_local(width: int) -> str:
    """The local a ``width`` px ring font is read into: one name per width,
    so an AOD ring of another width in the same method never redeclares
    it."""
    return "ringFont" if width == 1 else f"ringFont{width}"






def _apply_units(
    b: Builder, node: dict[str, Any], value: Expression | None,
) -> tuple[Expression, str, Expression, tuple[str, ...], int] | None:
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
            b.bag.error("units", f"{element_id}: 'units:' converts the reading in a "
                        "placeholder, and this text is fixed", span)
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
            notes=["'units:' converts a placeholder that is exactly one of: "
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


def _in_seconds(b: Builder, node: dict[str, Any], value: Expression) -> Expression:
    """A duration `format:` reads its value as seconds, so a bare source
    the catalogue states in minutes, hours or days is rewritten to seconds
    (`wfb.conversion.SECONDS_PER_UNIT`) -- the same expression rewrite
    `units:` makes, and for the same reason only a bare source: an
    arbitrary expression no longer states its unit, and is read as seconds
    as written."""
    spec = node.get("format")
    if spec is None or not formatting.is_duration(str(spec), value.value.type):
        return value
    raw = str(node["value"]).strip()
    source = catalog.CATALOG.get(raw)
    factor = conversion.SECONDS_PER_UNIT.get(source.unit or "") if source is not None else None
    if factor is None or factor == 1:
        return value
    scaled = b.compile_expression(f"{raw} * {factor}", b.doc.span(node, "value"), "value")
    return value if scaled is None else scaled


def _build_more(b: Builder, node: dict[str, Any], element: Text) -> tuple[TextSegment, ...]:
    """The readings after the first of a `text:` template with several
    placeholders (`more_values:`, `wfb.lower`), each compiled and its
    format checked like the first's.  `units:` and `absent: {value:}`
    speak of one reading, so either is an error beside several."""
    entries = node.get("more_values") or []
    if not entries:
        return ()
    if "units" in node:
        b.bag.error("format", f"{element.id}: 'units:' converts the reading of a text with "
                    f"one placeholder, and this text has {len(entries) + 1}",
                    b.doc.span(node, "units"),
                    notes=["give the converted reading a text element of its own"])
    if isinstance(node.get("absent"), dict):
        b.bag.error("format", f"{element.id}: 'absent: {{value:}}' substitutes the reading of "
                    f"a text with one placeholder, and this text has {len(entries) + 1}",
                    b.fallback_span(node),
                    notes=["write 'absent: hide' or a text to draw instead "
                           "('absent: \"--\"'); the text is absent when any reading is"])
    out = []
    for entry in entries:
        value = b.expression(entry, "value")
        if value is None:
            continue
        value = _in_seconds(b, entry, value)
        b.check_format(entry, value, str(entry["format"]))
        out.append(TextSegment(value, str(entry["format"])))
    return tuple(out)


def _check_unit_field(b: Builder, node: dict[str, Any], element: Text) -> None:
    """`{unit}` in `format:` (or its `aod:` twin) is the label of a
    `units:` conversion, so it needs one.  A `units:` that was written but
    failed is reported once, where it failed, not again here."""
    if "units" in node:
        return
    aod = node.get("aod")
    for where, spec, span in (
        ("text", element.format, b.doc.span(node, "format")),
        ("aod.text", aod.get("format") if isinstance(aod, dict) else None,
         b.doc.span(aod, "format") if isinstance(aod, dict) else None),
    ):
        if spec and formatting.has_unit_field(str(spec)):
            b.bag.error("format", f"{element.id}.{where}: '{{unit}}' is the label of a "
                        "'units:' conversion, and this element has no 'units:'",
                        span, notes=["add 'units: auto' to show the wearer's own units"])


class TextKind(ElementKind[Text, PlacedText]):
    name = "text"
    ringed = True

    def ring_draws(self, element: Text, face: Face) -> int:
        return (1 if baked_ring(element, face, 1) is not None
                else super().ring_draws(element, face))
    ir_class = Text
    placed_class = PlacedText

    def build(self, b: Builder, node: dict[str, Any], common: dict[str, Any], path: tuple[str | int, ...]) -> Element:
        value = b.expression(node, "value") if "value" in node else None
        units = None
        if "units" in node:
            units = _apply_units(b, node, value)
            if units is not None:
                value = units[0]
        elif value is not None:
            value = _in_seconds(b, node, value)
        align, vertical_align = b.alignment(node)
        element = Text(
            **common,
            value=value,
            literal=node.get("text"),
            format=node.get("format"),
            color=b.color_expression(node, "color"),
            align=align,
            vertical_align=vertical_align,
            **b.absence(node),
        )
        if units is not None:
            _, element.units, element.unit_label, element.unit_labels, element.unit_digits = units
        if value is not None:
            element.more = _build_more(b, node, element)
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
        if font_ok and "unsupported" in node and not element.in_subscreen:
            b.check_unsupported(node, element.id, font_is_vector, font_note)
        if "outline" in node:
            element.outline = b.build_outline(node, "outline", element.id, element=element)
        own_aod_format = element.aod_own is not None and "format" in element.aod_own
        aod_format_span = (b.doc.span(node.get("aod"), "format") or b.doc.span(node, "aod")
                           if own_aod_format else None)
        if value is not None:
            nullable = next((v for v, _ in element.segments() if v.nullable), value)
            b.check_absence(node, element, nullable, element.absent, element.placeholder,
                            element.fallback)
            b.check_format(node, value, element.format)
            if own_aod_format and element.aod_own is not None:
                # An `aod: {format: ...}` inherited from a group is checked
                # in `_resolve_aod` instead, once inheritance is resolved.
                b.check_format_spec(value, str(element.aod_own["format"]), aod_format_span)
        elif "value" not in node:
            # A fixed `text:` has no bound value for `format:`, or its
            # `aod:` twin, to format.  (A `value:` that failed to compile
            # already has its own error.)
            b.check_format_not_on_literal(node, element.id)
            refusal = b.aod_refusal("format", "text", None, literal_text=True)
            if own_aod_format and refusal is not None:
                code, what, notes = refusal
                b.bag.error(code, f"{element.id}.aod.text: {what}", aod_format_span,
                           notes=notes)
        b.check_other_absence(node, element, "color", element.color)
        b.check_reachable_substitute(node, element, "'color'",
                                     tuple(v for v, _ in element.segments()), (element.color,))
        return element

    def hidden_reason(self, placed: PlacedText) -> str | None:
        # `available` is only ever false for a `face:` font that failed
        # gates 1-3 here, which survives into a build only under
        # `unsupported: hide`.
        return None if placed.font.available else HIDDEN_BY_FONT

    def resolve(self, r: Resolver, element: Text, parent: Box, depth: int) -> Placed:
        font = r.text_font(element.font, element.font_is_custom, element.curve)
        widest = _widest_text(element)
        # A baked sheet measures exactly; anything else is an estimate --
        # still a conservative, non-zero one for an *unavailable* vector
        # font, whose metric locates no face and falls to Pillow's default.
        width = font.width(widest)
        line_height = font.line_height

        x, y = r.point(element.at, parent)
        curve = resolved_curve(element.curve)
        if element.curve is not None and curve.style == "radial" and element.curve.radius is not None:
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
            return ("format", "'aod: {text:}' restyles a placeholder, and this text is fixed", [])
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
                span=element.span, unsupported=element.unsupported, curve=element.curve))
        if aod_font is not None:
            # Whatever the element's own font is: a system or `face:` font
            # draws awake, this baked one asleep, and it still needs the glyphs.
            runs.append(TextRun(element.id, aod_font, glyphs=frozenset(aod_glyphs),
                                span=element.span, aod_only=True))
        return runs

    def lower(self, ctx: DrawContext, placed: PlacedText) -> list[Op]:
        """The text, after its `outline:` ring (or, with `ctx.ring`, only an
        outlined group's ring).  The string is a literal or the readings
        through their formats, with an `aod: {format: ...}` as a second
        string chosen per frame, and a `placeholder:`/`fallback:` built once
        into a local when the value's readings may be absent.  The font is a
        baked sheet (an early `return` if it failed to load, and a choice
        with an `aod: {font: ...}` override), a system `FONT_*` (the choice
        inline), or a `face:` font, whose draws all sit inside one null check
        (`docs/lore/codegen.md`, gate 4).  A ring is one `drawText` in the
        baked ring font where the build has one, else a stamp."""
        element = placed.element
        aod = ctx.aod
        prefix = const_prefix(placed.id)
        ops: list[Op] = []
        text: Str = self._text(ctx, element, ops)

        x, y = Const(f"{prefix}_X", placed.anchor_point[0]), Const(f"{prefix}_Y", placed.anchor_point[1])
        curve = placed.curve
        angle = (Const(f"{prefix}_ANGLE", float(curve.angle_garmin))
                 if curve.style is not None else None)
        radius = (Const(f"{prefix}_RADIUS", curve.radius_px)
                  if curve.style == "radial" else None)
        justify = tuple(placed.justify)

        def draw(font: Font, dx: int = 0, dy: int = 0) -> DrawText:
            interior = (dx, dy) == (0, 0) and font is main
            return DrawText(Shifted(x, dx), Shifted(y, dy), font, text, justify,
                        element.vertical_align, align=element.align, style=curve.style,
                        angle=angle, radius=radius, direction=curve.direction,
                        box=placed.inner_box if interior else None)

        main = self._font(ctx, placed, ops)

        def ring_ops(paint: Paint, width: int) -> list[Op]:
            """One ring: the baked ring font's single `drawText`, or a stamp."""
            baked = None if placed.font.is_vector else baked_ring(element, ctx.resolved.face, width)
            if baked is None:
                return [SetColor(paint), *(draw(main, dx, dy)
                                           for dx, dy in disc_perimeter_offsets(width))]
            local = baked_ring_local(width)
            ring_font = Font(local, baked=baked, metric=placed.font.metric)
            return [LoadFont(local, f"_{font_field(baked)}", on_null="none"),
                    IfNotNull(local, (SetColor(paint), draw(ring_font)))]

        body: list[Op] = []
        if ctx.ring is not None:
            body += ring_ops(RingColor(), ctx.ring.width)
        else:
            body += self._ring(element, aod, ring_ops)
            body += [SetColor(AodRestyled(element, "color")), draw(main)]
        if placed.font.is_vector:
            ops += [LoadFont("font", f"_{font_field(placed.font.reference)}", on_null="none"),
                    IfNotNull("font", tuple(body))]
        else:
            ops += body
        return ops

    @staticmethod
    def _text(ctx: DrawContext, element: Text, ops: list[Op]) -> Str:
        """The string drawn, appending the `placeholder:`/`fallback:` local
        it needs to ``ops``."""
        if element.literal is not None:
            return StrLit(element.literal)
        value = element.value
        assert value is not None  # a text without a literal binds `value:`
        unit = element.unit_label
        segments = element.segments()
        first = Reading(element.format or "{}", value, unit)
        text: Str = (first if len(segments) == 1 else
                     Concat((first, *(Reading(spec, v) for v, spec in segments[1:]))))
        if ctx.aod.on and element.aod is not None and element.aod.format is not None:
            # `format:` changes the formatting code, not an argument: both
            # strings are built up front and chosen per frame, inside any
            # placeholder or fallback substitution too.
            text = AodStr(Reading(element.aod.format, value, unit), text)
        if element.absent in ("placeholder", "fallback") and ctx.value_guards:
            # One string, not two draw calls: a placeholder is a different
            # value, and a fallback the same, through the same format.
            if element.absent == "placeholder":
                ops.append(Comment(vocab.absent(element)))
                initial: Str = StrLit(element.placeholder or "")
            else:
                assert element.fallback is not None  # absent: fallback sets it
                initial = Reading(element.format or "{}", element.fallback, unit)
                ops.append(Comment(vocab.absent(element)))
            ops += [LetText(initial, text, ctx.value_guards), Blank()]
            return Local("text")
        return text

    @staticmethod
    def _font(ctx: DrawContext, placed: PlacedText, ops: list[Op]) -> Font:
        """The font every draw names, appending its loading to ``ops``."""
        element = placed.element
        aod = ctx.aod
        metric = placed.font.metric
        if placed.font.is_vector:
            return Font("font", metric=metric, vector=True)
        override_code: str | None = None
        asleep: Font | None = None
        if aod.on and element.aod is not None and element.aod.font is not None:
            override = element.aod.font
            if not element.aod.font_is_custom:
                override_code = f"Graphics.{override}"
                asleep = Font(override_code,
                              metric=ctx.resolved.device.system_fonts.get(override))
            else:
                spec = ctx.resolved.face.fonts.get(override)
                # A `face:` override is a build error; naming the awake font
                # again loads nothing a second time.
                if (spec is not None and not spec.is_vector
                        and override != placed.font.reference):
                    override_code = f"_{aod_font_field(override)}"
                    asleep = Font(override_code, baked=override)
        if not placed.font.is_custom:
            awake_code = f"Graphics.{placed.font.reference}"
            code = aod.value(override_code, awake_code)
            return Font(code, metric=metric, asleep=replace(asleep, code=code) if asleep else None)
        field = f"_{font_field(placed.font.reference)}"
        if override_code is not None:
            final = "fontFinal"
            ops += [LoadFont("font", field, on_null="none"),
                    LoadFont(final, f"_aod ? {override_code} : font",
                             note="no font resource for this frame"), Blank()]
            assert asleep is not None
            return Font(final, baked=placed.font.reference, metric=metric,
                        asleep=replace(asleep, code=final))
        ops += [LoadFont("font", field), Blank()]
        return Font("font", baked=placed.font.reference, metric=metric)

    @staticmethod
    def _ring(element: Text, aod: AodStyle,
              ring_ops: Callable[[Paint, int], list[Op]]) -> list[Op]:
        """The `outline:` ring ahead of the interior, for the awake frame and
        the always-on one (`aod_outline_choice`): one ring, its colour a
        choice where the two frames' differ; a ring in only one frame under
        `if (_aod)`/`if (!_aod)`; or one ring in each branch when their
        widths differ."""
        awake = element.outline
        if not aod.on or element.aod is None:
            return [*ring_ops(Color(awake.color), awake.width), Blank()] if awake else []
        asleep, choice = _aod_ring(element, aod.dim is not None)
        if awake is None and asleep is None:
            return []
        if awake is None or asleep is None:
            only = asleep if awake is None else awake
            assert only is not None  # both absent returned above
            drawn = tuple(ring_ops(Color(only.color), only.width))
            return [IfAod(drawn) if awake is None else IfAwake(drawn), Blank()]
        if asleep.width != awake.width:
            # Only an override has a width of its own: a carried-over ring is
            # the awake one.
            return [IfAod(tuple(ring_ops(Color(asleep.color), asleep.width)),
                          tuple(ring_ops(Color(awake.color), awake.width))), Blank()]
        paint: Paint = (AodPaint(Color(asleep.color), Color(awake.color))
                        if choice == "override" else AodDimmed(element, awake.color))
        return [*ring_ops(paint, awake.width), Blank()]

    def describe(self, placed: PlacedText) -> str:
        return "text" if placed.element.value is not None else "fixed text"

    def layout_constants(self, prefix: str, placed: PlacedText) -> "layout_constants_mod.Constants":
        # For `curve: {style: radial}` this is the *centre of the circle*
        # (`at:` reinterpreted: `PlacedText.anchor_point`'s
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
