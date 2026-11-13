// Rules a face owns: a glyph set of the face's own over a built-in rule's
// reading becomes a rule of its own (`icons.customRule`), registered on the
// face under a stable name (`Face.registerIconRule`) and looked up through it,
// with its own generated chooser and preview.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { ExprValue } from "../src/expr.ts";
import { generate } from "../src/emit/project.ts";
import { bakeFonts } from "../src/emit/resources.ts";
import {
  CATALOG, type CustomSet, customRule, glyphOf, type IconRule, ruleFunction, ruleGlyphTable, ruleIconName, ruleNames, RULES, ruleSummary, stateKeys,
} from "../src/icons.ts";
import { Face, IconElement } from "../src/ir/model.ts";
import { resolve } from "../src/layout.ts";
import { previewOptions, render } from "../src/preview.ts";
import { db, face, MINIMAL, method, read } from "./designs.ts";

const rule = (name: string): IconRule => RULES.get(name)!;
const numeric = (entries: [number, string][]): CustomSet => ({ kind: "numeric", entries });

test("stateKeys: each built-in glyph's key, in step order", () => {
  const keys = Object.fromEntries([...RULES.values()].map((r) => [r.name, stateKeys(r)]));
  assert.deepEqual(keys["battery"], [0, 20, 40, 60, 80]);
  assert.deepEqual(keys["battery_bars"], [0, 20, 40, 60, 80]);
  assert.deepEqual(keys["battery_classic"], [0, 20, 40, 60, 80]);
  assert.deepEqual(keys["solar"], [0, 12, 23, 34, 45, 56, 67, 78, 89]);
  assert.deepEqual(keys["notification"], [0, 1]);
  assert.deepEqual(keys["alarm"], [0, 1]);
  assert.deepEqual(keys["dnd"], ["off", "on"]);
  assert.deepEqual(keys["phone"], ["off", "on"]);
  assert.deepEqual(keys["moon"], ["moon_new", "moon_waxing_crescent", "moon_first_quarter", "moon_waxing_gibbous", "moon_full",
    "moon_waning_gibbous", "moon_last_quarter", "moon_waning_crescent"]);
  assert.deepEqual(keys["weather"], ["weather_sunny", "weather_partly_cloudy", "weather_cloudy", "weather_rainy", "weather_snowy",
    "weather_windy", "weather_lightning_rainy", "weather_snowy_rainy", "weather_fog", "weather_hazy", "weather_hail", "weather_partly_rainy",
    "weather_partly_snowy_rainy", "weather_pouring", "weather_partly_snowy", "weather_snowy_heavy", "weather_partly_lightning", "weather_dust",
    "weather_tornado", "weather_cloudy_alert", "weather_sandstorm", "weather_volcano", "weather_hurricane", "weather_unknown"]);
  assert.equal(Object.keys(keys).length, 10, "every built-in rule is covered");
  // A level's key is the first whole reading drawing that step.
  for (const name of ["battery", "solar"]) {
    const r = rule(name);
    stateKeys(r).forEach((key, k) => {
      assert.equal(ruleIconName(r, key), r.steps[k], `${name} at ${key}`);
      if ((key as number) > 0) assert.equal(ruleIconName(r, (key as number) - 1), r.steps[k - 1], `${name} at ${(key as number) - 1}`);
    });
  }
});

