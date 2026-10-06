// Which elements a frame draws: one answer for the generated view, its read
// plan and the preview.
//
// The awake and low-power frames draw an element whose `modes` name them;
// the always-on frame draws every element whose resolved `aod:` is set. A
// group draws nothing itself. The Styles layout switch is a separate
// question (`inLayout`).
import type { Placed } from "../layout.ts";

/** The elements of `items` that `frame` draws, in their order. */
export function frameMembers(items: readonly Placed[], frame: string): Placed[] {
  if (frame === "aod") return items.filter((p) => p.kind !== "group" && p.element.aod !== null);
  return items.filter((p) => p.kind !== "group" && p.element.modes.includes(frame));
}

/** Whether `placed` draws while `layout` is the active Styles layout. */
export function inLayout(placed: Placed, layout: string | null): boolean {
  return placed.element.layout === null || placed.element.layout === layout;
}
