// The rest of the editor's surface against the real worker: Layers search,
// lock and hide-in-editor (beside the face, never in its text), "accept
// here…" on a lint warning, a palette colour's label and a colour
// setting's choices added inline. Each change is read back from the YAML
// text, and a hidden element from the pixels the page shows.

import assert from "node:assert/strict";
import type { Summary } from "../src/studio/protocol.ts";
import { diffLines, type Session, suite } from "./harness.ts";

const h = await suite(import.meta.url);

async function written(s: Session, before: Summary): Promise<Summary> {
  const after = await s.waitVersion(before.version);
  await s.waitIdle();
  return after;
}

/** A fresh minimal face, drawn and settled. */
async function minimal(s: Session, name: string): Promise<Summary> {
  await s.openTemplate("minimal", name);
  await s.waitFace();
  await s.waitIdle();
  return s.doc();
}

/** The Layers rows shown, by id, top to bottom. */
async function rows(s: Session): Promise<string[]> {
  return s.page.locator(".layers .item").evaluateAll((els) => els.map((e) => e.querySelector("span")!.textContent!));
}

/** The frame image's pixel the page shows at device pixel (`x`, `y`), as `[r, g, b]`. */
async function shownPixel(s: Session, width: number, x: number, y: number): Promise<number[]> {
  return s.page.evaluate(([width, x, y]) => {
    const img = document.querySelector(".canvas img.frame") as HTMLImageElement;
    const c = document.createElement("canvas");
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const ctx = c.getContext("2d")!;
    ctx.drawImage(img, 0, 0);
    const k = img.naturalWidth / width!;
    return [...ctx.getImageData(Math.floor(x! * k), Math.floor(y! * k), 1, 1).data.slice(0, 3)];
  }, [width, x, y]);
}

/** Until the page shows `want` (true: any ink, false: black) at device pixel (`x`, `y`). */
async function waitPixel(s: Session, width: number, x: number, y: number, inked: boolean): Promise<void> {
  await s.eventually(async () => (await shownPixel(s, width, x, y)).some((v) => v > 0) === inked, `the pixel at (${x}, ${y}) ${inked ? "inked" : "black"}`, 15_000);
}

