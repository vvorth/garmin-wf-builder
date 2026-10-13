// The editor's state machines, each a hook `app.js`'s Editor composes:
// the outbox every change goes through, the frame and what it is drawn
// at, the keyboard shortcuts, panning and zooming the face, and the right
// column's folds.

import type { JSX } from "preact";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import type { Dispatch, MutableRef, StateUpdater } from "preact/hooks";
import type { Answer, Args, DeviceInfo, Dragged, Frame, FrameArgs, Gesture, Op, Skin, Summary } from "../src/studio/protocol.ts";
import { api } from "./api.ts";
import { shortcutFor, typingIn } from "./keys.ts";
import type { Shortcut } from "./keys.ts";
import { droppedError, enqueue, mark, next } from "./outbox.ts";
import type { Entry, Failure, GestureEntry, RequestEntry, Where } from "./outbox.ts";
import { picksParam } from "./values.ts";

// An error as `api` throws one (its status kept); anything else thrown, as one.
function failure(e: unknown): Failure {
  return e instanceof Error ? e : new Error(String(e));
}

// -- the outbox ------------------------------------------------------------------------

/** The operations a queued change may be: every one answers with the face (a `Summary`, or a `Structured` with what to select). */
export type ChangeOp = { [O in Op]: Answer<O> extends Summary ? O : never }[Op];

/** A change as `send` takes it: the operation, its arguments (the face's id and version are added) and a file's bytes. */
export interface Change<O extends ChangeOp = ChangeOp> {
  op: O;
  args?: Record<string, unknown>;
  body?: Blob | Uint8Array | null;
}

/** What the canvas draws a gesture from while it is on its way: the dragged item, every element it moves and the preview. */
export type Shown = Pick<GestureEntry, "item" | "moving" | "preview">;

export interface OutboxProps {
  docId: string;
  doc: Summary | null;
  frame: Frame | null;
  /** The device and scope a gesture is written for, as they are when it is made. */
  where: { readonly current: Where };
  accept: (face: Summary) => void;
  reload: () => void;
  onError: (error: Failure) => void;
  onNotice: (message: string) => void;
}

export interface Outbox {
  queue: Entry[];
  queued: MutableRef<Entry[]>;
  onDrag: (ids: string[], gesture: Gesture, shown: Shown) => void;
  /** The face `request` produced (its operation's own answer), or null when it was refused. */
  send: <O extends ChangeOp>(request: Change<O>) => Promise<Answer<O> | null>;
}

const isGesture = (entry: Entry): entry is GestureEntry => entry.gesture !== undefined;
const isDragged = (face: Summary): face is Dragged => "landed" in face;

