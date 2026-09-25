"""`type: graph` -- a time series drawn as a line, a filled area or bars."""

from __future__ import annotations

import math

from .. import expr, series
from ..ir.model import Element, Expression, GRAPH_AREA_MAX_SAMPLES, Graph
from ..layout import Placed, PlacedGraph
from ..series import Acquisition, SeriesDef
from ..units import Axis, Box, Duration, UnitError
from ..emit.monkeyc import graph as graph_mod
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc.common import NO_AOD, AodStyle, _article
from ..emit.writer import Writer
from . import ElementKind

#: Which key each `graph` `style:` reads (a `bar_width:` on a `style: line`
#: graph would otherwise be silently dropped).
GRAPH_STYLE_KEYS = {
    "line": frozenset({"thickness"}),
    "area": frozenset(),
    "bars": frozenset({"bar_width"}),
}
_ALL_GRAPH_STYLE_KEYS = frozenset().union(*GRAPH_STYLE_KEYS.values())


def build(b, node: dict, common: dict, path: tuple) -> Element:
    """`type: graph` -- a time series over a data source and a range.

    The four validation questions here are independent of each other and
    of layout (nothing below reads a device or a box): which series,
    which range, whether `buckets:` means anything for that combination,
    and whether the resulting sample count fits the chosen `style:`.
    """
    name = node.get("series")
    src = series.get(name) if name else None
    if src is None:
        reason = series.unavailable_reason(str(name)) if name else None
        if reason is not None:
            # Not a typo -- a real quantity the platform will not serve as
            # a history.  Saying "unknown" would send the author hunting
            # for a spelling mistake that does not exist.
            b.bag.error(
                "graph",
                f"{name!r} cannot be plotted on a watch face",
                b.doc.span(node, "series"),
                notes=[reason,
                       "run `wfb series` for what a watch face can plot",
                       "docs/research/08-graphs-and-configuration.md §1 has "
                       "the evidence"],
            )
        else:
            b.bag.error(
                "graph",
                f"unknown series {name!r}",
                b.doc.span(node, "series"),
                notes=(series.SERIES.did_you_mean_notes(str(name)) if name else [])
                + ["run `wfb series` for the full list"],
            )

    range_kind, range_value = _graph_range(b, node, src)
    buckets = int(node.get("buckets", 40))
    heart_rate_duration = (
        src is not None and src.acquisition is Acquisition.HEART_RATE
        and range_kind == "duration"
    )
    if "buckets" in node and not heart_rate_duration:
        reason = (
            "a count range does not bin by time" if src is not None
            and src.acquisition is Acquisition.HEART_RATE
            else f"{name!r} is not time-binned" if src is not None
            else "the series is unknown"
        )
        b.bag.error(
            "graph",
            f"'buckets' has no effect here -- {reason}",
            b.doc.span(node, "buckets"),
            notes=["'buckets:' only means something for a time-binned series read "
                   "over a duration -- 'heart_rate' with a 'range:' such as '4h'",
                   "drop 'buckets:', or change 'range:' to a duration"],
        )
    if buckets < 1:
        b.bag.error(
            "graph", "'buckets' must be at least 1", b.doc.span(node, "buckets"),
        )
        buckets = 40

    style = node.get("style", "line")
    thickness = b._length(node, "thickness")
    bar_width = b._length(node, "bar_width")
    _check_graph_style_keys(b, node, style)

    min_expr, min_auto = _graph_bound(b, node, "min")
    max_expr, max_auto = _graph_bound(b, node, "max")
    if (min_expr is not None and min_expr.is_constant
            and max_expr is not None and max_expr.is_constant):
        try:
            lo, hi = float(min_expr.constant), float(max_expr.constant)
        except (TypeError, ValueError):
            lo = hi = None
        if lo is not None and lo >= hi:
            b.bag.error(
                "graph",
                f"min ({min_expr.text}) must be less than max ({max_expr.text})",
                b.doc.span(node, "max") or b.doc.span(node),
            )

    sample_count = _graph_sample_count(b, node, src, range_kind, range_value, buckets)
    if style == "area" and sample_count > GRAPH_AREA_MAX_SAMPLES:
        b.bag.error(
            "graph",
            f"a 'style: area' graph can plot at most {GRAPH_AREA_MAX_SAMPLES} "
            f"samples (Dc.fillPolygon's own 64-point limit, minus the two "
            f"corners that close the outline), but this graph requests "
            f"{sample_count}",
            b.doc.span(node, "range") or b.doc.span(node),
            notes=["use 'style: line' instead, or shorten 'range:'/'buckets:'"],
        )

    align, vertical_align = b._alignment(node)
    element = Graph(
        **common,
        series=str(name) if name is not None else "",
        series_def=src,
        range_kind=range_kind,
        range_value=range_value,
        buckets=buckets,
        style=style,
        thickness=thickness,
        bar_width=bar_width,
        min_auto=min_auto,
        max_auto=max_auto,
        min=min_expr,
        max=max_expr,
        size=b._size(node.get("size")),
        color=b._color_expression(node, "color"),
        sample_count=sample_count,
        align=align,
        vertical_align=vertical_align,
    )
    # No `_check_other_absence`: like `shape` and `icon`, a graph has no
    # `when_absent:`; a nullable `color:`/`min:`/`max:` still gets a
    # guard from `ReadPlan`, which hides the element when absent.
    return element


