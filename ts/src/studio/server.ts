// `wfb studio`: the editor's server. Node only.
//
// The editor runs in the browser: the compiler, previews, the history
// (IndexedDB) and bundles in and out are all in its worker. The server
// sends what only this computer has, and builds:
//
// - the app (`ts/app/`), and the worker and the canvas's rasteriser
//   (`src/raster/canvas.ts`), bundled at start;
// - `GET /api/devices`: every installed device's `compiler.json`,
//   `simulator.json` and a digest of its `api.debug.xml` (the symbol tags
//   the compiler reads, a few percent of the file), and the SDK device
//   reference;
// - `GET /api/devices/<id>/extras`: the device's simulator skin and every
//   font file its metrics read, recorded as the compiler looks them up, so
//   the browser answers the same lookups the same way;
// - `GET /api/schema`, `GET /api/icon-font`;
// - `GET /help/<path>`: the README, `LICENSE`, `docs/` and `examples/`,
//   read-only, for the Help popup;
// - `POST /api/build?device=&stem=`: a face's bundle in, built with
//   `monkeyc`, its log and memory out; `GET /api/builds/<id>` its `.prg`,
//   for the newest builds.
//
// Every request must name an IP address, `localhost` or the listening host
// in `Host`, and a build must come from the server's own page (`allowed`).
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { isIP } from "node:net";
import { tmpdir } from "node:os";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { gzipSync } from "node:zlib";
import { unzipSync } from "fflate";
import { DeviceDatabase } from "../devices/device.ts";
import { REPO_ROOT } from "../devices/node.ts";
import { Bag } from "../diagnostics.ts";
import { type FontFile, type FontFiles, locate } from "../fonts/files.ts";
import { NodeFontFiles } from "../fonts/node.ts";
import { ICON_FONT, SCHEMA } from "../node.ts";
import { build as runBuild, Toolchain } from "../node_build.ts";
import { formatFixed } from "../py.ts";
import { MAX_UPLOAD_BYTES } from "./bundle.ts";
import { devices as listDevices } from "./inspect.ts";

const APP = join(REPO_ROOT, "ts", "app");
const SRC = join(REPO_ROOT, "ts", "src");

/** A browser module, bundled at start from the sources, so a checkout serves its own. */
async function bundle(entry: string): Promise<Uint8Array> {
  const esbuild = await import("esbuild");
  const built = await esbuild.build({
    entryPoints: [join(SRC, entry)], bundle: true, format: "esm", platform: "browser", target: "es2023", write: false, logLevel: "silent",
  });
  return built.outputFiles[0]!.contents;
}
const LOOPBACK = ["127.0.0.1", "localhost", "::1"];
/** The builds kept for download; an older one's files are removed. */
const KEPT_BUILDS = 20;

/** `Host`'s name, brackets off an IPv6 address; null when it is missing or unreadable. */
function hostName(header: string | undefined): string | null {
  if (!header) return null;
  try {
    return new URL(`http://${header}`).hostname.replace(/^\[(.*)\]$/, "$1");
  } catch {
    return null;
  }
}

/**
 * Whether a request may be answered: addressed to an IP address,
 * `localhost` or the host the server was told to listen on (a name only a
 * DNS answer could point here is how a web page elsewhere reaches a
 * loopback server: DNS rebinding), and, for a build, sent by this server's
 * own page (a browser names the page's origin on a cross-site POST).
 */
export function allowed(request: IncomingMessage, listenHost: string): boolean {
  const name = hostName(request.headers.host);
  if (name === null || !(isIP(name) !== 0 || name === "localhost" || name === listenHost)) return false;
  const origin = request.headers.origin;
  if (request.method !== "GET" && request.method !== "HEAD" && origin !== undefined) {
    try {
      return new URL(origin).host === request.headers.host;
    } catch {
      return false;
    }
  }
  return true;
}
const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json", ".map": "application/json", ".ttf": "font/ttf", ".png": "image/png", ".svg": "image/svg+xml",
  ".md": "text/markdown; charset=utf-8", ".yaml": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".jpg": "image/jpeg", ".gif": "image/gif", "": "text/plain; charset=utf-8",
};
/** What `/help/` serves: the files a doc links to, never the compiler or the user's licensed `vendor/`. */
const HELP = /^(README\.md|LICENSE|docs\/.+|examples\/.+)$/;
/** The `api.debug.xml` tags `Device` reads: a function, a scope, a module, and a field (a symbol-table entry). */
const DIGEST_TAG = /<(functionEntry|apiScopeEntry|dataEntry)\b[^>]*>|<entry\b[^>]*\bfield="true"[^>]*>/g;
const ENTRY_SYMBOL = /\bsymbol="([^"]*)"/;

