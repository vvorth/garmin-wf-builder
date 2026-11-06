// A baked `fallback:` on a `face:` font: the format, the per-device mode,
// the diagnostics, the one shared view over a per-device Layout, the bake
// and the preview, over the three devices the example targets:
// fenix8solar47mm publishes BionicSemiBold (vector), fr955 has
// getVectorFont but not that face (fallback), fr255 has no getVectorFont
// at all (fallback).
import assert from "node:assert/strict";
import { test } from "node:test";
import { vectorFontMode } from "../src/availability.ts";
import { bakeFonts, glyphSet } from "../src/emit/resources.ts";
import { discPerimeterOffsets } from "../src/ir/model.ts";
import { HIDDEN_BY_FONT, PlacedText } from "../src/layout.ts";
import { previewOptions, render } from "../src/preview.ts";
import type { Image } from "../src/raster/pillow.ts";
import { readFontFile } from "../src/node.ts";
import { checked, db, divergences, drawn, errors, face, generated, load, resolved, view } from "./designs.ts";
import { REPO_ROOT } from "../src/devices/node.ts";
import { join } from "node:path";

const TTF = "examples/features/vector-text/assets/ChivoMono-Bold.ttf";
const read = (p: string) => readFontFile(join(REPO_ROOT, p));

/** A face in `font.dial` (`font` its YAML body), an upright `brand` and, unless `curved` is null, a curved `rim` with that `unsupported:`. */
function design(font: string, { targets = "fenix8solar47mm, fr955, fr255", curved = "hide" as string | null, outline = false } = {}): string {
  return `
format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [${targets}]
resources:
  fonts:
    dial:
${font}
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
    red: "#FF0000"
elements:
  background: { type: rectangle, at: { anchor: center }, size: { width: 100%, height: 100% }, color: color.bg }
  brand:
    type: text
    text: "BRAND"
    font: font.dial
    at: { anchor: center, dy: -30%r }
    color: color.fg${outline ? "\n    outline: { color: color.red, width: 2 }" : ""}
${curved === null ? "" : `  rim:
    type: text
    text: "RIM"
    font: font.dial
    at: { anchor: center }
    color: color.fg
    curve: { style: radial, angle: 180deg, radius: 70%r, direction: counter_clockwise }
    unsupported: ${curved}
    lint: { allow: [font-unavailable], reason: test }
`}`;
}

const FALLBACK = `      face: BionicSemiBold
      size: 12%r
      fallback:
        source: ${TTF}
`;

// -- the format ------------------------------------------------------------

test("fallback: on a baked font is a build error at its own key", () => {
  const found = errors(design(`      source: ${TTF}\n      size: 12%r\n      fallback: { source: ${TTF} }\n`));
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  assert.equal(found[0]!.code, "font");
  assert.match(found[0]!.message, /font 'dial': 'fallback:' is not accepted on a baked font/);
  assert.equal(found[0]!.span!.line, 13);
  assert.match(found[0]!.notes.join("\n"), /never unsupported/);
});

test("a missing fallback source is the baked font's error, at the fallback's own source line", () => {
  const found = errors(design(`      face: BionicSemiBold\n      size: 12%r\n      fallback:\n        source: assets/nowhere.ttf\n`));
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  assert.equal(found[0]!.code, "font");
  assert.equal(found[0]!.message, "font 'dial' 'fallback:': source file not found: assets/nowhere.ttf");
  assert.equal(found[0]!.span!.line, 14);
});

test("align: without monospace: inside a fallback is refused as on a baked font", () => {
  const found = errors(design(FALLBACK + "        align: left\n"));
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  assert.equal(found[0]!.message, "font 'dial' 'fallback:': 'align' needs 'monospace: true'");
  assert.equal(found[0]!.span!.line, 15);
});

test("face:, unsupported: and fallback: inside a fallback are schema errors", () => {
  for (const key of ["face: RobotoBlack", "unsupported: hide", `fallback: { source: ${TTF} }`]) {
    const found = errors(design(FALLBACK + `        ${key}\n`));
    assert.ok(found.length > 0 && found.every((d) => d.code === "schema"), `${key}: ${found.map((d) => `${d.code} ${d.message}`).join("\n")}`);
  }
});

