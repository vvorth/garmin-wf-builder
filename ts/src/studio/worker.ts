// The editor's worker: the compiler and the history store, answering the
// page's requests (`../../app/api.js`) through `Router`. Bundled by
// `npm run bundle` into `dist/worker.js`.
//
// It loads the schema, the icon font and every installed device's digest
// from the server once, and a device's skin and font files the first time
// a face needs that device (`prepare`). What the studio does goes to this
// tab's page and, on the `wfb-studio` channel, to every other tab's worker,
// which reads that face again from IndexedDB before telling its own page:
// each worker holds the store in memory, and one that wrote over another
// tab's change would lose it.
import opentype from "opentype.js";
import { DeviceDatabase } from "../devices/device.ts";
import { MemoryDeviceFiles } from "../devices/files.ts";
import { ICON_FONT } from "../emit/resources.ts";
import type { FontFile, FontFiles } from "../fonts/files.ts";
import { setIconFontGlyphs } from "../icons.ts";
import { loadSchema } from "../validate.ts";
import { Studio } from "./document.ts";
import type { devices } from "./inspect.ts";
import { type Request, type Response, Router } from "./router.ts";
import { type Backend, MemoryBackend, Store } from "./store.ts";

/** The store's records in one IndexedDB object store. */
class IdbBackend implements Backend {
  private readonly db: Promise<IDBDatabase>;

  constructor(name: string) {
    this.db = new Promise((done, fail) => {
      const open = indexedDB.open(name, 1);
      open.onupgradeneeded = () => open.result.createObjectStore("records");
      open.onsuccess = () => done(open.result);
      open.onerror = () => fail(open.error);
    });
  }

  private async run(mode: IDBTransactionMode, work: (records: IDBObjectStore) => void): Promise<void> {
    const db = await this.db;
    return new Promise((done, fail) => {
      const tx = db.transaction("records", mode);
      work(tx.objectStore("records"));
      tx.oncomplete = () => done();
      tx.onerror = () => fail(tx.error);
      tx.onabort = () => fail(tx.error);
    });
  }

  async load(prefix = ""): Promise<Map<string, unknown>> {
    const out = new Map<string, unknown>();
    await this.run("readonly", (records) => {
      const cursor = records.openCursor(prefix ? IDBKeyRange.bound(prefix, prefix + "\uffff") : null);
      cursor.onsuccess = () => {
        const at = cursor.result;
        if (at === null) return;
        out.set(String(at.key), at.value);
        at.continue();
      };
    });
    return out;
  }

  put(key: string, value: unknown): Promise<void> {
    return this.run("readwrite", (records) => records.put(value, key));
  }

  delete(keys: readonly string[]): Promise<void> {
    return this.run("readwrite", (records) => {
      for (const key of keys) records.delete(key);
    });
  }
}

/** Font lookups answered as the server recorded them for each prepared device. */
class RecordedFonts implements FontFiles {
  readonly answers = new Map<string, FontFile | undefined>();

  garmin(name: string, suffixes: readonly string[]): FontFile | undefined {
    return this.answers.get(`garmin\0${name}\0${suffixes.join(",")}`);
  }

  registry(key: string): FontFile | undefined {
    return this.answers.get(`registry\0${key}`);
  }
}

const decode = (text: string): Uint8Array => Uint8Array.from(atob(text), (c) => c.charCodeAt(0));

async function fetchOk(url: string): Promise<globalThis.Response> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response;
}

const channel = new BroadcastChannel("wfb-studio");

