// The Layers panel: the face's element tree, its structure edited in place.
// Each block and group is listed in draw order, as the YAML lists it: the
// top row is drawn first, under the rows below it. A `hands` element lists
// its set's hands and their parts beneath it, a pattern or a needle gauge
// its parts: a part row selects the part (by its tree path, under the
// element it sits in), and the element's ↘ (or a double-click) enters it,
// so the face shows its parts in their own frame; Exit, at the top, leaves.
// Click selects, Ctrl/Cmd-click adds to the selection or takes a row out
// of it, Shift-click selects every row from the selection to it; a row dragged
// onto another goes behind it (its top half) or in front of it, onto a
// group's middle into the group, onto a block's label to the block's front;
// a part row dragged onto a sibling part reorders the parts.
// Every change is one structural edit (or, for the parts, one `move_key`)
// the worker patches into the text, checks and records.
//
// The search box above the tree narrows it to the rows whose id or type
// holds what is typed, each with the rows it sits under; Escape or × clears
// it, and the selection stays as it was. A row shows its element's `z:`,
// when written, as a badge: it orders drawing before the rows' own order.

import type { JSX, VNode } from "preact";
import { html } from "htm/preact";
import { useState } from "preact/hooks";
import type { EditOp, Path, StructureOp, Summary, TreeBlock, TreeNode, Vocabulary } from "../src/studio/protocol.ts";
import { anyDrawn, PATH_TYPE, blocksOf, carriesPath, deleteOp, droppedPath, dropTarget, hasParts, isPartPath, matchingRows, partDrop, selectionId, siblingsOf, stepOp } from "./tree.ts";
import type { DropTarget } from "./tree.ts";

/** How a click changes the selection: `"range"` (Shift) every row from the selection to it, true (Ctrl/Cmd) toggles it, false selects it alone. */
export type SelectMode = "range" | boolean;

/** What an element type needs chosen before it is added: the word asked for, and the list offering it. */
type Need = [word: string, from: "series" | "slots" | "hand_sets"];
const NEEDS: Partial<Record<string, Need>> = { graph: ["series", "series"], data: ["slot", "slots"], hands: ["set", "hand_sets"] };

/** What every row and block shares: the selection, the entered element, what the frame draws, and where a click or a drop goes. */
interface Ctx {
  selected: string | null;
  extra: readonly string[];
  drawn: ReadonlySet<string> | null | undefined;
  entered: string | null;
  /** The rows a search leaves (`selectionId`s), or null for every row. */
  shown: ReadonlySet<string> | null;
  /** `owner`: the element a hand or part row sits under. */
  onSelect: (id: string, mode: SelectMode, owner?: Path) => void;
  onDrop: (path: Path, target: DropTarget["target"] | null) => void;
  /** A part row dropped on the sibling part `onto`, at `fraction` of its height. */
  onPartDrop: (path: Path, onto: TreeNode, fraction: number, siblings: readonly TreeNode[]) => void;
  onEnter: (path: Path) => void;
}

// A drop on the tree: a layer row's moves it; anything else (text, a
// file) is ignored.
function dropped(e: JSX.TargetedDragEvent<HTMLElement>, ctx: Ctx, target: DropTarget["target"] | null): void {
  const path = droppedPath(e.dataTransfer ? e.dataTransfer.getData(PATH_TYPE) : "");
  // a part stays in its own mapping: dropped on a block, it goes nowhere
  if (path && !isPartPath(path)) ctx.onDrop(path, target);
}

interface RowProps {
  node: TreeNode;
  /** The sibling drawn after it (the row below), or null at the block's end. */
  next: string | null;
  /** The siblings beside it, itself included, in order: the parts a part row is reordered among. */
  siblings: readonly TreeNode[];
  ctx: Ctx;
  depth: number;
  /** The element this row sits under, for a hand's or a part's row; null for an element's own. */
  owner: Path | null;
}

/** The fraction of the row's height a drag event is at (0 its top, 1 its bottom). */
const fractionOf = (e: JSX.TargetedDragEvent<HTMLDivElement>): number => {
  const r = e.currentTarget.getBoundingClientRect();
  return r.height ? (e.clientY - r.top) / r.height : 0.5;
};

