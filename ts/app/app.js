// wfb studio's front end. The page asks and shows; its worker
// (`api.js`) holds the face's text and runs the compiler, so nothing here
// decides what a face looks like: every image comes from the worker's
// renderer.

import { html, render, useState, useEffect, useRef, useCallback, useMemo }
  from "./vendor/preact-htm.module.js";
import { api, download, listen, saveBlob } from "./api.js";
import { clockNow, useClipboard, useFold, useFrame, useOutbox, usePanZoom, useShortcuts } from "./hooks.js";
import { flatten, movedBy, rangeIds, selectAll, together } from "./hit.js";
import { AddName, InlineName, Popover, WorkerImage } from "./ui.js";
import { newer, saveState } from "./outbox.js";
import { Canvas, Strip } from "./canvas.js";
import { Layers } from "./layers.js";
import { YamlPane } from "./yaml.js";
import { AskHost, BuildDialog, CalibrateDialog, Modal, ask } from "./dialogs.js";
import { HelpDialog } from "./help.js";
import { SHORTCUTS } from "./keys.js";
import { CSS_PX_PER_INCH, MAX_ZOOM, MIN_ZOOM, clampZoom, realZoom, screenMm, serverScale } from "./zoom.js";

// What this browser remembers between visits: the zoom, how many CSS
// pixels make a real inch on its screen, and the side panels' widths.
function stored(key, fallback) {
  try { const v = Number(localStorage.getItem(key)); return v > 0 ? v : fallback; } catch (_) { return fallback; }
}
const storedZoom = () => clampZoom(stored("wfb-zoom", 2));
const storedPxPerInch = () => stored("wfb-css-px-per-inch", CSS_PX_PER_INCH);
const PANEL_MIN = 180;
const PANEL_MAX = 720;
const clampPanel = (w) => Math.round(Math.min(PANEL_MAX, Math.max(PANEL_MIN, w)));
const storedPanels = () => ({ left: clampPanel(stored("wfb-panel-left", 280)),
                              right: clampPanel(stored("wfb-panel-right", 340)) });

// The edge between a side panel and the centre: dragged, it sets the
// panel's width (`sign` is +1 when the panel lies left of the edge);
// a double click puts the default back.
function Splitter({ width, sign, fallback, onWidth }) {
  const start = useRef(null);
  return html`<div class="splitter" title="drag to resize; double-click to reset"
    onPointerDown=${(e) => { e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId);
                             start.current = { x: e.clientX, width }; }}
    onPointerMove=${(e) => { if (start.current) onWidth(clampPanel(start.current.width + sign * (e.clientX - start.current.x)), false); }}
    onPointerUp=${() => { if (start.current) { start.current = null; onWidth(width, true); } }}
    onDblClick=${() => onWidth(fallback, true)}></div>`;
}
import { FacePanel, Inspector } from "./panels.js";
import { typeLabel } from "./values.js";
import { Diagnostics, diagnosticsLabel } from "./diagnostics.js";
import { blocksOf, deleteOp, elementsYaml, siblingsOf, stepOp } from "./tree.js";
import { TAB } from "./session.js";
import { latestText } from "./textsync.js";

// `text` on the clipboard, or, where the page may not write it (a
// browser that refuses, or a page served over plain http from another
// machine), downloaded as `filename`: "copied" or "downloaded".
async function copyOrDownload(text, filename) {
  try {
    await navigator.clipboard.writeText(text);
    return "copied";
  } catch (_) {
    saveBlob(new Blob([text], { type: "text/yaml" }), filename);
    return "downloaded";
  }
}


