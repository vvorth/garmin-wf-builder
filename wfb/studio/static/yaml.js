// The YAML tab: the face's text in CodeMirror, with the format's schema
// (completion, hovers, its own checks) and wfb's diagnostics in the gutter.
// Typing is sent as the whole text, debounced, against the version it
// was typed over (`textsync.js`); the server records it. A change made
// elsewhere meanwhile refuses the send, and the author chooses whose text
// to keep. Selection follows the canvas and the layer tree, and
// the cursor selects the element it is in. Leaving the tab keeps where it
// was scrolled and its cursor in `memory`, and coming back restores them
// unless another element was selected meanwhile; text not yet saved (not
// YAML, refused, or in a conflict) is kept there too and shown again.

import { html, useEffect, useRef, useState } from "./vendor/preact-htm.module.js";
import {
  Annotation, EditorSelection, EditorView, basicSetup, forceLinting, linter, lintGutter, yaml,
  yamlSchema,
} from "./vendor/codemirror.module.js";
import { elementAtLine, flatten } from "./hit.js";
import * as sync from "./textsync.js";
import { changeSummary, diffCounts, hunks, lineDiff } from "./linediff.js";
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
// pane leaves its place for next time, and its text on its way to the
// server (`memory.text`, below), so that a send answered after the tab
// closed, and text the server did not take, reach the pane that reopens.
// `onSaving(kind)` hears whether the pane's text is saved: `textsync.plan`'s
// "idle" (saved), "send" (on its way) or "held"/"wait" (not saved).
export function YamlPane({ doc, selected, reveal, memory, onDoc, onSelect, onError, onSaving }) {
  const host = useRef(null);
  const view = useRef(null);
  const own = useRef({});
  // `sync`: `textsync`'s state; `left`: the text the tab closed on, unsaved;
  // `status`: why the text is not saved, `{kind: "invalid" | "failed",
  // message}`, kept until a send succeeds (a failed one offers to send
  // again); `sending`: a send is out; `pane`: the open pane's display, or
  // null while the tab is closed
  const box = (memory || own.current).text ||=
    { sync: sync.initial(doc), left: null, status: null, sending: false, pane: null };
  const state = useRef({ doc, timer: null, selectTimer: null });
  const [status, setStatus] = useState(box.left === null ? null : box.status);
  const [conflict, setConflict] = useState(box.left !== null && box.sync.conflict);
  // whether the conflict banner lists the other change's lines
  const [showOther, setShowOther] = useState(false);
  useEffect(() => { if (!conflict) setShowOther(false); }, [conflict]);
  state.current.doc = doc;
  state.current.onSaving = onSaving;
  state.current.onSelect = onSelect;
  // the pane's text: the editor's while the tab is open, else what it left
  const buffer = () => (view.current ? view.current.state.doc.toString() : box.left);
  // tell the editor whether `text` (the pane's text now) is saved
  const report = (text) => {
    const s = state.current;
    if (s.onSaving) s.onSaving(box.sending ? "send" : text === null ? "idle" : sync.plan(box.sync, text).kind);
  };
  const show = (st) => { box.status = st; if (box.pane) box.pane.setStatus(st); };
  state.current.selected = selected;

  // Send the pane's text, if it is to be sent. With the tab closed, the
  // text it left is sent, and the answer is kept for when it reopens.
  const send = async () => {
    const s = state.current;
    const text = buffer();
    if (text === null || box.sending) return;
    const step = sync.plan(box.sync, text);
    if (step.kind !== "send") { if (step.kind === "idle") show(null); return; }
    box.sending = true;
    let answered = false;
    try {
      const response = await fetch(`/api/documents/${s.doc.id}/text?version=${step.version}`,
                                   { method: "POST", body: step.text });
      // an error page from something between (a proxy) may not be JSON
      const body = await response.json().catch(() => ({}));
      box.sync = sync.answered(box.sync, step.text, response.status, body.version);
      answered = true;
      if (response.ok) {
        show(null);
        onDoc(body);
      } else if (response.status === 409) {
        // changed elsewhere since the pane's text was typed over: the
        // text stays, and the author chooses (`choose`)
        if (box.pane) box.pane.setConflict(true);
        onDoc(await (await fetch(`/api/documents/${s.doc.id}`)).json());
      } else if (response.status === 401) {
        show({ kind: "failed", message: "this browser's session has ended" });
        sessionLost();
      } else if (response.status === 400) {
        // not YAML yet: keep typing; nothing was recorded
        show({ kind: "invalid", message: body.error || "the text is not YAML" });
      } else {
        show({ kind: "failed", message: body.error || `${response.status} ${response.statusText}` });
      }
    } catch (e) {
      if (!answered) box.sync = sync.failed(box.sync, step.text);
      show({ kind: "failed", message: e.message || String(e) });
    } finally {
      box.sending = false;
      if (box.pane) box.pane.settled();
      else {
        // the tab closed meanwhile: what it left is saved, or still to send
        if (box.left !== null && sync.plan(box.sync, box.left).kind === "idle") box.left = null;
        report(box.left);
        if (box.left !== null && sync.plan(box.sync, box.left).kind === "send") send();
      }
    }
  };

  // A send was answered with the tab open: report it, and send again if
  // the author typed on meanwhile.
  const settled = () => {
    const s = state.current;
    const text = buffer();
    report(text);
    if (text !== null && sync.plan(box.sync, text).kind === "send" && !s.timer) {
      s.timer = setTimeout(() => { s.timer = null; send(); }, DEBOUNCE);
    }
  };

  // The author's choice after a refused send: "mine" sends the pane's
  // text over the newer face, "theirs" shows the newer face.
  // Send the held text again, after a failure the author has seen.
  const retry = () => {
    box.sync = sync.retry(box.sync);
    if (view.current) report(view.current.state.doc.toString());
    send();
  };

  const choose = (choice) => {
    const s = state.current;
    const chosen = sync.resolve(box.sync, s.doc, choice);
    box.sync = chosen.state;
    if (view.current) report(chosen.replace ?? view.current.state.doc.toString());
    setConflict(false);
    show(null);
    if (chosen.replace !== null) replace(chosen.replace);
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
      // the text the tab last closed on, if the server does not have it
      const kept = box.left !== null;
      const opened = sync.reopened(box.sync, box.left, state.current.doc);
      box.sync = opened.state;
      box.left = null;
      if (!kept) box.status = null;
      box.pane = { setStatus, setConflict, settled, text: buffer };
      setConflict(box.sync.conflict);
      setStatus(box.status);
      view.current = new EditorView({
        parent: host.current,
        doc: opened.text,
        extensions: [
          basicSetup, yaml(), yamlSchema(s), lintGutter(),
          linter((v) => lintFrom(v, state.current.doc.diagnostics), { delay: 0 }),
          typed, EditorView.theme({ "&": { height: "100%" }, ".cm-scroller": { overflow: "auto" } }),
        ],
      });
      // the effects below ran before the view existed: catch up with them
      follow(state.current.doc);
      if (!box.sending) settled();
      const place = memory && memory.place;
      if (reveal && (!place || reveal.at > place.at)) showReveal(view.current);
      else if (place && place.selected === selected) { restore(view.current, place); view.current.focus(); }
      else showSelected(view.current);
    });
    return () => {
      alive = false;
      const st = state.current;
      clearTimeout(st.timer); clearTimeout(st.selectTimer);
      if (box.pane && box.pane.settled === settled) box.pane = null;
      if (!view.current) return;
      if (memory) memory.place = { ...remember(view.current), selected: st.selected, at: Date.now() };
      // text not saved stays in `box` for the pane that reopens; text on
      // its way is sent from there
      const left = sync.closed(box.sync, view.current.state.doc.toString());
      box.left = left.left;
      view.current.destroy();
      view.current = null;
      if (left.kind === "send") send();
      else report(box.left);
    };
  }, [doc.id]);

  // a change made elsewhere (the canvas, the inspector, undo) reaches the
  // pane when the author has nothing unsent
  const follow = (face) => {
    const v = view.current;
    if (!v) return;
    const followed = sync.follow(box.sync, face, v.state.doc.toString());
    box.sync = followed.state;
    report(followed.replace ?? v.state.doc.toString());
    if (followed.replace !== null) replace(followed.replace);
    forceLinting(v);
  };
  useEffect(() => { follow(doc); }, [doc.version, doc.text]);

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

  // the other change: from the text the pane's was typed over to the face now
  const other = conflict ? lineDiff(box.sync.acked, doc.text) : null;
  const counts = other && diffCounts(other);
  return html`<div class="yaml-pane">
    ${conflict ? html`<div class="yaml-conflict" role="alert">
      <span>The face changed elsewhere while you were typing, so your text was not saved.
        The other change ${changeSummary(counts)}.</span>
      ${counts.added + counts.removed
        ? html`<button onClick=${() => setShowOther(!showOther)} aria-expanded=${showOther}>
            ${showOther ? "Hide it" : "Show it"}</button>` : null}
      <button onClick=${() => choose("mine")} title="Save your text over the other change (undoable)">Keep my text</button>
      <button onClick=${() => choose("theirs")} title="Discard your typing and show the face as it now is">Take the face as it is</button>
      ${showOther ? html`<pre class="yaml-diff">${hunks(other).map((o) => o.op === "gap"
        ? html`<div class="gap">⋯</div>`
        : html`<div class=${o.op}>${{ same: "  ", del: "- ", add: "+ " }[o.op]}${o.text}</div>`)}</pre>` : null}
    </div>` : null}
    <div class="yaml-host" ref=${host}></div>
    ${status && status.kind === "invalid"
      ? html`<div class="yaml-status">${status.message} — not saved until it is YAML again</div>` : null}
    ${status && status.kind === "failed"
      ? html`<div class="yaml-status failed" role="alert">Not saved: ${status.message}
          <button onClick=${retry}>Retry</button></div>` : null}
  </div>`;
}
