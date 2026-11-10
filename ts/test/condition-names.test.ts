// `{<condition source>:name}` and `{...:short}`: a Weather.CONDITION_* as its
// name, from the one table a `data` element's weather reading also draws.
import assert from "node:assert/strict";
import { test } from "node:test";
import * as catalog from "../src/catalog.ts";
import * as complications from "../src/complications.ts";
import { glyphSet } from "../src/emit/resources.ts";
import * as formatting from "../src/formatting.ts";
import * as icons from "../src/icons.ts";
import { drawn, errors, face, generated, method, view } from "./designs.ts";

const BASE = `
format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
elements:
`;

const text = (template: string, extra = ""): string => BASE + `
  reading:
    type: text
    text: "${template}"
    font: FONT_SMALL
    at: {anchor: center}
    color: color.fg
    absent: hide${extra}
`;

const NAMED = [
  ...[...catalog.CATALOG].filter(([, s]) => s.enum === "weather_condition").map(([path]) => path),
  ...[...catalog.INDEXED].flatMap(([family, def]) => Object.entries(def.fields)
    .filter(([, f]) => f.enum === "weather_condition").map(([field]) => `${family}[n].${field}`)),
].sort();

test("the condition sources are named once: the catalogue, the weather icon rule and the slot readings agree", () => {
  assert.deepEqual(NAMED, [...icons.RULES.get("weather")!.sources].sort());
  for (const [name] of complications.TYPES) {
    const source = catalog.get(`complication.${name}`);
    assert.equal(source?.enum === "weather_condition", complications.READING.get(name) === "condition", name);
  }
  assert.equal(catalog.get("weather.temperature")!.enum, null);
});

test("a name spec compiles to the generated table and renders from the same one", () => {
  assert.equal(formatting.emit("{:name}", "c", "number"), "ConditionText.longName(c)");
  assert.equal(formatting.emit("now {:short}", "c", "number"), '"now " + ConditionText.shortName(c)');
  const r = (spec: string, v: unknown): string => formatting.render(spec, v, "number");
  assert.equal(r("{:name}", 1), "Partly cloudy");
  assert.equal(r("{:short}", 1), "Pt cldy");
  assert.equal(r("{:name}", 99), "Unknown"); // past the table reads as its last entry, as `entry` does on the watch
  // every value reads as the slot's own weather reading does: one table, not two
  for (const value of complications.WEATHER_CONDITION_TEXT.keys()) {
    for (const short of [false, true]) {
      assert.equal(r(short ? "{:short}" : "{:name}", value), complications.formatReading("current_weather", value, null, { short }), `${value}`);
    }
  }
});

test("a name spec's widest rendering and glyphs are the table's, with no digits", () => {
  assert.equal(formatting.widest("{:name}", null, "number"), "Cloudy chance of rain snow");
  assert.equal(formatting.widest("({:short})", null, "number"), "(Pt cldy)");
  const long = formatting.glyphs("{:name}", null, "number");
  assert.ok(long.has("x") && long.has("W") && !long.has("8") && !long.has("-"), [...long].join(""));
  const short = formatting.glyphs("{:short}", null, "number");
  assert.ok(!short.has("x") && short.has("/"), [...short].join(""));
});

test("a text reading a condition by name: the view, the module, the preview, and no permission", () => {
  const design = text("{weather.temperature:.0f}° {weather.condition:name}");
  assert.deepEqual(errors(design), []);
  const files = generated(design);
  const module = files.get("source/ConditionText.mc")!;
  assert.ok(module.includes("function longName(condition as Number) as String"), module);
  assert.ok(!module.includes("shortName"), "only the table something calls");
  assert.ok(method(view(design), "drawReading").includes('"° " + ConditionText.longName(weatherCondition)'));
  assert.ok(![...files.keys()].some((name) => name.endsWith("WfbReading.mc")), "the slot's barrel needs the complications permission");
  assert.ok(!files.get("manifest.xml")!.includes("ComplicationSubscriber"));
  assert.equal(drawn(design, "reading", { "weather.temperature": 21, "weather.condition": 23 }), "21° Mostly clear");
  // a face that names no condition carries no module
  assert.ok(!generated(text("{weather.condition:d}")).has("source/ConditionText.mc"));
});

test("a slot and a text share the one module, each table emitted once", () => {
  const design = BASE.replace("elements:\n", `config:
  slots:
    top:
      default: current_weather
      choices: [current_weather, steps]
elements:
`) + `
  slot:
    type: data
    slot: top
    at: {anchor: center, dy: -20%}
    font: FONT_SMALL
    color: color.fg
  now:
    type: text
    text: "{complication.forecast_weather_1day:short}"
    font: FONT_SMALL
    at: {anchor: center}
    color: color.fg
    absent: hide
`;
  assert.deepEqual(errors(design), []);
  const files = generated(design);
  const slotText = files.get("source/SlotText.mc")!;
  assert.ok(slotText.includes("ConditionText.longName(value.toNumber())") && !slotText.includes("|||"), slotText);
  const module = files.get("source/ConditionText.mc")!;
  assert.equal(module.split("function longName").length, 2);
  assert.equal(module.split("function shortName").length, 2);
});

test("a name spec on anything but a bare condition source is one format error", () => {
  for (const [template, shown] of [
    ["{heart_rate.current:name}", "heart_rate.current"],
    ["{(weather.condition + 1):short}", "(weather.condition + 1)"],
    ["{(system.charging ? weather.condition : weather.condition_today):name}", null],
  ] as const) {
    const found = errors(text(template));
    assert.equal(found.length, 1, template);
    assert.equal(found[0]!.code, "format");
    assert.match(found[0]!.message, /names a weather condition/);
    if (shown !== null) assert.ok(found[0]!.message.includes(`'${shown}' is not one`), found[0]!.message);
  }
  for (const path of NAMED) assert.deepEqual(errors(text(`{${path.replace("[n]", "[2]")}:name}`)), [], path);
});

test("an AOD restyle drawn in the element's own baked font gets its glyphs baked too", () => {
  const design = text("{weather.condition:short}", '\n    aod: {visible: true, text: "{weather.condition:name}"}')
    .replace("targets: [fenix8solar47mm]", "targets: [fenix847mm]")
    .replace("font: FONT_SMALL", "font: font.body")
    .replace("resources:\n", "resources:\n  fonts:\n    body: {source: ts/test/fixtures/slice/assets/OpenSans-Regular.ttf, size: 8%r}\n");
  assert.deepEqual(errors(design), []);
  const baked = glyphSet(face(design)).get("body")!;
  assert.ok(baked.includes("x"), `'Wintry mix' asleep needs an x: ${baked}`);
});
