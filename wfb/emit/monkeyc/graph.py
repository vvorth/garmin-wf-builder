"""Element emitter for `graph`, and its cached-series rebuild methods."""

from __future__ import annotations

from ... import series
from ...ir import (
    Graph, graph_built_field, graph_max_field, graph_min_field, graph_rebuild_method,
    graph_series_field,
)
from ...layout import PlacedGraph
from ...series import Acquisition
from .common import _color, _const_prefix
from ..writer import Writer


def _emit_graph_fields(w: Writer, graphs: list) -> None:
    """One cached series (plus its auto bounds, where asked for) per `graph`.

    Rebuilt once a minute (`_emit_graph`'s cadence check), not per frame --
    see `runtime-lib/WfbSeries.mc`'s module docstring for why.
    """
    if not graphs:
        return
    for placed in graphs:
        element = placed.element
        w.doc(f"`{element.id}`: the cached {element.series!r} series.")
        w.line(f"private var {graph_series_field(element.id)} as Array<Float?> = "
               "[] as Array<Float?>;")
        # heart_rate's auto bound comes from the iterator's own getMin/getMax,
        # which is a Number; every other series' comes from WfbSeries.autoMin/
        # autoMax over the collected Array<Float?>, which is a Float.
        auto_type = ("Number" if element.series_def is not None
                     and element.series_def.acquisition is Acquisition.HEART_RATE
                     else "Float")
        zero = "0" if auto_type == "Number" else "0.0"
        if element.min_auto:
            w.line(f"private var {graph_min_field(element.id)} as {auto_type} = {zero};")
        if element.max_auto:
            w.line(f"private var {graph_max_field(element.id)} as {auto_type} = {zero};")
        w.doc(f"`{element.id}`: the minute this series was last rebuilt.")
        w.line(f"private var {graph_built_field(element.id)} as Number = -1;")
    w.blank()


def _emit_graph(w: Writer, placed: PlacedGraph) -> None:
    """The rebuild-cadence check, then one drawing call per `style:`.

    The check runs here rather than unconditionally in `onUpdate` -- after
    the element's own guards, alongside every other kind's actual drawing --
    so a hidden graph does not pay for a rebuild nobody will see this frame.
    """
    element = placed.element
    prefix = _const_prefix(placed.id)
    built = graph_built_field(element.id)
    w.comment("the sample interval here is minutes, so rebuilding more often than")
    w.comment("once a minute could not show anything new (WfbSeries.mc's docstring)")
    w.line("var graphMinute = System.getClockTime().min;")
    with w.block(f"if (graphMinute != {built})"):
        w.line(f"{built} = graphMinute;")
        w.line(f"{graph_rebuild_method(element.id)}();")
    w.blank()

    values = graph_series_field(element.id)
    lo = (f"{graph_min_field(element.id)}.toFloat()" if element.min_auto
          else f"({element.min.code}).toFloat()")
    hi = (f"{graph_max_field(element.id)}.toFloat()" if element.max_auto
          else f"({element.max.code}).toFloat()")
    w.line(f"dc.setColor({_color(element.color)}, Graphics.COLOR_TRANSPARENT);")
    if element.style == "line":
        w.line(f"WfbSeries.drawLine(dc, Layout.{prefix}_X, Layout.{prefix}_Y, "
               f"Layout.{prefix}_WIDTH, Layout.{prefix}_HEIGHT,")
        w.line(f"                   Layout.{prefix}_THICKNESS, {values}, {lo}, {hi});")
    elif element.style == "area":
        w.line(f"WfbSeries.drawArea(dc, Layout.{prefix}_X, Layout.{prefix}_Y, "
               f"Layout.{prefix}_WIDTH, Layout.{prefix}_HEIGHT,")
        w.line(f"                   {values}, {lo}, {hi});")
    else:  # bars
        w.line(f"WfbSeries.drawBars(dc, Layout.{prefix}_X, Layout.{prefix}_Y, "
               f"Layout.{prefix}_WIDTH, Layout.{prefix}_HEIGHT,")
        w.line(f"                   Layout.{prefix}_BAR_WIDTH, {values}, {lo}, {hi});")


