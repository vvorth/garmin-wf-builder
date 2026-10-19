// Parts and points against the real worker: the showcase's `vintage` set
// entered from Layers and its hour blade's vertex dragged in the hand's own
// frame; `features/patterns`' `hour_ticks` entered and its tick part moved;
// `features/shapes`' chevron: one vertex dragged, the whole polygon moved
// (every point), a vertex added on a segment and removed again, byte for
// byte; the row's ✓ and Escape leave the frame, and Layers dims every
// other row while it is entered. Every change is read back from the
// YAML text and from the entered frame the worker draws.

import assert from "node:assert/strict";
import type { Frame, FrameItem, Handle, Path, Summary } from "../src/studio/protocol.ts";
import { diffLines, type Session, suite } from "./harness.ts";

const h = await suite(import.meta.url);

/** The entered frame as the page shows it: its parts by id, and where a device pixel is on the screen. */
interface Entered {
  frame: Frame;
  zoom: number;
  at(x: number, y: number): { x: number; y: number };
  item(id: string): FrameItem;
  /** The part's handle of `kind` with `index` (a vertex or segment) or `which` (a key or an end), never a mirrored one. */
  handle(id: string, kind: Handle["kind"], index?: number | string): Handle;
}

/** The frame of the element at `enter`, asked as the page asks it, with the device and style the controls show. */
async function entered(s: Session, enter: Path): Promise<Entered> {
  const id = await s.id();
  const view = await s.page.evaluate(() => {
    const device = (document.querySelector(".controls select") as HTMLSelectElement).value;
    const styleLabel = [...document.querySelectorAll(".controls label")].find((l) => l.textContent!.startsWith("Style"));
    const style = styleLabel ? (styleLabel.querySelector("select") as HTMLSelectElement).value : "";
    const r = document.querySelector(".canvas img.frame")!.getBoundingClientRect();
    return { device, style, rect: { left: r.left, top: r.top, width: r.width } };
  });
  const frame = await s.api("frame", { id, device: view.device, scale: 2, style: view.style, time: "", date: "", asleep: false, aod: false, picks: "", enter });
  assert.ok(frame.local, "the frame is not entered");
  const zoom = view.rect.width / frame.width;
  const item = (id: string): FrameItem => {
    const found = frame.items.find((i) => i.id === id);
    if (!found) throw new Error(`${id} is not in the entered frame: ${frame.items.map((i) => i.id).join(", ")}`);
    return found;
  };
  return {
    frame, zoom, item,
    at: (x, y) => ({ x: view.rect.left + x * zoom, y: view.rect.top + y * zoom }),
    handle: (id, kind, index) => {
      const found = item(id).handles.find((hd) => hd.kind === kind && !hd.mirrored
        && (index === undefined || hd.index === index || hd.after === index || hd.part === index || (Array.isArray(hd.key) ? hd.key.join(".") : hd.key) === index));
      if (!found) throw new Error(`${id} has no ${kind} handle${index !== undefined ? ` ${index}` : ""}: ${JSON.stringify(item(id).handles)}`);
      return found;
    },
  };
}

/** The tree node whose path joined with "/" is `id`, or whose id it is. */
function nodeOf(doc: Summary, id: string): { path: Path; line: number; end: number } {
  const all: { id: string; path: Path; line: number; end: number; children: unknown[] }[] = [];
  const walk = (list: Summary["tree"][number]["children"]): void => list.forEach((n) => { all.push(n); walk(n.children); });
  doc.tree.forEach((b) => walk(b.children));
  const found = all.find((n) => n.path.join("/") === id || n.id === id);
  assert.ok(found, `${id} is not in the tree`);
  return found;
}

/** The lines of `doc.text` the node `id` spans. */
const linesOf = (doc: Summary, id: string): string => { const n = nodeOf(doc, id); return doc.text.split("\n").slice(n.line - 1, n.end).join("\n"); };

/** A drag of `dx`, `dy` device pixels from the device pixel `from`, placed freely (Alt); the face once the change is written or refused. */
async function dragFree(s: Session, p: Entered, from: { x: number; y: number }, dx: number, dy: number): Promise<Summary> {
  const before = await s.doc();
  const start = p.at(from.x, from.y);
  const t = Date.now();
  await s.drag(start, { x: start.x + dx * p.zoom, y: start.y + dy * p.zoom }, { alt: true });
  const deadline = Date.now() + 15_000;
  for (;;) {
    if ((await s.doc()).version !== before.version || (await s.toastsSince(t)).length > 0) break;
    if (Date.now() > deadline) throw new Error("the drag was neither written nor refused in 15 s");
    await s.page.waitForTimeout(100);
  }
  await s.waitIdle();
  return s.doc();
}

