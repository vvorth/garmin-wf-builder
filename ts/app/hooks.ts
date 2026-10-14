// The editor's hooks on the browser itself, which `app.ts`'s Editor
// composes: the keyboard shortcuts, the clipboard, and panning and zooming
// the face. The editor's state lives in `store.ts`.

import type { JSX } from "preact";
import { useEffect, useLayoutEffect, useRef } from "preact/hooks";
import type { MutableRef } from "preact/hooks";
import { shortcutFor, typingIn } from "./keys.ts";
import type { Shortcut } from "./keys.ts";

// -- the keyboard ----------------------------------------------------------------------

/** The arguments a shortcut carries after its name: `zoom`'s step, `nudge`'s pixels. */
type ShortcutArgs<N extends Shortcut[0]> = Extract<Shortcut, [N, ...unknown[]]> extends [N, ...infer A] ? A : never;

/** One action per shortcut name: null, or missing, when it is not available; returning false leaves the key to the browser. */
export type ShortcutActions = {
  [N in Shortcut[0]]?: ((...args: ShortcutArgs<N>) => unknown) | null;
};

// The editor's shortcuts (`keys.shortcutFor`), with one listener for the
// editor's whole life: `actions` (one per action name) is read as it is
// at the key press. An action that is
// null, or returns false, is not available then, and the browser keeps
// the key (Ctrl+D, the arrows' scrolling). Nothing fires while typing.
export function useShortcuts(actions: ShortcutActions): void {
  const current = useRef(actions);
  current.current = actions;
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (typingIn(e.target)) return;
      const shortcut = shortcutFor(e);
      if (!shortcut) return;
      const [name, ...args] = shortcut;
      // the name and its arguments come as one tuple, and the table's entry
      // for that name takes exactly those, which the destructuring loses
      const action = current.current[name] as ((...args: unknown[]) => unknown) | null | undefined;
      if (action && action(...args) !== false) e.preventDefault();
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);
}

export interface ClipboardActions {
  /** The text to put on the clipboard, or null to leave the event to the browser. */
  copy: () => string | null;
  /** Remove what `copy` gave. */
  cut: () => void;
  paste?: ((text: string) => void) | undefined;
}

// Copy, cut and paste as the browser's own events, which read and write
// the system clipboard without asking, so elements go between faces, tabs
// and a text editor as YAML. `actions` (`{copy, cut, paste}`) is read as
// it is at the event: `copy()` returns the text to put on the clipboard,
// or null to leave the event to the browser; `cut()` then removes what was
// copied; `paste(text)` takes what is on it. Typing, or text selected on
// the page, keeps the browser's own.
export function useClipboard(actions: ClipboardActions): void {
  const current = useRef(actions);
  current.current = actions;
  useEffect(() => {
    const out = (cut: boolean) => (e: ClipboardEvent): void => {
      const selection = typeof getSelection === "function" ? String(getSelection() || "") : "";
      if (typingIn(e.target) || selection) return;
      const text = current.current.copy();
      if (!text || !e.clipboardData) return;
      e.clipboardData.setData("text/plain", text);
      e.preventDefault();
      if (cut) current.current.cut();
    };
    const onPaste = (e: ClipboardEvent): void => {
      const paste = current.current.paste;
      if (typingIn(e.target) || !paste) return;
      const text = e.clipboardData ? e.clipboardData.getData("text/plain") : "";
      if (!text) return;
      e.preventDefault();
      paste(text);
    };
    const onCopy = out(false), onCut = out(true);
    addEventListener("copy", onCopy); addEventListener("cut", onCut); addEventListener("paste", onPaste);
    return () => {
      removeEventListener("copy", onCopy); removeEventListener("cut", onCut);
      removeEventListener("paste", onPaste);
    };
  }, []);
}

// -- panning and zooming the face -------------------------------------------------------

export interface PanZoomProps {
  /** CSS pixels per watch pixel. */
  zoom: number;
  setZoom: (zoom: number) => void;
  /** The face pane is showing: Space then arms a pan. */
  active: boolean;
  /** A click on the space round the watch. */
  onBackground: () => void;
}

/** The scrolling box's handlers, spread onto it. */
export interface PanZoomHandlers {
  onWheel: (e: JSX.TargetedWheelEvent<HTMLDivElement>) => void;
  onPointerDownCapture: (e: JSX.TargetedPointerEvent<HTMLDivElement>) => void;
  onPointerMove: (e: JSX.TargetedPointerEvent<HTMLDivElement>) => void;
  onPointerUp: () => void;
  onPointerCancel: () => void;
}

