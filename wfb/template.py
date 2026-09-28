"""Format 2's ``text:`` template: ``"{expr:spec}"`` with literal text around it.

* ``{{`` and ``}}`` are a literal ``{`` and ``}``.
* ``{expr}`` and ``{expr:spec}`` are a placeholder.  The expression ends at
  the first ``:`` outside parentheses, brackets and quotes, so a ternary is
  parenthesised: ``"{(x > 0 ? x : 0):d}"``.  ``spec`` runs to the closing
  ``}`` and is exactly a format spec (``wfb.formatting``): ``d``, ``.1f``,
  ``%H:%M``, a duration.
* ``{unit}`` is the label of the unit a ``units:`` conversion displays in
  (``km``/``mi``), not an expression.

This module only parses.  Lowering a template into the compiler's internal
``value:`` + ``format:`` pair is :func:`to_value_format`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_V1_FIELD_RE = re.compile(r"\{(?:(?P<unit>unit)|:(?P<spec>[^}]*))?\}")

_OPEN = {"(": ")", "[": "]"}


class TemplateError(ValueError):
    """A malformed template, with an offset into its text."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.message = message
        self.offset = offset


@dataclass(frozen=True)
class Literal:
    text: str


@dataclass(frozen=True)
class Placeholder:
    expr: str
    spec: str | None
    #: Offset of the expression's first character in the template.
    offset: int


@dataclass(frozen=True)
class Unit:
    pass


@dataclass(frozen=True)
class Template:
    pieces: tuple[Literal | Placeholder | Unit, ...]

    @property
    def placeholders(self) -> list[Placeholder]:
        return [p for p in self.pieces if isinstance(p, Placeholder)]

    @property
    def placeholder(self) -> Placeholder | None:
        found = self.placeholders
        return found[0] if found else None

    @property
    def literal(self) -> str:
        """The text of a template with no placeholder."""
        return "".join(p.text if isinstance(p, Literal) else "" for p in self.pieces)


def parse_template(text: str) -> Template:
    pieces: list[Literal | Placeholder | Unit] = []
    buf: list[str] = []
    i, n = 0, len(text)

    def flush() -> None:
        if buf:
            pieces.append(Literal("".join(buf)))
            buf.clear()

    while i < n:
        ch = text[i]
        if ch == "{":
            if text.startswith("{{", i):
                buf.append("{")
                i += 2
                continue
            flush()
            placeholder, i = _placeholder(text, i)
            pieces.append(placeholder)
            continue
        if ch == "}":
            if text.startswith("}}", i):
                buf.append("}")
                i += 2
                continue
            raise TemplateError("a single '}' outside a placeholder; write '}}' for "
                                "a literal brace", i)
        buf.append(ch)
        i += 1
    flush()
    return Template(tuple(pieces))


def _placeholder(text: str, start: int) -> tuple[Placeholder | Unit, int]:
    """Parse the placeholder opening at ``text[start]`` (a ``{``)."""
    i = start + 1
    depth: list[str] = []
    quote: str | None = None
    n = len(text)
    while i < n:
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch in _OPEN:
            depth.append(_OPEN[ch])
        elif depth and ch == depth[-1]:
            depth.pop()
        elif not depth and ch in ":}":
            break
        elif ch == "{":
            raise TemplateError("'{' inside a placeholder", i)
        i += 1
    if i >= n:
        raise TemplateError("a '{' with no closing '}'; write '{{' for a literal brace",
                            start)
    expr = text[start + 1:i]
    if text[i] == "}":
        if expr.strip() == "unit":
            return Unit(), i + 1
        return Placeholder(expr.strip(), None, start + 1), i + 1
    close = text.find("}", i + 1)
    if close < 0:
        raise TemplateError("a '{' with no closing '}'", start)
    spec = text[i + 1:close]
    if "{" in spec:
        raise TemplateError("'{' inside a placeholder's format spec", i + 1)
    return Placeholder(expr.strip(), spec or None, start + 1), close + 1


def to_value_format(template: Template) -> tuple[str | None, str | None]:
    """``(expression, format)``: the compiler's internal ``value:`` and
    ``format:`` for a one-placeholder template; ``format`` is ``None`` when the
    template is its placeholder alone with no spec.  A template with no
    placeholder is ``(None, None)`` -- use :attr:`Template.literal`.  Raises
    :class:`TemplateError` when literal text around the placeholder would
    read as a field once lowered."""
    placeholder = template.placeholder
    if placeholder is None:
        return None, None
    if len(template.pieces) == 1 and placeholder.spec is None:
        return placeholder.expr, None
    out: list[str] = []
    for piece in template.pieces:
        if isinstance(piece, Literal):
            out.append(piece.text)
        elif isinstance(piece, Unit):
            out.append("{unit}")
        else:
            out.append("{:" + piece.spec + "}" if piece.spec else "{}")
    fmt = "".join(out)
    fields = [m for m in _V1_FIELD_RE.finditer(fmt)]
    expected = sum(1 for p in template.pieces if not isinstance(p, Literal))
    if len(fields) != expected:
        raise TemplateError("literal braces next to the placeholder that the "
                            "compiler would read as a second field", 0)
    return placeholder.expr, fmt