function route() {
  const m = location.hash.match(/^#\/face\/([0-9a-f]{32})$/);
  return m ? m[1] : null;
}

function go(docId) {
  location.hash = docId ? `#/face/${docId}` : "#/";
}

function useEvents(onEvent) {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  useEffect(() => {
    return listen((event, data) => handler.current(event, data));
  }, []);
}

function ago(seconds) {
  const s = Math.max(0, Date.now() / 1000 - seconds);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(seconds * 1000).toLocaleDateString();
}

// -- home ----------------------------------------------------------------------------

function Home({ onError }) {
  const [home, setHome] = useState(null);
  const [template, setTemplate] = useState("minimal");
  const [name, setName] = useState("My Face");
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [help, setHelp] = useState(false);
  const fileInput = useRef(null);

  const load = useCallback(() => api("home").then(setHome, onError), []);
  useEffect(() => { load(); }, []);
  // another tab deleted or renamed a face
  useEvents((name) => { if (name === "created" || name === "deleted" || name === "renamed") load(); });
  const [renaming, setRenaming] = useState(null);
  const rename = async (doc, to) => {
    setRenaming(null);
    try { await api("rename", { id: doc.id, name: to }); load(); }
    catch (e) { onError(e); }
  };

  const create = async () => {
    setBusy(true);
    try {
      const doc = await api("new", { template, name });
      go(doc.id);
    } catch (e) { onError(e); } finally { setBusy(false); }
  };

  const upload = async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      const doc = await api("upload", { filename: file.name }, file);
      go(doc.id);
    } catch (e) { onError(e); } finally { setBusy(false); }
  };

  const remove = async (doc) => {
    if (!await ask(`Delete "${doc.name}" and its whole history? This cannot be undone.`, "Delete")) return;
    try { await api("delete", { id: doc.id }); load(); }
    catch (e) { onError(e); }
  };

  if (!home) return html`<div class="home dim">Loading…</div>`;
  const blurb = (home.templates.find((t) => t.name === template) || {}).blurb;
  return html`
    <div class="home">
      <h1>wfb studio <button class="help-open" onClick=${() => setHelp(true)} title="The README and the guide">Help</button></h1>
      <div class="dim">Create a watch face, or open one to edit. Download it to save.</div>
      ${help ? html`<${HelpDialog} start="README.md" onClose=${() => setHelp(false)} />` : null}
      <div class="cards">
        <div class="card">
          <h2>New face</h2>
          <label>Start from</label>
          <select value=${template} onChange=${(e) => setTemplate(e.target.value)}>
            ${home.templates.map((t) => html`<option value=${t.name}>${t.name}</option>`)}
          </select>
          <div class="dim small blurb">${blurb}</div>
          <label>Name</label>
          <input type="text" value=${name} onInput=${(e) => setName(e.target.value)} />
          <div class="row"><button class="primary" disabled=${busy} onClick=${create}>Create</button></div>
        </div>
        <div class="card">
          <h2>Open</h2>
          <div class=${"drop" + (over ? " over" : "")}
               onDragOver=${(e) => { e.preventDefault(); setOver(true); }}
               onDragLeave=${() => setOver(false)}
               onDrop=${(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files[0]); }}>
            Drop a <code>.zip</code> (face.yaml + assets/) or a <code>.yaml</code> here
            <div class="row center">
              <button disabled=${busy} onClick=${() => fileInput.current.click()}>Choose file…</button>
            </div>
          </div>
          <input type="file" accept=".zip,.yaml,.yml" hidden ref=${fileInput}
                 onChange=${(e) => upload(e.target.files[0])} />
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
                          suggest=${() => d.name} valid=${(t) => t.length > 0}
                          onAdd=${(to) => rename(d, to)} onCancel=${() => setRenaming(null)} />`
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

function Missing({ doc, onSend }) {
  if (!doc.missing.length) return null;
  const add = (reference, file) => {
    if (file) onSend({ op: "assets", args: { filename: file.name, reference }, body: file });
  };
  return html`<div class="banner">
    <strong>Missing files:</strong>
    ${doc.missing.map((ref) => html`<span class="file">
      <code>${ref}</code>
      <label><button onClick=${(e) => e.currentTarget.nextElementSibling.click()}>Add…</button>
        <input type="file" accept=".ttf,.otf" hidden
               onChange=${(e) => add(ref, e.target.files[0])} /></label>
    </span>`)}
    <span class="dim">The face does not draw until every font file is added.</span>
  </div>`;
}

// The line of history, newest first: the current change marked, those
// past it (redo) dimmed; a click goes back or forward to that change in
// one step (`goto`).
function Changes({ states, onGoto, when }) {
  return html`<ul class="states">
    ${states.map((s) => html`<li class=${(s.current ? "current" : "") + (s.redo ? " redo" : "")}>
      <button class="state" disabled=${s.current} onClick=${() => onGoto(s)}
              title=${s.current ? "the face is here" : s.redo ? "go forward to this change" : "go back to this change"}>
        <span class="label">${s.label}</span><span class="dim">${when(s.time)}</span></button>
    </li>`)}
  </ul>`;
}