const base64 = (bytes: Uint8Array): string => Buffer.from(bytes).toString("base64");

/** A digest tag as `Device` needs it: a field entry cut to its symbol, every other tag whole. */
function digestTag(tag: string): string {
  if (!tag.startsWith("<entry")) return tag;
  const symbol = ENTRY_SYMBOL.exec(tag);
  return symbol === null ? "" : `<entry field="true" symbol="${symbol[1]}"/>`;
}

/** Every installed device's files (or the `only` named) and the reference, as the browser's `MemoryDeviceFiles` takes them. */
export function digest(db: DeviceDatabase, only?: readonly string[]): {
  devices: Record<string, Record<string, string>>; references: Record<string, unknown>; listing: ReturnType<typeof listDevices>;
} {
  const devices: Record<string, Record<string, string>> = {};
  for (const id of only ?? db.ids()) {
    const files: Record<string, string> = {};
    for (const name of ["compiler.json", "simulator.json"]) {
      const bytes = db.files.file(id, name);
      if (bytes !== undefined) files[name] = new TextDecoder().decode(bytes);
    }
    const xml = db.files.file(id, `${id}.api.debug.xml`);
    if (xml !== undefined) files[`${id}.api.debug.xml`] = [...new TextDecoder().decode(xml).matchAll(DIGEST_TAG)].map((m) => digestTag(m[0])).filter(Boolean).join("\n");
    devices[id] = files;
  }
  const references: Record<string, unknown> = {};
  for (const id of db.files.referenceIds()) references[id] = db.files.reference(id);
  // Listed here, where every skin and font file is at hand: the browser loads those per device, when needed.
  return { devices, references, listing: listDevices(db) };
}

/** `files` with every lookup recorded: `[kind, argument, path or null]`, and the bytes once per path. */
class Recording implements FontFiles {
  readonly calls: [string, string, string | null][] = [];
  readonly bytes = new Map<string, Uint8Array>();
  private readonly files: FontFiles;

  constructor(files: FontFiles) {
    this.files = files;
  }

  private readonly seen = new Set<string>();

  private note(kind: string, argument: string, file: FontFile | undefined): FontFile | undefined {
    if (!this.seen.has(`${kind}\0${argument}`)) this.calls.push([kind, argument, file?.path ?? null]);
    this.seen.add(`${kind}\0${argument}`);
    if (file !== undefined) this.bytes.set(file.path, file.bytes);
    return file;
  }

  garmin(name: string, suffixes: readonly string[]): FontFile | undefined {
    return this.note("garmin", `${name}\0${suffixes.join(",")}`, this.files.garmin(name, suffixes));
  }

  registry(key: string): FontFile | undefined {
    return this.note("registry", key, this.files.registry(key));
  }
}

/**
 * One device's skin and the font files the compiler looks up for it: its
 * system fonts, measured through a database whose font files record every
 * lookup, and the vector faces `faces` names.
 */
function extras(db: DeviceDatabase, id: string, fonts: FontFiles, faces: readonly string[]): unknown {
  const recording = new Recording(fonts);
  const recorded = new DeviceDatabase(db.files, recording);
  const device = recorded.get(id);
  for (const metric of device.systemFonts.values()) recorded.measure.systemFace(metric);
  for (const face of faces) {
    if (device.scalableFaces.includes(face)) locate(recording, device.scalableFaceFiles.get(face) ?? face, face);
  }
  const files: Record<string, string> = {};
  for (const [path, bytes] of recording.bytes) files[path] = base64(bytes);
  const skin = device.skinName;
  const skinBytes = skin !== null ? db.files.file(id, skin) : undefined;
  return { calls: recording.calls, files, skin: skin !== null && skinBytes !== undefined ? { name: skin, data: base64(skinBytes) } : null };
}

interface Built {
  prg: string;
  name: string;
  work: string;
}

