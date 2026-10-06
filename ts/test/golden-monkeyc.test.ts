// The generated Monkey C a person reviews: three designs' sources compared
// with ts/test/goldens/monkeyc/, and the properties those files must never
// silently lose (ADR 0003: generated code is readable). A golden diff is a
// real output change: explain it, then `WFB_UPDATE_GOLDENS=1 npm test`.
import assert from "node:assert/strict";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { load, resolveAll, selectDevices } from "../src/build.ts";
import { Bag } from "../src/diagnostics.ts";
import { type GeneratedProject, generate } from "../src/emit/project.ts";
import { bakeFonts, ICON_FONT } from "../src/emit/resources.ts";
import { readFontFile } from "../src/node.ts";
import { REPO_ROOT as ROOT } from "../src/devices/node.ts";
import { db } from "../tools/goldens.ts";

const GOLDEN = join(ROOT, "ts", "test", "goldens", "monkeyc");
const update = process.env["WFB_UPDATE_GOLDENS"] === "1";

function generated(design: string): GeneratedProject {
  const path = `tests/fixtures/${design}/face.yaml`;
  const text = readFileSync(join(ROOT, path), "utf8");
  const bag = new Bag();
  const exists = (p: string): boolean => existsSync(join(ROOT, p));
  const read = (p: string) => readFontFile(p === ICON_FONT ? p : join(ROOT, p));
  const face = load(path, bag, text, exists);
  assert.ok(face !== null, bag.render());
  const devices = selectDevices(face, db, bag);
  const [resolved] = resolveAll(face, devices, bag, (f, d) => bakeFonts(f, d, read));
  return generate(face, devices, read, { resolved });
}

function golden(name: string, actual: string): void {
  const path = join(GOLDEN, name);
  if (update) {
    writeFileSync(path, actual);
    return;
  }
  assert.ok(existsSync(path), `no golden file for ${name}: run WFB_UPDATE_GOLDENS=1 npm test`);
  assert.equal(actual, readFileSync(path, "utf8"), `${name} differs from its golden file`);
}

/** One method of a view, by name: from its declaration to the next doc comment. */
const method = (view: string, name: string): string => view.split(`private function ${name}`)[1]!.split("\n\n    //!")[0]!;

const slice = generated("slice");
const files = (p: GeneratedProject): Map<string, string> =>
  new Map([...p.files()].filter((e): e is [string, string] => typeof e[1] === "string"));

test("the slice's generated files match their goldens", () => {
  const f = files(slice);
  for (const name of ["manifest.xml", "monkey.jungle", "source/SliceApp.mc", "source/SliceView.mc", "source/Palette.mc",
    "source-fenix8solar47mm/Layout.mc", "source-fenix8solar51mm/Layout.mc", "source-fr955/Layout.mc", "resources-fenix8solar47mm/fonts/fonts.xml"]) {
    assert.ok(f.has(name), name);
    golden(name.replaceAll("/", "__"), f.get(name)!);
  }
});

test("the view names every element", () => {
  const view = files(slice).get("source/SliceView.mc")!;
  for (const element of slice.face.walk()) assert.ok(view.includes(`\`${element.id}\``), `${element.id} has no comment tying it to the YAML`);
});

