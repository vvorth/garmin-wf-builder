// The Diagnostics tab: the compiler's diagnostics for the open face, and
// the tab's label.

import { html, useState } from "./vendor/preact-htm.module.js";
import { elementAtLine } from "./hit.js";
import { severityCounts, shownDiagnostics } from "./values.js";

const NAMES = { error: "errors", warning: "warnings", note: "notes" };

// The filter in effect: `filter`, unless no diagnostic has that severity
// (then all show, and the label does not claim a filter).
function effective(items, filter) {
  return filter === "all" || severityCounts(items)[filter] ? filter : "all";
}

// The compiler's diagnostics, most severe first; with more than one
// severity present, chips filter them to one. The editor holds the filter
// (`filter`, `onFilter`), so it outlasts a visit to another tab and the
// tab's label can show it; without them the list keeps its own.
export function Diagnostics({ items, tree, onSelect, filter, onFilter }) {
  const [own, setOwn] = useState("all");
  const setFilter = onFilter || setOwn;
  if (!items.length) return html`<div class="body dim">No diagnostics.</div>`;
  const counts = severityCounts(items);
  const present = ["error", "warning", "note"].filter((s) => counts[s]);
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
export function diagnosticsLabel(items, filter = "all") {
  const counts = severityCounts(items);
  const parts = [["error", "✕"], ["warning", "⚠"], ["note", "ℹ"]]
    .filter(([s]) => counts[s]).map(([s, mark]) => html`<span class=${"count " + s}>${mark} ${counts[s]}</span>`);
  const which = effective(items, filter);
  return html`Diagnostics${parts.length ? html` ${parts}` : null}${which !== "all"
    ? html`<span class="filtered"> · ${NAMES[which]} only</span>` : null}`;
}
