// The fixture device `wfbtest` (`fixtures/devices/`): a round 260x260 MIP
// watch written by this project, so a design loads, resolves, lints,
// generates and draws with no Garmin device file anywhere. Every test here
// reads the fixture alone, never the installed devices, and a child `wfb`
// runs with a home folder that holds none.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { sourceUnavailable, SETTINGS_MENU_SYMBOL } from "../src/availability.ts";
import { load, resolveAll, selectDevices } from "../src/build.ts";
import { CATALOG } from "../src/catalog.ts";
import { Device, DeviceDatabase } from "../src/devices/device.ts";
import { NodeDeviceFiles, REPO_ROOT } from "../src/devices/node.ts";
import { Bag } from "../src/diagnostics.ts";
import { generate } from "../src/emit/project.ts";
import { bakeFonts } from "../src/emit/resources.ts";
import { locate } from "../src/fonts/files.ts";
import { NodeFontFiles } from "../src/fonts/node.ts";
import { CONFIG_SYMBOL } from "../src/ir/model.ts";
import { installAssets, readFontFile } from "../src/node.ts";
import { previewOptions, render } from "../src/preview.ts";

installAssets();
// Measured with the registry's stand-ins only, as on a machine with no Garmin files.
process.env["WFB_NO_GARMIN_FONTS"] = "1";

const FIXTURE_DEVICES = join(REPO_ROOT, "ts", "test", "fixtures", "devices");
const FIXTURE_REFERENCE = join(FIXTURE_DEVICES, "reference");

const db = new DeviceDatabase(NodeDeviceFiles.discover(FIXTURE_DEVICES, FIXTURE_REFERENCE), new NodeFontFiles());
const CLI = join(REPO_ROOT, "ts", "src", "cli.ts");

/** An example's text with its `targets:` (block or flow) replaced by `wfbtest` alone. */
function onFixture(example: string): string {
  const text = readFileSync(join(REPO_ROOT, example), "utf8");
  const out = text.replace(/^ {2}targets:\n(?: {4}- .*\n)+/m, "  targets:\n    - wfbtest\n").replace(/^ {2}targets: \[[^\]]*\]$/m, "  targets: [wfbtest]");
  assert.notEqual(out, text, `${example}: no targets: to replace`);
  return out;
}

/** An example loaded, resolved and linted on the fixture: the bag, and the resolved face. */
function compile(example: string) {
  const text = onFixture(example);
  const bag = new Bag();
  bag.registerSource(example, text);
  const exists = (p: string): boolean => { try { readFileSync(join(REPO_ROOT, p)); return true; } catch { return false; } };
  const face = load(example, bag, text, exists);
  assert.ok(face !== null, bag.render());
  const devices = selectDevices(face, db, bag);
  const read = (p: string) => readFontFile(join(REPO_ROOT, p));
  const [resolved] = resolveAll(face, devices, bag, (f, d) => bakeFonts(f, d, read));
  return { face, devices, bag, resolved: resolved.get("wfbtest"), read };
}

test("the fixture folder holds wfbtest alone, and its files read as a device", () => {
  assert.deepEqual(db.ids(), ["wfbtest"]);
  const d = db.get("wfbtest");
  assert.deepEqual([d.width, d.height, d.shape, d.deviceFamily, d.displayType], [260, 260, "round", "round-260x260", "mip"]);
  assert.deepEqual([d.watchfaceMemoryLimit, d.apiLevel, d.displayColors, d.alphaBlending], [131072, "5.2.0", 64, false]);
  assert.equal(d.skinName, "wfbtest.png");
  assert.deepEqual(d.displayLocation, [60, 60, 260, 260]);
  assert.deepEqual(d.scalableFaces, ["RobotoCondensedBold", "RobotoCondensedRegular"]);
});

