"""`visible:`: an element's own condition, conjoined with every
enclosing group's."""

from __future__ import annotations

from typing import Any

from ... import expr
from ...catalog import Type

from ..model import Element, Expression, Group
from .glyphs import GlyphHelpers


class VisibilityHelpers(GlyphHelpers):
    """`visible:` reading and the group stack it is conjoined with."""

    def _visible(self, node: dict[str, Any]) -> Expression | None:
        """Compile and type-check `visible:`.

        The one requirement beyond a normal expression is the static type: a
        gate that is not a boolean is a mistake the author wants named, not a
        truthiness rule invented on their behalf (Monkey C has no truthy
        Number, so `visible: activity.steps` would not even compile).

        Deliberately no `when_absent:` companion.  `when_absent:` chooses a
        substitute *value*; there is no substitute for existence, so a
        nullable source here means exactly one thing -- absent is hidden --
        and the emitter folds the null check into the same guard as the
        condition.

        Reused verbatim for a `type: pattern` part's own `visible:`, with
        `copy` bound in scope -- but there "absent is hidden" means the whole
        *pattern* is hidden, not just this part:
        `wfb.kinds.pattern._check_pattern_absence`
        governs that, not this method, because the reading is taken once per
        frame, before the loop, so its absence is not a per-copy fact.
        """
        expression = self.expression(node, "visible")
        if expression is None:
            return None
        if expression.value.type is not Type.BOOLEAN:
            self.bag.error(
                "type",
                f"visible must be a boolean, got {expression.value}",
                expression.span,
                notes=["write a condition: a comparison ('activity.steps > 0'), "
                       "'and'/'or'/'not', or a '?:' whose branches are booleans",
                       "there is no truthiness rule -- a Number is not a condition"],
            )
            return None
        return expression

    def _conjoin_visible(
        self, outer: Expression | None, inner: Expression | None,
    ) -> Expression | None:
        """``outer and inner`` as one real :class:`Expression`; either may be
        absent (`_make_aod_override` conjoins an optional `aod: visible:`).

        This is how a group gates its subtree.  A `group` emits no draw method
        of its own (`wfb.emit.monkeyc` skips `kind == "group"`) and
        `wfb.layout` flattens the tree, so by the time anything downstream sees
        the design there is no subtree left to gate -- the conjunction has to
        happen here, while the parent still owns its children.

        Building a genuine `Expression` rather than splicing code strings is
        what makes every consumer work unchanged: `ReadPlan` hoists the
        group's readers and null-checks its locals because `sources` names
        them, `wfb.preview.evaluate` walks the merged `ast`, and the linter's
        constant folding sees through the whole conjunction.  Nested groups
        compose because the inner group has already conjoined its own
        condition into its children before the outer one runs.
        """
        if outer is None:
            return inner
        if inner is None:
            return outer
        assert outer.ast is not None and inner.ast is not None  # compiled, so both kept
        combined = expr.Binary("and", outer.ast, inner.ast)
        try:
            value = expr.check(combined, self.scope)
            folded = expr.fold(combined, self.scope, fold_colors=False)
            code = expr.emit(folded, self.scope)
        except expr.ExprError as exc:  # unreachable: both halves already checked
            self.bag.error(exc.code or "expression", f"visible: {exc.message}",
                           inner.span or outer.span, notes=exc.notes)
            return inner
        constant = folded.value if isinstance(folded, expr.Literal) else None
        return Expression(
            # Parenthesised: this text is what diagnostics and the generated
            # doc comment show, and `a or b and c` read back flat would claim
            # a precedence the emitted code (correctly) does not have.
            text=f"({outer.text}) and ({inner.text})",
            code=code,
            value=value,
            sources=tuple(sorted(set(outer.sources) | set(inner.sources))),
            barrel=outer.barrel | inner.barrel,
            modules=outer.modules | inner.modules,
            # The child's own line where it has one: that is where an author
            # reading a `dead-element` warning expects to look first.
            span=inner.span or outer.span,
            constant=constant,
            ast=folded,
        )

    def push_visible(self, group: "Group") -> None:
        """Conjoin a group's `visible:` into every element beneath it.

        Every *descendant*, not just the direct children: an inner group has
        already pushed its own condition down by the time the outer group is
        built, so touching only the inner `Group` object would leave the
        grandchildren ungated.  Pushing into the inner group as well keeps its
        own record honest -- it is what `dead-element` reports against, and
        what `wfb preview` would consult if groups ever drew anything.
        """
        if group.visible is None:
            return

        def visit(items: list[Element]) -> None:
            for child in items:
                child.visible = self._conjoin_visible(group.visible, child.visible)
                visit(child.children())

        visit(group.items)
