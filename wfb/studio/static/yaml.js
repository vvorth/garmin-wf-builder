// The YAML tab: the face's text in CodeMirror, with the format's schema
// (completion, hovers, its own checks) and wfb's diagnostics in the gutter.
// Typing is sent as the whole text, debounced, against the version it
// started from; the server records it, and a version moved on elsewhere
// reloads the pane. Selection follows the canvas and the layer tree, and
// the cursor selects the element it is in. Leaving the tab keeps where it
// was scrolled and its cursor in `memory`, and coming back restores them
// unless another element was selected meanwhile.

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

// Where the pane was: the top line shown (and how far into it), and the
// cursor, by line and column so an edit made meanwhile moves it little.
function remember(v) {
  const d = v.state.doc;
  const block = v.lineBlockAtHeight(v.scrollDOM.scrollTop);
  const spot = (pos) => { const l = d.lineAt(pos); return [l.number, pos - l.from]; };
  const sel = v.state.selection.main;
  return { top: d.lineAt(block.from).number, into: v.scrollDOM.scrollTop - block.top,
           anchor: spot(sel.anchor), head: spot(sel.head) };
}

function restore(v, place) {
  const d = v.state.doc;
  const pos = ([line, col]) => { const l = d.line(Math.min(line, d.lines)); return Math.min(l.from + col, l.to); };
  v.dispatch({ selection: EditorSelection.single(pos(place.anchor), pos(place.head)), annotations: remote.of(true) });
  const top = d.line(Math.min(place.top, d.lines)).from;
  // once laid out: the line's height is known only then
  v.requestMeasure({ read: () => v.lineBlockAt(top).top,
                     write: (y) => { v.scrollDOM.scrollTop = y + place.into; } });
}

// `memory`: an object the editor keeps while the face is open, where the
// pane leaves its place for next time.
export function YamlPane({ doc, selected, reveal, memory, onDoc, onSelect, onError }) {
  const host = useRef(null);
  const view = useRef(null);
  const state = useRef({ doc, acked: doc.text, timer: null, sending: false, selectTimer: null });
  const [status, setStatus] = useState("");
  state.current.doc = doc;
  state.current.onSelect = onSelect;
  state.current.selected = selected;

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
      // the effects below ran before the view existed: catch up with them
      const place = memory && memory.place;
      if (reveal && (!place || reveal.at > place.at)) showReveal(view.current);
      else if (place && place.selected === selected) { restore(view.current, place); view.current.focus(); }
      else showSelected(view.current);
    });
    return () => {
      alive = false;
      const st = state.current;
      clearTimeout(st.timer); clearTimeout(st.selectTimer);
      if (view.current && memory) {
        memory.place = { ...remember(view.current), selected: st.selected, at: Date.now() };
      }
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
  const showSelected = (v) => {
    if (!selected || v.hasFocus) return;
    const node = flatten(doc.tree).find((n) => n.id === selected);
    if (!node || node.line > v.state.doc.lines) return;
    const from = v.state.doc.line(node.line).from;
    const to = v.state.doc.line(Math.min(node.end || node.line, v.state.doc.lines)).to;
    v.dispatch({ selection: EditorSelection.range(from, to), annotations: remote.of(true),
                 effects: EditorView.scrollIntoView(from, { y: "start", yMargin: 40 }) });
  };
  useEffect(() => { if (view.current) showSelected(view.current); }, [selected, doc.version]);

  // lines asked for from elsewhere (a hand set's "Edit in YAML")
  const showReveal = (v) => {
    if (!reveal || reveal.line > v.state.doc.lines) return;
    const from = v.state.doc.line(reveal.line).from;
    const to = v.state.doc.line(Math.min(reveal.end || reveal.line, v.state.doc.lines)).to;
    v.dispatch({ selection: EditorSelection.range(from, to), annotations: remote.of(true),
                 effects: EditorView.scrollIntoView(from, { y: "start", yMargin: 40 }) });
    v.focus();
  };
  useEffect(() => { if (view.current) showReveal(view.current); }, [reveal && reveal.at]);

  return html`<div class="yaml-pane">
    <div class="yaml-host" ref=${host}></div>
    ${status ? html`<div class="yaml-status">${status} — not recorded until it is YAML again</div>` : null}
  </div>`;
}
