// The weather forecasts addressed by index: `weather.daily_forecast[n].<field>`
// and `weather.hourly_forecast[n].<field>`, entry `n` of
// `Weather.getDailyForecast()`/`getHourlyForecast()`. The catalogue builds
// each indexed entry when first asked for, so the expression scope, the
// read plan, the guards and the preview all see an ordinary source.
import assert from "node:assert/strict";
import { test } from "node:test";
import * as catalog from "../src/catalog.ts";
import { tokenize } from "../src/expr.ts";
import * as icons from "../src/icons.ts";
import type { IconElement } from "../src/ir/model.ts";
import { localName } from "../src/ir/naming.ts";
import { checked, db, drawn, errors, face, method, MINIMAL, view } from "./designs.ts";

/** `MINIMAL` on `targets`, plus one text element `t` showing `text`, absent as "--". */
const shown = (text: string, targets = "fenix8solar47mm"): string => `${MINIMAL.replace("targets: [fenix8solar47mm]", `targets: [${targets}]`)}
  t:
    type: text
    text: "${text}"
    font: FONT_SMALL
    at: {anchor: center}
    color: color.fg
    absent: {text: "--"}
`;

const messages = (text: string): string[] => errors(text).map((d) => d.message);

test("an indexed path is one token, one catalogue entry built on demand, and one local", () => {
  assert.deepEqual(tokenize("weather.daily_forecast[1].condition > 2").map((t) => t.text), ["weather.daily_forecast[1].condition", ">", "2", ""]);
  const source = catalog.get("weather.daily_forecast[1].condition")!;
  assert.deepEqual([source.reader, source.field_name, source.array_index, source.type, source.enum, source.nullable],
    ["weather_daily", "condition", 1, "number", "weather_condition", true]);
  assert.equal(source.launch_complication, "forecast_weather_1day");
  assert.equal(catalog.get("weather.daily_forecast[0].condition")!.launch_complication, null);
  assert.equal(catalog.get("weather.hourly_forecast[23].uv_index")!.reader, "weather_hourly");
  assert.equal(catalog.get("weather.hourly_forecast[24].uv_index"), undefined, "past max_index");
  assert.equal(catalog.CATALOG.has("weather.daily_forecast[2].nope"), false);
  // iteration lists the fixed entries alone: a listing names a family once
  assert.ok([...catalog.CATALOG.keys()].every((path) => !path.includes("[")));
  assert.equal(localName("weather.daily_forecast[1].condition"), "weatherDailyForecast1Condition");
  assert.equal(localName("weather.hourly_forecast[12].wind_speed"), "weatherHourlyForecast12WindSpeed");
});

test("condition_today is daily_forecast[0]'s; the other _today readings are the current conditions' own", () => {
  const a = catalog.get("weather.condition_today")!, b = catalog.get("weather.daily_forecast[0].condition")!;
  assert.deepEqual([a.reader, a.field_name, a.array_index, a.enum], [b.reader, b.field_name, b.array_index, b.enum]);
  // the current conditions report these themselves, and they may not match the forecast's first day
  for (const [short, field] of [["weather.high_temperature_today", "highTemperature"], ["weather.low_temperature_today", "lowTemperature"],
    ["weather.precipitation_chance_today", "precipitationChance"]] as const) {
    const s = catalog.get(short)!;
    assert.deepEqual([s.reader, s.field_name, s.array_index], ["weather_current", field, null], short);
  }
  assert.equal(catalog.get("weather.precipitation_chance"), undefined, "the unqualified name is gone");
});

test("the view reads each entry behind the array's null and size checks, a reader per forecast", () => {
  const v = view(shown("{weather.daily_forecast[2].high_temperature:d} {weather.hourly_forecast[5].precipitation_chance:d}%"));
  assert.match(v, /var weatherDaily = Weather\.getDailyForecast\(\);/);
  assert.match(v, /var weatherHourly = Weather\.getHourlyForecast\(\);/);
  const draw = method(v, "drawT");
  assert.match(draw, /var weatherDailyForecast2HighTemperature = \(weatherDaily != null && weatherDaily\.size\(\) > 2\) \? weatherDaily\[2\]\.highTemperature : null;/);
  assert.match(draw, /var weatherHourlyForecast5PrecipitationChance = \(weatherHourly != null && weatherHourly\.size\(\) > 5\) \? weatherHourly\[5\]\.precipitationChance : null;/);
  assert.match(draw, /if \(weatherDailyForecast2HighTemperature != null && weatherHourlyForecast5PrecipitationChance != null\) \{/);
});

test("a wrong family, field or index is one error saying which; condition_tomorrow names its replacement", () => {
  assert.deepEqual(messages(shown("{weather.daily_forecast[10].condition:d}")),
    ["text: unknown data source 'weather.daily_forecast[10].condition': weather.daily_forecast[10] is past the last day a design may name, [9]"]);
  assert.deepEqual(messages(shown("{weather.daily_forecast[1].temperature:d}")),
    ["text: unknown data source 'weather.daily_forecast[1].temperature': weather.daily_forecast entries have no field temperature"]);
  assert.deepEqual(messages(shown("{weather.weekly_forecast[1].condition:d}")),
    ["text: unknown data source 'weather.weekly_forecast[1].condition': weather.weekly_forecast is not an indexed source"]);
  const renamed = errors(shown("{weather.condition_tomorrow:d}"));
  assert.deepEqual(renamed.map((d) => [d.code, d.message]),
    [["source-renamed", "text: 'weather.condition_tomorrow' has been renamed to 'weather.daily_forecast[1].condition'"]]);
});

test("an indexed condition takes the weather icon rule, the name spec and visible:", () => {
  assert.equal(icons.RULE_OF_SOURCE.get("weather.hourly_forecast[7].condition"), icons.RULES.get("weather"));
  assert.equal(icons.RULE_OF_SOURCE.get("weather.daily_forecast[1].high_temperature"), undefined);
  const text = `${MINIMAL}
  tomorrow:
    type: icon
    icon:
      for: weather.daily_forecast[1].condition
    size: 20%r
    at: {anchor: center}
    color: color.fg
  label:
    type: text
    text: "{weather.daily_forecast[1].condition:name}"
    font: FONT_SMALL
    at: {anchor: center, dy: 20%}
    color: color.fg
    visible: "weather.daily_forecast[1].precipitation_chance > 50"
    absent: {text: "--"}
`;
  assert.deepEqual(messages(text), []);
  assert.equal((face(text).walk().find((e) => e.id === "tomorrow") as IconElement).rule?.name, "weather");
});

test("the preview draws an indexed reading, an override, and the absent text", () => {
  const text = shown("{weather.daily_forecast[0].high_temperature:d}/{weather.daily_forecast[0].low_temperature:d}");
  assert.equal(drawn(text, "t", {}), "--", "no sample: absent, as the fixed temperatures");
  assert.equal(drawn(text, "t", { "weather.daily_forecast[0].high_temperature": 24, "weather.daily_forecast[0].low_temperature": 12 }), "24/12");
});

test("a field a target lacks fails it by default, attributed to it", (t) => {
  if (!db.ids().includes("fenix6")) {
    t.skip("fenix6 is not installed");
    return;
  }
  const found = checked(shown("uv {weather.hourly_forecast[3].uv_index:.0f}", "fenix8solar47mm, fenix6")).filter((d) => d.severity === "error");
  assert.deepEqual(found.map((d) => [d.code, d.devices]), [["source-unsupported", ["fenix6"]]]);
  assert.match(found[0]!.message, /'weather\.hourly_forecast\[3\]\.uv_index' needs field 'uvIndex', which fenix6 lacks/);
});