export interface PanZoom {
  wrap: MutableRef<HTMLDivElement | null>;
  handlers: PanZoomHandlers;
}

/** The watch pixel (`px`, `py`) under the pointer (`cx`, `cy`) when a zoom was asked, kept there as the zoom lands. */
interface Anchor {
  cx: number;
  cy: number;
  px: number;
  py: number;
}

/** A pan in progress: where the pointer was last, whether it moved, and whether it began as a click on the background. */
interface Pan {
  x: number;
  y: number;
  moved: boolean;
  background: boolean;
}

// Ctrl/Cmd + wheel zooms about the pointer (`zoom`, `setZoom`); dragging
// the space round the watch, the middle button anywhere, or any button
// with Space held (while `active`), pans; a click on that space calls
// `onBackground`. Returns the scrolling box's ref and its handlers.
export function usePanZoom({ zoom, setZoom, active, onBackground }: PanZoomProps): PanZoom {
  const wrap = useRef<HTMLDivElement | null>(null);
  const anchor = useRef<Anchor | null>(null);       // the watch pixel kept under the pointer
  const frameImage = (): HTMLImageElement | null => wrap.current && wrap.current.querySelector<HTMLImageElement>(".canvas img.frame");
  const onWheel = (e: JSX.TargetedWheelEvent<HTMLDivElement>): void => {
    const image = frameImage();
    if (!(e.ctrlKey || e.metaKey) || !image) return;
    e.preventDefault();
    const r = image.getBoundingClientRect();
    anchor.current = { cx: e.clientX, cy: e.clientY, px: (e.clientX - r.left) / zoom, py: (e.clientY - r.top) / zoom };
    setZoom(zoom * Math.exp(-e.deltaY * 0.002));
  };
  useLayoutEffect(() => {
    const a = anchor.current, el = wrap.current, image = frameImage();
    anchor.current = null;
    if (!a || !image || !el) return;
    const r = image.getBoundingClientRect();
    el.scrollLeft += r.left + a.px * zoom - a.cx;
    el.scrollTop += r.top + a.py * zoom - a.cy;
  }, [zoom]);
  const space = useRef(false);
  const live = useRef(active);
  live.current = active;
  useEffect(() => {
    // Space on a control still presses it
    const down = (e: KeyboardEvent): void => {
      // the DOM boundary: the key's target has `closest` only when it is an element
      const target = e.target as { closest?: (selector: string) => unknown } | null;
      if (e.code === "Space" && live.current && !typingIn(e.target)
          && !(target && typeof target.closest === "function" && target.closest("button"))) { space.current = true; e.preventDefault(); }
    };
    const up = (e: KeyboardEvent): void => { if (e.code === "Space") space.current = false; };
    addEventListener("keydown", down); addEventListener("keyup", up);
    return () => { removeEventListener("keydown", down); removeEventListener("keyup", up); };
  }, []);
  const pan = useRef<Pan | null>(null);
  const onPointerDownCapture = (e: JSX.TargetedPointerEvent<HTMLDivElement>): void => {
    const el = wrap.current;
    const background = e.target === el;
    if (!(e.button === 1 || space.current || (e.button === 0 && background))) return;
    e.preventDefault(); e.stopPropagation();
    if (el && typeof el.setPointerCapture === "function") el.setPointerCapture(e.pointerId);
    pan.current = { x: e.clientX, y: e.clientY, moved: false, background: background && e.button === 0 && !space.current };
  };
  const onPointerMove = (e: JSX.TargetedPointerEvent<HTMLDivElement>): void => {
    const p = pan.current, el = wrap.current;
    if (!p || !el) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    if (!p.moved && Math.hypot(dx, dy) < 3) return;
    p.moved = true;
    el.scrollLeft -= dx; el.scrollTop -= dy;
    p.x = e.clientX; p.y = e.clientY;
  };
  const onPointerUp = (): void => {
    const p = pan.current;
    pan.current = null;
    if (p && p.background && !p.moved) onBackground();
  };
  const onPointerCancel = (): void => { pan.current = null; };
  return { wrap, handlers: { onWheel, onPointerDownCapture, onPointerMove, onPointerUp, onPointerCancel } };
}
