// The editor's state, in one place. `EditorStore` holds an `EditorState`
// and the actions that change it; a component reads the slice it needs
// through `useStore(selector)` and is rendered again only when that slice
// changes. The store also owns the two machines that talk to the worker:
// the outbox every change goes through (`outbox.ts` holds its pure rules:
// changes are sent one at a time, each against the version the one before
// produced, and a refusal drops what was queued behind it and says how
// many), and the frame fetch (one frame on its way at a time, a newer ask
// replacing the one waiting, the newest answer shown), with the YAML tab's
// save (`textsync.ts`: the whole text, debounced, against the version it
// was typed over). The selection's field tree (`inspect`) is asked for the
// editing context -- the element, the viewed device, the frame and the
// style -- and asked again whenever one of those changes. Per-browser
// preferences (`view`, `ui`) are read once from `localStorage` and written
// back through `persist()`; a face's editor-only state (`faceState`: the
// elements locked and hidden in the editor) lives beside the face in the
// worker's store, and the frame is asked without the hidden ones.

import { createContext } from "preact";
import { useContext, useEffect, useRef, useState } from "preact/hooks";
import type {
  Answer, Args, AssetArgs, DeviceInfo, Dragged, EditOp, FaceUiState, Frame, FrameArgs, Gesture, Inspect, InspectArgs, Op, Path, Scope, Skin, Structured,
  StructureOp, Summary, TreeNode, Value, VersionArgs, Vocabulary,
} from "../src/studio/protocol.ts";
import { api, call, listen } from "./api.ts";
import { AssistSession } from "./assist-session.ts";
import type { DiagnosticFilter } from "./diagnostics.ts";
import { rangeIds, selectAll as allShown } from "./hit.ts";
import { droppedError, enqueue, inFlight, mark, newer, next, saveState } from "./outbox.ts";
import type { AnyGesture, Entry, Failure, GestureEntry, Where } from "./outbox.ts";
import { nodeAtPath, nodeById } from "./tree.ts";
import { TAB } from "./session.ts";
import * as sync from "./textsync.ts";
import type { PlanKind, SyncState } from "./textsync.ts";
import { lintSteps, picksParam } from "./values.ts";
import { CSS_PX_PER_INCH, clampZoom, realZoom, serverScale } from "./zoom.ts";

// -- the state ----------------------------------------------------------------------------

/** How a click selects: alone, a Shift range in the layers, or toggled into the selection. */
export type SelectMode = "range" | boolean;

/**
 * What is selected: `primary` an element's id, or a hand's or a part's tree
 * path joined with "/" (`tree.ts`'s `selectionId`), `extra` more elements,
 * and `vertex` the point of a polygon (element or part) picked on the face
 * or in Properties, which Delete removes.
 */
export interface Selection {
  primary: string | null;
  /** More elements selected with Ctrl/Cmd (or Shift on the face), for moving, deleting or grouping together. */
  extra: string[];
  vertex: number | null;
}

/** Which frame the preview draws: awake, asleep (MIP) or AOD (AMOLED), one at a time. */
export type FrameMode = "awake" | "asleep" | "aod";

/** The editing context: what the face is drawn as, which frame Properties edits, and where a geometry edit is written. */
export interface Context {
  device: string | null;
  style: string;
  frame: FrameMode;
  /** `HH:MM:SS`, or empty for the sample moment. */
  time: string;
  /** `YYYY-MM-DD`, or empty for the sample day. */
  date: string;
  /** Drawn at this computer's time and date, as it goes on. */
  now: boolean;
  /** What each slot is drawn showing, by slot name. */
  picks: Record<string, string>;
  /** Edit for: where a Properties edit or a drag writes `at:`, `size:`, `radius:` or `align:`: "all" the element's own key (a drag then goes where the viewed device reads it), else its override for the device, its shape or its display class. */
  target: Scope;
  /** The hands, pattern or needle element entered (its tree path): the canvas then shows its parts in its own frame; null outside any. */
  entered: Path | null;
}

export interface Panels {
  left: number;
  right: number;
}

/** How the face is shown: this browser's preferences. */
export interface View {
  /** CSS pixels per watch pixel. */
  zoom: number;
  /** The watch's real size, whatever the zoom. */
  real: boolean;
  skin: boolean;
  /** How many CSS pixels make a real inch on this screen. */
  pxPerInch: number;
  panels: Panels;
}

/** Which of the right column's two sections are folded. */
export interface Fold {
  props: boolean;
  lower: boolean;
}

export type Dialog = "build" | "calibrate" | "keys" | "help" | "assist" | null;

export interface Ui {
  leftTab: "layers" | "face";
  /** The Face tab's open section, remembered by this browser. */
  faceSection: string;
  pane: "face" | "yaml";
  reportsTab: "diagnostics" | "history";
  /** The Diagnostics tab's severity filter, kept across tabs, reset per face. */
  diagFilter: DiagnosticFilter;
  folds: Fold;
  dialog: Dialog;
  /** Ctrl+K's palette is open. */
  palette: boolean;
}

/** The outbox: the changes on their way to the worker, and the newest version known, for the next send. */
export interface Pending {
  queue: Entry[];
  latest: number | null;
}

/** Why the YAML tab's text is not saved: not YAML, or the request failed. */
export type Status = { kind: "invalid" | "failed"; message: string } | null;

/** Lines the YAML tab is asked to select, from a link elsewhere; `at` tells a new ask from the last. */
export interface Reveal {
  line: number;
  end?: number | null | undefined;
  at: number;
}

/** The YAML tab's text and whether the worker has it. */
export interface YamlState {
  sync: SyncState;
  /** The pane's text: what the author typed last, or the face's text while nothing is unsent. */
  text: string;
  status: Status;
  /** A send was refused as stale: the text waits for the author's choice. */
  conflict: boolean;
  /** A send is out. */
  sending: boolean;
  reveal: Reveal | null;
}

export interface FrameState {
  current: Frame | null;
  /** A frame is on its way. */
  busy: boolean;
  skin: Skin | null;
}

export type MessageKind = "error" | "notice";

