"""`Layout.mc` -- per-device layout constants resolved at build time."""

from __future__ import annotations

from ...availability import Guards, vector_font_face
from ...layout import (
    PlacedComplicationSlot, PlacedGraph, PlacedHands, PlacedIcon, PlacedPattern,
    PlacedProgress, PlacedShape, PlacedText, ResolvedFace,
)
from .common import (
    McLiteral, SourceFile, _NO_GUARDS, _const_prefix, _describe, _mc_number, _mc_type,
    _vector_fonts_used, header,
)
from ..writer import Writer


# --------------------------------------------------------------------------
# per-device layout constants


def _emit_constants(
    w: Writer, constants: list[tuple[str, float | str | bool | McLiteral, str]],
) -> None:
    """Render one `const NAME as TYPE = VALUE;  // note` block -- the one
    place a `Layout` constant is rendered, shared by the font-name-level
    block (`_emit_vector_font_constants`) and the per-placed-element loop
    below, so the two cannot silently drift into two different renderings
    of the same `(name, value, note)` shape.
    """
    for name, value, note in constants:
        suffix = f"  // {note}" if note else ""
        w.line(f"const {name} as {_mc_type(value)} = {_mc_number(value)};{suffix}")


def _vector_font_constants(
    resolved: ResolvedFace, name: str, guards: "Guards",
) -> list[tuple[str, float | str | bool | McLiteral, str]]:
    """The `Layout` constants for one used `face:` (vector) font, by name
    (plan 11 §3) -- `FONT_<NAME>_FACE`/`_SIZE` always, `_AVAILABLE` only
    when `guards.vector_fonts` says at least one *target* device in this
    build fails to resolve it (`wfb.emit.monkeyc.view._emit_on_layout`'s
    guarded construction reads it; the plain form does not, and the
    "no guard for a thing every target has" philosophy means it is not
    emitted for anything else -- `wfb/availability.py`'s `compute_guards`
    docstring).

    `_FACE`/`_SIZE` are resolved **for this one device**
    (`resolved.device`), independent of any element's own `curve:`
    (`wfb.availability.vector_font_face`'s own docstring says why) --
    empty-string `_FACE` on a device that fails to resolve it, which the
    generated `if (font != null)` at the draw call site (never omitted,
    gate 4) already keeps from ever reaching a real draw call.
    """
    face, device = resolved.face, resolved.device
    spec = face.fonts[name]
    prefix = f"FONT_{_const_prefix(name)}"
    resolved_face = vector_font_face(spec, device)
    size_px = spec.pixel_size(device.minor_radius)
    requested = ", ".join(spec.face)
    out: list[tuple[str, float | str | bool | McLiteral, str]] = [
        (f"{prefix}_FACE", resolved_face,
         f"requested, in author order: {requested}" if resolved_face
         else f"none of [{requested}] is published on {device.id}"),
        (f"{prefix}_SIZE", size_px, ""),
    ]
    if name in guards.vector_fonts:
        out.append((
            f"{prefix}_AVAILABLE", resolved_face != "",
            f"{device.id} {'publishes' if resolved_face else 'does not publish'} "
            "a usable face -- some other target in this build does not, so the "
            "shared view guards construction on this constant",
        ))
    return out


