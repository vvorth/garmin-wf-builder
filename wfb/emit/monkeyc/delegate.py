"""`<Face>Delegate.mc` -- touch and hold, and the on-device config editor callbacks."""

from __future__ import annotations

from ... import complications
from ...availability import Guards
from ...ir import ComplicationSlot, complication_slot_hold_method
from ...layout import ResolvedFace
from .common import (
    CONFIG_LAYOUT_METHOD, SourceFile, _NO_GUARDS, _editor_slot_pairs, const_prefix,
    header, hold_targets,
)
from ..writer import Writer


def _emit_on_watchface_config_edited(w: Writer) -> None:
    """`onWatchFaceConfigEdited` -- re-read settings after an on-device edit.

    The typed signature is copied verbatim from
    `docs/research/probes/watchface-config/ProbeDelegate.mc`, itself checked
    against the SDK's own doc comment for this method
    (`WatchFaceConfig.Delegate.Type` and `WatchFaceConfig.Id`, both API
    5.1.0) -- this project's own rule against inventing an API applies to a
    callback's parameter shape as much as to any call.

    Only ever called on a device that actually has the editor (the callback
    itself is never invoked otherwise), so no `Application has :WatchFaceConfig`
    guard is needed here the way `onLayout`'s first read needs one -- unlike
    that first read, this one only runs *because* the editor just fired it.
    """
    w.doc(
        "The wearer changed something in the native editor.  Re-read the whole\n"
        "settings snapshot and hand it to the view -- the same `applyConfig` the\n"
        "first onLayout read already uses, so there is exactly one place that\n"
        "turns a Settings object into view state."
    )
    with w.block(
        "function onWatchFaceConfigEdited(options as {\n"
        "        :configId as $.Toybox.Application.WatchFaceConfig.Id,\n"
        "        :type as WatchFaceConfigType?,\n"
        "        :committed as $.Toybox.Lang.Boolean}) as Void",
    ):
        w.line("var id = options[:configId] as WatchFaceConfig.Id?;")
        with w.block("if (id != null)"):
            w.line("var settings = WatchFaceConfig.getSettings(id);")
            with w.block("if (settings != null)"):
                w.line("_view.applyConfig(settings);")
    w.blank()


def _emit_exit_to(w: Writer, exit_arg: str, guard: str | None = None) -> None:
    """`Complications.exitTo(<exit_arg>); return true;`, optionally wrapped in
    a runtime guard -- both hold-target shapes below (a `complication_slot`'s
    `on_hold: auto` and a fixed `on_hold:` target) reach exactly this pair of
    lines, guarded or not, and only differ in what `exit_arg` and ``guard``
    are.
    """
    with w.block_if(f"if ({guard})" if guard is not None else None):
        w.line(f"Complications.exitTo({exit_arg});")
        w.line("return true;")


def _hit_test(box: str, extra: str = "") -> str:
    """The `if` header testing the touch point `(x, y)` against the
    `Layout.<box>_X/_Y/_WIDTH/_HEIGHT` rectangle, plus any ``extra`` term."""
    return (
        f"if (x >= Layout.{box}_X && x < Layout.{box}_X + Layout.{box}_WIDTH\n"
        f"        && y >= Layout.{box}_Y && y < Layout.{box}_Y + Layout.{box}_HEIGHT{extra})"
    )


