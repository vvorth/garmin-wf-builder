// The canvas's gestures against the real worker: on `features/shapes` and
// the showcase (a zip with its fonts), every element type present is
// selected and moved, each handle writes its key, the arrows nudge, a group
// and a multi-selection move as one change, a thin bar's centre moves it, a
// polygon's move is refused with the documented message, and Undo restores
// the text byte for byte after each gesture.

import assert from "node:assert/strict";
import type { Summary } from "../src/studio/protocol.ts";
import { diffLines, type Session, suite } from "./harness.ts";

const h = await suite(import.meta.url);

/** The element `id`'s own lines of `text`. */
function elementLines(doc: Summary, id: string): string {
  const nodes: { id: string; line: number; end: number }[] = [];
  const walk = (list: Summary["tree"][number]["children"]): void => list.forEach((n) => { nodes.push(n); walk(n.children); });
  doc.tree.forEach((b) => walk(b.children));
  const node = nodes.find((n) => n.id === id);
  assert.ok(node, `${id} is not in the tree`);
  return doc.text.split("\n").slice(node.line - 1, node.end).join("\n");
}

/** Undo, then the text must be byte-identical to `before`; the face after. */
async function undoBack(s: Session, before: Summary, what: string): Promise<Summary> {
  const after = await s.undo();
  assert.equal(after.text, before.text, `undo after ${what} did not restore the text: ${diffLines(before.text, after.text).join(" ; ")}`);
  return after;
}

/** Select `id` in Layers and check Properties and the canvas's box agree it is `type`. */
async function selectAndCheck(s: Session, id: string, type: string): Promise<void> {
  await s.selectLayer(id, []);
  assert.equal(await s.page.locator(".inspector .ins-head .name").textContent(), id);
  assert.equal(await s.page.locator(".inspector .ins-head > .dim").first().textContent(), type);
  const where = await s.page.locator(".props-section .where").textContent();
  assert.match(where ?? "", /line \d+/, `${id}'s place is not shown`);
}

h.test("shapes: each type selects, moves and undoes byte for byte", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const types: [string, string][] = [["background", "rectangle"], ["outer_arc", "arc"], ["card", "rectangle"], ["label", "text"], ["pill", "ellipse"], ["chevron", "polygon"], ["dot", "circle"], ["rule", "line"]];
  for (const [id, type] of types) await selectAndCheck(s, id, type);

  for (const [id, type] of types.filter(([id]) => !["background", "chevron"].includes(id))) {
    const before = await s.doc();
    const hint = { value: null as string | null };
    const p = await s.placed();
    const from = await p.ink(id);
    const start = p.at(from.x, from.y);
    hint.value = await s.drag(start, { x: start.x + 12 * p.zoom, y: start.y + 8 * p.zoom });
    assert.match(hint.value ?? "", /px · snapping/, `${id}: no drag hint while dragging`);
    const after = await s.waitVersion(before.version);
    await s.waitIdle();
    const diff = diffLines(before.text, after.text);
    assert.ok(diff.length >= 1, `${id} (${type}): the move wrote nothing`);
    assert.ok(diff.every((l) => /\b(at|to):/.test(l)), `${id} (${type}): a move changed more than at:/to:: ${diff.join(" ; ")}`);
    assert.equal(diff.filter((l) => l.startsWith("+")).length, type === "line" ? 2 : 1, `${id}: ${diff.join(" ; ")}`);
    assert.notEqual(elementLines(before, id), elementLines(after, id), `${id}: its own lines did not change`);
    assert.match(after.history.undo ?? "", new RegExp(`^move ${id} by \\(\\+?-?\\d+, \\+?-?\\d+\\) px on fenix8solar47mm$`), `history label: ${after.history.undo}`);
    assert.equal(await s.page.locator(".topbar .undo-group button").first().getAttribute("title"), `Undo: ${after.history.undo} (Ctrl+Z)`);
    await undoBack(s, before, `moving ${id}`);
  }
  assert.deepEqual(s.errors, []);
});

