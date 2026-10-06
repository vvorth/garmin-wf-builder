// The editor's open faces.
//
// A `Document` is one face: its head in the history store (`store.ts`) and
// the files its manifest names. The compiler reads the face as `face.yaml`
// and its fonts from those files, so relative font paths resolve exactly as
// they would on disk.
//
// The pipeline runs once per version: the load, one resolve per target
// (font sheets reused through the studio's bake memo), and the lint. A frame
// -- one device, one set of switches -- is rendered on demand and kept for
// that version.
import { resolveAll, selectDevices } from "../build.ts";
import type { DeviceDatabase } from "../devices/device.ts";
import { Bag, type Diagnostic } from "../diagnostics.ts";
import { inLayout } from "../draw/frames.ts";
import { layers } from "../draw/layers.ts";
import * as colors from "../edit/colors.ts";
import { type Baker, move, resize, type Scope, target, turn, View } from "../edit/geometry.ts";
import { Gate, Loaded, loadText } from "../edit/gate.ts";
import * as hands from "../edit/hands.ts";
import {
  deleteElement, deleteElements, duplicateElement, moveElement, type Patch, remove, removeSlot, renameKey, renameReference,
  renameSlot, setValue,
} from "../edit/patch.ts";
import * as schemes from "../edit/schemes.ts";
import * as slots from "../edit/slots.ts";
import { ELEMENT_BLOCKS, type Entry, indexFor, isElement, type Path, Refused, sameData, type SpanIndex } from "../edit/spans.ts";
import { add, group, moveToBlock, paste, ungroup } from "../edit/structure.ts";
import type { Data } from "../edit/yaml.ts";
import { type BakeMemo, bakeFonts, ICON_FONT } from "../emit/resources.ts";
import type { FontFile } from "../fonts/files.ts";
import { Group, type Element, type Face } from "../ir/model.ts";
import type { ResolvedFace } from "../layout.ts";
import { encodePng } from "../png.ts";
import { frameItems, pngBytes, previewOptions, type PreviewOptions, render, resolveStyleEntry } from "../preview.ts";
import { assetPath, type Bundle, bundle, FACE, inside, missing, references } from "./bundle.ts";
import { describe, handles } from "./drag.ts";
import { GEOMETRY, globalsOf, inspect } from "./inspect.ts";
import { jsonDumps } from "./json.ts";
import { canRedo, canUndo, CHANGE, type Change, REDO, type Snapshot, type Store, UNDO, UnknownDocument } from "./store.ts";

/** A change asked for against a version that is no longer the head. */
export class StaleVersion extends Error {}

/** The YAML tab's label for a change, and how long a burst of typing stays one step to undo. */
export const TEXT_EDIT = "edit the text";
export const TEXT_MERGE_SECONDS = 10.0;
/** How many of the newest changes a face's summary lists. */
export const HISTORY_SHOWN = 100;
/** `snapshotMinutes`' default. */
export const SNAPSHOT_MINUTES = 5.0;
/** How many documents stay open. */
export const MAX_OPEN = 8;
/** How many changes each face's history keeps; compacted at twice as many. */
export const KEEP_CHANGES = 500;

type Json = Record<string, unknown>;

export interface FrameKey {
  device: string;
  style: string | null;
  time: [number, number, number] | null;
  date: [number, number, number] | null;
  asleep: boolean;
  aod: boolean;
  scale: number;
  /** The type each slot is drawn showing, as `[slot, type]` pairs, sorted. */
  picks: [string, string][];
}

export function frameKey(fields: Partial<FrameKey> & { device: string }): FrameKey {
  return { style: null, time: null, date: null, asleep: false, aod: false, scale: 2, picks: [], ...fields };
}

/** One version through the pipeline. */
export interface Analysis {
  version: number;
  face: Face | null;
  bag: Bag;
  resolved: Map<string, ResolvedFace>;
}

function base64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

const dataUrl = (png: Uint8Array): string => "data:image/png;base64," + base64(png);

const now = (): number => Date.now() / 1000;

/** `when` as `YYYY-MM-DD HH:MM`, local time. */
function stamp(when: number): string {
  const d = new Date(when * 1000);
  const p = (n: number): string => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** The pixels of `image` whose alpha is not zero, as `[left, top, right, bottom)`, or `null`. */
function inkBox(image: { width: number; height: number; data: Uint8Array | Uint8ClampedArray }): [number, number, number, number] | null {
  let x0 = image.width, y0 = image.height, x1 = -1, y1 = -1;
  for (let y = 0; y < image.height; y++) {
    for (let x = 0; x < image.width; x++) {
      if (!image.data[(y * image.width + x) * 4 + 3]) continue;
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }
  }
  return x1 < 0 ? null : [x0, y0, x1 + 1, y1 + 1];
}

function cropPng(image: { width: number; height: number; data: Uint8Array | Uint8ClampedArray }, box: [number, number, number, number]): Uint8Array {
  const [x0, y0, x1, y1] = box;
  const w = x1 - x0, h = y1 - y0;
  const out = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) out.set(image.data.subarray(((y0 + y) * image.width + x0) * 4, ((y0 + y) * image.width + x1) * 4), y * w * 4);
  return encodePng(w, h, out, 4);
}

