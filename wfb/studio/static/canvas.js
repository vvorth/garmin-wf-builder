// The canvas: the face as the server drew it, selection, and the drag
// gestures. The frame arrives with its layers as JSON ops (`raster.js`
// draws them), so hit-testing reads where each layer leaves ink. During a
// move the whole face is drawn here from the layers' ops, the dragged ones
// translated; a resize, an angle or a line's end is drawn as an outline. On
// release one gesture goes to the server, which writes it in the author's
// units and answers with the new face, whose frame then replaces the
// preview. Nothing here decides where anything lands.

import { html, useEffect, useRef, useState } from "./vendor/preact-htm.module.js";
import { elementOf, moveHandle, movedBy, together, topmost } from "./hit.js";
import * as raster from "./raster.js";
import {
  angleAt, moveTargets, nearestTurn, resizeDelta, snapAngle, snapLength, snapMove,
} from "./snap.js";

const ACCENT = "#4f9cf9";
const GUIDE = "#f5c04a";
const GRID_PERCENT = 5;     // the %r grid a move and a length snap to
const HANDLE = 5;           // a handle's half size, screen pixels
const GRIP = 11;            // the move handle's radius, screen pixels
const START = 3;            // screen pixels before a press becomes a drag

// A fallback layer's PNG as RGBA bytes.
async function decodePng(src) {
  const img = new Image();
  img.src = src;
  await img.decode();
  const c = document.createElement("canvas");
  c.width = img.width; c.height = img.height;
  const ctx = c.getContext("2d");
  ctx.drawImage(img, 0, 0);
  const data = ctx.getImageData(0, 0, img.width, img.height);
  return { width: data.width, height: data.height, data: data.data };
}

// A frame's layers, ready to draw and hit-test: its tiles inflated, a
// fallback layer's image decoded. A JSON layer's ink is worked out the
// first time a press lands in its box (`inkAt`).
async function prepare(frame) {
  const tiles = await raster.inflateTiles(frame.tiles);
  const boxes = new Map(frame.items.map((i) => [i.id, i.box]));
  const layers = await Promise.all(frame.layers.map(async (l) => ({
    id: l.id, kind: l.kind, ops: l.ops || null, origin: l.origin || null,
    png: l.image ? await decodePng(l.image) : null,
    box: boxes.get(l.id) || null, ink: undefined,
  })));
  return { version: frame.version, tiles, layers };
}

// The layer's ink at device pixel (x, y), 0 or more. Layers come at the
// watch's native size.
function inkAt(frame, prepared, layer, x, y) {
  const px = Math.floor(x), py = Math.floor(y);
  if (layer.png) {
    if (!layer.origin) return 0;
    const ix = px - layer.origin[0], iy = py - layer.origin[1];
    if (ix < 0 || iy < 0 || ix >= layer.png.width || iy >= layer.png.height) return 0;
    return layer.png.data[(iy * layer.png.width + ix) * 4 + 3];
  }
  if (!layer.ops) return 0;
  if (layer.ink === undefined) {
    layer.ink = raster.inkOf(layer.ops, prepared.tiles, frame.width, frame.height, 1);
  }
  const b = layer.ink.box;
  if (!b || px < b[0] || py < b[1] || px >= b[2] || py >= b[3]) return 0;
  return layer.ink.mask[(py - b[1]) * (b[2] - b[0]) + (px - b[0])] ? 255 : 0;
}

