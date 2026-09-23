"""`<Face>View.mc` -- the generated view: fields, lifecycle methods and one
method per drawn element."""

from __future__ import annotations

from dataclasses import dataclass

from ... import complications, expr, series
from ...availability import Guards
from ...catalog import READERS
from ...devices import Device
from ...ir import (
    HOLD_AUTO, Face, config_data_ids, config_field, font_resource_id, local_name,
    static_group_method,
)
from ...layout import (
    ANTIALIASED_PRIMITIVES, PlacedComplicationSlot, PlacedGraph, PlacedHands, PlacedIcon,
    PlacedPattern, PlacedProgress, PlacedShape, PlacedText, ResolvedFace,
)
from ...palette import dim_fraction
from ...series import Acquisition
from .common import (
    AodDim, CONFIG_LAYOUT_METHOD, SourceFile, _BASE_IMPORTS, _NO_GUARDS, _aod_font_field,
    _aod_jitter_ns, _aod_only_fonts, _and_list, _const_prefix, _describe, _editor_slot_pairs,
    _field, _jitter_field, _loaded_fonts, _mc_bool, _method, _pattern_needs_math,
    _vector_fonts_used, header, hold_targets,
)
from .complication_slot import (
    _emit_complication_slot, _emit_complication_slot_editor_methods,
    _emit_complication_slot_hold_method, _emit_complication_slot_icon_method,
    _emit_pulsing_field,
)
from .graph import _emit_graph, _emit_graph_fields, _emit_graph_rebuild
from .readplan import ReadPlan
from .rotated import _emit_hands, _emit_pattern
from .shapes import _emit_icon, _emit_progress, _emit_shape, _emit_text
from ..writer import Writer


# --------------------------------------------------------------------------
# the view


#: The view field holding the offscreen buffer, and the method that fills it.
#: Fixed names rather than derived ones: there is at most one buffer per face
#: (an opaque full-screen blit cannot coexist with a second one -- see
#: `docs/research/probes/static-buffer/`), so there is nothing to disambiguate.
STATIC_FIELD = "_staticBuffer"


STATIC_RENDER = "renderStatic"


#: Re-paints the static buffer from the *current* field values -- the one
#: caller is `applyConfig`, for a config colour drawn into static content
#: (ADR 0006 1).  A fixed literal name, like the two above, not derived from
#: any element id -- so unlike `static_group_method`'s "drawStatic<Id>",
#: nothing an author writes can make this collide, and it does not need an
#: entry in `Builder._check_symbol_collision`.
REPAINT_STATIC_METHOD = "repaintStatic"


@dataclass
class StaticPlan:
    """Which drawn elements go into the offscreen buffer, and in what order.

    Built from the *resolved* items rather than the element tree, because the
    emitter works on the flattened draw order and `Element.static_root`
    (`wfb.ir.Builder._apply_static`) is what survives the flattening.

    `wfb.ir` has already guaranteed everything this relies on: `draw_sort_key`
    hoists the members to a contiguous prefix of draw order and keeps each
    root's members one unbroken run, nothing here reads a data source, and
    every member draws in the same modes.  So this class computes, it does not
    check.
    """

    #: ``(placed_root, [placed_member, ...])``, in draw order.
    groups: list
    #: Every buffered element, in draw order.
    members: list
    #: The modes the blit happens in -- all members agree on this.
    modes: tuple[str, ...]

    @property
    def ids(self) -> set[str]:
        return {placed.id for placed in self.members}

    def method(self, placed) -> str:
        """The method that paints one root: its own for a leaf, a wrapper else."""
        return (static_group_method(placed.id) if placed.kind == "group"
                else _method(placed.id))


def static_plan(resolved: ResolvedFace) -> StaticPlan | None:
    """The face's one static buffer, or None when nothing is static."""
    members = [p for p in resolved.items
               if p.kind != "group" and p.element.static_root is not None]
    if not members:
        return None
    roots = {p.id: p for p in resolved.items if p.element.static}
    groups: list = []
    for placed in members:
        root = roots.get(placed.element.static_root)
        if root is None:  # unreachable: `_apply_static` sets both together
            continue
        if not groups or groups[-1][0] is not root:
            groups.append((root, []))
        groups[-1][1].append(placed)
    modes = tuple(members[0].element.modes)
    return StaticPlan(groups=groups, members=members, modes=modes)


def _antialias_default(resolved: ResolvedFace) -> bool | None:
    """The face-wide `antialias:` default, or `None` when the feature is unused.

    `Element.resolved_antialias` already folds every inheritance step (face ->
    group -> element) into one per-element boolean (`wfb.ir.Builder.
    _resolve_antialias`), so "does any primitive-drawing element actually draw
    anti-aliased" is exactly "does any `ANTIALIASED_PRIMITIVES` member have
    `resolved_antialias == True`" -- no separate walk of the face default and
    the override tree is needed here.  The same tuple drives
    `_emit_element_method`'s toggle and `wfb.lint.check_antialias_palette`
    (this gate once kept a private copy without `PlacedHands`, so a face
    whose one anti-aliased element was a `type: hands` emitted no
    `applyAntiAlias` at all).

    `None` marks a design that never turns this on for a primitive-drawing
    element -- whether because the face default is `false` and nothing
    overrides it, or because the face default is `true` and every
    primitive-drawing element overrides it back to `false`. Returning `None`
    rather than `False` here is what lets every call site below skip
    emitting anything at all, instead of dutifully emitting
    `applyAntiAlias(dc, false)` calls that would be legal but pointless: a
    design that never uses the feature emits none of it.
    """
    used = any(
        isinstance(placed, ANTIALIASED_PRIMITIVES) and placed.element.resolved_antialias
        for placed in resolved.items
    )
    return resolved.face.antialias if used else None


def _emit_antialias_helper(w: Writer) -> None:
    """`applyAntiAlias` -- the guarded `Dc.setAntiAlias` call.

    `Dc.setAntiAlias` is API 3.2.0 and present on only 113 of 164 devices;
    `doc/docs/Core_Topics/Graphics.html` gives this exact `has` idiom for it.
    A build-time gate is not an option: `wfb/emit/project.py` generates one
    view shared across every target device, so the decision cannot become a
    per-device constant -- the call has to type-check under `-l 3` even on a
    device whose `api.debug.xml` lacks the symbol.

    Deliberately **not** named `setAntiAlias`: a same-named private method on
    the view shadows `Dc`'s own, so `:setAntiAlias` resolves to this class's
    symbol instead and `monkeyc` warns about it on every target
    (`docs/research/probes/antialias/README.md`, finding 3).
    """
    w.doc(
        "Turn primitive anti-aliasing on or off, where the device supports it.\n"
        "\n"
        "Guarded rather than called directly: `Dc.setAntiAlias` is absent on "
        "roughly a\n"
        "third of Connect IQ devices, and this view's generated code has to "
        "type-check\n"
        "on every target regardless of which one actually has the symbol."
    )
    with w.block("private function applyAntiAlias(dc as Dc, on as Boolean) as Void"):
        with w.block("if (dc has :setAntiAlias)"):
            w.line("dc.setAntiAlias(on);")
    w.blank()


def _has_partial_update(resolved: ResolvedFace) -> bool:
    """Does this build actually get an `onPartialUpdate` -- both the design
    declaring a `low_power` mode and the device itself supporting partial
    updates (AMOLED forbids it, CLAUDE.md constraint 5).  Named once rather
    than repeated at each of its three call sites (`emit_view`, twice, and
    `_emit_sleep_hooks`), which otherwise have to agree independently.
    """
    return resolved.in_mode("low_power") and resolved.device.supports_partial_update


