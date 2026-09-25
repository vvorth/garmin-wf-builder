"""`type: icon` -- one glyph drawn from a baked icon font, static or chosen
at runtime from a bound value (`icon_for:`)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import catalog, expr, icons, units
from ..ir import local_name
from ..ir.builder import ICON_SIZE_NOTE
from ..ir.model import Element, IconElement
from ..layout import Placed, PlacedIcon, alignment_shift
from ..preview import baked_glyph
from ..units import Box
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc.common import NO_AOD, AodStyle, const_prefix, font_field
from ..emit.monkeyc.shapes import emit_plain_text_call
from ..emit.writer import Writer
from . import ElementKind, IconFont, TextRun

if TYPE_CHECKING:
    from ..ir.builder import Builder
    from ..layout import Resolver
    from ..preview import Renderer


def _build_glyph_icon(b, node: dict, common: dict, placement: dict) -> Element:
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


class IconKind(ElementKind):
    name = "icon"
    ir_class = IconElement
    placed_class = PlacedIcon

    def build(self, b: Builder, node: dict, common: dict, path: tuple) -> Element:
        name = node.get("icon")
        has_icon_for = "icon_for" in node
        has_glyph = "glyph" in node
        chosen = [k for k in ("icon", "icon_for", "glyph") if k in node]
        if len(chosen) != 1:
            b.bag.error(
                "icon",
                "an icon element needs exactly one of 'icon', 'glyph' or 'icon_for'"
                + (f" -- got {', '.join(repr(k) for k in chosen)}" if chosen else ""),
                b.doc.span(node),
                notes=["'icon' names a glyph from the built-in catalogue (run "
                       "`wfb sources` for the list)",
                       "'glyph' is any codepoint in the icon font, written "
                       "'U+XXXX' -- for the ~10,000 glyphs the catalogue does not name",
                       "'icon_for' chooses one at runtime from a bound value -- see "
                       "wfb.catalog.WEATHER_CONDITION_SOURCES for what it accepts"],
            )

        size = b.baked_size_length(
            node, "size", code="icon", label="icon size", note=ICON_SIZE_NOTE,
        )

        align, vertical_align = b.alignment(node)
        # Shared by every branch below: `**placement` is the four keys an
        # `IconElement` needs regardless of which of 'icon'/'icon_for'/
        # 'glyph' chose it -- one `color_expression(node, "color")` call
        # instead of one per branch.
        placement = dict(
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
                    f"icon_for must be exactly one of: "
                    f"{', '.join(sorted(catalog.WEATHER_CONDITION_SOURCES))} "
                    f"-- not {value_for.text!r}",
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
        # `wfb.kinds.icon.IconKind.emit_draw`).
        dx, dy = alignment_shift(width, height, element.align, element.vertical_align)
        box = Box(cx + dx - width / 2, cy + dy - height / 2, width, height)
        return PlacedIcon(
            element, box.rounded(), (round(cx), round(cy)), depth,
            size=px, font_key=key, codepoint=measure_codepoint,
            anchor_point=(round(cx), round(cy)),
            justify=justify,
        )

    def text_runs(self, element: IconElement, face) -> list[TextRun]:
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

    def draw_preview(self, renderer: Renderer, placed: PlacedIcon) -> None:
        """One glyph from the baked icon font -- the same mechanism a
        custom-font text element uses to draw, not a hand-drawn shape.  See
        ``wfb.icons``: this is what makes preview and device agree on an icon's
        appearance without a second, hand-maintained drawing implementation."""
        font = renderer.resolved.fonts.get(placed.font_key)
        glyph = baked_glyph(font, placed.codepoint)
        if glyph is None:
            return  # the font failed to bake, or the glyph is missing from it
        s = renderer.scale
        color = renderer.aod_color(placed.element, "color", placed.element.color)
        renderer.paste_glyph(font.sheet, glyph, placed.box.x * s, placed.box.y * s, color)

    def emit_draw(self, w: Writer, resolved, placed: PlacedIcon, value_guards, plan,
                  aod: AodStyle = NO_AOD) -> None:
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
        does: `placed.justify` (`Resolver.justify`) picks the `TEXT_JUSTIFY_*`
        flags, and `glyph_y_expr` handles `bottom`'s missing platform flag by
        subtracting the *icon* font's own `dc.getFontHeight` -- the anchor
        itself (`Layout.<P>_CX/_CY`) never moves; center/center yields the same
        literal flags whether or not `align`/`vertical_align` are given.
        """
        element = placed.element
        prefix = const_prefix(placed.id)
        w.line(f"var font = _{font_field(placed.font_key)};")
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
        w.line(f"dc.setColor({aod.color(element, 'color')}, Graphics.COLOR_TRANSPARENT);")
        emit_plain_text_call(w, f"Layout.{prefix}_CX", f"Layout.{prefix}_CY", "font", glyph_expr,
                             justify, element.vertical_align)

    def describe(self, placed: PlacedIcon) -> str:
        element = placed.element
        if element.is_dynamic:
            return f"an icon chosen at runtime from {element.value_for.text!r}"
        return f"the {element.icon!r} icon"

    def layout_constants(self, prefix: str, placed: PlacedIcon) -> "layout_constants_mod.Constants":
        # A glyph kind's anchor never itself moves for `align`/`vertical_
        # align` -- only the device-side justify flags and `emit_draw`'s
        # `bottom` subtraction do -- so the constant names and values stay
        # `_CX`/`_CY` even when aligned; the comment says so only then.
        default = placed.element.align == "center" and placed.element.vertical_align == "center"
        note = "" if default else "the anchor drawText justifies the glyph from, not its centre"
        return [
            (f"{prefix}_CX", placed.center[0], note),
            (f"{prefix}_CY", placed.center[1], note),
        ]


KIND = IconKind()
