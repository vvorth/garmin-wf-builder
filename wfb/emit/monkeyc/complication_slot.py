"""Element emitter for `complication_slot`, and its on-device config-editor plumbing."""

from __future__ import annotations

from ... import complications
from ...availability import Guards
from ...ir import (
    Face, complication_slot_hold_method, complication_slot_icon_method, config_data_ids,
    config_field, element_method_name,
)
from ...layout import COMPLICATION_SLOT_ICON_GAP, PlacedComplicationSlot, ResolvedFace
from .common import SourceFile, _NO_GUARDS, _color, _const_prefix, _field, header
from ..writer import Writer


def _emit_pulsing_field(w: Writer) -> None:
    """`_pulsing` -- which complication_slot the native editor is currently
    animating (a `config_data_ids` unique id), or 0 for none.

    Read by every `complication_slot`'s own draw method
    (`_emit_complication_slot`'s guard) and written only from `setPulsing`,
    itself called only from the delegate's `getComplicationDrawable` -- which
    fires solely inside the on-device config editor
    (`docs/research/07-carousel-interaction.md`), so this stays 0 for the
    entire life of the app on a device with no editor, or while the face is
    simply being looked at.
    """
    w.doc(
        "Which complication_slot the native editor is animating right now (a\n"
        "config_data_ids unique id), or 0 for none.  Read by every\n"
        "complication_slot's own draw method so the system does not see it drawn\n"
        "twice while it pulses."
    )
    w.line("private var _pulsing as Number = 0;")
    w.blank()


def _emit_complication_slot_editor_methods(w: Writer, face: Face, pairs: list) -> None:
    """`setPulsing`/`drawSlot`/`drawableFor` -- the view's half of the native
    editor's animated highlight (`onTap`/`getComplicationDrawable` live on
    the delegate).  Only ever emitted when ``pairs`` (`_editor_slot_pairs`)
    is non-empty.

    `drawSlot` is the one new *public* surface a `complication_slot`'s own
    draw method needs: Monkey C's `private` genuinely blocks a cross-class
    call (verified by building both ways -- dropping the modifier turns
    "Cannot find symbol ':drawTopReading'" into a clean build) -- so rather
    than making every per-slot draw method public, one small dispatcher is,
    and the per-slot methods stay private like every other element's.
    """
    w.doc(
        "The native editor is telling this view which slot it is about to "
        "animate.\n\nOnly ever called from getComplicationDrawable, which "
        "fires solely inside\nthe on-device config editor (research 07 1a)."
    )
    with w.block("function setPulsing(unique as Number) as Void"):
        w.line("_pulsing = unique;")
    w.blank()

    w.doc(
        "Draw one complication_slot by its config_data_ids unique id -- the "
        "one\npublic entry point the generated SlotDrawable needs, so every "
        "per-slot\ndraw method itself can stay private like every other "
        "element's."
    )
    with w.block("function drawSlot(dc as Dc, unique as Number) as Void"):
        with w.block("switch (unique)"):
            for element, unique_id in pairs:
                w.line(f"case {unique_id}: {element_method_name(element.id)}(dc); break;")
    w.blank()

    w.doc(
        "Build the Drawable the editor animates for one slot, from that slot's "
        "own\nresolved box -- the same estimate the safe-area/overlap lints "
        "already\naccept, since the real drawn extent depends on content this "
        "element does\nnot know until the device pulls it.\n\n"
        "UNVERIFIED whether the box the editor animates actually lines up with "
        "what\nis drawn -- no simulator runs in this container and there is no "
        "watch."
    )
    with w.block(
        "function drawableFor(unique as Number) as WatchUi.ComplicationDrawableRef or Null",
    ):
        w.line("var drawable = null;")
        with w.block("switch (unique)"):
            for element, unique_id in pairs:
                prefix = _const_prefix(element.id)
                w.line(f"case {unique_id}: drawable = new {face.entry}SlotDrawable(self, {unique_id},")
                w.line(f"    Layout.{prefix}_BOX_X, Layout.{prefix}_BOX_Y,")
                w.line(f"    Layout.{prefix}_BOX_WIDTH, Layout.{prefix}_BOX_HEIGHT); break;")
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
    least one `complication_slot` element (`_editor_slot_pairs`): the whole
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
        "UNVERIFIED whether the animation this exists to support actually "
        "happens\nor lines up with what is drawn -- no simulator runs in this "
        "container and\nthere is no watch.  What is verified: this compiles "
        "warning-free on every\ntarget, including fr955, which has no editor "
        "and so never constructs one."
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