/** An author path from JSON: a list of keys and list indices. */
export function path(raw: unknown): Path {
  if (!Array.isArray(raw) || !raw.every((s) => typeof s === "string" || (typeof s === "number" && Number.isInteger(s)))) {
    throw new Refused("a path is a list of keys and indices");
  }
  return raw as Path;
}

const dotted = (p: Path): string => p.map(String).join(".");
const isSlot = (p: Path): boolean => p.length === 3 && p[0] === "config" && p[1] === "slots";
const text = (op: Json, key: string): string => String(op[key] || "").trim();

function shownValue(value: unknown): string {
  const t = typeof value === "string" ? value : jsonDumps(value);
  return t.length <= 40 ? t : t.slice(0, 37) + "...";
}

const withWhat = (p: Patch, what: string): Patch => ({ ...p, what });

/** Every edit `Document.edit` takes, each from its op's fields: one patch, labelled as the history lists it. */
const EDITS: Record<string, (doc: Document, index: SpanIndex, op: Json) => Patch> = {
  set: (doc, index, op) => {
    const p = doc.editPath(index, op);
    return withWhat(setValue(index, p, toData(op["value"])), `set ${dotted(p)} to ${shownValue(op["value"])}`);
  },
  remove: (doc, index, op) => {
    const p = doc.editPath(index, op);
    if (index.get(p) === undefined) throw new Refused(`${dotted(p)} is not set`);
    return withWhat(isSlot(p) ? removeSlot(index, String(p[2])) : remove(index, p), `remove ${dotted(p)}`);
  },
  rename: (doc, index, op) => {
    const p = doc.editPath(index, op);
    const to = String(op["to"] ?? "").trim();
    const prefix = String(op["prefix"] ?? "");
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(to)) throw new Refused(`'${to}' is not a name: letters, digits and _, not starting with a digit`);
    const patch = isSlot(p) ? renameSlot(index, String(p[2]), to) : prefix ? renameReference(index, p, to, prefix) : renameKey(index, p, to);
    return withWhat(patch, `rename ${dotted(p)} to ${to}`);
  },
  use_color: (doc, index, op) => colors.useColor(index, doc.editPath(index, op), String(op["value"] ?? "")),
  add_swatch: (_, index, op) => colors.addSwatch(index, String(op["value"] ?? ""))[0],
  set_swatch: (_, index, op) => colors.setSwatch(index, String(op["name"] ?? ""), String(op["value"] ?? "")),
  remove_unused: (_, index) => colors.removeUnused(index),
  make_switchable: (_, index, op) => schemes.makeSwitchable(index, ((op["names"] ?? []) as unknown[]).map(String), text(op, "scheme")),
  add_scheme: (_, index, op) => schemes.addScheme(index, text(op, "name"), text(op, "like") || null),
  rename_scheme: (_, index, op) => schemes.renameScheme(index, text(op, "name"), text(op, "to")),
  delete_scheme: (_, index, op) => schemes.deleteScheme(index, text(op, "name")),
  remove_theme: (_, index, op) => schemes.removeTheme(index, text(op, "keep")),
  add_role: (_, index, op) => schemes.addRole(index, text(op, "name"), toData(op["value"])),
  rename_role: (_, index, op) => schemes.renameRole(index, text(op, "name"), text(op, "to")),
  delete_role: (_, index, op) => schemes.deleteRole(index, text(op, "name")),
  add_slot: (_, index, op) => slots.addSlot(index, text(op, "name"), text(op, "default")),
  add_hand_set: (_, index, op) => hands.addHandSet(index, text(op, "name"), text(op, "preset")),
  duplicate_hand_set: (_, index, op) => hands.duplicateHandSet(index, text(op, "name")),
  rename_hand_set: (_, index, op) => hands.renameHandSet(index, text(op, "name"), text(op, "to")),
  delete_hand_set: (_, index, op) => hands.deleteHandSet(index, text(op, "name")),
};

/** JSON from the browser as YAML data: objects as `Map`s, as the patch engine reads mappings. */
export function toData(value: unknown): Data {
  if (Array.isArray(value)) return value.map(toData);
  if (value !== null && typeof value === "object") return new Map(Object.entries(value).map(([k, v]) => [k, toData(v)]));
  return (value ?? null) as Data;
}

function blockPaths(index: SpanIndex): [Path, string][] {
  const out: [Path, string][] = [[["static"], "static"], [["elements"], "elements"]];
  const layouts = index.data instanceof Map ? index.data.get("layouts") : undefined;
  if (layouts instanceof Map) {
    for (const name of layouts.keys()) {
      out.push([["layouts", String(name), "static"], `${name}: static`]);
      out.push([["layouts", String(name), "elements"], `${name}: elements`]);
    }
  }
  return out;
}

function children(index: SpanIndex, block: Entry): Json[] {
  const out: Json[] = [];
  for (const entry of index.entries()) {
    if (entry.path.length !== block.path.length + 1 || !entry.path.slice(0, -1).every((s, i) => s === block.path[i])) continue;
    if (!isElement(index, entry)) continue;
    let data: unknown = index.data;
    for (const step of entry.path) data = (data as Map<unknown, unknown>).get(step);
    const end = index.text.slice(0, index.valueEnd(entry)).split("\n").length - 1;
    const node: Json = {
      kind: "element", id: entry.name, type: (data as Map<unknown, unknown>).get("type") ?? null, path: [...entry.path],
      line: entry.key.start.line + 1, end, children: [] as Json[],
    };
    for (const sub of ELEMENT_BLOCKS) {
      const childBlock = index.get([...entry.path, sub]);
      if (childBlock !== undefined) (node["children"] as Json[]).push(...children(index, childBlock));
    }
    out.push(node);
  }
  return out;
}

