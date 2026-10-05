// The editor's keyboard shortcuts: which action a key press asks for. A
// pure function, no DOM, so Node can check it
// (tests/test_studio_frontend.py); `hooks.useShortcuts` acts on it.

const ARROWS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

// The action a key press (`{key, ctrlKey, metaKey, shiftKey, altKey}`)
// asks for, with its arguments: `["undo"]`, `["redo"]`, `["duplicate"]`,
// `["selectAll"]`, `["nudge", dx, dy]` (one pixel, ten with Shift) or
// `["remove"]`; null for any other key.
export function shortcutFor(e) {
  const key = (e.key || "").toLowerCase();
  if (e.ctrlKey || e.metaKey) {
    if (key === "z") return [e.shiftKey ? "redo" : "undo"];
    if (key === "y") return ["redo"];
    if (key === "d") return ["duplicate"];
    if (key === "a") return ["selectAll"];
    return null;
  }
  const arrow = ARROWS[e.key];
  if (arrow) {
    if (e.altKey) return null;
    const n = e.shiftKey ? 10 : 1;
    return ["nudge", arrow[0] * n, arrow[1] * n];
  }
  if (e.key === "Delete" || e.key === "Backspace") return ["remove"];
  return null;
}

// Whether a key press lands where it types (a field, the YAML tab), where
// the editor's shortcuts stand aside.
export function typingIn(target) {
  return !!(target && target.closest && target.closest("input, textarea, select, .cm-editor"));
}
