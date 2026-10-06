// The editor's durable state: every document's history, over a key-value
// backend: IndexedDB in the browser (`./worker.ts`), a map in tests.
//
// Records, each its own key, so an action is one or two writes:
//
// - `meta/<id>`: the display name and when the document was created;
// - `blob/<id>/<sha256>`: every text version and every asset file, content
//   addressed, so a long history of a small face costs little and an asset
//   is stored once. A text is stored zlib-compressed (`z: true`);
// - `journal/<id>/<seq>`: one record per action, naming the text and asset
//   manifest the document has after it by hash, so the last record *is*
//   the document;
// - `snapshot/<id>/<name>`: a point in time to go back to, naming its text
//   and assets by hash the same way.
//
// The journal's records are the Python store's journal lines, field for
// field, so a server can replay them later.
//
// **Undo and redo are journal records too.** A `change` adds a state; an
// `undo` or `redo` moves to an earlier or later one, naming it by its
// sequence number (`target`). Replaying the journal (`timeline`) gives the
// states on the current line of history and where the document is among
// them. A change after an undo drops the states past the cursor. A
// `change` marked `merge` takes the place of the state before it, so a
// burst of typing is one step to undo.
//
// The store holds everything in memory, read once (`open`); each action
// changes the memory at once and queues its writes, which `flush` awaits.
// A request's answer waits for its flush, so an acknowledged change is on
// disk.
//
// **Compaction** (`compact`) rewrites the journal as the newest states on
// the current line, and, when the document is in an earlier state than the
// newest, one move record to it under the head's `seq`; `collect` then
// removes every blob neither the journal nor a snapshot names.
import { uuid } from "../uuid.ts";
import { unzlibSync, zlibSync } from "fflate";
import { sha256 } from "./sha256.ts";

/** What a journal record does. */
export const CHANGE = "change", UNDO = "undo", REDO = "redo";

const ID = /^[0-9a-f]{32}$/;
const SHA = /^[0-9a-f]{64}$/;
const SNAPSHOT = /^[0-9]{8}-[0-9]+$/;

/** The store could not be read or written; the change is not applied. */
export class StoreError extends Error {}

/** No document with that id is in the store. */
export class UnknownDocument extends Error {}

/** No snapshot with that name is in the document. */
export class UnknownSnapshot extends Error {}

/** One journal record: the action, and the document after it. */
export interface Change {
  seq: number;
  time: number;
  label: string;
  text: string;
  assets: Record<string, string>;
  kind: string;
  /** For `undo`/`redo`: the `seq` of the `change` it moved to. */
  target?: number;
  /** For a `change`: it replaces the state before it on the line. */
  merge?: boolean;
}

export interface Timeline {
  states: Change[];
  cursor: number;
}

export const canUndo = (line: Timeline): boolean => line.cursor > 0;
export const canRedo = (line: Timeline): boolean => line.cursor < line.states.length - 1;

export interface Snapshot {
  name: string;
  time: number;
  /** Why it was taken: `timer`, `download`, `manual`. */
  reason: string;
  /** The journal position it was taken at, and that state's label. */
  seq: number;
  label: string;
  text: string;
  assets: Record<string, string>;
}

export interface Meta {
  name: string;
  created: number;
}

/** Where the store's records live. */
export interface Backend {
  /** Every record. */
  load(): Promise<Map<string, unknown>>;
  put(key: string, value: unknown): Promise<void>;
  delete(keys: readonly string[]): Promise<void>;
}

/** A backend holding its records in memory: tests, and a browser without IndexedDB. */
export class MemoryBackend implements Backend {
  readonly records = new Map<string, unknown>();

  async load(): Promise<Map<string, unknown>> {
    return new Map(this.records);
  }

  async put(key: string, value: unknown): Promise<void> {
    this.records.set(key, value);
  }

  async delete(keys: readonly string[]): Promise<void> {
    for (const key of keys) this.records.delete(key);
  }
}

