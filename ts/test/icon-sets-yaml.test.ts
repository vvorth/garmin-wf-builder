// `icons:` on `icon: {for:}`: the author's own glyph per state of the reading,
// read and checked by the builder, registered on the face as a rule of its
// own, and drawn by its generated chooser and the preview.
import assert from "node:assert/strict";
import { test } from "node:test";
import { WholeFloat } from "../src/edit/yaml.ts";
import type { ExprValue } from "../src/expr.ts";
import { CATALOG } from "../src/icons.ts";
import type { IconElement } from "../src/ir/model.ts";
import * as kinds from "../src/kinds/index.ts";
import { previewOptions, render } from "../src/preview.ts";
import { checked, errors, face, generated, method, MINIMAL, resolved, view } from "./designs.ts";

/** One `glyph` icon element after MINIMAL, `icon:` set to `spec`, with these extra lines. */
const icon = (spec: string, extra = ""): string => `${MINIMAL}
  glyph:
    type: icon
    icon: ${spec}
    size: 20%r
    at: {anchor: center}
    color: color.fg${extra ? `\n    ${extra}` : ""}
`;

/** The lit pixels of one preview frame of `text` at these readings. */
function lit(text: string, sample: [string, ExprValue][]): string {
  const frame = render(resolved(text), previewOptions({ scale: 1, sample: new Map(sample) }));
  return Array.from({ length: frame.width * frame.height }, (_, i) => (frame.data[i * 4]! > 128 ? "1" : "0")).join("");
}

/**
 * A frame of `glyph` drawn as the one fixed catalogue icon `name`. A dynamic
 * icon's font is sized by its rule's reference glyph, so this matches only
 * where that glyph and `name` are sized alike (the battery's and the bells).
 */
const fixed = (name: string): string => lit(icon(name), []);

const element = (text: string, id = "glyph"): IconElement => face(text).walk().find((e) => e.id === id) as IconElement;

const BATTERY = "{for: system.battery, icons: {0: battery_outline, 10: battery_low, 50: battery_medium, 90: battery}}";

