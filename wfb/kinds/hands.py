"""`type: hands` -- places a declared `hands:` set on screen, axis at
`at:`."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import math
from collections.abc import Callable
from dataclasses import dataclass

from ..ir.builder import dedup_append
from ..ir.model import Element, Expression, HandsElement
from ..layout import Placed, PlacedHands, ResolvedHand
from ..units import Box
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc import rotated
from ..emit.monkeyc.common import NO_AOD, AodStyle, and_list, const_prefix
from ..emit.writer import Writer
from . import ElementKind

if TYPE_CHECKING:
    from ..ir.builder import Builder
    from ..layout import Resolver
    from ..preview import Renderer


@dataclass(frozen=True)
class HandAngle:
    """One analog hand's angle rule (plan 04), both halves side by side --
    the `expr.Function`/`formatting.Code` pattern (plan 19 A1) applied to
    `runtime-lib/WfbHands.mc`: `monkeyc_function`/`monkeyc_return` are that
    function's name and its exact `return` expression, checked against the
    real `.mc` source by `tests/test_hand_angles.py` so the two cannot
    drift; `host` is `wfb.preview`'s own radians computation, Python's
    degrees-to-radians conversion rather than a reimplementation of the
    Monkey C constant, kept at exactly today's expression so a preview
    pixel never moves.
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
        lambda hour, minute, second: math.radians(((hour % 12) * 60 + minute) * 0.5),
    ),
    "minute": HandAngle(
        "minuteAngle", "clock.min * (Math.PI / 30.0)",
        lambda hour, minute, second: math.radians(minute * 6.0),
    ),
    "second": HandAngle(
        "secondAngle", "clock.sec * (Math.PI / 30.0)",
        lambda hour, minute, second: math.radians(second * 6.0),
    ),
}

#: hand name -> the `WfbHands` function that turns the time into its angle
#: (`HAND_ANGLES`'s own Monkey C half).
_HAND_ANGLE_FUNCTIONS = tuple(
    (name, HAND_ANGLES[name].monkeyc_function) for name in ("hour", "minute", "second")
)


def _emit_one_hand(w: Writer, element, prefix: str, hand_name: str, angle_fn: str, hand,
                   declared: bool, thickness_override: str | None, aod: AodStyle) -> None:
    """One hand's angle/sin/cos, then each of its parts, rotated and drawn.

    `declared` says whether `angle`/`sin`/`cos` already have a `var` in this
    method -- the first hand declares them, every later one reuses the same
    three locals (the probe's own shape: Monkey C has no block scoping that
    would need a fresh declaration per hand).
    """
    keyword = "" if declared else "var "
    w.line(f"{keyword}angle = WfbHands.{angle_fn}(clock);")
    w.line(f"{keyword}sin = Math.sin(angle);")
    w.line(f"{keyword}cos = Math.cos(angle);")
    # One setColor per colour *change*: consecutive parts of one hand
    # usually share its default colour.  Reset per hand rather than
    # carried across hands, because an `awake` second hand sits inside its
    # own `if` block and cannot rely on a colour set before it.
    current = None
    for index, part in enumerate(hand.parts):
        part_prefix = f"{prefix}_{hand_name.upper()}_{index}"
        color = aod.part_color(element, part.color)
        if color != current:
            w.line(f"dc.setColor({color}, Graphics.COLOR_TRANSPARENT);")
            current = color
        rotated.emit_transformed_part(
            w, part, part_prefix, radial=True,
            thickness_expr=aod.value(thickness_override, f"Layout.{part_prefix}_THICKNESS"))