function readBody(request: IncomingMessage): Promise<Uint8Array> {
  return new Promise((done, fail) => {
    const chunks: Buffer[] = [];
    let size = 0;
    request.on("data", (chunk: Buffer) => {
      size += chunk.length;
      if (size > MAX_UPLOAD_BYTES) {
        fail(new Error("too large"));
        request.destroy();
      } else chunks.push(chunk);
    });
    request.on("end", () => done(new Uint8Array(Buffer.concat(chunks))));
    request.on("error", fail);
  });
}

interface Options {
  host: string;
  port: number;
  db: DeviceDatabase;
  fontsDir: string | null;
}

/** Run the server until Ctrl-C. */
export async function serve(options: Options): Promise<void> {
  const { host, port } = options;
  const running = await start(options);
  const shown = host === "0.0.0.0" || host === "::" ? "127.0.0.1" : host.includes(":") ? `[${host}]` : host;
  console.log(`wfb studio on http://${shown}:${running.port}/  (faces are kept in the browser)`);
  if (!LOOPBACK.includes(host)) {
    if (process.env["WFB_CONTAINER"] === "1") {
      console.log(`in a container: publish the port to the host's loopback only, -p 127.0.0.1:${port}:${port}, and open the address above there`);
    } else {
      console.error(`warning: listening on ${host}, not loopback: anyone who can reach this port can run builds on this computer`);
    }
  }
  await new Promise<void>((done) => process.once("SIGINT", () => done()));
  await running.close();
}

