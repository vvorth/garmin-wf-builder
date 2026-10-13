// The changes on their way to the worker: pure functions, no DOM, so
// Node can check them (test/page-modules.test.ts).
//
// The editor sends one change at a time, each against the version the
// last one produced, and keeps the rest in order behind it, so the canvas
// takes the next press while the worker is still writing the last, and an
// edit made meanwhile (the inspector, the layers, undo) waits its turn
// instead of being refused as stale. A gesture from the canvas or the
// arrow keys is a `GestureEntry`; any other change is a `RequestEntry`,
// `request` being what the editor sends (`app.ts`). A gesture's entry is:
// `gesture` is what is sent, `preview` the same gesture with what the
// canvas draws it from; `where` the device and scope it is written for;
// `item` the dragged item and `moving` every element it moves (a group's
// children included); `state` is "queued", "sent" or "done", and `done`
// the version the worker answered with. Until a frame of that version
// arrives, the canvas still draws the entry itself.

import type { FrameItem, Gesture, Handle, Op, Scope, Summary } from "../src/studio/protocol.ts";
import type { Placed } from "./hit.ts";
import type { PlanKind } from "./textsync.ts";

type MoveGesture = Extract<Gesture, { kind: "move" }>;

/** The guide lines a snapped move landed on, for drawing. */
export interface Guides {
  x: number[];
  y: number[];
}

/** A gesture as the canvas draws it: what is sent, plus the guides it snapped to, the handle dragged and a radius's new value. */
export type Preview = Gesture & { guides?: Guides; handle?: Handle; to?: number };

/** The device a gesture is written for, and the scope (`auto`: where that device reads the key). */
export interface Where {
  device?: string;
  scope?: "auto" | Scope;
}

export type EntryState = "queued" | "sent" | "done";

export interface GestureEntry {
  ids: string[];
  gesture: Gesture;
  preview: Preview;
  item: Placed;
  moving: Iterable<string>;
  where: Where;
  request?: undefined;
  resolve?: undefined;
  state: EntryState;
  /** The version the worker answered with, once done. */
  done: number | null;
}

/** Any other change: the request as `api` takes it (the face's id and version are added when sent), and who waits for its answer. */
export interface RequestEntry {
  request: { op: Op; args?: Record<string, unknown>; body?: Blob | Uint8Array | null };
  resolve?: (answer: Summary | null) => void;
  gesture?: undefined;
  state: EntryState;
  done: number | null;
}

export type Entry = GestureEntry | RequestEntry;

/** An entry as it is added: the queue gives it its state. */
export type NewEntry = Omit<GestureEntry, "state" | "done"> | Omit<RequestEntry, "state" | "done">;

const isMove = (g: Gesture | undefined): g is MoveGesture => !!g && g.kind === "move" && (g.part || "both") === "both";
/** A gesture entry whose gesture moves the whole element. */
type MoveEntry = GestureEntry & { gesture: MoveGesture };
const movesWhole = (e: Entry | NewEntry | undefined): e is MoveEntry => !!e && e.gesture !== undefined && isMove(e.gesture);
const sameIds = (a: readonly string[], b: readonly string[]): boolean => a.length === b.length && a.every((id, i) => id === b[i]);
const sameWhere = (a: Where | undefined, b: Where | undefined): boolean => JSON.stringify(a || {}) === JSON.stringify(b || {});

// `queue` with `entry` added at the end. A move of the same elements, for
// the same device and scope, as the last entry while that one is still
// queued folds into it: a held arrow key is not one request per repeat.
export function enqueue(queue: readonly Entry[], entry: NewEntry): Entry[] {
  const last = queue[queue.length - 1];
  const added: Entry = { ...entry, state: "queued", done: null };
  if (last && last.state === "queued" && movesWhole(last) && movesWhole(entry)
      && sameIds(last.ids, entry.ids) && sameWhere(last.where, entry.where)) {
    const { dx, dy } = entry.gesture;
    const sum = <G extends { dx: number; dy: number }>(g: G): G => ({ ...g, dx: g.dx + dx, dy: g.dy + dy });
    // a move's preview is the move itself, with the guides it snapped to
    const { guides: _guides, ...preview } = last.preview as MoveGesture & { guides?: Guides };
    return [...queue.slice(0, -1), { ...last, gesture: sum(last.gesture), preview: sum(preview) }];
  }
  return [...queue, added];
}

