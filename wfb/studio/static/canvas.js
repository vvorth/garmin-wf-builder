// The canvas: the face as the server drew it, selection, and the drag
// gestures. During a gesture the dragged element is drawn here, from its
// layer image shifted (a move) or as an outline (a resize, an angle, a
// line's end); on release one gesture goes to the server, which writes it
// in the author's units and answers with the new face, whose frame then
// replaces the preview. Nothing here decides where anything lands.

import { html, useEffect, useRef, useState } from "./vendor/preact-htm.module.js";
import { elementOf, topmost } from "./hit.js";
import {
  angleAt, moveTargets, nearestTurn, resizeDelta, snapAngle, snapLength, snapMove,
} from "./snap.js";

const ACCENT = "#4f9cf9";
const GUIDE = "#f5c04a";
const GRID_PERCENT = 5;     // the %r grid a move and a length snap to
const HANDLE = 5;           // a handle's half size, screen pixels
const START = 3;            // screen pixels before a press becomes a drag

// One layer's image and pixels, decoded once.
const decoded = new WeakMap();
function layerImage(layer) {
  let entry = decoded.get(layer);
  if (!entry) {
    entry = { img: null, data: null };
    decoded.set(layer, entry);
    if (!layer.image) return entry;
    const img = new Image();
    img.onload = () => {
      entry.img = img;
      const c = document.createElement("canvas");
      c.width = img.width; c.height = img.height;
      const ctx = c.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(img, 0, 0);
      entry.data = ctx.getImageData(0, 0, img.width, img.height);
    };
    img.src = layer.image;
  }
  return entry;
}

// What is under device pixel (x, y): by the layers' alpha when they are
// here, else the smallest drawn box holding the point.
function pick(frame, layers, x, y, scale) {
  if (layers) {
    const hit = topmost(layers, x, y, (layer) => {
      const px = layerImage(layer).data;
      if (!px || !layer.origin) return 0;
      const ix = Math.floor(x * scale) - layer.origin[0], iy = Math.floor(y * scale) - layer.origin[1];
      if (ix < 0 || iy < 0 || ix >= px.width || iy >= px.height) return 0;
      return px.data[(iy * px.width + ix) * 4 + 3];
    });
    if (hit) return elementOf(hit.id);
  }
  let best = null;
  for (const item of frame.items) {
    if (!item.drawn) continue;
    const [bx, by, bw, bh] = item.box;
    if (x >= bx && y >= by && x < bx + bw && y < by + bh && (!best || bw * bh <= best.box[2] * best.box[3])) best = item;
  }
  return best ? best.id : null;
}

function drawHandle(ctx, x, y, s) {
  ctx.setLineDash([]);
  ctx.fillStyle = "#fff";
  ctx.strokeStyle = ACCENT;
  ctx.lineWidth = 1.5;
  ctx.fillRect(x * s - HANDLE, y * s - HANDLE, HANDLE * 2, HANDLE * 2);
  ctx.strokeRect(x * s - HANDLE, y * s - HANDLE, HANDLE * 2, HANDLE * 2);
}

function guides(ctx, g, frame, s) {
  ctx.setLineDash([3, 3]);
  ctx.strokeStyle = GUIDE;
  ctx.lineWidth = 1;
  for (const x of g.x) { ctx.beginPath(); ctx.moveTo(x * s, 0); ctx.lineTo(x * s, frame.height * s); ctx.stroke(); }
  for (const y of g.y) { ctx.beginPath(); ctx.moveTo(0, y * s); ctx.lineTo(frame.width * s, y * s); ctx.stroke(); }
}

// The box a resize would give: the moving edge follows the handle; a
// centred box grows both ways.
function resizedBox(box, handle, delta) {
  let [x, y, w, h] = box;
  if (handle.key[0] === "radius") return box;
  if (handle.axis === "x") {
    if (handle.gain === 2) { x -= delta / 2; w += delta; } else if (handle.gain < 0) { x -= delta; w += delta; } else w += delta;
  } else {
    if (handle.gain === 2) { y -= delta / 2; h += delta; } else if (handle.gain < 0) { y -= delta; h += delta; } else h += delta;
  }
  return [x, y, w, h];
}

