// `visible:`: an element's own condition, conjoined with every enclosing
// group's. Port of wfb/ir/builder/visibility.py.
import * as expr from "../../expr.ts";
import { type Element, Expression, type Group } from "../model.ts";
import { GlyphHelpers } from "./glyphs.ts";
import type { Node } from "./state.ts";

/** `visible:` reading and the group stack it is conjoined with. */
export class VisibilityHelpers extends GlyphHelpers {
  /**
   * `visible:` compiled and type-checked: a gate that is not a boolean is a
   * mistake, not a truthiness rule. No `absent:` companion: a nullable
   * source here means hidden.
   */
  visibleOf(node: Node): Expression | null {
    const expression = this.expression(node, "visible");
    if (expression === null) return null;
    if (expression.value.type !== "boolean") {
      this.bag.error("type", `visible must be a boolean, got ${expression.value}`, expression.span, {
        notes: ["write a condition: a comparison ('activity.steps > 0'), "
          + "'and'/'or'/'not', or a '?:' whose branches are booleans",
          "there is no truthiness rule -- a Number is not a condition"],
      });
      return null;
    }
    return expression;
  }

  /** `outer and inner` as one real expression; either may be absent. */
  conjoinVisible(outer: Expression | null, inner: Expression | null): Expression | null {
    if (outer === null) return inner;
    if (inner === null) return outer;
    const combined: expr.Node = { kind: "binary", op: "and", left: outer.ast!, right: inner.ast!, offset: 0 };
    let value: expr.Value, folded: expr.Node, code: string;
    try {
      value = expr.check(combined, this.scope);
      folded = expr.fold(combined, this.scope, false);
      code = expr.emit(folded, this.scope);
    } catch (error) {
      if (!(error instanceof expr.ExprError)) throw error;
      // Unreachable: both halves already checked.
      this.bag.error(error.code ?? "expression", `visible: ${error.message}`, inner.span ?? outer.span, { notes: error.notes });
      return inner;
    }
    return Expression.create({
      // Parenthesised, so a reader of the text sees the precedence the emitted code has.
      text: `(${outer.text}) and (${inner.text})`,
      code,
      value,
      sources: [...new Set([...outer.sources, ...inner.sources])].sort(),
      barrel: new Set([...outer.barrel, ...inner.barrel]),
      modules: new Set([...outer.modules, ...inner.modules]),
      // The child's own line where it has one: where a `dead-element` reader looks first.
      span: inner.span ?? outer.span,
      constant: folded.kind === "literal" ? folded.value : null,
      ast: folded,
    });
  }

  /** Conjoin a group's `visible:` into every element beneath it, nested groups included. */
  pushVisible(group: Group): void {
    if (group.visible === null) return;
    const visit = (items: Element[]): void => {
      for (const child of items) {
        child.visible = this.conjoinVisible(group.visible, child.visible);
        visit(child.children());
      }
    };
    visit(group.items);
  }
}
