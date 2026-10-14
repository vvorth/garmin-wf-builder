// The Properties panel's controls against the real worker, each change read
// back from the YAML text: numbers and units, the align picker, the colour
// picker's three groups, a text's `+ data`, the font, icon and `on_hold`
// selects, the four scope buttons writing overrides and `×` pruning an
// emptied one, renaming an element, and `curve:` on a curved text.

import assert from "node:assert/strict";
import type { Summary } from "../src/studio/protocol.ts";
import { diffLines, type Session, suite } from "./harness.ts";

const h = await suite(import.meta.url);

/** The element `id`'s own lines of the text. */
function lines(doc: Summary, id: string): string {
  const nodes: { id: string; line: number; end: number }[] = [];
  const walk = (list: Summary["tree"][number]["children"]): void => list.forEach((n) => { nodes.push(n); walk(n.children); });
  doc.tree.forEach((b) => walk(b.children));
  const node = nodes.find((n) => n.id === id);
  assert.ok(node, `${id} is not in the tree`);
  return doc.text.split("\n").slice(node.line - 1, node.end).join("\n");
}

/** Wait for the change after `before`, idle, and return the face. */
async function written(s: Session, before: Summary): Promise<Summary> {
  const after = await s.waitVersion(before.version);
  await s.waitIdle();
  return after;
}

async function undoTo(s: Session, before: Summary, what: string): Promise<void> {
  const after = await s.undo();
  assert.equal(after.text, before.text, `undo after ${what}: ${diffLines(before.text, after.text).join(" ; ")}`);
}

h.test("a number's unit: deg to turn converts, %r to px waits for a number, pt only where a font is", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();

  // deg -> turn: converted and written at once
  await s.selectLayer("outer_arc");
  const sweep = s.topField("sweep");
  assert.equal(await sweep.locator("input").inputValue(), "300");
  await sweep.locator("select").selectOption("turn");
  let after = await written(s, base);
  assert.match(lines(after, "outer_arc"), /sweep: 0\.833333turn/, lines(after, "outer_arc"));
  await s.expectValue(sweep.locator("input"), "0.833333");
  assert.equal(after.history.undo, "set elements.outer_arc.sweep to 0.833333turn");
  await undoTo(s, base, "the unit conversion");

  // px -> %r: nothing written until a number is typed in the new unit
  await s.selectLayer("dot");
  const radius = s.topField("radius");
  assert.deepEqual(await radius.locator("select option").allTextContents(), ["px", "%", "%r"], "pt offered on a circle's radius");
  await radius.locator("select").selectOption("%r");
  await s.page.waitForTimeout(800);
  assert.equal((await s.doc()).text, base.text, "a unit switch alone wrote something");
  const input = radius.locator("input");
  assert.equal(await input.inputValue(), "", "the number box did not empty");
  assert.equal(await input.getAttribute("placeholder"), "4", "the old number is not the hint");
  await assert.doesNotReject(input.evaluate((e) => { if (document.activeElement !== e) throw new Error("the number box did not take the focus"); }));
  await input.fill("5");
  await input.press("Enter");
  after = await written(s, base);
  assert.match(lines(after, "dot"), /radius: 5%r/, lines(after, "dot"));
  await undoTo(s, base, "the %r radius");

  // a text's lengths offer pt; a rectangle's do not
  await s.selectLayer("label");
  assert.deepEqual(await s.childField("at", "dy").locator("select option").allTextContents(), ["px", "%", "%r", "pt"]);
  await s.selectLayer("card");
  assert.deepEqual(await s.topField("thickness").locator("select option").allTextContents(), ["px", "%", "%r"]);
  assert.deepEqual(s.errors, []);
});