/** The `dx`/`dy` of the point `index` of the polygon whose lines are `own`, in `%r` or `%`, 0 when unwritten. */
function point(own: string, index: number): { dx: number; dy: number; unit: string } {
  const lines = own.split("\n").filter((l) => /^\s*-\s*\{/.test(l));
  const line = lines[index];
  assert.ok(line, `no point ${index} in\n${own}`);
  const num = (key: string): [number, string] => { const m = new RegExp(`${key}: (-?[\\d.]+)(%r|%|px)?`).exec(line); return m ? [Number(m[1]), m[2] ?? "px"] : [0, ""]; };
  const [dx, ux] = num("dx"), [dy, uy] = num("dy");
  return { dx, dy, unit: ux || uy };
}

/** The whole-pixel delta `(dx, dy)` on the screen turned into a part's frame drawn at `angle` degrees. */
const toLocal = (dx: number, dy: number, angle: number): [number, number] => {
  const t = (angle * Math.PI) / 180;
  return [dx * Math.cos(t) + dy * Math.sin(t), -dx * Math.sin(t) + dy * Math.cos(t)];
};

/** Enter the element `id` from its Layers row, and wait for the entered frame. */
async function enterFromLayers(s: Session, id: string): Promise<void> {
  await s.leftTab("Layers");
  await s.layerRow(id).locator("button.enter").click();
  await s.layerRow(id).locator("button.done").waitFor({ timeout: 15_000 });
  await s.page.locator(".canvas.entered").waitFor({ timeout: 30_000 });
  await s.waitIdle();
}

const left = async (s: Session): Promise<void> => {
  await s.page.locator(".layers.entering").waitFor({ state: "detached", timeout: 15_000 });
  await s.page.locator(".canvas.entered").waitFor({ state: "detached", timeout: 30_000 });
  await s.waitIdle();
};

h.test("showcase: the vintage set entered from Layers, the hour blade's vertex dragged in the hand's frame, ✓ and Escape", async (s) => {
  await s.openExample("showcase");
  await s.waitFace();
  await s.waitIdle();
  await s.page.locator(".controls label", { hasText: "Style" }).locator("select").selectOption("roman_dark");
  await s.waitIdle();
  const base = await s.doc();
  const handsPath = nodeOf(base, "roman_hands").path;
  const bladeId = "resources/hand_sets/vintage/hour/parts/blade";

  // Layers lists the hands and their parts under the element; its row enters the set
  const partRow = s.page.locator(`.layers .item[data-path="${bladeId}"]`);
  assert.equal(await partRow.count(), 1, "the blade part is not listed under roman_hands");
  assert.equal(await partRow.locator(".type").textContent(), "polygon");
  await enterFromLayers(s, "roman_hands");
  assert.match((await s.layerRow("roman_hands").getAttribute("class")) ?? "", /\bentered\b/);
  let p = await entered(s, handsPath);
  assert.equal(p.frame.local!.element.join("/"), handsPath.join("/"));
  assert.ok(p.frame.items.some((i) => i.id === bladeId), "the frame does not list the blade");
  // the blade part, selected from its row: Properties name the hand and the part, and list its points
  await partRow.click();
  await s.page.waitForFunction(() => document.querySelector(".inspector .ins-head .name")?.textContent === "hour › blade" && document.querySelector(".inspector .field") !== null, null, { timeout: 15_000 });
  assert.equal(await s.topField("points").locator(".list-item").count(), 2);

  // the vertex drag: the screen delta turned into the hand's frame, written in %r
  const blade = p.item(bladeId);
  const angle = blade.angle!;
  assert.equal(angle, p.frame.local!.angle, "the hour hand's angle is the frame's");
  const vertex = p.handle(bladeId, "vertex", 1);
  const before = point(linesOf(base, bladeId), 1);
  assert.deepEqual([before.dx, before.dy, before.unit], [-1.5, -26, "%r"]);
  const [dx, dy] = [6, -4];
  let after = await dragFree(s, p, { x: vertex.x, y: vertex.y }, dx, dy);
  assert.notEqual(after.version, base.version, `the vertex drag was not written: ${(await s.toastsSince(0)).join(" | ")}`);
  assert.match(after.history.undo ?? "", /^move vertex 1 of hour\.blade of roman_hands by \(\+6, -4\) px on fenix8solar47mm$/, after.history.undo ?? "");
  const diff = diffLines(base.text, after.text);
  assert.equal(diff.length, 2, `one point line changes: ${diff.join(" ; ")}`);
  const moved = point(linesOf(after, bladeId), 1);
  const [lx, ly] = toLocal(dx, dy, angle);
  const r = p.frame.local!.radius;
  assert.ok(Math.abs(moved.dx - (before.dx + lx / r)) < 0.6, `dx ${moved.dx} is not near ${before.dx + lx / r}`);
  assert.ok(Math.abs(moved.dy - (before.dy + ly / r)) < 0.6, `dy ${moved.dy} is not near ${before.dy + ly / r}`);
  assert.equal(moved.unit, "%r");
  // the frame's handle followed the drag; the mirrored twin went the other way across the axis
  p = await entered(s, handsPath);
  const landed = p.handle(bladeId, "vertex", 1);
  assert.ok(Math.abs(landed.x - (vertex.x + dx)) <= 1.5 && Math.abs(landed.y - (vertex.y + dy)) <= 1.5, `the vertex landed at ${landed.x}, ${landed.y}, not near ${vertex.x + dx}, ${vertex.y + dy}`);
  assert.equal(p.item(bladeId).handles.filter((hd) => hd.mirrored).length, 2);
  after = await s.undo();
  assert.equal(after.text, base.text, `undo: ${diffLines(base.text, after.text).join(" ; ")}`);

  // while entered, every other row is dimmed but its own; its ✓ leaves the set, and Escape does too
  assert.equal(await s.page.locator(".layers.entering .tree .item.entered.outside").count(), 0);
  assert.ok(await s.page.locator(".layers.entering .tree .item.outside").count() > 0);
  await s.page.locator(".layers .item.entered button.done").click();
  await left(s);
  await enterFromLayers(s, "roman_hands");
  await s.page.locator(".canvas .hit").click({ position: { x: 3, y: 3 } });
  await s.page.keyboard.press("Escape");
  await left(s);
  assert.deepEqual(s.errors, []);
});

h.test("patterns: hour_ticks entered and its tick moved in the copy's frame; count and skip redraw the entered frame", async (s) => {
  await s.openExample("features/patterns");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  const ticksPath = nodeOf(base, "hour_ticks").path;
  const tickId = "static/hour_ticks/parts/tick";
  await enterFromLayers(s, "hour_ticks");
  let p = await entered(s, ticksPath);
  // copy 0 is skipped, so the frame is copy 1's, at 30 degrees
  assert.equal(p.frame.local!.angle, 30);
  const tick = p.item(tickId);
  assert.equal(tick.kind, "rectangle");
  // a press on the tick's body, up its length from the centre and away from its size handles, moves it
  const t = (tick.angle! * Math.PI) / 180, up = 3.6 * p.frame.local!.radius;
  const from = { x: tick.center[0] + up * Math.sin(t), y: tick.center[1] - up * Math.cos(t) };
  const [dx, dy] = [5, 3];
  let after = await dragFree(s, p, from, dx, dy);
  assert.notEqual(after.version, base.version, `the tick's move was not written: ${(await s.toastsSince(0)).join(" | ")}`);
  assert.match(after.history.undo ?? "", /^move tick of hour_ticks by \(\+5, \+3\) px on fenix8solar47mm$/, after.history.undo ?? "");
  const diff = diffLines(base.text, after.text);
  assert.equal(diff.length, 2, `the tick's line alone changes: ${diff.join(" ; ")}`);
  const line = diff.find((l) => l.startsWith("+")) ?? "";
  // the moved `at:` gains a dx beside its dy, both in the part's own %r
  assert.match(line, /tick: \{ type: rectangle, at: \{ (dx|dy): -?[\d.]+%r, (dx|dy): -?[\d.]+%r \}, size: \{ width: 3%r, height: 12%r \} \}$/, line);
  const written = /at: \{ ([^}]*) \}/.exec(line)![1]!;
  const num = (key: string): number => Number((new RegExp(`${key}: (-?[\\d.]+)%r`).exec(written) ?? [])[1] ?? NaN);
  const [lx, ly] = toLocal(dx, dy, tick.angle!);
  assert.ok(Math.abs(num("dx") - lx / p.frame.local!.radius) < 0.6, `dx ${num("dx")}%r is not near ${lx / p.frame.local!.radius}`);
  assert.ok(Math.abs(num("dy") - (-88 + ly / p.frame.local!.radius)) < 0.6, `dy ${num("dy")}%r is not near ${-88 + ly / p.frame.local!.radius}`);
  p = await entered(s, ticksPath);
  const landed = p.item(tickId).center;
  assert.ok(Math.abs(landed[0] - (tick.center[0] + dx)) <= 1.5 && Math.abs(landed[1] - (tick.center[1] + dy)) <= 1.5, `the tick landed at ${landed}, not near ${[tick.center[0] + dx, tick.center[1] + dy]}`);
  after = await s.undo();
  assert.equal(after.text, base.text, `undo: ${diffLines(base.text, after.text).join(" ; ")}`);

  // the pattern itself, selected while entered, keeps the frame: its skip typed away puts copy 0 at 12 o'clock
  await s.selectLayer("hour_ticks");
  assert.equal(await s.page.locator(".canvas.entered").count(), 1, "selecting the entered element left it");
  const skip = s.topField("skip");
  await skip.locator("button[aria-label=remove]").first().click();
  after = await s.waitVersion(base.version);
  await s.waitIdle();
  assert.ok(!/skip: \[0\]/.test(linesOf(after, "hour_ticks")), linesOf(after, "hour_ticks"));
  p = await entered(s, ticksPath);
  assert.equal(p.frame.local!.angle, 0, "the entered frame did not follow the skip");
  await s.undo();
  assert.deepEqual(s.errors, []);
});

