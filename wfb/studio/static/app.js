// wfb studio's front end. The browser asks and shows; the server holds the
// face's text and runs the compiler, so nothing here decides what a face
// looks like: every image comes from the server's renderer.

import { html, render, useState, useEffect, useRef, useCallback, useMemo }
  from "./vendor/preact-htm.module.js";
import { elementAtLine, flatten, movedBy, together } from "./hit.js";
import { enqueue, mark, next, saveState } from "./outbox.js";
import { Canvas, Strip } from "./canvas.js";
import { Layers } from "./layers.js";
import { YamlPane } from "./yaml.js";
import { BuildDialog, CalibrateDialog } from "./dialogs.js";
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
// This computer's time and date, as the time and date inputs write them.
function clockNow() {
  const d = new Date();
  const two = (n) => String(n).padStart(2, "0");
  return { time: `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`,
           date: `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}` };
}
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
import { picksParam, typeLabel } from "./values.js";
import { Diagnostics, diagnosticsLabel } from "./diagnostics.js";
import { deleteOp } from "./tree.js";
import { sessionLost, watch } from "./session.js";

// -- the server --------------------------------------------------------------------

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const type = response.headers.get("content-type") || "";
  const body = type.includes("json") ? await response.json() : null;
  // the session cookie is gone (cleared, or expired): `session.js`
  if (response.status === 401) sessionLost();
  if (!response.ok) {
    const error = new Error((body && body.error) || `${response.status} ${response.statusText}`);
    error.status = response.status;
    throw error;
  }
  return body;
}

const enc = encodeURIComponent;

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
    const source = new EventSource("/api/events");
    for (const name of ["changed", "snapshot", "error"]) {
      source.addEventListener(name, (e) => handler.current(name, JSON.parse(e.data)));
    }
    return () => source.close();
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
  const fileInput = useRef(null);

  const load = useCallback(() => api("/api/home").then(setHome, onError), []);
  useEffect(() => { load(); }, []);

  const create = async () => {
    setBusy(true);
    try {
      const doc = await api(`/api/documents/new?template=${enc(template)}&name=${enc(name)}`,
                            { method: "POST" });
      go(doc.id);
    } catch (e) { onError(e); } finally { setBusy(false); }
  };

  const upload = async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      const doc = await api(`/api/documents/upload?filename=${enc(file.name)}`,
                            { method: "POST", body: file });
      go(doc.id);
    } catch (e) { onError(e); } finally { setBusy(false); }
  };

  const remove = async (doc) => {
    if (!confirm(`Delete "${doc.name}" and its whole history? This cannot be undone.`)) return;
    try { await api(`/api/documents/${doc.id}`, { method: "DELETE" }); load(); }
    catch (e) { onError(e); }
  };

  if (!home) return html`<div class="home dim">Loading…</div>`;
  const blurb = (home.templates.find((t) => t.name === template) || {}).blurb;
  return html`
    <div class="home">
      <h1>wfb studio</h1>
      <div class="dim">Create a watch face, or open one to edit. Download it to save.</div>
      <div class="cards">
        <div class="card">
          <h2>New face</h2>
          <label>Start from</label>
          <select value=${template} onChange=${(e) => setTemplate(e.target.value)}>
            ${home.templates.map((t) => html`<option value=${t.name}>${t.name}</option>`)}
          </select>
          <div class="dim" style="margin-top:6px;font-size:12px">${blurb}</div>
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
            <div class="row" style="justify-content:center">
              <button disabled=${busy} onClick=${() => fileInput.current.click()}>Choose file…</button>
            </div>
          </div>
          <input type="file" accept=".zip,.yaml,.yml" style="display:none" ref=${fileInput}
                 onChange=${(e) => upload(e.target.files[0])} />
        </div>
      </div>
      <div class="card" style="margin-top:16px">
        <h2>Recent</h2>
        ${home.documents.length === 0
          ? html`<div class="dim">Nothing yet. Faces you create or open are kept here, with their history.</div>`
          : html`<ul class="recent">
              ${home.documents.map((d) => html`
                <li>
                  <span class="name" onClick=${() => go(d.id)}>${d.name}</span>
                  <span class="dim">v${d.version} · ${ago(d.changed)}${d.snapshots ? ` · ${d.snapshots} snapshot${d.snapshots > 1 ? "s" : ""}` : ""}</span>
                  <button class="danger" onClick=${() => remove(d)}>Delete</button>
                </li>`)}
            </ul>`}
        <div class="dim" style="margin-top:10px;font-size:12px">History is kept in <code>${home.store}</code></div>
        ${home.shared ? null : html`<${AnotherBrowser} />`}
      </div>
    </div>`;
}