// The preview of a gesture in progress, or of one sent and not yet drawn.
function drawPreview(ctx, frame, layers, item, g, s) {
  ctx.setLineDash([6, 4]);
  ctx.strokeStyle = ACCENT;
  ctx.lineWidth = 2;
  if (g.kind === "move" && g.part === "both") {
    const own = layers && layers.filter((l) => elementOf(l.id) === item.id && layerImage(l).img);
    if (own && own.length && item.kind !== "group") {
      // the face as layers, the dragged one shifted: exact for a move
      ctx.fillStyle = "#000";
      ctx.fillRect(0, 0, frame.width * s, frame.height * s);
      ctx.save();
      if (frame.shape === "round") {
        ctx.beginPath();
        ctx.arc(frame.width * s / 2, frame.height * s / 2, Math.min(frame.width, frame.height) * s / 2, 0, Math.PI * 2);
        ctx.clip();
      }
      for (const l of layers) {
        const im = layerImage(l).img;
        if (!im || !l.origin) continue;
        const moved = elementOf(l.id) === item.id;
        ctx.drawImage(im, l.origin[0] + (moved ? g.dx * s : 0), l.origin[1] + (moved ? g.dy * s : 0));
      }
      ctx.restore();
    }
    const [x, y, w, h] = item.box;
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = ACCENT;
    ctx.strokeRect((x + g.dx) * s - 1, (y + g.dy) * s - 1, w * s + 2, h * s + 2);
  } else if (g.kind === "move") {
    const ends = item.handles.filter((h) => h.kind === "end");
    const fixed = ends.find((h) => h.part !== g.part), moving = ends.find((h) => h.part === g.part);
    ctx.beginPath();
    ctx.moveTo(fixed.x * s, fixed.y * s);
    ctx.lineTo((moving.x + g.dx) * s, (moving.y + g.dy) * s);
    ctx.stroke();
  } else if (g.kind === "resize" && g.key[0] === "radius") {
    ctx.beginPath();
    ctx.arc(item.center[0] * s, item.center[1] * s, Math.max(0, g.to) * s, 0, Math.PI * 2);
    ctx.stroke();
  } else if (g.kind === "resize") {
    const [x, y, w, h] = resizedBox(item.box, g.handle, g.delta);
    ctx.strokeRect(x * s, y * s, w * s, h * s);
  } else if (g.kind === "turn") {
    const h = g.handle;
    const start = g.key === "start_angle" ? g.degrees : h.start;
    const sweep = g.key === "sweep" ? g.degrees : h.sweep;
    const r = Math.hypot(h.x - h.cx, h.y - h.cy) || 1;
    const rad = (d) => ((d - 90) * Math.PI) / 180;
    ctx.beginPath();
    ctx.arc(h.cx * s, h.cy * s, r * s, rad(start), rad(start + sweep), sweep < 0);
    ctx.stroke();
    ctx.setLineDash([2, 3]);
    ctx.beginPath();
    const end = g.key === "start_angle" ? start : start + sweep;
    ctx.moveTo(h.cx * s, h.cy * s);
    ctx.lineTo((h.cx + r * Math.sin((end * Math.PI) / 180)) * s, (h.cy - r * Math.cos((end * Math.PI) / 180)) * s);
    ctx.stroke();
  }
  if (g.guides) guides(ctx, g.guides, frame, s);
}

// What a gesture in progress sends on release, and what its preview draws.
function gestureAt(frame, item, g, x, y, free) {
  const s = frame.scale;
  const dx = x - g.x, dy = y - g.y;
  const targets = moveTargets(frame.items, item.id, frame.width, frame.height, frame.minor_radius,
                              free ? 0 : GRID_PERCENT);
  if (g.handle === null) {
    const snapped = free ? { dx: Math.round(dx), dy: Math.round(dy), guides: { x: [], y: [] } }
      : snapMove(item, dx, dy, targets, 4);
    return { kind: "move", part: "both", dx: snapped.dx, dy: snapped.dy, guides: snapped.guides };
  }
  const h = g.handle;
  if (h.kind === "end") {
    const point = { box: [h.x, h.y, 0, 0], center: [h.x, h.y] };
    const snapped = free ? { dx: Math.round(dx), dy: Math.round(dy), guides: { x: [], y: [] } }
      : snapMove(point, dx, dy, targets, 4);
    return { kind: "move", part: h.part, dx: snapped.dx, dy: snapped.dy, guides: snapped.guides };
  }
  if (h.kind === "size") {
    if (h.key[0] === "radius") {
      const r0 = h.x - item.center[0];
      const to = free ? Math.round(r0 + dx) : snapLength(r0 + dx, frame.minor_radius, GRID_PERCENT);
      return { kind: "resize", key: h.key, delta: to - r0, to, handle: h };
    }
    let delta = resizeDelta(h, dx, dy);
    if (!free) {
      const extent = h.axis === "x" ? item.box[2] : item.box[3];
      delta = snapLength(extent + delta, frame.minor_radius, GRID_PERCENT) - extent;
    }
    return { kind: "resize", key: h.key, delta, handle: h };
  }
  // an arc's end: its angle about the centre
  let degrees = angleAt(h.cx, h.cy, x, y);
  if (!free) degrees = snapAngle(degrees);
  if (h.key === "sweep") degrees = nearestTurn(degrees - h.start, h.sweep);
  else degrees = nearestTurn(degrees, h.start);
  return { kind: "turn", key: h.key, degrees, handle: h };
}

