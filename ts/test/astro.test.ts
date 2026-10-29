// The `astro.*` sources: ten catalogue entries computed in WfbAstro.mc from
// the date, the clock and the position, each read through a barrel `call:`,
// with ts/src/astro.ts as the host twin the preview draws from. The twin is
// held to reference values from the `ephem` library (Royal Observatory,
// Greenwich, 51.4769 N, -0.0005 E, instants in UT), the barrel's text to the
// twin, and the generated view to the reader order the field check needs.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import * as astro from "../src/astro.ts";
import * as availability from "../src/availability.ts";
import { NO_GUARDS } from "../src/availability.ts";
import * as catalog from "../src/catalog.ts";
import { CATALOG } from "../src/catalog.ts";
import { REPO_ROOT } from "../src/devices/node.ts";
import { drawnText } from "../src/draw/index.ts";
import { WholeFloat } from "../src/edit/yaml.ts";
import { declarationsFor } from "../src/emit/monkeyc/readplan.ts";
import { barrelModules, RUNTIME_LIB } from "../src/emit/usage.ts";
import type { ExprValue } from "../src/expr.ts";
import { previewOptions, sampleValues } from "../src/preview.ts";
import { checked, db, face, generated, method, MINIMAL, resolved, view } from "./designs.ts";

const installed = (...ids: string[]): boolean => ids.every((id) => db.ids().includes(id));
const [LAT, LON] = [51.4769, -0.0005];
/** Days since J2000 at a UT instant. */
const ut = (y: number, m: number, d: number, h: number, mi: number): number => astro.daysSinceJ2000(y, m, d, astro.utSeconds(h, mi, 0, 0));
const num = (v: ExprValue | undefined): number => (v instanceof WholeFloat ? v.value : (v as number));

/** `MINIMAL` on `targets`, plus one text per `[id, template]`, every nullable one with `absent: {text: "--"}`. */
function bound(targets: string, ...texts: [string, string][]): string {
  const body = texts.map(([id, template]) => `  ${id}:
    type: text
    text: "${template}"
    font: FONT_SMALL
    at: {anchor: center}
    color: color.fg
    absent: {text: "--"}
`).join("");
  return MINIMAL.replace("targets: [fenix8solar47mm]", `targets: [${targets}]`) + body;
}

// -- the catalogue --

const TABLE: [string, string, string[], string, boolean][] = [
  // path, primary reader, extra readers, call, nullable
  ["astro.day_of_year", "date_short", [], "WfbAstro.dayOfYear", false],
  ["astro.days_since_j2000", "date_short", ["clock"], "WfbAstro.daysSinceJ2000", false],
  ["astro.equation_of_time", "date_short", [], "WfbAstro.equationOfTime", false],
  ["astro.moon_age", "date_short", ["clock"], "WfbAstro.moonAge", false],
  ["astro.moon_illumination", "date_short", ["clock"], "WfbAstro.moonIllumination", false],
  ["astro.sidereal_time", "weather_current", ["date_short", "clock"], "WfbAstro.siderealTime", true],
  ["astro.sun_altitude", "weather_current", ["date_short", "clock"], "WfbAstro.sunAltitude", true],
  ["astro.sun_azimuth", "weather_current", ["date_short", "clock"], "WfbAstro.sunAzimuth", true],
  ["astro.sun_declination", "date_short", [], "WfbAstro.sunDeclination", false],
  ["astro.sun_noon_altitude", "weather_current", ["date_short"], "WfbAstro.sunNoonAltitude", true],
];

test("astro.*: ten entries; the position-dependent four read weather_current first and are gated on its field", () => {
  assert.deepEqual(catalog.namespaces().get("astro"), TABLE.map(([path]) => path));
  for (const [path, reader, extras, call, nullable] of TABLE) {
    const source = CATALOG.get(path)!;
    assert.equal(source.type, path === "astro.day_of_year" ? "number" : "float", path);
    assert.equal(source.reader, reader, path);
    assert.deepEqual(source.extra_readers, extras, path);
    assert.equal(source.call, call, path);
    assert.equal(source.nullable, nullable, path);
    // The device-field check is keyed on the primary reader's local, so the gated field rides the reader that owns it.
    assert.equal(source.field_name, nullable ? "observationLocationPosition" : null, path);
    assert.deepEqual(source.permissions, nullable ? ["Positioning"] : [], path);
    assert.equal(catalog.guardNeeded(source), nullable, path);
    assert.match(source.doc, /\w/, path);
  }
  assert.equal(catalog.readExpr(CATALOG.get("astro.sun_altitude")!), "WfbAstro.sunAltitude(weatherCurrent, dateShort, clock)");
  assert.equal(catalog.readExpr(CATALOG.get("astro.moon_age")!), "WfbAstro.moonAge(dateShort, clock)");
  assert.equal(catalog.readExpr(CATALOG.get("astro.sun_declination")!), "WfbAstro.sunDeclination(dateShort)");
});

