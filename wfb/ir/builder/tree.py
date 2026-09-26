"""The element tree: one node to one `Element` through its kind
(`wfb.kinds`), ids and derived symbols, and `on_hold:` targets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ... import catalog, complications, kinds
from ...diagnostics import Span

from ..model import ComplicationSlot, Element, HOLD_AUTO, ROLE_VALUE
from ..naming import element_const_prefix, element_method_name
from .state import _lint_suppression
from .static import StaticPass

if TYPE_CHECKING:
    from . import Builder


class ElementTree(StaticPass):
    """Builds the element tree, dispatching each node to its kind."""

    # -- elements ---------------------------------------------------------

    def build_elements(self, raw: list[Any], path: tuple[str | int, ...]) -> list[Element]:
        """Build every element of an `elements:`/`children:` list, dropping
        any that reported an error.  `path` is the list's own schema path.
        """
        out: list[Element] = []
        for index, node in enumerate(raw):
            element = self._build_element(node, path + (index,))
            if element is not None:
                out.append(element)
        return out

    def _build_element(self, node: dict[str, Any], path: tuple[str | int, ...]) -> Element | None:
        span = self.doc.span_for_path(list(path))
        element_id = node["id"]
        if element_id in self.seen_ids:
            first = self.seen_ids[element_id]
            self.bag.error(
                "duplicate-id",
                f"duplicate element id {element_id!r}",
                self.doc.span(node, "id"),
                notes=[f"first declared at {first}"] if first else [],
            )
            return None
        self.seen_ids[element_id] = span
        if not self._check_symbol_collision(element_id, node, span):
            return None
        if node.get("overrides"):
            # Parsed and stored, but applied by nothing (ADR 0004 4 is still
            # unbuilt).  Accepting it silently would be the worst of the
            # three options: a misspelled device id and an invented key both
            # validate clean, and the author would be left believing a
            # per-device tweak landed.
            self.bag.error(
                "overrides",
                f"{element_id}: per-device 'overrides:' is not implemented yet, "
                "so this would be silently ignored",
                self.doc.span(node, "overrides") or span,
                notes=["ADR 0004 4 specifies it; nothing reads it yet -- see "
                       "docs/limitations.md 2",
                       "until it lands, express a per-device difference with a "
                       "relative unit (%r, %) rather than a fixed px"],
            )
            return None

        aod_own_hide, aod_own = self._build_aod_authored(node)
        common = dict(
            id=element_id,
            kind=node["type"],
            at=self.position(node.get("at"), node, "at"),
            modes=tuple(node.get("modes") or ("active",)),
            z=node.get("z"),
            span=span,
            **_lint_suppression(node),
            on_hold=self._hold_target(node),
            visible=self._visible(node),
            static=bool(node.get("static", False)),
            antialias=(bool(node["antialias"]) if "antialias" in node else None),
            min_1px=(bool(node["min_1px"]) if "min_1px" in node else None),
            aod_own_hide=aod_own_hide,
            aod_own=aod_own,
        )

        if node["type"] not in kinds.names():  # unreachable once the schema has run
            self.bag.error("element", f"unsupported element type {node['type']!r}", span)
            return None
        # A kind is written against the whole `Builder`, which this layer
        # only ever is a base of.
        element = kinds.get(node["type"]).build(cast("Builder", self), node, common, path)
        if element is not None:
            self._resolve_hold_auto(element)
        return element

    def _check_symbol_collision(self, element_id: str, node: dict[str, Any], span: Span | None) -> bool:
        """Reject two distinct ids that derive the same Monkey C symbol.

        ``_build_element`` above already rejects a literal duplicate id; this
        catches the case the emitter would otherwise discover on the
        generator's behalf, four `Redefinition of ...` errors deep, pointing
        at *generated* line numbers rather than the author's YAML -- exactly
        what the diagnostics module exists to prevent.  Checked against both
        derived forms (`element_const_prefix`, `element_method_name`) because
        they fold case and separators independently; in practice they collide
        together, but there is no reason to assume that stays true forever.
        """
        node_kind = node.get("type")
        extra_symbols = kinds.get(node_kind).extra_symbols if node_kind in kinds.names() else ()
        candidates = [element_const_prefix(element_id), element_method_name(element_id)]
        candidates += [derive(element_id) for derive in extra_symbols]
        collisions: list[tuple[str, str, Span | None]] = []
        for symbol in candidates:
            claimed = self.seen_symbols.get(symbol)
            if claimed is not None and claimed[0] != element_id:
                collisions.append((symbol, claimed[0], claimed[1]))
        if collisions:
            other_id = collisions[0][1]
            other_span = collisions[0][2]
            symbols = ", ".join(repr(symbol) for symbol, _, _ in collisions)
            notes = ["element ids only need to be distinct as literal strings today, "
                     "but codegen derives one Monkey C symbol per id, folding case and "
                     "separators away -- 'temp_low' and 'tempLow' both become 'TEMP_LOW'"]
            if other_span is not None:
                notes.insert(0, f"{other_id!r} first declared at {other_span}")
            self.bag.error(
                "duplicate-id",
                f"element id {element_id!r} generates the same Monkey C symbol as "
                f"{other_id!r} ({symbols})",
                self.doc.span(node, "id") or span,
                notes=notes,
            )
            return False
        for symbol in candidates:
            self.seen_symbols[symbol] = (element_id, span)
        return True

    def _hold_target(self, node: dict[str, Any]) -> str | None:
        """Validate `on_hold:` against the launchable complication table.

        A watch face cannot open an arbitrary app; `Complications.exitTo` is
        the only exit the platform offers, so the value here names a
        complication *type* and the watch opens whatever owns it.  Checked
        against :mod:`wfb.complications`, which is generated from the SDK's own
        `COMPLICATION_TYPE_*` table -- an invented name would compile to an
        undefined symbol, so catching it here points at the author's line
        instead of a generated one.

        `on_hold: auto` is validated here only as far as recognising the
        sentinel and passing it through unresolved -- this runs from
        `common`, *before* the kind-specific builder gives the element a
        value binding to resolve `auto` from.  `Builder._resolve_hold_auto`
        does the actual resolution once the element is fully built.
        """
        raw = node.get("on_hold")
        if raw is None:
            return None
        name = str(raw)
        if name == HOLD_AUTO:
            return HOLD_AUTO
        if complications.get(name) is not None:
            return name
        notes = self._complication_suggestion_notes(name, "launch targets")
        self.bag.error(
            "on-hold",
            f"unknown hold target {name!r}",
            self.doc.span(node, "on_hold"),
            notes=notes,
        )
        return None

    def _resolve_hold_auto(self, element: Element) -> None:
        """Resolve `on_hold: auto`.

        Deferred here, called from `_build_element` right after the
        kind-specific builder returns: this needs a *fully-built* element,
        since `_hold_target` (called from `common`, before the builder runs)
        has no value binding yet to resolve `auto` from.

        Afterwards `element.on_hold` is a real `wfb.complications.TYPES`
        key or `None` -- never `HOLD_AUTO`, except on a `complication_slot`.
        """
        if isinstance(element, ComplicationSlot):
            # A slot's `auto` stays `HOLD_AUTO`: the wearer can repoint the
            # slot at any moment, so the delegate reads the launch target
            # from the slot's own field on the device (`emit_delegate`).
            return
        if element.on_hold == HOLD_AUTO:
            element.on_hold = self._resolve_auto_target(
                element.id, "on_hold", self._hold_auto_sources(element), element.span)

    @staticmethod
    def _hold_auto_sources(element: Element) -> tuple[str, ...]:
        """The catalogue paths `on_hold: auto` may resolve from, for one element.

        Every `ROLE_VALUE`-tagged bound expression's sources (plan 19 A2) --
        deliberately not `color:`/`max:`, since a conditional colour's
        reference is not what the element is *about*.  A `text`'s `value:`,
        a `progress`'s `value:` (not `max:`), and an `icon`'s `icon_for:`
        (not a static `icon:`/`glyph:`, which reads no source at all) are
        each the one `ROLE_VALUE` expression their kind ever tags.

        Deliberately not `element.VALUE_ROLES`, the set `ReadPlan.
        _value_expressions` reads instead: that answers a different
        question (what a `when_absent:` policy governs -- it adds
        `Progress.max`, and has none at all for `IconElement`), so the two
        read the *tag* the same expressions share, not the *kind-specific
        subset* the other one narrows to.
        """
        for role, expression in element.bound_expressions():
            if role == ROLE_VALUE:
                return expression.sources
        return ()

    def _resolve_auto_target(self, label: str, key: str, sources: tuple[str, ...],
                             span: Span | None) -> str | None:
        """Resolve `auto` to exactly one `wfb.complications.TYPES` name.

        Three outcomes: exactly one distinct non-None
        `Source.launch_complication` among ``sources`` resolves; zero
        (including no value binding at all) is `hold-auto-unresolved`; more
        than one distinct is `hold-auto-ambiguous`.  Both are errors, not
        warnings -- guessing here would silently open the wrong glance, which
        is exactly the class of failure this compiler exists to prevent.
        """
        found: dict[str, str] = {}
        for path in sources:
            source = catalog.get(path)
            target = source.launch_complication if source is not None else None
            if target is not None and target not in found:
                found[target] = path
        if len(found) == 1:
            return next(iter(found))
        bound = ", ".join(repr(p) for p in sources) if sources else "(none)"
        if not found:
            self.bag.error(
                "hold-auto-unresolved",
                f"{label}: '{key}: auto' could not resolve a hold target -- "
                f"bound source(s): {bound}",
                span,
                notes=[
                    "none of this element's bound source(s) has a conventional "
                    "complication counterpart (wfb.catalog.Source.launch_complication)",
                    "name a target explicitly instead of 'auto' -- run "
                    "`wfb complications` for the full list",
                ],
            )
            return None
        candidates = ", ".join(repr(name) for name in sorted(found))
        self.bag.error(
            "hold-auto-ambiguous",
            f"{label}: 'auto' is ambiguous between {candidates} -- "
            f"bound source(s): {bound}",
            span,
            notes=["name one explicitly instead of 'auto' -- run "
                   "`wfb complications` for the full list"],
        )
        return None