test("a fallback bakes at the entry's size unless it writes its own, and keeps its baking keys", () => {
  const plain = face(design(FALLBACK)).fonts.get("dial")!;
  assert.ok(plain.isVector && plain.fallback !== null);
  assert.equal(String(plain.fallback.size), String(plain.size));
  assert.equal(plain.fallback.name, "dial");
  assert.equal(plain.fallback.source, TTF);
  const own = face(design(FALLBACK + "        size: 9px\n        monospace: true\n        align: left\n        glyphs: \"BRAND\"\n")).fonts.get("dial")!.fallback!;
  assert.equal(String(own.size), "9px");
  assert.deepEqual([own.monospace, own.align, own.glyphs], [true, "left", "BRAND"]);
});

test("an inline font's fallback becomes its entry's", () => {
  const text = design(FALLBACK, { curved: null }).replace("    font: font.dial\n", `    font: { face: BionicSemiBold, size: 12%r, fallback: { source: ${TTF} } }\n`);
  const f = face(text);
  assert.equal(f.fonts.get("brand_font")!.fallback!.source, TTF);
});

// -- the mode, per font per device ------------------------------------------

test("each device draws a face: font from the face, its fallback, or nothing", () => {
  const withFallback = face(design(FALLBACK)).fonts.get("dial")!;
  const without = face(design("      face: BionicSemiBold\n      size: 12%r\n      unsupported: hide\n")).fonts.get("dial")!;
  const modes = (spec: typeof without) => ["fenix8solar47mm", "fr955", "fr255"].map((id) => vectorFontMode(spec, db.get(id)));
  assert.deepEqual(modes(withFallback), ["vector", "fallback", "fallback"]);
  assert.deepEqual(modes(without), ["vector", "none", "none"]);
});

test("on a fallback device an upright text draws and measures from the sheet, a curved one is hidden", () => {
  const text = design(FALLBACK);
  for (const id of ["fr955", "fr255"]) {
    const r = resolved(text, id);
    const brand = r.items.find((p) => p.id === "brand") as PlacedText;
    assert.ok(brand.font.available && brand.font.fallback && brand.font.is_vector, id);
    assert.ok(r.fonts.has("dial"), id);
    assert.equal(brand.measured_width, r.fonts.get("dial")!.measure("BRAND")[0], id);
    assert.equal(brand.width_is_estimated, false, id);
    assert.equal(r.hidden.get("rim"), HIDDEN_BY_FONT, id);
    assert.equal(r.hidden.has("brand"), false, id);
  }
  const fenix = resolved(text, "fenix8solar47mm");
  const brand = fenix.items.find((p) => p.id === "brand") as PlacedText;
  assert.ok(brand.font.available && !brand.font.fallback);
  assert.equal(brand.font.face, "BionicSemiBold");
  assert.equal(fenix.fonts.has("dial"), false);
  assert.equal(fenix.hidden.size, 0);
});

// -- diagnostics ---------------------------------------------------------------

test("a curved text the fallback cannot draw fails under unsupported: error, naming the curve", () => {
  const found = checked(design(FALLBACK, { targets: "fr255", curved: "error" })).filter((d) => d.severity === "error");
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  assert.equal(found[0]!.code, "font-unavailable");
  assert.match(found[0]!.message, /rim: 'font: font.dial' has no usable face on fr255/);
  const notes = found[0]!.notes.join("\n");
  assert.match(notes, /fr255: has no 'Graphics.getVectorFont' at all .*; the baked 'fallback:' it draws instead cannot curve/);
  assert.match(notes, /'font.dial' has a 'fallback:', but a baked sheet draws upright text only/);
  // the upright text is not an error anywhere
  assert.equal(checked(design(FALLBACK, { targets: "fr255", curved: null })).filter((d) => d.severity === "error").length, 0);
});

test("font-unavailable offers fallback: to a font that has none, and says it cannot curve", () => {
  const bare = "      face: BionicSemiBold\n      size: 12%r\n";
  const upright = checked(design(bare, { targets: "fr255", curved: null })).find((d) => d.code === "font-unavailable")!;
  assert.match(upright.notes.join("\n"), /give 'font.dial' a 'fallback: \{source: \.\.\.\}'/);
  const curved = checked(design(bare + "      unsupported: hide\n", { targets: "fr255" }).replace("unsupported: hide\n    lint", "unsupported: error\n    lint"))
    .find((d) => d.code === "font-unavailable" && d.message.startsWith("rim"))!;
  assert.match(curved.notes.join("\n"), /a 'fallback:' on 'font.dial' would not draw this one/);
});

