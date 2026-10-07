// Format specs: the Monkey C they compile to, how the preview renders them,
// and their widest rendering; durations on a Number or Float of seconds.
import assert from "node:assert/strict";
import { test } from "node:test";
import { get } from "../src/catalog.ts";
import { barrelModules } from "../src/emit/usage.ts";
import * as formatting from "../src/formatting.ts";
import { drawn, errors, face, MINIMAL, method, template, view } from "./designs.ts";

const r = (spec: string, value: unknown, type: Parameters<typeof formatting.render>[2], values: Record<string, unknown> = {}): string =>
  formatting.render(spec, value, type, new Map(Object.entries(values)));

test("numeric emission", () => {
  for (const [spec, v, want] of [
    ["{:d}", "n", 'n.format("%d")'], ["{:02d}", "n", 'n.format("%02d")'], ["{:.1f}", "x", 'x.format("%.1f")'], ["{}", "n", "n.toString()"],
    ["{:d} steps", "n", 'n.format("%d") + " steps"'],
  ]) assert.equal(formatting.emit(spec!, v!, "number"), want, spec);
  assert.equal(formatting.emit("{:d}", "x", "float"), 'x.toNumber().format("%d")');
});

test("time emission", () => {
  const h = formatting.emit("{:%h:%M}", "", "time");
  assert.ok(h.includes("WfbTime.displayHour(clock.hour, settings.is24Hour)") && h.includes('clock.min.format("%02d")'));
  const big = formatting.emit("{:%H:%M}", "", "time");
  assert.ok(!big.includes("is24Hour") && big.includes('clock.hour.format("%02d")'));
  const twelve = formatting.emit("{:%I:%M %p}", "", "time");
  assert.ok(twelve.includes("WfbTime.hour12") && twelve.includes("WfbTime.meridiem"));
  assert.throws(() => formatting.emit("{:%Q}", "", "time"), (e: Error) => e instanceof formatting.FormatError && e.message.includes("%H"));
  assert.throws(() => formatting.parse("no field here"), formatting.FormatError);
});

test("widest renderings and glyph sets", () => {
  assert.equal(formatting.widest("{:%H:%M}", null, "time"), "23:59");
  assert.equal(formatting.widest("{:%h:%M %p}", null, "time"), "23:59 AM");
  assert.equal(formatting.widest("{:d}", get("activity.steps")!, "number"), "88888");
  assert.equal(formatting.widest("{:d}", get("heart_rate.current")!, "number"), "888");
  assert.equal(formatting.digitsAreKnown(get("activity.steps")!), true);
  assert.equal(formatting.digitsAreKnown(null), false);
  const time = formatting.glyphs("{:%h:%M}", null, "time");
  for (const ch of "0123456789:") assert.ok(time.has(ch));
  assert.ok(formatting.glyphs("{:.1f}", null, "float").has("."));
  assert.ok(formatting.glyphs("{:d}", get("activity.steps")!, "number").has("-"));
  assert.equal(formatting.widest("{:.0f}%", get("system.battery")!, "float"), "888%");
  assert.equal(formatting.widest("{:.1f}k", get("activity.steps")!, "number"), "88888.8k");
  assert.equal(formatting.widest("{:.1f}k", get("activity.steps")!, "number", 0.001), "88.8k");
});

test("dates", () => {
  assert.equal(formatting.emit("{:%a %e %b}", "", "date"), 'date.day_of_week + " " + date.day.format("%d") + " " + date.month');
  assert.throws(() => formatting.parseTime("%M", formatting.DATE_CODES), formatting.FormatError);
  assert.throws(() => formatting.parseTime("%b", formatting.TIME_CODES), formatting.FormatError);
  assert.equal(formatting.isTimeSpec("{:.0f}%"), false);
  assert.equal(formatting.isTimeSpec("{:%H:%M}"), true);
  assert.equal(formatting.emit("{:.0f}%", "battery", "float"), 'battery.format("%.0f") + "%"');
  const glyphs = formatting.glyphs("{:%a %e %b}", null, "date");
  for (const ch of "JanFebMarAprMayJunJulAugSepOctNovDecMonTueWedThuFriSatSun") assert.ok(glyphs.has(ch), ch);
  // %m reads the short reader: under FORMAT_MEDIUM the month is a String
  assert.equal(formatting.emit("{:%m}", "", "date"), '(dateShort.month as Number).format("%02d")');
  assert.equal(formatting.emit("{:%m}", "", "date", { readers: { ...formatting.DEFAULT_READERS, date: "d", date_short: "ds" } }), '(ds.month as Number).format("%02d")');
  assert.equal(formatting.emit("{:%a %d %e %b %Y %y %%}", "", "date"),
    'date.day_of_week + " " + date.day.format("%02d") + " " + date.day.format("%d") + " " + date.month + " " + date.year.format("%04d") + " " + (date.year % 100).format("%02d") + " " + "%"');
  for (const [spec, extra] of [["{:%m}", ["date.weekday"]], ["{:%Y-%m-%d}", ["date.weekday"]], ["{:%a %e %b}", []], ["{:%Y}", []]] as const) {
    assert.deepEqual(formatting.extraPaths(spec, "date"), extra, spec);
  }
});

