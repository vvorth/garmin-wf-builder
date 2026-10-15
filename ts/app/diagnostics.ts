// The Diagnostics tab: the compiler's diagnostics for the open face, and
// the tab's label. A warning a `lint: {allow}` may accept, on a line inside
// an element, offers "accept here…": it asks for the reason inline (the
// element's own reason, when its `lint:` has one, to keep or change) and
// writes the code into that element's `lint:` as one change.

import type { JSX, VNode } from "preact";
import { html } from "htm/preact";
import { useState } from "preact/hooks";
import type { Diagnostic, Path, Severity, TreeBlock, TreeNode, Value } from "../src/studio/protocol.ts";
import { elementAtLine } from "./hit.ts";
import { severityCounts, shownDiagnostics } from "./values.ts";

/** The tab's filter: every diagnostic, or one severity. */
export type DiagnosticFilter = "all" | Severity;

const NAMES: Record<Severity, string> = { error: "errors", warning: "warnings", note: "notes" };
const SEVERITIES: Severity[] = ["error", "warning", "note"];

// The filter in effect: `filter`, unless no diagnostic has that severity
// (then all show, and the label does not claim a filter).
function effective(items: readonly Diagnostic[], filter: DiagnosticFilter): DiagnosticFilter {
  return filter === "all" || severityCounts(items)[filter] ? filter : "all";
}

export interface DiagnosticsProps {
  items: readonly Diagnostic[];
  tree: readonly TreeBlock[];
  /** An element clicked, by id: the diagnostic's line names it. */
  onSelect: (id: string) => void;
  filter?: DiagnosticFilter | undefined;
  onFilter?: ((filter: DiagnosticFilter) => void) | undefined;
  /** The codes a `lint: {allow}` accepts (the vocabulary's); without them nothing offers "accept here…". */
  lintCodes?: readonly string[] | undefined;
  /** The element's `lint:` as written, or null: read when "accept here…" opens. */
  lintOf?: ((element: Path) => Promise<Value | null>) | undefined;
  /** Accept `code` on the element with `reason`, over its `lint:` as written. */
  onAccept?: ((element: Path, code: string, reason: string, written: Value | null) => void) | undefined;
}

/** "accept here…" open on one row: which, the element's `lint:` as written once read, and the reason typed. */
interface Accepting {
  key: string;
  element: TreeNode;
  code: string;
  written: Value | null;
  /** The element's `lint:` has been read: until then nothing is written, so a block it has is never written over. */
  read: boolean;
  reason: string;
}

/** A diagnostic row's identity while the list is shown: its place, and what it says (two rows may say the same). */
const keyOf = (d: Diagnostic, i: number): string => `${i}\0${d.code}\0${d.line ?? ""}\0${d.message}`;