def emit_layout(resolved: ResolvedFace, guards: "Guards" = _NO_GUARDS) -> SourceFile:
    face, device = resolved.face, resolved.device
    w = Writer()
    w.doc(
        header(
            face,
            f"Device:    {device.id} -- {device.width}x{device.height} {device.shape}, "
            f"{device.display_type}, family {device.device_family}",
        )
    ).blank()
    # Toybox.Graphics only when something here is typed against it: a polygon's
    # point array is `Array<Graphics.Point2D>`, and Point2D is the fixed-size
    # `[Numeric, Numeric]` tuple type, not `Array<Number>` (verified by
    # building -- docs/research/probes/polygon-const/).
    needs_graphics = any(
        (isinstance(p, PlacedShape) and p.element.shape == "polygon")
        or (isinstance(p, PlacedHands) and _hands_needs_graphics(p))
        or (isinstance(p, PlacedPattern) and _pattern_needs_graphics(p))
        for p in resolved.items
    )
    imports = ["import Toybox.Graphics;", "import Toybox.Lang;"] if needs_graphics \
        else ["import Toybox.Lang;"]
    w.lines(*imports).blank()
    w.doc(
        f"Layout resolved for {device.id}.\n"
        "\n"
        "Every value here came from a relative unit in the design -- percentages of\n"
        "the parent box, fractions of the screen's minor radius, angles measured\n"
        "clockwise from 12 o'clock.  Resolving them here means the device performs\n"
        "no layout arithmetic at all, which costs neither memory nor frame time."
    )
    with w.block("module Layout"):
        w.doc("The screen, for reference.")
        w.line(f"const SCREEN_WIDTH as Number = {device.width};")
        w.line(f"const SCREEN_HEIGHT as Number = {device.height};")
        vector_fonts = _vector_fonts_used(resolved)
        if vector_fonts:
            w.blank()
            w.doc(
                "Device-resident scalable ('face:') fonts this design draws with "
                "(plan 11).\n"
                "\n"
                "'_FACE'/'_SIZE' feed Graphics.getVectorFont directly, in onLayout.\n"
                "'_AVAILABLE' is emitted only for a font at least one target device in\n"
                "this build fails to publish -- the shared view (identical on every\n"
                "device) reads it to decide whether to even attempt construction here,\n"
                "so every device's own Layout.mc has to define it once any device\n"
                "needs it (wfb.availability.Guards.vector_fonts)."
            )
            for name in vector_fonts:
                w.blank()
                w.doc(f"`font.{name}`")
                _emit_constants(w, _vector_font_constants(resolved, name, guards))
        for placed in resolved.items:
            constants = _layout_constants(placed) + _hold_constants(placed)
            if not constants:
                continue
            w.blank()
            w.doc(f"`{placed.id}` -- {_describe(placed)}")
            _emit_constants(w, constants)
        clip = resolved.clip_for("low_power")
        if clip is not None:
            w.blank()
            w.doc(
                "The clip rectangle for low-power updates.\n"
                "\n"
                "setClip is charged by region *area* -- every pixel inside it counts as\n"
                "modified whenever any does -- so this is the tightest box covering all\n"
                f"low-power elements: {clip.area} px, "
                f"{100.0 * clip.area / (device.width * device.height):.0f}% of the screen."
            )
            w.line(f"const LOW_POWER_CLIP_X as Number = {clip.x};")
            w.line(f"const LOW_POWER_CLIP_Y as Number = {clip.y};")
            w.line(f"const LOW_POWER_CLIP_WIDTH as Number = {clip.width};")
            w.line(f"const LOW_POWER_CLIP_HEIGHT as Number = {clip.height};")
    return SourceFile(f"source-{device.id}/Layout.mc", w.render())


def _hands_needs_graphics(placed: "PlacedHands") -> bool:
    """Does this `type: hands` element draw at least one polygon part (a
    rectangle part folded in) -- the only shape that needs
    `Array<Graphics.Point2D>`, hence `Toybox.Graphics` in scope."""
    for hand in (placed.hour, placed.minute, placed.second):
        if hand is None:
            continue
        if any(part.shape == "polygon" for part in hand.parts):
            return True
    return False


def _pattern_needs_graphics(placed: "PlacedPattern") -> bool:
    """Does this `type: pattern` draw at least one polygon part (a rectangle
    part folded in) -- the same "needs `Array<Graphics.Point2D>`" test
    `_hands_needs_graphics` runs for a hand, generalised: a pattern has one
    flat template rather than up to three named hands.  A `shape: text` part
    needs no entry here: its `Layout` constants are plain `Number`s (an
    anchor `_X`/`_Y`, no point array), so it never forces `Toybox.Graphics`
    into the `Layout` module's own imports -- only the view file, which
    already imports `Toybox.Graphics` unconditionally, ever types anything
    against `Graphics.FontType`."""
    return any(part.shape == "polygon" for part in placed.parts)


def _hold_constants(placed) -> list[tuple[str, float, str]]:
    """The hit rectangle for an `on_hold:` element.

    Deliberately the element's own resolved box, not an inflated one: the
    region a finger must hit is then exactly the thing the eye sees, which is
    predictable and reviewable in `wfb preview`.  Inflating to some minimum
    touch size would be inventing a number Garmin does not publish, and would
    silently overlap neighbouring targets on a dense face.  An author who
    wants a bigger target puts the element in a `group` and taps that.
    """
    if placed.element.on_hold is None:
        return []
    prefix = _const_prefix(placed.id)
    box = placed.box
    return [
        (f"{prefix}_HOLD_X", box.x, "hit region: the element's own drawn box"),
        (f"{prefix}_HOLD_Y", box.y, ""),
        (f"{prefix}_HOLD_WIDTH", box.width, ""),
        (f"{prefix}_HOLD_HEIGHT", box.height, ""),
    ]


