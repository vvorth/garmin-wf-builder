// The gestures on their way to the server: pure functions, no DOM, so
// Node can check them (tests/test_studio_frontend.py).
//
// The editor sends one gesture at a time, each against the version the
// last one produced, and keeps the rest in order behind it, so the canvas
// takes the next press while the server is still writing the last. An
// entry is `{ids, gesture, preview, item, moving, where, state, done}`:
// `gesture` is what is sent, `preview` the same gesture with what the
// canvas draws it from; `where` the device and scope it is written for; `item` the dragged item and `moving` every element it moves (a
// group's children included); `state` is "queued", "sent" or "done", and
// `done` the version the server answered with. Until a frame of that
// version arrives, the canvas still draws the entry itself.

const isMove = (g) => g.kind === "move" && (g.part || "both") === "both";
const sameIds = (a, b) => a.length === b.length && a.every((id, i) => id === b[i]);
const sameWhere = (a, b) => JSON.stringify(a || {}) === JSON.stringify(b || {});

// `queue` with `entry` added at the end. A move of the same elements, for
// the same device and scope, as the last entry while that one is still
// queued folds into it: a held arrow key is not one request per repeat.
export function enqueue(queue, entry) {
  const last = queue[queue.length - 1];
  const added = { ...entry, state: "queued", done: null };
  if (last && last.state === "queued" && isMove(last.gesture) && isMove(entry.gesture)
      && sameIds(last.ids, entry.ids) && sameWhere(last.where, entry.where)) {
    const sum = (g) => ({ ...g, dx: g.dx + entry.gesture.dx, dy: g.dy + entry.gesture.dy });
    const { guides: _guides, ...preview } = last.preview;
    return [...queue.slice(0, -1), { ...last, gesture: sum(last.gesture), preview: sum(preview) }];
  }
  return [...queue, added];
}

// The first queued entry, to send next, or null while one is on its way.
export function next(queue) {
  if (queue.some((e) => e.state === "sent")) return null;
  return queue.find((e) => e.state === "queued") || null;
}

// `queue` with `entry` marked: "sent", or "done" at `version`.
export function mark(queue, entry, state, version = null) {
  return queue.map((e) => (e === entry ? { ...e, state, done: version } : e));
}

// The entries a frame of `version` does not show yet.
export function unshown(queue, version) {
  return queue.filter((e) => e.state !== "done" || e.done > version);
}

// How far each element of `entries` still has to move, as a Map from
// element id to [dx, dy]; null when one of them is not a move, which the
// canvas can only draw as its outline.
export function offsets(entries) {
  const out = new Map();
  for (const e of entries) {
    if (!isMove(e.gesture)) return null;
    for (const id of e.moving) {
      const [x, y] = out.get(id) || [0, 0];
      out.set(id, [x + e.gesture.dx, y + e.gesture.dy]);
    }
  }
  return out;
}

// `items` as they will be once `by` (offsets' Map) lands: each moved
// item's box, centre and handles shifted.
export function shiftItems(items, by) {
  if (!by || !by.size) return items;
  return items.map((item) => {
    const o = by.get(item.id);
    if (!o) return item;
    const [dx, dy] = o;
    const box = item.box ? [item.box[0] + dx, item.box[1] + dy, item.box[2], item.box[3]] : item.box;
    const center = item.center ? [item.center[0] + dx, item.center[1] + dy] : item.center;
    const handles = (item.handles || []).map((h) => ({
      ...h, x: h.x + dx, y: h.y + dy,
      ...(h.cx !== undefined ? { cx: h.cx + dx, cy: h.cy + dy } : {}),
    }));
    return { ...item, box, center, handles };
  });
}

// Whether the face's changes are saved, for the top bar: "unsaved" when
// the YAML tab holds text the server did not take (its `textsync.plan`
// kind is "held" or "wait"), "saving" while an edit's request, a gesture
// or the YAML tab's text is on its way, else "saved".
export function saveState({ inflight = 0, queue = [], yaml = "idle" }) {
  if (yaml === "held" || yaml === "wait") return "unsaved";
  if (inflight > 0 || yaml === "send" || queue.some((e) => e.state !== "done")) return "saving";
  return "saved";
}