def _emit_graph_rebuild(w: Writer, placed: PlacedGraph) -> None:
    """`rebuild<Id>()` -- recompute one graph's cached series.

    `heart_rate` is the one hand-written shape in `WfbSeries.mc`, shared by
    every design that plots it; every other series loops over its own array
    here, generated per project, because the field a design binds
    (`day.steps` vs. `day.calories`, `hour.temperature` vs. `hour.uvIndex`)
    varies and Monkey C offers no way to pass one.
    """
    element = placed.element
    src = element.series_def
    w.blank()
    w.doc(f"Recompute `{element.id}`'s {element.series!r} series.")
    with w.block(f"private function {graph_rebuild_method(element.id)}() as Void"):
        if src.acquisition is Acquisition.HEART_RATE:
            _emit_hr_rebuild(w, element)
        else:
            _emit_array_rebuild(w, element, src)


def _emit_hr_rebuild(w: Writer, element: Graph) -> None:
    """`heart_rate`: acquire the iterator, take its free min/max, then hand
    it to `WfbSeries` to bin (a duration range) or collect (a count range).

    `getMin()`/`getMax()` must run before the iterator is consumed by
    `next()` -- both queries are metadata on the iterator, not a cursor
    advance, confirmed against the reference probe
    (`docs/research/probes/graph-series/`), which calls them in exactly this
    order for exactly this reason.
    """
    period = (f"new Time.Duration({element.range_value})" if element.range_kind == "duration"
              else str(element.range_value))
    w.line(f"var iterator = ActivityMonitor.getHeartRateHistory({period}, false);")
    if element.min_auto:
        w.line("var lo = iterator.getMin();")
        w.line(f"{graph_min_field(element.id)} = (lo != null) ? lo : 0;")
    if element.max_auto:
        w.line("var hi = iterator.getMax();")
        w.line(f"{graph_max_field(element.id)} = (hi != null) ? hi : 0;")
    if element.range_kind == "duration":
        w.line(f"{graph_series_field(element.id)} = WfbSeries.binHeartRate("
               f"iterator, {element.sample_count}, {element.range_value});")
    else:
        w.line(f"{graph_series_field(element.id)} = WfbSeries.collectHeartRate(iterator);")


def _emit_array_rebuild(w: Writer, element: Graph, src) -> None:
    """`steps`/`calories`/.../`daily_precipitation_chance`: one short array,
    read into a fixed-size `Array<Float?>` -- `null` past the end when the
    acquired array is shorter than the requested sample count, which is the
    ordinary case for a design new enough not to have 7 days of history yet.
    """
    info = series.ACQUISITION[src.acquisition]
    n = element.sample_count
    values = graph_series_field(element.id)
    w.line(f"var raw = {info.call};")
    w.line(f"var out = new [{n}] as Array<Float?>;")
    with w.block(f"for (var i = 0; i < {n}; i += 1)"):
        w.line("out[i] = null;")

    def fill() -> None:
        w.line(f"var count = WfbSeries.min({n}, raw.size());")
        with w.block("for (var i = 0; i < count; i += 1)"):
            if info.newest_first:
                w.comment("most recent first on the wire; oldest first on screen")
                w.line("var entry = raw[count - 1 - i];")
            else:
                w.line("var entry = raw[i];")
            if src.intermediate is not None:
                suffix = src.field_name[len(src.intermediate) + 1:]
                w.line(f"var mid = entry.{src.intermediate};")
                w.line(f"out[i] = (mid != null) ? mid.{suffix}.toFloat() : null;")
            else:
                w.line(f"var v = entry.{src.field_name};")
                w.line("out[i] = (v != null) ? v.toFloat() : null;")

    if info.array_nullable:
        with w.block("if (raw != null)"):
            fill()
    else:
        fill()
    w.line(f"{values} = out;")
    if element.min_auto:
        w.line(f"{graph_min_field(element.id)} = WfbSeries.autoMin(out);")
    if element.max_auto:
        w.line(f"{graph_max_field(element.id)} = WfbSeries.autoMax(out);")
