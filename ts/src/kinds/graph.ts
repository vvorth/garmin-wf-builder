// `type: graph`: a time series over a data source and a range..
import * as catalog from "../catalog.ts";
import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import { allKeys } from "../ir/builder/glyphs.ts";
import { type Element, type Expression, GRAPH_AREA_MAX_SAMPLES, Graph } from "../ir/model.ts";
import { type Placed, PlacedGraph, type Resolver } from "../layout.ts";
import { isFloat, isInt, isNumber, num, quoted, roundHalfEven as round, str } from "../py.ts";
import type { Box } from "../units.ts";
import * as series from "../series.ts";
import type { SeriesDef } from "../series.ts";
import { Duration, UnitError } from "../units.ts";
import { type Common, ElementKind, register } from "./base.ts";
import {
  AodPick, AodRestyled, Blank, Comment, Const, Conv, type DrawContext, type Num, NumLocal, type Op, Paren, Read, SeriesDraw,
  SeriesRebuild, SetColor,
} from "../draw/program.ts";
import { article, constPrefix } from "../emit/monkeyc/common.ts";
import * as lc from "../emit/monkeyc/layout_constants.ts";
import { graphBuiltField, graphMaxField, graphMinField, graphRebuildMethod, graphSeriesField } from "../ir/naming.ts";

type Node = Map<DataKey, Data>;

/** Which key each graph `style:` reads. */
export const GRAPH_STYLE_KEYS: ReadonlyMap<string, ReadonlySet<string>> = new Map([
  ["line", new Set(["thickness"])],
  ["area", new Set<string>()],
  ["bars", new Set(["bar_width"])],
]);
const ALL_GRAPH_STYLE_KEYS = allKeys(GRAPH_STYLE_KEYS);

/** `range:`: a duration string or a bare integer sample count. */
function graphRange(b: Builder, node: Node): [string, number] {
  const raw = node.get("range");
  if (typeof raw === "boolean") {
    b.bag.error("units", "range must be a duration or an integer count", b.doc.span(node, "range"));
    return ["count", 0];
  }
  if (isInt(raw)) {
    if (raw < 1) {
      b.bag.error("graph", "range must be at least 1 sample", b.doc.span(node, "range"));
      return ["count", 1];
    }
    return ["count", raw];
  }
  if (typeof raw === "string") {
    try {
      return ["duration", Duration.parse(raw, "range").seconds];
    } catch (error) {
      if (!(error instanceof UnitError)) throw error;
      b.bag.error("units", error.message, b.doc.span(node, "range"));
      return ["duration", 0];
    }
  }
  b.bag.error("units", "range must be a duration ('30m', '4h', '7d') or an integer sample "
    + `count, got ${quoted(raw ?? null)}`, b.doc.span(node, "range"));
  return ["count", 0];
}

/** The build-time upper bound on the sample count; asking past a documented cap is an error, not a clamp. */
function graphSampleCount(b: Builder, node: Node, src: SeriesDef | null, rangeKind: string, rangeValue: number, buckets: number): number {
  if (src === null) return Math.max(1, rangeKind === "count" ? rangeValue : buckets);
  if (src.acquisition === "heart_rate") return rangeKind === "duration" ? buckets : Math.max(1, rangeValue);
  let count: number;
  if (rangeKind === "count") {
    count = Math.max(1, rangeValue);
  } else {
    const interval = src.interval_seconds || 1;
    count = Math.max(1, Math.ceil(rangeValue / interval));
  }
  if (src.max_count !== null && count > src.max_count) {
    b.bag.error("graph", `'${src.name}' requests ${count} entries, but returns at most ${src.max_count}`,
      b.doc.span(node, "range"), {
        notes: [`${src.source_ref} documents the cap directly`, "shorten 'range:', or lower the sample count"],
      });
  }
  return count;
}

function checkGraphStyleKeys(b: Builder, node: Node, style: string): void {
  if (!GRAPH_STYLE_KEYS.has(style)) return; // the schema has already rejected an unknown style
  b.checkForeignKeys(node, style, GRAPH_STYLE_KEYS, ALL_GRAPH_STYLE_KEYS, { code: "graph", disc: "style", emptyLabel: "(nothing)" });
}

/** `min:`/`max:`: `auto` (the default) or a compiled numeric expression. */
function graphBound(b: Builder, node: Node, key: string): [Expression | null, boolean] {
  const raw = node.get(key);
  if (raw === undefined || raw === null || (typeof raw === "string" && raw.trim() === "auto")) return [null, true];
  const expression = b.expression(node, key);
  if (expression !== null && !catalog.isNumeric(expression.value.type)) {
    b.bag.error("type", `graph ${key} must be a number, got ${expression.value}`, b.doc.span(node, key));
    return [null, false];
  }
  return [expression, false];
}

