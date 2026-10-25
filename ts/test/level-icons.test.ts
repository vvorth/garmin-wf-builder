// Level icons: an icon that fills with a 0-100 reading, on a slot and on `icon: {for:}`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { CATALOG, LEVEL_ICONS, levelBand, levelIconName } from "../src/icons.ts";
import { slotSampleGlyph } from "../src/kinds/data.ts";
import { previewOptions, render } from "../src/preview.ts";
import { errors, face, generated, method, MINIMAL, resolved, view } from "./designs.ts";

const glyph = (name: string): string => CATALOG.get(name)!.codepoint;

const slotted = (choices: string): string => `${MINIMAL.replace("elements:", `config:
  slots:
    left:
      default: steps
      choices: ${choices}
elements:`)}
  glyph:
    type: icon
    slot: left
    size: 20%r
    at: {anchor: center}
    color: color.fg
`;

const fixed = (source: string): string => `${MINIMAL}
  glyph:
    type: icon
    icon: {for: ${source}}
    size: 20%r
    at: {anchor: center}
    color: color.fg
`;

/** The lit pixels of one preview frame at these readings. */
function lit(text: string, sample: [string, number][], pick: string | null = null): string {
  const frame = render(resolved(text), previewOptions({ scale: 1, sample: new Map(sample), picks: pick !== null ? [["left", pick]] : [] }));
  return Array.from({ length: frame.width * frame.height }, (_, i) => (frame.data[i * 4]! > 128 ? "1" : "0")).join("");
}

test("a level band is the reading truncated into equal bands, 100 in the top one", () => {
  // Nine bands of 11.1: 11 is still the first, 12 the second.
  assert.deepEqual([0, 11, 12, 50, 88, 89, 99, 100].map((v) => levelBand(v, 9)), [0, 0, 1, 4, 7, 8, 8, 8]);
  assert.equal(levelBand(-3, 9), 0, "clamped below");
  assert.equal(levelBand(140, 9), 8, "clamped above");
  const solar = LEVEL_ICONS.get("solar")!;
  assert.equal(levelIconName(solar, null), "solar", "no reading: the plain icon");
  assert.equal(levelIconName(solar, 0), "solar_level_0");
  assert.equal(levelIconName(solar, 100), "solar_level_8");
});

test("a solar input pick's icon fills with the reading, unless the author chose one", () => {
  const text = slotted("[steps, solar_input]");
  const slot = face(text).config_data.get("left")!;
  assert.equal(slotSampleGlyph(slot, "solar_input", 0), glyph("solar_level_0"));
  assert.equal(slotSampleGlyph(slot, "solar_input", 50), glyph("solar_level_4"));
  assert.equal(slotSampleGlyph(slot, "solar_input", 100), glyph("solar_level_8"));
  assert.equal(slotSampleGlyph(slot, "solar_input", null), glyph("solar"), "no reading: the plain sun");
  assert.match(method(view(text), "iconForGlyph"),
    /SOLAR_INPUT: return \(value instanceof Lang.Number\) \? IconGlyphs.solarLevel\(value\) : "solar";/);
  const glyphs = generated(text).get("source/IconGlyphs.mc")!;
  assert.match(glyphs, /function solarLevel\(value as Lang.Numeric or Null\) as String/);
  assert.match(glyphs, /var band = \(value \* 9 \/ 100\)\.toNumber\(\);/);
  for (const name of LEVEL_ICONS.get("solar")!.steps) assert.match(glyphs, new RegExp(`case "${name}": return`));
  assert.notEqual(lit(text, [], "solar_input"), lit(text, [], "steps"));

  const authored = slotted("[steps, { type: solar_input, icon: { codepoint: \"U+F04CE\" } }]");
  assert.equal(slotSampleGlyph(face(authored).config_data.get("left")!, "solar_input", 0), "\u{F04CE}");
  assert.match(method(view(authored), "iconForGlyph"), /SOLAR_INPUT: return "U\+F04CE";/);
  assert.doesNotMatch(generated(authored).get("source/IconGlyphs.mc")!, /solarLevel/, "no level function nobody calls");
});

test("a slot without a solar choice has no level function", () => {
  assert.doesNotMatch(generated(slotted("[steps, stress]")).get("source/IconGlyphs.mc")!, /Level\(/);
});

test("icon: {for: complication.solar_input} fills with the reading and draws the plain sun without one", () => {
  const text = fixed("complication.solar_input");
  assert.deepEqual(errors(text), []);
  const draw = method(view(text), "drawGlyph");
  assert.match(draw, /IconGlyphs.glyph\(IconGlyphs.solarLevel\(complicationSolarInput\)\)/);
  assert.doesNotMatch(draw, /complicationSolarInput == null/, "no reading draws the plain icon, not nothing");
  const empty = lit(text, [["complication.solar_input", 0]]), half = lit(text, [["complication.solar_input", 50]]);
  const full = lit(text, [["complication.solar_input", 100]]), none = lit(text, []);
  assert.notEqual(empty, half);
  assert.notEqual(half, full);
  assert.notEqual(none, empty);
  assert.ok(none.includes("1"), "the plain sun is drawn");
});

test("icon: {for:} still refuses arithmetic over a level source", () => {
  const found = errors(fixed("complication.solar_input / 2"));
  assert.equal(found.length, 1);
  assert.match(found[0]!.message, /complication.solar_input, weather.condition/);
});