def emit_view(resolved: ResolvedFace, guards: "Guards | None" = None) -> SourceFile:
    face, device = resolved.face, resolved.device
    guards = guards if guards is not None else _NO_GUARDS
    plan = ReadPlan(resolved, guards)
    if _has_partial_update(resolved):
        plan.modules.add("Toybox.System")  # onPowerBudgetExceeded reports via println
    # `aod: {jitter: ...}` (plan 14 slice 5, §5.2): every distinct magnitude
    # an AOD-shown element actually resolves to, in this build -- `()` for a
    # design that never uses `jitter:` at all, or an all-MIP build, so this
    # feature costs nothing on either (byte-identical to before it existed).
    # Computed here, ahead of the `import` loop below (not beside the `aod`/
    # `dim` locals further down, which run *after* that loop has already
    # snapshotted `plan.modules` -- `guards.amoled_target` is used directly
    # rather than waiting for the `aod` local for exactly that reason).
    jitter_ns = _aod_jitter_ns(resolved) if guards.amoled_target else ()
    if jitter_ns:
        plan.modules.add("Toybox.System")  # getClockTime() for the minute of day

    graphs = [p for p in resolved.items if isinstance(p, PlacedGraph)]
    graph_modules: set[str] = set()
    if graphs:
        # System.getClockTime() drives the rebuild-cadence check on every
        # graph, regardless of series -- the same call the low-power branch
        # above adds System for, just unconditional here.
        graph_modules.add("Toybox.System")
        for placed in graphs:
            src = placed.element.series_def
            graph_modules.add(series.ACQUISITION[src.acquisition].module)
            if src.acquisition is Acquisition.HEART_RATE and placed.element.range_kind == "duration":
                graph_modules.add("Toybox.Time")  # new Time.Duration(seconds)

    config_modules: set[str] = set()
    if face.has_config:
        # `Application has :WatchFaceConfig` (onLayout's guard) needs the
        # first; `WatchFaceConfig.Settings`/`.getSettings` (applyConfig)
        # need the second.
        config_modules = {"Toybox.Application", "Toybox.Application.WatchFaceConfig"}
    if face.config_data:
        # `Complications.Id`/`Complications.COMPLICATION_TYPE_*` -- needed
        # even when no ordinary `complication.*` source is bound, which is
        # why this is not folded into `plan.modules` (derived from bound
        # sources only).
        config_modules.add("Toybox.Complications")

    hands_items = [p for p in resolved.items if isinstance(p, PlacedHands)]
    trig_modules: set[str] = set()
    if hands_items:
        # The view computes each hand's own sin/cos directly, not just the
        # barrel -- so Toybox.Math is imported here too, not only in
        # WfbHands.mc.
        trig_modules.add("Toybox.Math")
    pattern_items = [p for p in resolved.items if isinstance(p, PlacedPattern)]
    if any(_pattern_needs_math(p) for p in pattern_items):
        # Same reasoning: a radial pattern with at least one non-arc part
        # computes its own sin/cos in the loop, so Math has to be in scope
        # here too -- not only when hands are also on the design.
        # `_pattern_needs_math` is the one place this decision is made,
        # shared with `_emit_pattern` itself.
        trig_modules.add("Toybox.Math")
    hands_awake_second = any(
        p.second is not None and p.element.seconds == "awake" for p in hands_items
    )

    w = Writer()
    w.doc(header(face, f"Device:    {device.id}")).blank()
    for module in sorted(set(_BASE_IMPORTS) | plan.modules | graph_modules
                         | config_modules | trig_modules):
        w.line(f"import {module};")
    w.blank()

    w.doc(
        f"{face.name}.\n"
        "\n"
        "One private method per design element, in draw order.  Each is named after\n"
        "the element's `id:` in the source YAML, so a change on screen leads back to\n"
        "a line in the design file."
    )
    # `aod` (plan 14 D1's build-time half): whether *any* target in this
    # build is AMOLED. Only then does the shared view carry `_aod`, its
    # onEnterSleep/onExitSleep burn-in check, and the onUpdate branch that
    # reads it -- an all-MIP build emits none of it, so its generated
    # source stays byte-identical to a build before plan 14 (plan 14 §6
    # slice 1's own test).
    aod = guards.amoled_target
    if aod:
        plan.modules.add("Toybox.System")  # DeviceSettings.requiresBurnInProtection
    # `aod: {dim: ...}` (plan 14 §4.5): computed once here, as the same
    # `(num, den)` integer ratio every dimming call site shares -- `None`
    # for "no dimming", which is also what a face with no `dim:` at all (or
    # an all-MIP build, where `aod` above is already `False`) gets, so
    # nothing downstream needs a second "does this face even dim" check.
    dim: AodDim = dim_fraction(face.aod_dim) if aod and face.aod_dim is not None else None
    # `_sleeping` exists only for the `awake`-only second hand (whether to
    # draw it at all) -- `aod` no longer reads it: the AMOLED gate is `_aod`
    # below, recomputed straight from the device settings in onEnterSleep,
    # not derived from `_sleeping`. A field that is only ever *assigned*
    # (never read) warns (`docs/lore/monkeyc.md`), which is exactly what
    # `_sleeping` would do if emitted whenever `aod` alone were true and
    # nothing reads it back.
    needs_sleeping_field = hands_awake_second
    static = static_plan(resolved)
    antialias_default = _antialias_default(resolved)
    slot_pairs = _editor_slot_pairs(face)
    # `aod: {font: ...}` (plan 14 §4.3): a baked font named only by an AOD
    # override, never drawn while awake -- computed only when this build
    # ever emits AOD code at all, so an all-MIP build never even looks
    # (`aod_only_fonts` would be `[]` there regardless, since no element
    # gets a resolved `aod:` worth restyling, but this keeps the intent
    # explicit and matches every other `if aod:`-gated computation here).
    aod_only_fonts = _aod_only_fonts(resolved) if aod else []
    with w.block(f"class {face.entry}View extends WatchUi.WatchFace"):
        _emit_fields(w, resolved, aod_only_fonts)
        _emit_config_fields(w, face, guards)
        _emit_static_field(w, static)
        _emit_graph_fields(w, graphs)
        if slot_pairs:
            _emit_pulsing_field(w)
        if needs_sleeping_field:
            w.doc(_sleep_flag_doc(hands_awake_second))
            w.line("private var _sleeping as Boolean = false;")
            w.blank()
        if aod:
            w.doc(
                "Whether the AMOLED always-on-display frame should draw: asleep, on a\n"
                "device that requires burn-in protection. Recomputed in onEnterSleep\n"
                "(a hardware fact, not a per-frame one) and cleared in onExitSleep --\n"
                "see docs/guide/always-on-display.md."
            )
            w.line("private var _aod as Boolean = false;")
            w.blank()
        if jitter_ns:
            w.doc(
                "The current AOD frame's own deterministic per-minute pixel offset\n"
                "('aod: {jitter: ...}', plan 14 §5.2) -- one pair per distinct magnitude\n"
                "this design actually uses (WfbJitter.mc). Computed once, at the top of\n"
                "the AOD branch, from the current minute of day; reset to 0 in\n"
                "onExitSleep, so a jittered element's shared draw method can add these\n"
                "in unconditionally, at every coordinate, with no cost while awake."
            )
            for n in jitter_ns:
                w.line(f"private var {_jitter_field(n, 'x')} as Number = 0;")
                w.line(f"private var {_jitter_field(n, 'y')} as Number = 0;")
            w.blank()
        _emit_initialize(w, face, has_slots=bool(slot_pairs), guards=guards)
        if antialias_default is not None:
            _emit_antialias_helper(w)
        if face.has_config:
            _emit_apply_config(w, face, static)
        if face.has_config and any(t.layout is not None for t in hold_targets(face)):
            _emit_config_layout_accessor(w)
        _emit_on_layout(w, resolved, plan, static, guards)
        _emit_on_update(w, resolved, plan, aod, static, antialias_default, jitter_ns, guards)
        if _has_partial_update(resolved):
            _emit_on_partial_update(w, resolved, plan, antialias_default)
        _emit_sleep_hooks(w, resolved, needs_sleeping_field, aod, guards, aod_only_fonts, jitter_ns)
        if plan.complication_readers():
            _emit_complication_callback(w, plan)
        for placed in graphs:
            _emit_graph_rebuild(w, placed)
        for placed in resolved.items:
            if isinstance(placed, PlacedComplicationSlot) and placed.icon_font_key is not None:
                _emit_complication_slot_icon_method(w, resolved, placed)
            if isinstance(placed, PlacedComplicationSlot) and placed.element.on_hold == HOLD_AUTO:
                _emit_complication_slot_hold_method(w, placed, guards)
        if slot_pairs:
            _emit_complication_slot_editor_methods(w, face, slot_pairs)
        if static is not None:
            _emit_static_methods(w, face, static, antialias_default, needs_repaint=face.has_config)
        for placed in resolved.items:
            if placed.kind == "group":
                continue
            w.blank()
            _emit_element_method(w, resolved, placed, plan, antialias_default, aod, dim)
    return SourceFile(f"source/{face.entry}View.mc", w.render())


def _sleep_flag_doc(hands_awake_second: bool) -> str:
    """`_sleeping`'s own doc -- unlike before plan 14, this field exists only
    for the awake-only second hand; the AMOLED gate is `_aod`, which has its
    own doc where it is declared (`emit_view`), computed fresh from the
    device settings rather than derived from this flag.
    """
    assert hands_awake_second  # the only reason this field is ever emitted
    return (
        "Whether the watch is currently asleep.  Set by onEnterSleep/onExitSleep "
        "below.\n\n"
        "An awake-only second hand ('seconds: awake') reads it, so its own draw\n"
        "method skips the second hand while asleep instead of drawing it frozen at\n"
        "whatever second the once-a-minute sleeping update landed on."
    )