interface Blob {
  data: Uint8Array;
  z: boolean;
}

interface Doc {
  meta: Meta;
  journal: Change[];
  blobs: Map<string, Blob>;
  snapshots: Map<string, Snapshot>;
  timeline: Timeline | null;
}

/** The timeline a journal leaves. */
export function replay(journal: readonly Change[]): Timeline {
  const line: Timeline = { states: [], cursor: -1 };
  const bySeq = new Map<number, number>();
  for (const entry of journal) {
    if (entry.kind === CHANGE) {
      for (const gone of line.states.slice(line.cursor + 1)) bySeq.delete(gone.seq);
      line.states.splice(line.cursor + 1);
      if (entry.merge && line.states.length > 0) {
        bySeq.delete(line.states[line.states.length - 1]!.seq);
        line.states[line.states.length - 1] = entry;
      } else {
        line.states.push(entry);
      }
      line.cursor = line.states.length - 1;
      bySeq.set(entry.seq, line.cursor);
    } else if (entry.target !== undefined && bySeq.has(entry.target)) {
      line.cursor = bySeq.get(entry.target)!;
    }
  }
  return line;
}

const seqKey = (seq: number): string => String(seq).padStart(10, "0");
const now = (): number => Date.now() / 1000;
const encoder = new TextEncoder();

export class Store {
  private readonly backend: Backend;
  private readonly docs = new Map<string, Doc>();
  private pending: Promise<void>[] = [];
  private failure: unknown = null;

  private constructor(backend: Backend) {
    this.backend = backend;
  }

  /** The store over `backend`, every record read. */
  static async open(backend: Backend): Promise<Store> {
    const store = new Store(backend);
    let records: Map<string, unknown>;
    try {
      records = await backend.load();
    } catch (error) {
      throw new StoreError(`cannot read the history store: ${(error as Error).message}`);
    }
    const doc = (id: string): Doc => {
      let found = store.docs.get(id);
      if (found === undefined) {
        found = { meta: { name: "", created: 0 }, journal: [], blobs: new Map(), snapshots: new Map(), timeline: null };
        store.docs.set(id, found);
      }
      return found;
    };
    const metas = new Set<string>();
    for (const [key, value] of records) {
      const [kind, id, rest] = key.split("/");
      if (id === undefined || !ID.test(id)) continue;
      if (kind === "meta") {
        doc(id).meta = value as Meta;
        metas.add(id);
      } else if (kind === "journal") doc(id).journal.push(value as Change);
      else if (kind === "blob" && rest !== undefined) doc(id).blobs.set(rest, value as Blob);
      else if (kind === "snapshot" && rest !== undefined) doc(id).snapshots.set(rest, value as Snapshot);
    }
    for (const id of [...store.docs.keys()]) {
      if (!metas.has(id)) store.docs.delete(id);
      else store.docs.get(id)!.journal.sort((a, b) => a.seq - b.seq);
    }
    return store;
  }

  /** Wait for every queued write; a failed one is thrown, once. */
  async flush(): Promise<void> {
    const pending = this.pending;
    this.pending = [];
    await Promise.allSettled(pending);
    if (this.failure !== null) {
      const failure = this.failure;
      this.failure = null;
      throw new StoreError(`cannot write to the history store: ${(failure as Error).message ?? failure}`);
    }
  }

  private write(key: string, value: unknown): void {
    this.pending.push(this.backend.put(key, value).catch((e) => { this.failure = e; }));
  }

  private remove(keys: string[]): void {
    if (keys.length > 0) this.pending.push(this.backend.delete(keys).catch((e) => { this.failure = e; }));
  }

  private doc(id: string): Doc {
    const found = ID.test(id) ? this.docs.get(id) : undefined;
    if (found === undefined) throw new UnknownDocument(id);
    return found;
  }

  has(id: string): boolean {
    return ID.test(id) && this.docs.has(id);
  }

  // -- documents --