const when = (t) => new Date(t * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" });

function History({ doc, onChanged, onSend, onOpen, onError }) {
  const h = doc.history;
  const post = async (op, args = {}) => {
    try { return await api(op, { id: doc.id, ...args }); }
    catch (e) { onError(e); return null; }
  };
  // the summary lists the newest changes; once asked, all of them, kept
  // up to date while the tab is open
  const [wantAll, setWantAll] = useState(false);
  const [all, setAll] = useState(null);
  useEffect(() => { setWantAll(false); setAll(null); }, [doc.id]);
  useEffect(() => {
    if (!wantAll) return;
    let live = true;
    api("history", { id: doc.id }).then((got) => { if (live) setAll(got); }, onError);
    return () => { live = false; };
  }, [wantAll, doc.id, doc.version]);
  const states = all && all.version === doc.version ? all.states : h.states;
  const total = h.total ?? h.states.length;
  const restore = (s) => onSend({ op: "restore", args: { snapshot: s.name } });
  const copy = async (s) => {
    const created = await post("copy", { snapshot: s.name });
    if (created) onOpen(created.id);
  };
  const snapshotNow = async () => { if (await post("snapshot")) onChanged(null); };
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
    <${Changes} states=${states} when=${when} onGoto=${(s) => onSend({ op: "goto", args: { seq: s.seq } })} />
    ${states.length < total ? html`<div class="row">
      <button onClick=${() => setWantAll(true)} title="Only the newest changes are listed">Show all ${total} changes</button>
    </div>` : null}
  </div>`;
}

function DownloadMenu({ doc, onError }) {
  const save = (form) => download("download", { id: doc.id, form }).catch(onError);
  return html`<div class="menu">
    <button class="primary" onClick=${() => save("auto")}>Download</button>
    <${Popover} label="▾" title="Choose the format" align="right" bodyClass="menu-items">${(close) => html`
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

// Every shortcut, for "?" and the top bar's button.
function ShortcutHelp({ onClose }) {
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

function Editor({ docId, onError, onNotice }) {
  const [doc, setDoc] = useState(null);
  const [selected, setSelected] = useState(null);
  // more elements selected with Ctrl/Cmd (or Shift on the face), for
  // moving, deleting or grouping together
  const [extra, setExtra] = useState([]);
  const [view, setView] = useState({ device: null, style: "", time: "", date: "", now: false, asleep: false,
                                     aod: false, skin: false, zoom: storedZoom() });
  // the worker draws at a whole scale; the browser shows it at the zoom
  const scale = serverScale(view.zoom, window.devicePixelRatio || 1);
  const [pxPerInch, setPxPerInch] = useState(storedPxPerInch());
  const [dialog, setDialog] = useState(null);           // "build" | "calibrate" | "keys"
  const [vocab, setVocab] = useState({});
  // the face's slots, which the Preview popover picks a type for
  const slots = (doc && doc.globals && doc.globals.slots) || [];
  useEffect(() => { api("vocabulary").then(setVocab, onError); }, []);
  const [left, setLeft] = useState("layers");
  const [pane, setPane] = useState("face");
  const [tab, setTab] = useState("diagnostics");
  // the Diagnostics tab's severity filter, kept across tabs, reset per face
  const [diagFilter, setDiagFilter] = useState("all");
  const [fold, setFolded] = useFold();
  // where an inspector edit or a drag writes geometry: "all" (a drag then
  // writes where the viewed device reads it), the device, or its shape
  const [scope, setScope] = useState("all");

  // A face from the worker, shown unless it is older than the one shown
  // (`outbox.newer`): answers can arrive out of order. An answer about
  // another face (one left while its change was on its way) is dropped.
  const docIdRef = useRef(docId);
  docIdRef.current = docId;
  const accept = useCallback((d) => {
    if (d.id !== docIdRef.current) return;
    setDoc((current) => (newer(current, d) ? d : current));
  }, []);
  const loadDoc = useCallback(() => api("get", { id: docId }).then(accept, (e) => {
    onError(e);
    if (e.status === 404) go(null);
  }), [docId]);
  useEffect(() => { setDoc(null); setSelected(null); setExtra([]); setDiagFilter("all"); loadDoc(); }, [docId]);

  // The device defaults to the first target, and is kept while it stays one.
  useEffect(() => {
    if (doc && (!view.device || !doc.targets.includes(view.device)) && doc.targets.length) {
      setView((v) => ({ ...v, device: doc.targets[0] }));
    }
  }, [doc]);
  const deviceInfo = (vocab.devices || []).find((d) => d.id === view.device);
  const { frame, busy, skin, clock, setClock, time, date, picks } = useFrame({ docId, doc, view, scale, deviceInfo, onError });
  const real = deviceInfo ? realZoom(deviceInfo.ppi, pxPerInch) : null;
  // the slider's steps are hundredths; real size is set exactly
  const setZoom = (z, exact = false) => {
    const zoom = clampZoom(exact ? z : Math.round(z * 100) / 100);
    try { localStorage.setItem("wfb-zoom", String(zoom)); } catch (_) { /* private mode */ }
    setView((v) => ({ ...v, zoom }));
  };

  // the device and scope a gesture is written for, as they were when it was made
  const where = useRef({});
  where.current = { device: view.device, scope: scope === "all" ? "auto" : scope };
  const { queue, queued, onDrag, send } = useOutbox({ docId, doc, frame, where, accept, reload: loadDoc, onError, onNotice });
  const step = useCallback((which) => send({ op: which }), [send]);
  // One edit from the inspector or the Face panel: the worker patches the
  // text, checks it and answers with the face; a refusal says why.
  const edit = useCallback((op) => send({ op: "edit", args: { edit: op } }), [send]);
  const upload = useCallback((file, { font, size, reference }) => {
    const args = { filename: file.name };
    if (font) { args.font = font; args.size = size || "10%r"; }
    if (reference) args.reference = reference;
    return send({ op: "assets", args, body: file });
  }, [send]);
  // One structural edit from the Layers panel: the worker patches the text,
  // checks it and answers with the face and what to select.
  const structure = useCallback(async (op) => {
    const updated = await send({ op: "structure", args: { edit: op } });
    if (!updated) return;
    if (op.op === "delete") setSelected(null);
    else if (updated.select) setSelected(updated.select);
    setExtra([]);
  }, [send]);

  // the face was deleted (in another tab): editing it can no longer be saved
  const [gone, setGone] = useState(false);
  useEffect(() => { setGone(false); }, [docId]);
  useEvents((name, data) => {
    if (name === "error" && (!data.id || data.id === docId)) onError(new Error(data.message));
    if (!doc || data.id !== docId) return;
    if (name === "deleted") setGone(true);
    else if (name === "renamed") setDoc((d) => (d && d.id === data.id ? { ...d, name: data.name } : d));
    // this tab's own change reaches it with the answer to its request
    else if ((name === "changed" && data.tab !== TAB && data.version > doc.version)
             || name === "snapshot") loadDoc();
  });

  const element = useMemo(() => doc && selected && flatten(doc.tree).find((n) => n.id === selected),
                          [doc, selected]);
  // The YAML tab's own save state (`YamlPane`'s `onSaving`); every other
  // change is in the outbox.
  const [yamlSaving, setYamlSaving] = useState("idle");
  useEffect(() => { setYamlSaving("idle"); }, [docId]);
  // where the YAML tab was, per face, while the editor is open
  const yamlMemory = useRef({});
  const [copied, setCopied] = useState(null);
  const copyText = async () => {
    const box = (yamlMemory.current[docId] || {}).text;
    const text = latestText(box && box.pane ? box.pane.text() : null, box ? box.left : null, doc);
    setCopied(await copyOrDownload(text, `${doc.name}.yaml`));
  };
  const [panels, setPanels] = useState(storedPanels());
  // `save`: the drag is over, so the browser keeps the width
  const panelWidth = (side) => (w, save) => {
    setPanels((p) => ({ ...p, [side]: w }));
    if (save) { try { localStorage.setItem(`wfb-panel-${side}`, String(w)); } catch (_) { /* private mode */ } }
  };
  // lines the YAML tab is asked to select, from a link elsewhere
  const [reveal, setReveal] = useState(null);
  const showLines = useCallback((line, end) => { setReveal({ line, end, at: Date.now() }); setPane("yaml"); }, []);

  // `mode`: falsy selects `id` alone; "range" (Shift in the layers) selects
  // every element from the selection to it; anything else toggles it in
  // the selection
  const select = useCallback((id, mode) => {
    if (mode === "range" && selected && doc) {
      const ids = rangeIds(doc.tree, selected, id);
      const first = ids.includes(selected) ? selected : ids[0];
      setSelected(first || null); setExtra(ids.filter((x) => x !== first));
    } else if (mode && selected && id !== selected) {
      setExtra((xs) => (xs.includes(id) ? xs.filter((x) => x !== id) : [...xs, id]));
    } else { setSelected(id); setExtra([]); }
  }, [selected, doc]);
  const deselect = useCallback(() => { setSelected(null); setExtra([]); }, []);
  const chosen = [selected, ...extra].filter(Boolean);
  const onFace = pane === "face" && frame && doc;
  const nodes = doc ? blocksOf(doc.tree).nodes : [];
  const chosenPaths = chosen.map((id) => nodes.find((n) => n.id === id)).filter(Boolean).map((n) => n.path);
  // the zoom that shows the whole watch in the space round it
  const fit = () => {
    const box = panZoom.wrap.current, w = frame ? frame.width : deviceInfo && deviceInfo.width;
    const h = frame ? frame.height : deviceInfo && deviceInfo.height;
    if (!box || !w || !h) return false;
    setZoom(Math.min(box.clientWidth / w, box.clientHeight / h) * 0.9);
  };
  useShortcuts({
    undo: () => step("undo"),
    redo: () => step("redo"),
    duplicate: element ? () => structure({ op: "duplicate", path: element.path }) : null,
    // everything the frame shows, a group standing for its children
    selectAll: onFace ? () => {
      const ids = selectAll(doc.tree, new Set(frame.items.map((i) => i.id)));
      setSelected(ids[0] || null); setExtra(ids.slice(1));
    } : null,
    // a pixel, ten with Shift, written as a drag would be
    nudge: onFace && chosen.length ? (dx, dy) => {
      const item = chosen.length > 1 ? together(frame.items, chosen) : frame.items.find((i) => i.id === chosen[0]);
      if (!item || !item.box) return false;
      const gesture = { kind: "move", part: "both", dx, dy };
      onDrag(chosen, gesture, { item, moving: movedBy(doc.tree, chosen), preview: gesture });
      return true;
    } : null,
    // the whole selection, as one change
    remove: element ? () => { const op = deleteOp(doc.tree, chosen); if (op) structure(op); } : null,
    group: chosenPaths.length ? () => structure({ op: "group", paths: chosenPaths }) : null,
    ungroup: element && element.type === "group" ? () => structure({ op: "ungroup", path: element.path }) : null,
    forward: element ? () => { const op = stepOp(doc.tree, element.path, 1); if (op) structure(op); } : null,
    backward: element ? () => { const op = stepOp(doc.tree, element.path, -1); if (op) structure(op); } : null,
    zoom: (by) => setZoom(view.zoom * (by > 0 ? 1.25 : 0.8)),
    zoomFit: fit,
    zoomReal: () => { if (!real) return false; setZoom(real, true); },
    // the help, or a popover, closes first
    deselect: () => {
      if (dialog === "keys") { setDialog(null); return; }
      if (dialog || document.querySelector(".popover-body, .modal-back")) return false;
      if (!chosen.length) return false;
      deselect();
    },
    help: () => setDialog(dialog === "keys" ? null : "keys"),
  });
  // Copied elements are their YAML, so they paste into another face, or
  // into a text editor. A paste goes in front of the selection, in its
  // block, or at the front of elements:.
  useClipboard({
    copy: () => {
      if (!doc || !chosen.length) return null;
      const text = elementsYaml(doc.text, doc.tree, chosen);
      if (text) onNotice(`copied ${chosen.length > 1 ? `${chosen.length} elements` : chosen[0]}`);
      return text || null;
    },
    cut: () => { const op = deleteOp(doc.tree, chosen); if (op) structure(op); },
    paste: (text) => {
      if (!doc) return;
      const node = element || null;
      const block = node ? node.path.slice(0, -1) : ["elements"];
      const siblings = node ? siblingsOf(doc.tree, node.path) : [];
      const before = node ? siblings[siblings.indexOf(node.id) + 1] || null : null;
      structure({ op: "paste", text, block, before });
    },
  });

  // the top bar's error count: Diagnostics, open, showing the errors
  const showErrors = () => { setTab("diagnostics"); setDiagFilter("error"); setFolded("lower", false); };
  const panZoom = usePanZoom({ zoom: view.zoom, setZoom, active: pane === "face", onBackground: deselect });

  const drawn = useMemo(() => frame && new Set(frame.items.filter((i) => i.drawn).map((i) => i.id)), [frame]);
  const box = useMemo(() => {
    const item = frame && frame.items.find((i) => i.id === selected);
    return item && item.box;
  }, [frame, selected]);

  if (!doc) return html`<div class="home dim">Loading…</div>`;
  const set = (key) => (e) => setView({ ...view, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const saved = saveState({ queue, yaml: yamlSaving });
  const counts = doc.diagnostics.reduce((a, d) => ({ ...a, [d.severity]: (a[d.severity] || 0) + 1 }), {});
  const h = doc.history;
  // what the Preview button's label says is set: whatever is not the default
  const previewed = [
    view.now ? "now" : [time && time.slice(0, 5), date].filter(Boolean).join(" "),
    ...slots.filter((sl) => (view.picks || {})[sl.name] && view.picks[sl.name] !== sl.default)
      .map((sl) => typeLabel(vocab, view.picks[sl.name])),
    view.asleep && "asleep", view.aod && "AOD", view.skin && "skin",
  ].filter(Boolean);

  return html`<div class="editor">
    <div>
      <div class="topbar">
        <button onClick=${() => go(null)} title="All faces">← Faces</button>
        <span class="title"><${InlineName} value=${doc.name} className="name" valid=${(t) => t.length > 0}
          why="a face's name cannot be empty" title="click to rename the face"
          onRename=${async (to) => {
            try { const r = await api("rename", { id: doc.id, name: to });
                  setDoc((d) => ({ ...d, name: r.name })); }
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
            ${(close) => html`<div class="pop-title">Changes, newest first</div>
              <${Changes} states=${h.states} when=${when}
                onGoto=${(st) => { close(); send({ op: "goto", args: { seq: st.seq } }); }} />
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
                               onSelect=${select} onStructure=${structure} onReveal=${showLines} />`}</div>
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
          <${Popover} label=${html`Preview${previewed.length ? html`<span class="set"> · ${previewed.join(" · ")}</span>` : null} ▾`}
                      title="What the face is drawn at: the time and date, each slot's reading, asleep, AOD, the skin"
                      className="preview">
            <div class="preview-grid">
              <label>Time <input type="time" step="1" value=${time} disabled=${view.now} onChange=${set("time")} /></label>
              <label title="the day the date is drawn at; empty, a sample day">Date
                <input type="date" value=${date} disabled=${view.now} onChange=${set("date")} /></label>
              <label title="draw the face at this computer's time and date, as it goes on">
                <input type="checkbox" checked=${view.now}
                       onChange=${(e) => {
                         // switched off, the face stays at the moment it last drew
                         if (e.target.checked) { setClock(clockNow()); setView({ ...view, now: true }); }
                         else setView({ ...view, now: false, time: clock.time, date: clock.date });
                       }} /> now</label>
              ${slots.map((sl) => html`<label title=${`what the slot ${sl.name} is drawn showing; the wearer picks it on the watch`}>${sl.name}
                <select value=${(view.picks || {})[sl.name] || sl.default}
                        onChange=${(e) => setView({ ...view, picks: { ...(view.picks || {}), [sl.name]: e.target.value } })}>
                  ${(Array.isArray(sl.choices) ? sl.choices.map((c) => c.type) : (vocab.complication_types || []).map((t) => t.name))
                    .map((t) => html`<option value=${t}>${t === sl.default ? `${typeLabel(vocab, t)} (first)` : typeLabel(vocab, t)}</option>`)}
                </select></label>`)}
              <label><input type="checkbox" checked=${view.asleep} onChange=${set("asleep")} /> asleep</label>
              <label><input type="checkbox" checked=${view.aod} onChange=${set("aod")} /> AOD</label>
              <label title=${deviceInfo && !deviceInfo.skin ? "this watch's files have no skin" : "the watch drawn round the screen"}>
                <input type="checkbox" checked=${view.skin} disabled=${deviceInfo && !deviceInfo.skin}
                       onChange=${set("skin")} /> skin</label>
              ${previewed.length ? html`<button class="reset-preview" onClick=${() => setView({ ...view, time: "", date: "", now: false,
                  picks: {}, asleep: false, aod: false, skin: false })}>Back to the sample moment</button>` : null}
            </div>
          </${Popover}>
          <label class="zoom">Zoom
            <input type="range" min=${MIN_ZOOM} max=${MAX_ZOOM} step="0.01" value=${view.zoom}
                   list="zoom-notches" onInput=${(e) => setZoom(Number(e.target.value))} />
            <datalist id="zoom-notches">
              ${[1, 2, 3].map((n) => html`<option value=${n} />`)}
              ${real ? html`<option value=${real} />` : null}
            </datalist>
            <span class="mono">${view.zoom.toFixed(view.zoom < 1 ? 3 : 2)}×</span></label>
          <button class=${real && Math.abs(view.zoom - real) < 0.005 ? "on" : ""} disabled=${!real}
                  title=${real ? `the watch's real size, ${screenMm(deviceInfo.width, deviceInfo.ppi).toFixed(1)} mm across, on this screen`
                               : "this watch's files give no pixel density"}
                  onClick=${() => setZoom(real, true)}>1:1</button>
          <button class="reset" title="Calibrate real size with a bank card" aria-label="Calibrate real size with a bank card" onClick=${() => setDialog("calibrate")}>⚙</button>
        </div>
        ${pane === "yaml"
          ? html`<${YamlPane} doc=${doc} selected=${selected} reveal=${reveal} memory=${yamlMemory.current[docId] ||= {}} onDoc=${accept} onError=${onError} onSaving=${setYamlSaving}
                              onSelect=${(id) => { setSelected(id); setExtra([]); }} />`
          : html`<div class="canvas-wrap" ref=${panZoom.wrap} ...${panZoom.handlers}>
              ${busy ? html`<div class="busy">rendering…</div>` : null}
              ${frame ? html`<${Canvas} frame=${frame} selected=${selected}
                                        extra=${extra} tree=${doc.tree} queue=${queue}
                                        zoom=${view.zoom} skin=${skin && skin.scale === frame.scale ? skin : null}
                                        onPick=${select} onDrag=${onDrag} />`
                      : html`<div class="empty">${doc.loads ? "No frame yet." :
                          "The face does not load, so there is nothing to draw. The diagnostics on the right say why."}</div>`}
            </div>`}
        <${Strip} doc=${doc} view=${{ ...view, time, date }} picks=${picks}
                  onDevice=${(d) => setView({ ...view, device: d })} />
      </div>
      <${Splitter} width=${panels.right} sign=${-1} fallback=${340} onWidth=${panelWidth("right")} />
      <div class=${"panel right" + (fold.props ? " props-folded" : "") + (fold.lower ? " lower-folded" : "")}>
        <section class="props-section">
          <h3 class="fold" onClick=${() => setFolded("props", !fold.props)} aria-expanded=${!fold.props}
              title=${fold.props ? "Show the selection's properties" : "Fold the properties away"}>
            ${fold.props ? "▸" : "▾"} Properties${extra.length ? html` <span class="dim">· ${extra.length + 1} selected</span>` : null}</h3>
          ${fold.props ? null : html`<div class="section-scroll">
            ${element ? html`<div class="body dim where">
                in <code>${element.path.slice(0, -1).join(".")}</code>, line ${element.line}
                ${box ? html` · ${box[2]}×${box[3]} px at (${box[0]}, ${box[1]})` : ""}
                ${!box && drawn && element.type !== "group" ? " · not drawn in this frame" : ""}
              </div>` : null}
            <${Inspector} doc=${doc} element=${element} device=${view.device} vocab=${vocab}
                          scope=${scope} onScope=${setScope} onEdit=${edit} onError=${onError}
                          onReveal=${showLines} onSelect=${select} />
          </div>`}
        </section>
        <section class="lower-section">
          <div class="tabs">
            <button class=${tab === "diagnostics" && !fold.lower ? "on" : ""}
                    onClick=${() => { setTab("diagnostics"); setFolded("lower", false); }}>
              ${diagnosticsLabel(doc.diagnostics, diagFilter)}</button>
            <button class=${tab === "history" && !fold.lower ? "on" : ""}
                    onClick=${() => { setTab("history"); setFolded("lower", false); }}>History</button>
            <button class="fold-button" onClick=${() => setFolded("lower", !fold.lower)} aria-expanded=${!fold.lower}
                    title=${fold.lower ? "Show Diagnostics and History" : "Fold Diagnostics and History away"}>
              ${fold.lower ? "▴" : "▾"}</button>
          </div>
          ${fold.lower ? null : html`<div class="section-scroll">${tab === "diagnostics"
            ? html`<${Diagnostics} items=${doc.diagnostics} tree=${doc.tree} onSelect=${setSelected}
                                   filter=${diagFilter} onFilter=${setDiagFilter} />`
            : html`<${History} doc=${doc} onError=${onError} onOpen=${(id) => go(id)} onSend=${send}
                               onChanged=${(updated) => updated ? accept(updated) : loadDoc()} />`}</div>`}
        </section>
      </div>
    </div>
    ${dialog === "build" ? html`<${BuildDialog} doc=${doc} vocab=${vocab} device=${view.device}
                                               onClose=${() => setDialog(null)} />` : null}
    ${dialog === "keys" ? html`<${ShortcutHelp} onClose=${() => setDialog(null)} />` : null}
    ${dialog === "help" ? html`<${HelpDialog} start="docs/guide/studio.md" onClose=${() => setDialog(null)} />` : null}
    ${dialog === "calibrate" ? html`<${CalibrateDialog} current=${pxPerInch} onClose=${() => setDialog(null)}
        onSave=${(v) => {
          try { localStorage.setItem("wfb-css-px-per-inch", String(v)); } catch (_) { /* private mode */ }
          setPxPerInch(v); setDialog(null);
        }} />` : null}
  </div>`;
}

// -- the app -------------------------------------------------------------------------

// Every message the editor has shown, newest first: a toast goes after a
// few seconds, and a newer one replaces it, so a refusal's reason stays
// readable here. The badge counts those not seen yet.
function MessageLog({ log, unseen, onOpen, onClear }) {
  if (!log.length) return null;
  const time = (t) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
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

function App() {
  const [docId, setDocId] = useState(route());
  const [toast, setToast] = useState(null);       // {message, kind}
  const [log, setLog] = useState([]);              // [{message, kind, at}], newest first
  const [unseen, setUnseen] = useState(0);
  const toastTimer = useRef(null);
  useEffect(() => {
    const onHash = () => setDocId(route());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);
  // a new message replaces the last, and gets its own full time
  const show = useCallback((message, kind) => {
    clearTimeout(toastTimer.current);
    setToast({ message, kind });
    setLog((l) => [{ message, kind, at: Date.now() }, ...l].slice(0, 100));
    setUnseen((n) => n + 1);
    toastTimer.current = setTimeout(() => setToast(null), kind === "error" ? 6000 : 4000);
  }, []);
  const onError = useCallback((e) => show(e.message || String(e), "error"), [show]);
  const onNotice = useCallback((message) => show(message, "notice"), [show]);
  return html`
    ${docId ? html`<${Editor} docId=${docId} onError=${onError} onNotice=${onNotice} />`
            : html`<${Home} onError=${onError} />`}
    ${toast ? html`<div class=${"toast " + toast.kind} role=${toast.kind === "error" ? "alert" : "status"}
                        onClick=${() => setToast(null)}>${toast.message}</div>` : null}
    <${MessageLog} log=${log} unseen=${unseen} onOpen=${() => setUnseen(0)}
                   onClear=${() => { setLog([]); setUnseen(0); }} />
    <${AskHost} />`;
}

// The faces live only in this browser's storage, which it may clear when
// the disk runs low unless asked to keep it; a refusal changes nothing.
if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});

render(html`<${App} />`, document.getElementById("app"));