def _graph_range(b, node: dict, src: SeriesDef | None) -> tuple[str, int]:
    """Parse `range:` -- a duration string or a bare integer sample count."""
    raw = node.get("range")
    if isinstance(raw, bool):
        b.bag.error("units", "range must be a duration or an integer count",
                    b.doc.span(node, "range"))
        return "count", 0
    if isinstance(raw, int):
        if raw < 1:
            b.bag.error("graph", "range must be at least 1 sample",
                        b.doc.span(node, "range"))
            return "count", 1
        return "count", raw
    if isinstance(raw, str):
        try:
            duration = Duration.parse(raw, what="range")
        except UnitError as exc:
            b.bag.error("units", str(exc), b.doc.span(node, "range"))
            return "duration", 0
        return "duration", duration.seconds
    b.bag.error(
        "units",
        f"range must be a duration ('30m', '4h', '7d') or an integer sample "
        f"count, got {raw!r}",
        b.doc.span(node, "range"),
    )
    return "count", 0


def _graph_sample_count(b, node: dict, src: SeriesDef | None, range_kind: str,
                        range_value: int, buckets: int) -> int:
    """The build-time-known upper bound on this graph's sample count.

    `range: 14d` on `steps` is an error, not a clamp: silently drawing 7
    when 14 was asked for is exactly the quiet wrongness this
    compiler exists to remove.  Only checked against a *documented*
    maximum (`SeriesDef.max_count`) -- the forecast arrays document none,
    so a design asking for more than the provider actually has simply
    gets fewer, bounds-checked at runtime the same way `weather.
    condition_today`/`_tomorrow` already are.
    """
    if src is None:
        return max(1, range_value if range_kind == "count" else buckets)
    if src.acquisition is Acquisition.HEART_RATE:
        return buckets if range_kind == "duration" else max(1, range_value)
    if range_kind == "count":
        count = max(1, range_value)
    else:
        interval = src.interval_seconds or 1
        count = max(1, -(-range_value // interval))  # ceiling division
    if src.max_count is not None and count > src.max_count:
        b.bag.error(
            "graph",
            f"'{src.name}' requests {count} entries, but returns at most "
            f"{src.max_count}",
            b.doc.span(node, "range"),
            notes=[f"{src.source_ref} documents the cap directly",
                   "shorten 'range:', or lower the sample count"],
        )
    return count


def _check_graph_style_keys(b, node: dict, style: str) -> None:
    if style not in GRAPH_STYLE_KEYS:
        return  # the schema has already rejected an unknown style
    b._check_foreign_keys(
        node, style, GRAPH_STYLE_KEYS, _ALL_GRAPH_STYLE_KEYS,
        code="graph", disc="style", empty_label="(nothing)",
    )


def _graph_bound(b, node: dict, key: str) -> tuple[Expression | None, bool]:
    """`min:`/`max:` -- `auto` (the default) or a compiled numeric expression."""
    raw = node.get(key)
    if raw is None or (isinstance(raw, str) and raw.strip() == "auto"):
        return None, True
    expression = b._expression(node, key)
    if expression is not None and not expression.value.type.is_numeric():
        b.bag.error(
            "type", f"graph {key} must be a number, got {expression.value}",
            b.doc.span(node, key),
        )
        return None, False
    return expression, False


def resolve(r, element: Graph, parent: Box, depth: int) -> Placed:
    cx, cy = r._point(element.at, parent)
    min_1px = element.resolved_min_1px
    box, cx, cy = r._sized_box(element, parent, cx, cy)
    thickness = max(1, round(r._extent(element.thickness, parent, Axis.MINOR, 2,
                                       min_1px=min_1px, what="thickness")))
    bar_width = max(1, round(r._extent(element.bar_width, parent, Axis.MINOR, 3,
                                       min_1px=min_1px, what="bar_width")))
    aod_thickness = r._aod_extent(element, "thickness", parent, 2)
    aod_bar_width = r._aod_extent(element, "bar_width", parent, 3)
    return PlacedGraph(
        element, box.rounded(min_1px=min_1px), (round(cx), round(cy)), depth,
        thickness=thickness, bar_width=bar_width, size=(round(box.width), round(box.height)),
        aod_thickness=aod_thickness, aod_bar_width=aod_bar_width,
    )


def draw_preview(renderer, placed: PlacedGraph) -> None:
    """A synthetic series -- shape and placement only, never real data.

    There is no live `ActivityMonitor`/`Weather` history on the host, so
    this draws a deterministic stand-in sized to exactly the sample
    count the device will draw (`element.sample_count`, resolved at IR
    build time from `range:`/`buckets:` -- the same figure
    `wfb.emit.monkeyc` bakes into the generated acquisition call) --
    the honest analogue of the scalar `SAMPLE` table every other element
    already previews against. Geometry -- box, thickness, bar width --
    comes from the same resolved `PlacedGraph` the device draws from, so
    this is exactly the picture codegen produces, not a second guess at it.
    """
    element = placed.element
    values = _synthetic_series(max(0, element.sample_count))
    present = ([v for v in values if v is not None]
              if element.min_auto or element.max_auto else [])
    if element.min_auto:
        lo = min(present) if present else 0.0
    else:
        lo = _preview_graph_bound(renderer, element.min, 0.0)
    if element.max_auto:
        hi = max(present) if present else 1.0
    else:
        hi = _preview_graph_bound(renderer, element.max, 1.0)
    span = hi - lo
    if span <= 0:
        span = 1.0
    color = renderer._aod_color(element, "color", element.color)
    if element.style == "line":
        _graph_line(renderer, placed, values, lo, span, color)
    elif element.style == "area":
        _graph_area(renderer, placed, values, lo, span, color)
    else:
        _graph_bars(renderer, placed, values, lo, span, color)


def _preview_graph_bound(renderer, expression, default: float) -> float:
    """A fixed `min:`/`max:` expression, evaluated against the same
    sample readings every other bound value previews against."""
    if expression is None or expression.ast is None:
        return default
    value = expr.evaluate(expression.ast, renderer.values)
    return default if value is None else float(value)


def _graph_point(renderer, placed: PlacedGraph, i: int, n: int, value: float,
                 lo: float, span: float) -> tuple[float, float]:
    s = renderer.scale
    x, y = placed.box.x, placed.box.y
    w, h = placed.size
    cx = x + (i * w / (n - 1) if n > 1 else 0)
    cy = y + h - (value - lo) * h / span
    return cx * s, cy * s


def _graph_line(renderer, placed: PlacedGraph, values: list[float | None],
                lo: float, span: float, color) -> None:
    n = len(values)
    if n < 2:
        return
    s = renderer.scale
    previous = None
    for i, value in enumerate(values):
        if value is None:
            previous = None
            continue
        point = _graph_point(renderer, placed, i, n, value, lo, span)
        if previous is not None:
            thickness = renderer._aod_geometry(placed, "thickness", placed.thickness)
            renderer.draw.line([previous, point], fill=color, width=max(1, thickness * s))
        previous = point


def _graph_area(renderer, placed: PlacedGraph, values: list[float | None],
                lo: float, span: float, color) -> None:
    """One filled run per contiguous stretch of present samples -- the
    same "a gap must not draw" rule `WfbSeries.drawArea` follows, so a
    gap in the synthetic series (were one ever added) would look the
    same way here as it will on the wrist."""
    n = len(values)
    if n < 2:
        return
    s = renderer.scale
    y = placed.box.y
    h = placed.size[1]
    i = 0
    while i < n:
        if values[i] is None:
            i += 1
            continue
        run: list[tuple[float, float]] = []
        while i < n and values[i] is not None:
            run.append(_graph_point(renderer, placed, i, n, values[i], lo, span))
            i += 1
        if len(run) >= 2:
            bottom = (y + h) * s
            polygon = run + [(run[-1][0], bottom), (run[0][0], bottom)]
            renderer.draw.polygon(polygon, fill=color)


def _graph_bars(renderer, placed: PlacedGraph, values: list[float | None],
                lo: float, span: float, color) -> None:
    n = len(values)
    if n < 1:
        return
    s = renderer.scale
    x, y = placed.box.x, placed.box.y
    w, h = placed.size
    pitch = w / n
    bar_width = renderer._aod_geometry(placed, "bar_width", placed.bar_width)
    for i, value in enumerate(values):
        if value is None:
            continue
        bar_height = max(1, round((value - lo) * h / span))
        left = (x + i * pitch + (pitch - bar_width) / 2) * s
        top = (y + h - bar_height) * s
        renderer.draw.rectangle(
            [left, top, left + bar_width * s - 1, (y + h) * s - 1], fill=color
        )


def _synthetic_series(n: int) -> list[float | None]:
    """A deterministic stand-in series, sized to exactly `n` samples.

    Not real data -- there is no `ActivityMonitor`/`Weather` history on the
    host -- but a plausible, varying one, so a graph previews as a shape
    rather than a flat line. A smooth wave rather than noise, so the picture
    is legible and reproducible across runs (no `random`, no seed to manage).

    One sample is deliberately absent (index ``n // 3``, skipped when ``n``
    is too small for a gap to read as intentional) -- "a bucket with no
    samples must not draw" is a real, author-visible behaviour, and a
    preview that always shows a complete series would never demonstrate it.
    """
    if n <= 0:
        return []
    gap = n // 3 if n >= 6 else -1
    return [None if i == gap else 50.0 + 40.0 * math.sin(i * 0.6) for i in range(n)]


def describe(placed: PlacedGraph) -> str:
    element = placed.element
    return f"{_article(f'{element.style} graph')} of {element.series}"


def emit_draw(w: Writer, resolved, placed: PlacedGraph, value_guards, plan,
              aod: AodStyle = NO_AOD) -> None:
    graph_mod._emit_graph(w, placed, aod)


def layout_constants(prefix: str, placed: PlacedGraph) -> "layout_constants_mod.Constants":
    out: "layout_constants_mod.Constants" = list(
        layout_constants_mod._box_constants(prefix, placed.box))
    if placed.element.style == "line":
        out.append((f"{prefix}_THICKNESS", placed.thickness, "pen width"))
        out.extend(layout_constants_mod._aod_thickness_constant(prefix, placed))
    elif placed.element.style == "bars":
        out.append((f"{prefix}_BAR_WIDTH", placed.bar_width, "centred in each slot"))
        if placed.aod_bar_width is not None:
            out.append((f"{prefix}_AOD_BAR_WIDTH", placed.aod_bar_width,
                        "aod: bar_width override"))
    return out


KIND = ElementKind(
    name="graph",
    ir_class=Graph,
    placed_class=PlacedGraph,
    build=build,
    resolve=resolve,
    static_forbidden=(
        "a graph",
        "a graph's series is recomputed once a minute -- a buffer filled "
        "once would freeze it at whatever it showed on the first frame",
    ),
    antialiased=True,
    draw_preview=draw_preview,
    emit_draw=emit_draw,
    describe=describe,
    layout_constants=layout_constants,
)