h.test("Layers search narrows the rows to the ids and types holding it and clears with Escape or ×, the selection kept", async (s) => {
  await minimal(s, "Search");
  await s.selectLayer("clock");
  const all = await rows(s);
  assert.deepEqual(all, ["background", "clock", "seconds"]);
  const search = s.page.locator(".layers .layer-search input");
  await search.fill("SEC");
  await s.eventually(async () => JSON.stringify(await rows(s)) === JSON.stringify(["seconds"]), "only seconds shown");
  // a type matches too, and a block with nothing is left out
  await search.fill("rectangle");
  await s.eventually(async () => JSON.stringify(await rows(s)) === JSON.stringify(["background"]), "only the rectangle shown");
  assert.deepEqual(await s.page.locator(".layers .tree .block").allTextContents(), ["static"]);
  // the selection stayed on clock throughout
  await s.waitInspected("clock");
  await search.press("Escape");
  await s.eventually(async () => JSON.stringify(await rows(s)) === JSON.stringify(all), "every row again after Escape");
  assert.equal(await search.inputValue(), "");
  assert.match((await s.layerRow("clock").getAttribute("class")) ?? "", /\bselected\b/);
  await search.fill("zzz");
  await s.expectText(s.page.locator(".layers"), /no element's id or type holds/);
  await s.page.locator(".layers .layer-search button[aria-label='clear the search']").click();
  await s.eventually(async () => JSON.stringify(await rows(s)) === JSON.stringify(all), "every row again after ×");
  assert.deepEqual(s.errors, []);
});

h.test("a locked element is passed over on the canvas, never dragged, and Properties still edits it; unlocked it drags", async (s) => {
  const base = await minimal(s, "Lock");
  await s.leftTab("Layers");
  const p = await s.placed();
  const pt = await p.ink("seconds");
  const on = p.at(pt.x, pt.y);
  // locked: seconds, and what lies under it (the clock's box and the full-screen background), so a press there reaches nothing
  for (const id of ["seconds", "clock", "background"]) await s.page.locator(`.layers button[aria-label='lock ${id}']`).click();
  await s.eventually(async () => (await s.page.locator(".layers button[aria-label='lock seconds']").getAttribute("aria-pressed")) === "true", "seconds locked");
  await s.drag(on, { x: on.x + 30, y: on.y + 20 });
  await s.page.waitForTimeout(1500);
  await s.waitIdle();
  let doc = await s.doc();
  assert.equal(doc.version, base.version, "nothing was written");
  assert.equal(doc.text, base.text);
  // nor is it picked: the press selected nothing
  assert.equal(await s.page.locator(".layers .item.selected").count(), 0);
  // the lock is not in the face
  assert.doesNotMatch(doc.text, /\block(ed)?\b/);
  // still selected from Layers and edited in Properties
  await s.selectLayer("seconds");
  await s.commit(s.childField("at", "dy").locator("input").first(), "20");
  doc = await written(s, doc);
  assert.match(doc.text, /^    at: \{ anchor: center, dy: 20%r \}$/m, diffLines(base.text, doc.text).join(" ; "));
  // unlocked, the same drag moves it
  await s.page.locator(".layers button[aria-label='lock seconds']").click();
  await s.eventually(async () => (await s.page.locator(".layers button[aria-label='lock seconds']").getAttribute("aria-pressed")) === "false", "seconds unlocked");
  const moved = await s.dragElement("seconds", 10, 0, { alt: true });
  assert.notEqual(moved.version, doc.version);
  assert.match(moved.text, /^    at: \{ anchor: center, dy: 20%r, dx: /m, diffLines(doc.text, moved.text).join(" ; "));
  assert.deepEqual(s.errors, []);
});

h.test("a hidden element is left out of the editor's frame, its text untouched, and stays hidden after a reload", async (s) => {
  const base = await minimal(s, "Hide");
  await s.leftTab("Layers");
  const p = await s.placed();
  const ink = await p.ink("seconds");
  const width = p.frame.width;
  await waitPixel(s, width, ink.x, ink.y, true);
  await s.page.locator(".layers button[aria-label='hide seconds']").click();
  await waitPixel(s, width, ink.x, ink.y, false);
  assert.match((await s.layerRow("seconds").getAttribute("class")) ?? "", /\bhidden-row\b/);
  // the clock still draws
  const clock = await p.ink("clock");
  await waitPixel(s, width, clock.x, clock.y, true);
  await s.waitIdle();
  assert.equal((await s.doc()).text, base.text);
  // reopened, the face is drawn without it again
  await s.page.reload();
  await s.page.waitForSelector(".editor", { timeout: 30_000 });
  await s.waitFace();
  await waitPixel(s, width, ink.x, ink.y, false);
  await s.leftTab("Layers");
  assert.match((await s.layerRow("seconds").getAttribute("class")) ?? "", /\bhidden-row\b/);
  // shown again
  await s.page.locator(".layers button[aria-label='hide seconds']").click();
  await waitPixel(s, width, ink.x, ink.y, true);
  assert.equal((await s.doc()).version, base.version);
  assert.deepEqual(s.errors, []);
});

h.test("accept here… writes the element's lint: block with the reason typed, and the warning count drops", async (s) => {
  const made = await minimal(s, "Accept");
  // the seconds pushed off the dial: an off-screen warning on it
  await s.api("edit", { id: made.id, version: made.version, edit: { op: "set", path: ["elements", "seconds", "at"], value: { anchor: "center", dx: "300%r" } } });
  await s.page.reload();
  await s.page.waitForSelector(".editor", { timeout: 30_000 });
  await s.waitIdle();
  const before = await s.doc();
  const warnings = (d: Summary): number => d.diagnostics.filter((x) => x.severity === "warning").length;
  const offScreen = (d: Summary): number => d.diagnostics.filter((x) => x.code === "off-screen").length;
  assert.ok(offScreen(before) > 0);
  const row = s.page.locator(".diags li").filter({ hasText: "falls outside" }).first();
  await row.locator("button.accept").click();
  const reason = s.page.locator(".diags .accept-form input.reason");
  await reason.waitFor();
  assert.equal(await reason.inputValue(), "");
  await reason.fill("a readout left off the dial on purpose");
  await reason.press("Enter");
  const doc = await written(s, before);
  assert.match(doc.text, /^    lint: \{ allow: \[off-screen\], reason: a readout left off the dial on purpose \}$/m, diffLines(before.text, doc.text).join(" ; "));
  assert.equal(offScreen(doc), 0);
  assert.ok(warnings(doc) < warnings(before));
  assert.equal(doc.history.undo, "accept off-screen on seconds");
  await s.expectText(s.page.locator(".lower-section .tabs button").first(), new RegExp(`⚠ ${warnings(doc)}`));
  assert.deepEqual(s.errors, []);
});

h.test("a palette label writes the long form and, cleared, the bare colour; a colour setting's choice is added and moved inline", async (s) => {
  const base = await minimal(s, "Labels");
  await s.faceSection("Colours");
  const label = s.page.locator("input[aria-label='label of dim']");
  await s.commit(label, "Dim grey");
  let doc = await written(s, base);
  assert.match(doc.text, /^    dim: \{ value: "#AAAAAA", label: Dim grey \}$/m, diffLines(base.text, doc.text).join(" ; "));
  await s.expectValue(s.page.locator("input[aria-label='label of dim']"), "Dim grey");
  await s.commit(s.page.locator("input[aria-label='label of dim']"), "");
  doc = await written(s, doc);
  assert.equal(doc.text, base.text, diffLines(base.text, doc.text).join(" ; "));

  await s.faceSection("Colour settings");
  const body = s.page.locator(".face-section-body");
  await body.locator("button", { hasText: "+ Accent colour" }).click();
  doc = await written(s, doc);
  assert.match(doc.text, /accent_color: \{ default: color\.bg, choices: \[color\.bg\] \}/, diffLines(base.text, doc.text).join(" ; "));
  const axis = body.locator(".axis").first();
  await axis.locator(".axis-add button.chip-button").click();
  await s.page.locator(".popover-body.pop .pop-swatches button[aria-label=text]").click();
  doc = await written(s, doc);
  assert.match(doc.text, /accent_color: \{ default: color\.bg, choices: \[color\.bg, color\.text\] \}/);
  await axis.locator(".axis-choice button[aria-label='move text up']").click();
  doc = await written(s, doc);
  assert.match(doc.text, /accent_color: \{ default: color\.bg, choices: \[color\.text, color\.bg\] \}/);
  assert.deepEqual(await axis.locator(".axis-choice > span:nth-child(2)").allTextContents(), ["text", "bg"]);
  assert.deepEqual(s.errors, []);
});
