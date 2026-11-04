// `absent:` on an icon that follows data: `hide`, or `{icon:}` drawn instead
// while the reading is absent, on `icon: {for:}` and on `slot:`.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { ExprValue } from "../src/expr.ts";
import { CATALOG } from "../src/icons.ts";
import * as kinds from "../src/kinds/index.ts";
import { previewOptions, render } from "../src/preview.ts";
import { checked, errors, face, load, method, MINIMAL, resolved, view } from "./designs.ts";

const glyph = (name: string): string => CATALOG.get(name)!.codepoint;

/** One `glyph` icon element after MINIMAL, with these extra lines. */
const icon = (spec: string, extra = ""): string => `${MINIMAL}
  glyph:
    type: icon
    ${spec}
    size: 20%r
    at: {anchor: center}
    color: color.fg${extra ? `\n    ${extra}` : ""}
`;
const weather = (extra = ""): string => icon("icon: {for: weather.condition}", extra);

const slotted = (extra = ""): string => icon("slot: left", extra).replace("elements:", `config:
  slots:
    left:
      default: steps
      choices: [steps, current_weather]
elements:`);

/** The lit pixels of one preview frame at these readings. */
function lit(text: string, sample: [string, ExprValue][]): string {
  const frame = render(resolved(text), previewOptions({ scale: 1, sample: new Map(sample) }));
  return Array.from({ length: frame.width * frame.height }, (_, i) => (frame.data[i * 4]! > 128 ? "1" : "0")).join("");
}

/** The lit pixels of a slot design's frame, the slot showing `pick` with this complication reading. */
function litSlot(text: string, pick: string, reading: unknown): string {
  const frame = render(resolved(text), previewOptions({ scale: 1, picks: [["left", pick]], data_sample: new Map([[pick, reading]]) }));
  return Array.from({ length: frame.width * frame.height }, (_, i) => (frame.data[i * 4]! > 128 ? "1" : "0")).join("");
}

