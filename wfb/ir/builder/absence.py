"""Null handling and `format:`: the platform makes absence normal
(constraint 8), so a nullable binding must say what to draw without it."""

from __future__ import annotations

from typing import Any

from ... import catalog, formatting
from ...catalog import Type
from ...diagnostics import Span

from ..model import Element, Expression, ROLE_VISIBLE
from .reading import Readers

#: Shared notes of every "can be absent, so 'when_absent:' is required" error.
ABSENCE_IS_NORMAL = ("every ActivityMonitor field is nullable and sensors are simply missing "
                     "on some devices, so absence is the normal case, not an error")
_WHEN_ABSENT_CHOICES = ("choose one of: hide | placeholder (with 'placeholder:') | fallback "
                        "(with 'fallback:')")


class AbsenceChecks(Readers):
    """`when_absent:` and `format:` checks for a bound value."""

    # -- shared checks ----------------------------------------------------

    def check_absence(self, node: dict[str, Any], element: Element, bound: Expression,
                      when_absent: str | None, placeholder: str | None,
                      fallback: Expression | None, key: str = "value") -> None:
        """ADR 0005 3: null handling is part of the binding, not an afterthought."""
        if not bound.nullable:
            # Only "no effect" if nothing *else* on the element is nullable
            # either: since `check_other_absence`, a nullable colour or max
            # requires a policy too, so a `when_absent:` sitting next to a
            # non-nullable value can be doing real work.  Saying it has no
            # effect there would contradict the error the author just fixed.
            # Every *other* bound expression, `visible:` excluded -- it has
            # its own "absent means hidden" rule with no `when_absent:` of
            # its own to speak of (plan 19 A2: read by role, not identity,
            # so this reads the same as the isinstance-free form below).
            others_nullable = any(
                expression is not bound and role != ROLE_VISIBLE and expression.nullable
                for role, expression in element.bound_expressions()
            )
            if when_absent is not None and not others_nullable:
                self.bag.note(
                    "when-absent",
                    f"{element.id}: 'when_absent' has no effect -- {bound.text} is never absent",
                    self.doc.span(node, "when_absent"),
                )
            return
        if when_absent is None:
            self.bag.error(
                "when-absent",
                f"{element.id}: {bound.text!r} can be absent, so 'when_absent:' is required",
                self.doc.span(node, key),
                notes=[
                    ABSENCE_IS_NORMAL,
                    _WHEN_ABSENT_CHOICES,
                ],
            )
            return
        if when_absent == "placeholder" and placeholder is None:
            self.require(node, "placeholder", "when_absent: placeholder needs a 'placeholder:' string")
        if when_absent == "fallback" and fallback is None:
            self.require(node, "fallback", "when_absent: fallback needs a 'fallback:' expression")
        if when_absent == "fallback" and fallback is not None and fallback.nullable:
            self.bag.error(
                "when-absent",
                f"{element.id}: the fallback expression can itself be absent",
                self.doc.span(node, "fallback"),
                notes=["a fallback must always produce a value"],
            )

    def check_other_absence(self, node: dict[str, Any], element: Element, key: str,
                            bound: Expression | None, span: Span | None = None) -> None:
        """A nullable binding outside `value` still needs an explicit `when_absent:`.

        `check_absence` above only ever runs for `value` -- without this
        check, a nullable `color`/`track_color` would sail through
        validation with no policy at all.  Codegen (`wfb.emit.monkeyc`'s
        `ReadPlan.other_guards`) always treats an absent non-value binding
        as 'hide', regardless of which policy is chosen for the value,
        because there is no sensible placeholder or fallback for a colour.
        The requirement here is only that the author has consciously picked
        *something*, the same ADR 0005 3 contract `value` already has -- not
        that the chosen policy's exact semantics (placeholder text, a
        substitute number) apply to a colour, which they do not.

        `span` overrides `self.doc.span(node, key)` -- needed for a binding
        that does not live at `node[key]` directly, such as `outline.color`
        (`key` is `'outline.color'` for the message, but the real YAML node
        is `outline:`'s own sub-mapping, or `node['outline']` itself under
        the shorthand spelling; `Builder.build_outline` works out which and
        passes the right span in).
        """
        if bound is None or not bound.nullable:
            return
        if getattr(element, "when_absent", None) is not None:
            return
        self.bag.error(
            "when-absent",
            f"{element.id}: {key!r} reads {bound.text!r}, which can be absent, so "
            "'when_absent:' is required",
            span if span is not None else self.doc.span(node, key),
            notes=[
                ABSENCE_IS_NORMAL,
                f"'when_absent:' is required once anything on this element is nullable, not "
                f"just 'value' -- a nullable {key} always hides the element when absent, "
                "regardless of which policy is chosen for the bound value",
                _WHEN_ABSENT_CHOICES,
            ],
        )

    def check_reachable_substitute(self, node: dict[str, Any], element: Element, key: str,
                                   value_bindings: tuple[Expression | None, ...],
                                   other_bindings: tuple[Expression | None, ...]) -> None:
        """Warn when a `placeholder:`/`fallback:` can never actually be drawn.

        A nullable non-value binding hides the whole element (see
        `check_other_absence`), and that guard runs *before* the value's own
        substitute.  So if every nullable source behind the value is also read
        by a colour or max, the element is already gone by the time the
        substitute would be chosen, and the author's `placeholder:` is dead
        text -- declared, accepted, and impossible to see.

        Not an error: the design still behaves sensibly (it hides), and the
        fix is a judgement call -- drop the substitute, or stop reading the
        same source from the colour.  But saying nothing here would be the
        very failure this compiler exists to prevent, one level down.

        `visible:` joins the "other" bindings here for exactly the same
        reason, and with a stronger claim behind it: absence in a visibility
        condition means hidden by definition, and that guard is emitted before
        everything else in the method.  A placeholder for a reading the
        element's own visibility already depends on is unreachable text.  The
        label only grows when the element actually has a `visible:`, so no
        existing message moves.
        """
        policy = getattr(element, "when_absent", None)
        if policy not in ("placeholder", "fallback"):
            return
        value_sources = self.nullable_sources(value_bindings)
        if not value_sources:
            return
        if element.visible is not None:
            other_bindings = other_bindings + (element.visible,)
            key = f"{key}/'visible'"
        other_sources = self.nullable_sources(other_bindings)
        if not value_sources <= other_sources:
            return
        shared = ", ".join(sorted(value_sources))
        self.bag.warning(
            "when-absent",
            f"{element.id}: the {policy} can never be drawn -- {shared} is also read by "
            f"{key}, which hides the element whenever it is absent",
            self.doc.span(node, policy if policy == "fallback" else "placeholder")
            or self.doc.span(node, key),
            notes=[
                f"a nullable {key} always hides the element, and that guard runs before "
                f"the value's own {policy}",
                f"either drop the {policy}, or stop reading {shared} from {key} so the "
                "element can still draw when the reading is missing",
            ],
            confidence="exact -- the same guard order codegen emits",
        )

    @staticmethod
    def nullable_sources(bindings: tuple[Expression | None, ...]) -> set[str]:
        """Catalogue paths among `bindings` that the generated code null-checks."""
        out: set[str] = set()
        for bound in bindings:
            if bound is None:
                continue
            for path in bound.sources:
                source = catalog.get(path)
                if source is not None and source.guard_needed:
                    out.add(path)
        return out

    def check_format(self, node: dict[str, Any], bound: Expression, spec: str | None) -> None:
        """Check `format:` against the bound `value:`: a date or time value
        must have one, and a given spec must suit the value's type
        (:meth:`check_format_spec`).
        """
        span = self.doc.span(node, "format")
        if spec is None:
            if bound.value.type.is_formatted():
                example = "{:%a %e %b}" if bound.value.type is Type.DATE else "{:%H:%M}"
                self.bag.error(
                    "format",
                    f"a {bound.value.type.value} value needs a 'format:', e.g. '{example}'",
                    self.doc.span(node, "value"),
                )
            return
        self.check_format_spec(bound, spec, span)

    def check_format_spec(self, bound: Expression, spec: str, span: Span | None) -> None:
        """The coded-vs-type checks a `format:` spec needs against the value
        it formats -- factored out of `check_format` so an `aod: {format:
        ...}` override (which has no "was 'format:' omitted" case of its
        own: it is only ever consulted once a spec was actually written)
        can run through the exact same checks the awake `format:` gets,
        rather than a second, narrower implementation. An earlier pass left
        an override's spec unchecked entirely, so a malformed one reached
        `formatting.emit`/`formatting.render` as a raw, unhandled
        `FormatError` instead of a diagnostic on the author's line."""
        coded = formatting.is_time_spec(spec)
        if formatting.is_duration(spec, bound.value.type):
            # strftime codes on a Number or Float read it as seconds.
            try:
                for part in formatting.parse(spec):
                    if isinstance(part, formatting.Field):
                        formatting.parse_time(part.spec, formatting.DURATION_CODES)
            except formatting.FormatError as exc:
                self.bag.error("format", str(exc), span)
        elif coded and not bound.value.type.is_formatted():
            self.bag.error(
                "format",
                f"strftime-style format {spec!r} needs a time, date or number value, "
                f"got {bound.value}",
                span,
            )
        elif not coded and bound.value.type.is_formatted():
            example = "{:%a %e %b}" if bound.value.type is Type.DATE else "{:%H:%M}"
            self.bag.error(
                "format",
                f"a {bound.value.type.value} value needs a strftime-style format "
                f"such as '{example}'",
                span,
            )
        elif coded:
            # Catch a date spec on a clock value and the reverse: both parse, and
            # the wrong one silently renders nonsense (%M is minute, not month).
            codes = formatting.DATE_CODES if bound.value.type is Type.DATE else formatting.TIME_CODES
            try:
                formatting.parse_time(formatting.strip_braces(spec), codes)
            except formatting.FormatError as exc:
                self.bag.error("format", str(exc), span)

    def check_format_not_on_literal(self, node: dict[str, Any], label: str) -> bool:
        """`format:` is meaningless without a bound `value:` to format --
        shared by a `text` element and a pattern's own `shape: text` part,
        which both take the same `text:` spelling for a fixed string.
        Returns `False` (having already reported it) when `format:` was
        written anyway, `True` otherwise."""
        if "format" not in node:
            return True
        self.bag.error(
            "format",
            f"{label}.format: 'format:' applies only to 'value:', not a fixed 'text:'",
            self.doc.span(node, "format"),
        )
        return False
