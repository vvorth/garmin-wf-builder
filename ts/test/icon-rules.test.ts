// The icon rule table (`icons.json`'s `rules`): the band maths each rule
// splits a reading by, the chooser generated from each rule, and what each
// rule's icon draws in the preview on either side of its splits.
import assert from "node:assert/strict";
import { test } from "node:test";
import { WholeFloat } from "../src/edit/yaml.ts";
import type { ExprValue } from "../src/expr.ts";
import {
  CATALOG, fontHas, type IconRule, levelBand, readsBoolean, RULE_FOLLOWED, RULE_OF_SOURCE, RULES, ruleFunction, ruleGlyphTable, ruleIconName, ruleSummary,
} from "../src/icons.ts";
import { previewOptions, render } from "../src/preview.ts";
import { errors, generated, method, MINIMAL, resolved, view } from "./designs.ts";

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
  assert.deepEqual([...RULES.values()].map(ruleFunction), [
    "batteryIcon", "batteryBarsIcon", "batteryClassicIcon", "solarIcon", "notificationIcon", "alarmIcon", "dndIcon", "phoneIcon", "moonIcon", "weatherIcon",
  ]);
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

/** The lit pixels of one preview frame of `text` at these readings. */
function lit(text: string, sample: [string, ExprValue][]): string {
  const frame = render(resolved(text), previewOptions({ scale: 1, sample: new Map(sample) }));
  return Array.from({ length: frame.width * frame.height }, (_, i) => (frame.data[i * 4]! > 128 ? "1" : "0")).join("");
}

test("every catalogue glyph is in the icon font, and every rule's glyph is a catalogue name", () => {
  for (const icon of CATALOG.values()) assert.ok(fontHas(icon.codepoint), `${icon.name} (${icon.description}) is in the icon font`);
  const codepoints = new Map([["bell", 0xf009a], ["dnd", 0xf009b], ["alarm", 0xf0020], ["alarm_off", 0xf0023],
    ["phone_connected", 0xf00af], ["phone_disconnected", 0xf00b2], ["moon_new", 0xf0f64], ["moon_waxing_crescent", 0xf0f67],
    ["moon_first_quarter", 0xf0f61], ["moon_waxing_gibbous", 0xf0f68], ["moon_full", 0xf0f62], ["moon_waning_gibbous", 0xf0f66],
    ["moon_last_quarter", 0xf0f63], ["moon_waning_crescent", 0xf0f65]]);
  for (const [name, codepoint] of codepoints) assert.equal(CATALOG.get(name)?.codepoint.codePointAt(0), codepoint, name);
});

test("the alarm, do-not-disturb, phone and moon rules", () => {
  assert.deepEqual(["alarm", "dnd", "phone", "moon"].map((name) => rule(name).sources),
    [["device.alarm_count"], ["device.do_not_disturb"], ["device.phone_connected"], ["astro.moon_age"]]);
  assert.deepEqual([0, 1, 3].map((v) => ruleIconName(rule("alarm"), v)), ["alarm_off", "alarm", "alarm"]);
  assert.deepEqual([false, true, null].map((v) => ruleIconName(rule("dnd"), v)), ["bell", "dnd", "bell"]);
  assert.deepEqual([false, true, null].map((v) => ruleIconName(rule("phone"), v)), ["phone_disconnected", "phone_connected", "phone_connected"]);
  assert.deepEqual([...RULES.values()].filter(readsBoolean).map((r) => r.name), ["dnd", "phone"]);
  assert.equal(ruleIconName(rule("moon"), 0.5), "moon_new");
  assert.equal(ruleIconName(rule("moon"), 29.0), "moon_new");
  assert.equal(ruleIconName(rule("moon"), 14.77), "moon_full");
  assert.equal(ruleIconName(rule("moon"), null), "moon_new");
});

/** A Monkey C Float: single precision, each operation rounded to it. */
const f32 = Math.fround;

