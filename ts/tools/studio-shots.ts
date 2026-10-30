// Regenerates the screenshots of the editor in docs/screenshots/ that
// README.md shows: `wfb studio` started on a free port, a face opened in
// headless Chromium at twice the pixel density, and the visual editor
// caught with each element named selected in turn: `studio.png` for the
// first, `studio-2.png` for the second and so on.
// Needs the device definitions and Playwright, as `npm run test:browser`
// does.
//
//   node ts/tools/studio-shots.ts [--device ID] FACE.yaml|FACE-DIR ELEMENT...
//
// `--device` picks the watch the face is edited on, one of its targets. The
// README's come from the user's own Red Tactical face, which is not in the
// repository, on the fenix947mm (the sharpest of its targets):
// `node ts/tools/studio-shots.ts --device fenix947mm examples/other/red-tactical.yaml left_slot left_reading`.
import { existsSync, readFileSync, statSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import { parseArgs } from "node:util";
import { type Page } from "playwright";
import { launchBrowser, startServer, zipFolder } from "../browser/harness.ts";
import { REPO_ROOT } from "../src/devices/node.ts";

const { values: { device }, positionals: [face, ...selected] } = parseArgs({ options: { device: { type: "string" } }, allowPositionals: true });
if (!face || !selected.length) throw new Error("usage: node ts/tools/studio-shots.ts [--device ID] FACE.yaml|FACE-DIR ELEMENT...");
const OUT = join(REPO_ROOT, "docs", "screenshots");
const VIEWPORT = { width: 1440, height: 860 };

const settle = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

function layerRow(page: Page, id: string) {
  return page.locator(".layers .item").filter({ has: page.locator(`:scope > span:first-child:text-is("${id}")`) }).first();
}

async function select(page: Page, id: string): Promise<void> {
  await layerRow(page, id).click();
  await page.waitForFunction((id) => document.querySelector(".inspector .ins-head .name")?.textContent === id, id);
  await settle(1500);
}

/** The editor at rest: the pointer off the page, the strip caught up. */
async function shoot(page: Page, name: string): Promise<void> {
  await page.mouse.move(VIEWPORT.width - 2, VIEWPORT.height - 2);
  await settle(2500);
  await page.screenshot({ path: join(OUT, `${name}.png`) });
}

const path = resolve(face);
const file = statSync(path).isDirectory()
  ? { name: `${basename(path)}.zip`, mimeType: "application/zip", buffer: zipFolder(path) }
  : { name: basename(path), mimeType: "application/yaml", buffer: readFileSync(path) };
if (statSync(path).isDirectory() && !existsSync(join(path, "face.yaml"))) throw new Error(`${face} has no face.yaml`);

const { base, child } = await startServer();
const browser = await launchBrowser();
try {
  const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 2, colorScheme: "dark" });
  const page = await context.newPage();
  await page.goto(`${base}#/`);
  await page.waitForSelector("text=Library");
  await page.locator("input[type=file]").setInputFiles(file);
  await page.waitForSelector(".editor", { timeout: 60_000 });
  await page.waitForFunction(() => ((document.querySelector(".canvas img.frame") as HTMLImageElement | null)?.naturalWidth ?? 0) > 0, null, { timeout: 90_000 });
  if (device) {
    await page.locator("label", { hasText: "Device" }).locator("select").selectOption(device);
    await page.waitForFunction((d) => document.querySelector(".canvas img.frame")?.getAttribute("alt") === `the face on ${d}`, device);
    await settle(3000);
  }
  // fold Diagnostics and History away, so Properties has the right column
  await page.locator(".panel.right button", { hasText: /^▾$/ }).first().click();
  await page.keyboard.press("Control+0");

  for (const [i, id] of selected.entries()) {
    await select(page, id);
    await shoot(page, i ? `studio-${i + 1}` : "studio");
  }
} finally {
  await browser.close();
  child.kill();
}
