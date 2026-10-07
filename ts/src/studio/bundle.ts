// A face as the editor moves it in and out: a design's text plus the files
// it references, opened by upload and saved by download.
//
// The format is a `.zip` with the face at its root (`face.yaml` by
// convention) and its files beneath it, `assets/` by convention, or a plain
// `.yaml` when the face references no file. The only file a design
// references is a baked font's `resources.fonts.<name>.source`, relative to
// the design.
//
// Every path in a bundle is checked before anything is unpacked: no
// absolute path, no `..`, no link, and the uncompressed sizes within limits.
import { strToU8, unzipSync, zipSync } from "fflate";
import { indexFor, type Path } from "../edit/spans.ts";
import { quoted } from "../py.ts";

/** The design's name inside a bundle. */
export const FACE = "face.yaml";
/** Where an asset added in the editor goes. */
export const ASSETS = "assets";

export const MAX_UPLOAD_BYTES = 32 * 1024 * 1024;
export const MAX_UNPACKED_BYTES = 64 * 1024 * 1024;
export const MAX_ENTRIES = 512;

/** Archive litter a desktop zip tool adds; skipped, never refused. */
const LITTER = /(^|\/)(__MACOSX\/|\.DS_Store$|Thumbs\.db$)/;

/** An upload that cannot be opened; the message says why, for the author. */
export class BundleError extends Error {}

/** A face's display name, its text and its files, by bundle-relative path. */
export interface Bundle {
  name: string;
  text: string;
  files: Map<string, Uint8Array>;
}

export function bundle(name: string, text: string, files: Map<string, Uint8Array> = new Map()): Bundle {
  return { name, text, files };
}

/** One file a design names: the font, the author path of its `source:`, and the value as written. */
export interface Reference {
  font: string;
  path: Path;
  value: string;
  /** The bundle-relative path it names, or `null` when it points outside the bundle. */
  inside: string | null;
}

/** `value` as a normalised bundle-relative path, or `null` when it would leave the bundle. */
export function inside(value: string): string | null {
  if (!value || value.includes("\\") || value.startsWith("/") || /^[A-Za-z]:/.test(value)) return null;
  const parts: string[] = [];
  for (const part of value.split("/")) {
    if (part === "..") {
      if (parts.length === 0) return null;
      parts.pop();
    } else if (part !== "." && part !== "") {
      parts.push(part);
    }
  }
  return parts.join("/") || null;
}

/** Every file `text` references, in document order; a text that does not parse references nothing. */
export function references(text: string): Reference[] {
  let data: unknown;
  try {
    data = indexFor(text).data;
  } catch {
    return [];
  }
  const out: Reference[] = [];
  const get = (m: unknown, k: string): unknown => (m instanceof Map ? m.get(k) : undefined);
  const fonts = get(get(data, "resources"), "fonts");
  if (fonts instanceof Map) {
    for (const [name, spec] of fonts) {
      const source = get(spec, "source");
      if (typeof source === "string") {
        out.push({ font: String(name), path: ["resources", "fonts", String(name), "source"], value: source, inside: inside(source) });
      }
    }
  }
  return out;
}

/** The references whose file the bundle does not hold. */
export function missing(text: string, files: { has(path: string): boolean }): Reference[] {
  return references(text).filter((r) => r.inside === null || !files.has(r.inside));
}

/** The face's own `face: name:` when `text` has one, the file's stem otherwise. */
export function displayName(filename: string, text: string | null = null): string {
  if (text !== null) {
    let data: unknown = null;
    try {
      data = indexFor(text).data;
    } catch {
      data = null;
    }
    const face = data instanceof Map ? data.get("face") : undefined;
    const name = face instanceof Map ? face.get("name") : undefined;
    if (typeof name === "string" && name.trim()) return name.trim();
  }
  let stem = filename.replace(/\\/g, "/");
  stem = stem.slice(stem.lastIndexOf("/") + 1);
  for (const suffix of [".zip", ".yaml", ".yml"]) {
    if (stem.toLowerCase().endsWith(suffix)) stem = stem.slice(0, -suffix.length);
  }
  return stem || "face";
}

function decode(data: Uint8Array, what: string): string {
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(data);
    return text.startsWith("﻿") ? text.slice(1) : text;
  } catch {
    throw new BundleError(`${what} is not UTF-8 text`);
  }
}

/** An uploaded `.yaml`/`.yml` or `.zip`, checked and unpacked. */
export function readUpload(filename: string, data: Uint8Array, limits: Limits = {}): Bundle {
  if (data.length > MAX_UPLOAD_BYTES) throw new BundleError(`the upload is over ${MAX_UPLOAD_BYTES / (1024 * 1024)} MB`);
  const lower = filename.toLowerCase();
  if (lower.endsWith(".yaml") || lower.endsWith(".yml")) {
    const text = decode(data, filename);
    return bundle(displayName(filename, text), text);
  }
  if (lower.endsWith(".zip")) {
    const read = readZip(displayName(filename), data, limits);
    read.name = displayName(filename, read.text);
    return read;
  }
  throw new BundleError(`${quoted(filename)} is neither a .yaml nor a .zip`);
}

const S_IFMT = 0o170000, S_IFLNK = 0o120000;

