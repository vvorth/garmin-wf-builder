// The YAML tab: the face's text in CodeMirror, with the format's schema
// (completion, hovers, its own checks) and wfb's diagnostics in the gutter.
// Typing is sent as the whole text, debounced, against the version it
// was typed over (`textsync.ts`); the worker records it. A change made
// elsewhere meanwhile refuses the send, and the author chooses whose text
// to keep. Selection follows the canvas and the layer tree, and
// the cursor selects the element it is in. Leaving the tab keeps where it
// was scrolled and its cursor in `memory`, and coming back restores them
// unless another element was selected meanwhile; text not yet saved (not
// YAML, refused, or in a conflict) is kept there too and shown again.

import { html } from "htm/preact";
import type { VNode } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import {
  Annotation, EditorSelection, EditorView, HighlightStyle, basicSetup, forceLinting, linter, lintGutter,
  syntaxHighlighting, tags, yaml, yamlSchema,
} from "./vendor/codemirror.module.js";
import type { Diagnostic as LintDiagnostic, JSONSchema7 } from "./vendor/codemirror.module.js";
import type { Diagnostic, Refusal, Summary } from "../src/studio/protocol.ts";
import { elementAtLine, flatten } from "./hit.ts";
import * as sync from "./textsync.ts";
import type { PlanKind, SyncState } from "./textsync.ts";
import { changeSummary, diffCounts, hunks, lineDiff } from "./linediff.ts";
import { api, call } from "./api.ts";

// The text's colours on the studio's dark background, in its own palette:
// CodeMirror's default style is made for a light one, and its keys and
// tags are dark blue there.
const highlight = syntaxHighlighting(HighlightStyle.define([
  { tag: [tags.definition(tags.propertyName), tags.propertyName], color: "#8ab4f8" },
  { tag: [tags.string, tags.special(tags.string)], color: "#a5d6a7" },
  { tag: [tags.number, tags.bool, tags.null, tags.atom], color: "#f5c04a" },
  { tag: tags.comment, color: "#8b93a1", fontStyle: "italic" },
  { tag: [tags.meta, tags.labelName, tags.typeName, tags.keyword], color: "#d4a5f5" },
  { tag: [tags.punctuation, tags.separator, tags.squareBracket, tags.brace], color: "#9aa1ac" },
]));

const DEBOUNCE = 300;
// how a conflict's diff marks each line
const MARKS = { same: "  ", del: "- ", add: "+ " };
// A change the pane makes itself (a reload, a selection from outside): not
// the author's typing, so it is neither sent nor followed.
const remote = Annotation.define<boolean>();

let schema: Promise<JSONSchema7> | null = null;
function loadSchema(): Promise<JSONSchema7> {
  // `r.json()` is untyped: the schema is whatever the server serves
  schema = schema || fetch("/api/schema").then((r) => r.json() as Promise<JSONSchema7>);
  return schema;
}

// wfb's diagnostics as CodeMirror's, by line and column.
function lintFrom(view: EditorView, items: readonly Diagnostic[]): LintDiagnostic[] {
  const doc = view.state.doc;
  return items.filter((d): d is Diagnostic & { line: number } => !!d.line && d.line <= doc.lines).map((d) => {
    const line = doc.line(d.line);
    const from = Math.min(line.from + Math.max(0, (d.col || 1) - 1), line.to);
    return { from, to: Math.max(from, line.to), severity: d.severity === "note" ? "info" : d.severity,
             message: d.message + (d.notes.length ? "\n" + d.notes.join("\n") : ""), source: `wfb ${d.code}` };
  });
}

/** A position in the text by line and column, so an edit made meanwhile moves it little. */
type Spot = [line: number, col: number];

/** Where the pane was: the top line shown (and how far into it), and the cursor. */
interface Scrolled {
  top: number;
  into: number;
  anchor: Spot;
  head: Spot;
}

/** `Scrolled`, with the element selected then and when the pane left. */
export interface Place extends Scrolled {
  selected: string | null;
  at: number;
}

