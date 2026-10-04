// The Diagnostics tab: the compiler's diagnostics for the open face, and
// the tab's label.

import { html, useState } from "./vendor/preact-htm.module.js";
import { elementAtLine } from "./hit.js";
import { severityCounts, shownDiagnostics } from "./values.js";

// The compiler's diagnostics, most severe first; with more than one
// severity present, chips filter them to one.
export function Diagnostics({ items, tree, onSelect }) {
  const [filter, setFilter] = useState("all");
  if (!items.length) return html`<div class="body dim">No diagnostics.</div>`;
  const counts = severityCounts(items);
  const present = ["error", "warning", "note"].filter((s) => counts[s]);
  const which = filter === "all" || counts[filter] ? filter : "all";
  const names = { error: "errors", warning: "warnings", note: "notes" };
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

// The Diagnostics tab's label: its count per severity present.
export function diagnosticsLabel(items) {
  const counts = severityCounts(items);
  const parts = [["error", "✕"], ["warning", "⚠"], ["note", "ℹ"]]
    .filter(([s]) => counts[s]).map(([s, mark]) => html`<span class=${"count " + s}>${mark} ${counts[s]}</span>`);
  return html`Diagnostics${parts.length ? html` ${parts}` : null}`;
}