test("note[font-fallback]: one per font, naming the devices that bake its sheet", () => {
  const notes = checked(design(FALLBACK)).filter((d) => d.code === "font-fallback");
  assert.equal(notes.length, 1);
  assert.equal(notes[0]!.severity, "note");
  assert.match(notes[0]!.message, /font 'dial': drawn from its baked 'fallback:' on fr255, fr955 -- no usable face there/);
  assert.match(notes[0]!.confidence!, /^exact/);
  assert.equal(checked(design(FALLBACK, { targets: "fenix8solar47mm" })).filter((d) => d.code === "font-fallback").length, 0);
});

test("font-fallback is a code lint: {allow:} refuses as unsuppressible", () => {
  const text = design(FALLBACK).replace("allow: [font-unavailable]", "allow: [font-unavailable, font-fallback]");
  const [f, bag] = load(text);
  assert.ok(f !== null);
  const all = checked(text).filter((d) => d.code === "lint-allow");
  assert.equal(all.length, 1, bag.render());
  assert.match(all[0]!.message, /'font-fallback' is a real diagnostic code, but it is deliberately not suppressible/);
});

// -- the bake ------------------------------------------------------------------

test("the sheet is baked only where it draws, with the upright texts' characters", () => {
  const f = face(design(FALLBACK));
  assert.equal(glyphSet(f).get("dial"), "ABDNR");
  for (const [id, baked] of [["fenix8solar47mm", false], ["fr955", true], ["fr255", true]] as const) {
    assert.equal(bakeFonts(f, db.get(id), read).has("dial"), baked, id);
  }
  const files = generated(design(FALLBACK));
  assert.equal(files.has("resources-fenix8solar47mm/fonts/fonts.xml"), false);
  for (const id of ["fr955", "fr255"]) {
    const xml = files.get(`resources-${id}/fonts/fonts.xml`)!;
    assert.match(xml, /<!-- dial: ChivoMono-Bold.ttf at \d+px, 5 glyphs -->/);
    assert.match(xml, /<font id="FontDial" filename="dial.fnt" filter="ABDNR" antialias="false" \/>/);
  }
});

test("a fallback font's ring is stamped, with no ring sheet", () => {
  const text = design(FALLBACK, { curved: null, outline: true });
  const f = face(text);
  assert.deepEqual([...bakeFonts(f, db.get("fr255"), read).keys()], ["dial"]);
  const draw = view(text).split("function drawBrand")[1]!.split("\n    }")[0]!;
  assert.equal((draw.match(/dc\.drawText/g) ?? []).length, discPerimeterOffsets(2).length + 1); // the ring's stamps, then the text
  assert.doesNotMatch(draw, /Ring|ring/);
});

// -- the generated sources -----------------------------------------------------

