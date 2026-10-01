"""Element emitter for `complication_slot`, and its on-device config-editor plumbing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ... import complications
from ...availability import Guards
from ...ir import (
    ComplicationSlot, Face, complication_slot_hold_method, complication_slot_icon_method, config_data_ids,
    config_field, element_method_name,
)
from ...layout import COMPLICATION_SLOT_ICON_GAP, PlacedComplicationSlot, ResolvedFace
from .common import (
    NO_AOD, AodStyle, EditorSlot, SourceFile, _NO_GUARDS, complication_slots, const_prefix,
    font_field, header, mc_color,
)
from ..writer import Writer

if TYPE_CHECKING:
    from .readplan import ReadPlan


#: The view method holding `onLayout`'s font loading and first config read,
#: on a design with a `complication_slot`, and the flag saying it has run.
LOAD_RESOURCES_METHOD = "loadResources"
RESOURCES_LOADED_FIELD = "_resourcesLoaded"


def _emit_resources_loaded_field(w: Writer) -> None:
    """`_resourcesLoaded` -- whether `loadResources` has run.

    Entering the native editor's Data list starts the face afresh, and the
    editor asks for the preselected slot's drawable and draws it before the
    view's `onLayout` has run: seen on a fenix8solar47mm, the slot pulsed
    with no icon (its font field still null) and its text centred alone,
    until anything redrew the face.  `drawableFor` reads this flag and loads
    first.
    """
    w.doc(
        "Whether loadResources has run.  The native editor can ask for a slot's\n"
        "drawable, and draw it, before onLayout -- drawableFor loads first then."
    )
    w.line(f"private var {RESOURCES_LOADED_FIELD} as Boolean = false;")
    w.blank()


def _emit_pulsing_field(w: Writer) -> None:
    """`_pulsing` -- which slot the native editor is currently animating (a
    `config_data_ids` unique id), or 0 for none.

    Read by every element drawing a slot (`emit_complication_slot`'s guard,
    and a slot gauge's), set by `setPulsing` from the delegate's
    `getComplicationDrawable` and cleared by it from
    `onWatchFaceConfigEdited` -- both of which fire solely inside the
    on-device config editor (`docs/research/07-carousel-interaction.md`),
    so this stays 0 for the entire life of the app on a device with no
    editor, or while the face is simply being looked at -- and cleared again
    at the end of every `onUpdate`, so the skip covers one redraw
    (`_emit_on_update`).  `drawSlot` lifts it for its own call, so the
    editor's drawable still draws the slot the face itself skips.
    """
    w.doc(
        "Which slot the native editor is animating right now (a\n"
        "config_data_ids unique id), or 0 for none.  Read by every element\n"
        "drawing a slot so the system does not see it drawn twice while it\n"
        "pulses, and cleared after every onUpdate: the skip covers the one\n"
        "redraw that follows the editor's request for the drawable."
    )
    w.line("private var _pulsing as Number = 0;")
    w.blank()


def _emit_complication_slot_editor_methods(w: Writer, resolved: ResolvedFace, plan: "ReadPlan",
                                           slots: list[EditorSlot]) -> None:
    """`setPulsing`/`drawSlot`/`drawableFor`, and one `drawSlot<Name>` per
    slot -- the view's half of the native editor's animated highlight
    (`onTap`/`getComplicationDrawable` live on the delegate).  Only ever
    emitted when ``slots`` (`editor_slots`) is non-empty.

    `drawSlot` is the one new *public* surface the slot's elements need:
    Monkey C's `private` genuinely blocks a cross-class call (verified by
    building both ways -- dropping the modifier turns "Cannot find symbol
    ':drawTopReading'" into a clean build) -- so rather than making every
    per-element draw method public, one small dispatcher is, and the rest
    stay private like every other element's.

    A slot can be drawn by several elements (a gauge's ring and the reading),
    and the editor selects, highlights and redraws them as one: each slot's
    `drawSlot<Name>` calls every one of them, pulling first whatever readers
    their draw methods take (a colour that reads data), the same pulls
    `onUpdate` makes.

    `drawSlot` clears `_pulsing` around its own dispatch and restores it
    after: each element of the slot skips itself while it pulses so the face
    does not draw it under the editor's animation, and without the lift the
    editor's own drawable -- which reaches the same methods through here --
    would skip them too, leaving the slot drawn by nobody (seen on a
    fenix8solar47mm: the selected slot vanished and never previewed a
    choice).  The SDK sample does the same with `setVisible(false)` around
    `View.onUpdate` and `setVisible(true)` after it.
    """
    face = resolved.face
    placed_by_id = {placed.id: placed for placed in resolved.items}
    w.doc(
        "The native editor is telling this view which slot it is about to "
        "animate,\nor, with 0, that none is being animated any more.\n\n"
        "Only ever called from getComplicationDrawable and "
        "onWatchFaceConfigEdited,\nwhich fire solely inside the on-device "
        "config editor (research 07 1a)."
    )
    with w.block("function setPulsing(unique as Number) as Void"):
        w.line("_pulsing = unique;")
    w.blank()

    for slot in slots:
        members = [placed_by_id[element.id] for element in slot.elements
                   if element.id in placed_by_id]
        w.doc(f"Every element drawing config.data.{slot.name}, as the editor's drawable shows it.")
        with w.block(f"private function {slot.draw_method}(dc as Dc) as Void"):
            readers: list[str] = []
            for placed in members:
                readers += [name for name in plan.readers_of(placed) if name not in readers]
            plan.emit_pulls(w, readers)
            for placed in members:
                w.line(f"{element_method_name(placed.id)}(dc{plan.arguments(placed)});")
        w.blank()

    w.doc(
        "Draw one slot by its config_data_ids unique id -- the one public entry\n"
        "point the generated SlotDrawable needs, so every element's own draw\n"
        "method can stay private.\n\n"
        "The editor is drawing the slot it animates, so each element's own\n"
        "_pulsing skip is lifted for this call: the face skips that slot so it is\n"
        "not drawn under the animation, and this is what draws it instead."
    )
    with w.block("function drawSlot(dc as Dc, unique as Number) as Void"):
        w.line("var pulsing = _pulsing;")
        w.line("_pulsing = 0;")
        with w.block("switch (unique)"):
            for slot in slots:
                w.line(f"case {slot.unique}: {slot.draw_method}(dc); break;")
        w.line("_pulsing = pulsing;")
    w.blank()

    w.doc(
        "Build the Drawable the editor animates for one slot, on that slot's "
        "own\nhighlight box: every element drawing it, and for a reading, every "
        "screen\ncolumn it could reach -- the editor clips the drawable to this "
        "box, and\nwhat the pick draws (label, value, unit, icon) is not known "
        "until the\ndevice pulls it."
    )
    with w.block(
        "function drawableFor(unique as Number) as WatchUi.ComplicationDrawableRef or Null",
    ):
        w.comment("the editor can get here before onLayout: fonts and the wearer's")
        w.comment("config first, or the slot draws without its icon")
        with w.block(f"if (!{RESOURCES_LOADED_FIELD})"):
            w.line(f"{LOAD_RESOURCES_METHOD}();")
        w.line("var drawable = null;")
        with w.block("switch (unique)"):
            for slot in slots:
                box = f"Layout.{slot.const_prefix}_HIGHLIGHT"
                w.line(f"case {slot.unique}: drawable = new {face.entry}SlotDrawable(self, {slot.unique},")
                w.line(f"    {box}_X, {box}_Y,")
                w.line(f"    {box}_WIDTH, {box}_HEIGHT); break;")
        with w.block("if (drawable == null)"):
            w.line("return null;")
        w.line("return new WatchUi.ComplicationDrawableRef(")
        w.line("    { :drawable => drawable, :boundingBox => drawable.boundingBox() });")
    w.blank()


def emit_slot_drawable(face: Face) -> SourceFile:
    """`source/<Face>SlotDrawable.mc` -- the generated stand-in for one
    `complication_slot`, handed to the native editor so it can animate
    ("pulse") the slot the wearer is about to change.

    Delegates straight back to the view's own `drawSlot`, so there is exactly
    one implementation of what a slot looks like -- this class exists only
    because `getComplicationDrawable` needs *something* satisfying
    `WatchUi.Drawable` to hand back, not because the drawing lives here.
    Only ever generated, and only ever constructed, when the design has at
    least one element drawing a slot (`editor_slots`): the whole
    file is dead weight on a passive face, since `getComplicationDrawable`
    itself never fires there (`docs/research/07-carousel-interaction.md`).

    Shape verified against `docs/research/probes/config-axes/SlotDrawable.mc`,
    which built warning-free under `-l 3` on all three targets, including
    `fr955`.
    """
    w = Writer()
    w.doc(header(face)).blank()
    w.lines("import Toybox.Graphics;", "import Toybox.Lang;", "import Toybox.WatchUi;").blank()
    w.doc(
        "A generated stand-in for one complication_slot, handed to the editor so\n"
        "it can animate (\"pulse\") the slot the wearer is about to change.  It\n"
        "delegates straight back to the view's own drawSlot, so there is exactly\n"
        "one implementation of what a slot looks like.\n"
        "\n"
        "Seen on a fenix8solar47mm: the editor animates it over the slot.  A "
        "watch\nwith no editor never constructs one."
    )
    with w.block(f"class {face.entry}SlotDrawable extends WatchUi.Drawable"):
        w.line(f"private var _view as {face.entry}View;")
        w.line("private var _unique as Number;")
        w.blank()
        with w.block(
            f"function initialize(view as {face.entry}View, unique as Number,\n"
            "                    x as Number, y as Number, w as Number, h as Number)",
        ):
            w.line("Drawable.initialize({ :locX => x, :locY => y, :width => w, :height => h });")
            w.line("_view = view;")
            w.line("_unique = unique;")
        w.blank()
        with w.block("function boundingBox() as Graphics.BoundingBox"):
            w.line("var box = new Graphics.BoundingBox();")
            w.line("box.addRectangle(locX.toNumber(), locY.toNumber(), "
                   "width.toNumber(), height.toNumber());")
            w.line("return box;")
        w.blank()
        with w.block("function draw(dc as Dc) as Void"):
            with w.block("if (!isVisible)"):
                w.line("return;")
            w.line("_view.drawSlot(dc, _unique);")
    return SourceFile(f"source/{face.entry}SlotDrawable.mc", w.render())


#: The generated module a `complication_slot`'s reading is formatted by.
SLOT_TEXT_MODULE = "SlotText"


def slot_reading_types(face: Face) -> list[str]:
    """Every `wfb.complications.TYPES` name a drawn `complication_slot` can
    show, across every slot: the ones `SlotText.reading` needs a case for.
    `choices: any` can show every type."""
    names: set[str] = set()
    for element in complication_slots(face):
        slot = face.config_data.get(element.slot)
        if slot is None:
            continue
        names |= set(complications.TYPES) if slot.allow_any else set(slot.choices)
    return sorted(names)


def _worded_variants(face: Face, kind: str) -> set[bool]:
    """The `short:` values of the drawn slots that can show a `kind` reading
    -- which of its long and short name tables the program needs."""
    variants: set[bool] = set()
    for element in complication_slots(face):
        slot = face.config_data.get(element.slot)
        if slot is None:
            continue
        shown = complications.TYPES if slot.allow_any else slot.choices
        if any(complications.READING[name] == kind for name in shown):
            variants.add(element.short)
    return variants


#: `SlotText.reading`'s return expression for each numeric reading kind,
#: over the narrowed `value`, the pulled `c`, the element's `unit`/`short`
#: and, where the kind follows it, the device's `settings`.
_NUMERIC_READING: dict[str, str] = {
    "percent": "WfbReading.percent(value, unit)",
    "vo2max": "(value.toNumber() == 0) ? null : WfbReading.count(value, c.unit)",
    "clock": "WfbReading.clock(value, settings.is24Hour)",
    "duration": "WfbReading.duration(value)",
    "hours": "WfbReading.hours(value)",
    "temperature": ("WfbReading.temperature(value, "
                    "settings.temperatureUnits == System.UNIT_STATUTE, unit)"),
    "elevation": ("WfbReading.elevation(value, "
                  "settings.elevationUnits == System.UNIT_STATUTE, unit, short)"),
    "distance": ("WfbReading.distance(value, "
                 "settings.distanceUnits == System.UNIT_STATUTE, unit, short)"),
    "pressure": "WfbReading.pressure(value, unit, short)",
    "pace": ("WfbReading.pace(value, "
             "settings.paceUnits == System.UNIT_STATUTE, unit, short)"),
}

#: The numeric kinds whose rule reads `System.getDeviceSettings()`.
_READS_SETTINGS = frozenset({"clock", "temperature", "elevation", "distance", "pace"})


def _variant_expression(variants: set[bool], short: str, full: str) -> str:
    """The expression for a reading with a short and a full form, given the
    `short:` values the slots showing it use."""
    if variants == {True}:
        return short
    if variants == {False}:
        return full
    return f"short ? {short} : {full}"


#: What pads a packed name table's entries to one width
#: (`WfbReading.packed`); no name contains it.
_PACK_FILL = "|"


def _packed_names(short: bool) -> tuple[str, int]:
    """Every `Weather.CONDITION_*` name, in value order, padded to one
    width and joined: one string literal instead of a 54-way `switch`,
    measured 1,246 B smaller for the short names on a fenix8solar47mm."""
    names = [complications.WEATHER_CONDITION_TEXT[value][1 if short else 0]
             for value in sorted(complications.WEATHER_CONDITION_TEXT)]
    assert sorted(complications.WEATHER_CONDITION_TEXT)[-1] == complications.UNKNOWN_CONDITION
    width = max(len(name) for name in names)
    assert all(_PACK_FILL not in name for name in names)
    return "".join(name.ljust(width, _PACK_FILL) for name in names), width


def _emit_condition_table(w: Writer, method: str, short: bool) -> None:
    packed, width = _packed_names(short)
    with w.block(f"function {method}(condition as Number) as String"):
        w.line(f'return WfbReading.packed("{packed}",')
        w.line(f"        {width}, condition);")
    w.blank()


def emit_slot_text(face: Face) -> SourceFile:
    """`source/SlotText.mc` -- a `complication_slot`'s reading as the text
    it draws, one rule per complication type (`wfb.complications.READING`).

    Generated, rather than a barrel file, so a program carries a case only
    for the types its slots can show, and the weather and training-status
    name tables only in the variants (`short:` or not) a slot draws.  The
    arithmetic lives in `runtime-lib/WfbReading.mc`.  A type with no case (an
    app's complication, under `choices: any`) falls back to the value as
    reported, with `Complication.unit`'s suffix under `unit:`.
    """
    names = slot_reading_types(face)
    kinds = {name: complications.READING[name] for name in names}
    constant = {name: f"Complications.{complications.TYPES[name].constant}" for name in names}
    training = _worded_variants(face, "training_status")
    conditions = _worded_variants(face, "condition")

    w = Writer()
    w.doc(header(face)).blank()
    w.lines("import Toybox.Complications;", "import Toybox.Lang;", "import Toybox.System;").blank()
    w.doc(
        "A complication_slot's reading as the text it draws: one rule per\n"
        "complication type, generated from wfb.complications.READING."
    )
    with w.block(f"module {SLOT_TEXT_MODULE}"):
        w.doc(
            "The pulled complication `c`, of type `t`, as display text, or null when\n"
            "it has no reading.  `unit` and `short` are the element's own keys."
        )
        with w.block("function reading(t as Complications.Type, c as Complications.Complication,\n"
                     "                     unit as Boolean, short as Boolean) as String?"):
            w.line("var value = c.value;")
            with w.block("if (value == null)"):
                w.line("return null;")
            with w.block("if (value instanceof Lang.String)"):
                # only a slot drawn `short:` changes the device's own text
                string_cases: dict[str, str] = {}
                for name in names:
                    shortened = {"training_status": "trainingShort(value)",
                                 "high_low": "WfbReading.highLowShort(value)"}.get(kinds[name])
                    variants = _worded_variants(face, kinds[name])
                    if shortened is not None and True in variants:
                        string_cases[name] = _variant_expression(variants, shortened, "value")
                if string_cases:
                    with w.block("switch (t)"):
                        for name, expression in string_cases.items():
                            w.line(f"case {constant[name]}: return {expression};")
                w.line("return value;")
            if any(kinds[n] in _READS_SETTINGS for n in names):
                w.line("var settings = System.getDeviceSettings();")
            numeric = [n for n in names if kinds[n] not in complications.WORDED - {"condition"}]
            if numeric:
                groups: dict[str, list[str]] = {}
                for name in numeric:
                    kind = kinds[name]
                    if kind == "count":
                        suffix = complications.COUNT_UNIT.get(name, "")
                        expression = ("WfbReading.count(value, c.unit)" if not suffix else
                                      f'WfbReading.suffixed(WfbReading.count(value, c.unit), '
                                      f'unit ? "{suffix}" : "", short)')
                    elif kind == "condition":
                        expression = _variant_expression(
                            conditions, "conditionShort(value.toNumber())",
                            "conditionName(value.toNumber())")
                    else:
                        expression = _NUMERIC_READING[kind]
                    groups.setdefault(expression, []).append(name)
                with w.block("switch (t)"):
                    for expression, members in groups.items():
                        for name in members[:-1]:
                            w.line(f"case {constant[name]}:")
                        w.line(f"case {constant[members[-1]]}: return {expression};")
            w.comment("no rule of its own: an app's complication, under choices: any")
            w.line("return WfbReading.suffixed(WfbReading.formatValue(value),")
            w.line('        unit ? WfbReading.unitSuffix(c.unit) : "", short);')
        w.blank()
        if True in conditions:
            _emit_condition_table(w, "conditionShort", short=True)
        if False in conditions:
            _emit_condition_table(w, "conditionName", short=False)
        if True in training:
            w.doc("A training status's short form, in the case the device reported it.")
            with w.block("function trainingShort(status as String) as String"):
                with w.block("switch (status.toUpper())"):
                    for status, short in complications.TRAINING_STATUS_SHORT.items():
                        w.line(f'case "{status}": return WfbReading.inCaseOf("{short}", status);')
                    w.line("default: return status;")
    return SourceFile(f"source/{SLOT_TEXT_MODULE}.mc", w.render())


def _emit_complication_slot_hold_method(w: Writer, placed: PlacedComplicationSlot,
                                        guards: "Guards" = _NO_GUARDS) -> None:
    """`holdTargetFor<Id>()` -- the public getter `on_hold: auto` on a
    `complication_slot` compiles to, returning this slot's own current
    `Complications.Id` field directly.

    Public, unlike every draw method: the delegate is a different class and
    Monkey C's `private` genuinely blocks a cross-class call (verified by
    building both ways).  Only emitted for a slot that actually declares
    `on_hold: auto` -- `wfb.kinds.complication_slot.ComplicationSlotKind.build` restricts a slot to
    exactly that or nothing, so there is no fixed `wfb.complications.TYPES`
    name to resolve here the way a `Text`/`Progress`/`IconElement`'s `auto`
    resolves one; the delegate reads this id and hands it straight to
    `Complications.exitTo`.

    Returns `Complications.Id?`, not `Complications.Id`, exactly when
    `guards.complications` -- the field itself is nullable there (see
    `_emit_config_fields`), staying `null` on a device lacking
    `Toybox.Complications`; the delegate's own call site (`emit_delegate`)
    treats a `null` return as "this hold does nothing here", the ordinary
    absence contract, rather than needing a second guard of its own.
    """
    element = placed.element
    field = config_field(f"data_{element.slot}")
    return_type = "Complications.Id?" if guards.complications else "Complications.Id"
    w.blank()
    w.doc(f"`{element.id}`'s current pick, for the delegate's 'on_hold: auto' ->\n"
          "Complications.exitTo.  Whatever the wearer has this slot pointed at right\n"
          "now, read fresh -- never a fixed type baked in at build time.")
    with w.block(f"function {complication_slot_hold_method(element.id)}() as {return_type}"):
        w.line(f"return {field};")


def _emit_complication_slot_icon_method(w: Writer, resolved: ResolvedFace,
                                        placed: PlacedComplicationSlot) -> None:
    """`iconFor<Id>(t)` -- one slot's `Complications.Type` -> catalogue name
    (via `IconGlyphs.glyph`) -> drawn glyph lookup.

    A generated method rather than an inline mutable local: Monkey C locals
    cannot be given an explicit `as String?` type ("Invalid explicit typing
    of a local variable", from a real build), so there is no way to declare
    one that starts `null` and is later assigned a `String`.  Returning
    through a function whose own signature declares `String?` sidesteps that
    -- the call site's local infers its type from the call expression
    instead.  Verified buildable under `-l 3`
    (docs/research/probes/config-axes/ProbeView.mc's `iconFor`).
    """
    element = placed.element
    face = resolved.face
    slot = face.config_data[element.slot]
    mapped = slot.icons
    # `slot.choices` is an ordered tuple for an explicit list, but the
    # literal string "any" for 'choices: any' (allowed together with
    # `icon_size:`) -- iterating that would walk its three characters, not a
    # type list, so the switch's case order falls back to a stable
    # alphabetical one there instead, over every mapped type.
    names = slot.choices if not slot.allow_any else sorted(mapped)
    follows = slot.condition_icons
    w.blank()
    w.doc(f"`{element.id}`'s icon, chosen from the wearer's picked type -- not from\n"
          "the reading, so it still shows on a frame the reading could not be pulled.\n"
          "A weather type's icon follows the pulled condition when there is one.")
    method = complication_slot_icon_method(element.id)
    with w.block(f"private function {method}(t as Complications.Type,\n"
                 "            pulled as Complications.Complication?) as String?"):
        if follows:
            w.line("var value = (pulled != null) ? pulled.value : null;")
        with w.block("switch (t)"):
            for name in names:
                icon = mapped.get(name)
                if icon is None:
                    continue
                ctype = complications.TYPES[name]
                if name in follows:
                    w.line(f"case Complications.{ctype.constant}: return (value instanceof Lang.Number)"
                           f' ? WfbWeather.chooseIcon(value) : "{icon.key}";')
                else:
                    w.line(f'case Complications.{ctype.constant}: return "{icon.key}";')
            w.line("default: return null;")
    w.blank()


def emit_complication_slot(w: Writer, resolved: ResolvedFace, placed: PlacedComplicationSlot,
                           guards: "Guards" = _NO_GUARDS, aod: AodStyle = NO_AOD) -> None:
    """A native Data-axis slot: pull the wearer's chosen complication, choose
    an icon from its *type* alone, then draw the two as one centred pair.

    Everything here is a plain per-frame pull (`WfbComplications.valueOf`),
    exactly like an ordinary `complication.<name>` catalogue source -- the
    compiled field just holds a `Complications.Id` the *wearer* can repoint,
    instead of a build-time-fixed one (CLAUDE.md: "complications are pulled
    not cached", docs/research/probes/complication-pull/).

    The icon is chosen from `chosenId.getType()`, not from the pulled value,
    so it still shows even on a frame the reading itself could not be pulled
    -- verified buildable under `-l 3`
    (docs/research/probes/config-axes/ProbeView.mc's `iconFor`).  The icon
    and the reading are placed on this element's own anchor as one pair, via
    `Dc.getTextWidthInPixels` -- the actual text is not known until the value
    is pulled, so unlike every other element this cannot be precomputed at
    build time (ADR 0004's one deliberate exception, and for exactly that
    reason).  `align`/`vertical_align` move that pair off the anchor with
    the same per-`icon_position:` arithmetic this exception needs --
    `center`/`center` is the fast path below, the same plain expression
    used when neither key is authored.

    Every `complication_slot` -- not only ones with `on_hold:` -- starts with
    a `_pulsing` guard: the native editor can animate *any* slot's highlight
    (`getComplicationDrawable`), and the SDK sample's own comment on this
    exact hazard is what makes skipping the normal draw mandatory while that
    happens -- "This prevents the complication from being drawn on the watch
    face while it is pulsing."  A design with `complication_slot` elements
    always has at least one, so this function running at all is exactly the
    condition under which the guard applies -- see `_emit_pulsing_field`.

    When `guards.complications`, `chosenId` (the slot's own field) is
    `Complications.Id?`, not `Complications.Id` -- see
    `_emit_config_fields`/`_emit_initialize` -- so both places that
    dereference it (`chosenId.getType()` for the icon, `chosenId` itself as
    `WfbComplications.valueOf`'s non-nullable parameter) go through a
    ternary null guard instead of a bare reference. A `null` chosenId reads
    exactly like an unsupported complication *type* already does: the icon
    lookup and the pulled value both come back `null`, so `_emit_absent()`
    below already covers it -- there is nothing complication-module-specific
    for this function's drawing logic to know about.
    """
    element = placed.element
    prefix = const_prefix(placed.id)
    face = resolved.face
    field = config_field(f"data_{element.slot}")
    unique = config_data_ids(face)[element.slot]

    w.comment("the editor is animating this exact slot right now -- skip it, or the")
    w.comment("system draws it twice while it pulses (SDK sample's own comment);")
    w.comment("drawSlot lifts this for the editor's own drawable")
    with w.block(f"if (_pulsing == {unique})"):
        w.line("return;")
    w.blank()
    w.comment(f"slot: config.data.{element.slot}")
    w.line(f"var chosenId = {field};")
    if guards.complications:
        w.line("var pulled = (chosenId != null) ? WfbComplications.valueOf(chosenId) : null;")
    else:
        w.line("var pulled = WfbComplications.valueOf(chosenId);")

    icon_font_expr = None
    if placed.icon_font_key is not None:
        w.line(f"var iconFont = _{font_field(placed.icon_font_key)};")
        w.comment("the icon is chosen from the wearer's picked *type*, so it still shows")
        w.comment("even on a frame the reading itself could not be pulled -- a name,")
        w.comment("then IconGlyphs.glyph turns it into the actual character")
        icon_method = complication_slot_icon_method(element.id)
        if guards.complications:
            w.line(f"var iconName = (chosenId != null) ? {icon_method}(chosenId.getType(), pulled) : null;")
        else:
            w.line(f"var iconName = {icon_method}(chosenId.getType(), pulled);")
        w.line("var iconGlyph = (iconName != null) ? IconGlyphs.glyph(iconName) : null;")
        w.blank()
        icon_font_expr = "iconFont"

    if placed.font.is_custom:
        w.line(f"var textFont = _{font_field(placed.font.reference)};")
        with w.block("if (textFont == null)"):
            w.line("return;  // the font resource failed to load")
        font_expr = "textFont"
    else:
        font_expr = f"Graphics.{placed.font.reference}"
    w.blank()

    def _emit_absent() -> None:
        if element.when_absent == "placeholder":
            w.comment("when_absent: placeholder")
            w.line(f'text = "{element.placeholder}";')
        else:
            w.comment("when_absent: hide -- the reading blanks, the icon (if any) stays")

    w.line('var text = "";')
    unit = "true" if element.unit else "false"
    short = "true" if element.short else "false"
    with w.block("if (pulled == null || chosenId == null)" if guards.complications
                 else "if (pulled == null)"):
        _emit_absent()
    with w.block("else"):
        w.line(f"var reading = {SLOT_TEXT_MODULE}.reading(chosenId.getType(), pulled, {unit}, {short});")
        with w.block("if (reading == null)"):
            _emit_absent()
        with w.block("else"):
            if element.label in ("short", "long"):
                attr = "shortLabel" if element.label == "short" else "longLabel"
                w.line(f"var label = pulled.{attr};")
                with w.block("if (label != null)"):
                    w.line('text = label + " ";')
            w.line("text += reading;")
    w.blank()

    text_color_expr = aod.color(element, "color")
    # `None` when the icon simply draws in the text's colour, `dc`'s state
    # already: no `icon_color:` and no `aod: {icon_color: ...}` either. An
    # `aod:` override with no awake `icon_color:` keeps the text's colour
    # while awake; `dim` (applied inside `aod.color`) reaches an authored
    # `icon_color:` but never the text colour a second time.
    has_icon_override = (aod.on and element.aod is not None
                         and element.aod.icon_color is not None)
    if element.icon_color is None and not has_icon_override:
        icon_color_expr = None
    else:
        awake_icon_expr = (mc_color(element.icon_color) if element.icon_color is not None
                           else text_color_expr)
        icon_color_expr = aod.color(element, "icon_color", awake_icon_expr)
    fast_path = (
        placed.icon_position == "left"
        and element.icon_gap is None
        and icon_color_expr is None
        and element.align == "center"
        and element.vertical_align == "center"
    )

    if fast_path:
        # The plain case: none of 'icon_position:'/'icon_gap:'/'icon_color:'/
        # 'align:'/'vertical_align:' is authored away from its default, so
        # this is exactly the expression those keys produce when unused. Any
        # one of them authored (even 'left' with a non-default 'align:'/
        # 'vertical_align:') falls through to the general path below.
        w.line(f"dc.setColor({text_color_expr}, Graphics.COLOR_TRANSPARENT);")
        w.line(f"var textWidth = dc.getTextWidthInPixels(text, {font_expr});")
        w.line("var iconWidth = 0;")
        if icon_font_expr is not None:
            with w.block(f"if (iconGlyph != null && {icon_font_expr} != null)"):
                w.line(
                    f"iconWidth = dc.getTextWidthInPixels(iconGlyph, {icon_font_expr}) + "
                    f"{COMPLICATION_SLOT_ICON_GAP};"
                )
        w.line("var totalWidth = iconWidth + textWidth;")
        w.line(f"var startX = Layout.{prefix}_CX - totalWidth / 2;")
        if icon_font_expr is not None:
            with w.block(f"if (iconGlyph != null && {icon_font_expr} != null)"):
                w.line(f"dc.drawText(startX, Layout.{prefix}_CY, {icon_font_expr}, iconGlyph,")
                w.line("            Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER);")
        w.line(f"dc.drawText(startX + iconWidth, Layout.{prefix}_CY, {font_expr}, text,")
        w.line("            Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER);")
        return

    # General path: any position other than the default 'left', an authored
    # 'icon_gap:'/'icon_color:' on 'left' itself, or a non-default 'align:'/
    # 'vertical_align:' -- the pair's alignment arithmetic is runtime-only,
    # mirroring `wfb.layout.alignment_shift`'s rule but never calling it,
    # since neither the real text nor (for icon_position top/bottom, align
    # != center) the real icon glyph width is known until the value above is
    # pulled (ADR 0004's one deliberate exception) -- everything below goes
    # through `Dc.getTextWidthInPixels`/`Dc.getFontHeight` instead of a
    # build-time measurement.  Every offset below is computed once, at build
    # time in Python, from `element.align`/`.vertical_align` alone (never a
    # runtime branch): center reproduces the same expression the fast path
    # above emits.
    gap_expr = (f"Layout.{prefix}_ICON_GAP" if element.icon_gap is not None
               else str(COMPLICATION_SLOT_ICON_GAP))
    icon_present_guard = (f"iconGlyph != null && {icon_font_expr} != null"
                         if icon_font_expr is not None else None)
    # Whether this slot can ever draw an icon at all (a resolvable
    # `icon_size:`) -- not merely whether the *wearer's current pick* has one
    # (that is `icon_present_guard`, a runtime condition). When this is
    # `False`, every codegen branch below that only reads a width/height/gap
    # from inside an `if (icon_present_guard)` block must not declare that
    # local at all, or it warns as unused under -l 3 (the whole block is
    # never emitted, not merely runtime-skipped).
    has_icon = icon_present_guard is not None
    w.line(f"dc.setColor({text_color_expr}, Graphics.COLOR_TRANSPARENT);")

    def _set_icon_color() -> None:
        if icon_color_expr is not None:
            w.line(f"dc.setColor({icon_color_expr}, Graphics.COLOR_TRANSPARENT);")

    def _reset_text_color() -> None:
        if icon_color_expr is not None and icon_font_expr is not None:
            w.line(f"dc.setColor({text_color_expr}, Graphics.COLOR_TRANSPARENT);")

    # One axis table for both layouts: the pair lies along a row
    # (`icon_position: left`/`right`) or a column (`top`/`bottom`). Along it,
    # the `lead` position draws the icon first; `main_align` (`align:` for a
    # row, `vertical_align:` for a column) shifts where the pair starts.
    # Across it, the other alignment key shifts the shared axis the pieces
    # are drawn on.
    row = placed.icon_position in ("left", "right")
    if row:
        lead, trail, main_align, cross_align = "left", "right", element.align, element.vertical_align
        size, icon_local, start, center = "Width", "iconGlyphWidth", "startX", f"Layout.{prefix}_CX"
        text_size = f"dc.getTextWidthInPixels(text, {font_expr})"
        icon_size = f"dc.getTextWidthInPixels(iconGlyph, {icon_font_expr})"
        justify = "Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER"
    else:
        lead, trail, main_align, cross_align = "top", "bottom", element.vertical_align, element.align
        size, icon_local, start, center = "Height", "iconHeight", "startY", f"Layout.{prefix}_CY"
        text_size = f"dc.getFontHeight({font_expr})"
        icon_size = f"dc.getFontHeight({icon_font_expr})"
        justify = "Graphics.TEXT_JUSTIFY_CENTER"
    text_local, total = f"text{size}", f"total{size}"
    position = placed.icon_position

    # Each local is declared only when something reads it afterwards -- an
    # unused local warns under -l 3. The `lead` position's final offset
    # always reads the icon's size and the gap; the `trail` position's reads
    # the text's size and the gap only inside `if (icon_present_guard)`,
    # which is never emitted when this slot can draw no icon (`has_icon`
    # false); `total` needs all three unless `main_align` is `lead`. Checked
    # exhaustively in `tests/test_align_glyph_kinds.py` (every
    # `icon_position:` x every `align:`/`vertical_align:` x
    # icon-present/icon-less).
    if (position == trail and has_icon) or main_align != lead:
        w.line(f"var {text_local} = {text_size};")
    if position == lead or main_align != lead:
        w.line(f"var {icon_local} = 0;")
        if icon_present_guard is not None:
            with w.block(f"if ({icon_present_guard})"):
                w.line(f"{icon_local} = {icon_size};")
    if position == lead or (position == trail and has_icon) or main_align != lead:
        w.line(f"var gap = ({icon_present_guard}) ? {gap_expr} : 0;"
               if icon_present_guard is not None else "var gap = 0;")
    # `main_align` sets the start: `center - {0, total/2, total}` for
    # lead/center/trail.
    if main_align == lead:
        w.line(f"var {start} = {center};")
    elif main_align == trail:
        w.line(f"var {total} = {icon_local} + gap + {text_local};")
        w.line(f"var {start} = {center} - {total};")
    else:
        w.line(f"var {total} = {icon_local} + gap + {text_local};")
        w.line(f"var {start} = {center} - {total} / 2;")

    # `cross_align` shifts the shared axis by half the larger of the two
    # pieces across the pair, measured on-device, since only one of them may
    # draw at all (an icon-less slot, or a frame whose icon did not resolve).
    if row:
        if cross_align == "center":
            cross_expr = f"Layout.{prefix}_CY"
        else:
            w.line(f"var rowHeight = dc.getFontHeight({font_expr});")
            if icon_present_guard is not None:
                with w.block(f"if ({icon_present_guard})"):
                    w.line(f"var iconRowHeight = dc.getFontHeight({icon_font_expr});")
                    with w.block("if (iconRowHeight > rowHeight)"):
                        w.line("rowHeight = iconRowHeight;")
            sign = "+" if cross_align == "top" else "-"
            w.line(f"var rowY = Layout.{prefix}_CY {sign} rowHeight / 2;")
            cross_expr = "rowY"
    else:
        if cross_align == "center":
            cross_expr = f"Layout.{prefix}_CX"
        else:
            w.line(f"var textWidth = dc.getTextWidthInPixels(text, {font_expr});")
            w.line("var iconGlyphWidth = 0;")
            if icon_present_guard is not None:
                with w.block(f"if ({icon_present_guard})"):
                    w.line(f"iconGlyphWidth = dc.getTextWidthInPixels(iconGlyph, {icon_font_expr});")
            w.line("var pairWidth = (iconGlyphWidth > textWidth) ? iconGlyphWidth : textWidth;")
            sign = "+" if cross_align == "left" else "-"
            w.line(f"var pairX = Layout.{prefix}_CX {sign} pairWidth / 2;")
            cross_expr = "pairX"

    def _at(offset: str) -> str:
        """`x, y` for a piece `offset` along the pair from its start."""
        along = f"{start}{offset}"
        return f"{along}, {cross_expr}" if row else f"{cross_expr}, {along}"

    if position == lead:
        if icon_present_guard is not None:
            with w.block(f"if ({icon_present_guard})"):
                _set_icon_color()
                w.line(f"dc.drawText({_at('')}, {icon_font_expr}, iconGlyph,")
                w.line(f"            {justify});")
        _reset_text_color()
        w.line(f"dc.drawText({_at(f' + {icon_local} + gap')}, {font_expr}, text,")
        w.line(f"            {justify});")
    else:
        w.line(f"dc.drawText({_at('')}, {font_expr}, text,")
        w.line(f"            {justify});")
        if icon_present_guard is not None:
            with w.block(f"if ({icon_present_guard})"):
                _set_icon_color()
                w.line(f"dc.drawText({_at(f' + {text_local} + gap')}, "
                       f"{icon_font_expr}, iconGlyph,")
                w.line(f"            {justify});")
