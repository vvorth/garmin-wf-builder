// The view controls against the real worker: the Device and Style selects,
// the zoom, 1:1, the skin, the Preview menu (time, date, now, a slot's pick,
// awake/asleep/AOD on `features/aod`), Ctrl+K, the History tab (go to a
// change, snapshot, restore, open a copy), Download as yaml and as zip, and
// the browser's leave prompt while a change is on its way.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { diffLines, suite } from "./harness.ts";

const h = await suite(import.meta.url);

/** The frame image's source, which changes whenever the worker draws the face differently. */
const frameSrc = (s: { page: { locator: (sel: string) => { getAttribute: (a: string) => Promise<string | null> } } }) => s.page.locator(".canvas img.frame").getAttribute("src");

h.test("the Device and Style selects redraw the face; zoom, 1:1 and the skin size it", async (s) => {
  await s.openExample("showcase");
  await s.waitFace();
  await s.waitIdle();
  const device = s.page.locator(".controls label", { hasText: "Device" }).locator("select");
  const style = s.page.locator(".controls label", { hasText: "Style" }).locator("select");
  assert.equal(await device.inputValue(), "fenix8solar47mm");
  assert.equal(await s.page.locator(".strip button.on").textContent(), "fenix8solar47mm");
  let src = await frameSrc(s);
  await device.selectOption("fr955");
  await s.page.waitForFunction((old) => document.querySelector(".canvas img.frame")?.getAttribute("src") !== old, src, { timeout: 15_000 });
  await s.waitIdle();
  assert.equal(await s.page.locator(".canvas img.frame").getAttribute("alt"), "the face on fr955");
  assert.equal((await s.placed()).frame.device, "fr955");
  await s.expectText(s.page.locator(".strip button.on"), "fr955");
  // a click on the strip picks the watch too
  await s.page.locator(".strip button", { hasText: "fenix8solar51mm" }).click();
  await s.expectValue(device, "fenix8solar51mm");
  await s.waitIdle();

  // the style: the layout's rows light up in Layers
  src = await frameSrc(s);
  await style.selectOption("analog_dark");
  await s.page.waitForFunction((old) => document.querySelector(".canvas img.frame")?.getAttribute("src") !== old, src, { timeout: 15_000 });
  await s.waitIdle();
  await s.leftTab("Layers");
  const undrawn = async (id: string) => /\bundrawn\b/.test((await s.layerRow(id).getAttribute("class")) ?? "");
  assert.equal(await undrawn("analog_hands"), false);
  assert.equal(await undrawn("hr_graph"), true);
  await style.selectOption("digital_dark");
  await s.waitIdle();
  await s.page.waitForFunction(() => [...document.querySelectorAll(".layers .item")].some((e) => e.querySelector("span")!.textContent === "hr_graph" && !/undrawn/.test(e.className)), null, { timeout: 15_000 });
  assert.equal(await undrawn("analog_hands"), true);

  // zoom: the slider, the label and the image's size agree
  const slider = s.page.locator(".controls .zoom input[type=range]");
  const frame = (await s.placed()).frame;
  await slider.evaluate((e) => { (e as HTMLInputElement).value = "3"; e.dispatchEvent(new Event("input", { bubbles: true })); });
  await s.expectText(s.page.locator(".controls .zoom .mono"), "3.00×");
  assert.equal(Math.round((await s.placed()).rect.width), frame.width * 3);
  await s.page.keyboard.press("Control+=");
  await s.expectText(s.page.locator(".controls .zoom .mono"), "3.75×");
  await s.page.keyboard.press("Control+0");
  const fitted = Number(((await s.page.locator(".controls .zoom .mono").textContent()) ?? "0").replace("×", ""));
  assert.ok(fitted > 0.5 && fitted < 3.75, `fit gave ${fitted}×`);
  // 1:1 is a switch: the watch's real size on this screen, 96 CSS px an inch
  const real = s.page.locator(".controls button", { hasText: "1:1" });
  assert.equal(await real.isDisabled(), false);
  await real.click();
  assert.equal(await real.getAttribute("aria-pressed"), "true");
  const ppi = (await s.api("vocabulary")).devices.find((d) => d.id === "fenix8solar51mm")!.ppi!;
  const shown = Number(((await s.page.locator(".controls .zoom .mono").textContent()) ?? "0").replace("×", ""));
  assert.ok(Math.abs(shown - 96 / ppi) < 0.002, `1:1 shows ${shown}×, not ${96 / ppi}`);
  await real.click();
  assert.equal(await real.getAttribute("aria-pressed"), "false");
  await s.expectText(s.page.locator(".controls .zoom .mono"), `${fitted.toFixed(fitted < 1 ? 3 : 2)}×`);

  // the skin, from the Preview menu, draws the watch round the screen
  await s.page.locator(".controls .preview > button").click();
  await s.page.locator(".preview-grid label", { hasText: "skin" }).locator("input").click();
  await s.page.locator(".canvas img.skin").waitFor({ state: "visible", timeout: 15_000 });
  assert.match((await s.page.locator(".controls .preview > button").textContent()) ?? "", /skin/);
  await s.page.locator(".preview-grid label", { hasText: "skin" }).locator("input").click();
  await s.page.locator(".canvas img.skin").waitFor({ state: "detached", timeout: 15_000 });
  await s.page.keyboard.press("Escape");
  assert.deepEqual(s.errors, []);
});