test("absent: hide on a weather icon brings the null guard back: nothing without a reading, rain at condition 3", () => {
  const text = weather("absent: hide");
  assert.deepEqual(checked(text).filter((d) => d.severity !== "note"), []);
  const element = face(text).walk().find((e) => e.id === "glyph")!;
  assert.equal((element as unknown as { absent: string }).absent, "hide");
  assert.equal(kinds.forElement(element).drawsWhileAbsent(element), false);
  const draw = method(view(text), "drawGlyph");
  assert.match(draw, /\/\/ absent: hide\n\s+if \(weatherCondition == null\) \{\n\s+return;/);
  assert.ok(!lit(text, [["weather.condition", null]]).includes("1"), "nothing drawn without a reading");
  const rain = lit(text, [["weather.condition", 3]]);
  assert.ok(rain.includes("1"));
  assert.equal(rain, lit(weather(), [["weather.condition", 3]]), "with a reading, the same rain as without 'absent:'");
  assert.notEqual(lit(weather(), [["weather.condition", null]]), lit(text, [["weather.condition", null]]),
    "without 'absent:' the plain glyph still draws");
});

test("absent: {icon:} draws that glyph without a reading, through the same font when the rule's set holds it", () => {
  const text = weather("absent: {icon: weather_cloudy_alert}");
  assert.deepEqual(checked(text).filter((d) => d.severity !== "note"), []);
  const draw = method(view(text), "drawGlyph");
  assert.match(draw, /\/\/ absent: \{icon: weather_cloudy_alert\} -- drawn instead while the reading is absent/);
  assert.ok(draw.includes(`(weatherCondition != null) ? IconGlyphs.glyph(IconGlyphs.weatherIcon(weatherCondition)) : "${glyph("weather_cloudy_alert")}"`));
  assert.doesNotMatch(draw, /if \(weatherCondition == null\)/, "no guard: the substitute draws instead");
  assert.match(draw, /var font = _fontIcon20pctrWeather;/, "weather_cloudy_alert is already a weather glyph: no font of its own");
  // Condition 33 is the one Garmin condition that maps to weather_cloudy_alert.
  const absent = lit(text, [["weather.condition", null]]);
  assert.equal(absent, lit(text, [["weather.condition", 33]]));
  assert.notEqual(absent, lit(text, [["weather.condition", 53]]), "and not the plain weather_unknown");
  assert.equal(lit(text, [["weather.condition", 3]]), lit(weather(), [["weather.condition", 3]]));
});

test("absent: {icon: {codepoint:}} takes any glyph; one outside the rule's set gets a font of its own", () => {
  // U+F0590 is weather_cloudy, conditions 2 and 20.
  const cloudy = weather("absent: {icon: {codepoint: \"U+F0590\"}}");
  assert.deepEqual(errors(cloudy), []);
  assert.equal(lit(cloudy, [["weather.condition", null]]), lit(cloudy, [["weather.condition", 2]]));

  const alert = weather("absent: {icon: {codepoint: \"u+f0026\"}}");
  assert.deepEqual(checked(alert).filter((d) => d.severity !== "note"), []);
  const draw = method(view(alert), "drawGlyph");
  assert.match(draw, /\/\/ absent: \{icon: U\+F0026\}/);
  assert.ok(draw.includes(`: "\u{F0026}"`));
  assert.match(draw, /var font = _fontIcon20pctrWeatherOrUf0026;/);
  const drawn = lit(alert, [["weather.condition", null]]);
  assert.ok(drawn.includes("1"));
  assert.notEqual(drawn, lit(weather(), [["weather.condition", null]]));
  const run = kinds.faceTextRuns(face(alert)).find(([e]) => e.id === "glyph")![1];
  assert.ok(run.icon!.glyphs.includes("\u{F0026}"), "the font holds the substitute");

  // A sibling without 'absent:' keeps the rule's own font, without the substitute.
  const both = alert.replace("elements:", "elements:\n  plain:\n    type: icon\n    icon: {for: weather.condition}\n    size: 20%r\n    at: {anchor: center}");
  const runs = new Map(kinds.faceTextRuns(face(both)).map(([e, r]) => [e.id, r]));
  assert.notEqual(runs.get("plain")!.font, runs.get("glyph")!.font);
  assert.ok(!runs.get("plain")!.icon!.glyphs.includes("\u{F0026}"));
});

test("a slot icon's absent: follows the pick's reading, not its type", () => {
  const text = slotted("absent: {icon: weather_cloudy_alert}");
  assert.deepEqual(checked(text).filter((d) => d.severity !== "note"), []);
  const draw = method(view(text), "drawGlyph");
  assert.match(draw, /\/\/ absent: \{icon: weather_cloudy_alert\} -- drawn instead while the pick has no reading\n\s+if \(iconGlyph != null && \(pulled == null \|\| pulled\.value == null\)\) \{\n\s+iconGlyph = "\u{F0F2F}";/u);
  assert.match(draw, /var iconFont = _fontIcon20pctrSlotLeft;/, "the weather choice already put the substitute in the slot's font");
  // The steps pick with no reading draws the glyph the weather pick draws at condition 33.
  const absent = litSlot(text, "steps", null);
  assert.equal(absent, litSlot(slotted(), "current_weather", 33));
  assert.notEqual(absent, litSlot(slotted(), "steps", null), "without 'absent:' the type's icon draws");
  assert.equal(litSlot(text, "steps", 5000), litSlot(slotted(), "steps", 5000), "with a reading, the type's icon");

  const hidden = slotted("absent: hide");
  assert.match(method(view(hidden), "drawGlyph"), /\/\/ absent: hide -- no icon while the pick has no reading\n\s+if \(iconGlyph != null && \(pulled == null \|\| pulled\.value == null\)\) \{\n\s+iconGlyph = null;/);
  assert.ok(!litSlot(hidden, "steps", null).includes("1"));
  assert.ok(litSlot(hidden, "steps", 5000).includes("1"));

  const own = slotted("absent: {icon: {codepoint: \"U+F0026\"}}");
  assert.match(method(view(own), "drawGlyph"), /var iconFont = _fontIcon20pctrSlotLeftOrUf0026;/);
  assert.ok(litSlot(own, "steps", null).includes("1"));
});

test("absent: on a fixed icon is an error: it has no reading", () => {
  for (const spec of ["icon: heart", "icon: {codepoint: \"U+F05F6\"}"]) {
    const found = errors(icon(spec, "absent: hide"));
    assert.equal(found.length, 1, spec);
    assert.equal(found[0]!.code, "when-absent");
    assert.equal(found[0]!.message, "glyph: 'absent:' needs an icon that follows data ('icon: {for:}' or 'slot:')");
  }
});

test("absent: {text:} or {value:} on an icon is refused, naming {icon:}", () => {
  for (const [absent, what] of [["{text: \"--\"}", "text"], ["{value: 1}", "a value"]] as const) {
    const found = errors(weather(`absent: ${absent}`));
    assert.equal(found.length, 1, absent);
    assert.equal(found[0]!.code, "schema");
    assert.equal(found[0]!.message,
      `elements.glyph.absent: an icon draws a glyph, not ${what}, while its reading is absent -- write 'absent: {icon: <name>}'`);
  }
  const bare = errors(weather("absent: weather_cloudy"));
  assert.equal(bare.length, 1);
  assert.equal(bare[0]!.message, "elements.glyph.absent: a substitute icon is written 'absent: {icon: weather_cloudy}', not a bare string");
  const codepoint = errors(weather("absent: {icon: \"U+F0026\"}"));
  assert.equal(codepoint.length, 1);
  assert.equal(codepoint[0]!.message, "elements.glyph.absent.icon: write 'icon: {codepoint: \"U+F0026\"}' -- a bare string is a catalogue name");
});

test("an unknown substitute is the error a bad icon: gets", () => {
  const [unknown, ...rest] = errors(weather("absent: {icon: weather_nope}"));
  assert.deepEqual(rest, []);
  assert.equal(unknown!.code, "icon");
  assert.equal(unknown!.message, errors(icon("icon: weather_nope"))[0]!.message);
  assert.match(unknown!.message, /unknown icon 'weather_nope'/);
  assert.ok(unknown!.notes.some((n) => n.includes("weather_cloudy_alert")), "the catalogue is listed");

  const [bad, ...more] = errors(slotted("absent: {icon: {codepoint: \"U+110000\"}}"));
  assert.deepEqual(more, []);
  assert.equal(bad!.code, "icon");
  assert.equal(bad!.message, "an icon codepoint is written 'U+XXXX', not 'U+110000'");
});

test("absent: on a source that is never absent has no effect, a note", () => {
  for (const source of ["system.battery", "device.notification_count"]) {
    const [, bag] = load(icon(`icon: {for: ${source}}`, "absent: hide"));
    assert.deepEqual(bag.errors, []);
    const notes = bag.items.filter((d) => d.code === "when-absent");
    assert.equal(notes.length, 1, source);
    assert.equal(notes[0]!.severity, "note");
    assert.equal(notes[0]!.message, `glyph: 'absent:' has no effect -- ${source} is never absent`);
  }
  // And nothing changes: no guard, no substitute.
  const text = icon("icon: {for: system.battery}", "absent: {icon: heart}");
  assert.doesNotMatch(method(view(text), "drawGlyph"), /!= null\) \?/);
  const run = kinds.faceTextRuns(face(text)).find(([e]) => e.id === "glyph")![1];
  assert.ok(!run.icon!.glyphs.includes(glyph("heart")), "the font is the rule's own");
  assert.doesNotMatch(run.font, /_or_/);
});
