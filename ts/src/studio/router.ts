// The editor's requests, answered in the browser: the paths the front end
// asks for (`/api/documents/...`) mapped to the studio. The worker (`./worker.ts`) runs it on every
// message; the tests run it directly.
//
// Each answer waits for the store's writes, so an acknowledged change is
// kept. What the studio did is announced through `emit` ("changed",
// "deleted", "renamed", "snapshot"), which the worker broadcasts to the
// editor's other tabs.
import { slug } from "../build.ts";
import { DeviceError } from "../devices/device.ts";
import { indexFor, Refused } from "../edit/spans.ts";
import { encodePng } from "../png.ts";
import { skinFor } from "../preview.ts";
import { repr } from "../py.ts";
import * as starters from "../starters.ts";
import { BundleError, bundle, readUpload, toZip } from "./bundle.ts";
import { type Document, frameKey, type FrameKey, StaleVersion, type Studio } from "./document.ts";
import { devices, vocabulary } from "./inspect.ts";
import { plain } from "./json.ts";
import { StoreError, UnknownDocument, UnknownSnapshot } from "./store.ts";

type Json = Record<string, unknown>;

export interface Request {
  method: string;
  /** The path and query, as `fetch` was given it. */
  url: string;
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

function int(query: URLSearchParams, name: string): number {
  const raw = query.get(name);
  if (raw === null || !/^-?\d+$/.test(raw)) throw new Refused(`${name} must be a whole number`);
  return Number(raw);
}

const flag = (query: URLSearchParams, name: string): boolean => ["1", "true", "yes"].includes(query.get(name) ?? "");

function time(raw: string | null): [number, number, number] | null {
  if (!raw) return null;
  const m = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(raw);
  if (m === null || Number(m[1]) > 23 || Number(m[2]) > 59 || Number(m[3] ?? 0) > 59) throw new Refused(`time ${repr(raw)} is not HH:MM or HH:MM:SS`);
  return [Number(m[1]), Number(m[2]), Number(m[3] ?? 0)];
}

function date(raw: string | null): [number, number, number] | null {
  if (!raw) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  const [y, mo, d] = m === null ? [0, 0, 0] : [Number(m[1]), Number(m[2]), Number(m[3])];
  const day = new Date(Date.UTC(y, mo - 1, d));
  if (m === null || day.getUTCFullYear() !== y || day.getUTCMonth() !== mo - 1 || day.getUTCDate() !== d) {
    throw new Refused(`date ${repr(raw)} is not a day, YYYY-MM-DD`);
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

function key(query: URLSearchParams, scale: number | null = null): FrameKey {
  return frameKey({
    device: query.get("device") ?? "", style: query.get("style") || null, time: time(query.get("time")), date: date(query.get("date")),
    asleep: flag(query, "asleep"), aod: flag(query, "aod"),
    scale: Math.min(4, Math.max(1, scale ?? (query.has("scale") ? int(query, "scale") : 2))), picks: picks(query.get("picks")),
  });
}

function parseJson(body: Uint8Array | null | undefined, what: string): unknown {
  try {
    return JSON.parse(new TextDecoder().decode(body ?? new Uint8Array()) || "{}");
  } catch {
    throw new Refused(`${what} is not JSON`);
  }
}

function base64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
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

  /** Answer one request; every refusal is JSON with its status, never a stack trace. */
  async handle(request: Request): Promise<Response> {
    try {
      const answer = await this.route(request);
      await this.studio.store.flush();
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

  private changed(doc: Document, tab: string | null): void {
    this.host.emit("changed", { id: doc.id, version: doc.version, tab });
  }

  private async route({ method, url, body = null, tab = null }: Request): Promise<Response> {
    const parsed = new URL(url, "http://wfb");
    const q = parsed.searchParams;
    const parts = parsed.pathname.split("/").filter(Boolean).map(decodeURIComponent);
    const studio = this.studio;
    if (parts[0] !== "api") return error(404, "not found");
    const [, top, id, action, name, sub] = parts;

    if (top === "home" && method === "GET") {
      return json({
        templates: starters.names().map((n) => ({ name: n, blurb: starters.blurb(n) })),
        documents: studio.store.documents(), store: "this browser", shared: true,
      });
    }
    if (top === "vocabulary") {
      const [installed, unreadable] = this.host.devices?.() ?? devices(studio.db);
      return json({ ...vocabulary(), devices: installed, unreadable_devices: unreadable });
    }
    if (top === "skin") {
      const device = q.get("device") ?? "";
      await this.host.prepare([device]);
      const scale = Math.min(4, Math.max(1, q.has("scale") ? int(q, "scale") : 2));
      const found = skinFor(studio.db.get(device), scale);
      if (found === null) return error(404, `${device}'s files have no skin`);
      const [image, [x, y]] = found;
      const png = encodePng(image.width, image.height, new Uint8Array(image.data.buffer, image.data.byteOffset, image.data.byteLength), 4);
      return json({ device, scale, image: "data:image/png;base64," + base64(png), width: image.width, height: image.height, x, y });
    }
    if (top !== "documents" || id === undefined) return error(404, "not found");

    if (id === "new" && method === "POST") {
      const template = q.get("template") ?? "minimal";
      const faceName = (q.get("name") ?? "").trim() || "My Face";
      const created = studio.create(bundle(faceName, starters.instantiate(template, faceName)), `new from the ${template} template`);
      await this.open(created.id);
      return json(created.summary());
    }
    if (id === "upload" && method === "POST") {
      const filename = q.get("filename") ?? "";
      const created = studio.create(readUpload(filename, body ?? new Uint8Array()), `open ${filename}`);
      await this.open(created.id);
      return json(created.summary());
    }

    const device = q.get("device");
    const doc = await this.open(id, action === "drag" ? null : device);
    switch (`${method} ${action ?? ""}`) {
      case "GET ": return json(doc.summary());
      case "DELETE ":
        studio.delete(id);
        this.host.emit("deleted", { id });
        return json({ deleted: id });
      case "POST rename":
        doc.rename(q.get("name") ?? "");
        this.host.emit("renamed", { id, name: doc.name });
        return json({ id, name: doc.name });
      case "GET cover": {
        const png = doc.cover();
        return png === null ? error(404, "the face does not load, so it has no picture") : { status: 200, body: png, type: "image/png" };
      }
      case "POST goto":
        doc.goto(int(q, "seq"), int(q, "version"));
        this.changed(doc, tab);
        return json(doc.summary());
      case "GET frame": return json(doc.frame(key(q)));
      case "GET thumbnail": return { status: 200, body: doc.thumbnail(key(q, 1)), type: "image/png" };
      case "GET handset":
        return { status: 200, body: doc.handSetImage(q.get("name") ?? "", device ?? "", q.has("scale") ? int(q, "scale") : 1), type: "image/png" };
      case "POST drag": return await this.drag(doc, q, body, tab);
      case "POST assets": {
        const font = q.get("font") || null;
        doc.addAsset(q.get("filename") ?? "", body ?? new Uint8Array(), q.get("reference") || null, int(q, "version"),
          font ? [font, q.get("size") || "10%r"] : null);
        this.changed(doc, tab);
        return json(doc.summary());
      }
      case "POST edit": {
        const op = parseJson(body, "the edit");
        if (op === null || typeof op !== "object" || Array.isArray(op)) throw new Refused("the edit is a JSON object");
        doc.edit(op as Json, int(q, "version"));
        this.changed(doc, tab);
        return json(doc.summary());
      }
      case "POST structure": {
        const op = parseJson(body, "the edit");
        if (op === null || typeof op !== "object" || Array.isArray(op)) throw new Refused("the edit is a JSON object");
        const [, select] = doc.structure(op as Json, int(q, "version"));
        this.changed(doc, tab);
        return json({ ...doc.summary(), select });
      }
      case "POST text": {
        let text: string;
        try {
          text = new TextDecoder("utf-8", { fatal: true }).decode(body ?? new Uint8Array());
        } catch {
          throw new Refused("the text is not UTF-8");
        }
        doc.replaceText(text, int(q, "version"));
        this.changed(doc, tab);
        return json(doc.summary());
      }
      case "GET inspect": {
        let element: unknown;
        try {
          element = JSON.parse(q.get("element") ?? "null");
        } catch {
          throw new Refused("element is a JSON list");
        }
        return json(doc.inspect(element, device || null));
      }
      case "POST build": {
        const target = device ?? "";
        doc.check(int(q, "version"));
        const watch = studio.db.get(target);
        if (!watch.supportsWatchface) throw new Refused(`${target} cannot run a watch face`);
        if (doc.analysis().face === null) throw new Refused("the face does not load: mend the errors in Diagnostics first");
        return json(await this.host.build(toZip(doc.bundle()), target, doc.version, slug(doc.name)));
      }
      case "POST undo":
        doc.undo(int(q, "version"));
        this.changed(doc, tab);
        return json(doc.summary());
      case "POST redo":
        doc.redo(int(q, "version"));
        this.changed(doc, tab);
        return json(doc.summary());
      case "GET history": return json(doc.history(null));
      case "POST snapshots": {
        if (name !== undefined) break;
        const snap = doc.snapshot("manual");
        this.host.emit("snapshot", { id, name: snap.name, version: doc.version });
        return json(doc.history());
      }
      case "GET download": {
        let form = q.get("form") ?? "auto";
        const b = doc.bundle();
        // Every download is a point in time worth going back to, unless that version has a snapshot.
        if (doc.lastSnapshot[1] !== doc.version) {
          const snap = doc.snapshot("download");
          this.host.emit("snapshot", { id, name: snap.name, version: doc.version });
        }
        if (form === "auto") form = b.files.size > 0 ? "zip" : "yaml";
        const stem = slug(b.name);
        if (form === "yaml") return { status: 200, body: new TextEncoder().encode(b.text), type: "application/yaml", filename: `${stem}.yaml` };
        if (form === "zip") return { status: 200, body: toZip(b), type: "application/zip", filename: `${stem}.zip` };
        throw new Refused(`form ${repr(form)} is neither zip nor yaml`);
      }
    }
    if (method === "POST" && action === "snapshots" && name !== undefined) {
      if (sub === "restore") {
        doc.restore(name, int(q, "version"));
        this.changed(doc, tab);
        return json(doc.summary());
      }
      if (sub === "copy") {
        const copy = studio.fork(id, name);
        await this.open(copy.id);
        return json(copy.summary());
      }
    }
    return error(404, "not found");
  }

  private async drag(doc: Document, q: URLSearchParams, raw: Uint8Array | null, tab: string | null): Promise<Response> {
    const body = parseJson(raw, "the gesture") as Json;
    if (body !== null && typeof body === "object" && body["device"]) await this.host.prepare([String(body["device"])], needs(doc.text)[1]);
    if (body === null || typeof body !== "object" || typeof body["gesture"] !== "object" || body["gesture"] === null) {
      throw new Refused("a drag is {element, gesture, device, scope}");
    }
    const elements = body["elements"];
    const gesture = body["gesture"] as Json;
    if (elements !== undefined && elements !== null
      && (!Array.isArray(elements) || gesture["kind"] !== "move" || (gesture["part"] ?? "both") !== "both")) {
      throw new Refused("several elements can only be moved together");
    }
    let change, landed: boolean;
    if (Array.isArray(elements)) {
      const dx = Number(gesture["dx"]), dy = Number(gesture["dy"]);
      if (!Number.isFinite(dx) || !Number.isFinite(dy)) throw new Refused("a move needs its dx and dy");
      [change, landed] = doc.moveAll(elements.map(String), Math.trunc(dx), Math.trunc(dy), String(body["device"] ?? ""),
        String(body["scope"] ?? "auto"), int(q, "version"));
    } else {
      [change, landed] = doc.drag(String(body["element"] ?? ""), gesture, String(body["device"] ?? ""), String(body["scope"] ?? "auto"), int(q, "version"));
    }
    this.changed(doc, tab);
    return json({ ...doc.summary(), landed, what: change.label });
  }
}

