"""Reading one key of a node: expressions, colours, lengths, angles,
positions, sizes, alignment and font references, each reporting its own
error on the author's line."""

from __future__ import annotations

import re
from typing import Any

from ... import catalog, expr, units
from ...catalog import Type
from ...diagnostics import Span
from ...palette import Color, ColorError
from ...units import Angle, Length, UnitError
from ...yamlsrc import Origin

from ..model import DataElement, Expression, Position, SYSTEM_FONTS, Size, Text
from .state import BuilderState

#: Matches `expr.check`'s "unknown data source" message for a `color.<name>`
#: the scope does not bind -- `Builder.expression` explains a scheme role
#: that no style picks.
_COLOR_RE = re.compile(r"^unknown data source 'color\.([A-Za-z_][A-Za-z0-9_]*)'$")


def _offset_span(span: Span | None, text: str, offset: int) -> Span | None:
    """Shift a span to point inside the expression string, not just at its key."""
    if span is None:
        return None
    return Span(span.path, span.line, span.col + offset)


class Readers(BuilderState):
    """Coercion helpers: a key of a node in, a typed value (or `None`, after
reporting why) out."""

    def alignment(self, node: dict[str, Any]) -> tuple[str, str]:
        """`align:` as `(horizontal, vertical)`, each defaulting to
        `"center"` -- the one place every kind with a placement box reads
        it.  `top_left` is `("left", "top")`, `top` is `("center", "top")`
        and `left` is `("left", "center")`.  The schema is normative on
        which values reach here, and `wfb.lower` has already spelled a
        compass alias (`NE`) out."""
        value = str(node.get("align", "center"))
        vertical = next((v for v in ("top", "bottom")
                         if value == v or value.startswith(v + "_")), None)
        if vertical is None:
            return value, "center"
        return value[len(vertical) + 1:] or "center", vertical

    def absence(self, node: dict[str, Any]) -> dict[str, Any]:
        """`absent:` as the IR's three fields: `absent` (the policy:
        `"hide"`, `"placeholder"`, `"fallback"`, or `None` when unwritten),
        `placeholder` (the text drawn instead) and `fallback` (the
        expression read instead, `absent: {value: ...}`)."""
        value = node.get("absent")
        if value is None or value == "hide":
            return {"absent": value, "placeholder": None, "fallback": None}
        if isinstance(value, dict):
            return {"absent": "fallback", "placeholder": None,
                    "fallback": self.expression(value, "value")}
        return {"absent": "placeholder", "placeholder": str(value), "fallback": None}

    def fallback_span(self, node: dict[str, Any]) -> Span | None:
        """Where `absent: {value: ...}`'s expression is written."""
        absent = node.get("absent")
        return ((self.doc.span(absent, "value") if isinstance(absent, dict) else None)
                or self.doc.span(node, "absent"))

    def require(self, node: dict[str, Any], key: str, message: str) -> None:
        """Report `message` as an `element` error on `node[key]`'s line, or
        on the node's own when the key is absent -- for a key the schema
        cannot require on its own.
        """
        self.bag.error("element", message, self.doc.span(node, key) or self.doc.span(node))

    # -- coercion helpers -------------------------------------------------

    def expression(self, node: dict[str, Any], key: str) -> Expression | None:
        """`node[key]` parsed, type-checked and compiled to Monkey C as an
        :class:`Expression`, or `None` when the key is absent or the
        expression was reported as an error.
        """
        raw = node.get(key)
        if raw is None:
            return None
        return self.compile_expression(str(raw), self.doc.span(node, key), key,
                                       origin=self.doc.origin(node, key))

    def compile_expression(self, text: str, span: Span | None, key: str, *,
                           origin: Origin | None = None) -> Expression | None:
        """`text` parsed, type-checked and compiled as :meth:`expression`
        does for an authored key -- for an expression the builder writes
        itself (a `units:` conversion, `wfb.conversion`), reported against
        ``span`` under ``key``.  ``origin`` is what the author wrote there,
        when `wfb.lower` rewrote it: a diagnostic names and points into
        that instead."""
        before = set(self.scope.used)
        self.scope.used.clear()
        syntax_error = False
        try:
            try:
                node_ast = expr.parse(text)
            except expr.ExprError:
                # A *syntax* failure, as opposed to an unknown source or a type
                # error below.  Worth telling apart: `value: XX%` is almost
                # always someone reaching for literal text, while
                # `value: activity.stepss` is a real typo in a real expression
                # and must not be told to use `text:` instead.
                syntax_error = True
                raise
            value = expr.check(node_ast, self.scope)
            # Emit from a fold that keeps palette names; derive the build-time
            # constant, which the linter needs, from a fold that resolves them.
            folded = expr.fold(node_ast, self.scope, fold_colors=False)
            code = expr.emit(folded, self.scope)
            resolved = expr.fold(node_ast, self.scope)
        except expr.ExprError as exc:
            message, notes, code_ = exc.message, exc.notes, exc.code or "expression"
            # `wfb.lower` has refused an unknown `color.<name>`, so one that
            # reaches here unbound is a scheme role: it has a value only once
            # a style picks the scheme, and with no `config: style:` naming
            # one, no role is bound at all.
            match = _COLOR_RE.match(message)
            declared = {r for scheme in self.color_scheme.values() for r in scheme.colors}
            if match is not None and match.group(1) in declared:
                code_ = "config"
                message = (f"color.{match.group(1)} is a role of 'theme: schemes:', "
                           "but no 'config: style:' entry picks a scheme")
                notes = ["add a 'config: style:' entry with 'scheme:', or make it a "
                         "palette colour"]
            if syntax_error and key == "value" and origin is None:
                notes = list(notes) + [
                    "'value:' is an expression over data sources, not literal text -- "
                    "for a fixed string use 'text:' instead:\n"
                    '    text: "XX%"',
                    "note that YAML strips the quotes, so `value: 'XX%'` reaches the "
                    "expression parser as a bare XX%",
                ]
            offset = exc.offset if origin is None else origin.author_offset(exc.offset)
            if self._quoted_at(span):
                offset += 1  # the offset is into the value, after its opening quote
            self.bag.error(
                code_,
                f"{origin.key if origin is not None else key}: {message}",
                _offset_span(span, text, offset),
                notes=notes,
            )
            self.scope.used |= before
            return None
        used = [p for p in self.scope.used if p in catalog.CATALOG]
        self.scope.used |= before
        barrel = {c.name for c in expr.walk(folded)
                  if isinstance(c, expr.Call) and c.name in expr.CALL_BARREL}
        modules = {expr.CALL_MODULES[c.name] for c in expr.walk(folded)
                   if isinstance(c, expr.Call) and c.name in expr.CALL_MODULES}
        constant = resolved.value if isinstance(resolved, expr.Literal) else None
        author = None
        if origin is not None and origin.text is not None:
            author = origin.quote if origin.quote is not None else origin.text
        return Expression(
            text=text, code=code, value=value, sources=tuple(sorted(used)),
            barrel=frozenset(barrel), modules=frozenset(modules), span=span, constant=constant,
            ast=folded, author=author,
        )

    def _quoted_at(self, span: Span | None) -> bool:
        """Does a quoted scalar open at ``span``?"""
        if span is None or span.path != self.doc.path:
            return False
        lines = self.doc.text.split("\n")
        if not 0 < span.line <= len(lines):
            return False
        line = lines[span.line - 1]
        return 0 < span.col <= len(line) and line[span.col - 1] in "'\""

    def color_expression(self, node: dict[str, Any], key: str) -> Expression | None:
        """`node[key]` as a colour :class:`Expression`: a bare `#RRGGBB`
        literal (accepted, with a `raw-color` note) or any expression of
        colour type.  `None` when absent or reported.
        """
        raw = node.get(key)
        if raw is None:
            return None
        span = self.doc.span(node, key)
        text = str(raw)
        # A bare hex literal is not expression syntax; accept it and say so.
        if text.startswith("#"):
            try:
                color = Color.parse(text, what=key)
            except ColorError as exc:
                self.bag.error("color", str(exc), span)
                return None
            self.bag.note(
                "raw-color",
                f"{self.doc.author_key(node, key)}: {text} is a literal colour -- prefer a "
                "named palette swatch",
                span,
                notes=["palette entries keep a design's colours consistent and lintable"],
            )
            return Expression(text, color.as_monkeyc(), expr.Value(Type.COLOR), (),
                              frozenset(), frozenset(), span, constant=color.value,
                              ast=expr.Literal(color.value, Type.COLOR))
        bound = self.expression(node, key)
        if bound is not None and bound.value.type is not Type.COLOR:
            self.bag.error(
                "type", f"{self.doc.author_key(node, key)} must be a colour, got {bound.value}",
                span,
                notes=["known palette swatches: " + (", ".join(f"color.{n}" for n in sorted(self.palette)) or "(none)")],
            )
            return None
        return bound

    def _font_reference(self, name: str, span: Span | None) -> tuple[str, bool] | None:
        """Resolve a `font:`/`value_font:` name to ``(reference, is_custom)``.

        Shared by every element's `font:` (`text`, `data`), so
        they cannot disagree about what a font name means.

        Returns ``None`` when the name does not resolve.  The one subtlety is
        what happens for a font that *was* declared and then rejected by
        `_build_fonts` (a missing `source:`, a bad `size:`, `align:` without
        `monospace:`): the build is already failing, with an error pointing
        at the real mistake in the `fonts:` block, so this stays quiet
        rather than adding one more error per element blaming the element
        for it -- see `NamedRegistry`'s docstring for why the name still
        resolves here.
        """
        if not name.startswith("font."):
            if name in SYSTEM_FONTS:
                return name, False
            self.bag.error(
                "font", f"unknown font {name!r}", span,
                notes=["use 'font.<name>' for a custom font, or a system font: "
                       + ", ".join(SYSTEM_FONTS)],
            )
            return None
        key = name[len("font."):]
        spec = self.fonts.resolve(
            self.bag, key, span, code="font",
            message=f"unknown font {name!r}",
            note="declared fonts", prefix="font.",
        )
        return (key, True) if spec is not None else None

    def resolve_font(self, node: dict[str, Any], element: Text | DataElement) -> bool:
        """Set `.font`/`.font_is_custom` from `node["font"]`.

        Returns whether the reference is trustworthy: `True` when no
        `font:` was written at all (the element keeps its class-default
        system font) or the name resolved; `False` only when an explicit
        `font:` failed to resolve, which already has its own error.  Callers
        use it to skip a further font-kind check that would otherwise blame
        the untouched default for a mistake reported one line up -- the
        "declared and rejected stays quiet" cascade `NamedRegistry` follows.
        """
        raw = node.get("font")
        if raw is None:
            return True
        resolved = self._font_reference(str(raw), self.doc.span(node, "font"))
        if resolved is not None:
            element.font, element.font_is_custom = resolved
            return True
        return False

    def position(self, raw: dict[str, Any] | None, node: dict[str, Any], key: str, *,
                 allow_subscreen: bool = False) -> Position:
        """An `at:`-style position (`anchor`, `dx`/`dy` or polar
        `angle`/`radius`) from `raw`, which is `node[key]`; the default
        centre position when `raw` is `None` or a unit error was reported.
        `anchor: subscreen` is an error unless ``allow_subscreen`` (only a
        top-level element's own `at:` passes it,
        `ElementTree._build_element`): every other position on the element
        is already inside the window's box.
        """
        if raw is None:
            return Position()
        span = self.doc.span(node, key)
        if raw.get("anchor") == "subscreen" and not allow_subscreen:
            self.bag.error(
                "subscreen",
                f"'anchor: subscreen' is not accepted in '{key}:' here",
                self.doc.span(raw, "anchor") or span,
                notes=["it is accepted only on a top-level element's own 'at:'; that "
                       "element's other positions ('to:', 'points:', a group's children) "
                       "are then already laid out inside the subscreen window"],
            )
            return Position()
        try:
            return Position(
                anchor=raw.get("anchor", "center"),
                dx=Length.parse(raw["dx"], what="dx") if "dx" in raw else None,
                dy=Length.parse(raw["dy"], what="dy") if "dy" in raw else None,
                angle=Angle.parse(raw["angle"], what="angle") if "angle" in raw else None,
                radius=Length.parse(raw["radius"], what="radius") if "radius" in raw else None,
            )
        except UnitError as exc:
            self.bag.error("units", str(exc), span)
            return Position()

    def size(self, raw: dict[str, Any] | None) -> Size:
        """A `size: {width, height}` from `raw`; an empty :class:`Size` when
        `raw` is `None` or a unit error was reported.
        """
        if raw is None:
            return Size()
        try:
            return Size(
                width=Length.parse(raw["width"], what="width") if "width" in raw else None,
                height=Length.parse(raw["height"], what="height") if "height" in raw else None,
            )
        except UnitError as exc:
            self.bag.error("units", str(exc), self.doc.span(raw))
            return Size()

    def length(self, node: dict[str, Any], key: str) -> Length | None:
        """`node[key]` as a :class:`Length`, or `None` when absent or a unit
        error was reported.
        """
        if key not in node:
            return None
        try:
            return Length.parse(node[key], what=key)
        except UnitError as exc:
            self.bag.error("units", str(exc), self.doc.span(node, key))
            return None

    def baked_size_length(
        self, node: dict[str, Any], key: str, *, code: str, label: str, note: str,
    ) -> Length | None:
        """`key`'s length, rejected unless it is `px`/`%r` -- shared by every
        size baked before layout runs: an icon's own `size:`
        (`wfb.kinds.icon.IconKind.build`), and a data element's
        `icon_size:`/`icon_gap:`
        (`wfb.kinds.data.DataKind.build`).  `label`
        is the quantity name the message leads with (``'icon size'``/
        ``'icon_size'``/``'icon_gap'``); `note` is the one explanatory note, worded enough
        differently between the three ("its size" vs. "the gap that sits
        against it") that this takes it as a parameter rather than deriving
        one.
        """
        length = self.length(node, key)
        if length is not None and length.unit not in units.SIZE_UNITS:
            self.bag.error(code, f"{label} must be px or %r, not {length.unit}",
                           self.doc.span(node, key), notes=[note])
            return None
        return length

    def angle(self, node: dict[str, Any], key: str) -> Angle | None:
        """`node[key]` as an :class:`Angle`, or `None` when absent or a unit
        error was reported.
        """
        if key not in node:
            return None
        try:
            return Angle.parse(node[key], what=key)
        except UnitError as exc:
            self.bag.error("units", str(exc), self.doc.span(node, key))
            return None