test("every time or date code is barrel-scanned as it calls", () => {
  for (const table of [formatting.TIME_CODES, formatting.DATE_CODES]) {
    for (const [name, code] of table) {
      const text = code.emit(formatting.DEFAULT_READERS);
      assert.equal(barrelModules([text]).has("WfbTime.mc"), text.includes("WfbTime."), name);
    }
  }
  assert.deepEqual(barrelModules([formatting.emit("{:%H:%M}", "clock", "time")]), new Set());
  assert.deepEqual(barrelModules([formatting.emit("{:%I:%M %p}", "clock", "time")]), new Set(["WfbTime.mc"]));
});

test("text around a clock or date field is kept", () => {
  assert.equal(formatting.emit("at {:%H:%M} UTC", "", "time"), '"at " + clock.hour.format("%02d") + ":" + clock.min.format("%02d") + " UTC"');
  assert.equal(r("at {:%H:%M} UTC", null, "time"), "at 10:09 UTC");
  assert.equal(formatting.widest("at {:%H:%M} UTC", null, "time"), "at 23:59 UTC");
  assert.equal(formatting.emit("{:%a}, {:%e %b}", "", "date"), 'date.day_of_week + ", " + date.day.format("%d") + " " + date.month');
  assert.equal(r("{:%a}, {:%e %b}", null, "date"), "Wed, 3 Sep");
  assert.equal(formatting.widest("{:%a}, {:%e %b}", null, "date"), "Wed, 30 Sep");
  const g = formatting.glyphs("at {:%H:%M} UTC", null, "time");
  for (const ch of "atUTC") assert.ok(g.has(ch));
});

const SPEC_TEXT = (value: string, spec: string): string => `format: 2
face:
  id: 7ed9e962-7b9d-4a2f-af79-639f4fb96641
  name: Fmt
build:
  targets: [fr955]
elements:
  reading:
    type: text
    text: "{${value}:${spec}}"
`;

test("a malformed spec is one format error, never a crash", () => {
  const [error, ...rest] = errors(SPEC_TEXT("time.hour", "zz"));
  assert.equal(rest.length, 0);
  assert.equal(error!.code, "format");
  assert.ok(error!.message.includes("'zz' is not a supported format spec"));
  const aod = SPEC_TEXT("time.hour", "02d").replace("  targets: [fr955]", "  targets: [fenix847mm]") + '    aod: {text: "{:zz}"}\n';
  assert.ok(errors(aod)[0]!.message.includes("'zz' is not a supported format spec"));
  for (const t of ["{time.hour}", "{time.hour:d}", "{time.hour:02d}", "{time.hour:.1f}", "a {time.hour} b"]) {
    assert.deepEqual(errors(SPEC_TEXT("time.hour", "d").replace('"{time.hour:d}"', `"${t}"`)), [], t);
  }
});

// -- durations --

test("duration rendering: the largest unit carries the total", () => {
  for (const [spec, seconds, want] of [
    ["{:%M:%S}", 3900, "65:00"], ["{:%H:%M:%S}", 3900, "01:05:00"], ["{:%-M:%S}", 270, "4:30"], ["{:%-H:%M:%S}", 13512, "3:45:12"],
    ["{:%-H:%M}", 2235 * 60, "37:15"], ["{:%H:%M}", 24120, "06:42"], ["{:%-M:%S}", -75, "-1:15"], ["T-{:%-M:%S} left", 75, "T-1:15 left"],
    ["{:%-S%%}", 7, "7%"],
  ] as const) assert.equal(r(spec, seconds, "number"), want, spec);
  assert.equal(r("{:%-M:%S}", 272.7, "float"), "4:32");
  assert.equal(r("{:%-M:%S}", -0.5, "float"), "0:00");
  for (const [is24, want] of [[true, "18:05 PM"], [false, "6:05 PM"]] as const) assert.equal(r("{:%h:%M %p}", 18 * 3600 + 300, "number", { "device.is_24_hour": is24 }), want);
  assert.equal(r("{:%H:%M}", 90000, "number"), "25:00");
  assert.equal(r("{:%l:%M %p}", 90000, "number"), "1:00 AM");
  assert.equal(r("{:%I:%M}", -3600, "number"), "01:00");
});