// Where the pane was: the top line shown (and how far into it), and the
// cursor, by line and column so an edit made meanwhile moves it little.
function remember(v: EditorView): Scrolled {
  const d = v.state.doc;
  const block = v.lineBlockAtHeight(v.scrollDOM.scrollTop);
  const spot = (pos: number): Spot => { const l = d.lineAt(pos); return [l.number, pos - l.from]; };
  const sel = v.state.selection.main;
  return { top: d.lineAt(block.from).number, into: v.scrollDOM.scrollTop - block.top,
           anchor: spot(sel.anchor), head: spot(sel.head) };
}

function restore(v: EditorView, place: Scrolled): void {
  const d = v.state.doc;
  const pos = ([line, col]: Spot): number => { const l = d.line(Math.min(line, d.lines)); return Math.min(l.from + col, l.to); };
  v.dispatch({ selection: EditorSelection.single(pos(place.anchor), pos(place.head)), annotations: remote.of(true) });
  const top = d.line(Math.min(place.top, d.lines)).from;
  // once laid out: the line's height is known only then
  v.requestMeasure({ read: () => v.lineBlockAt(top).top,
                     write: (y) => { v.scrollDOM.scrollTop = y + place.into; } });
}

/** Why the pane's text is not saved: not YAML, or the request failed. */
export type Status = { kind: "invalid" | "failed"; message: string } | null;

/** The open pane, as a send answered after the tab closed reaches it. */
interface PaneHandle {
  setStatus(status: Status): void;
  setConflict(conflict: boolean): void;
  settled(): void;
  /** The pane's text now. */
  text(): string | null;
}

/** The pane's text on its way to the worker, kept while the face is open. */
export interface TextBox {
  sync: SyncState;
  /** The text the tab closed on, unsaved, or null. */
  left: string | null;
  status: Status;
  /** A send is out. */
  sending: boolean;
  /** The open pane's display, or null while the tab is closed. */
  pane: PaneHandle | null;
}

/** What the editor keeps for the pane while the face is open: its place, and its text's state. */
export interface YamlMemory {
  place?: Place;
  text?: TextBox;
}

/** Lines the pane is asked to select, from a link elsewhere; `at` tells a new ask from the last. */
export interface Reveal {
  line: number;
  end?: number | null | undefined;
  at: number;
}

export interface YamlPaneProps {
  doc: Summary;
  selected: string | null;
  reveal: Reveal | null;
  memory: YamlMemory | null | undefined;
  /** The face, when the worker took the text. */
  onDoc(face: Summary): void;
  /** The element the cursor is in. */
  onSelect(id: string): void;
  onError(e: unknown): void;
  /** Whether the pane's text is saved: `textsync.plan`'s kind. */
  onSaving(kind: PlanKind): void;
}

/** What each render leaves for the pane's listeners, which outlive it. */
interface PaneState {
  doc: Summary;
  timer: number | null;
  selectTimer: number | null;
  onSaving: (kind: PlanKind) => void;
  onSelect: (id: string) => void;
  selected: string | null;
}

