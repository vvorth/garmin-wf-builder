// The editor's service worker (src/studio/sw.ts): the network first, its
// whole answers kept, the kept copy when the server or its proxy fails, and
// a proxy's sign-in redirect passed through.
import assert from "node:assert/strict";
import { test } from "node:test";

const kept = new Map<string, Response>();
const listeners = new Map<string, (event: unknown) => void>();
let network: (request: Request) => Promise<Response>;
const ORIGIN = "https://studio.example";
const path = (url: string): string => url.split("?")[0]!;
Object.assign(globalThis, {
  self: { location: new URL(`${ORIGIN}/wfb/sw.js`), addEventListener: (name: string, f: (event: unknown) => void) => listeners.set(name, f) },
  fetch: (request: Request) => network(request),
  caches: {
    open: async () => ({ put: async (request: Request, response: Response) => void kept.set(request.url, response) }),
    match: async (request: Request, options?: { ignoreSearch?: boolean }) => {
      const copy = kept.get(request.url) ?? (options?.ignoreSearch ? [...kept].find(([url]) => path(url) === path(request.url))?.[1] : undefined);
      return copy?.clone();
    },
  },
});
const { answer } = await import("../src/studio/sw.ts");

const get = (p: string): Request => new Request(`${ORIGIN}/wfb/${p}`);
const served = (body: string, status = 200): Response => Object.defineProperty(new Response(body, { status }), "type", { value: "basic" });
const down = async (): Promise<Response> => { throw new TypeError("Failed to fetch"); };

test("a reachable server answers, and its whole answers are kept for later", async () => {
  network = async () => served("schema v2");
  assert.equal(await (await answer(get("api/schema"))).text(), "schema v2");
  network = down;
  assert.equal(await (await answer(get("api/schema"))).text(), "schema v2", "no network: the kept copy");
});

test("a proxy's 5xx (the server unreachable behind it) is answered from the copy; a 404 is not", async () => {
  network = async () => served("app v1");
  await answer(get("dist/app.js"));
  network = async () => served("Bad gateway", 502);
  assert.equal(await (await answer(get("dist/app.js"))).text(), "app v1");
  network = async () => served("not found", 404);
  assert.equal((await answer(get("dist/app.js"))).status, 404);
  assert.equal((await answer(get("never-seen"))).status, 404);
});

test("a sign-in redirect reaches the browser, and is never kept", async () => {
  const redirect = { ok: false, status: 0, type: "opaqueredirect", redirected: false } as unknown as Response;
  network = async () => redirect;
  assert.equal(await answer(get("./")), redirect);
  assert.equal(kept.has(`${ORIGIN}/wfb/`), false);
});

test("a device's extras for other faces stand in for the ones never fetched; nothing kept fails as the network did", async () => {
  network = async () => served("fr955 fonts");
  await answer(get("api/devices/fr955/extras"));
  network = down;
  assert.equal(await (await answer(get("api/devices/fr955/extras?faces=RobotoCondensedBold"))).text(), "fr955 fonts");
  await assert.rejects(answer(get("api/devices/fenix7/extras")), /Failed to fetch/);
});

test("a build, and anything not a GET of this origin, goes to the network untouched", () => {
  const responded: string[] = [];
  const fetchEvent = (request: Request): void =>
    listeners.get("fetch")!({ request, respondWith: () => responded.push(request.url) });
  fetchEvent(new Request(`${ORIGIN}/wfb/api/build?device=fr955`, { method: "POST" }));
  fetchEvent(get("api/builds/0123"));
  fetchEvent(new Request("https://elsewhere.example/x"));
  fetchEvent(get("api/schema"));
  assert.deepEqual(responded, [`${ORIGIN}/wfb/api/schema`]);
});
