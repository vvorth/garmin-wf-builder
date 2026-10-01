"""The single draw program: each element is lowered once into a list of
drawing ops, which a printer writes as Monkey C (`printer`) and an evaluator
paints on the host (`evaluator`).

A kind opts in by overriding `ElementKind.lower`; a kind that has not yet
done so keeps its own `emit_draw` and `draw_preview`, and the view and the
preview reach whichever the kind has through `emit_body` and `paint` here.
The values and ops are in `program`; the barrel's arithmetic the evaluator
needs, transcribed from `runtime-lib/`, is in `barrel`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import kinds
from .program import DrawContext, Op

if TYPE_CHECKING:
    from ..emit.monkeyc.common import AodStyle, RingPass
    from ..emit.monkeyc.readplan import ReadPlan
    from ..emit.writer import Writer
    from ..layout import Placed, ResolvedFace
    from ..preview import Renderer

__all__ = ["DrawContext", "Op", "emit_body", "lowered", "paint"]


def lowered(ctx: DrawContext, placed: "Placed") -> list[Op] | None:
    """``placed``'s program, or `None` when its kind has not been ported."""
    return kinds.for_placed(placed).lower(ctx, placed)


def emit_body(w: "Writer", resolved: "ResolvedFace", placed: "Placed",
              value_guards: list[str] | None, plan: "ReadPlan", aod: "AodStyle",
              ring: "RingPass | None" = None) -> None:
    """The `draw<Id>` body (or a `ring<Id>` pass): the printed program, or
    the kind's own `emit_draw` when it has none."""
    from .printer import print_ops

    ops = (lowered(DrawContext(resolved, aod, tuple(value_guards or ()), ring), placed)
           if kinds.for_placed(placed).lowers else None)
    if ops is None:
        kind = kinds.for_placed(placed)
        if ring is None:
            kind.emit_draw(w, resolved, placed, value_guards, plan, aod)
        else:
            kind.emit_draw(w, resolved, placed, value_guards, plan, aod, ring=ring)
        return
    print_ops(w, ops)


def paint(renderer: "Renderer", placed: "Placed") -> bool:
    """Paint ``placed`` from its program and say so, or return `False` when
    its kind has none (the caller then runs the kind's `draw_preview`).

    The program is lowered with always-on code present (`AodStyle(on=True)`)
    and the evaluator takes the branch of the frame being painted, which is
    the pixel result of any build's choice."""
    from ..emit.monkeyc.common import AodStyle
    from ..palette import dim_fraction
    from .evaluator import evaluate

    if not kinds.for_placed(placed).lowers:
        return False
    dim = renderer.resolved.face.aod_dim
    aod = AodStyle(on=True, dim=dim_fraction(dim) if dim is not None else None)
    ctx = DrawContext(renderer.resolved, aod, tuple(renderer.value_guards(placed)))
    ops = lowered(ctx, placed)
    if ops is None:
        return False
    evaluate(ops, renderer)
    return True
