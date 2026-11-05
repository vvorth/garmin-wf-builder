// An element's id is its YAML key qualified by the ids of the groups it
// sits in, joined with `.`: `top.label` for `elements: top: children:
// label:`. The key, the element's *name*, need only be unique among its
// siblings (YAML itself refuses a duplicate key in one mapping); the
// qualified id is unique across the face by construction, and is what the
// IR, the lints, the editor's protocol and the generated Monkey C symbols
// (`drawTopLabel`, `TOP_LABEL_*`) all key on.
//
// The synthetic containers desugaring mints count as groups: the
// top-level `static:` block's elements are `static.<name>`, a layout's are
// `layout_<layout>.<name>` and `layout_<layout>_static.<name>`
// (`desugar.ts`). The compiler qualifies while it injects ids
// (`childElementId`); the editor qualifies from a YAML path
// (`elementIdOfPath`). The two must agree, so both live here.

/** Between a parent's id and a child's name. */
export const ID_SEPARATOR = ".";

/** The id of the element `name` directly under the element (or synthetic group) `parentId`; a top-level element's id is its name. */
export function childElementId(parentId: string | null, name: string): string {
  return parentId === null ? name : parentId + ID_SEPARATOR + name;
}

/** The YAML key an element was written under: the last step of its id. */
export function elementName(elementId: string): string {
  const at = elementId.lastIndexOf(ID_SEPARATOR);
  return at < 0 ? elementId : elementId.slice(at + 1);
}

/** The id of the group an element sits in, `null` for a top-level one (a synthetic container counts as a group). */
export function parentElementId(elementId: string): string | null {
  const at = elementId.lastIndexOf(ID_SEPARATOR);
  return at < 0 ? null : elementId.slice(0, at);
}

/** The id the top-level `static:` block's synthetic group is given; reserved at the top level. */
export const STATIC_GROUP_ID = "static";

/** The ids of the two synthetic groups a `layouts:` entry's `static:` and `elements:` become; reserved at the top level. */
export function layoutIds(name: string): [staticId: string, elementsId: string] {
  return [`layout_${name}_static`, `layout_${name}`];
}

/**
 * The id of the element at a YAML path of the authored document, before
 * desugaring: `["elements", "top", "children", "label"]` is `top.label`,
 * `["static", "ticks"]` is `static.ticks`, `["layouts", "roman", "elements",
 * "hour"]` is `layout_roman.hour` and `["layouts", "roman", "static",
 * "rim"]` is `layout_roman_static.rim`. `null` when the path is not an
 * element's (a part, a block, a field).
 */
export function elementIdOfPath(path: readonly (string | number)[]): string | null {
  const steps = path.map(String);
  let rest: string[];
  let parent: string | null;
  if (steps[0] === "elements") {
    rest = steps.slice(1);
    parent = null;
  } else if (steps[0] === "static") {
    rest = steps.slice(1);
    parent = STATIC_GROUP_ID;
  } else if (steps[0] === "layouts" && steps.length >= 4 && (steps[2] === "elements" || steps[2] === "static")) {
    const [staticId, elementsId] = layoutIds(steps[1]!);
    rest = steps.slice(3);
    parent = steps[2] === "static" ? staticId : elementsId;
  } else {
    return null;
  }
  if (rest.length === 0) return null;
  let id = childElementId(parent, rest[0]!);
  // below the first element, every further element sits under a group's `children:`
  for (let at = 1; at < rest.length; at += 2) {
    if (rest[at] !== "children" || at + 1 >= rest.length) return null;
    id = childElementId(id, rest[at + 1]!);
  }
  return id;
}