test("every system font resolves to a registry stand-in that is installed", () => {
  const d = db.get("wfbtest");
  const symbols = [...d.systemFonts.keys()];
  assert.deepEqual(symbols, ["FONT_XTINY", "FONT_TINY", "FONT_SMALL", "FONT_MEDIUM", "FONT_LARGE",
    "FONT_NUMBER_MILD", "FONT_NUMBER_MEDIUM", "FONT_NUMBER_HOT", "FONT_NUMBER_THAI_HOT"]);
  for (const metric of d.systemFonts.values()) {
    const [file, match] = locate(db.fonts, metric.font, metric.face);
    assert.ok(file !== null, `${metric.symbol}: ${metric.font} has no stand-in installed (run ts/tools/fetch-system-fonts.ts)`);
    assert.equal(match, "exact", `${metric.symbol}: ${metric.font} is not an exact stand-in`);
    assert.ok(db.measure.systemFace(metric) !== null, `${metric.symbol} does not measure`);
  }
});

test("its own symbol table has every module, function and field the compiler asks a device about", () => {
  const d = db.get("wfbtest");
  for (const path of CATALOG.keys()) {
    assert.equal(sourceUnavailable(path, d)?.reason ?? null, null, `${path} is unavailable on wfbtest`);
  }
  for (const symbol of [Device.VECTOR_FONT_SYMBOL, Device.DRAW_ANGLED_TEXT_SYMBOL, Device.DRAW_RADIAL_TEXT_SYMBOL,
    Device.DISPLAY_MODE_SYMBOL, CONFIG_SYMBOL, SETTINGS_MENU_SYMBOL, "Toybox.WatchUi.WatchFaceDelegate.onPress"]) {
    assert.ok(d.hasSymbol(symbol), `wfbtest lacks ${symbol}`);
  }
  assert.ok(d.hasModule("Complications") && d.hasModule("Weather"));
  assert.ok(d.hasField(Device.BURN_IN_FIELD));
  // a symbol it does not list is absent, as on a real device
  assert.equal(d.hasSymbol("Toybox.Graphics.Dc.drawBitmap2"), false);
});

test("the shapes example loads, resolves, lints clean, generates and draws on wfbtest", () => {
  const { face, devices, bag, resolved, read } = compile("examples/features/shapes/face.yaml");
  assert.equal(bag.render({ verbose: true, merge: false }), "");
  assert.ok(resolved !== undefined);
  const files = new Map(generate(face, devices, read).files());
  assert.match(String(files.get("manifest.xml")), /<iq:product id="wfbtest"\s*\/>/);
  const frame = render(resolved, previewOptions({ skin: true, scale: 1 }));
  // the skin around the panel: 380 square, the bezel its flat grey, the panel's centre inside it
  assert.deepEqual([frame.width, frame.height], [380, 380]);
  const at = (x: number, y: number): number[] => [...frame.data.subarray((y * frame.width + x) * 4, (y * frame.width + x) * 4 + 3)];
  assert.deepEqual(at(190, 20), [0x40, 0x40, 0x40]);
  // the drawn face: something besides black lies inside the panel
  let lit = 0;
  for (let y = 60; y < 320; y++) for (let x = 60; x < 320; x++) if (at(x, y).some((c) => c !== 0)) lit++;
  assert.ok(lit > 2000, `only ${lit} lit pixels inside the panel`);
});

test("a design reading complications lints clean on wfbtest: Toybox.Complications is in its symbol table", () => {
  const { bag, resolved } = compile("examples/features/complications/face.yaml");
  assert.ok(resolved !== undefined);
  assert.equal(bag.render({ verbose: true, merge: false }), "");
});

test("wfb finds the fixture through WFB_DEVICES and WFB_DEVICE_REFERENCE, with no other device visible", () => {
  const home = mkdtempSync(join(tmpdir(), "wfb-fixture-"));
  const done = spawnSync(process.execPath, [CLI, "devices", "--color", "never"], {
    cwd: REPO_ROOT,
    env: { ...process.env, HOME: home, WFB_DEVICES: FIXTURE_DEVICES, WFB_DEVICE_REFERENCE: FIXTURE_REFERENCE, WFB_NO_GARMIN_FONTS: "1" },
  });
  const out = done.stdout.toString();
  assert.equal(done.status, 0, out + done.stderr.toString());
  const rows = out.split("\n").slice(1).filter((line) => line.trim() !== "");
  assert.equal(rows.length, 1, out);
  assert.match(rows[0]!, /^wfbtest\s+260x260\s+round\s+mip\s+64\s+5\.2\.0\s+128 KB\s+round-260x260$/);
});
