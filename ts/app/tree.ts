// The element tree's structure: pure functions, no DOM, so Node can check
// them (test/page-modules.test.ts).

import type { Path, StructureOp, TreeBlock, TreeNode } from "../src/studio/protocol.ts";

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
// each top-level and layout block, then each group's children.
export function blocksOf(tree: readonly TreeBlock[]): { nodes: TreeNode[]; destinations: Destination[] } {
  const nodes: TreeNode[] = [], destinations: Destination[] = tree.map((b) => ({ path: b.path, label: b.label }));
  const walk = (list: readonly TreeNode[]): void => list.forEach((n) => {
    nodes.push(n);
    if (n.type === "group") destinations.push({ path: [...n.path, "children"], label: `${n.id} (group)` });
    walk(n.children);
  });
  tree.forEach((b) => walk(b.children));
  return { nodes, destinations };
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
