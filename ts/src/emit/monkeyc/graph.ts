// A `graph`'s cached-series fields and rebuild methods; its drawing is the
// graph kind's `lower`.
import { type Guards, NO_GUARDS } from "../../availability.ts";
import type { Graph } from "../../ir/model.ts";
import { graphBuiltField, graphMaxField, graphMinField, graphRebuildMethod, graphSeriesField } from "../../ir/naming.ts";
import type { PlacedGraph } from "../../layout.ts";
import { quoted } from "../../py.ts";
import { ACQUISITION, type SeriesDef } from "../../series.ts";
import type { Writer } from "../writer.ts";

/** One cached series (and its auto bounds, where asked for) per `graph`, rebuilt once a minute. */
export function emitGraphFields(w: Writer, graphs: readonly PlacedGraph[]): void {
  if (graphs.length === 0) return;
  for (const placed of graphs) {
    const element = placed.element;
    w.doc(`\`${element.id}\`: the cached ${quoted(element.series)} series.`);
    w.line(`private var ${graphSeriesField(element.id)} as Array<Float?> = [] as Array<Float?>;`);
    // heart_rate's auto bound is the iterator's own Number; every other series' a Float
    const autoType = element.series_def !== null && element.series_def.acquisition === "heart_rate" ? "Number" : "Float";
    const zero = autoType === "Number" ? "0" : "0.0";
    if (element.min_auto) w.line(`private var ${graphMinField(element.id)} as ${autoType} = ${zero};`);
    if (element.max_auto) w.line(`private var ${graphMaxField(element.id)} as ${autoType} = ${zero};`);
    w.doc(`\`${element.id}\`: the minute this series was last rebuilt.`);
    w.line(`private var ${graphBuiltField(element.id)} as Number = -1;`);
  }
  w.blank();
}

/** `rebuild<Id>()`: recompute one graph's cached series. */
export function emitGraphRebuild(w: Writer, placed: PlacedGraph, guards: Guards = NO_GUARDS): void {
  const element = placed.element;
  const src = element.series_def!;
  w.blank();
  w.doc(`Recompute \`${element.id}\`'s ${quoted(element.series)} series.`);
  w.block(`private function ${graphRebuildMethod(element.id)}() as Void`, () => {
    if (src.acquisition === "heart_rate") emitHrRebuild(w, element);
    else emitArrayRebuild(w, element, src, guards);
  });
}

/** `heart_rate`: the iterator's free min/max first, then `WfbSeries` bins or collects it. */
function emitHrRebuild(w: Writer, element: Graph): void {
  const period = element.range_kind === "duration" ? `new Time.Duration(${element.range_value})` : String(element.range_value);
  w.line(`var iterator = ActivityMonitor.getHeartRateHistory(${period}, false);`);
  if (element.min_auto) {
    w.line("var lo = iterator.getMin();");
    w.line(`${graphMinField(element.id)} = (lo != null) ? lo : 0;`);
  }
  if (element.max_auto) {
    w.line("var hi = iterator.getMax();");
    w.line(`${graphMaxField(element.id)} = (hi != null) ? hi : 0;`);
  }
  if (element.range_kind === "duration") {
    w.line(`${graphSeriesField(element.id)} = WfbSeries.binHeartRate(iterator, ${element.sample_count}, ${element.range_value});`);
  } else {
    w.line(`${graphSeriesField(element.id)} = WfbSeries.collectHeartRate(iterator);`);
  }
}

/** Any other series: one short array read into a fixed-size `Array<Float?>`, null past its end. */
function emitArrayRebuild(w: Writer, element: Graph, src: SeriesDef, guards: Guards): void {
  const info = ACQUISITION[src.acquisition];
  const n = element.sample_count;
  const values = graphSeriesField(element.id);
  const module = info.module.replace(/^Toybox\./, "");
  const guarded = guards.modules.has(module);
  w.line(guarded ? `var raw = (Toybox has :${module}) ? ${info.call} : null;` : `var raw = ${info.call};`);
  w.line(`var out = new [${n}] as Array<Float?>;`);
  w.block(`for (var i = 0; i < ${n}; i += 1)`, () => w.line("out[i] = null;"));
  w.blockIf(info.arrayNullable || guarded ? "if (raw != null)" : null, () => {
    w.line(`var count = WfbSeries.min(${n}, raw.size());`);
    w.block("for (var i = 0; i < count; i += 1)", () => {
      if (info.newestFirst) {
        w.comment("most recent first on the wire; oldest first on screen");
        w.line("var entry = raw[count - 1 - i];");
      } else {
        w.line("var entry = raw[i];");
      }
      if (src.intermediate !== null) {
        const suffix = src.field_name!.slice(src.intermediate.length + 1);
        w.line(`var mid = entry.${src.intermediate};`);
        w.line(`out[i] = (mid != null) ? mid.${suffix}.toFloat() : null;`);
      } else {
        w.line(`var v = entry.${src.field_name};`);
        w.line("out[i] = (v != null) ? v.toFloat() : null;");
      }
    });
  });
  w.line(`${values} = out;`);
  if (element.min_auto) w.line(`${graphMinField(element.id)} = WfbSeries.autoMin(out);`);
  if (element.max_auto) w.line(`${graphMaxField(element.id)} = WfbSeries.autoMax(out);`);
}
