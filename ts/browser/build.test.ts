// Build… against the real server: the showcase built for `fenix8solar47mm`
// with `monkeyc`, its `.prg` downloaded and the dialog reporting the memory
// it uses. Skipped, with the reason, when `CIQ_SDK` is not set.

import assert from "node:assert/strict";
import { statSync } from "node:fs";
import { test } from "node:test";
import { suite } from "./harness.ts";

const h = await suite(import.meta.url);

if (!process.env["CIQ_SDK"]) {
  test("Build… downloads a .prg", { skip: "CIQ_SDK is not set: export CIQ_SDK=<the Connect IQ SDK> for a build (tools/setup-env.sh installs one)" }, () => {});
} else {
  h.test("Build… for fenix8solar47mm downloads a .prg and reports its memory", async (s) => {
    const doc = await s.openExample("features/shapes");
    await s.waitFace();
    await s.waitIdle();
    await s.page.locator(".topbar button", { hasText: "Build…" }).click();
    const modal = s.page.locator(".modal");
    await modal.waitFor();
    // the face's own watches first, the one in view chosen
    assert.deepEqual(await modal.locator(".choices li code").allTextContents(), doc.targets);
    assert.equal(await modal.locator(".choices li").filter({ has: s.page.locator("input:checked") }).locator("code").textContent(), "fenix8solar47mm");
    assert.ok((await modal.locator("select option").allTextContents()).some((o) => o.endsWith("(fr255)")), "other installed watches are not offered");
    const waiting = s.page.waitForEvent("download", { timeout: 60_000 });
    await modal.locator("button.primary", { hasText: "Build and download" }).click();
    await modal.locator(".modal-body", { hasText: "Building for" }).waitFor();
    const download = await waiting;
    assert.equal(download.suggestedFilename(), "feature-shapes-1.0.0-fenix8solar47mm.prg");
    const size = statSync((await download.path())!).size;
    assert.ok(size > 10_000, `the .prg is only ${size} bytes`);
    const report = modal.locator(".modal-body", { hasText: "Built" });
    await report.waitFor({ timeout: 60_000 });
    assert.match((await report.textContent()) ?? "", /Built fenix8solar47mm in \d+(\.\d+)? s: [\d,]+ B \/ [\d,]+ B \(\d+(\.\d+)?%\)/);
    await modal.locator("summary", { hasText: "Log" }).click();
    assert.match((await modal.locator("pre.log").textContent()) ?? "", /monkeyc|\.prg/);
    await modal.locator(".modal-foot button.primary", { hasText: "Close" }).click();
    await modal.waitFor({ state: "detached" });
    assert.deepEqual(s.errors, []);
  }, { timeout: 180_000 });
}
