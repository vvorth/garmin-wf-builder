// The Layers panel against the real worker: every type added (with the
// series, slot and set pickers; a live type added with a `static:` element
// selected lands in `elements:`), the order buttons, a row dragged onto
// another, move to…, group and ungroup, duplicate, delete, copy and paste,
// and Ctrl+A. Each change is read back from the YAML text and from the tree.

import assert from "node:assert/strict";
import type { Summary, TreeNode } from "../src/studio/protocol.ts";
import { diffLines, type Session, suite } from "./harness.ts";

const h = await suite(import.meta.url);

/** Every element of the tree, flat, in draw order. */
function nodes(doc: Summary): TreeNode[] {
  const out: TreeNode[] = [];
  const walk = (list: readonly TreeNode[]): void => list.forEach((n) => { out.push(n); walk(n.children); });
  doc.tree.forEach((b) => walk(b.children));
  return out;
}

/** The ids of the block at `path`, in order. */
function blockIds(doc: Summary, path: string): string[] {
  return nodes(doc).filter((n) => n.path.slice(0, -1).join(".") === path).map((n) => n.id);
}

function node(doc: Summary, id: string): TreeNode {
  const found = nodes(doc).find((n) => n.id === id);
  assert.ok(found, `${id} is not in the tree`);
  return found;
}

async function written(s: Session, before: Summary): Promise<Summary> {
  const after = await s.waitVersion(before.version);
  await s.waitIdle();
  return after;
}

/** The Layers rows as shown, top to bottom: `id` or `id/type`. */
async function rows(s: Session): Promise<string[]> {
  return s.page.locator(".layers .item").evaluateAll((els) => els.map((e) => e.querySelector("span")!.textContent!));
}

h.test("+ add… adds every type, with its picker; a live type beside a static element goes to elements:", async (s) => {
  await s.openExample("showcase");
  await s.waitFace();
  await s.waitIdle();
  await s.leftTab("Layers");
  const types = (await s.page.locator(".layers .add-bar select").first().locator("option").allTextContents()).filter((t) => t !== "+ add…");
  assert.ok(types.length >= 14, `few types: ${types.join(", ")}`);
  const pickers: Record<string, string> = { graph: "series", data: "slot", hands: "set" };
  let doc = await s.doc();
  const added: string[] = [];
  for (const type of types) {
    const before = doc;
    const bar = s.page.locator(".layers .add-bar");
    await bar.locator("select").first().selectOption(type);
    if (pickers[type]) {
      const picker = bar.locator("select").nth(1);
      assert.equal((await picker.locator("option").first().textContent())?.trim(), `${pickers[type]}…`, `${type}'s picker`);
      const options = (await picker.locator("option").allTextContents()).slice(1);
      assert.ok(options.length > 0, `${type}: nothing to pick`);
      assert.equal(await bar.locator("button.primary").isDisabled(), true, `${type}: Add enabled before its choice`);
      await picker.selectOption(options[0]!);
    }
    await bar.locator("button.primary", { hasText: "Add" }).click();
    doc = await written(s, before);
    const id = `new_${type}`;
    added.push(id);
    assert.match(doc.history.undo ?? "", new RegExp(`^add .*${id}`), doc.history.undo ?? "");
    assert.ok(new RegExp(`^  ${id}:\\n    type: ${type}\\n`, "m").test(doc.text), `${id} is not in the text as written: ${diffLines(before.text, doc.text).join(" ; ")}`);
    // the new element is selected, and drawn in front of the last selection: after it in the block
    await s.waitInspected(id);
    assert.match((await s.layerRow(id).getAttribute("class")) ?? "", /\bselected\b/);
    assert.equal(doc.loads, true, `${type} added leaves the face unloadable: ${doc.diagnostics.filter((d) => d.severity === "error").map((d) => d.message).join("; ")}`);
  }
  assert.deepEqual(blockIds(doc, "elements").slice(-added.length), added, "each new element goes in front of (after) the one before it");

  // with a static element selected, a type that cannot be static lands at the front of elements:
  await s.selectLayer("background");
  const before = doc;
  await s.page.locator(".layers .add-bar select").first().selectOption("gauge");
  await s.page.locator(".layers .add-bar button.primary").click();
  doc = await written(s, before);
  assert.equal(node(doc, "new_gauge2").path.join("."), "elements.new_gauge2");
  assert.ok(!blockIds(doc, "static").includes("new_gauge2"));
  assert.equal(blockIds(doc, "elements").at(-1), "new_gauge2", "the live type did not go to the front of elements:");
  // a shape beside it stays in static:
  await s.selectLayer("background");
  await s.page.locator(".layers .add-bar select").first().selectOption("circle");
  await s.page.locator(".layers .add-bar button.primary").click();
  doc = await written(s, doc);
  assert.deepEqual(blockIds(doc, "static"), ["background", "new_circle2", "left_card", "right_card"]);
  assert.deepEqual(s.errors, []);
});

