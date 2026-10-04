"""The single draw program: each element is lowered once into a list of
drawing ops, which a printer writes as Monkey C (`printer`) and an evaluator
paints on the host (`evaluator`).

Every kind that draws overrides `ElementKind.lower`.  `program` puts the
element's own guards (`visible:`, absence, `antialias:`) around it, and the
view prints that (`emit_body`) while the preview paints it (`paint`).
The values and ops are in `program`; the barrel's arithmetic the evaluator
needs, transcribed from `runtime-lib/`, is in `barrel`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import kinds, vocab
from .program import DrawContext, Op

if TYPE_CHECKING:
    from ..emit.monkeyc.common import AodStyle, RingPass
    from ..emit.monkeyc.readplan import ReadPlan
    from ..emit.writer import Writer
    from ..layout import Placed, ResolvedFace
    from ..preview import Renderer

__all__ = ["DrawContext", "Op", "drawn_text", "emit_body", "lowered", "paint", "program"]


def lowered(ctx: DrawContext, placed: "Placed") -> list[Op]:
    """``placed``'s own drawing, its kind's `lower`."""
    return kinds.for_placed(placed).lower(ctx, placed)


def program(ctx: DrawContext, placed: "Placed", plan: "ReadPlan",
            antialias_default: bool | None = None) -> list[Op]:
    """The whole body of ``placed``'s `draw<Id>` (or, with `ctx.ring`, its
    `ring<Id>`) after its reads: the element's own guards, then its drawing.

    - `visible:` first, before every other guard: it gates the element as a
      whole (`VisibleGuard`).
    - A data element (`complication_slot`) has no other guard: its reading
      is a fresh per-frame pull, not an element-level binding.
    - `placeholder`/`fallback` govern the *value*: a substitute takes over
      instead of the element not drawing.  They say nothing about a nullable
      colour, track colour or max, which always hide the element, so those
      keep a real guard whatever the value's policy.  A gauge that keeps its
      track while absent (`ElementKind.draws_while_absent`) guards its value
      itself, so it too is guarded here only for its other bindings.
      Anything else hides as a whole while any binding is absent
      (`NullGuard`).
    - `antialias:` brackets only the drawing, after every guard: a guard
      returns early, and toggling first would leave `dc` anti-aliased on a
      frame that drew nothing (`AntiAlias`).  Only a primitive-drawing kind
      has the switch; glyph kinds anti-alias in their baked font."""
    from .. import catalog
    from ..emit.monkeyc.view import _negated
    from ..ir import local_name
    from .program import AntiAlias, NullGuard, VisibleGuard

    element = placed.element
    kind = kinds.for_placed(placed)
    ops: list[Op] = []
    visible = element.visible
    if visible is not None:
        always = visible.constant is not None and bool(visible.constant)
        ops.append(VisibleGuard(visible, tuple(plan.visible_guards(placed)),
                                "" if always else _negated(visible)))
    if kind.name == "complication_slot":
        return ops + lowered(ctx, placed)
    paths = {local_name(path): path for path in catalog.CATALOG}

    def guard(names: list[str], note: str) -> None:
        if names:
            ops.append(NullGuard(tuple(names), tuple(paths[name] for name in names), note))

    substitutes = (bool(element.VALUE_ROLES)
                   and getattr(element, "when_absent", None) in ("placeholder", "fallback"))
    if substitutes or (kind.draws_while_absent(element) and plan.value_guards(placed)):
        guard(plan.other_guards(placed),
              "hide -- a nullable colour/track_color/max always hides the element, "
              "regardless of the value's own absent:")
    else:
        guard(plan.guards(placed), vocab.absent(element))
    toggles = (antialias_default is not None and kind.antialiased
               and element.resolved_antialias != antialias_default)
    if toggles:
        ops.append(AntiAlias(element.resolved_antialias, comment=True))
    ops += lowered(ctx, placed)
    if toggles and antialias_default is not None:
        ops.append(AntiAlias(antialias_default))
    return ops


def emit_body(w: "Writer", resolved: "ResolvedFace", placed: "Placed", plan: "ReadPlan",
              aod: "AodStyle", ring: "RingPass | None" = None,
              antialias_default: bool | None = None) -> None:
    """The printed `draw<Id>` body (or a `ring<Id>` pass), after its reads."""
    from .printer import print_ops

    guards = () if kinds.for_placed(placed).name == "complication_slot" else tuple(
        plan.value_guards(placed))
    ctx = DrawContext(resolved, aod, guards, ring,
                      complications_guarded=plan.device_guards.complications)
    print_ops(w, program(ctx, placed, plan, antialias_default), aod)


def paint(renderer: "Renderer", placed: "Placed", ring: "RingPass | None" = None,
          ring_color: tuple[int, int, int] | None = None) -> None:
    """Paint ``placed``'s program, its guards included; with ``ring``, its
    share of an outlined group's ring in ``ring_color``.

    The program is lowered with always-on code present (`AodStyle(on=True)`)
    and the evaluator takes the branch of the frame being painted, which is
    the pixel result of any build's choice."""
    from .evaluator import Evaluator

    ctx = _context(renderer, placed, ring)
    Evaluator(renderer, ring_color).run_program(program(ctx, placed, renderer.read_plan))


def _context(renderer: "Renderer", placed: "Placed",
             ring: "RingPass | None" = None) -> DrawContext:
    """How the host lowers ``placed``: with always-on code present
    (`AodStyle(on=True)`) and the face's own dimming, so the frame being
    painted picks its branch, and with the same value guards the view
    passes."""
    from ..emit.monkeyc.common import AodStyle
    from ..palette import dim_fraction

    dim = renderer.resolved.face.aod_dim
    aod = AodStyle(on=True, dim=dim_fraction(dim) if dim is not None else None)
    return DrawContext(renderer.resolved, aod, tuple(renderer.value_guards(placed)), ring,
                       picks=renderer.options.picks)


def drawn_text(resolved: "ResolvedFace", placed: "Placed", values: dict[str, object],
               *, aod: bool = False) -> str | None:
    """The string ``placed`` (a lowered, text-drawing element) draws at the
    readings ``values``, in the always-on frame when ``aod``: what the
    preview paints, without painting it.  `None` when it draws none, its
    reading being absent with nothing to substitute."""
    from ..emit.monkeyc.common import AodStyle
    from ..emit.monkeyc.readplan import ReadPlan
    from .evaluator import str_value
    from .program import IfAod, IfAwake, IfNotNull, LetText, Text

    ctx = DrawContext(resolved, AodStyle(on=True), tuple(ReadPlan(resolved).value_guards(placed)))
    ops = lowered(ctx, placed)
    env: dict[str, str | None] = {}

    def walk(body: "list[Op] | tuple[Op, ...]") -> tuple[bool, str | None]:
        for op in body:
            if isinstance(op, LetText):
                value = str_value(op.value, values, env, aod)
                env[op.name] = value if value is not None else str_value(op.initial, values, env,
                                                                          aod)
            elif isinstance(op, Text):
                return True, str_value(op.text, values, env, aod)
            elif isinstance(op, IfNotNull):
                found = walk(op.body)
                if found[0]:
                    return found
            elif isinstance(op, IfAod):
                found = walk(op.then if aod else op.otherwise)
                if found[0]:
                    return found
            elif isinstance(op, IfAwake) and not aod:
                found = walk(op.body)
                if found[0]:
                    return found
        return False, None

    return walk(ops)[1]