function changed(gesture) {
  if (gesture.kind === "move") return gesture.dx !== 0 || gesture.dy !== 0;
  if (gesture.kind === "resize") return gesture.delta !== 0;
  return Math.abs(gesture.degrees - (gesture.key === "sweep" ? gesture.handle.sweep : gesture.handle.start)) >= 0.5;
}

export function Canvas({ frame, layers, selected, onPick, onDrag }) {
  const overlay = useRef(null);
  const [drag, setDragState] = useState(null);     // a press, maybe a gesture
  // The handlers read the press from a ref: two pointer events can arrive
  // before the re-render the first one scheduled.
  const dragRef = useRef(null);
  const setDrag = (value) => { dragRef.current = value; setDragState(value); };
  const [pending, setPending] = useState(null);    // a gesture sent, not yet drawn
  const usable = layers && layers.version === frame.version ? layers.layers : null;

  useEffect(() => { if (usable) usable.forEach(layerImage); }, [usable]);
  // the new frame replaces a sent gesture's preview
  useEffect(() => { if (pending && frame.version !== pending.version) setPending(null); }, [frame.version]);

  const item = frame.items.find((i) => i.id === selected);
  const shown = drag && drag.gesture ? drag.gesture : pending ? pending.gesture : null;

  useEffect(() => {
    const c = overlay.current;
    if (!c) return;
    const s = frame.scale;
    c.width = frame.width * s; c.height = frame.height * s;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, c.width, c.height);
    if (!item) return;
    if (shown) { drawPreview(ctx, frame, usable, item, shown, s); return; }
    const [x, y, w, h] = item.box;
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = ACCENT;
    ctx.lineWidth = 2;
    ctx.strokeRect(x * s - 1, y * s - 1, w * s + 2, h * s + 2);
    for (const hd of item.handles) drawHandle(ctx, hd.x, hd.y, s);
  }, [frame, usable, selected, shown]);

  const point = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const k = (frame.width * frame.scale) / (rect.width || frame.width * frame.scale);
    return { x: ((e.clientX - rect.left) * k) / frame.scale, y: ((e.clientY - rect.top) * k) / frame.scale,
             sx: e.clientX, sy: e.clientY };
  };

  const down = (e) => {
    if (e.button !== 0 || pending) return;
    const p = point(e);
    const near = (h) => Math.abs((h.x - p.x) * frame.scale) <= HANDLE + 2 && Math.abs((h.y - p.y) * frame.scale) <= HANDLE + 2;
    const handle = item ? item.handles.find(near) : null;
    let id = selected;
    if (!handle) {
      id = pick(frame, usable, p.x, p.y, frame.scale);
      if (id !== selected) onPick(id);
    }
    if (!id) return;
    e.currentTarget.setPointerCapture && e.currentTarget.setPointerCapture(e.pointerId);
    setDrag({ id, handle: handle || null, x: p.x, y: p.y, sx: p.sx, sy: p.sy, gesture: null });
  };

  const move = (e) => {
    const drag = dragRef.current;
    if (!drag) return;
    if (!drag.gesture && Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) < START) return;
    const target = frame.items.find((i) => i.id === drag.id);
    if (!target) return;
    const p = point(e);
    setDrag({ ...drag, gesture: gestureAt(frame, target, drag, p.x, p.y, e.altKey) });
  };

  const up = () => {
    const drag = dragRef.current;
    if (!drag) return;
    const g = drag.gesture;
    setDrag(null);
    if (!g || !changed(g)) return;
    const { handle, guides: _g, to: _t, ...send } = g;
    setPending({ gesture: g, version: frame.version });
    Promise.resolve(onDrag(drag.id, send)).then((ok) => { if (!ok) setPending(null); });
  };

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") setDrag(null); };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);

  return html`<div class="canvas">
    <img src=${frame.frame} width=${frame.width * frame.scale} height=${frame.height * frame.scale}
         alt="the face on ${frame.device}" />
    <canvas ref=${overlay}></canvas>
    <div class=${"hit" + (drag && drag.gesture ? " dragging" : "")}
         onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${() => setDrag(null)}></div>
    ${pending ? html`<div class="saving">saving…</div>` : null}
  </div>`;
}

// One small frame per target, the selected device marked; a click views it.
export function Strip({ doc, view, onDevice }) {
  if (doc.targets.length < 2) return null;
  const q = (device) => {
    const p = new URLSearchParams({ device, v: doc.version });
    if (view.style) p.set("style", view.style);
    if (view.time) p.set("time", view.time);
    if (view.asleep) p.set("asleep", "1");
    if (view.aod) p.set("aod", "1");
    return `/api/documents/${doc.id}/thumbnail?${p}`;
  };
  return html`<div class="strip">
    ${doc.targets.map((t) => html`<button class=${t === view.device ? "on" : ""} title=${t} onClick=${() => onDevice(t)}>
      <img src=${q(t)} alt=${t} loading="lazy" /><span>${t}</span></button>`)}
  </div>`;
}
