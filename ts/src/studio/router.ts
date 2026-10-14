// The editor's requests, answered in the browser: an operation and its
// arguments (`{op: "edit", args: {id, version, op}}`), as the page's
// `api.ts` sends them, mapped to the studio. The worker (`./worker.ts`)
// runs it on every message; the tests run it directly. The arguments come
// as the page wrote them, structured-cloned, so each is checked for its
// type here.
//
// An answer is `{status, json}`, or `{status, body, type, filename}` for a
// file; a refusal's status says why: 400 refused, 404 no such face or
// snapshot, 409 the face moved on (stale), 507 the store failed. Every
// request's arguments and every answer's shape is `./protocol.ts`.
//
// Requests are answered one at a time (`exclusive`), so no two interleave
// over one face; a build waits its turn only to check and pack the face, and
// the server's compile runs outside it, so editing goes on meanwhile. The
// queue has lanes (`PRIORITY`): a change, and a read that must see the
// newest state, goes ahead of a frame waiting to be drawn, and a frame
// ahead of a thumbnail, so a run of thumbnails never delays an edit; within
// a lane, requests are answered in the order asked. A frame or thumbnail
// asked again while an older ask for the same picture (its `v`, the face's
// version, apart) is still waiting is drawn once, and both asks get it.
//
// Each answer waits for the store's writes, so an acknowledged change is
// kept. What the studio did is announced through `emit` ("created",
// "changed", "deleted", "renamed", "snapshot"), which the worker hands its
// page and the other tabs' workers.
import { slug } from "../build.ts";
import { DeviceError } from "../devices/device.ts";
import { indexFor, Refused } from "../edit/spans.ts";
import { encodePng } from "../png.ts";
import { skinFor } from "../preview.ts";
import { quoted } from "../py.ts";
import * as starters from "../starters.ts";
import { BundleError, bundle, readUpload, toZip } from "./bundle.ts";
import { base64, type Document, frameKey, type FrameKey, StaleVersion, type Studio } from "./document.ts";
import { devices, vocabulary } from "./inspect.ts";
import { plain } from "./json.ts";
import type {
  Answer, BuildResult, Event, EventData, EventName, FaceUiState, Home, Op, RefusedResponse, Request, Response, Skin, UiState,
  Vocabulary,
} from "./protocol.ts";
import { StoreError, UnknownDocument, UnknownSnapshot } from "./store.ts";

export type { Request, Response };

/** A request's arguments as they arrive: checked field by field below. */
type Json = Record<string, unknown>;

export interface Host {
  /** Load whatever the named devices need before the compiler reads them (fonts, skins, the vector `faces` named); nothing in Node. */
  prepare(deviceIds: readonly string[], faces?: readonly string[]): Promise<void>;
  /** Build a face's bundle for one watch on the server. */
  build(zip: Uint8Array, device: string, version: number, stem: string): Promise<BuildResult>;
  /** Tell the page, and the other tabs, what the studio did. */
  emit(event: Event): void;
  /** The installed devices as the vocabulary lists them, when the host has them listed already (`inspect.devices`). */
  devices?(): ReturnType<typeof devices>;
}

// `plain` guards the answer against a stray `Map`; the builders already return the protocol's shapes.
const json = <T extends Answer<Op>>(value: T): { status: 200; json: T } => ({ status: 200, json: plain(value) as T });
const error = (status: RefusedResponse["status"], message: string): RefusedResponse => ({ status, json: { error: message } });

function int(args: Json, name: string): number {
  const value = args[name];
  if (!Number.isInteger(value)) throw new Refused(`${name} must be a whole number`);
  return value as number;
}

/** `args[name]` as text: absent is `""`. */
function text(args: Json, name: string): string {
  const value = args[name] ?? "";
  if (typeof value !== "string") throw new Refused(`${name} must be text`);
  return value;
}

