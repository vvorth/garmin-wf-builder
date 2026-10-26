// Level icons: an icon that fills with a 0-100 reading, on a slot and on `icon: {for:}`;
// and Body Battery, the other glyph drawn at bake time.
import assert from "node:assert/strict";
import { test } from "node:test";
import { WholeFloat } from "../src/edit/yaml.ts";
import { ICON_FONT } from "../src/emit/resources.ts";
import { bake } from "../src/fonts/bake.ts";
import { BODY_BATTERY_SEGMENTS_FROM_PX, SOLAR_ARCS_FROM_PX } from "../src/fonts/composite.ts";
import { CATALOG, fontHas, LEVEL_ICONS, levelBand, levelIconName } from "../src/icons.ts";
import { slotSampleGlyph } from "../src/kinds/data.ts";
import { bakeSize } from "../src/emit/resources.ts";
import { readFontFile } from "../src/node.ts";
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

/** The square's eight symmetries, as maps of a pixel in an `n`-wide tile. */
const SYMMETRIES: ((x: number, y: number, n: number) => [number, number])[] = [
  (x, y) => [x, y], (x, y, n) => [n - 1 - y, x], (x, y, n) => [n - 1 - x, n - 1 - y], (x, y, n) => [y, n - 1 - x],
  (x, y, n) => [n - 1 - x, y], (x, y, n) => [x, n - 1 - y], (x, y) => [y, x], (x, y, n) => [n - 1 - y, n - 1 - x],
];

/** Each solar step baked at nominal `size`: its tile's pixels (1 for ink), and the tile's box. */
function solarTiles(size: number): { across: number; pixels: Map<string, number[]>; boxes: Map<string, number[]> } {
  const steps = LEVEL_ICONS.get("solar")!.steps;
  const font = bake(readFontFile(ICON_FONT), { name: "solar", size, glyphs: steps.map(glyph).join("") });
  const sheet = font.sheet!, pixels = new Map<string, number[]>(), boxes = new Map<string, number[]>();
  for (const name of steps) {
    const g = font.glyphs.get(glyph(name))!;
    assert.equal(g.width, g.height, `${name} at ${size}: a square tile`);
    pixels.set(name, Array.from({ length: g.width * g.height }, (_, i) => (sheet.bytes[(g.y + Math.floor(i / g.width)) * sheet.width + g.x + (i % g.width)]! ? 1 : 0)));
    boxes.set(name, [g.width, g.height, g.xoffset, g.yoffset, g.xadvance]);
  }
  return { across: font.glyphs.get(glyph(steps[0]!))!.width, pixels, boxes };
}

/** The ink outside `share` of the tile's radius: the arcs or the teeth' tips, not the disc. */
const rim = (pixels: number[], n: number, share: number): number[] =>
  pixels.map((v, i) => (v && Math.hypot((i % n) + 0.5 - n / 2, Math.floor(i / n) + 0.5 - n / 2) > (share * n) / 2 ? 1 : 0));

test("each solar step is a carved disc in the same square, every arc or tooth the same pixels", () => {
  const steps = LEVEL_ICONS.get("solar")!.steps;
  for (const name of steps) assert.ok(fontHas(glyph(name)), `${name} is in the icon font, composed`);
  const tiers = new Set<string>();
  for (let size = 12; size <= 52; size++) {
    const { across: n, pixels, boxes } = solarTiles(size);
    for (const name of steps) assert.deepEqual(boxes.get(name), boxes.get(steps[0]!), `${size}: ${name} has step 0's box`);
    const full = pixels.get(steps[8]!)!;
    // The bolt is cut out of the disc's middle.
    assert.ok(rim(full, n, 0).some((v, i) => !v && Math.hypot((i % n) + 0.5 - n / 2, Math.floor(i / n) + 0.5 - n / 2) < n / 5), `${size}: the bolt is carved`);
    const outer = rim(full, n, 0.74);
    for (const map of SYMMETRIES) {
      const moved = new Array<number>(n * n).fill(0);
      outer.forEach((v, i) => { const [x, y] = map(i % n, Math.floor(i / n), n); moved[y * n + x] = v; });
      assert.deepEqual(moved, outer, `${size}: the rim looks the same flipped or turned`);
    }
    if (n < SOLAR_ARCS_FROM_PX) {
      tiers.add("star");
      for (const name of steps) assert.deepEqual(pixels.get(name), full, `${size} (${n}px): ${name} is the static star`);
      assert.ok(outer.some((v) => v), `${size}: the star has teeth`);
    } else {
      tiers.add("arcs");
      const one = rim(pixels.get(steps[1]!)!, n, 0.74);
      const perArc = one.filter((v) => v).length;
      assert.ok(perArc > 0, `${size}: one arc is lit`);
      steps.forEach((name, k) => assert.equal(rim(pixels.get(name)!, n, 0.74).filter((v) => v).length, k * perArc, `${size}: ${name} lights ${k} equal arcs`));
      // The first arc is clockwise from 12 o'clock: the upper right quarter.
      one.forEach((v, i) => { if (v) assert.ok(i % n >= n / 2 && Math.floor(i / n) < n / 2, `${size}: the first arc is upper right`); });
    }
  }
  assert.deepEqual([...tiers].sort(), ["arcs", "star"]);
});

