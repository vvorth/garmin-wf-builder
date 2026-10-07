// The editor's requests: answered by its worker (`/dist/worker.js`, the
// compiler and the history store in this browser), JSON in and out, each
// naming this tab, a refusal thrown as an Error carrying its status. What
// only the server has (a build's .prg) stays a plain URL.

import { TAB } from "./session.js";

const waiting = new Map();
const listeners = new Set();
let next = 0;
let worker = null;

// Started on the first request, so a module that only draws (and its tests) needs none.
function started() {
  if (worker === null) {
    worker = new Worker("/dist/worker.js", { type: "module" });
    worker.onmessage = (e) => {
      const { id, response, event, data } = e.data;
      if (event) { for (const f of listeners) f(event, data); return; }
      waiting.get(id)(response);
      waiting.delete(id);
    };
  }
  return worker;
}

// The worker's answer to `path`: `{status, json}` or `{status, body, type, filename}`.
export async function call(path, { method = "GET", body = null } = {}) {
  let bytes = null;
  if (typeof body === "string") bytes = new TextEncoder().encode(body);
  else if (body instanceof Blob) bytes = new Uint8Array(await body.arrayBuffer());
  else if (body) bytes = body;
  const id = next++;
  return new Promise((resolve) => {
    waiting.set(id, resolve);
    started().postMessage({ id, request: { method, url: path, body: bytes, tab: TAB } });
  });
}

function refused(response) {
  const error = new Error((response.json && response.json.error) || `${response.status}`);
  error.status = response.status;
  return error;
}

export async function api(path, options = {}) {
  const response = await call(path, options);
  if (response.status >= 400) throw refused(response);
  return response.json;
}

// An answer that is a file (a PNG, a download) as an object URL; the caller revokes it.
export async function objectUrl(path, options = {}) {
  const response = await call(path, options);
  if (response.status >= 400) throw refused(response);
  return URL.createObjectURL(new Blob([response.body], { type: response.type }));
}

// Save an answer that is a file, under the name the worker gave it.
export async function download(path) {
  const response = await call(path);
  if (response.status >= 400) throw refused(response);
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([response.body], { type: response.type }));
  link.download = response.filename || "face";
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

// What the studio did, in this tab or another (once this tab's worker has
// read it): `onEvent(name, data)` until the returned function is called.
export function listen(onEvent) {
  started();
  listeners.add(onEvent);
  return () => listeners.delete(onEvent);
}

export const enc = encodeURIComponent;
