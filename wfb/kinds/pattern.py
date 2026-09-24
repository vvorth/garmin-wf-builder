"""`type: pattern` -- one template of 1-16 primitives, drawn repeatedly:
turned about `at:` (`pattern: radial`) or stepped along `{dx, dy}`
(`pattern: linear`)."""

from __future__ import annotations

from .. import lint
from ..ir.model import PatternElement, Position
from ..layout import PlacedPattern, Resolver
from ..preview import _Renderer
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc import rotated
from . import ElementKind


def _aod_refusal(key, shape, literal_text):
    if key == "font":
        return (
            "aod",
            "a pattern's 'aod: {font: ...}' override is not implemented yet (plan 14)",
            ["restyle this pattern's colour/thickness in AOD instead, or drop the font "
             "override for now"],
        )
    return None


def circular_extent(placed: PlacedPattern):
    if placed.element.pattern == "radial":
        return (placed.center[0], placed.center[1], placed.reach)
    return None


def describe(placed: PlacedPattern) -> str:
    element = placed.element
    total = element.count
    drawn_count = len(placed.copies)
    note = "" if drawn_count == total else f" ({drawn_count} drawn)"
    if element.pattern == "radial":
        return f"a radial pattern: {total} copies, {element.step_angle:g} degrees apart{note}"
    step = element.step or Position()
    offsets = [f"{axis} {length}" for axis, length in
              (("dx", step.dx), ("dy", step.dy)) if length is not None]
    step_desc = ", ".join(offsets) if offsets else "0px"
    return f"a linear pattern: {total} copies, step {step_desc}{note}"


def loaded_fonts(placed: PlacedPattern) -> list[str]:
    return [part.font_reference for part in placed.parts
            if part.shape == "text" and part.font_is_custom and not part.font_is_vector]


def vector_fonts(placed: PlacedPattern) -> list[str]:
    return [part.font_reference for part in placed.parts
            if part.shape == "text" and part.font_is_vector]


def font_unavailable(placed, part_index: int | None) -> bool:
    return (isinstance(placed, PlacedPattern) and part_index is not None
            and part_index < len(placed.parts) and not placed.parts[part_index].font_available)


def glyph_needs(element: PatternElement, face, bucket) -> None:
    # Every drawn copy's string is known at build time (`HandPart.texts`),
    # so a text part's font needs exactly those.
    for part in element.parts:
        if part.shape != "text" or not part.font_is_custom:
            continue
        glyphs = bucket(part.font)
        if glyphs is None:
            continue
        for index in element.drawn_indices():
            glyphs |= set(part.texts[index])


def vector_font_names(element: PatternElement) -> tuple[str, ...]:
    return tuple(part.font for part in element.parts
                if part.shape == "text" and part.font_is_custom)


def vector_text_carriers(element: PatternElement) -> list:
    return [(f"{element.id}.parts[{index}]", part, index)
            for index, part in enumerate(element.parts) if part.shape == "text"]


def check_glyphs(placed: PlacedPattern, resolved, bag) -> None:
    for index, part in enumerate(placed.parts):
        if part.shape != "text" or not part.font_is_custom:
            continue
        font = resolved.fonts.get(part.font_reference)
        if font is None:
            continue
        missing: set[str] = set()
        for copy_index in placed.copies:
            missing |= font.missing(part.texts[copy_index])
        if missing:
            lint._missing_glyph_error(
                bag, f"{placed.id}.parts[{index}]", part.font_reference, missing,
                placed.element.parts[index].span, [])


def contrast_subjects(placed: PlacedPattern):
    """A `pattern` yields each template part once (every copy shares its
    colours); it has no per-part structure on `Element.color_roles()`
    either.  `allow_backdrop_match` is false only for a `shape: text` part,
    the one shape where an exact backdrop match is invisible content by
    mistake."""
    for index, part in enumerate(placed.parts):
        yield (f"{placed.id}.parts[{index}]", part.color, part.outline_color,
               part.shape != "text")


KIND = ElementKind(
    name="pattern",
    ir_class=PatternElement,
    placed_class=PlacedPattern,
    build=lambda b, node, common, path: b._build_pattern_element(node, common),
    resolve=Resolver._resolve_pattern,
    aod_refusal=_aod_refusal,
    antialiased=True,
    circular_extent=circular_extent,
    draw_preview=_Renderer._pattern,
    emit_draw=lambda w, resolved, placed, value_guards, plan, aod: rotated._emit_pattern(
        w, placed, aod),
    describe=describe,
    layout_constants=layout_constants_mod._pattern_constants,
    loaded_fonts=loaded_fonts,
    vector_fonts=vector_fonts,
    font_unavailable=font_unavailable,
    glyph_needs=glyph_needs,
    vector_font_names=vector_font_names,
    vector_text_carriers=vector_text_carriers,
    check_glyphs=check_glyphs,
    contrast_subjects=contrast_subjects,
)
