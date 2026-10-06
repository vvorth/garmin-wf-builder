// What each installed device has: its limits and display, its symbol table,
// and which catalogue readings, modules and fields each target lacks.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import * as availability from "../src/availability.ts";
import { CATALOG } from "../src/catalog.ts";
import { DeviceError } from "../src/devices/device.ts";
import { DEVICE_REFERENCE } from "../src/devices/node.ts";
import { db, face } from "./designs.ts";

const has = (id: string): boolean => db.ids().includes(id);

test("the verification devices: limits, display and family read from their files", () => {
  for (const id of ["fenix8solar47mm", "fenix8solar51mm", "fr955"]) {
    const d = db.get(id);
    assert.ok(d.supportsWatchface, id);
    assert.equal(d.watchfaceMemoryLimit, 131072, id);
    assert.equal(d.bitsPerPixel, 8, id);
    assert.equal(d.displayColors, 64, id);
    assert.equal(d.alphaBlending, false, id);
    assert.equal(d.displayType, "mip", id);
    assert.equal(d.isAmoled, false, id);
    assert.equal(d.supportsPartialUpdate, true, id);
    assert.equal(d.graphicsPoolBytes, 1048576, id);
  }
  assert.equal(db.get("fenix8solar47mm").deviceFamily, "round-260x260");
  assert.equal(db.get("fr955").deviceFamily, "round-260x260");
  assert.equal(db.get("fenix8solar51mm").deviceFamily, "round-280x280");
});

test("symbols: API level alone does not decide, and the parent is matched in full", () => {
  const fr955 = db.get("fr955"), fenix = db.get("fenix8solar47mm");
  assert.ok(fr955.apiLevel >= "5.1.0");
  assert.equal(fenix.hasSymbol("Toybox.WatchUi.WatchFaceDelegate.onTap"), true);
  assert.equal(fr955.hasSymbol("Toybox.WatchUi.WatchFaceDelegate.onTap"), false);
  assert.equal(fr955.hasSymbol("Toybox.WatchUi.InputDelegate.onTap"), true);
  assert.equal(fenix.hasSymbol("Toybox.WatchUi.WatchFaceDelegate.onNothing"), false);
  assert.equal(fenix.hasModule("NoSuchToyboxModule"), false);
  assert.equal(fenix.hasField("noSuchField"), false);
});

test("modules and fields: the real gaps and a negative control", () => {
  if (has("fenix6")) {
    assert.equal(db.get("fenix6").hasModule("Complications"), false);
    assert.equal(db.get("fenix6").hasField("stressScore"), false);
  }
  if (has("fr245")) {
    assert.equal(db.get("fr245").hasField("floorsClimbed"), false);
    assert.equal(db.get("fr245").hasModule("Complications"), false);
  }
  const f8 = db.get("fenix8solar47mm");
  assert.ok(f8.hasModule("Complications") && f8.hasField("stressScore") && f8.hasField("floorsClimbed"));
  for (const id of db.ids()) {
    assert.equal(db.get(id).hasModule("ActivityMonitor"), true, id);
    assert.equal(db.get(id).hasField("battery"), true, id);
  }
  if (has("fenix5")) {
    assert.equal(db.get("fenix5").hasModule("Weather"), false);
    assert.equal(db.get("fenix5").hasField("solarIntensity"), false);
  }
});

test("an unknown device names the installed ones; system fonts are per device; default fonts are English", () => {
  assert.throws(() => db.get("nosuchwatch"), (e: Error) => e instanceof DeviceError && e.message.includes("fenix8solar47mm"));
  const small = db.get("fenix8solar47mm").systemFonts.get("FONT_NUMBER_HOT"), large = db.get("fenix8solar51mm").systemFonts.get("FONT_NUMBER_HOT");
  if (small && large) assert.ok(large.size_px > small.size_px);
  for (const id of ["fenix8solar47mm", "fenix8solar51mm", "fr955"]) {
    const fonts = JSON.parse(readFileSync(join(DEVICE_REFERENCE, `${id}.json`), "utf8")).fonts;
    const english = Object.keys(fonts).filter((k) => k.split(",").includes("eng"));
    assert.ok(english.length > 0, id);
    assert.deepEqual(fonts.default, fonts[english[0]!], id);
  }
});

