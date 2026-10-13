// wfb studio's front end. The page asks and shows; its worker
// (`api.ts`) holds the face's text and runs the compiler, so nothing here
// decides what a face looks like: every image comes from the worker's
// renderer.

import { html } from "htm/preact";
import type { JSX, VNode } from "preact";
import { useState, useEffect, useRef, useCallback, useMemo } from "preact/hooks";
import type { Dispatch, StateUpdater } from "preact/hooks";
import { api, download, listen, saveBlob } from "./api.ts";
import { clockNow, useClipboard, useFold, useFrame, useOutbox, usePanZoom, useShortcuts } from "./hooks.ts";
import type { Fold, FrameState, Outbox, PanZoom } from "./hooks.ts";
import { flatten, movedBy, rangeIds, selectAll, together } from "./hit.ts";
import type { Box, Placed } from "./hit.ts";
import { AddName, InlineName, Popover, WorkerImage } from "./ui.ts";
import { inFlight, newer, saveState } from "./outbox.ts";
import type { Entry, Preview, RequestEntry, Where } from "./outbox.ts";
import { Canvas, Strip } from "./canvas.ts";
import { Layers } from "./layers.ts";
import { YamlPane } from "./yaml.ts";
import type { Reveal, YamlMemory } from "./yaml.ts";
import { AskHost, BuildDialog, CalibrateDialog, Modal, ask } from "./dialogs.ts";
import { HelpDialog } from "./help.ts";
import { SHORTCUTS } from "./keys.ts";
import { CSS_PX_PER_INCH, MAX_ZOOM, MIN_ZOOM, clampZoom, realZoom, screenMm, serverScale } from "./zoom.ts";
import { FacePanel, Inspector } from "./panels.ts";
import { severityCounts, typeLabel } from "./values.ts";
import { Diagnostics, diagnosticsLabel } from "./diagnostics.ts";
import { blocksOf, deleteOp, elementsYaml, siblingsOf, stepOp } from "./tree.ts";
import { TAB } from "./session.ts";
import { latestText } from "./textsync.ts";
import type { PlanKind } from "./textsync.ts";
import type {
  Answer, Args, AssetArgs, DeviceInfo, DownloadArgs, EditOp, EventFields, EventName, Frame, Gesture, History, HistorySnapshot,
  HistoryState, Home as HomeAnswer, LibraryEntry, Op, Path, Scope, Severity, Skin, SlotEntry, StructureOp, Structured, Summary,
  TreeBlock, TreeNode, Value, VersionArgs, Vocabulary,
} from "../src/studio/protocol.ts";

/** Shows an error (`api`'s refusal, or anything thrown) as a toast. */
export type OnError = (e: unknown) => void;
export type OnNotice = (message: string) => void;

/** A change for the outbox: the request as `api` takes it, the face's id and version added when sent; its answer, or null when refused. */
export type Send = Outbox["send"];

/** How a click selects: alone, a Shift range in the layers, or toggled into the selection. */
export type SelectMode = "range" | boolean;
export type OnSelect = (id: string | null, mode?: SelectMode) => void;

/** The Diagnostics tab's filter: every severity, or one. */
export type DiagFilter = "all" | Severity;

/** What the face is drawn at, and how it is shown. */
export interface View {
  device: string | null;
  style: string;
  time: string;
  date: string;
  /** Drawn at this computer's time and date, as it goes on. */
  now: boolean;
  asleep: boolean;
  aod: boolean;
  skin: boolean;
  zoom: number;
  /** The watch's real size, whatever the zoom. */
  real: boolean;
  /** What each slot is drawn showing, by slot name. */
  picks?: Record<string, string>;
}

type SetView = Dispatch<StateUpdater<View>>;

/** This computer's time and date, as the time and date inputs write them. */
interface Clock {
  time: string;
  date: string;
}

type Dialog = "build" | "calibrate" | "keys" | "help" | "palette";

// What this browser remembers between visits: the zoom, how many CSS
// pixels make a real inch on its screen, and the side panels' widths.
function stored(key: string, fallback: number): number {
  try { const v = Number(localStorage.getItem(key)); return v > 0 ? v : fallback; } catch (_) { return fallback; }
}
const storedZoom = (): number => clampZoom(stored("wfb-zoom", 2));
// the Face-tab section this browser last left open, or the first
const storedFaceSection = (): string => {
  try { return localStorage.getItem("wfb-face-section") || "targets"; } catch (_) { return "targets"; }
};
const storedSkin = (): boolean => stored("wfb-skin", 0) === 1;
const storedPxPerInch = (): number => stored("wfb-css-px-per-inch", CSS_PX_PER_INCH);
const PANEL_MIN = 180;
const PANEL_MAX = 720;
const clampPanel = (w: number): number => Math.round(Math.min(PANEL_MAX, Math.max(PANEL_MIN, w)));
interface Panels {
  left: number;
  right: number;
}
const storedPanels = (): Panels => ({ left: clampPanel(stored("wfb-panel-left", 280)),
                                      right: clampPanel(stored("wfb-panel-right", 340)) });

interface SplitterProps {
  width: number;
  /** +1 when the panel lies left of the edge. */
  sign: 1 | -1;
  fallback: number;
  /** `save`: the drag is over, so the browser keeps the width. */
  onWidth(width: number, save: boolean): void;
}

// The edge between a side panel and the centre: dragged, it sets the
// panel's width (`sign` is +1 when the panel lies left of the edge);
// a double click puts the default back.
function Splitter({ width, sign, fallback, onWidth }: SplitterProps): VNode {
  const start = useRef<{ x: number; width: number } | null>(null);
  return html`<div class="splitter" title="drag to resize; double-click to reset"
    onPointerDown=${(e: JSX.TargetedEvent<HTMLDivElement, PointerEvent>) => { e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId);
                             start.current = { x: e.clientX, width }; }}
    onPointerMove=${(e: JSX.TargetedEvent<HTMLDivElement, PointerEvent>) => { if (start.current) onWidth(clampPanel(start.current.width + sign * (e.clientX - start.current.x)), false); }}
    onPointerUp=${() => { if (start.current) { start.current = null; onWidth(width, true); } }}
    onDblClick=${() => onWidth(fallback, true)}></div>`;
}

// `text` on the clipboard, or, where the page may not write it (a
// browser that refuses, or a page served over plain http from another
// machine), downloaded as `filename`: "copied" or "downloaded".
async function copyOrDownload(text: string, filename: string): Promise<"copied" | "downloaded"> {
  try {
    await navigator.clipboard.writeText(text);
    return "copied";
  } catch (_) {
    saveBlob(new Blob([text], { type: "text/yaml" }), filename);
    return "downloaded";
  }
}


// `set(key)`: an input's handler writing its value (a checkbox's checked) to `view[key]`.
const setter = (setView: SetView) => (key: "device" | "style" | "time" | "date" | "skin") =>
  (e: JSX.TargetedEvent<HTMLInputElement | HTMLSelectElement>) => {
    const t = e.currentTarget;
    const value = "checked" in t && t.type === "checkbox" ? t.checked : t.value;
    setView((v) => ({ ...v, [key]: value }));
  };

