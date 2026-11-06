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
