"""YAML loading that keeps source spans attached to the parsed document.

ruamel's round-trip loader annotates every mapping and sequence with an ``lc``
object holding the 0-based line/column of each key, value and item.  We keep the
``CommentedMap``/``CommentedSeq`` objects themselves as the document -- they are
``dict``/``list`` subclasses, so ``jsonschema`` and ordinary attribute access work
unchanged -- and use :func:`span` to recover a location whenever we need to
report against one.

Round-tripping (ADR 0002's lossless-GUI requirement) is a property of the same
loader, so the compiler and the future editor cannot disagree about the file.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import MarkedYAMLError

from .diagnostics import Bag, Span


@dataclass(frozen=True)
class Origin:
    """What the author wrote where the compiler now reads one key of a
    lowered format 2 document (`wfb.lower`): the author's own name for the
    key, and, when lowering rewrote the value's text, the author's text and
    where the rewritten text's offsets land in it -- so a diagnostic names
    and quotes what is in the file."""

    key: str
    text: str | None = None
    #: ``(rewritten offset, author offset)`` pairs, ascending: an offset into
    #: the rewritten text maps to the author offset of the last pair at or
    #: before it, plus the distance past that pair.
    offsets: tuple[tuple[int, int], ...] = ()
    #: What a diagnostic quotes for this value, when not ``text`` itself (a
    #: template's placeholder expression, not the whole template).
    quote: str | None = None

    def author_offset(self, offset: int) -> int:
        base_rewritten, base_author = 0, 0
        for rewritten, author in self.offsets:
            if rewritten > offset:
                break
            base_rewritten, base_author = rewritten, author
        return base_author + (offset - base_rewritten)


class YamlDocument:
    """A parsed YAML file plus the machinery to locate any node inside it."""

    def __init__(self, path: Path, text: str, data: Any) -> None:
        self.path = path
        self.text = text
        self.data = data
        #: The ``format:`` the author wrote: 2 for a document `wfb.lower`
        #: rewrote into the compiler's internal shape, 1 otherwise.
        self.format = 1
        self._origins: dict[tuple[int, str], Origin] = {}

    # -- format 2 origins ---------------------------------------------------

    def set_origin(self, node: Any, key: str, origin: Origin) -> None:
        self._origins[(id(node), key)] = origin

    def origin(self, node: Any, key: str) -> Origin | None:
        return self._origins.get((id(node), key))

    def author_key(self, node: Any, key: str) -> str:
        """The name the author wrote for ``node[key]``."""
        origin = self._origins.get((id(node), key))
        return origin.key if origin is not None else key

    # -- span lookup ------------------------------------------------------

    def span(self, node: Any, key: Any = None, *, of: str = "value") -> Span | None:
        """Locate ``node``, or ``node[key]`` when a key or index is given.

        ``of="key"`` locates the mapping key rather than its value, which is the
        right anchor for "unknown key" style diagnostics.
        """
        lc = getattr(node, "lc", None)
        if lc is None:
            return None
        if key is None:
            return Span(self.path, lc.line + 1, lc.col + 1)
        try:
            if isinstance(key, int) and not isinstance(node, dict):
                pos = lc.item(key)
            elif of == "key":
                pos = lc.key(key)
            else:
                pos = lc.value(key)
        except (KeyError, IndexError, AttributeError, TypeError):
            return Span(self.path, lc.line + 1, lc.col + 1)
        return Span.from_ruamel(self.path, pos)

    def span_for_path(self, parts: list[Any]) -> Span | None:
        """Locate a node addressed by a jsonschema-style path of keys/indices."""
        node = self.data
        span = self.span(node)
        for part in parts:
            try:
                # A node this compiler minted (`wfb.desugar`) can carry an
                # `lc` with no line at all, which `span` does not survive.
                span = self.span(node, part) or span
            except Exception:
                pass
            try:
                node = node[part]
            except (KeyError, IndexError, TypeError):
                break
        return span


def load(path: Path, bag: Bag, text: str | None = None) -> YamlDocument | None:
    """Parse ``path``, or ``text`` in its place when given -- an editor's
    unsaved text, reported and resolved (relative font paths) as if it were
    the file.  Reports a diagnostic and returns ``None`` on failure."""
    if text is None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            bag.error("io", f"cannot read {path}: {exc.strerror}")
            return None
    bag.register_source(path, text)

    yaml = YAML()  # round-trip mode: preserves order, comments and anchors
    try:
        data = yaml.load(io.StringIO(text))
    except MarkedYAMLError as exc:
        mark = exc.problem_mark
        span = Span(path, mark.line + 1, mark.column + 1) if mark else None
        bag.error("yaml", (exc.problem or "invalid YAML").strip(), span)
        return None

    if data is None:
        bag.error("yaml", "the document is empty", Span(path, 1, 1))
        return None
    return YamlDocument(path, text, data)

