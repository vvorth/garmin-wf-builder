// The element tree's structure: pure functions, no DOM, so Node can check
// them (test/page-modules.test.ts).

import type { EditOp, Path, StructureOp, TreeBlock, TreeNode } from "../src/studio/protocol.ts";

/** A block an element can be moved to: its path and the label the picker shows. */
export interface Destination {
  path: Path;
  label: string;
}

/** Where a dropped row lands: the block, and the sibling it goes before (null: the block's end). */
export interface DropTarget {
  where: "before" | "after" | "into";
  target: { block: Path; before: string | null };
}

// Every element (flat, draw order) and every block an element can go to:
// each top-level and layout block, then each group's children. A hand or a
// part under an element is not an element: it is left out.
export function blocksOf(tree: readonly TreeBlock[]): { nodes: TreeNode[]; destinations: Destination[] } {
  const nodes: TreeNode[] = [], destinations: Destination[] = tree.map((b) => ({ path: b.path, label: b.label }));
  const walk = (list: readonly TreeNode[]): void => list.forEach((n) => {
    if (n.kind === "hand" || n.kind === "part") return;
    nodes.push(n);
    if (n.type === "group") destinations.push({ path: [...n.path, "children"], label: `${n.id} (group)` });
    walk(n.children);
  });
  tree.forEach((b) => walk(b.children));
  return { nodes, destinations };
}

// How the editor names a node in a selection: an element by its id, a hand
// or a part by its tree path joined with "/" (the entered frame's item id,
// and what a drag names it by), which no element id can be.
export const selectionId = (node: Pick<TreeNode, "kind" | "id" | "path">): string => (node.kind === "element" ? node.id : node.path.join("/"));

// The node a selection names (`selectionId`), of any kind, or null.
export function nodeById(tree: readonly TreeBlock[], id: string): TreeNode | null {
  let found: TreeNode | null = null;
  const walk = (list: readonly TreeNode[]): void => list.forEach((n) => {
    if (found) return;
    if (selectionId(n) === id) { found = n; return; }
    walk(n.children);
  });
  tree.forEach((b) => walk(b.children));
  return found;
}

// The node at `path`, of any kind, or null.
export function nodeAtPath(tree: readonly TreeBlock[], path: Path): TreeNode | null {
  const want = path.join("/");
  let found: TreeNode | null = null;
  const walk = (list: readonly TreeNode[]): void => list.forEach((n) => {
    if (found) return;
    if (n.path.join("/") === want) { found = n; return; }
    walk(n.children);
  });
  tree.forEach((b) => walk(b.children));
  return found;
}

// Whether `path` names a part written in an id-keyed `parts:` (or a
// needle's `needle:`) mapping: one a `move_key` can reorder.
export const isPartPath = (path: Path): boolean => path.length >= 3 && (path[path.length - 2] === "parts" || path[path.length - 2] === "needle") && typeof path[path.length - 1] === "string";

// Whether an element's node has hands or parts under it: one the editor can enter.
export const hasParts = (node: TreeNode): boolean => node.kind === "element" && node.children.some((c) => c.kind === "hand" || c.kind === "part");

// The edit that puts the part at `from` where a drop on the sibling part at
// `onto` lands it: before that sibling (`fraction` under half) or after it,
// among `siblings` (the parent's parts, in order). Null when the two are
// not parts of the same mapping, or nothing would move.
export function partDrop(from: Path, onto: Path, fraction: number, siblings: readonly Path[]): EditOp | null {
  if (!isPartPath(from) || !isPartPath(onto) || from.slice(0, -1).join("/") !== onto.slice(0, -1).join("/")) return null;
  const index = (p: Path): number => siblings.findIndex((s) => s.join("/") === p.join("/"));
  const i = index(from), j = index(onto);
  if (i < 0 || j < 0 || i === j) return null;
  let to = fraction < 0.5 ? j : j + 1;
  if (i < to) to--;
  if (to === i) return null;
  return { op: "move_key", element: from.slice(0, -2), path: from.slice(-2), to };
}