def _emit_static_field(w: Writer, static: "StaticPlan | None") -> None:
    """The offscreen buffer the static content is painted into, once."""
    if static is None:
        return
    w.doc("The static content, painted once in onLayout and blitted every frame\n"
          "afterwards.\n"
          "\n"
          "Allocated from the graphics pool, which is separate from the watch face's\n"
          "own memory limit -- so this costs a full screen of pixels there, not here.\n"
          "Null on a device without createBufferedBitmap, or if the pool declines the\n"
          "allocation; onUpdate then draws the same content directly instead, so the\n"
          "face renders either way.")
    w.line(f"private var {STATIC_FIELD} as BufferedBitmap?;")
    w.blank()


def _emit_static_allocation(w: Writer, static: "StaticPlan") -> None:
    """Allocate the buffer and fill it -- the `onLayout` half of the feature.

    `.get()` rather than the reference it comes back as: the Core Topics
    Graphics page is explicit that a purged BufferedBitmap is *not* restored the
    way a resource is, and nothing here would ever refill it, so the lock is
    correctness rather than an optimisation.  Same shape as
    `$CIQ_SDK/samples/Analog/source/AnalogView.mc`, and `Graphics has
    :createBufferedBitmap` guards it for the same reason that sample does.

    No `:palette`: a reduced palette cannot take an anti-aliased font, which the
    Analog sample hit and worked around with a second buffer.  A static group may
    hold text, so it gets the system colours.  The same absence of `:palette` is
    also what makes `applyAntiAlias` legal on this buffer's own Dc --
    `Dc.setAntiAlias` is documented unsupported only for a palette'd
    `BufferedBitmap` -- so a static anti-aliased shape or progress element needs
    no special case in `renderStatic`.
    """
    w.comment("the static content, painted once into a buffer in the graphics pool")
    with w.block("if (Graphics has :createBufferedBitmap)"):
        w.line(f"{STATIC_FIELD} = Graphics.createBufferedBitmap({{")
        w.line("    :width => dc.getWidth(),")
        w.line("    :height => dc.getHeight()")
        w.line("}).get() as BufferedBitmap?;")
    w.line(f"var buffer = {STATIC_FIELD};")
    with w.block("if (buffer != null)"):
        w.line(f"{STATIC_RENDER}(buffer.getDc());")


def _emit_static_blit(w: Writer, static: "StaticPlan") -> None:
    """One blit, or the same drawing done live when there is no buffer."""
    w.comment("static content: one blit of the buffer filled in onLayout")
    w.line(f"var buffer = {STATIC_FIELD};")
    with w.block("if (buffer != null)"):
        w.line("dc.drawBitmap(0, 0, buffer);")
    with w.block("else"):
        w.comment("no buffer on this device: draw the same content directly")
        w.line(f"{STATIC_RENDER}(dc);")


def _emit_static_methods(w: Writer, face: Face, static: "StaticPlan",
                         antialias_default: bool | None = None,
                         needs_repaint: bool = False) -> None:
    """`renderStatic`, plus one `drawStatic<Id>` per static *group*.

    `renderStatic` takes a Dc rather than the buffer, and is called with the
    buffer's Dc from onLayout and with the screen's from onUpdate.  That is the
    whole of the fallback: one method, two call sites, and no second version of
    the drawing to drift.

    It clears first.  The buffer's initial contents are not documented anywhere
    in the SDK, so it has to; and because the static content is always the
    prefix of draw order (`wfb.ir.draw_sort_key` puts it there), clearing on the
    *screen* path too is both safe (nothing has been drawn yet this frame) and
    what makes the two paths identical.  Black is also what
    `wfb preview` starts from, so the host renderer and the device agree.

    Anti-aliasing is reset here too, for the same one-method-two-call-sites
    reason: `_emit_static_allocation` allocates the buffer without `:palette`
    (`Dc.setAntiAlias` is documented unsupported only for a palette'd
    `BufferedBitmap`), so the call is legal on both the buffer's Dc and the
    screen's, and putting the reset inside `renderStatic` itself, rather than
    at each of its two call sites, is what keeps that true without saying it
    twice.

    Each root's *call* -- not its `drawStatic<Id>` body -- is what a layout
    guard wraps: a static root's members are all shared, or all one layout's
    own (`Builder._apply_static` marks a whole subtree from one root, and
    `Builder._assign_layouts` stamps `Element.layout` on a whole subtree from
    one synthetic group, so the two can never disagree within one root --
    asserted below, not just assumed).  `drawStatic<Id>` itself stays
    unguarded, the same body regardless of which layout is active, because it
    is only ever called from behind that one guard.
    """
    w.blank()
    w.doc("Everything that never changes, drawn once.\n"
          "\n"
          "Called with the offscreen buffer's Dc from onLayout, and with the screen's\n"
          "own Dc from onUpdate when there is no buffer.  One method, so the buffered\n"
          "and unbuffered paths cannot drift apart.")
    with w.block(f"private function {STATIC_RENDER}(dc as Dc) as Void"):
        w.comment("a fresh buffer's contents are undefined, and this is the first")
        w.comment("thing drawn in the frame either way, so start from a known ground")
        w.line("dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);")
        w.line("dc.clear();")
        if antialias_default is not None:
            w.line(f"applyAntiAlias(dc, {_mc_bool(antialias_default)});")
        calls = []
        for root, members in static.groups:
            assert all(p.element.layout == root.element.layout for p in members), (
                f"static root {root.id!r} mixes layouts across its own members -- "
                "_apply_static/_assign_layouts should make that unreachable"
            )
            calls.append((root.element, f"{static.method(root)}(dc);"))
        _emit_layout_guarded_calls(w, face, calls)
    if needs_repaint:
        w.blank()
        w.doc("Re-paint the static buffer from the current field values, in place.\n"
              "\n"
              "Called only from `applyConfig`: a config colour drawn into static "
              "content\n"
              "was already baked into the buffer once in onLayout, so a wearer's "
              "edit\n"
              "needs this to show before the buffer is blitted again.  Narrows "
              "through a\n"
              "local rather than calling `.getDc()` straight off the field -- "
              "`monkeyc`\n"
              "cannot narrow a `Null` check across a field read (CLAUDE.md).")
        with w.block(f"private function {REPAINT_STATIC_METHOD}() as Void"):
            w.line(f"var buffer = {STATIC_FIELD};")
            with w.block("if (buffer != null)"):
                w.line(f"{STATIC_RENDER}(buffer.getDc());")
    for root, members in static.groups:
        if root.kind != "group":
            continue  # a static leaf is drawn by its own method, called above
        w.blank()
        w.doc(f"`{root.element.id}` -- the static subtree, in draw order.")
        with w.block(f"private function {static.method(root)}(dc as Dc) as Void"):
            for placed in members:
                w.line(f"{_method(placed.id)}(dc);")


def _emit_fields(w: Writer, resolved: ResolvedFace, aod_only_fonts: list[str] | None = None) -> None:
    loaded = _loaded_fonts(resolved)
    vector_fonts = _vector_fonts_used(resolved)
    aod_only_fonts = aod_only_fonts or []
    if not loaded and not vector_fonts and not aod_only_fonts:
        return
    if loaded:
        w.doc("Bitmap fonts -- custom text and icon glyphs alike -- loaded once in\n"
              "onLayout rather than per frame.")
        for name in loaded:
            w.line(f"private var _{_field(name)} as FontResource?;")
        w.blank()
    if aod_only_fonts:
        w.doc(
            "Bitmap fonts named only by an 'aod: {font: ...}' override (plan 14\n"
            "§4.3) -- never drawn while awake, so they are loaded in onEnterSleep\n"
            "instead of here, only when _aod ends up true, and released (nulled) in\n"
            "onExitSleep so they do not sit in memory the whole time."
        )
        for name in aod_only_fonts:
            w.line(f"private var _{_aod_font_field(name)} as FontResource?;")
        w.blank()
    if vector_fonts:
        # Not a `WatchUi.loadResource` resource at all (plan 11) -- a
        # `Graphics.VectorFont` handed back by `Graphics.getVectorFont`, or
        # `null` when this device cannot build it (a target that fails
        # gates 1-3 under `if_unavailable: hide`, or `Graphics.
        # getVectorFont`'s own documented "or NULL" even when it can --
        # gate 4, never assumed away). Every draw call using one checks for
        # `null` before drawing (`shapes._emit_text_draw`).
        w.doc("Device-resident scalable ('face:') fonts (plan 11) -- a Graphics.\n"
              "VectorFont handed back by Graphics.getVectorFont, not a loaded\n"
              "resource; null wherever this device cannot build it, which every\n"
              "draw call below checks before using it.")
        for name in vector_fonts:
            w.line(f"private var _{_field(name)} as Graphics.VectorFont?;")
        w.blank()