test("a numeric set over the battery: its keys are the bands, uneven ones too, at whole and Float readings", () => {
  const r = customRule(rule("battery"), "battery_custom1", numeric([[50, "battery_medium"], [0, "battery_outline"], [90, "battery"], [10, "battery_low"]]));
  assert.deepEqual([r.kind, r.range, r.thresholds, r.steps, r.plain, r.family, r.variant, r.variants, r.sources],
    ["steps", null, [10, 50, 90], ["battery_outline", "battery_low", "battery_medium", "battery"], "battery", "battery", null, [], rule("battery").sources]);
  const at = (v: unknown): string => ruleIconName(r, v);
  assert.deepEqual([0, 9, 9.99, 10, 10.0001, 49.9, 50, 89, 89.99, 90, 100, null].map(at),
    ["battery_outline", "battery_outline", "battery_outline", "battery_low", "battery_low", "battery_low", "battery_medium",
      "battery_medium", "battery_medium", "battery", "battery", "battery"]);
  assert.deepEqual(stateKeys(r), [0, 10, 50, 90]);
  assert.equal(ruleFunction(r), "batteryCustom1Icon");
  assert.equal(ruleSummary(r), "battery_custom1 — battery_outline / battery_low / battery_medium / battery (0–9 / 10–49 / 50–89 / 90+)");
  // The five even bands written as keys draw what the built-in rule draws, a Float either side of each key included.
  const even = customRule(rule("battery"), "battery_custom2", numeric(stateKeys(rule("battery")).map((k, i) => [k as number, rule("battery").steps[i]!])));
  for (const v of [0, 19.9, 20, 20.0, 39.99, 40, 59.5, 60, 79.9, 80, 99.9, 100]) assert.equal(ruleIconName(even, v), ruleIconName(rule("battery"), v), String(v));
});

test("a numeric set over solar gives it as many bands as it has keys", () => {
  const glyphs = ["solar_level_0", "solar_level_2", "solar_level_4", "solar_level_6", "solar_level_8"];
  const r = customRule(rule("solar"), "solar_custom1", numeric([[0, glyphs[0]!], [20, glyphs[1]!], [40, glyphs[2]!], [60, glyphs[3]!], [80, glyphs[4]!]]));
  assert.deepEqual(r.thresholds, [20, 40, 60, 80]);
  assert.deepEqual([0, 19, 20, 39, 40, 59, 60, 79, 80, 100].map((v) => ruleIconName(r, v)),
    [glyphs[0], glyphs[0], glyphs[1], glyphs[1], glyphs[2], glyphs[2], glyphs[3], glyphs[3], glyphs[4], glyphs[4]]);
  assert.equal(ruleIconName(r, null), "solar");
});

test("an on/off set: off below 1, on from 1, the plain glyph without a reading", () => {
  const r = customRule(rule("dnd"), "dnd_custom1", { kind: "onoff", off: "notification", on: "alarm" });
  assert.deepEqual([r.thresholds, r.steps, r.plain], [[1], ["notification", "alarm"], "bell"]);
  assert.deepEqual([false, true, null].map((v) => ruleIconName(r, v)), ["notification", "alarm", "bell"]);
  assert.deepEqual(stateKeys(r), ["off", "on"]);
  assert.throws(() => customRule(rule("battery"), "x", { kind: "onoff", off: "bell", on: "dnd" }), /not an on\/off rule/);
});

test("an overlay replaces a glyph wherever the rule draws it, and keeps the rest", () => {
  const weather = customRule(rule("weather"), "weather_custom1", { kind: "overlay", replace: new Map([["weather_rainy", "heart"]]) });
  assert.deepEqual([3, 25, 0, 99, null].map((v) => ruleIconName(weather, v)), ["heart", "heart", "weather_sunny", "weather_unknown", "weather_unknown"]);
  assert.ok(!ruleNames(weather).includes("weather_rainy"));
  const unknown = customRule(rule("weather"), "weather_custom2", { kind: "overlay", replace: new Map([["weather_unknown", "flame"]]) });
  assert.deepEqual([53, 99, null].map((v) => ruleIconName(unknown, v)), ["flame", "flame", "flame"], "weather_unknown is the plain glyph too");
  const moon = customRule(rule("moon"), "moon_custom1", { kind: "overlay", replace: new Map([["moon_full", "sunrise"]]) });
  assert.equal(ruleIconName(moon, 14.77), "sunrise");
  assert.equal(ruleIconName(moon, 0), "moon_new");
  assert.deepEqual(moon.steps, rule("moon").steps.map((s) => (s === "moon_full" ? "sunrise" : s)));
  assert.throws(() => customRule(rule("battery"), "x", { kind: "overlay", replace: new Map([["battery", "heart"]]) }), /overlay/);
  assert.throws(() => customRule(rule("weather"), "x", numeric([[0, "heart"], [1, "heart"]])), /ordered number/);
});

