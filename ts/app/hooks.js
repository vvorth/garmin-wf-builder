// The editor's state machines, each a hook `app.js`'s Editor composes:
// the outbox every change goes through, the frame and what it is drawn
// at, the keyboard shortcuts, panning and zooming the face, and the right
// column's folds.

import { useCallback, useEffect, useLayoutEffect, useRef, useState }
  from "./vendor/preact-htm.module.js";
import { api } from "./api.js";
import { shortcutFor, typingIn } from "./keys.js";
import { droppedError, enqueue, mark, next } from "./outbox.js";
import { picksParam } from "./values.js";

// -- the outbox ------------------------------------------------------------------------

// Every change to the face -- gestures from the canvas and the arrow keys,
// edits from the panels and the layers, undo, redo, uploads and restores
// -- sent one at a time, each against the version the one before produced
// (`outbox.js`), so the canvas never waits for the server and an edit made
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
export function useOutbox({ docId, doc, frame, where, accept, reload, onError, onNotice }) {
  const [queue, setQueue] = useState([]);
  const queued = useRef([]);
  const latest = useRef(null);       // the newest version known, for the next send
  const shown = useRef(docId);       // the face open now: an answer about another is dropped
  shown.current = docId;
  const commit = (q) => { queued.current = q; setQueue(q); };
  useEffect(() => { if (doc) latest.current = doc.version; }, [doc && doc.id, doc && doc.version]);
  useEffect(() => { commit([]); latest.current = null; }, [docId]);
  // a frame showing a gesture's version retires it
  useEffect(() => {
    if (frame) commit(queued.current.filter((e) => !(e.state === "done" && e.done <= frame.version)));
  }, [frame && frame.version]);

  const post = (entry, version) => {
    if (entry.gesture) {
      const which = entry.ids.length > 1 ? { elements: entry.ids } : { element: entry.ids[0] };
      return api("drag", { id: docId, version, ...which, gesture: entry.gesture, ...entry.where });
    }
    const { op, args = {}, body = null } = entry.request;
    return api(op, { ...args, id: docId, version }, body);
  };
  const pump = useCallback(async () => {
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
      if (entry.gesture && !updated.landed) onNotice(`${updated.what}: written as close as its units allow, not exactly on the pixel`);
      if (entry.resolve) entry.resolve(updated);
      pump();
    } catch (e) {
      if (shown.current !== docId) { if (entry.resolve) entry.resolve(null); return; }
      // what was queued behind it was aimed at a face that did not happen,
      // and the message says how much that was
      const dropped = queued.current.filter((q) => q.state !== "done");
      commit(queued.current.filter((q) => q.state === "done"));
      for (const q of dropped) if (q.resolve) q.resolve(null);
      onError(droppedError(e, dropped.length - 1));
      if (e.status === 409) reload();
    }
  }, [docId]);
  const onDrag = useCallback((ids, gesture, shown) => {
    commit(enqueue(queued.current, { ids, gesture, ...shown, where: { ...where.current } }));
    pump();
  }, [pump]);
  const send = useCallback((request) => new Promise((resolve) => {
    commit(enqueue(queued.current, { request, resolve }));
    pump();
  }), [pump]);
  return { queue, queued, onDrag, send };
}

// -- the frame -------------------------------------------------------------------------

// This computer's time and date, as the time and date inputs write them.
export function clockNow() {
  const d = new Date();
  const two = (n) => String(n).padStart(2, "0");
  return { time: `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`,
           date: `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}` };
}

