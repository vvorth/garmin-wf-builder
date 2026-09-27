"""`<Face>App.mc`, `Palette.mc` and `IconGlyphs.mc` -- the shared, device-independent sources."""

from __future__ import annotations

from ... import icons, kinds
from ...ir import Face
from .common import SourceFile, _editor_slot_pairs, header, needs_delegate
from ..writer import Writer


def emit_app(face: Face) -> SourceFile:
    """`source/<Face>App.mc` -- the application entry point.

    `onStart`/`_editMode` are only emitted when the design has at least one
    `complication_slot` (`_editor_slot_pairs`): detecting edit mode is
    otherwise pointless, since nothing else reads it.  Exactly the SDK
    sample's own `ConfigurationWatchFaceApp.onStart`, reading
    `state[:launchedFromWatchFaceSettingsEditor]` -- **not** a level compare
    or a `has` guard, because `onStart`'s own `state` dictionary is the only
    place this flag is ever delivered.

    A design with `settings:` keeps the view in `_view`, so
    `onSettingsChanged` (a Garmin Connect push, constraint 12) can re-read
    the settings into it.
    """
    needs_it = needs_delegate(face)
    has_settings = bool(face.settings)
    has_slots = bool(_editor_slot_pairs(face))
    w = Writer()
    w.doc(header(face)).blank()
    w.lines("import Toybox.Application;", "import Toybox.Lang;", "import Toybox.WatchUi;").blank()
    w.doc(f"The application entry point for {face.name!r}.")
    with w.block(f"class {face.entry}App extends Application.AppBase"):
        if has_slots:
            w.doc(
                "Whether the watch face was started by the native config editor.\n"
                "\n"
                "Read exactly once, by getInitialView just below -- which is what "
                "keeps\nthis from being a written-but-never-read field (verified: "
                "that warns\n\"Member variable '_editMode' is not used.\"; a value "
                "read back by a\nconstructor call, even one the view itself then "
                "discards, does not)."
            )
            w.line("private var _editMode as Boolean = false;")
            w.blank()
        if has_settings:
            w.doc("The view, kept so onSettingsChanged can re-read the settings into it.")
            w.line(f"private var _view as {face.entry}View?;")
            w.blank()
        with w.block("function initialize()"):
            w.line("AppBase.initialize();")
        w.blank()
        if has_slots:
            w.doc(
                "Detect edit mode before the initial view is retrieved -- the SDK's "
                "own\nConfigurationWatchFaceApp.onStart, verbatim."
            )
            with w.block("function onStart(state as Dictionary?) as Void"):
                with w.block("if (state != null)"):
                    w.line("var editing = state[:launchedFromWatchFaceSettingsEditor] as Boolean?;")
                    with w.block("if (editing != null && editing)"):
                        w.line("_editMode = true;")
            w.blank()
        with w.block("function getInitialView() as [Views] or [Views, InputDelegates]"):
            view_ctor = f"new {face.entry}View(_editMode)" if has_slots else f"new {face.entry}View()"
            if not needs_it and not has_settings:
                w.line(f"return [ {view_ctor} ];")
            elif not needs_it:
                w.line(f"var view = {view_ctor};")
                w.line("_view = view;")
                w.line("return [ view ];")
            else:
                w.line(f"var view = {view_ctor};")
                if has_settings:
                    w.line("_view = view;")
                w.comment("the `has` guard is the SDK's own idiom (samples/Analog): a watch")
                w.comment("without WatchFaceDelegate still gets the face, just not the holds")
                w.comment("(or, for a `config:` design, the re-read on a settings edit)")
                with w.block("if (WatchUi has :WatchFaceDelegate)"):
                    w.comment("the delegate holds the view so a config edit can update it")
                    w.line(f"return [ view, new {face.entry}Delegate(view) ];")
                w.line("return [ view ];")
        if has_settings:
            w.blank()
            w.doc(
                "A setting changed: re-read every setting into the view and redraw.\n"
                "\n"
                "The system calls this only for a Garmin Connect push (CLAUDE.md\n"
                "constraint 12)."
            )
            with w.block("function onSettingsChanged() as Void"):
                w.line("var view = _view;")
                with w.block("if (view != null)"):
                    w.line("view.applySettings();")
                w.line("WatchUi.requestUpdate();")
        if face.settings_menu:
            w.blank()
            w.doc(
                "The settings menu, opened from the watch's Watch Face menu.  A device\n"
                "without getSettingsView (fenix5) never calls this, and keeps every\n"
                "setting's default."
            )
            with w.block("function getSettingsView() as [Views] or [Views, InputDelegates] or Null"):
                w.line("var view = _view;")
                with w.block("if (view == null)"):
                    w.comment("nothing documents that getInitialView runs first, so build the")
                    w.comment("view here if it has not: its constructor reads the settings")
                    w.line(f"view = {view_ctor};")
                    w.line("_view = view;")
                w.line(f"return [ view.settingsMenu(), new {face.entry}SettingsDelegate(view) ];")
    return SourceFile(f"source/{face.entry}App.mc", w.render())


