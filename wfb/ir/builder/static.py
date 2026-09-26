"""`static:` subtrees: marking, checking and ranking the elements drawn
once into a buffer."""

from __future__ import annotations


from ... import kinds

from ..model import Element, PatternElement, authored_draw_order, walk_elements
from .state import and_paths
from .aod import AodPass


class StaticPass(AodPass):
    """`static:` marking and its checks."""

    # -- static subtrees ---------------------------------------------------

    def _apply_static(self, elements: list[Element]) -> None:
        """Mark, then check, every `static: true` subtree.

        A static subtree is drawn once into an offscreen ``BufferedBitmap`` and
        blitted every frame afterwards.  The buffer is **opaque and
        full-screen**, because transparency could not be established from the
        SDK and cannot be observed in this container -- the whole argument is in
        `docs/research/probes/static-buffer/`.  Everything checked here follows
        from that one decision plus "the buffer is filled exactly once":

        * a binding would make the content change, and the buffer would not;
        * `low_power` would charge the blit against the partial-update budget by
          clip *area* (CLAUDE.md constraint 4), which is the whole screen here;
        * a nested `static:` is a second buffer for content the outer one
          already draws;
        * mixed `modes:` inside one buffer would blit elements into a mode they
          asked not to be drawn in.

        Every one of these is an error rather than a warning: each is a design
        that would compile and then be silently wrong on the wrist, which is the
        failure mode this compiler exists to remove.

        The one restriction that is *not* an error any more is draw order.  An
        opaque blit erases whatever is under it, so static content has to come
        first -- but "has to come first" is something the compiler can simply
        arrange, and now does: :func:`draw_sort_key` hoists it, and the author
        hears about it only where the hoist can change the picture
        (`warning[static-overlap]`, `wfb.lint.check_static_overlap`).  Ranking
        the roots here is the whole of what the hoist needs from this pass.
        """
        roots = [e for e in walk_elements(elements) if e.static]
        if not roots:
            return
        for root in roots:
            self._mark_static(root, root)
        self._rank_static(elements, roots)
        self._check_static_subtrees(roots)

    def _mark_static(self, root: Element, element: Element) -> None:
        if element is not root and element.static:
            self.bag.error(
                "static",
                f"{element.id!r} declares `static: true` inside the static "
                f"subtree of {root.id!r}",
                element.span,
                notes=[f"{root.id!r} already draws it into the same buffer",
                       "delete the inner `static: true`"],
            )
            return
        element.static_root = root.id
        for child in element.children():
            self._mark_static(root, child)

    def _check_static_subtrees(self, roots: list[Element]) -> None:
        """A kind whose own `static_forbidden` attribute is set (`graph`,
        `complication_slot`, `hands`) reads its picture from something that
        is not an `Expression` at all -- a series, a wearer's runtime pick,
        the clock -- so the generic "nothing here may read a data source"
        sweep below would never catch any of them on its own."""
        for root in roots:
            for element in walk_elements([root]):
                forbidden = kinds.for_element(element).static_forbidden
                if forbidden is not None:
                    phrase, note = forbidden
                    self.bag.error(
                        "static",
                        f"{element.id!r} is {phrase} and cannot be static",
                        element.span,
                        notes=[note,
                               f"take it out of {root.id!r}"
                               if element is not root else
                               "drop `static: true` from it"],
                    )
                    continue
                for expression in element.expressions():
                    if not expression.sources:
                        continue
                    is_part_visible = (
                        isinstance(element, PatternElement)
                        and any(expression is p.visible for p in element.parts)
                    )
                    where = ("visible" if expression is element.visible or is_part_visible
                             else "a value")
                    self.bag.error(
                        "static",
                        f"{element.id!r} binds {where} to "
                        f"{and_paths(expression.sources)} inside the static "
                        f"subtree of {root.id!r}",
                        expression.span or element.span,
                        notes=["a static subtree is drawn once, into a buffer "
                               "that is never refilled -- a reading bound here "
                               "would freeze at whatever it was on the first "
                               "frame",
                               "move this element out of the static group, or "
                               "replace the binding with a constant"],
                    )
                if "low_power" in element.modes:
                    self.bag.error(
                        "static",
                        f"{element.id!r} is static and declares "
                        "`modes: [... low_power ...]`",
                        element.span,
                        notes=["onPartialUpdate is charged by clip *area*, and "
                               "the buffer is the whole screen -- one blit a "
                               "second would spend the power budget, which is "
                               "disabled permanently once exceeded",
                               "`active` is fine -- and 'aod:' governs the AMOLED "
                               "sleep frame independently of `modes:`"],
                    )

    def _rank_static(self, elements: list[Element], roots: list[Element]) -> None:
        """Number the static roots by where the author's own draw order put them.

        Each root's rank is the authored draw-order position of its
        first-drawn member, and every element of the subtree carries it.
        :func:`draw_sort_key` then hoists the static content as a block,
        keeping each root's members contiguous and the roots in the order the
        author put them -- rather than in document order, which a `z:` on one
        of the roots may well have overruled.
        """
        position = {id(e): i for i, e in enumerate(authored_draw_order(elements))}
        for root in roots:
            members = [e for e in walk_elements([root]) if e.kind != "group"]
            rank = min((position[id(e)] for e in members if id(e) in position),
                       default=len(position))
            for element in walk_elements([root]):
                element.static_rank = rank
