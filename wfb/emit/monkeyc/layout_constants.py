"""`Layout.mc` -- per-device layout constants resolved at build time."""

from __future__ import annotations

from ... import kinds
from ...availability import Guards, vector_font_face
from ...ir import disc_perimeter_offsets
from ...layout import (
    PlacedComplicationSlot, PlacedHands, PlacedPattern,
    PlacedText, ResolvedFace,
)
from .common import (
    McLiteral, SourceFile, _NO_GUARDS, _const_prefix, _describe, _mc_number, _mc_type,
    _vector_fonts_used, header,
)
from ..writer import Writer


#: One `Layout` block: `(name, value, note)` per constant, the note (if any)
#: rendered as a trailing comment.
Constants = list[tuple[str, float | str | bool | McLiteral, str]]


def _emit_constants(w: Writer, constants: Constants) -> None:
    """Render one `const NAME as TYPE = VALUE;  // note` block -- the one
    place a `Layout` constant is rendered, shared by the font-name-level
    block (`_emit_vector_font_constants`) and the per-placed-element loop
    below, so the two cannot silently drift into two different renderings
    of the same `(name, value, note)` shape.
    """
    for name, value, note in constants:
        suffix = f"  // {note}" if note else ""
        w.line(f"const {name} as {_mc_type(value)} = {_mc_number(value)};{suffix}")