def emit_settings_delegate(face: Face) -> SourceFile:
    """`source/<Face>SettingsDelegate.mc` -- the settings menu's input
    delegate, plus, when a setting has choices, the delegate of the list
    a choice opens. Both hand the selection to the view, which owns the
    fields the menu shows and the one path that applies a change."""
    w = Writer()
    w.doc(header(face)).blank()
    w.lines("import Toybox.Lang;", "import Toybox.WatchUi;").blank()
    w.doc("Input for the settings menu: every selection goes to the view.")
    with w.block(f"class {face.entry}SettingsDelegate extends WatchUi.Menu2InputDelegate"):
        w.line(f"private var _view as {face.entry}View;")
        w.blank()
        with w.block(f"function initialize(view as {face.entry}View)"):
            w.line("Menu2InputDelegate.initialize();")
            w.line("_view = view;")
        w.blank()
        with w.block("function onSelect(item as WatchUi.MenuItem) as Void"):
            w.line("_view.selectSetting(item);")
    if any(s.type != "boolean" for s in face.settings.values()):
        w.blank()
        w.doc(
            "Input for one choice's list of options: the picked option is stored, the\n"
            "settings menu's item shows it, and the list closes."
        )
        with w.block(f"class {face.entry}SettingChoiceDelegate extends WatchUi.Menu2InputDelegate"):
            w.line(f"private var _view as {face.entry}View;")
            w.line("private var _setting as Number;")
            w.line("private var _parent as WatchUi.MenuItem;")
            w.blank()
            with w.block(f"function initialize(view as {face.entry}View, setting as Number, "
                         "parent as WatchUi.MenuItem)"):
                w.line("Menu2InputDelegate.initialize();")
                w.line("_view = view;")
                w.line("_setting = setting;")
                w.line("_parent = parent;")
            w.blank()
            with w.block("function onSelect(item as WatchUi.MenuItem) as Void"):
                w.line("var index = item.getId();")
                with w.block("if (index instanceof Number)"):
                    w.line("_view.chooseSetting(_setting, index);")
                    w.line("_parent.setSubLabel(item.getLabel());")
                w.line("WatchUi.popView(WatchUi.SLIDE_RIGHT);")
    return SourceFile(f"source/{face.entry}SettingsDelegate.mc", w.render())


def emit_palette(face: Face) -> SourceFile:
    w = Writer()
    w.doc(header(face)).blank()
    w.lines("import Toybox.Lang;").blank()
    w.doc(
        "Colours declared in the design's `palette:` block.\n"
        "\n"
        "Elements reference these by name rather than by hex, so a colour can be\n"
        "changed in one place and linted in one place."
    )
    with w.block("module Palette"):
        for index, (name, color) in enumerate(face.palette.items()):
            if index:
                w.blank()
            w.doc(f"`palette.{name}` = {color}")
            w.line(f"const {name.upper()} as Number = {color.as_monkeyc()};")
    return SourceFile("source/Palette.mc", w.render())


def emit_icon_glyphs(face: Face, via_char: frozenset[str] = frozenset()) -> SourceFile:
    """`source/IconGlyphs.mc`: catalogue name -> drawn glyph, for a dynamic
    (`icon_for:`) icon.

    A static icon's glyph is known at build time and gets baked directly
    into its `drawText` call as a literal (see `wfb.kinds.icon.IconKind.emit_draw`)
    -- no lookup needed. A dynamic icon's name is only known on-device, so
    this table, generated straight from `wfb.icon_catalog.CATALOG` rather than
    hand-maintained, resolves it there: `WfbWeather.mc`'s
    `chooseIcon` only ever produces a name, and this is the one place a
    name becomes a character, for every icon in the catalogue, not just
    weather ones.

    Scoped to the keys a dynamic icon can actually produce in this design --
    every entry `wfb.icons.GARMIN_WEATHER_CONDITION_ICON` can select, plus,
    for every `complication_slot` with `icon_size:`, every key
    `wfb.ir.ConfigDataSlot.icons` can resolve to for that slot -- so a
    design using only one of the two dynamic-icon features does not bake a
    lookup table for the other's keys too.

    A key in `via_char` gets its glyph built at runtime,
    `(0xF050F).toChar().toString()`, instead of written as a string literal:
    `wfb.emit.project.generate` passes the keys whose glyph literal would
    share a `str___<hash>` label with another string in the program, which
    crashes monkeyc (`wfb.emit.strhash`).
    """
    entries = icon_glyph_entries(face)
    w = Writer()
    w.doc(header(face)).blank()
    w.lines("import Toybox.Lang;").blank()
    w.doc(
        "Catalogue name (or a per-choice 'glyph:' override's canonical U+XXXX\n"
        "spelling) -> drawn glyph, for a dynamic (`icon_for:`) icon.\n"
        "\n"
        "Generated directly from wfb.icon_catalog.CATALOG (plus any per-choice\n"
        "override) -- see wfb/icons.py's module docstring for why this table,\n"
        "rather than WfbWeather.mc, is where a name becomes a character."
    )
    with w.block("module IconGlyphs"):
        with w.block("function glyph(name as String) as String"):
            with w.block("switch (name)"):
                for key in sorted(entries):
                    if key in via_char:
                        w.comment("built at runtime: as a literal, this glyph would share monkeyc's")
                        w.comment("str___<hash> label with another string (wfb/emit/strhash.py)")
                        w.line(f'case "{key}": return ({ord(entries[key]):#x}).toChar().toString();')
                    else:
                        w.line(f'case "{key}": return "{entries[key]}";')
                w.line(f'default: return "{icons.FALLBACK_CODEPOINT}";')
    return SourceFile("source/IconGlyphs.mc", w.render())


def icon_glyph_entries(face: Face) -> dict[str, str]:
    """Every key `IconGlyphs.glyph` must answer in this design -> its glyph.

    See `emit_icon_glyphs` for which keys, and why only those.
    """
    entries: dict[str, str] = {}  # key -> codepoint
    for _, run in kinds.face_text_runs(face):
        if run.glyph_table is not None:
            entries.update(run.glyph_table)
    return entries