def _emit_config_fields(w: Writer, face: Face, guards: "Guards" = _NO_GUARDS) -> None:
    """One field per declared `config:` colour entry, one per role of the
    *default* `config: style:` entry's `color_scheme:`, and one
    `Complications.Id` per declared `config: data:` slot -- each initialised
    to its compiled-in default.

    The compiled-in default is not a fallback path -- it is *the* path: a
    device with no native editor (fr955) never calls `applyConfig` at all
    and simply keeps running with this.  A Styles role starts at the
    *default entry's* scheme colour for that role, and a `config: data:`
    slot starts at its own declared `default:` type, the same "default is
    the path, not a fallback" reasoning applied to a colour and a
    complication type alike.  A layout-only default entry (`colors is
    None`) has no scheme to start a role from, so it emits no role fields at
    all.

    A `config: data:` slot's field is the one exception to "initialised
    inline, right here": when some target lacks `Toybox.Complications`
    (`guards.complications`), `new Complications.Id(...)` cannot run
    unconditionally -- a field initialiser runs at *construction*, on every
    device, before any `has` guard could ever skip it, so an inline
    `new Complications.Id(...)` here would crash a device like fenix6 the
    instant the view is constructed, guard or no guard elsewhere. The field
    is declared nullable and left `null` here instead; `_emit_initialize`
    constructs it, guarded, in the constructor, where a `Toybox has
    :Complications` check actually runs before the construction it guards.
    """
    if not face.has_config:
        return
    w.doc("Colours and complications the wearer can change in the native "
          "on-device editor\n"
          "(fēnix 8 and newer only).  Each starts at its declared default, "
          "which is also\n"
          "the only value a device with no editor -- fr955 -- ever shows.")
    for name, entry in face.config.items():
        w.line(f"private var {entry.field} as Number = {entry.default.as_monkeyc()};")
    if face.config_style is not None and face.config_style.default_entry.colors is not None:
        default_scheme = face.color_scheme[face.config_style.default_entry.colors]
        for role, color in default_scheme.colors.items():
            field = config_field(f"colors_{role}")
            w.line(f"private var {field} as Number = {color.as_monkeyc()};")
    if face.layouts:
        # The default entry's layout, in declaration order -- always set,
        # since `layout:` is required on every entry once `layouts:` is
        # declared.  Not a fallback path: fr955 has no native editor and
        # never calls `applyConfig` at all, so this is the only layout it
        # ever shows.
        default_layout = face.config_style.default_entry.layout
        default_index = face.layouts.index(default_layout)
        w.line(f"private var {CONFIG_LAYOUT_FIELD} as Number = {default_index};")
    for name, slot in face.config_data.items():
        ctype = complications.TYPES[slot.default]
        if guards.complications:
            w.line(f"private var {slot.field} as Complications.Id? = null;  "
                   f"// set in initialize() -- see this method's own doc")
        else:
            w.line(f"private var {slot.field} as Complications.Id = "
                   f"new Complications.Id(Complications.{ctype.constant});")
    w.blank()


def _emit_apply_config(w: Writer, face: Face, static: "StaticPlan | None") -> None:
    """`applyConfig` -- turn one `WatchFaceConfig.Settings` snapshot into view
    state.  Called from both `onLayout`'s first read and the delegate's
    `onWatchFaceConfigEdited`, so there is exactly one place that does this.

    Every field on the way in is nullable twice over -- `Settings.accentColor`
    is `Color?` and its own `.color` is `ColorType?` again
    (`docs/research/probes/watchface-config/`) -- so each axis gets its own
    two-deep guard, matching the probe's `apply()` exactly rather than
    inventing a shorter form.  `styleId` (the `config: style:` axis, if
    declared) is only nullable once, and is range-checked rather than
    dereferenced twice -- see `_emit_resolve_style`.
    """
    w.doc(
        "Apply one WatchFaceConfig.Settings snapshot.\n"
        "\n"
        "Every field is nullable twice over, so a missing value simply leaves the\n"
        "existing (defaulted) field alone rather than being treated as an error."
    )

    with w.block("function applyConfig(settings as WatchFaceConfig.Settings) as Void"):
        if face.config_style is not None:
            style_local = local_name("config_style")
            w.line(f"var {style_local} = settings.styleId;")
            with w.block(
                f"if ({style_local} != null && {style_local} >= 0 && "
                f"{style_local} < {len(face.config_style.entries)})"
            ):
                w.line(f"{RESOLVE_STYLE_METHOD}({style_local});")
        for name, entry in face.config.items():
            axis = entry.axis
            local = local_name(f"config_{name}")
            w.line(f"var {local} = settings.{axis.settings_field};")
            with w.block(f"if ({local} != null)"):
                value_local = f"{local}Value"
                w.line(f"var {value_local} = {local}.color;")
                with w.block(f"if ({value_local} != null)"):
                    w.line(f"{entry.field} = {value_local} as Number;")
        if face.config_data:
            ids = config_data_ids(face)
            w.blank()
            w.comment("config: data: -- each ComplicationRef names the slot it belongs")
            w.comment("to by 'uniqueIdentifier', matching the <complication id=...> below")
            w.line("var slots = settings.complicationSettings;")
            with w.block("if (slots != null)"):
                with w.block("for (var i = 0; i < slots.size(); i += 1)"):
                    w.line("var ref = slots[i];")
                    w.line("var unique = ref.uniqueIdentifier;")
                    w.line("var picked = ref.complicationId;")
                    with w.block("if (unique == null || picked == null)"):
                        w.line("continue;")
                    # Plain sequential `if`s rather than an `if`/`else if`
                    # chain -- `unique` cannot equal two distinct slot ids at
                    # once, so the two are equivalent, and independent blocks
                    # are simpler for `Writer` to emit correctly (the same
                    # reasoning `_emit_resolve_style` already uses).
                    for name, slot_id in ids.items():
                        slot = face.config_data[name]
                        with w.block(f"if (unique == {slot_id})"):
                            w.line(f"{slot.field} = picked;")
        if static is not None:
            w.blank()
            w.comment("a config colour may be painted into the static buffer -- repaint")
            w.comment("it now so a wearer's change shows without waiting for onLayout")
            w.line(f"{REPAINT_STATIC_METHOD}();")
        w.line("WatchUi.requestUpdate();")
    w.blank()
    if face.config_style is not None:
        _emit_resolve_style(w, face)


def _emit_config_layout_accessor(w: Writer) -> None:
    """`configLayout()` -- the view's public accessor for `_configLayout`.

    Public, not `private`: the one and only reader is the generated
    delegate's `onPress`, a *different* class, and `private` genuinely
    blocks a cross-class method call (confirmed by building both ways --
    docs/lore/monkeyc.md) the same way it would a field.  Emitted only when
    some `on_hold:` target actually belongs to a layout (`emit_view`'s own
    call site) -- there is no reason to emit a method nothing calls.
    """
    w.doc("The active layout's index, for the delegate's onPress to test a "
          "layout-scoped\n"
          "hold target against.  Public: a delegate method cannot reach a "
          "private field\n"
          "on this class.")
    with w.block(f"function {CONFIG_LAYOUT_METHOD}() as Number"):
        w.line(f"return {CONFIG_LAYOUT_FIELD};")
    w.blank()


#: Fixed generated method name -- there is at most one `config: style:` axis
#: per face (unlike `drawStatic<Id>`/`draw<Id>`, nothing here is derived from
#: an author id), so it needs no per-design collision check the way those do.
RESOLVE_STYLE_METHOD = "resolveStyle"


#: The view field the active layout's declaration-order index is cached in
#: -- `_configLayout`, read by every guard below (`_emit_layout_guarded_calls`)
#: and by the view's own `configLayout()` accessor.  Emitted only when
#: `face.layouts` is non-empty: there is nothing for it to hold otherwise.
CONFIG_LAYOUT_FIELD = config_field("layout")


def _emit_resolve_style(w: Writer, face: Face) -> None:
    """`resolveStyle` -- decode one Styles id into this design's `config:
    style:` entries.

    One `if (style == i)` block per entry, in `choices:` order (index 0
    first, matching `<style id="N">` in the generated resource) -- this is
    the only place a `styleId` (an opaque `Number` Garmin gives no meaning to
    at all, `docs/research/09-data-library-and-config-axes.md` §3) is given
    one.  A colour-carrying entry's block assigns that entry's scheme's
    roles; a layout-carrying entry's also sets `_configLayout` to that
    layout's declaration-order index (the same index every guard below
    tests).  A layout-only entry has no colour lines, and a
    colour-only entry has no `_configLayout` line -- both read straight off
    which of `entry.colors`/`entry.layout` is set.  Plain sequential `if`s
    rather than an `if`/`else if` chain: `style` cannot equal two distinct
    literals at once, so the two are equivalent, and independent blocks are
    simpler for `Writer` to emit correctly.

    An out-of-range id is guarded by the caller (`applyConfig`) before this is
    ever called, and any id it does not recognise here is silently ignored: a
    rebuild with fewer entries can leave a saved style id past the end.
    """
    assert face.config_style is not None
    w.doc(
        "Decode one Styles id into this design's config: style: entries.  styleId is\n"
        "an opaque Number Garmin gives no meaning to -- this is the only place\n"
        "that meaning is assigned, in 'choices:' order, index 0 first."
    )
    with w.block(f"private function {RESOLVE_STYLE_METHOD}(style as Number) as Void"):
        for index, entry in enumerate(face.config_style.entries):
            with w.block(f"if (style == {index})"):
                comment = []
                if entry.colors is not None:
                    comment.append(f"color_scheme.{entry.colors}")
                if entry.layout is not None:
                    comment.append(f"layouts.{entry.layout}")
                w.comment(f"{entry.name} -- {', '.join(comment)}")
                if entry.colors is not None:
                    scheme = face.color_scheme[entry.colors]
                    for role, color in scheme.colors.items():
                        field = config_field(f"colors_{role}")
                        w.line(f"{field} = {color.as_monkeyc()};")
                if entry.layout is not None:
                    layout_index = face.layouts.index(entry.layout)
                    w.line(f"{CONFIG_LAYOUT_FIELD} = {layout_index};")
    w.blank()