h.test("Preview: time, date, now, a slot's pick, and awake/asleep/AOD per watch", async (s) => {
  await s.openExample("showcase");
  await s.waitFace();
  await s.waitIdle();
  const menu = s.page.locator(".controls .preview > button");
  const changed = async (old: string | null, what: string) => {
    await s.page.waitForFunction((o) => document.querySelector(".canvas img.frame")?.getAttribute("src") !== o, old, { timeout: 15_000 }).catch(() => { throw new Error(`${what} did not redraw the face`); });
    await s.waitIdle();
    return frameSrc(s);
  };
  let src = await frameSrc(s);
  await menu.click();
  const grid = s.page.locator(".preview-grid");
  await grid.locator("input[type=time]").fill("17:45:30");
  src = await changed(src, "the time");
  assert.match((await menu.textContent()) ?? "", /17:45/);
  await grid.locator("input[type=date]").fill("2026-12-25");
  src = await changed(src, "the date");
  assert.match((await menu.textContent()) ?? "", /17:45 2026-12-25/);
  // a slot's pick: what the wearer could choose
  const slot = grid.locator("label", { hasText: "left_register" }).locator("select");
  assert.equal(await slot.inputValue(), "steps");
  await slot.selectOption("heart_rate");
  src = await changed(src, "the slot's pick");
  assert.match((await menu.textContent()) ?? "", /Heart rate/);
  // now: this computer's clock, moving on
  await grid.locator("label", { hasText: "now" }).locator("input[type=checkbox]").click();
  src = await changed(src, "now");
  assert.match((await menu.textContent()) ?? "", /^Preview · now/);
  assert.equal(await grid.locator("input[type=time]").isDisabled(), true);
  await grid.locator("button", { hasText: "Back to the sample moment" }).click();
  src = await changed(src, "the sample moment");
  assert.match((await menu.textContent()) ?? "", /^Preview · Heart rate ▾$/);
  await s.page.keyboard.press("Escape");

  // the low-power frame: asleep on a MIP watch, AOD on an AMOLED one, swapped with the watch
  await s.openExample("features/aod");
  await s.waitFace();
  await s.waitIdle();
  // the watch viewed is remembered across faces when the new face targets it too, so pick the AMOLED one explicitly
  const device = s.page.locator(".controls label", { hasText: "Device" }).locator("select");
  if ((await device.inputValue()) !== "fenix847mm") { await device.selectOption("fenix847mm"); await s.waitIdle(); }
  assert.equal(await device.inputValue(), "fenix847mm");
  src = await frameSrc(s);
  await menu.click();
  const mode = (label: string) => grid.locator(".preview-mode label", { hasText: label }).locator("input");
  assert.equal(await mode("asleep").isDisabled(), true, "an AMOLED watch offers asleep");
  assert.equal(await mode("AOD").isDisabled(), false);
  await mode("AOD").click();
  src = await changed(src, "AOD");
  assert.match((await menu.textContent()) ?? "", /AOD/);
  await s.page.keyboard.press("Escape");
  await device.selectOption("fenix8solar47mm");
  src = await changed(src, "a MIP watch");
  await s.expectText(menu, /asleep/);
  await menu.click();
  assert.equal(await mode("AOD").isDisabled(), true, "a MIP watch offers AOD");
  assert.equal(await mode("asleep").isChecked(), true, "AOD did not become asleep on a MIP watch");
  // awake again (a MIP watch's asleep frame can be the awake one, so no redraw is required)
  await mode("awake").click();
  await s.expectText(menu, /^Preview ▾$/);
  await s.waitIdle();
  await s.page.keyboard.press("Escape");
  assert.deepEqual(s.errors, []);
});