def _box_constants(prefix: str, box, note: str = "") -> list[tuple[str, float, str]]:
    """The `_X/_Y/_WIDTH/_HEIGHT` quartet for one resolved box -- shared by a
    rectangular shape, a bar-style progress, a graph and a complication_slot's
    editor highlight box (``prefix`` already carries that last one's own
    `_BOX` suffix).  ``note`` documents the `_X` constant only, the same
    "first constant of the block carries the note" convention every other
    multi-constant block here follows.
    """
    return [
        (f"{prefix}_X", box.x, note),
        (f"{prefix}_Y", box.y, ""),
        (f"{prefix}_WIDTH", box.width, ""),
        (f"{prefix}_HEIGHT", box.height, ""),
    ]


def _arc_constants(prefix: str, placed) -> list[tuple[str, float, str]]:
    """The `_RADIUS/_THICKNESS/_START/_SWEEP` quartet for one resolved arc --
    shared by a `shape: arc` and a `progress` arc, which both resolve
    `placed.radius`/`.thickness`/`.garmin_start`/`.start_angle`/`.sweep`
    through `wfb.layout.garmin_arc` the same way, so the two agree about
    the angle convention by construction.
    """
    return [
        (f"{prefix}_RADIUS", placed.radius, ""),
        (f"{prefix}_THICKNESS", placed.thickness, "pen width; there is no filled-arc primitive"),
        (f"{prefix}_START", float(placed.garmin_start),
         f"{placed.start_angle:g}deg clockwise from 12 o'clock, in Garmin's convention"),
        (f"{prefix}_SWEEP", float(placed.sweep), "clockwise-positive degrees"),
    ]


