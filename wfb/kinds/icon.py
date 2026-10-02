"""`type: icon` -- one glyph drawn from a baked icon font, static or chosen
at runtime from a bound value (`icon_for:`)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from .. import catalog, expr, icons, units
from ..ir import disc_perimeter_offsets
from ..ir.builder import ICON_SIZE_NOTE
from ..ir.model import Element, IconElement
from ..layout import Placed, PlacedIcon, alignment_shift
from ..units import Box
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc.common import const_prefix, font_field
from ..draw.program import (
    AodDimmed, AodRestyled, Blank, Comment, Const, DrawContext, Font, Glyph, IconChoice,
    IfNotNull, LoadFont, Op, Paint, RingColor, SetColor, Shifted, Str, StrLit,
)
from . import ElementKind, IconFont, TextRun
from .text import baked_ring, baked_ring_local

if TYPE_CHECKING:
    from ..ir.builder import Builder
    from ..ir.model import Face
    from ..layout import Resolver


def _build_glyph_icon(b: Builder, node: dict[str, Any], common: dict[str, Any], placement: dict[str, Any]) -> Element:
    """`glyph: "U+F0BC"` -- a codepoint the catalogue does not name.

    The only way to reach a glyph the catalogue does not name, and spelled
    so that it survives a code review: `U+F0BC` is greppable and visible,
    where the character itself renders as a blank box (or nothing) in
    most editors and diffs.  `icon:` does not accept a raw pasted
    character; this is the one place a codepoint outside the catalogue
    belongs.  Everything downstream -- baking, sizing, the per-codepoint
    font key -- is identical once it is a character, because this is
    exactly what a catalogue name resolves to.
    """
    raw = str(node.get("glyph"))
    span = b.doc.span(node, "glyph")
    character = b.resolve_icon_glyph(raw, span)
    if character is None:
        character = icons.FALLBACK_CODEPOINT
    return IconElement(**common, icon=raw.upper(), codepoint=character, **placement)


class IconKind(ElementKind[IconElement, PlacedIcon]):
    name = "icon"
    ir_class = IconElement
    placed_class = PlacedIcon
    ringed = True

    def ring_draws(self, element: IconElement, face: Face) -> int:
        return (1 if baked_ring(element, face, 1) is not None
                else super().ring_draws(element, face))

    def build(self, b: Builder, node: dict[str, Any], common: dict[str, Any], path: tuple[str | int, ...]) -> Element:
        name = node.get("icon")
        has_icon_for = "icon_for" in node
        has_glyph = "glyph" in node
        chosen = [k for k in ("icon", "icon_for", "glyph") if k in node]
        if len(chosen) != 1:
            b.bag.error(
                "icon",
                "an icon element needs one 'icon:'",
                b.doc.span(node),
                notes=["'icon:' names a glyph from the built-in catalogue (run "
                       "`wfb sources` for the list)",
                       "or is any codepoint in the icon font, written 'U+XXXX' -- for "
                       "the ~10,000 glyphs the catalogue does not name",
                       "or is {for: <expression>}, choosing one at runtime from a "
                       "bound value -- see wfb.catalog.WEATHER_CONDITION_SOURCES for "
                       "what it accepts"],
            )

        size = b.baked_size_length(
            node, "size", code="icon", label="icon size", note=ICON_SIZE_NOTE,
        )

        align, vertical_align = b.alignment(node)
        # Shared by every branch below: `**placement` is the four keys an
        # `IconElement` needs regardless of which of 'icon'/'icon_for'/
        # 'glyph' chose it -- one `color_expression(node, "color")` call
        # instead of one per branch.
        placement: dict[str, Any] = dict(
            size=size, color=b.color_expression(node, "color"),
            align=align, vertical_align=vertical_align,
        )

        if has_icon_for:
            value_for = b.expression(node, "icon_for")
            if value_for is not None and (
                not isinstance(value_for.ast, expr.Ref)
                or len(value_for.sources) != 1
                or value_for.sources[0] not in catalog.WEATHER_CONDITION_SOURCES
            ):
                b.bag.error(
                    "icon",
                    f"icon: {{for:}} must be exactly one of: "
                    f"{', '.join(sorted(catalog.WEATHER_CONDITION_SOURCES))} "
                    f"-- not {value_for.shown!r}",
                    b.doc.span(node, "icon_for"),
                    notes=["arithmetic or a conditional would break the "
                           "condition-to-glyph lookup, which needs the raw "
                           "Weather.CONDITION_* value"],
                )
                value_for = None
            return IconElement(
                **common, icon=None, codepoint=icons.FALLBACK_CODEPOINT,
                value_for=value_for, **placement,
            )

        if has_glyph:
            return _build_glyph_icon(b, node, common, placement)

        assert name is not None  # the schema requires one of icon/glyph/icon_for
        codepoint = b.resolve_icon_name(name, b.doc.span(node, "icon"))
        if codepoint is None:
            codepoint = icons.FALLBACK_CODEPOINT

        return IconElement(**common, icon=name, codepoint=codepoint, **placement)

    def resolve(self, r: Resolver, element: IconElement, parent: Box, depth: int) -> Placed:
        cx, cy = r.point(element.at, parent)
        # Independent of `parent`, deliberately: an icon's font is baked once,
        # before any box in the tree is resolved, so its size cannot depend on
        # one (ADR-equivalent reasoning in wfb.units.pixel_size).
        px = units.pixel_size(element.size, r.device.minor_radius)
        if element.is_dynamic:
            # The real glyph is chosen on-device at runtime (WfbWeather.mc);
            # measure and preview against the same representative glyph
            # `bake_size` used, which is guaranteed to be in this font.
            glyph_key = icons.DYNAMIC_WEATHER_TAG
            measure_codepoint = icons.WEATHER_BAKE_REFERENCE_GLYPH
        else:
            glyph_key = measure_codepoint = element.codepoint
        key = icons.font_key(element.size, glyph_key, element.resolved_antialias)
        font = r.fonts.get(key)
        if font is not None:
            width, height = font.measure(measure_codepoint)
        else:
            width = height = px  # the font failed to bake; keep a plausible box
        justify = r.justify(element)
        # The lint box only -- like `wfb.kinds.text.TextKind.resolve`, the runtime `drawText`
        # anchor stays `(cx, cy)` unshifted: an icon's alignment is a
        # device-side justify, not a build-time box move (see
        # `wfb.kinds.icon.IconKind.lower`).
        dx, dy = alignment_shift(width, height, element.align, element.vertical_align)
        box = Box(cx + dx - width / 2, cy + dy - height / 2, width, height)
        return PlacedIcon(
            element, box.rounded(), (round(cx), round(cy)), depth,
            size=px, font_key=key, codepoint=measure_codepoint,
            anchor_point=(round(cx), round(cy)),
            justify=justify,
        )

    def text_runs(self, element: IconElement, face: Face) -> list[TextRun]:
        if element.is_dynamic:
            # The glyph is chosen on-device (`WfbWeather.chooseIcon`, then
            # `IconGlyphs.glyph`), so the font holds every one it could be.
            glyph_key = icons.DYNAMIC_WEATHER_TAG
            glyphs = icons.WEATHER_GLYPH_SET
            reference = icons.WEATHER_BAKE_REFERENCE_GLYPH
            table = {
                name: icons.CATALOG[name].codepoint
                for name in set(icons.GARMIN_WEATHER_CONDITION_ICON.values())
            }
        else:
            glyph_key = glyphs = reference = element.codepoint
            table = None
        key = icons.font_key(element.size, glyph_key, element.resolved_antialias)
        return [TextRun(
            element.id, key, span=element.span,
            icon=IconFont(element.size, glyphs, reference, element.resolved_antialias),
            glyph_table=table)]

    def lower(self, ctx: DrawContext, placed: PlacedIcon) -> list[Op]:
        """A `drawText` of the icon's glyph in its baked icon font -- see
        `wfb.icons`: an icon is a one-character string drawn with a bitmap
        font, the same mechanism any other bound text uses, not a hand-drawn
        shape.

        A *dynamic* icon (`icon: {for: ...}`) draws the same way, except the
        glyph is resolved in two steps at runtime instead of being a literal
        baked in at build time: `WfbWeather.chooseIcon` picks a catalogue
        *name* from the bound value, and `IconGlyphs.glyph` (generated per
        project, directly from `wfb.icon_catalog.CATALOG`) turns that name
        into the character -- the same table any static icon's build-time
        lookup uses, not a second, weather-only one. The font has every
        glyph that call could return, baked ahead of time
        (`wfb.emit.resources.icon_font_specs`).

        `align`/`vertical_align` place the glyph the way a `text` element's
        are placed: `placed.justify` (`Resolver.justify`) picks the
        `TEXT_JUSTIFY_*` flags, and `bottom`, which has no flag, subtracts the
        icon font's own `dc.getFontHeight` (`glyph_y_expr`). The anchor
        (`Layout.<P>_CX/_CY`) never moves.

        `outline:` draws the glyph once more ahead of it: one `drawText` in
        its baked ring font (the glyph dilated, `wfb.fonts.bmfont.dilate`)
        where the build has one, else a stamp. An opening inside the icon
        wider than 2px keeps a ring of its own. With `ctx.ring`, only an
        outlined group's ring is drawn."""
        element = placed.element
        prefix = const_prefix(placed.id)
        font = Font("font", baked=placed.font_key)
        ops: list[Op] = [
            LoadFont("font", f"_{font_field(placed.font_key)}",
                     note="the icon font resource failed to load"),
            Blank(),
        ]
        glyph: Str
        if element.value_for is not None:
            ops.append(Comment(f"{element.value_for.text!r} -> a name (WfbWeather) "
                               "-> a glyph (IconGlyphs)"))
            glyph = IconChoice(element.value_for)
        else:
            ops.append(Comment(f"{element.icon!r}"))
            glyph = StrLit(element.codepoint)
        x, y = Const(f"{prefix}_CX", placed.center[0]), Const(f"{prefix}_CY", placed.center[1])

        def draw(face: Font, dx: int = 0, dy: int = 0) -> Glyph:
            return Glyph(Shifted(x, dx), Shifted(y, dy), face, glyph, tuple(placed.justify),
                         element.vertical_align, placed.inner_box, placed.center)

        def ring_ops(paint: Paint, width: int) -> list[Op]:
            """One ring: the baked ring font's single `drawText`, or a stamp."""
            baked = baked_ring(element, ctx.resolved.face, width)
            if baked is None:
                return [SetColor(paint), *(draw(font, dx, dy)
                                           for dx, dy in disc_perimeter_offsets(width))]
            local = baked_ring_local(width)
            return [LoadFont(local, f"_{font_field(baked)}", on_null="none"),
                    IfNotNull(local, (SetColor(paint), draw(Font(local, baked=baked))))]

        if ctx.ring is not None:
            return ops + ring_ops(RingColor(), ctx.ring.width)
        if element.outline is not None:
            ops += [*ring_ops(AodDimmed(element, element.outline.color), element.outline.width),
                    Blank()]
        return ops + [SetColor(AodRestyled(element, "color")), draw(font)]

    def describe(self, placed: PlacedIcon) -> str:
        element = placed.element
        if element.value_for is not None:
            return f"an icon chosen at runtime from {element.value_for.text!r}"
        return f"the {element.icon!r} icon"

    def layout_constants(self, prefix: str, placed: PlacedIcon) -> "layout_constants_mod.Constants":
        # A glyph kind's anchor never itself moves for `align`/`vertical_
        # align` -- only the device-side justify flags and `lower`'s
        # `bottom` subtraction do -- so the constant names and values stay
        # `_CX`/`_CY` even when aligned; the comment says so only then.
        default = placed.element.align == "center" and placed.element.vertical_align == "center"
        note = "" if default else "the anchor drawText justifies the glyph from, not its centre"
        return [
            (f"{prefix}_CX", placed.center[0], note),
            (f"{prefix}_CY", placed.center[1], note),
        ]


KIND = IconKind()
