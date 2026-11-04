// Dynamic icons beyond the level ones (`level-icons.test.ts`): a count icon
// that empties at zero, and what every `icon: {for:}` draws without a reading.
import assert from "node:assert/strict";
import { test } from "node:test";
import { WholeFloat } from "../src/edit/yaml.ts";
import type { ExprValue } from "../src/expr.ts";
import { RULES, ruleIconName } from "../src/icons.ts";
import { previewOptions, render } from "../src/preview.ts";
import { errors, generated, method, MINIMAL, resolved, view } from "./designs.ts";

const dynamic = (source: string, extra = ""): string => `${MINIMAL}
  glyph:
    type: icon
    icon: {for: ${source}}
    size: 20%r
    at: {anchor: center}
    color: color.fg${extra}
`;

/** The lit pixels of one preview frame at these readings. */
function lit(text: string, sample: [string, ExprValue][]): string {
  const frame = render(resolved(text), previewOptions({ scale: 1, sample: new Map(sample) }));
  return Array.from({ length: frame.width * frame.height }, (_, i) => (frame.data[i * 4]! > 128 ? "1" : "0")).join("");
}

test("a count icon is empty at exactly zero, and otherwise or without a reading its plain icon", () => {
  const notification = RULES.get("notification")!;
  assert.equal(ruleIconName(notification, 0), "notification_none");
  assert.equal(ruleIconName(notification, new WholeFloat(0)), "notification_none");
  assert.equal(ruleIconName(notification, 3), "notification");
  assert.equal(ruleIconName(notification, null), "notification", "not pulled is not known to be zero");
});

test("icon: {for: device.notification_count} empties at zero, through a generated IconGlyphs chooser", () => {
  const text = dynamic("device.notification_count");
  assert.deepEqual(errors(text), []);
  const draw = method(view(text), "drawGlyph");
  assert.match(draw, /IconGlyphs\.glyph\(IconGlyphs\.notificationIcon\(deviceNotificationCount\)\)/);
  const glyphs = generated(text).get("source/IconGlyphs.mc")!;
  assert.match(glyphs, /function notificationIcon\(value as Lang\.Numeric or Null\) as String/);
  assert.match(glyphs, /if \(value instanceof Lang\.Number && value == 0\) \{\n\s+return "notification_none";/);
  assert.match(glyphs, /case "notification": return/);
  assert.match(glyphs, /case "notification_none": return/);
  const empty = lit(text, [["device.notification_count", 0]]);
  assert.notEqual(empty, lit(text, [["device.notification_count", 3]]), "the outline differs from the filled bubble");
  assert.equal(lit(text, [["device.notification_count", 1]]), lit(text, [["device.notification_count", 3]]), "any count above zero is the filled one");
});

test("icon: {for: complication.notification_count} draws the filled bubble when the count could not be pulled", () => {
  const text = dynamic("complication.notification_count");
  assert.deepEqual(errors(text), []);
  const draw = method(view(text), "drawGlyph");
  assert.doesNotMatch(draw, /if \(complicationNotificationCount != null\)/, "no null guard: absence draws the plain icon");
  assert.match(draw, /IconGlyphs\.notificationIcon\(complicationNotificationCount\)/);
  const absent = lit(text, [["complication.notification_count", null]]);
  assert.equal(absent, lit(text, [["complication.notification_count", 3]]));
  assert.notEqual(absent, lit(text, [["complication.notification_count", 0]]));
});

test("a weather icon without a reading draws weather_unknown, the CONDITION_UNKNOWN glyph, unless visible: hides it", () => {
  const text = dynamic("weather.condition");
  const draw = method(view(text), "drawGlyph");
  assert.doesNotMatch(draw, /if \(weatherCondition != null\)/, "no null guard in front of the draw");
  assert.match(draw, /IconGlyphs\.glyph\(IconGlyphs\.weatherIcon\(weatherCondition\)\)/);
  const absent = lit(text, [["weather.condition", null]]);
  assert.equal(absent, lit(text, [["weather.condition", 53]]), "the same N/A glyph CONDITION_UNKNOWN gets");
  assert.notEqual(absent, lit(text, [["weather.condition", 3]]), "and not rain");
  assert.ok(absent.includes("1"), "something is drawn");

  const hidden = dynamic("weather.condition", "\n    visible: weather.condition >= 0");
  assert.deepEqual(errors(hidden), []);
  assert.ok(!lit(hidden, [["weather.condition", null]]).includes("1"), "the documented opt-out leaves the space empty");
  assert.ok(lit(hidden, [["weather.condition", 3]]).includes("1"));
});

test("the for: error names every accepted source", () => {
  const [error] = errors(dynamic("activity.steps"));
  assert.ok(error !== undefined);
  for (const source of ["device.notification_count", "complication.notification_count", "system.battery", "weather.condition_tomorrow"]) {
    assert.ok(error.message.includes(source), `${source} is listed`);
  }
});