// This browser's faces are its own; a one-time link opens them in another.
function AnotherBrowser() {
  const [link, setLink] = useState(null);
  const [error, setError] = useState("");
  const ask = async () => {
    try {
      const got = await api("/api/claims", { method: "POST" });
      setLink({ url: new URL(got.url, location.href).href, minutes: Math.round(got.seconds / 60) });
    } catch (e) { setError(e.message); }
  };
  return html`<div class="another">
    <div class="dim">These faces belong to this browser. To open them in another browser too:</div>
    ${link ? html`<div><code class="mono">${link.url}</code>
        <div class="dim">Open it in the other browser within ${link.minutes} minutes. It works once.</div></div>`
      : html`<button onClick=${ask}>Use my faces in another browser</button>`}
    ${error ? html`<div class="error-text">${error}</div>` : null}
  </div>`;
}

// -- the editor ----------------------------------------------------------------------

function Missing({ doc, onChanged, onError }) {
  if (!doc.missing.length) return null;
  const add = async (reference, file) => {
    if (!file) return;
    try {
      const updated = await api(
        `/api/documents/${doc.id}/assets?filename=${enc(file.name)}&reference=${enc(reference)}&version=${doc.version}`,
        { method: "POST", body: file });
      onChanged(updated);
    } catch (e) { onError(e); }
  };
  return html`<div class="banner">
    <strong>Missing files:</strong>
    ${doc.missing.map((ref) => html`<span class="file">
      <code>${ref}</code>
      <label><button onClick=${(e) => e.currentTarget.nextElementSibling.click()}>Add…</button>
        <input type="file" accept=".ttf,.otf" style="display:none"
               onChange=${(e) => add(ref, e.target.files[0])} /></label>
    </span>`)}
    <span class="dim">The face does not draw until every font file is added.</span>
  </div>`;
}

