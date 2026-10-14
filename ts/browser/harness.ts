// The browser suite's harness: `wfb studio` started as a child process on a
// free port, headless Chromium driving its page, and the helpers every test
// file shares. Each test file calls `suite()` once at the top, which starts
// the server and the browser (one `BrowserContext` per file, so its tests
// share one library) and registers their teardown, then `h.test(name, fn)`
// for each test, whose `fn` gets a `Session`: a fresh page with the helpers
// bound to it. A test that fails leaves a screenshot in `browser/shots/`.
//
// Everything a test asserts about the face it reads twice: from the DOM and
// from the YAML text the worker holds (`doc().text`), through the page's
// `globalThis.wfbStudio` hook (`app/main.ts`).
//
// Without device definitions installed, every test is skipped with one
// message naming `tools/setup-env.sh`: the editor cannot draw a face
// without them, and a silent pass would say nothing.

import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { createServer } from "node:net";
import { basename, join, relative } from "node:path";
import { after, test, type TestContext } from "node:test";
import { fileURLToPath } from "node:url";
import { zipSync } from "fflate";
import type { Browser, BrowserContext, ConsoleMessage, Locator, Page } from "playwright";
import { NodeDeviceFiles, REPO_ROOT } from "../src/devices/node.ts";
import { decodePng } from "../src/png.ts";
import { inflateTiles, inkOf } from "../src/raster/canvas.ts";
import type { Answer, Args, Frame, FrameItem, Handle, Op, Summary } from "../src/studio/protocol.ts";

export { REPO_ROOT };
export const EXAMPLES = join(REPO_ROOT, "examples");
const SHOTS = join(REPO_ROOT, "ts", "browser", "shots");
/** The ports the servers the tests start may use. */
const PORTS = Array.from({ length: 10 }, (_, i) => 8780 + i);
const VIEWPORT = { width: 1600, height: 1000 };

// Playwright is a dev dependency, so a checkout that ran `npm ci` has it
// beside the package; a machine with only the global install (the
// development container) finds it there.
function loadPlaywright(): typeof import("playwright") {
  const require = createRequire(import.meta.url);
  try {
    return require("playwright");
  } catch {
    const root = process.env["NODE_PATH"] ?? "/opt/node22/lib/node_modules";
    try {
      return require(join(root, "playwright"));
    } catch {
      throw new Error("playwright is not installed: run npm ci in ts/, or npm install -g playwright@1.56");
    }
  }
}

/** Why the suite cannot run here, or null: the device definitions `wfb studio` needs are missing. */
export function skipReason(): string | null {
  try {
    NodeDeviceFiles.discover();
    return null;
  } catch (e) {
    return `no device definitions installed, so wfb studio cannot draw a face: run tools/setup-env.sh (${(e as Error).message.split(".")[0]})`;
  }
}

async function freePort(): Promise<number> {
  for (const port of PORTS) {
    const free = await new Promise<boolean>((resolve) => {
      const probe = createServer();
      probe.once("error", () => resolve(false));
      probe.listen(port, "127.0.0.1", () => probe.close(() => resolve(true)));
    });
    if (free) return port;
  }
  throw new Error(`no free port in ${PORTS[0]}-${PORTS[PORTS.length - 1]}`);
}

/** `wfb studio` on a free port: resolves once it answers `GET /` with 200. */
async function startServer(): Promise<{ base: string; child: ChildProcess }> {
  const port = await freePort();
  const child = spawn(process.execPath, [join(REPO_ROOT, "ts", "src", "cli.ts"), "studio", "-p", String(port)], {
    cwd: REPO_ROOT, stdio: ["ignore", "pipe", "pipe"], env: process.env,
  });
  let output = "";
  child.stdout!.on("data", (d: Buffer) => { output += d.toString(); });
  child.stderr!.on("data", (d: Buffer) => { output += d.toString(); });
  let exited: string | null = null;
  child.on("exit", (code) => { exited = `wfb studio exited with ${code}:\n${output}`; });
  const base = `http://127.0.0.1:${port}/`;
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    if (exited) throw new Error(exited);
    try {
      const r = await fetch(base);
      if (r.status === 200) return { base, child };
    } catch { /* not listening yet */ }
    await new Promise((r) => setTimeout(r, 200));
  }
  child.kill();
  throw new Error(`wfb studio did not answer on ${base} in time:\n${output}`);
}

