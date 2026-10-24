// `prefix: true` on a data element: the picked type's tag before its reading.
import assert from "node:assert/strict";
import { test } from "node:test";
import { PREFIX } from "../src/complications.ts";
import { DrawContext, lowered } from "../src/draw/index.ts";
import { slotText as hostText } from "../src/draw/evaluator.ts";
import type { SlotText } from "../src/draw/program.ts";
import { AodStyle } from "../src/emit/monkeyc/common.ts";
import type { PlacedData } from "../src/layout.ts";
import { errors, generated, method, MINIMAL, resolved, view } from "./designs.ts";

/** A slot `top` showing `choices`, drawn by a data element with `extra` keys. */
const reading = (extra = "    prefix: true\n", choices = "[heart_rate, steps, vo2max_run, vo2max_bike, date]", defaultType = "heart_rate"): string => `${MINIMAL
  .replace("elements:", `config:
  slots:
    top: {default: ${defaultType}, choices: ${choices}}
elements:`)}
  value:
    type: data
    slot: top
    at: {anchor: center}
    font: FONT_SMALL
    color: color.fg
    absent: {text: "--"}
${extra}`;

const slotText = (text: string): string => [...generated(text)].find(([name]) => name.endsWith("SlotText.mc"))![1];

test("the tags are the ones asked for, and sunrise is RISE", () => {
  assert.deepEqual(Object.fromEntries(PREFIX), {
    heart_rate: "HR", steps: "STEPS", altitude: "ALT", sea_level_pressure: "BARO", battery: "BATT", body_battery: "BODY",
    calories: "CAL", floors_climbed: "FLRS", intensity_minutes: "INT MIN", notification_count: "NOTIF", sunrise: "RISE",
    sunset: "SET", vo2max_run: "VO2", vo2max_bike: "VO2", current_temperature: "NOW", weekly_bike_distance: "BIKE",
    weekly_run_distance: "RUN",
  });
});

test("SlotText.prefix names only the tagged types the slot can show, sharing a tag's case", () => {
  const prefix = method(slotText(reading()), "prefix");
  assert.match(prefix, /case Complications\.COMPLICATION_TYPE_HEART_RATE: return "HR";/);
  assert.match(prefix, /case Complications\.COMPLICATION_TYPE_STEPS: return "STEPS";/);
  assert.match(prefix, /case Complications\.COMPLICATION_TYPE_VO2MAX_BIKE:\s+case Complications\.COMPLICATION_TYPE_VO2MAX_RUN: return "VO2";/);
  assert.doesNotMatch(prefix, /DATE|CALORIES/, "the date has no tag; calories is not a choice");
  assert.match(prefix, /return null;\s*$/);
});

test("without prefix: true there is no prefix function and no tag in the draw", () => {
  const text = reading("");
  assert.doesNotMatch(slotText(text), /function prefix/);
  assert.doesNotMatch(method(view(text), "drawValue"), /SlotText\.prefix/);
});

test("the draw writes the tag and a space before the reading", () => {
  const draw = method(view(reading()), "drawValue");
  assert.match(draw, /var tag = SlotText\.prefix\(chosenId\.getType\(\)\);\s+if \(tag != null\) \{\s+text = tag \+ " ";\s+\}\s+text \+= reading;/);
});

/** The text the preview draws for `value` with slot `top` showing `pick`. */
function previewText(text: string, pick: string): string {
  const r = resolved(text);
  const placed = r.items.find((p) => p.id === "value")!;
  const ops = lowered(new DrawContext(r, new AodStyle(true), [], null, { picks: [["top", pick]] }), placed);
  return hostText(ops.find((op): op is SlotText => op.t === "SlotText")!, new Map());
}

test("the preview draws the tag of the pick shown, and none for a type without one", () => {
  assert.equal(previewText(reading(), "heart_rate"), "HR 72");
  assert.match(previewText(reading(), "steps"), /^STEPS \d/);
  assert.equal(previewText(reading(), "date"), previewText(reading(""), "date"), "the date has no tag: its reading alone");
  assert.equal(previewText(reading(""), "heart_rate"), "72");
});

test("the reading's lint box is measured with the widest tag", () => {
  const value = (text: string): PlacedData => resolved(text).items.find((p) => p.id === "value") as PlacedData;
  // the lint box is measured from the widest tagged reading, so it grows with the tag
  assert.ok(value(reading()).box.width > value(reading("")).box.width, "the tag widens the reading's box");
  const dateOnly = reading("    prefix: true\n", "[date]", "date");
  assert.equal(value(dateOnly).box.width, value(reading("", "[date]", "date")).box.width, "an untagged type is as wide either way");
});

test("prefix: and label: both write before the reading: refused together", () => {
  const found = errors(reading("    prefix: true\n    label: short\n")).map((d) => d.message);
  assert.ok(found.includes("value: 'prefix:' and 'label:' both write before the reading -- use one"), found.join("\n"));
  assert.deepEqual(errors(reading("    label: short\n")).map((d) => d.message), []);
});

test("a baked font for a tagged reading carries the tag's letters", () => {
  const baked = (text: string): string => text.replace("font: FONT_SMALL", "font: font.reading")
    .replace("resources:\n", "resources:\n  fonts:\n    reading: {source: ts/test/fixtures/slice/assets/OpenSans-Regular.ttf, size: 12%r}\n");
  const glyphs = (text: string): Map<string, unknown> => {
    const r = resolved(baked(text));
    return r.fonts.get((r.items.find((p) => p.id === "value") as PlacedData).font.reference)!.glyphs as Map<string, unknown>;
  };
  // numbers only: no choice here is a firmware string, which would bake the whole alphabet anyway
  const numeric = "[heart_rate, steps, vo2max_run]";
  const tagged = glyphs(reading("    prefix: true\n", numeric));
  for (const c of "HRSTEPVO ") assert.ok(tagged.has(c), `glyph ${JSON.stringify(c)}`);
  assert.ok(!glyphs(reading("", numeric)).has("H"), "without prefix: the H is not baked");
});