/** The central directory's entries: name, uncompressed size and external attributes. */
function centralDirectory(data: Uint8Array): { name: string; size: number; attr: number }[] {
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  let end = -1;
  for (let i = data.length - 22; i >= Math.max(0, data.length - 22 - 65535); i--) {
    if (view.getUint32(i, true) === 0x06054b50) {
      end = i;
      break;
    }
  }
  if (end < 0) throw new BundleError("the upload is not a readable .zip");
  const count = view.getUint16(end + 10, true);
  let at = view.getUint32(end + 16, true);
  const out: { name: string; size: number; attr: number }[] = [];
  for (let n = 0; n < count; n++) {
    if (at + 46 > data.length || view.getUint32(at, true) !== 0x02014b50) throw new BundleError("the upload is not a readable .zip");
    const size = view.getUint32(at + 24, true);
    const nameLength = view.getUint16(at + 28, true), extra = view.getUint16(at + 30, true), comment = view.getUint16(at + 32, true);
    const attr = view.getUint32(at + 38, true);
    const name = new TextDecoder().decode(data.subarray(at + 46, at + 46 + nameLength));
    out.push({ name, size, attr });
    at += 46 + nameLength + extra + comment;
  }
  return out;
}

/** How much a bundle may unpack to and hold; the defaults, but for a test. */
export interface Limits {
  unpacked?: number;
  entries?: number;
}

function readZip(name: string, data: Uint8Array, { unpacked: maxUnpacked = MAX_UNPACKED_BYTES, entries: maxEntries = MAX_ENTRIES }: Limits): Bundle {
  const listed = centralDirectory(data).filter((e) => !LITTER.test(e.name));
  if (listed.length > maxEntries) throw new BundleError(`the bundle has ${listed.length} entries; at most ${maxEntries}`);
  if (listed.reduce((n, e) => n + e.size, 0) > maxUnpacked) {
    throw new BundleError(`the bundle unpacks to over ${Math.floor(maxUnpacked / (1024 * 1024))} MB`);
  }
  let entries = new Map<string, string>();
  for (const entry of listed) {
    if (((entry.attr >>> 16) & S_IFMT) === S_IFLNK) throw new BundleError(`${entry.name} is a link; a bundle holds plain files only`);
    if (entry.name.endsWith("/")) continue;
    const path = inside(entry.name);
    if (path === null) throw new BundleError(`${entry.name} points outside the bundle`);
    entries.set(path, entry.name);
  }
  entries = unwrapped(entries);
  let unpacked: Record<string, Uint8Array>;
  try {
    const wanted = new Set(entries.values());
    unpacked = unzipSync(data, { filter: (file) => wanted.has(file.name) });
  } catch {
    throw new BundleError("the upload is not a readable .zip");
  }
  let faces = [...entries.keys()].filter((p) => !p.includes("/") && /\.ya?ml$/i.test(p));
  if (faces.length === 0) throw new BundleError("the bundle has no .yaml at its root");
  if (faces.length > 1) {
    if (!faces.includes(FACE)) {
      throw new BundleError(`the bundle has more than one .yaml at its root: ${faces.sort().join(", ")}; name the face ${FACE}`);
    }
    faces = [FACE];
  }
  const face = faces[0]!;
  const files = new Map<string, Uint8Array>();
  for (const [path, member] of entries) if (path !== face) files.set(path, unpacked[member]!);
  return bundle(name, decode(unpacked[entries.get(face)!]!, face), files);
}

/** A zip of a folder (`myface/face.yaml`) read as the folder's contents. */
function unwrapped(entries: Map<string, string>): Map<string, string> {
  if ([...entries.keys()].some((p) => !p.includes("/"))) return entries;
  const tops = new Set([...entries.keys()].map((p) => p.split("/", 1)[0]));
  if (tops.size !== 1) return entries;
  return new Map([...entries].map(([p, member]) => [p.slice(p.indexOf("/") + 1), member]));
}

/** `path`, or `stem-2.ext` and so on when it is taken. */
function free(files: { has(path: string): boolean }, path: string): string {
  if (!files.has(path)) return path;
  const slash = path.lastIndexOf("/");
  const parent = path.slice(0, slash), base = path.slice(slash + 1);
  const dot = base.lastIndexOf(".");
  const stem = dot > 0 ? base.slice(0, dot) : base, suffix = dot > 0 ? base.slice(dot) : "";
  let n = 2;
  while (files.has(`${parent}/${stem}-${n}${suffix}`)) n++;
  return `${parent}/${stem}-${n}${suffix}`;
}

/** Where an asset the author adds is stored: under `assets/`, by its own base name, renamed when taken. */
export function assetPath(files: { has(path: string): boolean }, filename: string): string {
  const normal = filename.replace(/\\/g, "/");
  const base = normal.slice(normal.lastIndexOf("/") + 1);
  if (!base || base === "." || base === "..") throw new BundleError(`${quoted(filename)} is not a file name`);
  return free(files, `${ASSETS}/${base}`);
}

/** The bundle as a `.zip`, the face at its root as `face.yaml`. */
export function toZip(b: Bundle): Uint8Array {
  const entries: Record<string, Uint8Array> = { [FACE]: strToU8(b.text) };
  for (const path of [...b.files.keys()].sort()) entries[path] = b.files.get(path)!;
  return zipSync(entries, { level: 6 });
}