function History({ doc, onChanged, onOpen, onError }) {
  const h = doc.history;
  const post = async (path) => {
    try { return await api(`/api/documents/${doc.id}/${path}`, { method: "POST" }); }
    catch (e) { onError(e); return null; }
  };
  const restore = async (s) => {
    const updated = await post(`snapshots/${s.name}/restore?version=${doc.version}`);
    if (updated) onChanged(updated);
  };
  const copy = async (s) => {
    const created = await post(`snapshots/${s.name}/copy`);
    if (created) onOpen(created.id);
  };
  const snapshotNow = async () => { if (await post("snapshots")) onChanged(null); };
  const when = (t) => new Date(t * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" });
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
    <ul class="states">
      ${h.states.map((s) => html`<li class=${(s.current ? "current" : "") + (s.redo ? " redo" : "")}>
        <span class="label">${s.label}</span><span class="dim">${when(s.time)}</span>
      </li>`)}
    </ul>
  </div>`;
}

function DownloadMenu({ doc }) {
  const [open, setOpen] = useState(false);
  const link = (form) => `/api/documents/${doc.id}/download?form=${form}`;
  return html`<div class="menu">
    <button class="primary" onClick=${() => { location.href = link("auto"); }}>Download</button>
    <button onClick=${() => setOpen(!open)} title="Choose the format">▾</button>
    ${open ? html`<div class="items" onClick=${() => setOpen(false)}>
      <button onClick=${() => { location.href = link("zip"); }}>.zip (face.yaml + assets)</button>
      <button onClick=${() => {
        if (!doc.assets.length || confirm("This face uses asset files; a plain .yaml will not build on its own. Download it anyway?")) {
          location.href = link("yaml");
        }
      }}>.yaml only</button>
    </div>` : null}
  </div>`;
}

function Editor({ docId, onError, onNotice }) {
  const [doc, setDoc] = useState(null);
  const [frame, setFrame] = useState(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(null);
  const [view, setView] = useState({ device: null, style: "", time: "", date: "", now: false, asleep: false,
                                     aod: false, skin: false, zoom: storedZoom() });
  // "now": the frame follows this computer's clock; the time and date it
  // was drawn at, moved on a second after each frame arrives
  const [clock, setClock] = useState(clockNow());
  const time = view.now ? clock.time : view.time;
  const date = view.now ? clock.date : view.date;
  // the server draws at a whole scale; the browser shows it at the zoom
  const scale = serverScale(view.zoom, window.devicePixelRatio || 1);
  const [pxPerInch, setPxPerInch] = useState(storedPxPerInch());
  const [dialog, setDialog] = useState(null);           // "build" | "calibrate"
  const [skin, setSkin] = useState(null);
  const [vocab, setVocab] = useState({});
  // the face's slots, which the "showing" control picks a type for
  const slots = (doc && doc.globals && doc.globals.slots) || [];
  useEffect(() => { api("/api/vocabulary").then(setVocab, onError); }, []);

  const loadDoc = useCallback(() => api(`/api/documents/${docId}`).then(setDoc, (e) => {
    onError(e);
    if (e.status === 404) go(null);
  }), [docId]);
  useEffect(() => { setDoc(null); setFrame(null); setSelected(null); loadDoc(); }, [docId]);

  // The device defaults to the first target, and is kept while it stays one.
  useEffect(() => {
    if (doc && (!view.device || !doc.targets.includes(view.device)) && doc.targets.length) {
      setView((v) => ({ ...v, device: doc.targets[0] }));
    }
  }, [doc]);

  useEffect(() => {
    if (!doc || !view.device || !doc.targets.includes(view.device)) { setFrame(null); return; }
    let live = true;
    setBusy(true);
    const q = new URLSearchParams({ device: view.device, scale });
    if (view.style) q.set("style", view.style);
    if (time) q.set("time", time);
    if (date) q.set("date", date);
    if (view.asleep) q.set("asleep", "1");
    if (view.aod) q.set("aod", "1");
    const picks = picksParam(view.picks, slots);
    if (picks) q.set("picks", picks);
    api(`/api/documents/${docId}/frame?${q}`)
      .then((f) => { if (live) setFrame(f); }, onError)
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [doc && doc.version, doc && doc.targets.join(), view.device, view.style, time, date,
      view.asleep, view.aod, scale, picksParam(view.picks, slots)]);

  // the watch's skin, at the frame's scale, when asked for and it has one
  const deviceInfo = (vocab.devices || []).find((d) => d.id === view.device);
  useEffect(() => {
    if (!view.skin || !deviceInfo || !deviceInfo.skin) { setSkin(null); return; }
    let live = true;
    api(`/api/skin?device=${enc(view.device)}&scale=${scale}`).then((s) => { if (live) setSkin(s); }, onError);
    return () => { live = false; };
  }, [view.skin, view.device, scale, deviceInfo && deviceInfo.skin]);
  // the next tick waits for the frame, so a slow one is never queued behind
  useEffect(() => {
    if (!view.now || busy) return;
    const timer = setTimeout(() => setClock(clockNow()), 1000 - (Date.now() % 1000) + 5);
    return () => clearTimeout(timer);
  }, [view.now, busy, clock]);
  const real = deviceInfo ? realZoom(deviceInfo.ppi, pxPerInch) : null;
  // the slider's steps are hundredths; real size is set exactly
  const setZoom = (z, exact = false) => {
    const zoom = clampZoom(exact ? z : Math.round(z * 100) / 100);
    try { localStorage.setItem("wfb-zoom", String(zoom)); } catch (_) { /* private mode */ }
    setView((v) => ({ ...v, zoom }));
  };

  useEvents((name, data) => {
    if (!doc || data.id !== docId) return;
    if (name === "error") onError(new Error(data.message));
    else if ((name === "changed" && data.version !== doc.version) || name === "snapshot") loadDoc();
  });

  const element = useMemo(() => doc && selected && flatten(doc.tree).find((n) => n.id === selected),
                          [doc, selected]);
  const step = useCallback(async (which) => {
    if (!doc) return;
    try { setDoc(await saving(api(`/api/documents/${docId}/${which}?version=${doc.version}`, { method: "POST" }))); }
    catch (e) { onError(e); if (e.status === 409) loadDoc(); }
  }, [doc]);
  const [tab, setTab] = useState("diagnostics");
  // Changes on their way: the edits below while their request is out, and
  // the YAML tab's own state (`YamlPane`'s `onSaving`).
  const [inflight, setInflight] = useState(0);
  const saving = useCallback((request) => {
    setInflight((n) => n + 1);
    return request.finally(() => setInflight((n) => n - 1));
  }, []);
  const [yamlSaving, setYamlSaving] = useState("idle");
  useEffect(() => { setYamlSaving("idle"); }, [docId]);
  // A lost session with work unsaved (`session.js`) is a banner, not a reload.
  const [lost, setLost] = useState(false);
  const unsavedNow = useRef(() => false);
  unsavedNow.current = () => yamlSaving !== "idle" || queued.current.some((e) => e.state !== "done");
  useEffect(() => watch(() => unsavedNow.current(), () => setLost(true)), []);
  // where an inspector edit or a drag writes geometry: "all" (a drag then
  // writes where the viewed device reads it), the device, or its shape
  const [scope, setScope] = useState("all");
  // The outbox (`outbox.js`): gestures from the canvas and the arrow keys,
  // sent one at a time, each against the version the one before produced,
  // so the canvas never waits for the server. `ids`: the elements one
  // gesture drags; several only for a move.
  const [queue, setQueue] = useState([]);
  const queued = useRef([]);
  const latest = useRef(null);       // the newest version known, for the next send
  const commit = (q) => { queued.current = q; setQueue(q); };
  useEffect(() => { if (doc) latest.current = doc.version; }, [doc && doc.version]);
  useEffect(() => { commit([]); }, [docId]);
  // a frame showing a gesture's version retires it
  useEffect(() => {
    if (frame) commit(queued.current.filter((e) => !(e.state === "done" && e.done <= frame.version)));
  }, [frame && frame.version]);
  // the device and scope a gesture is written for, as they were when it was made
  const where = useRef({});
  where.current = { device: view.device, scope: scope === "all" ? "auto" : scope };
  const pump = useCallback(async () => {
    const entry = next(queued.current);
    if (!entry || latest.current === null) return;
    commit(mark(queued.current, entry, "sent"));
    const which = entry.ids.length > 1 ? { elements: entry.ids } : { element: entry.ids[0] };
    try {
      const updated = await api(`/api/documents/${docId}/drag?version=${latest.current}`, {
        method: "POST",
        body: JSON.stringify({ ...which, gesture: entry.gesture, ...entry.where }),
      });
      latest.current = updated.version;
      commit(mark(queued.current, queued.current.find((e) => e.state === "sent"), "done", updated.version));
      setDoc(updated);
      if (!updated.landed) onNotice(`${updated.what}: written as close as its units allow, not exactly on the pixel`);
      pump();
    } catch (e) {
      // what was queued behind it was aimed at a face that did not happen
      commit(queued.current.filter((q) => q.state === "done"));
      onError(e);
      if (e.status === 409) loadDoc();
    }
  }, [docId]);
  const onDrag = useCallback((ids, gesture, shown) => {
    commit(enqueue(queued.current, { ids, gesture, ...shown, where: { ...where.current } }));
    pump();
  }, [pump]);
  const [left, setLeft] = useState("layers");
  const [pane, setPane] = useState("face");
  // where the YAML tab was, per face, while the editor is open
  const yamlMemory = useRef({});
  const [panels, setPanels] = useState(storedPanels());
  // `save`: the drag is over, so the browser keeps the width
  const panelWidth = (side) => (w, save) => {
    setPanels((p) => ({ ...p, [side]: w }));
    if (save) { try { localStorage.setItem(`wfb-panel-${side}`, String(w)); } catch (_) { /* private mode */ } }
  };
  // lines the YAML tab is asked to select, from a link elsewhere
  const [reveal, setReveal] = useState(null);
  const showLines = useCallback((line, end) => { setReveal({ line, end, at: Date.now() }); setPane("yaml"); }, []);
  // more elements selected with Ctrl/Cmd/Shift, for grouping
  const [extra, setExtra] = useState([]);
  const select = useCallback((id, additive) => {
    if (additive && selected && id !== selected) {
      setExtra((xs) => (xs.includes(id) ? xs.filter((x) => x !== id) : [...xs, id]));
    } else { setSelected(id); setExtra([]); }
  }, [selected]);
  // One structural edit from the Layers panel: the server patches the text,
  // checks it and answers with the face and what to select.
  const structure = useCallback(async (op) => {
    if (!doc) return;
    try {
      const updated = await saving(api(`/api/documents/${docId}/structure?version=${doc.version}`,
                                       { method: "POST", body: JSON.stringify(op) }));
      setDoc(updated);
      if (op.op === "delete") setSelected(null);
      else if (updated.select) setSelected(updated.select);
      setExtra([]);
    } catch (e) { onError(e); if (e.status === 409) loadDoc(); }
  }, [doc]);
  // Arrow keys move the selection a pixel, ten with Shift, as a drag would.
  const nudge = useCallback((dx, dy) => {
    const ids = [selected, ...extra].filter(Boolean);
    if (!ids.length || !frame || !doc) return false;
    const item = ids.length > 1 ? together(frame.items, ids) : frame.items.find((i) => i.id === ids[0]);
    if (!item || !item.box) return false;
    const gesture = { kind: "move", part: "both", dx, dy };
    onDrag(ids, gesture, { item, moving: movedBy(doc.tree, ids), preview: gesture });
    return true;
  }, [selected, extra, frame, doc, onDrag]);
  useEffect(() => {
    const onKey = (e) => {
      if (!(e.ctrlKey || e.metaKey) || e.target.closest("input, textarea, select, .cm-editor")) return;
      const key = e.key.toLowerCase();
      if (key === "z" && !e.shiftKey) { e.preventDefault(); step("undo"); }
      else if ((key === "z" && e.shiftKey) || key === "y") { e.preventDefault(); step("redo"); }
      else if (key === "d" && element) { e.preventDefault(); structure({ op: "duplicate", path: element.path }); }
    };
    addEventListener("keydown", onKey);
    // the arrows nudge, while the face is shown and nothing is being typed
    const onArrow = (e) => {
      const step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
      if (!step || pane !== "face" || e.ctrlKey || e.metaKey || e.altKey
          || e.target.closest("input, textarea, select, .cm-editor")) return;
      const n = e.shiftKey ? 10 : 1;
      if (nudge(step[0] * n, step[1] * n)) e.preventDefault();
    };
    addEventListener("keydown", onArrow);
    // Delete: the whole selection, as one change; no modifier, and not
    // while typing
    const onDelete = (e) => {
      if ((e.key === "Delete" || e.key === "Backspace") && !e.ctrlKey && !e.metaKey && element &&
          !e.target.closest("input, textarea, select, .cm-editor")) {
        e.preventDefault();
        const op = deleteOp(doc.tree, [selected, ...extra]);
        if (op) structure(op);
      }
    };
    addEventListener("keydown", onDelete);
    return () => {
      removeEventListener("keydown", onKey); removeEventListener("keydown", onArrow);
      removeEventListener("keydown", onDelete);
    };
  }, [step, structure, element, nudge, pane, doc, selected, extra]);

  // One edit from the inspector or the Face panel: the server patches the
  // text, checks it and answers with the face; a refusal says why.
  const edit = useCallback(async (op) => {
    if (!doc) return;
    try {
      setDoc(await saving(api(`/api/documents/${docId}/edit?version=${doc.version}`,
                              { method: "POST", body: JSON.stringify(op) })));
    } catch (e) { onError(e); if (e.status === 409) loadDoc(); }
  }, [doc]);
  const upload = useCallback(async (file, { font, size, reference }) => {
    if (!doc) return;
    const q = new URLSearchParams({ filename: file.name, version: doc.version });
    if (font) { q.set("font", font); q.set("size", size || "10%r"); }
    if (reference) q.set("reference", reference);
    try { setDoc(await saving(api(`/api/documents/${docId}/assets?${q}`, { method: "POST", body: file }))); }
    catch (e) { onError(e); if (e.status === 409) loadDoc(); }
  }, [doc]);

  const drawn = useMemo(() => frame && new Set(frame.items.filter((i) => i.drawn).map((i) => i.id)), [frame]);
  const box = useMemo(() => {
    const item = frame && frame.items.find((i) => i.id === selected);
    return item && item.box;
  }, [frame, selected]);

  if (!doc) return html`<div class="home dim">Loading…</div>`;
  const set = (key) => (e) => setView({ ...view, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const saved = saveState({ inflight, queue, yaml: yamlSaving });
  const counts = doc.diagnostics.reduce((a, d) => ({ ...a, [d.severity]: (a[d.severity] || 0) + 1 }), {});

  return html`<div class="editor">
    <div>
      <div class="topbar">
        <button onClick=${() => go(null)} title="All faces">← Faces</button>
        <span class="title">${doc.name}</span>
        <span class="dim">version ${doc.version}</span>
        <span class=${"save " + saved} role="status"
              title=${saved === "unsaved" ? "the YAML tab's text is not saved: see under the text" : "changes are recorded as you make them"}>
          ${{ saved: "saved", saving: "saving…", unsaved: "not saved" }[saved]}</span>
        <button disabled=${!doc.history.can_undo} onClick=${() => step("undo")} title="Undo (Ctrl+Z)">↶ Undo</button>
        <button disabled=${!doc.history.can_redo} onClick=${() => step("redo")} title="Redo (Ctrl+Shift+Z)">↷ Redo</button>
        <span class="spacer"></span>
        ${counts.error ? html`<span class="error-text">${counts.error} error${counts.error > 1 ? "s" : ""}</span>` : null}
        <button disabled=${!doc.loads} title=${doc.loads ? "Build a .prg for one watch" : "the face does not load"}
                onClick=${() => setDialog("build")}>Build…</button>
        <${DownloadMenu} doc=${doc} />
      </div>
      ${lost ? html`<div class="banner lost" role="alert">
        <strong>This browser's session has ended</strong> (its cookie was cleared or expired), so changes can no longer be saved.
        Copy anything unsaved from the YAML tab, then reload to start a new session.
        <button onClick=${() => location.reload()}>Reload</button></div>` : null}
      <${Missing} doc=${doc} onChanged=${setDoc} onError=${onError} />
    </div>
    <div class="columns" style=${`grid-template-columns:${panels.left}px auto minmax(0, 1fr) auto ${panels.right}px`}>
      <div class="panel left">
        <div class="tabs top">
          <button class=${left === "layers" ? "on" : ""} onClick=${() => setLeft("layers")}>Layers</button>
          <button class=${left === "face" ? "on" : ""} onClick=${() => setLeft("face")}>Face</button>
        </div>
        ${left === "layers"
          ? html`<${Layers} doc=${doc} vocab=${vocab} selected=${selected} extra=${extra} drawn=${drawn}
                            onSelect=${select} onStructure=${structure} />`
          : html`<${FacePanel} doc=${doc} vocab=${vocab} onEdit=${edit} onUpload=${upload}
                               onSelect=${select} onStructure=${structure} onReveal=${showLines} />`}
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
          ${slots.map((s) => html`<label title=${`what the slot ${s.name} is drawn showing; the wearer picks it on the watch`}>${s.name}
            <select value=${(view.picks || {})[s.name] || s.default}
                    onChange=${(e) => setView({ ...view, picks: { ...(view.picks || {}), [s.name]: e.target.value } })}>
              ${(Array.isArray(s.choices) ? s.choices.map((c) => c.type) : (vocab.complication_types || []).map((t) => t.name))
                .map((t) => html`<option value=${t}>${t === s.default ? `${typeLabel(vocab, t)} (first)` : typeLabel(vocab, t)}</option>`)}
            </select></label>`)}
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
          <label><input type="checkbox" checked=${view.asleep} onChange=${set("asleep")} /> asleep</label>
          <label><input type="checkbox" checked=${view.aod} onChange=${set("aod")} /> AOD</label>
          <label title=${deviceInfo && !deviceInfo.skin ? "this watch's files have no skin" : "the watch drawn round the screen"}>
            <input type="checkbox" checked=${view.skin} disabled=${deviceInfo && !deviceInfo.skin}
                   onChange=${set("skin")} /> skin</label>
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
          <button class="reset" title="Calibrate real size with a bank card" onClick=${() => setDialog("calibrate")}>⚙</button>
        </div>
        ${pane === "yaml"
          ? html`<${YamlPane} doc=${doc} selected=${selected} reveal=${reveal} memory=${yamlMemory.current[docId] ||= {}} onDoc=${setDoc} onError=${onError} onSaving=${setYamlSaving}
                              onSelect=${(id) => { setSelected(id); setExtra([]); }} />`
          : html`<div class="canvas-wrap">
              ${busy ? html`<div class="busy">rendering…</div>` : null}
              ${frame ? html`<${Canvas} frame=${frame} selected=${selected}
                                        extra=${extra} tree=${doc.tree} queue=${queue}
                                        zoom=${view.zoom} skin=${skin && skin.scale === frame.scale ? skin : null}
                                        onPick=${select} onDrag=${onDrag} />`
                      : html`<div class="empty">${doc.loads ? "No frame yet." :
                          "The face does not load, so there is nothing to draw. The diagnostics on the right say why."}</div>`}
            </div>`}
        <${Strip} doc=${doc} view=${{ ...view, time, date }} picks=${picksParam(view.picks, slots)}
                  onDevice=${(d) => setView({ ...view, device: d })} />
      </div>
      <${Splitter} width=${panels.right} sign=${-1} fallback=${340} onWidth=${panelWidth("right")} />
      <div class="panel right">
        <h3>Properties</h3>
        ${element ? html`<div class="body dim where">
            in <code>${element.path.slice(0, -1).join(".")}</code>, line ${element.line}
            ${box ? html` · ${box[2]}×${box[3]} px at (${box[0]}, ${box[1]})` : ""}
            ${!box && drawn && element.type !== "group" ? " · not drawn in this frame" : ""}
          </div>` : null}
        <${Inspector} doc=${doc} element=${element} device=${view.device} vocab=${vocab}
                      scope=${scope} onScope=${setScope} onEdit=${edit} onError=${onError}
                      onReveal=${showLines} onSelect=${select} />
        <div class="tabs">
          <button class=${tab === "diagnostics" ? "on" : ""} onClick=${() => setTab("diagnostics")}>
            ${diagnosticsLabel(doc.diagnostics)}</button>
          <button class=${tab === "history" ? "on" : ""} onClick=${() => setTab("history")}>History</button>
        </div>
        ${tab === "diagnostics"
          ? html`<${Diagnostics} items=${doc.diagnostics} tree=${doc.tree} onSelect=${setSelected} />`
          : html`<${History} doc=${doc} onError=${onError} onOpen=${(id) => go(id)}
                             onChanged=${(updated) => updated ? setDoc(updated) : loadDoc()} />`}
      </div>
    </div>
    ${dialog === "build" ? html`<${BuildDialog} doc=${doc} vocab=${vocab} device=${view.device}
                                               onClose=${() => setDialog(null)} />` : null}
    ${dialog === "calibrate" ? html`<${CalibrateDialog} current=${pxPerInch} onClose=${() => setDialog(null)}
        onSave=${(v) => {
          try { localStorage.setItem("wfb-css-px-per-inch", String(v)); } catch (_) { /* private mode */ }
          setPxPerInch(v); setDialog(null);
        }} />` : null}
  </div>`;
}

// -- the app -------------------------------------------------------------------------

function App() {
  const [docId, setDocId] = useState(route());
  const [toast, setToast] = useState(null);       // {message, kind}
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
    toastTimer.current = setTimeout(() => setToast(null), kind === "error" ? 6000 : 4000);
  }, []);
  const onError = useCallback((e) => show(e.message || String(e), "error"), [show]);
  const onNotice = useCallback((message) => show(message, "notice"), [show]);
  return html`
    ${docId ? html`<${Editor} docId=${docId} onError=${onError} onNotice=${onNotice} />`
            : html`<${Home} onError=${onError} />`}
    ${toast ? html`<div class=${"toast " + toast.kind} role=${toast.kind === "error" ? "alert" : "status"}
                        onClick=${() => setToast(null)}>${toast.message}</div>` : null}`;
}

render(html`<${App} />`, document.getElementById("app"));
