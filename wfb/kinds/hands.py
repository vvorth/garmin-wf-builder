"""`type: hands` -- places a declared `hands:` set on screen, axis at
`at:`."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from collections.abc import Callable
from dataclasses import dataclass, replace

from ..ir.builder import dedup_append
from ..ir.model import Element, Expression, HandsElement
from ..layout import Placed, PlacedHands, ResolvedHand, rotatable_parts
from ..units import Box
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc.common import and_list, const_prefix
from ..draw import barrel
from ..draw.printer import color_code
from ..draw.program import (
    AodDimmed, AodPart, AodPick, Assign, Blank, Call, Comment, Const, Disagreement, DrawContext,
    If, Let, Num, NumLocal, NotSleeping, Op, Paint, Part, RingColor, SetColor,
)
from ..draw.program import HandAngle as AngleOf
from . import ElementKind

if TYPE_CHECKING:
    from collections.abc import Iterator

    from . import ContrastSubject
    from ..ir.builder import Builder
    from ..layout import Resolver, RotatablePart


@dataclass(frozen=True)
class HandAngle:
    """One analog hand's angle rule, both halves side by side --
    the `expr.Function`/`formatting.Code` pattern applied to
    `runtime-lib/WfbHands.mc`: `monkeyc_function`/`monkeyc_return` are that
    function's name and its exact `return` expression, checked against the
    real `.mc` source by `tests/test_hand_angles.py` so the two cannot
    drift; `host` is its twin in `wfb.draw.barrel`, which the preview
    evaluates.
    """

    monkeyc_function: str
    monkeyc_return: str
    host: Callable[[int, int, int], float]


#: Hour: 30 degrees an hour plus half a degree a minute, so it sits between
#: numerals at half past rather than jumping on the hour.  Minute/second:
#: whole minutes/seconds, 6 degrees each.  `host` takes `(hour, minute,
#: second)`, the sample the preview always has on hand, even though a given
#: hand's rule only reads one or two of the three.
HAND_ANGLES: dict[str, HandAngle] = {
    "hour": HandAngle(
        "hourAngle", "((clock.hour % 12) * 60 + clock.min) * (Math.PI / 360.0)",
        barrel.hour_angle,
    ),
    "minute": HandAngle(
        "minuteAngle", "clock.min * (Math.PI / 30.0)", barrel.minute_angle,
    ),
    "second": HandAngle(
        "secondAngle", "clock.sec * (Math.PI / 30.0)", barrel.second_angle,
    ),
}

#: hand name -> the `WfbHands` function that turns the time into its angle
#: (`HAND_ANGLES`'s own Monkey C half).
_HAND_ANGLE_FUNCTIONS = tuple(
    (name, HAND_ANGLES[name].monkeyc_function) for name in ("hour", "minute", "second")
)


class HandsKind(ElementKind[HandsElement, PlacedHands]):
    name = "hands"
    ir_class = HandsElement
    placed_class = PlacedHands
    ringed = True
    rings_itself = True
    static_forbidden = (
        "analog hands",
        "a hand's angle is the time -- a buffer filled once would freeze "
        "it at whatever it showed on the first frame",
    )
    antialiased = True

    def build(self, b: Builder, node: dict[str, Any], common: dict[str, Any], path: tuple[str | int, ...]) -> Element | None:
        """`type: hands` -- places a declared `hands:` set on screen.

        `common["at"]` is already the axis (resolved exactly like any
        element's `at:`); there is no `size:` to build, because the
        element's extent is the disc it sweeps, computed later in
        `wfb.layout`, not a box.
        """
        name = node["hands"]
        element_id = common["id"]
        hand_set = b.hand_sets.resolve(
            b.bag, name, b.doc.span(node, "hands"), code="hands",
            message=f"{element_id}: unknown hand set {name!r}",
            note="declared hand sets",
        )
        if hand_set is None:
            return None

        seconds = node.get("seconds")
        if seconds is not None and hand_set.second is None:
            declared = ", ".join(n for n, _ in hand_set.hands()) or "(none)"
            b.bag.error(
                "hands",
                f"{element_id}: 'seconds: {seconds}' needs a second hand, but "
                f"hand_sets.{name} declares none",
                b.doc.span(node, "seconds"),
                notes=[f"hand_sets.{name} declares: {declared}"],
            )
            return None
        if seconds is None and hand_set.second is not None:
            seconds = "awake"  # the default
        if seconds == "never" and hand_set.hour is None and hand_set.minute is None:
            # The one combination that draws nothing at all -- refused rather
            # than generated as a method with no drawing in it (no silent
            # no-ops, CLAUDE.md §7).
            b.bag.error(
                "hands",
                f"{element_id}: 'seconds: never' on hand_sets.{name}, which has only a "
                "second hand, draws nothing",
                b.doc.span(node, "seconds"),
                notes=["remove the element, or place a set with an hour or minute hand"],
            )
            return None

        if "low_power" in common["modes"]:
            b.bag.error(
                "hands",
                f"{element_id}: 'sleep_update: true' is not accepted on analog hands",
                b.doc.span(node, "modes") or common["span"],
                notes=["the hour and minute hands never need it -- they change once a "
                       "minute, and the sleeping onUpdate already redraws them",
                       "a second hand while asleep is 'seconds: always', which is not "
                       "implemented yet (docs/limitations.md)"],
            )
            return None

        colors: list[Expression] = []
        for hand_name, hand in hand_set.hands():
            if hand_name == "second" and seconds == "never":
                continue  # never drawn, so its colours reach no lint and no read
            dedup_append(colors, hand.color)
            for part in hand.parts:
                dedup_append(colors, part.color)

        return HandsElement(**common, hands=name, seconds=seconds, colors=tuple(colors))

    def resolve(self, r: Resolver, element: HandsElement, parent: Box, depth: int) -> Placed:
        """`type: hands` -- the axis, plus every part of every drawn hand
        resolved to whole pixels in the hand's own frame.  The rotation is
        the one piece of layout arithmetic the device performs (ADR 0004,
        amended).
        """
        cx, cy = r.point(element.at, parent)
        hand_set = r.face.hands[element.hands]
        resolved: dict[str, ResolvedHand] = {}
        reach = 0.0
        for name, hand in hand_set.hands():
            if name == "second" and element.seconds == "never":
                # Not drawn: left unresolved, exactly as if the set declared
                # no `second:`, so it neither emits nor inflates the reach.
                continue
            # `<id>.<hand>`: a set has up to three `parts:` lists, so the bare
            # id would not say which hand a `sub-pixel-length` finding means.
            parts, hand_reach = r.resolve_parts(
                hand.parts, f"{element.id}.{name}", min_1px=element.resolved_min_1px)
            resolved[name] = ResolvedHand(parts=rotatable_parts(parts, f"{element.id}.{name}"))
            reach = max(reach, hand_reach)
        axis = (round(cx), round(cy))
        box = Box(cx - reach, cy - reach, 2 * reach, 2 * reach)
        aod_thickness = r.aod_extent(element, "thickness", parent, 1)
        return PlacedHands(
            element, box.rounded(), axis, depth,
            hour=resolved.get("hour"), minute=resolved.get("minute"),
            second=resolved.get("second"), reach=reach,
            aod_thickness=aod_thickness,
        )

    def circular_extent(self, placed: PlacedHands) -> tuple[float, float, float] | None:
        return (placed.center[0], placed.center[1], placed.reach)

    def lower(self, ctx: DrawContext, placed: PlacedHands) -> list[Op]:
        """`type: hands` -- one `sin`/`cos` pair per drawn hand, then each of
        its parts rotated and drawn, shaped like the analog-hands probe's
        `drawMainHands` (`docs/research/probes/analog-hands/`): the axis
        first, then hour, minute, second in that fixed order, with an `awake`
        second hand's parts wrapped in `if (!_sleeping)`.  The first hand
        declares `angle`/`sin`/`cos`; every later one reuses them.

        `aod: {color: ...}`/`{thickness: ...}` apply uniformly to every part
        of every hand: one element-level override, reused by every part's own
        colour and pen width.

        `outline:` rings each hand whole, just before its parts: every part's
        ring in the ring colour (`WfbRing`, each part rotated once), then the
        parts -- so a hand's own parts never ring each other, and each hand's
        ring is drawn over the hand beneath it.  With `ctx.ring`, only the
        rings are drawn.  Colours are set once per change within a hand,
        reset per hand: an `awake` second hand sits in its own `if` and
        cannot rely on a colour set before it."""
        element = placed.element
        prefix = const_prefix(placed.id)
        override = (Const(f"{prefix}_AOD_THICKNESS", placed.aod_thickness)
                    if placed.aod_thickness is not None else None)
        stamp: tuple[Paint, int] | None = None
        if ctx.ring is not None:
            stamp = (RingColor(), ctx.ring.width)
        elif element.outline is not None:
            stamp = (AodDimmed(element, element.outline.color), element.outline.width)
        ops: list[Op] = [Let("cx", Const(f"{prefix}_CX", placed.center[0])),
                         Let("cy", Const(f"{prefix}_CY", placed.center[1]))]
        declared = False
        for hand_name, angle_fn in _HAND_ANGLE_FUNCTIONS:
            hand = getattr(placed, hand_name)
            if hand is None:
                continue
            gated = hand_name == "second" and element.seconds == "awake"
            angle = NumLocal("angle")
            assign: Callable[[str, Num], Op] = Assign if declared else Let
            body: list[Op] = [
                assign("angle", AngleOf(angle_fn, hand_name)),
                assign("sin", Call("Math.sin", (angle,))),
                assign("cos", Call("Math.cos", (angle,))),
            ]
            parts = [(f"{prefix}_{hand_name.upper()}_{index}", part)
                     for index, part in enumerate(hand.parts)]

            def pen(part_prefix: str, part: RotatablePart) -> AodPick:
                return AodPick(Const(f"{part_prefix}_THICKNESS", getattr(part, "thickness", 1)),
                               override)

            if stamp is not None:
                body.append(SetColor(stamp[0]))
                for part_prefix, part in parts:
                    ring = Part(part, part_prefix, True, pen(part_prefix, part), ring=stamp[1])
                    if part.shape == "circle" and part.filled:
                        body.append(Disagreement(
                            watch=(ring,), preview=(replace(ring, stamp=True),),
                            why="the watch is sent a grown circle; the preview stamps, and "
                                "which of the two the watch's rasteriser matches is not yet "
                                "measured"))
                    else:
                        body.append(ring)
            if ctx.ring is None:
                current = None
                for part_prefix, part in parts:
                    paint = AodPart(element, part.color)
                    code = color_code(paint, ctx.aod)
                    if code != current:
                        body.append(SetColor(paint))
                        current = code
                    body.append(Part(part, part_prefix, True, pen(part_prefix, part)))
            ops += [Blank(), Comment(f"{hand_name}" + (" -- seconds: awake" if gated else ""))]
            ops += [If(NotSleeping(), tuple(body))] if gated else body
            declared = True
        return ops

    def describe(self, placed: PlacedHands) -> str:
        element = placed.element
        drawn = [n for n in ("hour", "minute", "second") if getattr(placed, n, None) is not None]
        seconds_note = f", seconds: {element.seconds}" if element.seconds else ""
        return f"analog hands (hands.{element.hands}): {and_list(drawn)}{seconds_note}"

    def layout_constants(self, prefix: str,
                         placed: PlacedHands) -> "layout_constants_mod.Constants":
        out: "layout_constants_mod.Constants" = [
            (f"{prefix}_CX", placed.center[0], "the axis"),
            (f"{prefix}_CY", placed.center[1], ""),
        ]
        out.extend(layout_constants_mod.aod_thickness_constant(
            prefix, placed, layout_constants_mod.EVERY_PART_NOTE))
        for hand_name in ("hour", "minute", "second"):
            hand = getattr(placed, hand_name)
            if hand is None:
                continue
            for index, part in enumerate(hand.parts):
                out.extend(layout_constants_mod.hand_part_constants(
                    f"{prefix}_{hand_name.upper()}_{index}", f"{hand_name} hand", index, part))
        return out

    def contrast_subjects(self, placed: PlacedHands) -> Iterator[ContrastSubject]:
        """A `hands` element yields each part of each hand (its effective
        colour, `ResolvedHandPart.color`) -- it has no per-part structure on
        the IR to give `Element.color_roles()` a label finer than the whole
        element."""
        ring = placed.element.outline.color if placed.element.outline is not None else None
        for hand in ("hour", "minute", "second"):
            resolved_hand = getattr(placed, hand)
            if resolved_hand is None:
                continue
            for index, part in enumerate(resolved_hand.parts):
                yield f"{placed.id}.{hand}.parts[{index}]", part.color, ring, True


KIND = HandsKind()
