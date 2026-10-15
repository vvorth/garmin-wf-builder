// The data editors against the real worker, each change read back from the
// YAML text: a text template's chips (a data chip added, its spec picked,
// two chips reordered by dragging), a colour that follows data built in
// rows and drawn, a `visible:` switched between its rows and its
// expression, and a text's own font resized with its handle on the face.

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

h.test("a template's chips: + data, a spec picked for it, and two chips reordered by dragging", async (s) => {
  await s.openExample("showcase");
  await s.waitFace();
  await s.waitIdle();
  let doc = await s.doc();
  await s.selectLayer("weather_now");
  const template = s.topField("text").locator(".template");
  assert.deepEqual(await template.locator(".tpl-chip").evaluateAll((cs) => cs.map((c) => c.className)), ["tpl-chip tpl-data", "tpl-chip tpl-text"]);
  // a data chip at the end
  await template.locator("select[aria-label='add data']").selectOption("activity.steps");
  doc = await written(s, doc);
  assert.match(lines(doc, "weather_now"), /text: "\{weather\.feels_like_temperature:d\}°\{activity\.steps\}"/, lines(doc, "weather_now"));
  // its spec, from the number specs its picker offers
  const steps = template.locator(".tpl-chip").nth(2);
  await steps.locator("button.tpl-data-button").click();
  await steps.locator("button.spec", { hasText: /^d$/ }).first().click();
  doc = await written(s, doc);
  assert.match(lines(doc, "weather_now"), /text: "\{weather\.feels_like_temperature:d\}°\{activity\.steps:d\}"/, lines(doc, "weather_now"));
  await s.page.keyboard.press("Escape");
  // the literal "°" dragged onto the first chip goes first
  await template.locator(".tpl-chip").nth(1).locator(".tpl-grip").dragTo(template.locator(".tpl-chip").nth(0));
  doc = await written(s, doc);
  assert.match(lines(doc, "weather_now"), /text: "°\{weather\.feels_like_temperature:d\}\{activity\.steps:d\}"/, lines(doc, "weather_now"));
  await s.expectText(template.locator(".tpl-chip").nth(1).locator(".tpl-expr"), "weather.feels_like_temperature");
  assert.deepEqual(s.errors, []);
});

h.test("a colour built in rows is written as the rule list and drawn; a visible: goes from rows to its expression and back", async (s) => {
  await s.openExample("showcase");
  await s.waitFace();
  await s.waitIdle();
  let doc = await s.doc();
  const layerOps = async (): Promise<string> => JSON.stringify((await s.placed()).frame.layers.find((l) => l.id === "notification_count"));
  const drawnBefore = await layerOps();
  await s.selectLayer("notification_count");
  const color = s.topField("color");
  await color.locator("button", { hasText: "follows data…" }).click();
  await color.locator("select[aria-label=source]").selectOption("system.battery");
  await color.locator("select[aria-label=operator]").selectOption("<");
  const value = color.locator("input[aria-label=value]");
  assert.equal(await value.getAttribute("placeholder"), "percent");
  await s.commit(value, "20");
  await s.page.waitForTimeout(500);
  assert.equal((await s.doc()).text, doc.text, "an incomplete row wrote something");
  // the row's colour, then a new else: each from this face's swatches
  const pick = async (row: string, swatch: string): Promise<void> => {
    await color.locator(row).locator("button.chip-button").click();
    await color.locator(row).locator(`.pop-swatches button[aria-label=${swatch}]`).click();
  };
  await pick(".rule:not(.else)", "orange");
  doc = await written(s, doc);
  assert.match(lines(doc, "notification_count"), /\n {8}color: \[\{ when: "system\.battery < 20", value: color\.orange \}, \{ else: color\.notify \}\]$/m, lines(doc, "notification_count"));
  await pick(".rule.else", "red");
  doc = await written(s, doc);
  assert.match(lines(doc, "notification_count"), /\n {8}color: \[\{ when: "system\.battery < 20", value: color\.orange \}, \{ else: color\.red \}\]$/m, lines(doc, "notification_count"));
  await s.eventually(async () => (await layerOps()) !== drawnBefore, "the frame drawing the new colour");

  // visible: one row; as expression, its text; rows again; a second row writes the rule list
  const visible = s.topField("visible");
  assert.equal(await visible.locator(".rule").count(), 1);
  await visible.locator("button", { hasText: "as expression" }).click();
  await s.expectValue(visible.locator("input[aria-label=expression]"), "device.notification_count > 0");
  assert.equal((await s.doc()).text, doc.text, "switching to the expression wrote something");
  await visible.locator("button", { hasText: /^rows$/ }).click();
  assert.equal(await visible.locator(".rule").count(), 1);
  await visible.locator("button", { hasText: "+ row" }).click();
  await visible.locator(".rule").nth(1).locator("select[aria-label=source]").selectOption("system.charging");
  doc = await written(s, doc);
  assert.match(lines(doc, "notification_count"),
    /\n {8}visible: \[\{ when: "device\.notification_count > 0", value: true \}, \{ when: system\.charging, value: true \}, \{ else: false \}\]$/m, lines(doc, "notification_count"));
  assert.deepEqual(s.errors, []);
});

h.test("a text's own font, written by own font…, resized by dragging its size handle", async (s) => {
  await s.openExample("features/outline");
  await s.waitFace();
  await s.waitIdle();
  let doc = await s.doc();
  await s.selectLayer("clock");
  await s.topField("font").locator("select[aria-label=font]").selectOption("own font…");
  doc = await written(s, doc);
  assert.match(lines(doc, "clock"), /\n {4}font: \{ ?source: assets\/ChivoMono-Bold\.ttf, size: 22%r ?\}$/m, lines(doc, "clock"));
  const before = doc.text;
  const handle = (await s.placed()).handle("clock", "size", "font.size");
  assert.equal(handle.live, null);
  doc = await s.dragHandle("clock", "size", "font.size", 0, -4);
  const size = /\n {4}font: \{ ?source: assets\/ChivoMono-Bold\.ttf, size: ([\d.]+)%r ?\}$/m.exec(lines(doc, "clock"));
  assert.ok(size, lines(doc, "clock"));
  assert.ok(Number(size[1]) > 22, `the font grew: ${size[1]}%r`);
  assert.deepEqual(diffLines(before, doc.text).length, 2, diffLines(before, doc.text).join(" ; "));
  assert.deepEqual(s.errors, []);
});