def _layout_constants(placed) -> list[tuple[str, float | McLiteral, str]]:
    prefix = _const_prefix(placed.id)
    out: list[tuple[str, float | McLiteral, str]] = []
    if isinstance(placed, PlacedShape):
        element = placed.element
        if element.shape in ("circle", "line", "arc", "ellipse"):
            out.append((f"{prefix}_CX", placed.center[0], ""))
            out.append((f"{prefix}_CY", placed.center[1], ""))
        if element.shape == "circle":
            out.append((f"{prefix}_RADIUS", placed.radius, ""))
        elif element.shape == "line":
            out.append((f"{prefix}_END_X", placed.end[0], ""))
            out.append((f"{prefix}_END_Y", placed.end[1], ""))
            out.append((f"{prefix}_THICKNESS", placed.thickness, ""))
        elif element.shape == "arc":
            out.extend(_arc_constants(prefix, placed))
        elif element.shape == "ellipse":
            out.append((f"{prefix}_RX", placed.rx, "semi-axis along x"))
            out.append((f"{prefix}_RY", placed.ry, "semi-axis along y"))
            if not element.filled:
                out.append((f"{prefix}_THICKNESS", placed.thickness, "pen width"))
        elif element.shape == "polygon":
            points = ", ".join(f"[{x}, {y}]" for x, y in placed.points)
            out.append((
                f"{prefix}_POINTS",
                McLiteral("Array<Graphics.Point2D>", f"[{points}]"),
                f"{len(placed.points)} vertices; fillPolygon's own limit is 64",
            ))
        else:
            rect = placed.rect or placed.box
            out.extend(_box_constants(prefix, rect))
            if element.shape == "rounded_rectangle":
                out.append((f"{prefix}_CORNER", placed.corner_radius, ""))
            if not element.filled:
                out.append((f"{prefix}_THICKNESS", placed.thickness, "pen width"))
    elif isinstance(placed, PlacedText):
        # For `curve: {style: radial}` this is the *centre of the circle*
        # (plan 11 §2.2's `at:` reinterpretation, `PlacedText.anchor_point`'s
        # own docstring), not a `drawText`-style anchor -- still `_X`/`_Y`,
        # since the codegen call site reads it that way regardless.
        out.append((f"{prefix}_X", placed.anchor_point[0], ""))
        out.append((f"{prefix}_Y", placed.anchor_point[1], ""))
        note = f'widest rendering "{placed.widest}" is {placed.measured_width} px'
        if placed.width_is_estimated:
            note += " (estimated)"
        out.append((f"{prefix}_WIDTH", placed.measured_width, note))
        if placed.curve_style is not None:
            # Both angle conventions in the comment, the same `arc`
            # precedent `_arc_constants`'s own `_START` follows -- keeps the
            # conversion auditable without having to re-derive it.
            author_note = (
                f"{placed.curve_angle_degrees:g}deg clockwise from 12 o'clock"
                if placed.curve_style == "radial"
                else f"{placed.curve_angle_degrees:g}deg clockwise rotation from upright"
            )
            out.append((
                f"{prefix}_ANGLE", float(placed.curve_angle_garmin),
                f"{author_note}, in Garmin's convention",
            ))
            if placed.curve_style == "radial":
                out.append((f"{prefix}_RADIUS", placed.curve_radius_px, ""))
    elif isinstance(placed, PlacedProgress):
        out.append((f"{prefix}_CX", placed.center[0], ""))
        out.append((f"{prefix}_CY", placed.center[1], ""))
        if placed.element.style == "arc":
            out.extend(_arc_constants(prefix, placed))
        else:
            out.extend(_box_constants(prefix, placed.box))
    elif isinstance(placed, PlacedIcon):
        # A glyph kind's anchor never itself moves for `align`/`vertical_
        # align` -- only the device-side justify flags and `_emit_icon`'s
        # `bottom` subtraction do -- so the constant names and
        # values stay `_CX`/`_CY` (byte-identical for center/center) even
        # when aligned; the comment says so only then, so the default note
        # (`""`) is unchanged.
        default = placed.element.align == "center" and placed.element.vertical_align == "center"
        note = "" if default else "the anchor drawText justifies the glyph from, not its centre"
        out.append((f"{prefix}_CX", placed.center[0], note))
        out.append((f"{prefix}_CY", placed.center[1], note))
    elif isinstance(placed, PlacedGraph):
        out.extend(_box_constants(prefix, placed.box))
        if placed.element.style == "line":
            out.append((f"{prefix}_THICKNESS", placed.thickness, "pen width"))
        elif placed.element.style == "bars":
            out.append((f"{prefix}_BAR_WIDTH", placed.bar_width,
                        "centred in each slot"))
    elif isinstance(placed, PlacedComplicationSlot):
        out.append((f"{prefix}_CX", placed.anchor_point[0],
                    "the icon+reading pair is centred here at runtime"))
        out.append((f"{prefix}_CY", placed.anchor_point[1], ""))
        # The editor's animated highlight needs a fixed box at build time --
        # `getComplicationDrawable` hands the system a `Drawable` up front,
        # before anything is pulled -- so this reuses the same estimated
        # `box` the safe-area/overlap lints already accept as good enough for
        # a slot's real, content-dependent extent (`PlacedComplicationSlot`'s
        # own docstring).  Emitted for every slot regardless of `on_hold:`:
        # the editor can animate any slot, not only ones that also launch
        # something on a live face.
        out.extend(_box_constants(f"{prefix}_BOX", placed.box,
                                  "the editor's animated highlight box (estimated)"))
        if placed.element.icon_gap is not None:
            # Only emitted when the author actually wrote 'icon_gap:' --
            # otherwise the generated view keeps embedding the literal
            # COMPLICATION_SLOT_ICON_GAP it always has, so a design that
            # never sets this emits none of it. Resolved per device ('%r'
            # is a different pixel count per screen) the same reason
            # `wfb.icons.font_key` keys by the *declared* size, not the
            # resolved one.
            out.append((f"{prefix}_ICON_GAP", placed.icon_gap_px,
                        "icon_gap: resolved for this device"))
    elif isinstance(placed, PlacedHands):
        out.append((f"{prefix}_CX", placed.center[0], "the axis"))
        out.append((f"{prefix}_CY", placed.center[1], ""))
        for hand_name in ("hour", "minute", "second"):
            hand = getattr(placed, hand_name)
            if hand is None:
                continue
            hand_prefix = f"{prefix}_{hand_name.upper()}"
            for index, part in enumerate(hand.parts):
                out.extend(_hand_part_constants(
                    f"{hand_prefix}_{index}", f"{hand_name} hand", index, part))
    elif isinstance(placed, PlacedPattern):
        note = ("the centre every copy turns about" if placed.element.pattern == "radial"
                else "copy 0's origin")
        out.append((f"{prefix}_X", placed.center[0], note))
        out.append((f"{prefix}_Y", placed.center[1], ""))
        if placed.element.pattern == "linear":
            out.append((f"{prefix}_DX", placed.dx, "step between copies, whole pixels"))
            out.append((f"{prefix}_DY", placed.dy, ""))
        for index, part in enumerate(placed.parts):
            out.extend(_hand_part_constants(f"{prefix}_{index}", "template", index, part))
    return out


