// The wearer's position (`position.latitude`/`longitude`), read off the
// weather report through a barrel call, and the catalogue mechanism behind
// it: a source with `call:` reads `<call>(<reader>[, <extra readers>...])`,
// every reader it names is hoisted and guarded, and the manifest gains the
// Positioning permission.
import assert from "node:assert/strict";
import { test } from "node:test";
import * as availability from "../src/availability.ts";
import { NO_GUARDS } from "../src/availability.ts";
import * as catalog from "../src/catalog.ts";
import { CATALOG, type Source } from "../src/catalog.ts";
import { declarationsFor } from "../src/emit/monkeyc/readplan.ts";
import { barrelModules, RUNTIME_LIB } from "../src/emit/usage.ts";
import { SAMPLE } from "../src/sample.ts";
import { checked, db, drawn, face, generated, method, MINIMAL, view } from "./designs.ts";

const installed = (...ids: string[]): boolean => ids.every((id) => db.ids().includes(id));

/** `MINIMAL` on `targets`, plus one text bound to `path` with `absent: {text: "--"}`. */
const bound = (targets: string, path: string, id = "lat"): string => `${MINIMAL.replace("targets: [fenix8solar47mm]", `targets: [${targets}]`)}
  ${id}:
    type: text
    text: "lat {${path}:.4f}"
    font: FONT_SMALL
    at: {anchor: center}
    color: color.fg
    absent: {text: "--"}
`;

test("position.*: two nullable floats off weather_current, through WfbAstro, needing Positioning", () => {
  assert.deepEqual(catalog.namespaces().get("position"), ["position.latitude", "position.longitude"]);
  for (const [path, call] of [["position.latitude", "WfbAstro.latitude"], ["position.longitude", "WfbAstro.longitude"]]) {
    const source = CATALOG.get(path!)!;
    assert.equal(source.type, "float");
    assert.equal(source.reader, "weather_current");
    assert.deepEqual(source.extra_readers, []);
    assert.equal(source.call, call);
    assert.equal(source.field_name, "observationLocationPosition");
    assert.equal(source.nullable, true);
    assert.deepEqual(source.permissions, ["Positioning"]);
    assert.equal(catalog.readExpr(source), `${call}(weatherCurrent)`);
    assert.equal(catalog.guardNeeded(source), true);
  }
  // Every pre-existing entry reads a field, with defaults for the new keys.
  const temperature = CATALOG.get("weather.temperature")!;
  assert.equal(temperature.call, null);
  assert.deepEqual(temperature.extra_readers, []);
  assert.equal(catalog.readExpr(temperature), "weatherCurrent.temperature");
});

test("the view reads the call behind the reader's null guard and takes the reader as its parameter", () => {
  const v = view(bound("fenix8solar47mm", "position.latitude"), ["fenix8solar47mm"]);
  assert.match(v, /var weatherCurrent = Weather\.getCurrentConditions\(\);/);
  assert.match(v, /private function drawLat\(dc as Dc, weatherCurrent as Weather\.CurrentConditions\?\) as Void/);
  assert.match(v, /var positionLatitude = \(weatherCurrent != null\) \? WfbAstro\.latitude\(weatherCurrent\) : null;/);
  assert.doesNotMatch(v, /has :/);
  assert.ok(barrelModules(v).has("WfbAstro.mc"));
  const lon = view(bound("fenix8solar47mm", "position.longitude", "lon"), ["fenix8solar47mm"]);
  assert.match(lon, /var positionLongitude = \(weatherCurrent != null\) \? WfbAstro\.longitude\(weatherCurrent\) : null;/);
});

test("a build with fenix5 guards the Weather module and the field around the call, and lints api-gated there", () => {
  if (!installed("fenix5", "fenix8solar47mm")) return;
  const text = bound("fenix5, fenix8solar47mm", "position.latitude");
  const guards = availability.computeGuards(face(text), [db.get("fenix5"), db.get("fenix8solar47mm")]);
  assert.deepEqual(guards.modules, new Set(["Weather"]));
  assert.deepEqual(guards.fields, new Set(["observationLocationPosition"]));
  const v = view(text, ["fenix5", "fenix8solar47mm"]);
  assert.match(v, /var weatherCurrent = \(Toybox has :Weather\) \? Weather\.getCurrentConditions\(\) : null;/);
  assert.match(v, /var positionLatitude = \(\(Toybox has :Weather\) && weatherCurrent != null && weatherCurrent has :observationLocationPosition\) \? WfbAstro\.latitude\(weatherCurrent\) : null;/);
  // The lint: the module gap on fenix5, nothing on the verification targets.
  const gated = checked(text).filter((d) => d.code === "api-gated").map((d) => d.message);
  assert.deepEqual(gated, ["lat: 'position.latitude' needs module Toybox.Weather, which fenix5 lacks, so it reads as absent there ('absent:' applies)"]);
  assert.deepEqual(checked(bound("fenix8solar47mm, fenix8solar51mm, fr955", "position.latitude")).filter((d) => d.code === "api-gated"), []);
  const gap = availability.sourceUnavailable("position.latitude", db.get("fenix5"))!;
  assert.deepEqual([gap.kind, gap.symbol], ["module", "Weather"]);
  assert.equal(availability.sourceUnavailable("position.latitude", db.get("fenix8solar47mm")), null);
});

