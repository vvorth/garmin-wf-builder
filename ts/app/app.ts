// wfb studio's front end. The page asks and shows; its worker
// (`api.ts`) holds the face's text and runs the compiler, so nothing here
// decides what a face looks like: every image comes from the worker's
// renderer. The editor's state is `store.ts`'s `EditorStore`, which `App`
// creates once and provides; each part of the page reads the slice it
// needs through `useStore` and calls the store's actions.

import { html } from "htm/preact";
import type { JSX, VNode } from "preact";
import { useState, useEffect, useRef, useCallback, useMemo } from "preact/hooks";
import { api, download, listen, saveBlob } from "./api.ts";
import { useClipboard, usePanZoom, useShortcuts } from "./hooks.ts";
import type { PanZoom } from "./hooks.ts";
import { movedBy, together } from "./hit.ts";
import type { Box } from "./hit.ts";
import { AddName, InlineName, Popover, WorkerImage } from "./ui.ts";
import { Canvas, Strip } from "./canvas.ts";
import { Layers } from "./layers.ts";
import { YamlPane } from "./yaml.ts";
import { AskHost, BuildDialog, CalibrateDialog, Modal, ask } from "./dialogs.ts";
import { HelpDialog } from "./help.ts";
import { SHORTCUTS } from "./keys.ts";
import { MAX_ZOOM, MIN_ZOOM, screenMm } from "./zoom.ts";
import { FacePanel, Inspector } from "./panels.ts";
import { picksParam, severityCounts, typeLabel } from "./values.ts";
import { Diagnostics, diagnosticsLabel } from "./diagnostics.ts";
import type { DiagnosticFilter } from "./diagnostics.ts";
import { blocksOf, deleteOp, elementsYaml, siblingsOf, stepOp } from "./tree.ts";
import { latestText } from "./textsync.ts";
import {
  EditorStore, PANEL_DEFAULTS, StoreProvider, chosenIds, clampPanel, deviceInfoOf, elementOf, go, isAmoled, realZoomOf, route, savedState,
  shownDate, shownTime, useEditorStore, useStore, zoomOf,
} from "./store.ts";
import type { Clock, Context, EditorState, FrameMode, Message, SelectMode, Shown } from "./store.ts";
import type { AnyGesture } from "./outbox.ts";
import type {
  Answer, Args, DownloadArgs, EditOp, EventFields, EventName, History, HistorySnapshot, HistoryState, Home as HomeAnswer,
  LibraryEntry, Op, Path, PointGesture, Scope, SlotEntry, StructureOp, Summary, TreeBlock, TreeNode, Value, Vocabulary,
} from "../src/studio/protocol.ts";

/** Shows an error (`api`'s refusal, or anything thrown) as a toast. */
export type OnError = (e: unknown) => void;
/** `owner`: the element a hand's or part's Layers row sits under, entered before the part is selected. */
export type OnSelect = (id: string | null, mode?: SelectMode, owner?: Path) => void;

interface SplitterProps {
  width: number;
  /** +1 when the panel lies left of the edge. */
  sign: 1 | -1;
  fallback: number;
  onWidth(width: number): void;
}

