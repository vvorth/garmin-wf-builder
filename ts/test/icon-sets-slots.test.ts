// `icons:` and `absent:` on a `config: slots:` choice: the author's own glyph
// per state of the reading the type's icon follows, and what it draws without
// that reading, read by the builder, chosen by the slot's icon method and
// drawn by the preview; an icon element's own `absent:` wins over a choice's.
import assert from "node:assert/strict";
import { test } from "node:test";
import { CATALOG } from "../src/icons.ts";
import type { ConfigDataSlot } from "../src/ir/model.ts";
import * as kinds from "../src/kinds/index.ts";
import { previewOptions, render } from "../src/preview.ts";
import { errors, face, generated, method, MINIMAL, resolved, view } from "./designs.ts";

const glyph = (name: string): string => CATALOG.get(name)!.codepoint;

/**
 * A slot `left` with these `choices:` (flow entries, one per line) and
 * `default:`, drawn by a `type: icon` (`glyph`, with these extra lines) and,
 * with `data`, a `type: data` (`reading`).
 */
function slotted(choices: string[], { fallback = "steps", extra = "", data = false }: { fallback?: string; extra?: string; data?: boolean } = {}): string {
  const list = choices.map((c) => `        - ${c}`).join("\n");
  return `${MINIMAL}
  glyph:
    type: icon
    slot: left
    size: 20%r
    at: {anchor: center}
    color: color.fg${extra ? `\n    ${extra}` : ""}
${data ? `  reading:
    type: data
    slot: left
    at: {anchor: center, dy: 30%}
    color: color.fg
    font: FONT_TINY
    icon: {size: 12%r}
` : ""}`.replace("elements:", `config:
  slots:
    left:
      default: ${fallback}
      choices:
${list}
elements:`);
}

/** The lit pixels of a slot design's frame, the slot showing `pick` with this complication reading. */
function litSlot(text: string, pick: string, reading: unknown): string {
  const frame = render(resolved(text), previewOptions({ scale: 1, picks: [["left", pick]], data_sample: new Map([[pick, reading]]) }));
  return Array.from({ length: frame.width * frame.height }, (_, i) => (frame.data[i * 4]! > 128 ? "1" : "0")).join("");
}

const slotOf = (text: string): ConfigDataSlot => face(text).config_data.get("left")!;
const BATTERY = "{type: battery, icons: {0: battery_outline, 50: battery_medium, 90: battery}}";
const BATTERY_ABSENT = "{type: battery, icons: {0: battery_outline, 50: battery_medium, 90: battery}, absent: {icon: battery_classic}}";

/** The `case Complications.<TYPE>:` line of `iconForGlyph`, for `type`. */
function caseOf(viewText: string, constant: string, id = "Glyph"): string {
  const body = method(viewText, `iconFor${id}`);
  const line = body.split("\n").find((l) => l.includes(`Complications.${constant}`));
  assert.ok(line !== undefined, `no ${constant} case in iconFor${id}:\n${body}`);
  return line.trim();
}

test("a battery choice's set: the slot draws the face's own rule, through the Float chain", () => {
  const text = slotted(["steps", BATTERY]);
  assert.deepEqual(errors(text), []);
  assert.equal(slotOf(text).rules.get("battery")!.name, "battery_custom1");
  assert.equal(caseOf(view(text), "COMPLICATION_TYPE_BATTERY"), "case Complications.COMPLICATION_TYPE_BATTERY: return (value instanceof Lang.Number "
    + "|| value instanceof Lang.Float) ? (value < 50 ? \"battery_outline\" : value < 90 ? \"battery_medium\" : \"battery\") : \"battery\";");
  // each band's glyph in the preview, a Float compared as it is
  const [b10, b49, b50, b95] = [10, 49.5, 50, 95].map((v) => litSlot(text, "battery", v));
  assert.equal(b10, b49);
  assert.equal(new Set([b10, b50, b95]).size, 3);
});

test("absent: {icon:} on a choice: the no-reading return, the glyph in the slot's font and the preview", () => {
  const text = slotted(["steps", BATTERY_ABSENT]);
  assert.deepEqual(errors(text), []);
  assert.match(caseOf(view(text), "COMPLICATION_TYPE_BATTERY"), / : "battery_classic";$/);
  const [run] = kinds.forElement(face(text).walk().find((e) => e.id === "glyph")!).textRuns(face(text).walk().find((e) => e.id === "glyph")!, face(text));
  assert.ok(run!.icon!.glyphs.includes(glyph("battery_classic")), "the slot's font holds the absent glyph");
  assert.equal(run!.glyph_table!.get("battery_classic"), glyph("battery_classic"));
  assert.match(generated(text).get("source/IconGlyphs.mc")!, /case "battery_classic": return /);
  const absent = litSlot(text, "battery", null);
  assert.notEqual(absent, litSlot(slotted(["steps", BATTERY]), "battery", null), "without absent: the type's own icon draws");
  assert.equal(absent, litSlot(slotted(["steps", "{type: battery, icon: battery_classic}"]), "battery", 50), "the absent glyph, as its own icon draws it");
  assert.equal(litSlot(text, "battery", 50), litSlot(slotted(["steps", BATTERY]), "battery", 50), "with a reading, the set's glyph");
});

