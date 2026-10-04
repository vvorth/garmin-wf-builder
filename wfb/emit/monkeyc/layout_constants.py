"""`Layout.mc` -- per-device layout constants resolved at build time."""

from __future__ import annotations

from ... import kinds
from ...availability import Guards, vector_font_face
from ...ir import Element, disc_perimeter_offsets, slot_of
from ...ir.rings import ring_groups
from ...layout import (
    HIDDEN_BY_SUBSCREEN, Placed, PlacedGraph, PlacedHands, PlacedPattern, PlacedProgress,
    PlacedShape, ResolvedFace, ResolvedHandPart,
)
from ...units import IntBox
from .common import (
    EditorSlot, McLiteral, SourceFile, _NO_GUARDS, _describe, _mc_number, _mc_type,
    _vector_fonts_used, const_prefix, editor_slots, header,
)
from ..writer import Writer
from . import config_menu
from . import profile as profile_mod


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
    """The `Layout` constants for one used `face:` (vector) font, by name:
    `FONT_<NAME>_FACE`/`_SIZE` always, `_AVAILABLE` only
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
    prefix = f"FONT_{const_prefix(name)}"
    resolved_face = vector_font_face(spec, device)
    size_px = spec.pixel_size(device.minor_radius)
    requested = ", ".join(spec.face or ())
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


def slot_box_constants(resolved: ResolvedFace, slot: EditorSlot) -> Constants:
    """One slot's two editor boxes on this device, as `Layout` constants.

    The editor needs both at build time -- `getComplicationDrawable` hands
    the system a `Drawable` up front, before anything is pulled.  `_BOX` is
    what `onTap` hit-tests: the union of each element's own estimated box,
    the one the safe-area/overlap lints accept, so side-by-side slots stay
    separate targets.  `_HIGHLIGHT` is what the drawable is built on, since
    the editor clips it to that box: the union again, with a reading's box
    widened to every column its pick could reach
    (`wfb.kinds.complication_slot.highlight_box`).  Emitted for every slot
    regardless of `on_hold:`: the editor can animate any slot.
    """
    members = [placed for placed in resolved.items if slot_of(placed.element) == slot.name]
    if not members:
        return []
    tap = members[0].box
    highlight = _highlight(members[0])
    for placed in members[1:]:
        tap = tap.union(placed.box)
        highlight = highlight.union(_highlight(placed))
    out: Constants = []
    out.extend(box_constants(f"{slot.const_prefix}_BOX", tap, "the editor's tap target (estimated)"))
    out.extend(box_constants(f"{slot.const_prefix}_HIGHLIGHT", highlight,
                             "the editor clips the slot's drawable to this box"))
    return out


def _highlight(placed: Placed) -> IntBox:
    return getattr(placed, "highlight", None) or placed.box


def _transforms_at_runtime(element: Element) -> bool:
    """Does ``element`` ring parts it transforms on the watch -- a hand, a
    gauge needle, a pattern copy -- through `WfbRing`?  Every other ring is
    unrolled with literal offsets and reads no table."""
    return (element.kind in ("hands", "pattern")
            or (element.kind == "progress" and getattr(element, "style", None) == "needle"))


def _outline_widths_used(resolved: ResolvedFace) -> list[int]:
    """Every distinct ring width wider than 1px that `WfbRing` draws in this
    design, in first-appearance draw order: a runtime-transformed element's
    own `outline:` (`_transforms_at_runtime`), or its share of an outlined
    group's (`wfb.ir.rings`, the widths summed).  Only what is used
    generates code, the same rule `_vector_fonts_used`/`_loaded_fonts`
    follow.  A 1px ring needs no table: `WfbRing`'s own 1px functions spell
    its four offsets out.
    """
    out: list[int] = []

    def add(width: int) -> None:
        if width > 1 and width not in out:
            out.append(width)

    for ring in ring_groups(resolved.face.elements):
        for leaf, width in ring.members:
            if _transforms_at_runtime(leaf):
                add(width)
    for placed in resolved.items:
        outline = placed.element.outline
        if outline is not None and _transforms_at_runtime(placed.element):
            add(outline.width)
    return out


def _outline_offsets_constants(width: int) -> Constants:
    """`OUTLINE_OFFSETS_<W>` -- the flat `Array<Number>` (`[dx0, dy0, dx1,
    dy1, ...]`) of `wfb.ir.disc_perimeter_offsets(width)`, which `WfbRing`'s
    wider-ring functions walk for a part transformed at runtime (a hand, a
    needle, a pattern copy).  Every other stamp unrolls its offsets as
    literals.  Flat rather than `Array<Graphics.Point2D>` because each
    point is applied as two separate `Number` shifts.
    """
    offsets = disc_perimeter_offsets(width)
    flat = ", ".join(str(v) for pair in offsets for v in pair)
    return [(
        f"OUTLINE_OFFSETS_{width}",
        McLiteral("Array<Number>", f"[{flat}]"),
        f"{len(offsets)} disc-perimeter points, {width}px ring",
    )]


def emit_layout(resolved: ResolvedFace, guards: "Guards" = _NO_GUARDS,
                profile: int | None = None) -> SourceFile:
    """One device's `Layout` module.  ``profile`` (the repetition count of
    `wfb build --profile`) adds the overlay's anchors (`profile.py`)."""
    face, device = resolved.face, resolved.device
    w = Writer()
    w.doc(
        header(
            face,
            f"Device:    {device.id} -- {device.width}x{device.height} {device.shape}, "
            f"{device.display_type}, family {device.device_family}",
        )
    ).blank()
    per_item = [(placed, _shown_constants(resolved, placed, guards)
                 + _layout_constants(placed) + _hold_constants(resolved, placed))
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
    menu_slots = guards.config_menu and bool(face.config_data)
    if menu_slots:
        imports.insert(0, "import Toybox.Complications;")
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
        if menu_slots:
            config_menu.emit_layout_constants(w, face, device)
        for slot in editor_slots(face):
            boxes = slot_box_constants(resolved, slot)
            if boxes:
                w.blank()
                w.doc(f"The native editor's boxes for slot {slot.name}: every element "
                      "drawing it,\ntaken together.")
                _emit_constants(w, boxes)
        vector_fonts = _vector_fonts_used(resolved)
        if vector_fonts:
            w.blank()
            w.doc(
                "Device-resident scalable ('face:') fonts this design draws with.\n"
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
                "'outline:' offsets for each ring wider than 1px this design uses:\n"
                "the points WfbRing shifts a runtime-transformed part to, index\n"
                "i/i+1 per (dx, dy) pair."
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
        if profile:
            w.blank()
            w.doc("`wfb build --profile`: where each timed entry's reading is drawn "
                  "(the top\ncentre of its box), which layout it belongs to (-1: shared), "
                  "and the\nheader line.")
            for line in profile_mod.layout_lines(resolved, profile_mod.plan_for(resolved, profile)):
                w.line(line)
    return SourceFile(f"source-{device.id}/Layout.mc", w.render())


def _shown_constants(resolved: ResolvedFace, placed: Placed, guards: "Guards") -> Constants:
    """`<ID>_SHOWN` for an element laid out in the subscreen window, when
    some target in the build has none (`Guards.subscreen_hidden`): false
    where this device hides it, and its draw method returns early there.
    A group draws nothing itself, so only its hold region (below) needs
    the answer."""
    if placed.id not in guards.subscreen_hidden or placed.kind == "group":
        return []
    reason = resolved.hidden.get(placed.id)
    note = ("drawn in the subscreen window" if reason is None
            else "no subscreen on this device: 'if_unavailable: hide'"
            if reason == HIDDEN_BY_SUBSCREEN
            else "its font has no face on this device: 'if_unavailable: hide'")
    return [(f"{const_prefix(placed.id)}_SHOWN", reason is None, note)]


def _hold_constants(resolved: ResolvedFace, placed: Placed) -> Constants:
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
    prefix = const_prefix(placed.id)
    box = placed.box
    note = "hit region: the element's own drawn box"
    if placed.id in resolved.hidden:
        # Not drawn here, so nothing to hold: an empty region never matches.
        box, note = IntBox(0, 0, 0, 0), "hit region: empty, not drawn on this device"
    return [
        (f"{prefix}_HOLD_X", box.x, note),
        (f"{prefix}_HOLD_Y", box.y, ""),
        (f"{prefix}_HOLD_WIDTH", box.width, ""),
        (f"{prefix}_HOLD_HEIGHT", box.height, ""),
    ]


def box_constants(prefix: str, box: IntBox, note: str = "") -> list[tuple[str, float, str]]:
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


def arc_constants(prefix: str,
                  placed: PlacedShape | PlacedProgress) -> list[tuple[str, float, str]]:
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


def aod_thickness_constant(prefix: str,
                           placed: PlacedShape | PlacedProgress | PlacedGraph | PlacedHands
                           | PlacedPattern,
                           note: str = "aod: thickness override") -> list[tuple[str, float, str]]:
    """`{prefix}_AOD_THICKNESS`, only when this element's resolved `aod:`
    overrides `thickness:` -- the codegen ternary at the draw
    call site falls back to the plain `_THICKNESS` constant otherwise."""
    if placed.aod_thickness is None:
        return []
    return [(f"{prefix}_AOD_THICKNESS", placed.aod_thickness, note)]


#: One override, applied uniformly to every part of a hands/pattern element
#: -- not one constant per part.
EVERY_PART_NOTE = "aod: thickness override, applied to every part"


def _layout_constants(placed: Placed) -> Constants:
    return kinds.for_placed(placed).layout_constants(const_prefix(placed.id), placed)


def hand_part_constants(
    part_prefix: str, owner: str, index: int, part: ResolvedHandPart,
) -> Constants:
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

    A text part's own `curve: {style: radial}` adds one
    more constant, `_RADIUS`, the device-dependent circle radius -- the
    same reason a standalone `curve: {style: radial}` `text` element's own
    `PlacedText` gets one (`wfb.kinds.text.TextKind.layout_constants`).
    The angle itself is deliberately **not** a `Layout` constant: it is
    device-independent (plain degrees) and needs a *per-copy* runtime term
    for a radial pattern, so it is inlined straight into the shared view
    instead (`wfb.kinds.pattern._text_angle`) --
    exactly the precedent an arc part's own `start_angle`/`sweep` already
    set one row down: those get no `_START`/`_SWEEP` constants here either.
    """
    if part.shape == "text":
        out: Constants = [
            (f"{part_prefix}_X", part.x, f"{owner}, part {index}: text (the anchor)"),
            (f"{part_prefix}_Y", part.y, ""),
        ]
        if part.curve.style == "radial":
            out.append((f"{part_prefix}_RADIUS", part.curve.radius_px,
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