function route(): string | null {
  const m = location.hash.match(/^#\/face\/([0-9a-f]{32})$/);
  return m ? m[1] ?? null : null;
}

function go(docId: string | null): void {
  location.hash = docId ? `#/face/${docId}` : "#/";
}

function useEvents(onEvent: (event: EventName, data: EventFields) => void): void {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  useEffect(() => {
    return listen((event, data) => handler.current(event, data));
  }, []);
}

function ago(seconds: number): string {
  const s = Math.max(0, Date.now() / 1000 - seconds);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(seconds * 1000).toLocaleDateString();
}

// The status a refusal was thrown with (`api`), or undefined for any other error.
const statusOf = (e: unknown): number | undefined =>
  typeof e === "object" && e !== null && "status" in e && typeof e.status === "number" ? e.status : undefined;

// -- home ----------------------------------------------------------------------------

export interface HomeProps {
  onError: OnError;
}

function Home({ onError }: HomeProps): VNode {
  const [home, setHome] = useState<HomeAnswer | null>(null);
  const [template, setTemplate] = useState("minimal");
  const [name, setName] = useState("My Face");
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [help, setHelp] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(() => api("home").then(setHome, onError), []);
  useEffect(() => { load(); }, []);
  // another tab deleted or renamed a face
  useEvents((name) => { if (name === "created" || name === "deleted" || name === "renamed") load(); });
  const [renaming, setRenaming] = useState<string | null>(null);
  const rename = async (doc: LibraryEntry, to: string): Promise<void> => {
    setRenaming(null);
    try { await api("rename", { id: doc.id, name: to }); load(); }
    catch (e) { onError(e); }
  };

  const create = async (): Promise<void> => {
    setBusy(true);
    try {
      const doc = await api("new", { template, name });
      go(doc.id);
    } catch (e) { onError(e); } finally { setBusy(false); }
  };

  const upload = async (file: File | undefined): Promise<void> => {
    if (!file) return;
    setBusy(true);
    try {
      const doc = await api("upload", { filename: file.name }, file);
      go(doc.id);
    } catch (e) { onError(e); } finally { setBusy(false); }
  };

  const remove = async (doc: LibraryEntry): Promise<void> => {
    if (!await ask(`Delete "${doc.name}" and its whole history? This cannot be undone.`, "Delete")) return;
    try { await api("delete", { id: doc.id }); load(); }
    catch (e) { onError(e); }
  };

  if (!home) return html`<div class="home dim">Loading…</div>`;
  const blurb = home.templates.find((t) => t.name === template)?.blurb;
  return html`
    <div class="home">
      <h1>wfb studio <button class="help-open" onClick=${() => setHelp(true)} title="The README and the guide">Help</button></h1>
      <div class="dim">Create a watch face, or open one to edit. Download it to save.</div>
      ${help ? html`<${HelpDialog} start="README.md" onClose=${() => setHelp(false)} />` : null}
      <div class="cards">
        <div class="card">
          <h2>New face</h2>
          <label>Start from</label>
          <select value=${template} onChange=${(e: JSX.TargetedEvent<HTMLSelectElement>) => setTemplate(e.currentTarget.value)}>
            ${home.templates.map((t) => html`<option value=${t.name}>${t.name}</option>`)}
          </select>
          <div class="dim small blurb">${blurb}</div>
          <label>Name</label>
          <input type="text" value=${name} onInput=${(e: JSX.TargetedEvent<HTMLInputElement>) => setName(e.currentTarget.value)} />
          <div class="row"><button class="primary" disabled=${busy} onClick=${create}>Create</button></div>
        </div>
        <div class="card">
          <h2>Open</h2>
          <div class=${"drop" + (over ? " over" : "")}
               onDragOver=${(e: JSX.TargetedEvent<HTMLDivElement, DragEvent>) => { e.preventDefault(); setOver(true); }}
               onDragLeave=${() => setOver(false)}
               onDrop=${(e: JSX.TargetedEvent<HTMLDivElement, DragEvent>) => { e.preventDefault(); setOver(false); upload(e.dataTransfer?.files[0]); }}>
            Drop a <code>.zip</code> (face.yaml + assets/) or a <code>.yaml</code> here
            <div class="row center">
              <button disabled=${busy} onClick=${() => fileInput.current?.click()}>Choose file…</button>
            </div>
          </div>
          <input type="file" accept=".zip,.yaml,.yml" hidden ref=${fileInput}
                 onChange=${(e: JSX.TargetedEvent<HTMLInputElement>) => upload(e.currentTarget.files?.[0])} />
        </div>
      </div>
      <div class="card library">
        <h2>Library</h2>
        ${home.documents.length === 0
          ? html`<div class="dim">Nothing yet. Faces you create or open are kept here, with their history, until you delete them.</div>`
          : html`<ul class="recent">
              ${home.documents.map((d) => html`
                <li>
                  <span class="cover" onClick=${() => go(d.id)} title="Open">
                    <${WorkerImage} op="cover" args=${{ id: d.id, v: d.version }} /></span>
                  <span class="about">
                    ${renaming === d.id
                      ? html`<${AddName} label="name" placeholder="the face's name" startOpen=${true}
                          suggest=${() => d.name} valid=${(t: string) => t.length > 0}
                          onAdd=${(to: string) => rename(d, to)} onCancel=${() => setRenaming(null)} />`
                      : html`<span class="name" onClick=${() => go(d.id)} title="Open">${d.name}</span>`}
                    <span class="dim">v${d.version} · ${ago(d.changed)}${d.snapshots ? ` · ${d.snapshots} snapshot${d.snapshots > 1 ? "s" : ""}` : ""}</span>
                  </span>
                  <button onClick=${() => setRenaming(d.id)} disabled=${renaming === d.id}>Rename</button>
                  <button class="danger" onClick=${() => remove(d)}>Delete</button>
                </li>`)}
            </ul>`}
        <div class="dim small store-note">Faces and their history are kept in ${home.store} for <code>${location.origin}</code>${" "}until you delete them; another address or port has a library of its own</div>
      </div>
    </div>`;
}

// -- the editor ----------------------------------------------------------------------

interface MissingProps {
  doc: Summary;
  onSend: Send;
}

function Missing({ doc, onSend }: MissingProps): VNode | null {
  if (!doc.missing.length) return null;
  const add = (reference: string, file: File | undefined): void => {
    if (file) onSend({ op: "assets", args: { filename: file.name, reference }, body: file });
  };
  return html`<div class="banner">
    <strong>Missing files:</strong>
    ${doc.missing.map((ref) => html`<span class="file">
      <code>${ref}</code>
      <label><button onClick=${(e: JSX.TargetedEvent<HTMLButtonElement, MouseEvent>) =>
          (e.currentTarget.nextElementSibling as HTMLInputElement | null)?.click()}>Add…</button>
        <input type="file" accept=".ttf,.otf" hidden
               onChange=${(e: JSX.TargetedEvent<HTMLInputElement>) => add(ref, e.currentTarget.files?.[0])} /></label>
    </span>`)}
    <span class="dim">The face does not draw until every font file is added.</span>
  </div>`;
}

interface ChangesProps {
  states: HistoryState[];
  onGoto(state: HistoryState): void;
  /** A time as the list shows it. */
  when(time: number): string;
}

// The line of history, newest first: the current change marked, those
// past it (redo) dimmed; a click goes back or forward to that change in
// one step (`goto`).
function Changes({ states, onGoto, when }: ChangesProps): VNode {
  return html`<ul class="states">
    ${states.map((s) => html`<li class=${(s.current ? "current" : "") + (s.redo ? " redo" : "")}>
      <button class="state" disabled=${s.current} onClick=${() => onGoto(s)}
              title=${s.current ? "the face is here" : s.redo ? "go forward to this change" : "go back to this change"}>
        <span class="label">${s.label}</span><span class="dim">${when(s.time)}</span></button>
    </li>`)}
  </ul>`;
}

const when = (t: number): string => new Date(t * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" });

interface HistoryProps {
  doc: Summary;
  /** The face after a snapshot was taken, or null to fetch it. */
  onChanged(updated: Summary | null): void;
  onSend: Send;
  /** Open another face (a snapshot's copy). */
  onOpen(id: string): void;
  onError: OnError;
}

function History({ doc, onChanged, onSend, onOpen, onError }: HistoryProps): VNode {
  const h = doc.history;
  const post = async <O extends Op>(op: O, args: Args<O>): Promise<Answer<O> | null> => {
    try { return await api(op, args); }
    catch (e) { onError(e); return null; }
  };
  // the summary lists the newest changes; once asked, all of them, kept
  // up to date while the tab is open
  const [wantAll, setWantAll] = useState(false);
  const [all, setAll] = useState<History | null>(null);
  useEffect(() => { setWantAll(false); setAll(null); }, [doc.id]);
  useEffect(() => {
    if (!wantAll) return;
    let live = true;
    api("history", { id: doc.id }).then((got) => { if (live) setAll(got); }, onError);
    return () => { live = false; };
  }, [wantAll, doc.id, doc.version]);
  const states = all && all.version === doc.version ? all.states : h.states;
  const total = h.total ?? h.states.length;
  const restore = (s: HistorySnapshot): void => { onSend({ op: "restore", args: { snapshot: s.name } }); };
  const copy = async (s: HistorySnapshot): Promise<void> => {
    const created = await post("copy", { id: doc.id, snapshot: s.name });
    if (created) onOpen(created.id);
  };
  const snapshotNow = async (): Promise<void> => { if (await post("snapshot", { id: doc.id })) onChanged(null); };
  return html`<div class="history">
    <div class="row">
      <button onClick=${snapshotNow} title="Keep this version as a point in time">Snapshot now</button>
    </div>
    <div class="sub">Snapshots</div>
    ${h.snapshots.length ? html`<ul class="snaps">
      ${h.snapshots.map((s) => html`<li>
        <div><span>${when(s.time)}</span> <span class="dim">${s.reason}${s.current ? " · this version" : ""}</span></div>
        <div class="dim label">${s.label}</div>
        <div class="row">
          <button disabled=${s.current} onClick=${() => restore(s)} title="Make this the current version (undoable)">Restore</button>
          <button onClick=${() => copy(s)} title="Open it as a separate face">Open copy</button>
        </div>
      </li>`)}
    </ul>` : html`<div class="dim pad">None yet: one is taken every few minutes while the face changes, and on every download.</div>`}
    <div class="sub">Changes</div>
    <${Changes} states=${states} when=${when} onGoto=${(s: HistoryState) => onSend({ op: "goto", args: { seq: s.seq } })} />
    ${states.length < total ? html`<div class="row">
      <button onClick=${() => setWantAll(true)} title="Only the newest changes are listed">Show all ${total} changes</button>
    </div>` : null}
  </div>`;
}

interface DownloadMenuProps {
  doc: Summary;
  onError: OnError;
}

function DownloadMenu({ doc, onError }: DownloadMenuProps): VNode {
  const save = (form: NonNullable<DownloadArgs["form"]>): Promise<void> => download("download", { id: doc.id, form }).catch(onError);
  return html`<div class="menu">
    <button class="primary" onClick=${() => save("auto")}>Download</button>
    <${Popover} label="▾" title="Choose the format" align="right" bodyClass="menu-items">${(close: () => void) => html`
      <button onClick=${() => { close(); save("zip"); }}>.zip (face.yaml + assets)</button>
      <button onClick=${async () => {
        close();
        if (!doc.assets.length || await ask("This face uses asset files; a plain .yaml will not build on its own. Download it anyway?", "Download .yaml")) {
          save("yaml");
        }
      }}>.yaml only</button>`}
    </${Popover}>
  </div>`;
}

interface CommandPaletteProps {
  doc: Summary;
  onSelect(id: string): void;
  onFaceSection(key: string): void;
  onClose(): void;
}

/** One row of the palette: what it shows, and what choosing it does. */
interface PaletteItem {
  key: string;
  label: string;
  hint: Value;
  pick(): void;
}

// Ctrl/Cmd+K: a fuzzy-find over every element (by id, its type as the
// hint), colour, role, font, slot, hand set and style name. Choosing one
// does exactly what clicking it already does: an element is selected, as
// in Layers or on the face; anything else jumps to its Face-tab section
// (the same jump a colour role's own link gives from Properties).
function CommandPalette({ doc, onSelect, onFaceSection, onClose }: CommandPaletteProps): VNode {
  const [q, setQ] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (input.current && input.current.focus) input.current.focus(); }, []);
  const g = doc.globals;
  const items: PaletteItem[] = [
    ...blocksOf(doc.tree).nodes.map((n) => ({ key: `element:${n.id}`, label: n.id, hint: n.type, pick: () => onSelect(n.id) })),
    ...(g.palette || []).map((p) => ({ key: `colour:${p.name}`, label: p.name, hint: "colour", pick: () => onFaceSection("colours") })),
    ...((g.schemes && g.schemes.roles) || []).map((r) => ({ key: `role:${r}`, label: r, hint: "role", pick: () => onFaceSection("schemes") })),
    ...(g.fonts || []).map((f) => ({ key: `font:${f.name}`, label: f.name, hint: "font", pick: () => onFaceSection("fonts") })),
    ...(g.slots || []).map((s) => ({ key: `slot:${s.name}`, label: s.name, hint: "slot", pick: () => onFaceSection("slots") })),
    ...(g.hand_sets || []).map((h) => ({ key: `hand_set:${h}`, label: h, hint: "hand set", pick: () => onFaceSection("hand_sets") })),
    ...((g.styles && g.styles.entries) || []).map((s) => ({ key: `style:${s.name}`, label: s.name, hint: "style", pick: () => onFaceSection("styles") })),
  ];
  const needle = q.trim().toLowerCase();
  const matches = (needle ? items.filter((it) => it.label.toLowerCase().includes(needle)) : items).slice(0, 50);
  const choose = (it: PaletteItem | undefined): void => { if (it) { it.pick(); onClose(); } };
  return html`<${Modal} title="Jump to…" onClose=${onClose} className="palette">
    <div class="modal-body">
      <input ref=${input} type="text" class="mono" placeholder="an element, colour, font, slot, hand set or style"
        value=${q} onInput=${(e: JSX.TargetedEvent<HTMLInputElement>) => { setQ(e.currentTarget.value); setIndex(0); }}
        onKeyDown=${(e: JSX.TargetedEvent<HTMLInputElement, KeyboardEvent>) => {
          if (e.key === "Escape") { e.preventDefault(); onClose(); }
          else if (e.key === "ArrowDown") { e.preventDefault(); setIndex((i) => Math.min(i + 1, matches.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setIndex((i) => Math.max(i - 1, 0)); }
          else if (e.key === "Enter") { e.preventDefault(); choose(matches[index]); }
        }} />
      <ul class="rows palette-list">
        ${matches.map((it, i) => html`<li key=${it.key} class=${i === index ? "on" : ""} onClick=${() => choose(it)}>
          <span>${it.label}</span><span class="dim">${it.hint}</span>
        </li>`)}
        ${!matches.length ? html`<li class="dim">No match.</li>` : null}
      </ul>
    </div>
  </${Modal}>`;
}

