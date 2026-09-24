"""`type: graph` -- a time series drawn as a line, a filled area or bars."""

from __future__ import annotations

from ..ir.model import Graph
from ..layout import PlacedGraph, Resolver
from ..preview import _Renderer
from ..emit.monkeyc import graph as graph_mod
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc.common import _article
from . import ElementKind


def describe(placed: PlacedGraph) -> str:
    element = placed.element
    return f"{_article(f'{element.style} graph')} of {element.series}"


KIND = ElementKind(
    name="graph",
    ir_class=Graph,
    placed_class=PlacedGraph,
    build=lambda b, node, common, path: b._build_graph(node, common),
    resolve=Resolver._resolve_graph,
    static_forbidden=(
        "a graph",
        "a graph's series is recomputed once a minute -- a buffer filled "
        "once would freeze it at whatever it showed on the first frame",
    ),
    antialiased=True,
    draw_preview=_Renderer._graph,
    emit_draw=lambda w, resolved, placed, value_guards, plan, aod: graph_mod._emit_graph(
        w, placed, aod),
    describe=describe,
    layout_constants=layout_constants_mod._graph_constants,
)