def _vector_font_constants(resolved: ResolvedFace, name: str, guards: "Guards") -> Constants:
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
    out: Constants = [
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


def _outline_widths_used(resolved: ResolvedFace) -> list[int]:
    """Every distinct `outline.width` a `text` element or a pattern's own
    `shape: text` part (plan 15 §14 slice 2) actually draws with in this
    design, in first-appearance draw order -- the same "only what's
    actually used generates code" rule `_vector_fonts_used`/`_loaded_fonts`
    already follow (`wfb.emit.monkeyc.common`). `getattr(..., "outline",
    None)` rather than `isinstance(placed, PlacedText)` so a standalone
    element needs no special-casing; a `PatternElement`'s own `parts`
    (`getattr(..., "parts", None)`, true only for a pattern -- neither
    `Text` nor `HandsElement` has one) are walked too, since `outline:`
    lives per-part there, not on the element itself.
    """
    out: list[int] = []
    for placed in resolved.items:
        outline = getattr(placed.element, "outline", None)
        if outline is not None and outline.width not in out:
            out.append(outline.width)
        for part in getattr(placed.element, "parts", None) or ():
            part_outline = getattr(part, "outline", None)
            if part_outline is not None and part_outline.width not in out:
                out.append(part_outline.width)
    return out


def _outline_offsets_constants(width: int) -> list[tuple[str, McLiteral, str]]:
    """`OUTLINE_OFFSETS_<W>` -- the flat `Array<Number>` (`[dx0, dy0, dx1,
    dy1, ...]`) the stamp loop iterates over (plan 15 §8), one per distinct
    ring width actually used anywhere in the design, deduplicated the same
    way a `face:` font's `_FACE`/`_SIZE` constants are emitted once per
    font name rather than once per element. The `_POINTS` precedent (a
    polygon's own vertex array, above) is the reason this is an
    `Array<Graphics.Point2D>`-shaped exception rather than a plain
    `Number`: `Dc.drawText`'s own `(x, y)` are two separate `Number`
    arguments, not a `Point2D`, so a flat `Array<Number>` (index `i`/`i+1`
    per stamp) is what the call site actually wants, not a tuple array.
    """
    offsets = disc_perimeter_offsets(width)
    flat = ", ".join(str(v) for pair in offsets for v in pair)
    return [(
        f"OUTLINE_OFFSETS_{width}",
        McLiteral("Array<Number>", f"[{flat}]"),
        f"{len(offsets)} disc-perimeter points, {width}px ring (plan 15, "
        "docs/research/14-stamped-ring-text.md §1)",
    )]


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
    per_item = [(placed, _layout_constants(placed) + _hold_constants(placed))
                for placed in resolved.items]
    # Toybox.Graphics only when some constant is typed against it (a
    # polygon's `Array<Graphics.Point2D>`: Point2D is the fixed-size
    # `[Numeric, Numeric]` tuple type, not `Array<Number>` -- verified by
    # building, docs/research/probes/polygon-const/). Read off the constants
    # themselves, so a new shape typed that way needs no second rule here.
    needs_graphics = any(
        isinstance(value, McLiteral) and "Graphics." in value.type
        for _, constants in per_item for _, value, _ in constants
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
        outline_widths = _outline_widths_used(resolved)
        if outline_widths:
            w.blank()
            w.doc(
                "'outline:' stamp offsets (plan 15): the disc-perimeter table for\n"
                "each ring width this design actually uses, shared by every element\n"
                "drawing with that width -- the array the generated stamp loop\n"
                "iterates over, index i/i+1 per (dx, dy) pair."
            )
            for width in outline_widths:
                _emit_constants(w, _outline_offsets_constants(width))
        for placed, constants in per_item:
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


def _aod_thickness_constant(prefix: str, placed,
                            note: str = "aod: thickness override") -> list[tuple[str, float, str]]:
    """`{prefix}_AOD_THICKNESS`, only when this element's resolved `aod:`
    overrides `thickness:` (plan 14 §4.2) -- the codegen ternary at the draw
    call site falls back to the plain `_THICKNESS` constant otherwise."""
    if placed.aod_thickness is None:
        return []
    return [(f"{prefix}_AOD_THICKNESS", placed.aod_thickness, note)]


def _text_constants(prefix: str, placed: PlacedText) -> Constants:
    # For `curve: {style: radial}` this is the *centre of the circle*
    # (plan 11 §2.2's `at:` reinterpretation, `PlacedText.anchor_point`'s
    # own docstring), not a `drawText`-style anchor -- still `_X`/`_Y`,
    # since the codegen call site reads it that way regardless.
    note = f'widest rendering "{placed.widest}" is {placed.measured_width} px'
    if placed.width_is_estimated:
        note += " (estimated)"
    out: Constants = [
        (f"{prefix}_X", placed.anchor_point[0], ""),
        (f"{prefix}_Y", placed.anchor_point[1], ""),
        (f"{prefix}_WIDTH", placed.measured_width, note),
    ]
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
    return out


def _complication_slot_constants(prefix: str, placed: PlacedComplicationSlot) -> Constants:
    out: Constants = [
        (f"{prefix}_CX", placed.anchor_point[0], "the icon+reading pair is centred here at runtime"),
        (f"{prefix}_CY", placed.anchor_point[1], ""),
    ]
    # The editor's animated highlight needs a fixed box at build time --
    # `getComplicationDrawable` hands the system a `Drawable` up front,
    # before anything is pulled -- so this reuses the same estimated `box`
    # the safe-area/overlap lints accept. Emitted for every slot regardless
    # of `on_hold:`: the editor can animate any slot.
    out.extend(_box_constants(f"{prefix}_BOX", placed.box,
                              "the editor's animated highlight box (estimated)"))
    if placed.element.icon_gap is not None:
        # Only when the author wrote 'icon_gap:' -- otherwise the view keeps
        # the literal COMPLICATION_SLOT_ICON_GAP. Resolved per device ('%r'
        # is a different pixel count per screen).
        out.append((f"{prefix}_ICON_GAP", placed.icon_gap_px,
                    "icon_gap: resolved for this device"))
    return out


#: One override, applied uniformly to every part of a hands/pattern element
#: (plan 14 §5.1) -- not one constant per part.
_EVERY_PART_NOTE = "aod: thickness override, applied to every part"


def _hands_constants(prefix: str, placed: PlacedHands) -> Constants:
    out: Constants = [
        (f"{prefix}_CX", placed.center[0], "the axis"),
        (f"{prefix}_CY", placed.center[1], ""),
    ]
    out.extend(_aod_thickness_constant(prefix, placed, _EVERY_PART_NOTE))
    for hand_name in ("hour", "minute", "second"):
        hand = getattr(placed, hand_name)
        if hand is None:
            continue
        for index, part in enumerate(hand.parts):
            out.extend(_hand_part_constants(
                f"{prefix}_{hand_name.upper()}_{index}", f"{hand_name} hand", index, part))
    return out


def _pattern_constants(prefix: str, placed: PlacedPattern) -> Constants:
    radial = placed.element.pattern == "radial"
    out: Constants = [
        (f"{prefix}_X", placed.center[0],
         "the centre every copy turns about" if radial else "copy 0's origin"),
        (f"{prefix}_Y", placed.center[1], ""),
    ]
    if not radial:
        out.append((f"{prefix}_DX", placed.dx, "step between copies, whole pixels"))
        out.append((f"{prefix}_DY", placed.dy, ""))
    out.extend(_aod_thickness_constant(prefix, placed, _EVERY_PART_NOTE))
    for index, part in enumerate(placed.parts):
        out.extend(_hand_part_constants(f"{prefix}_{index}", "template", index, part))
    return out


def _layout_constants(placed) -> Constants:
    return kinds.for_placed(placed).layout_constants(_const_prefix(placed.id), placed)


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
    `PlacedText` gets one (`_text_constants`).
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