test("a fixed solar_level_8 behind the live icon is its track, pixel for pixel", () => {
  const track = MINIMAL + `
  glyph:
    type: icon
    icon: solar_level_8
    size: 20%r
    at: {anchor: center}
    color: color.fg
`;
  assert.deepEqual(errors(track), []);
  const live = (value: number): string => lit(fixed("complication.solar_input"), [["complication.solar_input", value]]);
  assert.notEqual(live(100), live(0), "big enough to draw arcs");
  assert.equal(lit(track, []), live(100));
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

test("a battery's five bands are 20 wide: 0-19 empty, 80-100 full", () => {
  const battery = LEVEL_ICONS.get("battery")!;
  assert.deepEqual([0, 19, 20, 39, 40, 79, 80, 100].map((v) => levelIconName(battery, v)),
    ["battery_level_0", "battery_level_0", "battery_level_1", "battery_level_1", "battery_level_2", "battery_level_3", "battery_level_4", "battery_level_4"]);
  assert.equal(levelIconName(battery, new WholeFloat(68)), "battery_level_3", "system.battery is a Float");
  assert.equal(levelIconName(battery, null), "battery");
  assert.equal(glyph("battery_level_0"), "\u{F244}");
  assert.equal(glyph("battery_level_4"), "\u{F240}");
});

test("a battery pick's icon fills with the charge", () => {
  const text = slotted("[steps, battery]");
  const slot = face(text).config_data.get("left")!;
  assert.equal(slotSampleGlyph(slot, "battery", 19), glyph("battery_level_0"));
  assert.equal(slotSampleGlyph(slot, "battery", 20), glyph("battery_level_1"));
  assert.equal(slotSampleGlyph(slot, "battery", null), glyph("battery"));
  assert.match(method(view(text), "iconForGlyph"),
    /COMPLICATION_TYPE_BATTERY: return \(value instanceof Lang.Number\) \? IconGlyphs.batteryLevel\(value\) : "battery";/);
  assert.match(generated(text).get("source/IconGlyphs.mc")!, /var band = \(value \* 5 \/ 100\)\.toNumber\(\);/);
});

test("icon: {for: system.battery} and {for: complication.battery} share one font and fill with the charge", () => {
  const text = `${fixed("system.battery")}
  other:
    type: icon
    icon: {for: complication.battery}
    size: 20%r
    at: {anchor: center, dy: 30%}
    color: color.fg
`;
  assert.deepEqual(errors(text), []);
  const v = view(text);
  assert.match(method(v, "drawGlyph"), /IconGlyphs.glyph\(IconGlyphs.batteryLevel\(systemBattery\)\)/);
  assert.match(method(v, "drawOther"), /IconGlyphs.glyph\(IconGlyphs.batteryLevel\(complicationBattery\)\)/);
  const r = resolved(text);
  const keys = r.items.filter((p) => p.id === "glyph" || p.id === "other").map((p) => (p as unknown as { font_key: string }).font_key);
  assert.equal(new Set(keys).size, 1, keys.join(", "));
  assert.notEqual(lit(fixed("system.battery"), [["system.battery", 19]]), lit(fixed("system.battery"), [["system.battery", 20]]));
});

test("icon: {for:} still refuses arithmetic over a level source", () => {
  const found = errors(fixed("complication.solar_input / 2"));
  assert.equal(found.length, 1);
  assert.match(found[0]!.message, /complication.battery, complication.solar_input, system.battery, weather.condition,/);
});

/** The 4-connected pieces of a `w`-wide tile's ink, each as its pixel indices. */
function pieces(pixels: readonly number[], w: number): number[][] {
  const seen = new Set<number>(), out: number[][] = [];
  pixels.forEach((v, start) => {
    if (!v || seen.has(start)) return;
    const piece: number[] = [], todo = [start];
    seen.add(start);
    while (todo.length > 0) {
      const i = todo.pop()!;
      piece.push(i);
      const [x, y] = [i % w, Math.floor(i / w)];
      for (const [nx, ny] of [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]] as const) {
        const j = ny * w + nx;
        if (nx >= 0 && nx < w && ny >= 0 && j < pixels.length && pixels[j] && !seen.has(j)) { seen.add(j); todo.push(j); }
      }
    }
    out.push(piece);
  });
  return out;
}

test("body_battery is a head and shoulders in a gauge that thickens clockwise, in segments once they read", () => {
  const ch = CATALOG.get("body_battery")!.codepoint, source = readFontFile(ICON_FONT);
  assert.ok(fontHas(ch), "in the icon font, composed");
  const tiers = new Set<string>();
  for (let px = 10; px <= 48; px++) {
    // Baked as a slot or a `{for:}` icon bakes it: its longer side `px`.
    const font = bake(source, { name: "bb", size: bakeSize(source, ch, px, true), glyphs: ch });
    const g = font.glyphs.get(ch)!, w = g.width;
    const pixels = Array.from({ length: w * g.height }, (_, i) => (font.sheet!.bytes[(g.y + Math.floor(i / w)) * font.sheet!.width + g.x + (i % w)]! ? 1 : 0));
    const found = pieces(pixels, w);
    const segmented = w >= BODY_BATTERY_SEGMENTS_FROM_PX;
    tiers.add(segmented ? "segments" : "band");
    // The head, the shoulders, and the gauge's band or its four segments, none touching another.
    assert.equal(found.length, segmented ? 6 : 3, `${px} (${w}px across): ${found.length} pieces`);
    if (!segmented) continue;
    // The gauge's first segment holds the lowest-left ink, its last the highest-right; the last is the heavier.
    const score = (i: number, sx: number, sy: number): number => sx * (i % w) + sy * Math.floor(i / w);
    const extreme = (sx: number, sy: number): number[] => found.find((p) => p.includes(pixels.reduce((best, v, i) => (v && score(i, sx, sy) > score(best, sx, sy) ? i : best), pixels.indexOf(1))))!;
    const first = extreme(-1, 1), last = extreme(1, -1);
    assert.ok(last.length > first.length, `${px}: the last segment (${last.length}) is heavier than the first (${first.length})`);
  }
  assert.deepEqual([...tiers].sort(), ["band", "segments"]);
});