def _hand_part_constants(
    part_prefix: str, owner: str, index: int, part,
) -> list[tuple[str, float | McLiteral, str]]:
    """The `Layout` constants for one resolved hand part, or one resolved
    pattern template part, reusing the same shapes:
    `<P>_<i>_POINTS` for a polygon (a rectangle part already folded into
    one by `wfb.layout`), `_X1/_Y1/_X2/_Y2/_THICKNESS` for a line,
    `_X/_Y/_RADIUS[/_THICKNESS]` for a circle, `_RADIUS/_THICKNESS` for
    an arc (pattern-only -- a hand never produces this shape), or `_X/_Y`
    alone for a text part (pattern-only too -- the anchor a copy's
    transform moves; no radius or thickness, since the glyphs are
    measured, not stroked) -- one comment naming the part's own shape, the
    same "why" every other constant block gets.  ``owner`` is the
    human-readable thing this part belongs to (``"hour hand"``, or
    ``"template"`` for a pattern, which has only the one), folded into
    that comment.

    A text part's own `curve: {style: radial}` (plan 11 slice 2) adds one
    more constant, `_RADIUS`, the device-dependent circle radius -- the
    same reason a standalone `curve: {style: radial}` `text` element's own
    `PlacedText` gets one (`_layout_constants`'s own `PlacedText` branch).
    The angle itself is deliberately **not** a `Layout` constant: it is
    device-independent (plain degrees) and needs a *per-copy* runtime term
    for a radial pattern, so it is inlined straight into the shared view
    instead (`wfb.emit.monkeyc.rotated._emit_pattern_text_angle_expr`) --
    exactly the precedent an arc part's own `start_angle`/`sweep` already
    set one row down: those get no `_START`/`_SWEEP` constants here either.
    """
    if part.shape == "text":
        out = [
            (f"{part_prefix}_X", part.x, f"{owner}, part {index}: text (the anchor)"),
            (f"{part_prefix}_Y", part.y, ""),
        ]
        if part.curve_style == "radial":
            out.append((f"{part_prefix}_RADIUS", part.curve_radius_px,
                        "curve: radial's own circle radius"))
        return out
    if part.shape == "polygon":
        points = ", ".join(f"[{x}, {y}]" for x, y in part.points)
        return [(
            f"{part_prefix}_POINTS",
            McLiteral("Array<Graphics.Point2D>", f"[{points}]"),
            f"{owner}, part {index}: a {len(part.points)}-vertex polygon",
        )]
    if part.shape == "line":
        return [
            (f"{part_prefix}_X1", part.x1, f"{owner}, part {index}: a line"),
            (f"{part_prefix}_Y1", part.y1, ""),
            (f"{part_prefix}_X2", part.x2, ""),
            (f"{part_prefix}_Y2", part.y2, ""),
            (f"{part_prefix}_THICKNESS", part.thickness, "pen width"),
        ]
    if part.shape == "arc":
        # Always centred on the origin (x=y=0) -- no _X/_Y.
        return [
            (f"{part_prefix}_RADIUS", part.radius, f"{owner}, part {index}: an arc"),
            (f"{part_prefix}_THICKNESS", part.thickness,
             "pen width; there is no filled-arc primitive"),
        ]
    # circle
    out = [
        (f"{part_prefix}_X", part.x, f"{owner}, part {index}: a circle"),
        (f"{part_prefix}_Y", part.y, ""),
        (f"{part_prefix}_RADIUS", part.radius, ""),
    ]
    if not part.filled:
        out.append((f"{part_prefix}_THICKNESS", part.thickness,
                    "pen width; there is no filled-arc-style outline shortcut here"))
    return out