h.test("reorder, drag a row, move to…, group, ungroup, duplicate, delete", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  const order = ["background", "outer_arc", "accent_arc", "card", "card_inner", "label", "pill", "pill_outline", "chevron", "dot", "rule"];
  assert.deepEqual(blockIds(base, "elements"), order);
  assert.deepEqual(await rows(s), order);

  // ↑ sends backward (drawn earlier), ↓ brings forward; Ctrl+[ and Ctrl+] the same
  await s.selectLayer("dot");
  await s.page.locator(".layers .actions button[title^='Send backward']").click();
  let doc = await written(s, base);
  assert.deepEqual(blockIds(doc, "elements").slice(8), ["dot", "chevron", "rule"]);
  assert.deepEqual((await rows(s)).slice(8), ["dot", "chevron", "rule"], "the rows did not follow the text");
  await s.page.locator(".layers .actions button[title^='Bring forward']").click();
  doc = await written(s, doc);
  assert.deepEqual(blockIds(doc, "elements"), order);
  // a moved element takes its lines and comment with it; a blank line between two may change sides
  const squeezed = (t: string) => t.replace(/\n\n+/g, "\n");
  assert.equal(squeezed(doc.text), squeezed(base.text), `back and forth changed more than blank lines: ${diffLines(base.text, doc.text).join(" ; ")}`);
  await s.page.keyboard.press("Control+]");
  doc = await written(s, doc);
  assert.deepEqual(blockIds(doc, "elements").slice(8), ["chevron", "rule", "dot"]);
  await s.page.keyboard.press("Control+[");
  doc = await written(s, doc);
  assert.deepEqual(blockIds(doc, "elements"), order, "Ctrl+[ did not put dot back");
  // four undos: the text as opened, byte for byte
  for (let i = 0; i < 4; i++) doc = await s.undo();
  assert.equal(doc.text, base.text, `four undos: ${diffLines(base.text, doc.text).join(" ; ")}`);

  // a row dragged onto the upper half of another goes behind it
  await s.layerRow("rule").dragTo(s.layerRow("card"), { targetPosition: { x: 20, y: 3 } });
  doc = await written(s, doc);
  assert.deepEqual(blockIds(doc, "elements").slice(2, 5), ["accent_arc", "rule", "card"], `drag onto a row: ${blockIds(doc, "elements")}`);
  assert.match(doc.history.undo ?? "", /^move rule /);
  await s.undo();

  // move to… a block: the static block, listed empty until something goes in
  await s.selectLayer("dot");
  assert.equal(await s.page.locator(".layers .block", { hasText: "static" }).count(), 1);
  const to = s.page.locator(".layers .actions select");
  assert.deepEqual(await to.locator("option").allTextContents(), ["move to…", "static"]);
  await to.selectOption({ label: "static" });
  doc = await written(s, doc);
  assert.deepEqual(blockIds(doc, "static"), ["dot"]);
  // the element takes its comment along, into a static: block written after elements:
  assert.match(doc.text, /\n\nstatic:\n  # The two primitives that were already here, for completeness\.\n  dot:\n    type: circle/, "static: was not written with dot in it");
  assert.deepEqual((await rows(s)).slice(0, 1), ["dot"]);
  await s.undo();
  doc = await s.doc();
  assert.equal(doc.text, base.text);

  // group two neighbours (Ctrl-click adds), then ungroup
  await s.selectLayer("card");
  await s.selectLayer("card_inner", ["Control"]);
  assert.match((await s.page.locator(".layers .actions button", { hasText: "Group" }).textContent()) ?? "", /Group \(2\)/);
  await s.page.locator(".layers .actions button", { hasText: "Group" }).click();
  doc = await written(s, doc);
  assert.deepEqual(blockIds(doc, "elements").slice(3, 4), ["group"]);
  assert.deepEqual(node(doc, "group").children.map((n) => n.id), ["card", "card_inner"]);
  assert.match(doc.text, /^  group:\n    type: group\n    children:\n      # An outlined rounded rectangle/m, "the group does not hold its children with their comments");
  assert.equal(await s.page.locator(".inspector .ins-head .name").textContent(), "group");
  // the tree redraws a moment after the text changes, so the nesting is polled
  await s.eventually(async () => (await s.layerRow("card").evaluate((e) => e.closest("ul.tree")!.closest("li")!.querySelector(".item span")!.textContent)) === "group", "card shown under the group");
  // Ctrl+Shift+G ungroups
  await s.page.keyboard.press("Control+Shift+g");
  doc = await written(s, doc);
  assert.equal(doc.text, base.text, `ungroup did not give the text back: ${diffLines(base.text, doc.text).join(" ; ")}`);

  // duplicate: a copy beside it, numbered
  await s.selectLayer("dot");
  await s.page.locator(".layers .actions button", { hasText: "Duplicate" }).click();
  doc = await written(s, doc);
  assert.deepEqual(blockIds(doc, "elements").slice(9, 11), ["dot", "dot_copy"]);
  assert.equal(doc.history.undo, "duplicate dot as dot_copy");
  await s.waitInspected("dot_copy");
  // Ctrl+D too: a copy of the copy, named apart
  await s.page.keyboard.press("Control+d");
  doc = await written(s, doc);
  const ids = blockIds(doc, "elements");
  assert.equal(ids.length, 13);
  assert.match(ids[11] ?? "", /^dot_copy/);

  // delete the selection: the button, then Del on both copies at once
  await s.page.locator(".layers .actions button.danger").click();
  doc = await written(s, doc);
  assert.deepEqual(blockIds(doc, "elements").slice(9, 12), ["dot", "dot_copy", "rule"]);
  assert.equal(await s.page.locator(".inspector .ins-head").count(), 0, "something stays selected after a delete");
  doc = await s.undo();
  await s.selectLayer("dot_copy");
  await s.selectLayer(ids[11]!, ["Control"]);
  assert.equal(await s.page.locator(".layers .item.selected").count(), 2);
  await s.layerRow("dot_copy").press("Delete");
  doc = await written(s, doc);
  assert.equal(doc.text, base.text, `deleting two: ${diffLines(base.text, doc.text).join(" ; ")}`);
  assert.equal(doc.history.undo, `delete dot_copy, ${ids[11]}`);
  assert.deepEqual(s.errors, []);
});

h.test("copy, cut and paste as YAML; Ctrl+A selects everything the frame shows", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  await s.selectLayer("dot");
  // the row has the focus after its click, so the shortcuts act
  const t = Date.now();
  await s.page.keyboard.press("Control+c");
  assert.equal(await s.waitToast(t, /copied/), "copied dot");
  const clip = await s.page.evaluate(() => navigator.clipboard.readText()).catch(() => null);
  if (clip !== null) assert.equal(clip, "dot:\n  type: circle\n  at: { anchor: center }\n  radius: 4px\n  color: color.text\n");
  await s.selectLayer("card");
  await s.page.keyboard.press("Control+v");
  let doc = await written(s, base);
  assert.deepEqual(blockIds(doc, "elements").slice(3, 5), ["card", "dot2"], "the paste did not land in front of the selection, renamed");
  assert.match(doc.text, /^  dot2:\n    type: circle\n    at: \{ anchor: center \}\n    radius: 4px\n    color: color\.text$/m);
  assert.equal(doc.history.undo, "paste dot2");
  assert.equal(await s.page.locator(".inspector .ins-head .name").textContent(), "dot2");
  // cut takes it out again
  await s.page.keyboard.press("Control+x");
  doc = await written(s, doc);
  assert.equal(doc.text, base.text, `cut: ${diffLines(base.text, doc.text).join(" ; ")}`);

  // a paste that needs a colour the face lacks is refused with the reason
  await s.selectLayer("dot");
  await s.page.evaluate(() => {
    const dt = new DataTransfer();
    dt.setData("text/plain", "stray:\n  type: circle\n  at: { anchor: center }\n  radius: 9px\n  color: color.nothing_here\n");
    document.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
  });
  const refused = await s.waitToast(Date.now() - 2000, /nothing_here/);
  assert.match(refused, /nothing_here/);
  assert.equal((await s.doc()).text, base.text);

  // Ctrl+A on the face: every drawn element
  await s.page.locator(".canvas .hit").click({ position: { x: 2, y: 2 } });
  await s.page.keyboard.press("Control+a");
  assert.equal(await s.page.locator(".layers .item.selected").count(), 11);
  assert.match((await s.page.locator(".props-section h3").textContent()) ?? "", /11 selected/);
  // a click on the space around the watch selects nothing
  await s.page.locator(".canvas-wrap").click({ position: { x: 5, y: 5 } });
  assert.equal(await s.page.locator(".layers .item.selected").count(), 0);
  assert.deepEqual(s.errors, []);
});