h.test("shapes: a chevron vertex dragged, the whole chevron moved, a vertex added on a segment and removed byte for byte", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  await s.selectLayer("chevron");
  let p = await s.placed();
  const chevron = p.item("chevron");
  assert.deepEqual(chevron.handles.filter((hd) => hd.kind === "vertex").map((hd) => hd.index), [0, 1, 2]);
  assert.deepEqual(chevron.handles.filter((hd) => hd.kind === "segment").map((hd) => hd.after), [0, 1, 2]);

  // one vertex: its point alone changes, in the author's %
  const vertex = chevron.handles.find((hd) => hd.kind === "vertex" && hd.index === 1)!;
  assert.ok(vertex);
  let after = await s.dragElement("chevron", 10, 0, { from: { x: vertex.x, y: vertex.y }, alt: true });
  assert.match(after.history.undo ?? "", /^move vertex 1 of chevron by \(\+10, \+0\) px on fenix8solar47mm$/, after.history.undo ?? "");
  let diff = diffLines(base.text, after.text);
  assert.equal(diff.length, 2, diff.join(" ; "));
  assert.match(diff.find((l) => l.startsWith("+")) ?? "", /^\+\d+:\s+- \{ anchor: center, dx: -?[\d.]+%, dy: 34% \}$/, diff.join(" ; "));
  assert.ok(!/dx: -9%, dy: 34%/.test(linesOf(after, "chevron")), "point 1 did not move");
  p = await s.placed();
  const landed = p.item("chevron").handles.find((hd) => hd.kind === "vertex" && hd.index === 1)!;
  assert.ok(Math.abs(landed.x - (vertex.x + 10)) <= 1.5 && Math.abs(landed.y - vertex.y) <= 1.5, `the vertex landed at ${landed.x}, ${landed.y}`);
  after = await s.undo();
  assert.equal(after.text, base.text);

  // the whole polygon: every point moves
  await s.selectLayer("chevron");
  after = await s.dragElement("chevron", 15, 0, { alt: true });
  assert.match(after.history.undo ?? "", /^move chevron by \(\+15, \+0\) px on fenix8solar47mm$/, after.history.undo ?? "");
  diff = diffLines(base.text, after.text);
  assert.equal(diff.filter((l) => l.startsWith("+")).length, 3, `every point moves: ${diff.join(" ; ")}`);
  assert.ok(diff.every((l) => /- \{ anchor: center/.test(l)), diff.join(" ; "));
  after = await s.undo();
  assert.equal(after.text, base.text);

  // a click on a segment handle adds a vertex at its midpoint
  await s.selectLayer("chevron");
  p = await s.placed();
  const segment = p.item("chevron").handles.find((hd) => hd.kind === "segment" && hd.after === 0)!;
  const where = p.at(segment.x, segment.y);
  await s.page.mouse.click(where.x, where.y);
  after = await s.waitVersion(base.version);
  await s.waitIdle();
  assert.equal(after.history.undo, "add a vertex to chevron on fenix8solar47mm");
  diff = diffLines(base.text, after.text);
  assert.equal(diff.length, 1, `one line added: ${diff.join(" ; ")}`);
  assert.match(diff[0]!, /^\+\d+:\s+- \{ anchor: center, dx: -?[\d.]+%, dy: -?[\d.]+% \}$/, diff[0]);
  assert.equal(linesOf(after, "chevron").split("\n").filter((l) => /^\s*- \{/.test(l)).length, 4);
  await s.eventually(async () => (await s.topField("points").locator(".list-item").count()) === 4, "the points list to show four items");
  // the new vertex, clicked, is selected: its item is marked, and Delete removes it
  p = await s.placed();
  const added = p.item("chevron").handles.find((hd) => hd.kind === "vertex" && hd.index === 1)!;
  const at = p.at(added.x, added.y);
  await s.page.mouse.click(at.x, at.y);
  await s.eventually(async () => /\bon\b/.test((await s.topField("points").locator(".list-item").nth(1).getAttribute("class")) ?? ""), "the vertex's item to be marked");
  await s.page.keyboard.press("Delete");
  after = await s.waitVersion(after.version);
  await s.waitIdle();
  assert.equal(after.history.undo, "remove vertex 1 of chevron on fenix8solar47mm");
  assert.equal(after.text, base.text, `add then remove: ${diffLines(base.text, after.text).join(" ; ")}`);
  assert.deepEqual(s.errors, []);
});
