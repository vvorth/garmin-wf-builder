"""Format 2's ``text:`` template: ``"{expr:spec}"`` with literal text around it.

* ``{{`` and ``}}`` are a literal ``{`` and ``}``.
* ``{expr}`` and ``{expr:spec}`` are a placeholder.  The expression ends at
  the first ``:`` outside parentheses, brackets and quotes, so a ternary is
  parenthesised: ``"{(x > 0 ? x : 0):d}"``.  ``spec`` runs to the closing
  ``}`` and is exactly a format spec (``wfb.formatting``): ``d``, ``.1f``,
  ``%H:%M``, a duration.
* ``{unit}`` is the label of the unit a ``units:`` conversion displays in
  (``km``/``mi``), not an expression.

This module only parses.  :func:`readings` turns a template into what the
builder compiles: each placeholder's expression with its format string
(:func:`to_value_format`, after :func:`segments` cuts a template with several
placeholders into one per reading), and :func:`aod_format` an
``aod: {text:}`` restyle into its format string alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .expr import ExprError, tokenize

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


def segments(template: Template) -> list[Template]:
    """``template`` cut into one template per placeholder, in order, whose
    concatenation is the whole: the first keeps the literal text before
    it, and each keeps the literal text (and ``{unit}``) after it, up to
    the next placeholder."""
    out: list[list[Literal | Placeholder | Unit]] = []
    lead: list[Literal | Placeholder | Unit] = []
    for piece in template.pieces:
        if isinstance(piece, Placeholder):
            out.append(lead + [piece] if not out else [piece])
            lead = []
        elif out:
            out[-1].append(piece)
        else:
            lead.append(piece)
    if not out:
        return [template]
    return [Template(tuple(pieces)) for pieces in out]


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


@dataclass(frozen=True)
class Reading:
    """One placeholder of a ``text:`` template, as the builder compiles it."""

    #: The expression, with a ternary's template parentheses dropped.
    expr: str
    #: Its format string (``"{:02d}"``, ``"Steps {}"``), or ``None`` for the
    #: first reading when that is its placeholder alone with no spec.
    format: str | None
    #: Where ``expr`` starts in the template, for a caret inside it.
    offset: int
    #: The placeholder's expression as written, which a diagnostic quotes.
    quote: str


def readings(raw: str) -> tuple[str | None, tuple[Reading, ...]]:
    """``(literal, readings)``: a template with no placeholder is its literal
    text and no readings; otherwise ``literal`` is ``None`` and each
    placeholder is one :class:`Reading`, the literal text around it in its
    format.  A reading after the first always has a format (``"{}"`` at
    least).  Raises :class:`TemplateError`."""
    template = parse_template(raw)
    if template.placeholder is None:
        return template.literal, ()
    out: list[Reading] = []
    for segment in segments(template):
        placeholder = segment.placeholder
        assert placeholder is not None
        expr, fmt = to_value_format(segment)
        assert expr is not None
        expr, strip = strip_template_parens(expr)
        offset = placeholder.offset + leading_space(raw, placeholder.offset) + strip
        if out and fmt is None:
            fmt = "{}"
        out.append(Reading(expr, fmt, offset, placeholder.expr))
    return None, tuple(out)


def aod_format(raw: str) -> str:
    """An ``aod: {text:}`` restyle's format string: the template with its
    placeholder's expression set aside (it must read the element's own).
    Raises :class:`TemplateError`."""
    template = parse_template(raw)
    stripped = Template(tuple(Placeholder("x", p.spec, p.offset)
                              if isinstance(p, Placeholder) else p
                              for p in template.pieces))
    _, fmt = to_value_format(stripped)
    return fmt if fmt is not None else "{}"


def strip_template_parens(expr: str) -> tuple[str, int]:
    """A ternary needs parentheses inside a placeholder; they are template
    syntax, not part of the expression.  Returns the expression and how many
    characters were dropped from its front."""
    text = expr.strip()
    if not (text.startswith("(") and text.endswith(")")):
        return expr, 0
    depth = 0
    for index, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and index != len(text) - 1:
                return expr, 0  # "(a) + (b)": the outer pair is not one group
    inner = text[1:-1]
    if not _top_level_colon(inner):
        return expr, 0
    return inner, 1


def _top_level_colon(expr: str) -> bool:
    try:
        tokens = tokenize(expr)
    except ExprError:
        return False
    depth = 0
    for token in tokens:
        if token.text == "(":
            depth += 1
        elif token.text == ")":
            depth -= 1
        elif token.kind == "op" and token.text == ":" and depth == 0:
            return True
    return False


def leading_space(raw: str, offset: int) -> int:
    """How many spaces open the placeholder expression at ``offset``."""
    return len(raw[offset:]) - len(raw[offset:].lstrip())
