// The editor's requests: an operation and its arguments (`api("edit",
// {id, version, edit})`), answered by its worker (`/dist/worker.js`, the
// compiler and the history store in this browser). Every operation, its
// arguments and its answer is `src/studio/protocol.ts`, which types what
// `api` returns. Each request names this tab; a refusal is thrown as an
// Error carrying its status (400 refused, 404 gone, 409 stale). What only
// the server has (a build's .prg) stays a plain URL.

import type { Answer, Args, EventFields, EventName, Op, RefusedResponse, Request, Response } from "../src/studio/protocol.ts";
import { TAB } from "./session.ts";

/** What the worker posts: an answer to the request `id`, or an event. */
type Incoming = { id: number; response: Response } | { event: EventName; data: EventFields };

type Listener = (event: EventName, data: EventFields) => void;

const waiting = new Map<number, (response: Response) => void>();
const listeners = new Set<Listener>();
let next = 0;
let worker: Worker | null = null;
let loaded = false;                        // the worker has answered once
let failed: RefusedResponse | null = null; // the answer every request gets once the worker failed to load

// Started on the first request, so a module that only draws (and its tests) needs none.
function started(): Worker {
  if (worker === null) {
    worker = new Worker("/dist/worker.js", { type: "module" });
    worker.onmessage = (e: MessageEvent) => {
      loaded = true;
      const message = e.data as Incoming;   // the worker boundary: `postMessage` carries untyped data
      if ("event" in message) { for (const f of listeners) f(message.event, message.data); return; }
      waiting.get(message.id)?.(message.response);
      waiting.delete(message.id);
    };
    // The worker did not load (the server stopped, say): every request
    // waiting, and every one after, is answered with that, not left hanging.
    // An error once it has answered is its own, and its request says so.
    worker.onerror = (e: ErrorEvent) => {
      if (loaded) return;
      e.preventDefault();
      failed = { status: 503, json: { error: "the editor's worker did not start: is wfb studio still running? Reload the page once it is" } };
      for (const answer of waiting.values()) answer(failed);
      waiting.clear();
    };
  }
  return worker;
}

/**
 * The worker's answer to `op`: `{status, json}` or `{status, body, type, filename}`.
 * `body` is a file's bytes (a Blob or a Uint8Array): an upload or an asset.
 */
export async function call<O extends Op>(op: O, args?: Args<O>, body: Blob | Uint8Array | null = null): Promise<Response<O>> {
  const bytes = body instanceof Blob ? new Uint8Array(await body.arrayBuffer()) : body;
  const id = next++;
  return new Promise((resolve) => {
    if (failed) { resolve(failed); return; }
    waiting.set(id, resolve as (response: Response) => void);
    const request: Request<O> = { op, args: (args ?? {}) as Args<O>, body: bytes, tab: TAB } as Request<O>;
    started().postMessage({ id, request });
  });
}

function refused(response: RefusedResponse): Error & { status: number } {
  return Object.assign(new Error((response.json && response.json.error) || `${response.status}`), { status: response.status });
}

/** The worker's JSON answer to `op`, or the refusal thrown. */
export async function api<O extends Op>(op: O, args?: Args<O>, body: Blob | Uint8Array | null = null): Promise<Answer<O>> {
  const response = await call(op, args, body);
  if (response.status !== 200) throw refused(response);
  return response.json as Answer<O>;
}

/** The bytes of an answer that is a file, as a Blob of its type. */
function fileOf(response: Response): Blob {
  if (response.status !== 200) throw refused(response);
  if (response.body === undefined) throw new Error("the answer is not a file");
  return new Blob([response.body as Uint8Array<ArrayBuffer>], { type: response.type });
}

/** An answer that is a file (a PNG, a download) as an object URL; the caller revokes it. */
export async function objectUrl<O extends Op>(op: O, args?: Args<O>): Promise<string> {
  return URL.createObjectURL(fileOf(await call(op, args)));
}

// `blob` saved as `filename` through the browser's downloads.
export function saveBlob(blob: Blob, filename: string): void {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

/** Save an answer that is a file, under the name the worker gave it. */
export async function download<O extends Op>(op: O, args?: Args<O>): Promise<void> {
  const response = await call(op, args);
  saveBlob(fileOf(response), (response.status === 200 && response.filename) || "face");
}

/**
 * What the studio did, in this tab or another (once this tab's worker has
 * read it): `onEvent(name, data)` until the returned function is called.
 */
export function listen(onEvent: Listener): () => void {
  started();
  listeners.add(onEvent);
  return () => { listeners.delete(onEvent); };
}