// Every `.toast` text as it appears, kept on `window.__toasts` across the
// page's life, so a message that went after four seconds is still readable.
const TOAST_INIT = `(() => {
  window.__toasts = [];
  const seen = new WeakMap();
  const scan = () => { for (const t of document.querySelectorAll('.toast')) { if (seen.get(t) !== t.textContent) { seen.set(t, t.textContent); window.__toasts.push({ t: Date.now(), kind: t.className, text: t.textContent }); } } };
  new MutationObserver(scan).observe(document, { childList: true, subtree: true, characterData: true });
})();`;

/** A device pixel's place on the screen, and the frame it was read from. */
export interface Placed {
  frame: Frame;
  /** The frame image's box on the screen (CSS pixels). */
  rect: { left: number; top: number; width: number; height: number };
  /** Screen pixels per device pixel. */
  zoom: number;
  /** Device pixel (x, y) as screen coordinates. */
  at(x: number, y: number): { x: number; y: number };
  item(id: string): FrameItem;
  /** A device pixel of the element's own ink that nothing drawn later covers, nearest its box centre: where a press picks it. */
  ink(id: string): Promise<{ x: number; y: number }>;
  /** The element's handle of `kind`, and `key` or `part` when given. */
  handle(id: string, kind: Handle["kind"], which?: string): Handle;
}

// Each layer's ink mask, as the page's hit-test reads it (`app/hit.ts`'s
// `topmost` over `raster.inkOf`), worked out in Node from the same ops.
async function inkMasks(frame: Frame): Promise<{ id: string; has(x: number, y: number): boolean }[]> {
  const tiles = await inflateTiles(frame.tiles);
  return frame.layers.map((layer) => {
    const id = layer.id.startsWith("ring:") ? layer.id.slice(5) : layer.id;
    if (layer.ops) {
      const ink = inkOf(layer.ops, tiles, frame.width, frame.height, 1);
      const b = ink.box;
      return { id, has: (x, y) => b !== null && x >= b[0] && y >= b[1] && x < b[2] && y < b[3] && ink.mask[(y - b[1]) * (b[2] - b[0]) + (x - b[0])] !== 0 };
    }
    if (layer.image && layer.origin) {
      const png = decodePng(Uint8Array.from(atob(layer.image.split(",")[1]!), (c) => c.charCodeAt(0)));
      const [ox, oy] = layer.origin;
      return { id, has: (x, y) => png !== null && x >= ox && y >= oy && x < ox + png.width && y < oy + png.height && png.pixels[((y - oy) * png.width + (x - ox)) * 4 + 3]! > 0 };
    }
    return { id, has: () => false };
  });
}

/**
 * The lines that differ between `a` and `b`, as a line diff (longest common
 * subsequence): `-n: line` for a line of `a` that is gone, `+n: line` for a
 * line of `b` that is new, each with its 1-based line number.
 */
export function diffLines(a: string, b: string): string[] {
  const A = a.split("\n"), B = b.split("\n");
  // trim the common head and tail, so the table stays small
  let head = 0;
  while (head < A.length && head < B.length && A[head] === B[head]) head++;
  let tail = 0;
  while (tail < A.length - head && tail < B.length - head && A[A.length - 1 - tail] === B[B.length - 1 - tail]) tail++;
  const X = A.slice(head, A.length - tail), Y = B.slice(head, B.length - tail);
  const n = X.length, m = Y.length;
  const table: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      table[i]![j] = X[i] === Y[j] ? table[i + 1]![j + 1]! + 1 : Math.max(table[i + 1]![j]!, table[i]![j + 1]!);
    }
  }
  const out: string[] = [];
  let i = 0, j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && X[i] === Y[j]) { i++; j++; }
    else if (j < m && (i >= n || table[i]![j + 1]! >= table[i + 1]![j]!)) { out.push(`+${head + j + 1}: ${Y[j]}`); j++; }
    else { out.push(`-${head + i + 1}: ${X[i]}`); i++; }
  }
  return out;
}

/** Every face under `dir` (a `face.yaml` with the folder round it), `dashboard/` left out: the user's playground. */
export function exampleFaces(dir = EXAMPLES): { name: string; dir: string; yaml: string; assets: boolean }[] {
  const out: { name: string; dir: string; yaml: string; assets: boolean }[] = [];
  const walk = (d: string): void => {
    for (const entry of readdirSync(d).sort()) {
      const path = join(d, entry);
      if (!statSync(path).isDirectory()) continue;
      if (basename(path) === "dashboard" || entry === "assets") continue;
      const yaml = join(path, "face.yaml");
      if (existsSync(yaml)) out.push({ name: relative(dir, path), dir: path, yaml, assets: existsSync(join(path, "assets")) });
      walk(path);
    }
  };
  walk(dir);
  return out;
}

