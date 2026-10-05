// Outlined groups: which leaves an outlined `group`'s ring goes round, and
// how far each is dilated. Port of wfb/ir/rings.py.
//
// A group's ring is the union of its members' dilations, drawn just before
// the group's first member. A member's dilation includes its own ring and
// every outlined group between it and this one, so the width is the sum.
import { type Element, Group } from "./model.ts";

/** One outlined group, and every leaf it rings with its total width. */
export class RingGroup {
  readonly group: Group;
  /** `[leaf, width]` in authored order: the leaf's dilation for this group's pass, in px. */
  readonly members: readonly (readonly [Element, number])[];

  constructor(group: Group, members: readonly (readonly [Element, number])[]) {
    this.group = group;
    this.members = members;
  }

  get ids(): Set<string> {
    return new Set(this.members.map(([leaf]) => leaf.id));
  }

  widthOf(elementId: string): number {
    return this.members.find(([leaf]) => leaf.id === elementId)![1];
  }
}

/** Every outlined group under `elements`, outermost first. */
export function ringGroups(elements: readonly Element[]): RingGroup[] {
  const out: RingGroup[] = [];
  const walk = (element: Element): void => {
    if (element instanceof Group) {
      if (element.outline !== null) out.push(new RingGroup(element, [...leaves(element, element.outline.width)]));
      for (const child of element.items) walk(child);
    }
  };
  for (const element of elements) walk(element);
  return out;
}

function* leaves(group: Group, width: number): Generator<[Element, number]> {
  for (const child of group.items) {
    const own = child.outline !== null ? child.outline.width : 0;
    if (child instanceof Group) yield* leaves(child, width + own);
    else yield [child, width + own];
  }
}