  newDocument(name: string): string {
    const id = uuid().replace(/-/g, "");
    const meta = { name, created: now() };
    this.docs.set(id, { meta, journal: [], blobs: new Map(), snapshots: new Map(), timeline: null });
    this.write(`meta/${id}`, meta);
    return id;
  }

  meta(id: string): Meta {
    return { ...this.doc(id).meta };
  }

  rename(id: string, name: string): void {
    const doc = this.doc(id);
    doc.meta = { ...doc.meta, name };
    this.write(`meta/${id}`, doc.meta);
  }

  /** Every document with a recorded change, most recently changed first. */
  documents(): { id: string; name: string; created: number; changed: number; version: number; snapshots: number }[] {
    const out = [];
    for (const [id, doc] of this.docs) {
      const head = doc.journal[doc.journal.length - 1];
      if (head === undefined) continue;
      out.push({ id, name: doc.meta.name, created: doc.meta.created, changed: head.time, version: head.seq, snapshots: doc.snapshots.size });
    }
    return out.sort((a, b) => b.changed - a.changed);
  }

  delete(id: string): void {
    const doc = this.doc(id);
    this.docs.delete(id);
    this.remove([
      `meta/${id}`,
      ...doc.journal.map((c) => `journal/${id}/${seqKey(c.seq)}`),
      ...[...doc.blobs.keys()].map((sha) => `blob/${id}/${sha}`),
      ...[...doc.snapshots.keys()].map((name) => `snapshot/${id}/${name}`),
    ]);
  }

  // -- blobs --

  /** Store `data` once, by its hash; `compress` keeps it deflated. */
  put(id: string, data: Uint8Array, compress = false): string {
    const doc = this.doc(id);
    const sha = sha256(data);
    if (!doc.blobs.has(sha)) {
      const blob = { data: compress ? zlibSync(data, { level: 6 }) : data, z: compress };
      doc.blobs.set(sha, blob);
      this.write(`blob/${id}/${sha}`, blob);
    }
    return sha;
  }

  get(id: string, sha: string): Uint8Array {
    if (!SHA.test(sha)) throw new StoreError(`not a blob id: '${sha}'`);
    const blob = this.doc(id).blobs.get(sha);
    if (blob === undefined) throw new StoreError(`the history store has lost the file ${sha}`);
    return blob.z ? unzlibSync(blob.data) : blob.data;
  }

  text(id: string, state: { text: string }): string {
    return new TextDecoder().decode(this.get(id, state.text));
  }

  // -- the journal --

  /**
   * Record a change: `text` and `assets` (bytes to store, or the hash of a
   * blob already stored) become the head. With `merge` it takes the place
   * of the state before it on the line.
   */
  append(id: string, label: string, text: string, assets: ReadonlyMap<string, Uint8Array | string>, merge = false): Change {
    const manifest: Record<string, string> = {};
    for (const path of [...assets.keys()].sort()) {
      const value = assets.get(path)!;
      manifest[path] = typeof value === "string" ? value : this.put(id, value);
    }
    return this.record(id, label, this.put(id, encoder.encode(text), true), manifest, CHANGE, undefined, merge);
  }

  /** Record an undo or redo to `state`, a `change`. */
  move(id: string, kind: string, label: string, state: Change): Change {
    return this.record(id, label, state.text, { ...state.assets }, kind, state.seq);
  }

  private record(id: string, label: string, text: string, assets: Record<string, string>, kind: string,
    target: number | undefined, merge = false): Change {
    const doc = this.doc(id);
    const head = doc.journal[doc.journal.length - 1];
    const change: Change = { seq: head ? head.seq + 1 : 1, time: now(), label, text, assets, kind };
    if (target !== undefined) change.target = target;
    if (merge) change.merge = true;
    doc.journal.push(change);
    doc.timeline = null;
    this.write(`journal/${id}/${seqKey(change.seq)}`, change);
    return change;
  }

  journal(id: string): Change[] {
    return [...this.doc(id).journal];
  }