h.test("the align picker, a text's + data, its font and on_hold, and × back to the default", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  await s.selectLayer("label");

  // align: the 3x3 picker
  await s.topField("align").locator(".align button[title=left]").click();
  let after = await written(s, base);
  assert.match(lines(after, "label"), /\n    align: left$/m, lines(after, "label"));
  await s.topField("align").locator(".align button.on[title=left]").waitFor({ timeout: 8000 });
  // × removes the key again
  await s.topField("align").locator("button.reset").click();
  after = await written(s, after);
  assert.equal(after.text, base.text, `× did not put the text back: ${diffLines(base.text, after.text).join(" ; ")}`);

  // + data inserts a placeholder into the template
  const template = s.topField("text").locator(".template");
  await template.locator("select").selectOption("time.hour");
  after = await written(s, after);
  assert.match(lines(after, "label"), /text: "(SHAPES\{time\.hour\}|\{time\.hour\}SHAPES)"/, lines(after, "label"));
  await s.expectValue(template.locator("input"), lines(after, "label").match(/text: "([^"]*)"/)![1]!);
  await undoTo(s, base, "+ data");

  // the font select offers the watch's system fonts
  await s.selectLayer("label");
  const font = s.topField("font").locator("select");
  assert.ok((await font.locator("option").allTextContents()).includes("FONT_TINY"), "FONT_TINY is not offered");
  await font.selectOption("FONT_TINY");
  after = await written(s, base);
  assert.match(lines(after, "label"), /font: FONT_TINY/);
  await s.expectValue(font, "FONT_TINY");
  await undoTo(s, base, "the font");

  // on_hold: a complication to open on touch and hold
  await s.selectLayer("label");
  await s.topField("on_hold").locator("select").selectOption("steps");
  after = await written(s, base);
  assert.match(lines(after, "label"), /\n    on_hold: steps$/m, lines(after, "label"));
  await undoTo(s, base, "on_hold");
  assert.deepEqual(s.errors, []);
});

h.test("the colour picker: this face, MIP 64 and a custom colour", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  await s.selectLayer("dot");
  const chip = s.topField("color").locator("button.chip-button");
  assert.equal(await chip.textContent(), "text");

  // this face: one of its own colours
  await chip.click();
  const pop = s.page.locator(".popover-body.pop");
  await pop.locator(".pop-title", { hasText: "This face" }).waitFor();
  await pop.locator(".pop-swatches button[aria-label=accent]").click();
  let after = await written(s, base);
  assert.match(lines(after, "dot"), /color: color\.accent/);
  await s.expectText(chip, "accent");
  assert.equal(after.globals.palette.length, base.globals.palette.length, "picking a face colour changed the palette");
  await undoTo(s, base, "a face colour");

  // MIP 64: one the face lacks is added under its name, and used
  const vocab = await s.api("vocabulary");
  const held = new Set(base.globals.palette.map((p) => String(p.value).toUpperCase()));
  const fresh = vocab.mip.find((m) => !held.has(m.value.toUpperCase()));
  assert.ok(fresh, "every MIP colour is in the palette already");
  await s.selectLayer("dot");
  await chip.click();
  await pop.locator(`.pop-grid button[aria-label="${fresh.label}"]`).click();
  after = await written(s, base);
  assert.match(lines(after, "dot"), new RegExp(`color: color\\.${fresh.name}\\b`), lines(after, "dot"));
  // one of the 64 is added with its label, in the long form
  assert.ok(new RegExp(`^    ${fresh.name}: \\{ value: "${fresh.value}", label: ${fresh.label} \\}$`, "mi").test(after.text), `the palette did not gain ${fresh.name}: ${diffLines(base.text, after.text).join(" ; ")}`);
  assert.ok(after.globals.palette.some((p) => p.name === fresh.name && p.automatic), "the new swatch is not marked automatic");
  await undoTo(s, base, "a MIP colour");

  // custom: a hex, named after its value
  await s.selectLayer("dot");
  await chip.click();
  await pop.locator("input.hex").fill("#FF8000");
  assert.match((await pop.locator(".note").textContent()) ?? "", /adds cFF8000/);
  await pop.locator("button.primary", { hasText: "Use" }).click();
  after = await written(s, base);
  assert.match(lines(after, "dot"), /color: color\.cFF8000/);
  assert.match(after.text, /^    cFF8000: "#FF8000"$/m);
  await undoTo(s, base, "a custom colour");
  assert.deepEqual(s.errors, []);
});