// The edge between a side panel and the centre: dragged, it sets the
// panel's width (`sign` is +1 when the panel lies left of the edge);
// a double click puts the default back.
function Splitter({ width, sign, fallback, onWidth }: SplitterProps): VNode {
  const start = useRef<{ x: number; width: number } | null>(null);
  return html`<div class="splitter" title="drag to resize; double-click to reset"
    onPointerDown=${(e: JSX.TargetedEvent<HTMLDivElement, PointerEvent>) => { e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId);
                             start.current = { x: e.clientX, width }; }}
    onPointerMove=${(e: JSX.TargetedEvent<HTMLDivElement, PointerEvent>) => { if (start.current) onWidth(clampPanel(start.current.width + sign * (e.clientX - start.current.x))); }}
    onPointerUp=${() => { start.current = null; }}
    onDblClick=${() => onWidth(fallback)}></div>`;
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

// -- home ----------------------------------------------------------------------------

function Home(): VNode {
  const store = useEditorStore();
  const onError: OnError = (e) => store.error(e);
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

function Missing({ doc }: { doc: Summary }): VNode | null {
  const store = useEditorStore();
  if (!doc.missing.length) return null;
  const add = (reference: string, file: File | undefined): void => {
    if (file) store.upload(file, { reference });
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

function HistoryTab({ doc }: { doc: Summary }): VNode {
  const store = useEditorStore();
  const h = doc.history;
  const post = async <O extends Op>(op: O, args: Args<O>): Promise<Answer<O> | null> => {
    try { return await api(op, args); }
    catch (e) { store.error(e); return null; }
  };
  // the summary lists the newest changes; once asked, all of them, kept
  // up to date while the tab is open
  const [wantAll, setWantAll] = useState(false);
  const [all, setAll] = useState<History | null>(null);
  useEffect(() => { setWantAll(false); setAll(null); }, [doc.id]);
  useEffect(() => {
    if (!wantAll) return;
    let live = true;
    api("history", { id: doc.id }).then((got) => { if (live) setAll(got); }, (e: unknown) => store.error(e));
    return () => { live = false; };
  }, [wantAll, doc.id, doc.version]);
  const states = all && all.version === doc.version ? all.states : h.states;
  const total = h.total ?? h.states.length;
  const copy = async (s: HistorySnapshot): Promise<void> => {
    const created = await post("copy", { id: doc.id, snapshot: s.name });
    if (created) go(created.id);
  };
  const snapshotNow = async (): Promise<void> => { if (await post("snapshot", { id: doc.id })) store.reload(); };
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
          <button disabled=${s.current} onClick=${() => store.restore(s.name)} title="Make this the current version (undoable)">Restore</button>
          <button onClick=${() => copy(s)} title="Open it as a separate face">Open copy</button>
        </div>
      </li>`)}
    </ul>` : html`<div class="dim pad">None yet: one is taken every few minutes while the face changes, and on every download.</div>`}
    <div class="sub">Changes</div>
    <${Changes} states=${states} when=${when} onGoto=${(s: HistoryState) => store.goto(s.seq)} />
    ${states.length < total ? html`<div class="row">
      <button onClick=${() => setWantAll(true)} title="Only the newest changes are listed">Show all ${total} changes</button>
    </div>` : null}
  </div>`;
}

function DownloadMenu({ doc }: { doc: Summary }): VNode {
  const store = useEditorStore();
  const save = (form: NonNullable<DownloadArgs["form"]>): Promise<void> => download("download", { id: doc.id, form }).catch((e: unknown) => store.error(e));
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
function CommandPalette({ doc }: { doc: Summary }): VNode {
  const store = useEditorStore();
  const onClose = (): void => store.setUi({ palette: false });
  const onFaceSection = (key: string): void => store.openFaceSection(key);
  const [q, setQ] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (input.current && input.current.focus) input.current.focus(); }, []);
  const g = doc.globals;
  const items: PaletteItem[] = [
    ...blocksOf(doc.tree).nodes.map((n) => ({ key: `element:${n.id}`, label: n.id, hint: n.type, pick: () => store.select(n.id) })),
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

// Every shortcut, for "?" and the top bar's button.
function ShortcutHelp({ onClose }: { onClose(): void }): VNode {
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

// The right column's upper section: the selection's place and keys.
function PropertiesSection({ doc }: { doc: Summary }): VNode {
  const store = useEditorStore();
  const folded = useStore((s) => s.ui.folds.props);
  const selection = useStore((s) => s.selection);
  const element = useStore(elementOf);
  const ins = useStore((s) => s.inspect);
  const target = useStore((s) => s.context.target);
  const vocab = useStore((s) => s.vocab);
  const frame = useStore((s) => s.frame.current);
  const drawn = useMemo(() => (frame ? new Set(frame.items.filter((i) => i.drawn).map((i) => i.id)) : null), [frame]);
  const box = useMemo((): Box | null | undefined => {
    const item = frame && frame.items.find((i) => i.id === selection.primary);
    return item && item.box;
  }, [frame, selection.primary]);
  const extra = selection.extra;
  return html`
    <section class="props-section">
      <h3 class="fold" onClick=${() => store.setFolded("props", !folded)} aria-expanded=${!folded}
          title=${folded ? "Show the selection's properties" : "Fold the properties away"}>
        ${folded ? "▸" : "▾"} Properties${extra.length ? html` <span class="dim">· ${extra.length + 1} selected</span>` : null}</h3>
      ${folded ? null : html`<div class="section-scroll">
        ${element ? html`<div class="body dim where">
            in <code>${element.path.slice(0, -1).join(".")}</code>, line ${element.line}
            ${box ? html` · ${box[2]}×${box[3]} px at (${box[0]}, ${box[1]})` : ""}
            ${!box && drawn && element.type !== "group" ? " · not drawn in this frame" : ""}
          </div>` : null}
        <${Inspector} doc=${doc} element=${element} ins=${ins} target=${target} vocab=${vocab ?? {}}
                      vertex=${selection.vertex} onHoverVertex=${(i: number) => store.selectVertex(i)}
                      onEdit=${(op: EditOp) => store.edit(op)} onBatch=${(label: string, edits: EditOp[]) => { void store.batch(label, edits); }}
                      onReveal=${(line: number, end?: number) => store.reveal(line, end)} onSelect=${(id: string) => store.select(id)}
                      onFaceSection=${(key: string) => store.openFaceSection(key)} />
      </div>`}
    </section>`;
}

// The right column's lower section: the Diagnostics and History tabs.
function ReportsSection({ doc }: { doc: Summary }): VNode {
  const store = useEditorStore();
  const folded = useStore((s) => s.ui.folds.lower);
  const tab = useStore((s) => s.ui.reportsTab);
  const filter = useStore((s) => s.ui.diagFilter);
  const onFold = (f: boolean): void => store.setFolded("lower", f);
  const show = (reportsTab: EditorState["ui"]["reportsTab"]): void => store.setUi({ reportsTab, folds: { ...store.state.ui.folds, lower: false } });
  return html`
    <section class="lower-section">
      <div class="tabs">
        <button class=${tab === "diagnostics" && !folded ? "on" : ""} onClick=${() => show("diagnostics")}>
          ${diagnosticsLabel(doc.diagnostics, filter)}</button>
        <button class=${tab === "history" && !folded ? "on" : ""} onClick=${() => show("history")}>History</button>
        <button class="fold-button" onClick=${() => onFold(!folded)} aria-expanded=${!folded}
                title=${folded ? "Show Diagnostics and History" : "Fold Diagnostics and History away"}>
          ${folded ? "▴" : "▾"}</button>
      </div>
      ${folded ? null : html`<div class="section-scroll">${tab === "diagnostics"
        ? html`<${Diagnostics} items=${doc.diagnostics} tree=${doc.tree} onSelect=${(id: string) => store.select(id)}
                               filter=${filter} onFilter=${(f: DiagnosticFilter) => store.setUi({ diagFilter: f })} />`
        : html`<${HistoryTab} doc=${doc} />`}</div>`}
    </section>`;
}

interface PreviewMenuProps {
  context: Context;
  /** The time and date the frame is drawn at: the clock's with `context.now`, else the context's. */
  time: string;
  date: string;
  clock: Clock;
  slots: SlotEntry[];
  vocab: Partial<Vocabulary>;
  amoled: boolean;
  /** This watch's files have a skin; undefined while the watch is unknown. */
  hasSkin: boolean | undefined;
  skin: boolean;
}

// The Preview popover: what the face is drawn at (the time and date, each
// slot's reading, asleep, AOD, the skin), its button saying what is set.
function PreviewMenu({ context, time, date, clock, slots, vocab, amoled, hasSkin, skin }: PreviewMenuProps): VNode {
  const store = useEditorStore();
  const picks = context.picks;
  // what the Preview button's label says is set: whatever is not the default
  const previewed = [
    context.now ? "now" : [time && time.slice(0, 5), date].filter(Boolean).join(" "),
    ...slots.flatMap((sl) => { const pick = picks[sl.name]; return pick && pick !== sl.default ? [typeLabel(vocab, pick)] : []; }),
    context.frame === "asleep" && "asleep", context.frame === "aod" && "AOD", skin && "skin",
  ].filter(Boolean);
  // each frame, and whether this watch has it
  const modes: [FrameMode, string, boolean][] = [["awake", "awake", true], ["asleep", "asleep", !amoled], ["aod", "AOD", amoled]];
  return html`
    <${Popover} label=${html`Preview${previewed.length ? html`<span class="set"> · ${previewed.join(" · ")}</span>` : null} ▾`}
                title="What the face is drawn at: the time and date, each slot's reading, asleep, AOD, the skin"
                className="preview">
      <div class="preview-grid">
        <label>Time <input type="time" step="1" value=${time} disabled=${context.now}
                           onChange=${(e: JSX.TargetedEvent<HTMLInputElement>) => store.setContext({ time: e.currentTarget.value })} /></label>
        <label title="the day the date is drawn at; empty, a sample day">Date
          <input type="date" value=${date} disabled=${context.now}
                 onChange=${(e: JSX.TargetedEvent<HTMLInputElement>) => store.setContext({ date: e.currentTarget.value })} /></label>
        <label title="draw the face at this computer's time and date, as it goes on">
          <input type="checkbox" checked=${context.now}
                 onChange=${(e: JSX.TargetedEvent<HTMLInputElement>) => {
                   // switched off, the face stays at the moment it last drew
                   if (e.currentTarget.checked) store.setContext({ now: true });
                   else store.setContext({ now: false, time: clock.time, date: clock.date });
                 }} /> now</label>
        ${slots.map((sl) => html`<label title=${`what the slot ${sl.name} is drawn showing; the wearer picks it on the watch`}>${sl.name}
          <select value=${picks[sl.name] || sl.default}
                  onChange=${(e: JSX.TargetedEvent<HTMLSelectElement>) => store.setContext({ picks: { ...picks, [sl.name]: e.currentTarget.value } })}>
            ${(Array.isArray(sl.choices) ? sl.choices.map((c) => c.type ?? "") : (vocab.complication_types || []).map((t) => t.name))
              .map((t) => html`<option value=${t}>${t === sl.default ? `${typeLabel(vocab, t)} (first)` : typeLabel(vocab, t)}</option>`)}
          </select></label>`)}
        <div class="preview-mode" role="radiogroup" title="awake, or the watch's low-power frame: asleep on an always-on (MIP) screen, AOD on an AMOLED one">
          ${modes.map(([mode, label, fits]) => html`
            <label title=${fits ? "" : amoled ? "an AMOLED watch has no asleep frame: its low-power frame is AOD" : "only an AMOLED watch has an AOD frame"}>
              <input type="radio" name="preview-mode" checked=${context.frame === mode} disabled=${!fits}
                     onChange=${() => store.setContext({ frame: mode })} /> ${label}</label>`)}
        </div>
        <label title=${hasSkin === false ? "this watch's files have no skin" : "the watch drawn round the screen"}>
          <input type="checkbox" checked=${skin} disabled=${hasSkin === false}
                 onChange=${(e: JSX.TargetedEvent<HTMLInputElement>) => store.setView({ skin: e.currentTarget.checked })} /> skin</label>
        ${context.now || time || date ? html`<button class="reset-preview" title="the sample time and date; the frame and the skin stay"
            onClick=${() => store.setContext({ time: "", date: "", now: false })}>Back to the sample moment</button>` : null}
      </div>
    </${Popover}>`;
}

// The top bar: the face's name, whether it is saved, undo and redo, and the
// buttons for help, building and downloading.
function TopBar({ doc }: { doc: Summary }): VNode {
  const store = useEditorStore();
  const saved = useStore(savedState);
  const counts = severityCounts(doc.diagnostics);
  const h = doc.history;
  // the top bar's error count: Diagnostics, open, showing the errors
  const showErrors = (): void => store.setUi({ reportsTab: "diagnostics", diagFilter: "error", folds: { ...store.state.ui.folds, lower: false } });
  return html`<div class="topbar">
    <button onClick=${() => go(null)} title="All faces">← Faces</button>
    <span class="title"><${InlineName} value=${doc.name} className="name" valid=${(t: string) => t.length > 0}
      why="a face's name cannot be empty" title="click to rename the face"
      onRename=${(to: string) => store.rename(to)} /></span>
    <span role="status">${saved === "unsaved"
      ? html`<button class="save unsaved" onClick=${() => store.setUi({ pane: "yaml" })}
                     title=${`the YAML tab's text is not saved: open it to see why · version ${doc.version}`}>not saved</button>`
      : html`<span class=${"save " + saved}
                   title=${`changes are recorded as you make them · version ${doc.version}`}>
          ${saved === "saving" ? "saving…" : "saved"}</span>`}</span>
    <span class="undo-group">
      <button disabled=${!h.can_undo} onClick=${() => store.undo()}
              title=${h.can_undo ? `Undo: ${h.undo} (Ctrl+Z)` : "Nothing to undo"}>↶ Undo</button>
      <button disabled=${!h.can_redo} onClick=${() => store.redo()}
              title=${h.can_redo ? `Redo: ${h.redo} (Ctrl+Shift+Z)` : "Nothing to redo"}>↷ Redo</button>
      <${Popover} label="▾" title="Go back or forward to any change" className="history-menu">
        ${(close: () => void) => html`<div class="pop-title">Changes, newest first</div>
          <${Changes} states=${h.states} when=${when}
            onGoto=${(st: HistoryState) => { close(); store.goto(st.seq); }} />
          ${(h.total ?? h.states.length) > h.states.length ? html`<button class="more" onClick=${() => {
            close(); store.setUi({ reportsTab: "history", folds: { ...store.state.ui.folds, lower: false } }); }}>
            ${h.total - h.states.length} older in the History tab</button>` : null}`}
      </${Popover}>
    </span>
    <span class="spacer"></span>
    ${counts.error ? html`<button class="errors" onClick=${showErrors} title="Show the errors in Diagnostics">
        ${counts.error} error${counts.error > 1 ? "s" : ""}</button>` : null}
    <button title="The README and the guide" onClick=${() => store.setUi({ dialog: "help" })}>Help</button>
    <button class="keys-help" title="Keyboard shortcuts (?)" onClick=${() => store.setUi({ dialog: "keys" })}>?</button>
    <button disabled=${!doc.loads} title=${doc.loads ? "Build a .prg for one watch" : "the face does not load"}
            onClick=${() => store.setUi({ dialog: "build" })}>Build…</button>
    <${DownloadMenu} doc=${doc} />
  </div>`;
}

// The face was deleted in another tab: its text can still be copied.
function GoneBanner({ doc }: { doc: Summary }): VNode {
  const store = useEditorStore();
  const [copied, setCopied] = useState<"copied" | "downloaded" | null>(null);
  const copyText = async (): Promise<void> => {
    setCopied(await copyOrDownload(latestText(store.state.yaml.text, null, doc), `${doc.name}.yaml`));
  };
  return html`<div class="banner lost" role="alert">
    <strong>This face was deleted</strong> (in another tab), so changes to it can no longer be saved.
    <button onClick=${copyText} title="The face's text as you last had it, the YAML tab's included">Copy my text</button>
    ${copied ? html`<span class="dim">${copied === "copied" ? "copied" : "downloaded as a file"}</span>` : null}
    <button onClick=${() => go(null)}>Back to the faces</button></div>`;
}

// The left column: the Layers and Face tabs.
function LeftPanel({ doc }: { doc: Summary }): VNode {
  const store = useEditorStore();
  const left = useStore((s) => s.ui.leftTab);
  const faceSection = useStore((s) => s.ui.faceSection);
  const vocab = useStore((s) => s.vocab);
  const selection = useStore((s) => s.selection);
  const frame = useStore((s) => s.frame.current);
  const entered = useStore((s) => s.context.entered);
  // inside an entered element the frame lists its parts: the rows of the face's elements are not dimmed for it
  const drawn = useMemo(() => (frame && !frame.local ? new Set(frame.items.filter((i) => i.drawn).map((i) => i.id)) : null), [frame]);
  const select: OnSelect = (id, mode, owner) => store.select(id, mode, owner);
  const structure = (op: StructureOp): Promise<void> => store.structure(op);
  return html`<div class="panel left">
    <div class="tabs top">
      <button class=${left === "layers" ? "on" : ""} onClick=${() => store.setUi({ leftTab: "layers" })}>Layers</button>
      <button class=${left === "face" ? "on" : ""} onClick=${() => store.setUi({ leftTab: "face" })}>Face</button>
    </div>
    <div class="panel-scroll">${left === "layers"
      ? html`<${Layers} doc=${doc} vocab=${vocab ?? {}} selected=${selection.primary} extra=${selection.extra} drawn=${drawn} entered=${entered}
                        onSelect=${select} onStructure=${structure} onEdit=${(op: EditOp) => store.edit(op)}
                        onEnter=${(path: Path) => store.enter(path)} onExit=${() => store.leave()} />`
      : html`<${FacePanel} doc=${doc} vocab=${vocab ?? {}} onEdit=${(op: EditOp) => store.edit(op)}
                           onUpload=${(file: File, what: Parameters<EditorStore["upload"]>[1]) => store.upload(file, what)}
                           onSelect=${select} onStructure=${structure} onReveal=${(line: number, end: number) => store.reveal(line, end)}
                           section=${faceSection} onSection=${(key: string) => store.setUi({ faceSection: key })} />`}</div>
  </div>`;
}

/** A `display:` class as the Edit for button names it: `amoled` is "AMOLED", `mip` "MIP", `lcd` "LCD". */
const displayName = (cls: string | null | undefined): string => String(cls || "").toUpperCase();

// The controls above the face: the pane, the device, Edit for, the style,
// the Preview popover, the zoom and 1:1.
function Controls({ doc }: { doc: Summary }): VNode {
  const store = useEditorStore();
  const pane = useStore((s) => s.ui.pane);
  const context = useStore((s) => s.context);
  const clock = useStore((s) => s.clock);
  const vocab = useStore((s) => s.vocab);
  const deviceInfo = useStore(deviceInfoOf);
  const real = useStore(realZoomOf);
  const zoom = useStore(zoomOf);
  const skin = useStore((s) => s.view.skin);
  const isReal = useStore((s) => s.view.real);
  const time = context.now ? clock.time : context.time;
  const date = context.now ? clock.date : context.date;
  // the watch's width on this screen at 1:1, when its files give a pixel density (`real` is set then too)
  const mmAcross = deviceInfo ? screenMm(deviceInfo.width, deviceInfo.ppi) : null;
  return html`<div class="controls">
    <span class="seg" title="The face drawn, or its text">
      <button class=${pane === "face" ? "on" : ""} onClick=${() => store.setUi({ pane: "face" })}>Face</button>
      <button class=${pane === "yaml" ? "on" : ""} onClick=${() => store.setUi({ pane: "yaml" })}>YAML</button>
    </span>
    <label>Device
      <select value=${context.device || ""} onChange=${(e: JSX.TargetedEvent<HTMLSelectElement>) => store.setContext({ device: e.currentTarget.value })}>
        ${doc.targets.map((t) => html`<option value=${t}>${t}</option>`)}
      </select></label>
    <${EditFor} target=${context.target} device=${context.device} shape=${deviceInfo?.shape} display=${deviceInfo?.display}
                onTarget=${(t: Scope) => store.setContext({ target: t })} />
    ${doc.styles.length ? html`<label>Style
      <select value=${context.style} onChange=${(e: JSX.TargetedEvent<HTMLSelectElement>) => store.setContext({ style: e.currentTarget.value })}>
        <option value="">default</option>
        ${doc.styles.map((s) => html`<option value=${s.name}>${s.label}</option>`)}
      </select></label>` : null}
    <${PreviewMenu} context=${context} time=${time} date=${date} clock=${clock} slots=${doc.globals.slots || []} vocab=${vocab ?? {}}
                    amoled=${isAmoled(deviceInfo)} hasSkin=${deviceInfo ? deviceInfo.skin : undefined} skin=${skin} />
    <label class="zoom">Zoom
      <input type="range" min=${MIN_ZOOM} max=${MAX_ZOOM} step="0.01" value=${zoom}
             list="zoom-notches" onInput=${(e: JSX.TargetedEvent<HTMLInputElement>) => store.setZoom(Number(e.currentTarget.value))} />
      <datalist id="zoom-notches">
        ${[1, 2, 3].map((n) => html`<option value=${n} />`)}
        ${real !== null ? html`<option value=${real} />` : null}
      </datalist>
      <span class="mono">${zoom.toFixed(zoom < 1 ? 3 : 2)}×</span></label>
    <button class=${isReal && real !== null ? "on" : ""} disabled=${real === null} aria-pressed=${!!(isReal && real !== null)}
            title=${mmAcross !== null ? `the watch's real size, ${mmAcross.toFixed(1)} mm across, on this screen`
                                      : "this watch's files give no pixel density"}
            onClick=${() => store.toggleReal()}>1:1</button>
    <button class="reset" title="Calibrate real size with a bank card" aria-label="Calibrate real size with a bank card" onClick=${() => store.setUi({ dialog: "calibrate" })}>⚙</button>
  </div>`;
}

interface EditForProps {
  target: Scope;
  device: string | null;
  shape: string | undefined;
  display: string | undefined;
  onTarget(target: Scope): void;
}

// Edit for: where a Properties edit or a drag writes `at:`, `size:`,
// `radius:` and `align:` -- the element's own key, for every watch, or its
// override for the watch in view, its screen shape or its display class.
// The three overrides need a watch in view.
function EditFor({ target, device, shape, display, onTarget }: EditForProps): VNode {
  const choices: [Scope, string, string][] = [
    ["all", "all watches", "the element's own key, for every watch"],
    ["device", "this watch", `an override for ${device ?? "the watch in view"} only`],
    ["shape", "this shape", `an override for every ${shape ?? "same-shaped"} watch`],
    ["display", "this display", `an override for every ${display ? displayName(display) : "same-display"} watch`],
  ];
  return html`<span class="seg edit-for" role="radiogroup"
      title="Where a change to at:, size:, radius: or align: is written: the element's own key, or its override for this watch, its shape or its display class"><span class="dim">Edit for</span>
    ${choices.map(([t, label, what]) => html`<button class=${target === t ? "on" : ""} aria-pressed=${target === t} title=${what}
        disabled=${t !== "all" && !device} onClick=${() => onTarget(t)}>${label}</button>`)}
  </span>`;
}

// The slot picks as the frame request spells them.
const picksParamOf = (s: EditorState): string => picksParam(s.context.picks, s.doc ? s.doc.globals.slots : []);

// The centre: the face drawn (or its text), and the strip of targets below.
function Stage({ doc, panZoom }: { doc: Summary; panZoom: PanZoom }): VNode {
  const store = useEditorStore();
  const pane = useStore((s) => s.ui.pane);
  const frame = useStore((s) => s.frame.current);
  const busy = useStore((s) => s.frame.busy);
  const skin = useStore((s) => s.frame.skin);
  const selection = useStore((s) => s.selection);
  const queue = useStore((s) => s.pending.queue);
  const zoom = useStore(zoomOf);
  const context = useStore((s) => s.context);
  const time = useStore(shownTime);
  const date = useStore(shownDate);
  const picks = useStore(picksParamOf);
  return html`<div class="stage">
    <${Controls} doc=${doc} />
    ${pane === "yaml"
      ? html`<${YamlPane} doc=${doc} />`
      : html`<div class="canvas-wrap" ref=${panZoom.wrap} ...${panZoom.handlers}>
          ${busy ? html`<div class="busy">rendering…</div>` : null}
          ${frame ? html`<${Canvas} frame=${frame} selected=${selection.primary} vertex=${selection.vertex}
                                    extra=${selection.extra} tree=${doc.tree} queue=${queue}
                                    zoom=${zoom} skin=${skin && skin.scale === frame.scale ? skin : null}
                                    onPick=${(id: string | null, additive: boolean) => store.select(id, additive)}
                                    onVertex=${(index: number | null) => store.selectVertex(index)}
                                    onDrag=${(ids: string[], gesture: AnyGesture, shown: Shown) => store.drag(ids, gesture, shown)} />`
                  : html`<div class="empty">${doc.loads ? "No frame yet." :
                      "The face does not load, so there is nothing to draw. The diagnostics on the right say why."}</div>`}
        </div>`}
    <${Strip} doc=${doc} view=${{ device: context.device, style: context.style, time, date, now: context.now,
                                  asleep: context.frame === "asleep", aod: context.frame === "aod" }} picks=${picks}
              onDevice=${(d: string) => store.setContext({ device: d })} />
  </div>`;
}

function Dialogs({ doc }: { doc: Summary }): VNode | null {
  const store = useEditorStore();
  const dialog = useStore((s) => s.ui.dialog);
  const palette = useStore((s) => s.ui.palette);
  const vocab = useStore((s) => s.vocab);
  const device = useStore((s) => s.context.device);
  const pxPerInch = useStore((s) => s.view.pxPerInch);
  const close = (): void => store.setUi({ dialog: null });
  return html`
    ${dialog === "build" ? html`<${BuildDialog} doc=${doc} vocab=${vocab ?? {}} device=${device} onClose=${close} />` : null}
    ${dialog === "keys" ? html`<${ShortcutHelp} onClose=${close} />` : null}
    ${palette ? html`<${CommandPalette} doc=${doc} />` : null}
    ${dialog === "help" ? html`<${HelpDialog} start="docs/guide/studio.md" onClose=${close} />` : null}
    ${dialog === "calibrate" ? html`<${CalibrateDialog} current=${pxPerInch} onClose=${close}
        onSave=${(v: number) => { store.setView({ pxPerInch: v }); close(); }} />` : null}`;
}

// The editor's shortcuts and clipboard: each action reads the state as it
// is at the key press, and is unavailable (the browser keeps the key) when
// the state has nothing for it to act on.
function useEditorKeys(store: EditorStore, panZoom: PanZoom): void {
  const s = (): EditorState => store.state;
  const tree = (): TreeBlock[] => s().doc?.tree ?? [];
  const chosen = (): string[] => chosenIds(s().selection);
  // the selected element, for the structural shortcuts; a hand or a part selected is none
  const element = (): TreeNode | null => { const node = elementOf(s()); return node && node.kind === "element" ? node : null; };
  // the face and its frame, while the Face pane shows them
  const onFace = (): { frame: NonNullable<EditorState["frame"]["current"]>; doc: Summary } | null => {
    const { ui, frame, doc } = s();
    return ui.pane === "face" && frame.current && doc ? { frame: frame.current, doc } : null;
  };
  const structure = (op: StructureOp | null): false | undefined => { if (!op) return false; void store.structure(op); return undefined; };
  // the zoom that shows the whole watch in the space round it
  const fit = (): false | undefined => {
    const info = deviceInfoOf(s()), frame = s().frame.current;
    const box = panZoom.wrap.current, w = frame ? frame.width : info && info.width;
    const h = frame ? frame.height : info && info.height;
    if (!box || !w || !h) return false;
    store.setZoom(Math.min(box.clientWidth / w, box.clientHeight / h) * 0.9);
    return undefined;
  };
  useShortcuts({
    undo: () => store.undo(),
    redo: () => store.redo(),
    duplicate: () => { const el = element(); return structure(el ? { op: "duplicate", path: el.path } : null); },
    selectAll: () => (onFace() ? (store.selectAll(), undefined) : false),
    // a pixel, ten with Shift, written as a drag would be
    nudge: (dx: number, dy: number): boolean => {
      const face = onFace(), ids = chosen();
      if (!face || !ids.length) return false;
      const item = ids.length > 1 ? together(face.frame.items, ids) : face.frame.items.find((i) => i.id === ids[0]);
      if (!item || !item.box) return false;
      store.moveAll(ids, dx, dy, { item, moving: movedBy(face.doc.tree, ids) });
      return true;
    },
    // a picked vertex of the selected polygon goes; else the whole selection, as one change
    remove: (): false | undefined => {
      const { selection } = s();
      const face = onFace();
      if (selection.vertex !== null && selection.primary && face) {
        const item = face.frame.items.find((i) => i.id === selection.primary);
        if (!item) return false;
        const gesture: PointGesture = { kind: "remove_vertex", index: selection.vertex };
        store.drag([item.id], gesture, { item, moving: new Set([item.id]), preview: gesture });
        store.selectVertex(null);
        return undefined;
      }
      return element() ? structure(deleteOp(tree(), chosen())) : false;
    },
    group: () => {
      const nodes = blocksOf(tree()).nodes;
      const paths = chosen().flatMap((id) => { const n = nodes.find((node) => node.id === id); return n ? [n.path] : []; });
      return paths.length ? structure({ op: "group", paths }) : false;
    },
    ungroup: () => { const el = element(); return el && el.type === "group" ? structure({ op: "ungroup", path: el.path }) : false; },
    forward: () => { const el = element(); return el ? structure(stepOp(tree(), el.path, 1)) : false; },
    backward: () => { const el = element(); return el ? structure(stepOp(tree(), el.path, -1)) : false; },
    zoom: (by: number) => store.setZoom(zoomOf(s()) * (by > 0 ? 1.25 : 0.8)),
    zoomFit: fit,
    zoomReal: (): false | undefined => { if (realZoomOf(s()) === null) return false; store.toggleReal(); return undefined; },
    // the help, or an open menu or dialog, closes first; then an entered element is left; then the selection goes
    deselect: (): false | undefined => {
      const { ui, context } = s();
      if (ui.palette) { store.setUi({ palette: false }); return undefined; }
      if (ui.dialog === "keys") { store.setUi({ dialog: null }); return undefined; }
      if (ui.dialog || document.querySelector(".popover-body:popover-open, .modal-back")) return false;
      if (context.entered !== null) { store.leave(); return undefined; }
      if (!chosen().length) return false;
      store.deselect();
      return undefined;
    },
    help: () => store.setUi({ dialog: s().ui.dialog === "keys" ? null : "keys" }),
    commandPalette: () => store.setUi({ palette: !s().ui.palette }),
  });
  // Copied elements are their YAML, so they paste into another face, or
  // into a text editor. A paste goes in front of the selection, in its
  // block, or at the front of elements:.
  useClipboard({
    copy: (): string | null => {
      const { doc } = s(), ids = chosen();
      if (!doc || !ids.length) return null;
      const text = elementsYaml(doc.text, doc.tree, ids);
      if (text) store.notice(`copied ${ids.length > 1 ? `${ids.length} elements` : ids[0]}`);
      return text || null;
    },
    cut: () => { structure(deleteOp(tree(), chosen())); },
    paste: (text: string) => {
      const { doc } = s();
      if (!doc) return;
      const node = element();
      const block: Path = node ? node.path.slice(0, -1) : ["elements"];
      const siblings = node ? siblingsOf(doc.tree, node.path) : [];
      const before = node ? siblings[siblings.indexOf(node.id) + 1] || null : null;
      void store.structure({ op: "paste", text, block, before });
    },
  });
}

function Editor(): VNode {
  const store = useEditorStore();
  const doc = useStore((s) => s.doc);
  const gone = useStore((s) => s.gone);
  const pane = useStore((s) => s.ui.pane);
  const zoom = useStore(zoomOf);
  const panels = useStore((s) => s.view.panels);
  const folds = useStore((s) => s.ui.folds);
  const panZoom: PanZoom = usePanZoom({ zoom, setZoom: (z) => store.setZoom(z), active: pane === "face", onBackground: () => store.deselect() });
  useEditorKeys(store, panZoom);
  if (!doc) return html`<div class="home dim">Loading…</div>`;
  const panelWidth = (side: keyof EditorState["view"]["panels"]) => (w: number): void => store.setView({ panels: { ...store.state.view.panels, [side]: w } });
  return html`<div class="editor">
    <div>
      <${TopBar} doc=${doc} />
      ${gone ? html`<${GoneBanner} doc=${doc} />` : null}
      <${Missing} doc=${doc} />
    </div>
    <div class="columns" style=${`grid-template-columns:${panels.left}px auto minmax(0, 1fr) auto ${panels.right}px`}>
      <${LeftPanel} doc=${doc} />
      <${Splitter} width=${panels.left} sign=${1} fallback=${PANEL_DEFAULTS.left} onWidth=${panelWidth("left")} />
      <${Stage} doc=${doc} panZoom=${panZoom} />
      <${Splitter} width=${panels.right} sign=${-1} fallback=${PANEL_DEFAULTS.right} onWidth=${panelWidth("right")} />
      <div class=${"panel right" + (folds.props ? " props-folded" : "") + (folds.lower ? " lower-folded" : "")}>
        <${PropertiesSection} doc=${doc} />
        <${ReportsSection} doc=${doc} />
      </div>
    </div>
    <${Dialogs} doc=${doc} />
  </div>`;
}

// -- the app -------------------------------------------------------------------------

interface MessageLogProps {
  /** Newest first. */
  log: Message[];
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

function Shell(): VNode {
  const store = useEditorStore();
  const docId = useStore((s) => s.docId);
  const messages = useStore((s) => s.messages);
  const toast = messages.toast;
  return html`
    ${docId ? html`<${Editor} />` : html`<${Home} />`}
    ${toast ? html`<div class=${"toast " + toast.kind} role=${toast.kind === "error" ? "alert" : "status"}
                        onClick=${() => store.dismissToast()}>${toast.message}</div>` : null}
    <${MessageLog} log=${messages.log} unseen=${messages.unseen} onOpen=${() => store.seenMessages()}
                   onClear=${() => store.clearMessages()} />
    <${AskHost} />`;
}

// The app: one store for its life, opened on the face the address names
// and following the address as it changes.
export function App(): VNode {
  const store = useMemo(() => new EditorStore(route()), []);
  useEffect(() => {
    const onHash = (): void => store.open(route());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, [store]);
  return html`<${StoreProvider} value=${store}><${Shell} /></${StoreProvider}>`;
}