h.test("Ctrl+K jumps to an element, or to the Face section that lists a colour", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  await s.page.keyboard.press("Control+k");
  const palette = s.page.locator(".modal.palette");
  await palette.waitFor();
  await palette.locator("input").fill("dot");
  assert.deepEqual(await palette.locator(".palette-list li").allTextContents(), ["dotcircle"]);
  await s.page.keyboard.press("Enter");
  await palette.waitFor({ state: "detached" });
  await s.waitInspected("dot");
  assert.match((await s.layerRow("dot").getAttribute("class")) ?? "", /\bselected\b/);
  // a colour: the Face tab opens at Colours, even while the Face tab shows another section
  await s.faceSection("Fonts");
  await s.page.keyboard.press("Control+k");
  await palette.waitFor();
  await palette.locator("input").fill("accent");
  const rows = await palette.locator(".palette-list li").allTextContents();
  assert.deepEqual(rows, ["accent_arcarc", "accentcolour"]);
  await palette.locator(".palette-list li", { hasText: "colour" }).click();
  await palette.waitFor({ state: "detached" });
  assert.equal(await s.page.locator(".face-nav button.on").textContent(), "Colours5");
  assert.deepEqual(s.errors, []);
});

h.test("History: the changes list goes back and forward; snapshot, restore and open a copy", async (s) => {
  const base = await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  await s.page.locator(".lower-section .tabs button", { hasText: "History" }).click();
  const history = s.page.locator(".history");
  await history.locator("button", { hasText: "Snapshot now" }).click();
  await history.locator(".snaps li").waitFor({ timeout: 10_000 });
  assert.match((await history.locator(".snaps li").textContent()) ?? "", /manual · this version/);
  // two nudges, then back one through the list
  await s.selectLayer("dot");
  await s.page.keyboard.press("ArrowRight");
  const one = await s.waitVersion(base.version);
  await s.page.keyboard.press("ArrowRight");
  const two = await s.waitVersion(one.version);
  await s.waitIdle();
  assert.deepEqual(two.history.states.slice(0, 3).map((st) => [st.label.replace(/ on .*$/, ""), st.current]), [["move dot by (+1, +0) px", true], ["move dot by (+1, +0) px", false], ["open face.yaml", false]]);
  await s.page.locator(".lower-section .tabs button", { hasText: "History" }).click();
  await history.locator(".states li").nth(2).locator("button.state").click();
  const back = await s.waitVersion(two.version);
  await s.waitIdle();
  assert.equal(back.text, base.text, `going back two: ${diffLines(base.text, back.text).join(" ; ")}`);
  assert.equal(back.history.can_redo, true);
  // forward again, to the newest, in one step
  await history.locator(".states li.redo").first().locator("button.state").click();
  const forward = await s.waitVersion(back.version);
  await s.waitIdle();
  assert.equal(forward.text, two.text);
  // restore the snapshot: an ordinary, undoable change
  await history.locator(".snaps li button", { hasText: "Restore" }).click();
  const restored = await s.waitVersion(forward.version);
  await s.waitIdle();
  assert.equal(restored.text, base.text);
  assert.match(restored.history.undo ?? "", /^restore/);
  // open a copy: a new face with the snapshot's text, the original untouched
  const original = await s.id();
  await history.locator(".snaps li button", { hasText: "Open copy" }).click();
  await s.page.waitForURL((u) => /#\/face\//.test(u.toString()) && !u.toString().includes(original), { timeout: 15_000 });
  await s.page.waitForSelector(".editor");
  const copy = await s.doc();
  assert.notEqual(copy.id, original);
  assert.equal(copy.text, base.text);
  await s.waitFace();
  assert.deepEqual(s.errors, []);
});

h.test("Download gives the .yaml or the .zip, and asks before a bare .yaml of a face with files", async (s) => {
  const shapes = await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  let waiting = s.page.waitForEvent("download");
  await s.page.locator(".topbar .menu button.primary", { hasText: "Download" }).click();
  let download = await waiting;
  assert.equal(download.suggestedFilename(), "feature-shapes.yaml");
  assert.equal(readFileSync((await download.path())!, "utf8"), shapes.text);
  // a download takes a snapshot
  await s.eventually(async () => (await s.doc()).history.snapshots.some((sn) => sn.reason === "download"), "the download's snapshot");

  const showcase = await s.openExample("showcase");
  await s.waitFace();
  await s.waitIdle();
  waiting = s.page.waitForEvent("download");
  await s.page.locator(".topbar .menu button.primary", { hasText: "Download" }).click();
  download = await waiting;
  assert.equal(download.suggestedFilename(), "showcase.zip");
  const zip = readFileSync((await download.path())!);
  assert.deepEqual([...zip.subarray(0, 2)], [0x50, 0x4b], "not a zip");
  assert.ok(zip.includes(Buffer.from("assets/ChivoMono-Bold.ttf")), "the zip lacks the font file");
  // the menu's .yaml only asks first
  await s.page.locator(".topbar .menu .popover > button").click();
  await s.page.locator(".popover-body.menu-items button", { hasText: ".yaml only" }).click();
  await s.page.locator(".modal .ask", { hasText: "a plain .yaml will not build on its own" }).waitFor();
  waiting = s.page.waitForEvent("download");
  await s.page.locator(".modal-foot button.primary", { hasText: "Download .yaml" }).click();
  download = await waiting;
  assert.equal(download.suggestedFilename(), "showcase.yaml");
  assert.equal(readFileSync((await download.path())!, "utf8"), showcase.text);
  assert.deepEqual(s.errors, []);
});

h.test("leaving while a change is on its way asks first; staying, the change is saved", async (s) => {
  const base = await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  await s.pane("YAML");
  await s.appendYaml("\n# typed just before leaving");
  // the typing waits out its debounce: the page asks before it is left, and flushes the text on the way
  const dialog = s.page.waitForEvent("dialog", { timeout: 15_000 });
  void s.page.close({ runBeforeUnload: true }).catch(() => {});
  const d = await dialog;
  assert.equal(d.type(), "beforeunload");
  await d.dismiss();
  await s.page.waitForTimeout(500);
  assert.equal(s.page.isClosed(), false, "the page closed although leaving was cancelled");
  // read through a second page of the same library, so nothing waits on the page that was asked
  const other = await h.context.newPage();
  try {
    await other.goto(`${h.base}#/`);
    await other.waitForSelector("text=Library");
    const saved = await other.evaluate(async (id) => {
      const hook = (globalThis as unknown as { wfbStudio: { api: (op: string, args: unknown) => Promise<{ text: string; version: number }> } }).wfbStudio;
      for (let i = 0; i < 100; i++) {
        const got = await hook.api("get", { id });
        if (got.text.endsWith("# typed just before leaving")) return got;
        await new Promise((r) => setTimeout(r, 100));
      }
      return hook.api("get", { id });
    }, base.id);
    assert.equal(saved.text, base.text + "\n# typed just before leaving", "the text typed just before leaving was not saved");
    assert.ok(saved.version > base.version);
  } finally {
    await other.close();
  }
});