def emit_delegate(resolved: ResolvedFace, guards: "Guards | None" = None) -> SourceFile:
    """`source/<Face>Delegate.mc`: turn a touch and hold into a glance.

    **`onPress` only, on every device.**  `WatchFaceDelegate.onTap` exists on
    the fēnix 8 targets, but the SDK documents it "Only available in WatchFace
    config mode" -- it is how the *on-device editor* learns which complication
    slot the user picked (`samples/ConfigurableWatchFace`), and it never fires
    on a face that is merely being looked at.  Touch and hold is the whole
    input surface a live watch face gets; there is no swipe, and the physical
    keys belong to the system.  See `docs/research/07-carousel-interaction.md`
    §1 and ADR 0006 §6.

    `Complications.exitTo` is the whole mechanism on the other side: a watch
    face cannot launch an arbitrary app, only the one that owns a
    complication type.

    A `complication_slot` on `on_hold: auto` is a second shape: unlike
    every other target, the type this opens is not known at build time -- the
    wearer can repoint the slot at any moment -- so this reads it back
    through `Complications.exitTo(_view.<holdMethod>())` rather than indexing
    `wfb.complications.TYPES` with a fixed name (`Builder._resolve_hold_auto`'s
    own docstring explains why a slot's `auto` is never resolved to one).

    **`onTap`/`getComplicationDrawable` are the one exception to "no onTap",
    and only when the design has at least one `complication_slot`.**  Both
    are documented "Only available in WatchFace config mode" -- they never
    fire on a face merely being looked at, on any device (research 07 §1) --
    so they exist here purely to serve the native editor's own animated
    highlight over a slot, which is a wholly different thing from the "no
    onTap on a live face" rule above.  `docs/research/09-data-library-and-
    config-axes.md` §4 and `docs/research/probes/config-axes/` are the
    research and the working reference this follows.
    """
    face = resolved.face
    guards = guards if guards is not None else _NO_GUARDS
    targets = hold_targets(face)
    has_config = face.has_config
    slot_pairs = _editor_slot_pairs(face)
    w = Writer()
    w.doc(header(face)).blank()
    imports = ["import Toybox.Lang;", "import Toybox.WatchUi;"]
    if has_config:
        imports.insert(0, "import Toybox.Application.WatchFaceConfig;")
    if targets:
        imports.insert(0, "import Toybox.Complications;")
    w.lines(*imports).blank()
    w.doc(
        f"Touch handling for {face.name}.\n"
        "\n"
        "Each region below is one element's own drawn box, resolved per device in\n"
        "the Layout module, so what the finger must hit is what the eye sees."
    )
    needs_view = has_config
    with w.block(f"class {face.entry}Delegate extends WatchUi.WatchFaceDelegate"):
        if needs_view:
            w.doc("The view, so a config edit can be applied to it, or a\n"
                  "complication_slot's hold target read back.\n"
                  "\n"
                  "Only declared when it is actually read from: `monkeyc -w` reports an\n"
                  "unused member variable (verified -- \"Member variable '_view' is not\n"
                  "used.\" on a plain `on_hold:` design with neither `config:` nor a\n"
                  "complication_slot), and a generator has no excuse for output a human\n"
                  "wouldn't have written (CLAUDE.md).  The constructor parameter stays\n"
                  "unconditional either way: an unused *parameter* does not warn (verified\n"
                  "the same way, standalone), so one delegate shape and one\n"
                  "`new ...Delegate(view)` call site still serve every design -- only the\n"
                  "field is conditional.")
            w.line(f"private var _view as {face.entry}View;")
            w.blank()
        with w.block(f"function initialize(view as {face.entry}View)"):
            w.line("WatchFaceDelegate.initialize();")
            if needs_view:
                w.line("_view = view;")
        w.blank()
        if has_config:
            _emit_on_watchface_config_edited(w)
        if slot_pairs:
            _emit_on_tap(w, slot_pairs)
            _emit_get_complication_drawable(w)
        w.doc("A touch and hold -- the only gesture a live watch face receives.\n"
              "\n"
              "There is deliberately no onTap here for a live face: it is documented\n"
              "\"Only available in WatchFace config mode\" and never fires during normal\n"
              "display, on any device." +
              ("  The onTap above exists purely to serve the\n"
               "native editor's own animated highlight over a complication_slot, which\n"
               "is a different thing entirely.\n" if slot_pairs else "\n") +
              "\n"
              "Returns true when the touch was consumed, so the system does not also\n"
              "act on it.")
        with w.block("function onPress(clickEvent as ClickEvent) as Boolean"):
            if not targets:
                w.comment("this design declares no on_hold target -- the delegate exists")
                w.comment("only for onWatchFaceConfigEdited above")
            else:
                w.line("var where = clickEvent.getCoordinates();")
                w.line("var x = where[0];")
                w.line("var y = where[1];")
            for element in targets:
                assert element.on_hold is not None  # hold_targets keeps only these
                prefix = const_prefix(element.id)
                w.blank()
                # A hold target that belongs to a layout only fires while
                # that layout is the active one -- folded into the same hit
                # test rather than a separate guard around it, through the
                # view's own configLayout() (the delegate cannot read a
                # private field on another class -- CLAUDE.md,
                # docs/lore/monkeyc.md).  Unlike `visible:`, which keeps its
                # hold region while hidden because the delegate cannot see
                # that frame's readings, the layout *is* a view field the
                # delegate already has a handle to.
                layout_test = (
                    f" && _view.{CONFIG_LAYOUT_METHOD}() == {face.layouts.index(element.layout)}"
                    if element.layout is not None else ""
                )
                condition = _hit_test(f"{prefix}_HOLD", layout_test)
                if isinstance(element, ComplicationSlot):
                    w.comment(f"`{element.id}` -> whatever the wearer picked for "
                              f"config.data.{element.slot}")
                    with w.block(condition):
                        if guards.complications:
                            # The slot's own Id field is null wherever
                            # Toybox.Complications is absent (see
                            # _emit_config_fields/_emit_initialize) -- a null
                            # here means "nothing to launch", not "launch
                            # nothing", so the hold just does not fire, the
                            # same "absent means it does nothing" contract
                            # every complication hold already has for an
                            # unsupported *type* (wfb.complications module
                            # docstring).
                            w.line(f"var id = _view.{complication_slot_hold_method(element.id)}();")
                            _emit_exit_to(w, "id", guard="id != null")
                        else:
                            _emit_exit_to(w, f"_view.{complication_slot_hold_method(element.id)}()")
                    continue
                launch = complications.TYPES[element.on_hold]
                w.comment(f"`{element.id}` -> {element.on_hold}")
                exit_arg = f"new Complications.Id(Complications.{launch.constant})"
                with w.block(condition):
                    # `Complications.exitTo`/`Complications.Id` cannot be
                    # referenced at all on a device lacking the module --
                    # not only a call, any reference (Device.has_module's
                    # own docstring) -- so unlike the slot case above
                    # (which the field's own null already gates), a fixed
                    # `on_hold:` target needs its own `has` guard here.
                    _emit_exit_to(w, exit_arg, guard="Toybox has :Complications"
                                  if guards.complications else None)
            w.blank()
            w.line("return false;")
    return SourceFile(f"source/{face.entry}Delegate.mc", w.render())


