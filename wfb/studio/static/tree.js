// The element tree's structure: pure functions, no DOM, so Node can check
// them (tests/test_studio_frontend.py).

// Every element (flat, draw order) and every block an element can go to:
// each top-level and layout block, then each group's children.
export function blocksOf(tree) {
  const nodes = [], destinations = tree.map((b) => ({ path: b.path, label: b.label }));
  const walk = (list) => list.forEach((n) => {
    nodes.push(n);
    if (n.type === "group") destinations.push({ path: [...n.path, "children"], label: `${n.id} (group)` });
    walk(n.children || []);
  });
  tree.forEach((b) => walk(b.children));
  return { nodes, destinations };
}

// The ids beside the element at `path`, itself included, in order.
export function siblingsOf(tree, path) {
  const parent = JSON.stringify(path.slice(0, -1));
  const out = [];
  const walk = (list) => list.forEach((n) => {
    if (JSON.stringify(n.path.slice(0, -1)) === parent) out.push(n.id);
    walk(n.children || []);
  });
  tree.forEach((b) => walk(b.children));
  return out;
}

// Where a row dropped at `fraction` of its height (0 top, 1 bottom) sends
// the dragged element: before the row, after it (before its next sibling,
// `next`, or at the block's end), or, in a group's middle third, into the
// group.
export function dropTarget(node, fraction, next = null) {
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
export function carriesPath(types) {
  return Array.from(types || []).includes(PATH_TYPE);
}

// The path a drop carries, or null when it is not a path.
export function droppedPath(raw) {
  let path;
  try { path = JSON.parse(raw); } catch (_) { return null; }
  const step = (s) => typeof s === "string" || Number.isInteger(s);
  return Array.isArray(path) && path.length && path.every(step) ? path : null;
}