def _emit_initialize(w: Writer, face: Face, has_slots: bool = False,
                     guards: "Guards" = _NO_GUARDS) -> None:
    """The view's constructor.

    `editMode` is accepted, not stored, when the design has at least one
    `complication_slot`: `getComplicationDrawable`/`onTap` are self-gating --
    the system simply never calls them outside the editor -- and this
    project pulls every complication fresh every frame rather than caching
    or subscribing the way the SDK sample's own `_editMode` flag skips a
    subscription, so there is nothing left here for it to gate.  An unused
    *parameter* does not warn (verified, the same as the delegate's own
    `view` parameter), which is what lets `AppBase.onStart` detect edit mode
    at all without forcing an unused *field* here too (verified the other
    way: a written-but-never-read member variable does warn -- "Member
    variable '_editMode' is not used." -- so the App class reads its own
    field back by passing it on to this constructor, and this constructor's
    signature is the whole reason that counts as a read).

    When `guards.complications`, this is also where every `config: data:`
    slot's `Complications.Id` field actually gets built -- see
    `_emit_config_fields`'s own doc for why a field *initialiser* is the
    wrong place for it (it runs before any `has` guard could matter) and the
    constructor, which runs code rather than merely declaring a default, is
    the right one.
    """
    if has_slots:
        w.doc(
            "`editMode` is accepted, not stored: getComplicationDrawable/onTap\n"
            "(the delegate) are self-gating -- the system simply never calls them\n"
            "outside the native editor -- and every complication here is pulled\n"
            "fresh every frame rather than cached or subscribed, so there is\n"
            "nothing else in this view for edit mode to change.  An unused\n"
            "*parameter* does not warn (verified, same as the delegate's own\n"
            "`view` parameter); a written-but-never-read *field* does (verified\n"
            "the other way -- \"Member variable '_editMode' is not used.\"), which\n"
            "is why AppBase.onStart's own flag is forwarded here rather than kept."
        )
    signature = "function initialize(editMode as Boolean)" if has_slots else "function initialize()"
    with w.block(signature):
        w.line("WatchFace.initialize();")
        if guards.complications and face.config_data:
            w.blank()
            w.comment("Toybox.Complications is absent on at least one target -- leave")
            w.comment("every slot's Id null there, which config: data: draw code below")
            w.comment("already treats as \"nothing chosen\" (when_absent-style absence)")
            with w.block("if (Toybox has :Complications)"):
                for name, slot in face.config_data.items():
                    ctype = complications.TYPES[slot.default]
                    w.line(f"{slot.field} = new Complications.Id(Complications.{ctype.constant});")
    w.blank()


def _emit_complication_subscribe_lines(w: Writer, event: list[str]) -> None:
    """The register-callback line, then one `WfbComplications.subscribe` per
    reader -- emitted identically whether or not it sits behind a `Toybox has
    :Complications` guard, so `_emit_on_layout`'s guarded and unguarded
    branches cannot drift apart.
    """
    w.line("Complications.registerComplicationChangeCallback(method(:onComplicationChanged));")
    for name in event:
        reader = READERS[name]
        w.line(f"WfbComplications.subscribe(new Complications.Id(Complications.{reader.complication_type}));")


def _emit_vector_font_construction(w: Writer, name: str, guards: "Guards") -> None:
    """One font's `Graphics.getVectorFont(...)` construction in `onLayout`
    (plan 11 §3): the plain form when every target device in this build
    resolves `name` (the "no guard for a thing every target has"
    philosophy, `wfb/availability.py`'s `Guards` docstring), or wrapped in
    `if (Layout.FONT_<NAME>_AVAILABLE && (Graphics has :getVectorFont))`
    when `guards.vector_fonts` says at least one target does not.

    The `(Graphics has :getVectorFont)` runtime check and the build-time-
    baked `Layout.*_AVAILABLE` constant are not redundant with each other:
    `Graphics has :getVectorFont` is the only one of the two a device can
    answer about *itself* (constraint 6d -- `monkeyc` checks the SDK-wide
    API, not the device's, so an unguarded reference to a symbol this
    device lacks compiles fine everywhere and only fails at runtime), while
    "does the device's own catalogue include any of the requested faces"
    (gates 2/3) has no runtime query at all and has to be resolved at build
    time per device instead -- see `wfb.availability.vector_font_face`.
    Neither on its own is enough, and `-O 3z` is not relied on to fold
    either away (CLAUDE.md constraint on this exact point, plan 11 §3).
    """
    field = f"_{_field(name)}"
    prefix = f"FONT_{_const_prefix(name)}"
    assignment = (
        f"{field} = Graphics.getVectorFont("
        f"{{:face => Layout.{prefix}_FACE, :size => Layout.{prefix}_SIZE}});"
    )
    if name in guards.vector_fonts:
        w.comment(f"font.{name}: some target device in this build does not publish "
                 "any requested face")
        with w.block(f"if (Layout.{prefix}_AVAILABLE && (Graphics has :getVectorFont))"):
            w.line(assignment)
    else:
        w.line(assignment)


def _emit_on_layout(w: Writer, resolved: ResolvedFace, plan: "ReadPlan",
                    static: "StaticPlan | None" = None, guards: "Guards" = _NO_GUARDS) -> None:
    face = resolved.face
    loaded = _loaded_fonts(resolved)
    vector_fonts = _vector_fonts_used(resolved)
    event = plan.complication_readers()
    has_config = face.has_config
    w.doc("Load resources once.  Loading is expensive and must not happen per frame."
          + ("\n\nThis is also where the static content is painted, once, into its\n"
             "offscreen buffer -- every later frame just blits it." if static else "")
          + ("\n\nThe first config read happens here too, so the very first frame\n"
             "already reflects the wearer's own choice rather than the compiled-in\n"
             "default -- guarded, since a device with no native editor (fr955) has\n"
             "no WatchFaceConfig module to call at all." if has_config else ""))
    with w.block("function onLayout(dc as Dc) as Void"):
        if not loaded and not vector_fonts and not event and static is None and not has_config:
            w.line("// No resources to load: this face draws entirely from system fonts.")
        for name in loaded:
            resource = font_resource_id(name)
            w.line(
                f"_{_field(name)} = WatchUi.loadResource(Rez.Fonts.{resource}) as FontResource;"
            )
        if vector_fonts:
            if loaded:
                w.blank()
            for name in vector_fonts:
                _emit_vector_font_construction(w, name, guards)
        if event:
            if loaded or vector_fonts:
                w.blank()
            w.comment(
                "complications: one subscription per type, which keeps the "
                "platform's own reading fresh -- the value itself is pulled in "
                "onUpdate, not delivered here. WfbComplications.subscribe absorbs "
                "a device that does not support a given type"
            )
            if plan.device_guards.complications:
                # Unlike an unsupported *type* (WfbComplications.subscribe's own
                # job), a device that lacks Toybox.Complications entirely --
                # fenix6, fr245 -- fails on the bare reference to
                # registerComplicationChangeCallback/Complications.Id, before
                # WfbComplications is ever reached, so the guard has to sit
                # here, not in the barrel (CLAUDE.md: monkeyc checks the
                # SDK-wide API, not the device's -- this only fails at runtime).
                w.comment("Toybox.Complications is absent on at least one target device")
                with w.block("if (Toybox has :Complications)"):
                    _emit_complication_subscribe_lines(w, event)
            else:
                _emit_complication_subscribe_lines(w, event)
        if has_config:
            if loaded or event:
                w.blank()
            w.comment("the native on-device editor, where this device has one -- absent on")
            w.comment("fr955, which keeps running on the compiled-in defaults above")
            with w.block("if (Application has :WatchFaceConfig)"):
                w.line("var settings = WatchFaceConfig.getSettings(null);")
                with w.block("if (settings != null)"):
                    w.line("applyConfig(settings);")
        if static is not None:
            if loaded or event or has_config:
                w.blank()
            _emit_static_allocation(w, static)
    w.blank()


