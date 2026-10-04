"""The element tree: one node to one `Element` through its kind
(`wfb.kinds`), ids and derived symbols, and `on_hold:` targets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ... import catalog, complications, kinds, vocab
from ...diagnostics import Span

from ..model import ComplicationSlot, Element, HOLD_AUTO, ROLE_VALUE, Position
from ..naming import element_const_prefix, element_method_name
from ..rings import ring_groups
from .state import _lint_suppression
from .static import StaticPass

if TYPE_CHECKING:
    from . import Builder

#: The keys an `overrides:` patch may carry, as `wfb.lower` leaves them.
_OVERRIDE_FIELDS = ("at", "size", "radius", "align")

#: Kinds whose `align:` is a `TEXT_JUSTIFY_*` flag in the shared view
#: rather than a per-device box shift, so no override may change it.
_GLYPH_KINDS = frozenset({"text", "icon", "complication_slot"})


def _merged(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """``patch`` deep-merged over ``base``: mappings key by key, anything
    else replaced."""
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merged(out[key], value)
        else:
            out[key] = value
    return out


def _kind_name(element: Element) -> str:
    """The `type:` the author wrote for ``element``."""
    if element.kind == "shape":
        return str(getattr(element, "shape", "shape")).replace("rounded_rectangle", "rectangle")
    return vocab.kind(element.kind)


def _takes_align(element: Element) -> bool:
    """Whether this element's own `align:` places it -- the kinds whose
    alignment layout resolves into its box."""
    if element.kind == "shape":
        from ...kinds.shape import SHAPE_GEOMETRY_KEYS  # the kind imports the IR
        return "align" in SHAPE_GEOMETRY_KEYS.get(getattr(element, "shape", ""), frozenset())
    return element.kind in ("group", "progress", "graph")


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
        aod_own_hide, aod_own = self._build_aod_authored(node)
        at = self.position(node.get("at"), node, "at", allow_subscreen=True)
        if not self._check_subscreen(node, at, path, span):
            return None
        common = dict(
            id=element_id,
            kind=node["type"],
            at=at,
            modes=("active", "low_power") if node.get("sleep_update") is True else ("active",),
            sleep_update=node.get("sleep_update"),
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
            unsupported=node.get("unsupported"),
        )

        if node["type"] not in kinds.names():  # unreachable once the schema has run
            self.bag.error("element", f"unsupported element type {node['type']!r}", span)
            return None
        # A kind is written against the whole `Builder`, which this layer
        # only ever is a base of.
        element = kinds.get(node["type"]).build(cast("Builder", self), node, common, path)
        if element is not None and node.get("overrides"):
            if not self._build_overrides(node, element):
                return None
        if element is not None:
            self._resolve_hold_auto(element)
            if "outline" in node and element.outline is None and element.kind != "text":
                # `text` builds its own ring, alongside `curve:`; the schema
                # decides which other kinds accept one.
                element.outline = cast("Builder", self).build_outline(
                    node, "outline", element_id, element=element)
            refusal = kinds.get(element.kind).ring_refusal(element)
            if element.outline is not None and refusal is not None:
                self.bag.error("outline", f"{element_id}: 'outline:' {refusal}",
                               self.doc.span(node, "outline", of="key") or span,
                               notes=["not implemented yet -- docs/limitations.md §2"])
                return None
        return element

    # -- overrides --------------------------------------------------------

    def _build_overrides(self, node: dict[str, Any], element: Element) -> bool:
        """`overrides:` (ADR 0004 §4): each selector's geometry patch
        checked, then merged over the element's own keys and parsed once per
        selector and per (shape, device) pair, into `Element.overrides`.
        False, having reported why, when a patch is refused."""
        raw = node["overrides"]
        shapes: dict[str, dict[str, Any]] = {}
        devices: dict[str, dict[str, Any]] = {}
        selectors: list[tuple[str, Span | None]] = []
        ok = True
        for selector, patch in raw.items():
            selector = str(selector)
            selectors.append((selector, self.doc.span(raw, selector, of="key")
                              or self.doc.span(raw, selector)))
            if selector.startswith("shape:"):
                shapes[selector[len("shape:"):]] = patch
            else:
                devices[selector] = patch
            ok = self._check_override_patch(node, element, selector, patch) and ok
        element.override_selectors = tuple(selectors)
        if not ok:
            return False
        combos: list[tuple[str | None, str | None]] = [
            *((shape, None) for shape in shapes), *((None, device) for device in devices),
            *((shape, device) for shape in shapes for device in devices)]
        for shape, device in combos:
            patches = [p for p in (shapes.get(shape or ""), devices.get(device or ""))
                       if p is not None]
            element.overrides[(shape, device)] = self._override_fields(node, element, patches)
        return True

    def _check_override_patch(self, node: dict[str, Any], element: Element, selector: str,
                              patch: dict[str, Any]) -> bool:
        """One selector's patch: only keys this element writes (or, for
        `at:`/`align:`, takes), alignment never on a glyph kind, the
        subscreen window never entered or left, and every length valid."""
        label = f"{element.id}.overrides.{selector}"
        errors_before = len(self.bag.errors)
        for key in patch:
            span = self.doc.span(patch, key, of="key") or self.doc.span(patch, key)
            if key == "align":
                if element.kind in _GLYPH_KINDS:
                    self.bag.error(
                        "overrides",
                        f"{label}: 'align:' on a {_kind_name(element)} is the draw call's "
                        "justification, which every target shares",
                        span, notes=["move it with 'at:' instead"])
                elif not _takes_align(element):
                    self.bag.error("overrides",
                                   f"{label}: a {_kind_name(element)} takes no 'align:'", span)
            elif key in ("size", "radius"):
                if key not in node:
                    self.bag.error(
                        "overrides",
                        f"{label}: '{key}:' is not a key this element writes",
                        span, notes=["an override changes the element's own geometry; it "
                                     "cannot add a key the element does not have"])
                elif key == "size":
                    self.size(patch["size"])
                else:
                    self.length(patch, "radius")
            elif key == "at":
                at = patch["at"]
                base = node.get("at") or {}
                merged_anchor = at.get("anchor", base.get("anchor")) if isinstance(at, dict) \
                    else None
                if (merged_anchor == "subscreen") != (base.get("anchor") == "subscreen"):
                    self.bag.error(
                        "overrides",
                        f"{label}: an override cannot move an element into or out of "
                        "the subscreen window", span)
                elif isinstance(at, dict):
                    self.position(_merged(base, at), patch, "at",
                                  allow_subscreen=merged_anchor == "subscreen")
        return len(self.bag.errors) == errors_before

    def _override_fields(self, node: dict[str, Any], element: Element,
                         patches: list[dict[str, Any]]) -> dict[str, Any]:
        """The element's geometry fields with ``patches`` merged over its
        own keys in order: a mapping key by key, anything else replaced, and
        `align:` replacing the element's whole alignment."""
        own: dict[str, Any] = {key: node[key] for key in _OVERRIDE_FIELDS if key in node}
        for patch in patches:
            if "align" in patch:
                own.pop("align", None)
            own = _merged(own, patch)
        touched = {key for patch in patches for key in patch}
        fields: dict[str, Any] = {}
        if "at" in touched:
            fields["at"] = self.position(own.get("at"), own, "at",
                                         allow_subscreen=element.in_subscreen)
        if "size" in touched:
            fields["size"] = self.size(own.get("size"))
        if "radius" in touched:
            fields["radius"] = self.length(own, "radius")
        if "align" in touched:
            fields["align"], fields["vertical_align"] = self.alignment(own)
        return fields

    def check_group_outlines(self, elements: list[Element]) -> None:
        """What an outlined `group` needs of its members: a
        ring every member can draw, and a colour the frame can compute
        without the members' data.

        - Every leaf must be a `ringed` kind: its ring pass is its own
          `ring<Id>` method.
        - `outline.color` reads no data source: the ring is drawn from the
          frame methods, which read only what the members themselves bind.

        A group is never partly static: `static:` is a block, and its root
        is always a whole subtree (`_apply_static`), so every member of an
        outlined group draws in the same frame sequence.
        """
        for ring in ring_groups(elements):
            group = ring.group
            assert group.outline is not None
            span = group.span
            for leaf, _ in ring.members:
                refusal = kinds.get(leaf.kind).ring_refusal(leaf)
                if refusal is not None and kinds.get(leaf.kind).ringed:
                    self.bag.error(
                        "outline",
                        f"{group.id}: 'outline:' on a group needs every member to draw a "
                        f"ring, and {leaf.id!r} cannot: 'outline:' {refusal}",
                        leaf.span or span,
                        notes=["not implemented yet -- docs/limitations.md §2"],
                    )
                elif not kinds.get(leaf.kind).ringed:
                    self.bag.error(
                        "outline",
                        f"{group.id}: 'outline:' on a group needs every member to draw a "
                        f"ring, and {leaf.id!r} is a '{leaf.kind}', which cannot yet",
                        leaf.span or span,
                        notes=["text, icons, shapes, hands, patterns and gauges can be "
                               "ringed; move this element out of the group, or drop the "
                               "group's 'outline:'"],
                    )
            if group.outline.color.sources:
                self.bag.error(
                    "outline",
                    f"{group.id}: a group's 'outline.color' cannot read data "
                    f"({', '.join(group.outline.color.sources)})",
                    span,
                    notes=["use a palette, scheme or config colour, or a literal"],
                )

    def _check_subscreen(self, node: dict[str, Any], at: Position, path: tuple[str | int, ...],
                         span: Span | None) -> bool:
        """`anchor: subscreen` is a top-level element's alone, and
        `unsupported:` needs something that can be unavailable: the
        subscreen here, or a `text` element's `face:` font (checked by the
        text kind itself, `Builder.check_unsupported`)."""
        in_subscreen = at.anchor == "subscreen"
        if in_subscreen and "children" in path:
            self.bag.error(
                "subscreen",
                f"{node['id']}: 'anchor: subscreen' is not accepted on a group's child",
                self.doc.span(node.get("at"), "anchor") or span,
                notes=["put 'anchor: subscreen' on the top-level group instead: its "
                       "children are then laid out inside the window"],
            )
            return False
        if "unsupported" in node and not in_subscreen and node["type"] != "text":
            self.bag.error(
                "subscreen",
                f"{node['id']}: 'unsupported:' is not accepted here",
                self.doc.span(node, "unsupported") or span,
                notes=["on this element it governs 'at: {anchor: subscreen}' on a target "
                       "without a subscreen window; this element is not anchored there",
                       "drop 'unsupported:', or anchor the element to the subscreen"],
            )
            return False
        return True

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

        Every `ROLE_VALUE`-tagged bound expression's sources --
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