/** Python's `isinstance(x, (int, float))` of a folded constant. */
const isPyNumber = (value: unknown): boolean => isNumber(value) || typeof value === "bigint" || isFloat(value);

/** A deterministic stand-in series of `n` samples, one deliberately absent (index `n // 3`, from 6 samples). */
export function syntheticSeries(n: number): (number | null)[] {
  if (n <= 0) return [];
  const gap = n >= 6 ? Math.floor(n / 3) : -1;
  return Array.from({ length: n }, (_, i) => (i === gap ? null : 50.0 + 40.0 * Math.sin(i * 0.6)));
}

class GraphKind extends ElementKind<Graph> {
  readonly name = "graph";
  readonly irClass = Graph;
  override readonly staticForbidden = [
    "a graph",
    "a graph's series is recomputed once a minute -- a buffer filled "
    + "once would freeze it at whatever it showed on the first frame",
  ] as const;
  override readonly antialiased = true;

  override resolve(r: Resolver, element: Graph, parent: Box, depth: number): Placed {
    const [px, py] = r.point(element.at, parent);
    const min1px = element.resolved_min_1px;
    const [box, cx, cy] = r.sizedBox(element, parent, px, py);
    const thickness = Math.max(1, round(r.extent(element.thickness, parent, "minor", 2, null, min1px, "thickness")));
    const barWidth = Math.max(1, round(r.extent(element.bar_width, parent, "minor", 3, null, min1px, "bar_width")));
    const aodThickness = r.aodExtent(element, "thickness", parent, 2);
    const aodBarWidth = r.aodExtent(element, "bar_width", parent, 3);
    return PlacedGraph.create({
      element, box: box.rounded(min1px), center: [round(cx), round(cy)], depth, thickness, bar_width: barWidth,
      size: [round(box.width), round(box.height)], aod_thickness: aodThickness, aod_bar_width: aodBarWidth,
    });
  }

  build(b: Builder, node: Node, common: Common): Element {
    const name = node.get("series");
    const src = name ? series.get(name as string) ?? null : null;
    if (src === null) {
      const reason = name ? series.unavailableReason(str(name)) : null;
      if (reason !== null) {
        // Not a typo: a real quantity the platform will not serve as a history.
        b.bag.error("graph", `${quoted(name)} cannot be plotted on a watch face`, b.doc.span(node, "series"), {
          notes: [reason, "run `wfb series` for what a watch face can plot (docs/guide/progress-and-graphs.md)"],
        });
      } else {
        b.bag.error("graph", `unknown series ${quoted(name ?? null)}`, b.doc.span(node, "series"), {
          notes: [...(name ? series.SERIES.didYouMeanNotes(str(name)) : []), "run `wfb series` for the full list"],
        });
      }
    }

    const [rangeKind, rangeValue] = graphRange(b, node);
    let buckets = Math.trunc(num((node.get("buckets") ?? 40) as number));
    const heartRateDuration = src !== null && src.acquisition === "heart_rate" && rangeKind === "duration";
    if (node.has("buckets") && !heartRateDuration) {
      const reason = src !== null && src.acquisition === "heart_rate" ? "a count range does not bin by time"
        : src !== null ? `${quoted(name)} is not time-binned` : "the series is unknown";
      b.bag.error("graph", `'buckets' has no effect here -- ${reason}`, b.doc.span(node, "buckets"), {
        notes: ["'buckets:' only means something for a time-binned series read "
          + "over a duration -- 'heart_rate' with a 'range:' such as '4h'",
        "drop 'buckets:', or change 'range:' to a duration"],
      });
    }
    if (buckets < 1) {
      b.bag.error("graph", "'buckets' must be at least 1", b.doc.span(node, "buckets"));
      buckets = 40;
    }

    const style = (node.get("style") ?? "line") as string;
    const thickness = b.length(node, "thickness");
    const barWidth = b.length(node, "bar_width");
    checkGraphStyleKeys(b, node, style);

    const [minExpr, minAuto] = graphBound(b, node, "min");
    const [maxExpr, maxAuto] = graphBound(b, node, "max");
    if (minExpr !== null && minExpr.isConstant && maxExpr !== null && maxExpr.isConstant) {
      const lo = minExpr.constant, hi = maxExpr.constant;
      if (isPyNumber(lo) && isPyNumber(hi) && toNumber(lo) >= toNumber(hi)) {
        b.bag.error("graph", `min (${minExpr.text}) must be less than max (${maxExpr.text})`,
          b.doc.span(node, "max") ?? b.doc.span(node));
      }
    }

    const sampleCount = graphSampleCount(b, node, src, rangeKind, rangeValue, buckets);
    if (style === "area" && sampleCount > GRAPH_AREA_MAX_SAMPLES) {
      b.bag.error("graph", `a 'style: area' graph can plot at most ${GRAPH_AREA_MAX_SAMPLES} `
        + "samples (Dc.fillPolygon's own 64-point limit, minus the two "
        + `corners that close the outline), but this graph requests ${sampleCount}`,
      b.doc.span(node, "range") ?? b.doc.span(node), { notes: ["use 'style: line' instead, or shorten 'range:'/'buckets:'"] });
    }

    const [align, verticalAlign] = b.alignment(node);
    const size = b.size(node.get("size"));
    const color = b.colorExpression(node, "color");
    // No `checkOtherAbsence`: a graph has no `absent:`; a nullable colour or bound hides it.
    return Graph.create({
      ...common,
      series: name !== undefined && name !== null ? str(name) : "",
      series_def: src,
      range_kind: rangeKind,
      range_value: rangeValue,
      buckets,
      style,
      thickness,
      bar_width: barWidth,
      min_auto: minAuto,
      max_auto: maxAuto,
      min: minExpr,
      max: maxExpr,
      size,
      color,
      sample_count: sampleCount,
      align,
      vertical_align: verticalAlign,
    });
  }