test("a battery set: its own Float chooser, called from the view, drawing each band's glyph", () => {
  const text = icon(BATTERY);
  assert.deepEqual(errors(text), []);
  assert.equal(element(text).rule!.name, "battery_custom1");
  assert.match(method(view(text), "drawGlyph"), /IconGlyphs\.glyph\(IconGlyphs\.batteryCustom1Icon\(systemBattery\)\)/);
  const glyphs = generated(text).get("source/IconGlyphs.mc")!;
  assert.match(glyphs, /function batteryCustom1Icon\(value as Lang\.Numeric or Null\) as String \{\n\s+if \(value == null\) \{\n\s+return "battery";\n\s+\}\n\s+if \(value < 10\) \{\n\s+return "battery_outline";/);
  assert.match(glyphs, /if \(value < 50\) \{\n\s+return "battery_low";/);
  assert.doesNotMatch(glyphs, /instanceof Lang\.Number/, "a Float reading is compared, never tested for a Number");
  assert.doesNotMatch(glyphs, /function batteryIcon\(/, "the built-in chooser is not called");
  const at = (v: number): string => lit(text, [["system.battery", Number.isInteger(v) ? new WholeFloat(v) : v]]);
  const [b5, b99, b10, b499, b50, b90] = [5, 9.9, 10, 49.9, 50, 90].map(at);
  assert.equal(b5, b99, "one band below 10");
  assert.equal(b10, b499, "one band from 10 up to 50");
  assert.equal(new Set([b5, b10, b50, b90]).size, 4, "four bands, four glyphs");
  assert.equal(b5, fixed("battery_outline"));
  assert.equal(b10, fixed("battery_low"));
  assert.equal(b50, fixed("battery_medium"));
  assert.equal(b90, fixed("battery"));
});

test("a solar set of five keys gives the reading five bands", () => {
  const text = icon("{for: complication.solar_input, icons: {0: solar_level_0, 20: solar_level_2, 40: solar_level_4, 60: solar_level_6, 80: solar_level_8}}");
  assert.deepEqual(errors(text), []);
  const rule = element(text).rule!;
  assert.deepEqual(rule.thresholds, [20, 40, 60, 80]);
  assert.match(method(view(text), "drawGlyph"), /IconGlyphs\.solarCustom1Icon\(complicationSolarInput\)/);
  const frames = [0, 19, 20, 39, 40, 60, 80, 100].map((v) => lit(text, [["complication.solar_input", v]]));
  assert.equal(frames[0], frames[1]);
  assert.equal(frames[2], frames[3]);
  assert.equal(new Set(frames).size, 5);
  // A level set's font is still a level's.
  assert.ok(resolved(text).fonts.has("icon_20pctr_level_solar_custom1"), [...resolved(text).fonts.keys()].join(", "));
});

test("a notification set keeps the whole-number chooser", () => {
  const text = icon("{for: device.notification_count, icons: {0: bell, 1: notification}}");
  assert.deepEqual(errors(text), []);
  const glyphs = generated(text).get("source/IconGlyphs.mc")!;
  const chooser = glyphs.slice(glyphs.indexOf("function notificationCustom1Icon"));
  assert.match(chooser, /instanceof Lang\.Number/);
  assert.equal(lit(text, [["device.notification_count", 0]]), fixed("bell"));
  assert.equal(lit(text, [["device.notification_count", 3]]), fixed("notification"));
});

test("a do-not-disturb set is keyed off and on", () => {
  // The built-in pair swapped: each state draws the other's built-in glyph, sized by the same plain bell.
  const text = icon("{for: device.do_not_disturb, icons: {off: dnd, on: bell}}");
  const builtIn = icon("{for: device.do_not_disturb}");
  assert.deepEqual(errors(text), []);
  assert.match(method(view(text), "drawGlyph"), /IconGlyphs\.dndCustom1Icon\(deviceDoNotDisturb\)/);
  const [off, on] = [false, true].map((v) => lit(text, [["device.do_not_disturb", v]]));
  assert.notEqual(off, on);
  assert.equal(off, lit(builtIn, [["device.do_not_disturb", true]]));
  assert.equal(on, lit(builtIn, [["device.do_not_disturb", false]]));
});

test("a weather or moon set overlays the built-in glyphs it names", () => {
  // Both sized by the rule's own reference glyph, so a replacement draws exactly as the built-in glyph it names does.
  const weather = icon("{for: weather.condition, icons: {weather_rainy: heart}}");
  const builtInWeather = icon("{for: weather.condition}");
  const heartWhenAbsent = icon("{for: weather.condition}", "absent: {icon: heart}");
  assert.deepEqual(errors(weather), []);
  assert.match(method(view(weather), "drawGlyph"), /IconGlyphs\.weatherCustom1Icon\(weatherCondition\)/);
  const rain = lit(weather, [["weather.condition", 3]]);
  assert.notEqual(rain, lit(builtInWeather, [["weather.condition", 3]]), "rain no longer draws the built-in rain");
  assert.equal(rain, lit(heartWhenAbsent, [["weather.condition", null]]), "rain draws the heart");
  assert.equal(lit(weather, [["weather.condition", 0]]), lit(builtInWeather, [["weather.condition", 0]]), "sun keeps its own glyph");
  const moon = icon("{for: astro.moon_age, icons: {moon_full: moon_new}}");
  const builtInMoon = icon("{for: astro.moon_age}");
  assert.deepEqual(errors(moon), []);
  const full = lit(moon, [["astro.moon_age", 14.8]]);
  assert.notEqual(full, lit(builtInMoon, [["astro.moon_age", 14.8]]));
  assert.equal(full, lit(builtInMoon, [["astro.moon_age", 0.5]]), "the full moon draws the new moon's glyph");
  assert.equal(lit(moon, [["astro.moon_age", 7.4]]), lit(builtInMoon, [["astro.moon_age", 7.4]]), "the other phases keep theirs");
});

test("a codepoint value draws that glyph", () => {
  // battery_outline's own codepoint, written in lower case: kept in its canonical spelling, drawn as the named glyph.
  const text = icon("{for: system.battery, icons: {0: {codepoint: \"u+f008e\"}, 50: battery}}");
  assert.deepEqual(errors(text), []);
  assert.deepEqual(element(text).rule!.steps, ["U+F008E", "battery"]);
  const named = icon("{for: system.battery, icons: {0: battery_outline, 50: battery}}");
  assert.equal(lit(text, [["system.battery", 20]]), lit(named, [["system.battery", 20]]));
  assert.notEqual(lit(text, [["system.battery", 20]]), lit(text, [["system.battery", 60]]));
  // A codepoint the catalogue names gets the same note as `icon:` gives it.
  const heart = icon(`{for: system.battery, icons: {0: {codepoint: "U+${CATALOG.get("heart")!.codepoint.codePointAt(0)!.toString(16).toUpperCase()}"}, 50: battery}}`);
  assert.match(checked(heart).map((d) => d.message).join("\n"), /is in the catalogue as 'heart'/);
});

test("absent: keeps working beside a set", () => {
  const text = icon("{for: complication.battery, icons: {0: battery_outline, 50: battery_medium}}", "absent: {icon: battery_classic}");
  assert.deepEqual(errors(text), []);
  const draw = method(view(text), "drawGlyph");
  assert.match(draw, /\(complicationBattery != null\) \? IconGlyphs\.glyph\(IconGlyphs\.batteryCustom1Icon\(complicationBattery\)\) : "/);
  const absent = lit(text, [["complication.battery", null]]);
  assert.ok(absent.includes("1"));
  assert.notEqual(absent, lit(text, [["complication.battery", 60]]));
  assert.notEqual(absent, lit(icon("{for: complication.battery, icons: {0: battery_outline, 50: battery_medium}}"), [["complication.battery", null]]),
    "without 'absent:' the plain glyph draws");
  assert.equal(absent, lit(icon("{for: complication.battery, icons: {0: battery_low, 20: battery_high}}", "absent: {icon: battery_classic}"),
    [["complication.battery", null]]), "the substitute, whatever the set");
  assert.equal(lit(text, [["complication.battery", 60]]), fixed("battery_medium"));
  const hidden = icon("{for: complication.battery, icons: {0: battery_outline, 50: battery_medium}}", "absent: hide");
  assert.equal(kinds.forElement(element(hidden)).drawsWhileAbsent(element(hidden)), false);
  assert.ok(!lit(hidden, [["complication.battery", null]]).includes("1"));
});

test("equal sets share one chooser; a different set gets the next name", () => {
  const second = (spec: string): string => `${icon(BATTERY)}
  other:
    type: icon
    icon: ${spec}
    size: 20%r
    at: {anchor: center, dy: 30%r}
    color: color.fg
`;
  // The same keys and glyphs in another order are the same set.
  const same = second("{for: complication.battery, icons: {90: battery, 50: battery_medium, 10: battery_low, 0: battery_outline}}");
  assert.deepEqual(errors(same), []);
  const sameFace = face(same);
  const rules = ["glyph", "other"].map((id) => (sameFace.walk().find((e) => e.id === id) as IconElement).rule);
  assert.equal(rules[0], rules[1], "one rule object");
  assert.deepEqual([...sameFace.icon_rules.keys()], ["battery_custom1"]);
  const glyphs = generated(same).get("source/IconGlyphs.mc")!;
  assert.equal(glyphs.match(/function batteryCustom1Icon\(/g)?.length, 1);
  assert.doesNotMatch(glyphs, /batteryCustom2Icon/);
  const other = second("{for: system.battery, icons: {0: battery_outline, 50: battery}}");
  assert.deepEqual(errors(other), []);
  assert.equal(element(other, "other").rule!.name, "battery_custom2");
  assert.match(method(view(other), "drawOther"), /IconGlyphs\.batteryCustom2Icon\(systemBattery\)/);
  assert.match(generated(other).get("source/IconGlyphs.mc")!, /function batteryCustom2Icon\(/);
});

/** The one error `spec` gives, as `[line, column, message]`, the line found by `marker`. */
function oneError(spec: string, marker: string): [number, number, string] {
  const text = icon(spec);
  const found = errors(text);
  assert.equal(found.length, 1, JSON.stringify(found.map((d) => d.message)));
  const line = text.split("\n").findIndex((l) => l.includes("icon: {for:")) + 1;
  const column = text.split("\n")[line - 1]!.indexOf(marker) + 1;
  assert.equal(found[0]!.span!.line, line, found[0]!.message);
  assert.equal(found[0]!.span!.col, column, `${found[0]!.message}: column`);
  return [found[0]!.span!.line, found[0]!.span!.col, found[0]!.message];
}

test("each mistake in a set is one error at what was written, naming what is accepted", () => {
  const cases: [string, string, string][] = [
    ["{for: system.battery, icons: {10: battery_low, 50: battery}}", "{10:",
      "icons: needs a key at 0, where system.battery's reading starts -- the lowest written is 10"],
    ["{for: system.battery, icons: {0: battery_low}}", "{0:",
      "icons: has one key -- a set over system.battery needs at least two, one where each glyph starts"],
    ["{for: system.battery, icons: {0: battery_low, 120: battery}}", "120:",
      "icons: key 120 is above 100, the top of the reading -- system.battery is a level, keyed by numbers from 0 to 100"],
    ["{for: device.alarm_count, icons: {0: alarm_off, -1: alarm}}", "-1:",
      "icons: key -1 is below 0, where the reading starts -- device.alarm_count is a count, keyed by whole numbers from 0"],
    ["{for: device.notification_count, icons: {0: bell, 1.5: notification}}", "1.5:",
      "icons: key 1.5 is not a whole number -- device.notification_count is a count, keyed by whole numbers from 0"],
    ["{for: system.battery, icons: {0: battery_low, \"20\": battery}}", "\"20\":",
      "icons: key '20' is quoted -- write it unquoted (20:), as system.battery's keys are numbers"],
    ["{for: device.do_not_disturb, icons: {0: bell, 1: dnd}}", "0:",
      "icons: key 0 -- device.do_not_disturb is on or off, so its keys are 'off' and 'on'"],
    ["{for: device.do_not_disturb, icons: {off: bell}}", "{off:",
      "icons: needs both 'off' and 'on' for device.do_not_disturb -- 'on' is missing"],
    ["{for: device.notification_count, icons: {off: bell, on: notification}}", "off:",
      "icons: key 'off' is not a reading -- device.notification_count is a count, keyed by whole numbers from 0"],
    ["{for: weather.condition, icons: {weather_rainyy: heart}}", "weather_rainyy:",
      "icons: key 'weather_rainyy' is not a glyph weather.condition's icon draws -- its keys are the names of its built-in glyphs"],
    ["{for: weather.condition, icons: {3: heart}}", "3:",
      "icons: key 3 is not a glyph weather.condition's icon draws -- its keys are the names of its built-in glyphs"],
    ["{for: system.battery, icons: {0: batery, 50: battery}}", "batery",
      "unknown icon 'batery'"],
    ["{for: system.battery, variant: bars, icons: {0: battery_low, 50: battery}}", "{0: battery_low",
      "'icons:' and 'variant:' both choose system.battery's glyphs -- 'variant:' picks a built-in set; 'icons:' is your own complete set, keep one"],
  ];
  for (const [spec, marker, message] of cases) assert.equal(oneError(spec, marker)[2], message, spec);
});

test("the notes name the accepted keys", () => {
  const notes = (spec: string): string => errors(icon(spec))[0]!.notes.join("\n");
  assert.match(notes("{for: system.battery, icons: {0: battery_low, 120: battery}}"), /its built-in set starts its glyphs at 0, 20, 40, 60, 80/);
  assert.match(notes("{for: device.notification_count, icons: {off: bell, on: notification}}"), /at 0, 1\n'off' and 'on' key an on\/off reading/);
  assert.match(notes("{for: device.do_not_disturb, icons: {0: bell, 1: dnd}}"), /e\.g\. icons: \{off: bell, on: dnd\}/);
  assert.match(notes("{for: weather.condition, icons: {weather_rainyy: heart}}"), /did you mean: weather_rainy, .*\nits glyphs: weather_sunny, /);
  assert.match(notes("{for: system.battery, icons: {0: batery, 50: battery}}"), /^did you mean: battery, /);
});
