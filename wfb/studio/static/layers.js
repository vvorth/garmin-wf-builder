// The Layers panel: the face's element tree, its structure edited in place.
// Click selects, Ctrl/Cmd/Shift-click adds to the selection; a row dragged
// onto another goes before it, onto a group's middle into the group, onto
// a block's label to the block's end. Every change is one structural edit
// the server patches into the text, checks and records.

import { html, useState } from "./vendor/preact-htm.module.js";
import { blocksOf, dropTarget, siblingsOf } from "./tree.js";

const NEEDS = { graph: ["series", "series"], data: ["slot", "slots"], hands: ["set", "hand_sets"] };

function Row({ node, next, ctx, depth }) {
  const [over, setOver] = useState(null);
  const selected = ctx.selected === node.id || ctx.extra.includes(node.id);
  const drawn = ctx.drawn;
  const zone = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    return dropTarget(node, r.height ? (e.clientY - r.top) / r.height : 0.5, next);
  };
  return html`<li>
    <div class=${"item" + (selected ? " selected" : "") + (over ? ` drop-${over}` : "") +
                 (drawn && node.type !== "group" && !drawn.has(node.id) ? " undrawn" : "")}
         draggable="true" title=${`line ${node.line}`}
         onClick=${(e) => ctx.onSelect(node.id, e.ctrlKey || e.metaKey || e.shiftKey)}
         onDragStart=${(e) => { e.dataTransfer.setData("text/plain", JSON.stringify(node.path)); e.dataTransfer.effectAllowed = "move"; }}
         onDragOver=${(e) => { e.preventDefault(); setOver(zone(e).where); }}
         onDragLeave=${() => setOver(null)}
         onDrop=${(e) => { e.preventDefault(); setOver(null); ctx.onDrop(JSON.parse(e.dataTransfer.getData("text/plain")), zone(e).target); }}>
      <span>${node.id}</span><span class="type">${node.type}</span>
    </div>
    ${node.children.length ? html`<ul class="tree">${node.children.map((c, i) => html`<${Row} node=${c} next=${(node.children[i + 1] || {}).id ?? null} ctx=${ctx} depth=${depth + 1} />`)}</ul>` : null}
  </li>`;
}

function Block({ block, ctx }) {
  const [over, setOver] = useState(false);
  return html`<li>
    <div class=${"block" + (over ? " drop-into" : "")}
         onDragOver=${(e) => { e.preventDefault(); setOver(true); }}
         onDragLeave=${() => setOver(false)}
         onDrop=${(e) => { e.preventDefault(); setOver(false); ctx.onDrop(JSON.parse(e.dataTransfer.getData("text/plain")), { block: block.path, before: null }); }}>
      ${block.label}</div>
    ${block.children.length ? html`<ul class="tree">${block.children.map((c, i) => html`<${Row} node=${c} next=${(block.children[i + 1] || {}).id ?? null} ctx=${ctx} depth=${1} />`)}</ul>`
      : html`<div class="empty-block">empty: drop here</div>`}
  </li>`;
}

export function Layers({ doc, vocab, selected, extra, drawn, onSelect, onStructure }) {
  const [type, setType] = useState("");
  const [choice, setChoice] = useState("");
  const blocks = blocksOf(doc.tree);
  const selectedNode = selected && blocks.nodes.find((n) => n.id === selected);
  const needs = NEEDS[type];
  const globals = doc.globals || {};
  const options = !needs ? [] : needs[1] === "series" ? vocab.series || []
    : needs[1] === "slots" ? (globals.slots || []).map((s) => s.name) : globals[needs[1]] || [];

  const add = () => {
    const block = selectedNode ? selectedNode.path.slice(0, -1) : ["elements"];
    const siblings = selectedNode ? siblingsOf(doc.tree, selectedNode.path) : [];
    const next = selectedNode ? siblings[siblings.indexOf(selectedNode.id) + 1] || null : null;
    onStructure({ op: "add", type, block, before: next, choice: needs ? choice : undefined });
    setType(""); setChoice("");
  };
  const step = (by) => {
    const siblings = siblingsOf(doc.tree, selectedNode.path);
    const at = siblings.indexOf(selectedNode.id);
    const to = at + by;
    if (to < 0 || to >= siblings.length) return;
    const rest = siblings.filter((s) => s !== selectedNode.id);
    onStructure({ op: "move", path: selectedNode.path, block: selectedNode.path.slice(0, -1), before: rest[to] ?? null });
  };
  const group = () => {
    const ids = [selected, ...extra];
    const paths = ids.map((id) => blocks.nodes.find((n) => n.id === id)).filter(Boolean).map((n) => n.path);
    onStructure({ op: "group", paths });
  };
  const ctx = {
    selected, extra, drawn, onSelect,
    onDrop: (path, target) => {
      if (!target || JSON.stringify(path) === JSON.stringify([...target.block, target.before])) return;
      onStructure({ op: "move", path, block: target.block, before: target.before });
    },
  };
  const destinations = blocks.destinations.filter((d) => selectedNode && JSON.stringify(d.path) !== JSON.stringify(selectedNode.path.slice(0, -1))
    && JSON.stringify(d.path.slice(0, selectedNode.path.length)) !== JSON.stringify(selectedNode.path));

  return html`<div class="layers">
    <div class="add-bar">
      <select value=${type} onChange=${(e) => { setType(e.target.value); setChoice(""); }} title="Add an element after the selection, or at the end of elements:">
        <option value="">+ add…</option>
        ${(vocab.types || []).map((t) => html`<option value=${t}>${t}</option>`)}
      </select>
      ${needs ? html`<select value=${choice} onChange=${(e) => setChoice(e.target.value)}>
        <option value="">${needs[0]}…</option>
        ${options.map((o) => html`<option value=${o}>${o}</option>`)}
      </select>` : null}
      ${type ? html`<button class="primary" disabled=${needs && !choice} onClick=${add}>Add</button>` : null}
      ${needs && !options.length ? html`<div class="note">${needs[1] === "slots" ? "Add a slot in the Face tab first." : needs[1] === "hand_sets" ? "Add a hand set in the Face tab first (or write one under resources: hand_sets:)." : ""}</div>` : null}
    </div>
    ${selectedNode ? html`<div class="actions">
      <button title="Move up" onClick=${() => step(-1)}>↑</button>
      <button title="Move down" onClick=${() => step(1)}>↓</button>
      <button title="Duplicate (Ctrl+D)" onClick=${() => onStructure({ op: "duplicate", path: selectedNode.path })}>Duplicate</button>
      <button class="danger" title="Delete (Del)" onClick=${() => onStructure({ op: "delete", path: selectedNode.path })}>Delete</button>
      <button title="Group the selection (Ctrl/Cmd-click to select more)" onClick=${group}>Group${extra.length ? ` (${extra.length + 1})` : ""}</button>
      ${selectedNode.type === "group" ? html`<button onClick=${() => onStructure({ op: "ungroup", path: selectedNode.path })}>Ungroup</button>` : null}
      <select value="" onChange=${(e) => { if (e.target.value) onStructure({ op: "move", path: selectedNode.path, block: JSON.parse(e.target.value), before: null }); }}>
        <option value="">move to…</option>
        ${destinations.map((d) => html`<option value=${JSON.stringify(d.path)}>${d.label}</option>`)}
      </select>
    </div>` : null}
    <ul class="tree root">${doc.tree.map((b) => html`<${Block} block=${b} ctx=${ctx} />`)}</ul>
  </div>`;
}
