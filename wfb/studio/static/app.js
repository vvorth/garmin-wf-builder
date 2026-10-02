// wfb studio's front end. The browser asks and shows; the server holds the
// face's text and runs the compiler, so nothing here decides what a face
// looks like: every image comes from the server's renderer.

import { html, render, useState, useEffect, useRef, useCallback, useMemo }
  from "./vendor/preact-htm.module.js";
import { elementAtLine, flatten } from "./hit.js";
import { Canvas, Strip } from "./canvas.js";
import { FacePanel, Inspector } from "./panels.js";

// -- the server --------------------------------------------------------------------

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const type = response.headers.get("content-type") || "";
  const body = type.includes("json") ? await response.json() : null;
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
    for (const name of ["changed", "rendered", "error"]) {
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
      </div>
    </div>`;
}

// -- the editor ----------------------------------------------------------------------

function Tree({ nodes, selected, drawn, onSelect }) {
  return html`<ul class="tree">
    ${nodes.map((n) => n.kind === "block"
      ? html`<li><div class="block">${n.label}</div>
               <${Tree} nodes=${n.children} selected=${selected} drawn=${drawn} onSelect=${onSelect} /></li>`
      : html`<li>
          <div class=${"item" + (n.id === selected ? " selected" : "") +
                       (drawn && n.type !== "group" && !drawn.has(n.id) ? " undrawn" : "")}
               onClick=${() => onSelect(n.id)} title=${`line ${n.line}`}>
            <span>${n.id}</span><span class="type">${n.type}</span>
          </div>
          ${n.children.length ? html`<${Tree} nodes=${n.children} selected=${selected}
                                             drawn=${drawn} onSelect=${onSelect} />` : null}
        </li>`)}
  </ul>`;
}

function Diagnostics({ items, tree, onSelect }) {
  if (!items.length) return html`<div class="body dim">No diagnostics.</div>`;
  const order = { error: 0, warning: 1, note: 2 };
  const sorted = [...items].sort((a, b) => order[a.severity] - order[b.severity]);
  return html`<ul class="diags">
    ${sorted.map((d) => html`
      <li onClick=${() => { const el = d.line && elementAtLine(tree, d.line); if (el) onSelect(el.id); }}>
        <span class=${"sev " + d.severity}>${d.severity}</span>${d.message}
        ${d.line ? html`<div class="where">${d.file}:${d.line}:${d.col} · ${d.code}</div>` : null}
        ${d.notes.length ? html`<div class="notes">${d.notes.join("\n")}</div>` : null}
      </li>`)}
  </ul>`;
}

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

function Editor({ docId, onError }) {
  const [doc, setDoc] = useState(null);
  const [frame, setFrame] = useState(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(null);
  const [view, setView] = useState({ device: null, style: "", time: "", asleep: false, aod: false, scale: 2 });

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
    const q = new URLSearchParams({ device: view.device, scale: view.scale });
    if (view.style) q.set("style", view.style);
    if (view.time) q.set("time", view.time);
    if (view.asleep) q.set("asleep", "1");
    if (view.aod) q.set("aod", "1");
    api(`/api/documents/${docId}/frame?${q}`)
      .then((f) => {
        if (!live) return;
        setFrame(f);
        // the layers follow: alpha hit-testing and a drag's moving image
        return api(`/api/documents/${docId}/layers?${q}`).then((l) => { if (live) setLayers(l); });
      }, onError)
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [doc && doc.version, doc && doc.targets.join(), view]);

  useEvents((name, data) => {
    if (!doc || data.id !== docId) return;
    if ((name === "changed" && data.version !== doc.version) || name === "snapshot") loadDoc();
  });

  const step = useCallback(async (which) => {
    if (!doc) return;
    try { setDoc(await api(`/api/documents/${docId}/${which}?version=${doc.version}`, { method: "POST" })); }
    catch (e) { onError(e); if (e.status === 409) loadDoc(); }
  }, [doc]);
  useEffect(() => {
    const onKey = (e) => {
      if (!(e.ctrlKey || e.metaKey) || e.target.closest("input, textarea, select, .cm-editor")) return;
      const key = e.key.toLowerCase();
      if (key === "z" && !e.shiftKey) { e.preventDefault(); step("undo"); }
      else if ((key === "z" && e.shiftKey) || key === "y") { e.preventDefault(); step("redo"); }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [step]);
  const [tab, setTab] = useState("diagnostics");
  const [layers, setLayers] = useState(null);
  // where an inspector edit or a drag writes geometry: "all" (a drag then
  // writes where the viewed device reads it), the device, or its shape
  const [scope, setScope] = useState("all");
  const onDrag = useCallback(async (element, gesture) => {
    if (!doc) return false;
    try {
      const updated = await api(`/api/documents/${docId}/drag?version=${doc.version}`, {
        method: "POST",
        body: JSON.stringify({ element, gesture, device: view.device, scope: scope === "all" ? "auto" : scope }),
      });
      setDoc(updated);
      if (!updated.landed) onError(new Error(`${updated.what}: written as close as its units allow, not exactly on the pixel`));
      return true;
    } catch (e) { onError(e); if (e.status === 409) loadDoc(); return false; }
  }, [doc, view.device, scope]);
  const [left, setLeft] = useState("layers");
  const [vocab, setVocab] = useState({});
  useEffect(() => { api("/api/vocabulary").then(setVocab, onError); }, []);

  // One edit from the inspector or the Face panel: the server patches the
  // text, checks it and answers with the face; a refusal says why.
  const edit = useCallback(async (op) => {
    if (!doc) return;
    try {
      setDoc(await api(`/api/documents/${docId}/edit?version=${doc.version}`,
                       { method: "POST", body: JSON.stringify(op) }));
    } catch (e) { onError(e); if (e.status === 409) loadDoc(); }
  }, [doc]);
  const upload = useCallback(async (file, { font, size, reference }) => {
    if (!doc) return;
    const q = new URLSearchParams({ filename: file.name, version: doc.version });
    if (font) { q.set("font", font); q.set("size", size || "10%r"); }
    if (reference) q.set("reference", reference);
    try { setDoc(await api(`/api/documents/${docId}/assets?${q}`, { method: "POST", body: file })); }
    catch (e) { onError(e); if (e.status === 409) loadDoc(); }
  }, [doc]);

  const drawn = useMemo(() => frame && new Set(frame.items.filter((i) => i.drawn).map((i) => i.id)), [frame]);
  const element = useMemo(() => doc && selected && flatten(doc.tree).find((n) => n.id === selected),
                          [doc, selected]);
  const box = useMemo(() => {
    const item = frame && frame.items.find((i) => i.id === selected);
    return item && item.box;
  }, [frame, selected]);

  if (!doc) return html`<div class="home dim">Loading…</div>`;
  const set = (key) => (e) => setView({ ...view, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const counts = doc.diagnostics.reduce((a, d) => ({ ...a, [d.severity]: (a[d.severity] || 0) + 1 }), {});

  return html`<div class="editor">
    <div>
      <div class="topbar">
        <button onClick=${() => go(null)} title="All faces">← Faces</button>
        <span class="title">${doc.name}</span>
        <span class="dim">version ${doc.version}</span>
        <button disabled=${!doc.history.can_undo} onClick=${() => step("undo")} title="Undo (Ctrl+Z)">↶ Undo</button>
        <button disabled=${!doc.history.can_redo} onClick=${() => step("redo")} title="Redo (Ctrl+Shift+Z)">↷ Redo</button>
        <span class="spacer"></span>
        ${counts.error ? html`<span class="error-text">${counts.error} error${counts.error > 1 ? "s" : ""}</span>` : null}
        <${DownloadMenu} doc=${doc} />
      </div>
      <${Missing} doc=${doc} onChanged=${setDoc} onError=${onError} />
    </div>
    <div class="columns">
      <div class="panel left">
        <div class="tabs top">
          <button class=${left === "layers" ? "on" : ""} onClick=${() => setLeft("layers")}>Layers</button>
          <button class=${left === "face" ? "on" : ""} onClick=${() => setLeft("face")}>Face</button>
        </div>
        ${left === "layers"
          ? html`<div class="tree root">
              <${Tree} nodes=${doc.tree} selected=${selected} drawn=${drawn} onSelect=${setSelected} />
            </div>`
          : html`<${FacePanel} doc=${doc} vocab=${vocab} onEdit=${edit} onUpload=${upload} />`}
      </div>
      <div class="stage">
        <div class="controls">
          <label>Device
            <select value=${view.device || ""} onChange=${set("device")}>
              ${doc.targets.map((t) => html`<option value=${t}>${t}</option>`)}
            </select></label>
          ${doc.styles.length ? html`<label>Style
            <select value=${view.style} onChange=${set("style")}>
              <option value="">default</option>
              ${doc.styles.map((s) => html`<option value=${s.name}>${s.label}</option>`)}
            </select></label>` : null}
          <label>Time <input type="time" step="1" value=${view.time} onChange=${set("time")} /></label>
          <label><input type="checkbox" checked=${view.asleep} onChange=${set("asleep")} /> asleep</label>
          <label><input type="checkbox" checked=${view.aod} onChange=${set("aod")} /> AOD</label>
          <label>Zoom
            <select value=${view.scale} onChange=${(e) => setView({ ...view, scale: Number(e.target.value) })}>
              ${[1, 2, 3, 4].map((n) => html`<option value=${n}>${n}×</option>`)}
            </select></label>
        </div>
        <div class="canvas-wrap">
          ${busy ? html`<div class="busy">rendering…</div>` : null}
          ${frame ? html`<${Canvas} frame=${frame} layers=${layers} selected=${selected}
                                    onPick=${setSelected} onDrag=${onDrag} />`
                  : html`<div class="empty">${doc.loads ? "No frame yet." :
                      "The face does not load, so there is nothing to draw. The diagnostics on the right say why."}</div>`}
        </div>
        <${Strip} doc=${doc} view=${view} onDevice=${(d) => setView({ ...view, device: d })} />
      </div>
      <div class="panel right">
        <h3>Properties</h3>
        ${element ? html`<div class="body dim where">
            in <code>${element.path.slice(0, -1).join(".")}</code>, line ${element.line}
            ${box ? html` · ${box[2]}×${box[3]} px at (${box[0]}, ${box[1]})` : ""}
            ${!box && drawn && element.type !== "group" ? " · not drawn in this frame" : ""}
          </div>` : null}
        <${Inspector} doc=${doc} element=${element} device=${view.device} vocab=${vocab}
                      scope=${scope} onScope=${setScope} onEdit=${edit} onError=${onError} />
        <div class="tabs">
          <button class=${tab === "diagnostics" ? "on" : ""} onClick=${() => setTab("diagnostics")}>
            Diagnostics${doc.diagnostics.length ? ` (${doc.diagnostics.length})` : ""}</button>
          <button class=${tab === "history" ? "on" : ""} onClick=${() => setTab("history")}>History</button>
        </div>
        ${tab === "diagnostics"
          ? html`<${Diagnostics} items=${doc.diagnostics} tree=${doc.tree} onSelect=${setSelected} />`
          : html`<${History} doc=${doc} onError=${onError} onOpen=${(id) => go(id)}
                             onChanged=${(updated) => updated ? setDoc(updated) : loadDoc()} />`}
      </div>
    </div>
  </div>`;
}

// -- the app -------------------------------------------------------------------------

function App() {
  const [docId, setDocId] = useState(route());
  const [toast, setToast] = useState(null);
  useEffect(() => {
    const onHash = () => setDocId(route());
    addEventListener("hashchange", onHash);
    // `wfb studio face.yaml` opens that face first.
    if (!route()) api("/api/home").then((h) => { if (h.initial && !sessionStorage.getItem("wfb-initial-shown")) {
      try { sessionStorage.setItem("wfb-initial-shown", "1"); } catch (_) { /* private mode */ }
      go(h.initial);
    } }, () => {});
    return () => removeEventListener("hashchange", onHash);
  }, []);
  const onError = useCallback((e) => {
    setToast(e.message || String(e));
    setTimeout(() => setToast(null), 6000);
  }, []);
  return html`
    ${docId ? html`<${Editor} docId=${docId} onError=${onError} />` : html`<${Home} onError=${onError} />`}
    ${toast ? html`<div class="toast" onClick=${() => setToast(null)}>${toast}</div>` : null}`;
}

render(html`<${App} />`, document.getElementById("app"));