// What is under device pixel (x, y): by the layers' ink when they are
// ready, else the smallest drawn box holding the point.
function pick(frame, prepared, x, y) {
  if (prepared) {
    const hit = topmost(prepared.layers, x, y, (layer) => inkAt(frame, prepared, layer, x, y));
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

// The face drawn from its layers, each JSON layer's ops passed through
// `change(layer)` and each fallback image shifted by `shift(layer)` frame
// pixels: what the server will draw once a gesture lands. Drawn at the
// watch's native size and enlarged `s` times without smoothing, as the
// server's frame is. Cleared to black inside the screen's own shape only,
// so the skin round a round screen stays visible.
function drawChanged(ctx, frame, prepared, change, shift, s) {
  const width = frame.width, height = frame.height;
  const im = raster.image(width, height, [0, 0, 0]);
  for (const l of prepared.layers) {
    if (l.ops) raster.drawOps(im, change(l), prepared.tiles, 1);
    else if (l.png && l.origin) {
      const [dx, dy] = shift(l);
      raster.composite(im, l.png, l.origin[0] + dx, l.origin[1] + dy);
    }
  }
  const scratch = document.createElement("canvas");
  scratch.width = width; scratch.height = height;
  scratch.getContext("2d").putImageData(new ImageData(im.data, width, height), 0, 0);
  ctx.save();
  if (frame.shape === "round") {
    ctx.beginPath();
    ctx.arc(width * s / 2, height * s / 2, Math.min(width, height) * s / 2, 0, Math.PI * 2);
    ctx.clip();
  }
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(scratch, 0, 0, width * s, height * s);
  ctx.restore();
}

// `k`: canvas pixels per screen pixel, so a handle is the same size on the
// screen at every zoom.
function drawHandle(ctx, x, y, s, k) {
  const r = HANDLE * k;
  ctx.setLineDash([]);
  ctx.fillStyle = "#fff";
  ctx.strokeStyle = ACCENT;
  ctx.lineWidth = 1.5 * k;
  ctx.fillRect(x * s - r, y * s - r, r * 2, r * 2);
  ctx.strokeRect(x * s - r, y * s - r, r * 2, r * 2);
}

// The move handle: a disc with four arrows, the same size at every zoom.
function drawGrip(ctx, x, y, s, k) {
  const cx = x * s, cy = y * s, r = GRIP * k, a = 3 * k, reach = r - 3 * k;
  ctx.setLineDash([]);
  ctx.fillStyle = "#fff";
  ctx.strokeStyle = ACCENT;
  ctx.lineWidth = 1.5 * k;
  ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
  ctx.beginPath();
  for (const [ux, uy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
    const tx = cx + ux * reach, ty = cy + uy * reach;
    ctx.moveTo(cx, cy); ctx.lineTo(tx, ty);
    ctx.moveTo(tx - ux * a + uy * a, ty - uy * a + ux * a); ctx.lineTo(tx, ty);
    ctx.lineTo(tx - ux * a - uy * a, ty - uy * a - ux * a);
  }
  ctx.stroke();
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

// The face with the elements in `moving` moved by (dx, dy) device pixels.
function drawMoved(ctx, frame, prepared, moving, dx, dy, s) {
  const moved = (l) => moving.has(elementOf(l.id));
  drawChanged(ctx, frame, prepared, (l) => (moved(l) ? raster.translateOps(l.ops, dx, dy) : l.ops),
              (l) => (moved(l) ? [dx, dy] : [0, 0]), s);
}

// The face with `item` drawn as a live handle (`handle.live`, which the
// server declares only where it predicts the edit exactly) leaves it.
function drawLive(ctx, frame, prepared, item, g, s) {
  const change = g.kind === "turn" ? { degrees: g.degrees } : { delta: g.delta };
  drawChanged(ctx, frame, prepared,
              (l) => (l.id === item.id ? raster.liveOps(l.ops, g.handle.live, change) : l.ops),
              () => [0, 0], s);
}

// The preview of a gesture in progress, or of one sent and not yet drawn.
// `moving`: every element the gesture moves (a group's children included).
function drawPreview(ctx, frame, prepared, item, moving, g, s) {
  ctx.setLineDash([6, 4]);
  ctx.strokeStyle = ACCENT;
  ctx.lineWidth = 2;
  if (g.kind !== "move" && g.handle && g.handle.live && prepared) {
    drawLive(ctx, frame, prepared, item, g, s);
  } else if (g.kind === "move" && g.part === "both") {
    if (prepared) drawMoved(ctx, frame, prepared, moving, g.dx, g.dy, s);
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
// `g.moving`: every element it moves, none of which is a snapping target.
function gestureAt(frame, item, g, x, y, free) {
  const dx = x - g.x, dy = y - g.y;
  const targets = moveTargets(frame.items, g.moving, frame.width, frame.height, frame.minor_radius,
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

// `zoom`: screen (CSS) pixels per watch pixel; the frame was drawn at
// `frame.scale` and is shown at the zoom. `skin`: the watch drawn round the
// screen, at the frame's scale, with where the screen sits in it.
// `selected` and `extra`: the selection, `extra` being the elements added
// to it with Ctrl/Cmd/Shift; `tree`: the face's blocks, for what a group
// carries. `onPick(id, additive)`; `onDrag(ids, gesture)`.
export function Canvas({ frame, selected, extra = [], tree = [], onPick, onDrag,
                         zoom = frame.scale, skin = null }) {
  const overlay = useRef(null);
  const [drag, setDragState] = useState(null);     // a press, maybe a gesture
  // The handlers read the press from a ref: two pointer events can arrive
  // before the re-render the first one scheduled.
  const dragRef = useRef(null);
  const setDrag = (value) => { dragRef.current = value; setDragState(value); };
  const [pending, setPending] = useState(null);    // a gesture sent, not yet drawn
  const [prepared, setPrepared] = useState(null);  // the frame's layers, ready
  const usable = prepared && prepared.version === frame.version ? prepared : null;

  useEffect(() => {
    let live = true;
    prepare(frame).then((p) => { if (live) setPrepared(p); }, () => {});
    return () => { live = false; };
  }, [frame]);
  // the new frame replaces a sent gesture's preview
  useEffect(() => { if (pending && frame.version !== pending.version) setPending(null); }, [frame.version]);

  const item = frame.items.find((i) => i.id === selected);
  const others = frame.items.filter((i) => extra.includes(i.id));
  const live = drag && drag.gesture ? drag : pending;

  useEffect(() => {
    const c = overlay.current;
    if (!c) return;
    const s = frame.scale;
    c.width = frame.width * s; c.height = frame.height * s;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, c.width, c.height);
    if (live) { drawPreview(ctx, frame, usable, live.item, live.moving, live.gesture, s); return; }
    if (!item) return;
    const k = s / zoom;
    ctx.setLineDash([6 * k, 4 * k]);
    ctx.strokeStyle = ACCENT;
    ctx.lineWidth = 2 * k;
    for (const one of [item, ...others]) {
      const [x, y, w, h] = one.box;
      ctx.strokeRect(x * s - k, y * s - k, w * s + 2 * k, h * s + 2 * k);
    }
    // handles act on one element, so a selection of several shows none
    if (!others.length) for (const hd of item.handles) drawHandle(ctx, hd.x, hd.y, s, k);
    const grip = moveHandle(frame.items, [selected, ...extra], (GRIP + 2) / zoom);
    if (grip) drawGrip(ctx, grip.x, grip.y, s, k);
  }, [frame, usable, selected, extra, live, zoom]);

  const point = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const k = (frame.width * frame.scale) / (rect.width || frame.width * frame.scale);
    return { x: ((e.clientX - rect.left) * k) / frame.scale, y: ((e.clientY - rect.top) * k) / frame.scale,
             sx: e.clientX, sy: e.clientY };
  };

  // A press on a handle drags it; on the move handle, the whole selection
  // (a group with its children); on an element that is itself selected,
  // the whole selection too, and if it turns out to be a click, just that
  // element. A press anywhere else, a selected group's member included,
  // selects what is under it and drags that. Ctrl/Cmd/Shift adds to the
  // selection.
  const down = (e) => {
    if (e.button !== 0 || pending) return;
    const p = point(e);
    const chosen = [selected, ...extra].filter(Boolean);
    const grip = moveHandle(frame.items, chosen, (GRIP + 2) / zoom);
    const onGrip = grip && Math.hypot((grip.x - p.x) * zoom, (grip.y - p.y) * zoom) <= GRIP + 2;
    const near = (h) => Math.abs((h.x - p.x) * zoom) <= HANDLE + 2 && Math.abs((h.y - p.y) * zoom) <= HANDLE + 2;
    const handle = !onGrip && item && !extra.length ? item.handles.find(near) : null;
    const under = handle || onGrip ? null : pick(frame, usable, p.x, p.y);
    if (!handle && !onGrip && (e.ctrlKey || e.metaKey || e.shiftKey)) {
      if (under) onPick(under, true);
      return;
    }
    let ids, click = null;
    if (handle) ids = [selected];
    else if (onGrip) ids = chosen;
    else if (under && chosen.includes(under)) {
      ids = chosen;
      click = under;
    } else {
      if (under !== selected || extra.length) onPick(under, false);
      if (!under) return;
      ids = [under];
    }
    e.currentTarget.setPointerCapture && e.currentTarget.setPointerCapture(e.pointerId);
    setDrag({ ids, moving: movedBy(tree, ids), click, handle: handle || null,
              x: p.x, y: p.y, sx: p.sx, sy: p.sy, gesture: null });
  };

  const move = (e) => {
    const drag = dragRef.current;
    if (!drag) return;
    if (!drag.gesture && Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) < START) return;
    const target = drag.ids.length > 1 ? together(frame.items, drag.ids)
      : frame.items.find((i) => i.id === drag.ids[0]);
    if (!target) return;
    const p = point(e);
    setDrag({ ...drag, item: target, gesture: gestureAt(frame, target, drag, p.x, p.y, e.altKey) });
  };

  const up = () => {
    const drag = dragRef.current;
    if (!drag) return;
    const g = drag.gesture;
    setDrag(null);
    if (!g) {
      // a click inside the selection: select what is under it
      if (drag.click && (drag.click !== selected || extra.length)) onPick(drag.click, false);
      return;
    }
    if (!changed(g)) return;
    const { handle, guides: _g, to: _t, ...send } = g;
    setPending({ gesture: g, item: drag.item, moving: drag.moving, version: frame.version });
    Promise.resolve(onDrag(drag.ids, send)).then((ok) => { if (!ok) setPending(null); });
  };

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") setDrag(null); };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);

  // the screen, and round it the skin when shown, all at the zoom
  const w = frame.width * zoom, h = frame.height * zoom;
  const at = skin ? [skin.x / skin.scale * zoom, skin.y / skin.scale * zoom] : [0, 0];
  const box = skin ? [skin.width / skin.scale * zoom, skin.height / skin.scale * zoom] : [w, h];
  const screen = `left:${at[0]}px;top:${at[1]}px;width:${w}px;height:${h}px`;
  return html`<div class="canvas" style=${`width:${box[0]}px;height:${box[1]}px`}>
    <img class="frame" src=${frame.frame} style=${screen} alt="the face on ${frame.device}" />
    ${skin ? html`<img class="skin" src=${skin.image} style=${`width:${box[0]}px;height:${box[1]}px`} alt="" />` : null}
    <canvas ref=${overlay} style=${screen}></canvas>
    <div class=${"hit" + (drag && drag.gesture ? " dragging" : "")} style=${screen}
         onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${() => setDrag(null)}></div>
    ${pending ? html`<div class="saving">saving…</div>` : null}
  </div>`;
}

// One small frame per target, the selected device marked; a click views it.
export function Strip({ doc, view, picks, onDevice }) {
  if (doc.targets.length < 2) return null;
  const q = (device) => {
    const p = new URLSearchParams({ device, v: doc.version });
    if (view.style) p.set("style", view.style);
    if (view.time) p.set("time", view.time);
    if (view.asleep) p.set("asleep", "1");
    if (view.aod) p.set("aod", "1");
    if (picks) p.set("picks", picks);
    return `/api/documents/${doc.id}/thumbnail?${p}`;
  };
  return html`<div class="strip">
    ${doc.targets.map((t) => html`<button class=${t === view.device ? "on" : ""} title=${t} onClick=${() => onDevice(t)}>
      <img src=${q(t)} alt=${t} loading="lazy" /><span>${t}</span></button>`)}
  </div>`;
}
