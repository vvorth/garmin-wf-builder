// The icon rule table (`icons.json`'s `rules`): the band maths each rule
// splits a reading by, and the chooser generated from each rule.
import assert from "node:assert/strict";
import { test } from "node:test";
import { WholeFloat } from "../src/edit/yaml.ts";
import { type IconRule, levelBand, RULE_FOLLOWED, RULE_OF_SOURCE, RULES, ruleFunction, ruleGlyphTable, ruleIconName } from "../src/icons.ts";
import { generated, method, MINIMAL, view } from "./designs.ts";

const rule = (name: string): IconRule => RULES.get(name)!;

/** A steps rule over a range, for the band maths alone. */
const ranged = (steps: number, range: [number, number], cyclic = false): IconRule => ({
  ...rule("battery"), steps: Array.from({ length: steps }, (_, i) => `step_${i}`), range, cyclic,
});

test("a range splits into equal bands, truncated and clamped", () => {
  const five = ranged(5, [0, 100]);
  assert.deepEqual([0, 19.9, 20, 59, 60, 99, 100].map((v) => levelBand(five, v)), [0, 0, 1, 2, 3, 4, 4]);
  assert.equal(levelBand(five, -10), 0, "clamped below");
  assert.equal(levelBand(five, 250), 4, "clamped above");
  const offset = ranged(4, [10, 20]);
  assert.deepEqual([10, 12.4, 12.5, 17.5, 20].map((v) => levelBand(offset, v)), [0, 0, 1, 3, 3], "bands start at lo, not 0");
});

test("a cyclic range centres band 0 on lo and wraps round", () => {
  const moon = ranged(8, [0, 29.530588], true);
  assert.equal(levelBand(moon, 0.5), 0, "just after new");
  assert.equal(levelBand(moon, 29.0), 0, "just before new wraps to band 0, not the last");
  assert.equal(levelBand(moon, 14.77), 4, "full");
  assert.equal(levelBand(moon, 3.7), 1, "past the half band");
  // The same ages without cyclic: 29.0 is the last band.
  assert.equal(levelBand(ranged(8, [0, 29.530588]), 29.0), 7);
});

test("thresholds count how many lie at or below the reading; a boolean is 0 or 1", () => {
  const count = rule("notification");
  assert.deepEqual(count.thresholds, [1]);
  assert.deepEqual([0, 1, 7].map((v) => levelBand(count, v)), [0, 1, 1]);
  assert.equal(ruleIconName(count, false), "notification_none");
  assert.equal(ruleIconName(count, true), "notification");
  assert.equal(ruleIconName(count, new WholeFloat(0)), "notification_none");
  const two = { ...count, thresholds: [1, 5], steps: ["a", "b", "c"] };
  assert.deepEqual([0, 1, 4, 5, 9].map((v) => levelBand(two, v)), [0, 1, 1, 2, 2]);
});

test("a table maps each value it names, and draws plain for any other or none", () => {
  const weather = rule("weather");
  assert.equal(ruleIconName(weather, 3), "weather_rainy");
  assert.equal(ruleIconName(weather, 99), "weather_unknown");
  assert.equal(ruleIconName(weather, null), "weather_unknown");
  assert.equal(ruleIconName(weather, true), "weather_unknown", "a boolean is not a value a table names");
  assert.ok(ruleGlyphTable(weather).has("weather_unknown"));
  assert.equal(ruleGlyphTable(weather).size, new Set(weather.map.values()).size);
});

test("each source follows one rule, and a temperature reads its condition beside it", () => {
  assert.equal(RULE_OF_SOURCE.get("system.battery"), rule("battery"));
  assert.equal(RULE_OF_SOURCE.get("complication.current_weather"), rule("weather"));
  assert.equal(RULE_OF_SOURCE.get("complication.current_temperature"), undefined, "a temperature is not a condition");
  assert.deepEqual(RULE_FOLLOWED.get("complication.current_temperature"), { rule: rule("weather"), source: "weather.condition" });
  assert.deepEqual(RULE_FOLLOWED.get("complication.high_low_temperature"), { rule: rule("weather"), source: "weather.condition_today" });
  assert.deepEqual([...RULES.values()].map(ruleFunction), ["batteryIcon", "solarIcon", "notificationIcon", "weatherIcon"]);
});

const dynamic = (source: string): string => `${MINIMAL}
  glyph:
    type: icon
    icon: {for: ${source}}
    size: 20%r
    at: {anchor: center}
    color: color.fg
`;

test("a weather icon's view calls the generated chooser, which names every value in the map", () => {
  const text = dynamic("weather.condition");
  assert.match(method(view(text), "drawGlyph"), /IconGlyphs\.glyph\(IconGlyphs\.weatherIcon\(weatherCondition\)\)/);
  const glyphs = generated(text).get("source/IconGlyphs.mc")!;
  assert.match(glyphs, /function weatherIcon\(value as Lang\.Numeric or Null\) as String \{\n\s+if \(value == null\) \{\n\s+return "weather_unknown";/);
  for (const [value, name] of rule("weather").map) assert.match(glyphs, new RegExp(`\\n\\s+case ${value}: return "${name}";`));
  assert.match(glyphs, /default: return "weather_unknown";/);
  assert.doesNotMatch(glyphs, /batteryIcon|notificationIcon/, "no chooser nobody calls");
});

test("a slot's weather and temperature picks: the reading's condition, and the one read beside it", () => {
  const text = `${MINIMAL.replace("elements:", `config:
  slots:
    left:
      default: current_weather
      choices: [current_weather, current_temperature]
elements:`)}
  glyph:
    type: icon
    slot: left
    size: 20%r
    at: {anchor: center}
    color: color.fg
`;
  const files = generated(text);
  const icon = method(view(text), "iconForGlyph");
  assert.match(icon, /\n\s+case Complications\.COMPLICATION_TYPE_CURRENT_WEATHER: return \(value instanceof Lang\.Number\) \? IconGlyphs\.weatherIcon\(value\) : "weather";\n/);
  assert.match(icon, /\n\s+case Complications\.COMPLICATION_TYPE_CURRENT_TEMPERATURE: return WfbConditions\.iconOr\(WfbConditions\.current\(\), "temperature"\);\n/);
  assert.match(files.get("source/IconGlyphs.mc")!, /function weatherIcon\(/);
  assert.match(files.get("runtime-lib/WfbConditions.mc")!, /IconGlyphs\.weatherIcon\(condition\)/);
  assert.ok(![...files.keys()].some((path) => path.includes("WfbWeather")), "the chooser is generated, not a barrel file");
});