// -- the twin against ephem --

/** [y, m, d, h, min UT, declination, altitude, azimuth, equation of time (min)] at Greenwich. */
const SUN: [number, number, number, number, number, number, number, number, number][] = [
  [2026, 3, 20, 12, 0, -0.047, 38.452, 177.625, -7.44],
  [2026, 6, 21, 12, 0, 23.437, 61.958, 179.112, -1.82],
  [2026, 9, 3, 9, 9, 7.478, 33.805, 126.129, 0.64],
  [2026, 9, 23, 12, 0, -0.195, 38.303, 182.430, 7.62],
  [2026, 12, 21, 12, 0, -23.439, 15.083, 180.459, 1.93],
  [2026, 2, 11, 12, 0, -13.929, 24.521, 176.218, -14.18],
  [2026, 11, 3, 12, 0, -15.153, 23.273, 184.320, 16.44],
];

const within = (got: number, want: number, tolerance: number, what: string): void =>
  assert.ok(Math.abs(got - want) <= tolerance, `${what}: ${got} is not within ${tolerance} of ${want}`);

test("the sun at Greenwich: declination within 0.3 deg, altitude and azimuth within 1 deg, equation of time within 0.5 min", () => {
  for (const [y, m, d, h, mi, decl, alt, az, eot] of SUN) {
    const when = `${y}-${m}-${d} ${h}:${mi}`;
    const now = ut(y, m, d, h, mi);
    within(astro.sunDeclination(now), decl, 0.3, `${when} declination`);
    within(astro.sunAltitude(now, LAT, LON), alt, 1.0, `${when} altitude`);
    within(astro.sunAzimuth(now, LAT, LON), az, 1.0, `${when} azimuth`);
    within(astro.equationOfTime(now), eot, 0.5, `${when} equation of time`);
    // The achieved figures, so a regression inside the tolerance is still seen.
    within(astro.sunDeclination(now), decl, 0.01, `${when} declination (achieved)`);
    within(astro.sunAltitude(now, LAT, LON), alt, 0.01, `${when} altitude (achieved)`);
    within(astro.sunAzimuth(now, LAT, LON), az, 0.02, `${when} azimuth (achieved)`);
    within(astro.equationOfTime(now), eot, 0.07, `${when} equation of time (achieved)`);
  }
  // Noon altitude is the culmination: 90 minus the distance from the latitude to the declination.
  within(astro.sunNoonAltitude(ut(2026, 6, 21, 12, 0), LAT), 61.958, 0.1, "midsummer noon");
  within(astro.sunNoonAltitude(ut(2026, 12, 21, 12, 0), LAT), 15.083, 0.1, "midwinter noon");
  // A broken twin is caught: dropping the equation of centre moves the declination by up to 0.8 deg.
  const meanOnly = (d: number): number => Math.asin(Math.sin(astro.obliquity(d)) * Math.sin(astro.meanLongitude(d) * astro.RAD)) * astro.DEG;
  assert.ok(SUN.some(([y, m, d, h, mi, decl]) => Math.abs(meanOnly(ut(y, m, d, h, mi)) - decl) > 0.3));
});

test("sidereal time: GMST 7:59:05 at 2026-09-03 09:09 UT, plus the longitude in hours", () => {
  const now = ut(2026, 9, 3, 9, 9);
  const gmstHours = 7 + 59 / 60 + 5 / 3600;
  within(astro.gmst(now) / 15, gmstHours, 1 / 3600, "GMST");
  within(astro.siderealTime(now, 0), gmstHours, 1 / 3600, "LMST at 0 E");
  within(astro.siderealTime(now, 15), gmstHours + 1, 1 / 3600, "LMST at 15 E");
  within(astro.siderealTime(now, -0.0005), gmstHours - 0.0005 / 15, 1 / 3600, "LMST at Greenwich");
  assert.ok(astro.siderealTime(now, 300) < 24 && astro.siderealTime(now, -300) >= 0);
});

