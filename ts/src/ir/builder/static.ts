// `static:` subtrees: marking, checking and ranking the elements drawn once
// into a buffer. Port of wfb/ir/builder/static.py.
import * as kinds from "../../kinds/index.ts";
import { repr } from "../../py.ts";
import { authoredDrawOrder, type Element, PatternElement, walkElements } from "../model.ts";
import { AodPass } from "./aod.ts";
import { andPaths } from "./state.ts";

/** How a diagnostic names a static subtree's root: the `static:` block by its key, anything else by id. */
function rootName(root: Element): string {
  if (root.id === "static") return "the 'static:' block";
  if (root.id.startsWith("layout_") && root.id.endsWith("_static")) {
    return `layout ${repr(root.id.slice("layout_".length, -"_static".length))}'s 'static:' block`;
  }
  return repr(root.id);
}

/** `static:` marking and its checks. */
export class StaticPass extends AodPass {
  /** Mark, rank, then check every `static: true` subtree (drawn once into an opaque full-screen buffer). */
  applyStatic(elements: Element[]): void {
    const roots = walkElements(elements).filter((e) => e.static);
    if (roots.length === 0) return;
    for (const root of roots) this.markStatic(root, root);
    this.rankStatic(elements, roots);
    this.checkStaticSubtrees(roots);
  }

  private markStatic(root: Element, element: Element): void {
    if (element !== root && element.static) {
      this.bag.error("static", `${repr(element.id)} is static inside the static subtree of ${rootName(root)}`, element.span, {
        notes: [`${rootName(root)} already draws it into the same buffer`, "delete the inner `static: true`"],
      });
      return;
    }
    element.static_root = root.id;
    for (const child of element.children()) this.markStatic(root, child);
  }

  private checkStaticSubtrees(roots: Element[]): void {
    for (const root of roots) {
      for (const element of walkElements([root])) {
        const forbidden = kinds.forElement(element).staticForbidden;
        if (forbidden !== null) {
          const [phrase, note] = forbidden;
          this.bag.error("static", `${repr(element.id)} is ${phrase} and cannot be static`, element.span, {
            notes: [note, element !== root ? `take it out of ${rootName(root)}` : "move it out of the 'static:' block"],
          });
          continue;
        }
        for (const expression of element.expressions()) {
          if (expression.sources.length === 0) continue;
          const isPartVisible = element instanceof PatternElement && element.parts.some((p) => expression === p.visible);
          const where = expression === element.visible || isPartVisible ? "visible" : "a value";
          this.bag.error("static", `${repr(element.id)} binds ${where} to ${andPaths(expression.sources)} inside the static `
            + `subtree of ${repr(root.id)}`, expression.span ?? element.span, {
            notes: ["a static subtree is drawn once, into a buffer "
              + "that is never refilled -- a reading bound here "
              + "would freeze at whatever it was on the first frame",
            "move this element out of the static group, or replace the binding with a constant"],
          });
        }
        if (element.modes.includes("low_power")) {
          this.bag.error("static", `${repr(element.id)} is static and declares 'sleep_update: true'`, element.span, {
            notes: ["onPartialUpdate is charged by clip *area*, and "
              + "the buffer is the whole screen -- one blit a "
              + "second would spend the power budget, which is "
              + "disabled permanently once exceeded",
            "the once-a-minute sleeping update is fine -- and "
              + "'aod:' governs the AMOLED sleep frame independently"],
          });
        }
      }
    }
  }

  /** Number the static roots by where the author's own draw order put them. */
  private rankStatic(elements: Element[], roots: Element[]): void {
    const order = authoredDrawOrder(elements);
    const position = new Map(order.map((e, i) => [e, i]));
    for (const root of roots) {
      const members = walkElements([root]).filter((e) => e.kind !== "group");
      const ranks = members.filter((e) => position.has(e)).map((e) => position.get(e)!);
      const rank = ranks.length > 0 ? Math.min(...ranks) : position.size;
      for (const element of walkElements([root])) element.static_rank = rank;
    }
  }
}
