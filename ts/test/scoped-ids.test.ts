// Element names are unique among siblings; ids are the name qualified by
// the enclosing groups' ids, and the generated symbols follow the id.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { load as loadDesign } from "../src/build.ts";
import { REPO_ROOT } from "../src/devices/node.ts";
import { Bag } from "../src/diagnostics.ts";
import { indexFor } from "../src/edit/spans.ts";
import { childElementId, elementIdOfPath, elementName, layoutIds, STATIC_GROUP_ID } from "../src/element_ids.ts";
import { installAssets, repoFileExists } from "../src/node.ts";
import { exampleDesigns } from "../tools/goldens.ts";
import { checked, errors, face, generated, MINIMAL } from "./designs.ts";

const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/;

const TEXT = (text: string, font = "FONT_SMALL"): string =>
  `type: text, text: "${text}", at: {anchor: center}, color: color.fg, font: ${font}`;
const GROUP = (indent: string, name: string, children: string): string =>
  `${indent}${name}:\n${indent}  type: group\n${indent}  at: {anchor: center}\n${indent}  size: {width: 60%, height: 40%}\n${indent}  children:\n${children}`;

/** Every warning or error of a build, as text; the notes a lint reports are not a failure. */
const complaints = (text: string): string =>
  checked(text).filter((d) => d.severity !== "note").map((d) => `${d.severity}[${d.code}]: ${d.message}`).join("\n");

/** The generated sources' text, concatenated. */
const sources = (text: string): string => [...generated(text).values()].join("\n");

test("the same name in two groups, and at the top level and in a group, builds under qualified ids and symbols", () => {
  const design = MINIMAL
    + GROUP("  ", "top", `      label: {${TEXT("up")}}\n`)
    + GROUP("  ", "bottom", `      label: {${TEXT("down")}}\n`)
    + `  label: {${TEXT("free")}}\n`;
  const f = face(design);
  assert.deepEqual(f.walk().map((e) => e.id), ["background", "top", "top.label", "bottom", "bottom.label", "label"]);
  assert.deepEqual(f.walk().map((e) => e.name), ["background", "top", "label", "bottom", "label", "label"]);
  assert.equal(complaints(design), "");
  const text = sources(design);
  for (const symbol of ["drawTopLabel", "drawBottomLabel", "drawLabel", "TOP_LABEL_X", "BOTTOM_LABEL_X", "LABEL_X"]) {
    assert.ok(text.includes(symbol), `${symbol} is generated`);
  }
  assert.ok(!/draw[A-Za-z]*Label_\d/.test(text), "no suffixed draw method stands in for a scope");
});

test("a static: block's element and an elements: one may share a name; so may two layouts' elements", () => {
  const design = MINIMAL.replace("elements:\n", `static:\n  ticks: {type: circle, at: {anchor: center}, radius: 40%r, color: color.fg}\nelements:\n`)
    + `  ticks: {type: circle, at: {anchor: center}, radius: 10%r, color: color.fg}\n`;
  const f = face(design);
  assert.deepEqual(f.walk().map((e) => e.id), ["static", "static.ticks", "background", "ticks"]);
  assert.equal(complaints(design), "");
  const text = sources(design);
  assert.ok(text.includes("drawStaticTicks") && text.includes("drawTicks") && text.includes("STATIC_TICKS_CX") && text.includes("TICKS_CX"));

  // a top-level *group* of that name too: its buffer painter is paintStaticTicks, not the element's drawStaticTicks
  const grouped = MINIMAL.replace("elements:\n", `static:\n  ticks: {type: circle, at: {anchor: center}, radius: 40%r, color: color.fg}\nelements:\n`)
    + `  ticks:\n    type: group\n    children:\n      dot: {type: circle, at: {anchor: center}, radius: 10%r, color: color.fg}\n`;
  assert.equal(complaints(grouped), "");
  const groupedText = sources(grouped);
  assert.ok(groupedText.includes("drawStaticTicks") && groupedText.includes("paintStatic(") && groupedText.includes("drawTicksDot"));

  // the shared background goes in `static:`, so no layout's static content is hoisted in front of it
  const layouts = MINIMAL.replace("elements:\n", "static:\n") + "layouts:\n"
    + `  big:\n    static:\n      rim: {type: circle, at: {anchor: center}, radius: 45%r, color: color.fg}\n    elements:\n      clock: {${TEXT("a")}}\n`
    + `  small:\n    static:\n      rim: {type: circle, at: {anchor: center}, radius: 30%r, color: color.fg}\n    elements:\n      clock: {${TEXT("b")}}\n`
    + "config:\n  style:\n    default: big\n    choices:\n      big: {layout: big}\n      small: {layout: small}\n";
  const g = face(layouts);
  assert.deepEqual(g.walk().map((e) => e.id),
    ["static", "static.background", "layout_big_static", "layout_big_static.rim", "layout_big", "layout_big.clock",
      "layout_small_static", "layout_small_static.rim", "layout_small", "layout_small.clock"]);
  assert.equal(complaints(layouts), "");
  const generatedText = sources(layouts);
  for (const symbol of ["drawLayoutBigClock", "drawLayoutSmallClock", "drawLayoutBigStaticRim", "drawLayoutSmallStaticRim", "LAYOUT_BIG_CLOCK_X"]) {
    assert.ok(generatedText.includes(symbol), `${symbol} is generated`);
  }
});