export class Document {
  readonly studio: Studio;
  readonly id: string;
  name: string;
  head: Change;
  text: string;
  private analysisCache: Analysis | null = null;
  /** Frames, layers and thumbnails of this version, by what and key, least recently used first. */
  private readonly frames = new Map<string, unknown>();
  private readonly handSets = new Map<string, Uint8Array>();
  /** This version's load, with its own diagnostics only, and the gate's load of the text about to become the head. */
  private loaded: Loaded | null = null;
  private seed: Loaded | null = null;
  /** When the last snapshot was taken, and of which version. */
  lastSnapshot: [number, number | null];

  constructor(studio: Studio, id: string) {
    this.studio = studio;
    this.id = id;
    const store = studio.store;
    const meta = store.meta(id);
    const head = store.head(id);
    if (head === null) throw new UnknownDocument(id);
    this.name = meta.name;
    this.head = head;
    this.text = store.text(id, head);
    const snaps = store.snapshots(id);
    this.lastSnapshot = snaps.length > 0 ? [snaps[snaps.length - 1]!.time, snaps[snaps.length - 1]!.seq] : [store.journal(id)[0]!.time, null];
  }

  get version(): number {
    return this.head.seq;
  }

  // -- the files the compiler reads --

  /** Where a design-relative path points inside the bundle, by `assets`. */
  private files(assets: ReadonlyMap<string, Uint8Array | string>): { exists: (p: string) => boolean; read: (p: string) => FontFile } {
    const get = (p: string): Uint8Array | null => {
      const rel = inside(p);
      const found = rel === null ? undefined : assets.get(rel);
      if (found === undefined) return null;
      return typeof found === "string" ? this.studio.store.get(this.id, found) : found;
    };
    return {
      exists: (p) => get(p) !== null,
      read: (p) => {
        if (p === ICON_FONT) return this.studio.iconFont();
        const bytes = get(p);
        if (bytes === null) throw new Refused(`${p} is not in the face's files`);
        return this.studio.fontFile(p, bytes);
      },
    };
  }

  private headAssets(): Map<string, string> {
    return new Map(Object.entries(this.head.assets));
  }

  private get exists(): (p: string) => boolean {
    return this.files(this.headAssets()).exists;
  }

  get baker(): Baker {
    const { read } = this.files(this.headAssets());
    return (face, device) => bakeFonts(face, device, read, this.studio.memo);
  }

  // -- changes --

  /** Record a change against version `expected`; `loaded` is `text` as the gate loaded it; `merge` takes the head's place. */
  commit(text: string, assets: ReadonlyMap<string, Uint8Array | string>, label: string, expected: number, loaded: Loaded | null = null, merge = false): Change {
    this.check(expected);
    const change = this.moved(this.studio.store.append(this.id, label, text, assets, merge));
    this.seed = loaded;
    return change;
  }

  private gate(): Gate {
    const before = this.loaded !== null && this.loaded.text === this.text ? this.loaded : null;
    return new Gate(FACE, this.text, this.exists, before);
  }

  /** Refuse a change asked for against `expected` unless that is the version the face is at. */
  check(expected: number): void {
    if (expected !== this.version) {
      throw new StaleVersion(`the face is at version ${this.version}, not ${expected}: reload it to see the newer change`);
    }
  }

  private moved(change: Change): Change {
    this.head = change;
    this.text = this.studio.store.text(this.id, change);
    this.analysisCache = null;
    this.frames.clear();
    return change;
  }

  // -- history --

  undo(expected: number): Change {
    this.check(expected);
    const line = this.studio.store.timeline(this.id);
    if (!canUndo(line)) throw new Refused("there is nothing to undo");
    const undone = line.states[line.cursor]!;
    return this.moved(this.studio.store.move(this.id, UNDO, `undo ${undone.label}`, line.states[line.cursor - 1]!));
  }

  redo(expected: number): Change {
    this.check(expected);
    const line = this.studio.store.timeline(this.id);
    if (!canRedo(line)) throw new Refused("there is nothing to redo");
    const state = line.states[line.cursor + 1]!;
    return this.moved(this.studio.store.move(this.id, REDO, `redo ${state.label}`, state));
  }

  /** Move to the state `seq` on the line of history in one step, recorded as one undo or redo. */
  goto(seq: number, expected: number): Change {
    this.check(expected);
    const line = this.studio.store.timeline(this.id);
    const at = line.states.findIndex((c) => c.seq === seq);
    if (at < 0) throw new Refused(`version ${seq} is not on the line of history`);
    if (at === line.cursor) throw new Refused("the face is already at that change");
    const state = line.states[at]!;
    const [kind, verb] = at < line.cursor ? [UNDO, "undo"] : [REDO, "redo"];
    return this.moved(this.studio.store.move(this.id, kind, `${verb} to ${state.label}`, state));
  }

