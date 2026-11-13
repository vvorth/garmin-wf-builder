// A `text:` placeholder whose value is a string: a `?:` over string literals,
// a string source (`date.month`), or a mix. The literals are known at build
// time, so the baked font holds exactly their characters and the box is as
// wide as the widest of them; a string only the watch knows bakes every
// letter. Run on the fixture device, so it needs no Garmin file.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { load, resolveAll, selectDevices } from "../src/build.ts";
import { CATALOG } from "../src/catalog.ts";
import { DeviceDatabase } from "../src/devices/device.ts";
import { NodeDeviceFiles, REPO_ROOT } from "../src/devices/node.ts";
import { Bag } from "../src/diagnostics.ts";
import { generate } from "../src/emit/project.ts";
import { bakeFonts, glyphSet } from "../src/emit/resources.ts";
import { parse, stringValues } from "../src/expr.ts";
import * as formatting from "../src/formatting.ts";
import { NodeFontFiles } from "../src/fonts/node.ts";
import { PlacedText } from "../src/layout.ts";
import { installAssets, readFontFile } from "../src/node.ts";
import { previewOptions, render } from "../src/preview.ts";

installAssets();
process.env["WFB_NO_GARMIN_FONTS"] = "1";

const FIXTURE_DEVICES = join(REPO_ROOT, "ts", "test", "fixtures", "devices");
const db = new DeviceDatabase(NodeDeviceFiles.discover(FIXTURE_DEVICES, join(FIXTURE_DEVICES, "reference")), new NodeFontFiles());
// Beside the slice fixture, so `assets/OpenSans-Regular.ttf` is its real TTF.
const PATH = "ts/test/fixtures/slice/string-ternary.yaml";

function design(text: string, font = "{ source: assets/OpenSans-Regular.ttf, size: 20%r }"): string {
  return `format: 2
face: { id: 572b5279-ae01-4fd6-8605-f5cd7b3b84ab, name: Tern, version: 1.0.0 }
build: { targets: [wfbtest] }
resources:
  palette: { text: "#FFFFFF" }
elements:
  clock:
    type: text
    text: ${JSON.stringify(text)}
    font: ${font}
    at: { anchor: center }
    color: color.text
`;
}

function compile(text: string) {
  const bag = new Bag();
  bag.registerSource(PATH, text);
  const exists = (p: string): boolean => { try { readFileSync(join(REPO_ROOT, p)); return true; } catch { return false; } };
  const face = load(PATH, bag, text, exists);
  assert.ok(face !== null, bag.render());
  const devices = selectDevices(face, db, bag);
  const read = (p: string) => readFontFile(join(REPO_ROOT, p));
  const [resolved] = resolveAll(face, devices, bag, (f, d) => bakeFonts(f, d, read));
  const placed = resolved.get("wfbtest")!.items.find((p) => p.id === "clock") as PlacedText;
  return { face, devices, bag, resolved: resolved.get("wfbtest")!, placed, read };
}

/** Lit pixels of a 1x frame inside `placed`'s box. */
function litIn(resolved: ReturnType<typeof compile>["resolved"], placed: PlacedText, date: [number, number, number] | null = null): number {
  const frame = render(resolved, previewOptions({ scale: 1, mask_shape: false, date }));
  let lit = 0;
  const { x, y, width, height } = placed.box;
  for (let py = y; py < y + height; py++) {
    for (let px = x; px < x + width; px++) {
      const i = (py * frame.width + px) * 4;
      if (frame.data[i]! + frame.data[i + 1]! + frame.data[i + 2]! > 0) lit++;
    }
  }
  return lit;
}

const TERNARY = "{(date.weekday == 3 ? 'TUE' : 'XYZ')}";