test("readers: complications by module, the ordinary ones everywhere, weather where the module is", () => {
  if (has("fenix6")) {
    const gap = availability.readerUnavailable("complication_body_battery", db.get("fenix6"))!;
    assert.deepEqual([gap.kind, gap.symbol], ["module", "Complications"]);
  }
  assert.equal(availability.readerUnavailable("complication_body_battery", db.get("fenix8solar47mm")), null);
  let sawWeather = false, sawNone = false;
  for (const id of db.ids()) {
    const device = db.get(id);
    for (const reader of ["clock", "settings", "stats", "date", "activity", "activity_info", "user_profile"]) {
      assert.equal(availability.readerUnavailable(reader, device), null, `${reader} ${id}`);
    }
    for (const reader of ["weather_current", "weather_daily"]) {
      const gap = availability.readerUnavailable(reader, device);
      if (device.hasModule("Weather")) {
        sawWeather = true;
        assert.equal(gap, null, id);
      } else {
        sawNone = true;
        assert.deepEqual([gap?.kind, gap?.symbol], ["module", "Weather"], id);
      }
    }
  }
  assert.ok(sawWeather && sawNone, "both branches exercised");
});

test("sources: by field, by module, never absent, unknown", () => {
  if (has("fenix6")) {
    const stress = availability.sourceUnavailable("activity.stress_score", db.get("fenix6"))!;
    assert.deepEqual([stress.kind, stress.symbol], ["field", "stressScore"]);
    assert.equal(availability.sourceUnavailable("complication.body_battery", db.get("fenix6"))!.kind, "module");
  }
  assert.equal(availability.sourceUnavailable("activity.stress_score", db.get("fenix8solar47mm")), null);
  if (has("fr245")) assert.deepEqual([availability.sourceUnavailable("activity.floors_climbed", db.get("fr245"))!.symbol], ["floorsClimbed"]);
  for (const id of db.ids()) assert.equal(availability.sourceUnavailable("time.hour", db.get(id)), null);
  assert.equal(availability.sourceUnavailable("no.such.path", db.get("fenix8solar47mm")), null);
});

test("no catalogue source is unavailable on the richest target; fenix6's and fr245's gaps are pinned", () => {
  const f8 = db.get("fenix8solar47mm");
  assert.deepEqual([...CATALOG.keys()].filter((p) => availability.sourceUnavailable(p, f8) !== null), []);
  const complications = new Set([...CATALOG.keys()].filter((p) => p.startsWith("complication.")));
  for (const [id, fields] of [
    ["fenix6", { "activity.stress_score": "stressScore" }],
    ["fr245", { "activity.floors_climbed": "floorsClimbed", "activity.floors_climbed_goal": "floorsClimbedGoal", "activity.stress_score": "stressScore", "ambient.pressure": "ambientPressure", "system.battery_in_days": "batteryInDays" }],
  ] as const) {
    if (!has(id)) continue;
    const gaps = new Map([...CATALOG.keys()].map((p) => [p, availability.sourceUnavailable(p, db.get(id))] as const).filter(([, g]) => g !== null));
    assert.deepEqual(Object.fromEntries([...gaps].filter(([, g]) => g!.kind === "field").map(([p, g]) => [p, g!.symbol])), fields, id);
    assert.deepEqual(new Set([...gaps].filter(([, g]) => g!.kind === "module").map(([p]) => p)), complications, id);
    assert.ok([...gaps.values()].every((g) => g!.kind !== "module" || g!.symbol === "Complications"), id);
  }
});