test("the moon's generated chooser and icons.levelBand agree at every band edge", () => {
  const moon = rule("moon");
  const glyphs = generated(dynamic("astro.moon_age")).get("source/IconGlyphs.mc")!;
  const body = /function moonIcon\(value as Lang\.Numeric or Null\) as String \{([\s\S]*?)\n {4}\}/.exec(glyphs)?.[1];
  assert.ok(body !== undefined, glyphs);
  assert.match(body, /if \(value == null\) \{\n\s+return "moon_new";/);
  const [, span, scale, wrap] = /var band = \(value\.toFloat\(\) \/ ([\d.]+) \* (\d+) \+ 0\.5\)\.toNumber\(\) % (\d+);/.exec(body) ?? [];
  assert.equal(span, "29.530588");
  assert.equal(scale, "8");
  assert.equal(wrap, "8");
  const cases = new Map([...body.matchAll(/case (\d+): return "(\w+)";/g)].map((m) => [Number(m[1]), m[2]!]));
  const fallback = /default: return "(\w+)";/.exec(body)![1]!;
  /** What the generated text computes, in the watch's single-precision Floats. */
  const watch = (age: number): string => {
    const band = Math.trunc(f32(f32(f32(f32(age) / f32(Number(span))) * Number(scale)) + 0.5)) % Number(wrap);
    return cases.get(band) ?? fallback;
  };
  // Band k is centred on k * 29.530588 / 8; its lower edge is half a band below that.
  const half = 29.530588 / 16;
  const edges = [1, 3, 5, 7, 9, 11, 13, 15].map((k) => k * half);
  assert.deepEqual(edges.map((e) => Number(e.toFixed(2))), [1.85, 5.54, 9.23, 12.92, 16.61, 20.3, 23.99, 27.68]);
  const ages = [0, 1.84, 1.85, 12.91, 12.93, 14.76, 14.77, 27.68, 27.69, 29.0, 29.53];
  const expected = [0, 0, 1, 3, 4, 4, 4, 7, 0, 0, 0];
  assert.deepEqual(ages.map((age) => levelBand(moon, age)), expected);
  assert.deepEqual(ages.map(watch), expected.map((band) => moon.steps[band]));
  for (const [k, edge] of edges.entries()) {
    for (const age of [edge - 0.001, edge + 0.001]) assert.equal(watch(age), ruleIconName(moon, age), `age ${age}, edge ${k}`);
  }
  assert.match(glyphs, /\/\/! each centred on its step, so 'moon_new' takes 0 up to 1\.85 and 27\.68 up to 29\.530588,/);
});

test("an on/off rule's chooser takes a Lang.Boolean and compares it; a count's stays a Number test", () => {
  const glyphs = generated(`${dynamic("device.do_not_disturb")}${dynamic("device.phone_connected").slice(MINIMAL.length).replace("glyph:", "glyph2:")}${
    dynamic("device.alarm_count").slice(MINIMAL.length).replace("glyph:", "glyph3:")}`).get("source/IconGlyphs.mc")!;
  assert.match(glyphs, /\n\s+\/\/! The 'dnd' icon for an on\/off reading: 'bell' when off, 'dnd' when on,\n\s+\/\/! and 'bell' without a reading\.\n\s+function dndIcon\(value as Lang\.Boolean or Null\) as String \{\n\s+if \(value == true\) \{\n\s+return "dnd";\n\s+\}\n\s+return "bell";\n\s+\}/);
  assert.match(glyphs, /function phoneIcon\(value as Lang\.Boolean or Null\) as String \{\n\s+if \(value == false\) \{\n\s+return "phone_disconnected";\n\s+\}\n\s+return "phone_connected";\n\s+\}/);
  assert.match(glyphs, /function alarmIcon\(value as Lang\.Numeric or Null\) as String \{\n\s+if \(value instanceof Lang\.Number && value == 0\) \{\n\s+return "alarm_off";\n\s+\}\n\s+return "alarm";\n\s+\}/);
  assert.doesNotMatch(glyphs, /function (dnd|phone)Icon[^}]*instanceof/, "a Boolean is never tested as a Number");
});

for (const [name, source, local, below, above] of [
  ["alarm", "device.alarm_count", "deviceAlarmCount", [0], [1, 4]],
  ["dnd", "device.do_not_disturb", "deviceDoNotDisturb", [false], [true]],
  ["phone", "device.phone_connected", "devicePhoneConnected", [false], [true]],
] as const) {
  test(`icon: {for: ${source}} changes glyph across its threshold, through IconGlyphs.${name}Icon`, () => {
    const text = dynamic(source);
    assert.deepEqual(errors(text), []);
    assert.match(method(view(text), "drawGlyph"), new RegExp(`IconGlyphs\\.glyph\\(IconGlyphs\\.${name}Icon\\(${local}\\)\\)`));
    const frames = [...below, ...above].map((v) => lit(text, [[source, v]]));
    assert.ok(frames.every((f) => f.includes("1")), "something is drawn");
    assert.notEqual(frames[0], frames[below.length], "the glyph changes across the threshold");
    for (const f of frames.slice(below.length)) assert.equal(f, frames[below.length], "and stays within the band above it");
  });
}

test("icon: {for: astro.moon_age} draws four different phases a quarter apart, and one glyph within a band", () => {
  const text = dynamic("astro.moon_age");
  assert.deepEqual(errors(text), []);
  assert.match(method(view(text), "drawGlyph"), /IconGlyphs\.glyph\(IconGlyphs\.moonIcon\(astroMoonAge\)\)/);
  const at = (age: number): string => lit(text, [["astro.moon_age", age]]);
  const quarters = [0.5, 7.4, 14.77, 22.1].map(at);
  assert.equal(new Set(quarters).size, 4, "new, first quarter, full and last quarter all differ");
  assert.equal(at(29.0), quarters[0], "29.0 days wraps round to the new moon");
  assert.equal(at(14.0), quarters[2], "the full moon's band");
  assert.equal(at(15.5), quarters[2]);
});

test("the for: error names the alarm, do-not-disturb, phone and moon sources", () => {
  const [error] = errors(dynamic("activity.steps"));
  assert.ok(error !== undefined);
  for (const source of ["device.alarm_count", "device.do_not_disturb", "device.phone_connected", "astro.moon_age"]) {
    assert.ok(error.message.includes(source), `${source} is listed`);
  }
});

test("a rule's summary names its glyphs in order and how the reading splits", () => {
  assert.equal(ruleSummary(rule("phone")), "phone — phone_disconnected / phone_connected (off / on)");
  assert.equal(ruleSummary(rule("alarm")), "alarm — alarm_off / alarm (0 / 1+)");
  assert.equal(ruleSummary({ ...rule("alarm"), thresholds: [1, 5], steps: ["a", "b", "c"] }), "alarm — a / b / c (0 / 1–4 / 5+)");
  assert.equal(ruleSummary(rule("moon")), "moon — moon_new, moon_waxing_crescent, moon_first_quarter, moon_waxing_gibbous, moon_full, "
    + "moon_waning_gibbous, moon_last_quarter, moon_waning_crescent (8 bands over 0–29.53 days, cyclic)");
  assert.equal(ruleSummary(rule("battery")), "battery — battery_20, battery_40, battery_60, battery_80, battery (5 bands over 0–100%)");
  assert.match(ruleSummary(rule("weather")), /^weather — \d+ glyphs over the 54 values it names \(weather_unknown for any other\)$/);
});
