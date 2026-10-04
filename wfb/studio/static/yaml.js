// The YAML tab: the face's text in CodeMirror, with the format's schema
// (completion, hovers, its own checks) and wfb's diagnostics in the gutter.
// Typing is sent as the whole text, debounced, against the version it
// was typed over (`textsync.js`); the server records it. A change made
// elsewhere meanwhile refuses the send, and the author chooses whose text
// to keep. Selection follows the canvas and the layer tree, and
// the cursor selects the element it is in. Leaving the tab keeps where it
// was scrolled and its cursor in `memory`, and coming back restores them
// unless another element was selected meanwhile.

import { html, useEffect, useRef, useState } from "./vendor/preact-htm.module.js";
import {
  Annotation, EditorSelection, EditorView, basicSetup, forceLinting, linter, lintGutter, yaml,
  yamlSchema,
} from "./vendor/codemirror.module.js";
import { elementAtLine, flatten } from "./hit.js";
import * as sync from "./textsync.js";
import { sessionLost } from "./session.js";

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
// `onSaving(kind)` hears whether the pane's text is saved: `textsync.plan`'s
// "idle" (saved), "send" (on its way) or "held"/"wait" (not saved).
export function YamlPane({ doc, selected, reveal, memory, onDoc, onSelect, onError, onSaving }) {
  const host = useRef(null);
  const view = useRef(null);
  const state = useRef({ doc, sync: sync.initial(doc), timer: null, sending: false, selectTimer: null });
  // why the pane's text is not saved: `{kind: "invalid" | "failed", message}`,
  // kept until a send succeeds; a failed one offers to send again
  const [status, setStatus] = useState(null);
  const [conflict, setConflict] = useState(false);
  state.current.doc = doc;
  state.current.onSaving = onSaving;
  state.current.onSelect = onSelect;
  // tell the editor whether `buffer` (the text now) is saved
  const report = (buffer) => {
    const s = state.current;
    if (s.onSaving) s.onSaving(s.sending ? "send" : sync.plan(s.sync, buffer).kind);
  };
  state.current.selected = selected;

  const send = async () => {
    const s = state.current;
    const v = view.current;
    if (!v || s.sending) return;
    const step = sync.plan(s.sync, v.state.doc.toString());
    if (step.kind !== "send") { if (step.kind === "idle") setStatus(null); return; }
    s.sending = true;
    let answered = false;
    try {
      const response = await fetch(`/api/documents/${s.doc.id}/text?version=${step.version}`,
                                   { method: "POST", body: step.text });
      // an error page from something between (a proxy) may not be JSON
      const body = await response.json().catch(() => ({}));
      s.sync = sync.answered(s.sync, step.text, response.status, body.version);
      answered = true;
      if (response.ok) {
        setStatus(null);
        onDoc(body);
      } else if (response.status === 409) {
        // changed elsewhere since the pane's text was typed over: the
        // text stays, and the author chooses (`choose`)
        setConflict(true);
        onDoc(await (await fetch(`/api/documents/${s.doc.id}`)).json());
      } else if (response.status === 401) {
        setStatus({ kind: "failed", message: "this browser's session has ended" });
        sessionLost();
      } else if (response.status === 400) {
        // not YAML yet: keep typing; nothing was recorded
        setStatus({ kind: "invalid", message: body.error || "the text is not YAML" });
      } else {
        setStatus({ kind: "failed", message: body.error || `${response.status} ${response.statusText}` });
      }
    } catch (e) {
      if (!answered) s.sync = sync.failed(s.sync, step.text);
      setStatus({ kind: "failed", message: e.message || String(e) });
    } finally {
      s.sending = false;
      report(view.current ? view.current.state.doc.toString() : step.text);
      if (view.current && sync.plan(s.sync, view.current.state.doc.toString()).kind === "send"
          && !s.timer) {
        s.timer = setTimeout(() => { s.timer = null; send(); }, DEBOUNCE);
      }
    }
  };

  // The author's choice after a refused send: "mine" sends the pane's
  // text over the newer face, "theirs" shows the newer face.
  // Send the held text again, after a failure the author has seen.
  const retry = () => {
    state.current.sync = sync.retry(state.current.sync);
    if (view.current) report(view.current.state.doc.toString());
    send();
  };

  const choose = (choice) => {
    const s = state.current;
    const settled = sync.resolve(s.sync, s.doc, choice);
    s.sync = settled.state;
    if (view.current) report(settled.replace ?? view.current.state.doc.toString());
    setConflict(false);
    setStatus(null);
    if (settled.replace !== null) replace(settled.replace);
    else send();
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
          report(u.state.doc.toString());
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
      if (view.current && sync.plan(st.sync, view.current.state.doc.toString()).kind === "send") send();
      else if (st.onSaving) st.onSaving("idle");
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
    const followed = sync.follow(st.sync, doc, v.state.doc.toString());
    st.sync = followed.state;
    report(followed.replace ?? v.state.doc.toString());
    if (followed.replace !== null) replace(followed.replace);
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
    ${conflict ? html`<div class="yaml-conflict" role="alert">
      The face changed elsewhere while you were typing, so your text was not saved.
      <button onClick=${() => choose("mine")} title="Save your text over the other change (undoable)">Keep my text</button>
      <button onClick=${() => choose("theirs")} title="Discard your typing and show the face as it now is">Take the face as it is</button>
    </div>` : null}
    <div class="yaml-host" ref=${host}></div>
    ${status && status.kind === "invalid"
      ? html`<div class="yaml-status">${status.message} — not saved until it is YAML again</div>` : null}
    ${status && status.kind === "failed"
      ? html`<div class="yaml-status failed" role="alert">Not saved: ${status.message}
          <button onClick=${retry}>Retry</button></div>` : null}
  </div>`;
}