  /** Give the face the display name `name` (not part of its text, so not a change). */
  rename(name: string): void {
    name = name.split(/\s+/).filter(Boolean).join(" ");
    if (!name) throw new Refused("a face's name cannot be empty");
    if (name.length > 120) throw new Refused("a face's name is at most 120 characters");
    this.studio.store.rename(this.id, name);
    this.name = name;
  }

  /** Cut the history back to its newest `keep` changes and remove the files nothing names any more. */
  compact(keep: number): number {
    const dropped = this.studio.store.compact(this.id, keep);
    if (dropped) this.studio.store.collect(this.id);
    return dropped;
  }

  snapshot(reason: string, when: number | null = null): Snapshot {
    const snap = this.studio.store.snapshot(this.id, this.head, reason, when ?? now());
    this.lastSnapshot = [snap.time, snap.seq];
    return snap;
  }

  /** Make a snapshot the head, as one change: undoable like any other. */
  restore(name: string, expected: number): Change {
    this.check(expected);
    const store = this.studio.store;
    const snap = store.getSnapshot(this.id, name);
    return this.commit(store.text(this.id, snap), new Map(Object.entries(snap.assets)), `restore the snapshot of ${stamp(snap.time)}`, expected);
  }

  /** The line of history, its newest `limit` states (all with `null`), and every snapshot. */
  history(limit: number | null = HISTORY_SHOWN): Json {
    const store = this.studio.store;
    const line = store.timeline(this.id);
    const first = limit === null ? 0 : Math.max(0, line.states.length - limit);
    const states: Json[] = [];
    for (let i = line.states.length - 1; i >= first; i--) {
      const c = line.states[i]!;
      states.push({ seq: c.seq, time: c.time, label: c.label, current: i === line.cursor, redo: i > line.cursor });
    }
    return {
      version: this.version, can_undo: canUndo(line), can_redo: canRedo(line),
      undo: canUndo(line) ? line.states[line.cursor]!.label : null,
      redo: canRedo(line) ? line.states[line.cursor + 1]!.label : null,
      states, total: line.states.length,
      snapshots: store.snapshots(this.id).reverse().map((s) => ({
        name: s.name, time: s.time, reason: s.reason, seq: s.seq, label: s.label, current: s.seq === this.version,
      })),
    };
  }

  /**
   * Store an uploaded file under `assets/`, as one change, and either point
   * every font whose `source:` is written `reference` at it, or declare it
   * as a new font `[name, size]`. A replaced file nothing else refers to
   * leaves the bundle. Each patch passes the gate.
   */
  addAsset(filename: string, data: Uint8Array, reference: string | null, expected: number, font: [string, string] | null = null): Change {
    this.check(expected);
    const assets = new Map<string, Uint8Array | string>(Object.entries(this.head.assets));
    const rel = assetPath(assets, filename);
    assets.set(rel, data);
    let t = this.text;
    let label: string;
    const { exists } = this.files(assets);
    if (reference !== null) {
      if (!references(t).some((r) => r.value === reference)) throw new Refused(`no font's source is written '${reference}'`);
      t = this.repoint(t, new Map([[reference, rel]]), exists);
      const old = inside(reference);
      if (old !== null && assets.has(old) && !references(t).some((r) => r.inside === old)) assets.delete(old);
      label = `use ${rel} for ${reference}`;
    } else if (font !== null) {
      const [name, size] = font;
      const index = indexFor(t);
      if (index.get(["resources", "fonts", name]) !== undefined) throw new Refused(`there is already a font called ${name}`);
      const patch = setValue(index, ["resources", "fonts", name], new Map<string, Data>([["source", rel], ["size", size]]));
      new Gate(FACE, t, exists).check(patch);
      t = patch.text;
      label = `add the font ${name} from ${rel}`;
    } else {
      label = `add ${rel}`;
    }
    return this.commit(t, assets, label, expected);
  }

  /** One edit from the inspector or the Face panel, gated and recorded (`EDITS`). */
  edit(op: Json, expected: number): Change {
    this.check(expected);
    const kind = op["op"];
    const handler = typeof kind === "string" && Object.hasOwn(EDITS, kind) ? EDITS[kind] : undefined;
    if (handler === undefined) throw new Refused(`unknown edit ${typeof kind === "string" ? `'${kind}'` : jsonDumps(kind ?? null)}`);
    const patch = handler(this, indexFor(this.text), op);
    const after = this.gate().check(patch);
    return this.commit(patch.text, this.headAssets(), patch.what, expected, after);
  }

  /**
   * The key an edit's `path` names: as written, or, for an element's key
   * (`element` given), that element's key or, for a geometry key, its
   * override on `device` that `scope` names.
   */
  editPath(index: SpanIndex, op: Json): Path {
    const p = path(op["path"]);
    if (op["element"] === undefined || op["element"] === null) return p;
    const element = path(op["element"]);
    const scope = op["scope"] ?? "all";
    if (scope !== "all" && scope !== "device" && scope !== "shape") throw new Refused(`scope '${String(scope)}' is not all, device or shape`);
    if (scope === "all") return [...element, ...p];
    if (p.length === 0 || !GEOMETRY.has(String(p[0]))) {
      throw new Refused(`${p.map(String).join(".")} cannot be overridden per device; only at:, size:, radius: and align: can`);
    }
    return target(index, element, p, this.studio.db.get(String(op["device"])), scope as Scope);
  }

