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

from ..model import ComplicationSlot, Expression, Position, SYSTEM_FONTS, Size, Text
from .state import BuilderState

#: Matches `expr.check`'s "unknown data source" message for exactly
#: `config.colors` or `config.colors.<role>`.  Group 1 is `""` for the bare
#: axis, or `.<role>` for a bad role -- `Builder.expression` turns either
#: into a domain-specific error.
_CONFIG_COLORS_RE = re.compile(
    r"^unknown data source 'config\.colors((?:\.[A-Za-z_][A-Za-z0-9_]*)?)'$"
)


def _offset_span(span: Span | None, text: str, offset: int) -> Span | None:
    """Shift a span to point inside the expression string, not just at its key."""
    if span is None:
        return None
    return Span(span.path, span.line, span.col + offset)


class Readers(BuilderState):
    """Coercion helpers: a key of a node in, a typed value (or `None`, after
reporting why) out."""

    def alignment(self, node: dict[str, Any]) -> tuple[str, str]:
        """`(align, vertical_align)`, defaulting to `"center"`/`"center"` --
        the one place every kind with a placement box reads the two keys.
        The schema is normative on which values reach here, so this is a
        plain lookup.
        """
        return node.get("align", "center"), node.get("vertical_align", "center")

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
        return self.compile_expression(str(raw), self.doc.span(node, key), key)

    def compile_expression(self, text: str, span: Span | None, key: str) -> Expression | None:
        """`text` parsed, type-checked and compiled as :meth:`expression`
        does for an authored key -- for an expression the builder writes
        itself (a `units:` conversion, `wfb.conversion`), reported against
        ``span`` under ``key``."""
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
            # `config.colors` (a scheme, used bare) and `config.colors.<bad
            # role>` both reach here as an ordinary "unknown data source" --
            # nothing under `config.colors.*` is bound in scope except the
            # roles a real axis actually has (`_build_scope`).  Overridden
            # with a domain-specific message rather than left as a generic
            # typo report: a bare `color: config.colors` (missing its role)
            # or a misspelled role deserves better than a "did you mean"
            # guess against an unrelated name.
            if self._config_colors_roles is not None:
                match = _CONFIG_COLORS_RE.match(message)
                if match is not None:
                    roles = ", ".join(f"config.colors.{r}" for r in self._config_colors_roles)
                    code_ = "config"
                    if match.group(1) == "":
                        message = "config.colors is a colour scheme, not a colour"
                        notes = [f"reference a role instead: {roles}"]
                    else:
                        message = f"config.colors has no role {match.group(1)[1:]!r}"
                        notes = [f"declared roles: {roles}"]
            if syntax_error and key == "value":
                notes = list(notes) + [
                    "'value:' is an expression over data sources, not literal text -- "
                    "for a fixed string use 'text:' instead:\n"
                    '    text: "XX%"',
                    "note that YAML strips the quotes, so `value: 'XX%'` reaches the "
                    "expression parser as a bare XX%",
                ]
            self.bag.error(
                code_,
                f"{key}: {message}",
                _offset_span(span, text, exc.offset),
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
        return Expression(
            text=text, code=code, value=value, sources=tuple(sorted(used)),
            barrel=frozenset(barrel), modules=frozenset(modules), span=span, constant=constant,
            ast=folded,
        )

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
                f"{key}: {text} is a literal colour -- prefer a named palette entry",
                span,
                notes=["palette entries keep a design's colours consistent and lintable"],
            )
            return Expression(text, color.as_monkeyc(), expr.Value(Type.COLOR), (),
                              frozenset(), frozenset(), span, constant=color.value,
                              ast=expr.Literal(color.value, Type.COLOR))
        bound = self.expression(node, key)
        if bound is not None and bound.value.type is not Type.COLOR:
            self.bag.error(
                "type", f"{key} must be a colour, got {bound.value}", span,
                notes=["known palette entries: " + (", ".join(f"palette.{n}" for n in sorted(self.palette)) or "(none)")],
            )
            return None
        return bound

    def _font_reference(self, name: str, span: Span | None) -> tuple[str, bool] | None:
        """Resolve a `font:`/`value_font:` name to ``(reference, is_custom)``.

        Shared by every element's `font:` (`text`, `complication_slot`), so
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

    def resolve_font(self, node: dict[str, Any], element: Text | ComplicationSlot) -> bool:
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

    def position(self, raw: dict[str, Any] | None, node: dict[str, Any], key: str) -> Position:
        """An `at:`-style position (`anchor`, `dx`/`dy` or polar
        `angle`/`radius`) from `raw`, which is `node[key]`; the default
        centre position when `raw` is `None` or a unit error was reported.
        """
        if raw is None:
            return Position()
        span = self.doc.span(node, key)
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
        (`wfb.kinds.icon.IconKind.build`), and a complication_slot's
        `icon_size:`/`icon_gap:`
        (`wfb.kinds.complication_slot.ComplicationSlotKind.build`).  `label`
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
