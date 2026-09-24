"""`type: icon` -- one glyph drawn from a baked icon font, static or chosen
at runtime from a bound value (`icon_for:`)."""

from __future__ import annotations

from .. import icons
from ..ir.model import IconElement
from ..layout import PlacedIcon, Resolver
from ..preview import _Renderer
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc import shapes
from . import ElementKind


def describe(placed: PlacedIcon) -> str:
    element = placed.element
    if element.is_dynamic:
        return f"an icon chosen at runtime from {element.value_for.text!r}"
    return f"the {element.icon!r} icon"


def loaded_fonts(placed: PlacedIcon) -> list[str]:
    return [placed.font_key]


def icon_font_need(element: IconElement, face):
    if element.is_dynamic:
        glyph_key = icons.DYNAMIC_WEATHER_TAG
        glyphs = icons.WEATHER_GLYPH_SET
        reference = icons.WEATHER_BAKE_REFERENCE_GLYPH
    else:
        glyph_key = glyphs = reference = element.codepoint
    key = icons.font_key(element.size, glyph_key, element.resolved_antialias)
    return key, (element.size, glyphs, reference, element.resolved_antialias)


def needs_icon_glyphs(element: IconElement, face) -> bool:
    return element.is_dynamic


def icon_glyph_entries(element: IconElement, face) -> dict[str, str]:
    if not element.is_dynamic:
        return {}
    return {
        name: icons.CATALOG[name].codepoint
        for name in set(icons.GARMIN_WEATHER_CONDITION_ICON.values())
    }


KIND = ElementKind(
    name="icon",
    ir_class=IconElement,
    placed_class=PlacedIcon,
    build=lambda b, node, common, path: b._build_icon(node, common),
    resolve=Resolver._resolve_icon,
    draw_preview=_Renderer._icon,
    emit_draw=lambda w, resolved, placed, value_guards, plan, aod: shapes._emit_icon(
        w, placed, aod),
    describe=describe,
    layout_constants=layout_constants_mod._icon_constants,
    loaded_fonts=loaded_fonts,
    icon_font_need=icon_font_need,
    needs_icon_glyphs=needs_icon_glyphs,
    icon_glyph_entries=icon_glyph_entries,
)