// The frame of the face shown: `doc` on `view.device`, at `time` and
// `date`, drawn at the whole `scale`, with `view`'s style, slot picks,
// asleep and AOD; and the watch's skin when `view.skin` asks and the
// device (`deviceInfo`) has one. With `view.now`, the clock moves on a
// second after each frame arrives, so a slow frame is never queued behind.
// Returns `{frame, busy, skin, clock, setClock}`.
export function useFrame({ docId, doc, view, scale, deviceInfo, onError }) {
  const [frame, setFrame] = useState(null);
  const [busy, setBusy] = useState(false);
  const [skin, setSkin] = useState(null);
  const [clock, setClock] = useState(clockNow());
  const time = view.now ? clock.time : view.time;
  const date = view.now ? clock.date : view.date;
  const slots = (doc && doc.globals && doc.globals.slots) || [];
  const picks = picksParam(view.picks, slots);
  // One frame on its way at a time: the worker draws in turn with the
  // face's edits, so a zoom drag or a run of time steps must not queue a
  // frame per step. A newer ask replaces the one waiting, and only the
  // newest ask's answer is shown.
  const asked = useRef(0);            // the newest ask, by number
  const waiting = useRef(null);       // the ask not sent yet, {n, args}
  const sending = useRef(false);
  const pump = async () => {
    if (sending.current || waiting.current === null) return;
    const { n, args } = waiting.current;
    waiting.current = null;
    sending.current = true;
    try {
      const f = await api("frame", args);
      if (n === asked.current) setFrame(f);
    } catch (e) {
      if (n === asked.current) onError(e);
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
    api("skin", { device: view.device, scale }).then((s) => { if (live) setSkin(s); }, onError);
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

// The editor's shortcuts (`keys.shortcutFor`), with one listener for the
// editor's whole life: `actions` (one per action name) is read as it is
// at the key press. An action that is
// null, or returns false, is not available then, and the browser keeps
// the key (Ctrl+D, the arrows' scrolling). Nothing fires while typing.
export function useShortcuts(actions) {
  const current = useRef(actions);
  current.current = actions;
  useEffect(() => {
    const onKey = (e) => {
      if (typingIn(e.target)) return;
      const shortcut = shortcutFor(e);
      if (!shortcut) return;
      const [name, ...args] = shortcut;
      const action = current.current[name];
      if (action && action(...args) !== false) e.preventDefault();
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);
}

// Copy, cut and paste as the browser's own events, which read and write
// the system clipboard without asking, so elements go between faces, tabs
// and a text editor as YAML. `actions` (`{copy, cut, paste}`) is read as
// it is at the event: `copy()` returns the text to put on the clipboard,
// or null to leave the event to the browser; `cut()` then removes what was
// copied; `paste(text)` takes what is on it. Typing, or text selected on
// the page, keeps the browser's own.
export function useClipboard(actions) {
  const current = useRef(actions);
  current.current = actions;
  useEffect(() => {
    const out = (cut) => (e) => {
      const selection = typeof getSelection === "function" ? String(getSelection() || "") : "";
      if (typingIn(e.target) || selection) return;
      const text = current.current.copy();
      if (!text || !e.clipboardData) return;
      e.clipboardData.setData("text/plain", text);
      e.preventDefault();
      if (cut) current.current.cut();
    };
    const onPaste = (e) => {
      if (typingIn(e.target) || !current.current.paste) return;
      const text = e.clipboardData ? e.clipboardData.getData("text/plain") : "";
      if (!text) return;
      e.preventDefault();
      current.current.paste(text);
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

// Ctrl/Cmd + wheel zooms about the pointer (`zoom`, `setZoom`); dragging
// the space round the watch, the middle button anywhere, or any button
// with Space held (while `active`), pans; a click on that space calls
// `onBackground`. Returns the scrolling box's ref and its handlers.
export function usePanZoom({ zoom, setZoom, active, onBackground }) {
  const wrap = useRef(null);
  const anchor = useRef(null);       // the watch pixel kept under the pointer
  const frameImage = () => wrap.current && wrap.current.querySelector(".canvas img.frame");
  const onWheel = (e) => {
    if (!(e.ctrlKey || e.metaKey) || !frameImage()) return;
    e.preventDefault();
    const r = frameImage().getBoundingClientRect();
    anchor.current = { cx: e.clientX, cy: e.clientY, px: (e.clientX - r.left) / zoom, py: (e.clientY - r.top) / zoom };
    setZoom(zoom * Math.exp(-e.deltaY * 0.002));
  };
  useLayoutEffect(() => {
    const a = anchor.current, el = wrap.current, image = frameImage();
    anchor.current = null;
    if (!a || !image) return;
    const r = image.getBoundingClientRect();
    el.scrollLeft += r.left + a.px * zoom - a.cx;
    el.scrollTop += r.top + a.py * zoom - a.cy;
  }, [zoom]);
  const space = useRef(false);
  const live = useRef(active);
  live.current = active;
  useEffect(() => {
    // Space on a control still presses it
    const down = (e) => {
      if (e.code === "Space" && live.current && !typingIn(e.target)
          && !(e.target.closest && e.target.closest("button"))) { space.current = true; e.preventDefault(); }
    };
    const up = (e) => { if (e.code === "Space") space.current = false; };
    addEventListener("keydown", down); addEventListener("keyup", up);
    return () => { removeEventListener("keydown", down); removeEventListener("keyup", up); };
  }, []);
  const pan = useRef(null);
  const onPointerDownCapture = (e) => {
    const background = e.target === wrap.current;
    if (!(e.button === 1 || space.current || (e.button === 0 && background))) return;
    e.preventDefault(); e.stopPropagation();
    wrap.current.setPointerCapture && wrap.current.setPointerCapture(e.pointerId);
    pan.current = { x: e.clientX, y: e.clientY, moved: false, background: background && e.button === 0 && !space.current };
  };
  const onPointerMove = (e) => {
    const p = pan.current;
    if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    if (!p.moved && Math.hypot(dx, dy) < 3) return;
    p.moved = true;
    wrap.current.scrollLeft -= dx; wrap.current.scrollTop -= dy;
    p.x = e.clientX; p.y = e.clientY;
  };
  const onPointerUp = () => {
    const p = pan.current;
    pan.current = null;
    if (p && p.background && !p.moved) onBackground();
  };
  const onPointerCancel = () => { pan.current = null; };
  return { wrap, handlers: { onWheel, onPointerDownCapture, onPointerMove, onPointerUp, onPointerCancel } };
}

// -- the right column's folds -------------------------------------------------------------

// Which of the right column's two sections are folded (`props`, `lower`),
// as this browser last left them, and `setFolded(which, folded)`.
export function useFold() {
  const [fold, setFold] = useState(() => {
    try { return { props: false, lower: false, ...JSON.parse(localStorage.getItem("wfb-fold") || "{}") }; }
    catch (_) { return { props: false, lower: false }; }
  });
  const setFolded = (which, value) => setFold((f) => {
    const changed = { ...f, [which]: value };
    try { localStorage.setItem("wfb-fold", JSON.stringify(changed)); } catch (_) { /* private mode */ }
    return changed;
  });
  return [fold, setFolded];
}
