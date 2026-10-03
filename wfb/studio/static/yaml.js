// The YAML tab: the face's text in CodeMirror, with the format's schema
// (completion, hovers, its own checks) and wfb's diagnostics in the gutter.
// Typing is sent as the whole text, debounced, against the version it
// started from; the server records it, and a version moved on elsewhere
// reloads the pane. Selection follows the canvas and the layer tree, and
// the cursor selects the element it is in.

import { html, useEffect, useRef, useState } from "./vendor/preact-htm.module.js";
import {
  Annotation, EditorSelection, EditorView, basicSetup, forceLinting, linter, lintGutter, yaml,
  yamlSchema,
} from "./vendor/codemirror.module.js";
import { elementAtLine, flatten } from "./hit.js";

const DEBOUNCE = 300;
// A change the pane makes itself (a reload, a selection from outside): not
// the author's typing, so it is neither sent nor followed.
const remote = Annotation.define();

let schema = null;
function loadSchema() {
  schema = schema || fetch("/api/schema").then((r) => r.json());
  return schema;
}

// wfb's diagnostics as CodeMirror's, by line and column.
function lintFrom(view, items) {
  const doc = view.state.doc;
  return items.filter((d) => d.line && d.line <= doc.lines).map((d) => {
    const line = doc.line(d.line);
    const from = Math.min(line.from + Math.max(0, (d.col || 1) - 1), line.to);
    return { from, to: Math.max(from, line.to), severity: d.severity === "note" ? "info" : d.severity,
             message: d.message + (d.notes.length ? "\n" + d.notes.join("\n") : ""), source: `wfb ${d.code}` };
  });
}

export function YamlPane({ doc, selected, reveal, onDoc, onSelect, onError }) {
  const host = useRef(null);
  const view = useRef(null);
  const state = useRef({ doc, acked: doc.text, timer: null, sending: false, selectTimer: null });
  const [status, setStatus] = useState("");
  state.current.doc = doc;
  state.current.onSelect = onSelect;

  const send = async () => {
    const s = state.current;
    const v = view.current;
    if (!v || s.sending) return;
    const text = v.state.doc.toString();
    if (text === s.acked) { setStatus(""); return; }     // back to what the server has
    s.sending = true;
    try {
      const response = await fetch(`/api/documents/${s.doc.id}/text?version=${s.doc.version}`,
                                   { method: "POST", body: text });
      const body = await response.json();
      if (response.ok) {
        s.acked = text;
        setStatus("");
        onDoc(body);
      } else if (response.status === 409) {
        onError(new Error(`${body.error} — the text was reloaded`));
        const fresh = await (await fetch(`/api/documents/${s.doc.id}`)).json();
        s.acked = fresh.text;
        replace(fresh.text);
        onDoc(fresh);
      } else {
        // not YAML yet: keep typing; nothing was recorded
        setStatus(body.error || `${response.status}`);
      }
    } catch (e) { onError(e); } finally {
      s.sending = false;
      if (view.current && view.current.state.doc.toString() !== s.acked && !s.timer) {
        s.timer = setTimeout(() => { s.timer = null; send(); }, DEBOUNCE);
      }
    }
  };

  const replace = (text) => {
    const v = view.current;
    if (!v || v.state.doc.toString() === text) return;
    v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: text }, annotations: remote.of(true) });
  };

  useEffect(() => {
    let alive = true;
    loadSchema().then((s) => {
      if (!alive || !host.current) return;
      const typed = EditorView.updateListener.of((u) => {
        const st = state.current;
        const own = u.transactions.some((t) => t.annotation(remote));
        if (u.docChanged && !own) {
          clearTimeout(st.timer);
          st.timer = setTimeout(() => { st.timer = null; send(); }, DEBOUNCE);
        }
        if (u.selectionSet && !own && u.view.hasFocus) {
          clearTimeout(st.selectTimer);
          st.selectTimer = setTimeout(() => {
            const line = u.state.doc.lineAt(u.state.selection.main.head).number;
            const node = elementAtLine(st.doc.tree, line);
            if (node) st.onSelect(node.id);
          }, 150);
        }
      });
      view.current = new EditorView({
        parent: host.current,
        doc: state.current.doc.text,
        extensions: [
          basicSetup, yaml(), yamlSchema(s), lintGutter(),
          linter((v) => lintFrom(v, state.current.doc.diagnostics), { delay: 0 }),
          typed, EditorView.theme({ "&": { height: "100%" }, ".cm-scroller": { overflow: "auto" } }),
        ],
      });
    });
    return () => {
      alive = false;
      const st = state.current;
      clearTimeout(st.timer); clearTimeout(st.selectTimer);
      if (view.current && view.current.state.doc.toString() !== st.acked) send();
      view.current && view.current.destroy();
      view.current = null;
    };
  }, [doc.id]);

  // a change made elsewhere (the canvas, the inspector, undo) reaches the
  // pane when the author has nothing unsent
  useEffect(() => {
    const st = state.current;
    const v = view.current;
    if (!v) return;
    if (v.state.doc.toString() === st.acked && doc.text !== st.acked) {
      st.acked = doc.text;
      replace(doc.text);
    }
    forceLinting(v);
  }, [doc.version, doc.text]);

  // a selection made elsewhere selects the element's lines
  useEffect(() => {
    const v = view.current;
    if (!v || !selected || v.hasFocus) return;
    const node = flatten(doc.tree).find((n) => n.id === selected);
    if (!node || node.line > v.state.doc.lines) return;
    const from = v.state.doc.line(node.line).from;
    const to = v.state.doc.line(Math.min(node.end || node.line, v.state.doc.lines)).to;
    v.dispatch({ selection: EditorSelection.range(from, to), annotations: remote.of(true),
                 effects: EditorView.scrollIntoView(from, { y: "start", yMargin: 40 }) });
  }, [selected, doc.version]);

  // lines asked for from elsewhere (a hand set's "Edit in YAML")
  useEffect(() => {
    const v = view.current;
    if (!v || !reveal || reveal.line > v.state.doc.lines) return;
    const from = v.state.doc.line(reveal.line).from;
    const to = v.state.doc.line(Math.min(reveal.end || reveal.line, v.state.doc.lines)).to;
    v.dispatch({ selection: EditorSelection.range(from, to), annotations: remote.of(true),
                 effects: EditorView.scrollIntoView(from, { y: "start", yMargin: 40 }) });
    v.focus();
  }, [reveal && reveal.at]);

  return html`<div class="yaml-pane">
    <div class="yaml-host" ref=${host}></div>
    ${status ? html`<div class="yaml-status">${status} — not recorded until it is YAML again</div>` : null}
  </div>`;
}