  head(id: string): Change | null {
    const journal = this.doc(id).journal;
    return journal[journal.length - 1] ?? null;
  }

  timeline(id: string): Timeline {
    const doc = this.doc(id);
    if (doc.timeline === null) doc.timeline = replay(doc.journal);
    return doc.timeline;
  }

  // -- snapshots --

  /** Keep `state` (the document's head) as a point in time. */
  snapshot(id: string, state: Change, reason: string, when: number = now()): Snapshot {
    const snap: Snapshot = {
      name: `${String(state.seq).padStart(8, "0")}-${Math.trunc(when * 1000)}`, time: when, reason, seq: state.seq,
      label: state.label, text: state.text, assets: { ...state.assets },
    };
    this.doc(id).snapshots.set(snap.name, snap);
    this.write(`snapshot/${id}/${snap.name}`, snap);
    return snap;
  }

  /** Oldest first. */
  snapshots(id: string): Snapshot[] {
    return [...this.doc(id).snapshots.values()].sort((a, b) => a.time - b.time);
  }

  getSnapshot(id: string, name: string): Snapshot {
    const snap = SNAPSHOT.test(name) ? this.doc(id).snapshots.get(name) : undefined;
    if (snap === undefined) throw new UnknownSnapshot(name);
    return snap;
  }

  // -- compaction and pruning --

  /** Rewrite the journal as the newest `keep` states on its line (never cutting the current one); how many records went. */
  compact(id: string, keep: number): number {
    const doc = this.doc(id);
    if (doc.journal.length === 0) return 0;
    const line = this.timeline(id);
    const head = doc.journal[doc.journal.length - 1]!;
    const current = line.states[line.cursor]!;
    const first = Math.min(Math.max(0, line.states.length - keep), line.cursor);
    const records: Change[] = line.states.slice(first).map((s) => ({ seq: s.seq, time: s.time, label: s.label, text: s.text, assets: s.assets, kind: CHANGE }));
    if (head.seq !== current.seq) {
      records.push({ seq: head.seq, time: head.time, label: head.label, text: current.text, assets: { ...current.assets }, kind: head.kind, target: current.seq });
    }
    if (records.length >= doc.journal.length) return 0;
    this.remove(doc.journal.map((c) => `journal/${id}/${seqKey(c.seq)}`));
    for (const c of records) this.write(`journal/${id}/${seqKey(c.seq)}`, c);
    const dropped = doc.journal.length - records.length;
    doc.journal = records;
    doc.timeline = null;
    return dropped;
  }

  /** Remove every blob no journal record and no snapshot names; how many. */
  collect(id: string): number {
    const doc = this.doc(id);
    const used = new Set<string>();
    for (const c of [...doc.journal, ...doc.snapshots.values()]) {
      used.add(c.text);
      for (const sha of Object.values(c.assets)) used.add(sha);
    }
    const gone = [...doc.blobs.keys()].filter((sha) => !used.has(sha));
    for (const sha of gone) doc.blobs.delete(sha);
    this.remove(gone.map((sha) => `blob/${id}/${sha}`));
    return gone.length;
  }

  /** Every snapshot past each document's newest `keepSnapshots`, and history past `keepChanges`; one line per document pruned. */
  prune(keepSnapshots: number, keepChanges: number | null = null): string[] {
    const removed: string[] = [];
    for (const d of this.documents()) {
      const snaps = this.snapshots(d.id);
      const doc = this.doc(d.id);
      for (const snap of snaps.slice(0, Math.max(0, snaps.length - keepSnapshots))) {
        doc.snapshots.delete(snap.name);
        this.remove([`snapshot/${d.id}/${snap.name}`]);
        removed.push(`${d.name}: snapshot ${snap.name}`);
      }
      if (keepChanges === null) continue;
      const lines = this.compact(d.id, keepChanges);
      const files = this.collect(d.id);
      if (lines || files) removed.push(`${d.name}: ${lines} old history lines, ${files} unused files`);
    }
    return removed;
  }
}
