// `type: graph`: a time series over a data source and a range. Port of
// wfb/kinds/graph.py's build half.
import * as catalog from "../catalog.ts";
import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import { allKeys } from "../ir/builder/glyphs.ts";
import { type Element, type Expression, GRAPH_AREA_MAX_SAMPLES, Graph } from "../ir/model.ts";
import { isFloat, isInt, isNumber, num, repr, str } from "../py.ts";
import * as series from "../series.ts";
import type { SeriesDef } from "../series.ts";
import { Duration, UnitError } from "../units.ts";
import { type Common, ElementKind, register } from "./base.ts";

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
    + `count, got ${repr(raw ?? null)}`, b.doc.span(node, "range"));
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

class GraphKind extends ElementKind<Graph> {
  readonly name = "graph";
  readonly irClass = Graph;
  override readonly staticForbidden = [
    "a graph",
    "a graph's series is recomputed once a minute -- a buffer filled "
    + "once would freeze it at whatever it showed on the first frame",
  ] as const;
  override readonly antialiased = true;

  build(b: Builder, node: Node, common: Common): Element {
    const name = node.get("series");
    const src = name ? series.get(name as string) ?? null : null;
    if (src === null) {
      const reason = name ? series.unavailableReason(str(name)) : null;
      if (reason !== null) {
        // Not a typo: a real quantity the platform will not serve as a history.
        b.bag.error("graph", `${repr(name)} cannot be plotted on a watch face`, b.doc.span(node, "series"), {
          notes: [reason, "run `wfb series` for what a watch face can plot (docs/guide/progress-and-graphs.md)"],
        });
      } else {
        b.bag.error("graph", `unknown series ${repr(name ?? null)}`, b.doc.span(node, "series"), {
          notes: [...(name ? series.SERIES.didYouMeanNotes(str(name)) : []), "run `wfb series` for the full list"],
        });
      }
    }

    const [rangeKind, rangeValue] = graphRange(b, node);
    let buckets = Math.trunc(num((node.get("buckets") ?? 40) as number));
    const heartRateDuration = src !== null && src.acquisition === "heart_rate" && rangeKind === "duration";
    if (node.has("buckets") && !heartRateDuration) {
      const reason = src !== null && src.acquisition === "heart_rate" ? "a count range does not bin by time"
        : src !== null ? `${repr(name)} is not time-binned` : "the series is unknown";
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
}

function toNumber(value: unknown): number {
  if (typeof value === "bigint") return Number(value);
  return num(value as number);
}

register(new GraphKind());
