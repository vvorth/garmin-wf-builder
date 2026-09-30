"""`type: complication_slot` -- the element half of the native Data axis:
draws whichever complication the wearer currently has this `slot:` pointed
at."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from .. import complications, icons, units, vocab
from ..diagnostics import Span
from ..fonts import BakedFont, fallback
from ..ir.builder import ICON_SIZE_NOTE
from ..ir.model import HOLD_AUTO, ComplicationSlot, ConfigDataSlot, Element, Expression
from ..ir.naming import complication_slot_hold_method, complication_slot_icon_method
from ..layout import (
    COMPLICATION_SLOT_ICON_GAP, Placed, PlacedComplicationSlot,
    alignment_shift, complication_slot_pair_geometry, longer,
)
from ..preview import baked_glyph
from ..units import Box, IntBox
from ..emit.monkeyc import complication_slot as complication_slot_mod
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc.common import NO_AOD, AodStyle, RingPass
from ..emit.resources import COMPLICATION_TEXT_ALPHABET
from ..emit.writer import Writer
from . import ElementKind, IconFont, TextRun

if TYPE_CHECKING:
    from ..ir.builder import Builder
    from ..ir.model import Face
    from ..emit.monkeyc.readplan import ReadPlan
    from ..layout import ResolvedFace, Resolver
    from ..preview import Renderer

#: Illustrative raw readings for a `complication_slot` preview, keyed by
#: `wfb.complications.TYPES` name, in the units the SDK documents -- not
#: real data (there is no live `Complications` subscription on the host),
#: just something plausible, formatted by the same rules the watch uses
#: (`wfb.complications.format_reading`).  Falls back to 12 / "--" for a
#: type not listed here.
_COMPLICATION_SLOT_SAMPLE: dict[str, object] = {
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


def _resolve_slot_reference(b: Builder, raw: str, span: Span | None) -> ConfigDataSlot | None:
    """Resolve a `complication_slot`'s `slot: config.data.<name>` reference.

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


def _preview_settings(renderer: Renderer) -> complications.ReadingSettings:
    """The preview's own `device.*` sample settings, as a reading follows
    them (`wfb preview --units statute` flips the units)."""
    values = renderer.values
    statute = {key: values.get(f"device.{key}_units") == 1
               for key in ("distance", "elevation", "temperature", "pace")}
    return complications.ReadingSettings(
        is_24_hour=bool(values.get("device.is_24_hour", True)),
        statute_distance=statute["distance"], statute_elevation=statute["elevation"],
        statute_temperature=statute["temperature"], statute_pace=statute["pace"],
    )