test("the field check is keyed on field_name even for a call: fenix5 lacks observationLocationPosition", () => {
  if (!installed("fenix5", "fenix8solar47mm")) return;
  // A reader fenix5 has, so the module check passes and the field check answers.
  const source: Source = { ...CATALOG.get("position.latitude")!, path: "astro.test", reader: "clock" };
  const gap = availability.sourceGap(source, db.get("fenix5"))!;
  assert.deepEqual([gap.kind, gap.symbol], ["field", "observationLocationPosition"]);
  assert.equal(availability.sourceGap(source, db.get("fenix8solar47mm")), null);
});

test("the manifest gains Positioning from the binding, and only from it", () => {
  const files = generated(bound("fenix8solar47mm", "position.longitude"), ["fenix8solar47mm"]);
  assert.match(files.get("manifest.xml")!, /<iq:uses-permission id="Positioning"\/>/);
  const weather = generated(bound("fenix8solar47mm", "weather.temperature"), ["fenix8solar47mm"]);
  assert.doesNotMatch(weather.get("manifest.xml")!, /Positioning/);
  assert.deepEqual([...face(bound("fenix8solar47mm", "position.latitude")).requirements().permissions], ["Positioning"]);
});

test("a call with an extra reader: both readers hoisted, the nullable one guarded, the module guard where a target lacks it", () => {
  // Synthetic: the primary reader is never null, the extra one is nullable and module-gated.
  const source: Source = {
    ...CATALOG.get("position.latitude")!, path: "astro.test", reader: "clock", extra_readers: ["weather_current"], call: "WfbAstro.latitude",
  };
  assert.deepEqual(catalog.readerNames(source), ["clock", "weather_current"]);
  assert.equal(catalog.readExpr(source), "WfbAstro.latitude(clock, weatherCurrent)");
  assert.equal(catalog.guardNeeded({ ...source, nullable: false }), true, "a nullable extra reader needs the guard");
  assert.equal(catalog.guardNeeded({ ...source, nullable: false, extra_readers: [] }), false);
  const requirements = new catalog.Requirements();
  requirements.add(source);
  assert.deepEqual(requirements.readers, new Set(["clock", "weather_current"]));
  assert.deepEqual(requirements.modules, new Set(["Toybox.System", "Toybox.Weather"]));
  assert.deepEqual(declarationsFor(source, NO_GUARDS), [["astroTest", "(weatherCurrent != null) ? WfbAstro.latitude(clock, weatherCurrent) : null"]]);
  assert.deepEqual(declarationsFor(source, { ...NO_GUARDS, modules: new Set(["Weather"]) }),
    [["astroTest", "((Toybox has :Weather) && weatherCurrent != null) ? WfbAstro.latitude(clock, weatherCurrent) : null"]]);
  // An extra reader some target lacks makes the source unavailable there.
  if (installed("fenix5")) {
    const gap = availability.sourceGap(source, db.get("fenix5"))!;
    assert.deepEqual([gap.kind, gap.symbol], ["module", "Weather"]);
  }
  // Through the view: the element's method takes both readers, in order, and the frame pulls both.
  CATALOG.set(source.path, source);
  try {
    const v = view(bound("fenix8solar47mm", "astro.test"), ["fenix8solar47mm"]);
    assert.match(v, /var clock = System\.getClockTime\(\);/);
    assert.match(v, /var weatherCurrent = Weather\.getCurrentConditions\(\);/);
    assert.match(v, /drawLat\(dc, clock, weatherCurrent\);/);
    assert.match(v, /private function drawLat\(dc as Dc, clock as System\.ClockTime, weatherCurrent as Weather\.CurrentConditions\?\) as Void/);
    assert.match(method(v, "drawLat"), /var astroTest = \(weatherCurrent != null\) \? WfbAstro\.latitude\(clock, weatherCurrent\) : null;/);
  } finally {
    CATALOG.delete(source.path);
  }
});

test("the preview draws the Greenwich sample, an overriding sample, and the absent text", () => {
  assert.equal(SAMPLE.get("position.latitude"), 51.4769);
  assert.equal(SAMPLE.get("position.longitude"), -0.0005);
  const text = bound("fenix8solar47mm", "position.latitude");
  assert.equal(drawn(text, "lat", { "position.latitude": SAMPLE.get("position.latitude") }), "lat 51.4769");
  assert.equal(drawn(text, "lat", { "position.latitude": 48.8566 }), "lat 48.8566");
  assert.equal(drawn(text, "lat", { "position.latitude": null }), "--");
});

test("WfbAstro checks the Weather module and the field itself, every caller notwithstanding", () => {
  const astro = RUNTIME_LIB.get("WfbAstro.mc")!;
  for (const fn of ["latitude", "longitude"]) {
    const body = astro.split(`function ${fn}(`)[1]!.split("\n    }")[0]!;
    assert.match(body, /if \(\(Toybox has :Weather\) && \(conditions has :observationLocationPosition\)\) \{/, fn);
    assert.match(body, /return \(location != null\) \? location\.toDegrees\(\)\[[01]\]\.toFloat\(\) : null;/, fn);
  }
  assert.match(astro, /function latitude\(conditions as Weather\.CurrentConditions\) as Float\?/);
  assert.match(astro, /function longitude\(conditions as Weather\.CurrentConditions\) as Float\?/);
});