interface ShortcutHelpProps {
  onClose(): void;
}

// Every shortcut, for "?" and the top bar's button.
function ShortcutHelp({ onClose }: ShortcutHelpProps): VNode {
  return html`<${Modal} title="Keyboard shortcuts" onClose=${onClose}>
    <div class="modal-body shortcuts">
      ${SHORTCUTS.map(([group, rows]) => html`<section>
        <h4>${group}</h4>
        <dl>${rows.map(([keys, what]) => html`<dt><kbd>${keys}</kbd></dt><dd>${what}</dd>`)}</dl>
      </section>`)}
      <div class="dim">Ctrl is Cmd on a Mac. None of these act while you type in a field or the YAML tab.</div>
    </div>
  </${Modal}>`;
}

interface PropertiesSectionProps {
  folded: boolean;
  onFold(folded: boolean): void;
  /** The elements selected besides `element`. */
  extra: string[];
  element: TreeNode | null;
  /** The selected element's box in the frame, when it is drawn. */
  box: Box | null | undefined;
  /** The ids the frame draws. */
  drawn: Set<string> | null;
  doc: Summary;
  device: string | null;
  vocab: Partial<Vocabulary>;
  scope: Scope;
  onScope(scope: Scope): void;
  onEdit(op: EditOp): Promise<Summary | null>;
  onError: OnError;
  onReveal(line: number, end?: number): void;
  onSelect: OnSelect;
  onFaceSection(key: string): void;
}

