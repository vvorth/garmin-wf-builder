// The YAML tab: the face's text in CodeMirror, with the format's schema
// (completion, hovers, its own checks) and wfb's diagnostics in the gutter.
// The pane is a view of the store's `yaml` slice (`store.ts`): typing goes
// up as `replaceText`, which the store sends debounced against the version
// it was typed over (`textsync.ts`); the text the store holds comes back
// down, so a change made elsewhere replaces the pane's text once nothing
// is unsent, and a refused send (changed elsewhere meanwhile) shows the
// conflict for the author to settle. Selection follows the canvas and the
// layer tree, and the cursor selects the element it is in. Leaving the tab
// keeps where it was scrolled and its cursor in the store, and coming back
// restores them unless another element was selected meanwhile.

import { html } from "htm/preact";
import type { VNode } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import {
  Annotation, EditorSelection, EditorView, HighlightStyle, basicSetup, forceLinting, linter, lintGutter,
  syntaxHighlighting, tags, yaml, yamlSchema,
} from "./vendor/codemirror.module.js";
import type { Diagnostic as LintDiagnostic, JSONSchema7 } from "./vendor/codemirror.module.js";
import type { Diagnostic, Summary } from "../src/studio/protocol.ts";
import { elementAtLine, flatten } from "./hit.ts";
import { changeSummary, diffCounts, hunks, lineDiff } from "./linediff.ts";
import { useEditorStore, useStore } from "./store.ts";
import type { YamlPlace } from "./store.ts";

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

// how a conflict's diff marks each line
const MARKS = { same: "  ", del: "- ", add: "+ " };
// A change the pane makes itself (the store's text, a selection from
// outside): not the author's typing, so it is neither sent nor followed.
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

// Where the pane was: the top line shown (and how far into it), and the
// cursor, by line and column so an edit made meanwhile moves it little.
function remember(v: EditorView): Omit<YamlPlace, "selected" | "at"> {
  const d = v.state.doc;
  const block = v.lineBlockAtHeight(v.scrollDOM.scrollTop);
  const spot = (pos: number): Spot => { const l = d.lineAt(pos); return [l.number, pos - l.from]; };
  const sel = v.state.selection.main;
  return { top: d.lineAt(block.from).number, into: v.scrollDOM.scrollTop - block.top,
           anchor: spot(sel.anchor), head: spot(sel.head) };
}

function restore(v: EditorView, place: YamlPlace): void {
  const d = v.state.doc;
  const pos = ([line, col]: Spot): number => { const l = d.line(Math.min(line, d.lines)); return Math.min(l.from + col, l.to); };
  v.dispatch({ selection: EditorSelection.single(pos(place.anchor), pos(place.head)), annotations: remote.of(true) });
  const top = d.line(Math.min(place.top, d.lines)).from;
  // once laid out: the line's height is known only then
  v.requestMeasure({ read: () => v.lineBlockAt(top).top,
                     write: (y) => { v.scrollDOM.scrollTop = y + place.into; } });
}

export interface YamlPaneProps {
  doc: Summary;
}

/** What each render leaves for the pane's listeners, which outlive it. */
interface PaneState {
  doc: Summary;
  selectTimer: ReturnType<typeof setTimeout> | null;
  selected: string | null;
}

