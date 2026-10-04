"""`type: progress` -- a bound fraction, drawn as an arc, a bar, a gauge
needle, lit segments, or a scale with a pointer."""

from __future__ import annotations

import math
from typing import Any, TYPE_CHECKING

from .. import catalog, complications, expr, vocab
from ..catalog import Type
from ..ir.model import HOLD_AUTO, Element, Expression, Progress
from ..layout import Placed, PlacedProgress, arc_box, rotatable_parts, stroke_pad
from ..preview import SAMPLE_GOALS, SAMPLE_HEART_RATE_ZONES, SAMPLE_WEARER_AGE, SAMPLE_WEARER_SEX
from ..units import Axis, Box, IntBox
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc.common import article, const_prefix
from ..emit.monkeyc.slot_scale import SLOT_SCALE_MODULE
from ..ir.naming import config_data_ids, config_field
from ..ir import disc_perimeter_offsets
from ..draw.printer import color_code
from ..draw.program import (
    AodDimmed, AodPart, AodPick, AodRestyled, ArcProgress, ArcSpan, Assign, Bin, Blank, Call, Cmp,
    Comment, Cond, Const, Conv, DrawContext, FloatLit, For, Grown, If, Let,
    LetAutoScale, LetSlotPick, Lit, LocalsSet, NotPulsing, Num, NumLocal, NumPick, Op, Paint,
    PaintPick, Paren, Part, Present, Primitive, Read, RingColor, SetColor, Shifted,
)
from . import ElementKind
from .complication_slot import COMPLICATION_SLOT_SAMPLE, resolve_slot_reference

if TYPE_CHECKING:
    from collections.abc import Iterator

    from . import ContrastSubject
    from ..ir.builder import Builder
    from ..ir.model import Face
    from ..layout import Resolver, RotatablePart

def _check_fallback_fraction(b: Builder, node: dict[str, Any], element: Progress) -> None:
    """A `progress` fallback is a **fill fraction**, so it must be 0.0-1.0.

    This is the one place `fallback:` means something other than "the
    value" -- for a progress, either the value or the max can be the
    absent reading, so the outcome is the only well-defined substitute
    (see `_fallback_num`).  That makes an out-of-range constant a
    plausible mistake -- writing the *step count* you wanted rather than
    the fraction -- and it is the one path not already clamped by
    `WfbMath.percent`, so a bar could be drawn wider than its own box.  Only a build-time constant is checked here; a
    computed fallback is clamped on device instead.
    """
    fallback = element.fallback
    if element.absent != "fallback" or fallback is None or not fallback.is_constant:
        return
    try:
        value = float(expr.as_number(fallback.constant))
    except TypeError:
        return
    if 0.0 <= value <= 1.0:
        return
    b.bag.error(
        "when-absent",
        f"{element.id}: a gauge's 'absent: {{value:}}' is a fill fraction, so it must "
        f"be between 0.0 and 1.0 -- got {fallback.shown}",
        b.fallback_span(node),
        notes=[
            "unlike a text's 'absent: {value:}', which supplies the value and is "
            "then formatted, a gauge's supplies the filled proportion "
            "directly: either the value or the max can be the absent reading, "
            "so the outcome is the only well-defined thing to substitute",
            "for 'half full' write 0.5, not the reading you would have shown",
        ],
    )


#: What a gauge with `slot:` does not read, and why.
_NOT_BESIDE_SLOT = {
    "max": "the scale is the picked metric's own, and one 'max:' cannot fit every "
           "choice the wearer has",
    "bands": "'bands:' are fractions of one fixed scale; zones from the picked "
             "metric's own bands are not implemented yet",
}


def _auto_scale_type(b: Builder, node: dict[str, Any], element_id: str,
                     value: Expression | None) -> str | None:
    """The complication type `max: auto` scales by: `value:` must be a bare
    `complication.<type>`, and that type must have a scale.  None, with the
    reason reported, otherwise."""
    if value is None:
        return None  # the value's own error is already reported
    ref = value.ast
    if not isinstance(ref, expr.Ref) or not ref.path.startswith("complication."):
        b.bag.error(
            "element",
            f"{element_id}: 'max: auto' needs 'value:' to be a bare 'complication.<type>', "
            f"got {value.shown}",
            b.doc.span(node, "max"),
            notes=["the scale is that complication type's own; write 'max:' as a number or "
                   "an expression for anything else",
                   'docs/guide/progress-and-graphs.md, "Gauges on a slot"'],
        )
        return None
    name = ref.path[len("complication."):]
    if name not in complications.SCALE:
        b.bag.error(
            "element",
            f"{element_id}: 'max: auto' -- {ref.path} has no scale of its own",
            b.doc.span(node, "max"),
            notes=["types with one: " + ", ".join(sorted(complications.SCALE)),
                   "write 'max:' as a number or an expression for this one"],
        )
        return None
    return name


