"""A data element's (`data`'s) on-device config-editor plumbing;
its drawing is `wfb.kinds.data.DataKind.lower`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ... import complications
from ...availability import Guards
from ...ir import (
    Face, data_hold_method, data_icon_method, config_field,
    element_method_name,
)
from ...layout import PlacedData, ResolvedFace
from .common import EditorSlot, SourceFile, _NO_GUARDS, data_elements, header
from ..writer import Writer

if TYPE_CHECKING:
    from .readplan import ReadPlan


#: The view method holding `onLayout`'s font loading and first config read,
#: on a design with a `data` element, and the flag saying it has run.
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

    Read by every element drawing a slot (a data element's guard,
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


def _emit_data_editor_methods(w: Writer, resolved: ResolvedFace, plan: "ReadPlan",
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
        w.doc(f"Every element drawing slot `{slot.name}`, as the editor's drawable shows it.")
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
    `data`, handed to the native editor so it can animate
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
        "A generated stand-in for one `data` element's slot, handed to the editor so\n"
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


#: The generated module a `data` element's reading is formatted by.
SLOT_TEXT_MODULE = "SlotText"


def slot_reading_types(face: Face) -> list[str]:
    """Every `wfb.complications.TYPES` name a drawn `data` can
    show, across every slot: the ones `SlotText.reading` needs a case for.
    `choices: any` can show every type."""
    names: set[str] = set()
    for element in data_elements(face):
        slot = face.config_data.get(element.slot)
        if slot is None:
            continue
        names |= set(complications.TYPES) if slot.allow_any else set(slot.choices)
    return sorted(names)


def _worded_variants(face: Face, kind: str) -> set[bool]:
    """The `short:` values of the drawn slots that can show a `kind` reading
    -- which of its long and short name tables the program needs."""
    variants: set[bool] = set()
    for element in data_elements(face):
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
    """`source/SlotText.mc` -- a `data` element's reading as the text
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
        "A `data` element's reading as the text it draws: one rule per\n"
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


def _emit_data_hold_method(w: Writer, placed: PlacedData,
                                        guards: "Guards" = _NO_GUARDS) -> None:
    """`holdTargetFor<Id>()` -- the public getter `on_hold: auto` on a
    `data` compiles to, returning this slot's own current
    `Complications.Id` field directly.

    Public, unlike every draw method: the delegate is a different class and
    Monkey C's `private` genuinely blocks a cross-class call (verified by
    building both ways).  Only emitted for a slot that actually declares
    `on_hold: auto` -- `wfb.kinds.data.DataKind.build` restricts a slot to
    exactly that or nothing, so there is no fixed `wfb.complications.TYPES`
    name to resolve here the way a `Text`/`Gauge`/`IconElement`'s `auto`
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
    with w.block(f"function {data_hold_method(element.id)}() as {return_type}"):
        w.line(f"return {field};")


def _emit_data_icon_method(w: Writer, resolved: ResolvedFace,
                                        placed: PlacedData) -> None:
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
    method = data_icon_method(element.id)
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
