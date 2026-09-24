"""`type: hands` -- places a declared `hands:` set on screen, axis at
`at:`."""

from __future__ import annotations

from ..ir.model import HandsElement
from ..layout import PlacedHands, Resolver
from ..preview import _Renderer
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc import rotated
from ..emit.monkeyc.common import _and_list
from . import ElementKind


def precheck(doc, bag, element: dict) -> bool:
    """`seconds: always` is not implemented; say why rather than list the
    two values the schema's `seconds:` enum does accept."""
    if element.get("type") != "hands":
        return False
    if element.get("seconds") != "always":
        return False
    bag.error(
        "schema",
        "'seconds: always' is not implemented yet -- a second hand while "
        "asleep needs a full-frame buffer and a moving onPartialUpdate clip, "
        "a different buffer architecture from 'static:'s paint-once one",
        doc.span(element, "seconds"),
        notes=["see docs/limitations.md, \"Not implemented yet\"",
               "'seconds: awake' (the default -- drawn while awake, hidden "
               "asleep) or 'seconds: never' are implemented"],
    )
    return True


def circular_extent(placed: PlacedHands):
    return (placed.center[0], placed.center[1], placed.reach)


def describe(placed: PlacedHands) -> str:
    element = placed.element
    drawn = [n for n in ("hour", "minute", "second") if getattr(placed, n, None) is not None]
    seconds_note = f", seconds: {element.seconds}" if element.seconds else ""
    return f"analog hands (hands.{element.hands}): {_and_list(drawn)}{seconds_note}"


def contrast_subjects(placed: PlacedHands):
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


KIND = ElementKind(
    name="hands",
    ir_class=HandsElement,
    placed_class=PlacedHands,
    build=lambda b, node, common, path: b._build_hands_element(node, common),
    resolve=Resolver._resolve_hands,
    static_forbidden=(
        "analog hands",
        "a hand's angle is the time -- a buffer filled once would freeze "
        "it at whatever it showed on the first frame",
    ),
    precheck=precheck,
    antialiased=True,
    circular_extent=circular_extent,
    draw_preview=_Renderer._hands,
    emit_draw=lambda w, resolved, placed, value_guards, plan, aod: rotated._emit_hands(
        w, placed, aod),
    describe=describe,
    layout_constants=layout_constants_mod._hands_constants,
    contrast_subjects=contrast_subjects,
)