def _check_slot_keys(b: Builder, node: dict[str, Any], element_id: str) -> bool:
    """Refuse the keys a gauge with `slot:` does not read.  False when
    anything was reported."""
    ok = True
    for key, why in _NOT_BESIDE_SLOT.items():
        if key in node:
            b.bag.error("element", f"{element_id}: '{key}:' is not read beside 'slot:' -- {why}",
                        b.doc.span(node, key),
                        notes=['docs/guide/progress-and-graphs.md, "Gauges on a slot"'])
            ok = False
    return ok


def keeps_track(element: Progress) -> bool:
    """Whether `absent: hide` still draws this gauge's value-independent
    parts -- the arc or bar track, every segment unlit, a scale's track and
    bands -- and hides only what the value places: the fill, the lit
    segments, the pointer.  A needle has nothing that does not depend on the
    value, so it hides whole.  The one definition the program
    (`ProgressKind.lower`) and the view's guard (`draws_while_absent`) both
    read."""
    return element.absent == "hide" and element.style != "needle"


#: Keys a `style: needle` progress does not read: the needle's shape is its
#: parts, and `at:` is the axis it turns about, not a box.
_NEEDLE_UNREAD = {
    "radius": "the needle's length is its parts' own geometry",
    "thickness": "a line part's own 'thickness:' is the needle's pen width",
    "size": "a needle has no box; its extent is the disc it sweeps",
    "track_color": "a needle draws no track -- draw the dial with its own "
                   "'style: arc' gauge or a pattern",
    "align": "'at:' is the axis the needle turns about, not a box",
}


def _build_needle(b: Builder, node: dict[str, Any], element: Progress) -> bool:
    """`style: needle`'s parts, built exactly like an analog hand's
    (`Builder.build_hand_part`), with the element's own `color:` as every
    part's default.  False when anything was reported."""
    ok = True
    for key, why in _NEEDLE_UNREAD.items():
        if key in node:
            b.bag.error("element", f"{element.id}: '{vocab.key(key)}:' is not read by "
                        f"'style: needle' -- {why}",
                        b.doc.span(node, key))
            ok = False
    color_failed = "color" in node and element.color is None
    parts = []
    for index, raw in enumerate(node.get("needle") or []):
        part = b.build_hand_part(raw, f"{element.id}.needle", index, element.color, color_failed)
        if part is None:
            ok = False
            continue
        parts.append(part)
    element.needle = tuple(parts)
    return ok


#: Keys only one style reads, and which.
_STYLE_ONLY_KEYS = {"needle": "needle", "count": "segments", "gap": "segments",
                    "bands": "scale", "pointer": "scale"}

_ARC_KEYS = ("radius", "thickness", "start_angle", "sweep")


def _build_ticked(b: Builder, node: dict[str, Any], element: Progress) -> bool:
    """`style: segments`/`scale`: which track they draw on (an arc's four
    keys, or a bar's `size:` -- exactly one), then their own keys.  False
    when anything was reported."""
    style = element.style
    arc_given = [key for key in _ARC_KEYS if key in node]
    if arc_given and "size" in node:
        b.bag.error("element", f"{element.id}: 'style: {style}' draws on an arc or a bar, "
                    "not both -- give an arc's radius/thickness/start_angle/sweep, or a "
                    "bar's size", b.doc.span(node, "size"))
        return False
    if not arc_given and "size" not in node:
        b.bag.error("element", f"{element.id}: 'style: {style}' needs a track -- an arc's "
                    "radius, thickness, start_angle and sweep, or a bar's size",
                    b.doc.span(node, "style"))
        return False
    missing = [key for key in _ARC_KEYS if key not in node] if arc_given else []
    if missing:
        b.bag.error("element", f"{element.id}: an arc 'style: {style}' also needs "
                    + ", ".join(repr(k) for k in missing), b.doc.span(node, "style"))
        return False
    if style == "segments":
        element.count = int(node["count"])
        element.gap = b.length(node, "gap")
        return True
    element.pointer = b.length(node, "pointer")
    bands = []
    previous = 0.0
    for index, raw in enumerate(node.get("bands") or []):
        to = float(raw["to"])
        if to <= previous:
            b.bag.error("element", f"{element.id}.bands[{index}]: 'to: {raw['to']}' must be "
                        f"greater than the previous band's ({previous:g}) -- bands run in "
                        "order along the track", b.doc.span(raw, "to"))
            return False
        color = b.color_expression(raw, "color")
        if color is None:
            return False
        b.check_other_absence(raw, element, "bands.color", color)
        bands.append((to, color))
        previous = to
    element.bands = tuple(bands)
    return True