// An element's row: selected by its id, dragged as its path, entered by ↘
// or a double-click when it has parts.
function Row({ node, next, ctx, depth }: RowProps): VNode {
  const [over, setOver] = useState<DropTarget["where"] | null>(null);
  const selected = ctx.selected === node.id || ctx.extra.includes(node.id);
  const drawn = ctx.drawn;
  const entered = ctx.entered === node.path.join("/");
  const enterable = hasParts(node);
  const zone = (e: JSX.TargetedDragEvent<HTMLDivElement>): DropTarget => dropTarget(node, fractionOf(e), next);
  // a part's row dropped on an element goes nowhere: parts stay in their mapping
  const accepts = (e: JSX.TargetedDragEvent<HTMLDivElement>): boolean => carriesPath(e.dataTransfer?.types);
  return html`<li>
    <div class=${"item" + (selected ? " selected" : "") + (over ? ` drop-${over}` : "") + (entered ? " entered" : "") +
                 (drawn && !anyDrawn(node, drawn) ? " undrawn" : "")}
         draggable="true" title=${`line ${node.line}`}
         onClick=${(e: JSX.TargetedMouseEvent<HTMLDivElement>) => ctx.onSelect(node.id, e.shiftKey ? "range" : e.ctrlKey || e.metaKey)}
         onDblClick=${() => { if (enterable) ctx.onEnter(node.path); }}
         onDragStart=${(e: JSX.TargetedDragEvent<HTMLDivElement>) => {
           if (!e.dataTransfer) return;
           e.dataTransfer.setData(PATH_TYPE, JSON.stringify(node.path)); e.dataTransfer.effectAllowed = "move";
         }}
         onDragOver=${(e: JSX.TargetedDragEvent<HTMLDivElement>) => { e.preventDefault(); if (accepts(e)) setOver(zone(e).where); }}
         onDragLeave=${() => setOver(null)}
         onDrop=${(e: JSX.TargetedDragEvent<HTMLDivElement>) => { e.preventDefault(); setOver(null); dropped(e, ctx, zone(e).target); }}>
      <span>${node.id}</span><span class="type">${node.type}</span>
      ${node.z !== undefined ? html`<span class="z-badge" title=${`z: ${String(node.z)}: drawn by this number among its siblings before their order here`}>z ${String(node.z)}</span>` : null}
      ${enterable ? html`<button class="enter" title=${entered ? "the parts of this element are on the face" : "Enter: edit its parts on the face (or double-click the row)"}
          disabled=${entered} onClick=${(e: JSX.TargetedMouseEvent<HTMLButtonElement>) => { e.stopPropagation(); ctx.onEnter(node.path); }}>↘</button>` : null}
    </div>
    ${node.children.length ? html`<ul class="tree">${inDrawOrder(node.children, ctx, depth + 1, enterable ? node.path : null)}</ul>` : null}
  </li>`;
}

// A hand's or a part's row under its element: selected by its tree path
// (`selectionId`), its type shown as the kind; a part row of an id-keyed
// mapping is dragged onto a sibling part to reorder them.
function PartRow({ node, ctx, depth, owner, siblings }: RowProps): VNode {
  const [over, setOver] = useState<DropTarget["where"] | null>(null);
  const id = selectionId(node);
  const selected = ctx.selected === id;
  const movable = node.kind === "part" && isPartPath(node.path);
  const accepts = (e: JSX.TargetedDragEvent<HTMLDivElement>): boolean => movable && carriesPath(e.dataTransfer?.types);
  return html`<li>
    <div class=${`item ${node.kind}` + (selected ? " selected" : "") + (over ? ` drop-${over}` : "")}
         draggable=${movable ? "true" : "false"} title=${`line ${node.line}`} data-path=${id}
         onClick=${() => ctx.onSelect(id, false, owner ?? undefined)}
         onDragStart=${(e: JSX.TargetedDragEvent<HTMLDivElement>) => {
           if (!e.dataTransfer || !movable) { e.preventDefault(); return; }
           e.dataTransfer.setData(PATH_TYPE, JSON.stringify(node.path)); e.dataTransfer.effectAllowed = "move";
         }}
         onDragOver=${(e: JSX.TargetedDragEvent<HTMLDivElement>) => { e.preventDefault(); if (accepts(e)) setOver(fractionOf(e) < 0.5 ? "before" : "after"); }}
         onDragLeave=${() => setOver(null)}
         onDrop=${(e: JSX.TargetedDragEvent<HTMLDivElement>) => {
           e.preventDefault(); setOver(null);
           const path = droppedPath(e.dataTransfer ? e.dataTransfer.getData(PATH_TYPE) : "");
           if (path && movable) ctx.onPartDrop(path, node, fractionOf(e), siblings);
         }}>
      <span>${node.id}</span><span class="type">${node.type}</span>
    </div>
    ${node.children.length ? html`<ul class="tree">${inDrawOrder(node.children, ctx, depth + 1, owner)}</ul>` : null}
  </li>`;
}