test("absent: hide on a choice returns null without a reading, and the preview draws nothing", () => {
  const text = slotted(["steps", "{type: battery, absent: hide}"]);
  assert.deepEqual(errors(text), []);
  assert.match(caseOf(view(text), "COMPLICATION_TYPE_BATTERY"), /COMPLICATION_TYPE_BATTERY: return \(value instanceof Lang\.Number\) \? IconGlyphs\.batteryIcon\(value\) : null;$/);
  assert.ok(!litSlot(text, "battery", null).includes("1"));
  assert.ok(litSlot(text, "battery", 50).includes("1"));
  assert.ok(litSlot(slotted(["steps", "battery"]), "battery", null).includes("1"), "without absent: the type's own icon draws");
});

test("a notification count set: the whole-number chain with its own glyphs", () => {
  const text = slotted(["steps", "{type: notification_count, icons: {0: bell, 1: dnd}}"]);
  assert.deepEqual(errors(text), []);
  assert.equal(caseOf(view(text), "COMPLICATION_TYPE_NOTIFICATION_COUNT"), "case Complications.COMPLICATION_TYPE_NOTIFICATION_COUNT: return "
    + "(value instanceof Lang.Number && value == 0) ? \"bell\" : (value instanceof Lang.Number) ? \"dnd\" : \"notification\";");
  assert.notEqual(litSlot(text, "notification_count", 0), litSlot(text, "notification_count", 3));
});

