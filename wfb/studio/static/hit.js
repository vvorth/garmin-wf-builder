// Picking what is under the pointer: pure functions, no DOM, so Node can
// check them (tests/test_studio_frontend.py).

// The element a layer belongs to: an outlined group's ring layer is
// `ring:<group id>` and selects the group.
export function elementOf(layerId) {
  return layerId.startsWith("ring:") ? layerId.slice(5) : layerId;
}

// The topmost layer with ink under device pixel (x, y). `layers` are in
// draw order (bottom first), each `{id, box: [x, y, w, h] | null}`;
// `alphaAt(layer, x, y)` reads that layer's coverage there (0..255). A
// layer whose box misses the point is skipped without reading its pixels.
export function topmost(layers, x, y, alphaAt) {
  for (let i = layers.length - 1; i >= 0; i--) {
    const layer = layers[i];
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
// entry) starts after it.
export function elementAtLine(blocks, line) {
  let best = null;
  const walk = (nodes, end) => {
    nodes.forEach((node, i) => {
      const next = i + 1 < nodes.length ? nodes[i + 1].line : end;
      if (node.line <= line && line < next) {
        if (node.kind === "element") best = node;
        walk(node.children || [], next);
      }
    });
  };
  walk(blocks, Infinity);
  return best;
}

// Every element of the tree, depth first, in draw order.
export function flatten(blocks) {
  const out = [];
  const walk = (nodes) => nodes.forEach((n) => {
    if (n.kind === "element") out.push(n);
    walk(n.children || []);
  });
  walk(blocks);
  return out;
}