  /**
   * The whole text as typed in the YAML tab. Unlike a patch, it is not
   * refused for an error the load reports: typing passes through broken
   * states. Text that is not YAML at all is refused, not recorded.
   */
  replaceText(t: string, expected: number): Change {
    this.check(expected);
    if (t === this.text) return this.head;
    indexFor(t);
    const loaded = loadText(FACE, t, this.exists);
    return this.commit(t, this.headAssets(), TEXT_EDIT, expected, loaded, this.typing());
  }

  private typing(): boolean {
    return this.head.kind === CHANGE && this.head.label === TEXT_EDIT && now() - this.head.time < TEXT_MERGE_SECONDS;
  }

  /** One structural edit from the layer tree or the canvas, gated and recorded, and the id to select after it. */
  structure(op: Json, expected: number): [Change, string | null] {
    this.check(expected);
    const index = indexFor(this.text);
    const kind = op["op"];
    let select: string | null = null;
    let patch: Patch;
    const added = (p: Patch): string | null => {
      const before = index.elementIds();
      return [...indexFor(p.text).elementIds()].find((id) => !before.has(id)) ?? null;
    };
    if (kind === "add") {
      const block = path(op["block"] || ["elements"]);
      patch = add(index, String(op["type"]), block, (op["before"] as string) || null, null, (op["choice"] as string | undefined) ?? null);
      select = added(patch);
    } else if (kind === "delete" && op["paths"] !== undefined && op["paths"] !== null) {
      if (!Array.isArray(op["paths"])) throw new Refused("a delete of several is a list of paths");
      patch = deleteElements(index, op["paths"].map(path));
    } else if (kind === "delete" || kind === "duplicate" || kind === "ungroup") {
      const p = path(op["path"]);
      patch = kind === "delete" ? deleteElement(index, p) : kind === "duplicate" ? duplicateElement(index, p) : ungroup(index, p);
      if (kind === "duplicate") select = added(patch);
    } else if (kind === "move") {
      const p = path(op["path"]);
      const block = path(op["block"] || p.slice(0, -1));
      const before = (op["before"] as string) || null;
      if (block.length === p.length - 1 && block.every((s, i) => s === p[i])) {
        const siblings = index.entries().filter((e) => e.path.length === block.length + 1 && block.every((s, i) => s === e.path[i]) && isElement(index, e)).map((e) => e.name);
        const name = String(p[p.length - 1]);
        if (!siblings.includes(name) || (before !== null && !siblings.includes(before))) throw new Refused(`${before} is not in ${block.map(String).join(".")}`);
        const order = siblings.filter((n) => n !== name);
        patch = moveElement(index, p, before !== null ? order.indexOf(before) : order.length);
      } else {
        patch = moveToBlock(index, p, block, before);
      }
      select = String(p[p.length - 1]);
    } else if (kind === "paste") {
      const clip = op["text"];
      if (typeof clip !== "string" || !clip.trim()) throw new Refused("there is nothing to paste");
      const block = path(op["block"] || ["elements"]);
      patch = paste(index, clip, block, (op["before"] as string) || null);
      const after = indexFor(patch.text);
      const ids = index.elementIds();
      select = after.entries().find((e) => e.path.length === block.length + 1 && block.every((s, i) => s === e.path[i])
        && !ids.has(e.name) && isElement(after, e))?.name ?? null;
    } else if (kind === "group") {
      if (!Array.isArray(op["paths"])) throw new Refused("a group is made of a list of paths");
      patch = group(index, op["paths"].map(path));
      select = added(patch);
    } else {
      throw new Refused(`unknown structural edit ${typeof kind === "string" ? `'${kind}'` : jsonDumps(kind ?? null)}`);
    }
    const after = this.gate().check(patch);
    return [this.commit(patch.text, this.headAssets(), patch.what, expected, after), select];
  }

  /** `t` with every font `source:` written as a key of `moved` rewritten to its value, each patch gated. */
  repoint(t: string, moved: ReadonlyMap<string, string>, exists: (p: string) => boolean = this.exists): string {
    for (const ref of references(t).filter((r) => moved.has(r.value) && moved.get(r.value) !== r.value)) {
      const patch = setValue(indexFor(t), ref.path, moved.get(ref.value)!);
      new Gate(FACE, t, exists).check(patch);
      t = patch.text;
    }
    return t;
  }

  // -- the bundle --

  bundle(): Bundle {
    const files = new Map<string, Uint8Array>();
    for (const [rel, sha] of Object.entries(this.head.assets)) files.set(rel, this.studio.store.get(this.id, sha));
    return bundle(this.name, this.text, files);
  }

  missing(): string[] {
    return missing(this.text, this.headAssets()).map((r) => r.value);
  }

  // -- the pipeline --

  analysis(): Analysis {
    if (this.analysisCache !== null && this.analysisCache.version === this.version) return this.analysisCache;
    const seed = this.seed;
    this.seed = null;
    const loaded = seed !== null && seed.text === this.text ? seed : loadText(FACE, this.text, this.exists);
    // What the gate compares against: the load's own diagnostics, before the resolve and the lint add theirs.
    const copy = new Bag();
    copy.items = [...loaded.bag.items];
    this.loaded = new Loaded(loaded.text, loaded.face, copy);
    const bag = loaded.bag;
    const analysis: Analysis = { version: this.version, face: loaded.face, bag, resolved: new Map() };
    if (loaded.face !== null) {
      const devices = selectDevices(loaded.face, this.studio.db, bag);
      if (devices.length > 0) analysis.resolved = resolveAll(loaded.face, devices, bag, this.baker)[0];
    }
    this.analysisCache = analysis;
    return analysis;
  }

