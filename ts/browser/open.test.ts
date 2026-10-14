// Every example face (as a `.yaml`, or as a zip when it has assets) and every
// template on the home screen opens in the editor and draws a frame, with
// no console error or page error on the way. The time to the first frame is
// recorded in the output, not asserted. Two examples take the editor's two
// detours: a `.yaml` naming a font file outside its folder opens with the
// missing-files banner, and adding the file through it makes the face draw;
// a face whose targets are not installed here opens without a frame and
// says so.

import assert from "node:assert/strict";
import { join } from "node:path";
import { exampleFaces, shortName, suite } from "./harness.ts";

const h = await suite(import.meta.url);

for (const face of exampleFaces()) {
  h.test(`opens ${face.name} as ${face.assets ? "a zip" : "yaml"}`, async (s, t) => {
    let doc = face.assets ? await s.openZip(face.dir) : await s.openYaml(face.yaml);
    if (doc.missing.length) {
      // the banner lists each missing file, and Add… brings it in
      const banner = s.page.locator(".banner");
      for (const ref of doc.missing) {
        await assert.doesNotReject(banner.locator("code", { hasText: ref }).waitFor({ timeout: 5000 }), `the banner does not list ${ref}`);
        const input = banner.locator(".file").filter({ hasText: ref }).locator("input[type=file]");
        await input.setInputFiles(join(face.dir, ref));
      }
      doc = await s.waitVersion(doc.version);
      await s.waitIdle();
      assert.deepEqual(doc.missing, [], "files still missing after Add…");
      assert.equal(await banner.count(), 0, "the missing-files banner stays after the files were added");
      t.diagnostic(`${face.name}: added ${doc.assets.join(", ")} through the banner`);
    }
    assert.equal(doc.loads, true, `${shortName(face.yaml)} does not load: ${doc.diagnostics.filter((d) => d.severity === "error").map((d) => d.message).join("; ")}`);
    if (doc.targets.length === 0) {
      // none of its watches is installed here: no frame, and the editor says why
      const problems = doc.globals.target_problems;
      assert.deepEqual(Object.keys(problems).sort(), [...doc.globals.targets].sort(), "every target should be reported as unavailable");
      await s.page.locator(".canvas-wrap .empty", { hasText: "No frame yet" }).waitFor({ timeout: 10_000 });
      await s.faceSection("Target devices");
      assert.equal(await s.page.locator(".face-panel .warn", { hasText: "not available here" }).count(), doc.globals.targets.length);
      t.diagnostic(`${face.name}: targets ${doc.globals.targets.join(", ")} are not installed here; no frame drawn`);
    } else {
      const ms = await s.waitFace();
      t.diagnostic(`${face.name}: first frame in ${ms} ms, ${doc.text.split("\n").length} lines, ${doc.targets.length} targets`);
    }
    await s.waitIdle();
    // the DOM and the text agree on what was opened
    assert.equal(await s.page.locator(".topbar .title .name").textContent(), doc.name);
    await s.leftTab("Layers");
    const rows = await s.page.locator(".layers .item > span:first-child").allTextContents();
    assert.ok(rows.length > 0, "the Layers tree is empty");
    for (const id of rows) assert.ok(new RegExp(`^\\s+${id}:`, "m").test(doc.text), `${id} is listed in Layers but not in the text`);
    assert.deepEqual(s.errors, [], "console or page errors while opening");
  });
}

h.test("every template on the home screen opens and draws", async (s, t) => {
  await s.page.goto(`${h.base}#/`);
  await s.page.waitForSelector("text=Library");
  const templates = await s.page.locator(".card").filter({ hasText: "New face" }).locator("select option").allTextContents();
  assert.ok(templates.length >= 5, `few templates: ${templates.join(", ")}`);
  for (const template of templates) {
    const doc = await s.openTemplate(template, `From ${template}`);
    assert.equal(doc.name, `From ${template}`);
    assert.equal(doc.loads, true, `${template} does not load: ${doc.diagnostics.map((d) => d.message).join("; ")}`);
    const ms = await s.waitFace();
    t.diagnostic(`template ${template}: first frame in ${ms} ms`);
    await s.waitIdle();
    assert.ok(/^format: 2/m.test(doc.text), `${template}'s text is not format 2`);
    assert.ok(await s.page.locator(".layers .item").count() > 0, `${template} lists no layers`);
  }
  assert.deepEqual(s.errors, [], "console or page errors while opening templates");
});