test("layout constants are named, not inlined", () => {
  for (const line of files(slice).get("source/SliceView.mc")!.split("\n")) {
    const stripped = line.trim();
    if (!/^(dc\.fill|dc\.draw|WfbArc\.)/.test(stripped)) continue;
    assert.ok(!/\(\s*-?\d/.test(stripped.replace(/"[^"]*"/g, '""')), stripped);
  }
});

test("the slice's manifest, guards, layouts, barrel and headers", () => {
  const f = files(slice);
  const view = f.get("source/SliceView.mc")!;
  assert.ok(view.includes("activitySteps == null") || view.includes("activitySteps != null"));
  assert.ok(f.get("manifest.xml")!.includes("<iq:language>eng</iq:language>"));
  assert.ok(f.get("manifest.xml")!.includes("<iq:permissions/>"));
  assert.equal([...f.keys()].filter((n) => n.endsWith("Layout.mc")).length, slice.devices.length);
  assert.notEqual(f.get("source-fenix8solar47mm/Layout.mc"), f.get("source-fenix8solar51mm/Layout.mc"));
  assert.deepEqual(new Set(slice.barrel), new Set(["WfbArc.mc", "WfbMath.mc", "WfbTime.mc"]));
  for (const [name, text] of f) if (name.endsWith(".mc") && !name.startsWith("runtime-lib/")) assert.ok(text.includes("garmin-wf-builder") && text.includes("face.yaml"), name);
});

test("vector text: its goldens, its loading, its gates", () => {
  const f = files(generated("vector_text"));
  for (const name of ["source/VectorTextView.mc", "source-fenix8solar47mm/Layout.mc", "source-fr955/Layout.mc"]) golden(`vector_text__${name.replaceAll("/", "__")}`, f.get(name)!);
  const view = f.get("source/VectorTextView.mc")!;
  const layout = f.get("source-fenix8solar47mm/Layout.mc")!;
  assert.ok(view.includes("_fontBezel = Graphics.getVectorFont(") && !view.includes("_fontBezel = WatchUi.loadResource("));
  assert.ok(view.includes("_fontClock = WatchUi.loadResource(Rez.Fonts.") && !view.includes("_fontClock = Graphics.getVectorFont("));
  const fonts = f.get("resources-fenix8solar47mm/fonts/fonts.xml")!;
  assert.ok(!fonts.includes("bezel") && !fonts.includes("RobotoCondensed"));
  assert.ok(view.includes("dc.drawAngledText(") && view.includes("dc.drawRadialText("));
  for (const c of ["const BRAND_ANGLE as Float", "const BEZEL_TEXT_ANGLE as Float", "const BEZEL_TEXT_RADIUS as Number"]) assert.ok(layout.includes(c), c);
  const upright = method(view, "drawUprightVector");
  assert.ok(upright.includes("dc.drawText(") && !upright.includes("dc.drawAngledText(") && !upright.includes("dc.drawRadialText("));
  for (const name of ["drawUprightVector", "drawBrand", "drawBezelText"]) assert.ok(method(view, name).includes("if (font != null)"), name);
  assert.ok(!view.includes("FONT_BEZEL_AVAILABLE") && !layout.includes("FONT_BEZEL_AVAILABLE"));
});

test("outlined text: its goldens, its stamps, its ring font", () => {
  const f = files(generated("outline_text"));
  for (const name of ["source/OutlineTextView.mc", "source-fenix8solar47mm/Layout.mc", "source-fr955/Layout.mc"]) golden(`outline_text__${name.replaceAll("/", "__")}`, f.get(name)!);
  const view = f.get("source/OutlineTextView.mc")!;
  assert.ok(!f.get("source-fenix8solar47mm/Layout.mc")!.includes("OUTLINE_OFFSETS"));
  const clock = method(view, "drawClock");
  assert.ok(!clock.includes("while") && clock.indexOf("ringFont") < clock.lastIndexOf("dc.setColor("));
  assert.ok(clock.includes("dc.drawText(") && !clock.includes("dc.drawAngledText(") && !clock.includes("dc.drawRadialText("));
  for (const [name, x] of [["drawUprightVector", "UPRIGHT_VECTOR_X"], ["drawBrand", "BRAND_X"], ["drawBezelText", "BEZEL_TEXT_X"]] as const) {
    const m = method(view, name);
    assert.ok(m.includes(`Layout.${x} - 1,`) && m.includes(`Layout.${x} + 1,`), name);
    assert.ok(m.indexOf(`Layout.${x} + 1,`) < m.lastIndexOf("dc.setColor("), name);
    assert.equal(m.split("if (font != null)").length - 1, 1, name);
  }
  assert.ok(view.includes("dc.drawAngledText(") && view.includes("dc.drawRadialText("));
});