// The first queued entry, to send next, or null while one is on its way.
export function next(queue: readonly Entry[]): Entry | null {
  if (queue.some((e) => e.state === "sent")) return null;
  return queue.find((e) => e.state === "queued") || null;
}

// `queue` with `entry` marked: "sent", or "done" at `version`. A change
// that is not a gesture has nothing for the canvas to draw, so once done
// it leaves the queue.
export function mark(queue: readonly Entry[], entry: Entry | undefined, state: EntryState, version: number | null = null): Entry[] {
  return queue.flatMap((e) => {
    if (e !== entry) return [e];
    return state === "done" && !e.gesture ? [] : [{ ...e, state, done: version }];
  });
}

// The gestures a frame of `version` does not show yet.
export function unshown(queue: readonly Entry[], version: number): GestureEntry[] {
  return queue.filter((e): e is GestureEntry => e.gesture !== undefined && (e.state !== "done" || (e.done !== null && e.done > version)));
}

// How far each element of `entries` (gestures) still has to move, as a
// Map from element id to [dx, dy]; null when one of them is not a move,
// which the canvas can only draw as its outline.
export function offsets(entries: readonly GestureEntry[]): Map<string, [number, number]> | null {
  const out = new Map<string, [number, number]>();
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
export function shiftItems(items: readonly FrameItem[], by: ReadonlyMap<string, [number, number]> | null | undefined): FrameItem[] {
  if (!by || !by.size) return [...items];
  return items.map((item) => {
    const o = by.get(item.id);
    if (!o) return item;
    const [dx, dy] = o;
    const box: FrameItem["box"] = [item.box[0] + dx, item.box[1] + dy, item.box[2], item.box[3]];
    const center: FrameItem["center"] = [item.center[0] + dx, item.center[1] + dy];
    const handles = item.handles.map((h) => ({
      ...h, x: h.x + dx, y: h.y + dy,
      ...(h.cx !== undefined && h.cy !== undefined ? { cx: h.cx + dx, cy: h.cy + dy } : {}),
    }));
    return { ...item, box, center, handles };
  });
}

/** What the top bar's saved state is read from: requests in flight, the outbox and the YAML pane's plan. */
export interface SaveInputs {
  inflight?: number;
  queue?: readonly Entry[];
  yaml?: PlanKind | null;
}

// Whether the face's changes are saved, for the top bar: "unsaved" when
// the YAML tab holds text the worker did not take (its `textsync.plan`
// kind is "held" or "wait"), "saving" while a request, a change in the
// queue or the YAML tab's text is on its way, else "saved".
export function saveState({ inflight = 0, queue = [], yaml = "idle" }: SaveInputs): "unsaved" | "saving" | "saved" {
  if (yaml === "held" || yaml === "wait") return "unsaved";
  if (inflight > 0 || yaml === "send" || queue.some((e) => e.state !== "done")) return "saving";
  return "saved";
}

// Whether leaving the page now would lose a change: one queued or sent
// and not yet answered, or the YAML tab's text not yet taken ("saving").
// Text the worker refused ("unsaved") was answered: the page already
// shows it as not saved.
export function inFlight(state: SaveInputs): boolean {
  return saveState(state) === "saving";
}

// Whether `incoming`, a face from the worker, may replace `current`, the
// one shown: answers can arrive out of order, and an older face shown over
// a newer one would aim the next change at a version that is gone. Another
// face (a different id) always replaces it.
export function newer(current: Pick<Summary, "id" | "version"> | null | undefined, incoming: Pick<Summary, "id" | "version">): boolean {
  return !current || incoming.id !== current.id || incoming.version >= current.version;
}

/** An error as `api` throws it: the refusal's status, when it was one. */
export type Failure = Error & { status?: number | undefined };

// The error to show for a refused change, `error`, when `later` changes
// queued behind it were dropped with it: the same error, its status kept,
// its message saying so, since nothing else would.
export function droppedError(error: Failure, later: number): Failure {
  if (!(later > 0)) return error;
  return Object.assign(new Error(`${error.message} (${later} later change${later > 1 ? "s were" : " was"} not sent)`),
    { status: error.status });
}