def _emit_complication_slot_hold_method(w: Writer, placed: PlacedComplicationSlot,
                                        guards: "Guards" = _NO_GUARDS) -> None:
    """`holdTargetFor<Id>()` -- the public getter `on_hold: auto` on a
    `complication_slot` compiles to, returning this slot's own current
    `Complications.Id` field directly.

    Public, unlike every draw method: the delegate is a different class and
    Monkey C's `private` genuinely blocks a cross-class call (verified by
    building both ways).  Only emitted for a slot that actually declares
    `on_hold: auto` -- `Builder._build_complication_slot` restricts a slot to
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
    w.blank()
    w.doc(f"`{element.id}`'s icon, chosen from the wearer's picked type alone -- not\n"
          "from the pulled value, so it still shows even on a frame the reading itself\n"
          "could not be pulled.")
    method = complication_slot_icon_method(element.id)
    with w.block(f"private function {method}(t as Complications.Type) as String?"):
        with w.block("switch (t)"):
            for name in names:
                icon = mapped.get(name)
                if icon is None:
                    continue
                ctype = complications.TYPES[name]
                w.line(f'case Complications.{ctype.constant}: return "{icon.key}";')
            w.line("default: return null;")
    w.blank()


    # `IconGlyphs.glyph` turns the catalogue name into the actual character --
    # see `emit_icon_glyphs`'s own docstring for why a name, not a raw
    # character, is what this method should have produced in the first
    # place, matching the weather-icon split.


def _emit_complication_slot(w: Writer, resolved: ResolvedFace, placed: PlacedComplicationSlot,
                            guards: "Guards" = _NO_GUARDS) -> None:
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
    prefix = _const_prefix(placed.id)
    face = resolved.face
    field = config_field(f"data_{element.slot}")
    unique = config_data_ids(face)[element.slot]

    w.comment("the editor is animating this exact slot right now -- skip it, or the")
    w.comment("system draws it twice while it pulses (SDK sample's own comment)")
    with w.block(f"if (_pulsing == {unique})"):
        w.line("return;")
    w.blank()
    w.comment(f"slot: config.data.{element.slot}")
    w.line(f"var chosenId = {field};")

    icon_font_expr = None
    if placed.icon_font_key is not None:
        w.line(f"var iconFont = _{_field(placed.icon_font_key)};")
        w.comment("the icon is chosen from the wearer's picked *type*, so it still shows")
        w.comment("even on a frame the reading itself could not be pulled -- a name")
        w.comment("(WfbComplications-style split), then IconGlyphs.glyph turns it into")
        w.comment("the actual character, exactly like a dynamic weather icon does")
        icon_method = complication_slot_icon_method(element.id)
        if guards.complications:
            w.line(f"var iconName = (chosenId != null) ? {icon_method}(chosenId.getType()) : null;")
        else:
            w.line(f"var iconName = {icon_method}(chosenId.getType());")
        w.line("var iconGlyph = (iconName != null) ? IconGlyphs.glyph(iconName) : null;")
        w.blank()
        icon_font_expr = "iconFont"

    if placed.font_is_custom:
        w.line(f"var textFont = _{_field(placed.font_reference)};")
        with w.block("if (textFont == null)"):
            w.line("return;  // the font resource failed to load")
        font_expr = "textFont"
    else:
        font_expr = f"Graphics.{placed.font_reference}"
    w.blank()

    def _emit_absent() -> None:
        if element.when_absent == "placeholder":
            w.comment("when_absent: placeholder")
            w.line(f'text = "{element.placeholder}";')
        else:
            w.comment("when_absent: hide -- the reading blanks, the icon (if any) stays")

    w.line('var text = "";')
    if guards.complications:
        w.line("var pulled = (chosenId != null) ? WfbComplications.valueOf(chosenId) : null;")
    else:
        w.line("var pulled = WfbComplications.valueOf(chosenId);")
    with w.block("if (pulled == null)"):
        _emit_absent()
    with w.block("else"):
        # `pulled.value` is read into its own local, and narrowed through
        # *that* local rather than re-read off `pulled` -- monkeyc cannot
        # narrow a null check across a repeated field-access expression
        # (CLAUDE.md), only across a local variable, and `pulled` itself
        # stays narrowed for the whole of this `else` (it never leaves that
        # local's own guarded scope), which is what still lets `pulled.
        # shortLabel`/`.longLabel`/`.unit` below be read unconditionally.
        w.line("var value = pulled.value;")
        with w.block("if (value == null)"):
            _emit_absent()
        with w.block("else"):
            if element.label in ("short", "long"):
                attr = "shortLabel" if element.label == "short" else "longLabel"
                w.line(f"var label = pulled.{attr};")
                with w.block("if (label != null)"):
                    w.line('text = label + " ";')
            w.line("text += WfbComplications.formatValue(value);")
            if element.unit:
                w.line("text += WfbComplications.unitSuffix(pulled.unit);")
    w.blank()

    text_color_expr = _color(element.color)
    icon_color_expr = _color(element.icon_color) if element.icon_color is not None else None
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

    if placed.icon_position in ("left", "right"):
        # 'textWidth'/'iconGlyphWidth'/'gap' are declared only when something
        # actually reads them afterwards -- not merely when the value could
        # in principle be non-zero. The position's own final offset for
        # 'left' is unconditional (it always adds 'iconGlyphWidth + gap',
        # icon present or not), but for 'right' the offset that reads
        # 'textWidth + gap' sits inside 'if (icon_present_guard)' -- when
        # this slot can never draw an icon at all (`has_icon` false: no
        # choice resolves one), that whole block is never emitted, so
        # 'textWidth'/'gap' would be declared and never read again unless
        # 'totalWidth' below also needs them (whenever 'align:' is not
        # 'left'). Checked exhaustively in `tests/test_align_glyph_kinds.py`
        # (every `icon_position:` x every `align:`/`vertical_align:` x
        # icon-present/icon-less).
        need_icon_glyph_width = placed.icon_position == "left" or element.align != "left"
        need_text_width = (placed.icon_position == "right" and has_icon) or element.align != "left"
        need_gap = (
            placed.icon_position == "left"
            or (placed.icon_position == "right" and has_icon)
            or element.align != "left"
        )
        if need_text_width:
            w.line(f"var textWidth = dc.getTextWidthInPixels(text, {font_expr});")
        if need_icon_glyph_width:
            w.line("var iconGlyphWidth = 0;")
            if icon_present_guard is not None:
                with w.block(f"if ({icon_present_guard})"):
                    w.line(f"iconGlyphWidth = dc.getTextWidthInPixels(iconGlyph, {icon_font_expr});")
        if need_gap:
            w.line(f"var gap = ({icon_present_guard}) ? {gap_expr} : 0;"
                   if icon_present_guard is not None else "var gap = 0;")
        # 'align:' shifts the row's horizontal start: 'startX = CX - {0,
        # total/2, total}' for left/center/right -- center
        # is the plain expression above with no shift. 'totalWidth' is declared only when
        # 'align:' actually reads it ('left' does not -- an unused local
        # warns under -l 3).
        if element.align == "left":
            w.line(f"var startX = Layout.{prefix}_CX;")
        elif element.align == "right":
            w.line("var totalWidth = iconGlyphWidth + gap + textWidth;")
            w.line(f"var startX = Layout.{prefix}_CX - totalWidth;")
        else:
            w.line("var totalWidth = iconGlyphWidth + gap + textWidth;")
            w.line(f"var startX = Layout.{prefix}_CX - totalWidth / 2;")
        if element.vertical_align == "center":
            row_y_expr = f"Layout.{prefix}_CY"
        else:
            # 'vertical_align:' shifts the row's own VCENTER axis by half the
            # taller of the two drawn fonts' heights --
            # measured on-device, since only one of the two may draw at all
            # (an icon-less slot, or a frame the icon glyph did not resolve).
            w.line(f"var rowHeight = dc.getFontHeight({font_expr});")
            if icon_present_guard is not None:
                with w.block(f"if ({icon_present_guard})"):
                    w.line(f"var iconRowHeight = dc.getFontHeight({icon_font_expr});")
                    with w.block("if (iconRowHeight > rowHeight)"):
                        w.line("rowHeight = iconRowHeight;")
            if element.vertical_align == "top":
                w.line(f"var rowY = Layout.{prefix}_CY + rowHeight / 2;")
            else:  # bottom
                w.line(f"var rowY = Layout.{prefix}_CY - rowHeight / 2;")
            row_y_expr = "rowY"
        if placed.icon_position == "left":
            if icon_present_guard is not None:
                with w.block(f"if ({icon_present_guard})"):
                    _set_icon_color()
                    w.line(f"dc.drawText(startX, {row_y_expr}, {icon_font_expr}, iconGlyph,")
                    w.line("            Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER);")
            _reset_text_color()
            w.line(f"dc.drawText(startX + iconGlyphWidth + gap, {row_y_expr}, {font_expr}, text,")
            w.line("            Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER);")
        else:  # right
            w.line(f"dc.drawText(startX, {row_y_expr}, {font_expr}, text,")
            w.line("            Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER);")
            if icon_present_guard is not None:
                with w.block(f"if ({icon_present_guard})"):
                    _set_icon_color()
                    w.line(f"dc.drawText(startX + textWidth + gap, {row_y_expr}, "
                           f"{icon_font_expr}, iconGlyph,")
                    w.line("            Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER);")
    else:  # "top" / "bottom"
        # Same reasoning as the left/right branch above, on the vertical
        # axis, `has_icon` included: 'top's own final offset (unconditional)
        # always reads 'iconHeight + gap'; 'bottom's matching offset reads
        # 'textHeight + gap' only inside 'if (icon_present_guard)', which is
        # never emitted at all when this slot can draw no icon
        # ('has_icon` false). 'totalHeight' below needs all three, but only
        # when 'vertical_align:' is not 'top'.
        need_icon_height = placed.icon_position == "top" or element.vertical_align != "top"
        need_text_height = (placed.icon_position == "bottom" and has_icon) or element.vertical_align != "top"
        need_gap = (
            placed.icon_position == "top"
            or (placed.icon_position == "bottom" and has_icon)
            or element.vertical_align != "top"
        )
        if need_text_height:
            w.line(f"var textHeight = dc.getFontHeight({font_expr});")
        if need_icon_height:
            w.line("var iconHeight = 0;")
            if icon_present_guard is not None:
                with w.block(f"if ({icon_present_guard})"):
                    w.line(f"iconHeight = dc.getFontHeight({icon_font_expr});")
        if need_gap:
            w.line(f"var gap = ({icon_present_guard}) ? {gap_expr} : 0;"
                   if icon_present_guard is not None else "var gap = 0;")
        # 'vertical_align:' shifts the column's vertical start: 'startY = CY
        # - {0, total/2, total}' for top/center/bottom --
        # center is the plain expression above with no shift. 'totalHeight' is declared
        # only when 'vertical_align:' actually reads it ('top' does not --
        # an unused local warns under -l 3).
        if element.vertical_align == "top":
            w.line(f"var startY = Layout.{prefix}_CY;")
        elif element.vertical_align == "bottom":
            w.line("var totalHeight = iconHeight + gap + textHeight;")
            w.line(f"var startY = Layout.{prefix}_CY - totalHeight;")
        else:
            w.line("var totalHeight = iconHeight + gap + textHeight;")
            w.line(f"var startY = Layout.{prefix}_CY - totalHeight / 2;")
        if element.align == "center":
            col_x_expr = f"Layout.{prefix}_CX"
        else:
            # 'align:' shifts the pair's own TEXT_JUSTIFY_CENTER axis by half
            # the wider of the two drawn pieces -- the same
            # "measure both, take the icon-guarded max" shape as the row case
            # above, on the perpendicular axis.
            w.line(f"var textWidth = dc.getTextWidthInPixels(text, {font_expr});")
            w.line("var iconGlyphWidth = 0;")
            if icon_present_guard is not None:
                with w.block(f"if ({icon_present_guard})"):
                    w.line(f"iconGlyphWidth = dc.getTextWidthInPixels(iconGlyph, {icon_font_expr});")
            w.line("var pairWidth = (iconGlyphWidth > textWidth) ? iconGlyphWidth : textWidth;")
            if element.align == "left":
                w.line(f"var pairX = Layout.{prefix}_CX + pairWidth / 2;")
            else:  # right
                w.line(f"var pairX = Layout.{prefix}_CX - pairWidth / 2;")
            col_x_expr = "pairX"
        if placed.icon_position == "top":
            if icon_present_guard is not None:
                with w.block(f"if ({icon_present_guard})"):
                    _set_icon_color()
                    w.line(f"dc.drawText({col_x_expr}, startY, {icon_font_expr}, iconGlyph,")
                    w.line("            Graphics.TEXT_JUSTIFY_CENTER);")
            _reset_text_color()
            w.line(f"dc.drawText({col_x_expr}, startY + iconHeight + gap, {font_expr}, text,")
            w.line("            Graphics.TEXT_JUSTIFY_CENTER);")
        else:  # bottom
            w.line(f"dc.drawText({col_x_expr}, startY, {font_expr}, text,")
            w.line("            Graphics.TEXT_JUSTIFY_CENTER);")
            if icon_present_guard is not None:
                with w.block(f"if ({icon_present_guard})"):
                    _set_icon_color()
                    w.line(f"dc.drawText({col_x_expr}, startY + textHeight + gap, "
                           f"{icon_font_expr}, iconGlyph,")
                    w.line("            Graphics.TEXT_JUSTIFY_CENTER);")