test("a codepoint glyph is held in its canonical spelling, and the glyph table gives its character", () => {
  const r = customRule(rule("notification"), "notification_custom1", numeric([[0, "u+f0a2"], [1, "notification"]]));
  assert.deepEqual(r.steps, ["U+F0A2", "notification"]);
  assert.equal(ruleIconName(r, 0), "U+F0A2");
  const table = ruleGlyphTable(r);
  assert.equal(table.get("U+F0A2"), "");
  assert.equal(table.get("notification"), CATALOG.get("notification")!.codepoint);
  assert.equal(glyphOf("U+F0A2"), "");
  assert.throws(() => glyphOf("no_such_icon"), /neither/);
});

test("a face names its sets by family and first use, and equal sets share one rule", () => {
  const f = Face.create({});
  const a = f.registerIconRule(rule("battery"), numeric([[0, "battery_outline"], [50, "battery"]]));
  const w = f.registerIconRule(rule("weather"), { kind: "overlay", replace: new Map([["weather_rainy", "heart"]]) });
  const b = f.registerIconRule(rule("battery"), numeric([[0, "battery_low"], [50, "battery"]]));
  const again = f.registerIconRule(rule("battery"), numeric([[50, "battery"], [0, "battery_outline"]]));
  const codepoint = f.registerIconRule(rule("battery"), numeric([[0, "battery_outline"], [50, "u+f0e7"]]));
  const spelled = f.registerIconRule(rule("battery"), numeric([[0, "battery_outline"], [50, "U+F0E7"]]));
  assert.deepEqual([a.name, w.name, b.name, codepoint.name], ["battery_custom1", "weather_custom1", "battery_custom2", "battery_custom3"]);
  assert.equal(again, a, "the same set in another order is the same rule");
  assert.equal(spelled, codepoint, "a codepoint spelled either way is the same glyph");
  assert.deepEqual([...f.icon_rules.keys()], ["battery_custom1", "weather_custom1", "battery_custom2", "battery_custom3"]);
  assert.equal(f.iconRule("battery_custom2"), b);
  assert.equal(f.iconRule("battery"), RULES.get("battery"), "a built-in name still finds the built-in rule");
  assert.equal(f.iconRule("nothing"), undefined);
  assert.equal(ruleFunction(w), "weatherCustom1Icon");
});

const BATTERY = `${MINIMAL}
  glyph:
    type: icon
    icon: {for: system.battery}
    size: 20%r
    at: {anchor: center}
    color: color.fg
`;

const UNEVEN = numeric([[0, "battery_outline"], [10, "battery_low"], [50, "battery_medium"], [90, "battery"]]);

/** `text` loaded, with its `glyph` element drawing `set` over its own rule. */
function customised(text: string, set: CustomSet): Face {
  const f = face(text);
  const element = f.walk().find((e) => e.id === "glyph") as IconElement;
  element.custom_rule = f.registerIconRule(element.rule!, set);
  return f;
}

function sources(f: Face, deviceIds: string[] = ["fenix8solar47mm"]): Map<string, string> {
  const out = new Map<string, string>();
  for (const [name, content] of generate(f, deviceIds.map((id) => db.get(id)), read).files()) if (typeof content === "string") out.set(name, content);
  return out;
}

/** The lit pixels of `f`'s preview frame at these readings. */
function lit(f: Face, sample: [string, ExprValue][]): string {
  const device = db.get("fenix8solar47mm");
  const frame = render(resolve(f, device, bakeFonts(f, device, read)), previewOptions({ scale: 1, sample: new Map(sample) }));
  return Array.from({ length: frame.width * frame.height }, (_, i) => (frame.data[i * 4]! > 128 ? "1" : "0")).join("");
}