// The right column's upper section: the selection's place and keys.
function PropertiesSection({ folded, onFold, extra, element, box, drawn, doc, device, vocab, scope, onScope, onEdit, onError,
                             onReveal, onSelect, onFaceSection }: PropertiesSectionProps): VNode {
  return html`
    <section class="props-section">
      <h3 class="fold" onClick=${() => onFold(!folded)} aria-expanded=${!folded}
          title=${folded ? "Show the selection's properties" : "Fold the properties away"}>
        ${folded ? "▸" : "▾"} Properties${extra.length ? html` <span class="dim">· ${extra.length + 1} selected</span>` : null}</h3>
      ${folded ? null : html`<div class="section-scroll">
        ${element ? html`<div class="body dim where">
            in <code>${element.path.slice(0, -1).join(".")}</code>, line ${element.line}
            ${box ? html` · ${box[2]}×${box[3]} px at (${box[0]}, ${box[1]})` : ""}
            ${!box && drawn && element.type !== "group" ? " · not drawn in this frame" : ""}
          </div>` : null}
        <${Inspector} doc=${doc} element=${element} device=${device} vocab=${vocab}
                      scope=${scope} onScope=${onScope} onEdit=${onEdit} onError=${onError}
                      onReveal=${onReveal} onSelect=${onSelect} onFaceSection=${onFaceSection} />
      </div>`}
    </section>`;
}

type ReportsTab = "diagnostics" | "history";

interface ReportsSectionProps {
  folded: boolean;
  onFold(folded: boolean): void;
  tab: ReportsTab;
  onTab(tab: ReportsTab): void;
  doc: Summary;
  filter: DiagFilter;
  onFilter(filter: DiagFilter): void;
  onSelect(id: string | null): void;
  onError: OnError;
  onSend: Send;
  onChanged(updated: Summary | null): void;
}

// The right column's lower section: the Diagnostics and History tabs.
function ReportsSection({ folded, onFold, tab, onTab, doc, filter, onFilter, onSelect, onError, onSend, onChanged }: ReportsSectionProps): VNode {
  return html`
    <section class="lower-section">
      <div class="tabs">
        <button class=${tab === "diagnostics" && !folded ? "on" : ""}
                onClick=${() => { onTab("diagnostics"); onFold(false); }}>
          ${diagnosticsLabel(doc.diagnostics, filter)}</button>
        <button class=${tab === "history" && !folded ? "on" : ""}
                onClick=${() => { onTab("history"); onFold(false); }}>History</button>
        <button class="fold-button" onClick=${() => onFold(!folded)} aria-expanded=${!folded}
                title=${folded ? "Show Diagnostics and History" : "Fold Diagnostics and History away"}>
          ${folded ? "▴" : "▾"}</button>
      </div>
      ${folded ? null : html`<div class="section-scroll">${tab === "diagnostics"
        ? html`<${Diagnostics} items=${doc.diagnostics} tree=${doc.tree} onSelect=${onSelect}
                               filter=${filter} onFilter=${onFilter} />`
        : html`<${History} doc=${doc} onError=${onError} onOpen=${(id: string) => go(id)} onSend=${onSend}
                           onChanged=${onChanged} />`}</div>`}
    </section>`;
}

// Whether the watch's low-power frame is AOD (AMOLED) rather than asleep.
const isAmoled = (deviceInfo: DeviceInfo | null | undefined): boolean =>
  !!deviceInfo && ["amoled", "oled"].includes(String(deviceInfo.display).toLowerCase());

type PreviewMode = "awake" | "asleep" | "aod";

// Which frame the preview draws: awake, asleep (MIP) or AOD (AMOLED), one at a time.
const previewMode = (view: View): PreviewMode => (view.aod ? "aod" : view.asleep ? "asleep" : "awake");

interface PreviewMenuProps {
  view: View;
  setView: SetView;
  /** The time and date the frame is drawn at: the clock's with `view.now`, else `view`'s. */
  time: string;
  date: string;
  clock: Clock;
  setClock(clock: Clock): void;
  slots: SlotEntry[];
  vocab: Partial<Vocabulary>;
  deviceInfo: DeviceInfo | undefined;
}

// The Preview popover: what the face is drawn at (the time and date, each
// slot's reading, asleep, AOD, the skin), its button saying what is set.
function PreviewMenu({ view, setView, time, date, clock, setClock, slots, vocab, deviceInfo }: PreviewMenuProps): VNode {
  const set = setter(setView);
  const amoled = isAmoled(deviceInfo);
  const picks = view.picks || {};
  // what the Preview button's label says is set: whatever is not the default
  const previewed = [
    view.now ? "now" : [time && time.slice(0, 5), date].filter(Boolean).join(" "),
    ...slots.flatMap((sl) => { const pick = picks[sl.name]; return pick && pick !== sl.default ? [typeLabel(vocab, pick)] : []; }),
    view.asleep && "asleep", view.aod && "AOD", view.skin && "skin",
  ].filter(Boolean);
  // each frame, and whether this watch has it
  const modes: [PreviewMode, string, boolean][] = [["awake", "awake", true], ["asleep", "asleep", !amoled], ["aod", "AOD", amoled]];
  return html`
    <${Popover} label=${html`Preview${previewed.length ? html`<span class="set"> · ${previewed.join(" · ")}</span>` : null} ▾`}
                title="What the face is drawn at: the time and date, each slot's reading, asleep, AOD, the skin"
                className="preview">
      <div class="preview-grid">
        <label>Time <input type="time" step="1" value=${time} disabled=${view.now} onChange=${set("time")} /></label>
        <label title="the day the date is drawn at; empty, a sample day">Date
          <input type="date" value=${date} disabled=${view.now} onChange=${set("date")} /></label>
        <label title="draw the face at this computer's time and date, as it goes on">
          <input type="checkbox" checked=${view.now}
                 onChange=${(e: JSX.TargetedEvent<HTMLInputElement>) => {
                   // switched off, the face stays at the moment it last drew
                   if (e.currentTarget.checked) { setClock(clockNow()); setView((v) => ({ ...v, now: true })); }
                   else setView((v) => ({ ...v, now: false, time: clock.time, date: clock.date }));
                 }} /> now</label>
        ${slots.map((sl) => html`<label title=${`what the slot ${sl.name} is drawn showing; the wearer picks it on the watch`}>${sl.name}
          <select value=${picks[sl.name] || sl.default}
                  onChange=${(e: JSX.TargetedEvent<HTMLSelectElement>) => {
                    const type = e.currentTarget.value;
                    setView((v) => ({ ...v, picks: { ...(v.picks || {}), [sl.name]: type } }));
                  }}>
            ${(Array.isArray(sl.choices) ? sl.choices.map((c) => c.type ?? "") : (vocab.complication_types || []).map((t) => t.name))
              .map((t) => html`<option value=${t}>${t === sl.default ? `${typeLabel(vocab, t)} (first)` : typeLabel(vocab, t)}</option>`)}
          </select></label>`)}
        <div class="preview-mode" role="radiogroup" title="awake, or the watch's low-power frame: asleep on an always-on (MIP) screen, AOD on an AMOLED one">
          ${modes.map(([mode, label, fits]) => html`
            <label title=${fits ? "" : amoled ? "an AMOLED watch has no asleep frame: its low-power frame is AOD" : "only an AMOLED watch has an AOD frame"}>
              <input type="radio" name="preview-mode" checked=${previewMode(view) === mode} disabled=${!fits}
                     onChange=${() => setView((v) => ({ ...v, asleep: mode === "asleep", aod: mode === "aod" }))} /> ${label}</label>`)}
        </div>
        <label title=${deviceInfo && !deviceInfo.skin ? "this watch's files have no skin" : "the watch drawn round the screen"}>
          <input type="checkbox" checked=${view.skin} disabled=${deviceInfo && !deviceInfo.skin}
                 onChange=${set("skin")} /> skin</label>
        ${view.now || time || date ? html`<button class="reset-preview" title="the sample time and date; the frame and the skin stay"
            onClick=${() => setView((v) => ({ ...v, time: "", date: "", now: false }))}>Back to the sample moment</button>` : null}
      </div>
    </${Popover}>`;
}

