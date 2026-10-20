// The editor's service worker, served as `sw.js` beside the page: it keeps
// the last copy of everything the page and its worker fetched, and answers
// from it when the server cannot be reached, so the editor opens and works
// with no network. Building needs the server and is never answered here.
//
// The network always comes first, so a reachable server is never shadowed
// by an old copy and a new version needs no cache naming. A sign-in
// redirect from a proxy in front (Cloudflare Access, say) is passed to the
// browser, never kept: the page's own load follows it to the sign-in page.
// The same redirect on a background fetch fails as a cross-origin request,
// and is answered from the copy like any other failure.
declare const self: ServiceWorkerGlobalScope;

export const CACHE = "wfb-studio";
/** What a first visit fetches before this worker controls the page, relative to the page. */
export const SHELL = [
  "./", "static/studio.css", "static/manifest.webmanifest", "static/icon-192.png", "static/icon-512.png",
  "dist/app.js", "dist/raster.js", "dist/worker.js", "api/schema", "api/icon-font", "api/devices",
];

/** A response worth keeping: the server's own, whole, not a redirect's end. */
const keep = (response: Response): boolean => response.ok && response.type === "basic" && !response.redirected;

/** The kept copy for `request`; another query of the same path when that one was never fetched (a device's extras for other faces). */
async function kept(request: Request): Promise<Response | undefined> {
  return await caches.match(request) ?? await caches.match(request, { ignoreSearch: true });
}

/** `request` from the server, kept when whole; the kept copy when the server, or the proxy before it, fails. */
export async function answer(request: Request): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(request);
  } catch (error) {
    const copy = await kept(request);
    if (copy !== undefined) return copy;
    throw error;
  }
  if (keep(response)) await (await caches.open(CACHE)).put(request, response.clone());
  // 5xx: the proxy could not reach the server (a tunnel down, the server stopped)
  else if (response.status >= 500) return await kept(request) ?? response;
  return response;
}

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // one missing file (no icon font installed) must not stop the rest
    await Promise.all(SHELL.map(async (path) => {
      try {
        const response = await fetch(path);
        if (keep(response)) await cache.put(path, response);
      } catch { /* kept on its next fetch */ }
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  // a build's .prg is the server's alone, and only lasts while it runs
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.includes("/api/builds/")) return;
  event.respondWith(answer(request));
});