function object(args: Json, name: string): Json {
  const value = args[name];
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Refused(`${name} must be an object`);
  return value as Json;
}

function time(raw: string | null): [number, number, number] | null {
  if (!raw) return null;
  const m = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(raw);
  if (m === null || Number(m[1]) > 23 || Number(m[2]) > 59 || Number(m[3] ?? 0) > 59) throw new Refused(`time ${quoted(raw)} is not HH:MM or HH:MM:SS`);
  return [Number(m[1]), Number(m[2]), Number(m[3] ?? 0)];
}

function date(raw: string | null): [number, number, number] | null {
  if (!raw) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  const [y, mo, d] = m === null ? [0, 0, 0] : [Number(m[1]), Number(m[2]), Number(m[3])];
  const day = new Date(Date.UTC(y, mo - 1, d));
  if (m === null || day.getUTCFullYear() !== y || day.getUTCMonth() !== mo - 1 || day.getUTCDate() !== d) {
    throw new Refused(`date ${quoted(raw)} is not a day, YYYY-MM-DD`);
  }
  return [y, mo, d];
}

function picks(raw: string | null): [string, string][] {
  const out: [string, string][] = [];
  for (const item of (raw ?? "").split(",")) {
    const at = item.indexOf(":");
    const slot = at < 0 ? item.trim() : item.slice(0, at).trim(), type = at < 0 ? "" : item.slice(at + 1).trim();
    if (slot && type) out.push([slot, type]);
  }
  return out.sort((a, b) => (a[0] + "\0" + a[1] < b[0] + "\0" + b[1] ? -1 : 1));
}

function key(args: Json, scale: number | null = null): FrameKey {
  return frameKey({
    device: text(args, "device"), style: text(args, "style") || null, time: time(text(args, "time")), date: date(text(args, "date")),
    asleep: args["asleep"] === true, aod: args["aod"] === true,
    scale: Math.min(4, Math.max(1, scale ?? (args["scale"] === undefined ? 2 : int(args, "scale")))), picks: picks(text(args, "picks")),
  });
}

/** The devices a face's text targets and the vector faces its fonts name, as far as it parses. */
function needs(text: string): [string[], string[]] {
  const get = (m: unknown, k: string): unknown => (m instanceof Map ? m.get(k) : undefined);
  let data: unknown;
  try {
    data = indexFor(text).data;
  } catch {
    return [[], []];
  }
  const targets = get(get(data, "build"), "targets");
  const fonts = get(get(data, "resources"), "fonts");
  const faces = fonts instanceof Map ? [...fonts.values()].flatMap((spec) => {
    const face = get(spec, "face");
    return Array.isArray(face) ? face.map(String) : [];
  }) : [];
  return [Array.isArray(targets) ? targets.map(String) : [], faces];
}

/** One ask waiting its turn: its lane, and the promise its asker holds; `pending` keeps asks in the order made. */
interface Queued {
  priority: number;
  work: () => Promise<unknown>;
  /** What picture this draws, when another ask for the same one may answer it (`sameAsk`). */
  same: string | null;
  resolve: (value: unknown) => void;
  reject: (error: unknown) => void;
}

/** The queue's lanes: 1 for a read that may see the state a moment later, 2 for a thumbnail; everything else, every change among it, 0. */
const PRIORITY: Record<string, number> = { get: 1, inspect: 1, frame: 1, handset: 1, cover: 1, thumbnail: 2 };

/** For a frame or thumbnail, what it draws: its arguments but `v`, the version the page asked at, with their keys sorted; `null` for any other request. */
function sameAsk({ op, args = {} }: Request): string | null {
  if (op !== "frame" && op !== "thumbnail") return null;
  const fields = args as Record<string, unknown>;
  const keys = Object.keys(fields).filter((k) => k !== "v").sort();
  return JSON.stringify([op, keys.map((k) => [k, fields[k] ?? null])]);
}

export class Router {
  readonly studio: Studio;
  readonly host: Host;