// `children` as rows in draw order: each told the sibling drawn after it,
// the row below it; a hand or a part under `owner`, the element they sit in.
// A search shows only the rows it leaves, but a drop still lands by the
// real siblings.
function inDrawOrder(children: readonly TreeNode[], ctx: Ctx, depth: number, owner: Path | null = null): VNode[] {
  return children.flatMap((c, i) => (ctx.shown && !ctx.shown.has(selectionId(c)) ? []
    : [html`<${c.kind === "element" ? Row : PartRow} key=${selectionId(c)} node=${c} next=${children[i + 1]?.id ?? null}
                                             siblings=${children} ctx=${ctx} depth=${depth} owner=${owner} />`]));
}

interface BlockProps {
  block: TreeBlock;
  ctx: Ctx;
}

function Block({ block, ctx }: BlockProps): VNode | null {
  const [over, setOver] = useState(false);
  // a search hides a block none of whose rows it leaves
  if (ctx.shown && !block.children.some((c) => ctx.shown!.has(selectionId(c)))) return null;
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
  /** The selected element's id, or a hand's or part's tree path joined with "/". */
  selected: string | null;
  /** More elements selected with Ctrl/Cmd or Shift. */
  extra: readonly string[];
  /** The ids the frame draws, or null without a frame. */
  drawn: ReadonlySet<string> | null | undefined;
  /** The entered element's tree path, whose parts the face shows, or null. */
  entered?: Path | null | undefined;
  /** `owner`: the element a hand's or part's row sits under. */
  onSelect: (id: string, mode: SelectMode, owner?: Path) => void;
  onStructure: (op: StructureOp) => void;
  /** A part row dropped on a sibling: one `move_key`. */
  onEdit?: ((op: EditOp) => unknown) | undefined;
  onEnter?: ((path: Path) => void) | undefined;
  onExit?: (() => void) | undefined;
}

export function Layers({ doc, vocab, selected, extra, drawn, entered = null, onSelect, onStructure, onEdit, onEnter, onExit }: LayersProps): VNode {
  const [type, setType] = useState("");
  const [choice, setChoice] = useState("");
  const [query, setQuery] = useState("");
  const shown = matchingRows(doc.tree, query);
  const blocks = blocksOf(doc.tree);
  const selectedNode = selected ? blocks.nodes.find((n) => n.id === selected) : undefined;
  const enteredNode = entered ? blocks.nodes.find((n) => n.path.join("/") === entered.join("/")) : undefined;
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
    selected, extra, drawn, onSelect, entered: entered ? entered.join("/") : null, shown,
    onDrop: (path, target) => {
      if (!target || JSON.stringify(path) === JSON.stringify([...target.block, target.before])) return;
      onStructure({ op: "move", path, block: target.block, before: target.before });
    },
    onPartDrop: (path, onto, fraction, siblings) => {
      const op = partDrop(path, onto.path, fraction, siblings.map((n) => n.path));
      if (op && onEdit) onEdit(op);
    },
    onEnter: (path) => { if (onEnter) onEnter(path); },
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
    ${enteredNode ? html`<div class="entered-bar">
      <button class="exit" title="Leave the parts and edit the face again (Esc)" onClick=${() => { if (onExit) onExit(); }}>↖ Exit</button>
      <span class="dim">the parts of <code>${enteredNode.id}</code> are on the face</span>
    </div>` : null}
    <div class="layer-search">
      <input type="search" class="search" placeholder="search ids and types" aria-label="search the layers" value=${query}
        onInput=${(e: JSX.TargetedEvent<HTMLInputElement>) => setQuery(e.currentTarget.value)}
        onKeyDown=${(e: JSX.TargetedKeyboardEvent<HTMLInputElement>) => { if (e.key === "Escape" && query) { e.stopPropagation(); setQuery(""); } }} />
      ${query ? html`<button class="reset" title="clear the search" aria-label="clear the search" onClick=${() => setQuery("")}>×</button>` : null}
    </div>
    <div class="order-note dim" title="Each block draws its rows top to bottom">front at the bottom</div>
    ${shown && shown.size === 0 ? html`<div class="dim note">no element's id or type holds “${query.trim()}”</div>` : null}
    <ul class="tree root">${doc.tree.map((b) => html`<${Block} block=${b} ctx=${ctx} />`)}</ul>
  </div>`;
}