/** A message shown, and when. */
export interface Message {
  message: string;
  kind: MessageKind;
  at: number;
}

export interface Messages {
  /** Newest first. */
  log: Message[];
  /** How many of the newest the author has not opened the list for. */
  unseen: number;
  /** The one shown now. */
  toast: Message | null;
}

/** A time and a date, as the time and date inputs write them. */
export interface Clock {
  time: string;
  date: string;
}

export interface EditorState {
  docId: string | null;
  /** The face as the worker last answered. */
  doc: Summary | null;
  /** The face was deleted in another tab: editing it can no longer be saved. */
  gone: boolean;
  vocab: Vocabulary | null;
  devices: DeviceInfo[];
  selection: Selection;
  context: Context;
  /** The selected element's field tree for the context, as the worker last answered; null while nothing is selected or the answer is on its way. */
  inspect: Inspect | null;
  view: View;
  ui: Ui;
  pending: Pending;
  yaml: YamlState;
  frame: FrameState;
  /** This computer's clock, as the frame follows it. */
  clock: Clock;
  messages: Messages;
  /** Each face's editor-only state, by id, once read. */
  faceState: Record<string, FaceUiState>;
}

/** Where the YAML pane was when the tab closed: its scroll and cursor, kept per face while the editor is open. */
export interface YamlPlace {
  top: number;
  into: number;
  anchor: [line: number, col: number];
  head: [line: number, col: number];
  selected: string | null;
  at: number;
}

/** The operations a queued change may be: every one answers with the face (a `Summary`, or a `Structured` with what to select). */
export type ChangeOp = { [O in Op]: Answer<O> extends Summary ? O : never }[Op];

/** A change as `send` takes it: the operation, its arguments (the face's id and version are added) and a file's bytes. */
export interface Change<O extends ChangeOp = ChangeOp> {
  op: O;
  args?: Record<string, unknown>;
  body?: Blob | Uint8Array | null;
}

/** What the canvas draws a gesture from while it is on its way: the dragged item, every element it moves and the preview. */
export type Shown = Pick<GestureEntry, "item" | "moving" | "preview">;

/** How long typing in the YAML tab rests before it is sent. */
export const TEXT_DEBOUNCE_MS = 300;
const PANEL_MIN = 180;
const PANEL_MAX = 720;
export const PANEL_DEFAULTS: Panels = { left: 280, right: 340 };
export const clampPanel = (w: number): number => Math.round(Math.min(PANEL_MAX, Math.max(PANEL_MIN, w)));

// -- helpers ------------------------------------------------------------------------------

// This computer's time and date, as the time and date inputs write them.
export function clockNow(): Clock {
  const d = new Date();
  const two = (n: number): string => String(n).padStart(2, "0");
  return { time: `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`,
           date: `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}` };
}

// An error's message, or the error shown as text: `api` throws Errors, but anything can be thrown.
export const messageOf = (e: unknown): string => (e instanceof Error && e.message) || String(e);

// The status a refusal was thrown with (`api`), or undefined for any other error.
export const statusOf = (e: unknown): number | undefined =>
  typeof e === "object" && e !== null && "status" in e && typeof e.status === "number" ? e.status : undefined;

// An error as `api` throws one (its status kept); anything else thrown, as one.
const failure = (e: unknown): Failure => (e instanceof Error ? e : new Error(String(e)));

const isGesture = (entry: Entry): entry is GestureEntry => entry.gesture !== undefined;
const isDragged = (face: Summary): face is Dragged => "landed" in face;