  constructor(studio: Studio, host: Host) {
    this.studio = studio;
    this.host = host;
  }

  /** What this request did, announced once its writes are on disk: another tab's worker reads them then. */
  private announced: Event[] = [];

  private emit<E extends EventName>(event: E, data: EventData<E>): void {
    this.announced.push({ event, data } as Event);
  }

  // One request at a time across every face; render is synchronous, so only a worker per face would let a slow frame not hold up another face.
  private readonly pending: Queued[] = [];
  private running = false;

  /** Run `work` once the queue reaches it, ahead of everything of a lower priority (`exclusive` is the first lane): the worker's timed snapshots and other tabs' reloads take their turn here too. */
  exclusive<T>(work: () => Promise<T>, priority = 0): Promise<T> {
    return this.enqueue(priority, work, null);
  }

  private enqueue<T>(priority: number, work: () => Promise<T>, same: string | null): Promise<T> {
    let resolve!: (value: unknown) => void, reject!: (error: unknown) => void;
    const promise = new Promise<T>((res, rej) => { resolve = res as (value: unknown) => void; reject = rej; });
    if (same !== null) {
      // an older ask for the same picture, not yet started, takes this one's answer instead of being drawn too
      const at = this.pending.findIndex((q) => q.same === same);
      if (at >= 0) this.pending.splice(at, 1)[0]!.resolve(promise);
    }
    this.pending.push({ priority, work, same, resolve, reject });
    void this.pump();
    return promise;
  }

  /** Run what is queued, one at a time, the first lane with anything waiting first and the earliest ask within it. */
  private async pump(): Promise<void> {
    if (this.running) return;
    this.running = true;
    while (this.pending.length > 0) {
      let at = 0;
      for (let i = 1; i < this.pending.length; i++) if (this.pending[i]!.priority < this.pending[at]!.priority) at = i;
      const next = this.pending.splice(at, 1)[0]!;
      try {
        next.resolve(await next.work());
      } catch (error) {
        next.reject(error);
      }
    }
    this.running = false;
  }

  /** Answer one request, in its lane's turn; every refusal is JSON with its status, never a stack trace. */
  async handle(request: Request): Promise<Response> {
    const answer = await this.enqueue(PRIORITY[request.op] ?? 0, () => this.answer(request), sameAsk(request));
    return typeof answer === "function" ? await answer() : answer;
  }

  /** The answer, or the work left to do once the queue is free again (a build). */
  private async answer(request: Request): Promise<Response | (() => Promise<Response>)> {
    this.announced = [];
    try {
      const answer = await this.route(request);
      await this.studio.store.flush();
      for (const event of this.announced) this.host.emit(event);
      return answer;
    } catch (e) {
      if (e instanceof UnknownDocument) return error(404, "there is no such face; it may have been deleted");
      if (e instanceof UnknownSnapshot) return error(404, "there is no such snapshot; it may have been pruned");
      if (e instanceof StaleVersion) return error(409, e.message);
      if (e instanceof BundleError || e instanceof Refused || e instanceof starters.UnknownTemplate || e instanceof DeviceError) return error(400, e.message);
      if (e instanceof StoreError) return error(507, e.message);
      throw e;
    }
  }

  /** The document `id`, with whatever its targets and `device` need loaded. */
  private async open(id: string, device: string | null = null): Promise<Document> {
    if (!this.studio.store.has(id)) throw new UnknownDocument(id);
    const doc = this.studio.document(id);
    const [wanted, faces] = needs(doc.text);
    if (device && !wanted.includes(device)) wanted.push(device);
    await this.host.prepare(wanted, faces);
    return doc;
  }

  /** A change made: announced, answered with the face. */
  private changed(doc: Document, tab: string | null): Response {
    this.emit("changed", { id: doc.id, version: doc.version, tab });
    return json(doc.summary());
  }

