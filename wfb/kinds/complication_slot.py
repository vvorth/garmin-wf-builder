"""`type: complication_slot` -- the element half of the native Data axis:
draws whichever complication the wearer currently has this `slot:` pointed
at."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TYPE_CHECKING

from .. import complications, icons, units, vocab
from ..diagnostics import Span
from ..ir.builder import ICON_SIZE_NOTE
from ..ir.model import HOLD_AUTO, ComplicationSlot, ConfigDataSlot, Element, Expression
from ..ir.naming import complication_slot_hold_method, complication_slot_icon_method
from ..layout import (
    COMPLICATION_SLOT_ICON_GAP, Placed, PlacedComplicationSlot,
    alignment_shift, complication_slot_pair_geometry, longer,
)
from ..units import Box, IntBox
from ..emit.monkeyc import complication_slot as complication_slot_mod
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.resources import COMPLICATION_TEXT_ALPHABET
from ..draw.program import (
    AodRestyled, Assign, Bin, Blank, Cmp, Comment, Cond, Const, DrawContext, Font, FontHeight, If,
    IsPulsing, Let, Lit, LoadFont, Local, LocalsSet, Num, NumLocal, NumPick, Op, Paint, Return,
    SetColor, SlotIcon, SlotPull, SlotText, Str, Text, TextWidth,
)
from ..emit.monkeyc.common import const_prefix, font_field
from ..ir.naming import config_data_ids, config_field
from . import ElementKind, IconFont, TextRun

if TYPE_CHECKING:
    from ..ir.builder import Builder
    from ..ir.model import Face
    from ..layout import Resolver

#: Illustrative raw readings for a `complication_slot` preview, keyed by
#: `wfb.complications.TYPES` name, in the units the SDK documents -- not
#: real data (there is no live `Complications` subscription on the host),
#: just something plausible, formatted by the same rules the watch uses
#: (`wfb.complications.format_reading`).  Falls back to 12 / "--" for a
#: type not listed here.
COMPLICATION_SLOT_SAMPLE: dict[str, object] = {
    "steps": 8432,
    "heart_rate": 72,
    "calories": 1840,
    "battery": 68,
    "body_battery": 62,
    "floors_climbed": 7,
    "intensity_minutes": 17,
    "notification_count": 3,
    "stress": 34,
    "current_temperature": 21.4,
    "high_low_temperature": "H 26 / L 17",
    "current_weather": 22,
    "forecast_weather_1day": 1,
    "forecast_weather_2day": 3,
    "forecast_weather_3day": 0,
    "sunrise": 22512,
    "sunset": 65558,
    "altitude": 511.0,
    "sea_level_pressure": 101675.0,
    "recovery_time": 2161,
    "race_predictor_5k": 1480,
    "race_predictor_10k": 3090,
    "race_predictor_half_marathon": 6900,
    "race_predictor_marathon": 14520,
    "race_pace_predictor_5k": 3.38,
    "race_pace_predictor_10k": 3.24,
    "race_pace_predictor_half_marathon": 3.06,
    "race_pace_predictor_marathon": 2.91,
    "weekly_run_distance": 23400.0,
    "weekly_bike_distance": 61200.0,
    "vo2max_run": 49,
    "vo2max_bike": 45,
    "pulse_ox": 97,
    "respiration_rate": 15,
    "solar_input": 40,
    "sleep_score": 88,
    "calendar_events": "19:00",
    "date": "28 Mar",
    "weekday_monthday": "Wed 28",
    "training_status": "PRODUCTIVE",
}


def resolve_slot_reference(b: Builder, raw: str, span: Span | None) -> ConfigDataSlot | None:
    """Resolve a `slot: config.data.<name>` reference -- a `data` element's
    or a gauge's.

    The same declared/rejected cascade every other `config:` sub-block
    keeps: a name that was declared and then rejected (a bad default/
    choice reference, or a default not among choices) gets no second
    error here, because the real mistake already has its own error
    reported against the `config: data:` block.
    """
    if not raw.startswith("config.data."):
        b.bag.error(
            "complication-slot",
            f"slot: expected the name of a 'config: slots:' entry, got {raw!r}",
            span,
        )
        return None
    name = raw[len("config.data."):]
    return b.config_data.resolve(
        b.bag, name, span, code="complication-slot",
        message=f"unknown slot {name!r}",
        note="declared slots (config: slots:)", prefix="",
    )


def _check_slot_color_absence(
    b: Builder, node: dict[str, Any], element: "ComplicationSlot", key: str,
    color: Expression | None, note: str,
) -> None:
    """A complication_slot's `color:`/`icon_color:` may not read
    anything absent-able -- neither has a `when_absent:` of its own to
    fall back through, unlike the pulled reading itself (shared by both
    colours in `build`; `note` carries the one
    wording difference between them -- "colour ... its own" vs.
    "colours ... their own" -- so the messages stay exactly what they
    were before this was one method).
    """
    if color is None or not color.nullable:
        return
    b.bag.error(
        "complication-slot",
        f"{element.id}: '{vocab.key(key)}' reads {color.shown!r}, which can be absent",
        b.doc.span(node, key),
        notes=[
            note,
            "guard it in the expression instead, e.g. "
            "\"x != null and x > 100 ? color.hot : color.fg\"",
        ],
    )


def _slot_choices(face: Face, element: ComplicationSlot) -> tuple[str, ...]:
    """The types this slot can show that the build knows a rule for: its
    declared choices, or, for `choices: any`, every native type."""
    slot = face.config_data.get(element.slot)
    if slot is None:
        return ()
    if slot.allow_any:
        return tuple(complications.names())
    return tuple(name for name in slot.choices if name in complications.TYPES)


def _complication_slot_widest(r: Resolver, element: ComplicationSlot) -> str:
    """The widest plausible reading a `complication_slot` can draw: the
    widest of its choices' readings under its `unit:`/`short:`
    (`wfb.complications.widest_reading`), and the placeholder.

    `label:` is deliberately not folded in: it is a localised device string
    with no documented bound, so any padding is either routinely wrong or
    large enough to push ordinary slots into spurious `off-screen`
    warnings.  `docs/limitations.md` records the gap.
    """
    font = r.font_for_ref(element.font, element.font_is_custom)
    widest = ""
    for name in _slot_choices(r.face, element):
        candidate = complications.widest_reading(name, element.unit, element.short)
        if not widest or font.width(candidate) > font.width(widest):
            widest = candidate
    if element.when_absent == "placeholder" and element.placeholder:
        widest = longer(widest, element.placeholder)
    return widest


def highlight_box(box: IntBox, anchor_x: int, align: str, screen_width: int) -> IntBox:
    """The box the native editor gets with a slot's drawable: the slot's own
    rows, and every screen column its icon+reading pair could reach.

    The editor clips the drawable to this box (seen on a fenix8solar47mm:
    "STEPS 5068" drawn as "TEPS 506" with its icon gone), and `box` cannot
    bound the pair -- it leaves out the label, the unit and a string value
    such as a date's weekday, which have no documented width.  So the width
    comes from the screen instead, the way the SDK's own
    `ConfigurableWatchFace` sample makes its drawable the full screen width.
    `align:` says which side of the anchor the pair grows on
    (`wfb.layout.alignment_shift`, the device's own rule): `left` reaches
    from the anchor to the right edge, `right` from the left edge to the
    anchor, and `center` as far either way as the nearer edge allows, so the
    editor's animation stays centred on the anchor; past that, a centred
    pair is already off-screen on the other side.  `box` is kept inside,
    for an anchor at the very edge.
    """
    if align == "left":
        left, right = anchor_x, screen_width
    elif align == "right":
        left, right = 0, anchor_x
    else:
        half = max(min(anchor_x, screen_width - anchor_x), 0)
        left, right = anchor_x - half, anchor_x + half
    return IntBox(left, box.y, right - left, box.height).union(box)


def _text_glyphs(element: ComplicationSlot, face: Face) -> set[str]:
    """Every character the slot's reading could render.  The wearer can
    point this slot at any of its choices, each with its own rule, so the
    font must carry everything *any* choice could render."""
    glyphs: set[str] = set()
    for name in _slot_choices(face, element):
        glyphs |= complications.reading_glyphs(name, element.unit, element.short)
        if complications.READING[name] in ("text", "training_status", "high_low"):
            # Text the device supplies: a firmware string, unbounded.
            glyphs |= set(COMPLICATION_TEXT_ALPHABET)
    if element.placeholder:
        glyphs |= set(element.placeholder)
    if element.label != "none":
        # A label is always a localised device string -- unbounded.
        glyphs |= set(COMPLICATION_TEXT_ALPHABET)
    return glyphs


def _icon_run(element: ComplicationSlot, face: Face) -> TextRun | None:
    """The slot's multi-glyph icon font (with `icon_size:`), keyed by the
    slot's name, or `None` when none of its choices has a catalogue icon --
    it simply draws none, which is a documented, legitimate outcome
    (`wfb.icons.COMPLICATION_ICON`'s own docstring), not something to bake a
    font for."""
    if element.icon_size is None:
        return None
    slot = face.config_data.get(element.slot)
    if slot is None:
        return None
    mapped = slot.icons  # 'choices: any' resolves against the whole of
                         # COMPLICATION_ICON -- see ConfigDataSlot.icons's
                         # own docstring.
    if not mapped:
        return None
    codepoints = {si.codepoint for si in mapped.values()}
    table = {slot_icon.key: slot_icon.codepoint for slot_icon in mapped.values()}
    if slot.condition_icons:
        # A weather choice's icon follows the pulled condition on-device, so
        # the font needs every condition's glyph.
        codepoints |= set(icons.WEATHER_GLYPH_SET)
        table |= {name: icons.CATALOG[name].codepoint
                  for name in icons.GARMIN_WEATHER_CONDITION_ICON.values()}
    glyphs = "".join(sorted(codepoints))
    # The default choice's own icon normalises the shared nominal size,
    # the same "pick one reference glyph" trade-off
    # `WEATHER_BAKE_REFERENCE_GLYPH` makes for the weather set.
    default_icon = mapped.get(slot.default)
    reference_icon = default_icon or sorted(mapped.values(), key=lambda si: si.key)[0]
    key = icons.font_key(element.icon_size, f"slot_{element.slot}", element.resolved_antialias)
    return TextRun(
        f"{element.id}.icon", key, span=element.span,
        icon=IconFont(element.icon_size, glyphs, reference_icon.codepoint,
                      element.resolved_antialias),
        glyph_table=table)

def _general_pair(element: ComplicationSlot, placed: PlacedComplicationSlot, prefix: str,
                  font: Font, icon_font: Font | None, icon_shown: Cond | None, text_paint: Paint,
                  icon_paint: Paint | None, draw: Callable[..., Op]) -> list[Op]:
    """Any `icon_position:` other than the default `left`, an authored
    `icon_gap:`/`icon_color:` on `left` itself, or a non-default
    `align:`/`vertical_align:`: the pair's alignment is computed on the watch,
    from `Dc.getTextWidthInPixels`/`Dc.getFontHeight`, since neither the
    real text nor the real icon is known until the value is pulled.  Every
    offset is chosen here from `align`/`vertical_align` alone, never a
    runtime branch; `center` reproduces the fast path's expression.

    One axis table serves both layouts: the pair lies along a row (`left`/
    `right`) or a column (`top`/`bottom`).  Along it, the `lead` position
    draws the icon first and `main_align` shifts where the pair starts;
    across it, the other key shifts the shared axis.  Each local is declared
    only when something reads it afterwards: an unused local warns under
    `-l 3` (`tests/test_align_glyph_kinds.py` checks every combination)."""
    cx = Const(f"{prefix}_CX", placed.anchor_point[0])
    cy = Const(f"{prefix}_CY", placed.anchor_point[1])
    gap_value: Num = (Const(f"{prefix}_ICON_GAP", placed.icon_gap_px)
                      if element.icon_gap is not None else Lit(COMPLICATION_SLOT_ICON_GAP))
    has_icon = icon_shown is not None
    text, glyph = Local("text"), Local("iconGlyph")
    ops: list[Op] = [SetColor(text_paint)]
    row = placed.icon_position in ("left", "right")
    if row:
        lead, trail, main_align, cross_align = "left", "right", element.align, element.vertical_align
        size, icon_local, start, center = "Width", "iconGlyphWidth", "startX", cx
        text_size: Num = TextWidth(text, font)
        icon_size: Num | None = TextWidth(glyph, icon_font) if icon_font is not None else None
        justify: tuple[str, ...] = ("TEXT_JUSTIFY_LEFT", "TEXT_JUSTIFY_VCENTER")
    else:
        lead, trail, main_align, cross_align = "top", "bottom", element.vertical_align, element.align
        size, icon_local, start, center = "Height", "iconHeight", "startY", cy
        text_size = FontHeight(font)
        icon_size = FontHeight(icon_font) if icon_font is not None else None
        justify = ("TEXT_JUSTIFY_CENTER",)
    text_local, total = f"text{size}", f"total{size}"
    position = placed.icon_position
    if (position == trail and has_icon) or main_align != lead:
        ops.append(Let(text_local, text_size))
    if position == lead or main_align != lead:
        ops.append(Let(icon_local, Lit(0)))
        if icon_shown is not None and icon_size is not None:
            ops.append(If(icon_shown, (Assign(icon_local, icon_size),)))
    if position == lead or (position == trail and has_icon) or main_align != lead:
        ops.append(Let("gap", NumPick(icon_shown, gap_value, Lit(0)) if icon_shown is not None
                       else Lit(0)))
    pieces = Bin("+", Bin("+", NumLocal(icon_local), NumLocal("gap")), NumLocal(text_local))
    if main_align == lead:
        ops.append(Let(start, center))
    elif main_align == trail:
        ops += [Let(total, pieces), Let(start, Bin("-", center, NumLocal(total)))]
    else:
        ops += [Let(total, pieces),
                Let(start, Bin("-", center, Bin("/", NumLocal(total), Lit(2))))]

    cross: Num
    if row:
        if cross_align == "center":
            cross = cy
        else:
            ops.append(Let("rowHeight", FontHeight(font)))
            if icon_shown is not None and icon_font is not None:
                ops.append(If(icon_shown, (
                    Let("iconRowHeight", FontHeight(icon_font)),
                    If(Cmp(">", NumLocal("iconRowHeight"), NumLocal("rowHeight")),
                       (Assign("rowHeight", NumLocal("iconRowHeight")),)))))
            sign = "+" if cross_align == "top" else "-"
            ops.append(Let("rowY", Bin(sign, cy, Bin("/", NumLocal("rowHeight"), Lit(2)))))
            cross = NumLocal("rowY")
    else:
        if cross_align == "center":
            cross = cx
        else:
            ops += [Let("textWidth", TextWidth(text, font)), Let("iconGlyphWidth", Lit(0))]
            if icon_shown is not None and icon_font is not None:
                ops.append(If(icon_shown, (Assign("iconGlyphWidth", TextWidth(glyph, icon_font)),)))
            ops.append(Let("pairWidth", NumPick(
                Cmp(">", NumLocal("iconGlyphWidth"), NumLocal("textWidth")),
                NumLocal("iconGlyphWidth"), NumLocal("textWidth"))))
            sign = "+" if cross_align == "left" else "-"
            ops.append(Let("pairX", Bin(sign, cx, Bin("/", NumLocal("pairWidth"), Lit(2)))))
            cross = NumLocal("pairX")

    def at(offset: str | None) -> tuple[Num, Num]:
        """``x, y`` for a piece ``offset`` along the pair from its start."""
        along: Num = NumLocal(start)
        if offset is not None:
            along = Bin("+", Bin("+", along, NumLocal(offset)), NumLocal("gap"))
        return (along, cross) if row else (cross, along)

    def set_icon_color() -> list[Op]:
        return [SetColor(icon_paint)] if icon_paint is not None else []

    if position == lead:
        if icon_shown is not None and icon_font is not None:
            ops.append(If(icon_shown, (*set_icon_color(), draw(*at(None), icon_font, glyph,
                                                               justify))))
        if icon_paint is not None and icon_font is not None:
            ops.append(SetColor(text_paint))
        ops.append(draw(*at(icon_local), font, text, justify))
    else:
        ops.append(draw(*at(None), font, text, justify))
        if icon_shown is not None and icon_font is not None:
            ops.append(If(icon_shown, (*set_icon_color(), draw(*at(text_local), icon_font,
                                                               glyph, justify))))
    return ops


class ComplicationSlotKind(ElementKind[ComplicationSlot, PlacedComplicationSlot]):
    name = "complication_slot"
    ir_class = ComplicationSlot
    placed_class = PlacedComplicationSlot
    extra_symbols = (complication_slot_icon_method, complication_slot_hold_method)
    static_forbidden = (
        "a data element",
        "its reading is pulled fresh every frame, and the wearer can "
        "repoint it to a different complication at any time -- a buffer "
        "filled once would freeze both",
    )

    def build(self, b: Builder, node: dict[str, Any], common: dict[str, Any], path: tuple[str | int, ...]) -> Element:
        """`type: complication_slot` -- the element half of the native Data
        axis (docs/research/09-data-library-and-config-axes.md §4).

        Most of what makes every other element kind checkable at build time
        -- a fixed source, a static type -- does not exist here: which
        `complication.<name>` the wearer picked is only known on-device.  So
        this validates the *slot reference* and the authoring keys that do
        not depend on the choice (`icon_size:`, `format:`), and leaves
        everything about the pulled value itself to
        `ComplicationSlotKind.lower`, which reads it fresh
        every frame the same way any other `complication.*` source does.
        """
        slot_raw = node["slot"]
        slot = resolve_slot_reference(b, str(slot_raw), b.doc.span(node, "slot"))

        icon_size = b.baked_size_length(
            node, "icon_size", code="complication-slot", label="icon: {size:}",
            note=ICON_SIZE_NOTE,
        )

        icon_position = node.get("icon_position", "left")
        icon_gap = b.baked_size_length(
            node, "icon_gap", code="complication-slot", label="icon: {gap:}",
            note="the same restriction the icon's size has -- an icon's font is "
                 "baked once, before layout runs, so the gap that sits "
                 "against it cannot depend on a parent box (%) or an "
                 "element's own font (pt)",
        )
        if icon_gap is not None and icon_gap.value < 0:
            b.bag.error(
                "complication-slot",
                f"icon: {{gap:}} must not be negative, got {icon_gap.value:g}{icon_gap.unit}",
                b.doc.span(node, "icon_gap"),
            )
            icon_gap = None

        icon_color = b.color_expression(node, "icon_color")

        # None of 'icon_position:'/'icon_gap:'/'icon_color:' means anything
        # without an icon to place, space or colour -- checked against
        # whether the author wrote 'icon_size:' at all, not against whatever
        # it resolved to, so a *different* mistake in 'icon_size:' (a bad
        # unit, say) is reported once, not doubled up with a second "needs
        # icon_size:" complaint about the same missing icon.
        if "icon_size" not in node:
            for key in ("icon_position", "icon_gap", "icon_color"):
                if key not in node:
                    continue
                b.bag.error(
                    "complication-slot",
                    f"{common['id']}: '{vocab.key(key)}' needs 'icon: {{size:}}'",
                    b.doc.span(node, key),
                    notes=[f"'{vocab.key(key)}' only means something for the icon this "
                           "slot draws, and there is no icon to place, space or colour "
                           "without a size",
                           f"add 'icon: {{size:}}', or drop '{vocab.key(key)}'"],
                )
            icon_position = "left"
            icon_gap = None
            icon_color = None

        if "format" in node:
            b.bag.error(
                "complication-slot",
                f"{common['id']}: 'format:' is not accepted on a 'type: data' element",
                b.doc.span(node, "format"),
                notes=[
                    "Complications.Complication.value is a String or Number or "
                    "Float or Long or Double union whose concrete type genuinely "
                    "varies by which choice the wearer picks -- a format string "
                    "written for one choice would be silently wrong for another",
                    "this element formats each type by its own rule instead (a "
                    "time of day, a duration, a pace, a rounded temperature, ...); "
                    "use 'unit:', 'short:' and 'label:' to adjust it",
                ],
            )

        color = b.color_expression(node, "color")
        align, vertical_align = b.alignment(node)
        element = ComplicationSlot(
            **common,
            slot=(slot.name if slot is not None else str(slot_raw)),
            icon_size=icon_size,
            color=color,
            icon_position=icon_position,
            icon_gap=icon_gap,
            icon_color=icon_color,
            label=node.get("label", "none"),
            unit=bool(node.get("unit", False)),
            short=bool(node.get("short", False)),
            when_absent=node.get("when_absent", "hide"),
            placeholder=node.get("placeholder"),
            align=align,
            vertical_align=vertical_align,
        )
        font_ok = b.resolve_font(node, element)
        if font_ok and b.is_vector_font(element.font, element.font_is_custom):
            # `ComplicationSlotKind.lower` has no vector-font draw path.
            b.bag.error(
                "complication-slot",
                f"{element.id}: 'font: font.{element.font}' is a 'face:' "
                "(vector) font -- not accepted on a 'type: data' element",
                b.doc.span(node, "font"),
                notes=[
                    "a vector font is drawn straight from the device's own "
                    "resident face through Dc.drawText/drawAngledText/"
                    "drawRadialText -- a data element draws its reading "
                    "through a different path that only accepts a baked "
                    "bitmap font or one of the platform's fixed system fonts",
                    "a vector font is only usable on a 'text' element",
                    "declare this font with 'source:' instead, or point "
                    "'font:' at a baked or system font",
                ],
            )

        if element.on_hold is not None and element.on_hold != HOLD_AUTO:
            # A fixed target would disagree with the slot the moment the
            # wearer repoints it; `auto` is resolved on-device from the
            # slot's own current id (`_resolve_hold_auto`).
            b.bag.error(
                "complication-slot",
                f"{element.id}: 'on_hold:' on a 'type: data' element only accepts "
                f"'auto', not {element.on_hold!r}",
                element.span,
                notes=[
                    "a slot already draws whatever complication the wearer chose in "
                    "the native editor -- opening a fixed, different glance on hold "
                    "would silently disagree with what is on screen the moment the "
                    "wearer repoints it",
                    "'on_hold: auto' opens the glance the wearer's own current pick "
                    "belongs to (Complications.exitTo on this slot's own id), "
                    "resolved fresh on every hold rather than fixed at build time",
                    "to always launch one fixed glance regardless of what this slot "
                    "shows, bind a plain 'text'/'icon' element to the matching "
                    "'complication.<name>' source and put 'on_hold: <name>' there "
                    "instead",
                ],
            )
            element.on_hold = None

        if color is None:
            b.require(node, "color", "a data element needs a color")
        else:
            _check_slot_color_absence(
                b, node, element, "color", color,
                "a data element's colour has no 'absent:' of its own -- 'absent:' "
                "governs the pulled reading, not the element's appearance",
            )

        _check_slot_color_absence(
            b, node, element, "icon_color", icon_color,
            "a data element's colours have no 'absent:' of their own -- "
            "'absent:' governs the pulled reading, not the element's appearance",
        )

        if element.when_absent == "placeholder" and element.placeholder is None:
            b.require(node, "placeholder", "when_absent: placeholder needs a 'placeholder:'")

        return element

    def resolve(self, r: Resolver, element: ComplicationSlot, parent: Box, depth: int) -> Placed:
        """A `complication_slot`: an estimated box, plus the icon and text
        fonts the emitter needs.  What is drawn is the wearer's runtime pick,
        so this sizes the text by `_complication_slot_widest` and, with
        `icon_size:`, one multi-glyph icon font keyed by the slot's name
        (so two slots never share one), measured by a reference glyph.  The
        pair's extent comes from `complication_slot_pair_geometry`, with the
        *declared* icon size as the icon's height.
        """
        cx, cy = r.point(element.at, parent)
        font = r.font_for_ref(element.font, element.font_is_custom)
        widest = _complication_slot_widest(r, element)
        text_width, line_height = font.width(widest), font.line_height

        icon_font_key: str | None = None
        icon_px = 0
        icon_width = 0
        if element.icon_size is not None:
            slot = r.face.config_data.get(element.slot)
            reference_glyph: str | None = None
            if slot is not None:
                mapped = slot.icons
                if mapped:
                    default_icon = mapped.get(slot.default)
                    reference_icon = (default_icon
                                      or sorted(mapped.values(), key=lambda si: si.key)[0])
                    reference_glyph = reference_icon.codepoint
            if reference_glyph is not None:
                icon_px = units.pixel_size(element.icon_size, r.device.minor_radius)
                icon_font_key = icons.font_key(
                    element.icon_size, f"slot_{element.slot}", element.resolved_antialias)
                icon_font = r.fonts.get(icon_font_key)
                icon_width = (icon_font.measure(reference_glyph)[0] if icon_font is not None
                              else icon_px)

        gap_px = (units.pixel_size(element.icon_gap, r.device.minor_radius)
                 if element.icon_gap is not None else COMPLICATION_SLOT_ICON_GAP)
        # `icon_width`/`icon_px` stay 0 when no icon font resolved.
        geometry = complication_slot_pair_geometry(
            element.icon_position, icon_width, icon_px, text_width, line_height, gap_px)
        height = max(geometry.height, 1)
        # The lint box only: the device centres the real pair on the
        # unshifted anchor at runtime.
        dx, dy = alignment_shift(geometry.width, height, element.align, element.vertical_align)
        box = Box(cx + dx - geometry.width / 2, cy + dy - height / 2, geometry.width, height)
        rounded = box.rounded()
        return PlacedComplicationSlot(
            element, rounded, (round(cx), round(cy)), depth,
            anchor_point=(round(cx), round(cy)),
            font=font.resolved(),
            widest=widest, icon_font_key=icon_font_key, icon_px=icon_px,
            icon_position=element.icon_position, icon_gap_px=gap_px,
            highlight=highlight_box(rounded, round(cx), element.align, r.device.width),
        )

    def aod_refusal(self, key: str, shape: str | None,
                    literal_text: bool) -> tuple[str, str, list[str]] | None:
        if key == "font":
            return (
                "aod",
                "a data element's 'aod: {font: ...}' override is not implemented yet",
                ["restyle this element's 'color:'/'icon: {color:}' in AOD instead, or drop "
                 "the font override for now"],
            )
        return None

    def text_runs(self, element: ComplicationSlot, face: Face) -> list[TextRun]:
        runs = []
        if element.font_is_custom:
            runs.append(TextRun(element.id, element.font,
                                glyphs=frozenset(_text_glyphs(element, face)), span=element.span))
        icon_run = _icon_run(element, face)
        if icon_run is not None:
            runs.append(icon_run)
        return runs

    def lower(self, ctx: DrawContext, placed: PlacedComplicationSlot) -> list[Op]:
        """A native Data-axis slot: pull the wearer's chosen complication,
        choose an icon from its *type* alone, then draw the two as one pair.

        Everything here is a plain per-frame pull (`WfbComplications.valueOf`),
        like an ordinary `complication.<name>` source: the compiled field holds
        a `Complications.Id` the *wearer* can repoint (complications are pulled,
        not cached; docs/research/probes/complication-pull/).

        The icon is chosen from `chosenId.getType()`, not from the pulled
        value, so it still shows on a frame the reading could not be pulled
        (docs/research/probes/config-axes/ProbeView.mc's `iconFor`).  The pair
        is placed on the element's own anchor with `Dc.getTextWidthInPixels`:
        the text is not known until the value is pulled, so unlike every other
        element this cannot be precomputed (ADR 0004's one deliberate
        exception).  `align`/`vertical_align` move the pair off the anchor
        with the same per-`icon_position:` arithmetic; `center`/`center` with
        the icon on the left, its default gap and the text's colour is the
        fast path.

        Every slot starts with a `_pulsing` guard: the native editor can
        animate *any* slot's highlight (`getComplicationDrawable`), and the
        SDK sample's own comment makes skipping the normal draw mandatory
        while it does -- "This prevents the complication from being drawn on
        the watch face while it is pulsing."

        Where `Complications` may be absent (`ctx.complications_guarded`),
        `chosenId` may be null, so both places that dereference it go through
        a null-safe ternary; a null `chosenId` then reads like an unsupported
        type: the icon and the pulled value both come back null.

        On the host the pick is the slot's `default:` and the reading an
        illustrative sample (`COMPLICATION_SLOT_SAMPLE`): there is no
        on-device editor to ask, and no live subscription."""
        element = placed.element
        aod = ctx.aod
        prefix = const_prefix(placed.id)
        face = ctx.resolved.face
        slot = face.config_data[element.slot]
        shown = ctx.shown(slot)
        ctype = complications.TYPES[shown]
        sample = COMPLICATION_SLOT_SAMPLE.get(
            ctype.name, 12 if ctype.value_type != "string" else "--")
        guarded = ctx.complications_guarded
        ops: list[Op] = [
            Comment("the editor is animating this exact slot right now -- skip it, or the"),
            Comment("system draws it twice while it pulses (SDK sample's own comment);"),
            Comment("drawSlot lifts this for the editor's own drawable"),
            If(IsPulsing(config_data_ids(face)[element.slot]), (Return(),)),
            Blank(),
            Comment(f"slot: {element.slot}"),
            SlotPull(config_field(f"data_{element.slot}"), guarded,
                     COMPLICATION_SLOT_SAMPLE.get(shown)),
        ]

        icon_font: Font | None = None
        if placed.icon_font_key is not None:
            icon = slot.icons.get(shown)
            glyph = None
            if icon is not None:
                glyph = icon.codepoint
                if shown in slot.condition_icons and isinstance(sample, int):
                    glyph = icons.CATALOG[icons.GARMIN_WEATHER_CONDITION_ICON.get(
                        sample, "weather_unknown")].codepoint
            ops.append(SlotIcon(font_field(placed.icon_font_key), placed.icon_font_key,
                                complication_slot_icon_method(element.id), guarded, glyph))
            icon_font = Font("iconFont", baked=placed.icon_font_key)

        if placed.font.is_custom:
            ops.append(LoadFont("textFont", f"_{font_field(placed.font.reference)}"))
            code = "textFont"
        else:
            code = f"Graphics.{placed.font.reference}"
        font = Font(code, baked=placed.font.reference if placed.font.is_custom else None,
                    metric=placed.font.metric, px=placed.font.px)
        ops += [
            Blank(),
            SlotText(complication_slot_mod.SLOT_TEXT_MODULE, guarded, element.unit, element.short, element.label,
                     element.when_absent, element.placeholder, ctype.name, sample,
                     {"short": "Now ", "long": "Current "}.get(element.label or "", "")),
        ]
        text_paint = AodRestyled(element, "color")
        # `None` when the icon draws in the text's colour, `dc`'s state
        # already: no `icon_color:` and no `aod: {icon_color: ...}` either.
        has_override = aod.on and element.aod is not None and element.aod.icon_color is not None
        icon_paint: Paint | None
        if element.icon_color is None and not has_override:
            icon_paint = None
        elif element.icon_color is not None:
            icon_paint = AodRestyled(element, "icon_color")
        else:
            icon_paint = AodRestyled(element, "icon_color", awake=text_paint)
        text, glyph_text = Local("text"), Local("iconGlyph")
        cx, cy = Const(f"{prefix}_CX", placed.anchor_point[0]), Const(f"{prefix}_CY",
                                                                      placed.anchor_point[1])
        icon_shown = LocalsSet(("iconGlyph", "iconFont")) if icon_font is not None else None

        def draw(x: Num, y: Num, face_: Font, string: Str, justify: tuple[str, ...]) -> Text:
            valign = "center" if "TEXT_JUSTIFY_VCENTER" in justify else "top"
            return Text(x, y, face_, string, justify, valign, joined=True)

        fast = (placed.icon_position == "left" and element.icon_gap is None
                and icon_paint is None and element.align == "center"
                and element.vertical_align == "center")
        if fast:
            row = ("TEXT_JUSTIFY_LEFT", "TEXT_JUSTIFY_VCENTER")
            ops += [SetColor(text_paint), Let("textWidth", TextWidth(text, font)),
                    Let("iconWidth", Lit(0))]
            if icon_font is not None and icon_shown is not None:
                ops.append(If(icon_shown, (Assign("iconWidth", Bin(
                    "+", TextWidth(glyph_text, icon_font), Lit(COMPLICATION_SLOT_ICON_GAP))),)))
            ops += [Let("totalWidth", Bin("+", NumLocal("iconWidth"), NumLocal("textWidth"))),
                    Let("startX", Bin("-", cx, Bin("/", NumLocal("totalWidth"), Lit(2))))]
            if icon_font is not None and icon_shown is not None:
                ops.append(If(icon_shown, (draw(NumLocal("startX"), cy, icon_font, glyph_text,
                                                row),)))
            ops.append(draw(Bin("+", NumLocal("startX"), NumLocal("iconWidth")), cy, font, text,
                            row))
            return ops
        return ops + _general_pair(element, placed, prefix, font, icon_font, icon_shown,
                                   text_paint, icon_paint, draw)

    def describe(self, placed: PlacedComplicationSlot) -> str:
        return f"a native Data-axis slot (`slot: {placed.element.slot}`)"

    def layout_constants(self, prefix: str,
                         placed: PlacedComplicationSlot) -> "layout_constants_mod.Constants":
        out: "layout_constants_mod.Constants" = [
            (f"{prefix}_CX", placed.anchor_point[0],
             "the icon+reading pair is centred here at runtime"),
            (f"{prefix}_CY", placed.anchor_point[1], ""),
        ]
        # The editor's tap target and highlight are the whole slot's, every
        # element drawing it together (`layout_constants.slot_box_constants`).
        if placed.element.icon_gap is not None:
            # Only when the author wrote 'icon_gap:' -- otherwise the view keeps
            # the literal COMPLICATION_SLOT_ICON_GAP. Resolved per device ('%r'
            # is a different pixel count per screen).
            out.append((f"{prefix}_ICON_GAP", placed.icon_gap_px,
                        "icon: {gap:} resolved for this device"))
        return out


KIND = ComplicationSlotKind()
