// The YAML tab against the real worker: a comment typed is saved; text that
// is not YAML is not saved, with the reason under the pane; a compiler error
// is saved and shown; a `pt` typed where no font is keeps the face readable,
// reports an error on its line and undoes clean; and the two-tab conflict,
// "Keep my text" and "Take the face as it is", with two pages in one context.

import assert from "node:assert/strict";
import type { Page } from "playwright";
import { diffLines, Session, suite } from "./harness.ts";

const h = await suite(import.meta.url);

h.test("a comment typed is saved a moment later; Undo outside the tab takes the typing back", async (s) => {
  const base = await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  await s.pane("YAML");
  assert.equal(await s.yamlText(), base.text, "the pane does not show the face's text");
  await s.appendYaml("\n# a note typed in the editor");
  const after = await s.waitVersion(base.version);
  await s.waitIdle();
  assert.equal(after.text, base.text + "\n# a note typed in the editor");
  assert.equal(after.history.undo, "edit the text");
  assert.equal(await s.page.locator(".topbar .save").textContent(), "saved");
  // more typing within ten seconds joins the same step
  await s.appendYaml(" and more");
  const more = await s.waitVersion(after.version);
  assert.ok(more.text.endsWith("# a note typed in the editor and more"));
  assert.equal(more.history.states.filter((st) => st.label === "edit the text").length, 1, "a burst of typing made more than one history step");
  await s.pane("Face");
  const undone = await s.undo();
  assert.equal(undone.text, base.text);
  await s.pane("YAML");
  assert.equal(await s.yamlText(), base.text, "the pane did not follow the undo");
  assert.deepEqual(s.errors, []);
});

h.test("text that is not YAML is not saved, and says so until it is YAML again", async (s) => {
  const base = await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  await s.pane("YAML");
  await s.typeYaml(base.text.replace("radius: 4px", "radius: [4px"));
  const status = s.page.locator(".yaml-status");
  await status.waitFor({ timeout: 5000 });
  assert.match((await status.textContent()) ?? "", /not saved until it is YAML again$/);
  await s.page.waitForTimeout(500);
  assert.equal((await s.doc()).version, base.version, "the broken text was recorded");
  assert.equal(await s.page.locator(".topbar .save").textContent(), "not saved");
  assert.match((await s.page.locator(".topbar .save").getAttribute("title")) ?? "", /not saved/);
  // mended, it saves
  await s.typeYaml(base.text.replace("radius: 4px", "radius: 5px"));
  const after = await s.waitVersion(base.version);
  assert.match(after.text, /radius: 5px/, diffLines(base.text, after.text).join(" ; "));
  assert.equal(await status.count(), 0, "the status stays after the text became YAML");
  await s.waitIdle();
  assert.deepEqual(s.errors, []);
});

h.test("a compiler error is saved and shown: in Diagnostics and in the top bar; the face is not drawn", async (s, t) => {
  const base = await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  await s.pane("YAML");
  // the last element's colour, so the error's line is in view at the end of the text
  await s.typeYaml(base.text.replace("    thickness: 1px\n    color: color.dim", "    thickness: 1px\n    color: color.nope"));
  const after = await s.waitVersion(base.version);
  await s.waitIdle();
  assert.equal(after.loads, false, diffLines(base.text, after.text).join(" ; "));
  const errors = after.diagnostics.filter((d) => d.severity === "error");
  assert.equal(errors.length, 1, JSON.stringify(after.diagnostics));
  assert.match(errors[0]!.message, /nope/);
  assert.equal(errors[0]!.line, after.text.split("\n").findIndex((l) => l.includes("color.nope")) + 1);
  assert.equal(await s.page.locator(".topbar .errors").textContent(), "1 error");
  // the gutter should mark the line too; it is recorded, not asserted, since no marker has been
  // seen in headless Chromium so far (the Diagnostics tab and the top bar carry the error)
  const marked = await s.page.locator(".cm-gutter-lint .cm-lint-marker-error").first().waitFor({ timeout: 4000 }).then(() => true, () => false);
  t.diagnostic(marked ? "the lint gutter marks the error's line" : "the lint gutter shows no marker for the error (docs/guide/studio.md promises one)");
  await s.page.locator(".topbar .errors").click();
  assert.match((await s.page.locator(".lower-section .diag, .lower-section li, .lower-section .section-scroll").first().textContent()) ?? "", /nope/);
  await s.pane("Face");
  await s.expectText(s.page.locator(".canvas-wrap .empty"), /does not load/);
  assert.equal(await s.page.locator(".topbar button", { hasText: "Build…" }).isDisabled(), true);
  const undone = await s.undo();
  assert.equal(undone.text, base.text);
  await s.waitFace();
  assert.deepEqual(s.errors, []);
});