// `memory`: an object the editor keeps while the face is open, where the
// pane leaves its place for next time, and its text on its way to the
// worker (`memory.text`, below), so that a send answered after the tab
// closed, and text the worker did not take, reach the pane that reopens.
// `onSaving(kind)` hears whether the pane's text is saved: `textsync.plan`'s
// "idle" (saved), "send" (on its way) or "held"/"wait" (not saved).
export function YamlPane({ doc, selected, reveal, memory, onDoc, onSelect, onSaving }: YamlPaneProps): VNode {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const own = useRef<YamlMemory>({});
  // `sync`: `textsync`'s state; `left`: the text the tab closed on, unsaved;
  // `status`: why the text is not saved, `{kind: "invalid" | "failed",
  // message}`, kept until a send succeeds (a failed one offers to send
  // again); `sending`: a send is out; `pane`: the open pane's display, or
  // null while the tab is closed
  const box: TextBox = (memory || own.current).text ||=
    { sync: sync.initial(doc), left: null, status: null, sending: false, pane: null };
  const state = useRef<PaneState>({ doc, timer: null, selectTimer: null, onSaving, onSelect, selected });
  const [status, setStatus] = useState<Status>(box.left === null ? null : box.status);
  const [conflict, setConflict] = useState<boolean>(box.left !== null && box.sync.conflict);
  // whether the conflict banner lists the other change's lines
  const [showOther, setShowOther] = useState(false);
  useEffect(() => { if (!conflict) setShowOther(false); }, [conflict]);
  state.current.doc = doc;
  state.current.onSaving = onSaving;
  state.current.onSelect = onSelect;
  // the pane's text: the editor's while the tab is open, else what it left
  const buffer = (): string | null => (view.current ? view.current.state.doc.toString() : box.left);
  // tell the editor whether `text` (the pane's text now) is saved
  const report = (text: string | null): void => {
    const s = state.current;
    s.onSaving(box.sending ? "send" : text === null ? "idle" : sync.plan(box.sync, text).kind);
  };
  const show = (st: Status): void => { box.status = st; if (box.pane) box.pane.setStatus(st); };
  state.current.selected = selected;

  // Send the pane's text, if it is to be sent. With the tab closed, the
  // text it left is sent, and the answer is kept for when it reopens.
  const send = async (): Promise<void> => {
    const s = state.current;
    const text = buffer();
    if (text === null || box.sending) return;
    const step = sync.plan(box.sync, text);
    if (step.kind !== "send") { if (step.kind === "idle") show(null); return; }
    box.sending = true;
    let answered = false;
    try {
      const response = await call("text", { id: s.doc.id, version: step.version, text: step.text });
      const ok = response.status === 200;
      // the face, when the worker took the text; else why it did not
      const face: Summary | null = response.status === 200 ? response.json ?? null : null;
      const refusal: Refusal | null = response.status === 200 ? null : response.json;
      box.sync = sync.answered(box.sync, step.text, response.status, face ? face.version : null);
      answered = true;
      if (ok) {
        show(null);
        if (face) onDoc(face);
      } else if (response.status === 409) {
        // changed elsewhere since the pane's text was typed over: the
        // text stays, and the author chooses (`choose`)
        if (box.pane) box.pane.setConflict(true);
        onDoc(await api("get", { id: s.doc.id }));
      } else if (response.status === 400) {
        // not YAML yet: keep typing; nothing was recorded
        show({ kind: "invalid", message: (refusal && refusal.error) || "the text is not YAML" });
      } else {
        show({ kind: "failed", message: (refusal && refusal.error) || `${response.status}` });
      }
    } catch (e) {
      if (!answered) box.sync = sync.failed(box.sync, step.text);
      show({ kind: "failed", message: (e instanceof Error && e.message) || String(e) });
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
  const settled = (): void => {
    const s = state.current;
    const text = buffer();
    report(text);
    if (text !== null && sync.plan(box.sync, text).kind === "send" && !s.timer) {
      s.timer = setTimeout(() => { s.timer = null; send(); }, DEBOUNCE);
    }
  };

  // Send the held text again, after a failure the author has seen.
  const retry = (): void => {
    box.sync = sync.retry(box.sync);
    if (view.current) report(view.current.state.doc.toString());
    send();
  };

  // The author's choice after a refused send: "mine" sends the pane's
  // text over the newer face, "theirs" shows the newer face.
  const choose = (choice: "mine" | "theirs"): void => {
    const s = state.current;
    const chosen = sync.resolve(box.sync, s.doc, choice);
    box.sync = chosen.state;
    if (view.current) report(chosen.replace ?? view.current.state.doc.toString());
    setConflict(false);
    show(null);
    if (chosen.replace !== null) replace(chosen.replace);
    else send();
  };

  const replace = (text: string): void => {
    const v = view.current;
    if (!v || v.state.doc.toString() === text) return;
    v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: text }, annotations: remote.of(true) });
  };

  // Leaving or reloading the page kills the worker with it: text waiting
  // out the debounce is sent at once (the editor asks the browser to
  // confirm leaving while it is on its way).
  useEffect(() => {
    const flush = (): void => {
      const st = state.current;
      if (st.timer === null) return;
      clearTimeout(st.timer);
      st.timer = null;
      send();
    };
    addEventListener("pagehide", flush);
    addEventListener("beforeunload", flush);
    return () => { removeEventListener("pagehide", flush); removeEventListener("beforeunload", flush); };
  }, [doc.id]);

  useEffect(() => {
    let alive = true;
    loadSchema().then((s) => {
      if (!alive || !host.current) return;
      const typed = EditorView.updateListener.of((u) => {
        const st = state.current;
        const own = u.transactions.some((t) => t.annotation(remote));
        if (u.docChanged && !own) {
          report(u.state.doc.toString());
          if (st.timer !== null) clearTimeout(st.timer);
          st.timer = setTimeout(() => { st.timer = null; send(); }, DEBOUNCE);
        }
        if (u.selectionSet && !own && u.view.hasFocus) {
          if (st.selectTimer !== null) clearTimeout(st.selectTimer);
          st.selectTimer = setTimeout(() => {
            const line = u.state.doc.lineAt(u.state.selection.main.head).number;
            const node = elementAtLine(st.doc.tree, line);
            if (node) st.onSelect(node.id);
          }, 150);
        }
      });
      // the text the tab last closed on, if the worker does not have it
      const kept = box.left !== null;
      const opened = sync.reopened(box.sync, box.left, state.current.doc);
      box.sync = opened.state;
      box.left = null;
      if (!kept) box.status = null;
      box.pane = { setStatus, setConflict, settled, text: buffer };
      setConflict(box.sync.conflict);
      setStatus(box.status);
      const v = new EditorView({
        parent: host.current,
        doc: opened.text,
        extensions: [
          basicSetup, highlight, yaml(), yamlSchema(s), lintGutter(),
          linter((lv) => lintFrom(lv, state.current.doc.diagnostics), { delay: 0 }),
          typed, EditorView.theme({ "&": { height: "100%" }, ".cm-scroller": { overflow: "auto" } }, { dark: true }),
        ],
      });
      view.current = v;
      // the effects below ran before the view existed: catch up with them
      follow(state.current.doc);
      if (!box.sending) settled();
      const place = memory && memory.place;
      if (reveal && (!place || reveal.at > place.at)) showReveal(v);
      else if (place && place.selected === selected) { restore(v, place); v.focus(); }
      else showSelected(v);
    });
    return () => {
      alive = false;
      const st = state.current;
      if (st.timer !== null) clearTimeout(st.timer);
      if (st.selectTimer !== null) clearTimeout(st.selectTimer);
      if (box.pane && box.pane.settled === settled) box.pane = null;
      const v = view.current;
      if (!v) return;
      if (memory) memory.place = { ...remember(v), selected: st.selected, at: Date.now() };
      // text not saved stays in `box` for the pane that reopens; text on
      // its way is sent from there
      const left = sync.closed(box.sync, v.state.doc.toString());
      box.left = left.left;
      v.destroy();
      view.current = null;
      if (left.kind === "send") send();
      else report(box.left);
    };
  }, [doc.id]);

  // a change made elsewhere (the canvas, the inspector, undo) reaches the
  // pane when the author has nothing unsent
  const follow = (face: Summary): void => {
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
  const showSelected = (v: EditorView): void => {
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
  const showReveal = (v: EditorView): void => {
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
  const counts = other ? diffCounts(other) : null;
  return html`<div class="yaml-pane">
    ${other && counts ? html`<div class="yaml-conflict" role="alert">
      <span>The face changed elsewhere while you were typing, so your text was not saved.
        The other change ${changeSummary(counts)}.</span>
      ${counts.added + counts.removed
        ? html`<button onClick=${() => setShowOther(!showOther)} aria-expanded=${showOther}>
            ${showOther ? "Hide it" : "Show it"}</button>` : null}
      <button onClick=${() => choose("mine")} title="Save your text over the other change (undoable)">Keep my text</button>
      <button onClick=${() => choose("theirs")} title="Discard your typing and show the face as it now is">Take the face as it is</button>
      ${showOther ? html`<pre class="yaml-diff">${hunks(other).map((o) => o.op === "gap"
        ? html`<div class="gap">⋯</div>`
        : html`<div class=${o.op}>${MARKS[o.op]}${o.text}</div>`)}</pre>` : null}
    </div>` : null}
    <div class="yaml-host" ref=${host}></div>
    ${status && status.kind === "invalid"
      ? html`<div class="yaml-status">${status.message} — not saved until it is YAML again</div>` : null}
    ${status && status.kind === "failed"
      ? html`<div class="yaml-status failed" role="alert">Not saved: ${status.message}
          <button onClick=${retry}>Retry</button></div>` : null}
  </div>`;
}
