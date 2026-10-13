// The Layers panel: the face's element tree, its structure edited in place.
// Each block and group is listed in draw order, as the YAML lists it: the
// top row is drawn first, under the rows below it.
// Click selects, Ctrl/Cmd-click adds to the selection or takes a row out
// of it, Shift-click selects every row from the selection to it; a row dragged
// onto another goes behind it (its top half) or in front of it, onto a
// group's middle into the group, onto a block's label to the block's front.
// Every change is one structural edit the worker patches into the text,
// checks and records.

import type { JSX, VNode } from "preact";
import { html } from "htm/preact";
import { useState } from "preact/hooks";
import type { Path, StructureOp, Summary, TreeBlock, TreeNode, Vocabulary } from "../src/studio/protocol.ts";
import { anyDrawn, PATH_TYPE, blocksOf, carriesPath, deleteOp, droppedPath, dropTarget, siblingsOf, stepOp } from "./tree.ts";
import type { DropTarget } from "./tree.ts";

/** How a click changes the selection: `"range"` (Shift) every row from the selection to it, true (Ctrl/Cmd) toggles it, false selects it alone. */
export type SelectMode = "range" | boolean;

/** What an element type needs chosen before it is added: the word asked for, and the list offering it. */
type Need = [word: string, from: "series" | "slots" | "hand_sets"];
const NEEDS: Partial<Record<string, Need>> = { graph: ["series", "series"], data: ["slot", "slots"], hands: ["set", "hand_sets"] };

/** What every row and block shares: the selection, what the frame draws, and where a click or a drop goes. */
interface Ctx {
  selected: string | null;
  extra: readonly string[];
  drawn: ReadonlySet<string> | null | undefined;
  onSelect: (id: string, mode: SelectMode) => void;
  onDrop: (path: Path, target: DropTarget["target"] | null) => void;
}

// A drop on the tree: a layer row's moves it; anything else (text, a
// file) is ignored.
function dropped(e: JSX.TargetedDragEvent<HTMLElement>, ctx: Ctx, target: DropTarget["target"] | null): void {
  const path = droppedPath(e.dataTransfer ? e.dataTransfer.getData(PATH_TYPE) : "");
  if (path) ctx.onDrop(path, target);
}

interface RowProps {
  node: TreeNode;
  /** The sibling drawn after it (the row below), or null at the block's end. */
  next: string | null;
  ctx: Ctx;
  depth: number;
}

function Row({ node, next, ctx, depth }: RowProps): VNode {
  const [over, setOver] = useState<DropTarget["where"] | null>(null);
  const selected = ctx.selected === node.id || ctx.extra.includes(node.id);
  const drawn = ctx.drawn;
  const zone = (e: JSX.TargetedDragEvent<HTMLDivElement>): DropTarget => {
    const r = e.currentTarget.getBoundingClientRect();
    return dropTarget(node, r.height ? (e.clientY - r.top) / r.height : 0.5, next);
  };
  return html`<li>
    <div class=${"item" + (selected ? " selected" : "") + (over ? ` drop-${over}` : "") +
                 (drawn && !anyDrawn(node, drawn) ? " undrawn" : "")}
         draggable="true" title=${`line ${node.line}`}
         onClick=${(e: JSX.TargetedMouseEvent<HTMLDivElement>) => ctx.onSelect(node.id, e.shiftKey ? "range" : e.ctrlKey || e.metaKey)}
         onDragStart=${(e: JSX.TargetedDragEvent<HTMLDivElement>) => {
           if (!e.dataTransfer) return;
           e.dataTransfer.setData(PATH_TYPE, JSON.stringify(node.path)); e.dataTransfer.effectAllowed = "move";
         }}
         onDragOver=${(e: JSX.TargetedDragEvent<HTMLDivElement>) => { e.preventDefault(); if (carriesPath(e.dataTransfer?.types)) setOver(zone(e).where); }}
         onDragLeave=${() => setOver(null)}
         onDrop=${(e: JSX.TargetedDragEvent<HTMLDivElement>) => { e.preventDefault(); setOver(null); dropped(e, ctx, zone(e).target); }}>
      <span>${node.id}</span><span class="type">${node.type}</span>
    </div>
    ${node.children.length ? html`<ul class="tree">${inDrawOrder(node.children, ctx, depth + 1)}</ul>` : null}
  </li>`;
}

// `children` as rows in draw order: each told the sibling drawn after it,
// the row below it.
function inDrawOrder(children: readonly TreeNode[], ctx: Ctx, depth: number): VNode[] {
  return children.map((c, i) => html`<${Row} key=${c.id} node=${c} next=${children[i + 1]?.id ?? null}
                                             ctx=${ctx} depth=${depth} />`);
}

interface BlockProps {
  block: TreeBlock;
  ctx: Ctx;
}

function Block({ block, ctx }: BlockProps): VNode {
  const [over, setOver] = useState(false);
  return html`<li>
    <div class=${"block" + (over ? " drop-into" : "")}
         onDragOver=${(e: JSX.TargetedDragEvent<HTMLDivElement>) => { e.preventDefault(); if (carriesPath(e.dataTransfer?.types)) setOver(true); }}
         onDragLeave=${() => setOver(false)}
         title="drop here to put an element in front of everything in this block"
         onDrop=${(e: JSX.TargetedDragEvent<HTMLDivElement>) => { e.preventDefault(); setOver(false); dropped(e, ctx, { block: block.path, before: null }); }}>
      ${block.label}</div>
    ${block.children.length ? html`<ul class="tree">${inDrawOrder(block.children, ctx, 1)}</ul>`
      : html`<div class="empty-block">empty: drop here</div>`}
  </li>`;
}