// Every change to the face -- gestures from the canvas and the arrow keys,
// edits from the panels and the layers, undo, redo, uploads and restores
// -- sent one at a time, each against the version the one before produced
// (`outbox.ts`), so the canvas never waits for the worker and an edit made
// while a drag is on its way is not refused as stale.
//
// `doc` and `frame` are the face and frame shown; `where` a ref holding
// the device and scope a gesture is written for; `accept(face)` shows an
// answer; `reload()` fetches the face after a refusal for being stale.
// Returns the queue (state, for drawing; `queued`, a ref, for reading
// now), `onDrag(ids, gesture, shown)` for a gesture and `send(request)`
// for any other change, `{op, args, body}` (the face's id and version are
// added), which
// resolves to the face it produced, or null when it was refused (the
// refusal is shown).
export function useOutbox({ docId, doc, frame, where, accept, reload, onError, onNotice }: OutboxProps): Outbox {
  const [queue, setQueue] = useState<Entry[]>([]);
  const queued = useRef<Entry[]>([]);
  const latest = useRef<number | null>(null);       // the newest version known, for the next send
  const shown = useRef(docId);                      // the face open now: an answer about another is dropped
  shown.current = docId;
  const commit = (q: Entry[]): void => { queued.current = q; setQueue(q); };
  useEffect(() => { if (doc) latest.current = doc.version; }, [doc && doc.id, doc && doc.version]);
  useEffect(() => { commit([]); latest.current = null; }, [docId]);
  // a frame showing a gesture's version retires it
  useEffect(() => {
    if (frame) commit(queued.current.filter((e) => !(e.state === "done" && (e.done ?? 0) <= frame.version)));
  }, [frame && frame.version]);

  const post = (entry: Entry, version: number): Promise<Summary> => {
    if (isGesture(entry)) {
      const which = entry.ids.length > 1 ? { elements: entry.ids } : { element: entry.ids[0]! };
      // a gesture is always made on a viewed device; without one the worker refuses it
      const { device = "", ...where } = entry.where;
      return api("drag", { id: docId, version, device, ...where, ...which, gesture: entry.gesture });
    }
    const { op, args = {}, body = null } = entry.request;
    // the queue's request carries loose arguments (`outbox.ts`): the worker
    // checks them, and every change the editor queues answers with the face
    return api(op, { ...args, id: docId, version } as Args<Op>, body) as Promise<Summary>;
  };
  const pump = useCallback(async (): Promise<void> => {
    const entry = next(queued.current);
    if (!entry || latest.current === null) return;
    commit(mark(queued.current, entry, "sent"));
    try {
      const updated = await post(entry, latest.current);
      // the editor moved to another face meanwhile: its queue and version
      // are that face's now
      if (shown.current !== docId) { if (entry.resolve) entry.resolve(null); return; }
      latest.current = updated.version;
      commit(mark(queued.current, queued.current.find((e) => e.state === "sent"), "done", updated.version));
      accept(updated);
      if (isGesture(entry) && isDragged(updated) && !updated.landed) {
        onNotice(`${updated.what}: written as close as its units allow, not exactly on the pixel`);
      }
      if (entry.resolve) entry.resolve(updated);
      pump();
    } catch (e) {
      if (shown.current !== docId) { if (entry.resolve) entry.resolve(null); return; }
      // what was queued behind it was aimed at a face that did not happen,
      // and the message says how much that was
      const dropped = queued.current.filter((q) => q.state !== "done");
      commit(queued.current.filter((q) => q.state === "done"));
      for (const q of dropped) if (q.resolve) q.resolve(null);
      const error = failure(e);
      onError(droppedError(error, dropped.length - 1));
      if (error.status === 409) reload();
    }
  }, [docId]);
  const onDrag = useCallback((ids: string[], gesture: Gesture, shown: Shown): void => {
    commit(enqueue(queued.current, { ids, gesture, ...shown, where: { ...where.current } }));
    pump();
  }, [pump]);
  const send = useCallback(<O extends ChangeOp>(request: Change<O>): Promise<Answer<O> | null> => new Promise((resolve) => {
    // the queue types every answer as the face; this one is the operation's own
    commit(enqueue(queued.current, { request, resolve: resolve as (answer: Summary | null) => void }));
    pump();
  }), [pump]);
  return { queue, queued, onDrag, send };
}

// -- the frame -------------------------------------------------------------------------

/** A time and a date, as the time and date inputs write them. */
export interface Clock {
  time: string;
  date: string;
}

// This computer's time and date, as the time and date inputs write them.
export function clockNow(): Clock {
  const d = new Date();
  const two = (n: number): string => String(n).padStart(2, "0");
  return { time: `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`,
           date: `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}` };
}

/** What the frame is drawn at, out of the editor's view state. */
export interface FrameView {
  device: string | null;
  style: string;
  /** `HH:MM:SS`, or empty for the sample moment. */
  time: string;
  /** `YYYY-MM-DD`, or empty for the sample day. */
  date: string;
  /** Follow this computer's clock. */
  now: boolean;
  asleep: boolean;
  aod: boolean;
  skin: boolean;
  /** What each slot is drawn showing, by slot name. */
  picks?: Readonly<Record<string, string | undefined>> | null;
}

export interface FrameProps {
  docId: string;
  doc: Summary | null;
  view: FrameView;
  /** The whole scale the worker draws at. */
  scale: number;
  deviceInfo: DeviceInfo | undefined;
  onError: (error: Failure) => void;
}

export interface FrameState {
  frame: Frame | null;
  /** A frame is on its way. */
  busy: boolean;
  skin: Skin | null;
  clock: Clock;
  setClock: Dispatch<StateUpdater<Clock>>;
  /** The time and date drawn: the clock's when following it, else the view's. */
  time: string;
  date: string;
  /** The slot picks as the frame request spells them. */
  picks: string;
}

