"""The always-on display: the face-wide `aod:` defaults, each node's own
`aod:` (`hide`/`show`/an override block), and resolution down the tree
(element > nearest ancestor group > face default)."""

from __future__ import annotations

from typing import Any, cast

from ... import kinds

from ..model import AodOverride, Element, Outline, Shape, Text
from .state import _lint_suppression
from .hands import HandParts

def _aod_kind(element: Element) -> tuple[str | None, str | None, bool]:
    """``(kind, shape, literal_text)`` of a built element, in the same terms
    `Builder.aod_refusal` reads off a raw node.  `shape`/`literal_text` are
    each one kind's own extra fact (a `Shape`'s own `.shape`, a `Text`'s own
    "was this a fixed 'text:'"); every other kind passes `None`/`False`,
    which is also what its own `aod_refusal` method ignores."""
    kind = kinds.for_element(element)
    shape = element.shape if isinstance(element, Shape) else None
    literal_text = isinstance(element, Text) and element.value is None
    return kind.name, shape, literal_text


class AodPass(HandParts):
    """`aod:` reading and resolution."""

    # -- always-on display (`aod:`, plan 14) --------------------------------

    def _build_face_aod(self, raw: dict[str, Any]) -> None:
        """Top-level `aod:` (plan 14 §2.2): `default:`, `dim:` (§4.5), `mask:`
        (plan 16 §4)."""
        self.face_aod_default_hide = raw.get("default", "hide") == "hide"
        lint = _lint_suppression(raw)
        self.face_aod_lint_allow = lint["lint_allow"]
        self.face_aod_lint_reason = lint["lint_reason"]
        dim_raw = raw.get("dim")
        # `dim: 1` means "no dimming", exactly like no `dim:` -- both become
        # `None`, which keeps the generated source byte-identical.
        self.face_aod_dim = None if dim_raw is None or float(dim_raw) == 1.0 else float(dim_raw)
        self.face_aod_mask = bool(raw.get("mask", True))

    def aod_refusal(self, key: str, kind: str | None, shape: str | None,
                    literal_text: bool) -> tuple[str, str, list[str]] | None:
        """``(code, what, notes)`` when an `aod:` override's `key` cannot
        apply to an element of this kind, else ``None`` -- the one table
        both an element's own block (`_build_aod_authored`,
        `wfb.kinds.text.TextKind.build`) and a key it inherits from a group
        (`_resolve_aod`) are checked
        against, so the two cannot drift (plan 18 item 5).  Each kind's own
        refusal rule lives on its `ElementKind.aod_refusal` method."""
        if kind is None or kind not in kinds.names():
            return None
        return kinds.get(kind).aod_refusal(key, shape, literal_text)

    def _build_aod_authored(self, node: dict[str, Any]) -> tuple[bool, dict[str, object] | None]:
        """Parse one element/group's own `aod:` (plan 14 §2.1) into
        ``(hide, keys)``: ``hide`` is `True` only for the literal `aod: hide`;
        ``keys`` is `None` when nothing but that was written (or nothing at
        all), or the resolved key -> value dict an `aod: show` (`{}`) or an
        override block produced.

        One parser for every kind: the schema's per-kind `aod<Kind>` `$defs`
        already restrict which keys may appear.  Every value resolves
        through the same machinery as the element's own property of that
        name (`color_expression`, `length`, `_font_reference` -- kept as
        its `(name, is_custom)` pair, `_visible`).
        """
        raw = node.get("aod")
        if raw is None:
            return False, None
        if raw == "hide":
            return True, None
        if raw == "show":
            return False, {}
        element_id = node.get("id", "?")
        keys: dict[str, Any] = {}
        for key in ("color", "track_color", "icon_color"):
            if key in raw:
                keys[key] = self.color_expression(raw, key)
        for key in ("thickness", "bar_width"):
            if key in raw:
                keys[key] = self.length(raw, key)
        kind, shape = node.get("type"), node.get("shape")
        if "filled" in raw:
            refusal = self.aod_refusal("filled", kind, shape, literal_text=False)
            if refusal is not None:
                code, what, notes = refusal
                self.bag.error(code, f"{element_id}: {what}",
                               self.doc.span(raw, "filled") or self.doc.span(node, "aod"),
                               notes=notes)
            else:
                keys["filled"] = bool(raw["filled"])
        if "font" in raw:
            refusal = self.aod_refusal("font", kind, shape, literal_text=False)
            if refusal is not None:
                code, what, notes = refusal
                self.bag.error(code, f"{element_id}: {what}",
                               self.doc.span(raw, "font") or self.doc.span(node, "aod"),
                               notes=notes)
            else:
                resolved = self._font_reference(str(raw["font"]), self.doc.span(raw, "font"))
                if resolved is not None and self.is_vector_font(*resolved):
                    self.bag.error(
                        "aod",
                        f"{element_id}: an 'aod: {{font: ...}}' override "
                        f"naming a 'face:' (vector) font is not implemented yet "
                        f"(plan 14)",
                        self.doc.span(raw, "font"),
                        notes=[f"{resolved[0]!r} is declared with 'face:', not 'source:' "
                               "-- name a baked font instead, or drop the override "
                               "for now"],
                    )
                elif resolved is not None:
                    keys["font"] = resolved
        if "format" in raw:
            keys["format"] = raw["format"]
        if "outline" in raw:
            # Same grammar, colour machinery and width cap as the element's
            # own `outline:`; `none` is kept, since it drops an awake ring.
            outline = self.build_outline(raw, "outline", f"{element_id}.aod")
            if outline is not None or raw["outline"] == "none":
                keys["outline"] = outline if outline is not None else "none"
        if "visible" in raw:
            keys["visible"] = self._visible(raw)
        return False, keys

    def _make_aod_override(self, element: Element, keys: dict[str, Any]) -> AodOverride:
        """Build the `AodOverride` a *drawn* (non-hidden) element gets, from
        its fully key-by-key-resolved `keys` (`_resolve_aod`)."""
        font = cast("tuple[str, bool] | None", keys.get("font"))
        font_name, font_is_custom = font if font is not None else (None, False)
        own_visible = keys.get("visible")
        outline = keys.get("outline")
        return AodOverride(
            outline=outline if isinstance(outline, Outline) else None,
            outline_none=outline == "none",
            color=keys.get("color"),
            track_color=keys.get("track_color"),
            icon_color=keys.get("icon_color"),
            thickness=keys.get("thickness"),
            bar_width=keys.get("bar_width"),
            filled=keys.get("filled"),
            font=font_name,
            font_is_custom=font_is_custom,
            format=keys.get("format"),
            visible=self._conjoin_visible(element.visible, own_visible),
            visible_override=own_visible,
        )

    def _resolve_aod(self, elements: list[Element]) -> None:
        """Resolve `aod:` over the whole tree (plan 14 §3): element wins key
        by key over its nearest ancestor group's own `aod:`, which wins over
        the face's `aod: default:`.

        A top-down walk, like `_resolve_inherited_flag`, but tracking two
        things down the tree rather than one:

        * ``forced_hidden`` -- sticky once an *explicit* `aod: hide` is seen
          (own or inherited): every descendant is hidden regardless of what
          it writes itself, mirroring `visible:`'s own group-conjoins-down
          precedent, one level stricter (nothing can undo it below).
        * ``nearest`` -- the most recently seen explicit `aod: show`/override
          dict on the path from the root to here, replaced wholesale (not
          merged) by a nearer one when a deeper group writes its own; `None`
          exactly when nothing along the ancestry has spoken yet, which is
          what lets the face default apply only there.

        `aod_ancestor_hidden` is stamped on every element for the
        `aod-unreachable` lint, which must tell "an ancestor's hide buried my
        own override" apart from "no `aod:` of my own".

        A key an element inherits (rather than writes) is checked here
        against the same per-kind refusals its own block would get
        (`aod_refusal`), because only here has a group's key reached the
        element: one error per element, on the element, naming the group,
        and the key is dropped (plan 18 item 5).
        """
        def visit(items: list[Element], forced_hidden: bool,
                 nearest: dict[str, object] | None, nearest_from: Element | None) -> None:
            for element in items:
                element.aod_ancestor_hidden = forced_hidden
                own_hide = element.aod_own_hide
                own = element.aod_own
                if forced_hidden or own_hide:
                    hidden = True
                elif own is not None or nearest is not None:
                    hidden = False
                else:
                    hidden = self.face_aod_default_hide
                child_forced_hidden = forced_hidden or own_hide
                child_nearest = own if own is not None else nearest
                child_nearest_from = element if own is not None else nearest_from
                if hidden:
                    element.aod = None
                else:
                    effective = dict(nearest or {})
                    if nearest_from is not None:
                        self._refuse_inherited_aod_keys(element, effective, own, nearest_from)
                    if own is not None:
                        effective.update(own)
                    element.aod = self._make_aod_override(element, effective)
                    fmt = effective.get("format")
                    if (fmt is not None and isinstance(element, Text) and element.value is not None
                            and not (own is not None and "format" in own)):
                        # Inherited from a group, whose block may reach
                        # several kinds and value types -- only checkable
                        # here.  An element's own one `wfb.kinds.text.TextKind.build` checked.
                        self.check_format_spec(element.value, str(fmt), element.span)
                visit(element.children(), child_forced_hidden, child_nearest,
                      child_nearest_from)

        visit(elements, False, None, None)

    def _refuse_inherited_aod_keys(self, element: Element, inherited: dict[str, object],
                                   own: dict[str, object] | None, group: Element) -> None:
        """Report, and drop from ``inherited``, every key ``group``'s own
        `aod:` passed down that ``element`` cannot take and does not
        override itself."""
        kind, shape, literal = _aod_kind(element)
        for key in sorted(inherited):
            if own is not None and key in own:
                continue
            refusal = self.aod_refusal(key, kind, shape, literal)
            if refusal is None:
                continue
            code, what, notes = refusal
            where = f"line {group.span.line}" if group.span is not None else "its own 'aod:'"
            self.bag.error(
                code,
                f"{element.id}: {what}, inherited from group {group.id!r}",
                element.span,
                notes=[f"group {group.id!r} sets 'aod: {{{key}: ...}}' ({where}) for every "
                       f"element below it", *notes,
                       f"move the group's '{key}' onto the elements that can take it"],
            )
            del inherited[key]

    def _resolve_inherited_flag(self, elements: list[Element], key: str, default: bool) -> None:
        """Resolve a boolean key as an inherited default, root to leaf --
        `antialias:` and `min_1px:`.  `Element.<key>` holds what the author
        wrote (`None` = inherit); the answer is stamped into
        `Element.resolved_<key>`, with `default` (the face-wide value) at the
        root.  The nearest declaration wins outright -- unlike `visible:`,
        nothing accumulates -- which is why this is a walk over the finished
        tree rather than a push per group the way `push_visible` is.
        """
        resolved = f"resolved_{key}"

        def visit(items: list[Element], inherited: bool) -> None:
            for element in items:
                authored_value = getattr(element, key)
                resolved_value = authored_value if authored_value is not None else inherited
                setattr(element, resolved, resolved_value)
                visit(element.children(), resolved_value)

        visit(elements, default)