/** A face folder zipped in memory, as a desktop "compress" would make it: `face.yaml` and `assets/` at the root. */
export function zipFolder(dir: string): Buffer {
  const entries: Record<string, Uint8Array> = {};
  const walk = (d: string): void => {
    for (const entry of readdirSync(d)) {
      const path = join(d, entry);
      if (statSync(path).isDirectory()) walk(path);
      else entries[relative(dir, path)] = new Uint8Array(readFileSync(path));
    }
  };
  walk(dir);
  return Buffer.from(zipSync(entries, { level: 1 }));
}

/** A page of the editor with the helpers bound to it. */
export class Session {
  readonly page: Page;
  readonly base: string;
  /** Console errors and page errors, as they came. */
  readonly errors: string[] = [];
  /** When the last open was asked for, for the time to its first frame. */
  private openedAt = 0;

  constructor(page: Page, base: string) {
    this.page = page;
    this.base = base;
    page.on("console", (m: ConsoleMessage) => { if (m.type() === "error") this.errors.push(`console.error: ${m.text()}`); });
    page.on("pageerror", (e: Error) => this.errors.push(`pageerror: ${e.stack || e.message}`));
  }

  /** The open face's id, from the address. */
  async id(): Promise<string> {
    const m = /#\/face\/([0-9a-f]{32})/.exec(this.page.url());
    if (!m) throw new Error(`no face is open: ${this.page.url()}`);
    return m[1]!;
  }

  /** The worker's answer to `op`, through the page's hook; a refusal is thrown with its message. */
  async api<O extends Op>(op: O, args: Partial<Args<O>> & Record<string, unknown> = {}): Promise<Answer<O>> {
    const result = await this.page.evaluate(async ([op, args]) => {
      const hook = (globalThis as unknown as { wfbStudio: { api: (op: string, args: unknown) => Promise<unknown> } }).wfbStudio;
      try { return { ok: true as const, value: await hook.api(op, args) }; }
      catch (e) { const err = e as Error & { status?: number }; return { ok: false as const, error: err.message || String(e), status: err.status ?? 0 }; }
    }, [op, args] as [string, unknown]);
    if (result.ok) return result.value as Answer<O>;
    throw Object.assign(new Error(result.error), { status: result.status });
  }

  /** `api`, with a refusal returned as `{error, status}` instead of thrown. */
  async tryApi<O extends Op>(op: O, args: Partial<Args<O>> & Record<string, unknown> = {}): Promise<{ ok: true; value: Answer<O> } | { ok: false; error: string; status: number }> {
    try { return { ok: true, value: await this.api(op, args) }; }
    catch (e) { return { ok: false, error: (e as Error).message, status: (e as { status?: number }).status ?? 0 }; }
  }

  /** The open face's summary: its text, tree, diagnostics, history and globals. */
  async doc(): Promise<Summary> {
    return this.api("get", { id: await this.id() });
  }

  // -- opening faces -----------------------------------------------------------

  private async home(): Promise<void> {
    await this.page.goto(`${this.base}#/`);
    await this.page.waitForSelector("text=Library");
    this.openedAt = Date.now();
  }

