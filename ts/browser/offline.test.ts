// The editor with its server gone: the service worker's copy opens the face
// again and draws it, and Build says what it needs instead of failing blind.

import assert from "node:assert/strict";
import { suite } from "./harness.ts";

const h = await suite(import.meta.url);

h.test("with the server stopped, a reload opens the face from the offline copy, and Build says why it cannot", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  assert.equal(await s.page.evaluate(() => navigator.serviceWorker.controller !== null), true, "a first visit ends under the service worker");
  const id = await s.id();
  await h.stop();
  await s.page.reload();
  await s.page.waitForSelector(".editor", { timeout: 60_000 });
  await s.waitFace();
  assert.equal(await s.id(), id);

  await s.page.locator(".topbar button", { hasText: "Build…" }).click();
  const modal = s.page.locator(".modal");
  await modal.locator("button.primary", { hasText: "Build and download" }).click();
  await s.expectText(modal, /building needs wfb studio, which did not answer/, 30_000);
  assert.deepEqual(s.errors.filter((e) => e.startsWith("pageerror")), []);
});
