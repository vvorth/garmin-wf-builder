// The editor's requests, answered in the browser: an operation and its
// arguments (`{op: "edit", args: {id, version, op}}`), as the page's
// `api.js` sends them, mapped to the studio. The worker (`./worker.ts`)
// runs it on every message; the tests run it directly. The arguments come
// as the page wrote them, structured-cloned, so each is checked for its
// type here.
//
// An answer is `{status, json}`, or `{status, body, type, filename}` for a
// file; a refusal's status says why: 400 refused, 404 no such face or
// snapshot, 409 the face moved on (stale), 507 the store failed.
//
// Requests are answered one at a time (`exclusive`), so no two interleave
// over one face; a build waits its turn only to check and pack the face, and
// the server's compile runs outside it, so editing goes on meanwhile.
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
import { StoreError, UnknownDocument, UnknownSnapshot } from "./store.ts";

type Json = Record<string, unknown>;

export interface Request {
  op: string;
  args?: Json;
  /** A file's bytes: an upload or an asset. */
  body?: Uint8Array | null;
  /** The tab asking, which `changed` names so it can skip its own change. */
  tab?: string | null;
}

export interface Response {
  status: number;
  /** A JSON answer, or bytes with their type. */
  json?: unknown;
  body?: Uint8Array;
  type?: string;
  /** A download's file name. */
  filename?: string;
}

export interface Host {
  /** Load whatever the named devices need before the compiler reads them (fonts, skins, the vector `faces` named); nothing in Node. */
  prepare(deviceIds: readonly string[], faces?: readonly string[]): Promise<void>;
  /** Build a face's bundle for one watch on the server. */
  build(zip: Uint8Array, device: string, version: number, stem: string): Promise<Json>;
  emit(event: string, data: Json): void;
  /** The installed devices as the vocabulary lists them, when the host has them listed already (`inspect.devices`). */
  devices?(): ReturnType<typeof devices>;
}

const json = (value: unknown, status = 200): Response => ({ status, json: plain(value) });
const error = (status: number, message: string): Response => ({ status, json: { error: message } });

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

export class Router {
  readonly studio: Studio;
  readonly host: Host;

  constructor(studio: Studio, host: Host) {
    this.studio = studio;
    this.host = host;
  }

  /** What this request did, announced once its writes are on disk: another tab's worker reads them then. */
  private announced: [string, Json][] = [];

  private emit(event: string, data: Json): void {
    this.announced.push([event, data]);
  }

  // ponytail: one request at a time across every face; render is synchronous, so only a worker per face would let a slow frame not hold up another face.
  private queue: Promise<unknown> = Promise.resolve();

  /** Run `work` after everything queued before it: the worker's timed snapshots and other tabs' reloads take their turn here too. */
  exclusive<T>(work: () => Promise<T>): Promise<T> {
    const run = this.queue.then(work);
    this.queue = run.catch(() => {});
    return run;
  }

  /** Answer one request, in turn; every refusal is JSON with its status, never a stack trace. */
  async handle(request: Request): Promise<Response> {
    const answer = await this.exclusive(() => this.answer(request));
    return typeof answer === "function" ? await answer() : answer;
  }

  /** The answer, or the work left to do once the queue is free again (a build). */
  private async answer(request: Request): Promise<Response | (() => Promise<Response>)> {
    this.announced = [];
    try {
      const answer = await this.route(request);
      await this.studio.store.flush();
      for (const [event, data] of this.announced) this.host.emit(event, data);
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

  private async route({ op, args = {}, body = null, tab = null }: Request): Promise<Response | (() => Promise<Response>)> {
    const studio = this.studio;
    switch (op) {
      case "home":
        return json({
          templates: starters.names().map((n) => ({ name: n, blurb: starters.blurb(n) })),
          documents: studio.store.documents(), store: "this browser", shared: true,
        });
      case "vocabulary": {
        const [installed, unreadable] = this.host.devices?.() ?? devices(studio.db);
        return json({ ...vocabulary(), devices: installed, unreadable_devices: unreadable });
      }
      case "skin": {
        const device = text(args, "device");
        await this.host.prepare([device]);
        const scale = Math.min(4, Math.max(1, args["scale"] === undefined ? 2 : int(args, "scale")));
        const found = skinFor(studio.db.get(device), scale);
        if (found === null) return error(404, `${device}'s files have no skin`);
        const [image, [x, y]] = found;
        const png = encodePng(image.width, image.height, new Uint8Array(image.data.buffer, image.data.byteOffset, image.data.byteLength), 4);
        return json({ device, scale, image: "data:image/png;base64," + base64(png), width: image.width, height: image.height, x, y });
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