  override lower(_ctx: DrawContext, placed: Placed): Op[] {
    const p = placed as PlacedGraph;
    const element = p.element;
    const prefix = constPrefix(p.id);
    const seriesField = graphSeriesField(element.id);
    const minimum = graphMinField(element.id), maximum = graphMaxField(element.id);
    const lo: Num = element.min_auto || element.min === null ? Conv(NumLocal(minimum), "toFloat") : Conv(Paren(Read(element.min)), "toFloat");
    const hi: Num = element.max_auto || element.max === null ? Conv(NumLocal(maximum), "toFloat") : Conv(Paren(Read(element.max)), "toFloat");
    let width: Num | null = null;
    if (element.style === "line") {
      width = AodPick(Const(`${prefix}_THICKNESS`, p.thickness), p.aod_thickness !== null ? Const(`${prefix}_AOD_THICKNESS`, p.aod_thickness) : null);
    } else if (element.style === "bars") {
      width = AodPick(Const(`${prefix}_BAR_WIDTH`, p.bar_width), p.aod_bar_width !== null ? Const(`${prefix}_AOD_BAR_WIDTH`, p.aod_bar_width) : null);
    }
    const box = p.box;
    return [
      Comment("the sample interval here is minutes, so rebuilding more often than"),
      Comment("once a minute could not show anything new (WfbSeries.mc's docstring)"),
      SeriesRebuild(graphBuiltField(element.id), graphRebuildMethod(element.id), seriesField, minimum, maximum,
        syntheticSeries(Math.max(0, element.sample_count)), element.min_auto, element.max_auto),
      Blank(),
      SetColor(AodRestyled(element, "color")),
      SeriesDraw(element.style, Const(`${prefix}_X`, box.x), Const(`${prefix}_Y`, box.y), Const(`${prefix}_WIDTH`, box.width),
        Const(`${prefix}_HEIGHT`, box.height), width, seriesField, lo, hi),
    ];
  }

  override layoutConstants(prefix: string, placed: Placed): lc.Constants {
    const p = placed as PlacedGraph;
    const out: lc.Constants = [...lc.boxConstants(prefix, p.box)];
    if (p.element.style === "line") {
      out.push([`${prefix}_THICKNESS`, p.thickness, "pen width"], ...lc.aodThicknessConstant(prefix, p));
    } else if (p.element.style === "bars") {
      out.push([`${prefix}_BAR_WIDTH`, p.bar_width, "centred in each slot"]);
      if (p.aod_bar_width !== null) out.push([`${prefix}_AOD_BAR_WIDTH`, p.aod_bar_width, "aod: bar_width override"]);
    }
    return out;
  }

  override describe(placed: Placed): string {
    const element = (placed as PlacedGraph).element;
    return `${article(`${element.style} graph`)} of ${element.series}`;
  }
}

function toNumber(value: unknown): number {
  if (typeof value === "bigint") return Number(value);
  return num(value as number);
}

register(new GraphKind());