test("a face's own battery set: its chooser compares a Float reading, the view calls it, the preview draws each band", () => {
  const f = customised(BATTERY, UNEVEN);
  const files = sources(f);
  const glyphs = files.get("source/IconGlyphs.mc")!;
  const chooser = glyphs.split("function batteryCustom1Icon(")[1]?.split("\n    }")[0];
  assert.ok(chooser !== undefined, glyphs);
  assert.match(chooser, /^value as Lang\.Numeric or Null\) as String \{/);
  // A Float reading (system.battery) reaches every band: no `instanceof Lang.Number` test, and `<` at every key.
  assert.doesNotMatch(chooser, /instanceof/);
  assert.match(chooser, /if \(value == null\) \{\s+return "battery";\s+\}\s+if \(value < 10\) \{\s+return "battery_outline";\s+\}\s+if \(value < 50\) \{\s+return "battery_low";\s+\}\s+if \(value < 90\) \{\s+return "battery_medium";\s+\}\s+return "battery";/);
  assert.doesNotMatch(glyphs, /function batteryIcon\(/, "the built-in chooser nobody calls is left out");
  for (const name of ["battery_outline", "battery_low", "battery_medium", "battery"]) assert.match(glyphs, new RegExp(`case "${name}": return`));
  const viewText = [...files].find(([name]) => name.endsWith("View.mc"))![1];
  assert.match(method(viewText, "drawGlyph"), /IconGlyphs\.glyph\(IconGlyphs\.batteryCustom1Icon\(systemBattery\)\)/);
  const frames = [5, 9.9, 10, 49.5, 50, 89.9, 90].map((v) => lit(f, [["system.battery", v]]));
  assert.ok(frames.every((frame) => frame.includes("1")), "something is drawn");
  assert.equal(frames[0], frames[1], "one band: 5 and 9.9");
  assert.equal(frames[2], frames[3], "one band: 10 and 49.5");
  assert.equal(frames[4], frames[5], "one band: 50 and 89.9");
  assert.equal(new Set([frames[1], frames[2], frames[4], frames[6]]).size, 4, "each side of each key draws a different glyph");
});

test("a count keeps its whole-number chooser; a face's own count set does too", () => {
  const text = BATTERY.replace("system.battery", "device.notification_count");
  const builtIn = sources(face(text)).get("source/IconGlyphs.mc")!;
  assert.match(builtIn, /if \(value instanceof Lang\.Number && value == 0\)/);
  const own = sources(customised(text, numeric([[0, "bell"], [1, "notification"], [5, "alarm"]]))).get("source/IconGlyphs.mc")!;
  const chooser = own.split("function notificationCustom1Icon(")[1]!.split("\n    }")[0]!;
  assert.match(chooser, /if \(value instanceof Lang\.Number && value == 0\) \{\s+return "bell";/);
  assert.match(chooser, /if \(value instanceof Lang\.Number && value < 5\) \{\s+return "notification";/);
});

const SLOTTED = `${MINIMAL.replace("elements:", `config:
  slots:
    left:
      default: battery
      choices: [battery, steps]
elements:`)}
  glyph:
    type: icon
    slot: left
    size: 20%r
    at: {anchor: center}
    color: color.fg
`;

test("a slot choice's own battery set: the icon method's inline chain compares a Number or a Float", () => {
  const f = face(SLOTTED);
  const slot = f.config_data.get("left")!;
  slot.custom_rules.set("battery", f.registerIconRule(RULES.get("battery")!, UNEVEN));
  const files = sources(f);
  const viewText = [...files].find(([name]) => name.endsWith("View.mc"))![1];
  const battery = /case Complications\.COMPLICATION_TYPE_BATTERY: return (.*);/.exec(method(viewText, "iconForGlyph"))?.[1];
  assert.equal(battery, `(value instanceof Lang.Number || value instanceof Lang.Float) ? `
    + `(value < 10 ? "battery_outline" : value < 50 ? "battery_low" : value < 90 ? "battery_medium" : "battery") : "battery"`);
  const glyphs = files.get("source/IconGlyphs.mc")!;
  for (const name of ["battery_outline", "battery_low", "battery_medium", "battery"]) assert.match(glyphs, new RegExp(`case "${name}": return`));
  assert.doesNotMatch(glyphs, /function battery\w*Icon\(/, "an inline chain needs no chooser");
});
