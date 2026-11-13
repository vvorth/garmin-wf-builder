// Icon rule variants: a family of glyph sets over one reading and one band
// split (the battery's fill, bars and classic), chosen with `variant:` on an
// `icon: {for:}` or a slot choice.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { ExprValue } from "../src/expr.ts";
import { RULE_OF_SOURCE, RULES, ruleFunction, ruleIconName, ruleVariant, variantNames } from "../src/icons.ts";
import { SCHEMA } from "../src/node.ts";
import { previewOptions, render } from "../src/preview.ts";
import { errors, generated, method, MINIMAL, resolved, view } from "./designs.ts";

test("the battery's family: fill by default, then bars and classic, each its own rule", () => {
  const fill = RULE_OF_SOURCE.get("system.battery")!;
  assert.equal(fill.name, "battery");
  assert.deepEqual(fill.variants, ["fill", "bars", "classic"]);
  assert.equal(RULE_OF_SOURCE.get("complication.battery"), fill, "a source follows the family's default");
  const [bars, classic] = [ruleVariant(fill, "bars")!, ruleVariant(fill, "classic")!];
  assert.deepEqual([bars.name, classic.name], ["battery_bars", "battery_classic"]);
  assert.equal(ruleVariant(fill, "fill"), fill);
  assert.equal(ruleVariant(fill, null), fill);
  assert.equal(ruleVariant(bars, null), fill, "a variant's default is its family's");
  assert.equal(ruleVariant(RULES.get("solar")!, "bars"), undefined, "a rule without variants has none to give");
  assert.deepEqual([fill, bars, classic].map(ruleFunction), ["batteryIcon", "batteryBarsIcon", "batteryClassicIcon"]);
  const readings = [5, 25, 45, 65, 85, 100, null];
  assert.deepEqual(readings.map((v) => ruleIconName(fill, v)), ["battery_20", "battery_40", "battery_60", "battery_80", "battery", "battery", "battery"]);
  assert.deepEqual(readings.map((v) => ruleIconName(bars, v)),
    ["battery_outline", "battery_low", "battery_medium", "battery_high", "battery", "battery", "battery"]);
  assert.deepEqual(readings.map((v) => ruleIconName(classic, v)),
    ["battery_level_0", "battery_level_1", "battery_level_2", "battery_level_3", "battery_level_4", "battery_level_4", "battery_classic"]);
});

test("the schema's variant enum is every family's variants", () => {
  const schema = JSON.parse(readFileSync(SCHEMA, "utf8")) as { $defs: Record<string, { enum?: string[] }> };
  assert.deepEqual(schema.$defs["iconVariant"]!.enum, variantNames());
  for (const rule of RULES.values()) if (rule.variants.length > 0) assert.deepEqual(rule.variants, variantNames(), rule.name);
});

const icon = (spec: string): string => `${MINIMAL}
  glyph:
    type: icon
    icon: ${spec}
    size: 20%r
    at: {anchor: center}
    color: color.fg
`;

/** The lit pixels of one preview frame of `text` at these readings. */
function lit(text: string, sample: [string, ExprValue][]): string {
  const frame = render(resolved(text), previewOptions({ scale: 1, sample: new Map(sample) }));
  return Array.from({ length: frame.width * frame.height }, (_, i) => (frame.data[i * 4]! > 128 ? "1" : "0")).join("");
}

test("icon: {for: system.battery, variant:} calls its own chooser, and draws its own glyphs", () => {
  const texts = ["{for: system.battery}", "{for: system.battery, variant: fill}", "{for: system.battery, variant: bars}",
    "{for: system.battery, variant: classic}"].map(icon);
  for (const text of texts) assert.deepEqual(errors(text), []);
  const calls = texts.map((text) => /IconGlyphs\.glyph\(IconGlyphs\.(\w+)\(systemBattery\)\)/.exec(method(view(text), "drawGlyph"))?.[1]);
  assert.deepEqual(calls, ["batteryIcon", "batteryIcon", "batteryBarsIcon", "batteryClassicIcon"]);
  const glyphs = generated(texts[2]!).get("source/IconGlyphs.mc")!;
  assert.match(glyphs, /function batteryBarsIcon\(value as Lang\.Numeric or Null\) as String \{\n\s+if \(value == null\) \{\n\s+return "battery";/);
  assert.match(glyphs, /case 1: return "battery_low";/);
  assert.doesNotMatch(glyphs, /function batteryIcon\(/, "no chooser nobody calls");
  const frames = texts.map((text) => lit(text, [["system.battery", 50]]));
  assert.ok(frames.every((f) => f.includes("1")), "something is drawn");
  assert.equal(frames[0], frames[1], "fill is the default");
  assert.equal(new Set([frames[1], frames[2], frames[3]]).size, 3, "the three variants draw three different glyphs");
});

test("variant: on an icon whose reading has no variants is one error on the variant", () => {
  const text = icon("{for: weather.condition, variant: bars}");
  const found = errors(text);
  assert.equal(found.length, 1, JSON.stringify(found.map((d) => d.message)));
  assert.equal(found[0]!.message, "variant: 'bars' -- weather.condition's icon has no variants");
  assert.equal(found[0]!.span!.line, text.split("\n").findIndex((l) => l.includes("variant: bars")) + 1);
  assert.match(errors(icon("{for: system.battery, variant: big}")).map((d) => d.message).join("\n"), /variant: .big. is not valid here/, "the schema refuses a name no family has");
});

const slotted = (choices: string): string => `${MINIMAL.replace("elements:", `config:
  slots:
    left:
      default: battery
      choices: ${choices}
elements:`)}
  glyph:
    type: icon
    slot: left
    size: 20%r
    at: {anchor: center}
    color: color.fg
`;

test("a slot choice's variant: picks the chooser and the plain glyph its battery pick draws", () => {
  const icons = (choices: string): string => method(view(slotted(choices)), "iconForGlyph");
  const battery = /case Complications\.COMPLICATION_TYPE_BATTERY: return (.*);/;
  assert.equal(battery.exec(icons("[battery, steps]"))?.[1], `(value instanceof Lang.Number) ? IconGlyphs.batteryIcon(value) : "battery"`);
  assert.equal(battery.exec(icons("[{type: battery, variant: bars}, steps]"))?.[1],
    `(value instanceof Lang.Number) ? IconGlyphs.batteryBarsIcon(value) : "battery"`);
  assert.equal(battery.exec(icons("[{type: battery, variant: classic}, steps]"))?.[1],
    `(value instanceof Lang.Number) ? IconGlyphs.batteryClassicIcon(value) : "battery_classic"`);
  assert.deepEqual(errors(slotted("[{type: battery, variant: classic}, steps]")), []);
});

test("a slot choice's variant: is refused on a type without variants, and beside the choice's own icon:", () => {
  const noVariants = slotted("[battery, {type: steps, variant: bars}]");
  assert.deepEqual(errors(noVariants).map((d) => d.message), ["variant: 'bars' -- steps's icon has no variants"]);
  const both = slotted("[{type: battery, icon: heart, variant: bars}, steps]");
  assert.deepEqual(errors(both).map((d) => d.message),
    ["config.slots.left.choices[0]: 'variant:' picks the type's own icon, which this choice's 'icon:' replaces"]);
  // The same type twice stays one error: the watch reports only the type picked.
  assert.match(errors(slotted("[{type: battery, variant: bars}, {type: battery, variant: fill}]")).map((d) => d.message).join("\n"),
    /battery is listed more than once/);
});