/** The new and full moons of 2026, UT. */
const MOONS: ["new" | "full", number, number, number, number, number][] = [
  ["new", 2026, 2, 17, 12, 1], ["new", 2026, 3, 19, 1, 23], ["new", 2026, 8, 12, 17, 37], ["new", 2026, 9, 11, 3, 27], ["new", 2026, 10, 10, 15, 50],
  ["full", 2026, 3, 3, 11, 38], ["full", 2026, 4, 2, 2, 12], ["full", 2026, 8, 28, 4, 18], ["full", 2026, 9, 26, 16, 49], ["full", 2026, 10, 26, 4, 12],
];

/** Signed distance of an age from `want`, round the cycle. */
function phaseError(age: number, want: number): number {
  let e = age - want;
  if (e > astro.SYNODIC_MONTH / 2) e -= astro.SYNODIC_MONTH;
  if (e < -astro.SYNODIC_MONTH / 2) e += astro.SYNODIC_MONTH;
  return e;
}

test("the moon: every new and full moon of 2026 within 0.3 d (0.02 achieved); illumination 60.9% on 2026-09-03 09:09 UT", () => {
  for (const [kind, y, m, d, h, mi] of MOONS) {
    const want = kind === "new" ? 0 : astro.SYNODIC_MONTH / 2;
    const age = astro.moonAge(ut(y, m, d, h, mi));
    assert.ok(age >= 0 && age < astro.SYNODIC_MONTH, `${kind} ${y}-${m}-${d}: age ${age}`);
    const error = Math.abs(phaseError(age, want));
    assert.ok(error <= 0.3, `${kind} ${y}-${m}-${d}: age ${age} is ${error} d off`);
    assert.ok(error <= 0.02, `${kind} ${y}-${m}-${d}: age ${age} is ${error} d off (achieved)`);
    const lit = astro.moonIllumination(ut(y, m, d, h, mi));
    within(lit, kind === "new" ? 0 : 1, 0.001, `${kind} ${y}-${m}-${d} illumination`);
  }
  within(astro.moonIllumination(ut(2026, 9, 3, 9, 9)), 0.609, 0.005, "illumination");
  // The rejected alternative, kept so the sweep is seen to separate it: the mean synodic cycle anchored on the
  // new moon of 2000-01-06 18:14 UT drifts up to 0.73 d from the true phases above.
  const anchor = ut(2000, 1, 6, 18, 14);
  const meanCycleAge = (d: number): number => { const a = (d - anchor) % astro.SYNODIC_MONTH; return a < 0 ? a + astro.SYNODIC_MONTH : a; };
  const worst = Math.max(...MOONS.map(([kind, y, m, d, h, mi]) => Math.abs(phaseError(meanCycleAge(ut(y, m, d, h, mi)), kind === "new" ? 0 : astro.SYNODIC_MONTH / 2))));
  assert.ok(worst > 0.3 && worst < 0.8, String(worst));
});

test("the calendar: day of the year, days since J2000, and the Float the watch hands back", () => {
  assert.equal(astro.dayOfYear(2026, 1, 1), 1);
  assert.equal(astro.dayOfYear(2026, 9, 3), 246);
  assert.equal(astro.dayOfYear(2026, 12, 31), 365);
  assert.equal(astro.dayOfYear(2024, 12, 31), 366);
  assert.equal(astro.dayOfYear(2024, 3, 1), 61);
  assert.equal(astro.daysSinceJ2000(2000, 1, 1, 12 * 3600), 0);
  assert.equal(astro.daysSinceJ2000(2000, 1, 2, 0), 0.5);
  // A local 10:09:42 at UTC+2 is 08:09:42 UT; the offset may carry the instant across midnight either way.
  const sample = astro.daysSinceJ2000(2026, 9, 3, astro.utSeconds(10, 9, 42, 7200));
  within(sample, 9741.8401, 0.0001, "sample instant");
  assert.equal(astro.daysSinceJ2000(2026, 9, 3, astro.utSeconds(0, 30, 0, 7200)), astro.daysSinceJ2000(2026, 9, 2, astro.utSeconds(22, 30, 0, 0)));
  assert.equal(astro.daysSinceJ2000(2026, 9, 3, astro.utSeconds(23, 30, 0, -3600)), astro.daysSinceJ2000(2026, 9, 4, astro.utSeconds(0, 30, 0, 0)));
  // Float: 24 significant bits, so days since J2000 resolve to 2^-10 d (84 s) at 1e4 days.
  assert.equal(Math.fround(sample) - sample < 1 / 1024, true);
  assert.equal(astro.wrap360(-1), 359);
  assert.equal(astro.wrap360(725), 5);
  assert.equal(astro.wrap360(360), 0);
});