  diagnostics(): Json[] {
    return this.analysis().bag.items.map((d) => this.diagnostic(d));
  }

  private diagnostic(d: Diagnostic): Json {
    const out: Json = { severity: d.severity, code: d.code, message: d.message, notes: [...d.notes] };
    if (d.span !== null) Object.assign(out, { file: d.span.path, line: d.span.line, col: d.span.col });
    return out;
  }

  /** This version on `key.device`, and the preview options for `key`. */
  private placed(key: FrameKey): [ResolvedFace, PreviewOptions] {
    const resolved = this.analysis().resolved.get(key.device);
    if (resolved === undefined) throw new Refused(`${key.device} is not drawn: the face does not load, or does not target it`);
    return [resolved, previewOptions({
      scale: key.scale, style: key.style, time: key.time, date: key.date, asleep: key.asleep, aod: key.aod, picks: key.picks,
    })];
  }

  private cached<T>(kind: string, key: FrameKey, make: () => T): T {
    const slot = JSON.stringify([kind, key]);
    if (this.frames.has(slot)) {
      const value = this.frames.get(slot) as T;
      this.frames.delete(slot);
      this.frames.set(slot, value);
      return value;
    }
    const value = make();
    this.frames.set(slot, value);
    while (this.frames.size > 48) this.frames.delete(this.frames.keys().next().value!);
    return value;
  }

  /**
   * One frame: the image the preview draws; every element the frame shows
   * (and every group in its layout) with its box, centre and drag handles;
   * and the frame as layers in draw order, which the browser draws itself.
   * A layer is its JSON ops, the tiles its text and icons paste being the
   * frame's `tiles`, or, for one with an op the browser does not draw (an
   * outlined group's ring), its image cropped to its ink.
   */
  frame(key: FrameKey): Json {
    return this.cached("frame", key, () => {
      const [resolved, options] = this.placed(key);
      const entry = resolveStyleEntry(resolved.face, options.style);
      const drawn = new Set(frameItems(resolved, options, entry).map((p) => p.id));
      const layout = entry !== null ? entry.layout : null;
      // A group the author wrote; the `static:` block's and a layout's own groups are containers, not elements.
      const authored = indexFor(this.text).elementIds();
      const items: Json[] = [];
      for (const placed of resolved.items) {
        if (!drawn.has(placed.id) && !(placed.kind === "group" && authored.has(placed.id) && inLayout(placed, layout))) continue;
        const box = placed.box;
        const span = placed.element.span;
        items.push({
          id: placed.id, kind: placed.kind, drawn: drawn.has(placed.id), line: span !== null ? span.line : null,
          box: [box.x, box.y, box.width, box.height], center: [...placed.center], handles: handles(placed),
        });
      }
      const stack: Json[] = [];
      let tiles = null;
      for (const layer of layers(resolved, options, { paintAll: false })) {
        tiles = layer.tiles ?? tiles;
        if (layer.image === null) {
          stack.push({ id: layer.id, kind: layer.kind, ops: layer.ops });
          continue;
        }
        const ink = inkBox(layer.image);
        stack.push({
          id: layer.id, kind: layer.kind, origin: ink !== null ? [ink[0], ink[1]] : null,
          image: ink !== null ? dataUrl(cropPng(layer.image, ink)) : null,
        });
      }
      const [packed, index] = tiles !== null ? tiles.pack() : [new Uint8Array(0), {}];
      const device = resolved.device;
      return {
        version: this.version, device: device.id, scale: key.scale, width: device.width, height: device.height,
        shape: device.shape, minor_radius: device.minorRadius,
        frame: dataUrl(pngBytes(render(resolved, options))),
        items, layers: stack, tiles: { data: base64(packed), index },
      };
    });
  }

  /**
   * The hand set `name` drawn alone on `deviceId` at the sample time, centred
   * and cropped to its ink: a throwaway `hands` element placing it is loaded
   * beside the face, so the set's colours resolve as they do in the face.
   */
  handSetImage(name: string, deviceId: string, scale = 1): Uint8Array {
    const slot = JSON.stringify([this.version, name, deviceId, scale]);
    const cached = this.handSets.get(slot);
    if (cached !== undefined) return cached;
    const index = indexFor(this.text);
    if (!hands.summaryNames(index).includes(name)) throw new Refused(`there is no hand set called ${name}`);
    const element = "wfb_hand_set_preview";
    const patch = setValue(index, ["elements", element], new Map<string, Data>([["type", "hands"], ["set", name], ["at", new Map([["anchor", "center"]])]]));
    const loaded = loadText(".hand-set.yaml", patch.text, this.exists);
    if (loaded.face === null) throw new Refused("the face does not load: mend the errors in Diagnostics first");
    const device = this.studio.db.get(deviceId);
    const [resolved] = resolveAll(loaded.face, [device], new Bag(), this.baker);
    const options = previewOptions({ scale: Math.min(4, Math.max(1, scale)) });
    const image = layers(resolved.get(device.id)!, options).find((l) => l.id === element)?.image ?? null;
    const ink = image !== null ? inkBox(image) : null;
    if (image === null || ink === null) throw new Refused(`the hand set ${name} draws nothing on ${deviceId}`);
    const out = cropPng(image, ink);
    this.handSets.set(slot, out);
    while (this.handSets.size > 32) this.handSets.delete(this.handSets.keys().next().value!);
    return out;
  }