const TEMPLATE = (targets: string): string => `
format: 2
face: {id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f59, name: Test}
build:
  targets: [${targets}]
resources:
  palette: {bg: "#000000", fg: "#FFFFFF"}
elements:
  bg:
    type: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: color.bg
  bb:
    type: text
    text: "{complication.body_battery}"
    absent: hide
    font: FONT_TINY
    at: {anchor: center, dy: -30%}
    color: color.fg
  stress:
    type: text
    text: "{activity.stress_score:d}"
    absent: hide
    font: FONT_TINY
    at: {anchor: center, dy: 0%}
    color: color.fg
  hr:
    type: icon
    icon: heart
    size: 10%r
    at: {anchor: center, dy: 30%}
    color: color.fg
    on_hold: heart_rate
`;

const WEATHER = (targets: string): string => `
format: 2
face: {id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f5b, name: Weather}
build:
  targets: [${targets}]
resources:
  palette: {bg: "#000000", fg: "#FFFFFF"}
elements:
  temp:
    type: text
    text: "{weather.temperature:.0f}"
    absent: hide
    at: {anchor: center, dy: -20%}
    color: color.fg
  cond:
    type: icon
    icon: {for: weather.condition_today}
    size: 16%r
    at: {anchor: center}
    color: color.fg
  fc:
    type: graph
    at: {anchor: center, dy: 25%}
    size: {width: 62%, height: 13%}
    series: forecast_temperature
    range: 24h
    style: line
    thickness: 2px
    color: color.fg
    min: auto
    max: auto
`;

test("design-wide: the fields read, whether complications are used", () => {
  assert.deepEqual(availability.designFields(face(TEMPLATE("fenix6, fenix8solar47mm"))), new Set(["stressScore"]));
  assert.equal(availability.usesComplications(face(TEMPLATE("fenix8solar47mm"))), true);
  assert.equal(availability.usesComplications(face(TEMPLATE("fenix8solar47mm").replace('    text: "{complication.body_battery}"\n', '    text: "{activity.steps}"\n'))), true);
  const plain = "\nformat: 2\nface: {id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f5a, name: Test}\nbuild:\n  targets: [fenix8solar47mm]\nresources:\n  palette: {bg: \"#000000\", fg: \"#FFFFFF\"}\n"
    + "elements:\n  steps:\n    type: text\n    text: \"{activity.steps:d}\"\n    absent: hide\n    color: color.fg\n    at: {anchor: center}\n";
  assert.equal(availability.usesComplications(face(plain)), false);
});

test("guards: across the targets, for complications, fields and weather", () => {
  const f8 = db.get("fenix8solar47mm");
  if (has("fenix6")) {
    const guards = availability.computeGuards(face(TEMPLATE("fenix6, fenix8solar47mm")), [db.get("fenix6"), f8]);
    assert.equal(guards.complications, true);
    assert.deepEqual(guards.fields, new Set(["stressScore"]));
  }
  const none = availability.computeGuards(face(TEMPLATE("fenix8solar47mm")), [f8]);
  assert.equal(none.complications, false);
  assert.equal(none.fields.size, 0);
  if (has("fr245")) {
    const guards = availability.computeGuards(face(TEMPLATE("fr245, fenix8solar47mm").replace("activity.stress_score", "activity.floors_climbed")), [db.get("fr245"), f8]);
    assert.ok(guards.complications && guards.fields.has("floorsClimbed"));
  }
  if (has("fenix5")) {
    const guards = availability.computeGuards(face(WEATHER("fenix5, fenix8solar47mm")), [db.get("fenix5"), f8]);
    assert.deepEqual(guards.modules, new Set(["Weather"]));
    assert.equal(guards.complications, false);
    const text = WEATHER("fenix5, fenix8solar47mm");
    const graphOnly = text.split("  temp:\n")[0] + "  fc:\n" + text.split("  fc:\n")[1];
    assert.deepEqual(availability.computeGuards(face(graphOnly), [db.get("fenix5"), f8]).modules, new Set(["Weather"]));
  }
  assert.equal(availability.computeGuards(face(WEATHER("fenix8solar47mm")), [f8]).modules.size, 0);
});
