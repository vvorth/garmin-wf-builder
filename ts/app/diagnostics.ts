// The Diagnostics tab: the compiler's diagnostics for the open face, and
// the tab's label.

import type { VNode } from "preact";
import { html } from "htm/preact";
import { useState } from "preact/hooks";
import type { Diagnostic, Severity, TreeBlock } from "../src/studio/protocol.ts";
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
}

// The compiler's diagnostics, most severe first; with more than one
// severity present, chips filter them to one. The editor holds the filter
// (`filter`, `onFilter`), so it outlasts a visit to another tab and the
// tab's label can show it; without them the list keeps its own.
export function Diagnostics({ items, tree, onSelect, filter, onFilter }: DiagnosticsProps): VNode {
  const [own, setOwn] = useState<DiagnosticFilter>("all");
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
    ${shownDiagnostics(items, which).map((d) => html`
      <li onClick=${() => { const el = d.line && elementAtLine(tree, d.line); if (el) onSelect(el.id); }}>
        <span class=${"sev " + d.severity}>${d.severity}</span>${d.message}
        ${d.line ? html`<div class="where">${d.file}:${d.line}:${d.col} · ${d.code}</div>` : null}
        ${d.notes.length ? html`<div class="notes">${d.notes.join("\n")}</div>` : null}
      </li>`)}
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