def _emit_on_update(w: Writer, resolved: ResolvedFace, plan: "ReadPlan", aod: bool,
                    static: "StaticPlan | None" = None,
                    antialias_default: bool | None = None,
                    jitter_ns: tuple[int, ...] = (),
                    guards: "Guards" = _NO_GUARDS) -> None:
    w.doc(
        "Draw the full face.\n"
        "\n"
        "Called once a minute in low-power mode and once a second while the watch is\n"
        "awake." + (
            "  While _aod (asleep, on a burn-in-protected device), draws the resolved\n"
            "'aod:' set instead -- see _aod, set by onEnterSleep/onExitSleep below -- or\n"
            "nothing at all if the device says the display itself is off (research 11 §6 F)."
            if aod else ""
        ) + (
            "  The static content comes first, as one blit of a buffer painted in\n"
            "onLayout -- or, on a device that could not allocate one, drawn straight\n"
            "onto the screen instead."
            if static is not None else ""
        ) + (
            "  Anti-aliasing is reset to the face default here, once, so it covers\n"
            "both the asleep and awake branches below; an element that overrides the\n"
            "default sets and restores it around its own drawing."
            if antialias_default is not None else ""
        )
    )
    with w.block("function onUpdate(dc as Dc) as Void"):
        w.line("dc.clearClip();")
        if antialias_default is not None:
            w.line(f"applyAntiAlias(dc, {_mc_bool(antialias_default)});")
        if aod:
            with w.block("if (_aod)"):
                _emit_aod_body(w, resolved, plan, jitter_ns, guards)
            with w.block("else"):
                _emit_mode_body(w, resolved, plan, "active", static)
        else:
            _emit_mode_body(w, resolved, plan, "active", static)
    w.blank()


def _emit_layout_guarded_calls(w: Writer, face: Face, calls: list) -> None:
    """Emit a sequence of ``(element, call_line)`` pairs, grouping
    *consecutive* calls whose ``element.layout`` agrees into one
    ``if (_configLayout == N) { ... }`` block; ``layout is None`` (shared
    content) emits with no guard at all -- **guards test the layout, never
    the config entry**: however many `config: style:` entries share one
    layout, this still emits only the one guard for it.

    The one place any draw sequence decides how a layout gates a call, so
    ``_emit_mode_body``, ``_emit_on_partial_update`` and
    ``_emit_static_methods``'s per-root calls in ``renderStatic`` cannot
    drift into guarding differently.  A design with no `layouts:` has
    ``element.layout is None`` on every element, so every call falls into
    the single unguarded branch below and the emitted sequence is exactly
    what it always was -- the golden files and the baseline byte-identity
    both rest on that.
    """
    index = 0
    total = len(calls)
    while index < total:
        element, line = calls[index]
        layout = element.layout
        end = index + 1
        while end < total and calls[end][0].layout == layout:
            end += 1
        if layout is None:
            for k in range(index, end):
                w.line(calls[k][1])
        else:
            guard = f"{CONFIG_LAYOUT_FIELD} == {face.layouts.index(layout)}"
            with w.block(f"if ({guard})"):
                for k in range(index, end):
                    w.line(calls[k][1])
        index = end


def _draw_calls(resolved: ResolvedFace, plan: "ReadPlan", mode: str,
                skip: frozenset[str] = frozenset()) -> list:
    """`(element, call_line)` pairs for every element drawn in ``mode``, in
    draw order -- shared by `_emit_mode_body` (which passes ``skip``, a
    static id already painted into the buffer) and `_emit_on_partial_update`
    (which never skips anything: it draws `low_power` fresh every call, with
    no static blit of its own).
    """
    calls = []
    for placed in resolved.items:
        if placed.kind == "group" or mode not in placed.element.modes:
            continue
        if placed.id in skip:
            continue  # painted into the buffer above
        calls.append((placed.element, f"{_method(placed.id)}(dc{plan.arguments(placed)});"))
    return calls


def _emit_mode_body(w: Writer, resolved: ResolvedFace, plan: "ReadPlan", mode: str,
                    static: "StaticPlan | None") -> None:
    """One mode's draw sequence: the static blit, then everything dynamic."""
    buffered = static is not None and mode in static.modes
    if buffered:
        _emit_static_blit(w, static)
        w.blank()
    # Reads everything unconditionally, layout guards included below -- a
    # read only a hidden layout's element uses is wasted work.  A real
    # optimisation (moving reads inside the guards) is left for later and
    # only worth doing if it is measured.
    plan.emit_reads(w, mode)
    w.blank()
    skip = static.ids if static is not None else set()
    calls = _draw_calls(resolved, plan, mode, skip)
    _emit_layout_guarded_calls(w, resolved.face, calls)


def _emit_aod_body(w: Writer, resolved: ResolvedFace, plan: "ReadPlan",
                   jitter_ns: tuple[int, ...] = (),
                   guards: "Guards" = _NO_GUARDS) -> None:
    """The AMOLED always-on frame (plan 14 slices 1-2): every element whose
    resolved `aod:` is not `None`, calling the exact same per-element method
    the active frame calls, restyled by the ternaries/branches those methods
    now read `_aod` through.

    **`DISPLAY_MODE_OFF` (plan 14 slice 6, research 11 §6 F): drawn nothing,
    before even the black clear.** `_aod` only narrows "asleep, on a
    burn-in-protected device" -- it says nothing about *which* of the FAQ's
    three display modes that device is actually in right now (research 11
    §2: `System.getDisplayMode`/`DISPLAY_MODE_*`/`Application.AppBase.
    onDisplayModeChanged`, none of which `_aod` reads). `DISPLAY_MODE_OFF`
    ("Display is off," `Toybox/System.html`) means the panel itself is
    unlit: no pixel this call could draw would ever become visible, so
    there is nothing to gain from drawing -- not even the black clear
    below, since clearing to black changes nothing an off panel would show
    either, and skipping it is strictly cheaper. The next call that finds
    the mode back at `DISPLAY_MODE_LOW_POWER` clears and redraws fresh, so
    nothing is left stale by skipping a frame here. Only emitted on a
    device that actually has the symbol (`Guards.display_mode_guarded`
    decides whether that needs a runtime `has` check or not, mirroring
    `Guards.burn_in_field_guarded`); a device lacking `getDisplayMode`
    (every device installed here except `fenix847mm`/`fenix947mm`, research
    11 §2) keeps the pre-slice-6 behaviour of drawing the resolved `aod:`
    set on every asleep frame, `_sleeping` as the only signal it has ever
    had.

    **A static element bypasses its buffer here** (plan 14 §4.4): the
    buffer is one opaque, all-or-nothing blit painted once, in `onLayout`,
    from the *active* styling, so it can never stand in for a restyled AOD
    frame. Its own generated method (`_method(placed.id)`) exists
    regardless of `static:` -- it is what `renderStatic` itself calls to
    fill the buffer in the first place (`_emit_static_methods`) -- so
    calling it a second time, directly, while `_aod`, costs nothing new to
    generate: this is simply no longer excluded from `entries` below.

    The element's own generated method already checks its plain `visible:`
    unconditionally (awake or asleep); only the *extra* condition an
    `aod: {visible: ...}` override contributes, if any, is checked here, at
    the call site (`ReadPlan.aod_guard_condition`).

    **Starts from black, unconditionally.** `Dc` keeps its contents between
    `onUpdate` calls -- there is no implicit clear -- and the awake frame's
    own background element (if it has one) is exactly what the active
    branch relies on for that. An `aod:`-drawn design's own resolved set
    almost never includes a full-screen background (the whole point is to
    light as little as possible), so without this the first AOD frame
    would draw its few elements over whatever the *last awake frame*
    happened to leave behind -- every pixel that frame lit stays lit,
    which is precisely the burn-in this feature exists to prevent. Black
    is the only correct AOD ground (research 11 §1.1: a pixel is "off"
    only when it renders black), so this is not configurable the way
    `renderStatic`'s own ground-clear isn't either.

    **`aod: {jitter: ...}` (plan 14 slice 5, §5.2): every distinct magnitude
    in `jitter_ns` gets its own `(dx, dy)`, computed once here**, from the
    current minute of day, via `WfbJitter.offsetX`/`offsetY` -- the same
    arithmetic `wfb.aod_jitter.offset` performs in Python, bit for bit
    (`tests/test_aod_jitter.py`). A dedicated local (`aodClock`), not the
    `clock` local `plan.emit_reads` may already have declared for an
    ordinary `time.clock`-bound element: the two would only collide by
    coincidence of naming, and this keeps this computation correct whether
    or not any element actually reads the clock too.
    """
    # `_emit_aod_body` is only ever called from inside `_emit_on_update`'s own
    # `if (_aod)` branch, itself only emitted when `aod` (== `guards.
    # amoled_target`) is true, so this check does not need to test that flag
    # again -- only whether the device (some, all, or none) actually has the
    # symbol, exactly the question `guards.display_mode_guarded` answers.
    w.comment("research 11 §6 F: the panel is unlit, so there is nothing to draw --")
    w.comment("not even the black clear below, which an off panel could not show anyway")
    condition = "System.getDisplayMode() == System.DISPLAY_MODE_OFF"
    if guards.display_mode_guarded:
        condition = f"(System has :getDisplayMode) && ({condition})"
    with w.block(f"if ({condition})"):
        w.line("return;")
    w.blank()
    w.comment("AOD starts from black: Dc keeps its contents between frames,")
    w.comment("and the awake frame's own background does not draw here")
    w.line("dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);")
    w.line("dc.clear();")
    if jitter_ns:
        w.comment("aod: {jitter: ...} -- this frame's own deterministic pixel offset(s)")
        w.line("var aodClock = System.getClockTime();")
        w.line("var aodMinuteOfDay = aodClock.hour * 60 + aodClock.min;")
        for n in jitter_ns:
            w.line(f"{_jitter_field(n, 'x')} = WfbJitter.offsetX(aodMinuteOfDay, {n});")
            w.line(f"{_jitter_field(n, 'y')} = WfbJitter.offsetY(aodMinuteOfDay, {n});")
        w.blank()
    plan.emit_reads(w, "aod")
    w.blank()
    ids = set(plan.aod_ids())
    entries = [placed for placed in resolved.items if placed.id in ids]
    _emit_layout_guarded_aod_calls(w, resolved.face, plan, entries)