// The frame of the face shown: `doc` on `view.device`, at `time` and
// `date`, drawn at the whole `scale`, with `view`'s style, slot picks,
// asleep and AOD; and the watch's skin when `view.skin` asks and the
// device (`deviceInfo`) has one. With `view.now`, the clock moves on a
// second after each frame arrives, so a slow frame is never queued behind.
// Returns `{frame, busy, skin, clock, setClock}`.
export function useFrame({ docId, doc, view, scale, deviceInfo, onError }: FrameProps): FrameState {
  const [frame, setFrame] = useState<Frame | null>(null);
  const [busy, setBusy] = useState(false);
  const [skin, setSkin] = useState<Skin | null>(null);
  const [clock, setClock] = useState<Clock>(clockNow());
  const time = view.now ? clock.time : view.time;
  const date = view.now ? clock.date : view.date;
  const slots = (doc && doc.globals && doc.globals.slots) || [];
  const picks = picksParam(view.picks, slots);
  // One frame on its way at a time: the worker draws in turn with the
  // face's edits, so a zoom drag or a run of time steps must not queue a
  // frame per step. A newer ask replaces the one waiting, and only the
  // newest ask's answer is shown.
  const asked = useRef(0);                                              // the newest ask, by number
  const waiting = useRef<{ n: number; args: FrameArgs } | null>(null);  // the ask not sent yet
  const sending = useRef(false);
  const pump = async (): Promise<void> => {
    if (sending.current || waiting.current === null) return;
    const { n, args } = waiting.current;
    waiting.current = null;
    sending.current = true;
    try {
      const f = await api("frame", args);
      if (n === asked.current) setFrame(f);
    } catch (e) {
      if (n === asked.current) onError(failure(e));
    } finally {
      sending.current = false;
      if (waiting.current !== null) pump();
      else setBusy(false);
    }
  };
  useEffect(() => { setFrame(null); }, [docId]);
  useEffect(() => {
    const n = ++asked.current;
    if (!doc || !view.device || !doc.targets.includes(view.device)) { waiting.current = null; setFrame(null); return; }
    setBusy(true);
    waiting.current = { n, args: { id: docId, device: view.device, scale, style: view.style, time, date,
                                   asleep: view.asleep, aod: view.aod, picks } };
    pump();
  }, [doc && doc.version, doc && doc.targets.join(), view.device, view.style, time, date,
      view.asleep, view.aod, scale, picks]);
  useEffect(() => {
    if (!view.skin || !deviceInfo || !deviceInfo.skin) { setSkin(null); return; }
    let live = true;
    // `deviceInfo` is the viewed device's, so its id is `view.device`
    api("skin", { device: deviceInfo.id, scale }).then((s) => { if (live) setSkin(s); }, (e: unknown) => onError(failure(e)));
    return () => { live = false; };
  }, [view.skin, view.device, scale, deviceInfo && deviceInfo.skin]);
  useEffect(() => {
    if (!view.now || busy) return;
    const timer = setTimeout(() => setClock(clockNow()), 1000 - (Date.now() % 1000) + 5);
    return () => clearTimeout(timer);
  }, [view.now, busy, clock]);
  return { frame, busy, skin, clock, setClock, time, date, picks };
}

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

// -- the right column's folds -------------------------------------------------------------

/** Which of the right column's two sections are folded. */
export interface Fold {
  props: boolean;
  lower: boolean;
}

// Which of the right column's two sections are folded (`props`, `lower`),
// as this browser last left them, and `setFolded(which, folded)`.
export function useFold(): [Fold, (which: keyof Fold, value: boolean) => void] {
  const [fold, setFold] = useState<Fold>(() => {
    // the browser's storage holds what this hook last wrote
    try { return { props: false, lower: false, ...(JSON.parse(localStorage.getItem("wfb-fold") || "{}") as Partial<Fold>) }; }
    catch (_) { return { props: false, lower: false }; }
  });
  const setFolded = (which: keyof Fold, value: boolean): void => setFold((f) => {
    const changed = { ...f, [which]: value };
    try { localStorage.setItem("wfb-fold", JSON.stringify(changed)); } catch (_) { /* private mode */ }
    return changed;
  });
  return [fold, setFolded];
}