h.test("shapes: the size, radius, angle and line-end handles each write their key", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();

  // a rectangle's width edge
  await s.selectLayer("card");
  let after = await s.dragHandle("card", "size", "size.width", 20, 0);
  let diff = diffLines(base.text, after.text);
  assert.equal(diff.length, 2, `the width handle: ${diff.join(" ; ")}`);
  assert.match(diff.find((l) => l.startsWith("+")) ?? "", /^\+\d+:\s+size: \{ width: \d+%, height: 20% \}$/, `the width handle: ${diff.join(" ; ")}`);
  assert.ok(!/width: 46%/.test(elementLines(after, "card")), "card's width stayed 46%");
  await undoBack(s, base, "the width handle");

  // its height edge
  await s.selectLayer("card");
  after = await s.dragHandle("card", "size", "size.height", 0, 14);
  assert.ok(!/height: 20%/.test(elementLines(after, "card")), "card's height stayed 20%");
  assert.ok(/width: 46%/.test(elementLines(after, "card")), "the height handle changed the width");
  await undoBack(s, base, "the height handle");

  // a circle's radius, from its right
  await s.selectLayer("dot");
  after = await s.dragHandle("dot", "size", "radius", 10, 0);
  assert.match(elementLines(after, "dot"), /radius: (1[0-9]|[5-9])px/, `dot's radius: ${elementLines(after, "dot")}`);
  await undoBack(s, base, "the radius handle");

  // an arc's angles: each end, along the circle
  await s.selectLayer("outer_arc");
  const p = await s.placed();
  const start = p.handle("outer_arc", "angle", "start_angle");
  const r = Math.hypot(start.x - start.cx!, start.y - start.cy!);
  const along = (deg: number) => ({ x: start.cx! + r * Math.sin((deg * Math.PI) / 180), y: start.cy! - r * Math.cos((deg * Math.PI) / 180) });
  const to = along(start.start! + 18);
  after = await s.dragElement("outer_arc", to.x - start.x, to.y - start.y, { from: { x: start.x, y: start.y } });
  assert.ok(!/start_angle: 210deg/.test(elementLines(after, "outer_arc")), "start_angle stayed 210deg");
  assert.match(elementLines(after, "outer_arc"), /sweep: 300deg/, "the start handle changed the sweep");
  await undoBack(s, base, "the start_angle handle");

  await s.selectLayer("outer_arc");
  const sweep = p.handle("outer_arc", "angle", "sweep");
  const end = along(start.start! + sweep.sweep! - 24);
  after = await s.dragElement("outer_arc", end.x - sweep.x, end.y - sweep.y, { from: { x: sweep.x, y: sweep.y } });
  assert.match(elementLines(after, "outer_arc"), /start_angle: 210deg/, "the sweep handle changed start_angle");
  assert.ok(!/sweep: 300deg/.test(elementLines(after, "outer_arc")), "sweep stayed 300deg");
  await undoBack(s, base, "the sweep handle");

  // a line's ends: `to`, then `at`
  await s.selectLayer("rule");
  after = await s.dragHandle("rule", "end", "to", 0, 12);
  diff = diffLines(base.text, after.text);
  assert.ok(diff.some((l) => l.startsWith("+") && /^\+\d+:\s+to: /.test(l)), `the to handle: ${diff.join(" ; ")}`);
  assert.ok(!diff.some((l) => /^\+\d+:\s+at: /.test(l)), `the to handle moved at: too: ${diff.join(" ; ")}`);
  await undoBack(s, base, "the to handle");
  await s.selectLayer("rule");
  after = await s.dragHandle("rule", "end", "at", 0, -12);
  diff = diffLines(base.text, after.text);
  assert.ok(diff.some((l) => /^\+\d+:\s+at: /.test(l)) && !diff.some((l) => /^\+\d+:\s+to: /.test(l)), `the at handle: ${diff.join(" ; ")}`);
  await undoBack(s, base, "the at handle");
  assert.deepEqual(s.errors, []);
});

h.test("shapes: arrows nudge the selection by one pixel, ten with Shift", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  await s.selectLayer("dot");
  await s.page.keyboard.press("ArrowRight");
  let after = await s.waitVersion(base.version);
  await s.waitIdle();
  assert.match(elementLines(after, "dot"), /at: \{ anchor: center, dx: 1(px|%r) \}/, elementLines(after, "dot"));
  assert.equal(after.history.undo, "move dot by (+1, +0) px on fenix8solar47mm");
  assert.deepEqual((await s.placed()).item("dot").center, [131, 130], "the dot did not land one pixel right");
  await s.page.keyboard.press("Shift+ArrowDown");
  after = await s.waitVersion(after.version);
  await s.waitIdle();
  assert.match(elementLines(after, "dot"), /at: \{ anchor: center, dx: 1(px|%r), dy: \d+(\.\d+)?(px|%r) \}/, elementLines(after, "dot"));
  assert.equal(after.history.undo, "move dot by (+0, +10) px on fenix8solar47mm");
  // the canvas's box followed: the dot sits 1 right and 10 down
  const p = await s.placed();
  assert.deepEqual(p.item("dot").center, [131, 140]);
  await s.undo();
  await undoBack(s, base, "two nudges");
  assert.deepEqual(s.errors, []);
});

h.test("shapes: a polygon's move is refused with the documented message", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  const t = Date.now();
  const after = await s.dragElement("chevron", 15, 0);
  assert.equal(after.text, base.text, `the polygon moved: ${diffLines(base.text, after.text).join(" ; ")}`);
  assert.equal(after.version, base.version);
  const toast = await s.waitToast(t, /polygon/);
  assert.equal(toast, "chevron is a polygon: move its points: in the text");
  assert.ok((await s.messageLog()).some((m) => m.includes("chevron is a polygon")), "the Messages log did not keep the refusal");
  assert.equal(await s.page.locator(".topbar .undo-group button").first().isDisabled(), true, "Undo is offered after a refused move");
  assert.deepEqual(s.errors, []);
});