test("one shared view: a FontType field and a VectorFont field, constructed or loaded through Layout", () => {
  const text = design(FALLBACK);
  assert.deepEqual(divergences(text), []);
  const v = view(text);
  assert.match(v, /private var _fontDial as Graphics\.FontType\?;/);
  assert.match(v, /private var _fontDialVector as Graphics\.VectorFont\?;/);
  assert.match(v, /if \(Layout\.FONT_DIAL_AVAILABLE && \(Graphics has :getVectorFont\)\) \{\n\s+_fontDialVector = Graphics\.getVectorFont\(\{:face => Layout\.FONT_DIAL_FACE, :size => Layout\.FONT_DIAL_SIZE\}\);\n\s+_fontDial = _fontDialVector;\n\s+\}\n\s+else \{\n(\s+\/\/.*\n)?\s+_fontDial = Layout\.fontDialFallback\(\);/);
  assert.doesNotMatch(v, /Rez\.Fonts/);
  const brand = v.split("function drawBrand")[1]!.split("\n    }")[0]!;
  assert.match(brand, /var font = _fontDial;\n\s+if \(font != null\) \{/);
  const rim = v.split("function drawRim")[1]!.split("\n    }")[0]!;
  assert.match(rim, /var font = _fontDialVector;\n\s+if \(font != null\) \{/);
  assert.match(rim, /dc\.drawRadialText\(/);
});

test("each device's Layout loads the sheet where it draws it and returns null where it builds the face", () => {
  const files = generated(design(FALLBACK));
  const fenix = files.get("source-fenix8solar47mm/Layout.mc")!;
  assert.match(fenix, /const FONT_DIAL_AVAILABLE as Boolean = true;/);
  assert.match(fenix, /function fontDialFallback\(\) as Graphics\.FontType\? \{\n\s+return null;\n\s+\}/);
  assert.doesNotMatch(fenix, /Rez\.Fonts/);
  for (const id of ["fr955", "fr255"]) {
    const layout = files.get(`source-${id}/Layout.mc`)!;
    assert.match(layout, /const FONT_DIAL_AVAILABLE as Boolean = false;/, id);
    assert.match(layout, /function fontDialFallback\(\) as Graphics\.FontType\? \{\n\s+return WatchUi\.loadResource\(Rez\.Fonts\.FontDial\) as WatchUi\.FontResource;\n\s+\}/, id);
    assert.match(layout, /import Toybox\.WatchUi;/, id);
  }
});

test("with no device drawing the fallback, nothing loads it, and an upright-only font has one field", () => {
  const vectorOnly = view(design(FALLBACK, { targets: "fenix8solar47mm" }));
  assert.match(vectorOnly, /_fontDialVector = Graphics\.getVectorFont/);
  assert.doesNotMatch(vectorOnly, /Fallback\(\)|AVAILABLE/);
  const upright = view(design(FALLBACK, { curved: null }));
  assert.match(upright, /private var _fontDial as Graphics\.FontType\?;/);
  assert.doesNotMatch(upright, /_fontDialVector/);
  assert.match(upright, /_fontDial = Graphics\.getVectorFont\(/);
});

test("a pattern's curved and upright parts in one fallback font read the two fields", () => {
  const text = design(FALLBACK, { curved: null }).replace("  brand:\n", `  ring:
    type: pattern
    pattern: radial
    at: { anchor: center }
    count: 4
    color: color.fg
    parts:
      up: { type: text, text: "U", font: font.dial, at: { dy: -60%r } }
      bent: { type: text, text: "B", font: font.dial, at: { dy: -80%r }, curve: { style: angled, angle: 0deg }, unsupported: hide }
    lint: { allow: [font-unavailable], reason: test }
  brand:
`);
  assert.deepEqual(divergences(text), []);
  const ring = view(text).split("function drawRing")[1]!.split("\n    }")[0]!;
  assert.match(ring, /var font0 = _fontDial;/);
  assert.match(ring, /var font1 = _fontDialVector;/);
  assert.match(ring, /dc\.drawAngledText\([^;]*font1/);
});

// -- the preview -----------------------------------------------------------------

const frame = (text: string, id: string): Image => render(resolved(text, id), previewOptions({ scale: 1, quantise: false, mask_shape: false }));
const crop = (im: Image, box: { x: number; y: number; width: number; height: number }): number[] => {
  const out: number[] = [];
  for (let y = box.y; y < box.y + box.height; y++) for (let x = box.x; x < box.x + box.width; x++) out.push(im.data[(y * im.width + x) * 4]!);
  return out;
};

test("the preview draws a fallback device's text from the baked sheet, and the curve only where the face is", () => {
  const text = design(FALLBACK);
  const asBaked = design(`      source: ${TTF}\n      size: 12%r\n`, { curved: null });
  for (const id of ["fr955", "fr255"]) {
    const r = resolved(text, id);
    const box = r.items.find((p) => p.id === "brand")!.box;
    const pixels = crop(frame(text, id), box);
    assert.ok(pixels.some((v) => v > 0), `${id}: brand drawn`);
    assert.deepEqual(pixels, crop(frame(asBaked, id), box), `${id}: drawn from the sheet a source: font bakes`);
    const rim = r.items.find((p) => p.id === "rim")!.box;
    assert.ok(crop(frame(text, id), rim).every((v) => v === 0), `${id}: rim not drawn`);
  }
  const fenix = resolved(text, "fenix8solar47mm");
  const im = frame(text, "fenix8solar47mm");
  assert.ok(crop(im, fenix.items.find((p) => p.id === "rim")!.box).some((v) => v > 0), "fenix: rim drawn");
  assert.equal(drawn(text, "brand", {}, "fr255"), "BRAND");
});