// -- the generated view --

test("the view calls the barrel with the readers in the catalogue's order, a nullable one behind its guard", () => {
  const text = bound("fenix8solar47mm", ["decl", "{astro.sun_declination:.2f}"], ["age", "{astro.moon_age:.1f}"], ["alt", "{astro.sun_altitude:.1f}"]);
  const v = view(text, ["fenix8solar47mm"]);
  assert.match(method(v, "drawDecl"), /var astroSunDeclination = WfbAstro\.sunDeclination\(dateShort\);/);
  assert.match(method(v, "drawAge"), /var astroMoonAge = WfbAstro\.moonAge\(dateShort, clock\);/);
  assert.match(method(v, "drawAlt"), /var astroSunAltitude = \(weatherCurrent != null\) \? WfbAstro\.sunAltitude\(weatherCurrent, dateShort, clock\) : null;/);
  assert.match(v, /private function drawAlt\(dc as Dc, weatherCurrent as Weather\.CurrentConditions\?, dateShort as Gregorian\.Info, clock as System\.ClockTime\) as Void/);
  assert.match(v, /private function drawDecl\(dc as Dc, dateShort as Gregorian\.Info\) as Void/);
  assert.match(v, /var dateShort = Gregorian\.info\(Time\.now\(\), Time\.FORMAT_SHORT\);/);
  assert.match(v, /var clock = System\.getClockTime\(\);/);
  assert.match(v, /var weatherCurrent = Weather\.getCurrentConditions\(\);/);
  assert.doesNotMatch(v, /has :/);
  assert.ok(barrelModules(v).has("WfbAstro.mc"));
  // The permission follows the position dependence.
  assert.match(generated(text, ["fenix8solar47mm"]).get("manifest.xml")!, /<iq:uses-permission id="Positioning"\/>/);
  assert.doesNotMatch(generated(bound("fenix8solar47mm", ["age", "{astro.moon_age:.1f}"]), ["fenix8solar47mm"]).get("manifest.xml")!, /Positioning/);
});

test("the field check lands on the primary reader's local when extra readers are present", () => {
  const source = CATALOG.get("astro.sun_altitude")!;
  assert.deepEqual(declarationsFor(source, { ...NO_GUARDS, fields: new Set(["observationLocationPosition"]) }), [[
    "astroSunAltitude", "(weatherCurrent != null && weatherCurrent has :observationLocationPosition) ? WfbAstro.sunAltitude(weatherCurrent, dateShort, clock) : null",
  ]]);
  assert.deepEqual(declarationsFor(source, { ...NO_GUARDS, modules: new Set(["Weather"]), fields: new Set(["observationLocationPosition"]) }), [[
    "astroSunAltitude",
    "((Toybox has :Weather) && weatherCurrent != null && weatherCurrent has :observationLocationPosition) ? WfbAstro.sunAltitude(weatherCurrent, dateShort, clock) : null",
  ]]);
  // The shape that would have read null everywhere: the gated field on an extra reader, checked on the primary.
  const swapped = { ...source, reader: "date_short", extra_readers: ["clock", "weather_current"] };
  const read = declarationsFor(swapped, { ...NO_GUARDS, fields: new Set(["observationLocationPosition"]) })[0]![1];
  assert.match(read, /dateShort has :observationLocationPosition/);
});

