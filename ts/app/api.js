// The editor's requests: an operation and its arguments (`api("edit",
// {id, version, edit})`), answered by its worker (`/dist/worker.js`, the
// compiler and the history store in this browser, `src/studio/router.ts`
// lists the operations). Each names this tab; a refusal is thrown as an
// Error carrying its status (400 refused, 404 gone, 409 stale). What only
// the server has (a build's .prg) stays a plain URL.

import { TAB } from "./session.js";

const waiting = new Map();
const listeners = new Set();
let next = 0;
let worker = null;
let loaded = false;      // the worker has answered once
let failed = null;       // the answer every request gets once the worker failed to load

// Started on the first request, so a module that only draws (and its tests) needs none.
function started() {
  if (worker === null) {
    worker = new Worker("/dist/worker.js", { type: "module" });
    worker.onmessage = (e) => {
      loaded = true;
      const { id, response, event, data } = e.data;
      if (event) { for (const f of listeners) f(event, data); return; }
      waiting.get(id)(response);
      waiting.delete(id);
    };
    // The worker did not load (the server stopped, say): every request
    // waiting, and every one after, is answered with that, not left hanging.
    // An error once it has answered is its own, and its request says so.
    worker.onerror = (e) => {
      if (loaded) return;
      e.preventDefault();
      failed = { status: 503, json: { error: "the editor's worker did not start: is wfb studio still running? Reload the page once it is" } };
      for (const answer of waiting.values()) answer(failed);
      waiting.clear();
    };
  }
  return worker;
}

// The worker's answer to `op`: `{status, json}` or `{status, body, type, filename}`.
// `body` is a file's bytes (a Blob or a Uint8Array): an upload or an asset.
export async function call(op, args = {}, body = null) {
  const bytes = body instanceof Blob ? new Uint8Array(await body.arrayBuffer()) : body;
  const id = next++;
  return new Promise((resolve) => {
    if (failed) { resolve(failed); return; }
    waiting.set(id, resolve);
    started().postMessage({ id, request: { op, args, body: bytes, tab: TAB } });
  });
}

function refused(response) {
  return Object.assign(new Error((response.json && response.json.error) || `${response.status}`), { status: response.status });
}

export async function api(op, args = {}, body = null) {
  const response = await call(op, args, body);
  if (response.status >= 400) throw refused(response);
  return response.json;
}

// An answer that is a file (a PNG, a download) as an object URL; the caller revokes it.
export async function objectUrl(op, args = {}) {
  const response = await call(op, args);
  if (response.status >= 400) throw refused(response);
  return URL.createObjectURL(new Blob([response.body], { type: response.type }));
}

// `blob` saved as `filename` through the browser's downloads.
export function saveBlob(blob, filename) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

// Save an answer that is a file, under the name the worker gave it.
export async function download(op, args = {}) {
  const response = await call(op, args);
  if (response.status >= 400) throw refused(response);
  saveBlob(new Blob([response.body], { type: response.type }), response.filename || "face");
}

// What the studio did, in this tab or another (once this tab's worker has
// read it): `onEvent(name, data)` until the returned function is called.
export function listen(onEvent) {
  started();
  listeners.add(onEvent);
  return () => listeners.delete(onEvent);
}

