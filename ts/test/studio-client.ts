// The editor's worker, run in Node for the studio tests: a studio over an
// in-memory store and the installed devices, and a client sending it the
// requests the page sends.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { DeviceDatabase } from "../src/devices/device.ts";
import { NodeDeviceFiles, REPO_ROOT } from "../src/devices/node.ts";
import { indexFor } from "../src/edit/spans.ts";
import { setValue } from "../src/edit/patch.ts";
import { ICON_FONT } from "../src/emit/resources.ts";
import { NodeFontFiles } from "../src/fonts/node.ts";
import { installAssets, readFontFile } from "../src/node.ts";
import * as starters from "../src/starters.ts";
import { type Document, Studio } from "../src/studio/document.ts";
import { type Response, Router } from "../src/studio/router.ts";
import { type Backend, MemoryBackend, Store } from "../src/studio/store.ts";

installAssets();
export const db = new DeviceDatabase(NodeDeviceFiles.discover(), new NodeFontFiles());
export const ROOT = REPO_ROOT;
export const read = (path: string): Uint8Array => new Uint8Array(readFileSync(join(ROOT, path)));
export const readText = (path: string): string => readFileSync(join(ROOT, path), "utf8");

export const SHOWCASE = "examples/showcase/face.yaml";
export const PROFILE = "examples/features/profile/face.yaml";
export const STYLES = "examples/features/styles/face.yaml";
export const ALIGN = "examples/features/align/face.yaml";
export const CHIVO = "examples/showcase/assets/ChivoMono-Bold.ttf";
export const DYNALIGHT = "examples/showcase/assets/Dynalight-Regular.ttf";

export const minimalText = (name = "T"): string => starters.instantiate("minimal", name);

export async function newStudio(backend: Backend = new MemoryBackend(), options: { snapshotMinutes?: number; keepChanges?: number } = {}): Promise<Studio> {
  return new Studio(await Store.open(backend), db, () => readFontFile(ICON_FONT), options);
}

/** A reply, its JSON typed loosely, as a test reads it. */
export type Reply = Response & { json: any };

export class Client {
  readonly studio: Studio;
  readonly router: Router;
  readonly events: [string, Record<string, unknown>][] = [];
  tab: string | null = null;

  constructor(studio: Studio) {
    this.studio = studio;
    this.router = new Router(studio, {
      prepare: async () => {},
      build: async () => ({ ok: false, log: "no builds in tests" }),
      emit: (event, data) => this.events.push([event, data]),
    });
  }

  static async open(backend?: Backend): Promise<Client> {
    return new Client(await newStudio(backend));
  }

  async send(method: string, url: string, body: unknown = null): Promise<Reply> {
    const bytes = body === null ? null : body instanceof Uint8Array ? body
      : new TextEncoder().encode(typeof body === "string" ? body : JSON.stringify(body));
    return await this.router.handle({ method, url, body: bytes, tab: this.tab }) as Reply;
  }

  get(url: string): Promise<Reply> {
    return this.send("GET", url);
  }

  post(url: string, body: unknown = null): Promise<Reply> {
    return this.send("POST", url, body);
  }

  delete(url: string): Promise<Reply> {
    return this.send("DELETE", url);
  }

  /** A face from a template, as its summary; throws unless it was made. */
  async create(template = "minimal", name = "D"): Promise<any> {
    const r = await this.post(`/api/documents/new?template=${template}&name=${encodeURIComponent(name)}`);
    if (r.status !== 200) throw new Error(JSON.stringify(r.json));
    return r.json;
  }

  async upload(filename: string, data: Uint8Array | string): Promise<any> {
    const r = await this.post(`/api/documents/upload?filename=${encodeURIComponent(filename)}`, data);
    if (r.status !== 200) throw new Error(JSON.stringify(r.json));
    return r.json;
  }
}

/** The document's text with `face.version` set to `1.0.<n>`: one line changed. */
export function bumped(doc: Document, n: number): string {
  return setValue(indexFor(doc.text), ["face", "version"], `1.0.${n}`).text;
}

export function versionOf(doc: Document): string {
  return ((indexFor(doc.text).data as Map<string, any>).get("face") as Map<string, any>).get("version");
}

export const noAssets = new Map<string, string>();

/**
 * A design on disk and the files it references, as an upload of its folder
 * would bring them: a file inside the design's folder keeps its path, one
 * outside is gathered under `assets/` and its reference patched.
 */
export function openExample(studio: import("../src/studio/document.ts").Studio, path: string): Document {
  const { bundle, references } = bundleModule;
  const text = readText(path);
  const folder = path.slice(0, path.lastIndexOf("/") + 1);
  const files = new Map<string, Uint8Array>();
  const moved = new Map<string, string>();
  for (const ref of references(text)) {
    const bytes = read(normalize(folder + ref.value));
    const at = ref.inside ?? `assets/${ref.value.slice(ref.value.lastIndexOf("/") + 1)}`;
    if (ref.inside === null) moved.set(ref.value, at);
    files.set(at, bytes);
  }
  return studio.create(bundle("T", text, files), "open", moved);
}

import * as bundleModule from "../src/studio/bundle.ts";
import { normalize } from "node:path";
import { plain } from "../src/studio/json.ts";

/** The document's text as plain data. */
export const dataOf = (doc: Document): any => plain(indexFor(doc.text).data);