  private async route(request: Request): Promise<Response | (() => Promise<Response>)> {
    const { op, body = null, tab = null } = request;
    // the page's arguments are data: each is read by name and checked for its type below
    const args = (request.args ?? {}) as Json;
    const studio = this.studio;
    switch (op) {
      case "home":
        return json<Home>({
          templates: starters.names().map((n) => ({ name: n, blurb: starters.blurb(n) })),
          documents: studio.store.documents(), store: "this browser", shared: true,
        });
      case "vocabulary": {
        const [installed, unreadable] = this.host.devices?.() ?? devices(studio.db);
        return json<Vocabulary>({ ...vocabulary(), devices: installed, unreadable_devices: unreadable });
      }
      case "skin": {
        const device = text(args, "device");
        await this.host.prepare([device]);
        const scale = Math.min(4, Math.max(1, args["scale"] === undefined ? 2 : int(args, "scale")));
        const found = skinFor(studio.db.get(device), scale);
        if (found === null) return error(404, `${device}'s files have no skin`);
        const [image, [x, y]] = found;
        const png = encodePng(image.width, image.height, new Uint8Array(image.data.buffer, image.data.byteOffset, image.data.byteLength), 4);
        return json<Skin>({ device, scale, image: "data:image/png;base64," + base64(png), width: image.width, height: image.height, x, y });
      }
      case "new": {
        const template = text(args, "template") || "minimal";
        const faceName = text(args, "name").trim() || "My Face";
        return await this.created(studio.create(
          bundle(faceName, starters.instantiate(template, faceName), starters.files(template)), `new from the ${template} template`));
      }
      case "upload": {
        const filename = text(args, "filename");
        return await this.created(studio.create(readUpload(filename, body ?? new Uint8Array()), `open ${filename}`));
      }
    }

    const id = text(args, "id");
    const device = text(args, "device") || null;
    const doc = await this.open(id, op === "drag" ? null : device);
    switch (op) {
      case "get": return json(doc.summary());
      case "delete":
        studio.delete(id);
        this.emit("deleted", { id });
        return json({ deleted: id });
      case "rename":
        doc.rename(text(args, "name"));
        this.emit("renamed", { id, name: doc.name });
        return json({ id, name: doc.name });
      case "cover": {
        const png = doc.cover();
        return png === null ? error(404, "the face does not load, so it has no picture") : { status: 200, body: png, type: "image/png" };
      }
      case "goto":
        doc.goto(int(args, "seq"), int(args, "version"));
        return this.changed(doc, tab);
      case "frame": return json(doc.frame(key(args)));
      case "thumbnail": return { status: 200, body: doc.thumbnail(key(args, 1)), type: "image/png" };
      case "handset":
        return { status: 200, body: doc.handSetImage(text(args, "name"), device ?? "", args["scale"] === undefined ? 1 : int(args, "scale")), type: "image/png" };
      case "drag": return await this.drag(doc, args, tab);
      case "assets": {
        const font = text(args, "font") || null;
        doc.addAsset(text(args, "filename"), body ?? new Uint8Array(), text(args, "reference") || null, int(args, "version"),
          font ? [font, text(args, "size") || "10%r"] : null);
        return this.changed(doc, tab);
      }
      case "edit":
        doc.edit(object(args, "edit"), int(args, "version"));
        return this.changed(doc, tab);
      case "structure": {
        const [, select] = doc.structure(object(args, "edit"), int(args, "version"));
        this.emit("changed", { id: doc.id, version: doc.version, tab });
        return json({ ...doc.summary(), select });
      }
      case "batch": {
        const [, select] = doc.batch({ op, label: args["label"], edits: args["edits"] }, int(args, "version"));
        this.emit("changed", { id: doc.id, version: doc.version, tab });
        return json({ ...doc.summary(), select });
      }
      case "text":
        doc.replaceText(text(args, "text"), int(args, "version"));
        return this.changed(doc, tab);
      case "inspect": {
        const element = args["element"];
        if (!Array.isArray(element)) throw new Refused("element is a list");
        return json(doc.inspect(element, device));
      }
      case "build": {
        const target = device ?? "";
        doc.check(int(args, "version"));
        const watch = studio.db.get(target);
        if (!watch.supportsWatchface) throw new Refused(`${target} cannot run a watch face`);
        if (doc.analysis().face === null) throw new Refused("the face does not load: mend the errors in Diagnostics first");
        const [zip, version, stem] = [toZip(doc.bundle()), doc.version, slug(doc.name)];
        return async () => json(await this.host.build(zip, target, version, stem));
      }
      case "undo":
        doc.undo(int(args, "version"));
        return this.changed(doc, tab);
      case "redo":
        doc.redo(int(args, "version"));
        return this.changed(doc, tab);
      case "history": return json(doc.history(null));
      case "snapshot": {
        const snap = doc.snapshot("manual");
        this.emit("snapshot", { id, name: snap.name, version: doc.version });
        return json(doc.history());
      }
      case "download": {
        let form = text(args, "form") || "auto";
        const b = doc.bundle();
        // Every download is a point in time worth going back to, unless that version has a snapshot.
        if (doc.lastSnapshot[1] !== doc.version) {
          const snap = doc.snapshot("download");
          this.emit("snapshot", { id, name: snap.name, version: doc.version });
        }
        if (form === "auto") form = b.files.size > 0 ? "zip" : "yaml";
        const stem = slug(b.name);
        if (form === "yaml") return { status: 200, body: new TextEncoder().encode(b.text), type: "application/yaml", filename: `${stem}.yaml` };
        if (form === "zip") return { status: 200, body: toZip(b), type: "application/zip", filename: `${stem}.zip` };
        throw new Refused(`form ${quoted(form)} is neither zip nor yaml`);
      }
      case "restore":
        doc.restore(text(args, "snapshot"), int(args, "version"));
        return this.changed(doc, tab);
      case "copy":
        return await this.created(studio.fork(id, text(args, "snapshot")));
      case "ui_state": {
        const action = text(args, "action");
        if (action === "set") studio.store.setUiState(id, object(args, "state") as FaceUiState);
        else if (action !== "get") throw new Refused(`ui_state action ${quoted(action)} is neither get nor set`);
        return json<UiState>({ state: studio.store.uiState(id) as FaceUiState });
      }
    }
    throw new Refused(`no such request: ${quoted(op)}`);
  }