export interface EditorProps {
  docId: string;
  onError: OnError;
  onNotice: OnNotice;
}

function Editor({ docId, onError, onNotice }: EditorProps): VNode {
  // the face as the worker last answered (`protocol.ts`'s Summary)
  const [doc, setDoc] = useState<Summary | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  // more elements selected with Ctrl/Cmd (or Shift on the face), for
  // moving, deleting or grouping together
  const [extra, setExtra] = useState<string[]>([]);
  const [view, setView] = useState<View>({ device: null, style: "", time: "", date: "", now: false, asleep: false,
                                           aod: false, skin: storedSkin(), zoom: storedZoom(), real: false });
  const [pxPerInch, setPxPerInch] = useState(storedPxPerInch());
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [vocab, setVocab] = useState<Partial<Vocabulary>>({});
  // the face's slots, which the Preview popover picks a type for
  const slots: SlotEntry[] = (doc && doc.globals && doc.globals.slots) || [];
  useEffect(() => { api("vocabulary").then(setVocab, onError); }, []);
  const [left, setLeft] = useState<"layers" | "face">("layers");
  // the Face tab's open section, remembered by this browser
  const [faceSection, setFaceSectionState] = useState(storedFaceSection());
  const setFaceSection = useCallback((key: string) => {
    setFaceSectionState(key);
    try { localStorage.setItem("wfb-face-section", key); } catch (_) { /* private mode */ }
  }, []);
  // jump to a Face-tab section (Ctrl+K, a colour role in Properties),
  // whether or not the Face tab is showing
  const openFaceSection = useCallback((key: string) => { setFaceSection(key); setLeft("face"); }, [setFaceSection]);
  const [pane, setPane] = useState<"face" | "yaml">("face");
  const [tab, setTab] = useState<ReportsTab>("diagnostics");
  // the Diagnostics tab's severity filter, kept across tabs, reset per face
  const [diagFilter, setDiagFilter] = useState<DiagFilter>("all");
  // the hooks are JavaScript still, so what they give is typed here
  const [foldState, setFoldState] = useFold();
  const fold: Fold = foldState;
  const setFolded: (which: keyof Fold, folded: boolean) => void = setFoldState;
  // where an inspector edit or a drag writes geometry: "all" (a drag then
  // writes where the viewed device reads it), the device, its shape, or
  // its display class
  const [scope, setScope] = useState<Scope>("all");

  // A face from the worker, shown unless it is older than the one shown
  // (`outbox.newer`): answers can arrive out of order. An answer about
  // another face (one left while its change was on its way) is dropped.
  const docIdRef = useRef(docId);
  docIdRef.current = docId;
  const accept = useCallback((d: Summary) => {
    if (d.id !== docIdRef.current) return;
    setDoc((current) => (newer(current, d) ? d : current));
  }, []);
  const loadDoc = useCallback(() => api("get", { id: docId }).then(accept, (e: unknown) => {
    onError(e);
    if (statusOf(e) === 404) go(null);
  }), [docId]);
  useEffect(() => { setDoc(null); setSelected(null); setExtra([]); setDiagFilter("all"); loadDoc(); }, [docId]);

  // The device defaults to the first target, and is kept while it stays one.
  useEffect(() => {
    if (doc && (!view.device || !doc.targets.includes(view.device)) && doc.targets.length) {
      setView((v) => ({ ...v, device: doc.targets[0] ?? null }));
    }
  }, [doc]);
  const deviceInfo = (vocab.devices || []).find((d) => d.id === view.device);
  const real = deviceInfo ? realZoom(deviceInfo.ppi, pxPerInch) : null;
  // 1:1 stays on from watch to watch, each at its own real size; off, the zoom set before
  const zoom = view.real && real ? real : view.zoom;
  // the worker draws at a whole scale; the browser shows it at the zoom
  const scale = serverScale(zoom, window.devicePixelRatio || 1);
  const framed: FrameState = useFrame({ docId, doc, view, scale, deviceInfo, onError });
  const { frame, busy, skin, clock, setClock, time, date, picks } = framed;
  useEffect(() => {
    try { localStorage.setItem("wfb-skin", view.skin ? "1" : "0"); } catch (_) { /* private mode */ }
  }, [view.skin]);
  // another watch: its own low-power frame stands for the one shown, asleep for AOD and back
  useEffect(() => {
    if (!deviceInfo) return;
    const amoled = isAmoled(deviceInfo);
    if (view.asleep && amoled) setView((v) => ({ ...v, asleep: false, aod: true }));
    else if (view.aod && !amoled) setView((v) => ({ ...v, asleep: true, aod: false }));
  }, [deviceInfo && deviceInfo.id]);
  // a zoom of its own turns 1:1 off; the slider's steps are hundredths
  const setZoom = (z: number): void => {
    const zoom = clampZoom(Math.round(z * 100) / 100);
    try { localStorage.setItem("wfb-zoom", String(zoom)); } catch (_) { /* private mode */ }
    setView((v) => ({ ...v, zoom, real: false }));
  };
  const toggleReal = (): void => setView((v) => ({ ...v, real: !v.real }));

  // the device and scope a gesture is written for, as they were when it was made
  const where = useRef<Where>({});
  where.current = { ...(view.device !== null ? { device: view.device } : {}), scope: scope === "all" ? "auto" : scope };
  const outbox: Outbox = useOutbox({ docId, doc, frame, where, accept, reload: loadDoc, onError, onNotice });
  const { queue, queued, onDrag, send } = outbox;
  const step = useCallback((which: "undo" | "redo") => send({ op: which }), [send]);
  // One edit from the inspector or the Face panel: the worker patches the
  // text, checks it and answers with the face; a refusal says why.
  const edit = useCallback((op: EditOp) => send({ op: "edit", args: { edit: op } }), [send]);
  const upload = useCallback((file: File, { font, size, reference }: Partial<Pick<AssetArgs, "font" | "size" | "reference">>) => {
    const args: Omit<AssetArgs, keyof VersionArgs> = { filename: file.name };
    if (font) { args.font = font; args.size = size || "10%r"; }
    if (reference) args.reference = reference;
    return send({ op: "assets", args, body: file });
  }, [send]);
  // One structural edit from the Layers panel: the worker patches the text,
  // checks it and answers with the face and what to select.
  const structure = useCallback(async (op: StructureOp) => {
    const updated = await send({ op: "structure", args: { edit: op } });
    if (!updated) return;
    const select = (updated as Structured).select;   // a structure op answers a Structured
    if (op.op === "delete") setSelected(null);
    else if (select) setSelected(select);
    setExtra([]);
  }, [send]);

  // the face was deleted (in another tab): editing it can no longer be saved
  const [gone, setGone] = useState(false);
  useEffect(() => { setGone(false); }, [docId]);
  useEvents((name, data) => {
    if (name === "error" && (!data.id || data.id === docId)) onError(new Error(data.message));
    if (!doc || data.id !== docId) return;
    if (name === "deleted") setGone(true);
    else if (name === "renamed") setDoc((d) => (d && d.id === data.id && data.name !== undefined ? { ...d, name: data.name } : d));
    // this tab's own change reaches it with the answer to its request
    else if ((name === "changed" && data.tab !== TAB && data.version !== undefined && data.version > doc.version)
             || name === "snapshot") loadDoc();
  });

  const element = useMemo((): TreeNode | null => (doc && selected ? flatten(doc.tree).find((n) => n.id === selected) ?? null : null),
                          [doc, selected]);
  // The YAML tab's own save state (`YamlPane`'s `onSaving`); every other
  // change is in the outbox.
  const [yamlSaving, setYamlSaving] = useState<PlanKind>("idle");
  useEffect(() => { setYamlSaving("idle"); }, [docId]);
  // A change on its way to the worker dies with the page, so while one is
  // (`outbox.inFlight`) the browser asks before leaving. The YAML tab
  // flushes its own text on the same event.
  const yamlSavingRef = useRef<PlanKind>("idle");
  yamlSavingRef.current = yamlSaving;
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent): void => {
      if (!inFlight({ queue: queued.current, yaml: yamlSavingRef.current })) return;
      e.preventDefault();
      e.returnValue = "A change is still being saved.";
    };
    addEventListener("beforeunload", onBeforeUnload);
    return () => removeEventListener("beforeunload", onBeforeUnload);
  }, []);
  // where the YAML tab was, per face, while the editor is open
  const yamlMemory = useRef<Record<string, YamlMemory>>({});
  const [copied, setCopied] = useState<"copied" | "downloaded" | null>(null);
  const [panels, setPanels] = useState<Panels>(storedPanels());
  // `save`: the drag is over, so the browser keeps the width
  const panelWidth = (side: keyof Panels) => (w: number, save: boolean): void => {
    setPanels((p) => ({ ...p, [side]: w }));
    if (save) { try { localStorage.setItem(`wfb-panel-${side}`, String(w)); } catch (_) { /* private mode */ } }
  };
  // lines the YAML tab is asked to select, from a link elsewhere
  const [reveal, setReveal] = useState<Reveal | null>(null);
  const showLines = useCallback((line: number, end?: number) => { setReveal({ line, end, at: Date.now() }); setPane("yaml"); }, []);

  // `mode`: falsy selects `id` alone; "range" (Shift in the layers) selects
  // every element from the selection to it; anything else toggles it in
  // the selection
  const select: OnSelect = useCallback((id: string | null, mode?: SelectMode) => {
    if (mode === "range" && selected && doc) {
      const ids = id === null ? [] : rangeIds(doc.tree, selected, id);
      const first = ids.includes(selected) ? selected : ids[0];
      setSelected(first || null); setExtra(ids.filter((x) => x !== first));
    } else if (mode && selected && id !== null && id !== selected) {
      setExtra((xs) => (xs.includes(id) ? xs.filter((x) => x !== id) : [...xs, id]));
    } else { setSelected(id); setExtra([]); }
  }, [selected, doc]);
  const deselect = useCallback(() => { setSelected(null); setExtra([]); }, []);
  const chosen = selected ? [selected, ...extra] : extra;
  // the face and its frame, while the Face pane shows them
  const onFace = pane === "face" && frame && doc ? { frame, doc } : null;
  const tree: TreeBlock[] = doc ? doc.tree : [];
  const nodes = doc ? blocksOf(doc.tree).nodes : [];
  const chosenPaths = chosen.flatMap((id) => { const n = nodes.find((node) => node.id === id); return n ? [n.path] : []; });
  // the zoom that shows the whole watch in the space round it
  const fit = (): false | undefined => {
    const box = panZoom.wrap.current, w = frame ? frame.width : deviceInfo && deviceInfo.width;
    const h = frame ? frame.height : deviceInfo && deviceInfo.height;
    if (!box || !w || !h) return false;
    setZoom(Math.min(box.clientWidth / w, box.clientHeight / h) * 0.9);
    return undefined;
  };
  useShortcuts({
    undo: () => step("undo"),
    redo: () => step("redo"),
    duplicate: element ? () => structure({ op: "duplicate", path: element.path }) : null,
    // everything the frame shows, a group standing for its children
    selectAll: onFace ? () => {
      const ids = selectAll(onFace.doc.tree, new Set(onFace.frame.items.map((i) => i.id)));
      setSelected(ids[0] || null); setExtra(ids.slice(1));
    } : null,
    // a pixel, ten with Shift, written as a drag would be
    nudge: onFace && chosen.length ? (dx: number, dy: number): boolean => {
      const item = chosen.length > 1 ? together(onFace.frame.items, chosen) : onFace.frame.items.find((i) => i.id === chosen[0]);
      if (!item || !item.box) return false;
      const gesture: Gesture = { kind: "move", part: "both", dx, dy };
      onDrag(chosen, gesture, { item, moving: movedBy(onFace.doc.tree, chosen), preview: gesture });
      return true;
    } : null,
    // the whole selection, as one change
    remove: element ? () => { const op = deleteOp(tree, chosen); if (op) structure(op); } : null,
    group: chosenPaths.length ? () => structure({ op: "group", paths: chosenPaths }) : null,
    ungroup: element && element.type === "group" ? () => structure({ op: "ungroup", path: element.path }) : null,
    forward: element ? () => { const op = stepOp(tree, element.path, 1); if (op) structure(op); } : null,
    backward: element ? () => { const op = stepOp(tree, element.path, -1); if (op) structure(op); } : null,
    zoom: (by: number) => setZoom(zoom * (by > 0 ? 1.25 : 0.8)),
    zoomFit: fit,
    zoomReal: (): false | undefined => { if (!real) return false; toggleReal(); return undefined; },
    // the help, or a popover, closes first
    deselect: (): false | undefined => {
      if (dialog === "keys" || dialog === "palette") { setDialog(null); return undefined; }
      if (dialog || document.querySelector(".popover-body, .modal-back")) return false;
      if (!chosen.length) return false;
      deselect();
      return undefined;
    },
    help: () => setDialog(dialog === "keys" ? null : "keys"),
    commandPalette: () => setDialog(dialog === "palette" ? null : "palette"),
  });
  // Copied elements are their YAML, so they paste into another face, or
  // into a text editor. A paste goes in front of the selection, in its
  // block, or at the front of elements:.
  useClipboard({
    copy: (): string | null => {
      if (!doc || !chosen.length) return null;
      const text = elementsYaml(doc.text, doc.tree, chosen);
      if (text) onNotice(`copied ${chosen.length > 1 ? `${chosen.length} elements` : chosen[0]}`);
      return text || null;
    },
    cut: () => { const op = deleteOp(tree, chosen); if (op) structure(op); },
    paste: (text: string) => {
      if (!doc) return;
      const node = element;
      const block: Path = node ? node.path.slice(0, -1) : ["elements"];
      const siblings = node ? siblingsOf(doc.tree, node.path) : [];
      const before = node ? siblings[siblings.indexOf(node.id) + 1] || null : null;
      structure({ op: "paste", text, block, before });
    },
  });

  // the top bar's error count: Diagnostics, open, showing the errors
  const showErrors = (): void => { setTab("diagnostics"); setDiagFilter("error"); setFolded("lower", false); };
  const panZoom: PanZoom = usePanZoom({ zoom, setZoom, active: pane === "face", onBackground: deselect });

  const drawn = useMemo(() => (frame ? new Set(frame.items.filter((i) => i.drawn).map((i) => i.id)) : null), [frame]);
  const box = useMemo((): Box | null | undefined => {
    const item = frame && frame.items.find((i) => i.id === selected);
    return item && item.box;
  }, [frame, selected]);

  if (!doc) return html`<div class="home dim">Loading…</div>`;
  const set = setter(setView);
  const saved = saveState({ queue, yaml: yamlSaving });
  const counts = severityCounts(doc.diagnostics);
  const h = doc.history;
  const copyText = async (): Promise<void> => {
    const kept = yamlMemory.current[docId]?.text;
    const text = latestText(kept && kept.pane ? kept.pane.text() : null, kept ? kept.left : null, doc);
    setCopied(await copyOrDownload(text, `${doc.name}.yaml`));
  };
  // the watch's width on this screen at 1:1, when its files give a pixel density (`real` is set then too)
  const mmAcross = deviceInfo ? screenMm(deviceInfo.width, deviceInfo.ppi) : null;

  return html`<div class="editor">
    <div>
      <div class="topbar">
        <button onClick=${() => go(null)} title="All faces">← Faces</button>
        <span class="title"><${InlineName} value=${doc.name} className="name" valid=${(t: string) => t.length > 0}
          why="a face's name cannot be empty" title="click to rename the face"
          onRename=${async (to: string) => {
            try { const r = await api("rename", { id: doc.id, name: to });
                  setDoc((d) => (d ? { ...d, name: r.name } : d)); }
            catch (e) { onError(e); }
          }} /></span>
        <span role="status">${saved === "unsaved"
          ? html`<button class="save unsaved" onClick=${() => setPane("yaml")}
                         title=${`the YAML tab's text is not saved: open it to see why · version ${doc.version}`}>not saved</button>`
          : html`<span class=${"save " + saved}
                       title=${`changes are recorded as you make them · version ${doc.version}`}>
              ${saved === "saving" ? "saving…" : "saved"}</span>`}</span>
        <span class="undo-group">
          <button disabled=${!h.can_undo} onClick=${() => step("undo")}
                  title=${h.can_undo ? `Undo: ${h.undo} (Ctrl+Z)` : "Nothing to undo"}>↶ Undo</button>
          <button disabled=${!h.can_redo} onClick=${() => step("redo")}
                  title=${h.can_redo ? `Redo: ${h.redo} (Ctrl+Shift+Z)` : "Nothing to redo"}>↷ Redo</button>
          <${Popover} label="▾" title="Go back or forward to any change" className="history-menu">
            ${(close: () => void) => html`<div class="pop-title">Changes, newest first</div>
              <${Changes} states=${h.states} when=${when}
                onGoto=${(st: HistoryState) => { close(); send({ op: "goto", args: { seq: st.seq } }); }} />
              ${(h.total ?? h.states.length) > h.states.length ? html`<button class="more" onClick=${() => {
                close(); setTab("history"); setFolded("lower", false); }}>
                ${h.total - h.states.length} older in the History tab</button>` : null}`}
          </${Popover}>
        </span>
        <span class="spacer"></span>
        ${counts.error ? html`<button class="errors" onClick=${showErrors} title="Show the errors in Diagnostics">
            ${counts.error} error${counts.error > 1 ? "s" : ""}</button>` : null}
        <button title="The README and the guide" onClick=${() => setDialog("help")}>Help</button>
        <button class="keys-help" title="Keyboard shortcuts (?)" onClick=${() => setDialog("keys")}>?</button>
        <button disabled=${!doc.loads} title=${doc.loads ? "Build a .prg for one watch" : "the face does not load"}
                onClick=${() => setDialog("build")}>Build…</button>
        <${DownloadMenu} doc=${doc} onError=${onError} />
      </div>
      ${gone ? html`<div class="banner lost" role="alert">
        <strong>This face was deleted</strong> (in another tab), so changes to it can no longer be saved.
        <button onClick=${copyText} title="The face's text as you last had it, the YAML tab's included">Copy my text</button>
        ${copied ? html`<span class="dim">${copied === "copied" ? "copied" : "downloaded as a file"}</span>` : null}
        <button onClick=${() => go(null)}>Back to the faces</button></div>` : null}
      <${Missing} doc=${doc} onSend=${send} />
    </div>
    <div class="columns" style=${`grid-template-columns:${panels.left}px auto minmax(0, 1fr) auto ${panels.right}px`}>
      <div class="panel left">
        <div class="tabs top">
          <button class=${left === "layers" ? "on" : ""} onClick=${() => setLeft("layers")}>Layers</button>
          <button class=${left === "face" ? "on" : ""} onClick=${() => setLeft("face")}>Face</button>
        </div>
        <div class="panel-scroll">${left === "layers"
          ? html`<${Layers} doc=${doc} vocab=${vocab} selected=${selected} extra=${extra} drawn=${drawn}
                            onSelect=${select} onStructure=${structure} />`
          : html`<${FacePanel} doc=${doc} vocab=${vocab} onEdit=${edit} onUpload=${upload}
                               onSelect=${select} onStructure=${structure} onReveal=${showLines}
                               section=${faceSection} onSection=${setFaceSection} />`}</div>
      </div>
      <${Splitter} width=${panels.left} sign=${1} fallback=${280} onWidth=${panelWidth("left")} />
      <div class="stage">
        <div class="controls">
          <span class="seg" title="The face drawn, or its text">
            <button class=${pane === "face" ? "on" : ""} onClick=${() => setPane("face")}>Face</button>
            <button class=${pane === "yaml" ? "on" : ""} onClick=${() => setPane("yaml")}>YAML</button>
          </span>
          <label>Device
            <select value=${view.device || ""} onChange=${set("device")}>
              ${doc.targets.map((t) => html`<option value=${t}>${t}</option>`)}
            </select></label>
          ${doc.styles.length ? html`<label>Style
            <select value=${view.style} onChange=${set("style")}>
              <option value="">default</option>
              ${doc.styles.map((s) => html`<option value=${s.name}>${s.label}</option>`)}
            </select></label>` : null}
          <${PreviewMenu} view=${view} setView=${setView} time=${time} date=${date} clock=${clock} setClock=${setClock}
                          slots=${slots} vocab=${vocab} deviceInfo=${deviceInfo} />
          <label class="zoom">Zoom
            <input type="range" min=${MIN_ZOOM} max=${MAX_ZOOM} step="0.01" value=${zoom}
                   list="zoom-notches" onInput=${(e: JSX.TargetedEvent<HTMLInputElement>) => setZoom(Number(e.currentTarget.value))} />
            <datalist id="zoom-notches">
              ${[1, 2, 3].map((n) => html`<option value=${n} />`)}
              ${real ? html`<option value=${real} />` : null}
            </datalist>
            <span class="mono">${zoom.toFixed(zoom < 1 ? 3 : 2)}×</span></label>
          <button class=${view.real && real ? "on" : ""} disabled=${!real} aria-pressed=${!!(view.real && real)}
                  title=${mmAcross !== null ? `the watch's real size, ${mmAcross.toFixed(1)} mm across, on this screen`
                                            : "this watch's files give no pixel density"}
                  onClick=${toggleReal}>1:1</button>
          <button class="reset" title="Calibrate real size with a bank card" aria-label="Calibrate real size with a bank card" onClick=${() => setDialog("calibrate")}>⚙</button>
        </div>
        ${pane === "yaml"
          ? html`<${YamlPane} doc=${doc} selected=${selected} reveal=${reveal} memory=${yamlMemory.current[docId] ||= {}} onDoc=${accept} onError=${onError} onSaving=${setYamlSaving}
                              onSelect=${(id: string) => { setSelected(id); setExtra([]); }} />`
          : html`<div class="canvas-wrap" ref=${panZoom.wrap} ...${panZoom.handlers}>
              ${busy ? html`<div class="busy">rendering…</div>` : null}
              ${frame ? html`<${Canvas} frame=${frame} selected=${selected}
                                        extra=${extra} tree=${doc.tree} queue=${queue}
                                        zoom=${zoom} skin=${skin && skin.scale === frame.scale ? skin : null}
                                        onPick=${select} onDrag=${onDrag} />`
                      : html`<div class="empty">${doc.loads ? "No frame yet." :
                          "The face does not load, so there is nothing to draw. The diagnostics on the right say why."}</div>`}
            </div>`}
        <${Strip} doc=${doc} view=${{ ...view, time, date }} picks=${picks}
                  onDevice=${(d: string) => setView((v) => ({ ...v, device: d }))} />
      </div>
      <${Splitter} width=${panels.right} sign=${-1} fallback=${340} onWidth=${panelWidth("right")} />
      <div class=${"panel right" + (fold.props ? " props-folded" : "") + (fold.lower ? " lower-folded" : "")}>
        <${PropertiesSection} folded=${fold.props} onFold=${(f: boolean) => setFolded("props", f)} extra=${extra}
          element=${element} box=${box} drawn=${drawn} doc=${doc} device=${view.device} vocab=${vocab}
          scope=${scope} onScope=${setScope} onEdit=${edit} onError=${onError} onReveal=${showLines} onSelect=${select}
          onFaceSection=${openFaceSection} />
        <${ReportsSection} folded=${fold.lower} onFold=${(f: boolean) => setFolded("lower", f)} tab=${tab} onTab=${setTab}
          doc=${doc} filter=${diagFilter} onFilter=${setDiagFilter} onSelect=${setSelected} onError=${onError}
          onSend=${send} onChanged=${(updated: Summary | null) => updated ? accept(updated) : loadDoc()} />
      </div>
    </div>
    ${dialog === "build" ? html`<${BuildDialog} doc=${doc} vocab=${vocab} device=${view.device}
                                               onClose=${() => setDialog(null)} />` : null}
    ${dialog === "keys" ? html`<${ShortcutHelp} onClose=${() => setDialog(null)} />` : null}
    ${dialog === "palette" && doc ? html`<${CommandPalette} doc=${doc} onSelect=${select}
        onFaceSection=${openFaceSection} onClose=${() => setDialog(null)} />` : null}
    ${dialog === "help" ? html`<${HelpDialog} start="docs/guide/studio.md" onClose=${() => setDialog(null)} />` : null}
    ${dialog === "calibrate" ? html`<${CalibrateDialog} current=${pxPerInch} onClose=${() => setDialog(null)}
        onSave=${(v: number) => {
          try { localStorage.setItem("wfb-css-px-per-inch", String(v)); } catch (_) { /* private mode */ }
          setPxPerInch(v); setDialog(null);
        }} />` : null}
  </div>`;
}

// -- the app -------------------------------------------------------------------------

type ToastKind = "error" | "notice";

interface Toast {
  message: string;
  kind: ToastKind;
}

/** A message shown, and when. */
interface LogEntry extends Toast {
  at: number;
}

interface MessageLogProps {
  /** Newest first. */
  log: LogEntry[];
  /** How many of the newest the author has not opened the list for. */
  unseen: number;
  onOpen(): void;
  onClear(): void;
}

// Every message the editor has shown, newest first: a toast goes after a
// few seconds, and a newer one replaces it, so a refusal's reason stays
// readable here. The badge counts those not seen yet.
function MessageLog({ log, unseen, onOpen, onClear }: MessageLogProps): VNode | null {
  if (!log.length) return null;
  const time = (t: number): string => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return html`<div class="log-badge">
    <${Popover} align="right up" onOpen=${onOpen}
      label=${html`Messages${unseen ? html` <span class=${"count" + (log.some((m, i) => i < unseen && m.kind === "error") ? " error" : "")}>${unseen}</span>` : null}`}
      title="Every message shown, newest first">
      <div class="pop-title">Messages, newest first</div>
      <ul class="log">${log.map((m) => html`<li class=${m.kind}>
        <span class="dim">${time(m.at)}</span> ${m.message}</li>`)}</ul>
      <button class="more" onClick=${onClear}>Clear</button>
    </${Popover}>
  </div>`;
}

// An error's message, or the error shown as text: `api` throws Errors, but anything can be thrown.
const messageOf = (e: unknown): string => (e instanceof Error && e.message) || String(e);

export function App(): VNode {
  const [docId, setDocId] = useState<string | null>(route());
  const [toast, setToast] = useState<Toast | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);              // newest first
  const [unseen, setUnseen] = useState(0);
  const toastTimer = useRef<number | null>(null);
  useEffect(() => {
    const onHash = (): void => setDocId(route());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);
  // a new message replaces the last, and gets its own full time
  const show = useCallback((message: string, kind: ToastKind) => {
    if (toastTimer.current !== null) clearTimeout(toastTimer.current);
    setToast({ message, kind });
    setLog((l) => [{ message, kind, at: Date.now() }, ...l].slice(0, 100));
    setUnseen((n) => n + 1);
    toastTimer.current = setTimeout(() => setToast(null), kind === "error" ? 6000 : 4000);
  }, []);
  const onError: OnError = useCallback((e: unknown) => show(messageOf(e), "error"), [show]);
  const onNotice: OnNotice = useCallback((message: string) => show(message, "notice"), [show]);
  return html`
    ${docId ? html`<${Editor} docId=${docId} onError=${onError} onNotice=${onNotice} />`
            : html`<${Home} onError=${onError} />`}
    ${toast ? html`<div class=${"toast " + toast.kind} role=${toast.kind === "error" ? "alert" : "status"}
                        onClick=${() => setToast(null)}>${toast.message}</div>` : null}
    <${MessageLog} log=${log} unseen=${unseen} onOpen=${() => setUnseen(0)}
                   onClear=${() => { setLog([]); setUnseen(0); }} />
    <${AskHost} />`;
}