h.test("the scope buttons write a device, shape and display override; × prunes an emptied one", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  await s.selectLayer("dot");
  const scope = s.page.locator(".inspector .scope button");
  assert.deepEqual(await scope.allTextContents(), ["all targets", "fenix8solar47mm", "round screens", "MIP screens"]);

  for (const [index, selector, key] of [[1, "fenix8solar47mm", "fenix8solar47mm"], [2, "shape:round", '"shape:round"'], [3, "display:mip", '"display:mip"']] as const) {
    await scope.nth(index).click();
    const dx = s.childField("at", "dx").locator("input");
    await dx.fill("12");
    await dx.press("Enter");
    const after = await written(s, base);
    const own = lines(after, "dot");
    // a new override is written as one flow mapping, a selector with a colon quoted
    assert.ok(own.endsWith(`\n    overrides: { ${key}: { at: { dx: 12px } } }`), `${selector}: ${own}`);
    assert.match(own, /at: \{ anchor: center \}/, "the element's own at: changed");
    await s.expectValue(dx, "12");
    // back on all targets, the key says where the watch reads it
    await scope.nth(0).click();
    const note = await s.topField("at").locator(".children .field").filter({ has: s.page.locator(":scope > .name", { hasText: /^dx$/ }) }).locator(".note").textContent();
    assert.match(note ?? "", /overridden on this (device|shape|display class)/, `no note for ${selector}`);
    // × on the override takes the emptied override with it
    await scope.nth(index).click();
    await s.childField("at", "dx").locator("button.reset").click();
    const pruned = await written(s, after);
    assert.equal(pruned.text, base.text, `${selector}: × left something behind: ${diffLines(base.text, pruned.text).join(" ; ")}`);
    await scope.nth(0).click();
  }
  assert.deepEqual(s.errors, []);
});

h.test("renaming an element changes its one key and follows it in Layers", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  await s.selectLayer("dot");
  await s.page.locator(".inspector .ins-head .name").click();
  const input = s.page.locator(".inspector .ins-head input.inline-name");
  await input.fill("background");
  assert.equal(await input.getAttribute("aria-invalid"), "false");
  await input.fill("dot_renamed");
  await input.press("Enter");
  const after = await written(s, base);
  assert.equal(diffLines(base.text, after.text).join(" ; "), "+126:   dot_renamed: ; -126:   dot:");
  assert.equal(after.history.undo, "rename elements.dot to dot_renamed");
  await s.waitInspected("dot_renamed");
  assert.equal(await s.layerRow("dot_renamed").count(), 1);
  assert.equal(await s.layerRow("dot").count(), 0);
  // a name the face has already is refused with the reason
  await s.page.locator(".inspector .ins-head .name").click();
  const t = Date.now();
  await input.fill("background");
  await input.press("Enter");
  assert.match(await s.waitToast(t, /background/), /already|exists|is taken|used/, "the clash was not refused");
  assert.equal((await s.doc()).text, after.text);
  await undoTo(s, base, "the rename");
  assert.deepEqual(s.errors, []);
});

h.test("an icon element's picker, and curve: on an existing curved text", async (s) => {
  await s.openExample("showcase");
  await s.waitFace();
  await s.waitIdle();
  await s.page.locator(".controls label", { hasText: "Style" }).locator("select").selectOption("digital_dark");
  await s.waitIdle();
  let base = await s.doc();
  await s.selectLayer("hr_icon");
  const chip = s.topField("icon").locator("button.chip-button");
  assert.match((await chip.textContent()) ?? "", /body_battery$/);
  await chip.click();
  await s.page.locator(".popover-body.pop .pop-grid.icons button[aria-label=steps]").click();
  let after = await written(s, base);
  assert.match(lines(after, "hr_icon"), /icon: steps/);
  await s.expectText(chip, /steps$/);
  await undoTo(s, base, "the icon");

  await s.openExample("features/vector-text");
  await s.waitFace();
  await s.waitIdle();
  base = await s.doc();
  await s.selectLayer("wordmark");
  const curve = s.topField("curve");
  assert.equal(await s.childField("curve", "style").locator("select").inputValue(), "radial");
  const angle = s.childField("curve", "angle").locator("input");
  assert.equal(await angle.inputValue(), "165");
  await angle.fill("180");
  await angle.press("Enter");
  after = await written(s, base);
  assert.match(lines(after, "wordmark"), /curve:\n      style: radial\n      angle: 180deg\n      radius: 60%r/, lines(after, "wordmark"));
  await s.childField("curve", "direction").locator("select").selectOption("clockwise");
  after = await written(s, after);
  assert.match(lines(after, "wordmark"), /direction: clockwise/);
  assert.equal(await curve.locator(".children .field").count(), 4);
  await s.undo();
  await undoTo(s, base, "the curve");
  assert.deepEqual(s.errors, []);
});