test("a build with fenix5 guards the module and the field round a positioned call, and lints api-gated there only", () => {
  if (!installed("fenix5", "fenix8solar47mm")) return;
  const text = bound("fenix5, fenix8solar47mm", ["alt", "{astro.sun_altitude:.1f}"], ["age", "{astro.moon_age:.1f}"]);
  const guards = availability.computeGuards(face(text), [db.get("fenix5"), db.get("fenix8solar47mm")]);
  assert.deepEqual(guards.modules, new Set(["Weather"]));
  assert.deepEqual(guards.fields, new Set(["observationLocationPosition"]));
  const v = view(text, ["fenix5", "fenix8solar47mm"]);
  assert.match(method(v, "drawAlt"), /var astroSunAltitude = \(\(Toybox has :Weather\) && weatherCurrent != null && weatherCurrent has :observationLocationPosition\) \? WfbAstro\.sunAltitude\(weatherCurrent, dateShort, clock\) : null;/);
  assert.match(method(v, "drawAge"), /var astroMoonAge = WfbAstro\.moonAge\(dateShort, clock\);/);
  const gated = checked(text).filter((d) => d.code === "api-gated").map((d) => d.message);
  assert.deepEqual(gated, ["alt: 'astro.sun_altitude' needs module Toybox.Weather, which fenix5 lacks, so it reads as absent there ('absent:' applies)"]);
  for (const path of ["astro.sidereal_time", "astro.sun_azimuth", "astro.sun_noon_altitude"]) {
    assert.deepEqual([availability.sourceUnavailable(path, db.get("fenix5"))!.kind], ["module"], path);
  }
  for (const path of ["astro.moon_age", "astro.day_of_year", "astro.sun_declination"]) {
    assert.equal(availability.sourceUnavailable(path, db.get("fenix5")), null, path);
  }
});

// -- the preview --

const SAMPLE_UT = astro.daysSinceJ2000(2026, 9, 3, astro.utSeconds(10, 9, 42, 7200));

test("the preview derives the sample astronomy from the frame's date, time, offset and position", () => {
  const text = bound("fenix8solar47mm", ["alt", "ALT {astro.sun_altitude:.1f}"], ["age", "AGE {astro.moon_age:.1f}d"], ["doy", "{astro.day_of_year:d}"]);
  const r = resolved(text);
  const values = sampleValues(r, previewOptions(), null);
  assert.equal(values.get("astro.day_of_year"), 246);
  assert.equal(num(values.get("astro.days_since_j2000")), Math.fround(SAMPLE_UT));
  assert.equal(num(values.get("astro.moon_age")), Math.fround(astro.moonAge(SAMPLE_UT)));
  assert.equal(num(values.get("astro.sun_altitude")), Math.fround(astro.sunAltitude(SAMPLE_UT, LAT, LON)));
  assert.equal(num(values.get("astro.sidereal_time")), Math.fround(astro.siderealTime(SAMPLE_UT, LON)));
  assert.equal(num(values.get("astro.sun_noon_altitude")), Math.fround(astro.sunNoonAltitude(astro.noon(2026, 9, 3), LAT)));
  const item = (id: string) => r.items.find((p) => p.id === id)!;
  assert.equal(drawnText(r, item("alt"), values as never), "ALT 25.7");
  assert.equal(drawnText(r, item("age"), values as never), "AGE 21.1d");
  assert.equal(drawnText(r, item("doy"), values as never), "246");
  // An overridden offset or position flows through; an astro override of its own wins; no position, no sun.
  const utc = sampleValues(r, previewOptions({ sample: new Map([["time.utc_offset", 0]]) }), null);
  assert.equal(num(utc.get("astro.sun_altitude")), Math.fround(astro.sunAltitude(astro.daysSinceJ2000(2026, 9, 3, astro.utSeconds(10, 9, 42, 0)), LAT, LON)));
  const paris = sampleValues(r, previewOptions({ sample: new Map([["position.latitude", 48.8566], ["position.longitude", 2.3522]]) }), null);
  assert.equal(num(paris.get("astro.sun_altitude")), Math.fround(astro.sunAltitude(SAMPLE_UT, 48.8566, 2.3522)));
  const forced = sampleValues(r, previewOptions({ sample: new Map([["astro.moon_age", 3.5]]) }), null);
  assert.equal(forced.get("astro.moon_age"), 3.5);
  assert.equal(drawnText(r, item("age"), forced as never), "AGE 3.5d");
  const nowhere = sampleValues(r, previewOptions({ sample: new Map([["position.latitude", null]]) }), null);
  assert.equal(nowhere.get("astro.sun_altitude"), null);
  assert.equal(nowhere.get("astro.moon_age"), values.get("astro.moon_age"));
  assert.equal(drawnText(r, item("alt"), nowhere as never), "--");
  // --date and --time: the equinox at noon UT.
  const equinox = sampleValues(r, previewOptions({ date: [2026, 3, 20], time: [12, 0, 0], sample: new Map([["time.utc_offset", 0]]) }), null);
  within(num(equinox.get("astro.sun_declination")), -0.047, 0.3, "equinox declination");
  within(num(equinox.get("astro.sun_altitude")), 38.452, 1.0, "equinox altitude");
  assert.equal(equinox.get("astro.day_of_year"), 79);
});