def _complication_slot_text(element: ComplicationSlot, ctype: complications.ComplicationType,
                            settings: complications.ReadingSettings) -> str:
    """An illustrative reading for `ctype`, drawn the way
    `wfb.emit.monkeyc.complication_slot.emit_complication_slot` draws one:
    an optional label prefix, then the reading by the type's own rule --
    approximate only in that the label comes from the device at runtime."""
    value = _COMPLICATION_SLOT_SAMPLE.get(
        ctype.name, 12 if ctype.value_type != "string" else "--")
    reading = complications.format_reading(
        ctype.name, value, unit=element.unit, short=element.short, settings=settings)
    if reading is None:
        return element.placeholder or "" if element.when_absent == "placeholder" else ""
    prefix = {"short": "Now ", "long": "Current "}.get(element.label, "")
    return prefix + reading


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
        `wfb.emit.monkeyc.complication_slot.emit_complication_slot`, which reads it fresh
        every frame the same way any other `complication.*` source does.
        """
        slot_raw = node["slot"]
        slot = _resolve_slot_reference(b, str(slot_raw), b.doc.span(node, "slot"))

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
            # `emit_complication_slot` has no vector-font draw path.
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

    def draw_preview(self, renderer: Renderer, placed: PlacedComplicationSlot) -> None:
        """A `complication_slot`, previewed at its slot's *default* choice.

        There is no on-device editor to ask which type the wearer actually
        picked -- the same reason `config:`'s colour axes preview at their
        own `default:` above -- and the default is what a device without the
        native editor (fr955) always shows anyway.  The reading itself is an
        illustrative sample (`_COMPLICATION_SLOT_SAMPLE`), not real data:
        there is no live `Complications` subscription on the host.
        """
        element = placed.element
        slot = renderer.resolved.face.config_data.get(element.slot)
        if slot is None:
            return
        ctype = complications.TYPES[slot.default]
        color = renderer.aod_color(element, "color", element.color)
        if element.icon_color is not None:
            icon_color = renderer.aod_color(element, "icon_color", element.icon_color)
        else:
            # No awake `icon_color:` at all falls back to whatever colour
            # `color` (above) already resolved to -- matches codegen's own
            # "icon draws in the text's colour by default" rule exactly
            # (`wfb.emit.monkeyc.complication_slot.emit_complication_slot`).
            icon_aod = (
                element.aod.icon_color if (renderer.options.aod and element.aod is not None) else None
            )
            icon_color = renderer.color(icon_aod) if icon_aod is not None else color
        s = renderer.scale

        icon_font: BakedFont | None = None
        icon_glyph = None
        if placed.icon_font_key is not None:
            icon = slot.icons.get(slot.default)
            if icon is not None:
                icon_font = renderer.resolved.fonts.get(placed.icon_font_key)
                icon_glyph = icon.codepoint
                sample = _COMPLICATION_SLOT_SAMPLE.get(slot.default)
                if slot.default in slot.condition_icons and isinstance(sample, int):
                    icon_glyph = icons.CATALOG[icons.GARMIN_WEATHER_CONDITION_ICON.get(
                        sample, "weather_unknown")].codepoint

        text = _complication_slot_text(element, ctype, _preview_settings(renderer))
        text_font = (renderer.resolved.fonts.get(placed.font.reference)
                     if placed.font.is_custom else None)
        if text_font is not None:
            text_width, text_height = text_font.measure(text)
        elif placed.font.metric is not None:
            # `fallback.measure`'s second return is whether real metrics were
            # used, not a height -- `resolve` uses `fallback.line_height` for
            # exactly this case, and
            # this mirrors it. `fonts_root` matches `_system_face` below (the
            # same `PreviewOptions.fonts_root` every other measurement this
            # renderer makes goes through), so a slot's box is sized from the
            # same file it is then drawn with.
            text_width, _ = fallback.measure(text, placed.font.metric,
                                             fonts_root=renderer.options.fonts_root)
            text_height = fallback.line_height(placed.font.metric,
                                               fonts_root=renderer.options.fonts_root)
        else:
            text_width, text_height = 0, placed.font.px

        glyph_obj = baked_glyph(icon_font, icon_glyph)
        icon_width, icon_height = (icon_font.measure(icon_glyph)
                                   if glyph_obj is not None and icon_font is not None
                                   and icon_glyph is not None else (0, 0))

        # One shared geometry function for every position --
        # `wfb.layout.complication_slot_pair_geometry`, the same one
        # `resolve` uses to size the estimated
        # box, called here with the *actual* measured extents this preview
        # already has (unlike layout, which only has an estimate).
        geometry = complication_slot_pair_geometry(
            placed.icon_position, icon_width, icon_height, text_width, text_height,
            placed.icon_gap_px,
        )
        ax, ay = placed.anchor_point
        # `align`/`vertical_align` move the pair off the anchor -- the same
        # `wfb.layout.alignment_shift` rule every other kind's preview
        # uses, mirroring the arithmetic
        # `wfb.emit.monkeyc.complication_slot.emit_complication_slot` computes at runtime
        # from its own (real, pulled) measurements. center/center adds
        # exactly `0.0`.
        dx, dy = alignment_shift(geometry.width, geometry.height, element.align,
                                 element.vertical_align)
        origin_x = ax + dx - geometry.width / 2
        origin_y = ay + dy - geometry.height / 2

        if glyph_obj is not None and icon_font is not None and icon_font.sheet is not None:
            renderer.paste_glyph(icon_font.sheet, glyph_obj,
                              (origin_x + geometry.icon_x) * s,
                              (origin_y + geometry.icon_y) * s, icon_color)

        # `geometry.text_y` is the text's own line-box top, sized from the same
        # measurement as `resolve`'s box; the glyph source draws from there.
        source = renderer.glyph_source(text_font, placed.font.metric)
        if source is not None:
            source.draw(renderer, (origin_x + geometry.text_x) * s,
                        (origin_y + geometry.text_y) * s, text, color)

    def emit_draw(self, w: Writer, resolved: ResolvedFace, placed: PlacedComplicationSlot,
                  value_guards: list[str] | None, plan: ReadPlan,
                  aod: AodStyle = NO_AOD, *, ring: RingPass | None = None) -> None:
        complication_slot_mod.emit_complication_slot(w, resolved, placed, plan.device_guards, aod)

    def describe(self, placed: PlacedComplicationSlot) -> str:
        return f"a native Data-axis slot (config.data.{placed.element.slot})"

    def layout_constants(self, prefix: str,
                         placed: PlacedComplicationSlot) -> "layout_constants_mod.Constants":
        out: "layout_constants_mod.Constants" = [
            (f"{prefix}_CX", placed.anchor_point[0],
             "the icon+reading pair is centred here at runtime"),
            (f"{prefix}_CY", placed.anchor_point[1], ""),
        ]
        # The editor needs two boxes at build time -- `getComplicationDrawable`
        # hands the system a `Drawable` up front, before anything is pulled.
        # `onTap` hit-tests the same estimated `box` the safe-area/overlap
        # lints accept, so side-by-side slots stay separate targets; the
        # drawable gets `highlight`, wide enough for whatever the pick draws,
        # because the editor clips it to that box. Emitted for every slot
        # regardless of `on_hold:`: the editor can animate any slot.
        out.extend(layout_constants_mod.box_constants(
            f"{prefix}_BOX", placed.box, "the editor's tap target (estimated)"))
        out.extend(layout_constants_mod.box_constants(
            f"{prefix}_HIGHLIGHT", placed.highlight or placed.box,
            "the editor clips the slot's drawable to this box"))
        if placed.element.icon_gap is not None:
            # Only when the author wrote 'icon_gap:' -- otherwise the view keeps
            # the literal COMPLICATION_SLOT_ICON_GAP. Resolved per device ('%r'
            # is a different pixel count per screen).
            out.append((f"{prefix}_ICON_GAP", placed.icon_gap_px,
                        "icon_gap: resolved for this device"))
        return out


KIND = ComplicationSlotKind()
