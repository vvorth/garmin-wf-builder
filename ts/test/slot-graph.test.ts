// A graph on a `config: slots:` slot: the history of whatever the wearer picked.
import assert from "node:assert/strict";
import { test } from "node:test";
import { computeGuards } from "../src/availability.ts";
import { Graph } from "../src/ir/model.ts";
import { previewOptions, render } from "../src/preview.ts";
import { SLOT_SERIES } from "../src/series.ts";
import { checked, db, errors, face, generated, method, MINIMAL, resolved, view } from "./designs.ts";

const CHOICES = "[heart_rate, steps, current_temperature, body_battery]";

/** A face with a slot `bottom` and a bar graph drawing it; `extra` lines go on the graph. */
const slotGraph = (extra = "", choices = CHOICES, defaultType = "heart_rate", targets = "[fenix8solar47mm]"): string => `${MINIMAL
  .replace("targets: [fenix8solar47mm]", `targets: ${targets}`)
  .replace("elements:", `config:
  slots:
    bottom: {default: ${defaultType}, choices: ${choices}}
elements:`)}
  history:
    type: graph
    slot: bottom
    style: bars
    bar_width: 3px
    at: {anchor: center}
    size: {width: 60%, height: 20%}
    color: color.fg
${extra}`;

const messages = (text: string): string[] => errors(text).map((d) => d.message);

test("a slot graph builds clean and knows the picks it can plot, in choice order", () => {
  assert.deepEqual(messages(slotGraph()), []);
  const graph = face(slotGraph()).walk().find((e) => e.id === "history") as Graph;
  assert.equal(graph.slot, "bottom");
  assert.deepEqual(graph.slot_picks.map((p) => [p.pick.type, p.def.name, p.sample_count]),
    [["heart_rate", "heart_rate", 40], ["steps", "steps", 7], ["current_temperature", "forecast_temperature", 12]]);
  // choices: any offers every pick the table has
  const any = face(slotGraph("", "any")).walk().find((e) => e.id === "history") as Graph;
  assert.deepEqual(any.slot_picks.map((p) => p.pick.type), [...SLOT_SERIES.keys()]);
});

test("range:, min: and max: are refused beside slot:, and series: with it is a schema error", () => {
  for (const key of ["range: {samples: 7}", "min: 0", "max: 100"]) {
    const name = key.split(":")[0]!;
    assert.ok(messages(slotGraph(`    ${key}\n`)).some((m) => m === `history: '${name}:' is not read beside 'slot:' -- ${{
      range: "each pick's span is its own: hours of heart rate, days of steps",
      min: "the bounds follow the pick: its samples' own extent, from zero for a count",
      max: "the bounds follow the pick: its samples' own extent",
    }[name]}`), key);
  }
  assert.ok(messages(slotGraph("    series: steps\n")).some((m) => /'series' and 'slot' cannot both be set/.test(m)));
});

test("a slot with nothing to plot is an error naming what can be plotted", () => {
  const found = messages(slotGraph("", "[body_battery, stress]", "body_battery"));
  assert.ok(found.some((m) => m === "history: slot 'bottom' offers nothing a graph can plot"), found.join("\n"));
});

test("buckets: bins a heart-rate pick; without one it is an error", () => {
  const graph = face(slotGraph("    buckets: 24\n")).walk().find((e) => e.id === "history") as Graph;
  assert.equal(graph.slot_picks[0]!.sample_count, 24);
  const refused = messages(slotGraph("    buckets: 24\n", "[steps, calories]", "steps"));
  assert.ok(refused.some((m) => m === "'buckets' has no effect here -- slot 'bottom' cannot show heart rate"), refused.join("\n"));
});

test("style: area is held to fillPolygon's cap by the largest pick", () => {
  const area = (buckets: number): string => slotGraph(`    buckets: ${buckets}\n`).replace("style: bars\n    bar_width: 3px", "style: area");
  assert.deepEqual(messages(area(62)), []);
  assert.ok(messages(area(63)).some((m) => /a 'style: area' graph can plot at most 62 samples .* but a heart-rate pick reads 63/.test(m)));
});