h.test("showcase: each type selects and moves; a thin bar's centre moves it; a group and a selection move as one change", async (s) => {
  await s.openExample("showcase");
  await s.waitFace();
  await s.waitIdle();
  const style = s.page.locator(".controls label", { hasText: "Style" }).locator("select");

  // the digital layout: data, text, icon, graph, group, gauge, line
  await style.selectOption("digital_dark");
  await s.waitIdle();
  for (const [id, type] of [["left_register", "data"], ["hours", "text"], ["weather_icon", "icon"], ["hr_graph", "graph"], ["bb_cluster", "group"], ["steps_bar", "gauge"], ["battery_arc_l", "gauge"], ["sep_top", "line"]] as const) {
    await selectAndCheck(s, id, type);
  }
  for (const id of ["left_register", "hours", "weather_icon", "hr_graph", "steps_bar"]) {
    const before = await s.doc();
    const after = await s.dragElement(id, 9, 6);
    assert.notEqual(after.version, before.version, `${id}: the move was not written: ${(await s.toastsSince(0)).join(" | ")}`);
    const diff = diffLines(before.text, after.text);
    assert.ok(diff.every((l) => /\bat:/.test(l)) && diff.length === 2, `${id}: ${diff.join(" ; ")}`);
    if (id === "steps_bar") {
      // 156x4 px: a press on its middle is a move, not a resize
      assert.ok(!diff.some((l) => /size:|height:/.test(l)), `the thin bar was resized: ${diff.join(" ; ")}`);
      assert.match(after.history.undo ?? "", /^move steps_bar by /);
    }
    await undoBack(s, before, `moving ${id}`);
  }

  // the group: its move handle moves it and everything in it, as one change
  {
    const before = await s.doc();
    await s.selectLayer("bb_cluster");
    const p = await s.placed();
    const box = p.item("bb_cluster").box;
    const grip = p.at(box[0] + box[2] / 2, box[1]);
    // Alt: placed freely, so the children's shift on the frame is exactly the drag's
    await s.drag(grip, { x: grip.x + 10 * p.zoom, y: grip.y + 5 * p.zoom }, { alt: true });
    const after = await s.waitVersion(before.version);
    await s.waitIdle();
    assert.notEqual(elementLines(before, "bb_cluster").split("\n")[3], elementLines(after, "bb_cluster").split("\n")[3]);
    const diff = diffLines(before.text, after.text);
    assert.equal(diff.filter((l) => l.startsWith("+")).length, 1, `a group move should write its own at: only: ${diff.join(" ; ")}`);
    assert.equal(elementLines(before, "hr_icon"), elementLines(after, "hr_icon"), "a child's own at: changed with the group's");
    const q = await s.placed();
    const shift = (id: string) => [q.item(id).box[0] - p.item(id).box[0], q.item(id).box[1] - p.item(id).box[1]];
    // the group's box and its child both follow the drag; a `%` offset may round the two a pixel apart
    for (const id of ["bb_cluster", "hr_icon"]) {
      const [dx, dy] = shift(id);
      assert.ok(Math.abs(dx! - 10) <= 1 && Math.abs(dy! - 5) <= 1, `${id} landed ${dx}, ${dy} from where it was, not near (10, 5)`);
    }
    await undoBack(s, before, "the group move");
  }

  // two elements chosen in Layers (Ctrl-click) move together, one Undo
  {
    const before = await s.doc();
    await s.selectLayer("weather_icon");
    await s.selectLayer("hr_graph_icon", ["Control"]);
    assert.equal(await s.page.locator(".layers .item.selected").count(), 2);
    assert.match((await s.page.locator(".props-section h3").textContent()) ?? "", /2 selected/);
    const p = await s.placed();
    const from = await p.ink("weather_icon");
    const start = p.at(from.x, from.y);
    await s.drag(start, { x: start.x + 8 * p.zoom, y: start.y });
    const after = await s.waitVersion(before.version);
    await s.waitIdle();
    assert.notEqual(elementLines(before, "weather_icon"), elementLines(after, "weather_icon"), "weather_icon did not move");
    assert.notEqual(elementLines(before, "hr_graph_icon"), elementLines(after, "hr_graph_icon"), "hr_graph_icon did not move with the selection");
    assert.match(after.history.undo ?? "", /^move /);
    await undoBack(s, before, "the selection's move");
  }

  // the analog layout: pattern, hands, arc, circle
  await style.selectOption("analog_dark");
  await s.waitIdle();
  for (const [id, type] of [["minute_ticks", "pattern"], ["analog_hands", "hands"], ["dial_ring", "arc"], ["center_pin", "circle"], ["top_data", "group"]] as const) {
    await selectAndCheck(s, id, type);
  }
  for (const id of ["analog_hands", "bottom_data"]) {
    const before = await s.doc();
    const after = await s.dragElement(id, 6, 7);
    assert.notEqual(after.version, before.version, `${id}: the move was not written: ${(await s.toastsSince(0)).join(" | ")}`);
    assert.notEqual(elementLines(before, id), elementLines(after, id));
    await undoBack(s, before, `moving ${id}`);
  }
  assert.deepEqual(s.errors, []);
});