def _resolve_ticked(r: Resolver, element: Progress, placed: PlacedProgress,
                    parent: Box) -> None:
    """`segments`' cell and step, or `scale`'s pointer and band spans, on the
    track `placed` already has (degrees on an arc, pixels on a bar)."""
    min_1px = element.resolved_min_1px
    arc = element.geometry == "arc"
    length = placed.sweep if arc else float(placed.size[0])
    if element.style == "segments":
        gap = r.extent(element.gap, parent, Axis.MINOR, 2, min_1px=min_1px, what="gap")
        if arc:
            gap = math.degrees(gap / placed.radius) if placed.radius > 0 else 0.0
            gap = math.copysign(gap, placed.sweep)
        count = element.count
        assert count is not None  # `style: segments` requires count:
        placed.cell = (length - (count - 1) * gap) / count
        placed.step = placed.cell + gap
        return
    if element.pointer is not None:
        placed.pointer = round(r.extent(element.pointer, parent, Axis.MINOR, 1,
                                        min_1px=min_1px, what="pointer"))
    else:
        placed.pointer = placed.thickness if arc else placed.size[1]
    spans = []
    previous = 0.0
    for to, _ in element.bands:
        if arc:
            spans.append((placed.start_angle + previous * placed.sweep, (to - previous) * placed.sweep))
        else:
            spans.append((float(int(length * previous)), float(int(length * to))))
        previous = to
    placed.band_spans = tuple(spans)
    # The dot reaches past the track: grow the box the lints read, keeping
    # the bar's own rectangle for drawing.
    cx, cy = placed.center
    if arc:
        reach = placed.radius + max(stroke_pad(placed.thickness), placed.pointer)
        placed.box = Box(cx - reach, cy - reach, 2 * reach, 2 * reach).rounded()
    else:
        bar = placed.box
        placed.rect = bar
        dy = max(0, placed.pointer - bar.height // 2)
        placed.box = IntBox(bar.x - placed.pointer, bar.y - dy,
                            bar.width + 2 * placed.pointer, bar.height + 2 * dy)


def _fallback_num(element: Progress) -> Num:
    """The `progress` fallback, a Float in 0.0-1.0, as a program value.

    Two things have to be true of it, and neither is automatic.  It must be a
    **Float**: `fraction` is reassigned from the fill fraction (a Float) in the
    branch below, and a `var` first bound to a Number makes the whole thing a
    `PolyType<Float or Number>` that `WfbArc.drawProgress`'s `Float` parameter
    rejects under `-l 3`.  And it must be **in range**: the real path is
    clamped by `WfbMath.percent`, so an unclamped fallback is the one way a
    bar could be drawn wider than its own box.  A constant is checked at build
    time (`_check_fallback_fraction`) and emitted bare; anything else is
    clamped on device.
    """
    fallback = element.fallback
    assert fallback is not None, "only called for absent: fallback, which requires one"
    if fallback.is_constant:
        return FloatLit(float(expr.as_number(fallback.constant)), "f")
    return Conv(Call("WfbMath.clamp", (Read(fallback), FloatLit(0.0), FloatLit(1.0))),
                "toFloat")


class _Lowering:
    """One gauge's program: `ProgressKind.lower`'s helpers, sharing the
    placed gauge, its `Layout` constants and its paints."""

    def __init__(self, ctx: DrawContext, placed: PlacedProgress) -> None:
        self.ctx = ctx
        self.placed = placed
        self.element = element = placed.element
        self.prefix = const_prefix(placed.id)
        self.consts = {name: Const(name, value) for name, value, _
                       in KIND.layout_constants(self.prefix, placed)
                       if isinstance(value, (int, float))}
        self.color: Paint = AodRestyled(element, "color")
        self.track: Paint | None = (AodRestyled(element, "track_color")
                                    if element.track_color is not None else None)
        #: The ring to draw: an outlined group's pass, else the gauge's own.
        self.stamp: tuple[Paint, int] | None = None
        if ctx.ring is not None:
            self.stamp = (RingColor(), ctx.ring.width)
        elif element.outline is not None:
            self.stamp = (AodDimmed(element, element.outline.color), element.outline.width)

    def c(self, suffix: str) -> Const:
        return self.consts[f"{self.prefix}_{suffix}"]

    def thickness(self) -> AodPick:
        """The arc's pen width, with its `aod: {thickness: ...}` override."""
        return AodPick(self.c("THICKNESS"),
                       self.c("AOD_THICKNESS") if self.placed.aod_thickness is not None else None)

    def ops(self) -> list[Op]:
        element = self.element
        ops: list[Op] = []
        if element.slot is not None:
            return ops + self.slot_gauge()
        probes = tuple(e for e in (element.value, element.maximum) if e is not None)
        if element.auto_scale is not None:
            assert element.value is not None and isinstance(element.value.ast, expr.Ref)
            reader = catalog.READERS[catalog.CATALOG[element.value.ast.path].reader].name
            constant = complications.TYPES[element.auto_scale].constant
            return ops + [
                Comment(f"max: auto -- {element.value.ast.path}'s own scale"),
                LetAutoScale(reader, SLOT_SCALE_MODULE, constant, element.auto_scale,
                             element.value),
                Comment("no scale (an unset goal, no profile, ...) hides the whole gauge"),
                If(LocalsSet(("scale",)), tuple(self.bound(
                    Call("WfbScale.share", (Read(element.value), NumLocal("scale"))),
                    probes))),
            ]
        assert element.value is not None and element.maximum is not None  # both required
        fraction = Bin("/", Call("WfbMath.percent", (Read(element.value),
                                                     Read(element.maximum))), FloatLit(100.0))
        return ops + self.bound(fraction, probes)

    def bound(self, fraction: Num, probes: tuple[Expression, ...]) -> list[Op]:
        """A gauge bound to a value: `absent:`'s policy over ``fraction``,
        then each style's drawing."""
        element = self.element
        guards = self.ctx.value_guards
        present = (Present(guards, probes) if keeps_track(element) and guards else None)
        ops: list[Op] = []
        if element.absent == "fallback" and guards:
            # The fill fraction falls back, not the raw value/max: either half
            # of the pair can be the absent reading, so the outcome is the
            # only well-defined thing to substitute (`_check_fallback_fraction`).
            ops += [Comment(vocab.absent(element)),
                    Let("fraction", _fallback_num(element)),
                    If(Present(guards, probes), (Assign("fraction", fraction),)),
                    Blank()]
            fraction = NumLocal("fraction")
        return ops + self.styles(fraction, present)

    def slot_gauge(self) -> list[Op]:
        """A gauge on a `config: slots:` slot: the wearer's pick, against its
        own scale (`SlotScale`).  A pick with no scale draws nothing, track
        included; a scaled pick with no reading yet follows `absent:` as any
        gauge does.  While the native editor animates this slot it draws
        nothing either, as the slot's `data` element does: the editor's
        drawable draws it then.  Everything is wrapped, never returned from
        (`docs/lore/codegen.md`)."""
        element = self.element
        assert element.slot is not None
        face = self.ctx.resolved.face
        slot = face.config_data.get(element.slot)
        shown = self.ctx.shown(slot) if slot is not None else None
        sample = COMPLICATION_SLOT_SAMPLE.get(shown) if shown is not None else None
        scale = (complications.scale_for(
            shown, goals=SAMPLE_GOALS, heart_rate_zones=SAMPLE_HEART_RATE_ZONES,
            sex=SAMPLE_WEARER_SEX, age=SAMPLE_WEARER_AGE, value=sample)
            if shown is not None else None)
        reading = NumLocal("reading")
        has_reading = LocalsSet(("reading",))
        inner: list[Op] = [Let("reading", Call("WfbScale.fraction", (NumLocal("pulled"),
                                                                     NumLocal("scale"))))]
        if element.absent == "fallback":
            inner += [Comment(vocab.absent(element)),
                      Let("fraction", NumPick(has_reading, reading, _fallback_num(element))),
                      *self.styles(NumLocal("fraction"), None)]
        elif keeps_track(element):
            inner += self.styles(reading, has_reading)
        else:
            inner.append(If(has_reading, tuple(self.styles(reading, None))))
        body: list[Op] = [
            Comment(f"slot: {element.slot} -- the wearer's pick, against its own "
                    "scale"),
            LetSlotPick(config_field(f"data_{element.slot}"), SLOT_SCALE_MODULE,
                        self.ctx.complications_guarded, sample, scale),
            Comment("a pick with no scale hides the whole gauge, track included"),
            If(LocalsSet(("scale", "pulled")), tuple(inner)),
        ]
        return [
            Comment("the editor is animating this slot -- its drawable draws it (drawSlot)"),
            If(NotPulsing(config_data_ids(face)[element.slot]), tuple(body)),
        ]

    def styles(self, fraction: Num, present: Cond | None) -> list[Op]:
        """Each style's drawing from ``fraction``, the fill fraction; with
        ``present``, only the value-dependent parts are wrapped in it."""
        style = self.element.style
        if style == "needle":
            return self.needle(fraction)
        if style in ("segments", "scale"):
            # `outline:` is refused on these at build time (`ring_refusal`).
            return self.ticked(fraction, present)
        if style == "arc":
            return self.arc(fraction, present)
        return self.bar(fraction, present)

    def arc(self, fraction: Num, present: Cond | None) -> list[Op]:
        element, c = self.element, self.c
        thickness = self.thickness()

        def span(dx: int = 0, dy: int = 0) -> ArcSpan:
            return ArcSpan(Shifted(c("CX"), dx), Shifted(c("CY"), dy), c("RADIUS"), thickness,
                           c("START"), c("SWEEP"))

        def lit(dx: int = 0, dy: int = 0) -> ArcProgress:
            return ArcProgress(Shifted(c("CX"), dx), Shifted(c("CY"), dy), c("RADIUS"),
                               thickness, c("START"), c("SWEEP"), fraction)

        ops: list[Op] = []
        if self.stamp is not None:
            # Stamped: an arc's ends are undocumented, so it has no one-draw
            # dilation.  The whole track when there is one (the lit arc lies
            # inside it), else the lit arc alone, only while it draws.
            paint, width = self.stamp
            offsets = disc_perimeter_offsets(width)
            if element.track_color is not None:
                ops += [SetColor(paint), *(span(dx, dy) for dx, dy in offsets)]
            else:
                ops += _wrap(present, [SetColor(paint), *(lit(dx, dy) for dx, dy in offsets)])
            if self.ctx.ring is not None:
                return ops
            ops.append(Blank())
        if self.track is not None:
            ops += [Comment("the unfilled track"), SetColor(self.track), span(), Blank()]
        ops.append(Comment("the filled portion" if present is None else
                           "the filled portion -- absent: hide, so only while the value is "
                           "present"))
        return ops + _wrap(present, [SetColor(self.color), lit()])

    def bar(self, fraction: Num, present: Cond | None) -> list[Op]:
        element, c = self.element, self.c

        def rect(width: Num, dx: int = 0, dy: int = 0) -> Primitive:
            return Primitive("fillRectangle", ((Shifted(c("X"), dx), Shifted(c("Y"), dy), width,
                                                c("HEIGHT")),))

        def grown(width: Num) -> list[Op]:
            """A bar's ring: one rounded rectangle the ring's width larger all
            round, corners of that radius -- the watch's dilation of the
            rectangle (research 28 §7)."""
            assert self.stamp is not None
            paint, ring = self.stamp
            return [SetColor(paint), Primitive("fillRoundedRectangle", (
                (Grown(c("X"), ring, -1), Grown(c("Y"), ring, -1)),
                (Grown(width, ring, 2), Grown(c("HEIGHT"), ring, 2)),
                (Lit(ring),)))]

        ops: list[Op] = []
        ring_only = self.ctx.ring is not None
        if self.stamp is not None and element.track_color is not None:
            # The whole bar is the silhouette.
            ops += grown(c("WIDTH"))
            if ring_only:
                return ops
            ops.append(Blank())
        if self.track is not None:
            ops += [SetColor(self.track), rect(c("WIDTH")), Blank()]
        if present is not None:
            ops.append(Comment("the fill -- absent: hide, so only while the value is present"))
        filled = NumLocal("filled")
        body: list[Op] = [Let("filled", Conv(Paren(Bin("*", c("WIDTH"), fraction)), "toNumber"))]
        if self.stamp is not None and element.track_color is None:
            # No track: the lit length alone is the silhouette.
            body.append(If(Cmp(">", filled, Lit(0)), tuple(grown(filled))))
            if ring_only:
                return ops + _wrap(present, body)
        body += [SetColor(self.color), rect(filled)]
        return ops + _wrap(present, body)

    def ticked(self, fraction: Num, present: Cond | None) -> list[Op]:
        """`style: segments`: `(fraction * COUNT + 0.5).toNumber()` cells lit
        in `color:`, the rest in `track_color:` (or not drawn).  `style:
        scale`: the track, each band, then a dot at the value.  An arc cell
        or band is one `WfbArc.drawSpan`, so it follows the whole-degree
        rule every arc here does; a bar's cell edges truncate like `style:
        bar`'s fill.  ``present`` guards what the value places: while it is
        absent no cell is lit and no pointer drawn."""
        element, placed, c = self.element, self.placed, self.c
        arc = element.geometry == "arc"
        thickness = self.thickness() if arc else None

        def span(start: Num, sweep: Num) -> ArcSpan:
            assert thickness is not None
            return ArcSpan(c("CX"), c("CY"), c("RADIUS"), thickness, start, sweep)

        def bar_rect(x0: Num, x1: Num) -> list[Op]:
            return [Let("x0", x0),
                    Primitive("fillRectangle", ((Bin("+", c("X"), NumLocal("x0")), c("Y"),
                                                 Bin("-", x1, NumLocal("x0")), c("HEIGHT")),))]

        i = NumLocal("i")
        if element.style == "segments":
            count = element.count
            assert count is not None  # `style: segments` requires count:
            lit_value = Conv(Paren(Bin("+", Bin("*", Paren(fraction), Lit(count)),
                                       FloatLit(0.5))), "toNumber")
            ops: list[Op]
            if present is None:
                ops = [Let("lit", lit_value)]
            else:
                ops = [Comment("absent: hide -- every cell draws unlit while the value is absent"),
                       Let("lit", Lit(0)), If(present, (Assign("lit", lit_value),))]
            if self.track is None:
                ops.append(SetColor(self.color))
            cell: list[Op] = []
            if self.track is not None:
                cell.append(SetColor(PaintPick(Cmp("<", i, NumLocal("lit")), self.color,
                                               self.track)))
            if arc:
                cell.append(span(Bin("-", c("START"), Bin("*", i, c("STEP"))), c("CELL")))
            else:
                cell += bar_rect(Conv(Paren(Bin("*", i, c("STEP"))), "toNumber"),
                                 Conv(Paren(Bin("+", Bin("*", i, c("STEP")), c("CELL"))),
                                      "toNumber"))
            bound: Num = NumLocal("lit") if self.track is None else Lit(count)
            return ops + [For("i", bound, tuple(cell))]

        ops = []
        if self.track is not None:
            ops += [Comment("the track"), SetColor(self.track),
                    span(c("START"), c("SWEEP")) if arc
                    else Primitive("fillRectangle", ((c("X"), c("Y"), c("WIDTH"), c("HEIGHT")),))]
        for index, (_, band_color) in enumerate(element.bands):
            band = f"BAND_{index}"
            ops += [Comment(f"band {index}"), SetColor(AodDimmed(element, band_color))]
            if arc:
                ops.append(span(c(f"{band}_START"), c(f"{band}_SWEEP")))
            else:
                ops.append(Primitive("fillRectangle", ((
                    Bin("+", c("X"), c(f"{band}_X0")), c("Y"),
                    Bin("-", c(f"{band}_X1"), c(f"{band}_X0")), c("HEIGHT")),)))
        ops.append(Comment("the pointer" if present is None
                           else "the pointer -- absent: hide, so only while the value is "
                                "present"))
        pointer: list[Op] = [SetColor(self.color)]
        if arc:
            angle = NumLocal("angle")

            def offset(fn: str) -> Conv:
                return Conv(Call("Math.round", (Bin("*", c("RADIUS"), Call(fn, (angle,))),)),
                            "toNumber")

            pointer += [
                Let("angle", Bin("+", FloatLit(math.radians(placed.start_angle)),
                                 Bin("*", Paren(fraction), FloatLit(math.radians(placed.sweep))))),
                Primitive("fillCircle", ((Bin("+", c("CX"), offset("Math.sin")),),
                                         (Bin("-", c("CY"), offset("Math.cos")),),
                                         (c("POINTER"),))),
            ]
        else:
            pointer.append(Primitive("fillCircle", (
                (Bin("+", c("X"), Conv(Paren(Bin("*", c("WIDTH"), Paren(fraction))),
                                       "toNumber")),),
                (Bin("+", c("Y"), Bin("/", c("HEIGHT"), Lit(2))),),
                (c("POINTER"),))))
        return ops + _wrap(present, pointer)

    def needle(self, fraction: Num) -> list[Op]:
        """`style: needle`: one `sin`/`cos` pair for the needle's angle, then
        each part rotated and drawn -- an analog hand's own draw with
        `start + fraction * sweep` in place of the clock.  The angle's two
        constants are device-independent, so they are inlined rather than
        written to every device's `Layout`."""
        element, placed, c, prefix = self.element, self.placed, self.c, self.prefix
        angle = NumLocal("angle")
        ops: list[Op] = [
            Let("cx", c("CX")), Let("cy", c("CY")),
            Let("angle", Bin("+", FloatLit(math.radians(placed.start_angle)),
                             Bin("*", Paren(fraction), FloatLit(math.radians(placed.sweep))))),
            Let("sin", Call("Math.sin", (angle,))),
            Let("cos", Call("Math.cos", (angle,))),
        ]
        asleep = (Const(f"{prefix}_AOD_THICKNESS", placed.aod_thickness)
                  if placed.aod_thickness is not None else None)

        def pen(part_prefix: str, part: RotatablePart) -> AodPick:
            return AodPick(Const(f"{part_prefix}_THICKNESS", getattr(part, "thickness", 1)),
                           asleep)

        parts = [(f"{prefix}_NEEDLE_{index}", part) for index, part in enumerate(placed.needle)]
        if self.stamp is not None:
            # The needle ringed whole, as a hand is.
            paint, width = self.stamp
            ops.append(SetColor(paint))
            for part_prefix, part in parts:
                ops.append(Part(part, part_prefix, True, pen(part_prefix, part), ring=width))
            if self.ctx.ring is not None:
                return ops
        current = None
        for part_prefix, part in parts:
            paint = AodPart(element, part.color)
            code = color_code(paint, self.ctx.aod)
            if code != current:
                ops.append(SetColor(paint))
                current = code
            ops.append(Part(part, part_prefix, True, pen(part_prefix, part)))
        return ops


def _wrap(cond: Cond | None, body: list[Op]) -> list[Op]:
    """``body``, inside ``if (<cond>)`` when there is one."""
    return [If(cond, tuple(body))] if cond is not None else body


class ProgressKind(ElementKind[Progress, PlacedProgress]):
    name = "progress"
    ir_class = Progress
    placed_class = PlacedProgress
    antialiased = True
    ringed = True

    def ring_draws(self, element: Progress, face: Face) -> int:
        return 1 if element.style == "bar" else super().ring_draws(element, face)

    def ring_refusal(self, element: Progress) -> str | None:
        if element.style in ("segments", "scale"):
            return f"on a 'style: {element.style}' gauge is not implemented yet"
        return None

    def build(self, b: Builder, node: dict[str, Any], common: dict[str, Any], path: tuple[str | int, ...]) -> Element | None:
        slot = None
        if "slot" in node:
            slot = resolve_slot_reference(b, str(node["slot"]), b.doc.span(node, "slot"))
            if slot is None or not _check_slot_keys(b, node, common["id"]):
                return None
        auto = (slot is None and isinstance(node.get("max"), str)
                and node["max"].strip() == "auto")
        value = b.expression(node, "value") if slot is None else None
        maximum = b.expression(node, "max") if slot is None and not auto else None
        align, vertical_align = b.alignment(node)
        absence = b.absence(node)
        element = Progress(
            **common,
            style=node["style"],
            value=value,
            maximum=maximum,
            slot=slot.name if slot is not None else None,
            auto_scale=_auto_scale_type(b, node, common["id"], value) if auto else None,
            radius=b.length(node, "radius"),
            thickness=b.length(node, "thickness"),
            start_angle=b.angle(node, "start_angle"),
            sweep=b.angle(node, "sweep"),
            size=b.size(node.get("size")),
            color=b.color_expression(node, "color"),
            track_color=b.color_expression(node, "track_color"),
            absent=absence["absent"],
            fallback=absence["fallback"],
            align=align,
            vertical_align=vertical_align,
        )
        for name, bound in (("value", value), ("max", maximum)):
            if bound and not bound.value.type.is_numeric():
                b.bag.error(
                    "type",
                    f"gauge {name} must be a number, got {bound.value}",
                    b.doc.span(node, name),
                )
        if auto and element.auto_scale is None:
            return None
        if slot is not None:
            # The wearer's pick can always be absent: no reading yet, or a
            # type this watch does not have.
            reading = Expression(f"the reading of slot {slot.name}", "",
                                 expr.Value(Type.NUMBER, True), (), frozenset(), frozenset(), None)
            b.check_absence(node, element, reading, element.absent, None, element.fallback,
                            key="slot")
            _check_fallback_fraction(b, node, element)
            if element.on_hold == HOLD_AUTO:
                b.bag.error(
                    "on-hold",
                    f"{element.id}: 'on_hold: auto' on a gauge with 'slot:' is not "
                    "implemented yet",
                    b.doc.span(node, "on_hold"),
                    notes=["put 'on_hold: auto' on the slot's 'type: data' element, which "
                           "launches whatever the wearer picked"],
                )
                return None
        elif value is not None or maximum is not None:
            combined = expr.Value(
                Type.NUMBER,
                bool((value and value.nullable) or (maximum and maximum.nullable)),
            )
            probe = Expression("value/max", "", combined, (), frozenset(), frozenset(), None)
            b.check_absence(node, element, probe, element.absent, None, element.fallback,
                            key="value")
            _check_fallback_fraction(b, node, element)
        for key, owner in _STYLE_ONLY_KEYS.items():
            if key in node and element.style != owner:
                b.bag.error("element", f"{element.id}: '{key}:' is read only by 'style: {owner}'",
                            b.doc.span(node, key))
                return None
        if element.style == "needle":
            if not _build_needle(b, node, element):
                return None
        elif element.style in ("segments", "scale"):
            if not _build_ticked(b, node, element):
                return None
        b.check_other_absence(node, element, "color", element.color)
        b.check_other_absence(node, element, "track_color", element.track_color)
        b.check_reachable_substitute(node, element, "'color'/'track_color'",
                                     (element.value, element.maximum),
                                     (element.color, element.track_color))
        return element

    def resolve(self, r: Resolver, element: Progress, parent: Box, depth: int) -> Placed:
        cx, cy = r.point(element.at, parent)
        min_1px = element.resolved_min_1px
        if element.geometry == "arc":
            radius = round(r.extent(element.radius, parent, Axis.MINOR, 0,
                                    min_1px=min_1px, what="radius"))
            thickness = max(1, round(r.extent(element.thickness, parent, Axis.MINOR, 1,
                                              min_1px=min_1px, what="thickness")))
            # The author's clockwise-positive angle becomes Garmin's
            # counter-clockwise one; a positive sweep therefore draws clockwise
            # on the device.  `shape: arc` calls the same helper.
            box, cx, cy, start, sweep, garmin_start, direction = arc_box(
                radius, thickness, cx, cy, element.align, element.vertical_align,
                element.start_angle, element.sweep)
            aod_thickness = r.aod_extent(element, "thickness", parent, 1)
            placed = PlacedProgress(
                element, box, (round(cx), round(cy)), depth,
                radius=radius, thickness=thickness,
                start_angle=start, sweep=sweep,
                garmin_start=garmin_start,
                garmin_direction=direction,
                aod_thickness=aod_thickness,
            )
            if element.style in ("segments", "scale"):
                _resolve_ticked(r, element, placed, parent)
            return placed
        if element.style == "needle":
            parts, reach = r.resolve_parts(list(element.needle), f"{element.id}.needle",
                                           min_1px=min_1px)
            # `style: needle` requires both angles.
            assert element.start_angle is not None and element.sweep is not None
            disc = Box(cx - reach, cy - reach, 2 * reach, 2 * reach)
            return PlacedProgress(
                element, disc.rounded(), (round(cx), round(cy)), depth,
                start_angle=element.start_angle.degrees, sweep=element.sweep.degrees,
                needle=rotatable_parts(parts, f"{element.id}.needle"), reach=reach,
                aod_thickness=r.aod_extent(element, "thickness", parent, 1),
            )
        sized, cx, cy = r.sized_box(element, parent, cx, cy)
        placed = PlacedProgress(element, sized.rounded(min_1px=min_1px), (round(cx), round(cy)),
                                depth, size=(round(sized.width), round(sized.height)))
        if element.style in ("segments", "scale"):
            _resolve_ticked(r, element, placed, parent)
        return placed

    def circular_extent(self, placed: PlacedProgress) -> tuple[float, float, float] | None:
        if placed.element.geometry == "arc":
            reach = placed.radius + max(placed.thickness / 2.0, float(placed.pointer))
            return (placed.center[0], placed.center[1], reach)
        if placed.element.style == "needle":
            return (placed.center[0], placed.center[1], placed.reach)
        return None

    def lower(self, ctx: DrawContext, placed: PlacedProgress) -> list[Op]:
        """The gauge: its value's fill fraction under `absent:`'s policy (a
        `slot:` pick or `max: auto` scaled first), then its style's drawing,
        after its `outline:` ring when it has one.  With `ctx.ring` (an
        outlined group's pass), only the ring is drawn, in its colour."""
        return _Lowering(ctx, placed).ops()

    def draws_while_absent(self, element: Progress) -> bool:
        return keeps_track(element)

    def describe(self, placed: PlacedProgress) -> str:
        return article(f"{placed.element.style} gauge")

    def live_handle(self, placed: PlacedProgress, handle: dict[str, Any]) -> dict[str, Any] | None:
        """A plain arc gauge (`style: arc`) draws its track and its fill from
        `_RADIUS`, `_START` and `_SWEEP` alone, the fill as a fraction of
        the sweep (`WfbArc.drawProgress`): centred, its radius moves nothing
        else, and a turn sets one angle.  Segments and a scale work their
        cells and bands out from the sweep, and stay drawn as an outline."""
        element = placed.element
        if element.style != "arc":
            return None
        prefix = const_prefix(placed.id)
        raw = handle.get("key")
        key = tuple(raw) if isinstance(raw, list) else (raw,)
        if handle["kind"] == "angle":
            return {"angle": f"{prefix}_START" if key == ("start_angle",) else f"{prefix}_SWEEP"}
        centred = (getattr(element, "align", "center") == "center"
                   and getattr(element, "vertical_align", "center") == "center")
        if handle["kind"] == "size" and key == ("radius",) and centred:
            return {"consts": {f"{prefix}_RADIUS": 1}}
        return None

    def layout_constants(self, prefix: str,
                         placed: PlacedProgress) -> "layout_constants_mod.Constants":
        out: "layout_constants_mod.Constants" = [
            (f"{prefix}_CX", placed.center[0], ""),
            (f"{prefix}_CY", placed.center[1], ""),
        ]
        element = placed.element
        if element.geometry == "arc":
            out.extend(layout_constants_mod.arc_constants(prefix, placed))
            out.extend(layout_constants_mod.aod_thickness_constant(prefix, placed))
        elif element.style == "needle":
            out.extend(layout_constants_mod.aod_thickness_constant(
                prefix, placed, layout_constants_mod.EVERY_PART_NOTE))
            for index, part in enumerate(placed.needle):
                out.extend(layout_constants_mod.hand_part_constants(
                    f"{prefix}_NEEDLE_{index}", "needle", index, part))
        else:
            out.extend(layout_constants_mod.box_constants(prefix, placed.rect or placed.inner_box))
        if element.style == "segments":
            unit = "degrees" if element.geometry == "arc" else "px"
            out.append((f"{prefix}_CELL", float(placed.cell), f"one cell, {unit}"))
            out.append((f"{prefix}_STEP", float(placed.step), f"cell start to cell start, {unit}"))
        elif element.style == "scale":
            out.append((f"{prefix}_POINTER", placed.pointer, "the value dot's radius"))
            for index, (a, b) in enumerate(placed.band_spans):
                if element.geometry == "arc":
                    out.append((f"{prefix}_BAND_{index}_START", float(90.0 - a),
                                f"{a:g}deg clockwise from 12 o'clock, in Garmin's convention"))
                    out.append((f"{prefix}_BAND_{index}_SWEEP", float(b),
                                "clockwise-positive degrees"))
                else:
                    out.append((f"{prefix}_BAND_{index}_X0", int(a), "px from the bar's left"))
                    out.append((f"{prefix}_BAND_{index}_X1", int(b), ""))
        return out

    def contrast_subjects(self, placed: PlacedProgress) -> Iterator[ContrastSubject]:
        """A needle yields each part's own effective colour, like a hand's
        (`wfb.kinds.hands.HandsKind.contrast_subjects`); the other styles
        judge the element's `color:`."""
        if placed.element.style != "needle":
            yield from super().contrast_subjects(placed)
            return
        ring = placed.element.outline.color if placed.element.outline is not None else None
        for index, part in enumerate(placed.needle):
            yield f"{placed.id}.needle[{index}]", part.color, ring, True


KIND = ProgressKind()