// -- the barrel's text --

const STATEMENTS = [
  `const RAD = ${astro.RAD}d;`,
  `const DEG = ${astro.DEG}d;`,
  `(elongation(instant(date, clock)) / 360d * ${astro.SYNODIC_MONTH}d).toFloat();`,
  "return 367 * year - 7 * (year + (month + 9) / 12) / 4 + 275 * month / 9 + day - 730531;",
  "return clock.hour * 3600 + clock.min * 60 + clock.sec - clock.timeZoneOffset;",
  "wholeDays(date.year, date.month as Number, date.day).toDouble() + utSeconds(clock).toDouble() / 86400d - 0.5d;",
  "wholeDays(date.year, date.month as Number, date.day) - wholeDays(date.year, 1, 0);",
  "var w = x - 360d * (x / 360d).toNumber(); if (w < 0) { w += 360d; } return w;",
  "return wrap360(280.46646d + 36000.76983d * t + 0.0003032d * t * t);",
  "return wrap360(357.52911d + 35999.05029d * t - 0.0001537d * t * t);",
  "return (1.914602d - 0.004817d * t - 0.000014d * t * t) * sinD(m) + (0.019993d - 0.000101d * t) * sinD(2d * m) + 0.000289d * sinD(3d * m);",
  "return (23.439291d - 0.0130042d * century(d)) * RAD;",
  "return wrap360(atan2D(cosD(eps) * sinD(lambda), cosD(lambda)) * DEG);",
  "return asinD(sinD(eps) * sinD(lambda)) * DEG;",
  "var e = meanLongitude(d) - 0.0057183d - rightAscension(d); if (e > 180d) { e -= 360d; } if (e < -180d) { e += 360d; } return (e * 4d).toFloat();",
  "return wrap360(280.46061837d + 360.98564736629d * d + 0.000387933d * t * t - t * t * t / 38710000d);",
  "return wrap360(gmstAt(d) + longitude - rightAscension(d)) * RAD;",
  "218.32d + 481267.881d * t + 6.29d * sinD(wrap360(135.0d + 477198.87d * t) * RAD) - 1.27d * sinD(wrap360(259.3d - 413335.36d * t) * RAD)",
  "+ 0.66d * sinD(wrap360(235.7d + 890534.22d * t) * RAD) + 0.21d * sinD(wrap360(269.9d + 954397.70d * t) * RAD) - 0.19d * sinD(wrap360(357.5d + 35999.05d * t) * RAD)",
  "- 0.11d * sinD(wrap360(186.5d + 966404.03d * t) * RAD));",
  "return wrap360(moonLongitude(d) - trueLongitude(d));",
  "((1d - cosD(elongation(instant(date, clock)) * RAD)) / 2d).toFloat();",
  "return (asinD(sinD(phi) * sinD(decl) + cosD(phi) * cosD(decl) * cosD(h)) * DEG).toFloat();",
  "return wrap360(atan2D(sinD(h) * cosD(decl), cosD(h) * sinD(phi) * cosD(decl) - sinD(decl) * cosD(phi)) * DEG + 180d).toFloat();",
  "var gap = lat.toDouble() - declinationAt(noon(date)); if (gap < 0) { gap = -gap; } return (90d - gap).toFloat();",
  "return (wrap360(gmstAt(instant(date, clock)) + lon.toDouble()) / 15d).toFloat();",
  "function siderealTime(conditions as Weather.CurrentConditions, date as Gregorian.Info, clock as System.ClockTime) as Float?",
  "function sunAltitude(conditions as Weather.CurrentConditions, date as Gregorian.Info, clock as System.ClockTime) as Float?",
  "function sunAzimuth(conditions as Weather.CurrentConditions, date as Gregorian.Info, clock as System.ClockTime) as Float?",
  "function sunNoonAltitude(conditions as Weather.CurrentConditions, date as Gregorian.Info) as Float?",
  "function dayOfYear(date as Gregorian.Info) as Number",
  "function daysSinceJ2000(date as Gregorian.Info, clock as System.ClockTime) as Float",
  "function equationOfTime(date as Gregorian.Info) as Float",
  "function sunDeclination(date as Gregorian.Info) as Float",
];