// The compiler's diagnostics, most severe first; with more than one
// severity present, chips filter them to one. The editor holds the filter
// (`filter`, `onFilter`), so it outlasts a visit to another tab and the
// tab's label can show it; without them the list keeps its own.
export function Diagnostics({ items, tree, onSelect, filter, onFilter, lintCodes = [], lintOf, onAccept }: DiagnosticsProps): VNode {
  const [own, setOwn] = useState<DiagnosticFilter>("all");
  const [accepting, setAccepting] = useState<Accepting | null>(null);
  const setFilter = onFilter || setOwn;
  if (!items.length) return html`<div class="body dim">No diagnostics.</div>`;
  const counts = severityCounts(items);
  const present = SEVERITIES.filter((s) => counts[s]);
  const which = effective(items, filter ?? own);
  const names = NAMES;
  return html`${present.length > 1 ? html`<div class="diag-filter" role="group" aria-label="Show">
      <button class=${which === "all" ? "on" : ""} aria-pressed=${which === "all"} onClick=${() => setFilter("all")}>all ${items.length}</button>
      ${present.map((s) => html`<button class=${(which === s ? "on " : "") + s} aria-pressed=${which === s}
                                        onClick=${() => setFilter(s)}>${names[s]} ${counts[s]}</button>`)}
    </div>` : null}
    <ul class="diags">
    ${shownDiagnostics(items, which).map((d, i) => {
      const el = d.line ? elementAtLine(tree, d.line) : null;
      // a warning an element's own lint: block may accept
      const acceptable = onAccept && el && d.severity === "warning" && lintCodes.includes(d.code);
      const open = accepting && accepting.key === keyOf(d, i) ? accepting : null;
      const start = (e: JSX.TargetedMouseEvent<HTMLButtonElement>): void => {
        e.stopPropagation();
        if (!el) return;
        const key = keyOf(d, i);
        setAccepting({ key, element: el, code: d.code, written: null, read: !lintOf, reason: "" });
        // the reason the element's lint: has already is offered to keep
        if (lintOf) {
          void lintOf(el.path).then((written) => setAccepting((a) => (a && a.key === key
            ? { ...a, written, read: true, reason: a.reason || (written && typeof written === "object" && !Array.isArray(written) && typeof written["reason"] === "string" ? written["reason"] : "") }
            : a)), () => {});
        }
      };
      const accept = (): void => {
        if (!open || !open.read || !open.reason.trim() || !onAccept) return;
        onAccept(open.element.path, open.code, open.reason.trim(), open.written);
        setAccepting(null);
      };
      return html`
      <li onClick=${() => { if (el) onSelect(el.id); }}>
        <span class=${"sev " + d.severity}>${d.severity}</span>${d.message}
        ${d.line ? html`<div class="where">${d.file}:${d.line}:${d.col} · ${d.code}</div>` : null}
        ${d.notes.length ? html`<div class="notes">${d.notes.join("\n")}</div>` : null}
        ${acceptable && !open ? html`<button class="accept" title=${`write lint: {allow: [${d.code}], reason: ...} on ${el.id}: the warning is accepted there`}
            onClick=${start}>accept here…</button>` : null}
        ${open ? html`<div class="accept-form" onClick=${(e: JSX.TargetedMouseEvent<HTMLDivElement>) => e.stopPropagation()}>
          <span class="dim">accept <code>${open.code}</code> on <code>${open.element.id}</code> because</span>
          <input type="text" class="reason" aria-label="reason" placeholder="why it is right here" value=${open.reason}
            onInput=${(e: JSX.TargetedEvent<HTMLInputElement>) => { const reason = e.currentTarget.value; setAccepting((a) => (a ? { ...a, reason } : a)); }}
            onKeyDown=${(e: JSX.TargetedKeyboardEvent<HTMLInputElement>) => {
              if (e.key === "Enter") accept();
              if (e.key === "Escape") { e.stopPropagation(); setAccepting(null); }
            }} />
          <button class="primary" disabled=${!open.read || !open.reason.trim()} title="a lint: block needs its reason" onClick=${accept}>Accept</button>
          <button class="reset" title="keep the warning" aria-label="keep the warning" onClick=${() => setAccepting(null)}>×</button>
        </div>` : null}
      </li>`;
    })}
  </ul>`;
}

// The Diagnostics tab's label: its count per severity present, and the
// filter when one is in effect.
export function diagnosticsLabel(items: readonly Diagnostic[], filter: DiagnosticFilter = "all"): VNode {
  const counts = severityCounts(items);
  const marks: [Severity, string][] = [["error", "✕"], ["warning", "⚠"], ["note", "ℹ"]];
  const parts = marks.filter(([s]) => counts[s]).map(([s, mark]) => html`<span class=${"count " + s}>${mark} ${counts[s]}</span>`);
  const which = effective(items, filter);
  return html`Diagnostics${parts.length ? html` ${parts}` : null}${which !== "all"
    ? html`<span class="filtered"> · ${NAMES[which]} only</span>` : null}`;
}