export interface LayersProps {
  doc: Summary;
  vocab: Partial<Vocabulary>;
  selected: string | null;
  /** More elements selected with Ctrl/Cmd or Shift. */
  extra: readonly string[];
  /** The ids the frame draws, or null without a frame. */
  drawn: ReadonlySet<string> | null | undefined;
  onSelect: (id: string, mode: SelectMode) => void;
  onStructure: (op: StructureOp) => void;
}

export function Layers({ doc, vocab, selected, extra, drawn, onSelect, onStructure }: LayersProps): VNode {
  const [type, setType] = useState("");
  const [choice, setChoice] = useState("");
  const blocks = blocksOf(doc.tree);
  const selectedNode = selected ? blocks.nodes.find((n) => n.id === selected) : undefined;
  const needs = NEEDS[type];
  const globals = doc.globals;
  const options: string[] = !needs ? [] : needs[1] === "series" ? vocab.series || []
    : needs[1] === "slots" ? (globals.slots || []).map((s) => s.name) : globals.hand_sets || [];

  const add = (): void => {
    const block = selectedNode ? selectedNode.path.slice(0, -1) : ["elements"];
    const siblings = selectedNode ? siblingsOf(doc.tree, selectedNode.path) : [];
    const next = selectedNode ? siblings[siblings.indexOf(selectedNode.id) + 1] || null : null;
    onStructure({ op: "add", type, block, before: next, ...(needs ? { choice } : {}) });
    setType(""); setChoice("");
  };
  // +1 forward (down the list, drawn later), -1 backward
  const step = (by: number): void => {
    if (!selectedNode) return;
    const op = stepOp(doc.tree, selectedNode.path, by);
    if (op) onStructure(op);
  };
  const group = (): void => {
    const ids = [selected, ...extra];
    const paths = ids.map((id) => blocks.nodes.find((n) => n.id === id)).filter((n) => n !== undefined).map((n) => n.path);
    onStructure({ op: "group", paths });
  };
  const remove = (): void => {
    const op = deleteOp(doc.tree, [selected, ...extra].filter((id) => id !== null));
    if (op) onStructure(op);
  };
  const ctx: Ctx = {
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
      <select value=${type} onChange=${(e: JSX.TargetedEvent<HTMLSelectElement>) => { setType(e.currentTarget.value); setChoice(""); }} title="Add an element after the selection, or at the end of elements:">
        <option value="">+ add…</option>
        ${(vocab.types || []).map((t) => html`<option value=${t}>${t}</option>`)}
      </select>
      ${needs ? html`<select value=${choice} onChange=${(e: JSX.TargetedEvent<HTMLSelectElement>) => setChoice(e.currentTarget.value)}>
        <option value="">${needs[0]}…</option>
        ${options.map((o) => html`<option value=${o}>${o}</option>`)}
      </select>` : null}
      ${type ? html`<button class="primary" disabled=${needs && !choice} onClick=${add}>Add</button>` : null}
      ${needs && !options.length ? html`<div class="note">${needs[1] === "slots" ? "Add a slot in the Face tab first." : needs[1] === "hand_sets" ? "Add a hand set in the Face tab first (or write one under resources: hand_sets:)." : ""}</div>` : null}
    </div>
    ${selectedNode ? html`<div class="actions">
      <button title="Send backward: drawn under the row above (Ctrl+[)" onClick=${() => step(-1)}>↑</button>
      <button title="Bring forward: drawn over the row below (Ctrl+])" onClick=${() => step(1)}>↓</button>
      <button title="Duplicate (Ctrl+D)" onClick=${() => onStructure({ op: "duplicate", path: selectedNode.path })}>Duplicate</button>
      <button class="danger" title="Delete the selection (Del)" onClick=${remove}>Delete${extra.length ? ` (${extra.length + 1})` : ""}</button>
      <button title="Group the selection (Ctrl+G; Ctrl/Cmd-click to select more)" onClick=${group}>Group${extra.length ? ` (${extra.length + 1})` : ""}</button>
      ${selectedNode.type === "group" ? html`<button title="Ungroup (Ctrl+Shift+G)" onClick=${() => onStructure({ op: "ungroup", path: selectedNode.path })}>Ungroup</button>` : null}
      <select value="" onChange=${(e: JSX.TargetedEvent<HTMLSelectElement>) => {
        // the option's value is a destination's path, as this panel wrote it below
        if (e.currentTarget.value) onStructure({ op: "move", path: selectedNode.path, block: JSON.parse(e.currentTarget.value) as Path, before: null });
      }}>
        <option value="">move to…</option>
        ${destinations.map((d) => html`<option value=${JSON.stringify(d.path)}>${d.label}</option>`)}
      </select>
    </div>` : null}
    <div class="order-note dim" title="Each block draws its rows top to bottom">front at the bottom</div>
    <ul class="tree root">${doc.tree.map((b) => html`<${Block} block=${b} ctx=${ctx} />`)}</ul>
  </div>`;
}
