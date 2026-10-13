// Picking what is under the pointer: pure functions, no DOM, so Node can
// check them (test/page-modules.test.ts).

import type { FrameItem, Handle, TreeBlock, TreeNode } from "../src/studio/protocol.ts";

/** A box in device pixels: `[x, y, width, height]`. */
export type Box = [number, number, number, number];

/**
 * A placed element as the canvas handles it: a frame's item, or the
 * selection as one (`together`). An item without a box (nothing placed) is
 * skipped wherever a box is needed.
 */
export interface Placed {
  id: string;
  kind?: string;
  box: Box | null;
  center: [number, number];
  handles?: readonly Handle[];
}

// The element a layer belongs to: an outlined group's ring layer is
// `ring:<group id>` and selects the group.
export function elementOf(layerId: string): string {
  return layerId.startsWith("ring:") ? layerId.slice(5) : layerId;
}

// The topmost layer with ink under device pixel (x, y). `layers` are in
// draw order (bottom first), each `{id, box: [x, y, w, h] | null}`;
// `alphaAt(layer, x, y)` reads that layer's coverage there (0..255). A
// layer whose box misses the point is skipped without reading its pixels.
export function topmost<L extends { box: Box | null }>(layers: readonly L[], x: number, y: number, alphaAt: (layer: L, x: number, y: number) => number): L | null {
  for (let i = layers.length - 1; i >= 0; i--) {
    const layer = layers[i]!;
    const box = layer.box;
    if (box && (x < box[0] || y < box[1] || x >= box[0] + box[2] || y >= box[1] + box[3])) {
      continue;
    }
    if (alphaAt(layer, x, y) > 0) return layer;
  }
  return null;
}

// The element whose own lines hold `line`: the deepest tree element
// starting at or before it, whose next sibling (or its block's next
// entry) starts after it. A block not in the text yet (`line` null) holds
// no line and ends none.
export function elementAtLine(blocks: readonly TreeBlock[], line: number): TreeNode | null {
  let best: TreeNode | null = null;
  const walk = (all: readonly (TreeBlock | TreeNode)[], end: number): void => {
    const nodes = all.filter((n) => n.line != null);
    nodes.forEach((node, i) => {
      const start = node.line as number;    // the filter above kept only placed nodes
      const next = i + 1 < nodes.length ? (nodes[i + 1]!.line as number) : end;
      if (start <= line && line < next) {
        if (node.kind === "element") best = node;
        walk(node.children, next);
      }
    });
  };
  walk(blocks, Infinity);
  return best;
}

// Every element of the tree, depth first, in draw order.
export function flatten(blocks: readonly TreeBlock[]): TreeNode[] {
  const out: TreeNode[] = [];
  const walk = (nodes: readonly (TreeBlock | TreeNode)[]): void => nodes.forEach((n) => {
    if (n.kind === "element") out.push(n);
    walk(n.children);
  });
  walk(blocks);
  return out;
}

// The elements a drag of `ids` moves: each of them, and everything inside a
// group among them, since a group carries its children.
export function movedBy(blocks: readonly TreeBlock[], ids: readonly string[]): Set<string> {
  const out = new Set(ids);
  const walk = (nodes: readonly (TreeBlock | TreeNode)[], inside: boolean): void => nodes.forEach((n) => {
    const moved = inside || (n.kind === "element" && out.has(n.id));
    if (moved && n.kind === "element") out.add(n.id);
    walk(n.children, moved);
  });
  walk(blocks, false);
  return out;
}

// The selected items as one, for snapping a drag of several: the box round
// them all and its centre.
export function together(items: readonly Placed[], ids: readonly string[]): (Placed & { box: Box; handles: Handle[] }) | null {
  const boxes = items.filter((i) => ids.includes(i.id) && i.box).map((i) => i.box as Box);
  if (!boxes.length) return null;
  const x0 = Math.min(...boxes.map((b) => b[0])), y0 = Math.min(...boxes.map((b) => b[1]));
  const x1 = Math.max(...boxes.map((b) => b[0] + b[2])), y1 = Math.max(...boxes.map((b) => b[1] + b[3]));
  return { id: ids[0]!, box: [x0, y0, x1 - x0, y1 - y0], center: [(x0 + x1) / 2, (y0 + y1) / 2], handles: [] };
}

