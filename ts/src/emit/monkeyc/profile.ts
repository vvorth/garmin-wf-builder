// `wfb build --profile`: draw-time instrumentation for the active frame.
// Port of wfb/emit/monkeyc/profile.py.
//
// Each frame times one entry, drawn `reps` times in a row, and accumulates
// the milliseconds and the repetitions across frames; the average per call
// sharpens the longer the face runs. An entry is every element drawn in the
// active frame, one per outlined group's ring pass, and a `(loop)` baseline.
import type { Face } from "../../ir/model.ts";
import { elementMethodName, elementRingMethod } from "../../ir/naming.ts";
import { type RingGroup, ringGroups } from "../../ir/rings.ts";
import type { Placed, ResolvedFace } from "../../layout.ts";
import { IntBox } from "../../units.ts";

export const DEFAULT_REPS = 10;
export const NEXT = "_profNext";
export const MS = "_profMs";
export const REPS = "_profReps";
export const FRAME = "_profFrame";

/** One timed thing: an element's draw call, a group's ring pass, or the empty-loop baseline. */
export interface Entry {
  label: string;
  placed: Placed | null;
  /** `face.layouts` index, or -1 for shared content. */
  layout: number;
  /** A ring pass's `ring<Id>` methods, one per member. */
  members: string[];
}

export class ProfilePlan {
  readonly reps: number;
  readonly entries: Entry[];
  readonly layouts: boolean;

  constructor(reps: number, entries: Entry[], layouts: boolean) {
    this.reps = reps;
    this.entries = entries;
    this.layouts = layouts;
  }

  index(label: string): number {
    return this.entries.findIndex((entry) => entry.label === label);
  }
}

/** The entries of the active frame, in draw order. */
export function plan(resolved: ResolvedFace, rings: readonly RingGroup[], reps: number): ProfilePlan {
  const face = resolved.face;
  const byId = new Map(resolved.items.map((p) => [p.id, p]));
  const layoutIndex = (placed: Placed): number => (placed.element.layout !== null ? face.layouts.indexOf(placed.element.layout) : -1);
  const drawn = resolved.items.filter((p) => p.kind !== "group" && p.element.modes.includes("active"));
  const entries: Entry[] = [{ label: "(loop)", placed: null, layout: -1, members: [] }];
  const started = new Set<string>();
  for (const placed of drawn) {
    for (const ring of rings) {
      const members = drawn.filter((p) => ring.ids.has(p.id));
      if (members.length > 0 && members[0] === placed && !started.has(ring.group.id)) {
        started.add(ring.group.id);
        entries.push({
          label: `${ring.group.id}.ring`, placed: byId.get(ring.group.id)!, layout: layoutIndex(members[0]!),
          members: members.map((p) => elementRingMethod(p.id, ring.widthOf(p.id))),
        });
      }
    }
    entries.push({ label: placed.id, placed, layout: layoutIndex(placed), members: [] });
  }
  return new ProfilePlan(reps, entries, face.layouts.length > 0);
}

/** Each entry's code size in bytes, and each layout's total. */
export function codeReport(profile: ProfilePlan, face: Face, sizes: ReadonlyMap<string, number>): string[] {
  const view = `${face.entry}View`;
  const lines = [`${"entry".padEnd(28)} ${"code".padStart(7)}`];
  const perLayout = new Map<number, number>();
  for (const entry of profile.entries.slice(1)) {
    const size = entry.members.length > 0
      ? entry.members.reduce((s, method) => s + (sizes.get(`${view}.${method}`) ?? 0), 0)
      : sizes.get(`${view}.${elementMethodName(entry.label)}`) ?? 0;
    perLayout.set(entry.layout, (perLayout.get(entry.layout) ?? 0) + size);
    lines.push(`${entry.label.padEnd(28)} ${String(size).padStart(6)} B`);
  }
  lines.push("");
  for (const [index, total] of [...perLayout].sort(([a], [b]) => a - b)) {
    const name = index < 0 ? "(shared)" : `layout ${face.layouts[index]}`;
    lines.push(`${name.padEnd(28)} ${String(total).padStart(6)} B`);
  }
  return lines;
}

export function planFor(resolved: ResolvedFace, reps: number): ProfilePlan {
  return plan(resolved, ringGroups(resolved.face.elements), reps);
}

/** Where an entry's reading is drawn: above its element's (or group's) own box. */
export function labelBox(entry: Entry): IntBox {
  return entry.placed === null ? new IntBox(0, 0, 0, 0) : entry.placed.innerBox;
}

/** This device's `Layout` constants for the overlay. */
export function layoutLines(resolved: ResolvedFace, profile: ProfilePlan): string[] {
  const device = resolved.device;
  const xs = profile.entries.map((e) => { const b = labelBox(e); return String(b.x + Math.floor(b.width / 2)); });
  const ys = profile.entries.map((e) => String(labelBox(e).y));
  const layouts = profile.entries.map((e) => String(e.layout)).join(", ");
  return [
    `const PROF_X as Array<Number> = [${xs.join(", ")}] as Array<Number>;`,
    `const PROF_Y as Array<Number> = [${ys.join(", ")}] as Array<Number>;`,
    `const PROF_LAYOUT as Array<Number> = [${layouts}] as Array<Number>;`,
    `const PROF_HEAD_X as Number = ${Math.floor(device.width / 2)};`,
    `const PROF_HEAD_Y as Number = ${Math.floor(device.height / 8)};`,
  ];
}