test("duration emission, widths and refusals", () => {
  assert.equal(formatting.emit("{:%-M:%S}", "pace", "float"),
    'WfbTime.durationSign(pace) + WfbTime.durationPart(pace, 60, 0).format("%d") + ":" + WfbTime.durationPart(pace, 1, 60).format("%02d")');
  const sunrise = formatting.emit("{:%h:%M}", "sunrise", "number");
  assert.ok(!sunrise.includes("durationSign") && sunrise.includes("WfbTime.displayHour(WfbTime.durationPart(sunrise, 3600, 24), settings.is24Hour)"));
  assert.deepEqual(formatting.extraPaths("{:%h:%M}", "number"), ["device.is_24_hour"]);
  assert.deepEqual(formatting.extraPaths("{:%l:%M %p}", "number"), []);
  assert.equal(formatting.widest("{:%-M:%S} {unit}", null, "float", 1.0, { unitWidest: "/km" }), "88:59 /km");
  assert.equal(formatting.widest("{:%h:%M %p}", null, "number"), "23:59 AM");
  assert.ok(formatting.glyphs("{:%-M:%S}", null, "number").has("-"));
  const tod = formatting.glyphs("{:%l:%M %p}", null, "number");
  assert.ok(!tod.has("-") && ["A", "M", "P"].every((c) => tod.has(c)));
  assert.throws(() => formatting.emit("{:%-Q}", "x", "number"), /unknown duration code %-Q/);
  assert.throws(() => formatting.emit("{:%-H}", "", "time"), /unknown time code %-H/);
});

const BASE = `
format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
elements:
`;

const reading = (value: string, fmt: string, extra = ""): string => BASE + `
  reading:
    type: text
    text: "${template(value, fmt)}"
    font: FONT_SMALL
    at: {anchor: center}
    color: color.fg
    absent: hide${extra}
`;

test("a duration face: what the watch reads and the preview draws", () => {
  const sunrise = method(view(reading("complication.sunrise", "{:%h:%M}")), "drawReading");
  assert.ok(sunrise.includes("WfbTime.durationPart(complicationSunrise, 3600, 24)") && !sunrise.includes("clock") && sunrise.includes("settings.is24Hour"));
  const recovery = reading("complication.recovery_time", "{:%-H:%M}");
  assert.ok(method(view(recovery), "drawReading").includes("(complicationRecoveryTime * 60)"));
  assert.equal(drawn(recovery, "reading", { "complication.recovery_time": 2235 }), "37:15");
  const written = method(view(reading("complication.recovery_time * 60", "{:%-H:%M}")), "drawReading");
  assert.ok(!written.includes("* 60 * 60") && !written.includes("60) * 60"));
  assert.ok(!method(view(reading("complication.recovery_time", "{:d} min")), "drawReading").includes("* 60"));
});

test("a pace from units", () => {
  const pace = reading("complication.race_pace_predictor_5k", "{:%-M:%S}{unit}", "\n    units: auto");
  for (const [sample, want] of [
    [{ "complication.race_pace_predictor_5k": 1000 / 270, "device.pace_units": 0 }, "4:30/km"],
    [{ "complication.race_pace_predictor_5k": 1609.344 / 434, "device.pace_units": 1 }, "7:14/mi"],
    [{ "complication.race_pace_predictor_5k": 0.0, "device.pace_units": 0 }, "0:00/km"],
  ] as const) assert.equal(drawn(pace, "reading", sample), want);
  const m = method(view(pace), "drawReading");
  assert.ok(m.includes("settings.paceUnits") && m.includes("complicationRacePacePredictor5k > 0"));
});

test("duration refusals in a face", () => {
  const [unknown] = errors(reading("complication.sunrise", "{:%a %M}"));
  assert.ok(unknown!.code === "format" && unknown!.message.includes("unknown duration code %a"));
  assert.ok(errors(reading("date.month", "{:%H}")).some((e) => e.message.includes("needs a time, date or number value")));
  const pattern = (fmt: string): string => BASE + `
  dial:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 4
    color: color.fg
    parts:
      - type: text
        text: "{copy * 21600:${fmt}}"
        at: {dy: -80%r}
`;
  const [twelve] = errors(pattern("%h"));
  assert.ok(twelve!.code === "format" && twelve!.message.includes("12/24-hour"));
  assert.deepEqual((face(pattern("%H")).elements[0] as any).parts[0].texts, ["00", "06", "12", "18"]);
});

test("a Boolean reading reads as the watch prints it: true and false, lower case", () => {
  const text = MINIMAL + `  t:\n    type: text\n    at: {anchor: center}\n    text: "{system.charging} {not system.charging}"\n    color: color.fg\n`;
  assert.equal(drawn(text, "t", { "system.charging": true }), "true false");
});