test("the rebuild has one block per pick, keyed by the picked type, and an empty series for any other", () => {
  const rebuild = method(view(slotGraph()), "rebuildHistory");
  assert.match(rebuild, /^\(t as Complications\.Type or Null\) as Void \{/);
  assert.match(rebuild, /if \(t == Complications\.COMPLICATION_TYPE_HEART_RATE\) \{\s+\/\/ Heart rate: the last 4 hours, binned\s+var iterator = ActivityMonitor\.getHeartRateHistory\(new Time\.Duration\(14400\), false\);\s+var out = WfbSeries\.binHeartRate\(iterator, 40, 14400\);/);
  // a count starts at nothing; a temperature at its own lowest sample
  assert.match(rebuild, /COMPLICATION_TYPE_STEPS[\s\S]*?historyMin = 0\.0;\s+historyMax = WfbSeries\.autoMax\(out\);\s+return;/);
  assert.match(rebuild, /COMPLICATION_TYPE_CURRENT_TEMPERATURE[\s\S]*?Weather\.getHourlyForecast\(\)[\s\S]*?new \[12\][\s\S]*?historyMin = WfbSeries\.autoMin\(out\);/);
  assert.doesNotMatch(rebuild, /BODY_BATTERY/);
  assert.match(rebuild, /return;\s+\}\s+historySeries = \[\] as Array<Float\?>;/);
});

test("the draw rebuilds on a new minute or a new pick, and draws only a series with samples", () => {
  const draw = method(view(slotGraph()), "drawHistory");
  assert.match(draw, /if \(_pulsing != \d+\) \{/);
  assert.match(draw, /var chosenId = _configDataBottom;\s+var chosenType = chosenId\.getType\(\);/);
  assert.match(draw, /if \(graphMinute != historyBuiltAt \|\| chosenType != historyPickedType\) \{\s+historyBuiltAt = graphMinute;\s+historyPickedType = chosenType;\s+rebuildHistory\(chosenType\);/);
  assert.match(draw, /if \(historySeries\.size\(\) > 0\) \{\s+dc\.setColor[\s\S]*WfbSeries\.drawBars\(/);
  assert.match(view(slotGraph()), /private var historyPickedType as Complications\.Type or Null = null;/);
});

/** How many lit pixels the 1x preview draws inside the graph's box, with `bottom` showing `pick`. */
function graphInk(text: string, pick: string): number {
  const r = resolved(text);
  const box = r.items.find((p) => p.id === "history")!.box;
  const frame = render(r, previewOptions({ scale: 1, picks: [["bottom", pick]] }));
  let lit = 0;
  for (let y = box.y; y < box.y + box.height; y++) {
    for (let x = box.x; x < box.x + box.width; x++) if (frame.data[(y * frame.width + x) * 4]! > 128) lit++;
  }
  return lit;
}

test("the preview draws the pick shown, and nothing for a pick with no history", () => {
  const text = slotGraph();
  assert.ok(graphInk(text, "heart_rate") > 100, "heart rate plots");
  assert.ok(graphInk(text, "steps") > 100, "steps plot");
  assert.equal(graphInk(text, "body_battery"), 0, "Body Battery has no history: the graph hides");
});

test("on_hold: auto on a slot graph opens the wearer's pick", () => {
  const text = slotGraph("    on_hold: auto\n");
  assert.deepEqual(messages(text), []);
  const delegate = [...generated(text)].find(([name]) => name.endsWith("Delegate.mc"))![1];
  assert.match(delegate, /Complications\.exitTo\(_view\.holdTargetForHistory\(\)\);/);
});

test("a temperature pick guards its forecast where a target lacks Weather", (t) => {
  if (!db.ids().includes("fenix5")) {
    t.skip("fenix5 is not installed");
    return;
  }
  const text = slotGraph("", CHOICES, "heart_rate", "[fenix8solar47mm, fenix5]");
  const guards = computeGuards(face(text), [db.get("fenix8solar47mm"), db.get("fenix5")]);
  assert.ok(guards.modules.has("Weather"));
  assert.match(method(view(text, ["fenix8solar47mm", "fenix5"]), "rebuildHistory"),
    /var raw = \(Toybox has :Weather\) \? Weather\.getHourlyForecast\(\) : null;/);
  // Every watch without Weather also lacks Complications: the slot's own warning says it all, once.
  const gated = checked(text).filter((d) => d.code === "api-gated" && d.message.startsWith("history:")).map((d) => d.message);
  assert.deepEqual(gated, ["history: slot 'bottom' needs Toybox.Complications, which fenix5 lacks, so it shows its absent state here -- never the declared default"]);
});

test("a slot graph may not sit inside a layout", () => {
  const text = slotGraph().replace("config:\n  slots:", `layouts:
  one:
    elements:
      inner:
        type: graph
        slot: bottom
        style: line
        at: {anchor: center}
        size: {width: 50%, height: 10%}
        color: color.fg
config:
  style:
    default: one
    choices:
      one: {layout: one}
  slots:`);
  const found = messages(text);
  assert.ok(found.some((m) => m === "'inner': a graph with 'slot:' may not be inside layout 'one' content"), found.join("\n"));
});
