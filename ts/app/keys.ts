// The editor's keyboard shortcuts: which action a key press asks for, and
// the list the "?" overlay shows. Pure functions, no DOM, so Node can
// check them (test/page-modules.test.ts); `hooks.useShortcuts` acts on
// them.

/** What a key press carries, as the editor reads it: `KeyboardEvent`'s keys and modifiers. */
export interface KeyPress {
  key?: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
}

/**
 * An action and its arguments: `zoom` by a step in or out, `nudge` by
 * pixels along each axis.
 */
export type Shortcut =
  | ["undo"] | ["redo"] | ["duplicate"] | ["selectAll"] | ["group"] | ["ungroup"]
  | ["forward"] | ["backward"] | ["zoom", 1 | -1] | ["zoomFit"] | ["zoomReal"]
  | ["nudge", number, number] | ["remove"] | ["deselect"] | ["help"] | ["commandPalette"];

const ARROWS: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

// The action a key press asks for, with its arguments, or null for any
// other key: `forward` and `backward` are one step in draw order, `nudge`
// one pixel (ten with Shift). Copy, cut and paste are the browser's own
// events, not key presses (`app.js`).
export function shortcutFor(e: KeyPress): Shortcut | null {
  const key = (e.key || "").toLowerCase();
  if (e.ctrlKey || e.metaKey) {
    if (key === "z") return [e.shiftKey ? "redo" : "undo"];
    if (key === "y") return ["redo"];
    if (key === "d") return ["duplicate"];
    if (key === "a") return ["selectAll"];
    if (key === "g") return [e.shiftKey ? "ungroup" : "group"];
    if (key === "]") return ["forward"];
    if (key === "[") return ["backward"];
    if (key === "=" || key === "+") return ["zoom", 1];
    if (key === "-" || key === "_") return ["zoom", -1];
    if (key === "0") return ["zoomFit"];
    if (key === "k") return ["commandPalette"];
    return null;
  }
  if (e.altKey) return null;
  const arrow = e.key === undefined ? undefined : ARROWS[e.key];
  if (arrow) {
    const n = e.shiftKey ? 10 : 1;
    return ["nudge", arrow[0] * n, arrow[1] * n];
  }
  if (e.key === "Delete" || e.key === "Backspace") return ["remove"];
  if (e.key === "Escape") return ["deselect"];
  if (e.key === "?") return ["help"];
  if (e.key === "1") return ["zoomReal"];
  return null;
}

// Whether a key press lands where it types (a field, the YAML tab), where
// the editor's shortcuts stand aside. `target` is the event's target: an
// element, or anything else (null, a window) that types nothing.
export function typingIn(target: unknown): boolean {
  // the DOM boundary: an event's target has `closest` only when it is an element
  const t = target as { closest?: (selector: string) => unknown } | null | undefined;
  return !!(t && typeof t.closest === "function" && t.closest("input, textarea, select, .cm-editor"));
}

// What the "?" overlay lists, in groups: each `[keys, what]`, "Ctrl"
// standing for Cmd on a Mac.
export const SHORTCUTS: [string, [string, string][]][] = [
  ["Edit", [
    ["Ctrl+Z", "undo"], ["Ctrl+Shift+Z, Ctrl+Y", "redo"],
    ["Ctrl+C, Ctrl+X, Ctrl+V", "copy, cut and paste elements, between faces too"],
    ["Ctrl+D", "duplicate"], ["Del, Backspace", "delete the selection"],
    ["Ctrl+G, Ctrl+Shift+G", "group the selection, ungroup a group"],
    ["Ctrl+], Ctrl+[", "bring forward, send backward (draw order)"],
  ]],
  ["Select", [
    ["click, Ctrl+click", "select, add to or take out of the selection"],
    ["Shift+click", "on the face: add; in Layers: every row up to it"],
    ["Ctrl+A", "select everything the frame shows"], ["Esc", "select nothing, or cancel a drag"],
  ]],
  ["Move", [
    ["arrows, Shift+arrows", "nudge one pixel, ten"],
    ["drag", "move or resize, snapping to the grid and to other elements"],
    ["Alt while dragging", "move freely: no snapping"],
  ]],
  ["View", [
    ["Ctrl+=, Ctrl+-", "zoom in, out"], ["Ctrl+wheel", "zoom about the pointer"],
    ["Ctrl+0", "fit the watch in view"], ["1", "the watch's real size"],
    ["Space+drag, middle drag", "pan"], ["?", "this list"],
  ]],
  ["Find", [
    ["Ctrl+K", "jump to any element, colour, font, slot, hand set or style by name"],
  ]],
];