def _emit_layout_guarded_aod_calls(w: Writer, face: Face, plan: "ReadPlan", entries: list) -> None:
    """`_emit_layout_guarded_calls`'s own layout-grouping shape, for the AOD
    branch: each call may need its own `var`-declarations and an `if` guard
    ahead of it (`_emit_one_aod_call`), which a flat `(element, line)` pair
    cannot carry, so this walks `entries` (`Placed`, not pre-rendered lines)
    directly instead of building on that helper.
    """
    index = 0
    total = len(entries)
    while index < total:
        placed = entries[index]
        layout = placed.element.layout
        end = index + 1
        while end < total and entries[end].element.layout == layout:
            end += 1
        if layout is None:
            for k in range(index, end):
                _emit_one_aod_call(w, plan, entries[k])
        else:
            guard = f"{CONFIG_LAYOUT_FIELD} == {face.layouts.index(layout)}"
            with w.block(f"if ({guard})"):
                for k in range(index, end):
                    _emit_one_aod_call(w, plan, entries[k])
        index = end


def _emit_one_aod_call(w: Writer, plan: "ReadPlan", placed) -> None:
    call = f"{_method(placed.id)}(dc{plan.arguments(placed)});"
    condition = plan.aod_guard_condition(placed)
    if condition is None:
        w.line(call)
        return
    for name, read in plan.aod_guard_declarations(placed):
        w.line(f"var {name} = {read};")
    w.comment(f"aod: visible: {placed.element.aod.visible_override.text}")
    with w.block(f"if ({condition})"):
        w.line(call)


def _emit_on_partial_update(w: Writer, resolved: ResolvedFace, plan: "ReadPlan",
                            antialias_default: bool | None = None) -> None:
    clip = resolved.clip_for("low_power")
    fraction = 100.0 * clip.area / (resolved.device.width * resolved.device.height) if clip else 0
    w.doc(
        "Redraw only the low-power elements, once a second, while asleep.\n"
        "\n"
        "The clip is the tightest box around them because setClip is charged by\n"
        f"region area: {fraction:.0f}% of the screen here.  Overrunning the power\n"
        "budget calls onPowerBudgetExceeded and disables partial updates for the\n"
        "rest of the app's lifecycle.  Nothing here is rate-limited by the\n"
        "compiler: since the refresh-tier concept was deleted, any source a\n"
        "low_power element binds -- weather.* and complication.* included --\n"
        "is read on every one of these updates.  The suppressible\n"
        "partial-update-budget lint is the only thing watching that."
    )
    with w.block("function onPartialUpdate(dc as Dc) as Void"):
        w.line(
            "dc.setClip(Layout.LOW_POWER_CLIP_X, Layout.LOW_POWER_CLIP_Y,"
        )
        w.line(
            "           Layout.LOW_POWER_CLIP_WIDTH, Layout.LOW_POWER_CLIP_HEIGHT);"
        )
        if antialias_default is not None:
            w.line(f"applyAntiAlias(dc, {_mc_bool(antialias_default)});")
        plan.emit_reads(w, "low_power")
        w.blank()
        calls = _draw_calls(resolved, plan, "low_power")
        _emit_layout_guarded_calls(w, resolved.face, calls)
        w.line("dc.clearClip();")
    w.blank()


def _emit_sleep_hooks(w: Writer, resolved: ResolvedFace, needs_sleeping: bool,
                      aod: bool, guards: "Guards" = _NO_GUARDS,
                      aod_only_fonts: list[str] | None = None,
                      jitter_ns: tuple[int, ...] = ()) -> None:
    aod_only_fonts = aod_only_fonts or []
    w.doc("Awake: full-power updates resume.")
    with w.block("function onExitSleep() as Void"):
        if needs_sleeping:
            w.line("_sleeping = false;")
        if aod:
            w.line("_aod = false;")
        for n in jitter_ns:
            # `aod: {jitter: ...}` (plan 14 §5.2): the shared per-element
            # draw method adds these unconditionally, awake or asleep
            # (`wfb.emit.monkeyc.common._jitter_terms`), so they must be
            # exactly 0 every moment the watch is not actually drawing a
            # jittered AOD frame -- reset here, the same place `_aod` itself
            # goes back to `false`, rather than trusting the *next*
            # `_emit_aod_body` run to overwrite them before anything reads
            # them (nothing reads them in the meantime, but zeroing on exit
            # is the one place this is true by construction, not by timing).
            w.line(f"{_jitter_field(n, 'x')} = 0;")
            w.line(f"{_jitter_field(n, 'y')} = 0;")
        for name in aod_only_fonts:
            # Released unconditionally, not only when it was actually
            # loaded -- nulling an already-null field is harmless, and this
            # is simpler than tracking whether onEnterSleep's own load ran
            # (plan 14 §4.3: "released in onExitSleep so it doesn't sit in
            # memory all the time").
            w.line(f"_{_aod_font_field(name)} = null;")
        w.line("WatchUi.requestUpdate();")
    w.blank()
    if aod:
        doc = ("Asleep: the next onUpdate draws the resolved 'aod:' set instead of\n"
               "'active', if this device requires burn-in protection.")
    elif needs_sleeping:
        # `aod` is unused: an awake-only second hand is the only other
        # reason `needs_sleeping` is true.
        doc = "Asleep: the next onUpdate hides the awake-only second hand."
    else:
        doc = "Asleep: the next onUpdate draws the low-power layout."
    w.doc(doc)
    with w.block("function onEnterSleep() as Void"):
        if needs_sleeping:
            w.line("_sleeping = true;")
        if aod:
            w.line("var settings = System.getDeviceSettings();")
            if guards.burn_in_field_guarded:
                w.line(
                    f"_aod = (settings has :{Device.BURN_IN_FIELD}) && "
                    f"settings.{Device.BURN_IN_FIELD};"
                )
            else:
                w.line(f"_aod = settings.{Device.BURN_IN_FIELD};")
            if aod_only_fonts:
                w.comment("plan 14 §4.3: loaded only now, only when this device actually")
                w.comment("enters the AOD frame -- never sits in memory while awake")
                with w.block("if (_aod)"):
                    for name in aod_only_fonts:
                        resource = font_resource_id(name)
                        w.line(
                            f"_{_aod_font_field(name)} = "
                            f"WatchUi.loadResource(Rez.Fonts.{resource}) as FontResource;"
                        )
        w.line("WatchUi.requestUpdate();")
    w.blank()
    if _has_partial_update(resolved):
        w.doc(
            "The power budget was exceeded and partial updates are now off for the\n"
            "rest of this app's lifecycle.  Nothing can re-enable them; the face\n"
            "simply falls back to once-a-minute updates."
        )
        with w.block("function onPowerBudgetExceeded(powerInfo as WatchUi.WatchFacePowerInfo) as Void"):
            w.line('System.println("wfb: partial-update power budget exceeded: "')
            w.line('               + powerInfo.executionTimeAverage.format("%.2f") + " ms average");')
        w.blank()