// Where the move handle sits, or null: on the top edge of the selection,
// at its middle, when it is a group (which draws nothing of its own to press
// on) or several elements. `inset`: how far down from the screen's top it
// must sit to be wholly on the screen, for a selection reaching the top.
// A press there drags them all.
export function moveHandle(items: readonly Placed[], ids: readonly string[], inset = 0): { x: number; y: number } | null {
  const chosen = items.filter((i) => ids.includes(i.id) && i.box);
  if (!chosen.length || (chosen.length === 1 && chosen[0]!.kind !== "group")) return null;
  const t = together(items, ids);
  if (t === null) return null;
  return { x: t.center[0], y: Math.max(t.box[1], inset) };
}

// `ids` without any whose group is among them too: a group carries its
// children, so selecting both would name a child twice.
export function outermost(blocks: readonly TreeBlock[], ids: readonly string[]): string[] {
  const want = new Set(ids);
  const out: string[] = [];
  const walk = (nodes: readonly (TreeBlock | TreeNode)[], inside: boolean): void => nodes.forEach((n) => {
    const chosen = n.kind === "element" && want.has(n.id);
    if (n.kind === "element" && chosen && !inside) out.push(n.id);
    walk(n.children, inside || chosen);
  });
  walk(blocks, false);
  return out;
}

// Select All: every element the frame shows (`shown`, a Set of ids: its
// drawn elements and authored groups), a group standing for its children.
export function selectAll(blocks: readonly TreeBlock[], shown: ReadonlySet<string>): string[] {
  const out: string[] = [];
  const walk = (nodes: readonly (TreeBlock | TreeNode)[]): void => nodes.forEach((n) => {
    if (n.kind === "element" && shown.has(n.id)) out.push(n.id);
    else walk(n.children);
  });
  walk(blocks);
  return out;
}

// A Shift-click's range in the layers: every element from `from` to `to`
// in the tree's order, both included, a group standing for its children.
// With `from` not in the tree, just `to`.
export function rangeIds(blocks: readonly TreeBlock[], from: string, to: string): string[] {
  const order = flatten(blocks).map((n) => n.id);
  const a = order.indexOf(from), b = order.indexOf(to);
  if (b < 0) return [];
  if (a < 0) return [to];
  return outermost(blocks, order.slice(Math.min(a, b), Math.max(a, b) + 1));
}

// The handle a press at device pixel (x, y) takes on `item`, the selected
// element, or null when the press moves it instead. A handle takes a press
// within `zone` screen pixels of it (`zoom` screen pixels per device
// pixel). A size handle's zone covers the whole body of an element thinner
// than two zones along the handle's axis (a 4-px bar), where a press
// inside the element's box would otherwise never move it: there the press
// is a move, and the handle takes only a press outside the box. A line's
// ends and an arc's angle handles sit at the element's ends and always
// take a press near them.
export function handleAt(item: Pick<FrameItem, "handles"> & { box: Box | null }, x: number, y: number, zoom: number, zone: number): Handle | null {
  const near = (h: Handle): boolean => Math.abs((h.x - x) * zoom) <= zone && Math.abs((h.y - y) * zoom) <= zone;
  const [bx, by, bw, bh] = item.box || [0, 0, 0, 0];
  const inside = x >= bx && y >= by && x < bx + bw && y < by + bh;
  const covered = (h: Handle): boolean => h.kind === "size" && inside && (h.axis === "y" ? bh : bw) * zoom < 2 * zone;
  return item.handles.find((h) => near(h) && !covered(h)) || null;
}