async function start(): Promise<Router> {
  loadSchema(await (await fetchOk("/api/schema")).json());
  let iconFont: FontFile | null = null;
  try {
    const bytes = new Uint8Array(await (await fetchOk("/api/icon-font")).arrayBuffer());
    const font = opentype.parse(bytes.buffer);
    const map = (font.tables["cmap"] as { glyphIndexMap: Record<string, number> }).glyphIndexMap;
    setIconFontGlyphs(new Set(Object.keys(map).map((cp) => String.fromCodePoint(Number(cp)))));
    iconFont = { path: ICON_FONT, bytes };
  } catch {
    setIconFontGlyphs("the icon font is not installed on the server: run ./tools/setup-env.sh there");
  }
  const digest = await (await fetchOk("/api/devices")).json() as {
    devices: Record<string, Record<string, string>>; references: Record<string, unknown>; listing: ReturnType<typeof devices>;
  };
  const files = new MemoryDeviceFiles();
  for (const [id, folder] of Object.entries(digest.devices)) for (const [name, text] of Object.entries(folder)) files.add(id, name, text);
  for (const [id, page] of Object.entries(digest.references)) files.addReference(id, page);
  const fonts = new RecordedFonts();
  const db = new DeviceDatabase(files, fonts);
  const prepared = new Map<string, Promise<void>>();
  // Once per device and set of vector faces: a face naming a new one loads its file then.
  const prepare = (id: string, faces: readonly string[]): Promise<void> => {
    const key = `${id}\0${[...new Set(faces)].sort().join(",")}`;
    if (!prepared.has(key)) {
      prepared.set(key, (async () => {
        if (!db.ids().includes(id)) return;
        const query = faces.length > 0 ? `?faces=${encodeURIComponent([...new Set(faces)].join(","))}` : "";
        const extras = await (await fetchOk(`/api/devices/${encodeURIComponent(id)}/extras${query}`)).json() as {
          calls: [string, string, string | null][]; files: Record<string, string>; skin: { name: string; data: string } | null;
        };
        const bytes = new Map(Object.entries(extras.files).map(([path, data]) => [path, decode(data)]));
        for (const [kind, argument, path] of extras.calls) {
          fonts.answers.set(`${kind}\0${argument}`, path === null ? undefined : { path, bytes: bytes.get(path)! });
        }
        if (extras.skin !== null) files.add(id, extras.skin.name, decode(extras.skin.data));
      })());
      // a failed load is tried again on the next request, not remembered
      prepared.get(key)!.catch(() => prepared.delete(key));
    }
    return prepared.get(key)!;
  };
  // Without IndexedDB (a private window in some browsers) the faces last as long as the tab.
  const store = await Store.open(typeof indexedDB === "undefined" ? new MemoryBackend() : new IdbBackend("wfb-studio"));
  const studio = new Studio(store, db, () => {
    if (iconFont === null) throw new Error("the icon font is not installed on the server");
    return iconFont;
  });
  const emit = (event: string, data: Record<string, unknown>): void => {
    channel.postMessage({ event, data });
    self.postMessage({ event, data });
  };
  // timed snapshots and compaction, in turn with the requests, announced once written
  const later: [string, Record<string, unknown>][] = [];
  studio.onEvent = (event, data) => later.push([event, data]);
  setInterval(() => {
    queue = queue.then(async () => {
      studio.tick();
      try {
        await store.flush();
      } catch (error) {
        later.push(["error", { message: (error as Error).message }]);
      }
      for (const [event, data] of later.splice(0)) emit(event, data);
    });
  }, Math.max(1, Math.min(30, studio.snapshotSeconds / 4)) * 1000);
  return new Router(studio, {
    prepare: async (ids, faces = []) => {
      await Promise.all(ids.map((id) => prepare(id, faces)));
    },
    build: async (zip, device, _version, stem) => {
      const response = await fetch(`/api/build?device=${encodeURIComponent(device)}&stem=${encodeURIComponent(stem)}`, { method: "POST", body: zip as Uint8Array<ArrayBuffer> });
      const body = await response.json() as Record<string, unknown>;
      if (!response.ok) throw Object.assign(new Error(String(body["error"])), { status: response.status });
      return body;
    },
    emit,
    devices: () => digest.listing,
  });
}

const ready = start();
// ponytail: one request at a time across every face; per-face queues if a slow frame holds up another face's edits.
let queue: Promise<unknown> = Promise.resolve();

self.onmessage = (message: MessageEvent<{ id: number; request: Request }>) => {
  const { id, request } = message.data;
  queue = queue.then(async () => {
    let response: Response;
    try {
      response = await (await ready).handle(request);
    } catch (error) {
      response = { status: 500, json: { error: (error as Error).message ?? String(error) } };
    }
    self.postMessage({ id, response });
  });
};

// Another tab's worker changed a face: read it again, in turn with this
// tab's requests, then tell the page.
channel.onmessage = (message: MessageEvent<{ event: string; data: Record<string, unknown> }>) => {
  const { event, data } = message.data;
  queue = queue.then(async () => {
    try {
      if (typeof data["id"] === "string") await (await ready).studio.reload(data["id"]);
    } catch {
      // the face is read again when next asked for, and that answer says what failed
    }
    self.postMessage({ event, data });
  });
};