// Whether `node` shows anything in the frame `drawn` names: itself, when
// it is a leaf -- a group never draws itself, so it shows as drawn when
// any descendant does (recursively, for a group nested in a group).
export function anyDrawn(node: TreeNode, drawn: ReadonlySet<string>): boolean {
  if (node.type !== "group") return drawn.has(node.id);
  return node.children.some((c) => anyDrawn(c, drawn));
}

// The ids beside the element at `path`, itself included, in order.
export function siblingsOf(tree: readonly TreeBlock[], path: Path): string[] {
  const parent = JSON.stringify(path.slice(0, -1));
  const out: string[] = [];
  const walk = (list: readonly TreeNode[]): void => list.forEach((n) => {
    if (JSON.stringify(n.path.slice(0, -1)) === parent) out.push(n.id);
    walk(n.children);
  });
  tree.forEach((b) => walk(b.children));
  return out;
}

// Where a row dropped at `fraction` of its height (0 top, 1 bottom) sends
// the dragged element: before the row, after it (before its next sibling,
// `next`, or at the block's end), or, in a group's middle third, into the
// group.
export function dropTarget(node: TreeNode, fraction: number, next: string | null = null): DropTarget {
  const block = node.path.slice(0, -1);
  if (node.type === "group" && fraction > 1 / 3 && fraction < 2 / 3) {
    return { where: "into", target: { block: [...node.path, "children"], before: null } };
  }
  if (fraction < 0.5) return { where: "before", target: { block, before: node.id } };
  return { where: "after", target: { block, before: next } };
}

// What a dragged layer row carries: its author path, under a type of its
// own, so text or a file dragged in from elsewhere is never read as one.
export const PATH_TYPE = "application/x-wfb-path";

// Whether a drag (its `dataTransfer.types`) is a layer row's.
export function carriesPath(types: readonly string[] | null | undefined): boolean {
  return Array.from(types || []).includes(PATH_TYPE);
}

// The path a drop carries, or null when it is not a path.
export function droppedPath(raw: string): Path | null {
  let path: unknown;
  try { path = JSON.parse(raw); } catch (_) { return null; }
  const step = (s: unknown): s is string | number => typeof s === "string" || Number.isInteger(s);
  return Array.isArray(path) && path.length && path.every(step) ? path : null;
}

// The structural edit that deletes the elements `ids` name: one path, or
// all of them as one change.
export function deleteOp(tree: readonly TreeBlock[], ids: readonly string[]): StructureOp | null {
  const paths = blocksOf(tree).nodes.filter((n) => ids.includes(n.id)).map((n) => n.path);
  if (!paths.length) return null;
  return paths.length === 1 ? { op: "delete", path: paths[0]! } : { op: "delete", paths };
}

// The YAML of the elements `ids` name, as copied: each one's own lines
// out of `text` (`node.line` to `node.end`), in document order, a group
// standing for its children, every one moved to the first column.
export function elementsYaml(text: string, tree: readonly TreeBlock[], ids: readonly string[]): string {
  const lines = text.split("\n");
  const want = new Set(ids);
  const out: string[] = [];
  const walk = (nodes: readonly (TreeBlock | TreeNode)[], inside: boolean): void => nodes.forEach((n) => {
    const chosen = n.kind === "element" && want.has(n.id);
    if (n.kind === "element" && chosen && !inside) {
      const own = lines.slice(n.line - 1, n.end);
      const first = own[0] ?? "";
      const indent = first.length - first.trimStart().length;
      out.push(own.map((l) => l.slice(Math.min(indent, l.length - l.trimStart().length))).join("\n") + "\n");
    }
    walk(n.children, inside || chosen);
  });
  walk(tree, false);
  return out.join("");
}

// The structural edit that moves the element at `path` one step in draw
// order: `by` +1 forward (drawn later), -1 backward; null at the end.
export function stepOp(tree: readonly TreeBlock[], path: Path, by: number): StructureOp | null {
  const siblings = siblingsOf(tree, path);
  const id = path[path.length - 1];
  const to = siblings.indexOf(id as string) + by;
  if (to < 0 || to >= siblings.length) return null;
  const rest = siblings.filter((s) => s !== id);
  return { op: "move", path, block: path.slice(0, -1), before: rest[to] ?? null };
}