/** The server listening (`port` 0: any free port); `close` stops it and removes its builds. */
export async function start({ host, port, db, fontsDir }: Options): Promise<{ port: number; close: () => Promise<void> }> {
  const fonts = new NodeFontFiles(fontsDir);
  let digested: Buffer | null = null;
  const extrasCache = new Map<string, Buffer>();
  const builds = new Map<string, Built>();
  let building = false;
  const scratch = mkdtempSync(join(tmpdir(), "wfb-studio-builds-"));
  const worker = await bundle("studio/worker.ts");
  const raster = await bundle("raster/canvas.ts");

  const send = (response: ServerResponse, status: number, body: string | Uint8Array, type: string, headers: Record<string, string> = {}): void => {
    response.writeHead(status, { "Content-Type": type, "Cache-Control": "no-store", ...headers });
    response.end(body);
  };
  const sendJson = (response: ServerResponse, status: number, value: unknown): void => send(response, status, JSON.stringify(value), "application/json");
  const sendFile = (response: ServerResponse, root: string, relative: string): void => {
    const path = normalize(join(root, relative));
    if (!path.startsWith(root + "/") || !existsSync(path) || !statSync(path).isFile()) {
      sendJson(response, 404, { error: "not found" });
      return;
    }
    send(response, 200, readFileSync(path), TYPES[extname(path)] ?? "application/octet-stream");
  };

  const build = async (zip: Uint8Array, device: string, stem: string): Promise<unknown> => {
    const id = crypto.randomUUID().replace(/-/g, "");
    const work = join(scratch, id);
    const files = unzipSync(zip);
    for (const [path, bytes] of Object.entries(files)) {
      const target = resolve(work, "face", path);
      if (!target.startsWith(join(work, "face") + "/")) throw new Error(`${path} points outside the bundle`);
      mkdirSync(dirname(target), { recursive: true });
      writeFileSync(target, bytes);
    }
    const started = performance.now();
    const bag = new Bag();
    const cwd = process.cwd();
    let result;
    try {
      // Paths in the log read as the face's own, relative to its folder.
      process.chdir(join(work, "face"));
      result = await runBuild("face.yaml", { output: join(work, "out"), bag, devicesOnly: [device], db, toolchain: Toolchain.discover() });
    } finally {
      process.chdir(cwd);
    }
    const prg = result?.products.get(device) ?? null;
    const stats = result?.memory.get(device);
    const ok = result !== null && bag.ok() && prg !== null;
    const log = bag.render({ verbose: true }) + (result !== null && result.products.size === 0 && bag.ok() ? "\n\nthe build left no .prg" : "");
    if (ok) {
      builds.set(id, { prg: prg!, name: `${stem}-${device}.prg`, work });
      // a Map keeps insertion order: the first is the oldest
      for (const [old, kept] of [...builds].slice(0, Math.max(0, builds.size - KEPT_BUILDS))) {
        rmSync(kept.work, { recursive: true, force: true });
        builds.delete(old);
      }
    } else rmSync(work, { recursive: true, force: true });
    return {
      ok, device, log: log.trim(), seconds: Number(formatFixed((performance.now() - started) / 1000, 1)),
      memory: stats ? `${stats.total.toLocaleString("en-US")} B / ${stats.limit.toLocaleString("en-US")} B (${formatFixed(100 * stats.total / stats.limit, 1)}%)` : null,
      download: ok ? `/api/builds/${id}` : null,
    };
  };

  const server = createServer(async (request, response) => {
    try {
      if (!allowed(request, host)) return sendJson(response, 403, { error: "this server answers only its own page, at an IP address or localhost" });
      const url = new URL(request.url ?? "/", "http://wfb");
      const path = url.pathname;
      if (path === "/" || path === "/index.html") return sendFile(response, APP, "index.html");
      if (path.startsWith("/static/")) return sendFile(response, APP, path.slice("/static/".length));
      if (path === "/dist/worker.js") return send(response, 200, worker, "text/javascript; charset=utf-8");
      if (path === "/dist/raster.js") return send(response, 200, raster, "text/javascript; charset=utf-8");
      if (path.startsWith("/help/")) {
        const relative = normalize(decodeURIComponent(path.slice("/help/".length)));
        return HELP.test(relative) ? sendFile(response, REPO_ROOT, relative) : sendJson(response, 404, { error: "not found" });
      }
      if (path === "/api/schema") return send(response, 200, readFileSync(SCHEMA), "application/schema+json");
      if (path === "/api/icon-font") {
        if (!existsSync(ICON_FONT)) return sendJson(response, 404, { error: "the icon font is not installed: run ./tools/setup-env.sh" });
        return send(response, 200, readFileSync(ICON_FONT), "font/ttf", { "Cache-Control": "private, max-age=86400" });
      }
      if (path === "/api/devices") {
        digested ??= Buffer.from(JSON.stringify(digest(db)));
        const gzip = /\bgzip\b/.test(String(request.headers["accept-encoding"] ?? ""));
        return send(response, 200, gzip ? gzipSync(digested) : digested, "application/json", {
          ...(gzip ? { "Content-Encoding": "gzip" } : {}), "Cache-Control": "private, max-age=3600",
        });
      }
      const extra = /^\/api\/devices\/([^/]+)\/extras$/.exec(path);
      if (extra) {
        const id = decodeURIComponent(extra[1]!);
        const faces = (url.searchParams.get("faces") ?? "").split(",").filter(Boolean).sort();
        const cacheKey = `${id}\0${faces.join(",")}`;
        if (!extrasCache.has(cacheKey)) extrasCache.set(cacheKey, gzipSync(JSON.stringify(extras(db, id, fonts, faces))));
        return send(response, 200, extrasCache.get(cacheKey)!, "application/json", { "Content-Encoding": "gzip", "Cache-Control": "private, max-age=3600" });
      }
      if (path === "/api/build" && request.method === "POST") {
        if (building) return sendJson(response, 409, { error: "a build is already running; wait for it to finish" });
        building = true;
        try {
          const body = await readBody(request);
          return sendJson(response, 200, await build(body, url.searchParams.get("device") ?? "", url.searchParams.get("stem") || "face"));
        } finally {
          building = false;
        }
      }
      const download = /^\/api\/builds\/([0-9a-f]+)$/.exec(path);
      if (download) {
        const done = builds.get(download[1]!);
        if (done === undefined || !existsSync(done.prg)) return sendJson(response, 404, { error: `there is no such build; the newest ${KEPT_BUILDS} builds last until the editor stops` });
        return send(response, 200, readFileSync(done.prg), "application/octet-stream", { "Content-Disposition": `attachment; filename="${done.name}"` });
      }
      sendJson(response, 404, { error: "not found" });
    } catch (error) {
      sendJson(response, 400, { error: (error as Error).message });
    }
  });

  await new Promise<void>((done) => server.listen(port, host, done));
  return {
    port: (server.address() as { port: number }).port,
    close: () => new Promise<void>((done) => server.close(() => {
      rmSync(scratch, { recursive: true, force: true });
      done();
    })),
  };
}