  /** The face on its first target, at the watch's own size, for the library; `null` when it does not load. */
  cover(): Uint8Array | null {
    const targets = [...this.analysis().resolved.keys()];
    return targets.length > 0 ? this.thumbnail(frameKey({ device: targets[0]!, scale: 1 })) : null;
  }

  /** The frame as a PNG file, for the strip of targets. */
  thumbnail(key: FrameKey): Uint8Array {
    return this.cached("thumb", key, () => {
      const [resolved, options] = this.placed(key);
      return pngBytes(render(resolved, options));
    });
  }

  /**
   * One gesture on the canvas, on `deviceId`: written in the author's units
   * to the key that device reads ("auto"), or to the scope named, through
   * the gate. Returns the change and whether the element landed on the
   * dragged pixel.
   */
  drag(elementId: string, gesture: Json, deviceId: string, scope: string, expected: number): [Change, boolean] {
    this.check(expected);
    if (!["auto", "all", "device", "shape"].includes(scope)) throw new Refused(`scope '${scope}' is not auto, all, device or shape`);
    const device = this.studio.db.get(deviceId);
    const analysis = this.analysis();
    const view = new View(FACE, this.text, device, this.exists, this.baker, { loaded: this.loaded, resolved: analysis.resolved.get(deviceId) ?? null });
    const kind = gesture["kind"];
    const part = gesture["part"] ?? "both";
    if (part !== "both" && part !== "at" && part !== "to") throw new Refused(`part '${String(part)}' is not both, at or to`);
    if (kind !== "move" && kind !== "resize" && kind !== "turn") throw new Refused(`unknown gesture '${String(kind)}'`);
    const need = (name: string): unknown => {
      if (!(name in gesture)) throw new Refused(`a ${kind} gesture needs its values: '${name}'`);
      return gesture[name];
    };
    const int = (name: string): number => {
      const v = Number(need(name));
      if (!Number.isFinite(v)) throw new Refused(`a ${kind} gesture needs its values: ${name}`);
      return Math.trunc(v);
    };
    let converted;
    if (kind === "move") converted = move(view, elementId, int("dx"), int("dy"), scope as Scope, part);
    else if (kind === "resize") converted = resize(view, elementId, (need("key") as unknown[]).map(String), int("delta"), scope as Scope);
    else converted = turn(view, elementId, String(need("key")), Number(need("degrees")), scope as Scope);
    const after = this.gate().check(converted.patch, view.tried);
    const change = this.commit(converted.patch.text, this.headAssets(), describe(gesture, elementId, deviceId), expected, after);
    return [change, converted.landed];
  }

  /**
   * Several elements moved by one drag, as one change: each written as `drag`
   * writes one, in turn on the text the last left. An element inside a moved
   * group is left to the group. Returns the change and whether every element landed.
   */
  moveAll(elementIds: string[], dx: number, dy: number, deviceId: string, scope: string, expected: number): [Change, boolean] {
    this.check(expected);
    if (!["auto", "all", "device", "shape"].includes(scope)) throw new Refused(`scope '${scope}' is not auto, all, device or shape`);
    let ids = [...new Set(elementIds)];
    if (ids.length === 0) throw new Refused("a move needs at least one element");
    const device = this.studio.db.get(deviceId);
    const analysis = this.analysis();
    const face = this.loaded !== null ? this.loaded.face : null;
    if (face !== null) {
      const insideMoved = new Set<string>();
      const walk = (elements: readonly Element[], movedAbove: boolean): void => {
        for (const element of elements) {
          if (movedAbove) insideMoved.add(element.id);
          if (element instanceof Group) walk(element.items, movedAbove || ids.includes(element.id));
        }
      };
      walk(face.elements, false);
      ids = ids.filter((i) => !insideMoved.has(i));
    }
    let t = this.text, loaded = this.loaded, resolved: ResolvedFace | null = analysis.resolved.get(deviceId) ?? null;
    let landed = true;
    let patch: Patch | null = null;
    let view: View | null = null;
    for (const elementId of ids) {
      view = new View(FACE, t, device, this.exists, this.baker, { loaded, resolved });
      const converted = move(view, elementId, dx, dy, scope as Scope);
      patch = converted.patch;
      if (!sameData(indexFor(patch.text).data, patch.expected)) throw new Refused(`${patch.what}: the edit would change more than intended`);
      landed = landed && converted.landed;
      t = patch.text;
      loaded = view.tried;
      resolved = null;
    }
    const after = this.gate().check(patch!, view!.tried);
    const label = describe({ kind: "move", dx, dy }, ids.join(", "), deviceId);
    return [this.commit(patch!.text, this.headAssets(), label, expected, after), landed];
  }

  // -- what the editor shows --