def _emit_complication_callback(w: Writer, plan: "ReadPlan") -> None:
    """`onComplicationChanged`: one callback, one statement.

    No cache: `Complications.getComplication(id)` is a plain pull that needs
    no prior subscription at all -- the SDK's own `ConfigurableWatchFace`
    sample calls it from `onLayout` before it subscribes, and again in edit
    mode where it never subscribes. So `onUpdate` reads complications the
    same ordinary way it reads `ActivityMonitor.getInfo()`, and nothing has
    to be stored between frames.

    What is left is only the redraw: a complication can change between two
    scheduled updates, and this is how the face learns to draw sooner.  The
    subscription in `onLayout` remains for the same reason -- it is what keeps
    the platform's own value fresh, which is a different thing from caching it
    here.  See `docs/research/probes/complication-pull/`.
    """
    w.doc(
        "A subscribed complication changed.  Nothing is stored: onUpdate pulls\n"
        "every complication it needs, so this only asks for an earlier redraw\n"
        "than the next scheduled one."
    )
    with w.block("function onComplicationChanged(id as Complications.Id) as Void"):
        w.line("WatchUi.requestUpdate();")
    w.blank()


# --------------------------------------------------------------------------
# one method per element


def _emit_element_method(w: Writer, resolved: ResolvedFace, placed, plan: "ReadPlan",
                         antialias_default: bool | None = None, aod: bool = False,
                         dim: AodDim = None) -> None:
    element = placed.element
    w.doc(_method_doc(placed))
    signature = f"private function {_method(placed.id)}(dc as Dc{plan.parameters(placed)}) as Void"
    # 'placeholder'/'fallback' are policies for the *value* -- a substitute
    # text or fill fraction takes over instead of the element simply not
    # drawing.  They say nothing about a nullable colour, track colour or
    # max: there is no placeholder for a colour, so those always get a real
    # guard regardless of which policy the value chose.
    substitutes_value = (
        isinstance(placed, (PlacedText, PlacedProgress))
        and getattr(element, "when_absent", None) in ("placeholder", "fallback")
    )
    with w.block(signature):
        declarations = plan.declarations(placed)
        if declarations:
            w.comment("the values this element is bound to")
            for name, read in declarations:
                w.line(f"var {name} = {read};")
            w.blank()
        _emit_visible_guard(w, placed, plan)
        if isinstance(placed, PlacedComplicationSlot):
            # Deliberately no element-level guard: the reading is not an
            # element-level binding at all (it is a fresh per-frame pull off
            # a wearer-editable `Complications.Id`), so there is nothing for
            # `plan.guards`/`value_guards` to say about it -- `color:` is the
            # only ordinary expression here, and `Builder._build_complication_
            # slot` already requires it to be non-nullable.
            _emit_complication_slot(w, resolved, placed, plan.device_guards, aod, dim)
            return
        value_guards = plan.value_guards(placed)
        if substitutes_value:
            other_guards = plan.other_guards(placed)
            if other_guards:
                _emit_guard(w, placed, other_guards,
                           note="hide -- a nullable colour/track_color/max always hides "
                                "the element, regardless of the value's own when_absent")
        else:
            other_guards = plan.guards(placed)
            if other_guards:
                _emit_guard(w, placed, other_guards)
        # Anti-aliasing only ever varies for a primitive-drawing element
        # (`ANTIALIASED_PRIMITIVES`) -- text and icons draw glyphs, whose anti-aliasing is a font-resource matter
        # (baked at build time, see wfb.icons/wfb.fonts), not a per-frame Dc
        # call, so they emit no setAntiAlias-related code at all.  The toggle
        # brackets only the actual drawing call below, deliberately *after*
        # every guard above: a guard can return early, and doing this any
        # earlier would leave the Dc's anti-alias state changed on a frame
        # that drew nothing, breaking the invariant every other draw method
        # relies on -- that Dc is already at the face default by the time its
        # own drawing runs.
        overrides_antialias = (
            antialias_default is not None
            and isinstance(placed, ANTIALIASED_PRIMITIVES)
            and element.resolved_antialias != antialias_default
        )
        if overrides_antialias:
            w.comment(f"antialias: {_mc_bool(element.resolved_antialias)}")
            w.line(f"applyAntiAlias(dc, {_mc_bool(element.resolved_antialias)});")
        if isinstance(placed, PlacedShape):
            _emit_shape(w, placed, aod, dim)
        elif isinstance(placed, PlacedText):
            _emit_text(w, resolved, placed, value_guards, aod, dim)
        elif isinstance(placed, PlacedProgress):
            _emit_progress(w, placed, value_guards, aod, dim)
        elif isinstance(placed, PlacedIcon):
            _emit_icon(w, placed, aod, dim)
        elif isinstance(placed, PlacedGraph):
            _emit_graph(w, placed, aod, dim)
        elif isinstance(placed, PlacedHands):
            _emit_hands(w, placed, aod, dim)
        elif isinstance(placed, PlacedPattern):
            _emit_pattern(w, placed, aod, dim)
        if overrides_antialias:
            w.line(f"applyAntiAlias(dc, {_mc_bool(antialias_default)});")


def _method_doc(placed) -> str:
    element = placed.element
    lines = [f"`{element.id}` -- {_describe(placed)}."]
    # `visible:` gets its own line below rather than being listed as a
    # binding: it says when the element draws, not what it shows.
    bindings = [e.text for e in element.expressions()
                if e.sources and e is not element.visible]
    if bindings:
        lines.append("")
        lines.append("Bound to " + _and_list(f"`{text}`" for text in bindings) + ".")
    if element.visible is not None:
        lines.append(f"Drawn only when `{element.visible.text}` "
                     "(absent readings count as hidden).")
    policy = getattr(element, "when_absent", None)
    if policy:
        lines.append(f"When the value is absent: {policy}.")
    modes = ", ".join(element.modes)
    lines.append(f"Drawn in: {modes}.")
    return "\n".join(lines)


def _negated(expression) -> str:
    """The Monkey C for "this condition does **not** hold".

    A condition that is itself a `not` is un-negated rather than wrapped: the
    guard for `visible: "not system.charging"` reads `if (systemCharging)`, not
    `if (!(!systemCharging))`, which is not something a person would have
    written.  `expr.emit` renders a `not` as exactly `(!<operand>)`, so this is
    a slice off a known shape rather than a second, drifting emitter.
    """
    code = expression.code
    node = expression.ast
    if isinstance(node, expr.Unary) and node.op == "not":
        assert code.startswith("(!") and code.endswith(")"), code
        return code[2:-1]
    return f"!{_negatable(code)}"


def _negatable(code: str) -> str:
    """``code`` wrapped in parentheses unless it already is one group.

    `expr.emit` parenthesises every operator it emits, so a condition almost
    always arrives as `(a < b)` and `!((a < b))` would be the honest but
    unreadable result of wrapping it again.  Only a single enclosing group
    counts: `(a) || (b)` starts and ends with a bracket without being one.
    """
    if not (code.startswith("(") and code.endswith(")")):
        return f"({code})"
    depth = 0
    for index, char in enumerate(code):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and index != len(code) - 1:
                return f"({code})"
    return code


def _emit_visible_guard(w: Writer, placed, plan: "ReadPlan") -> None:
    """`visible:` -- one guard covering both absence and the condition.

    Emitted before every other guard, and before a complication_slot's own
    early return, because visibility gates the element as a whole.

    The shape is `if (x == null || !(cond)) { return; }`, one `== null` per
    nullable local the condition reads.  That is "absent means hidden" written
    out: there is no `when_absent:` for existence, so an unavailable reading
    and a false condition are the same outcome and belong in the same test.
    Verified that `monkeyc` narrows the local across the `||` -- the condition
    on the right dereferences it -- with a real warning-free `-w` build under
    the jungle's `project.typecheck = strict`.

    A condition that folded to a build-time constant is handled honestly
    rather than specially: a constant `true` emits nothing (there is nothing
    to check), and a constant `false` emits the guard as written, which
    `monkeyc` accepts without an unreachable-code warning (verified the same
    way) and `-O 3z` folds away.  The `dead-element` lint is what tells the
    author about the second case.
    """
    element = placed.element
    expression = element.visible
    if expression is None:
        return
    if expression.constant is not None and expression.constant:
        w.comment(f"visible: {expression.text} -- always true, nothing to check")
        w.blank()
        return
    parts = [f"{name} == null" for name in plan.visible_guards(placed)]
    parts.append(_negated(expression))
    w.comment(f"visible: {expression.text}"
              + (" -- absent means hidden" if len(parts) > 1 else ""))
    with w.block(f"if ({' || '.join(parts)})"):
        w.line("return;")
    w.blank()


def _emit_guard(w: Writer, placed, guards: list[str], note: str | None = None) -> None:
    """Emit the null check, and say which `when_absent:` produced it.

    ``note`` overrides the default "when_absent: <policy>" comment for the
    case where the guard covers only bindings the value's own policy does
    not govern -- a nullable colour still just hides the element even when
    the value itself falls back to a placeholder.
    """
    element = placed.element
    condition = " || ".join(f"{name} == null" for name in guards)
    w.comment(note if note is not None else f"when_absent: {getattr(element, 'when_absent', None) or 'hide'}")
    with w.block(f"if ({condition})"):
        w.line("return;")
    w.blank()