class HandsKind(ElementKind):
    name = "hands"
    ir_class = HandsElement
    placed_class = PlacedHands
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
                f"hands.{name} declares none",
                b.doc.span(node, "seconds"),
                notes=[f"hands.{name} declares: {declared}"],
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
                f"{element_id}: 'seconds: never' on hands.{name}, which has only a "
                "second hand, draws nothing",
                b.doc.span(node, "seconds"),
                notes=["remove the element, or place a set with an hour or minute hand"],
            )
            return None

        if "low_power" in common["modes"]:
            b.bag.error(
                "hands",
                f"{element_id}: 'modes:' may not include 'low_power' on analog hands",
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
            resolved[name] = ResolvedHand(parts=parts)
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

    def circular_extent(self, placed: PlacedHands):
        return (placed.center[0], placed.center[1], placed.reach)

    def draw_preview(self, renderer: Renderer, placed: PlacedHands) -> None:
        """`type: hands` -- the same three angle rules `runtime-lib/
        WfbHands.mc` computes on the device (`HAND_ANGLES`'s own
        `host` half), applied to the *resolved* geometry so this can never
        disagree with the generated code about a hand's shape or its axis.

        `--asleep` (or `--aod`, which implies it) hides an `awake`-only
        second hand, the same choice the generated view makes while
        `_sleeping`; a `seconds: never` hand was already excluded at resolve
        time.
        """
        element = placed.element
        s = renderer.scale
        cx, cy = placed.center[0] * s, placed.center[1] * s
        hour = int(renderer.values.get("time.hour", 0) or 0)
        minute = int(renderer.values.get("time.minute", 0) or 0)
        second = int(renderer.values.get("time.second", 0) or 0)
        angles = {
            name: HAND_ANGLES[name].host(hour, minute, second)
            for name in ("hour", "minute", "second")
        }
        asleep = renderer.options.asleep or renderer.options.aod
        for hand_name in ("hour", "minute", "second"):
            hand = getattr(placed, hand_name)
            if hand is None:
                continue
            if hand_name == "second" and element.seconds == "awake" and asleep:
                continue
            sin_t, cos_t = math.sin(angles[hand_name]), math.cos(angles[hand_name])
            for part in hand.parts:
                renderer.hand_part(placed, part, cx, cy, sin_t, cos_t)

    def emit_draw(self, w: Writer, resolved, placed: PlacedHands, value_guards, plan,
                  aod: AodStyle = NO_AOD) -> None:
        """`type: hands` -- one `sin`/`cos` pair per drawn hand, then rotate and
        draw each of its parts, shaped exactly like the analog-hands probe's
        `drawMainHands` (`docs/research/probes/analog-hands/`): the axis first,
        then hour, minute, second in that fixed order, with an `awake` second
        hand's parts wrapped in `if (!_sleeping)`.

        `aod: {color: ...}`/`{thickness: ...}` (plan 14 §5.1) apply uniformly to
        every part of every hand: one ternary against one element-level override,
        reused by every part's own colour/pen-width line.
        """
        element = placed.element
        prefix = const_prefix(placed.id)
        w.line(f"var cx = Layout.{prefix}_CX;")
        w.line(f"var cy = Layout.{prefix}_CY;")
        thickness_override = rotated.aod_thickness_override(placed, prefix)
        declared = False
        for hand_name, angle_fn in _HAND_ANGLE_FUNCTIONS:
            hand = getattr(placed, hand_name)
            if hand is None:
                continue
            gated = hand_name == "second" and element.seconds == "awake"
            w.blank()
            w.comment(f"{hand_name}" + (" -- seconds: awake" if gated else ""))
            with w.block_if("if (!_sleeping)" if gated else None):
                _emit_one_hand(w, element, prefix, hand_name, angle_fn, hand, declared,
                               thickness_override, aod)
            declared = True

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

    def contrast_subjects(self, placed: PlacedHands):
        """A `hands` element yields each part of each hand (its effective
        colour, `ResolvedHandPart.color`) -- it has no per-part structure on
        the IR to give `Element.color_roles()` a label finer than the whole
        element."""
        for hand in ("hour", "minute", "second"):
            resolved_hand = getattr(placed, hand)
            if resolved_hand is None:
                continue
            for index, part in enumerate(resolved_hand.parts):
                yield f"{placed.id}.{hand}.parts[{index}]", part.color, None, True


KIND = HandsKind()