test("a ternary of two string literals bakes both literals' characters and nothing else", () => {
  const { face, bag, resolved, placed } = compile(design(TERNARY));
  assert.equal(bag.errors.length, 0, bag.render());
  assert.equal(glyphSet(face).get("clock_font"), "ETUXYZ");
  // The box is as wide as the wider literal in this font, not five digits.
  const width = (s: string): number => resolved.fonts.get("clock_font")!.measure(s)[0];
  assert.notEqual(width("TUE"), width("XYZ"));
  assert.equal(placed.widest, width("TUE") > width("XYZ") ? "TUE" : "XYZ");
  assert.equal(placed.measured_width, Math.max(width("TUE"), width("XYZ")));
});

test("the preview draws the ternary's pick on both sides of it", () => {
  const { resolved, placed } = compile(design(TERNARY));
  // The preview's own sample is a Wednesday ("XYZ"); 2026-11-10 is a Tuesday ("TUE").
  assert.ok(litIn(resolved, placed) > 20, "nothing drawn for the default sample");
  assert.ok(litIn(resolved, placed, [2026, 11, 10]) > 20, "nothing drawn on a Tuesday");
});

test("the generated view draws the ternary itself, and the resource holds its letters", () => {
  const { face, devices, read } = compile(design(TERNARY));
  const files = new Map(generate(face, devices, read).files());
  const view = [...files].find(([name]) => name.endsWith("View.mc"))![1] as string;
  assert.match(view, /\(\(dateWeekday == 3\) \? "TUE" : "XYZ"\)\.toString\(\)/);
  const fnt = String(files.get("resources-wfbtest/fonts/clock_font.fnt"));
  const ids = [...fnt.matchAll(/^char id=(\d+)/gm)].map((m) => String.fromCodePoint(Number(m[1]))).join("");
  assert.equal(ids, "ETUXYZ");
  const layout = String(files.get("source-wfbtest/Layout.mc"));
  assert.doesNotMatch(layout, /88888/);
});

test("a declared glyphs: set missing one branch's letters is a missing-glyph error naming them", () => {
  const text = design(TERNARY, "font.f").replace("resources:\n", `resources:
  fonts:
    f: { source: assets/OpenSans-Regular.ttf, size: 20%r, glyphs: "TUE" }
`);
  const { bag } = compile(text);
  const found = bag.errors.filter((d) => d.code === "missing-glyph");
  assert.equal(found.length, 1, bag.render());
  assert.match(found[0]!.message, /'X', 'Y', 'Z'/);
});

test("a string source bakes letters, and a mixed ternary its literal too", () => {
  const month = compile(design("{date.month}"));
  assert.equal(month.bag.errors.length, 0, month.bag.render());
  const set = month.face && glyphSet(month.face).get("clock_font")!;
  for (const c of "SepWed") assert.ok(set.includes(c), `${c} not baked in ${set}`);
  assert.ok(litIn(month.resolved, month.placed) > 20, "nothing drawn for date.month");
  const mixed = compile(design("{(date.weekday == 3 ? date.month : '--')}"));
  const mixedSet = glyphSet(mixed.face).get("clock_font")!;
  assert.ok(mixedSet.includes("-") && mixedSet.includes("S"), mixedSet);
});

test("stringValues lists a ?: chain's literals once, in order, and flags a branch only the watch knows", () => {
  assert.deepEqual(stringValues(parse("x ? 'A' : y ? 'B' : 'A'")), { literals: ["A", "B"], open: false });
  assert.deepEqual(stringValues(parse("x ? date.month : '--'")), { literals: ["--"], open: true });
  assert.deepEqual(stringValues(parse("date.month")), { literals: [], open: true });
});

test("formatting measures a string value by its literals, and by the font when given one", () => {
  const strings = { literals: ["iii", "WW"], open: false };
  assert.equal(formatting.widest("{}", null, "string", 1.0, { strings }), "iii");
  assert.equal(formatting.widest("<{}>", null, "string", 1.0, { strings, measure: (s) => (s === "WW" ? 30 : 9) }), "<WW>");
  assert.deepEqual([...formatting.glyphs("{}", null, "string", 1.0, { strings })].sort(), ["W", "i"]);
  const open = formatting.glyphs("{}", CATALOG.get("date.month")!, "string");
  assert.ok(open.has("a") && open.has("Z") && open.has(" "));
});
