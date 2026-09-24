"""`type: complication_slot` -- the element half of the native Data axis:
draws whichever complication the wearer currently has this `slot:` pointed
at."""

from __future__ import annotations

from .. import catalog, complications, formatting, icons
from ..ir.model import ComplicationSlot
from ..ir.naming import complication_slot_hold_method, complication_slot_icon_method
from ..layout import PlacedComplicationSlot, Resolver
from ..preview import _Renderer
from ..emit.monkeyc import complication_slot as complication_slot_mod
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.resources import _COMPLICATION_TEXT_ALPHABET
from . import ElementKind


def _aod_refusal(key, shape, literal_text):
    if key == "font":
        return (
            "aod",
            "a complication_slot's 'aod: {font: ...}' override is not implemented yet (plan 14)",
            ["restyle this slot's colour/icon_color in AOD instead, or drop the font "
             "override for now"],
        )
    return None


def describe(placed: PlacedComplicationSlot) -> str:
    return f"a native Data-axis slot (config.data.{placed.element.slot})"


def loaded_fonts(placed: PlacedComplicationSlot) -> list[str]:
    out = []
    if placed.font_is_custom:
        out.append(placed.font_reference)
    if placed.icon_font_key is not None:
        out.append(placed.icon_font_key)
    return out


def glyph_needs(element: ComplicationSlot, face, bucket) -> None:
    if not element.font_is_custom:
        return
    glyphs = bucket(element.font)
    if glyphs is None:
        return
    # The wearer can point this slot at any of its declared choices, each
    # with its own value type and no per-choice `format:`, so the font
    # must carry everything *any* choice could render
    # (`Resolver._complication_slot_widest`, same reason).
    slot = face.config_data.get(element.slot)
    choices: tuple[str, ...] = ()
    if slot is not None:
        choices = (slot.default,) if slot.allow_any else slot.choices
    for name in choices:
        ctype = complications.TYPES.get(name)
        if ctype is None:
            continue
        value_type = (catalog.Type.STRING if ctype.value_type == "string"
                     else catalog.Type.NUMBER)
        glyphs |= formatting.glyphs("{}", None, value_type)
        if ctype.value_type == "float":
            glyphs |= set(".")
    if element.placeholder:
        glyphs |= set(element.placeholder)
    if element.label != "none" or element.unit:
        # A label is always a localised device string; a unit can be too
        # (`Complications.Unit or Lang.String`) -- both unbounded.
        glyphs |= set(_COMPLICATION_TEXT_ALPHABET)
    if element.unit:
        glyphs |= set("".join(complications.UNIT_SUFFIX.values()))


def icon_font_need(element: ComplicationSlot, face):
    if element.icon_size is None:
        return None
    slot = face.config_data.get(element.slot)
    if slot is None:
        return None
    mapped = slot.icons  # 'choices: any' resolves against the whole of
                         # COMPLICATION_ICON -- see ConfigDataSlot.icons's
                         # own docstring.
    if not mapped:
        # None of this slot's choices has a catalogue icon -- it simply
        # draws none, which is a documented, legitimate outcome
        # (`wfb.icons.COMPLICATION_ICON`'s own docstring), not something
        # to bake a font for.
        return None
    glyphs = "".join(sorted({si.codepoint for si in mapped.values()}))
    # The default choice's own icon normalises the shared nominal size,
    # the same "pick one reference glyph" trade-off
    # `WEATHER_BAKE_REFERENCE_GLYPH` makes for the weather set.
    default_icon = mapped.get(slot.default)
    reference_icon = default_icon or sorted(mapped.values(), key=lambda si: si.key)[0]
    reference = reference_icon.codepoint
    key = icons.font_key(element.icon_size, f"slot_{element.slot}", element.resolved_antialias)
    return key, (element.icon_size, glyphs, reference, element.resolved_antialias)


def needs_icon_glyphs(element: ComplicationSlot, face) -> bool:
    return element.icon_size is not None


def icon_glyph_entries(element: ComplicationSlot, face) -> dict[str, str]:
    if element.icon_size is None:
        return {}
    slot = face.config_data.get(element.slot)
    if slot is None:
        return {}
    return {slot_icon.key: slot_icon.codepoint for slot_icon in slot.icons.values()}


KIND = ElementKind(
    name="complication_slot",
    ir_class=ComplicationSlot,
    placed_class=PlacedComplicationSlot,
    build=lambda b, node, common, path: b._build_complication_slot(node, common),
    resolve=Resolver._resolve_complication_slot,
    extra_symbols=(complication_slot_icon_method, complication_slot_hold_method),
    static_forbidden=(
        "a complication_slot",
        "its reading is pulled fresh every frame, and the wearer can "
        "repoint it to a different complication at any time -- a buffer "
        "filled once would freeze both",
    ),
    aod_refusal=_aod_refusal,
    draw_preview=_Renderer._complication_slot,
    emit_draw=lambda w, resolved, placed, value_guards, plan, aod:
        complication_slot_mod._emit_complication_slot(w, resolved, placed, plan.device_guards, aod),
    emits_own_guards=True,
    describe=describe,
    layout_constants=layout_constants_mod._complication_slot_constants,
    loaded_fonts=loaded_fonts,
    glyph_needs=glyph_needs,
    icon_font_need=icon_font_need,
    needs_icon_glyphs=needs_icon_glyphs,
    icon_glyph_entries=icon_glyph_entries,
)