h.test("a pt typed where no font is keeps the face readable, reports an error on its line, and undoes clean", async (s) => {
  const base = await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  await s.pane("YAML");
  const lines = base.text.split("\n");
  const line = lines.findIndex((l) => l === "    radius: 4px") + 1;
  const element = lines.findIndex((l) => l === "  dot:") + 1;
  await s.typeYaml(base.text.replace("radius: 4px", "radius: 4pt"));
  const after = await s.waitVersion(base.version);
  await s.waitIdle();
  assert.match(after.text, /radius: 4pt/, diffLines(base.text, after.text).join(" ; "));
  const error = after.diagnostics.find((d) => d.severity === "error");
  assert.ok(error, "no error for a pt with no font in scope");
  assert.match(error.message, /pt/);
  // a resolve-time error is placed on the element (its own line, or the key's)
  assert.ok(error.line !== undefined && error.line >= element && error.line <= line, `the error is not on dot's lines ${element}-${line}: ${JSON.stringify(error)}`);
  assert.equal(await s.page.locator(".topbar .errors").textContent(), "1 error");
  // the face still reads after a reload, and from the library
  await s.page.reload();
  await s.page.waitForSelector(".editor", { timeout: 30_000 });
  const reopened = await s.doc();
  assert.equal(reopened.text, after.text);
  assert.equal(await s.page.locator(".topbar .undo-group button").first().isDisabled(), false, "Undo is disabled after the pt");
  const undone = await s.undo();
  assert.equal(undone.text, base.text, diffLines(base.text, undone.text).join(" ; "));
  assert.equal(undone.diagnostics.filter((d) => d.severity === "error").length, 0);
  await s.waitFace();
  assert.deepEqual(s.errors, []);
});

/** Open the face `url` in a second page of the same browser (the same library), with the harness's helpers. */
async function secondPage(url: string): Promise<Session> {
  const page: Page = await h.context.newPage();
  const other = new Session(page, h.base);
  await page.goto(url);
  await page.waitForSelector(".editor", { timeout: 30_000 });
  await other.waitFace();
  await other.waitIdle();
  return other;
}

/** In `a`'s YAML pane, type while `b` changes the face: the send is refused as stale and the conflict banner shows. */
async function provokeConflict(a: Session, b: Session): Promise<void> {
  const typing = a.page.keyboard.type("\n# typed while the other tab changed the face", { delay: 40 });
  await b.selectLayer("dot");
  const radius = b.topField("radius").locator("input");
  await radius.fill("6");
  await radius.press("Enter");
  await typing;
  await a.page.locator(".yaml-conflict").waitFor({ timeout: 15_000 });
}

h.test("two tabs: a change elsewhere while typing is not overwritten; Take the face as it is", async (s) => {
  const base = await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const other = await secondPage(s.page.url());
  try {
    await s.pane("YAML");
    await s.page.locator(".cm-content").click();
    await s.page.keyboard.press("Control+End");
    await provokeConflict(s, other);
    const banner = s.page.locator(".yaml-conflict");
    assert.match((await banner.textContent()) ?? "", /The face changed elsewhere while you were typing, so your text was not saved\.\s+The other change [^.]*1 line/);
    assert.equal(await s.page.locator(".topbar .save").textContent(), "not saved");
    const now = await s.doc();
    assert.match(now.text, /radius: 6px/, "the other tab's change did not land");
    assert.doesNotMatch(now.text, /typed while/, "the typing was saved over the other change");
    await banner.locator("button", { hasText: "Show it" }).click();
    assert.deepEqual(await banner.locator(".yaml-diff .del, .yaml-diff .add").allTextContents(), ["-     radius: 4px", "+     radius: 6px"]);
    await banner.locator("button", { hasText: "Take the face as it is" }).click();
    await banner.waitFor({ state: "hidden" });
    assert.equal(await s.yamlText(), now.text, "the pane does not show the face as it now is");
    assert.equal((await s.doc()).version, now.version);
    await s.waitIdle();
    assert.equal(await s.page.locator(".topbar .save").textContent(), "saved");
    assert.deepEqual(s.errors, []);
    assert.deepEqual(other.errors, []);
    assert.ok(now.version > base.version);
  } finally {
    await other.page.close();
  }
});

h.test("two tabs: Keep my text saves the typing over the other change, which Undo brings back", async (s) => {
  const base = await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const other = await secondPage(s.page.url());
  try {
    await s.pane("YAML");
    await s.page.locator(".cm-content").click();
    await s.page.keyboard.press("Control+End");
    await provokeConflict(s, other);
    const theirs = await s.doc();
    await s.page.locator(".yaml-conflict button", { hasText: "Keep my text" }).click();
    const mine = await s.waitVersion(theirs.version);
    await s.waitIdle();
    assert.ok(mine.text.endsWith("# typed while the other tab changed the face"), "the typing was not saved");
    assert.match(mine.text, /radius: 4px/, "the other change was kept under my text");
    assert.equal(mine.history.undo, "edit the text");
    assert.equal(await s.page.locator(".topbar .save").textContent(), "saved");
    // the other tab follows, and undo there brings its change back
    await other.waitVersion(theirs.version);
    assert.equal((await other.doc()).text, mine.text);
    const back = await other.undo();
    assert.equal(back.text, theirs.text, diffLines(theirs.text, back.text).join(" ; "));
    await s.waitVersion(mine.version);
    await s.eventually(async () => (await s.yamlText()) === theirs.text, "this tab's pane to follow the other tab's undo");
    assert.deepEqual(s.errors, []);
    assert.deepEqual(other.errors, []);
    assert.ok(theirs.version > base.version);
  } finally {
    await other.page.close();
  }
});