export function route(): string | null {
  const m = location.hash.match(/^#\/face\/([0-9a-f]{32})$/);
  return m ? m[1] ?? null : null;
}

/** Open a face, or the home screen with null; the hash change then opens it in the store. */
export function go(docId: string | null): void {
  location.hash = docId ? `#/face/${docId}` : "#/";
}

// What this browser remembers between visits, read back; a missing or
// unreadable value is the fallback.
function stored(key: string, fallback: number): number {
  try { const v = Number(localStorage.getItem(key)); return v > 0 ? v : fallback; } catch (_) { return fallback; }
}

function storedView(): View {
  return { zoom: clampZoom(stored("wfb-zoom", 2)), real: false, skin: stored("wfb-skin", 0) === 1,
           pxPerInch: stored("wfb-css-px-per-inch", CSS_PX_PER_INCH),
           panels: { left: clampPanel(stored("wfb-panel-left", PANEL_DEFAULTS.left)), right: clampPanel(stored("wfb-panel-right", PANEL_DEFAULTS.right)) } };
}

function storedUi(): Ui {
  let faceSection = "targets", folds: Fold = { props: false, lower: false };
  try { faceSection = localStorage.getItem("wfb-face-section") || "targets"; } catch (_) { /* private mode */ }
  try { folds = { ...folds, ...(JSON.parse(localStorage.getItem("wfb-fold") || "{}") as Partial<Fold>) }; } catch (_) { /* private mode */ }
  return { leftTab: "layers", faceSection, pane: "face", reportsTab: "diagnostics", diagFilter: "all", folds, dialog: null, palette: false };
}

const NO_SELECTION: Selection = { primary: null, extra: [], vertex: null };
const samePath = (a: Path | null, b: Path | null): boolean => a !== null && b !== null && a.length === b.length && a.every((step, i) => step === b[i]);
/** Whether a selection id names a hand or a part (a tree path joined with "/"), not an element. */
const isPartId = (id: string): boolean => id.includes("/");
const freshYaml = (): YamlState =>
  ({ sync: sync.initial({ text: "", version: 0 }), text: "", status: null, conflict: false, sending: false, reveal: null });

// -- derived values, for selectors --------------------------------------------------------------

export const deviceInfoOf = (s: EditorState): DeviceInfo | undefined => s.devices.find((d) => d.id === s.context.device);
/** Whether the watch's low-power frame is AOD (AMOLED) rather than asleep. */
export const isAmoled = (info: DeviceInfo | null | undefined): boolean =>
  !!info && ["amoled", "oled"].includes(String(info.display).toLowerCase());
/** The zoom that shows the viewed watch at its real size, or null when its files give no pixel density. */
export const realZoomOf = (s: EditorState): number | null => { const info = deviceInfoOf(s); return info ? realZoom(info.ppi, s.view.pxPerInch) : null; };
/** The zoom shown: 1:1 stays on from watch to watch, each at its own real size; off, the zoom set before. */
export const zoomOf = (s: EditorState): number => { const real = realZoomOf(s); return s.view.real && real !== null ? real : s.view.zoom; };
/** The whole scale the worker draws at: the zoom in device pixels, rounded up. */
export const scaleOf = (s: EditorState): number =>
  serverScale(zoomOf(s), typeof devicePixelRatio === "number" && devicePixelRatio > 0 ? devicePixelRatio : 1);
/** The time and date the frame is drawn at: the clock's when following it, else the context's. */
export const shownTime = (s: EditorState): string => (s.context.now ? s.clock.time : s.context.time);
export const shownDate = (s: EditorState): string => (s.context.now ? s.clock.date : s.context.date);
/** Every selected element, the primary first. */
export const chosenIds = (sel: Selection): string[] => (sel.primary ? [sel.primary, ...sel.extra] : sel.extra);
/** The selected node in the tree (an element, a hand or a part), or null. */
export const elementOf = (s: EditorState): TreeNode | null => (s.doc && s.selection.primary ? nodeById(s.doc.tree, s.selection.primary) : null);
/** The entered element's node, or null. */
export const enteredOf = (s: EditorState): TreeNode | null => (s.doc && s.context.entered ? nodeAtPath(s.doc.tree, s.context.entered) : null);
const NONE: readonly string[] = Object.freeze([]);
/** The open face's editor-only state, or an empty one. */
const faceUi = (s: EditorState): FaceUiState => (s.docId !== null ? s.faceState[s.docId] : undefined) ?? {};
/** The elements locked in the editor (by id, as the author locked them): the canvas neither picks nor drags them. */
export const lockedOf = (s: EditorState): readonly string[] => faceUi(s).locked ?? NONE;
/** The elements hidden in the editor's frame (by id, as the author hid them). */
export const hiddenOf = (s: EditorState): readonly string[] => faceUi(s).hidden ?? NONE;
/** Whether the YAML tab's text is saved: `textsync.plan`'s kind, "send" while a send is out. */
export const yamlSaving = (s: EditorState): PlanKind => (s.yaml.sending ? "send" : sync.plan(s.yaml.sync, s.yaml.text).kind);
/** The top bar's saved state: the outbox and the YAML tab together. */
export const savedState = (s: EditorState): "unsaved" | "saving" | "saved" => saveState({ queue: s.pending.queue, yaml: yamlSaving(s) });

// -- the store ---------------------------------------------------------------------------------

type Timer = ReturnType<typeof setTimeout>;

export class EditorStore {
  state: EditorState;
  /** The Assist chat: the page's, outliving the dialog that shows it. */
  readonly assist = new AssistSession({ doc: () => this.state.doc, device: () => this.state.context.device, accept: (d) => this.accept(d) });
  /** Where the YAML pane was, per face, while the editor is open. */
  readonly yamlPlaces = new Map<string, YamlPlace>();
  private readonly listeners = new Set<() => void>();
  // Counts the faces opened: an answer that arrives for an earlier one is dropped.
  private epoch = 0;
  private unlisten: (() => void) | null = null;
  private textTimer: Timer | null = null;
  private clockTimer: Timer | null = null;
  private toastTimer: Timer | null = null;
  // the frame: the ask last made (so the same picture is not asked twice), the ask not sent yet, and whether one is out
  private frameKey: string | null = null;
  private frameWaiting: { args: FrameArgs; epoch: number } | null = null;
  private frameSending = false;
  private skinKey: string | null = null;
  // the field tree: the ask last made, so the same tree is not asked for twice; only its answer is shown
  private inspectKey: string | null = null;

  constructor(docId: string | null = null) {
    this.state = {
      docId: null, doc: null, gone: false, vocab: null, devices: [], selection: NO_SELECTION,
      context: { device: null, style: "", frame: "awake", time: "", date: "", now: false, picks: {}, target: "all", entered: null },
      inspect: null, view: storedView(), ui: storedUi(), pending: { queue: [], latest: null }, yaml: freshYaml(),
      frame: { current: null, busy: false, skin: null }, clock: clockNow(), messages: { log: [], unseen: 0, toast: null }, faceState: {},
    };
    this.unlisten = listen((name, data) => this.onEvent(name, data));
    if (typeof addEventListener === "function") {
      // Leaving or reloading the page kills the worker with it: text waiting
      // out the debounce is sent at once, and while a change is on its way
      // the browser asks before leaving.
      addEventListener("pagehide", () => this.flushText());
      addEventListener("beforeunload", (e: BeforeUnloadEvent) => {
        this.flushText();
        if (!this.inFlight()) return;
        e.preventDefault();
        e.returnValue = "A change is still being saved.";
      });
    }
    if (docId !== null) this.open(docId);
  }

  /** `listener` is called after every change; the returned function stops it. */
  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  /** Stop the store's timers and its worker listener (tests). */
  dispose(): void {
    for (const t of [this.textTimer, this.clockTimer, this.toastTimer]) if (t !== null) clearTimeout(t);
    this.textTimer = this.clockTimer = this.toastTimer = null;
    if (this.unlisten) this.unlisten();
    this.unlisten = null;
  }

  private set(patch: Partial<EditorState>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of [...this.listeners]) listener();
  }

  // -- the face --

  /** Show the face `docId`, or the home screen with null: the state of the face before is dropped, the preferences kept. */
  open(docId: string | null): void {
    if (docId === this.state.docId) return;
    this.epoch++;
    this.assist.follow(docId);
    if (this.textTimer !== null) { clearTimeout(this.textTimer); this.textTimer = null; }
    this.frameWaiting = null;
    this.frameKey = null;
    this.inspectKey = null;
    this.set({ docId, doc: null, gone: false, selection: NO_SELECTION, inspect: null, pending: { queue: [], latest: null }, yaml: freshYaml(),
               context: { ...this.state.context, entered: null },
               frame: { ...this.state.frame, current: null, busy: false }, ui: { ...this.state.ui, diagFilter: "all", dialog: null, palette: false } });
    if (docId === null) return;
    this.reload();
    if (this.state.vocab === null) {
      api("vocabulary").then((v) => { this.set({ vocab: v, devices: v.devices }); this.reconcile(); }, (e: unknown) => this.error(e));
    }
    api("ui_state", { id: docId, action: "get" }).then(
      (r) => {
        if (this.state.docId !== docId) return;
        this.set({ faceState: { ...this.state.faceState, [docId]: r.state } });
        // the frame leaves out what this face hides in the editor
        this.askFrame();
      },
      (e: unknown) => { if (this.state.docId === docId && statusOf(e) !== 404) this.error(e); });
  }

  close(): void {
    this.open(null);
  }

  /** Fetch the face again (after a stale refusal, another tab's change, a snapshot). */
  reload(): void {
    const docId = this.state.docId;
    if (docId === null) return;
    api("get", { id: docId }).then((d) => this.accept(d), (e: unknown) => {
      if (this.state.docId !== docId) return;
      this.error(e);
      if (statusOf(e) === 404) go(null);
    });
  }

  /**
   * A face from the worker, shown unless it is older than the one shown
   * (`outbox.newer`): answers can arrive out of order. An answer about
   * another face (one left while its change was on its way) is dropped.
   */
  accept(d: Summary): void {
    const s = this.state;
    if (d.id !== s.docId || !newer(s.doc, d)) return;
    this.set({ doc: d, pending: { ...s.pending, latest: d.version } });
    this.followText(d);
    this.reconcile();
    void this.pump();
  }

  private onEvent(name: string, data: { id?: string; version?: number; tab?: string | null; name?: string; message?: string }): void {
    const s = this.state;
    if (name === "error" && (!data.id || data.id === s.docId)) this.error(new Error(data.message ?? "the editor's worker failed"));
    if (!s.doc || data.id !== s.docId) return;
    if (name === "deleted") this.set({ gone: true });
    else if (name === "renamed") { if (data.name !== undefined) this.set({ doc: { ...s.doc, name: data.name } }); }
    // this tab's own change reaches it with the answer to its request
    else if ((name === "changed" && data.tab !== TAB && data.version !== undefined && data.version > s.doc.version) || name === "snapshot") this.reload();
  }

  // The device defaults to the first target, and is kept while it stays
  // one; another watch's own low-power frame stands for the one shown,
  // asleep for AOD and back. Then the frame and the skin follow.
  private reconcile(): void {
    const s = this.state;
    let ctx = s.context;
    if (s.doc && (!ctx.device || !s.doc.targets.includes(ctx.device)) && s.doc.targets.length) ctx = { ...ctx, device: s.doc.targets[0] ?? null };
    // a style picked on another face is dropped when this one has no entry of that name: the frame could never render it
    if (s.doc && ctx.style && !s.doc.globals.styles.entries.some((e) => e.name === ctx.style)) ctx = { ...ctx, style: "" };
    // an element entered that the face no longer has (undone, deleted, retyped) cannot be drawn: the context leaves it
    if (s.doc && ctx.entered !== null) {
      const node = nodeAtPath(s.doc.tree, ctx.entered);
      if (!node || node.kind !== "element" || !node.children.some((c) => c.kind === "hand" || c.kind === "part")) ctx = { ...ctx, entered: null };
    }
    const info = s.devices.find((d) => d.id === ctx.device);
    if (info) {
      const amoled = isAmoled(info);
      if (ctx.frame === "asleep" && amoled) ctx = { ...ctx, frame: "aod" };
      else if (ctx.frame === "aod" && !amoled) ctx = { ...ctx, frame: "asleep" };
    }
    if (ctx !== s.context) this.set({ context: ctx });
    this.askFrame();
    this.askSkin();
    this.askInspect();
  }

  // -- selection --

  /**
   * `mode`: falsy selects `id` alone; "range" (Shift in the layers) selects
   * every element from the selection to it; anything else toggles it in
   * the selection. A hand or a part (its tree path joined with "/") is
   * selected alone, inside its element: `owner`, the element it was
   * clicked under in Layers, is entered first when it is not the entered
   * one; on the face, the entered element is its owner. An element outside
   * the entered one leaves it.
   */
  select(id: string | null, mode?: SelectMode, owner?: Path): void {
    const s = this.state;
    const { primary, extra } = s.selection;
    const entered = s.context.entered;
    let ctx = s.context;
    if (id !== null && isPartId(id)) {
      const into = owner ?? entered;
      if (into !== null && !samePath(into, entered)) ctx = { ...ctx, entered: into };
      mode = false;
    } else if (id !== null && entered !== null && s.doc) {
      const node = nodeAtPath(s.doc.tree, entered);
      if (!node || node.id !== id) ctx = { ...ctx, entered: null };
    }
    if (mode === "range" && primary && s.doc) {
      const ids = id === null ? [] : rangeIds(s.doc.tree, primary, id);
      const first = ids.includes(primary) ? primary : ids[0];
      this.set({ selection: { primary: first || null, extra: ids.filter((x) => x !== first), vertex: null } });
    } else if (mode && primary && id !== null && id !== primary) {
      this.set({ selection: { primary, extra: extra.includes(id) ? extra.filter((x) => x !== id) : [...extra, id], vertex: null } });
    } else if (id !== primary || extra.length) {
      this.set({ selection: { primary: id, extra: [], vertex: null } });
    }
    if (ctx !== s.context) { this.set({ context: ctx }); this.reconcile(); }
    this.askInspect();
  }

  /** The point `index` of the selected polygon (an element or a part) is picked, or none with null. */
  selectVertex(index: number | null): void {
    if (this.state.selection.vertex !== index) this.set({ selection: { ...this.state.selection, vertex: index } });
  }

  /**
   * Enter the hands, pattern or needle element at `path`: the frame becomes
   * its parts' (`Frame.local`), Layers marks it, and a selection outside it
   * is dropped for the element itself.
   */
  enter(path: Path): void {
    const s = this.state;
    if (samePath(s.context.entered, path)) return;
    const node = s.doc ? nodeAtPath(s.doc.tree, path) : null;
    const primary = s.selection.primary;
    if (node && primary !== null && !isPartId(primary) && primary !== node.id) this.set({ selection: { primary: node.id, extra: [], vertex: null } });
    else if (primary !== null && isPartId(primary) && !primary.startsWith(path.join("/"))) this.set({ selection: { primary: node ? node.id : null, extra: [], vertex: null } });
    this.setContext({ entered: path });
    this.askInspect();
  }

  /** Leave the entered element: the frame is the face's again, and a part or hand that was selected gives way to the element. */
  leave(): void {
    const s = this.state;
    if (s.context.entered === null) return;
    const node = enteredOf(s);
    const primary = s.selection.primary;
    if (primary !== null && isPartId(primary)) this.set({ selection: { primary: node ? node.id : null, extra: [], vertex: null } });
    else if (s.selection.vertex !== null) this.set({ selection: { ...s.selection, vertex: null } });
    this.setContext({ entered: null });
    this.askInspect();
  }

  /** Everything the frame shows, a group standing for its children; false while there is no frame. */
  selectAll(): boolean {
    const { doc, frame } = this.state;
    if (!doc || !frame.current) return false;
    const ids = allShown(doc.tree, new Set(frame.current.items.map((i) => i.id)));
    this.set({ selection: { primary: ids[0] || null, extra: ids.slice(1), vertex: null } });
    this.askInspect();
    return true;
  }

  deselect(): void {
    if (this.state.selection !== NO_SELECTION) this.set({ selection: NO_SELECTION });
    this.askInspect();
  }

  // -- the outbox --

  private commit(queue: Entry[]): void {
    this.set({ pending: { ...this.state.pending, queue } });
  }

  private post(entry: Entry, docId: string, version: number): Promise<Summary> {
    if (isGesture(entry)) {
      const which = entry.ids.length > 1 ? { elements: entry.ids } : { element: entry.ids[0]! };
      // a gesture is always made on a viewed device; without one the worker refuses it
      const { device = "", ...where } = entry.where;
      return api("drag", { id: docId, version, device, ...where, ...which, gesture: entry.gesture });
    }
    const { op, args = {}, body = null } = entry.request;
    // the queue's request carries loose arguments (`outbox.ts`): the worker
    // checks them, and every change the editor queues answers with the face
    return api(op, { ...args, id: docId, version } as Args<Op>, body) as Promise<Summary>;
  }

  // Send the next queued change, if none is out, against the newest
  // version known; its answer is the face. A refusal drops what was queued
  // behind it: that was aimed at a face that did not happen, and the message
  // says how much that was.
  private async pump(): Promise<void> {
    const { queue, latest } = this.state.pending;
    const docId = this.state.docId;
    const entry = next(queue);
    if (!entry || latest === null || docId === null) return;
    this.commit(mark(queue, entry, "sent"));
    try {
      const updated = await this.post(entry, docId, latest);
      // the editor moved to another face meanwhile: its queue and version are that face's now
      if (this.state.docId !== docId) { if (entry.resolve) entry.resolve(null); return; }
      const q = this.state.pending.queue;
      this.set({ pending: { latest: updated.version, queue: mark(q, q.find((e) => e.state === "sent"), "done", updated.version) } });
      this.accept(updated);
      if (isGesture(entry) && isDragged(updated) && !updated.landed) {
        this.notice(`${updated.what}: written as close as its units allow, not exactly on the pixel`);
      }
      if (entry.resolve) entry.resolve(updated);
      void this.pump();
    } catch (e) {
      if (this.state.docId !== docId) { if (entry.resolve) entry.resolve(null); return; }
      const q = this.state.pending.queue;
      const dropped = q.filter((x) => x.state !== "done");
      this.commit(q.filter((x) => x.state === "done"));
      for (const x of dropped) if (x.resolve) x.resolve(null);
      const error = failure(e);
      this.error(droppedError(error, dropped.length - 1));
      if (error.status === 409) this.reload();
    }
  }

  /** Any change but a gesture: `{op, args, body}` (the face's id and version are added); the face it produced, or null when refused. */
  send<O extends ChangeOp>(request: Change<O>): Promise<Answer<O> | null> {
    return new Promise((resolve) => {
      // the queue types every answer as the face; this one is the operation's own
      this.commit(enqueue(this.state.pending.queue, { request, resolve: resolve as (answer: Summary | null) => void }));
      void this.pump();
    });
  }

  /** A gesture from the canvas or the arrow keys on `ids`, drawn from `shown` until its frame arrives; inside an entered element it carries the frame's time, so a hand part's delta turns by the angle shown. */
  drag(ids: string[], gesture: AnyGesture, shown: Shown): void {
    const s = this.state;
    const { device, target, entered } = s.context;
    const where: Where = { ...(device !== null ? { device } : {}), scope: target === "all" ? "auto" : target, ...(entered !== null ? { time: shownTime(s) } : {}) };
    this.commit(enqueue(this.state.pending.queue, { ids, gesture, ...shown, where }));
    void this.pump();
  }

  /** `ids` moved together by (`dx`, `dy`) device pixels. */
  moveAll(ids: string[], dx: number, dy: number, shown: Omit<Shown, "preview">): void {
    const gesture: Gesture = { kind: "move", part: "both", dx, dy };
    this.drag(ids, gesture, { ...shown, preview: gesture });
  }

  /** One edit from the inspector or the Face panel: the worker patches the text, checks it and answers with the face; a refusal says why. */
  edit(op: EditOp): Promise<Summary | null> {
    return this.send({ op: "edit", args: { edit: op } });
  }

  /** One structural edit from the Layers panel: the worker answers with the face and what to select. */
  async structure(op: StructureOp): Promise<void> {
    const updated = await this.send({ op: "structure", args: { edit: op } });
    if (!updated) return;
    const select = (updated as Structured).select;
    if (op.op === "delete") this.set({ selection: NO_SELECTION });
    else this.set({ selection: { primary: select ?? this.state.selection.primary, extra: [], vertex: null } });
    this.askInspect();
  }

  /** Several edits as one change, under `label`. */
  async batch(label: string, edits: (EditOp | StructureOp)[]): Promise<void> {
    const updated = await this.send({ op: "batch", args: { label, edits } });
    if (!updated) return;
    const select = (updated as Structured).select;
    if (select) this.set({ selection: { primary: select, extra: [], vertex: null } });
    this.askInspect();
  }

  undo(): Promise<Summary | null> {
    return this.send({ op: "undo" });
  }

  redo(): Promise<Summary | null> {
    return this.send({ op: "redo" });
  }

  /** Back or forward to the change `seq` in one step. */
  goto(seq: number): Promise<Summary | null> {
    return this.send({ op: "goto", args: { seq } });
  }

  restore(snapshot: string): Promise<Summary | null> {
    return this.send({ op: "restore", args: { snapshot } });
  }

  /** A font file added to the bundle: declared as the font `font` at `size`, or pointed at by every font whose `source:` is `reference`. */
  upload(file: File, { font, size, reference }: Partial<Pick<AssetArgs, "font" | "size" | "reference">>): Promise<Summary | null> {
    const args: Omit<AssetArgs, keyof VersionArgs> = { filename: file.name };
    if (font) { args.font = font; args.size = size || "10%r"; }
    if (reference) args.reference = reference;
    return this.send({ op: "assets", args, body: file });
  }

  /** Rename the face; not a change in its history. */
  async rename(name: string): Promise<void> {
    const docId = this.state.docId;
    if (docId === null) return;
    try {
      const r = await api("rename", { id: docId, name });
      const doc = this.state.doc;
      if (doc && doc.id === docId) this.set({ doc: { ...doc, name: r.name } });
    } catch (e) { this.error(e); }
  }

  /** Whether leaving the page now would lose a change. */
  inFlight(): boolean {
    return inFlight({ queue: this.state.pending.queue, yaml: yamlSaving(this.state) });
  }

  // -- the frame --

  private askFrame(): void {
    const s = this.state;
    const { doc, context } = s;
    if (!doc || !context.device || !doc.targets.includes(context.device)) {
      this.frameWaiting = null;
      this.frameKey = null;
      if (s.frame.current || s.frame.busy) this.set({ frame: { ...s.frame, current: null, busy: false } });
      return;
    }
    const args: FrameArgs = { id: doc.id, device: context.device, scale: scaleOf(s), style: context.style, time: shownTime(s), date: shownDate(s),
                              asleep: context.frame === "asleep", aod: context.frame === "aod", picks: picksParam(context.picks, doc.globals.slots),
                              ...(context.entered !== null ? { enter: context.entered } : {}),
                              ...(hiddenOf(s).length ? { hidden: [...hiddenOf(s)] } : {}) };
    const key = `${doc.version}\0${JSON.stringify(args)}`;
    if (key === this.frameKey) return;
    this.frameKey = key;
    this.frameWaiting = { args, epoch: this.epoch };
    if (!s.frame.busy) this.set({ frame: { ...s.frame, busy: true } });
    void this.pumpFrame();
  }

  // One frame on its way at a time: the worker draws in turn with the
  // face's edits, so a zoom drag or a run of time steps must not queue a
  // frame per step. A newer ask replaces the one waiting, and only the
  // newest ask's answer is shown.
  private async pumpFrame(): Promise<void> {
    if (this.frameSending || this.frameWaiting === null) return;
    const { args, epoch } = this.frameWaiting;
    this.frameWaiting = null;
    this.frameSending = true;
    try {
      const f = await api("frame", args);
      if (epoch === this.epoch && this.frameWaiting === null) {
        // a frame showing a gesture's version retires it
        const queue = this.state.pending.queue.filter((e) => !(e.state === "done" && (e.done ?? 0) <= f.version));
        this.set({ frame: { ...this.state.frame, current: f }, pending: { ...this.state.pending, queue } });
      }
    } catch (e) {
      if (epoch === this.epoch && this.frameWaiting === null) {
        this.error(e);
        // an entered element this frame cannot draw (not placed on this watch, in this style) is left, so the face shows again
        if (args.enter !== undefined && samePath(this.state.context.entered, args.enter)) this.leave();
      }
    } finally {
      this.frameSending = false;
      if (this.frameWaiting !== null) void this.pumpFrame();
      else {
        if (this.state.frame.busy) this.set({ frame: { ...this.state.frame, busy: false } });
        this.scheduleClock();
      }
    }
  }

  // The selected element's field tree, for the editing context: asked
  // once per element, version, device, frame and style, and only the ask
  // last made is shown, since answers can arrive out of order. Another
  // element selected drops the tree shown, so a stale one is never read as
  // the new selection's.
  private askInspect(): void {
    const s = this.state;
    const node = elementOf(s);
    if (!s.doc || !node) {
      this.inspectKey = null;
      if (s.inspect) this.set({ inspect: null });
      return;
    }
    const args: InspectArgs = { id: s.doc.id, element: node.path, device: s.context.device || "", frame: s.context.frame, style: s.context.style };
    const key = `${s.doc.version}\0${JSON.stringify(args)}`;
    if (key === this.inspectKey) return;
    this.inspectKey = key;
    if (s.inspect && s.inspect.element.join("\0") !== node.path.join("\0")) this.set({ inspect: null });
    const epoch = this.epoch;
    api("inspect", args).then(
      (ins) => { if (epoch === this.epoch && this.inspectKey === key) this.set({ inspect: ins }); },
      (e: unknown) => { if (epoch === this.epoch && this.inspectKey === key) this.error(e); });
  }

  // The watch's skin round the screen, when asked for and the device has one.
  private askSkin(): void {
    const s = this.state;
    const info = deviceInfoOf(s);
    if (!s.view.skin || !info || !info.skin) {
      this.skinKey = null;
      if (s.frame.skin) this.set({ frame: { ...s.frame, skin: null } });
      return;
    }
    const scale = scaleOf(s);
    const key = `${info.id}\0${scale}`;
    if (key === this.skinKey) return;
    this.skinKey = key;
    api("skin", { device: info.id, scale }).then(
      (skin) => { if (this.skinKey === key) this.set({ frame: { ...this.state.frame, skin } }); },
      (e: unknown) => this.error(e));
  }

  // With `now`, the clock moves on a second after each frame arrives, so a
  // slow frame is never queued behind.
  private scheduleClock(): void {
    if (this.clockTimer !== null) { clearTimeout(this.clockTimer); this.clockTimer = null; }
    if (!this.state.context.now || this.state.frame.busy) return;
    this.clockTimer = setTimeout(() => {
      this.clockTimer = null;
      this.set({ clock: clockNow() });
      this.askFrame();
      if (!this.state.frame.busy) this.scheduleClock();
    }, 1000 - (Date.now() % 1000) + 5);
  }

  // -- the context, the view and the ui --

  /** The editing context: the frame and the strip follow it. */
  setContext(partial: Partial<Context>): void {
    const was = this.state.context;
    let ctx: Context = { ...was, ...partial };
    let clock = this.state.clock;
    if (ctx.now && !was.now) clock = clockNow();
    // switched off, the face stays at the moment it last drew
    else if (!ctx.now && was.now && partial.time === undefined && partial.date === undefined) ctx = { ...ctx, time: clock.time, date: clock.date };
    this.set({ context: ctx, clock });
    this.reconcile();
    if (ctx.now && !was.now) this.scheduleClock();
  }

  /** This browser's preferences for showing the face; kept between visits. */
  setView(partial: Partial<View>): void {
    this.set({ view: { ...this.state.view, ...partial } });
    this.persist();
    this.reconcile();
  }

  /** A zoom of its own turns 1:1 off; the slider's steps are hundredths. */
  setZoom(zoom: number): void {
    this.setView({ zoom: clampZoom(Math.round(zoom * 100) / 100), real: false });
  }

  toggleReal(): void {
    this.setView({ real: !this.state.view.real });
  }

  setUi(partial: Partial<Ui>): void {
    this.set({ ui: { ...this.state.ui, ...partial } });
    this.persist();
  }

  setFolded(which: keyof Fold, folded: boolean): void {
    this.setUi({ folds: { ...this.state.ui.folds, [which]: folded } });
  }

  /** Jump to a Face-tab section (Ctrl+K, a colour role in Properties), whether or not the Face tab is showing. */
  openFaceSection(key: string): void {
    this.setUi({ faceSection: key, leftTab: "face" });
  }

  /** Show lines `line` to `end` of the text in the YAML tab. */
  reveal(line: number, end?: number | null): void {
    this.set({ yaml: { ...this.state.yaml, reveal: { line, end, at: Date.now() } }, ui: { ...this.state.ui, pane: "yaml" } });
  }

  // Everything this browser remembers between visits, written together.
  private persist(): void {
    const { view, ui } = this.state;
    const write = (key: string, value: string): void => { try { localStorage.setItem(key, value); } catch (_) { /* private mode */ } };
    write("wfb-zoom", String(view.zoom));
    write("wfb-skin", view.skin ? "1" : "0");
    write("wfb-css-px-per-inch", String(view.pxPerInch));
    write("wfb-panel-left", String(view.panels.left));
    write("wfb-panel-right", String(view.panels.right));
    write("wfb-face-section", ui.faceSection);
    write("wfb-fold", JSON.stringify(ui.folds));
  }

  /** The element at `element`'s `lint:` as written, or null: what "accept here…" adds to. */
  async lintOf(element: Path): Promise<Value | null> {
    const doc = this.state.doc;
    if (!doc) return null;
    const ins = await api("inspect", { id: doc.id, element });
    const field = ins.fields.find((f) => f.key === "lint");
    return field && field.present ? field.value : null;
  }

  /** Accept the lint `code` on the element at `element` with `reason`, over its `lint:` as written, as one change. */
  acceptLint(element: Path, code: string, reason: string, written: Value | null): Promise<void> {
    const steps = lintSteps(element, code, reason, written);
    const id = String(element[element.length - 1]);
    return steps.length ? this.batch(`accept ${code} on ${id}`, steps) : Promise.resolve();
  }

  /** Lock the element `id` in the editor, or unlock it: a locked one is not picked or dragged on the canvas; Layers and Properties still reach it. */
  toggleLocked(id: string): void {
    const locked = lockedOf(this.state);
    this.setFaceState({ locked: locked.includes(id) ? locked.filter((x) => x !== id) : [...locked, id] });
  }

  /** Hide the element `id` in the editor's frame, or show it again; the face itself is not changed. */
  toggleHidden(id: string): void {
    const hidden = hiddenOf(this.state);
    this.setFaceState({ hidden: hidden.includes(id) ? hidden.filter((x) => x !== id) : [...hidden, id] });
    this.askFrame();
  }

  /** The open face's editor-only state, changed by `partial` and written beside the face. */
  setFaceState(partial: FaceUiState): void {
    const docId = this.state.docId;
    if (docId === null) return;
    const state: FaceUiState = { ...(this.state.faceState[docId] ?? {}), ...partial };
    this.set({ faceState: { ...this.state.faceState, [docId]: state } });
    api("ui_state", { id: docId, action: "set", state }).catch((e: unknown) => this.error(e));
  }

  // -- the YAML tab --

  private setYaml(patch: Partial<YamlState>): void {
    this.set({ yaml: { ...this.state.yaml, ...patch } });
  }

  /** The pane's text as the author typed it: sent once typing rests, against the version it was typed over. */
  replaceText(text: string): void {
    if (text === this.state.yaml.text) return;
    this.setYaml({ text });
    this.debounceText();
  }

  private debounceText(): void {
    if (this.textTimer !== null) clearTimeout(this.textTimer);
    this.textTimer = setTimeout(() => { this.textTimer = null; void this.sendText(); }, TEXT_DEBOUNCE_MS);
  }

  /** Text waiting out the debounce is sent now. */
  flushText(): void {
    if (this.textTimer === null) return;
    clearTimeout(this.textTimer);
    this.textTimer = null;
    void this.sendText();
  }

  // Send the pane's text, if it is to be sent. A change made elsewhere
  // meanwhile refuses the send (409), and the author chooses whose text to
  // keep (`yamlChoose`); text that is not YAML (400) is kept and not sent
  // again until it changes.
  private async sendText(): Promise<void> {
    const { docId, yaml } = this.state;
    const epoch = this.epoch;
    if (docId === null || yaml.sending) return;
    const step = sync.plan(yaml.sync, yaml.text);
    if (step.kind !== "send") { if (step.kind === "idle" && yaml.status) this.setYaml({ status: null }); return; }
    this.setYaml({ sending: true });
    let answered = false;
    try {
      const response = await call("text", { id: docId, version: step.version, text: step.text });
      if (epoch !== this.epoch) return;
      // the face, when the worker took the text; else why it did not
      const face: Summary | null = response.status === 200 ? response.json ?? null : null;
      const refusal = response.status === 200 ? null : response.json;
      answered = true;
      this.setYaml({ sync: sync.answered(this.state.yaml.sync, step.text, response.status, face ? face.version : null) });
      if (response.status === 200) {
        this.setYaml({ status: null });
        if (face) this.accept(face);
      } else if (response.status === 409) {
        // changed elsewhere since the pane's text was typed over: the text stays, and the author chooses
        this.setYaml({ conflict: true });
        const current = await api("get", { id: docId });
        if (epoch === this.epoch) this.accept(current);
      } else if (response.status === 400) {
        // not YAML yet: keep typing; nothing was recorded
        this.setYaml({ status: { kind: "invalid", message: (refusal && refusal.error) || "the text is not YAML" } });
      } else {
        this.setYaml({ status: { kind: "failed", message: (refusal && refusal.error) || `${response.status}` } });
      }
    } catch (e) {
      if (epoch !== this.epoch) return;
      if (!answered) this.setYaml({ sync: sync.failed(this.state.yaml.sync, step.text) });
      this.setYaml({ status: { kind: "failed", message: messageOf(e) } });
    } finally {
      if (epoch === this.epoch) {
        this.setYaml({ sending: false });
        // the author typed on meanwhile: send again once typing rests
        const y = this.state.yaml;
        if (sync.plan(y.sync, y.text).kind === "send" && this.textTimer === null) this.debounceText();
      }
    }
  }

  // A change made elsewhere (the canvas, the inspector, undo, another tab)
  // reaches the pane when the author has nothing unsent.
  private followText(doc: Summary): void {
    const y = this.state.yaml;
    const followed = sync.follow(y.sync, doc, y.text);
    if (followed.state !== y.sync || followed.replace !== null) this.setYaml({ sync: followed.state, text: followed.replace ?? y.text });
  }

  /** The pane opening: with nothing unsent, the face as it now is starts afresh, however it changed while the tab was closed. */
  yamlOpened(): void {
    const { doc, yaml } = this.state;
    if (!doc) return;
    if (sync.plan(yaml.sync, yaml.text).kind === "idle") this.setYaml({ sync: sync.initial(doc), text: doc.text, status: null });
  }

  /** Send the held text again, after a failure the author has seen. */
  yamlRetry(): void {
    this.setYaml({ sync: sync.retry(this.state.yaml.sync) });
    void this.sendText();
  }

  /** The author's choice after a refused send: "mine" sends the pane's text over the newer face, "theirs" shows the newer face. */
  yamlChoose(choice: "mine" | "theirs"): void {
    const { doc, yaml } = this.state;
    if (!doc) return;
    const chosen = sync.resolve(yaml.sync, doc, choice);
    this.setYaml({ sync: chosen.state, conflict: false, status: null, text: chosen.replace ?? yaml.text });
    if (chosen.replace === null) void this.sendText();
  }

  // -- messages --

  // A new message replaces the last, and gets its own full time.
  private show(message: string, kind: MessageKind): void {
    if (this.toastTimer !== null) clearTimeout(this.toastTimer);
    const m: Message = { message, kind, at: Date.now() };
    const { log, unseen } = this.state.messages;
    this.set({ messages: { log: [m, ...log].slice(0, 100), unseen: unseen + 1, toast: m } });
    this.toastTimer = setTimeout(() => {
      this.toastTimer = null;
      if (this.state.messages.toast === m) this.set({ messages: { ...this.state.messages, toast: null } });
    }, kind === "error" ? 6000 : 4000);
  }

  /** Shows an error (`api`'s refusal, or anything thrown) as a toast. */
  error(e: unknown): void {
    this.show(messageOf(e), "error");
  }

  notice(message: string): void {
    this.show(message, "notice");
  }

  dismissToast(): void {
    if (this.state.messages.toast) this.set({ messages: { ...this.state.messages, toast: null } });
  }

  /** The author opened the list: every message is seen. */
  seenMessages(): void {
    if (this.state.messages.unseen) this.set({ messages: { ...this.state.messages, unseen: 0 } });
  }

  clearMessages(): void {
    this.set({ messages: { log: [], unseen: 0, toast: null } });
  }
}

// -- reading the store from a component ----------------------------------------------------------

const StoreContext = createContext<EditorStore | null>(null);
export const StoreProvider = StoreContext.Provider;

/** The store in scope, for its actions. */
export function useEditorStore(): EditorStore {
  const store = useContext(StoreContext);
  if (store === null) throw new Error("no editor store in scope");
  return store;
}

/**
 * `selector(state)` now, and the component rendered again whenever its
 * value changes (by `Object.is`): select a slice the store replaces as a
 * whole, or a primitive, never a fresh object.
 */
export function useStore<T>(selector: (state: EditorState) => T): T {
  const store = useEditorStore();
  const [, rerender] = useState(0);
  const selected = selector(store.state);
  const latest = useRef({ selector, selected });
  latest.current = { selector, selected };
  useEffect(() => {
    const check = (): void => {
      const value = latest.current.selector(store.state);
      if (!Object.is(value, latest.current.selected)) {
        latest.current.selected = value;
        rerender((n) => n + 1);
      }
    };
    // a change between this render and the subscription
    check();
    return store.subscribe(check);
  }, [store]);
  return selected;
}