  private async opened(): Promise<Summary> {
    await this.page.waitForURL(/#\/face\//, { timeout: 60_000 });
    await this.page.waitForSelector(".editor", { timeout: 60_000 });
    return this.doc();
  }

  /** The home screen's Open, given a `.yaml` file. */
  async openYaml(path: string): Promise<Summary> {
    await this.home();
    await this.page.locator("input[type=file]").setInputFiles(path);
    return this.opened();
  }

  /** The home screen's Open, given a face folder zipped in memory. */
  async openZip(dir: string): Promise<Summary> {
    await this.home();
    await this.page.locator("input[type=file]").setInputFiles({ name: `${basename(dir)}.zip`, mimeType: "application/zip", buffer: zipFolder(dir) });
    return this.opened();
  }

  /** The home screen's New face, from `template`, called `name`. */
  async openTemplate(template: string, name = `T ${template}`): Promise<Summary> {
    await this.home();
    const card = this.page.locator(".card").filter({ hasText: "New face" });
    await card.locator("select").selectOption(template);
    await card.locator("input[type=text]").fill(name);
    await card.locator("button.primary").click();
    return this.opened();
  }

  /** An example by its folder (`features/shapes`), as a zip when it has assets, else its `.yaml`. */
  async openExample(name: string): Promise<Summary> {
    const dir = join(EXAMPLES, name);
    return existsSync(join(dir, "assets")) ? this.openZip(dir) : this.openYaml(join(dir, "face.yaml"));
  }

  // -- waiting -------------------------------------------------------------------

  /** Until the face is drawn (the frame image has pixels); returns the milliseconds since the face was opened. */
  async waitFace(timeout = 60_000): Promise<number> {
    await this.page.waitForFunction(() => {
      const img = document.querySelector(".canvas img.frame") as HTMLImageElement | null;
      return img !== null && img.naturalWidth > 0;
    }, null, { timeout });
    return Date.now() - this.openedAt;
  }

  /** Until the top bar says "saved" and nothing is rendering or on its way. */
  async waitIdle(timeout = 30_000): Promise<void> {
    await this.page.waitForFunction(() => {
      const save = document.querySelector(".topbar .save");
      return save !== null && save.textContent === "saved"
        && document.querySelector(".canvas .saving") === null && document.querySelector(".busy") === null;
    }, null, { timeout });
  }

  /** Until the face's version is not `version`; returns the face. Polled from here: the worker answers each ask in turn with the edits. */
  async waitVersion(version: number, timeout = 15_000): Promise<Summary> {
    const deadline = Date.now() + timeout;
    for (;;) {
      const doc = await this.doc();
      if (doc.version !== version) return doc;
      if (Date.now() > deadline) throw new Error(`the face stayed at version ${version} for ${timeout} ms`);
      await this.page.waitForTimeout(100);
    }
  }

  /**
   * Until `locator`'s value (an input or select) is `value`: a panel reads
   * the face back from the worker after a change, a moment after the text
   * has it, so a control is read with patience.
   */
  async expectValue(locator: Locator, value: string, timeout = 8_000): Promise<void> {
    const deadline = Date.now() + timeout;
    let seen = "";
    while (Date.now() < deadline) {
      seen = await locator.inputValue().catch(() => "<gone>");
      if (seen === value) return;
      await this.page.waitForTimeout(100);
    }
    throw new Error(`the control shows ${JSON.stringify(seen)}, not ${JSON.stringify(value)}`);
  }

  /** Until `locator`'s text matches `pattern`, as `expectValue`. */
  async expectText(locator: Locator, pattern: RegExp | string, timeout = 8_000): Promise<string> {
    const deadline = Date.now() + timeout;
    let seen = "";
    while (Date.now() < deadline) {
      seen = (await locator.textContent().catch(() => null)) ?? "<gone>";
      if (typeof pattern === "string" ? seen === pattern : pattern.test(seen)) return seen;
      await this.page.waitForTimeout(100);
    }
    throw new Error(`the text is ${JSON.stringify(seen)}, which does not match ${pattern}`);
  }

  /** Every toast shown since `t` (a `Date.now()`), oldest first. */
  async toastsSince(t: number): Promise<string[]> {
    return this.page.evaluate((t) => ((window as unknown as { __toasts?: { t: number; text: string }[] }).__toasts || [])
      .filter((x) => x.t >= t).map((x) => x.text), t);
  }

  /** Until a toast matching `pattern` has shown since `t`; returns it. */
  async waitToast(t: number, pattern: RegExp, timeout = 10_000): Promise<string> {
    const deadline = Date.now() + timeout;
    for (;;) {
      const found = (await this.toastsSince(t)).find((x) => pattern.test(x));
      if (found !== undefined) return found;
      if (Date.now() > deadline) throw new Error(`no toast matching ${pattern} since ${t}; shown: ${JSON.stringify(await this.toastsSince(t))}`);
      await this.page.waitForTimeout(100);
    }
  }

  // -- the editor's parts ----------------------------------------------------

  /** The left panel's tab, "Layers" or "Face". */
  async leftTab(name: "Layers" | "Face"): Promise<void> {
    const tab = this.page.locator(".panel.left .tabs.top button", { hasText: name });
    if (!/\bon\b/.test((await tab.getAttribute("class")) || "")) await tab.click();
  }

  /** The centre's pane, "Face" or "YAML". */
  async pane(name: "Face" | "YAML"): Promise<void> {
    const button = this.page.locator(".controls .seg button", { hasText: name });
    if (!/\bon\b/.test((await button.getAttribute("class")) || "")) await button.click();
    if (name === "YAML") await this.page.waitForSelector(".cm-editor .cm-content");
  }

  /** The Face tab's section by its button text ("Colours", "Styles", ...). */
  async faceSection(title: string): Promise<void> {
    await this.leftTab("Face");
    await this.page.locator(".face-nav button", { hasText: title }).click();
  }

  /** One Layers row by element id. */
  layerRow(id: string): Locator {
    return this.page.locator(".layers .item").filter({ has: this.page.locator(`:scope > span:first-child:text-is("${id}")`) }).first();
  }

  /** Click the layer `id` and wait until Properties shows it; `modifiers` add to the selection. */
  async selectLayer(id: string, modifiers: ("Control" | "Shift")[] = []): Promise<void> {
    await this.leftTab("Layers");
    await this.layerRow(id).click({ modifiers });
    if (!modifiers.length) await this.waitInspected(id);
  }

  /** Until Properties shows the element `id`, with its keys loaded. */
  async waitInspected(id: string): Promise<void> {
    await this.page.waitForFunction((id) => {
      const head = document.querySelector(".inspector .ins-head .name");
      return head !== null && head.textContent === id && document.querySelector(".inspector .field") !== null;
    }, id, { timeout: 15_000 });
  }

  /** The Properties field for the key `name` at the top level of the selected element. */
  topField(name: string): Locator {
    // the name's own span (an object's or list's sits in its head); a badge beside it names where the watch reads the key
    return this.page.locator(".inspector > .field").filter({ has: this.page.locator(":scope > .name > .key, :scope > .head > .name > .key").filter({ hasText: new RegExp(`^${name}$`) }) }).first();
  }

  /** The child field `child` of the object field `parent` (`at` → `dx`). */
  childField(parent: string, child: string): Locator {
    return this.topField(parent).locator(".children > .field").filter({ has: this.page.locator(":scope > .name > .key, :scope > .head > .name > .key").filter({ hasText: new RegExp(`^${child}$`) }) }).first();
  }

  /** Type `text` into a Commit input and press Enter, which blurs and commits it. */
  async commit(input: Locator, text: string): Promise<void> {
    await input.fill(text);
    await input.press("Enter");
  }

  /** The frame as drawn, and where its pixels are on the screen. */
  async placed(): Promise<Placed> {
    const id = await this.id();
    const view = await this.page.evaluate(() => {
      const device = (document.querySelector(".controls select") as HTMLSelectElement).value;
      const styleLabel = [...document.querySelectorAll(".controls label")].find((l) => l.textContent!.startsWith("Style"));
      const style = styleLabel ? (styleLabel.querySelector("select") as HTMLSelectElement).value : "";
      const img = document.querySelector(".canvas img.frame")!;
      const r = img.getBoundingClientRect();
      return { device, style, rect: { left: r.left, top: r.top, width: r.width, height: r.height } };
    });
    const frame = await this.api("frame", { id, device: view.device, scale: 2, style: view.style, time: "", date: "", asleep: false, aod: false, picks: "" });
    const zoom = view.rect.width / frame.width;
    const item = (id: string): FrameItem => {
      const found = frame.items.find((i) => i.id === id);
      if (!found) throw new Error(`${id} is not in the frame: ${frame.items.map((i) => i.id).join(", ")}`);
      return found;
    };
    let masks: Awaited<ReturnType<typeof inkMasks>> | null = null;
    return {
      frame, rect: view.rect, zoom, item,
      at: (x, y) => ({ x: view.rect.left + x * zoom, y: view.rect.top + y * zoom }),
      handle: (id, kind, which) => {
        const found = item(id).handles.find((h) => h.kind === kind && (which === undefined || h.part === which || (Array.isArray(h.key) ? h.key.join(".") : h.key) === which));
        if (!found) throw new Error(`${id} has no ${kind} handle${which ? ` for ${which}` : ""}: ${JSON.stringify(item(id).handles)}`);
        return found;
      },
      ink: async (id) => {
        masks ??= await inkMasks(frame);
        const own = masks.findIndex((m) => m.id === id);
        if (own < 0) throw new Error(`${id} has no layer in the frame`);
        const [bx, by, bw, bh] = item(id).box;
        const cx = bx + bw / 2, cy = by + bh / 2;
        let best: { x: number; y: number; d: number } | null = null;
        for (let y = by; y < by + bh; y++) {
          for (let x = bx; x < bx + bw; x++) {
            const d = (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2;
            if (best && d >= best.d) continue;
            if (!masks[own]!.has(x, y)) continue;
            if (masks.slice(own + 1).some((m) => m.has(x, y))) continue;
            best = { x, y, d };
          }
        }
        if (!best) throw new Error(`${id} has no uncovered ink in its box ${JSON.stringify(item(id).box)}`);
        return { x: best.x + 0.5, y: best.y + 0.5 };
      },
    };
  }

  /** A mouse drag from `from` to `to` (screen coordinates), in steps; returns the drag hint shown at the end. */
  async drag(from: { x: number; y: number }, to: { x: number; y: number }, { steps = 8, alt = false } = {}): Promise<string | null> {
    const { mouse, keyboard } = this.page;
    await mouse.move(from.x, from.y);
    await mouse.down();
    if (alt) await keyboard.down("Alt");
    let hint: string | null = null;
    for (let i = 1; i <= steps; i++) {
      await mouse.move(from.x + ((to.x - from.x) * i) / steps, from.y + ((to.y - from.y) * i) / steps);
      if (i === steps) hint = await this.page.locator(".canvas .drag-hint").textContent({ timeout: 500 }).catch(() => null);
    }
    await mouse.up();
    if (alt) await keyboard.up("Alt");
    return hint;
  }

  /**
   * A drag of `dx`, `dy` device pixels starting on the element `id`'s own
   * ink (or at the device pixel `from`); returns the face after it, once the
   * change is written or refused.
   */
  async dragElement(id: string, dx: number, dy: number, options: { steps?: number; alt?: boolean; from?: { x: number; y: number } } = {}): Promise<Summary> {
    const p = await this.placed();
    const start = options.from ?? await p.ink(id);
    return this.dragFrom(p, start, dx, dy, options);
  }

  /** A drag of `dx`, `dy` device pixels from the handle `kind` (and `which`) of the selected element `id`. */
  async dragHandle(id: string, kind: Handle["kind"], which: string | undefined, dx: number, dy: number, options: { steps?: number; alt?: boolean } = {}): Promise<Summary> {
    const p = await this.placed();
    const h = p.handle(id, kind, which);
    return this.dragFrom(p, { x: h.x, y: h.y }, dx, dy, options);
  }

  private async dragFrom(p: Placed, start: { x: number; y: number }, dx: number, dy: number, options: { steps?: number; alt?: boolean }): Promise<Summary> {
    const before = await this.doc();
    const from = p.at(start.x, start.y);
    const t = Date.now();
    await this.drag(from, { x: from.x + dx * p.zoom, y: from.y + dy * p.zoom }, options);
    // written (a new version), or refused (a toast); either way the outbox empties
    const deadline = Date.now() + 15_000;
    for (;;) {
      if ((await this.doc()).version !== before.version || (await this.toastsSince(t)).length > 0) break;
      if (Date.now() > deadline) throw new Error("the drag was neither written nor refused in 15 s");
      await this.page.waitForTimeout(100);
    }
    await this.waitIdle();
    return this.doc();
  }

  /** The top bar's Undo; returns the face after it. */
  async undo(): Promise<Summary> {
    const before = await this.doc();
    const button = this.page.locator(".topbar .undo-group button", { hasText: "Undo" });
    if (await button.isDisabled()) throw new Error(`Undo is disabled: ${await button.getAttribute("title")}`);
    await button.click();
    await this.waitVersion(before.version);
    await this.waitIdle();
    return this.doc();
  }

  /** The top bar's Redo; returns the face after it. */
  async redo(): Promise<Summary> {
    const before = await this.doc();
    await this.page.locator(".topbar .undo-group button", { hasText: "Redo" }).click();
    await this.waitVersion(before.version);
    await this.waitIdle();
    return this.doc();
  }

  /** The YAML pane's whole text and selection, as CodeMirror holds them (its view hangs off the content element). */
  async yamlState(): Promise<{ text: string; selected: string }> {
    return this.page.evaluate(() => {
      type View = { state: { doc: { toString(): string }; selection: { main: { from: number; to: number } } } };
      const cm = document.querySelector(".cm-content") as (HTMLElement & { cmTile?: { root: { view: View } } }) | null;
      if (!cm) throw new Error("the YAML pane is not open");
      const view = cm.cmTile?.root.view;
      if (!view) throw new Error("the YAML pane's editor is not reachable from its content element");
      const text = view.state.doc.toString();
      const { from, to } = view.state.selection.main;
      return { text, selected: text.slice(from, to) };
    });
  }

  /** The YAML pane's whole text. */
  async yamlText(): Promise<string> {
    return (await this.yamlState()).text;
  }

  /** Until `check` returns true; `what` names the wait in the error. */
  async eventually(check: () => Promise<boolean>, what: string, timeout = 8_000): Promise<void> {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (await check()) return;
      await this.page.waitForTimeout(100);
    }
    throw new Error(`gave up waiting for ${what}`);
  }

  /** Replace the YAML pane's text as typing would: select all, type `text` (an insertText, so CodeMirror sees one edit). */
  async typeYaml(text: string): Promise<void> {
    const content = this.page.locator(".cm-content");
    await content.click();
    await this.page.keyboard.press("Control+a");
    await this.page.keyboard.insertText(text);
  }

  /** Append `text` to the YAML pane at its end, typed key by key. */
  async appendYaml(text: string): Promise<void> {
    const content = this.page.locator(".cm-content");
    await content.click();
    await this.page.keyboard.press("Control+End");
    await this.page.keyboard.type(text);
  }

  /** Every Messages-log entry (newest first), opened and closed again. */
  async messageLog(): Promise<string[]> {
    const button = this.page.locator(".log-badge button").first();
    if (!(await button.count())) return [];
    await button.click();
    await this.page.locator(".log li").first().waitFor({ timeout: 5000 });
    const items = await this.page.locator(".log li").allInnerTexts();
    await this.page.keyboard.press("Escape");
    return items;
  }
}

export interface Harness {
  base: string;
  context: BrowserContext;
  /** A test with a fresh page; skipped, with the reason, when the suite cannot run here. */
  test(name: string, fn: (s: Session, t: TestContext) => Promise<void>, options?: { timeout?: number }): void;
}

/**
 * The file's suite: the server and the browser, started once and torn down
 * after the file's tests. `url` is the test file's `import.meta.url`, which
 * names its screenshots.
 */
export async function suite(url: string): Promise<Harness> {
  const file = basename(fileURLToPath(url)).replace(/\.test\.ts$/, "");
  const skip = skipReason();
  if (skip) {
    return {
      base: "", context: null as unknown as BrowserContext,
      test: (name) => { test(name, { skip }, () => {}); },
    };
  }
  const { chromium } = loadPlaywright();
  const server = await startServer();
  const browser: Browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: VIEWPORT, acceptDownloads: true });
  await context.addInitScript(TOAST_INIT);
  after(async () => {
    await browser.close().catch(() => {});
    server.child.kill();
  });
  mkdirSync(SHOTS, { recursive: true });
  return {
    base: server.base, context,
    test(name, fn, options = {}) {
      test(name, { timeout: options.timeout ?? 180_000 }, async (t) => {
        const page = await context.newPage();
        const s = new Session(page, server.base);
        try {
          await fn(s, t);
        } catch (e) {
          const shot = join(SHOTS, `${file}-${name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.png`);
          await page.screenshot({ path: shot, fullPage: true }).catch(() => {});
          t.diagnostic(`screenshot: ${relative(REPO_ROOT, shot)}`);
          if (s.errors.length) t.diagnostic(`page errors: ${s.errors.join(" | ")}`);
          // the editor's own messages (a refused edit, a frame that failed) say what the page saw
          const messages = await Promise.race([s.messageLog().catch(() => []), new Promise<string[]>((r) => setTimeout(() => r([]), 8_000))]);
          if (messages.length) t.diagnostic(`messages: ${messages.join(" | ")}`);
          throw e;
        } finally {
          // a page left mid-unload by a test could keep a plain close waiting; the browser closes it at the end anyway
          await Promise.race([page.close().catch(() => {}), new Promise((r) => setTimeout(r, 10_000))]);
        }
      });
    },
  };
}

/** The repository-relative name of `path`, for messages. */
export function shortName(path: string): string {
  return relative(REPO_ROOT, path);
}
