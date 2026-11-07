// A registry stand-in flagged `tabular_digits` (Rajdhani behind Garmin's
// Bionic) measures and draws its digits in one cell, the widest digit's
// advance, each centred, as the real face does; an unflagged key and
// Garmin's own file, when located, are measured as they are. Rajdhani's
// `1` (327 units) against its `0` (528) is the contrast: proportional, the
// two clocks measure apart.
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { DeviceDatabase, FontMetric } from "../src/devices/device.ts";
import { REPO_ROOT } from "../src/devices/node.ts";
import { bakeFonts } from "../src/emit/resources.ts";
import { type FontMeasure, type SystemFace } from "../src/fonts/fallback.ts";
import { type FontFiles, locate } from "../src/fonts/files.ts";
import { NodeFontFiles } from "../src/fonts/node.ts";
import { resolve } from "../src/layout.ts";
import { previewOptions, Renderer } from "../src/preview.ts";
import { image } from "../src/raster/pillow.ts";
import { db, face, MINIMAL, read } from "./designs.ts";

/** Registry stand-ins only: no Garmin font root, whatever the machine has. */
const standIns: FontFiles = { garmin: () => undefined, registry: (key) => db.fonts.registry(key) };
const bare = new DeviceDatabase(db.files, standIns);

const metric = (deviceId: string, symbol: string): FontMetric => bare.get(deviceId).systemFonts.get(symbol)!;

/** `face: BionicSemiBold` at `px`, the metric layout gives a vector face. */
function vectorMetric(px: number): FontMetric {
  const device = bare.get("fenix8solar47mm");
  return new FontMetric("BionicSemiBold", "BionicSemiBold", device.scalableFaceFiles.get("BionicSemiBold")!, px);
}

/** `ch`'s own advance in `face`, from its `hmtx` at the whole-pixel em, as an untabular face rounds it. */
function ownAdvance(face: SystemFace, ch: string): number {
  const { cmap, advances, unitsPerEm } = face.sfnt!;
  return Math.round(advances[cmap.get(ch.codePointAt(0)!)!]! * face.layoutEm! / unitsPerEm);
}

function assertTabular(measure: FontMeasure, m: FontMetric): void {
  const sface = measure.systemFace(m)!;
  assert.notEqual(sface.match, "garmin");
  const width = (text: string) => measure.measure(text, m)[0];
  assert.equal(width("11:11"), width("00:00"));
  assert.equal(width("Fri 11:11") - width("Wed 00:00"), width("Fri ") - width("Wed "));
  const cell = Math.max(...Array.from("0123456789", (d) => ownAdvance(sface, d)));
  assert.deepEqual(sface.advances("019:"), [cell, cell, cell, ownAdvance(sface, ":")]);
  assert.ok(ownAdvance(sface, "1") < cell, "Rajdhani's 1 is narrower than its widest digit");
}

test("fenix 8 FONT_NUMBER_MEDIUM through Rajdhani SemiBold measures its digits tabular", () => {
  const m = metric("fenix8solar47mm", "FONT_NUMBER_MEDIUM");
  assert.equal(locate(standIns, m.font, m.face || null)[0]!.path.includes("rajdhani-semibold"), true);
  assertTabular(bare.measure, m);
});

test("a face: BionicSemiBold font through its stand-in measures its digits tabular", () => {
  assertTabular(bare.measure, vectorMetric(60));
});

test("fenix 6's Bionic bitmaps, with no .cft, measure through Rajdhani Bold tabular", () => {
  const m = metric("fenix6", "FONT_NUMBER_HOT");
  assert.match(m.font, /BIONIC_BOLD/);
  const file = locate(standIns, m.font, m.face || null)[0]!;
  assert.equal(Buffer.compare(file.bytes, standIns.registry("rajdhani-bold")!.bytes), 0, `${file.path} is Rajdhani Bold`);
  assertTabular(bare.measure, m);
});

test("an unflagged key measures its digits as they are", () => {
  for (const [id, symbol] of [["fr955", "FONT_NUMBER_MEDIUM"], ["fenix8solar47mm", "FONT_MEDIUM"], ["fenix6", "FONT_NUMBER_MEDIUM"]] as const) {
    const m = metric(id, symbol);
    const sface = bare.measure.systemFace(m)!;
    assert.equal(sface.tabularDigits, false, `${id} ${symbol}`);
    assert.deepEqual(sface.advances("01:"), Array.from("01:", (ch) => ownAdvance(sface, ch)), `${id} ${symbol}`);
    assert.deepEqual(sface.drawOffsets("01:"), [0, 0, 0]);
  }
});

test("Garmin's own Bionic file, when located, is used as it is", (t) => {
  const roots = [process.env["WFB_FONTS"], join(REPO_ROOT, "vendor", "fonts"), join(homedir(), ".Garmin", "ConnectIQ", "Fonts"),
    join(homedir(), "Library", "Application Support", "Garmin", "ConnectIQ", "Fonts")];
  const root = roots.find((r) => r !== undefined && existsSync(join(r, "Bionic_semibold.ttf")));
  if (root === undefined) {
    t.skip("no Garmin font root with Bionic_semibold.ttf");
    return;
  }
  const withGarmin = new DeviceDatabase(db.files, new NodeFontFiles(root));
  const m = withGarmin.get("fenix8solar47mm").systemFonts.get("FONT_NUMBER_MEDIUM")!;
  assert.equal(locate(withGarmin.fonts, m.font, m.face || null)[1], "garmin");
  const sface = withGarmin.measure.systemFace(m)!;
  assert.equal(sface.tabularDigits, false);
  assert.deepEqual(sface.advances("01:"), Array.from("01:", (ch) => ownAdvance(sface, ch)));
});

/** The ink's horizontal centroid (red channel) of `draw` on a blank canvas. */
function inkCentre(draw: (r: Renderer) => void): number {
  const f = face(MINIMAL);
  const device = bare.get("fenix8solar47mm");
  const im = image(400, 200);
  draw(new Renderer(resolve(f, device, bakeFonts(f, device, read)), im, 1, new Map() as never, previewOptions({ scale: 1 })));
  let sum = 0, weight = 0;
  for (let y = 0; y < im.height; y++) {
    for (let x = 0; x < im.width; x++) {
      const v = im.data[(y * im.width + x) * 4]!;
      sum += x * v;
      weight += v;
    }
  }
  assert.ok(weight > 0, "something was drawn");
  return sum / weight;
}

test("the preview draws a 1 centred in its tabular cell, upright and turned", () => {
  const LEFT = 100;
  for (const [what, m] of [["FONT_NUMBER_HOT", metric("fenix8solar47mm", "FONT_NUMBER_HOT")], ["BionicSemiBold", vectorMetric(99)]] as const) {
    const sface = bare.measure.systemFace(m)!;
    const cell = sface.advances("1")[0]!;
    assert.ok(cell > ownAdvance(sface, "1"), `${what}: the cell is wider than the 1`);
    const centre = LEFT + cell / 2;
    const upright = inkCentre((r) => r.drawText(null, "1", [LEFT, 100], "left", "center", m, [255, 255, 255]));
    assert.ok(Math.abs(upright - centre) < 1.5, `${what} upright: ink at ${upright}, cell centre ${centre}`);
    const turned = inkCentre((r) => r.drawVectorText("1", [LEFT, 100], "left", "center", m, [255, 255, 255], "angled", 0, 0, null));
    assert.ok(Math.abs(turned - centre) < 1.5, `${what} angled: ink at ${turned}, cell centre ${centre}`);
  }
});