test("a weather overlay on current_weather: the face's own chooser, generated, called by the slot", () => {
  const text = slotted(["steps", "{type: current_weather, icons: {weather_rainy: weather_pouring}}"]);
  assert.deepEqual(errors(text), []);
  assert.match(caseOf(view(text), "COMPLICATION_TYPE_CURRENT_WEATHER"), /IconGlyphs\.weatherCustom1Icon\(value\) : "weather";$/);
  const glyphs = generated(text).get("source/IconGlyphs.mc")!;
  assert.match(glyphs, /function weatherCustom1Icon\(/);
  assert.match(glyphs, /case "weather_pouring": return /);
});

test("a weather overlay on a temperature: the case reads the condition and calls the face's chooser", () => {
  const text = slotted(["steps", "{type: current_temperature, icons: {weather_rainy: weather_pouring}}",
    "{type: high_low_temperature, icons: {weather_rainy: weather_pouring}, absent: hide}"]);
  assert.deepEqual(errors(text), []);
  const v = view(text);
  assert.equal(caseOf(v, "COMPLICATION_TYPE_CURRENT_TEMPERATURE"), "case Complications.COMPLICATION_TYPE_CURRENT_TEMPERATURE: var currentTemperatureCondition = "
    + "WfbConditions.current(); return (currentTemperatureCondition != null) ? IconGlyphs.weatherCustom1Icon(currentTemperatureCondition) : \"temperature\";");
  assert.equal(caseOf(v, "COMPLICATION_TYPE_HIGH_LOW_TEMPERATURE"), "case Complications.COMPLICATION_TYPE_HIGH_LOW_TEMPERATURE: var highLowTemperatureCondition = "
    + "WfbConditions.today(); return (highLowTemperatureCondition != null) ? IconGlyphs.weatherCustom1Icon(highLowTemperatureCondition) : null;");
  assert.doesNotMatch(method(v, "iconForGlyph"), /iconOr/);
  // the barrel's iconOr still calls the built-in chooser by name, so it is still generated
  const glyphs = generated(text).get("source/IconGlyphs.mc")!;
  assert.match(glyphs, /function weatherIcon\(/);
  assert.match(glyphs, /function weatherCustom1Icon\(/);
  // a temperature with absent: hide and no set has no barrel call that could take a null fallback
  const hidden = slotted(["steps", "{type: current_temperature, absent: {icon: battery_classic}}"]);
  assert.match(caseOf(view(hidden), "COMPLICATION_TYPE_CURRENT_TEMPERATURE"), /return WfbConditions\.iconOr\(WfbConditions\.current\(\), "battery_classic"\);$/);
});

test("equal sets on a choice and an element share one chooser", () => {
  const text = slotted(["steps", "{type: current_weather, icons: {weather_rainy: weather_pouring}}"]).replace("elements:\n", `elements:
  sky:
    type: icon
    icon: {for: weather.condition, icons: {weather_rainy: weather_pouring}}
    size: 15%r
    at: {anchor: center, dy: -30%}
    color: color.fg
`);
  assert.deepEqual(errors(text), []);
  const built = face(text);
  assert.deepEqual([...built.icon_rules.keys()], ["weather_custom1"]);
  assert.equal(built.config_data.get("left")!.rules.get("current_weather"), built.icon_rules.get("weather_custom1"));
  assert.equal(generated(text).get("source/IconGlyphs.mc")!.match(/function weatherCustom1Icon\(/g)!.length, 1);
});

test("an icon element's own absent: wins over its slot choice's; a data element draws the choice's", () => {
  const choices = ["steps", BATTERY_ABSENT];
  const own = slotted(choices, { extra: "absent: {icon: heart}", data: true });
  assert.deepEqual(errors(own), []);
  const v = view(own);
  // the icon element's method leaves the type's own icon for its absent: to replace; the data element's draws the choice's
  assert.match(caseOf(v, "COMPLICATION_TYPE_BATTERY"), / : "battery";$/);
  assert.match(caseOf(v, "COMPLICATION_TYPE_BATTERY", "Reading"), / : "battery_classic";$/);
  assert.ok(method(v, "drawGlyph").includes(`if (iconGlyph != null && (pulled == null || pulled.value == null)) {\n            iconGlyph = "${glyph("heart")}";`));
  // the preview: the element's heart without a reading, not the choice's classic battery
  const onlyGlyph = (text: string): string => text.replace(/  reading:\n(    .*\n)+/, "");
  assert.equal(litSlot(onlyGlyph(own), "battery", null), litSlot(onlyGlyph(slotted(["steps", BATTERY], { extra: "absent: {icon: heart}" })), "battery", null));
  assert.notEqual(litSlot(onlyGlyph(own), "battery", null), litSlot(onlyGlyph(slotted(choices)), "battery", null));
  // a choice's hide gives way too: the element's glyph still draws
  const hidden = slotted(["steps", "{type: battery, absent: hide}"], { extra: "absent: {icon: heart}" });
  assert.match(caseOf(view(hidden), "COMPLICATION_TYPE_BATTERY"), / : "battery";$/);
  assert.ok(litSlot(hidden, "battery", null).includes("1"));
  // without its own, the element draws the choice's
  assert.match(caseOf(view(slotted(choices)), "COMPLICATION_TYPE_BATTERY"), / : "battery_classic";$/);
});

/** The one error `text` gives. */
function oneError(text: string): { message: string; line: number | undefined } {
  const found = errors(text);
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  return { message: found[0]!.message, line: found[0]!.span?.line };
}

test("a choice's icons: and absent: are refused where they cannot apply, one error each", () => {
  // the choices list starts on line 17 of `slotted`'s text
  const at = (choice: string) => oneError(slotted(["battery", choice], { fallback: "battery" }));
  assert.deepEqual(at("{type: steps, icons: {0: steps, 1: heart}}"),
    { message: "icons: -- steps's icon follows no reading, so it has no states to give glyphs", line: 18 });
  assert.deepEqual(at("{type: notification_count, icon: bell, icons: {0: bell, 1: dnd}}"),
    { message: "config.slots.left.choices[1]: 'icon:' replaces the type's icon; 'icons:' gives its states your own glyphs -- keep one", line: 18 });
  assert.deepEqual(at("{type: notification_count, icon: bell, absent: hide}"),
    { message: "config.slots.left.choices[1]: 'absent:' says what the type's icon draws without a reading, which this choice's 'icon:' replaces", line: 18 });
  assert.deepEqual(at("{type: steps, absent: hide}"),
    { message: "config.slots.left.choices[1]: 'absent:' needs an icon that follows data -- steps's icon never reads the value, so it is never without a reading", line: 18 });
  assert.equal(at("{type: notification_count, absent: {text: \"--\"}}").line, 18);
  assert.deepEqual(at("{type: notification_count, icons: {0: bell, 1: dnd}, variant: bars}").message,
    "'icons:' and 'variant:' both choose notification_count's glyphs -- 'variant:' picks a built-in set; 'icons:' is your own complete set, keep one");
  assert.match(at("{type: battery_x, absent: hide}").message, /unknown complication type/);
});