  /** A face just made: announced, its devices loaded, its summary. */
  private async created(doc: Document): Promise<Response> {
    this.emit("created", { id: doc.id });
    await this.open(doc.id);
    return json(doc.summary());
  }

  private async drag(doc: Document, args: Json, tab: string | null): Promise<Response> {
    const device = text(args, "device");
    if (device) await this.host.prepare([device], needs(doc.text)[1]);
    const gesture = object(args, "gesture");
    const elements = args["elements"];
    if (elements !== undefined && elements !== null
      && (!Array.isArray(elements) || gesture["kind"] !== "move" || (gesture["part"] ?? "both") !== "both")) {
      throw new Refused("several elements can only be moved together");
    }
    let change, landed: boolean;
    const scope = text(args, "scope") || "auto";
    if (Array.isArray(elements)) {
      const dx = Number(gesture["dx"]), dy = Number(gesture["dy"]);
      if (!Number.isFinite(dx) || !Number.isFinite(dy)) throw new Refused("a move needs its dx and dy");
      [change, landed] = doc.moveAll(elements.map(String), Math.trunc(dx), Math.trunc(dy), device, scope, int(args, "version"));
    } else {
      [change, landed] = doc.drag(text(args, "element"), gesture, device, scope, int(args, "version"));
    }
    this.emit("changed", { id: doc.id, version: doc.version, tab });
    return json({ ...doc.summary(), landed, what: change.label });
  }
}