def _emit_on_tap(w: Writer, pairs: list[tuple[ComplicationSlot, int]]) -> None:
    """`onTap` -- fires only inside the on-device config editor (research 07
    §1), and only ever emitted when the design has at least one
    `complication_slot` to tell the editor about.  Hit-tests each slot's own
    resolved box (`_BOX_*`, the same estimate the editor's Drawable is given
    in `getComplicationDrawable`) and reports it with `setSelectedComplication`,
    a `WatchFaceDelegate` method every design inherits -- no import needed.
    """
    w.doc(
        "Only fires inside the on-device config editor (research 07 1a) -- tells\n"
        "it which complication_slot was pointed at, exactly the SDK sample's own\n"
        "ConfigurationWatchFaceDelegate.onTap.  Never fires while the face is\n"
        "simply being looked at, on any device."
    )
    with w.block("function onTap(clickEvent as ClickEvent) as Boolean"):
        w.line("var where = clickEvent.getCoordinates();")
        w.line("var x = where[0];")
        w.line("var y = where[1];")
        for element, unique in pairs:
            prefix = const_prefix(element.id)
            w.blank()
            w.comment(f"`{element.id}` (config.data.{element.slot})")
            with w.block(_hit_test(f"{prefix}_BOX")):
                w.line(f"setSelectedComplication({unique});")
                w.line("return true;")
        w.blank()
        w.line("return false;")
    w.blank()


def _emit_get_complication_drawable(w: Writer) -> None:
    """`getComplicationDrawable` -- fires only inside the on-device config
    editor, to hand back a `Drawable` the system animates ("pulses") while
    the wearer picks a new value for one slot.

    Delegates straight to the view: `_view.setPulsing` hides the slot from
    the view's own `onUpdate` (the SDK sample's own comment on
    `ComplicationDrawable.draw` -- "This prevents the complication from being
    drawn on the watch face while it is pulsing" -- is what makes this
    necessary, not optional), and `_view.drawableFor` builds the generated
    `SlotDrawable` that delegates straight back to the view's own per-slot
    draw method, so there is exactly one implementation of what a slot looks
    like.  UNVERIFIED: whether the highlight actually animates, and whether
    it lines up with what is drawn -- no simulator runs in this container and
    there is no watch (CLAUDE.md).  What is verified is that this compiles
    warning-free under `-l 3` on all three targets, including `fr955`, which
    has no editor and therefore never calls this at all.
    """
    w.doc(
        "Only fires inside the on-device config editor: hands back a Drawable the\n"
        "system animates while the wearer picks a new value for one slot.\n"
        "\n"
        "UNVERIFIED whether the highlight actually animates or lines up with what\n"
        "is drawn -- no simulator runs in this container and there is no watch.\n"
        "What is verified: this compiles warning-free on every target, including\n"
        "fr955, which has no editor and so never calls this at all."
    )
    with w.block(
        "function getComplicationDrawable(complication as ComplicationRef)\n"
        "        as Drawable or WatchUi.ComplicationDrawableRef or Null",
    ):
        w.line("var unique = complication.uniqueIdentifier;")
        with w.block("if (unique == null)"):
            w.line("return null;")
        w.line("_view.setPulsing(unique);")
        w.line("return _view.drawableFor(unique);")
    w.blank()