  /** The face's element blocks in draw order, each element with its children. */
  tree(): Json[] {
    let index: SpanIndex;
    try {
      index = indexFor(this.text);
    } catch (error) {
      if (error instanceof Refused) return [];
      throw error;
    }
    return blockPaths(index).map(([p, label]) => {
      const entry = index.get(p);
      return { kind: "block", label, path: [...p], line: entry ? entry.key.start.line + 1 : null, children: entry ? children(index, entry) : [] };
    });
  }

  summary(): Json {
    const analysis = this.analysis();
    const face = analysis.face;
    const styles = face !== null && face.config_style !== null
      ? face.config_style.entries.map((e) => ({ name: e.name, label: (e as { label?: string | null }).label || e.name }))
      : [];
    return {
      id: this.id, name: this.name, version: this.version, text: this.text, missing: this.missing(),
      loads: face !== null, targets: [...analysis.resolved.keys()], styles, tree: this.tree(),
      diagnostics: this.diagnostics(), assets: Object.keys(this.head.assets).sort(), history: this.history(),
      globals: globalsOf(this.text, this.studio.db),
    };
  }

  inspect(element: unknown, deviceId: string | null): Json {
    return inspect(this.text, path(element), deviceId ? this.studio.db.get(deviceId) : null);
  }
}

/**
 * Every document open, over one store and one device database. At most
 * `MAX_OPEN` stay open: the store rebuilds any of them. `onEvent(name,
 * data)` is told what the studio did on its own (a timed snapshot).
 */
export class Studio {
  readonly store: Store;
  readonly db: DeviceDatabase;
  readonly memo: BakeMemo = new WeakMap();
  readonly snapshotSeconds: number;
  readonly keepChanges: number;
  onEvent: (name: string, data: Json) => void = () => {};
  private readonly open = new Map<string, Document>();
  private readonly icon: () => FontFile;
  private readonly fontFiles = new Map<string, FontFile>();

  constructor(store: Store, db: DeviceDatabase, iconFont: () => FontFile,
    { snapshotMinutes = SNAPSHOT_MINUTES, keepChanges = KEEP_CHANGES }: { snapshotMinutes?: number; keepChanges?: number } = {}) {
    this.store = store;
    this.db = db;
    this.icon = iconFont;
    this.snapshotSeconds = snapshotMinutes * 60;
    this.keepChanges = keepChanges;
  }

  iconFont(): FontFile {
    return this.icon();
  }

  /** One `FontFile` per asset's bytes, so the bake memo finds its sheets again. */
  fontFile(path: string, bytes: Uint8Array): FontFile {
    const key = `${path}\0${bytes.length}`;
    const found = this.fontFiles.get(key);
    if (found !== undefined && (found.bytes === bytes || equalBytes(found.bytes, bytes))) return found;
    const file = { path, bytes };
    this.fontFiles.set(key, file);
    return file;
  }

  /**
   * Snapshot every open document that changed since its last snapshot, once
   * an interval has passed, and compact one whose history has grown past
   * twice `keepChanges`.
   */
  tick(when: number = now()): Snapshot[] {
    const taken: Snapshot[] = [];
    for (const doc of [...this.open.values()]) {
      try {
        if (this.store.journal(doc.id).length > 2 * this.keepChanges) doc.compact(this.keepChanges);
      } catch (error) {
        this.onEvent("error", { id: doc.id, message: `cutting the history short failed: ${(error as Error).message}` });
      }
      const [time, seq] = doc.lastSnapshot;
      if (seq === doc.version || when - time < this.snapshotSeconds) continue;
      const snap = doc.snapshot("timer", when);
      taken.push(snap);
      this.onEvent("snapshot", { id: doc.id, name: snap.name, version: doc.version });
    }
    return taken;
  }

  /** The document `id`, opened when needed. */
  document(id: string): Document {
    let doc = this.open.get(id);
    if (doc === undefined) {
      doc = new Document(this, id);
      this.open.set(id, doc);
    }
    this.open.delete(id);
    this.open.set(id, doc);
    while (this.open.size > MAX_OPEN) this.open.delete(this.open.keys().next().value!);
    return doc;
  }

  /** A new document from `b`; `moved` maps references to where their files were gathered, patched as a second change. */
  create(b: Bundle, label: string, moved: ReadonlyMap<string, string> | null = null): Document {
    const id = this.store.newDocument(b.name);
    this.store.append(id, label, b.text, b.files);
    const doc = this.document(id);
    if (moved !== null && moved.size > 0) {
      doc.commit(doc.repoint(doc.text, moved), new Map(Object.entries(doc.head.assets)), "gather assets into the bundle", doc.version);
    }
    return doc;
  }

  /** A new document holding a snapshot of `id`: "open as a copy". */
  fork(id: string, name: string): Document {
    const snap = this.store.getSnapshot(id, name);
    const source = this.document(id);
    const when = stamp(snap.time);
    const files = new Map<string, Uint8Array>();
    for (const [rel, sha] of Object.entries(snap.assets)) files.set(rel, this.store.get(id, sha));
    return this.create(bundle(`${source.name} (${when})`, this.store.text(id, snap), files), `copy of ${source.name}'s snapshot of ${when}`);
  }

  delete(id: string): void {
    this.open.delete(id);
    this.store.delete(id);
  }
}

function equalBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

