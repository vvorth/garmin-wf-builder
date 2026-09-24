"""`type: text` -- a bound or literal string, optionally curved onto a
`face:` (vector) font."""

from __future__ import annotations

from .. import catalog, formatting
from .. import lint
from ..ir.model import Text
from ..layout import PlacedText, Resolver, text_ink
from ..preview import _Renderer
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc import shapes
from . import ElementKind


def _aod_refusal(key, shape, literal_text):
    if key == "format" and literal_text:
        return ("format", "'aod: {format: ...}' applies only to 'value:', not a fixed 'text:'", [])
    return None


def ink(placed: PlacedText, fonts_root: str | None = None):
    """A curved element's rotated box/sector, rebuilt from the fields
    `Resolver._resolve_text` stored -- `None` for upright text, whose box
    corners are already its real corners."""
    if placed.curve_style is None:
        return None
    outline = placed.element.outline
    return text_ink(
        placed.anchor_point[0], placed.anchor_point[1], float(placed.measured_width),
        placed.line_height, placed.element.align, placed.element.vertical_align,
        curve_style=placed.curve_style, angle_garmin=placed.curve_angle_garmin,
        radius_px=placed.curve_radius_px, direction=placed.curve_direction,
        metric=placed.font_metric, pad=float(outline.width) if outline is not None else 0.0,
        fonts_root=fonts_root)


def describe(placed: PlacedText) -> str:
    return "text" if placed.element.value is not None else "fixed text"


def loaded_fonts(placed: PlacedText) -> list[str]:
    if placed.font_is_custom and not placed.font_is_vector:
        return [placed.font_reference]
    return []


def vector_fonts(placed: PlacedText) -> list[str]:
    return [placed.font_reference] if placed.font_is_vector else []


def font_unavailable(placed, part_index: int | None) -> bool:
    return isinstance(placed, PlacedText) and not placed.font_available


def glyph_needs(element: Text, face, bucket) -> None:
    if not element.font_is_custom:
        return
    glyphs = bucket(element.font)
    if glyphs is None:
        return
    # An `aod: {font: ...}` override naming a different baked font draws
    # the same string (through its own `format:` override, if any), so its
    # bucket needs the same glyphs -- not the "0123456789" fallback an
    # empty bucket would otherwise bake with.
    aod = element.aod
    aod_glyphs = (bucket(aod.font) if aod is not None and aod.font is not None
                  and aod.font_is_custom else None)
    if element.literal is not None:
        glyphs |= set(element.literal)
        if aod_glyphs is not None:
            aod_glyphs |= set(element.literal)
        return
    if element.value is None:
        return
    source = catalog.get(element.value.sources[0]) if element.value.sources else None
    spec = element.format or "{}"
    value_glyphs = formatting.glyphs(spec, source, element.value.value.type, element.value.scale)
    glyphs |= value_glyphs
    if aod_glyphs is not None:
        aod_spec = aod.format if aod.format is not None else spec
        aod_glyphs |= (
            value_glyphs if aod_spec == spec
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


def vector_font_names(element: Text) -> tuple[str, ...]:
    return (element.font,) if element.font_is_custom else ()


def vector_text_carriers(element: Text) -> list:
    return [(element.id, element, None)]


def check_glyphs(placed: PlacedText, resolved, bag) -> None:
    if not placed.font_is_custom:
        return
    font = resolved.fonts.get(placed.font_reference)
    if font is None:
        return
    missing = font.missing(placed.widest)
    if missing:
        lint._missing_glyph_error(
            bag, placed.id, placed.font_reference, missing, placed.element.span,
            [f"the widest rendering of this element is {placed.widest!r}"])


KIND = ElementKind(
    name="text",
    ir_class=Text,
    placed_class=PlacedText,
    build=lambda b, node, common, path: b._build_text(node, common),
    resolve=Resolver._resolve_text,
    aod_refusal=_aod_refusal,
    ink=ink,
    draw_preview=_Renderer._text,
    emit_draw=lambda w, resolved, placed, value_guards, plan, aod: shapes._emit_text(
        w, resolved, placed, value_guards, aod),
    describe=describe,
    layout_constants=layout_constants_mod._text_constants,
    loaded_fonts=loaded_fonts,
    vector_fonts=vector_fonts,
    font_unavailable=font_unavailable,
    glyph_needs=glyph_needs,
    vector_font_names=vector_font_names,
    vector_text_carriers=vector_text_carriers,
    check_glyphs=check_glyphs,
)