test("WfbAstro.mc still says what the twin transcribes, Double throughout", () => {
  const raw = readFileSync(join(REPO_ROOT, "runtime-lib", "WfbAstro.mc"), "utf8");
  assert.equal(RUNTIME_LIB.get("WfbAstro.mc"), raw, "run node ts/tools/export-data.ts");
  const text = raw.replace(/\s+/g, " ");
  for (const s of STATEMENTS) assert.ok(text.includes(s), `WfbAstro.mc no longer contains ${s}`);
  // Every literal in the arithmetic is a Double: no bare decimal that would drag a product down to Float.
  const arithmetic = raw.split("// -- the arithmetic")[1]!.split("\n").filter((line) => !line.trim().startsWith("//")).join("\n");
  assert.deepEqual([...arithmetic.matchAll(/\b\d+\.\d+(?!\d*d)\b/g)].map((m) => m[0]), []);
  assert.doesNotMatch(arithmetic, /Math\.PI/);
  // Each catalogue call names a function the barrel declares.
  for (const [, , , call] of TABLE) assert.match(raw, new RegExp(`function ${call.split(".")[1]}\\(`), call);
});

// -- the command line --

const CLI = join(REPO_ROOT, "ts", "src", "cli.ts");
const EXAMPLE = "examples/features/astro/face.yaml";

function wfb(args: string[]): { code: number; stdout: string; stderr: string; bytes: Buffer } {
  const done = spawnSync(process.execPath, [CLI, ...args], { cwd: REPO_ROOT, env: { ...process.env, WFB_NO_GARMIN_FONTS: "1" }, maxBuffer: 64 * 1024 * 1024 });
  return { code: done.status ?? -1, stdout: done.stdout.toString(), stderr: done.stderr.toString(), bytes: done.stdout };
}

test("wfb sources lists the astro group; wfb preview takes --date and refuses a day that is not one", () => {
  const sources = wfb(["sources"]);
  assert.equal(sources.code, 0, sources.stderr);
  assert.match(sources.stdout, /\nastro\n/);
  for (const [path] of TABLE) assert.ok(sources.stdout.includes(`  ${path}`), path);
  assert.match(sources.stdout, /astro\.sun_altitude\s+float\s+.*absent without a position\s+\[nullable, needs Positioning\]/);
  const plain = wfb(["preview", EXAMPLE, "-d", "fenix8solar47mm", "-o", "-"]);
  assert.equal(plain.code, 0, plain.stderr);
  const equinox = wfb(["preview", EXAMPLE, "-d", "fenix8solar47mm", "-o", "-", "--date", "2026-03-20", "--time", "12:00:00", "--sample", "time.utc_offset=0"]);
  assert.equal(equinox.code, 0, equinox.stderr);
  assert.ok(!equinox.bytes.equals(plain.bytes), "--date changes the frame");
  assert.ok(wfb(["preview", EXAMPLE, "-d", "fenix8solar47mm", "-o", "-", "--date", "2026-09-03"]).bytes.equals(plain.bytes), "the sample date draws the sample frame");
  for (const bad of ["2026-02-30", "2026-13-01", "20260903", "3 Sep 2026"]) {
    const r = wfb(["preview", EXAMPLE, "-d", "fenix8solar47mm", "-o", "-", "--date", bad]);
    assert.equal(r.code, 1, bad);
    assert.ok(r.stderr.includes(`--date '${bad}' is not a calendar day written YYYY-MM-DD`), r.stderr);
  }
});

test("the example binds every astro.* and position.* source and lints clean on the three targets", () => {
  const text = readFileSync(join(REPO_ROOT, EXAMPLE), "utf8");
  const paths = availability.designPaths(face(text));
  for (const [path] of TABLE) assert.ok(paths.has(path), path);
  assert.ok(paths.has("position.latitude") && paths.has("position.longitude"));
  assert.deepEqual(checked(text).filter((d) => d.severity !== "note").map((d) => `${d.code}: ${d.message}`), []);
});