export function YamlPane({ doc }: YamlPaneProps): VNode {
  const store = useEditorStore();
  const selected = useStore((s) => s.selection.primary);
  const status = useStore((s) => s.yaml.status);
  const conflict = useStore((s) => s.yaml.conflict);
  const acked = useStore((s) => s.yaml.sync.acked);
  const reveal = useStore((s) => s.yaml.reveal);
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const state = useRef<PaneState>({ doc, selectTimer: null, selected });
  state.current.doc = doc;
  state.current.selected = selected;
  // whether the conflict banner lists the other change's lines
  const [showOther, setShowOther] = useState(false);
  useEffect(() => { if (!conflict) setShowOther(false); }, [conflict]);

  // The store's text shown, when the pane's differs: a change made
  // elsewhere, or the author's choice after a conflict. Done on the store's
  // own notice, not on a render: a render lags the keystrokes, and a stale
  // text put back over them would lose what was typed meanwhile.
  const replace = (wanted: string): void => {
    const v = view.current;
    if (!v || v.state.doc.toString() === wanted) return;
    v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: wanted }, annotations: remote.of(true) });
  };

  useEffect(() => {
    let alive = true;
    let unsubscribe: (() => void) | null = null;
    loadSchema().then((s) => {
      if (!alive || !host.current) return;
      const typed = EditorView.updateListener.of((u) => {
        const st = state.current;
        const own = u.transactions.some((t) => t.annotation(remote));
        if (u.docChanged && !own) store.replaceText(u.state.doc.toString());
        if (u.selectionSet && !own && u.view.hasFocus) {
          if (st.selectTimer !== null) clearTimeout(st.selectTimer);
          st.selectTimer = setTimeout(() => {
            const line = u.state.doc.lineAt(u.state.selection.main.head).number;
            const node = elementAtLine(st.doc.tree, line);
            if (node) store.select(node.id);
          }, 150);
        }
      });
      // with nothing unsent, the face as it now is; else the text left unsaved
      store.yamlOpened();
      const v = new EditorView({
        parent: host.current,
        doc: store.state.yaml.text,
        extensions: [
          basicSetup, highlight, yaml(), yamlSchema(s), lintGutter(),
          linter((lv) => lintFrom(lv, state.current.doc.diagnostics), { delay: 0 }),
          typed, EditorView.theme({ "&": { height: "100%" }, ".cm-scroller": { overflow: "auto" } }, { dark: true }),
        ],
      });
      view.current = v;
      unsubscribe = store.subscribe(() => replace(store.state.yaml.text));
      const place = store.yamlPlaces.get(doc.id);
      const asked = store.state.yaml.reveal;
      if (asked && (!place || asked.at > place.at)) showReveal(v, asked);
      else if (place && place.selected === state.current.selected) { restore(v, place); v.focus(); }
      else showSelected(v);
    });
    return () => {
      alive = false;
      if (unsubscribe) unsubscribe();
      const st = state.current;
      if (st.selectTimer !== null) clearTimeout(st.selectTimer);
      const v = view.current;
      if (!v) return;
      store.yamlPlaces.set(doc.id, { ...remember(v), selected: st.selected, at: Date.now() });
      // text waiting out the debounce goes now; text the worker did not
      // take stays in the store for the pane that reopens
      store.flushText();
      v.destroy();
      view.current = null;
    };
  }, [doc.id]);

  useEffect(() => { if (view.current) forceLinting(view.current); }, [doc.version, doc.diagnostics]);

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
  const showReveal = (v: EditorView, asked: NonNullable<typeof reveal>): void => {
    if (asked.line > v.state.doc.lines) return;
    const from = v.state.doc.line(asked.line).from;
    const to = v.state.doc.line(Math.min(asked.end || asked.line, v.state.doc.lines)).to;
    v.dispatch({ selection: EditorSelection.range(from, to), annotations: remote.of(true),
                 effects: EditorView.scrollIntoView(from, { y: "start", yMargin: 40 }) });
    v.focus();
  };
  useEffect(() => { if (view.current && reveal) showReveal(view.current, reveal); }, [reveal && reveal.at]);

  // the other change: from the text the pane's was typed over to the face now
  const other = conflict ? lineDiff(acked, doc.text) : null;
  const counts = other ? diffCounts(other) : null;
  return html`<div class="yaml-pane">
    ${other && counts ? html`<div class="yaml-conflict" role="alert">
      <span>The face changed elsewhere while you were typing, so your text was not saved.
        The other change ${changeSummary(counts)}.</span>
      ${counts.added + counts.removed
        ? html`<button onClick=${() => setShowOther(!showOther)} aria-expanded=${showOther}>
            ${showOther ? "Hide it" : "Show it"}</button>` : null}
      <button onClick=${() => store.yamlChoose("mine")} title="Save your text over the other change (undoable)">Keep my text</button>
      <button onClick=${() => store.yamlChoose("theirs")} title="Discard your typing and show the face as it now is">Take the face as it is</button>
      ${showOther ? html`<pre class="yaml-diff">${hunks(other).map((o) => o.op === "gap"
        ? html`<div class="gap">⋯</div>`
        : html`<div class=${o.op}>${MARKS[o.op]}${o.text}</div>`)}</pre>` : null}
    </div>` : null}
    <div class="yaml-host" ref=${host}></div>
    ${status && status.kind === "invalid"
      ? html`<div class="yaml-status">${status.message} — not saved until it is YAML again</div>` : null}
    ${status && status.kind === "failed"
      ? html`<div class="yaml-status failed" role="alert">Not saved: ${status.message}
          <button onClick=${() => store.yamlRetry()}>Retry</button></div>` : null}
  </div>`;
}