test("two ids folding to one Monkey C symbol are one duplicate-id error naming both, wherever they sit", () => {
  const top = GROUP("  ", "top", `      label: {${TEXT("up")}}\n`);
  for (const other of ["top_label", "topLabel"]) {
    const found = errors(MINIMAL + top + `  ${other}: {${TEXT("x")}}\n`);
    assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
    assert.equal(found[0]!.code, "duplicate-id");
    assert.ok(found[0]!.message.includes(`'${other}'`) && found[0]!.message.includes("'top.label'"), found[0]!.message);
    assert.ok(found[0]!.notes.some((n) => n.includes("'top.label'") && n.includes("first declared")), found[0]!.notes.join("\n"));
  }
  // the same key twice in one mapping is YAML's own error, before any id exists
  const twice = errors(MINIMAL + `  label: {${TEXT("a")}}\n  label: {${TEXT("b")}}\n`);
  assert.ok(twice.length > 0 && twice.every((d) => d.code !== "duplicate-id"), twice.map((d) => `${d.code}: ${d.message}`).join("\n"));
});

test("an inline font: is hoisted under the element's name, not its qualified id", () => {
  const OPEN_SANS = "ts/test/fixtures/slice/assets/OpenSans-Regular.ttf";
  const one = face(MINIMAL + GROUP("  ", "top", `      label: {${TEXT("up", `{source: ${OPEN_SANS}, size: 20%r}`)}}\n`));
  assert.deepEqual([...one.fonts.keys()], ["label_font"]);
  const two = face(MINIMAL
    + GROUP("  ", "top", `      label: {${TEXT("up", `{source: ${OPEN_SANS}, size: 20%r}`)}}\n`)
    + GROUP("  ", "bottom", `      label: {${TEXT("down", `{source: ${OPEN_SANS}, size: 10%r}`)}}\n`));
  assert.deepEqual([...two.fonts.keys()], ["label_font", "label_font_2"]);
  const fontOf = (id: string): string => (two.walk().find((e) => e.id === id) as unknown as { font: string }).font;
  assert.deepEqual([fontOf("top.label"), fontOf("bottom.label")], ["label_font", "label_font_2"]);
});

test("every example's and fixture's ids are distinct and agree with the ids derived from the authored paths", () => {
  installAssets();
  let faces = 0;
  for (const path of exampleDesigns()) {
    const text = readFileSync(join(REPO_ROOT, path), "utf8");
    const bag = new Bag();
    bag.registerSource(path, text);
    const f = loadDesign(path, bag, text, repoFileExists);
    if (f === null) continue;
    faces++;
    const ids = f.walk().map((e) => e.id);
    assert.equal(new Set(ids).size, ids.length, `${path}: ids are distinct`);
    for (const element of f.walk()) {
      assert.ok(IDENTIFIER.test(element.name), `${path}: ${element.id} names an identifier`);
      assert.equal(element.id, childElementId(element.id === element.name ? null : element.id.slice(0, -element.name.length - 1), element.name));
    }
    // the editor's view of the same document: each element entry's path, qualified the same way; the
    // containers desugaring mints around `static:` and a layout's blocks are the only ids nobody wrote
    const authored = new Set(indexFor(text).elements().map((e) => elementIdOfPath(e.path)));
    const synthetic = new Set([STATIC_GROUP_ID, ...f.layouts.flatMap((name) => layoutIds(name))]);
    assert.deepEqual(authored, new Set(ids.filter((id) => !synthetic.has(id))), `${path}: the authored paths and the built ids name the same elements`);
  }
  assert.ok(faces > 10, `${faces} faces loaded`);
});

test("elementName of a built id is its key", () => {
  const nested = MINIMAL + GROUP("  ", "a", GROUP("      ", "b", `          c: {${TEXT("deep")}}\n`));
  const f = face(nested);
  const deep = f.walk().find((e) => e.id === "a.b.c")!;
  assert.equal(deep.name, "c");
  assert.equal(elementName(deep.id), "c");
  assert.ok(sources(nested).includes("drawABC"));
});
